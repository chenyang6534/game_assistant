"""训练单类地块检测模型。"""

from __future__ import annotations

import argparse
import importlib
import tempfile
import time
from pathlib import Path

import yaml


AI_ROOT = Path(__file__).resolve().parents[1]


def load_yolo_class():
    try:
        module = importlib.import_module("ultralytics")
    except ImportError as exc:  # pragma: no cover - 依赖缺失时由用户安装
        raise ImportError("请安装 ultralytics: pip install ultralytics") from exc
    return module.YOLO


def install_ultralytics_checkpoint_retry_patch() -> None:
    trainer_module = importlib.import_module("ultralytics.engine.trainer")
    base_trainer = trainer_module.BaseTrainer
    original_save_model = base_trainer.save_model
    if getattr(original_save_model, "_copilot_retry_patch", False):
        return

    def save_model_with_retry(self, *args, **kwargs):
        max_attempts = 8
        for attempt in range(max_attempts):
            try:
                return original_save_model(self, *args, **kwargs)
            except PermissionError as exc:
                if attempt >= max_attempts - 1:
                    raise
                delay_seconds = min(5.0, 0.5 * (attempt + 1))
                target = getattr(exc, "filename", "") or "checkpoint"
                print(
                    f"警告: 保存权重时文件被占用: {target}，"
                    f"{delay_seconds:.1f} 秒后重试 ({attempt + 1}/{max_attempts - 1})"
                )
                time.sleep(delay_seconds)

    save_model_with_retry._copilot_retry_patch = True
    base_trainer.save_model = save_model_with_retry


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="训练 AI 目标检测模型")
    parser.add_argument("--data", default=str(AI_ROOT / "datasets" / "plot_det" / "data.yaml"), help="data.yaml 路径")
    parser.add_argument("--model", default="yolov8n.pt", help="基础模型名称或权重路径")
    parser.add_argument("--imgsz", type=int, default=640, help="训练输入尺寸")
    parser.add_argument("--epochs", type=int, default=120, help="训练轮数")
    parser.add_argument("--batch", type=int, default=16, help="batch size")
    parser.add_argument("--workers", type=int, default=4, help="数据加载 worker 数")
    parser.add_argument("--patience", type=int, default=20, help="early stopping patience")
    parser.add_argument("--close-mosaic", type=int, default=10, help="最后多少轮关闭 mosaic")
    parser.add_argument("--device", default="", help="设备，例如 cpu、0、0,1；留空表示自动")
    parser.add_argument("--project", default=str(AI_ROOT / "outputs" / "train"), help="训练输出根目录")
    parser.add_argument("--name", default="plot_node_det_yolov8n", help="训练任务名称")
    parser.add_argument("--cache", action="store_true", help="是否缓存数据集")
    parser.add_argument("--exist-ok", action="store_true", help="允许覆盖同名输出目录")
    return parser.parse_args()


def resolve_model_arg(model_arg: str) -> str:
    candidate = Path(model_arg)
    if candidate.exists():
        return str(candidate.resolve())
    return model_arg


def build_resolved_data_config(data_path: Path) -> dict:
    with open(data_path, "r", encoding="utf-8") as file_obj:
        data = yaml.safe_load(file_obj) or {}

    if not isinstance(data, dict):
        raise ValueError(f"data.yaml 格式无效: {data_path}")

    yaml_parent = data_path.parent.resolve()
    raw_root = str(data.get("path", ".") or ".").strip()
    root_path = Path(raw_root)
    if not root_path.is_absolute():
        root_path = (yaml_parent / root_path).resolve()
    else:
        root_path = root_path.resolve()

    for split_name in ("train", "val"):
        split_value = str(data.get(split_name, "")).strip()
        if not split_value:
            raise ValueError(f"data.yaml 缺少 {split_name} 配置: {data_path}")
        split_path = Path(split_value)
        if not split_path.is_absolute():
            split_path = (root_path / split_path).resolve()
        if not split_path.exists():
            raise FileNotFoundError(f"{split_name} 图片目录不存在: {split_path}")

    test_value = str(data.get("test", "")).strip()
    if test_value:
        test_path = Path(test_value)
        if not test_path.is_absolute():
            test_path = (root_path / test_path).resolve()
        if not test_path.exists():
            print(f"警告: test 图片目录不存在，训练仍会继续: {test_path}")

    data["path"] = str(root_path)
    return data


def main() -> int:
    args = parse_args()
    data_path = Path(args.data).resolve()
    if not data_path.exists():
        raise FileNotFoundError(f"data.yaml 不存在: {data_path}")

    project_path = Path(args.project).resolve()
    project_path.mkdir(parents=True, exist_ok=True)

    yolo_class = load_yolo_class()
    install_ultralytics_checkpoint_retry_patch()
    model = yolo_class(resolve_model_arg(args.model))

    resolved_data = build_resolved_data_config(data_path)
    with tempfile.TemporaryDirectory(prefix="plot_det_data_") as temp_dir:
        resolved_yaml_path = Path(temp_dir) / data_path.name
        with open(resolved_yaml_path, "w", encoding="utf-8") as file_obj:
            yaml.safe_dump(resolved_data, file_obj, allow_unicode=True, sort_keys=False)

        print(f"使用解析后的数据配置: {resolved_yaml_path}")
        print(f"数据集根目录: {resolved_data['path']}")
        results = model.train(
            data=str(resolved_yaml_path),
            imgsz=args.imgsz,
            epochs=args.epochs,
            batch=args.batch,
            workers=args.workers,
            patience=args.patience,
            close_mosaic=args.close_mosaic,
            project=str(project_path),
            name=args.name,
            device=args.device or None,
            cache=args.cache,
            exist_ok=args.exist_ok,
            single_cls=True,
        )

    save_dir = getattr(results, "save_dir", None)
    print(f"训练完成，输出目录: {save_dir or project_path / args.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())