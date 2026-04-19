"""将未确认标注的原图移出训练候选集。"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="移动未确认标注的原图")
    parser.add_argument("--image-dir", required=True, help="原图目录")
    parser.add_argument("--label-dir", required=True, help="标签目录，里面可能同时包含 json 和 txt")
    parser.add_argument("--output-root", required=True, help="移出训练集后的保存目录")
    parser.add_argument("--dry-run", action="store_true", help="仅输出将要移动的文件，不实际移动")
    return parser.parse_args()


def has_nonempty_txt(label_path: Path) -> bool:
    if not label_path.exists() or not label_path.is_file():
        return False
    return bool(label_path.read_text(encoding="utf-8").strip())


def unique_target_path(target_dir: Path, file_name: str) -> Path:
    candidate = target_dir / file_name
    if not candidate.exists():
        return candidate
    stem = Path(file_name).stem
    suffix = Path(file_name).suffix
    index = 1
    while True:
        candidate = target_dir / f"{stem}__dup{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def iter_images(image_dir: Path) -> list[Path]:
    return sorted(path for path in image_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)


def main() -> int:
    args = parse_args()
    image_dir = Path(args.image_dir).resolve()
    label_dir = Path(args.label_dir).resolve()
    output_root = Path(args.output_root).resolve()
    output_image_dir = output_root / "images"
    output_label_dir = output_root / "labels"

    if not image_dir.exists():
        raise FileNotFoundError(f"原图目录不存在: {image_dir}")
    if not label_dir.exists():
        raise FileNotFoundError(f"标签目录不存在: {label_dir}")

    output_image_dir.mkdir(parents=True, exist_ok=True)
    output_label_dir.mkdir(parents=True, exist_ok=True)

    moved_records: list[dict[str, object]] = []
    skipped_with_json = 0
    skipped_with_nonempty_txt = 0

    for image_path in iter_images(image_dir):
        txt_path = label_dir / f"{image_path.stem}.txt"
        json_path = label_dir / f"{image_path.stem}.json"
        has_json = json_path.exists()
        has_txt_content = has_nonempty_txt(txt_path)

        if has_json:
            skipped_with_json += 1
            continue
        if has_txt_content:
            skipped_with_nonempty_txt += 1
            continue

        target_image_path = unique_target_path(output_image_dir, image_path.name)
        moved_record: dict[str, object] = {
            "image": image_path.name,
            "target_image": str(target_image_path),
            "had_txt": txt_path.exists(),
            "had_json": has_json,
        }

        if not args.dry_run:
            shutil.move(str(image_path), str(target_image_path))

        if txt_path.exists():
            target_txt_path = unique_target_path(output_label_dir, txt_path.name)
            moved_record["target_txt"] = str(target_txt_path)
            if not args.dry_run:
                shutil.move(str(txt_path), str(target_txt_path))

        moved_records.append(moved_record)

    summary = {
        "image_dir": str(image_dir),
        "label_dir": str(label_dir),
        "output_root": str(output_root),
        "dry_run": args.dry_run,
        "moved_count": len(moved_records),
        "skipped_with_json": skipped_with_json,
        "skipped_with_nonempty_txt": skipped_with_nonempty_txt,
        "moved_examples": moved_records[:50],
    }

    summary_path = output_root / "move_summary.json"
    with open(summary_path, "w", encoding="utf-8") as file_obj:
        json.dump(summary, file_obj, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"移动汇总已写入: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())