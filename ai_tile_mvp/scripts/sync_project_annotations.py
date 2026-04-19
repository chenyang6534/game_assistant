"""按项目配置将 AnyLabeling 标注同步为检测标签和属性分类数据。"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from PIL import Image


AI_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = AI_ROOT.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ai_tile_mvp.project_scaffold import load_project_meta


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
DESCRIPTION_SPLIT_PATTERN = re.compile(r"[\s,，;；|/、]+")
LEGACY_DETECTION_LABEL_NAME = "plot_node"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按项目配置同步 AnyLabeling 标注")
    parser.add_argument("--project-config", required=True, help="项目配置文件 project_meta.json")
    parser.add_argument("--image-dir", default="", help="原图目录，可覆盖项目默认值")
    parser.add_argument("--json-dir", default="", help="JSON 标签目录，可覆盖项目默认值")
    parser.add_argument("--detection-label-dir", default="", help="检测 txt 输出目录，可覆盖项目默认值")
    parser.add_argument("--attr-root", default="", help="属性分类数据集根目录，可覆盖项目默认值")
    parser.add_argument("--label-name", default="", help="检测标签名，可覆盖项目默认值")
    parser.add_argument("--crop-padding-ratio", type=float, default=0.06, help="裁剪框外扩比例")
    parser.add_argument("--clear-attr-raw", action="store_true", help="生成前清空属性 raw 目录")
    parser.add_argument("--summary-output", default="", help="汇总 JSON 输出路径")
    return parser.parse_args()


def collect_json_files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.glob("*.json") if path.is_file())


def build_detection_label_aliases(label_name: str) -> set[str]:
    aliases = {str(label_name).strip(), LEGACY_DETECTION_LABEL_NAME}
    return {alias for alias in aliases if alias}


def resolve_project_paths(project_root: Path, project_meta: dict[str, Any], args: argparse.Namespace) -> dict[str, Path]:
    paths = project_meta.get("paths") or {}
    image_dir = Path(args.image_dir).resolve() if args.image_dir else (project_root / paths["detection_raw_images"]).resolve()
    json_dir = Path(args.json_dir).resolve() if args.json_dir else (project_root / paths["detection_raw_labels"]).resolve()
    detection_label_dir = (
        Path(args.detection_label_dir).resolve()
        if args.detection_label_dir
        else (project_root / paths["detection_raw_labels"]).resolve()
    )
    attr_root = Path(args.attr_root).resolve() if args.attr_root else (project_root / paths["attribute_root"]).resolve()
    return {
        "image_dir": image_dir,
        "json_dir": json_dir,
        "detection_label_dir": detection_label_dir,
        "attr_root": attr_root,
    }


def prepare_attr_dirs(attr_root: Path, tasks: list[dict[str, Any]], clear_attr_raw: bool) -> None:
    for task in tasks:
        task_root = attr_root / task["slug"]
        raw_root = task_root / "raw"
        if clear_attr_raw and raw_root.exists():
            shutil.rmtree(raw_root)
        raw_root.mkdir(parents=True, exist_ok=True)
        class_names = [class_info["slug"] for class_info in task["classes"]]
        for class_name in class_names:
            (raw_root / class_name).mkdir(parents=True, exist_ok=True)
        with open(task_root / "classes.txt", "w", encoding="utf-8") as file_obj:
            file_obj.write("\n".join(class_names) + "\n")


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
    for class_info in task["classes"]:
        aliases = {_normalize_text(alias) for alias in class_info.get("aliases") or []}
        if normalized in aliases:
            return str(class_info["slug"])
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
    for class_info in task["classes"]:
        for alias in class_info.get("aliases") or []:
            alias_text = _normalize_text(alias)
            if alias_text and alias_text in compact_text:
                return str(class_info["slug"])
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


def padded_crop_box(
    bbox: tuple[float, float, float, float],
    image_width: int,
    image_height: int,
    padding_ratio: float,
) -> tuple[int, int, int, int]:
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
    crop_box: tuple[int, int, int, int],
    attr_root: Path,
    task_slug: str,
    class_slug: str,
    file_name: str,
) -> Path:
    crop = image.crop(crop_box)
    output_path = attr_root / task_slug / "raw" / class_slug / file_name
    crop.save(output_path)
    return output_path


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

    resolved_paths = resolve_project_paths(project_root, project_meta, args)
    image_dir = resolved_paths["image_dir"]
    json_dir = resolved_paths["json_dir"]
    detection_label_dir = resolved_paths["detection_label_dir"]
    attr_root = resolved_paths["attr_root"]
    label_name = args.label_name.strip() or str(project_meta.get("detection_label") or "plot_node")
    detection_label_aliases = build_detection_label_aliases(label_name)

    if not image_dir.exists():
        raise FileNotFoundError(f"原图目录不存在: {image_dir}")
    if not json_dir.exists():
        raise FileNotFoundError(f"JSON 目录不存在: {json_dir}")

    detection_label_dir.mkdir(parents=True, exist_ok=True)
    prepare_attr_dirs(attr_root, tasks, clear_attr_raw=args.clear_attr_raw)

    manifest_rows: list[dict[str, object]] = []
    warnings: list[str] = []
    detection_counter = Counter()
    attribute_counter = {task["slug"]: Counter() for task in tasks}

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

            detection_lines: list[str] = []
            for shape_index, shape in enumerate(label_data.get("shapes") or []):
                if str(shape.get("label", "")).strip() not in detection_label_aliases:
                    continue

                bbox = extract_bbox(shape)
                if bbox is None:
                    warnings.append(f"{json_path.name} 第 {shape_index} 个 shape 的框无效，已跳过")
                    continue

                detection_lines.append(to_yolo_line(bbox, image_width, image_height))
                detection_counter[label_name] += 1

                attributes = shape.get("attributes") or {}
                description = shape.get("description") or ""
                normalized_attrs: dict[str, str] = {}
                missing_tasks: list[str] = []
                for task in tasks:
                    class_slug = get_attr_value(task, attributes, description)
                    if class_slug is None:
                        missing_tasks.append(str(task["display_name"]))
                    else:
                        normalized_attrs[str(task["slug"])] = class_slug

                if missing_tasks:
                    warnings.append(
                        f"{json_path.name} 第 {shape_index} 个 shape 缺少属性: {', '.join(missing_tasks)}，已只生成检测标签"
                    )
                    continue

                crop_box = padded_crop_box(bbox, image_width, image_height, args.crop_padding_ratio)
                base_name = f"{image_path.stem}__s{shape_index:03d}.png"
                record: dict[str, object] = {
                    "image_name": image_path.name,
                    "json_name": json_path.name,
                    "shape_index": shape_index,
                    "bbox_left": crop_box[0],
                    "bbox_top": crop_box[1],
                    "bbox_right": crop_box[2],
                    "bbox_bottom": crop_box[3],
                }

                for task in tasks:
                    task_slug = str(task["slug"])
                    class_slug = normalized_attrs[task_slug]
                    output_path = save_task_crop(image, crop_box, attr_root, task_slug, class_slug, base_name)
                    attribute_counter[task_slug][class_slug] += 1
                    record[task_slug] = class_slug
                    record[f"{task_slug}_file"] = str(output_path.relative_to(attr_root))

                manifest_rows.append(record)

        with open(detection_label_dir / f"{json_path.stem}.txt", "w", encoding="utf-8") as file_obj:
            file_obj.write("\n".join(detection_lines))
            if detection_lines:
                file_obj.write("\n")

    manifest_path = attr_root / "manifest.csv"
    fieldnames = [
        "image_name",
        "json_name",
        "shape_index",
        "bbox_left",
        "bbox_top",
        "bbox_right",
        "bbox_bottom",
    ]
    for task in tasks:
        task_slug = str(task["slug"])
        fieldnames.extend([task_slug, f"{task_slug}_file"])

    with open(manifest_path, "w", encoding="utf-8-sig", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(manifest_rows)

    summary = {
        "project_name": project_meta.get("project_name"),
        "json_files": len(json_files),
        "detection_boxes": sum(detection_counter.values()),
        "attribute_samples": {
            task_slug: dict(counter) for task_slug, counter in attribute_counter.items()
        },
        "manifest": str(manifest_path),
        "warnings": warnings[:50],
        "warning_count": len(warnings),
    }

    summary_path = Path(args.summary_output).resolve() if args.summary_output else attr_root / "sync_summary.json"
    with open(summary_path, "w", encoding="utf-8") as file_obj:
        json.dump(summary, file_obj, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"同步汇总已写入: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())