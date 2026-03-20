"""导出可分发的 AI 地块识别模型包。"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

AI_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = AI_ROOT.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ai_tile_mvp.project_scaffold import get_review_classifier_config, load_project_meta


PACKAGE_MANIFEST_NAME = "model_package.gaimodel.json"
PACKAGE_README_NAME = "README.txt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导出可分发的 AI 模型包")
    parser.add_argument("--project-config", required=True, help="项目配置文件 project_meta.json")
    parser.add_argument("--detector-model", default="", help="要打包的检测 ONNX 路径，默认使用项目默认 onnx")
    parser.add_argument("--detector-meta", default="", help="检测模型元数据 json 路径，默认取 onnx 同名 json")
    parser.add_argument("--output-dir", required=True, help="模型包输出目录")
    parser.add_argument("--overwrite", action="store_true", help="输出目录已存在时允许覆盖")
    parser.add_argument("--zip", action="store_true", help="同时生成 zip 压缩包")
    return parser.parse_args()


def resolve_optional_project_path(project_root: Path, raw_path: object) -> Path | None:
    path_text = str(raw_path or "").strip()
    if not path_text:
        return None
    candidate = Path(path_text)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate.resolve()


def find_attribute_weights(train_attr_root: Path, task_slug: str) -> Path | None:
    direct = train_attr_root / f"{task_slug}_yolov8n_cls" / "weights" / "best.pt"
    if direct.exists():
        return direct

    candidates: list[Path] = []
    if train_attr_root.exists():
        for candidate in train_attr_root.rglob("best.pt"):
            run_name = candidate.parent.parent.name.lower()
            if task_slug.lower() in run_name:
                candidates.append(candidate)

    if not candidates:
        return None
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def default_detector_model_path(project_root: Path, project_meta: dict[str, Any]) -> Path:
    run_name = str(project_meta.get("detection_run_name") or "plot_node_det_yolov8n").strip() or "plot_node_det_yolov8n"
    return (project_root / "models" / "detector" / f"{run_name}_640.onnx").resolve()


def build_package_readme(
    package_root: Path,
    manifest_name: str,
    detector_model_rel: str,
    included_attribute_tasks: list[str],
    included_review_task: str,
    warnings: list[str],
) -> str:
    lines = [
        "AI 模型包",
        "",
        "这个目录是可分发的主程序运行包。解压后请保持目录结构不变。",
        "",
        "主程序使用方式：",
        "1. 打开主程序任务步骤，识别类型选择“AI 地块识别”",
        "2. 新版主程序可直接选择导出的 ZIP 压缩包，无需手动解压",
        f"3. 如果已经解压，在“识别目标”里优先选择 {manifest_name}；主程序版本较旧时也可以改选 {detector_model_rel}",
        "4. 不要单独把 onnx 从包里拖出来，否则主程序无法自动找到同包里的属性/复检权重",
        "",
        "包内内容：",
        f"- 检测模型: {detector_model_rel}",
        f"- 属性任务数: {len(included_attribute_tasks)}",
        f"- 候选框复检: {'有' if included_review_task else '无'}",
    ]

    if included_attribute_tasks:
        lines.append(f"- 已打包属性任务: {', '.join(included_attribute_tasks)}")
    if included_review_task:
        lines.append(f"- 已打包复检任务: {included_review_task}")

    if warnings:
        lines.extend(["", "导出警告："])
        lines.extend(f"- {item}" for item in warnings)
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    project_config_path = Path(args.project_config).resolve()
    if not project_config_path.exists():
        raise FileNotFoundError(f"项目配置不存在: {project_config_path}")

    project_root = project_config_path.parent
    project_meta = load_project_meta(project_config_path)
    package_root = Path(args.output_dir).resolve()
    if package_root.exists():
        has_content = any(package_root.iterdir()) if package_root.is_dir() else True
        if has_content and not args.overwrite:
            raise FileExistsError(f"输出目录已存在且非空: {package_root}")
        if args.overwrite:
            if package_root.is_dir():
                shutil.rmtree(package_root)
            else:
                package_root.unlink()
    package_root.mkdir(parents=True, exist_ok=True)

    detector_model_path = Path(args.detector_model).resolve() if args.detector_model.strip() else default_detector_model_path(project_root, project_meta)
    if not detector_model_path.exists():
        raise FileNotFoundError(f"检测 ONNX 不存在: {detector_model_path}")

    detector_meta_path = Path(args.detector_meta).resolve() if args.detector_meta.strip() else detector_model_path.with_suffix(".json")
    warnings: list[str] = []

    packaged_meta = deepcopy(project_meta)
    review_config_raw = packaged_meta.get("review_classifier")
    if isinstance(review_config_raw, dict):
        review_config_raw["weights"] = ""

    detector_rel = Path("models") / "detector" / detector_model_path.name
    copy_file(detector_model_path, package_root / detector_rel)
    print(f"已复制检测模型: {detector_model_path}")
    detector_meta_rel = ""
    if detector_meta_path.exists():
        detector_meta_rel = str((Path("models") / "detector" / detector_meta_path.name).as_posix())
        copy_file(detector_meta_path, package_root / detector_meta_rel)
        print(f"已复制模型元数据: {detector_meta_path}")
    else:
        warnings.append(f"未找到检测模型元数据: {detector_meta_path}")

    for relative_config in (
        Path("configs") / "label_classes.txt",
        Path("configs") / "attributes.json",
        Path("configs") / "model_meta.template.json",
    ):
        src = project_root / relative_config
        if src.exists():
            copy_file(src, package_root / relative_config)

    train_attr_root = project_root / "outputs" / "train_attr"
    included_attribute_tasks: list[str] = []
    for task in packaged_meta.get("attribute_tasks") or []:
        task_slug = str(task.get("slug") or "").strip()
        if not task_slug:
            continue
        weights_path = find_attribute_weights(train_attr_root, task_slug)
        if weights_path is None:
            warnings.append(f"未找到属性任务 {task_slug} 的 best.pt，已跳过")
            continue
        target = package_root / "outputs" / "train_attr" / f"{task_slug}_yolov8n_cls" / "weights" / "best.pt"
        copy_file(weights_path, target)
        included_attribute_tasks.append(task_slug)
        print(f"已复制属性模型: {task_slug} -> {weights_path}")

    included_review_task = ""
    review_config = get_review_classifier_config(packaged_meta, default_if_missing=False)
    if review_config is not None:
        review_task_slug = str(review_config.get("task_slug") or "").strip()
        weights_path = resolve_optional_project_path(project_root, review_config.get("weights"))
        if weights_path is not None and not weights_path.exists():
            warnings.append(f"复检配置指定的权重不存在: {weights_path}")
            weights_path = None
        if weights_path is None and review_task_slug:
            weights_path = find_attribute_weights(train_attr_root, review_task_slug)
        if weights_path is not None and review_task_slug:
            target = package_root / "outputs" / "train_attr" / f"{review_task_slug}_yolov8n_cls" / "weights" / "best.pt"
            copy_file(weights_path, target)
            included_review_task = review_task_slug
            print(f"已复制复检模型: {review_task_slug} -> {weights_path}")
        elif review_task_slug:
            warnings.append(f"未找到复检任务 {review_task_slug} 的 best.pt，主程序将仅使用检测模型")

    write_json(package_root / "project_meta.json", packaged_meta)

    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "project_name": str(packaged_meta.get("project_name") or project_root.name),
        "project_slug": str(packaged_meta.get("project_slug") or project_root.name),
        "project_meta": "project_meta.json",
        "detector_model": detector_rel.as_posix(),
        "detector_meta": detector_meta_rel,
        "attribute_tasks": included_attribute_tasks,
        "review_task": included_review_task,
    }
    write_json(package_root / PACKAGE_MANIFEST_NAME, manifest)
    write_text(
        package_root / PACKAGE_README_NAME,
        build_package_readme(
            package_root,
            PACKAGE_MANIFEST_NAME,
            detector_rel.as_posix(),
            included_attribute_tasks,
            included_review_task,
            warnings,
        ),
    )

    zip_path = ""
    if args.zip:
        archive_base = package_root.parent / package_root.name
        zip_candidate = archive_base.with_suffix(".zip")
        if zip_candidate.exists():
            if args.overwrite:
                zip_candidate.unlink()
            else:
                raise FileExistsError(f"ZIP 文件已存在: {zip_candidate}")
        zip_path = shutil.make_archive(str(archive_base), "zip", root_dir=package_root.parent, base_dir=package_root.name)

    print(f"模型包已生成: {package_root}")
    print(f"模型包清单: {package_root / PACKAGE_MANIFEST_NAME}")
    if zip_path:
        print(f"ZIP 压缩包: {zip_path}")
    if warnings:
        print("警告:")
        for item in warnings:
            print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())