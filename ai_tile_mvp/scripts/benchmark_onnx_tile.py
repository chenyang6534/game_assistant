"""离线评估 ONNX 地块检测模型的速度和可视化结果。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

AI_ROOT = Path(__file__).resolve().parents[1]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from runtime.onnx_tile_detector import OnnxTileDetector, draw_detections, load_image, save_image


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="基准测试 ONNX 地块检测模型")
    parser.add_argument("--model", required=True, help="onnx 模型路径")
    parser.add_argument("--meta", default="", help="模型元数据 json 路径")
    parser.add_argument("--image", default="", help="单张测试图片路径")
    parser.add_argument("--image-dir", default="", help="测试图片目录")
    parser.add_argument("--label-dir", default="", help="可选，测试标签目录，用于计算 precision/recall")
    parser.add_argument("--output-dir", default=str(AI_ROOT / "outputs" / "benchmark_preview"), help="可视化输出目录")
    parser.add_argument("--conf", type=float, default=-1.0, help="覆盖模型默认置信度阈值")
    parser.add_argument("--iou", type=float, default=-1.0, help="覆盖模型默认 NMS 阈值")
    parser.add_argument("--eval-iou", type=float, default=0.50, help="评估 TP/FP/FN 时采用的 IoU 阈值")
    parser.add_argument("--max-detections", type=int, default=300, help="最大检测数")
    parser.add_argument("--warmup", type=int, default=3, help="预热次数")
    parser.add_argument("--repeat", type=int, default=10, help="每张图重复推理次数")
    parser.add_argument("--no-save-preview", action="store_true", help="不保存可视化图片")
    return parser.parse_args()


def collect_images(single_image: str, image_dir: str) -> List[Path]:
    if single_image:
        return [Path(single_image).resolve()]
    if image_dir:
        directory = Path(image_dir).resolve()
        return sorted(path for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)
    raise ValueError("必须提供 --image 或 --image-dir")


def load_yolo_boxes(label_path: Path, image_width: int, image_height: int) -> List[Tuple[float, float, float, float]]:
    if not label_path.exists():
        return []

    boxes: List[Tuple[float, float, float, float]] = []
    for raw_line in label_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            continue
        _, cx, cy, width, height = parts
        cx_f = float(cx) * image_width
        cy_f = float(cy) * image_height
        width_f = float(width) * image_width
        height_f = float(height) * image_height
        x1 = cx_f - width_f / 2.0
        y1 = cy_f - height_f / 2.0
        x2 = cx_f + width_f / 2.0
        y2 = cy_f + height_f / 2.0
        boxes.append((x1, y1, x2, y2))
    return boxes


def detection_to_xyxy(detection) -> Tuple[float, float, float, float]:
    return (
        float(detection.x),
        float(detection.y),
        float(detection.x + detection.width),
        float(detection.y + detection.height),
    )


def compute_iou(box_a: Tuple[float, float, float, float], box_b: Tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    intersection = inter_w * inter_h
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - intersection
    if union <= 0.0:
        return 0.0
    return intersection / union


def evaluate_image(detections, gt_boxes: List[Tuple[float, float, float, float]], eval_iou: float) -> Dict[str, int]:
    matched_gt: set[int] = set()
    true_positive = 0
    false_positive = 0

    for detection in detections:
        pred_box = detection_to_xyxy(detection)
        best_index = -1
        best_iou = 0.0
        for index, gt_box in enumerate(gt_boxes):
            if index in matched_gt:
                continue
            iou = compute_iou(pred_box, gt_box)
            if iou >= eval_iou and iou > best_iou:
                best_iou = iou
                best_index = index
        if best_index >= 0:
            matched_gt.add(best_index)
            true_positive += 1
        else:
            false_positive += 1

    false_negative = max(0, len(gt_boxes) - len(matched_gt))
    return {
        "tp": true_positive,
        "fp": false_positive,
        "fn": false_negative,
    }


def build_metrics(tp: int, fp: int, fn: int) -> Dict[str, float]:
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2.0 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def main() -> int:
    args = parse_args()
    image_paths = collect_images(args.image, args.image_dir)
    if not image_paths:
        raise ValueError("没有找到可测试的图片")

    meta_path = Path(args.meta).resolve() if args.meta else None
    detector = OnnxTileDetector(args.model, meta_path=meta_path)
    label_dir = Path(args.label_dir).resolve() if args.label_dir else None
    if label_dir is not None and not label_dir.exists():
        raise FileNotFoundError(f"测试标签目录不存在: {label_dir}")

    output_dir = Path(args.output_dir).resolve()
    if not args.no_save_preview:
        output_dir.mkdir(parents=True, exist_ok=True)

    first_image = load_image(image_paths[0])
    for _ in range(max(0, args.warmup)):
        detector.predict(
            first_image,
            conf_threshold=None if args.conf < 0 else args.conf,
            iou_threshold=None if args.iou < 0 else args.iou,
            max_detections=args.max_detections,
        )

    all_times: List[float] = []
    summary_rows = []
    total_tp = 0
    total_fp = 0
    total_fn = 0

    for image_path in image_paths:
        image = load_image(image_path)
        detections = []
        timings: List[float] = []
        for _ in range(max(1, args.repeat)):
            start = time.perf_counter()
            detections = detector.predict(
                image,
                conf_threshold=None if args.conf < 0 else args.conf,
                iou_threshold=None if args.iou < 0 else args.iou,
                max_detections=args.max_detections,
            )
            timings.append((time.perf_counter() - start) * 1000.0)

        average_ms = sum(timings) / len(timings)
        all_times.extend(timings)
        row = {
            "image": image_path.name,
            "detections": len(detections),
            "avg_ms": round(average_ms, 3),
        }

        if label_dir is not None:
            gt_boxes = load_yolo_boxes(label_dir / f"{image_path.stem}.txt", image.shape[1], image.shape[0])
            metrics = evaluate_image(detections, gt_boxes, args.eval_iou)
            total_tp += metrics["tp"]
            total_fp += metrics["fp"]
            total_fn += metrics["fn"]
            row.update({
                "gt": len(gt_boxes),
                **metrics,
            })
            print(
                f"{image_path.name}: detections={len(detections)}, gt={len(gt_boxes)}, "
                f"tp={metrics['tp']}, fp={metrics['fp']}, fn={metrics['fn']}, avg={average_ms:.3f} ms"
            )
        else:
            print(f"{image_path.name}: detections={len(detections)}, avg={average_ms:.3f} ms")

        summary_rows.append(row)

        if not args.no_save_preview:
            preview = draw_detections(image, detections)
            save_image(output_dir / image_path.name, preview)

    total_avg = sum(all_times) / len(all_times)
    summary = {
        "image_count": len(image_paths),
        "repeat": max(1, args.repeat),
        "avg_ms": round(total_avg, 3),
        "details": summary_rows,
    }
    if label_dir is not None:
        summary.update({
            "eval_iou": args.eval_iou,
            "tp": total_tp,
            "fp": total_fp,
            "fn": total_fn,
            **build_metrics(total_tp, total_fp, total_fn),
        })
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if not args.no_save_preview:
        summary_path = output_dir / "benchmark_summary.json"
        with open(summary_path, "w", encoding="utf-8") as file_obj:
            json.dump(summary, file_obj, ensure_ascii=False, indent=2)
        print(f"基准结果已写入: {summary_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())