"""训练属性分类模型。"""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path


AI_ROOT = Path(__file__).resolve().parents[1]


def load_yolo_class():
    try:
        module = importlib.import_module("ultralytics")
    except ImportError as exc:  # pragma: no cover - 依赖缺失时由用户安装
        raise ImportError("请安装 ultralytics: pip install ultralytics") from exc
    return module.YOLO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="训练属性分类模型")
    parser.add_argument("--data-root", required=True, help="分类数据根目录，包含 train/val/test")
    parser.add_argument("--model", default="yolov8n-cls.pt", help="基础分类模型名称或权重路径")
    parser.add_argument("--imgsz", type=int, default=224, help="训练输入尺寸")
    parser.add_argument("--epochs", type=int, default=80, help="训练轮数")
    parser.add_argument("--batch", type=int, default=32, help="batch size")
    parser.add_argument("--workers", type=int, default=4, help="数据加载 worker 数")
    parser.add_argument("--patience", type=int, default=15, help="early stopping patience")
    parser.add_argument("--device", default="", help="设备，例如 cpu、0；留空表示自动")
    parser.add_argument("--project", default=str(AI_ROOT / "outputs" / "train_attr"), help="训练输出根目录")
    parser.add_argument("--name", default="attr_yolov8n_cls", help="训练任务名称")
    parser.add_argument("--cache", action="store_true", help="是否缓存数据集")
    parser.add_argument("--exist-ok", action="store_true", help="允许覆盖同名输出目录")
    return parser.parse_args()


def resolve_model_arg(model_arg: str) -> str:
    candidate = Path(model_arg)
    if candidate.exists():
        return str(candidate.resolve())
    return model_arg


def main() -> int:
    args = parse_args()
    data_root = Path(args.data_root).resolve()
    if not (data_root / "train").exists():
        raise FileNotFoundError(f"分类训练目录不存在: {data_root / 'train'}")
    if not (data_root / "val").exists():
        raise FileNotFoundError(f"分类验证目录不存在: {data_root / 'val'}")

    project_path = Path(args.project).resolve()
    project_path.mkdir(parents=True, exist_ok=True)

    yolo_class = load_yolo_class()
    model = yolo_class(resolve_model_arg(args.model))
    results = model.train(
        data=str(data_root),
        imgsz=args.imgsz,
        epochs=args.epochs,
        batch=args.batch,
        workers=args.workers,
        patience=args.patience,
        project=str(project_path),
        name=args.name,
        device=args.device or None,
        cache=args.cache,
        exist_ok=args.exist_ok,
    )

    save_dir = getattr(results, "save_dir", None)
    print(f"训练完成，输出目录: {save_dir or project_path / args.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())