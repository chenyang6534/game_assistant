"""将原始 YOLO 标注数据切分为 train/val/test。"""

from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path
from typing import Iterable, List, Tuple


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp"}


def parse_args() -> argparse.Namespace:
    default_root = Path(__file__).resolve().parents[1] / "datasets" / "plot_det"
    parser = argparse.ArgumentParser(description="切分地块检测数据集")
    parser.add_argument("--source-images", required=True, help="原始图片目录")
    parser.add_argument("--source-labels", required=True, help="原始标签目录")
    parser.add_argument("--output-root", default=str(default_root), help="数据集根目录")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="训练集比例")
    parser.add_argument("--val-ratio", type=float, default=0.1, help="验证集比例")
    parser.add_argument("--test-ratio", type=float, default=0.1, help="测试集比例")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--clear-output", action="store_true", help="切分前清空 train/val/test 目录")
    parser.add_argument("--strict-missing-labels", action="store_true", help="若图片缺少同名 txt 标签则直接报错")
    return parser.parse_args()


def collect_images(directory: Path) -> List[Path]:
    return sorted(path for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)


def ensure_ratio_sum(train_ratio: float, val_ratio: float, test_ratio: float) -> None:
    total = train_ratio + val_ratio + test_ratio
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"切分比例之和必须为 1，当前为 {total:.6f}")


def build_records(
    source_images: Path,
    source_labels: Path,
    strict_missing_labels: bool = False,
) -> Tuple[List[Tuple[Path, Path | None]], int]:
    records: List[Tuple[Path, Path | None]] = []
    missing_labels: List[str] = []
    empty_labels_created = 0
    for image_path in collect_images(source_images):
        label_path = source_labels / f"{image_path.stem}.txt"
        if not label_path.exists():
            if strict_missing_labels:
                missing_labels.append(image_path.name)
                continue
            empty_labels_created += 1
            records.append((image_path, None))
            continue
        records.append((image_path, label_path))

    if missing_labels:
        preview = ", ".join(missing_labels[:10])
        raise FileNotFoundError(f"以下图片缺少标签文件: {preview}")

    if not records:
        raise ValueError("没有找到可切分的图片和标签")
    return records, empty_labels_created


def prepare_split_dirs(output_root: Path, clear_output: bool) -> None:
    split_dirs = [
        output_root / "images" / "train",
        output_root / "images" / "val",
        output_root / "images" / "test",
        output_root / "labels" / "train",
        output_root / "labels" / "val",
        output_root / "labels" / "test",
    ]
    for directory in split_dirs:
        if clear_output and directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)


def split_records(records: List[Tuple[Path, Path | None]], train_ratio: float, val_ratio: float, seed: int) -> dict:
    random.Random(seed).shuffle(records)
    total = len(records)
    train_end = int(total * train_ratio)
    val_end = train_end + int(total * val_ratio)
    return {
        "train": records[:train_end],
        "val": records[train_end:val_end],
        "test": records[val_end:],
    }


def copy_split_files(output_root: Path, split_name: str, records: Iterable[Tuple[Path, Path | None]]) -> int:
    count = 0
    image_dir = output_root / "images" / split_name
    label_dir = output_root / "labels" / split_name
    for image_path, label_path in records:
        shutil.copy2(image_path, image_dir / image_path.name)
        target_label_path = label_dir / f"{image_path.stem}.txt"
        if label_path is None:
            target_label_path.write_text("", encoding="utf-8")
        else:
            shutil.copy2(label_path, target_label_path)
        count += 1
    return count


def main() -> int:
    args = parse_args()
    ensure_ratio_sum(args.train_ratio, args.val_ratio, args.test_ratio)

    source_images = Path(args.source_images)
    source_labels = Path(args.source_labels)
    output_root = Path(args.output_root)

    records, empty_labels_created = build_records(
        source_images,
        source_labels,
        strict_missing_labels=args.strict_missing_labels,
    )
    prepare_split_dirs(output_root, clear_output=args.clear_output)
    split_map = split_records(records, args.train_ratio, args.val_ratio, args.seed)

    summary = {
        "total": len(records),
        "seed": args.seed,
        "empty_labels_created": empty_labels_created,
        "train": copy_split_files(output_root, "train", split_map["train"]),
        "val": copy_split_files(output_root, "val", split_map["val"]),
        "test": copy_split_files(output_root, "test", split_map["test"]),
    }

    summary_path = output_root / "split_summary.json"
    with open(summary_path, "w", encoding="utf-8") as file_obj:
        json.dump(summary, file_obj, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"切分结果已写入: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())