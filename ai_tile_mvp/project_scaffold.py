"""AI 训练项目脚手架生成工具。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


AI_ROOT = Path(__file__).resolve().parent
DEFAULT_PROJECTS_ROOT = AI_ROOT / "projects"
DEFAULT_ATTRIBUTE_SPEC_TEXT = "\n".join(
    [
        "等级: 4级, 5级, 6级, 7级, 8级, 9级, 10级",
        "类型: 木材, 石头, 铁矿, 铜矿, 粮食",
        "关系: 同盟, 友盟, 中立, 敌对, 我方",
    ]
)

TASK_SLUG_HINTS = {
    "等级": "level",
    "level": "level",
    "级别": "level",
    "类型": "resource_type",
    "资源类型": "resource_type",
    "resource_type": "resource_type",
    "关系": "relation",
    "relation": "relation",
    "阵营": "relation",
    "外交关系": "relation",
}

TASK_ALIAS_HINTS = {
    "level": ["等级", "level", "级别"],
    "resource_type": ["类型", "resource_type", "资源类型"],
    "relation": ["关系", "relation", "阵营", "外交关系"],
}

CLASS_HINTS = {
    "level": {
        "4级": {"slug": "lv04", "aliases": ["4级", "4", "04", "lv4", "lv04"]},
        "5级": {"slug": "lv05", "aliases": ["5级", "5", "05", "lv5", "lv05"]},
        "6级": {"slug": "lv06", "aliases": ["6级", "6", "06", "lv6", "lv06"]},
        "7级": {"slug": "lv07", "aliases": ["7级", "7", "07", "lv7", "lv07"]},
        "8级": {"slug": "lv08", "aliases": ["8级", "8", "08", "lv8", "lv08"]},
        "9级": {"slug": "lv09", "aliases": ["9级", "9", "09", "lv9", "lv09"]},
        "10级": {"slug": "lv10", "aliases": ["10级", "10", "lv10"]},
    },
    "resource_type": {
        "木材": {"slug": "wood", "aliases": ["木材", "wood"]},
        "石头": {"slug": "stone", "aliases": ["石头", "石料", "stone"]},
        "铁矿": {"slug": "iron", "aliases": ["铁矿", "iron"]},
        "铜矿": {"slug": "copper", "aliases": ["铜矿", "铜", "copper"]},
        "粮食": {"slug": "food", "aliases": ["粮食", "food"]},
    },
    "relation": {
        "同盟": {"slug": "ally", "aliases": ["同盟", "ally"]},
        "友盟": {"slug": "friendly", "aliases": ["友盟", "friendly"]},
        "中立": {"slug": "neutral", "aliases": ["中立", "neutral"]},
        "敌对": {"slug": "enemy", "aliases": ["敌对", "enemy"]},
        "我方": {"slug": "self", "aliases": ["我方", "self"]},
    },
}

ATTRIBUTE_VALUE_SPLIT_PATTERN = re.compile(r"[,，;；、]+")
INVALID_PROJECT_CHARS = set('<>:"/\\|?*')
DEFAULT_REVIEW_TASK_SLUG = "candidate_review"
DEFAULT_REVIEW_DISPLAY_NAME = "候选框复检"
DEFAULT_REVIEW_THRESHOLD = 0.75
DEFAULT_REVIEW_POSITIVE_CLASS = {
    "display_name": "正确样本",
    "slug": "positive",
    "aliases": ["positive", "correct", "true", "target", "tile", "node", "plot", "目标", "地块"],
}
DEFAULT_REVIEW_NEGATIVE_CLASS = {
    "display_name": "错误样本",
    "slug": "negative",
    "aliases": [
        "negative",
        "wrong",
        "false",
        "background",
        "bg",
        "other",
        "not_plot",
        "notplot",
        "误检",
        "背景",
        "非地块",
    ],
}


def _unique_list(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        marker = text.lower()
        if marker in seen:
            continue
        seen.add(marker)
        result.append(text)
    return result


def build_default_review_classifier_config() -> dict[str, Any]:
    return {
        "task_slug": DEFAULT_REVIEW_TASK_SLUG,
        "display_name": DEFAULT_REVIEW_DISPLAY_NAME,
        "weights": "",
        "threshold": DEFAULT_REVIEW_THRESHOLD,
        "positive_class": {
            "display_name": str(DEFAULT_REVIEW_POSITIVE_CLASS["display_name"]),
            "slug": str(DEFAULT_REVIEW_POSITIVE_CLASS["slug"]),
            "aliases": list(DEFAULT_REVIEW_POSITIVE_CLASS["aliases"]),
        },
        "negative_class": {
            "display_name": str(DEFAULT_REVIEW_NEGATIVE_CLASS["display_name"]),
            "slug": str(DEFAULT_REVIEW_NEGATIVE_CLASS["slug"]),
            "aliases": list(DEFAULT_REVIEW_NEGATIVE_CLASS["aliases"]),
        },
    }


def _normalize_review_class(
    raw_class: object,
    *,
    role: str,
    default_class: dict[str, Any],
    legacy_aliases: object = None,
) -> dict[str, Any]:
    class_config = raw_class if isinstance(raw_class, dict) else {}
    display_name = str(class_config.get("display_name") or default_class["display_name"]).strip()
    if not display_name:
        display_name = str(default_class["display_name"])

    slug = slugify_identifier(
        str(class_config.get("slug") or default_class["slug"]),
        str(default_class["slug"]),
    )
    raw_aliases = class_config.get("aliases")
    alias_items = raw_aliases if isinstance(raw_aliases, (list, tuple, set)) else []
    legacy_items = legacy_aliases if isinstance(legacy_aliases, (list, tuple, set)) else []
    aliases = _unique_list(
        [
            display_name,
            slug,
            *(str(item) for item in alias_items),
            *(str(item) for item in default_class.get("aliases", [])),
            *(str(item) for item in legacy_items),
        ]
    )
    return {
        "role": role,
        "display_name": display_name,
        "slug": slug,
        "aliases": aliases,
    }


def normalize_review_classifier_config(raw_config: object) -> dict[str, Any] | None:
    if raw_config in (None, False):
        return None
    if not isinstance(raw_config, dict):
        return None
    if raw_config.get("enabled") is False:
        return None

    task_slug = slugify_identifier(str(raw_config.get("task_slug") or DEFAULT_REVIEW_TASK_SLUG), DEFAULT_REVIEW_TASK_SLUG)
    display_name = str(raw_config.get("display_name") or DEFAULT_REVIEW_DISPLAY_NAME).strip() or DEFAULT_REVIEW_DISPLAY_NAME

    positive_class = _normalize_review_class(
        raw_config.get("positive_class"),
        role="positive",
        default_class=DEFAULT_REVIEW_POSITIVE_CLASS,
    )
    negative_class = _normalize_review_class(
        raw_config.get("negative_class"),
        role="negative",
        default_class=DEFAULT_REVIEW_NEGATIVE_CLASS,
    )

    if positive_class["slug"] == negative_class["slug"]:
        negative_slug = slugify_identifier(f"{negative_class['slug']}_negative", "negative")
        negative_class["slug"] = negative_slug
        negative_class["aliases"] = _unique_list([negative_class["display_name"], negative_slug, *negative_class["aliases"]])

    try:
        threshold = float(raw_config.get("threshold", DEFAULT_REVIEW_THRESHOLD) or DEFAULT_REVIEW_THRESHOLD)
    except (TypeError, ValueError):
        threshold = DEFAULT_REVIEW_THRESHOLD

    classes = [positive_class, negative_class]
    return {
        "task_slug": task_slug,
        "display_name": display_name,
        "weights": str(raw_config.get("weights") or "").strip(),
        "threshold": max(0.0, min(1.0, threshold)),
        "positive_class": positive_class,
        "negative_class": negative_class,
        "positive_class_slug": str(positive_class["slug"]),
        "negative_class_slug": str(negative_class["slug"]),
        "classes": classes,
        "class_display_map": {str(item["slug"]): str(item["display_name"]) for item in classes},
        "positive_aliases": list(positive_class["aliases"]),
        "negative_aliases": list(negative_class["aliases"]),
    }


def get_review_classifier_config(
    project_meta: dict[str, Any] | None,
    *,
    default_if_missing: bool = False,
) -> dict[str, Any] | None:
    raw_config = None
    if isinstance(project_meta, dict):
        raw_config = project_meta.get("review_classifier")
    if raw_config is None and default_if_missing:
        raw_config = build_default_review_classifier_config()
    return normalize_review_classifier_config(raw_config)


def slugify_identifier(text: str, fallback: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", str(text).strip().lower())
    slug = "_".join(parts).strip("_")
    return slug or fallback


def validate_project_name(project_name: str) -> str:
    cleaned = str(project_name).strip()
    if not cleaned:
        raise ValueError("项目名不能为空")
    if cleaned in {".", ".."}:
        raise ValueError("项目名不能是 . 或 ..")
    if any(char in INVALID_PROJECT_CHARS for char in cleaned):
        raise ValueError("项目名包含 Windows 不允许的字符")
    if Path(cleaned).name != cleaned:
        raise ValueError("项目名不能包含路径分隔符")
    return cleaned


def build_default_detection_label(project_name: str) -> str:
    return f"{slugify_identifier(project_name, 'project')}_node"


def build_detection_run_name(project_name: str) -> str:
    return f"{slugify_identifier(project_name, 'project')}_det_yolov8n"


def _split_task_line(line: str) -> tuple[str, str]:
    for separator in (":", "：", "="):
        index = line.find(separator)
        if index > 0:
            left = line[:index].strip()
            right = line[index + 1 :].strip()
            if left and right:
                return left, right
    raise ValueError(f"属性定义格式无效: {line}")


def _split_name_and_slug(raw_text: str) -> tuple[str, str]:
    text = str(raw_text).strip()
    if "=>" in text:
        display_name, explicit_slug = text.split("=>", 1)
        return display_name.strip(), explicit_slug.strip()
    return text, ""


def _suggest_task_slug(display_name: str, index: int) -> str:
    direct = TASK_SLUG_HINTS.get(display_name)
    if direct:
        return direct
    return slugify_identifier(display_name, f"task_{index:02d}")


def _suggest_class_slug(task_slug: str, display_name: str, index: int) -> str:
    task_hints = CLASS_HINTS.get(task_slug, {})
    hint = task_hints.get(display_name)
    if hint:
        return str(hint["slug"])
    return slugify_identifier(display_name, f"class_{index:02d}")


def _build_task_aliases(display_name: str, slug: str) -> list[str]:
    return _unique_list([display_name, slug, *TASK_ALIAS_HINTS.get(slug, [])])


def _build_class_aliases(task_slug: str, display_name: str, slug: str) -> list[str]:
    task_hints = CLASS_HINTS.get(task_slug, {})
    hint = task_hints.get(display_name, {})
    aliases = [display_name, slug, *hint.get("aliases", [])]
    return _unique_list(aliases)


def parse_attribute_spec_text(spec_text: str) -> list[dict[str, Any]]:
    lines = [line.strip() for line in str(spec_text).splitlines() if line.strip()]
    if not lines:
        return []

    tasks: list[dict[str, Any]] = []
    used_task_slugs: set[str] = set()
    for task_index, line in enumerate(lines, start=1):
        raw_task_name, raw_values = _split_task_line(line)
        display_name, explicit_task_slug = _split_name_and_slug(raw_task_name)
        if not display_name:
            raise ValueError(f"属性名不能为空: {line}")

        task_slug = explicit_task_slug or _suggest_task_slug(display_name, task_index)
        if task_slug in used_task_slugs:
            raise ValueError(f"属性 slug 重复: {task_slug}")
        used_task_slugs.add(task_slug)

        value_items = [item.strip() for item in ATTRIBUTE_VALUE_SPLIT_PATTERN.split(raw_values) if item.strip()]
        if not value_items:
            raise ValueError(f"属性 {display_name} 至少要有一个可选值")

        classes: list[dict[str, Any]] = []
        used_class_slugs: set[str] = set()
        for class_index, raw_value in enumerate(value_items, start=1):
            value_display, explicit_class_slug = _split_name_and_slug(raw_value)
            if not value_display:
                raise ValueError(f"属性 {display_name} 存在空值")

            class_slug = explicit_class_slug or _suggest_class_slug(task_slug, value_display, class_index)
            if class_slug in used_class_slugs:
                raise ValueError(f"属性 {display_name} 的值 slug 重复: {class_slug}")
            used_class_slugs.add(class_slug)

            classes.append(
                {
                    "display_name": value_display,
                    "slug": class_slug,
                    "aliases": _build_class_aliases(task_slug, value_display, class_slug),
                }
            )

        tasks.append(
            {
                "display_name": display_name,
                "slug": task_slug,
                "aliases": _build_task_aliases(display_name, task_slug),
                "classes": classes,
            }
        )

    return tasks


def _relative_paths() -> dict[str, str]:
    return {
        "configs_root": "configs",
        "detection_root": "datasets/detection",
        "detection_raw_images": "datasets/detection/raw/images",
        "detection_raw_labels": "datasets/detection/raw/labels",
        "attribute_root": "datasets/attribute_cls",
        "smoke_root": "datasets/smoke_tests",
        "models_root": "models/detector",
        "outputs_root": "outputs",
        "outputs_label_check": "outputs/label_check",
        "outputs_train": "outputs/train",
        "outputs_train_attr": "outputs/train_attr",
        "outputs_benchmark": "outputs/benchmark_preview",
        "outputs_model_packages": "outputs/model_packages",
        "scripts_root": "scripts",
    }


def build_project_meta(
    project_name: str,
    detection_label: str,
    attribute_spec_text: str,
    tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    project_slug = slugify_identifier(project_name, "project")
    detection_run_name = build_detection_run_name(project_name)
    return {
        "schema_version": 1,
        "project_name": project_name,
        "project_slug": project_slug,
        "detection_label": detection_label,
        "detection_run_name": detection_run_name,
        "attribute_spec_text": attribute_spec_text.strip(),
        "attribute_tasks": tasks,
        "review_classifier": build_default_review_classifier_config(),
        "paths": _relative_paths(),
    }


def _render_task_summary_lines(project_meta: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for task in project_meta["attribute_tasks"]:
        value_text = ", ".join(
            f"{class_info['display_name']} ({class_info['slug']})" for class_info in task["classes"]
        )
        lines.append(f"- {task['display_name']} ({task['slug']}): {value_text}")
    if not lines:
        lines.append("- 当前未定义属性任务，运行时只使用检测模型和可选候选框复检模型")
    return lines


def _get_export_script_name(project_meta: dict[str, Any]) -> str:
    return f"{5 + len(project_meta['attribute_tasks']) * 2:02d}_export_onnx.cmd"


def _get_benchmark_script_name(project_meta: dict[str, Any]) -> str:
    return f"{6 + len(project_meta['attribute_tasks']) * 2:02d}_benchmark.cmd"


def _build_project_readme(project_meta: dict[str, Any]) -> str:
    task_lines = _render_task_summary_lines(project_meta)
    project_name = project_meta["project_name"]
    detection_label = project_meta["detection_label"]
    run_name = project_meta["detection_run_name"]
    export_script_name = _get_export_script_name(project_meta)
    benchmark_script_name = _get_benchmark_script_name(project_meta)
    review_config = get_review_classifier_config(project_meta, default_if_missing=True)
    assert review_config is not None
    review_task_slug = str(review_config["task_slug"])
    positive_class = dict(review_config["positive_class"])
    negative_class = dict(review_config["negative_class"])
    return "\n".join(
        [
            f"# {project_name} AI 训练项目",
            "",
            "这个目录是独立的 AI 训练项目根目录，当前项目需要的目录、配置和命令入口都放在这里。",
            "",
            "## 当前项目配置",
            "",
            f"- 检测标签: {detection_label}",
            f"- 检测训练名: {run_name}",
            "当前属性任务：",
            *task_lines,
            "",
            "可选候选框复检模型：",
            f"- 默认 task_slug: {review_task_slug}",
            f"- 样本类别: {positive_class['display_name']} ({positive_class['slug']}) / {negative_class['display_name']} ({negative_class['slug']})",
            f"- 训练完成后可把权重放到 outputs/train_attr/{review_task_slug}_yolov8n_cls/weights/best.pt",
            "- 也可以在 project_meta.json 的 review_classifier.weights 里手动指定路径",
            "- 若要发给其他人用，建议再导出一个自包含模型包，里面会同时带上 onnx、project_meta 和属性/复检 best.pt",
            "- 对方在主程序里优先选择模型包根目录下的 model_package.gaimodel.json；旧版主程序也可以直接选包内 models/detector/*.onnx",
            "",
            "## 目录说明",
            "",
            "- configs: 类别、属性和导出元数据模板",
            "- datasets/detection: 检测数据集",
            "- datasets/attribute_cls: 属性分类数据集",
            "- models/detector: 导出的 ONNX 模型",
            "- outputs: 抽检、训练、基准测试输出",
            "- scripts: 项目专用的一键命令入口",
            "",
            "## 建议流程",
            "",
            "1. 把截图放进 datasets/detection/raw/images",
            "2. 用 AnyLabeling 加载 configs/label_classes.txt 和 configs/attributes.json",
            "3. 标注 JSON 保存到 datasets/detection/raw/labels",
            "4. 运行 scripts/01_sync_annotations.cmd",
            "5. 运行 scripts/02_check_labels.cmd",
            "6. 运行 scripts/03_split_detection.cmd",
            "7. 分别运行 scripts/05_split_attr_<task>.cmd 和 scripts/06_train_attr_<task>.cmd",
            "8. 运行 scripts/04_train_detection.cmd",
            f"9. 运行 scripts/{export_script_name}",
            f"10. 运行 scripts/{benchmark_script_name}",
            f"11. 如果要启用候选框复检，额外训练一个 {review_task_slug} 二分类模型并放到 outputs/train_attr 下",
            "",
            "## AnyLabeling 使用要点",
            "",
            "- 标签文件: configs/label_classes.txt",
            "- 属性文件: configs/attributes.json",
            "- 原图目录: datasets/detection/raw/images",
            "- JSON 输出目录: datasets/detection/raw/labels",
            "",
            "如果属性面板异常，也可以把属性写进 description，例如：",
            "",
            "- 等级=5级 类型=木材 关系=中立",
            "",
            "通用同步脚本会优先读 attributes，缺失时回退解析 description。",
            "",
            "## 环境说明",
            "",
            "项目脚本默认调用 python 命令。建议先激活和 ai_tile_mvp 一致的虚拟环境，再运行这些 cmd 文件。",
            "",
        ]
    )


def _build_project_checklist(project_meta: dict[str, Any]) -> str:
    task_lines = _render_task_summary_lines(project_meta)
    detection_label = project_meta["detection_label"]
    return "\n".join(
        [
            "# 标注清单",
            "",
            "这份清单对应当前项目的独立标注流程。",
            "",
            "## 1. 检测类",
            "",
            f"- 只标 1 个检测类: {detection_label}",
            "- 框里要包含完整菱形主体，不要只框数字",
            "",
            "## 2. 当前属性定义",
            "",
            *task_lines,
            "",
            "## 3. 困难负样本",
            "",
            "- 不要给树林、乱石、道路纹理这类假目标单独画负类框",
            "- 正确做法是保留整张图，只标真地块；如果整张图都没有目标，也保存空 JSON",
            "- 这些图在同步后会生成空 txt 或只含真地块的 txt，可直接作为困难负样本参与训练",
            "",
            "## 4. 固定路径",
            "",
            "- 原图目录: datasets/detection/raw/images",
            "- JSON 标签目录: datasets/detection/raw/labels",
            "- 类别文件: configs/label_classes.txt",
            "- 属性文件: configs/attributes.json",
            "",
            "## 5. 标完后怎么做",
            "",
            "1. 运行 scripts/01_sync_annotations.cmd 生成检测 txt 和属性裁剪集",
            "2. 运行 scripts/02_check_labels.cmd 抽检检测框",
            "3. 运行 scripts/03_split_detection.cmd 做检测切分",
            "4. 运行属性切分和属性训练脚本",
            "5. 最后跑检测训练、导出和基准测试",
            "6. 如果要分发给别人运行主程序，再执行 scripts/export_model_package.cmd",
            "",
        ]
    )


def _build_attributes_json(project_meta: dict[str, Any]) -> dict[str, Any]:
    detection_label = project_meta["detection_label"]
    attributes = {
        task["display_name"]: [class_info["display_name"] for class_info in task["classes"]]
        for task in project_meta["attribute_tasks"]
    }
    widget_types = {
        task["display_name"]: "radiobutton" for task in project_meta["attribute_tasks"]
    }
    return {
        detection_label: attributes,
        "__widget_types__": {
            detection_label: widget_types,
        },
    }


def _build_model_meta(project_meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "input_size": 640,
        "conf_threshold": 0.35,
        "iou_threshold": 0.50,
        "max_detections": 300,
        "class_names": [project_meta["detection_label"]],
        "letterbox": True,
        "normalize": True,
        "version": f"{project_meta['project_slug']}-template",
    }


def _build_detection_data_yaml(project_meta: dict[str, Any]) -> str:
    return "\n".join(
        [
            "path: .",
            "train: images/train",
            "val: images/val",
            "test: images/test",
            "names:",
            f"  0: {project_meta['detection_label']}",
            "",
        ]
    )


def _build_detection_readme(project_meta: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# detection 说明",
            "",
            "这个目录用于当前项目的检测数据集。",
            "",
            "- raw/images: 原始截图",
            "- raw/labels: AnyLabeling JSON 和同步后的 YOLO txt",
            "- images/train|val|test: 切分后的检测图片",
            "- labels/train|val|test: 切分后的检测标签",
            "- data.yaml: 检测训练配置",
            "",
            f"当前检测类别只有 1 个: {project_meta['detection_label']}",
            "",
        ]
    )


def _build_attribute_readme(project_meta: dict[str, Any]) -> str:
    review_config = get_review_classifier_config(project_meta, default_if_missing=True)
    assert review_config is not None
    review_task_slug = str(review_config["task_slug"])
    positive_class = dict(review_config["positive_class"])
    negative_class = dict(review_config["negative_class"])
    lines = [
        "# attribute_cls 说明",
        "",
        "这个目录存放当前项目的属性分类数据集。",
        "",
        "每个属性任务目录结构如下：",
        "",
        "- raw: 从标注框裁剪出来的原始小图",
        "- train: 训练集",
        "- val: 验证集",
        "- test: 测试集",
        "- classes.txt: 当前任务类别列表",
        "",
        "当前任务定义：",
        "",
    ]
    lines.extend(_render_task_summary_lines(project_meta))
    lines.extend(
        [
            "",
            "可选候选框复检任务：",
            "",
            f"- {review_task_slug}/raw/{positive_class['slug']}: {positive_class['display_name']}裁剪图",
            f"- {review_task_slug}/raw/{negative_class['slug']}: {negative_class['display_name']}裁剪图",
        ]
    )
    lines.append("")
    return "\n".join(lines)


def _build_command_wrapper(command: str) -> str:
    return "\n".join(
        [
            "@echo off",
            "setlocal",
            "set PROJECT_ROOT=%~dp0..",
            "set AI_ROOT=%PROJECT_ROOT%\\..\\..",
            "",
            command,
            "set EXIT_CODE=%ERRORLEVEL%",
            "echo.",
            "if not \"%EXIT_CODE%\"==\"0\" (",
            "  echo 命令执行失败，退出码 %EXIT_CODE%。",
            ") else (",
            "  echo 命令执行完成。",
            ")",
            "pause",
            "exit /b %EXIT_CODE%",
            "",
        ]
    )


def _build_wrapper_files(project_meta: dict[str, Any]) -> dict[str, str]:
    run_name = project_meta["detection_run_name"]
    wrapper_files = {
        "scripts/00_open_project.cmd": "@echo off\r\nstart \"\" \"%~dp0..\"\r\n",
        "scripts/01_sync_annotations.cmd": _build_command_wrapper(
            'python "%AI_ROOT%\\scripts\\sync_project_annotations.py" --project-config "%PROJECT_ROOT%\\project_meta.json" --clear-attr-raw'
        ),
        "scripts/02_check_labels.cmd": _build_command_wrapper(
            'python "%AI_ROOT%\\scripts\\check_yolo_labels.py" --image-dir "%PROJECT_ROOT%\\datasets\\detection\\raw\\images" --label-dir "%PROJECT_ROOT%\\datasets\\detection\\raw\\labels" --output-dir "%PROJECT_ROOT%\\outputs\\label_check" --sample-count 40'
        ),
        "scripts/03_split_detection.cmd": _build_command_wrapper(
            'python "%AI_ROOT%\\scripts\\split_yolo_dataset.py" --source-images "%PROJECT_ROOT%\\datasets\\detection\\raw\\images" --source-labels "%PROJECT_ROOT%\\datasets\\detection\\raw\\labels" --output-root "%PROJECT_ROOT%\\datasets\\detection" --clear-output'
        ),
        "scripts/04_train_detection.cmd": _build_command_wrapper(
            f'python "%AI_ROOT%\\scripts\\train_yolo_tile.py" --data "%PROJECT_ROOT%\\datasets\\detection\\data.yaml" --model yolov8n.pt --epochs 120 --imgsz 640 --project "%PROJECT_ROOT%\\outputs\\train" --name "{run_name}"'
        ),
    }

    for task_index, task in enumerate(project_meta["attribute_tasks"], start=1):
        task_slug = task["slug"]
        split_index = 5 + (task_index - 1) * 2
        train_index = split_index + 1
        wrapper_files[f"scripts/{split_index:02d}_split_attr_{task_slug}.cmd"] = _build_command_wrapper(
            f'python "%AI_ROOT%\\scripts\\split_attribute_classification_dataset.py" --source-raw-root "%PROJECT_ROOT%\\datasets\\attribute_cls\\{task_slug}\\raw" --output-root "%PROJECT_ROOT%\\datasets\\attribute_cls\\{task_slug}" --clear-output'
        )
        wrapper_files[f"scripts/{train_index:02d}_train_attr_{task_slug}.cmd"] = _build_command_wrapper(
            f'python "%AI_ROOT%\\scripts\\train_yolo_attribute_cls.py" --data-root "%PROJECT_ROOT%\\datasets\\attribute_cls\\{task_slug}" --model yolov8n-cls.pt --epochs 80 --imgsz 224 --project "%PROJECT_ROOT%\\outputs\\train_attr" --name "{task_slug}_yolov8n_cls"'
        )

    export_script_name = _get_export_script_name(project_meta)
    benchmark_script_name = _get_benchmark_script_name(project_meta)
    wrapper_files[f"scripts/{export_script_name}"] = _build_command_wrapper(
        f'python "%AI_ROOT%\\scripts\\export_yolo_onnx.py" --weights "%PROJECT_ROOT%\\outputs\\train\\{run_name}\\weights\\best.pt" --output "%PROJECT_ROOT%\\models\\detector\\{run_name}_640.onnx" --meta-template "%PROJECT_ROOT%\\configs\\model_meta.template.json"'
    )
    wrapper_files["scripts/export_model_package.cmd"] = _build_command_wrapper(
        f'python "%AI_ROOT%\\scripts\\export_model_package.py" --project-config "%PROJECT_ROOT%\\project_meta.json" --detector-model "%PROJECT_ROOT%\\models\\detector\\{run_name}_640.onnx" --output-dir "%PROJECT_ROOT%\\outputs\\model_packages\\{project_meta["project_slug"]}_model_bundle" --zip --overwrite'
    )
    wrapper_files[f"scripts/{benchmark_script_name}"] = _build_command_wrapper(
        f'python "%AI_ROOT%\\scripts\\benchmark_onnx_tile.py" --model "%PROJECT_ROOT%\\models\\detector\\{run_name}_640.onnx" --image-dir "%PROJECT_ROOT%\\datasets\\detection\\images\\test" --label-dir "%PROJECT_ROOT%\\datasets\\detection\\labels\\test" --output-dir "%PROJECT_ROOT%\\outputs\\benchmark_preview"'
    )

    return wrapper_files


def _expected_generated_relative_paths(project_meta: dict[str, Any]) -> list[str]:
    review_config = get_review_classifier_config(project_meta, default_if_missing=True)
    assert review_config is not None
    relative_paths = [
        "project_meta.json",
        "README.md",
        "标注清单.md",
        "configs/label_classes.txt",
        "configs/attributes.json",
        "configs/model_meta.template.json",
        "datasets/detection/data.yaml",
        "datasets/detection/README.md",
        "datasets/attribute_cls/README.md",
    ]
    for task in project_meta["attribute_tasks"]:
        relative_paths.append(f"datasets/attribute_cls/{task['slug']}/classes.txt")
    relative_paths.append(f"datasets/attribute_cls/{review_config['task_slug']}/classes.txt")
    relative_paths.extend(_build_wrapper_files(project_meta).keys())
    return relative_paths


def _ensure_directories(project_root: Path, project_meta: dict[str, Any]) -> list[Path]:
    review_config = get_review_classifier_config(project_meta, default_if_missing=True)
    assert review_config is not None
    review_task_slug = str(review_config["task_slug"])
    positive_slug = str(review_config["positive_class_slug"])
    negative_slug = str(review_config["negative_class_slug"])
    directories = [
        project_root,
        project_root / "configs",
        project_root / "datasets" / "detection" / "raw" / "images",
        project_root / "datasets" / "detection" / "raw" / "labels",
        project_root / "datasets" / "detection" / "images" / "train",
        project_root / "datasets" / "detection" / "images" / "val",
        project_root / "datasets" / "detection" / "images" / "test",
        project_root / "datasets" / "detection" / "labels" / "train",
        project_root / "datasets" / "detection" / "labels" / "val",
        project_root / "datasets" / "detection" / "labels" / "test",
        project_root / "datasets" / "attribute_cls",
        project_root / "datasets" / "attribute_cls" / review_task_slug,
        project_root / "datasets" / "attribute_cls" / review_task_slug / "raw",
        project_root / "datasets" / "attribute_cls" / review_task_slug / "raw" / positive_slug,
        project_root / "datasets" / "attribute_cls" / review_task_slug / "raw" / negative_slug,
        project_root / "datasets" / "attribute_cls" / review_task_slug / "train",
        project_root / "datasets" / "attribute_cls" / review_task_slug / "val",
        project_root / "datasets" / "attribute_cls" / review_task_slug / "test",
        project_root / "datasets" / "smoke_tests",
        project_root / "models" / "detector",
        project_root / "outputs",
        project_root / "outputs" / "label_check",
        project_root / "outputs" / "train",
        project_root / "outputs" / "train_attr",
        project_root / "outputs" / "benchmark_preview",
        project_root / "outputs" / "model_packages",
        project_root / "scripts",
    ]

    for task in project_meta["attribute_tasks"]:
        task_root = project_root / "datasets" / "attribute_cls" / task["slug"]
        directories.extend(
            [
                task_root,
                task_root / "raw",
                task_root / "train",
                task_root / "val",
                task_root / "test",
            ]
        )
        for class_info in task["classes"]:
            directories.append(task_root / "raw" / class_info["slug"])

    created: list[Path] = []
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        created.append(directory)
    return created


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_json(path: Path, content: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file_obj:
        json.dump(content, file_obj, ensure_ascii=False, indent=2)
    return path


def _write_project_files(project_root: Path, project_meta: dict[str, Any]) -> list[Path]:
    review_config = get_review_classifier_config(project_meta, default_if_missing=True)
    assert review_config is not None
    written_files: list[Path] = []
    written_files.append(_write_json(project_root / "project_meta.json", project_meta))
    written_files.append(_write_text(project_root / "README.md", _build_project_readme(project_meta)))
    written_files.append(_write_text(project_root / "标注清单.md", _build_project_checklist(project_meta)))
    written_files.append(_write_text(project_root / "configs" / "label_classes.txt", f"{project_meta['detection_label']}\n"))
    written_files.append(_write_json(project_root / "configs" / "attributes.json", _build_attributes_json(project_meta)))
    written_files.append(_write_json(project_root / "configs" / "model_meta.template.json", _build_model_meta(project_meta)))
    written_files.append(_write_text(project_root / "datasets" / "detection" / "data.yaml", _build_detection_data_yaml(project_meta)))
    written_files.append(_write_text(project_root / "datasets" / "detection" / "README.md", _build_detection_readme(project_meta)))
    written_files.append(_write_text(project_root / "datasets" / "attribute_cls" / "README.md", _build_attribute_readme(project_meta)))

    for task in project_meta["attribute_tasks"]:
        classes_text = "\n".join(class_info["slug"] for class_info in task["classes"]) + "\n"
        written_files.append(_write_text(project_root / "datasets" / "attribute_cls" / task["slug"] / "classes.txt", classes_text))

    written_files.append(
        _write_text(
            project_root / "datasets" / "attribute_cls" / str(review_config["task_slug"]) / "classes.txt",
            "\n".join(
                [
                    str(review_config["positive_class_slug"]),
                    str(review_config["negative_class_slug"]),
                ]
            ) + "\n",
        )
    )

    for relative_path, content in _build_wrapper_files(project_meta).items():
        written_files.append(_write_text(project_root / relative_path, content))

    return written_files


def _cleanup_stale_generated_files(project_root: Path, old_project_meta: dict[str, Any], new_project_meta: dict[str, Any]) -> None:
    old_paths = set(_expected_generated_relative_paths(old_project_meta))
    new_paths = set(_expected_generated_relative_paths(new_project_meta))
    stale_paths = sorted(old_paths - new_paths)
    for relative_path in stale_paths:
        target_path = project_root / relative_path
        if target_path.is_file():
            target_path.unlink()

    scripts_root = project_root / "scripts"
    if scripts_root.exists():
        for script_path in scripts_root.glob("*.cmd"):
            if re.match(r"^\d{2}_.+\.cmd$", script_path.name):
                script_path.unlink()


def create_project_scaffold(
    base_dir: Path | str,
    project_name: str,
    detection_label: str,
    attribute_spec_text: str,
    allow_overwrite: bool = False,
) -> dict[str, Any]:
    validated_project_name = validate_project_name(project_name)
    base_path = Path(base_dir).resolve()
    base_path.mkdir(parents=True, exist_ok=True)
    project_root = base_path / validated_project_name

    if project_root.exists() and not allow_overwrite and any(project_root.iterdir()):
        raise FileExistsError(f"项目目录已存在且非空: {project_root}")

    resolved_detection_label = str(detection_label).strip() or build_default_detection_label(validated_project_name)
    tasks = parse_attribute_spec_text(attribute_spec_text)
    project_meta = build_project_meta(validated_project_name, resolved_detection_label, attribute_spec_text, tasks)

    old_project_meta: dict[str, Any] | None = None
    old_meta_path = project_root / "project_meta.json"
    if allow_overwrite and old_meta_path.exists():
        try:
            old_project_meta = load_project_meta(old_meta_path)
        except Exception:
            old_project_meta = None

    created_dirs = _ensure_directories(project_root, project_meta)
    if old_project_meta is not None:
        _cleanup_stale_generated_files(project_root, old_project_meta, project_meta)
    written_files = _write_project_files(project_root, project_meta)
    return {
        "project_root": project_root,
        "project_meta": project_meta,
        "created_dirs": created_dirs,
        "written_files": written_files,
    }


def load_project_meta(config_path: Path | str) -> dict[str, Any]:
    with open(Path(config_path), "r", encoding="utf-8") as file_obj:
        return json.load(file_obj)