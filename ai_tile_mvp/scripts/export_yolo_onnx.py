"""将 YOLO 权重导出为 ONNX，并生成模型元数据。"""

from __future__ import annotations

import argparse
import importlib
import json
import shutil
from pathlib import Path


AI_ROOT = Path(__file__).resolve().parents[1]


def load_yolo_class():
    try:
        module = importlib.import_module("ultralytics")
    except ImportError as exc:  # pragma: no cover - 依赖缺失时由用户安装
        raise ImportError("请安装 ultralytics: pip install ultralytics") from exc
    return module.YOLO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导出 YOLO ONNX 模型")
    parser.add_argument("--weights", required=True, help="best.pt 权重路径")
    parser.add_argument("--output", default=str(AI_ROOT / "models" / "tile_detector" / "plot_node_det_yolov8n_640.onnx"), help="导出的 onnx 路径")
    parser.add_argument("--meta-output", default="", help="导出的模型元数据 json 路径，默认放在 onnx 同目录")
    parser.add_argument("--meta-template", default=str(AI_ROOT / "configs" / "plot_model_meta.template.json"), help="元数据模板路径")
    parser.add_argument("--imgsz", type=int, default=640, help="导出尺寸")
    parser.add_argument("--opset", type=int, default=12, help="ONNX opset")
    parser.add_argument("--conf-threshold", type=float, default=0.35, help="写入元数据的默认置信度阈值")
    parser.add_argument("--iou-threshold", type=float, default=0.50, help="写入元数据的默认 NMS 阈值")
    parser.add_argument("--max-detections", type=int, default=300, help="写入元数据的最大检测数")
    parser.add_argument("--simplify", action="store_true", help="导出后尝试简化模型")
    parser.add_argument("--dynamic", action="store_true", help="导出动态尺寸模型")
    parser.add_argument("--half", action="store_true", help="导出半精度模型")
    parser.add_argument("--nms", action="store_true", help="导出时内置 NMS")
    return parser.parse_args()


def resolve_export_path(export_result, weights_path: Path) -> Path:
    if isinstance(export_result, (list, tuple)) and export_result:
        candidate = Path(str(export_result[0]))
        if candidate.exists():
            return candidate
    else:
        candidate = Path(str(export_result))
        if candidate.exists():
            return candidate

    recent = sorted(weights_path.parent.glob("*.onnx"), key=lambda path: path.stat().st_mtime, reverse=True)
    if recent:
        return recent[0]
    raise FileNotFoundError("导出完成后未找到 onnx 文件")


def build_meta(meta_template_path: Path, args: argparse.Namespace) -> dict:
    meta = {}
    if meta_template_path.exists():
        with open(meta_template_path, "r", encoding="utf-8") as file_obj:
            meta = json.load(file_obj)
    meta["input_size"] = args.imgsz
    meta["conf_threshold"] = args.conf_threshold
    meta["iou_threshold"] = args.iou_threshold
    meta["max_detections"] = args.max_detections
    meta.setdefault("class_names", ["plot_node"])
    meta["version"] = f"exported-{args.imgsz}"
    return meta


def main() -> int:
    args = parse_args()
    weights_path = Path(args.weights).resolve()
    if not weights_path.exists():
        raise FileNotFoundError(f"权重文件不存在: {weights_path}")

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    yolo_class = load_yolo_class()
    model = yolo_class(str(weights_path))
    export_result = model.export(
        format="onnx",
        imgsz=args.imgsz,
        opset=args.opset,
        simplify=args.simplify,
        dynamic=args.dynamic,
        half=args.half,
        nms=args.nms,
    )
    exported_path = resolve_export_path(export_result, weights_path)

    if exported_path != output_path:
        shutil.copy2(exported_path, output_path)
    else:
        output_path = exported_path

    meta_path = Path(args.meta_output).resolve() if args.meta_output else output_path.with_suffix(".json")
    meta = build_meta(Path(args.meta_template).resolve(), args)
    with open(meta_path, "w", encoding="utf-8") as file_obj:
        json.dump(meta, file_obj, ensure_ascii=False, indent=2)

    print(f"ONNX 模型已生成: {output_path}")
    print(f"模型元数据已生成: {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())