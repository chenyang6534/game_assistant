"""从 AnyLabeling JSON 生成单目标检测快测数据集。"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple


AI_ROOT = Path(__file__).resolve().parents[1]
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
DEFAULT_LABEL_NAME = "plot_node"

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
    parser = argparse.ArgumentParser(description="生成单目标检测快测数据集")
    parser.add_argument("--image-dir", required=True, help="原图目录")
    parser.add_argument("--json-dir", required=True, help="AnyLabeling JSON 标签目录")
    parser.add_argument("--output-root", default="", help="快测数据集根目录")
    parser.add_argument("--label-name", default=DEFAULT_LABEL_NAME, help="AnyLabeling 中的检测标签名")
    parser.add_argument("--level", default="lv05", help="目标等级，例如 lv05 或 5级")
    parser.add_argument("--resource-type", default="wood", help="目标类型，例如 wood 或 木材")
    parser.add_argument("--relation", default="neutral", help="目标关系，例如 neutral 或 中立")
    parser.add_argument("--target-label", default="", help="写入 data.yaml 的类别名，默认自动生成")
    parser.add_argument("--ignore-attrs", action="store_true", help="忽略 shape 属性，直接将所有已框 plot_node 视为当前单目标")
    parser.add_argument("--clear-output", action="store_true", help="生成前清空输出目录")
    return parser.parse_args()


def normalize_attr_value(task_name: str, raw_value: object) -> Optional[str]:
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    if not value:
        return None
    value_map = ATTRIBUTE_VALUE_MAPS[task_name]
    return value_map.get(value.lower(), value_map.get(value))


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


def normalize_target(args: argparse.Namespace) -> Dict[str, str]:
    target = {
        "level": normalize_attr_value("level", args.level),
        "resource_type": normalize_attr_value("resource_type", args.resource_type),
        "relation": normalize_attr_value("relation", args.relation),
    }
    missing = [task_name for task_name, value in target.items() if value is None]
    if missing:
        raise ValueError(f"目标属性不合法: {', '.join(missing)}")
    return target  # type: ignore[return-value]


def collect_json_files(directory: Path) -> List[Path]:
    return sorted(path for path in directory.glob("*.json") if path.is_file())


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


def build_target_slug(target: Dict[str, str]) -> str:
    return f"{target['level']}_{target['resource_type']}_{target['relation']}"


def write_data_yaml(output_root: Path, target_label: str) -> None:
    content = "\n".join([
        "path: .",
        "train: images/train",
        "val: images/val",
        "test: images/test",
        "names:",
        f"  0: {target_label}",
        "",
    ])
    (output_root / "data.yaml").write_text(content, encoding="utf-8")


def write_summary(output_root: Path, summary: dict) -> None:
    summary_path = output_root / "smoke_test_summary.json"
    with open(summary_path, "w", encoding="utf-8") as file_obj:
        json.dump(summary, file_obj, ensure_ascii=False, indent=2)


def main() -> int:
    args = parse_args()

    image_dir = Path(args.image_dir).resolve()
    json_dir = Path(args.json_dir).resolve()
    if not image_dir.exists():
        raise FileNotFoundError(f"原图目录不存在: {image_dir}")
    if not json_dir.exists():
        raise FileNotFoundError(f"JSON 标签目录不存在: {json_dir}")

    target = normalize_target(args)
    target_slug = build_target_slug(target)
    target_label = args.target_label.strip() or target_slug
    output_root = Path(args.output_root).resolve() if args.output_root else (AI_ROOT / "datasets" / "smoke_tests" / target_slug).resolve()

    if args.clear_output and output_root.exists():
        shutil.rmtree(output_root)

    raw_image_dir = output_root / "raw" / "images"
    raw_label_dir = output_root / "raw" / "labels"
    raw_image_dir.mkdir(parents=True, exist_ok=True)
    raw_label_dir.mkdir(parents=True, exist_ok=True)

    json_files = collect_json_files(json_dir)
    if not json_files:
        raise ValueError("没有找到 AnyLabeling JSON 标注文件")

    total_boxes = 0
    positive_images = 0
    negative_images = 0
    warnings: List[str] = []
    matched_by_attrs = 0
    matched_by_ignore_attrs = 0

    for json_path in json_files:
        with open(json_path, "r", encoding="utf-8") as file_obj:
            label_data = json.load(file_obj)

        image_path = resolve_image_path(image_dir, json_path, label_data)
        image_width = int(label_data.get("imageWidth") or 0)
        image_height = int(label_data.get("imageHeight") or 0)
        if image_width <= 0 or image_height <= 0:
            raise ValueError(f"标签缺少 imageWidth/imageHeight: {json_path.name}")

        lines: List[str] = []
        for shape_index, shape in enumerate(label_data.get("shapes") or []):
            if str(shape.get("label", "")).strip() != args.label_name:
                continue

            bbox = extract_bbox(shape)
            if bbox is None:
                warnings.append(f"{json_path.name} 第 {shape_index} 个框无效，已跳过")
                continue

            if args.ignore_attrs:
                matched = True
                matched_by_ignore_attrs += 1
            else:
                attributes = shape.get("attributes") or {}
                description = shape.get("description") or ""
                matched = True
                for task_name, expected_value in target.items():
                    current_value = get_attr_value(attributes, task_name, description)
                    if current_value != expected_value:
                        matched = False
                        break
            if not matched:
                continue

            if not args.ignore_attrs:
                matched_by_attrs += 1

            lines.append(to_yolo_line(bbox, image_width, image_height))

        shutil.copy2(image_path, raw_image_dir / image_path.name)
        label_path = raw_label_dir / f"{image_path.stem}.txt"
        with open(label_path, "w", encoding="utf-8") as file_obj:
            file_obj.write("\n".join(lines))
            if lines:
                file_obj.write("\n")

        total_boxes += len(lines)
        if lines:
            positive_images += 1
        else:
            negative_images += 1

    write_data_yaml(output_root, target_label)
    (output_root / "classes.txt").write_text(f"{target_label}\n", encoding="utf-8")

    summary = {
        "target": target,
        "target_label": target_label,
        "output_root": str(output_root),
        "json_file_count": len(json_files),
        "image_count": len(json_files),
        "positive_images": positive_images,
        "negative_images": negative_images,
        "target_boxes": total_boxes,
        "ignore_attrs": bool(args.ignore_attrs),
        "matched_by_attrs": matched_by_attrs,
        "matched_by_ignore_attrs": matched_by_ignore_attrs,
        "warning_count": len(warnings),
        "warnings": warnings[:50],
    }
    write_summary(output_root, summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"单目标快测数据集已生成: {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())