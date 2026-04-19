"""将属性分类原始裁剪集切分为 train/val/test。"""

from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path
from typing import Dict, List


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="切分属性分类数据集")
    parser.add_argument("--source-raw-root", required=True, help="原始裁剪集目录，例如 level/raw")
    parser.add_argument("--output-root", required=True, help="输出根目录，例如 level")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="训练集比例")
    parser.add_argument("--val-ratio", type=float, default=0.1, help="验证集比例")
    parser.add_argument("--test-ratio", type=float, default=0.1, help="测试集比例")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--clear-output", action="store_true", help="切分前清空 train/val/test 目录")
    return parser.parse_args()


def ensure_ratio_sum(train_ratio: float, val_ratio: float, test_ratio: float) -> None:
    total = train_ratio + val_ratio + test_ratio
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"切分比例之和必须为 1，当前为 {total:.6f}")


def collect_class_files(source_raw_root: Path) -> Dict[str, List[Path]]:
    class_map: Dict[str, List[Path]] = {}
    for class_dir in sorted(path for path in source_raw_root.iterdir() if path.is_dir()):
        files = sorted(
            path for path in class_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        )
        if files:
            class_map[class_dir.name] = files
    if not class_map:
        raise ValueError(f"原始裁剪目录没有找到任何类别图片: {source_raw_root}")
    return class_map


def prepare_output_dirs(output_root: Path, class_names: List[str], clear_output: bool) -> None:
    for split_name in ("train", "val", "test"):
        split_root = output_root / split_name
        if clear_output and split_root.exists():
            shutil.rmtree(split_root)
        split_root.mkdir(parents=True, exist_ok=True)
        for class_name in class_names:
            (split_root / class_name).mkdir(parents=True, exist_ok=True)


def split_list(files: List[Path], train_ratio: float, val_ratio: float, seed: int) -> Dict[str, List[Path]]:
    items = list(files)
    random.Random(seed).shuffle(items)
    total = len(items)
    train_end = int(total * train_ratio)
    val_end = train_end + int(total * val_ratio)
    return {
        "train": items[:train_end],
        "val": items[train_end:val_end],
        "test": items[val_end:],
    }


def copy_files(output_root: Path, class_name: str, split_name: str, files: List[Path]) -> int:
    destination = output_root / split_name / class_name
    for path in files:
        shutil.copy2(path, destination / path.name)
    return len(files)


def main() -> int:
    args = parse_args()
    ensure_ratio_sum(args.train_ratio, args.val_ratio, args.test_ratio)

    source_raw_root = Path(args.source_raw_root)
    output_root = Path(args.output_root)
    if not source_raw_root.exists():
        raise FileNotFoundError(f"原始裁剪目录不存在: {source_raw_root}")

    class_map = collect_class_files(source_raw_root)
    class_names = list(class_map.keys())
    prepare_output_dirs(output_root, class_names, clear_output=args.clear_output)

    summary = {
        "classes": class_names,
        "seed": args.seed,
        "splits": {},
    }

    for class_name, files in class_map.items():
        split_map = split_list(files, args.train_ratio, args.val_ratio, args.seed)
        summary["splits"][class_name] = {
            split_name: copy_files(output_root, class_name, split_name, split_files)
            for split_name, split_files in split_map.items()
        }

    classes_file = output_root / "classes.txt"
    with open(classes_file, "w", encoding="utf-8") as file_obj:
        file_obj.write("\n".join(class_names) + "\n")

    summary_path = output_root / "split_summary.json"
    with open(summary_path, "w", encoding="utf-8") as file_obj:
        json.dump(summary, file_obj, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"分类切分结果已写入: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())