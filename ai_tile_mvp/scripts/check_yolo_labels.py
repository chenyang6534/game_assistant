"""检查 YOLO 标签格式并导出抽检预览。"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np

AI_ROOT = Path(__file__).resolve().parents[1]
if str(AI_ROOT) not in sys.path:
    sys.path.insert(0, str(AI_ROOT))

from runtime.onnx_tile_detector import save_image


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp"}


def parse_args() -> argparse.Namespace:
    default_root = AI_ROOT / "datasets" / "plot_det"
    parser = argparse.ArgumentParser(description="检查 YOLO 标签并生成抽检预览")
    parser.add_argument("--image-dir", required=True, help="图片目录")
    parser.add_argument("--label-dir", required=True, help="标签目录")
    parser.add_argument("--output-dir", default=str(AI_ROOT / "outputs" / "label_check"), help="预览输出目录")
    parser.add_argument("--sample-count", type=int, default=40, help="随机抽检图片数量")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--strict", action="store_true", help="遇到格式错误时返回非 0")
    return parser.parse_args()


def collect_images(image_dir: Path) -> List[Path]:
    return sorted(path for path in image_dir.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)


def load_image(path: Path) -> np.ndarray:
    data = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法读取图片: {path}")
    return image


def parse_label_file(label_path: Path) -> List[Tuple[int, float, float, float, float]]:
    rows = []
    with open(label_path, "r", encoding="utf-8") as file_obj:
        for line_no, raw_line in enumerate(file_obj, start=1):
            text = raw_line.strip()
            if not text:
                continue
            parts = text.split()
            if len(parts) != 5:
                raise ValueError(f"{label_path.name}:{line_no} 列数不是 5")
            class_id = int(parts[0])
            cx, cy, width, height = [float(item) for item in parts[1:]]
            for value_name, value in (("cx", cx), ("cy", cy), ("width", width), ("height", height)):
                if value < 0 or value > 1:
                    raise ValueError(f"{label_path.name}:{line_no} {value_name} 超出 0 到 1")
            if width <= 0 or height <= 0:
                raise ValueError(f"{label_path.name}:{line_no} 框宽高必须大于 0")
            rows.append((class_id, cx, cy, width, height))
    return rows


def draw_labels(image: np.ndarray, labels: List[Tuple[int, float, float, float, float]]) -> np.ndarray:
    canvas = image.copy()
    height, width = canvas.shape[:2]
    for class_id, cx, cy, box_w, box_h in labels:
        left = int(round((cx - box_w / 2.0) * width))
        top = int(round((cy - box_h / 2.0) * height))
        right = int(round((cx + box_w / 2.0) * width))
        bottom = int(round((cy + box_h / 2.0) * height))
        center = (int(round(cx * width)), int(round(cy * height)))
        cv2.rectangle(canvas, (left, top), (right, bottom), (0, 200, 255), 2)
        cv2.circle(canvas, center, 3, (0, 0, 255), -1)
        cv2.putText(canvas, f"tile:{class_id}", (left, max(14, top - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1, cv2.LINE_AA)
    return canvas


def main() -> int:
    args = parse_args()
    image_dir = Path(args.image_dir).resolve()
    label_dir = Path(args.label_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    errors: List[str] = []
    images = collect_images(image_dir)
    if not images:
        raise ValueError("没有找到可检查的图片")

    valid_items = []
    for image_path in images:
        label_path = label_dir / f"{image_path.stem}.txt"
        if not label_path.exists():
            errors.append(f"缺少标签: {image_path.name}")
            continue
        try:
            labels = parse_label_file(label_path)
        except Exception as exc:
            errors.append(str(exc))
            continue
        valid_items.append((image_path, labels))

    randomizer = random.Random(args.seed)
    randomizer.shuffle(valid_items)
    sampled = valid_items[:max(0, min(args.sample_count, len(valid_items)))]

    for image_path, labels in sampled:
        image = load_image(image_path)
        preview = draw_labels(image, labels)
        save_image(output_dir / image_path.name, preview)

    print(f"总图片数: {len(images)}")
    print(f"有效标签数: {len(valid_items)}")
    print(f"抽检预览数: {len(sampled)}")
    print(f"预览输出目录: {output_dir}")
    if errors:
        print("发现的问题：")
        for item in errors[:50]:
            print(f"- {item}")
    return 1 if args.strict and errors else 0


if __name__ == "__main__":
    raise SystemExit(main())