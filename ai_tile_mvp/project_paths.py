"""AI 目标项目默认值与路径辅助。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .project_scaffold import (
    DEFAULT_PROJECTS_ROOT,
    DEFAULT_REVIEW_TASK_SLUG,
    get_review_classifier_config,
    load_project_meta,
)


AI_ROOT = Path(__file__).resolve().parent
DETECTION_DATA_ROOT = AI_ROOT / "datasets" / "plot_det"
DETECTION_RAW_IMAGE_DIR = DETECTION_DATA_ROOT / "raw" / "images"
DETECTION_RAW_LABEL_DIR = DETECTION_DATA_ROOT / "raw" / "labels"
DETECTION_MODEL_ROOT = AI_ROOT / "models" / "tile_detector"
ATTRIBUTE_DATA_ROOT = AI_ROOT / "datasets" / "plot_attr_cls"
SMOKE_TESTS_ROOT = AI_ROOT / "datasets" / "smoke_tests"
DEFAULT_DETECTION_LABEL_NAME = "plot_node"
DEFAULT_LABELS_FILE = AI_ROOT / "configs" / "plot_label_classes.txt"
DEFAULT_ATTRIBUTES_FILE = AI_ROOT / "configs" / "plot_node_attributes.json"
DEFAULT_META_TEMPLATE_FILE = AI_ROOT / "configs" / "plot_model_meta.template.json"
DEFAULT_CHECKLIST_FILE = AI_ROOT / "地块识别标注清单.md"
PROJECT_META_FILENAME = "project_meta.json"
PROJECT_CHECKLIST_FILENAME = "标注清单.md"
ATTRIBUTE_TASK_OPTIONS = [
    ("level", "等级"),
    ("resource_type", "类型"),
    ("relation", "关系"),
]
ATTRIBUTE_TASK_LABELS = dict(ATTRIBUTE_TASK_OPTIONS)
LEVEL_OPTIONS = [
    ("lv04", "4级"),
    ("lv05", "5级"),
    ("lv06", "6级"),
    ("lv07", "7级"),
    ("lv08", "8级"),
    ("lv09", "9级"),
    ("lv10", "10级"),
]
RESOURCE_TYPE_OPTIONS = [
    ("wood", "木材"),
    ("stone", "石头"),
    ("iron", "铁矿"),
    ("copper", "铜矿"),
    ("food", "粮食"),
]
RELATION_OPTIONS = [
    ("ally", "同盟"),
    ("friendly", "友盟"),
    ("neutral", "中立"),
    ("enemy", "敌对"),
    ("self", "我方"),
]
DEFAULT_SMOKE_LEVEL = "lv05"
DEFAULT_SMOKE_RESOURCE_TYPE = "wood"
DEFAULT_SMOKE_RELATION = "neutral"
FULL_DETECTION_RUN_NAME = "plot_node_det_yolov8n"
REVIEW_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def build_default_ui_attribute_tasks() -> list[dict[str, Any]]:
    return [
        {
            "display_name": "等级",
            "slug": "level",
            "classes": [
                {"display_name": label, "slug": value} for value, label in LEVEL_OPTIONS
            ],
        },
        {
            "display_name": "类型",
            "slug": "resource_type",
            "classes": [
                {"display_name": label, "slug": value} for value, label in RESOURCE_TYPE_OPTIONS
            ],
        },
        {
            "display_name": "关系",
            "slug": "relation",
            "classes": [
                {"display_name": label, "slug": value} for value, label in RELATION_OPTIONS
            ],
        },
    ]


def discover_project_config_paths() -> list[Path]:
    if not DEFAULT_PROJECTS_ROOT.exists():
        return []
    configs: list[Path] = []
    for directory in sorted(path for path in DEFAULT_PROJECTS_ROOT.iterdir() if path.is_dir()):
        config_path = directory / PROJECT_META_FILENAME
        if config_path.exists():
            configs.append(config_path.resolve())
    return configs


def build_project_info(config_path: Path) -> dict[str, Any]:
    resolved_path = config_path.resolve()
    return {
        "config_path": resolved_path,
        "root": resolved_path.parent,
        "meta": load_project_meta(resolved_path),
    }


def get_project_meta(project_info: dict[str, Any] | None) -> dict[str, Any] | None:
    if not project_info:
        return None
    meta = project_info.get("meta")
    return meta if isinstance(meta, dict) else None


def get_project_root(project_info: dict[str, Any] | None) -> Path | None:
    if not project_info:
        return None
    root = project_info.get("root")
    return Path(root) if root else None


def _get_project_meta_mapping(project_info: dict[str, Any] | None) -> dict[str, Any]:
    meta = get_project_meta(project_info)
    return meta if isinstance(meta, dict) else {}


def _get_project_path_mapping(project_info: dict[str, Any] | None) -> dict[str, Any]:
    paths = _get_project_meta_mapping(project_info).get("paths")
    return paths if isinstance(paths, dict) else {}


def _get_project_text_value(project_info: dict[str, Any] | None, key: str, default: str) -> str:
    value = _get_project_meta_mapping(project_info).get(key, default)
    text = str(value or "").strip()
    return text or default


def _resolve_project_relative_path(project_root: Path | None, relative_path: str) -> Path | None:
    if project_root is None:
        return None
    relative_text = str(relative_path or "").strip()
    if not relative_text:
        return None
    return (project_root / relative_text).resolve()


def get_project_path_by_key(
    project_info: dict[str, Any] | None,
    key: str,
    default_path: Path,
    project_default_relative_path: str = "",
) -> Path:
    project_root = get_project_root(project_info)
    relative_path = str(_get_project_path_mapping(project_info).get(key) or project_default_relative_path).strip()
    resolved = _resolve_project_relative_path(project_root, relative_path)
    return resolved if resolved is not None else default_path


def get_project_file(project_info: dict[str, Any] | None, relative_path: str, default_path: Path) -> Path:
    resolved = _resolve_project_relative_path(get_project_root(project_info), relative_path)
    return resolved if resolved is not None else default_path


def build_project_detector_output_path(project_root: Path | None, run_name: str, suffix: str, default_path: Path) -> Path:
    if project_root is None:
        return default_path
    return (project_root / "models" / "detector" / f"{run_name}_640.{suffix}").resolve()


def _get_project_detector_output_file(project_info: dict[str, Any] | None, suffix: str, default_path: Path) -> Path:
    return build_project_detector_output_path(
        get_project_root(project_info),
        get_project_detection_run_name(project_info),
        suffix,
        default_path,
    )


def get_project_detection_label(project_info: dict[str, Any] | None) -> str:
    return _get_project_text_value(project_info, "detection_label", DEFAULT_DETECTION_LABEL_NAME)


def build_detection_label_aliases(detection_label: str) -> list[str]:
    aliases: list[str] = []
    for item in [detection_label, DEFAULT_DETECTION_LABEL_NAME]:
        text = str(item).strip()
        if text and text not in aliases:
            aliases.append(text)
    return aliases


def get_project_detection_label_aliases(project_info: dict[str, Any] | None) -> list[str]:
    return build_detection_label_aliases(get_project_detection_label(project_info))


def get_project_detection_run_name(project_info: dict[str, Any] | None) -> str:
    return _get_project_text_value(project_info, "detection_run_name", FULL_DETECTION_RUN_NAME)


def get_project_attribute_tasks(project_info: dict[str, Any] | None) -> list[dict[str, Any]]:
    tasks = _get_project_meta_mapping(project_info).get("attribute_tasks") or []
    if isinstance(tasks, list) and tasks:
        return tasks
    return build_default_ui_attribute_tasks()


def get_project_review_classifier_task(project_info: dict[str, Any] | None) -> dict[str, Any] | None:
    project_meta = get_project_meta(project_info)
    review_config = get_review_classifier_config(project_meta, default_if_missing=project_meta is None)
    if review_config is None:
        return None

    return {
        "display_name": str(review_config["display_name"]),
        "slug": str(review_config["task_slug"]),
        "classes": [
            dict(review_config["positive_class"]),
            dict(review_config["negative_class"]),
        ],
    }


def get_project_review_classes(project_info: dict[str, Any] | None) -> list[dict[str, Any]]:
    review_task = get_project_review_classifier_task(project_info)
    if review_task is None:
        return []
    classes = review_task.get("classes") or []
    return [dict(class_info) for class_info in classes if isinstance(class_info, dict)]


def get_project_review_class_by_role(project_info: dict[str, Any] | None, role: str) -> dict[str, Any]:
    fallback = {
        "positive": {"role": "positive", "display_name": "正确样本", "slug": "positive", "aliases": []},
        "negative": {"role": "negative", "display_name": "错误样本", "slug": "negative", "aliases": []},
    }
    classes = get_project_review_classes(project_info)
    for class_info in classes:
        if str(class_info.get("role") or "").strip() == role:
            return class_info
    if role == "positive" and classes:
        return classes[0]
    if role == "negative" and len(classes) > 1:
        return classes[1]
    return dict(fallback.get(role, {"role": role, "display_name": role, "slug": role, "aliases": []}))


def get_project_review_positive_class(project_info: dict[str, Any] | None) -> dict[str, Any]:
    return get_project_review_class_by_role(project_info, "positive")


def get_project_review_negative_class(project_info: dict[str, Any] | None) -> dict[str, Any]:
    return get_project_review_class_by_role(project_info, "negative")


def get_project_trainable_classifier_tasks(project_info: dict[str, Any] | None) -> list[dict[str, Any]]:
    tasks = [dict(task) for task in get_project_attribute_tasks(project_info)]
    review_task = get_project_review_classifier_task(project_info)
    if review_task is not None:
        review_slug = str(review_task.get("slug") or "").strip()
        if review_slug and all(str(task.get("slug") or "").strip() != review_slug for task in tasks):
            tasks.append(review_task)
    return tasks


def get_project_review_task_slug(project_info: dict[str, Any] | None) -> str:
    review_task = get_project_review_classifier_task(project_info)
    if review_task is not None:
        task_slug = str(review_task.get("slug") or "").strip()
        if task_slug:
            return task_slug
    return DEFAULT_REVIEW_TASK_SLUG


def get_project_detection_root(project_info: dict[str, Any] | None) -> Path:
    return get_project_path_by_key(project_info, "detection_root", DETECTION_DATA_ROOT)


def get_project_detection_unconfirmed_root(project_info: dict[str, Any] | None) -> Path:
    return get_project_detection_root(project_info) / "excluded" / "unconfirmed_raw"


def get_project_smoke_root_dir(project_info: dict[str, Any] | None) -> Path:
    return get_project_path_by_key(project_info, "smoke_root", SMOKE_TESTS_ROOT, "datasets/smoke_tests")


def get_project_default_smoke_target_values(project_info: dict[str, Any] | None) -> dict[str, str]:
    defaults = {
        "level": DEFAULT_SMOKE_LEVEL,
        "resource_type": DEFAULT_SMOKE_RESOURCE_TYPE,
        "relation": DEFAULT_SMOKE_RELATION,
    }
    target_values: dict[str, str] = {}
    for task in get_project_attribute_tasks(project_info):
        task_slug = str(task.get("slug") or "")
        classes = task.get("classes") or []
        if not task_slug or not classes:
            continue
        preferred_slug = defaults.get(task_slug)
        selected_slug = ""
        if preferred_slug:
            for class_info in classes:
                class_slug = str(class_info.get("slug") or "")
                if class_slug == preferred_slug:
                    selected_slug = class_slug
                    break
        if not selected_slug:
            selected_slug = str(classes[0].get("slug") or "")
        if selected_slug:
            target_values[task_slug] = selected_slug
    return target_values


def build_project_smoke_target_slug(project_info: dict[str, Any] | None, target_values: dict[str, str]) -> str:
    ordered_values: list[str] = []
    for task in get_project_attribute_tasks(project_info):
        task_slug = str(task.get("slug") or "")
        value = target_values.get(task_slug)
        if value:
            ordered_values.append(value)
    return "_".join(ordered_values) if ordered_values else "all_boxes"


def get_project_smoke_test_root(project_info: dict[str, Any] | None, target_values: dict[str, str] | None = None) -> Path:
    resolved_target_values = target_values or get_project_default_smoke_target_values(project_info)
    return get_project_smoke_root_dir(project_info) / build_project_smoke_target_slug(project_info, resolved_target_values)


def get_project_smoke_detection_run_name(project_info: dict[str, Any] | None, target_values: dict[str, str] | None = None) -> str:
    slug = build_project_smoke_target_slug(project_info, target_values or get_project_default_smoke_target_values(project_info))
    return f"smoke_{slug}_yolov8n"


def get_project_detection_raw_images_dir(project_info: dict[str, Any] | None) -> Path:
    return get_project_path_by_key(project_info, "detection_raw_images", DETECTION_RAW_IMAGE_DIR)


def get_project_detection_raw_labels_dir(project_info: dict[str, Any] | None) -> Path:
    return get_project_path_by_key(project_info, "detection_raw_labels", DETECTION_RAW_LABEL_DIR)


def get_project_attribute_root(project_info: dict[str, Any] | None) -> Path:
    return get_project_path_by_key(project_info, "attribute_root", ATTRIBUTE_DATA_ROOT)


def get_project_outputs_label_check_dir(project_info: dict[str, Any] | None) -> Path:
    return get_project_path_by_key(project_info, "outputs_label_check", AI_ROOT / "outputs" / "label_check")


def get_project_outputs_train_dir(project_info: dict[str, Any] | None) -> Path:
    return get_project_path_by_key(project_info, "outputs_train", AI_ROOT / "outputs" / "train")


def get_project_outputs_train_attr_dir(project_info: dict[str, Any] | None) -> Path:
    return get_project_path_by_key(project_info, "outputs_train_attr", AI_ROOT / "outputs" / "train_attr")


def get_project_outputs_benchmark_dir(project_info: dict[str, Any] | None) -> Path:
    return get_project_path_by_key(project_info, "outputs_benchmark", AI_ROOT / "outputs" / "benchmark_preview")


def get_project_outputs_model_packages_dir(project_info: dict[str, Any] | None) -> Path:
    fallback_root = AI_ROOT / "outputs" / "model_packages"
    return get_project_path_by_key(project_info, "outputs_model_packages", fallback_root)


def get_project_label_classes_file(project_info: dict[str, Any] | None) -> Path:
    return get_project_file(project_info, "configs/label_classes.txt", DEFAULT_LABELS_FILE)


def get_project_attributes_file(project_info: dict[str, Any] | None) -> Path:
    return get_project_file(project_info, "configs/attributes.json", DEFAULT_ATTRIBUTES_FILE)


def get_project_model_meta_template(project_info: dict[str, Any] | None) -> Path:
    return get_project_file(project_info, "configs/model_meta.template.json", DEFAULT_META_TEMPLATE_FILE)


def get_project_checklist_file(project_info: dict[str, Any] | None) -> Path:
    return get_project_file(project_info, PROJECT_CHECKLIST_FILENAME, DEFAULT_CHECKLIST_FILE)


def get_project_detection_data_yaml(project_info: dict[str, Any] | None) -> Path:
    return get_project_detection_root(project_info) / "data.yaml"


def get_project_attribute_task_root(project_info: dict[str, Any] | None, task_name: str) -> Path:
    return get_project_attribute_root(project_info) / task_name


def get_project_attribute_task_raw_root(project_info: dict[str, Any] | None, task_name: str) -> Path:
    return get_project_attribute_task_root(project_info, task_name) / "raw"


def get_project_review_raw_root(project_info: dict[str, Any] | None) -> Path:
    return get_project_attribute_task_raw_root(project_info, get_project_review_task_slug(project_info))


def get_project_review_positive_dir(project_info: dict[str, Any] | None) -> Path:
    return get_project_review_raw_root(project_info) / str(get_project_review_positive_class(project_info).get("slug") or "positive")


def get_project_review_negative_dir(project_info: dict[str, Any] | None) -> Path:
    return get_project_review_raw_root(project_info) / str(get_project_review_negative_class(project_info).get("slug") or "negative")


def collect_image_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        (
            path for path in directory.rglob("*")
            if path.is_file() and path.suffix.lower() in REVIEW_IMAGE_EXTENSIONS
        ),
        key=lambda path: str(path.relative_to(directory)).lower(),
    )


def get_attribute_task_root(task_name: str) -> Path:
    return ATTRIBUTE_DATA_ROOT / task_name


def get_attribute_task_raw_root(task_name: str) -> Path:
    return get_attribute_task_root(task_name) / "raw"


def build_smoke_target_slug(level: str, resource_type: str, relation: str) -> str:
    return f"{level}_{resource_type}_{relation}"


def get_smoke_test_root(level: str, resource_type: str, relation: str) -> Path:
    return SMOKE_TESTS_ROOT / build_smoke_target_slug(level, resource_type, relation)


def get_default_smoke_root() -> Path:
    return get_smoke_test_root(DEFAULT_SMOKE_LEVEL, DEFAULT_SMOKE_RESOURCE_TYPE, DEFAULT_SMOKE_RELATION)


def get_smoke_detection_run_name(level: str, resource_type: str, relation: str) -> str:
    return f"smoke_{build_smoke_target_slug(level, resource_type, relation)}_yolov8n"


def get_default_smoke_detection_run_name() -> str:
    return get_smoke_detection_run_name(DEFAULT_SMOKE_LEVEL, DEFAULT_SMOKE_RESOURCE_TYPE, DEFAULT_SMOKE_RELATION)


def get_latest_train_run_name(prefix: str) -> str | None:
    train_root = AI_ROOT / "outputs" / "train"
    if not train_root.exists():
        return None

    candidates: list[Path] = []
    for directory in train_root.iterdir():
        if not directory.is_dir() or not directory.name.startswith(prefix):
            continue
        best_path = directory / "weights" / "best.pt"
        if best_path.exists():
            candidates.append(directory)

    if not candidates:
        return None

    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0].name


def get_latest_default_smoke_detection_run_name() -> str:
    return get_latest_train_run_name(get_default_smoke_detection_run_name()) or get_default_smoke_detection_run_name()


def get_latest_full_detection_run_name() -> str:
    return get_latest_train_run_name(FULL_DETECTION_RUN_NAME) or FULL_DETECTION_RUN_NAME


def get_full_detection_weights_path() -> Path:
    return AI_ROOT / "outputs" / "train" / get_latest_full_detection_run_name() / "weights" / "best.pt"


def get_default_smoke_weights_path() -> Path:
    return AI_ROOT / "outputs" / "train" / get_latest_default_smoke_detection_run_name() / "weights" / "best.pt"


def get_full_detection_model_path() -> Path:
    return DETECTION_MODEL_ROOT / f"{get_latest_full_detection_run_name()}_640.onnx"


def get_default_smoke_model_path() -> Path:
    return DETECTION_MODEL_ROOT / f"{get_latest_default_smoke_detection_run_name()}_640.onnx"


def get_full_detection_meta_path() -> Path:
    return DETECTION_MODEL_ROOT / f"{get_latest_full_detection_run_name()}_640.json"


def get_default_smoke_meta_path() -> Path:
    return DETECTION_MODEL_ROOT / f"{get_latest_default_smoke_detection_run_name()}_640.json"


def get_project_detection_weights_path(project_info: dict[str, Any] | None) -> Path:
    if project_info:
        return (get_project_outputs_train_dir(project_info) / get_project_detection_run_name(project_info) / "weights" / "best.pt").resolve()
    return get_full_detection_weights_path()


def get_project_detection_model_path(project_info: dict[str, Any] | None) -> Path:
    return _get_project_detector_output_file(project_info, "onnx", get_full_detection_model_path())


def get_project_detection_meta_path(project_info: dict[str, Any] | None) -> Path:
    return _get_project_detector_output_file(project_info, "json", get_full_detection_meta_path())


def get_project_model_package_output_dir(project_info: dict[str, Any] | None, model_path: Path | None = None) -> Path:
    output_root = get_project_outputs_model_packages_dir(project_info)
    chosen_model = model_path
    if chosen_model is None:
        chosen_model = get_project_detection_model_path(project_info)
    model_stem = chosen_model.stem if chosen_model else "ai_tile_model"
    return (output_root / f"{model_stem}_bundle").resolve()


def get_default_smoke_benchmark_output_dir() -> Path:
    return AI_ROOT / "outputs" / f"benchmark_{build_smoke_target_slug(DEFAULT_SMOKE_LEVEL, DEFAULT_SMOKE_RESOURCE_TYPE, DEFAULT_SMOKE_RELATION)}"