"""按项目配置生成单目标快测检测数据集。"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Optional


AI_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = AI_ROOT.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ai_tile_mvp.project_scaffold import load_project_meta


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
DESCRIPTION_SPLIT_PATTERN = re.compile(r"[\s,，;；|/、]+")
LEGACY_DETECTION_LABEL_NAME = "plot_node"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按项目配置生成单目标快测检测数据集")
    parser.add_argument("--project-config", required=True, help="项目配置文件 project_meta.json")
    parser.add_argument("--image-dir", default="", help="原图目录，可覆盖项目默认值")
    parser.add_argument("--json-dir", default="", help="AnyLabeling JSON 标签目录，可覆盖项目默认值")
    parser.add_argument("--output-root", default="", help="快测数据集根目录，可覆盖项目默认值")
    parser.add_argument("--label-name", default="", help="AnyLabeling 中的检测标签名，可覆盖项目默认值")
    parser.add_argument("--target", action="append", default=[], help="目标属性，格式 task_slug=class_slug，可重复传入")
    parser.add_argument("--target-label", default="", help="写入 data.yaml 的类别名，默认自动生成")
    parser.add_argument("--ignore-attrs", action="store_true", help="忽略 shape 属性，直接将所有已框检测类视为当前单目标")
    parser.add_argument("--clear-output", action="store_true", help="生成前清空输出目录")
    return parser.parse_args()


def collect_json_files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.glob("*.json") if path.is_file())


def build_detection_label_aliases(label_name: str) -> set[str]:
    aliases = {str(label_name).strip(), LEGACY_DETECTION_LABEL_NAME}
    return {alias for alias in aliases if alias}


def resolve_project_path(project_root: Path, project_meta: dict[str, Any], key: str, fallback: str) -> Path:
    relative_path = str((project_meta.get("paths") or {}).get(key, fallback)).strip()
    return (project_root / relative_path).resolve()


def resolve_image_path(image_dir: Path, json_path: Path, label_data: dict[str, Any]) -> Path:
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


def extract_bbox(shape: dict[str, Any]) -> Optional[tuple[float, float, float, float]]:
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


def to_yolo_line(bbox: tuple[float, float, float, float], image_width: int, image_height: int) -> str:
    x1, y1, x2, y2 = bbox
    cx = ((x1 + x2) * 0.5) / image_width
    cy = ((y1 + y2) * 0.5) / image_height
    width = (x2 - x1) / image_width
    height = (y2 - y1) / image_height
    return f"0 {cx:.6f} {cy:.6f} {width:.6f} {height:.6f}"


def _normalize_text(value: object) -> str:
    return str(value).strip().lower()


def _match_class_slug(task: dict[str, Any], raw_value: object) -> Optional[str]:
    normalized = _normalize_text(raw_value)
    if not normalized:
        return None
    for class_info in task.get("classes") or []:
        aliases = {_normalize_text(alias) for alias in class_info.get("aliases") or []}
        if normalized in aliases:
            return str(class_info.get("slug") or "")
    return None


def get_attr_value_from_description(task: dict[str, Any], description: object) -> Optional[str]:
    text = str(description or "").strip()
    if not text:
        return None

    tokens = [token.strip() for token in DESCRIPTION_SPLIT_PATTERN.split(text) if token.strip()]
    for token in tokens:
        normalized = _match_class_slug(task, token)
        if normalized:
            return normalized

        for separator in (":", "：", "="):
            if separator in token:
                _, value = token.split(separator, 1)
                normalized = _match_class_slug(task, value)
                if normalized:
                    return normalized

    compact_text = "".join(tokens).lower()
    for class_info in task.get("classes") or []:
        for alias in class_info.get("aliases") or []:
            alias_text = _normalize_text(alias)
            if alias_text and alias_text in compact_text:
                return str(class_info.get("slug") or "")
    return None


def get_attr_value(task: dict[str, Any], attributes: dict[str, Any], description: object = "") -> Optional[str]:
    normalized_keys = {_normalize_text(key): value for key, value in attributes.items()}
    for alias in task.get("aliases") or []:
        alias_text = _normalize_text(alias)
        if alias in attributes:
            normalized = _match_class_slug(task, attributes[alias])
            if normalized:
                return normalized
        if alias_text in normalized_keys:
            normalized = _match_class_slug(task, normalized_keys[alias_text])
            if normalized:
                return normalized
    return get_attr_value_from_description(task, description)


def parse_target_args(tasks: list[dict[str, Any]], raw_targets: list[str], ignore_attrs: bool) -> dict[str, str]:
    target_map: dict[str, str] = {}
    valid_tasks = {str(task.get("slug") or ""): task for task in tasks}
    for raw_target in raw_targets:
        if "=" not in raw_target:
            raise ValueError(f"目标参数格式无效: {raw_target}")
        task_slug, class_slug = [part.strip() for part in raw_target.split("=", 1)]
        if task_slug not in valid_tasks:
            raise ValueError(f"未知属性任务: {task_slug}")
        task = valid_tasks[task_slug]
        valid_class_slugs = {str(class_info.get("slug") or "") for class_info in task.get("classes") or []}
        if class_slug not in valid_class_slugs:
            raise ValueError(f"属性 {task_slug} 不存在值: {class_slug}")
        target_map[task_slug] = class_slug

    if ignore_attrs:
        return target_map

    missing = [str(task.get("slug") or "") for task in tasks if str(task.get("slug") or "") not in target_map]
    if missing:
        raise ValueError(f"缺少目标属性: {', '.join(missing)}")
    return target_map


def build_target_slug(tasks: list[dict[str, Any]], target_map: dict[str, str]) -> str:
    values = [target_map[str(task.get("slug") or "")] for task in tasks if str(task.get("slug") or "") in target_map]
    if not values:
        return "all_boxes"
    return "_".join(values)


def write_data_yaml(output_root: Path, target_label: str) -> None:
    content = "\n".join(
        [
            "path: .",
            "train: images/train",
            "val: images/val",
            "test: images/test",
            "names:",
            f"  0: {target_label}",
            "",
        ]
    )
    (output_root / "data.yaml").write_text(content, encoding="utf-8")


def write_summary(output_root: Path, summary: dict[str, Any]) -> None:
    summary_path = output_root / "smoke_test_summary.json"
    with open(summary_path, "w", encoding="utf-8") as file_obj:
        json.dump(summary, file_obj, ensure_ascii=False, indent=2)


def main() -> int:
    args = parse_args()
    project_config_path = Path(args.project_config).resolve()
    if not project_config_path.exists():
        raise FileNotFoundError(f"项目配置不存在: {project_config_path}")

    project_meta = load_project_meta(project_config_path)
    project_root = project_config_path.parent
    tasks = project_meta.get("attribute_tasks") or []
    if not tasks:
        raise ValueError("项目配置里没有定义任何属性任务")

    image_dir = Path(args.image_dir).resolve() if args.image_dir else resolve_project_path(project_root, project_meta, "detection_raw_images", "datasets/detection/raw/images")
    json_dir = Path(args.json_dir).resolve() if args.json_dir else resolve_project_path(project_root, project_meta, "detection_raw_labels", "datasets/detection/raw/labels")
    label_name = args.label_name.strip() or str(project_meta.get("detection_label") or "plot_node")
    detection_label_aliases = build_detection_label_aliases(label_name)
    target_map = parse_target_args(tasks, list(args.target), args.ignore_attrs)
    target_slug = build_target_slug(tasks, target_map)
    target_label = args.target_label.strip() or target_slug
    default_smoke_root = resolve_project_path(project_root, project_meta, "smoke_root", "datasets/smoke_tests")
    output_root = Path(args.output_root).resolve() if args.output_root else (default_smoke_root / target_slug).resolve()

    if not image_dir.exists():
        raise FileNotFoundError(f"原图目录不存在: {image_dir}")
    if not json_dir.exists():
        raise FileNotFoundError(f"JSON 标签目录不存在: {json_dir}")

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
    warnings: list[str] = []
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

        lines: list[str] = []
        for shape_index, shape in enumerate(label_data.get("shapes") or []):
            if str(shape.get("label", "")).strip() not in detection_label_aliases:
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
                for task in tasks:
                    task_slug = str(task.get("slug") or "")
                    expected_value = target_map.get(task_slug)
                    if expected_value is None:
                        matched = False
                        break
                    current_value = get_attr_value(task, attributes, description)
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
        "project_name": project_meta.get("project_name"),
        "target": target_map,
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