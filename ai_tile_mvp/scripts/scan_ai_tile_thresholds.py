"""扫描 AI 地块检测阈值与候选框复检阈值组合。"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any


AI_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = AI_ROOT.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from ai_tile_mvp.project_scaffold import load_project_meta
from ai_tile_mvp.runtime.onnx_tile_detector import load_image
from ai_tile_mvp.scripts.benchmark_onnx_tile import build_metrics, collect_images, evaluate_image, load_yolo_boxes
from core.ai_tile_recognition import AITileRecognition


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="扫描 AI 地块识别的检测阈值与复检阈值组合")
    parser.add_argument("--project-config", default="", help="项目 project_meta.json 路径；提供后可自动补全模型与测试集路径")
    parser.add_argument("--model-target", default="", help="AI 模型目标，可传 onnx、zip、.gaimodel.json、project_meta.json 或模型包目录")
    parser.add_argument("--image", default="", help="单张测试图片路径")
    parser.add_argument("--image-dir", default="", help="测试图片目录")
    parser.add_argument("--label-dir", default="", help="测试标签目录")
    parser.add_argument("--output-dir", default="", help="输出目录，默认写到项目 outputs/threshold_scan")
    parser.add_argument("--conf-values", default="0.05,0.10,0.15,0.20,0.25,0.35", help="检测阈值列表，逗号分隔")
    parser.add_argument(
        "--review-values",
        default="off,default,0.55,0.65,0.75,0.85",
        help="复检阈值列表，逗号分隔；支持 off、default 或 0-1 数字",
    )
    parser.add_argument("--eval-iou", type=float, default=0.50, help="评估 TP/FP/FN 使用的 IoU 阈值")
    parser.add_argument("--max-detections", type=int, default=300, help="最大检测数")
    parser.add_argument("--warmup", type=int, default=1, help="预热次数")
    parser.add_argument("--repeat", type=int, default=1, help="每张图重复推理次数")
    parser.add_argument("--top-k", type=int, default=10, help="终端输出前多少名组合")
    return parser.parse_args()


def parse_float_values(raw_text: str) -> list[float]:
    values: list[float] = []
    seen: set[float] = set()
    for raw_token in str(raw_text or "").split(","):
        token = raw_token.strip()
        if not token:
            continue
        value = float(token)
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"阈值超出 0-1 范围: {token}")
        rounded = round(value, 6)
        if rounded in seen:
            continue
        seen.add(rounded)
        values.append(rounded)
    if not values:
        raise ValueError("至少需要一个检测阈值")
    return values


def parse_review_values(raw_text: str) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    seen: set[tuple[bool, float | None]] = set()
    for raw_token in str(raw_text or "").split(","):
        token = raw_token.strip().lower()
        if not token:
            continue
        if token in {"off", "none", "disable", "disabled", "no_review"}:
            key = (False, None)
            if key not in seen:
                seen.add(key)
                options.append({"label": "off", "apply_review": False, "review_threshold": None})
            continue
        if token in {"default", "project", "auto"}:
            key = (True, None)
            if key not in seen:
                seen.add(key)
                options.append({"label": "default", "apply_review": True, "review_threshold": None})
            continue

        value = float(token)
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"复检阈值超出 0-1 范围: {raw_token.strip()}")
        rounded = round(value, 6)
        key = (True, rounded)
        if key in seen:
            continue
        seen.add(key)
        options.append(
            {
                "label": f"{rounded:.2f}",
                "apply_review": True,
                "review_threshold": rounded,
            }
        )

    if not options:
        options.append({"label": "default", "apply_review": True, "review_threshold": None})
    return options


def resolve_project_context(project_config_text: str) -> tuple[Path | None, dict[str, Any] | None]:
    config_text = str(project_config_text or "").strip()
    if not config_text:
        return None, None
    config_path = Path(config_text).resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"project_meta.json 不存在: {config_path}")
    return config_path.parent, load_project_meta(config_path)


def resolve_relative_path(path_text: str, project_root: Path | None) -> Path:
    candidate = Path(path_text)
    if not candidate.is_absolute() and project_root is not None:
        candidate = project_root / candidate
    return candidate.resolve()


def resolve_model_target(args: argparse.Namespace, project_root: Path | None, project_meta: dict[str, Any] | None) -> Path | str:
    if str(args.model_target or "").strip():
        return resolve_relative_path(args.model_target, project_root)

    if project_root is None or not project_meta:
        raise ValueError("未提供 --model-target，且无法从 --project-config 推断默认模型")

    run_name = str(project_meta.get("detection_run_name") or "").strip()
    detector_root = project_root / "models" / "detector"
    default_path = detector_root / f"{run_name}_640.onnx"
    if default_path.exists():
        return default_path.resolve()

    candidates = sorted(
        (path for path in detector_root.glob("*.onnx") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0].resolve()
    raise FileNotFoundError(f"未找到项目检测模型: {detector_root}")


def resolve_dataset_paths(args: argparse.Namespace, project_root: Path | None) -> tuple[str, str, Path]:
    single_image = str(args.image or "").strip()
    image_dir = str(args.image_dir or "").strip()
    label_dir = str(args.label_dir or "").strip()

    if not single_image and not image_dir:
        if project_root is None:
            raise ValueError("必须提供 --image 或 --image-dir")
        image_dir = str((project_root / "datasets" / "detection" / "images" / "test").resolve())

    if not label_dir:
        if project_root is None:
            raise ValueError("必须提供 --label-dir，或通过 --project-config 自动补全")
        label_dir = str((project_root / "datasets" / "detection" / "labels" / "test").resolve())

    if single_image:
        single_image = str(resolve_relative_path(single_image, project_root))
    if image_dir:
        image_dir = str(resolve_relative_path(image_dir, project_root))
    label_path = resolve_relative_path(label_dir, project_root)
    if not label_path.exists():
        raise FileNotFoundError(f"测试标签目录不存在: {label_path}")
    return single_image, image_dir, label_path


def resolve_output_dir(output_dir_text: str, project_root: Path | None) -> Path:
    if str(output_dir_text or "").strip():
        return resolve_relative_path(output_dir_text, project_root)
    if project_root is not None:
        return (project_root / "outputs" / "threshold_scan").resolve()
    return (AI_ROOT / "outputs" / "threshold_scan").resolve()


def load_dataset(single_image: str, image_dir: str, label_dir: Path) -> list[dict[str, Any]]:
    dataset: list[dict[str, Any]] = []
    for image_path in collect_images(single_image, image_dir):
        image = load_image(image_path)
        gt_boxes = load_yolo_boxes(label_dir / f"{image_path.stem}.txt", image.shape[1], image.shape[0])
        dataset.append({
            "image_path": image_path,
            "image": image,
            "gt_boxes": gt_boxes,
        })
    if not dataset:
        raise ValueError("没有找到可测试的图片")
    return dataset


def rank_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda item: (
            -float(item["f1"]),
            -float(item["recall"]),
            -float(item["precision"]),
            float(item["avg_ms"]),
            float(item["conf"]),
            str(item["review"]),
        ),
    )


def write_csv(output_path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "rank",
        "conf",
        "review",
        "apply_review",
        "review_threshold",
        "detections",
        "tp",
        "fp",
        "fn",
        "precision",
        "recall",
        "f1",
        "avg_ms",
    ]
    with open(output_path, "w", encoding="utf-8-sig", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        for index, row in enumerate(rows, start=1):
            payload = dict(row)
            payload["rank"] = index
            writer.writerow(payload)


def main() -> int:
    args = parse_args()
    project_root, project_meta = resolve_project_context(args.project_config)
    model_target = resolve_model_target(args, project_root, project_meta)
    single_image, image_dir, label_dir = resolve_dataset_paths(args, project_root)
    output_dir = resolve_output_dir(args.output_dir, project_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    conf_values = parse_float_values(args.conf_values)
    review_options = parse_review_values(args.review_values)
    dataset = load_dataset(single_image, image_dir, label_dir)

    recognizer = AITileRecognition()
    warmup_image = dataset[0]["image"]
    for _ in range(max(0, args.warmup)):
        recognizer.find_tiles(
            warmup_image,
            model_path=str(model_target),
            threshold=conf_values[0],
            max_count=args.max_detections,
            apply_review=review_options[0]["apply_review"],
            review_threshold=review_options[0]["review_threshold"],
        )

    rows: list[dict[str, Any]] = []
    for conf_value in conf_values:
        for review_option in review_options:
            total_tp = 0
            total_fp = 0
            total_fn = 0
            total_detections = 0
            all_times: list[float] = []

            for sample in dataset:
                matches = []
                for _ in range(max(1, args.repeat)):
                    started_at = time.perf_counter()
                    matches = recognizer.find_tiles(
                        sample["image"],
                        model_path=str(model_target),
                        threshold=conf_value,
                        max_count=args.max_detections,
                        apply_review=bool(review_option["apply_review"]),
                        review_threshold=review_option["review_threshold"],
                    )
                    elapsed_ms = (time.perf_counter() - started_at) * 1000.0
                    all_times.append(elapsed_ms)

                total_detections += len(matches)
                metrics = evaluate_image(matches, sample["gt_boxes"], args.eval_iou)
                total_tp += metrics["tp"]
                total_fp += metrics["fp"]
                total_fn += metrics["fn"]

            row = {
                "conf": round(conf_value, 4),
                "review": review_option["label"],
                "apply_review": bool(review_option["apply_review"]),
                "review_threshold": None
                if review_option["review_threshold"] is None
                else round(float(review_option["review_threshold"]), 4),
                "detections": total_detections,
                "tp": total_tp,
                "fp": total_fp,
                "fn": total_fn,
                "avg_ms": round(sum(all_times) / len(all_times), 3) if all_times else 0.0,
            }
            row.update(build_metrics(total_tp, total_fp, total_fn))
            rows.append(row)

    ranked_rows = rank_rows(rows)
    summary = {
        "project_root": "" if project_root is None else str(project_root),
        "model_target": str(model_target),
        "image_count": len(dataset),
        "repeat": max(1, args.repeat),
        "eval_iou": float(args.eval_iou),
        "max_detections": int(args.max_detections),
        "conf_values": conf_values,
        "review_values": [item["label"] for item in review_options],
        "best": ranked_rows[0] if ranked_rows else None,
        "rows": ranked_rows,
    }

    json_path = output_dir / "threshold_scan_summary.json"
    csv_path = output_dir / "threshold_scan_summary.csv"
    with open(json_path, "w", encoding="utf-8") as file_obj:
        json.dump(summary, file_obj, ensure_ascii=False, indent=2)
    write_csv(csv_path, ranked_rows)

    print(f"模型目标: {model_target}")
    print(f"测试图片数: {len(dataset)}")
    print(f"结果已写入: {json_path}")
    print(f"结果已写入: {csv_path}")
    print("Top 组合:")
    for index, row in enumerate(ranked_rows[: max(1, args.top_k)], start=1):
        print(
            f"{index:02d}. conf={row['conf']:.2f}, review={row['review']}, "
            f"P={row['precision']:.4f}, R={row['recall']:.4f}, F1={row['f1']:.4f}, avg={row['avg_ms']:.3f} ms"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())