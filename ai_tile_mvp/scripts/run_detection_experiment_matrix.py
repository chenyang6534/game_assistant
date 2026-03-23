"""运行检测模型对照实验并汇总结果。"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
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
from ai_tile_mvp.runtime.onnx_tile_detector import OnnxTileDetector, load_image
from ai_tile_mvp.scripts.benchmark_onnx_tile import build_metrics, collect_images, evaluate_image, load_yolo_boxes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行检测模型对照实验矩阵")
    parser.add_argument("--project-config", required=True, help="项目 project_meta.json 路径")
    parser.add_argument("--models", default="yolov8n.pt,yolov8s.pt", help="待比较模型列表，逗号分隔")
    parser.add_argument("--imgsz-values", default="640,768", help="待比较输入尺寸列表，逗号分隔")
    parser.add_argument("--epochs", type=int, default=120, help="训练轮数")
    parser.add_argument("--batch", type=int, default=16, help="batch size")
    parser.add_argument("--workers", type=int, default=4, help="数据加载 worker 数")
    parser.add_argument("--patience", type=int, default=20, help="early stopping patience")
    parser.add_argument("--close-mosaic", type=int, default=10, help="最后多少轮关闭 mosaic")
    parser.add_argument("--device", default="", help="训练设备，例如 cpu、0、0,1")
    parser.add_argument("--cache", action="store_true", help="训练时缓存数据集")
    parser.add_argument("--exist-ok", action="store_true", help="允许 Ultralytics 复用同名输出目录")
    parser.add_argument("--reuse-existing", action="store_true", help="若已存在权重或 onnx，则跳过训练或导出")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不执行训练与导出")
    parser.add_argument("--conf-values", default="0.05,0.10,0.15,0.20,0.25,0.35", help="评估时扫描的检测阈值列表")
    parser.add_argument("--eval-iou", type=float, default=0.50, help="评估 TP/FP/FN 使用的 IoU 阈值")
    parser.add_argument("--max-detections", type=int, default=300, help="最大检测数")
    parser.add_argument("--warmup", type=int, default=3, help="每个模型预热次数")
    parser.add_argument("--repeat", type=int, default=10, help="每张图重复推理次数")
    parser.add_argument("--output-dir", default="", help="实验汇总输出目录，默认项目 outputs/detection_experiments")
    parser.add_argument("--export-conf-threshold", type=float, default=0.10, help="导出 onnx 元数据默认检测阈值")
    parser.add_argument("--export-iou-threshold", type=float, default=0.50, help="导出 onnx 元数据默认 NMS 阈值")
    return parser.parse_args()


def parse_csv_items(raw_text: str) -> list[str]:
    items = [item.strip() for item in str(raw_text or "").split(",") if item.strip()]
    if not items:
        raise ValueError("至少需要一个实验项")
    return items


def parse_float_values(raw_text: str) -> list[float]:
    values: list[float] = []
    seen: set[float] = set()
    for token in parse_csv_items(raw_text):
        value = float(token)
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"阈值超出 0-1 范围: {token}")
        rounded = round(value, 6)
        if rounded in seen:
            continue
        seen.add(rounded)
        values.append(rounded)
    return values


def parse_int_values(raw_text: str) -> list[int]:
    values: list[int] = []
    seen: set[int] = set()
    for token in parse_csv_items(raw_text):
        value = int(token)
        if value <= 0:
            raise ValueError(f"输入尺寸必须大于 0: {token}")
        if value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def model_stem(model_arg: str) -> str:
    return Path(str(model_arg)).stem.lower()


def resolve_output_root(output_dir_text: str, project_root: Path) -> Path:
    if str(output_dir_text or "").strip():
        target = Path(output_dir_text)
        if not target.is_absolute():
            target = project_root / target
        return target.resolve()
    return (project_root / "outputs" / "detection_experiments").resolve()


def build_experiment_names(project_meta: dict[str, Any], model_arg: str, imgsz: int) -> tuple[str, str]:
    project_slug = str(project_meta.get("project_slug") or project_meta.get("project_name") or "project").strip()
    default_run_name = str(project_meta.get("detection_run_name") or f"{project_slug}_det_yolov8n").strip()
    stem = model_stem(model_arg)
    if imgsz == 640 and stem in default_run_name.lower():
        return default_run_name, f"{default_run_name}_640"
    run_name = f"{project_slug}_det_{stem}_{imgsz}"
    return run_name, run_name


def run_command(command: list[str], dry_run: bool) -> None:
    print("执行命令:")
    print(" ".join(command))
    if dry_run:
        return
    subprocess.run(command, check=True)


def load_dataset(image_dir: Path, label_dir: Path) -> list[dict[str, Any]]:
    dataset: list[dict[str, Any]] = []
    for image_path in collect_images("", str(image_dir)):
        image = load_image(image_path)
        gt_boxes = load_yolo_boxes(label_dir / f"{image_path.stem}.txt", image.shape[1], image.shape[0])
        dataset.append({
            "image_path": image_path,
            "image": image,
            "gt_boxes": gt_boxes,
        })
    if not dataset:
        raise ValueError(f"测试集为空: {image_dir}")
    return dataset


def benchmark_thresholds(
    model_path: Path,
    meta_path: Path | None,
    dataset: list[dict[str, Any]],
    conf_values: list[float],
    *,
    eval_iou: float,
    max_detections: int,
    warmup: int,
    repeat: int,
) -> list[dict[str, Any]]:
    detector = OnnxTileDetector(model_path, meta_path=meta_path if meta_path and meta_path.exists() else None)
    first_image = dataset[0]["image"]
    for _ in range(max(0, warmup)):
        detector.predict(first_image, conf_threshold=conf_values[0], max_detections=max_detections)

    rows: list[dict[str, Any]] = []
    for conf_value in conf_values:
        total_tp = 0
        total_fp = 0
        total_fn = 0
        total_detections = 0
        all_times: list[float] = []

        for sample in dataset:
            detections = []
            for _ in range(max(1, repeat)):
                started_at = time.perf_counter()
                detections = detector.predict(
                    sample["image"],
                    conf_threshold=conf_value,
                    max_detections=max_detections,
                )
                all_times.append((time.perf_counter() - started_at) * 1000.0)

            total_detections += len(detections)
            metrics = evaluate_image(detections, sample["gt_boxes"], eval_iou)
            total_tp += metrics["tp"]
            total_fp += metrics["fp"]
            total_fn += metrics["fn"]

        row = {
            "conf": round(conf_value, 4),
            "detections": total_detections,
            "tp": total_tp,
            "fp": total_fp,
            "fn": total_fn,
            "avg_ms": round(sum(all_times) / len(all_times), 3) if all_times else 0.0,
        }
        row.update(build_metrics(total_tp, total_fp, total_fn))
        rows.append(row)

    return sorted(
        rows,
        key=lambda item: (
            -float(item["f1"]),
            -float(item["recall"]),
            -float(item["precision"]),
            float(item["avg_ms"]),
            float(item["conf"]),
        ),
    )


def write_csv(output_path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with open(output_path, "w", encoding="utf-8-sig", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    args = parse_args()
    project_config = Path(args.project_config).resolve()
    if not project_config.exists():
        raise FileNotFoundError(f"project_meta.json 不存在: {project_config}")

    project_root = project_config.parent
    project_meta = load_project_meta(project_config)
    data_yaml = (project_root / "datasets" / "detection" / "data.yaml").resolve()
    image_dir = (project_root / "datasets" / "detection" / "images" / "test").resolve()
    label_dir = (project_root / "datasets" / "detection" / "labels" / "test").resolve()
    meta_template = (project_root / "configs" / "model_meta.template.json").resolve()
    train_output_root = (project_root / "outputs" / "train").resolve()
    detector_output_root = (project_root / "models" / "detector").resolve()
    matrix_output_root = resolve_output_root(args.output_dir, project_root)
    benchmark_output_root = matrix_output_root / "benchmark"
    summary_output_root = matrix_output_root / "summary"
    for directory in (train_output_root, detector_output_root, benchmark_output_root, summary_output_root):
        directory.mkdir(parents=True, exist_ok=True)

    dataset = load_dataset(image_dir, label_dir)
    conf_values = parse_float_values(args.conf_values)
    models = parse_csv_items(args.models)
    imgsz_values = parse_int_values(args.imgsz_values)

    experiment_rows: list[dict[str, Any]] = []
    for model_arg in models:
        for imgsz in imgsz_values:
            run_name, onnx_stem = build_experiment_names(project_meta, model_arg, imgsz)
            weights_path = train_output_root / run_name / "weights" / "best.pt"
            onnx_path = detector_output_root / f"{onnx_stem}.onnx"
            meta_path = onnx_path.with_suffix(".json")
            per_model_output_dir = benchmark_output_root / onnx_stem
            per_model_output_dir.mkdir(parents=True, exist_ok=True)

            row: dict[str, Any] = {
                "model": model_arg,
                "model_stem": model_stem(model_arg),
                "imgsz": imgsz,
                "run_name": run_name,
                "onnx_name": onnx_stem,
                "weights_path": str(weights_path),
                "onnx_path": str(onnx_path),
                "status": "pending",
            }

            try:
                train_command = [
                    sys.executable,
                    str(AI_ROOT / "scripts" / "train_yolo_tile.py"),
                    "--data",
                    str(data_yaml),
                    "--model",
                    model_arg,
                    "--imgsz",
                    str(imgsz),
                    "--epochs",
                    str(args.epochs),
                    "--batch",
                    str(args.batch),
                    "--workers",
                    str(args.workers),
                    "--patience",
                    str(args.patience),
                    "--close-mosaic",
                    str(args.close_mosaic),
                    "--project",
                    str(train_output_root),
                    "--name",
                    run_name,
                ]
                if args.device:
                    train_command.extend(["--device", args.device])
                if args.cache:
                    train_command.append("--cache")
                if args.exist_ok:
                    train_command.append("--exist-ok")

                should_train = not (args.reuse_existing and weights_path.exists())
                if should_train:
                    run_command(train_command, args.dry_run)
                else:
                    print(f"跳过训练，复用现有权重: {weights_path}")

                if not args.dry_run and not weights_path.exists():
                    raise FileNotFoundError(f"训练完成后未找到权重: {weights_path}")

                export_command = [
                    sys.executable,
                    str(AI_ROOT / "scripts" / "export_yolo_onnx.py"),
                    "--weights",
                    str(weights_path),
                    "--output",
                    str(onnx_path),
                    "--meta-template",
                    str(meta_template),
                    "--imgsz",
                    str(imgsz),
                    "--conf-threshold",
                    str(args.export_conf_threshold),
                    "--iou-threshold",
                    str(args.export_iou_threshold),
                ]
                should_export = not (args.reuse_existing and onnx_path.exists() and meta_path.exists())
                if should_export:
                    run_command(export_command, args.dry_run)
                else:
                    print(f"跳过导出，复用现有 onnx: {onnx_path}")

                if args.dry_run:
                    row["status"] = "dry_run"
                    experiment_rows.append(row)
                    continue

                if not onnx_path.exists():
                    raise FileNotFoundError(f"导出完成后未找到 onnx: {onnx_path}")

                ranked_rows = benchmark_thresholds(
                    onnx_path,
                    meta_path,
                    dataset,
                    conf_values,
                    eval_iou=args.eval_iou,
                    max_detections=args.max_detections,
                    warmup=args.warmup,
                    repeat=args.repeat,
                )
                best_row = ranked_rows[0]

                per_model_json = per_model_output_dir / "summary.json"
                per_model_csv = per_model_output_dir / "summary.csv"
                with open(per_model_json, "w", encoding="utf-8") as file_obj:
                    json.dump(
                        {
                            "model": model_arg,
                            "imgsz": imgsz,
                            "run_name": run_name,
                            "onnx_path": str(onnx_path),
                            "conf_values": conf_values,
                            "best": best_row,
                            "rows": ranked_rows,
                        },
                        file_obj,
                        ensure_ascii=False,
                        indent=2,
                    )
                write_csv(
                    per_model_csv,
                    ranked_rows,
                    ["conf", "detections", "tp", "fp", "fn", "precision", "recall", "f1", "avg_ms"],
                )

                row.update(
                    {
                        "status": "ok",
                        "best_conf": best_row["conf"],
                        "precision": best_row["precision"],
                        "recall": best_row["recall"],
                        "f1": best_row["f1"],
                        "avg_ms": best_row["avg_ms"],
                        "summary_json": str(per_model_json),
                        "summary_csv": str(per_model_csv),
                    }
                )
            except Exception as exc:
                row["status"] = "failed"
                row["error"] = str(exc)

            experiment_rows.append(row)

    ranking_rows = sorted(
        experiment_rows,
        key=lambda item: (
            item.get("status") != "ok",
            -float(item.get("f1", 0.0) or 0.0),
            -float(item.get("recall", 0.0) or 0.0),
            -float(item.get("precision", 0.0) or 0.0),
            float(item.get("avg_ms", 0.0) or 0.0),
        ),
    )

    summary_json = summary_output_root / "experiment_matrix_summary.json"
    summary_csv = summary_output_root / "experiment_matrix_summary.csv"
    with open(summary_json, "w", encoding="utf-8") as file_obj:
        json.dump(
            {
                "project_root": str(project_root),
                "models": models,
                "imgsz_values": imgsz_values,
                "rows": ranking_rows,
            },
            file_obj,
            ensure_ascii=False,
            indent=2,
        )
    write_csv(
        summary_csv,
        ranking_rows,
        [
            "status",
            "model",
            "model_stem",
            "imgsz",
            "run_name",
            "onnx_name",
            "best_conf",
            "precision",
            "recall",
            "f1",
            "avg_ms",
            "weights_path",
            "onnx_path",
            "summary_json",
            "summary_csv",
            "error",
        ],
    )

    print(f"实验汇总已写入: {summary_json}")
    print(f"实验汇总已写入: {summary_csv}")
    print("实验结果:")
    for index, row in enumerate(ranking_rows, start=1):
        if row.get("status") != "ok":
            print(f"{index:02d}. {row['model']} @ {row['imgsz']} -> {row['status']}: {row.get('error', '')}")
            continue
        print(
            f"{index:02d}. {row['model']} @ {row['imgsz']} -> conf={row['best_conf']}, "
            f"P={row['precision']:.4f}, R={row['recall']:.4f}, F1={row['f1']:.4f}, avg={row['avg_ms']:.3f} ms"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())