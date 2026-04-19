"""将 AnyLabeling 单类框+属性标注同步为检测标签和三套属性分类原始数据。"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from PIL import Image


AI_ROOT = Path(__file__).resolve().parents[1]
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
DEFAULT_LABEL_NAME = "plot_node"

TASK_CLASS_NAMES = {
    "level": ["lv04", "lv05", "lv06", "lv07", "lv08", "lv09", "lv10"],
    "resource_type": ["wood", "stone", "iron", "copper", "food"],
    "relation": ["ally", "friendly", "neutral", "enemy", "self"],
}

ATTRIBUTE_KEY_ALIASES = {
    "level": ["等级", "level", "级别"],
    "resource_type": ["类型", "resource_type", "资源类型"],
    "relation": ["关系", "relation", "阵营", "外交关系"],
}

ATTRIBUTE_VALUE_MAPS = {
    "level": {
        "4": "lv04",
        "04": "lv04",
        "4级": "lv04",
        "lv4": "lv04",
        "lv04": "lv04",
        "5": "lv05",
        "05": "lv05",
        "5级": "lv05",
        "lv5": "lv05",
        "lv05": "lv05",
        "6": "lv06",
        "06": "lv06",
        "6级": "lv06",
        "lv6": "lv06",
        "lv06": "lv06",
        "7": "lv07",
        "07": "lv07",
        "7级": "lv07",
        "lv7": "lv07",
        "lv07": "lv07",
        "8": "lv08",
        "08": "lv08",
        "8级": "lv08",
        "lv8": "lv08",
        "lv08": "lv08",
        "9": "lv09",
        "09": "lv09",
        "9级": "lv09",
        "lv9": "lv09",
        "lv09": "lv09",
        "10": "lv10",
        "10级": "lv10",
        "lv10": "lv10",
    },
    "resource_type": {
        "wood": "wood",
        "木材": "wood",
        "stone": "stone",
        "石头": "stone",
        "石料": "stone",
        "iron": "iron",
        "铁矿": "iron",
        "copper": "copper",
        "铜矿": "copper",
        "铜": "copper",
        "food": "food",
        "粮食": "food",
    },
    "relation": {
        "ally": "ally",
        "同盟": "ally",
        "friendly": "friendly",
        "友盟": "friendly",
        "neutral": "neutral",
        "中立": "neutral",
        "enemy": "enemy",
        "敌对": "enemy",
        "self": "self",
        "我方": "self",
    },
}

DESCRIPTION_SPLIT_PATTERN = re.compile(r"[\s,，;；|/、]+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从 AnyLabeling JSON 生成检测标签和属性分类原始数据")
    parser.add_argument("--image-dir", required=True, help="原图目录")
    parser.add_argument("--json-dir", required=True, help="AnyLabeling JSON 标签目录")
    parser.add_argument("--detection-label-dir", required=True, help="YOLO 检测 txt 输出目录")
    parser.add_argument(
        "--attr-root",
        default=str(AI_ROOT / "datasets" / "plot_attr_cls"),
        help="属性分类数据集根目录",
    )
    parser.add_argument("--label-name", default=DEFAULT_LABEL_NAME, help="检测标签名称")
    parser.add_argument("--crop-padding-ratio", type=float, default=0.06, help="裁剪框外扩比例")
    parser.add_argument("--clear-attr-raw", action="store_true", help="生成前清空属性 raw 目录")
    parser.add_argument("--summary-output", default="", help="汇总 JSON 输出路径")
    return parser.parse_args()


def collect_json_files(directory: Path) -> List[Path]:
    return sorted(path for path in directory.glob("*.json") if path.is_file())


def prepare_attr_dirs(attr_root: Path, clear_attr_raw: bool) -> None:
    for task_name, class_names in TASK_CLASS_NAMES.items():
        task_root = attr_root / task_name
        raw_root = task_root / "raw"
        if clear_attr_raw and raw_root.exists():
            shutil.rmtree(raw_root)
        raw_root.mkdir(parents=True, exist_ok=True)
        for class_name in class_names:
            (raw_root / class_name).mkdir(parents=True, exist_ok=True)
        with open(task_root / "classes.txt", "w", encoding="utf-8") as file_obj:
            file_obj.write("\n".join(class_names) + "\n")


def resolve_image_path(image_dir: Path, json_path: Path, label_data: dict) -> Path:
    image_name = Path(str(label_data.get("imagePath", "")).strip()).name
    if image_name:
        candidate = image_dir / image_name
        if candidate.exists():
            return candidate

    for extension in IMAGE_EXTENSIONS:
        candidate = image_dir / f"{json_path.stem}{extension}"
        if candidate.exists():
            return candidate

    raise FileNotFoundError(f"无法为标签文件找到对应原图: {json_path.name}")


def extract_bbox(shape: dict) -> Optional[Tuple[float, float, float, float]]:
    points = shape.get("points") or []
    if len(points) < 2:
        return None
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    x1, x2 = min(xs), max(xs)
    y1, y2 = min(ys), max(ys)
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def to_yolo_line(bbox: Tuple[float, float, float, float], image_width: int, image_height: int) -> str:
    x1, y1, x2, y2 = bbox
    cx = ((x1 + x2) * 0.5) / image_width
    cy = ((y1 + y2) * 0.5) / image_height
    width = (x2 - x1) / image_width
    height = (y2 - y1) / image_height
    return f"0 {cx:.6f} {cy:.6f} {width:.6f} {height:.6f}"


def normalize_attr_value(task_name: str, raw_value: object) -> Optional[str]:
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    if not value:
        return None
    return ATTRIBUTE_VALUE_MAPS[task_name].get(value.lower(), ATTRIBUTE_VALUE_MAPS[task_name].get(value))


def get_attr_value_from_description(task_name: str, description: object) -> Optional[str]:
    text = str(description or "").strip()
    if not text:
        return None

    tokens = [token.strip() for token in DESCRIPTION_SPLIT_PATTERN.split(text) if token.strip()]
    for token in tokens:
        normalized = normalize_attr_value(task_name, token)
        if normalized:
            return normalized

        for separator in (":", "：", "="):
            if separator in token:
                _, value = token.split(separator, 1)
                normalized = normalize_attr_value(task_name, value)
                if normalized:
                    return normalized

    compact_text = "".join(tokens).lower()
    for raw_value, canonical_value in ATTRIBUTE_VALUE_MAPS[task_name].items():
        raw_text = str(raw_value).strip().lower()
        if raw_text and raw_text in compact_text:
            return canonical_value
    return None


def get_attr_value(attributes: dict, task_name: str, description: object = "") -> Optional[str]:
    normalized_keys = {str(key).strip().lower(): value for key, value in attributes.items()}
    for alias in ATTRIBUTE_KEY_ALIASES[task_name]:
        if alias in attributes:
            normalized = normalize_attr_value(task_name, attributes[alias])
            if normalized:
                return normalized
        alias_lower = alias.lower()
        if alias_lower in normalized_keys:
            normalized = normalize_attr_value(task_name, normalized_keys[alias_lower])
            if normalized:
                return normalized
    return get_attr_value_from_description(task_name, description)


def padded_crop_box(
    bbox: Tuple[float, float, float, float],
    image_width: int,
    image_height: int,
    padding_ratio: float,
) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    width = x2 - x1
    height = y2 - y1
    pad_x = width * padding_ratio
    pad_y = height * padding_ratio
    left = max(0, int(round(x1 - pad_x)))
    top = max(0, int(round(y1 - pad_y)))
    right = min(image_width, int(round(x2 + pad_x)))
    bottom = min(image_height, int(round(y2 + pad_y)))
    return left, top, right, bottom


def save_task_crop(
    image: Image.Image,
    crop_box: Tuple[int, int, int, int],
    attr_root: Path,
    task_name: str,
    class_name: str,
    file_name: str,
) -> Path:
    crop = image.crop(crop_box)
    output_path = attr_root / task_name / "raw" / class_name / file_name
    crop.save(output_path)
    return output_path


def iter_task_names() -> Iterable[str]:
    return TASK_CLASS_NAMES.keys()


def main() -> int:
    args = parse_args()

    image_dir = Path(args.image_dir)
    json_dir = Path(args.json_dir)
    detection_label_dir = Path(args.detection_label_dir)
    attr_root = Path(args.attr_root)

    if not image_dir.exists():
        raise FileNotFoundError(f"原图目录不存在: {image_dir}")
    if not json_dir.exists():
        raise FileNotFoundError(f"JSON 目录不存在: {json_dir}")

    detection_label_dir.mkdir(parents=True, exist_ok=True)
    prepare_attr_dirs(attr_root, clear_attr_raw=args.clear_attr_raw)

    manifest_rows: List[Dict[str, object]] = []
    warnings: List[str] = []
    detection_counter = Counter()
    attribute_counter = {task_name: Counter() for task_name in iter_task_names()}

    json_files = collect_json_files(json_dir)
    if not json_files:
        raise ValueError("没有找到 AnyLabeling JSON 标注文件")

    for json_path in json_files:
        with open(json_path, "r", encoding="utf-8") as file_obj:
            label_data = json.load(file_obj)

        image_path = resolve_image_path(image_dir, json_path, label_data)
        with Image.open(image_path) as image_obj:
            image = image_obj.convert("RGB")
            image_width, image_height = image.size

            detection_lines: List[str] = []
            for shape_index, shape in enumerate(label_data.get("shapes") or []):
                if str(shape.get("label", "")).strip() != args.label_name:
                    continue

                bbox = extract_bbox(shape)
                if bbox is None:
                    warnings.append(f"{json_path.name} 第 {shape_index} 个 shape 的框无效，已跳过")
                    continue

                detection_lines.append(to_yolo_line(bbox, image_width, image_height))
                detection_counter[args.label_name] += 1

                attributes = shape.get("attributes") or {}
                description = shape.get("description") or ""
                normalized_attrs = {
                    task_name: get_attr_value(attributes, task_name, description)
                    for task_name in iter_task_names()
                }
                if any(value is None for value in normalized_attrs.values()):
                    warnings.append(
                        f"{json_path.name} 第 {shape_index} 个 shape 缺少完整属性/描述，已只生成检测标签"
                    )
                    continue

                crop_box = padded_crop_box(bbox, image_width, image_height, args.crop_padding_ratio)
                base_name = f"{image_path.stem}__s{shape_index:03d}.png"
                record: Dict[str, object] = {
                    "image_name": image_path.name,
                    "json_name": json_path.name,
                    "shape_index": shape_index,
                    "bbox_left": crop_box[0],
                    "bbox_top": crop_box[1],
                    "bbox_right": crop_box[2],
                    "bbox_bottom": crop_box[3],
                }

                for task_name, class_name in normalized_attrs.items():
                    output_path = save_task_crop(image, crop_box, attr_root, task_name, class_name, base_name)
                    attribute_counter[task_name][class_name] += 1
                    record[task_name] = class_name
                    record[f"{task_name}_file"] = str(output_path.relative_to(attr_root))

                manifest_rows.append(record)

        with open(detection_label_dir / f"{json_path.stem}.txt", "w", encoding="utf-8") as file_obj:
            file_obj.write("\n".join(detection_lines))
            if detection_lines:
                file_obj.write("\n")

    manifest_path = attr_root / "manifest.csv"
    with open(manifest_path, "w", encoding="utf-8-sig", newline="") as file_obj:
        fieldnames = [
            "image_name",
            "json_name",
            "shape_index",
            "bbox_left",
            "bbox_top",
            "bbox_right",
            "bbox_bottom",
            "level",
            "level_file",
            "resource_type",
            "resource_type_file",
            "relation",
            "relation_file",
        ]
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(manifest_rows)

    summary = {
        "json_files": len(json_files),
        "detection_boxes": sum(detection_counter.values()),
        "attribute_samples": {
            task_name: dict(counter) for task_name, counter in attribute_counter.items()
        },
        "manifest": str(manifest_path),
        "warnings": warnings[:50],
        "warning_count": len(warnings),
    }

    summary_path = Path(args.summary_output) if args.summary_output else attr_root / "sync_summary.json"
    with open(summary_path, "w", encoding="utf-8") as file_obj:
        json.dump(summary, file_obj, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"同步汇总已写入: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())