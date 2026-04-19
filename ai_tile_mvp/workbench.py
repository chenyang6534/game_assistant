"""AI 地块识别可视化工作台。"""

from __future__ import annotations

import json
import signal
import shutil
import subprocess
import sys
from copy import deepcopy
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

APP_ROOT = Path(__file__).resolve().parents[1]
AI_ROOT = Path(__file__).resolve().parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from core.window import WindowManager
from ai_tile_mvp.project_scaffold import (
    DEFAULT_ATTRIBUTE_SPEC_TEXT,
    DEFAULT_PROJECTS_ROOT,
    build_default_detection_label,
    create_project_scaffold,
    load_project_meta,
    parse_attribute_spec_text,
)


ANYLABELING_RELEASES_URL = "https://github.com/CVHub520/X-AnyLabeling/releases"
ANYLABELING_WORK_DIR = AI_ROOT / ".xanylabeling_workdir"
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
ANYLABELING_LIGHT_OVERLAY_CONFIG = """show_texts: false
show_labels: false
show_attributes: false
shape:
    line_color: [0, 255, 0, 180]
    fill_color: [220, 220, 220, 35]
    select_line_color: [255, 255, 255, 220]
    select_fill_color: [0, 255, 0, 45]
    point_size: 9
    line_width: 3
canvas:
    attributes:
        background_color: [33, 33, 33, 96]
        border_color: [66, 66, 66, 160]
        text_color: [33, 150, 243, 255]
"""


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


def get_project_path_by_key(project_info: dict[str, Any] | None, key: str, default_path: Path) -> Path:
    project_root = get_project_root(project_info)
    project_meta = get_project_meta(project_info)
    if project_root and project_meta:
        relative_path = str((project_meta.get("paths") or {}).get(key, "")).strip()
        if relative_path:
            return (project_root / relative_path).resolve()
    return default_path


def get_project_file(project_info: dict[str, Any] | None, relative_path: str, default_path: Path) -> Path:
    project_root = get_project_root(project_info)
    if project_root:
        return (project_root / relative_path).resolve()
    return default_path


def get_project_detection_label(project_info: dict[str, Any] | None) -> str:
    project_meta = get_project_meta(project_info)
    if project_meta:
        return str(project_meta.get("detection_label") or DEFAULT_DETECTION_LABEL_NAME)
    return DEFAULT_DETECTION_LABEL_NAME


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
    project_meta = get_project_meta(project_info)
    if project_meta:
        return str(project_meta.get("detection_run_name") or FULL_DETECTION_RUN_NAME)
    return FULL_DETECTION_RUN_NAME


def get_project_attribute_tasks(project_info: dict[str, Any] | None) -> list[dict[str, Any]]:
    project_meta = get_project_meta(project_info)
    if project_meta:
        tasks = project_meta.get("attribute_tasks") or []
        if isinstance(tasks, list) and tasks:
            return tasks
    return build_default_ui_attribute_tasks()


def get_project_detection_root(project_info: dict[str, Any] | None) -> Path:
    return get_project_path_by_key(project_info, "detection_root", DETECTION_DATA_ROOT)


def get_project_detection_unconfirmed_root(project_info: dict[str, Any] | None) -> Path:
    return get_project_detection_root(project_info) / "excluded" / "unconfirmed_raw"


def get_project_smoke_root_dir(project_info: dict[str, Any] | None) -> Path:
    project_root = get_project_root(project_info)
    project_meta = get_project_meta(project_info)
    if project_root and project_meta:
        relative_path = str((project_meta.get("paths") or {}).get("smoke_root", "datasets/smoke_tests")).strip()
        if relative_path:
            return (project_root / relative_path).resolve()
    return SMOKE_TESTS_ROOT


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
    if project_info:
        return get_project_attribute_root(project_info) / task_name
    return get_attribute_task_root(task_name)


def get_project_attribute_task_raw_root(project_info: dict[str, Any] | None, task_name: str) -> Path:
    return get_project_attribute_task_root(project_info, task_name) / "raw"


def get_project_detection_weights_path(project_info: dict[str, Any] | None) -> Path:
    if project_info:
        return get_project_outputs_train_dir(project_info) / get_project_detection_run_name(project_info) / "weights" / "best.pt"
    return get_full_detection_weights_path()


def get_project_detection_model_path(project_info: dict[str, Any] | None) -> Path:
    if project_info:
        run_name = get_project_detection_run_name(project_info)
        project_root = get_project_root(project_info)
        assert project_root is not None
        return (project_root / "models" / "detector" / f"{run_name}_640.onnx").resolve()
    return get_full_detection_model_path()


def get_project_detection_meta_path(project_info: dict[str, Any] | None) -> Path:
    if project_info:
        run_name = get_project_detection_run_name(project_info)
        project_root = get_project_root(project_info)
        assert project_root is not None
        return (project_root / "models" / "detector" / f"{run_name}_640.json").resolve()
    return get_full_detection_meta_path()


class ProjectContext(QObject):
    projectChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project_info: dict[str, Any] | None = None

    def current_project(self) -> dict[str, Any] | None:
        return self._project_info

    def set_project(self, project_info: dict[str, Any] | None) -> None:
        self._project_info = project_info
        self.projectChanged.emit(project_info)

class SmokeSelectionContext(QObject):
    smokeChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state: dict[str, Any] | None = None

    def current_state(self) -> dict[str, Any] | None:
        return self._state

    def set_state(self, state: dict[str, Any] | None) -> None:
        self._state = state
        self.smokeChanged.emit(state)


def build_smoke_state(project_info: dict[str, Any] | None, target_values: dict[str, str]) -> dict[str, Any]:
    return {
        "project_config_path": str(project_info["config_path"]) if project_info else "",
        "target_values": dict(target_values),
        "output_root": str(get_project_smoke_test_root(project_info, target_values)),
        "run_name": get_project_smoke_detection_run_name(project_info, target_values),
    }


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


def get_default_smoke_benchmark_output_dir() -> Path:
    return AI_ROOT / "outputs" / f"benchmark_{build_smoke_target_slug(DEFAULT_SMOKE_LEVEL, DEFAULT_SMOKE_RESOURCE_TYPE, DEFAULT_SMOKE_RELATION)}"


def resolve_preferred_python_executable() -> str:
    candidates = [
        APP_ROOT.parent / ".venv" / "Scripts" / "python.exe",
        APP_ROOT / ".venv" / "Scripts" / "python.exe",
        Path(sys.executable),
    ]
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = str(candidate.resolve())
        except OSError:
            resolved = str(candidate)
        normalized = resolved.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        if Path(resolved).exists():
            return resolved
    return sys.executable


def iter_workspace_scripts_dirs() -> list[Path]:
    candidates = [
        APP_ROOT.parent / ".venv" / "Scripts",
        APP_ROOT / ".venv" / "Scripts",
        Path(resolve_preferred_python_executable()).resolve().parent,
    ]
    result: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        normalized = str(resolved).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(resolved)
    return result


def preferred_python_has_anylabeling() -> bool:
    python_exe = Path(resolve_preferred_python_executable())
    venv_root = python_exe.parent.parent
    module_dir = venv_root / "Lib" / "site-packages" / "anylabeling"
    return module_dir.exists()


PYTHON_EXE = resolve_preferred_python_executable()


def open_local_path(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))


def open_web_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


def ensure_anylabeling_work_config() -> Path:
    ANYLABELING_WORK_DIR.mkdir(parents=True, exist_ok=True)
    config_path = ANYLABELING_WORK_DIR / ".xanylabelingrc"
    current_text = ""
    if config_path.exists():
        current_text = config_path.read_text(encoding="utf-8")
    if current_text != ANYLABELING_LIGHT_OVERLAY_CONFIG:
        config_path.write_text(ANYLABELING_LIGHT_OVERLAY_CONFIG, encoding="utf-8")
    return config_path


def ensure_anylabeling_launch_files(
    project_info: dict[str, Any] | None,
    classes_file: Path,
    attrs_file: Path,
) -> tuple[Path, Path]:
    detection_label = get_project_detection_label(project_info)
    label_aliases = get_project_detection_label_aliases(project_info)
    if len(label_aliases) <= 1:
        return classes_file, attrs_file

    ANYLABELING_WORK_DIR.mkdir(parents=True, exist_ok=True)
    launch_root = ANYLABELING_WORK_DIR / "project_launch"
    launch_root.mkdir(parents=True, exist_ok=True)
    project_meta = get_project_meta(project_info) or {}
    project_slug = str(project_meta.get("project_slug") or "default")

    compat_labels_file = launch_root / f"{project_slug}_labels.txt"
    compat_labels_file.write_text("\n".join(label_aliases) + "\n", encoding="utf-8")

    attrs_data = json.loads(attrs_file.read_text(encoding="utf-8"))
    shape_config_key = detection_label if detection_label in attrs_data else ""
    if not shape_config_key:
        for alias in label_aliases:
            if alias in attrs_data:
                shape_config_key = alias
                break

    if shape_config_key:
        for alias in label_aliases:
            if alias not in attrs_data:
                attrs_data[alias] = deepcopy(attrs_data[shape_config_key])

    widget_types = attrs_data.get("__widget_types__")
    if isinstance(widget_types, dict):
        widget_config_key = detection_label if detection_label in widget_types else ""
        if not widget_config_key:
            for alias in label_aliases:
                if alias in widget_types:
                    widget_config_key = alias
                    break
        if widget_config_key:
            for alias in label_aliases:
                if alias not in widget_types:
                    widget_types[alias] = deepcopy(widget_types[widget_config_key])

    compat_attrs_file = launch_root / f"{project_slug}_attributes.json"
    compat_attrs_file.write_text(json.dumps(attrs_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return compat_labels_file, compat_attrs_file


def resolve_anylabeling_launcher(launcher_text: str) -> tuple[str, list[str], str] | None:
    launcher_text = launcher_text.strip()
    if launcher_text:
        launcher_path = Path(launcher_text)
        if launcher_path.exists():
            resolved_path = str(launcher_path.resolve())
            suffix = launcher_path.suffix.lower()
            if suffix in {".cmd", ".bat"}:
                return "cmd.exe", ["/c", resolved_path], f"手动指定批处理: {resolved_path}"
            if suffix == ".py":
                return PYTHON_EXE, [resolved_path], f"手动指定 Python 脚本: {resolved_path}"
            return resolved_path, [], f"手动指定可执行文件: {resolved_path}"

        command_path = shutil.which(launcher_text)
        if command_path:
            return command_path, [], f"手动指定命令: {command_path}"

    for scripts_dir in iter_workspace_scripts_dirs():
        for launcher_name in ("xanylabeling.exe", "xanylabeling.cmd", "xanylabeling.bat", "xanylabeling"):
            launcher_path = scripts_dir / launcher_name
            if launcher_path.exists():
                resolved_path = str(launcher_path.resolve())
                if launcher_path.suffix.lower() in {".cmd", ".bat"}:
                    return "cmd.exe", ["/c", resolved_path], f"工作区环境中的启动器: {resolved_path}"
                return resolved_path, [], f"工作区环境中的启动器: {resolved_path}"

    for command_name in ("xanylabeling", "anylabeling"):
        command_path = shutil.which(command_name)
        if command_path:
            return command_path, [], f"自动检测到命令: {command_path}"

    if preferred_python_has_anylabeling() or find_spec("anylabeling.app") is not None:
        return PYTHON_EXE, ["-m", "anylabeling.app"], f"自动检测到 Python 环境中的 anylabeling.app: {PYTHON_EXE}"

    return None


def build_path_row(line_edit: QLineEdit, button_text: str, button_handler) -> tuple[QHBoxLayout, QPushButton]:
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    button = QPushButton(button_text)
    button.clicked.connect(button_handler)
    layout.addWidget(line_edit, 1)
    layout.addWidget(button)
    return layout, button


class WorkflowTabBase(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        self._process.setProcessEnvironment(env)
        self._process.readyReadStandardOutput.connect(self._on_process_output)
        self._process.finished.connect(self._on_process_finished)
        self._process.errorOccurred.connect(self._on_process_error)

        self._status_label = QLabel("状态: 空闲")
        self._log_edit = QPlainTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setPlaceholderText("这里会显示脚本运行日志")

    def _create_log_group(self, title: str = "运行日志") -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.addWidget(self._status_label)
        layout.addWidget(self._log_edit, 1)
        return group

    def _append_log(self, text: str) -> None:
        if not text:
            return
        cursor = self._log_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text)
        self._log_edit.setTextCursor(cursor)
        self._log_edit.ensureCursorVisible()

    def _run_python_script(self, script_path: Path, args: list[str], description: str) -> bool:
        if self._process.state() != QProcess.ProcessState.NotRunning:
            QMessageBox.warning(self, "提示", "当前已有任务在运行，请先停止或等待完成")
            return False

        self._log_edit.clear()
        self._append_log(f"启动任务: {description}\n")
        self._append_log(f"命令: {PYTHON_EXE} {script_path} {' '.join(args)}\n\n")
        self._status_label.setText(f"状态: 运行中 - {description}")
        self._set_running_state(True)
        self._process.setWorkingDirectory(str(APP_ROOT))
        self._process.start(PYTHON_EXE, [str(script_path), *args])
        if not self._process.waitForStarted(3000):
            self._append_log("无法启动脚本进程\n")
            self._status_label.setText("状态: 启动失败")
            self._set_running_state(False)
            return False
        return True

    def _stop_process(self) -> None:
        if self._process.state() == QProcess.ProcessState.NotRunning:
            return
        self._append_log("\n请求停止当前任务...\n")
        self._process.kill()

    def _on_process_output(self) -> None:
        data = bytes(self._process.readAllStandardOutput())
        if data:
            self._append_log(data.decode("utf-8", errors="ignore"))

    def _on_process_finished(self, exit_code: int, _exit_status) -> None:
        if exit_code == 0:
            self._status_label.setText("状态: 已完成")
            self._append_log("\n任务完成\n")
        else:
            self._status_label.setText(f"状态: 已结束，退出码 {exit_code}")
            self._append_log(f"\n任务结束，退出码 {exit_code}\n")
        self._set_running_state(False)

    def _on_process_error(self, error) -> None:
        if error == QProcess.ProcessError.Crashed:
            self._append_log("\n任务进程异常退出\n")

    def _set_running_state(self, running: bool) -> None:
        del running

    def _choose_directory(self, target: QLineEdit) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择目录", target.text().strip() or str(AI_ROOT))
        if directory:
            target.setText(directory)

    def _choose_open_file(self, target: QLineEdit, title: str, file_filter: str) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, title, target.text().strip() or str(AI_ROOT), file_filter)
        if file_path:
            target.setText(file_path)

    def _choose_save_file(self, target: QLineEdit, title: str, file_filter: str) -> None:
        file_path, _ = QFileDialog.getSaveFileName(self, title, target.text().strip() or str(AI_ROOT), file_filter)
        if file_path:
            target.setText(file_path)


class ProjectAwareTabBase(WorkflowTabBase):
    def __init__(self, project_context: ProjectContext | None = None, parent=None):
        super().__init__(parent)
        self._project_context = project_context
        self._project_info: dict[str, Any] | None = None

    def _bind_project_context(self) -> None:
        if self._project_context is None:
            self.apply_project_context(None)
            return
        self._project_context.projectChanged.connect(self._on_project_changed)
        self._on_project_changed(self._project_context.current_project())

    def _on_project_changed(self, project_info: dict[str, Any] | None) -> None:
        self._project_info = project_info
        self.apply_project_context(project_info)

    def apply_project_context(self, project_info: dict[str, Any] | None) -> None:
        del project_info


class ProjectCreationTab(WorkflowTabBase):
    projectCreated = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._base_dir_edit = QLineEdit(str(DEFAULT_PROJECTS_ROOT))
        self._project_name_edit = QLineEdit("test1")
        self._detection_label_edit = QLineEdit(build_default_detection_label("test1"))
        self._last_auto_detection_label = self._detection_label_edit.text().strip()
        self._attributes_table = QTableWidget(0, 2)
        self._attributes_table.setHorizontalHeaderLabels(["属性名", "可选值（逗号分隔）"])
        self._attributes_table.verticalHeader().setVisible(False)
        self._attributes_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._attributes_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._attributes_table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed | QAbstractItemView.EditTrigger.SelectedClicked)
        self._attributes_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._attributes_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._overwrite_check = QCheckBox("允许覆盖同名项目里的已生成文件")
        self._open_after_create_check = QCheckBox("创建后自动打开项目目录")
        self._open_after_create_check.setChecked(True)
        self._target_dir_label = QLabel()
        self._target_dir_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self._base_dir_browse_button = QPushButton("浏览...")
        self._base_dir_browse_button.clicked.connect(lambda: self._choose_directory(self._base_dir_edit))
        self._project_name_edit.textChanged.connect(self._on_project_name_changed)
        self._base_dir_edit.textChanged.connect(self._update_target_dir_preview)

        self._add_attr_button = QPushButton("新增属性")
        self._add_attr_button.clicked.connect(lambda: self._append_attribute_row())
        self._remove_attr_button = QPushButton("删除选中属性")
        self._remove_attr_button.clicked.connect(self._remove_selected_attribute_row)
        self._reset_attrs_button = QPushButton("恢复默认属性模板")
        self._reset_attrs_button.clicked.connect(lambda: self._load_attribute_rows(DEFAULT_ATTRIBUTE_SPEC_TEXT))
        self._create_button = QPushButton("创建 AI 训练项目")
        self._create_button.clicked.connect(self._create_project)
        self._open_project_button = QPushButton("打开项目目录")
        self._open_project_button.clicked.connect(self._open_project_root)

        note = QLabel(
            "这里用来创建独立 AI 训练项目。项目名例如 test1，创建后会在该目录下生成 configs、datasets、models、outputs、scripts、README 等整套文件。"
            "现在改成表格编辑属性。左列填属性名，右列填可选值列表。"
            "如果你想手动指定 slug，也支持在单元格里写“属性名=>task_slug”或“值=>slug”。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #444;")

        config_group = QGroupBox("项目创建")
        config_layout = QFormLayout(config_group)
        base_dir_row = QHBoxLayout()
        base_dir_row.setContentsMargins(0, 0, 0, 0)
        base_dir_row.setSpacing(8)
        base_dir_row.addWidget(self._base_dir_edit, 1)
        base_dir_row.addWidget(self._base_dir_browse_button)
        config_layout.addRow("项目父目录:", base_dir_row)
        config_layout.addRow("项目名:", self._project_name_edit)
        config_layout.addRow("检测标签名:", self._detection_label_edit)
        config_layout.addRow("目标项目目录:", self._target_dir_label)
        config_layout.addRow("", self._overwrite_check)
        config_layout.addRow("", self._open_after_create_check)

        attrs_group = QGroupBox("属性定义")
        attrs_layout = QVBoxLayout(attrs_group)
        attrs_layout.addWidget(self._attributes_table, 1)
        attrs_button_row = QHBoxLayout()
        attrs_button_row.addWidget(self._add_attr_button)
        attrs_button_row.addWidget(self._remove_attr_button)
        attrs_button_row.addWidget(self._reset_attrs_button)
        attrs_button_row.addStretch()
        attrs_layout.addLayout(attrs_button_row)

        button_row = QHBoxLayout()
        button_row.addWidget(self._create_button)
        button_row.addWidget(self._open_project_button)
        button_row.addStretch()

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(note)
        main_layout.addWidget(config_group)
        main_layout.addWidget(attrs_group, 1)
        main_layout.addLayout(button_row)
        main_layout.addWidget(self._create_log_group(), 1)

        self._update_target_dir_preview()
        self._load_attribute_rows(DEFAULT_ATTRIBUTE_SPEC_TEXT)

    def _current_project_root(self) -> Path:
        base_dir = Path(self._base_dir_edit.text().strip() or DEFAULT_PROJECTS_ROOT)
        project_name = self._project_name_edit.text().strip() or "project"
        return base_dir / project_name

    def _on_project_name_changed(self, text: str) -> None:
        auto_label = build_default_detection_label(text or "project")
        current_label = self._detection_label_edit.text().strip()
        if not current_label or current_label == self._last_auto_detection_label:
            self._detection_label_edit.setText(auto_label)
        self._last_auto_detection_label = auto_label
        self._update_target_dir_preview()

    def _update_target_dir_preview(self) -> None:
        self._target_dir_label.setText(str(self._current_project_root()))

    def _open_project_root(self) -> None:
        project_root = self._current_project_root()
        open_local_path(project_root if project_root.exists() else project_root.parent)

    def _append_attribute_row(self, attribute_name: str = "", value_text: str = "") -> None:
        row_index = self._attributes_table.rowCount()
        self._attributes_table.insertRow(row_index)
        self._attributes_table.setItem(row_index, 0, QTableWidgetItem(attribute_name))
        self._attributes_table.setItem(row_index, 1, QTableWidgetItem(value_text))

    def _remove_selected_attribute_row(self) -> None:
        selected_rows = sorted({item.row() for item in self._attributes_table.selectedItems()}, reverse=True)
        for row_index in selected_rows:
            self._attributes_table.removeRow(row_index)

    def _load_attribute_rows(self, spec_text: str) -> None:
        self._attributes_table.setRowCount(0)
        for task in parse_attribute_spec_text(spec_text):
            values_text = ", ".join(class_info["display_name"] for class_info in task.get("classes") or [])
            self._append_attribute_row(str(task.get("display_name") or ""), values_text)

    def _build_attribute_spec_text(self) -> str:
        lines: list[str] = []
        for row_index in range(self._attributes_table.rowCount()):
            name_item = self._attributes_table.item(row_index, 0)
            values_item = self._attributes_table.item(row_index, 1)
            attribute_name = name_item.text().strip() if name_item else ""
            value_text = values_item.text().strip() if values_item else ""
            if not attribute_name and not value_text:
                continue
            lines.append(f"{attribute_name}: {value_text}")
        return "\n".join(lines)

    def _create_project(self) -> None:
        self._log_edit.clear()
        self._status_label.setText("状态: 创建中")
        self._set_running_state(True)
        try:
            result = create_project_scaffold(
                base_dir=self._base_dir_edit.text().strip() or str(DEFAULT_PROJECTS_ROOT),
                project_name=self._project_name_edit.text().strip(),
                detection_label=self._detection_label_edit.text().strip(),
                attribute_spec_text=self._build_attribute_spec_text(),
                allow_overwrite=self._overwrite_check.isChecked(),
            )
        except Exception as exc:
            self._status_label.setText("状态: 创建失败")
            self._append_log(f"创建项目失败: {exc}\n")
            QMessageBox.critical(self, "创建失败", str(exc))
            self._set_running_state(False)
            return

        project_root = Path(result["project_root"])
        project_meta = result["project_meta"]
        written_files = result["written_files"]
        created_dirs = result["created_dirs"]

        self._status_label.setText("状态: 已创建")
        self._append_log(f"项目目录: {project_root}\n")
        self._append_log(f"检测标签: {project_meta['detection_label']}\n")
        self._append_log(f"属性任务数: {len(project_meta['attribute_tasks'])}\n")
        self._append_log(f"创建目录数: {len(created_dirs)}\n")
        self._append_log(f"生成文件数: {len(written_files)}\n")
        self._append_log("\n已生成的关键文件:\n")
        for path in written_files[:20]:
            self._append_log(f"- {Path(path).relative_to(project_root)}\n")
        if len(written_files) > 20:
            self._append_log(f"- ... 其余 {len(written_files) - 20} 个文件\n")

        self._set_running_state(False)
        self.projectCreated.emit(project_root)
        if self._open_after_create_check.isChecked():
            open_local_path(project_root)
        QMessageBox.information(
            self,
            "创建完成",
            f"项目已创建:\n{project_root}\n\n"
            f"检测标签: {project_meta['detection_label']}\n"
            f"属性任务数: {len(project_meta['attribute_tasks'])}\n"
            f"生成文件数: {len(written_files)}",
        )

    def _set_running_state(self, running: bool) -> None:
        self._base_dir_edit.setEnabled(not running)
        self._project_name_edit.setEnabled(not running)
        self._detection_label_edit.setEnabled(not running)
        self._attributes_table.setEnabled(not running)
        self._overwrite_check.setEnabled(not running)
        self._open_after_create_check.setEnabled(not running)
        self._base_dir_browse_button.setEnabled(not running)
        self._add_attr_button.setEnabled(not running)
        self._remove_attr_button.setEnabled(not running)
        self._reset_attrs_button.setEnabled(not running)
        self._create_button.setEnabled(not running)
        self._open_project_button.setEnabled(not running)


class SamplingTab(ProjectAwareTabBase):
    def __init__(self, project_context: ProjectContext | None = None, parent=None):
        super().__init__(project_context, parent)
        self._windows: list[dict] = []

        self._window_combo = QComboBox()
        self._refresh_button = QPushButton("刷新窗口")
        self._refresh_button.clicked.connect(self._refresh_windows)

        self._output_dir_edit = QLineEdit(str(DETECTION_RAW_IMAGE_DIR))
        output_row, self._output_browse_button = build_path_row(self._output_dir_edit, "浏览...", lambda: self._choose_directory(self._output_dir_edit))

        self._prefix_edit = QLineEdit("map")
        self._count_spin = QSpinBox()
        self._count_spin.setRange(1, 100000)
        self._count_spin.setValue(300)

        self._interval_spin = QDoubleSpinBox()
        self._interval_spin.setRange(0.1, 60.0)
        self._interval_spin.setDecimals(2)
        self._interval_spin.setValue(1.2)

        self._roi_edit = QLineEdit("0.10,0.08,0.80,0.84")

        self._diff_threshold_spin = QDoubleSpinBox()
        self._diff_threshold_spin.setRange(0.0, 255.0)
        self._diff_threshold_spin.setDecimals(2)
        self._diff_threshold_spin.setValue(2.0)

        self._bring_to_front_check = QCheckBox("采样前激活窗口")
        self._bring_to_front_check.setChecked(True)

        self._settle_seconds_spin = QDoubleSpinBox()
        self._settle_seconds_spin.setRange(0.0, 10.0)
        self._settle_seconds_spin.setDecimals(2)
        self._settle_seconds_spin.setValue(1.0)

        self._start_button = QPushButton("开始采样")
        self._start_button.clicked.connect(self._start_sampling)
        self._stop_button = QPushButton("停止采样")
        self._stop_button.clicked.connect(self._stop_process)
        self._open_output_button = QPushButton("打开输出目录")
        self._open_output_button.clicked.connect(self._open_output_dir)
        self._open_manifest_button = QPushButton("打开采样清单")
        self._open_manifest_button.clicked.connect(self._open_manifest)

        main_layout = QVBoxLayout(self)

        tips = QLabel(
            "采样开始后，请切到目标窗口并手动拖地图、缩放视角、切换场景，让采样器截到更多不同画面。"
            "如果画面静止不动，采样器只会得到少量相似图片。"
        )
        tips.setWordWrap(True)
        tips.setStyleSheet("color: #444;")
        main_layout.addWidget(tips)

        config_group = QGroupBox("采样设置")
        config_layout = QFormLayout(config_group)

        window_row = QHBoxLayout()
        window_row.setContentsMargins(0, 0, 0, 0)
        window_row.setSpacing(8)
        window_row.addWidget(self._window_combo, 1)
        window_row.addWidget(self._refresh_button)
        config_layout.addRow("采样窗口:", window_row)
        config_layout.addRow("输出目录:", output_row)
        config_layout.addRow("文件前缀:", self._prefix_edit)
        config_layout.addRow("采样张数:", self._count_spin)
        config_layout.addRow("采样间隔(秒):", self._interval_spin)
        config_layout.addRow("地图 ROI:", self._roi_edit)
        config_layout.addRow("最小差异阈值:", self._diff_threshold_spin)
        config_layout.addRow("激活窗口后等待(秒):", self._settle_seconds_spin)
        config_layout.addRow("", self._bring_to_front_check)
        main_layout.addWidget(config_group)

        button_row = QHBoxLayout()
        button_row.addWidget(self._start_button)
        button_row.addWidget(self._stop_button)
        button_row.addWidget(self._open_output_button)
        button_row.addWidget(self._open_manifest_button)
        button_row.addStretch()
        main_layout.addLayout(button_row)
        main_layout.addWidget(self._create_log_group(), 1)

        self._refresh_windows()
        self._set_running_state(False)
        self._bind_project_context()

    def _set_running_state(self, running: bool) -> None:
        self._start_button.setEnabled(not running)
        self._refresh_button.setEnabled(not running)
        self._output_browse_button.setEnabled(not running)
        self._stop_button.setEnabled(running)

    def _refresh_windows(self) -> None:
        self._window_combo.clear()
        self._windows = []
        manager = WindowManager()
        for window in manager.get_game_windows():
            item = {
                "hwnd": int(window.hwnd),
                "title": window.title,
                "class_name": window.class_name,
                "width": window.width,
                "height": window.height,
            }
            label = f"{window.title} [{window.width}x{window.height}] ({window.class_name})"
            self._window_combo.addItem(label, item)
            self._windows.append(item)

    def _current_window(self) -> dict | None:
        data = self._window_combo.currentData()
        return data if isinstance(data, dict) else None

    def _start_sampling(self) -> None:
        window = self._current_window()
        if not window:
            QMessageBox.warning(self, "提示", "请先选择采样窗口")
            return

        script_path = AI_ROOT / "scripts" / "sample_map_tiles.py"
        args = [
            "--window-hwnd",
            str(window["hwnd"]),
            "--output-dir",
            self._output_dir_edit.text().strip(),
            "--count",
            str(self._count_spin.value()),
            "--interval",
            f"{self._interval_spin.value():.2f}",
            "--prefix",
            self._prefix_edit.text().strip() or "map",
            "--diff-threshold",
            f"{self._diff_threshold_spin.value():.2f}",
            "--settle-seconds",
            f"{self._settle_seconds_spin.value():.2f}",
        ]
        roi_text = self._roi_edit.text().strip()
        if roi_text:
            args.extend(["--roi", roi_text])
        if self._bring_to_front_check.isChecked():
            args.append("--bring-to-front")

        self._run_python_script(script_path, args, f"采样窗口: {window['title']}")

    def _open_output_dir(self) -> None:
        output_dir = Path(self._output_dir_edit.text().strip() or AI_ROOT)
        output_dir.mkdir(parents=True, exist_ok=True)
        open_local_path(output_dir)

    def _open_manifest(self) -> None:
        manifest_path = Path(self._output_dir_edit.text().strip() or AI_ROOT) / "capture_manifest.csv"
        if manifest_path.exists():
            open_local_path(manifest_path)
        else:
            QMessageBox.information(self, "提示", "采样清单还不存在，先执行一次采样")

    def apply_project_context(self, project_info: dict[str, Any] | None) -> None:
        self._output_dir_edit.setText(str(get_project_detection_raw_images_dir(project_info)))


class LabelingTab(ProjectAwareTabBase):
    def __init__(self, project_context: ProjectContext | None = None, parent=None):
        super().__init__(project_context, parent)
        self._anylabeling_launcher_edit = QLineEdit()
        self._anylabeling_launcher_edit.setPlaceholderText("留空=自动检测 xanylabeling；也可手动选择 xanylabeling.exe")
        self._image_dir_edit = QLineEdit(str(DETECTION_RAW_IMAGE_DIR))
        self._label_dir_edit = QLineEdit(str(DETECTION_RAW_LABEL_DIR))
        self._attrs_config_edit = QLineEdit(str(DEFAULT_ATTRIBUTES_FILE))
        self._output_dir_edit = QLineEdit(str(AI_ROOT / "outputs" / "label_check"))
        self._sample_count_spin = QSpinBox()
        self._sample_count_spin.setRange(1, 10000)
        self._sample_count_spin.setValue(40)

        self._launch_anylabeling_button = QPushButton("启动 AnyLabeling")
        self._launch_anylabeling_button.clicked.connect(self._launch_anylabeling)
        self._open_anylabeling_release_button = QPushButton("打开发布页")
        self._open_anylabeling_release_button.clicked.connect(lambda: open_web_url(ANYLABELING_RELEASES_URL))
        self._move_unconfirmed_button = QPushButton("移走未确认原图")
        self._move_unconfirmed_button.clicked.connect(self._run_move_unconfirmed)
        self._check_button = QPushButton("运行标签抽检")
        self._check_button.clicked.connect(self._run_check)
        self._stop_button = QPushButton("停止抽检")
        self._stop_button.clicked.connect(self._stop_process)
        self._open_preview_button = QPushButton("打开抽检输出")
        self._open_preview_button.clicked.connect(lambda: open_local_path(Path(self._output_dir_edit.text().strip())))
        self._open_unconfirmed_button = QPushButton("打开移走目录")
        self._open_unconfirmed_button.clicked.connect(self._open_unconfirmed_dir)
        self._open_images_button = QPushButton("打开原图目录")
        self._open_images_button.clicked.connect(lambda: open_local_path(Path(self._image_dir_edit.text().strip())))
        self._open_labels_button = QPushButton("打开标签目录")
        self._open_labels_button.clicked.connect(lambda: open_local_path(Path(self._label_dir_edit.text().strip())))
        self._open_attrs_config_button = QPushButton("打开属性配置")
        self._open_attrs_config_button.clicked.connect(lambda: open_local_path(Path(self._attrs_config_edit.text().strip())))
        self._open_checklist_button = QPushButton("打开标注清单")
        self._open_checklist_button.clicked.connect(self._open_checklist)

        self._checklist_view = QTextEdit()
        self._checklist_view.setReadOnly(True)
        self._checklist_view.setMarkdown(DEFAULT_CHECKLIST_FILE.read_text(encoding="utf-8"))

        note = QLabel(
            "这里保存的是 AnyLabeling 的 JSON 主标注。标完后先去“标注同步”页生成检测 txt 和三套属性裁剪，"
            "再做抽检、切分和训练。优先尝试 Upload -> Upload Attributes File；如果 X-AnyLabeling 一导入属性文件就崩，"
            "就不要导入，直接在每个框的 description 里写“5级 木材 敌对”这类文本。"
            "如果你怀疑还有不少图没标完，可以先点‘移走未确认原图’，把没有 JSON 且没有有效 txt 的图片先移出训练候选集。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #444;")

        config_group = QGroupBox("标注与抽检")
        config_layout = QFormLayout(config_group)
        anylabeling_row, self._anylabeling_launcher_browse_button = build_path_row(
            self._anylabeling_launcher_edit,
            "浏览...",
            self._browse_anylabeling_launcher,
        )
        image_row, self._image_browse_button = build_path_row(self._image_dir_edit, "浏览...", lambda: self._choose_directory(self._image_dir_edit))
        label_row, self._label_browse_button = build_path_row(self._label_dir_edit, "浏览...", lambda: self._choose_directory(self._label_dir_edit))
        attrs_row, self._attrs_browse_button = build_path_row(self._attrs_config_edit, "浏览...", lambda: self._choose_open_file(self._attrs_config_edit, "选择属性配置文件", "JSON 文件 (*.json);;所有文件 (*.*)"))
        output_row, self._output_browse_button = build_path_row(self._output_dir_edit, "浏览...", lambda: self._choose_directory(self._output_dir_edit))
        config_layout.addRow("AnyLabeling 启动程序:", anylabeling_row)
        config_layout.addRow("原图目录:", image_row)
        config_layout.addRow("标签目录:", label_row)
        config_layout.addRow("属性配置文件:", attrs_row)
        config_layout.addRow("抽检输出目录:", output_row)
        config_layout.addRow("随机抽检数量:", self._sample_count_spin)

        helper_row = QHBoxLayout()
        helper_row.addWidget(self._launch_anylabeling_button)
        helper_row.addWidget(self._open_anylabeling_release_button)
        helper_row.addWidget(self._move_unconfirmed_button)
        helper_row.addWidget(self._open_unconfirmed_button)
        helper_row.addWidget(self._open_images_button)
        helper_row.addWidget(self._open_labels_button)
        helper_row.addWidget(self._open_attrs_config_button)
        helper_row.addWidget(self._open_checklist_button)
        helper_row.addStretch()

        action_row = QHBoxLayout()
        action_row.addWidget(self._check_button)
        action_row.addWidget(self._stop_button)
        action_row.addWidget(self._open_preview_button)
        action_row.addStretch()

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(note)
        main_layout.addWidget(config_group)
        main_layout.addLayout(helper_row)
        main_layout.addLayout(action_row)
        main_layout.addWidget(self._checklist_view, 1)
        main_layout.addWidget(self._create_log_group(), 1)
        self._set_running_state(False)
        self._bind_project_context()

    def _set_running_state(self, running: bool) -> None:
        self._check_button.setEnabled(not running)
        self._move_unconfirmed_button.setEnabled(not running)
        self._image_browse_button.setEnabled(not running)
        self._label_browse_button.setEnabled(not running)
        self._attrs_browse_button.setEnabled(not running)
        self._output_browse_button.setEnabled(not running)
        self._open_unconfirmed_button.setEnabled(not running)
        self._stop_button.setEnabled(running)

    def _browse_anylabeling_launcher(self) -> None:
        self._choose_open_file(
            self._anylabeling_launcher_edit,
            "选择 AnyLabeling 启动程序",
            "Executable Files (*.exe *.cmd *.bat *.py);;All Files (*)",
        )

    def _launch_anylabeling(self) -> None:
        image_dir = Path(self._image_dir_edit.text().strip())
        label_dir = Path(self._label_dir_edit.text().strip())
        classes_file = get_project_label_classes_file(self._project_info)
        attrs_file = Path(self._attrs_config_edit.text().strip())

        if not image_dir.exists():
            QMessageBox.warning(self, "提示", f"原图目录不存在:\n{image_dir}")
            return

        if not classes_file.exists():
            QMessageBox.warning(self, "提示", f"类别文件不存在:\n{classes_file}")
            return

        if not attrs_file.exists():
            QMessageBox.warning(self, "提示", f"属性配置文件不存在:\n{attrs_file}")
            return

        launcher = resolve_anylabeling_launcher(self._anylabeling_launcher_edit.text())
        if launcher is None:
            QMessageBox.information(
                self,
                "未找到 AnyLabeling",
                "没有自动检测到 AnyLabeling。\n\n"
                "推荐先在启动当前工作台的同一个 Python 环境中安装：\n"
                "python -m pip install -U uv\n"
                "python -m uv pip install x-anylabeling-cvhub[cpu]\n\n"
                "如果你下载的是绿色版，请在上面的“AnyLabeling 启动程序”里手动选中 xanylabeling.exe。",
            )
            return

        label_dir.mkdir(parents=True, exist_ok=True)
        ANYLABELING_WORK_DIR.mkdir(parents=True, exist_ok=True)
        config_path = ensure_anylabeling_work_config()
        launch_classes_file, launch_attrs_file = ensure_anylabeling_launch_files(self._project_info, classes_file, attrs_file)

        program, base_args, source_text = launcher
        launch_args = [
            *base_args,
            "--work-dir",
            str(ANYLABELING_WORK_DIR),
            "--filename",
            str(image_dir),
            "--output",
            str(label_dir),
            "--labels",
            str(launch_classes_file),
            "--validatelabel",
            "exact",
            "--no-auto-update-check",
        ]

        popen_kwargs = {"cwd": str(APP_ROOT)}
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if creationflags:
            popen_kwargs["creationflags"] = creationflags

        try:
            subprocess.Popen([program, *launch_args], **popen_kwargs)
        except OSError as exc:
            QMessageBox.critical(self, "启动失败", f"无法启动 AnyLabeling:\n{exc}")
            return

        command_preview = " ".join([program, *launch_args])
        self._status_label.setText("状态: 已启动 AnyLabeling")
        self._append_log(
            "已启动 AnyLabeling\n"
            f"来源: {source_text}\n"
            f"原图目录: {image_dir}\n"
            f"标签目录: {label_dir}\n"
            f"类别文件: {launch_classes_file}\n"
            f"属性配置文件: {launch_attrs_file}\n"
            f"轻遮挡配置: {config_path}\n"
            f"命令: {command_preview}\n\n"
        )
        QMessageBox.information(
            self,
            "已启动",
            "AnyLabeling 已启动。\n\n"
            "我已经帮你带入：\n"
            f"- 原图目录: {image_dir}\n"
            f"- 标签目录: {label_dir}\n"
            f"- 类别文件: {launch_classes_file}\n\n"
            "另外已经自动启用轻遮挡配置：隐藏框顶标签、框内属性文字，并降低框填充透明度。\n"
            "另外已经自动启用旧标签兼容：会同时兼容当前项目标签和旧的 plot_node。\n"
            "如果之前已经开着 AnyLabeling，请先关掉再从这里重开，配置才会生效。\n\n"
            "下一步有两种做法：\n"
            f"- 正常模式：Upload -> Upload Attributes File -> 选中 {launch_attrs_file}\n"
            "- 崩溃兜底：不要导入属性文件，直接在每个框的 description 文本里写“5级 木材 敌对”\n\n"
            "然后再按页面里的“打开标注清单”继续操作。",
        )

    def _run_check(self) -> None:
        script_path = AI_ROOT / "scripts" / "check_yolo_labels.py"
        args = [
            "--image-dir",
            self._image_dir_edit.text().strip(),
            "--label-dir",
            self._label_dir_edit.text().strip(),
            "--output-dir",
            self._output_dir_edit.text().strip(),
            "--sample-count",
            str(self._sample_count_spin.value()),
        ]
        self._run_python_script(script_path, args, "标签抽检")

    def _run_move_unconfirmed(self) -> None:
        output_root = get_project_detection_unconfirmed_root(self._project_info)
        reply = QMessageBox.question(
            self,
            "确认移走",
            "这个操作会把没有 JSON，且没有有效 txt 的原图移到 excluded 目录，不会直接删除。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        script_path = AI_ROOT / "scripts" / "move_unconfirmed_detection_images.py"
        args = [
            "--image-dir",
            self._image_dir_edit.text().strip(),
            "--label-dir",
            self._label_dir_edit.text().strip(),
            "--output-root",
            str(output_root),
        ]
        self._run_python_script(script_path, args, "移走未确认原图")

    def _open_unconfirmed_dir(self) -> None:
        open_local_path(get_project_detection_unconfirmed_root(self._project_info))

    def _open_checklist(self) -> None:
        open_local_path(get_project_checklist_file(self._project_info))

    def apply_project_context(self, project_info: dict[str, Any] | None) -> None:
        self._image_dir_edit.setText(str(get_project_detection_raw_images_dir(project_info)))
        self._label_dir_edit.setText(str(get_project_detection_raw_labels_dir(project_info)))
        self._attrs_config_edit.setText(str(get_project_attributes_file(project_info)))
        self._output_dir_edit.setText(str(get_project_outputs_label_check_dir(project_info)))
        checklist_path = get_project_checklist_file(project_info)
        if checklist_path.exists():
            self._checklist_view.setMarkdown(checklist_path.read_text(encoding="utf-8"))
        else:
            self._checklist_view.setPlainText(f"未找到标注清单: {checklist_path}")


class SmokeTestTab(ProjectAwareTabBase):
    def __init__(self, project_context: ProjectContext | None = None, smoke_context: SmokeSelectionContext | None = None, parent=None):
        super().__init__(project_context, parent)
        self._smoke_context = smoke_context
        self._image_dir_edit = QLineEdit(str(DETECTION_RAW_IMAGE_DIR))
        self._json_dir_edit = QLineEdit(str(DETECTION_RAW_LABEL_DIR))
        self._task_combos: dict[str, QComboBox] = {}
        self._task_labels: dict[str, str] = {}

        default_root = get_project_smoke_test_root(None)
        self._output_root_edit = QLineEdit(str(default_root))
        self._ignore_attrs_check = QCheckBox("忽略属性，直接把所有已框 plot_node 当成当前单目标")
        self._ignore_attrs_check.setChecked(True)
        self._clear_output_check = QCheckBox("生成前清空快测目录")
        self._clear_output_check.setChecked(True)

        self._build_button = QPushButton("生成单目标快测数据")
        self._build_button.clicked.connect(self._run_build)
        self._stop_button = QPushButton("停止")
        self._stop_button.clicked.connect(self._stop_process)
        self._open_output_button = QPushButton("打开快测目录")
        self._open_output_button.clicked.connect(lambda: open_local_path(Path(self._output_root_edit.text().strip())))
        self._open_summary_button = QPushButton("打开快测汇总")
        self._open_summary_button.clicked.connect(self._open_summary)

        self._note_label = QLabel(
            "这一步专门用来做单目标烟雾测试。你可以按当前项目定义的属性选择一个具体组合，"
            "例如某个等级、类型、关系的组合，然后快速生成一套独立的小检测数据集。"
            "注意：这里默认只收集有 JSON 的图片；如果你想让无目标图片也参与训练，请把它们也保存成空 JSON。"
        )
        self._note_label.setWordWrap(True)
        self._note_label.setStyleSheet("color: #444;")

        config_group = QGroupBox("单目标快测设置")
        config_layout = QFormLayout(config_group)
        image_row, self._image_browse_button = build_path_row(self._image_dir_edit, "浏览...", lambda: self._choose_directory(self._image_dir_edit))
        json_row, self._json_browse_button = build_path_row(self._json_dir_edit, "浏览...", lambda: self._choose_directory(self._json_dir_edit))
        output_row, self._output_browse_button = build_path_row(self._output_root_edit, "浏览...", lambda: self._choose_directory(self._output_root_edit))
        self._target_form_widget = QWidget()
        self._target_form_layout = QFormLayout(self._target_form_widget)
        config_layout.addRow("原图目录:", image_row)
        config_layout.addRow("JSON 标签目录:", json_row)
        config_layout.addRow("目标属性:", self._target_form_widget)
        config_layout.addRow("快测输出目录:", output_row)
        config_layout.addRow("", self._ignore_attrs_check)
        config_layout.addRow("", self._clear_output_check)

        button_row = QHBoxLayout()
        button_row.addWidget(self._build_button)
        button_row.addWidget(self._stop_button)
        button_row.addWidget(self._open_output_button)
        button_row.addWidget(self._open_summary_button)
        button_row.addStretch()

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self._note_label)
        main_layout.addWidget(config_group)
        main_layout.addLayout(button_row)
        main_layout.addWidget(self._create_log_group(), 1)
        self._set_running_state(False)
        self._bind_project_context()

    def _clear_target_form_rows(self) -> None:
        while self._target_form_layout.rowCount() > 0:
            self._target_form_layout.removeRow(0)
        self._task_combos = {}
        self._task_labels = {}

    def _rebuild_target_form(self, project_info: dict[str, Any] | None) -> None:
        self._clear_target_form_rows()
        tasks = get_project_attribute_tasks(project_info)
        default_values = get_project_default_smoke_target_values(project_info)
        for task in tasks:
            task_slug = str(task.get("slug") or "")
            task_label = str(task.get("display_name") or task_slug)
            class_infos = task.get("classes") or []
            combo = QComboBox()
            for class_info in class_infos:
                combo.addItem(str(class_info.get("display_name") or class_info.get("slug") or ""), str(class_info.get("slug") or ""))
            preferred_value = default_values.get(task_slug, "")
            target_index = 0
            for index in range(combo.count()):
                if combo.itemData(index) == preferred_value:
                    target_index = index
                    break
            combo.setCurrentIndex(target_index)
            combo.currentIndexChanged.connect(self._sync_output_root)
            self._task_combos[task_slug] = combo
            self._task_labels[task_slug] = task_label
            self._target_form_layout.addRow(f"{task_label}:", combo)

    def _current_target_values(self) -> dict[str, str]:
        return {
            task_slug: str(combo.currentData() or "")
            for task_slug, combo in self._task_combos.items()
            if str(combo.currentData() or "")
        }

    def _sync_output_root(self, *_args) -> None:
        target_values = self._current_target_values()
        self._output_root_edit.setText(str(get_project_smoke_test_root(self._project_info, target_values)))
        if self._smoke_context is not None:
            self._smoke_context.set_state(build_smoke_state(self._project_info, target_values))

    def _set_running_state(self, running: bool) -> None:
        self._build_button.setEnabled(not running)
        self._image_browse_button.setEnabled(not running)
        self._json_browse_button.setEnabled(not running)
        self._output_browse_button.setEnabled(not running)
        for combo in self._task_combos.values():
            combo.setEnabled(not running)
        self._stop_button.setEnabled(running)

    def _run_build(self) -> None:
        target_values = self._current_target_values()
        if self._project_info:
            script_path = AI_ROOT / "scripts" / "build_project_smoke_dataset.py"
            args = [
                "--project-config",
                str(self._project_info["config_path"]),
                "--image-dir",
                self._image_dir_edit.text().strip(),
                "--json-dir",
                self._json_dir_edit.text().strip(),
                "--output-root",
                self._output_root_edit.text().strip(),
                "--label-name",
                get_project_detection_label(self._project_info),
            ]
            for task_slug, class_slug in target_values.items():
                args.extend(["--target", f"{task_slug}={class_slug}"])
        else:
            script_path = AI_ROOT / "scripts" / "build_single_target_dataset.py"
            args = [
                "--image-dir",
                self._image_dir_edit.text().strip(),
                "--json-dir",
                self._json_dir_edit.text().strip(),
                "--output-root",
                self._output_root_edit.text().strip(),
                "--label-name",
                DEFAULT_DETECTION_LABEL_NAME,
                "--level",
                target_values.get("level", DEFAULT_SMOKE_LEVEL),
                "--resource-type",
                target_values.get("resource_type", DEFAULT_SMOKE_RESOURCE_TYPE),
                "--relation",
                target_values.get("relation", DEFAULT_SMOKE_RELATION),
            ]
        if self._ignore_attrs_check.isChecked():
            args.append("--ignore-attrs")
        if self._clear_output_check.isChecked():
            args.append("--clear-output")
        self._run_python_script(script_path, args, "生成单目标快测数据集")

    def _open_summary(self) -> None:
        summary_path = Path(self._output_root_edit.text().strip() or SMOKE_TESTS_ROOT) / "smoke_test_summary.json"
        if summary_path.exists():
            open_local_path(summary_path)
        else:
            QMessageBox.information(self, "提示", "快测汇总还不存在，请先生成一次快测数据")

    def apply_project_context(self, project_info: dict[str, Any] | None) -> None:
        detection_label = get_project_detection_label(project_info)
        self._image_dir_edit.setText(str(get_project_detection_raw_images_dir(project_info)))
        self._json_dir_edit.setText(str(get_project_detection_raw_labels_dir(project_info)))
        self._ignore_attrs_check.setText(f"忽略属性，直接把所有已框 {detection_label} 当成当前单目标")
        self._note_label.setText(
            f"这一步专门用来做单目标烟雾测试。当前项目检测标签是 {detection_label}。"
            "你可以按当前项目定义的属性选择一个具体组合，快速生成一套独立的小检测数据集。"
            "注意：这里默认只收集有 JSON 的图片；如果你想让无目标图片也参与训练，请把它们也保存成空 JSON。"
        )
        self._rebuild_target_form(project_info)
        self._sync_output_root()


class SyncTab(ProjectAwareTabBase):
    def __init__(self, project_context: ProjectContext | None = None, parent=None):
        super().__init__(project_context, parent)
        self._image_dir_edit = QLineEdit(str(DETECTION_RAW_IMAGE_DIR))
        self._json_dir_edit = QLineEdit(str(DETECTION_RAW_LABEL_DIR))
        self._detection_label_dir_edit = QLineEdit(str(DETECTION_RAW_LABEL_DIR))
        self._attr_root_edit = QLineEdit(str(ATTRIBUTE_DATA_ROOT))
        self._summary_output_edit = QLineEdit(str(ATTRIBUTE_DATA_ROOT / "sync_summary.json"))
        self._padding_spin = QDoubleSpinBox()
        self._padding_spin.setRange(0.0, 1.0)
        self._padding_spin.setDecimals(2)
        self._padding_spin.setSingleStep(0.01)
        self._padding_spin.setValue(0.06)
        self._clear_attr_raw_check = QCheckBox("同步前清空属性 raw 目录")
        self._clear_attr_raw_check.setChecked(True)

        self._sync_button = QPushButton("开始同步")
        self._sync_button.clicked.connect(self._run_sync)
        self._stop_button = QPushButton("停止")
        self._stop_button.clicked.connect(self._stop_process)
        self._open_attr_root_button = QPushButton("打开属性数据目录")
        self._open_attr_root_button.clicked.connect(lambda: open_local_path(Path(self._attr_root_edit.text().strip())))
        self._open_manifest_button = QPushButton("打开 manifest")
        self._open_manifest_button.clicked.connect(self._open_manifest)
        self._open_summary_button = QPushButton("打开同步汇总")
        self._open_summary_button.clicked.connect(self._open_summary)

        note = QLabel(
            "这一步会把 AnyLabeling 的 JSON 标注同步成两部分数据："
            "一是单类检测 txt 标签，二是等级/类型/关系三个分类任务的原始裁剪集。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #444;")

        config_group = QGroupBox("标注同步")
        config_layout = QFormLayout(config_group)
        image_row, self._image_browse_button = build_path_row(self._image_dir_edit, "浏览...", lambda: self._choose_directory(self._image_dir_edit))
        json_row, self._json_browse_button = build_path_row(self._json_dir_edit, "浏览...", lambda: self._choose_directory(self._json_dir_edit))
        det_label_row, self._detection_label_browse_button = build_path_row(self._detection_label_dir_edit, "浏览...", lambda: self._choose_directory(self._detection_label_dir_edit))
        attr_root_row, self._attr_root_browse_button = build_path_row(self._attr_root_edit, "浏览...", lambda: self._choose_directory(self._attr_root_edit))
        summary_row, self._summary_browse_button = build_path_row(self._summary_output_edit, "保存为...", lambda: self._choose_save_file(self._summary_output_edit, "保存同步汇总", "JSON 文件 (*.json)"))
        config_layout.addRow("原图目录:", image_row)
        config_layout.addRow("JSON 标签目录:", json_row)
        config_layout.addRow("检测 txt 输出目录:", det_label_row)
        config_layout.addRow("属性数据集根目录:", attr_root_row)
        config_layout.addRow("裁剪外扩比例:", self._padding_spin)
        config_layout.addRow("同步汇总输出:", summary_row)
        config_layout.addRow("", self._clear_attr_raw_check)

        button_row = QHBoxLayout()
        button_row.addWidget(self._sync_button)
        button_row.addWidget(self._stop_button)
        button_row.addWidget(self._open_attr_root_button)
        button_row.addWidget(self._open_manifest_button)
        button_row.addWidget(self._open_summary_button)
        button_row.addStretch()

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(note)
        main_layout.addWidget(config_group)
        main_layout.addLayout(button_row)
        main_layout.addWidget(self._create_log_group(), 1)
        self._set_running_state(False)
        self._bind_project_context()

    def _set_running_state(self, running: bool) -> None:
        self._sync_button.setEnabled(not running)
        self._image_browse_button.setEnabled(not running)
        self._json_browse_button.setEnabled(not running)
        self._detection_label_browse_button.setEnabled(not running)
        self._attr_root_browse_button.setEnabled(not running)
        self._summary_browse_button.setEnabled(not running)
        self._stop_button.setEnabled(running)

    def _run_sync(self) -> None:
        if self._project_info:
            script_path = AI_ROOT / "scripts" / "sync_project_annotations.py"
            args = [
                "--project-config",
                str(self._project_info["config_path"]),
                "--image-dir",
                self._image_dir_edit.text().strip(),
                "--json-dir",
                self._json_dir_edit.text().strip(),
                "--detection-label-dir",
                self._detection_label_dir_edit.text().strip(),
                "--attr-root",
                self._attr_root_edit.text().strip(),
                "--label-name",
                get_project_detection_label(self._project_info),
                "--crop-padding-ratio",
                f"{self._padding_spin.value():.2f}",
            ]
        else:
            script_path = AI_ROOT / "scripts" / "sync_resource_annotations.py"
            args = [
                "--image-dir",
                self._image_dir_edit.text().strip(),
                "--json-dir",
                self._json_dir_edit.text().strip(),
                "--detection-label-dir",
                self._detection_label_dir_edit.text().strip(),
                "--attr-root",
                self._attr_root_edit.text().strip(),
                "--label-name",
                DEFAULT_DETECTION_LABEL_NAME,
                "--crop-padding-ratio",
                f"{self._padding_spin.value():.2f}",
            ]
        summary_output = self._summary_output_edit.text().strip()
        if summary_output:
            args.extend(["--summary-output", summary_output])
        if self._clear_attr_raw_check.isChecked():
            args.append("--clear-attr-raw")
        self._run_python_script(script_path, args, "同步标注数据")

    def _open_manifest(self) -> None:
        manifest_path = Path(self._attr_root_edit.text().strip() or ATTRIBUTE_DATA_ROOT) / "manifest.csv"
        if manifest_path.exists():
            open_local_path(manifest_path)
        else:
            QMessageBox.information(self, "提示", "manifest.csv 还不存在，请先执行一次同步")

    def _open_summary(self) -> None:
        summary_path = Path(self._summary_output_edit.text().strip() or ATTRIBUTE_DATA_ROOT / "sync_summary.json")
        if summary_path.exists():
            open_local_path(summary_path)
        else:
            QMessageBox.information(self, "提示", "同步汇总还不存在，请先执行一次同步")

    def apply_project_context(self, project_info: dict[str, Any] | None) -> None:
        attr_root = get_project_attribute_root(project_info)
        self._image_dir_edit.setText(str(get_project_detection_raw_images_dir(project_info)))
        self._json_dir_edit.setText(str(get_project_detection_raw_labels_dir(project_info)))
        self._detection_label_dir_edit.setText(str(get_project_detection_raw_labels_dir(project_info)))
        self._attr_root_edit.setText(str(attr_root))
        self._summary_output_edit.setText(str(attr_root / "sync_summary.json"))


class DatasetSplitTab(ProjectAwareTabBase):
    def __init__(self, project_context: ProjectContext | None = None, smoke_context: SmokeSelectionContext | None = None, parent=None):
        super().__init__(project_context, parent)
        self._smoke_context = smoke_context
        self._source_images_edit = QLineEdit(str(get_default_smoke_root() / "raw" / "images"))
        self._source_labels_edit = QLineEdit(str(get_default_smoke_root() / "raw" / "labels"))
        self._output_root_edit = QLineEdit(str(get_default_smoke_root()))
        self._train_ratio_spin = QDoubleSpinBox()
        self._train_ratio_spin.setRange(0.0, 1.0)
        self._train_ratio_spin.setDecimals(2)
        self._train_ratio_spin.setSingleStep(0.05)
        self._train_ratio_spin.setValue(0.8)
        self._val_ratio_spin = QDoubleSpinBox()
        self._val_ratio_spin.setRange(0.0, 1.0)
        self._val_ratio_spin.setDecimals(2)
        self._val_ratio_spin.setSingleStep(0.05)
        self._val_ratio_spin.setValue(0.1)
        self._test_ratio_spin = QDoubleSpinBox()
        self._test_ratio_spin.setRange(0.0, 1.0)
        self._test_ratio_spin.setDecimals(2)
        self._test_ratio_spin.setSingleStep(0.05)
        self._test_ratio_spin.setValue(0.1)
        self._clear_output_check = QCheckBox("切分前清空 train/val/test 目录")
        self._clear_output_check.setChecked(True)

        self._split_button = QPushButton("切分检测数据")
        self._split_button.clicked.connect(self._run_split)
        self._stop_button = QPushButton("停止")
        self._stop_button.clicked.connect(self._stop_process)
        self._open_output_button = QPushButton("打开输出目录")
        self._open_output_button.clicked.connect(lambda: open_local_path(Path(self._output_root_edit.text().strip())))
        self._use_smoke_defaults_button = QPushButton("套用当前快测数据")
        self._use_smoke_defaults_button.clicked.connect(self._apply_smoke_defaults)
        self._use_full_defaults_button = QPushButton("切回完整检测数据")
        self._use_full_defaults_button.clicked.connect(self._apply_full_defaults)

        note = QLabel("如果你已经在单目标快测页生成了当前项目的快测数据，这一页可以直接套用那套路径。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #444;")

        config_group = QGroupBox("检测切分设置")
        config_layout = QFormLayout(config_group)
        images_row, self._images_browse_button = build_path_row(self._source_images_edit, "浏览...", lambda: self._choose_directory(self._source_images_edit))
        labels_row, self._labels_browse_button = build_path_row(self._source_labels_edit, "浏览...", lambda: self._choose_directory(self._source_labels_edit))
        output_row, self._output_browse_button = build_path_row(self._output_root_edit, "浏览...", lambda: self._choose_directory(self._output_root_edit))
        config_layout.addRow("原始图片目录:", images_row)
        config_layout.addRow("原始标签目录:", labels_row)
        config_layout.addRow("输出根目录:", output_row)
        config_layout.addRow("训练集比例:", self._train_ratio_spin)
        config_layout.addRow("验证集比例:", self._val_ratio_spin)
        config_layout.addRow("测试集比例:", self._test_ratio_spin)
        config_layout.addRow("", self._clear_output_check)

        button_row = QHBoxLayout()
        button_row.addWidget(self._use_smoke_defaults_button)
        button_row.addWidget(self._use_full_defaults_button)
        button_row.addWidget(self._split_button)
        button_row.addWidget(self._stop_button)
        button_row.addWidget(self._open_output_button)
        button_row.addStretch()

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(note)
        main_layout.addWidget(config_group)
        main_layout.addLayout(button_row)
        main_layout.addWidget(self._create_log_group(), 1)
        self._set_running_state(False)
        self._bind_project_context()

    def _apply_smoke_defaults(self) -> None:
        smoke_state = self._smoke_context.current_state() if self._smoke_context is not None else None
        smoke_root = Path(str(smoke_state.get("output_root"))) if smoke_state else get_default_smoke_root()
        self._source_images_edit.setText(str(smoke_root / "raw" / "images"))
        self._source_labels_edit.setText(str(smoke_root / "raw" / "labels"))
        self._output_root_edit.setText(str(smoke_root))

    def _apply_full_defaults(self) -> None:
        self._source_images_edit.setText(str(get_project_detection_raw_images_dir(self._project_info)))
        self._source_labels_edit.setText(str(get_project_detection_raw_labels_dir(self._project_info)))
        self._output_root_edit.setText(str(get_project_detection_root(self._project_info)))

    def _set_running_state(self, running: bool) -> None:
        self._split_button.setEnabled(not running)
        self._images_browse_button.setEnabled(not running)
        self._labels_browse_button.setEnabled(not running)
        self._output_browse_button.setEnabled(not running)
        self._use_smoke_defaults_button.setEnabled(not running)
        self._use_full_defaults_button.setEnabled(not running)
        self._stop_button.setEnabled(running)

    def _run_split(self) -> None:
        total = self._train_ratio_spin.value() + self._val_ratio_spin.value() + self._test_ratio_spin.value()
        if abs(total - 1.0) > 1e-6:
            QMessageBox.warning(self, "提示", "训练/验证/测试比例之和必须为 1.0")
            return

        script_path = AI_ROOT / "scripts" / "split_yolo_dataset.py"
        args = [
            "--source-images",
            self._source_images_edit.text().strip(),
            "--source-labels",
            self._source_labels_edit.text().strip(),
            "--output-root",
            self._output_root_edit.text().strip(),
            "--train-ratio",
            f"{self._train_ratio_spin.value():.2f}",
            "--val-ratio",
            f"{self._val_ratio_spin.value():.2f}",
            "--test-ratio",
            f"{self._test_ratio_spin.value():.2f}",
        ]
        if self._clear_output_check.isChecked():
            args.append("--clear-output")
        self._run_python_script(script_path, args, "切分检测数据集")

    def apply_project_context(self, project_info: dict[str, Any] | None) -> None:
        self._apply_full_defaults()


class AttributeSplitTab(ProjectAwareTabBase):
    def __init__(self, project_context: ProjectContext | None = None, parent=None):
        super().__init__(project_context, parent)
        self._task_combo = QComboBox()
        self._task_labels: dict[str, str] = {}
        self._task_combo.currentIndexChanged.connect(self._sync_task_paths)

        self._source_raw_root_edit = QLineEdit(str(get_attribute_task_raw_root("level")))
        self._output_root_edit = QLineEdit(str(get_attribute_task_root("level")))
        self._train_ratio_spin = QDoubleSpinBox()
        self._train_ratio_spin.setRange(0.0, 1.0)
        self._train_ratio_spin.setDecimals(2)
        self._train_ratio_spin.setSingleStep(0.05)
        self._train_ratio_spin.setValue(0.8)
        self._val_ratio_spin = QDoubleSpinBox()
        self._val_ratio_spin.setRange(0.0, 1.0)
        self._val_ratio_spin.setDecimals(2)
        self._val_ratio_spin.setSingleStep(0.05)
        self._val_ratio_spin.setValue(0.1)
        self._test_ratio_spin = QDoubleSpinBox()
        self._test_ratio_spin.setRange(0.0, 1.0)
        self._test_ratio_spin.setDecimals(2)
        self._test_ratio_spin.setSingleStep(0.05)
        self._test_ratio_spin.setValue(0.1)
        self._seed_spin = QSpinBox()
        self._seed_spin.setRange(0, 999999)
        self._seed_spin.setValue(42)
        self._clear_output_check = QCheckBox("切分前清空 train/val/test 目录")
        self._clear_output_check.setChecked(True)

        self._split_button = QPushButton("切分属性数据")
        self._split_button.clicked.connect(self._run_split)
        self._stop_button = QPushButton("停止")
        self._stop_button.clicked.connect(self._stop_process)
        self._open_output_button = QPushButton("打开任务目录")
        self._open_output_button.clicked.connect(lambda: open_local_path(Path(self._output_root_edit.text().strip())))
        self._open_summary_button = QPushButton("打开切分汇总")
        self._open_summary_button.clicked.connect(self._open_summary)

        config_group = QGroupBox("属性切分设置")
        config_layout = QFormLayout(config_group)
        source_row, self._source_browse_button = build_path_row(self._source_raw_root_edit, "浏览...", lambda: self._choose_directory(self._source_raw_root_edit))
        output_row, self._output_browse_button = build_path_row(self._output_root_edit, "浏览...", lambda: self._choose_directory(self._output_root_edit))
        config_layout.addRow("属性任务:", self._task_combo)
        config_layout.addRow("原始裁剪目录:", source_row)
        config_layout.addRow("任务输出目录:", output_row)
        config_layout.addRow("训练集比例:", self._train_ratio_spin)
        config_layout.addRow("验证集比例:", self._val_ratio_spin)
        config_layout.addRow("测试集比例:", self._test_ratio_spin)
        config_layout.addRow("随机种子:", self._seed_spin)
        config_layout.addRow("", self._clear_output_check)

        button_row = QHBoxLayout()
        button_row.addWidget(self._split_button)
        button_row.addWidget(self._stop_button)
        button_row.addWidget(self._open_output_button)
        button_row.addWidget(self._open_summary_button)
        button_row.addStretch()

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(config_group)
        main_layout.addLayout(button_row)
        main_layout.addWidget(self._create_log_group(), 1)
        self._set_running_state(False)
        self._bind_project_context()

    def _current_task_name(self) -> str:
        return str(self._task_combo.currentData() or "level")

    def _current_task_label(self) -> str:
        task_name = self._current_task_name()
        return self._task_labels.get(task_name, ATTRIBUTE_TASK_LABELS.get(task_name, task_name))

    def _reload_task_items(self, project_info: dict[str, Any] | None) -> None:
        current_task = self._current_task_name()
        tasks = get_project_attribute_tasks(project_info)
        self._task_labels = {str(task.get("slug") or ""): str(task.get("display_name") or task.get("slug") or "") for task in tasks}
        self._task_combo.blockSignals(True)
        self._task_combo.clear()
        for task in tasks:
            task_slug = str(task.get("slug") or "")
            task_label = str(task.get("display_name") or task_slug)
            self._task_combo.addItem(f"{task_label} ({task_slug})", task_slug)
        target_index = 0
        for index in range(self._task_combo.count()):
            if self._task_combo.itemData(index) == current_task:
                target_index = index
                break
        self._task_combo.setCurrentIndex(target_index)
        self._task_combo.blockSignals(False)
        self._sync_task_paths()

    def _sync_task_paths(self, *_args) -> None:
        task_name = self._current_task_name()
        self._source_raw_root_edit.setText(str(get_project_attribute_task_raw_root(self._project_info, task_name)))
        self._output_root_edit.setText(str(get_project_attribute_task_root(self._project_info, task_name)))

    def _set_running_state(self, running: bool) -> None:
        self._split_button.setEnabled(not running)
        self._source_browse_button.setEnabled(not running)
        self._output_browse_button.setEnabled(not running)
        self._stop_button.setEnabled(running)

    def _run_split(self) -> None:
        total = self._train_ratio_spin.value() + self._val_ratio_spin.value() + self._test_ratio_spin.value()
        if abs(total - 1.0) > 1e-6:
            QMessageBox.warning(self, "提示", "训练/验证/测试比例之和必须为 1.0")
            return

        script_path = AI_ROOT / "scripts" / "split_attribute_classification_dataset.py"
        args = [
            "--source-raw-root",
            self._source_raw_root_edit.text().strip(),
            "--output-root",
            self._output_root_edit.text().strip(),
            "--train-ratio",
            f"{self._train_ratio_spin.value():.2f}",
            "--val-ratio",
            f"{self._val_ratio_spin.value():.2f}",
            "--test-ratio",
            f"{self._test_ratio_spin.value():.2f}",
            "--seed",
            str(self._seed_spin.value()),
        ]
        if self._clear_output_check.isChecked():
            args.append("--clear-output")
        self._run_python_script(script_path, args, f"切分{self._current_task_label()}分类数据集")

    def _open_summary(self) -> None:
        summary_path = Path(self._output_root_edit.text().strip() or get_attribute_task_root(self._current_task_name())) / "split_summary.json"
        if summary_path.exists():
            open_local_path(summary_path)
        else:
            QMessageBox.information(self, "提示", "切分汇总还不存在，请先执行一次属性切分")

    def apply_project_context(self, project_info: dict[str, Any] | None) -> None:
        self._reload_task_items(project_info)


class TrainingTab(ProjectAwareTabBase):
    def __init__(self, project_context: ProjectContext | None = None, smoke_context: SmokeSelectionContext | None = None, parent=None):
        super().__init__(project_context, parent)
        self._smoke_context = smoke_context
        self._data_edit = QLineEdit(str(get_default_smoke_root() / "data.yaml"))
        self._model_edit = QLineEdit("yolov8n.pt")
        self._project_edit = QLineEdit(str(AI_ROOT / "outputs" / "train"))
        self._name_edit = QLineEdit(get_default_smoke_detection_run_name())

        self._imgsz_spin = QSpinBox()
        self._imgsz_spin.setRange(64, 4096)
        self._imgsz_spin.setSingleStep(32)
        self._imgsz_spin.setValue(640)
        self._epochs_spin = QSpinBox()
        self._epochs_spin.setRange(1, 10000)
        self._epochs_spin.setValue(120)
        self._batch_spin = QSpinBox()
        self._batch_spin.setRange(1, 1024)
        self._batch_spin.setValue(16)
        self._workers_spin = QSpinBox()
        self._workers_spin.setRange(0, 64)
        self._workers_spin.setValue(4)
        self._patience_spin = QSpinBox()
        self._patience_spin.setRange(1, 1000)
        self._patience_spin.setValue(20)
        self._close_mosaic_spin = QSpinBox()
        self._close_mosaic_spin.setRange(0, 1000)
        self._close_mosaic_spin.setValue(10)
        self._device_edit = QLineEdit("")
        self._cache_check = QCheckBox("缓存数据集")

        self._train_button = QPushButton("开始训练")
        self._train_button.clicked.connect(self._run_training)
        self._stop_button = QPushButton("停止训练")
        self._stop_button.clicked.connect(self._stop_process)
        self._open_output_button = QPushButton("打开训练输出")
        self._open_output_button.clicked.connect(lambda: open_local_path(Path(self._project_edit.text().strip())))
        self._use_smoke_defaults_button = QPushButton("套用当前快测数据")
        self._use_smoke_defaults_button.clicked.connect(self._apply_smoke_defaults)
        self._use_full_defaults_button = QPushButton("切回完整检测数据")
        self._use_full_defaults_button.clicked.connect(self._apply_full_defaults)

        self._note_label = QLabel(
            "这里训练的是单类检测模型 plot_node。你可以切回当前项目的完整检测数据，也可以套用当前单目标快测数据。"
            "训练前请确保当前 Python 环境已安装 ai_tile_mvp/requirements-ai.txt 中的依赖。"
        )
        self._note_label.setWordWrap(True)
        self._note_label.setStyleSheet("color: #444;")

        config_group = QGroupBox("检测训练参数")
        config_layout = QFormLayout(config_group)
        data_row, self._data_browse_button = build_path_row(self._data_edit, "浏览...", lambda: self._choose_open_file(self._data_edit, "选择 data.yaml", "YAML 文件 (*.yaml *.yml);;所有文件 (*.*)"))
        project_row, self._project_browse_button = build_path_row(self._project_edit, "浏览...", lambda: self._choose_directory(self._project_edit))
        config_layout.addRow("data.yaml:", data_row)
        config_layout.addRow("基础模型/权重:", self._model_edit)
        config_layout.addRow("输出目录:", project_row)
        config_layout.addRow("任务名称:", self._name_edit)
        config_layout.addRow("输入尺寸:", self._imgsz_spin)
        config_layout.addRow("训练轮数:", self._epochs_spin)
        config_layout.addRow("Batch Size:", self._batch_spin)
        config_layout.addRow("Workers:", self._workers_spin)
        config_layout.addRow("Early Stop Patience:", self._patience_spin)
        config_layout.addRow("Close Mosaic:", self._close_mosaic_spin)
        config_layout.addRow("Device:", self._device_edit)
        config_layout.addRow("", self._cache_check)

        button_row = QHBoxLayout()
        button_row.addWidget(self._use_smoke_defaults_button)
        button_row.addWidget(self._use_full_defaults_button)
        button_row.addWidget(self._train_button)
        button_row.addWidget(self._stop_button)
        button_row.addWidget(self._open_output_button)
        button_row.addStretch()

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self._note_label)
        main_layout.addWidget(config_group)
        main_layout.addLayout(button_row)
        main_layout.addWidget(self._create_log_group(), 1)
        self._set_running_state(False)
        self._bind_project_context()

    def _apply_smoke_defaults(self) -> None:
        smoke_state = self._smoke_context.current_state() if self._smoke_context is not None else None
        smoke_root = Path(str(smoke_state.get("output_root"))) if smoke_state else get_default_smoke_root()
        smoke_run_name = str(smoke_state.get("run_name")) if smoke_state else get_default_smoke_detection_run_name()
        self._data_edit.setText(str(smoke_root / "data.yaml"))
        self._project_edit.setText(str(get_project_outputs_train_dir(self._project_info)))
        self._name_edit.setText(smoke_run_name)

    def _apply_full_defaults(self) -> None:
        self._data_edit.setText(str(get_project_detection_data_yaml(self._project_info)))
        self._project_edit.setText(str(get_project_outputs_train_dir(self._project_info)))
        self._name_edit.setText(get_project_detection_run_name(self._project_info))

    def _set_running_state(self, running: bool) -> None:
        self._train_button.setEnabled(not running)
        self._data_browse_button.setEnabled(not running)
        self._project_browse_button.setEnabled(not running)
        self._use_smoke_defaults_button.setEnabled(not running)
        self._use_full_defaults_button.setEnabled(not running)
        self._stop_button.setEnabled(running)

    def _run_training(self) -> None:
        script_path = AI_ROOT / "scripts" / "train_yolo_tile.py"
        args = [
            "--data",
            self._data_edit.text().strip(),
            "--model",
            self._model_edit.text().strip() or "yolov8n.pt",
            "--imgsz",
            str(self._imgsz_spin.value()),
            "--epochs",
            str(self._epochs_spin.value()),
            "--batch",
            str(self._batch_spin.value()),
            "--workers",
            str(self._workers_spin.value()),
            "--patience",
            str(self._patience_spin.value()),
            "--close-mosaic",
            str(self._close_mosaic_spin.value()),
            "--project",
            self._project_edit.text().strip(),
            "--name",
            self._name_edit.text().strip() or FULL_DETECTION_RUN_NAME,
        ]
        device_text = self._device_edit.text().strip()
        if device_text:
            args.extend(["--device", device_text])
        if self._cache_check.isChecked():
            args.append("--cache")
        self._run_python_script(script_path, args, "训练检测模型")

    def apply_project_context(self, project_info: dict[str, Any] | None) -> None:
        self._apply_full_defaults()
        self._note_label.setText(
            f"这里训练的是单类检测模型 {get_project_detection_label(project_info)}。默认已经指向当前完整检测数据集。"
            "训练前请确保当前 Python 环境已安装 ai_tile_mvp/requirements-ai.txt 中的依赖。"
        )


class AttributeTrainingTab(ProjectAwareTabBase):
    def __init__(self, project_context: ProjectContext | None = None, parent=None):
        super().__init__(project_context, parent)
        self._task_combo = QComboBox()
        self._task_labels: dict[str, str] = {}
        self._task_combo.currentIndexChanged.connect(self._sync_task_defaults)

        self._data_root_edit = QLineEdit(str(get_attribute_task_root("level")))
        self._model_edit = QLineEdit("yolov8n-cls.pt")
        self._project_edit = QLineEdit(str(AI_ROOT / "outputs" / "train_attr"))
        self._name_edit = QLineEdit("level_yolov8n_cls")

        self._imgsz_spin = QSpinBox()
        self._imgsz_spin.setRange(64, 2048)
        self._imgsz_spin.setSingleStep(32)
        self._imgsz_spin.setValue(224)
        self._epochs_spin = QSpinBox()
        self._epochs_spin.setRange(1, 10000)
        self._epochs_spin.setValue(80)
        self._batch_spin = QSpinBox()
        self._batch_spin.setRange(1, 1024)
        self._batch_spin.setValue(32)
        self._workers_spin = QSpinBox()
        self._workers_spin.setRange(0, 64)
        self._workers_spin.setValue(4)
        self._patience_spin = QSpinBox()
        self._patience_spin.setRange(1, 1000)
        self._patience_spin.setValue(15)
        self._device_edit = QLineEdit("")
        self._cache_check = QCheckBox("缓存数据集")
        self._exist_ok_check = QCheckBox("允许覆盖同名输出目录")

        self._train_button = QPushButton("开始训练属性分类")
        self._train_button.clicked.connect(self._run_training)
        self._stop_button = QPushButton("停止训练")
        self._stop_button.clicked.connect(self._stop_process)
        self._open_output_button = QPushButton("打开训练输出")
        self._open_output_button.clicked.connect(lambda: open_local_path(Path(self._project_edit.text().strip())))

        note = QLabel("这里训练的是等级、类型、关系三个小分类器。对应任务目录里需要先有 train/val/test 三个子目录。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #444;")

        config_group = QGroupBox("属性训练参数")
        config_layout = QFormLayout(config_group)
        data_root_row, self._data_root_browse_button = build_path_row(self._data_root_edit, "浏览...", lambda: self._choose_directory(self._data_root_edit))
        project_row, self._project_browse_button = build_path_row(self._project_edit, "浏览...", lambda: self._choose_directory(self._project_edit))
        config_layout.addRow("属性任务:", self._task_combo)
        config_layout.addRow("data root:", data_root_row)
        config_layout.addRow("基础模型/权重:", self._model_edit)
        config_layout.addRow("输出目录:", project_row)
        config_layout.addRow("任务名称:", self._name_edit)
        config_layout.addRow("输入尺寸:", self._imgsz_spin)
        config_layout.addRow("训练轮数:", self._epochs_spin)
        config_layout.addRow("Batch Size:", self._batch_spin)
        config_layout.addRow("Workers:", self._workers_spin)
        config_layout.addRow("Early Stop Patience:", self._patience_spin)
        config_layout.addRow("Device:", self._device_edit)
        config_layout.addRow("", self._cache_check)
        config_layout.addRow("", self._exist_ok_check)

        button_row = QHBoxLayout()
        button_row.addWidget(self._train_button)
        button_row.addWidget(self._stop_button)
        button_row.addWidget(self._open_output_button)
        button_row.addStretch()

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(note)
        main_layout.addWidget(config_group)
        main_layout.addLayout(button_row)
        main_layout.addWidget(self._create_log_group(), 1)
        self._set_running_state(False)
        self._bind_project_context()

    def _current_task_name(self) -> str:
        return str(self._task_combo.currentData() or "level")

    def _current_task_label(self) -> str:
        task_name = self._current_task_name()
        return self._task_labels.get(task_name, ATTRIBUTE_TASK_LABELS.get(task_name, task_name))

    def _reload_task_items(self, project_info: dict[str, Any] | None) -> None:
        current_task = self._current_task_name()
        tasks = get_project_attribute_tasks(project_info)
        self._task_labels = {str(task.get("slug") or ""): str(task.get("display_name") or task.get("slug") or "") for task in tasks}
        self._task_combo.blockSignals(True)
        self._task_combo.clear()
        for task in tasks:
            task_slug = str(task.get("slug") or "")
            task_label = str(task.get("display_name") or task_slug)
            self._task_combo.addItem(f"{task_label} ({task_slug})", task_slug)
        target_index = 0
        for index in range(self._task_combo.count()):
            if self._task_combo.itemData(index) == current_task:
                target_index = index
                break
        self._task_combo.setCurrentIndex(target_index)
        self._task_combo.blockSignals(False)
        self._sync_task_defaults()

    def _sync_task_defaults(self, *_args) -> None:
        task_name = self._current_task_name()
        self._data_root_edit.setText(str(get_project_attribute_task_root(self._project_info, task_name)))
        self._project_edit.setText(str(get_project_outputs_train_attr_dir(self._project_info)))
        self._name_edit.setText(f"{task_name}_yolov8n_cls")

    def _set_running_state(self, running: bool) -> None:
        self._train_button.setEnabled(not running)
        self._data_root_browse_button.setEnabled(not running)
        self._project_browse_button.setEnabled(not running)
        self._stop_button.setEnabled(running)

    def _run_training(self) -> None:
        script_path = AI_ROOT / "scripts" / "train_yolo_attribute_cls.py"
        args = [
            "--data-root",
            self._data_root_edit.text().strip(),
            "--model",
            self._model_edit.text().strip() or "yolov8n-cls.pt",
            "--imgsz",
            str(self._imgsz_spin.value()),
            "--epochs",
            str(self._epochs_spin.value()),
            "--batch",
            str(self._batch_spin.value()),
            "--workers",
            str(self._workers_spin.value()),
            "--patience",
            str(self._patience_spin.value()),
            "--project",
            self._project_edit.text().strip(),
            "--name",
            self._name_edit.text().strip() or f"{self._current_task_name()}_yolov8n_cls",
        ]
        device_text = self._device_edit.text().strip()
        if device_text:
            args.extend(["--device", device_text])
        if self._cache_check.isChecked():
            args.append("--cache")
        if self._exist_ok_check.isChecked():
            args.append("--exist-ok")
        self._run_python_script(script_path, args, f"训练{self._current_task_label()}分类模型")

    def apply_project_context(self, project_info: dict[str, Any] | None) -> None:
        self._reload_task_items(project_info)


class ExportTab(ProjectAwareTabBase):
    def __init__(self, project_context: ProjectContext | None = None, smoke_context: SmokeSelectionContext | None = None, parent=None):
        super().__init__(project_context, parent)
        self._smoke_context = smoke_context
        self._weights_edit = QLineEdit(str(get_default_smoke_weights_path()))
        self._output_edit = QLineEdit(str(get_default_smoke_model_path()))
        self._meta_output_edit = QLineEdit("")
        self._imgsz_spin = QSpinBox()
        self._imgsz_spin.setRange(64, 4096)
        self._imgsz_spin.setSingleStep(32)
        self._imgsz_spin.setValue(640)
        self._conf_spin = QDoubleSpinBox()
        self._conf_spin.setRange(0.0, 1.0)
        self._conf_spin.setDecimals(2)
        self._conf_spin.setValue(0.35)
        self._iou_spin = QDoubleSpinBox()
        self._iou_spin.setRange(0.0, 1.0)
        self._iou_spin.setDecimals(2)
        self._iou_spin.setValue(0.50)
        self._max_detections_spin = QSpinBox()
        self._max_detections_spin.setRange(1, 10000)
        self._max_detections_spin.setValue(300)
        self._simplify_check = QCheckBox("导出后尝试简化模型")
        self._dynamic_check = QCheckBox("导出动态尺寸")
        self._half_check = QCheckBox("导出半精度")
        self._nms_check = QCheckBox("导出时内置 NMS")

        self._export_button = QPushButton("导出 ONNX")
        self._export_button.clicked.connect(self._run_export)
        self._stop_button = QPushButton("停止")
        self._stop_button.clicked.connect(self._stop_process)
        self._open_output_button = QPushButton("打开模型目录")
        self._open_output_button.clicked.connect(lambda: open_local_path(Path(self._output_edit.text().strip()).parent))
        self._use_smoke_defaults_button = QPushButton("套用当前快测数据")
        self._use_smoke_defaults_button.clicked.connect(self._apply_smoke_defaults)
        self._use_full_defaults_button = QPushButton("切回完整检测数据")
        self._use_full_defaults_button.clicked.connect(self._apply_full_defaults)

        note = QLabel("这里可以导出当前项目的完整训练产物，也可以切到当前单目标快测对应的训练产物。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #444;")

        config_group = QGroupBox("导出设置")
        config_layout = QFormLayout(config_group)
        weights_row, self._weights_browse_button = build_path_row(self._weights_edit, "浏览...", lambda: self._choose_open_file(self._weights_edit, "选择权重文件", "PyTorch 权重 (*.pt);;所有文件 (*.*)"))
        output_row, self._output_browse_button = build_path_row(self._output_edit, "保存为...", lambda: self._choose_save_file(self._output_edit, "保存 ONNX 模型", "ONNX 模型 (*.onnx)"))
        meta_row, self._meta_browse_button = build_path_row(self._meta_output_edit, "保存为...", lambda: self._choose_save_file(self._meta_output_edit, "保存模型元数据", "JSON 文件 (*.json)"))
        config_layout.addRow("权重文件:", weights_row)
        config_layout.addRow("ONNX 输出:", output_row)
        config_layout.addRow("元数据输出:", meta_row)
        config_layout.addRow("输入尺寸:", self._imgsz_spin)
        config_layout.addRow("默认置信度阈值:", self._conf_spin)
        config_layout.addRow("默认 IoU 阈值:", self._iou_spin)
        config_layout.addRow("最大检测数:", self._max_detections_spin)
        config_layout.addRow("", self._simplify_check)
        config_layout.addRow("", self._dynamic_check)
        config_layout.addRow("", self._half_check)
        config_layout.addRow("", self._nms_check)

        button_row = QHBoxLayout()
        button_row.addWidget(self._use_smoke_defaults_button)
        button_row.addWidget(self._use_full_defaults_button)
        button_row.addWidget(self._export_button)
        button_row.addWidget(self._stop_button)
        button_row.addWidget(self._open_output_button)
        button_row.addStretch()

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(note)
        main_layout.addWidget(config_group)
        main_layout.addLayout(button_row)
        main_layout.addWidget(self._create_log_group(), 1)
        self._set_running_state(False)
        self._bind_project_context()

    def _apply_smoke_defaults(self) -> None:
        smoke_state = self._smoke_context.current_state() if self._smoke_context is not None else None
        smoke_run_name = str(smoke_state.get("run_name")) if smoke_state else get_default_smoke_detection_run_name()
        self._weights_edit.setText(str(get_project_outputs_train_dir(self._project_info) / smoke_run_name / "weights" / "best.pt"))
        self._output_edit.setText(str(get_project_root(self._project_info) / "models" / "detector" / f"{smoke_run_name}_640.onnx") if self._project_info else get_default_smoke_model_path())
        self._meta_output_edit.setText("")

    def _apply_full_defaults(self) -> None:
        self._weights_edit.setText(str(get_project_detection_weights_path(self._project_info)))
        self._output_edit.setText(str(get_project_detection_model_path(self._project_info)))
        self._meta_output_edit.setText("")

    def _set_running_state(self, running: bool) -> None:
        self._export_button.setEnabled(not running)
        self._weights_browse_button.setEnabled(not running)
        self._output_browse_button.setEnabled(not running)
        self._meta_browse_button.setEnabled(not running)
        self._use_smoke_defaults_button.setEnabled(not running)
        self._use_full_defaults_button.setEnabled(not running)
        self._stop_button.setEnabled(running)

    def _run_export(self) -> None:
        script_path = AI_ROOT / "scripts" / "export_yolo_onnx.py"
        args = [
            "--weights",
            self._weights_edit.text().strip(),
            "--output",
            self._output_edit.text().strip(),
            "--meta-template",
            str(get_project_model_meta_template(self._project_info)),
            "--imgsz",
            str(self._imgsz_spin.value()),
            "--conf-threshold",
            f"{self._conf_spin.value():.2f}",
            "--iou-threshold",
            f"{self._iou_spin.value():.2f}",
            "--max-detections",
            str(self._max_detections_spin.value()),
        ]
        meta_output = self._meta_output_edit.text().strip()
        if meta_output:
            args.extend(["--meta-output", meta_output])
        if self._simplify_check.isChecked():
            args.append("--simplify")
        if self._dynamic_check.isChecked():
            args.append("--dynamic")
        if self._half_check.isChecked():
            args.append("--half")
        if self._nms_check.isChecked():
            args.append("--nms")
        self._run_python_script(script_path, args, "导出 ONNX 模型")

    def apply_project_context(self, project_info: dict[str, Any] | None) -> None:
        self._apply_full_defaults()


class BenchmarkTab(ProjectAwareTabBase):
    def __init__(self, project_context: ProjectContext | None = None, smoke_context: SmokeSelectionContext | None = None, parent=None):
        super().__init__(project_context, parent)
        self._smoke_context = smoke_context
        self._model_edit = QLineEdit(str(get_default_smoke_model_path()))
        self._meta_edit = QLineEdit(str(get_default_smoke_meta_path()))
        self._image_dir_edit = QLineEdit(str(get_default_smoke_root() / "images" / "test"))
        self._label_dir_edit = QLineEdit(str(get_default_smoke_root() / "labels" / "test"))
        self._output_dir_edit = QLineEdit(str(get_default_smoke_benchmark_output_dir()))
        self._repeat_spin = QSpinBox()
        self._repeat_spin.setRange(1, 1000)
        self._repeat_spin.setValue(10)
        self._warmup_spin = QSpinBox()
        self._warmup_spin.setRange(0, 1000)
        self._warmup_spin.setValue(3)
        self._max_detections_spin = QSpinBox()
        self._max_detections_spin.setRange(1, 10000)
        self._max_detections_spin.setValue(300)
        self._eval_iou_spin = QDoubleSpinBox()
        self._eval_iou_spin.setRange(0.1, 1.0)
        self._eval_iou_spin.setDecimals(2)
        self._eval_iou_spin.setValue(0.50)
        self._eval_with_labels_check = QCheckBox("如果提供测试标签则同时计算 precision / recall")
        self._eval_with_labels_check.setChecked(True)
        self._save_preview_check = QCheckBox("保存检测结果预览")
        self._save_preview_check.setChecked(True)

        self._benchmark_button = QPushButton("运行速度/准确率测试")
        self._benchmark_button.clicked.connect(self._run_benchmark)
        self._stop_button = QPushButton("停止")
        self._stop_button.clicked.connect(self._stop_process)
        self._open_output_button = QPushButton("打开基准输出")
        self._open_output_button.clicked.connect(lambda: open_local_path(Path(self._output_dir_edit.text().strip())))
        self._use_smoke_defaults_button = QPushButton("套用当前快测数据")
        self._use_smoke_defaults_button.clicked.connect(self._apply_smoke_defaults)
        self._use_full_defaults_button = QPushButton("切回完整检测数据")
        self._use_full_defaults_button.clicked.connect(self._apply_full_defaults)

        note = QLabel("这里可以对当前项目的完整模型做基准，也可以切到当前单目标快测模型和测试集。提供标签目录时会直接计算 precision / recall / F1。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #444;")

        config_group = QGroupBox("速度/准确率测试设置")
        config_layout = QFormLayout(config_group)
        model_row, self._model_browse_button = build_path_row(self._model_edit, "浏览...", lambda: self._choose_open_file(self._model_edit, "选择 ONNX 模型", "ONNX 模型 (*.onnx);;所有文件 (*.*)"))
        meta_row, self._meta_browse_button = build_path_row(self._meta_edit, "浏览...", lambda: self._choose_open_file(self._meta_edit, "选择模型元数据", "JSON 文件 (*.json);;所有文件 (*.*)"))
        image_dir_row, self._image_dir_browse_button = build_path_row(self._image_dir_edit, "浏览...", lambda: self._choose_directory(self._image_dir_edit))
        label_dir_row, self._label_dir_browse_button = build_path_row(self._label_dir_edit, "浏览...", lambda: self._choose_directory(self._label_dir_edit))
        output_dir_row, self._output_dir_browse_button = build_path_row(self._output_dir_edit, "浏览...", lambda: self._choose_directory(self._output_dir_edit))
        config_layout.addRow("ONNX 模型:", model_row)
        config_layout.addRow("模型元数据:", meta_row)
        config_layout.addRow("测试图片目录:", image_dir_row)
        config_layout.addRow("测试标签目录:", label_dir_row)
        config_layout.addRow("结果输出目录:", output_dir_row)
        config_layout.addRow("Warmup 次数:", self._warmup_spin)
        config_layout.addRow("Repeat 次数:", self._repeat_spin)
        config_layout.addRow("评估 IoU 阈值:", self._eval_iou_spin)
        config_layout.addRow("最大检测数:", self._max_detections_spin)
        config_layout.addRow("", self._eval_with_labels_check)
        config_layout.addRow("", self._save_preview_check)

        button_row = QHBoxLayout()
        button_row.addWidget(self._use_smoke_defaults_button)
        button_row.addWidget(self._use_full_defaults_button)
        button_row.addWidget(self._benchmark_button)
        button_row.addWidget(self._stop_button)
        button_row.addWidget(self._open_output_button)
        button_row.addStretch()

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(note)
        main_layout.addWidget(config_group)
        main_layout.addLayout(button_row)
        main_layout.addWidget(self._create_log_group(), 1)
        self._set_running_state(False)
        self._bind_project_context()

    def _apply_smoke_defaults(self) -> None:
        smoke_state = self._smoke_context.current_state() if self._smoke_context is not None else None
        smoke_root = Path(str(smoke_state.get("output_root"))) if smoke_state else get_default_smoke_root()
        smoke_run_name = str(smoke_state.get("run_name")) if smoke_state else get_default_smoke_detection_run_name()
        if self._project_info:
            self._model_edit.setText(str(get_project_root(self._project_info) / "models" / "detector" / f"{smoke_run_name}_640.onnx"))
            self._meta_edit.setText(str(get_project_root(self._project_info) / "models" / "detector" / f"{smoke_run_name}_640.json"))
            self._output_dir_edit.setText(str(get_project_outputs_benchmark_dir(self._project_info) / smoke_run_name))
        else:
            self._model_edit.setText(str(get_default_smoke_model_path()))
            self._meta_edit.setText(str(get_default_smoke_meta_path()))
            self._output_dir_edit.setText(str(get_default_smoke_benchmark_output_dir()))
        self._image_dir_edit.setText(str(smoke_root / "images" / "test"))
        self._label_dir_edit.setText(str(smoke_root / "labels" / "test"))

    def _apply_full_defaults(self) -> None:
        self._model_edit.setText(str(get_project_detection_model_path(self._project_info)))
        self._meta_edit.setText(str(get_project_detection_meta_path(self._project_info)))
        detection_root = get_project_detection_root(self._project_info)
        self._image_dir_edit.setText(str(detection_root / "images" / "test"))
        self._label_dir_edit.setText(str(detection_root / "labels" / "test"))
        self._output_dir_edit.setText(str(get_project_outputs_benchmark_dir(self._project_info)))

    def _set_running_state(self, running: bool) -> None:
        self._benchmark_button.setEnabled(not running)
        self._model_browse_button.setEnabled(not running)
        self._meta_browse_button.setEnabled(not running)
        self._image_dir_browse_button.setEnabled(not running)
        self._label_dir_browse_button.setEnabled(not running)
        self._output_dir_browse_button.setEnabled(not running)
        self._use_smoke_defaults_button.setEnabled(not running)
        self._use_full_defaults_button.setEnabled(not running)
        self._stop_button.setEnabled(running)

    def _run_benchmark(self) -> None:
        script_path = AI_ROOT / "scripts" / "benchmark_onnx_tile.py"
        args = [
            "--model",
            self._model_edit.text().strip(),
            "--meta",
            self._meta_edit.text().strip(),
            "--image-dir",
            self._image_dir_edit.text().strip(),
            "--output-dir",
            self._output_dir_edit.text().strip(),
            "--warmup",
            str(self._warmup_spin.value()),
            "--repeat",
            str(self._repeat_spin.value()),
            "--eval-iou",
            f"{self._eval_iou_spin.value():.2f}",
            "--max-detections",
            str(self._max_detections_spin.value()),
        ]
        if self._eval_with_labels_check.isChecked():
            label_dir = self._label_dir_edit.text().strip()
            if label_dir:
                args.extend(["--label-dir", label_dir])
        if not self._save_preview_check.isChecked():
            args.append("--no-save-preview")
        self._run_python_script(script_path, args, "速度/准确率测试")

    def apply_project_context(self, project_info: dict[str, Any] | None) -> None:
        self._apply_full_defaults()


class AIWorkbenchWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI 地块识别工作台")
        self.resize(1180, 860)
        self._project_context = ProjectContext(self)
        self._smoke_context = SmokeSelectionContext(self)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        intro = QLabel(
            "这是独立于主程序的 AI 工作台。你可以先在“创建项目”页生成一个独立项目目录，再进入完整流程：采样 -> 标注 -> 同步 -> 检测切分/训练 -> 属性切分/训练 -> 导出 -> 基准测试。"
            "如果你只想先验证可行性，也可以先走：标注 -> 单目标快测 -> 检测切分/训练 -> 导出 -> 基准测试。"
            "采样时你需要手动操作目标窗口，制造更多不同画面。"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("font-size: 13px; color: #333;")
        layout.addWidget(intro)

        project_bar = QGroupBox("当前项目")
        project_layout = QHBoxLayout(project_bar)
        self._project_combo = QComboBox()
        self._project_combo.currentIndexChanged.connect(self._on_project_selection_changed)
        self._refresh_projects_button = QPushButton("刷新项目列表")
        self._refresh_projects_button.clicked.connect(self._refresh_project_list)
        self._open_project_button = QPushButton("打开当前项目")
        self._open_project_button.clicked.connect(self._open_current_project)
        self._project_path_label = QLabel()
        self._project_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        project_layout.addWidget(QLabel("项目:"))
        project_layout.addWidget(self._project_combo, 1)
        project_layout.addWidget(self._refresh_projects_button)
        project_layout.addWidget(self._open_project_button)
        project_layout.addWidget(self._project_path_label, 2)
        layout.addWidget(project_bar)

        tabs = QTabWidget()
        project_creation_tab = ProjectCreationTab()
        project_creation_tab.projectCreated.connect(self._on_project_created)
        tabs.addTab(project_creation_tab, "0. 创建项目")
        tabs.addTab(SamplingTab(self._project_context), "1. 采样")
        tabs.addTab(LabelingTab(self._project_context), "2. 标注与抽检")
        tabs.addTab(SmokeTestTab(self._project_context, self._smoke_context), "3. 单目标快测")
        tabs.addTab(SyncTab(self._project_context), "4. 标注同步")
        tabs.addTab(DatasetSplitTab(self._project_context, self._smoke_context), "5. 检测切分")
        tabs.addTab(TrainingTab(self._project_context, self._smoke_context), "6. 检测训练")
        tabs.addTab(AttributeSplitTab(self._project_context), "7. 属性切分")
        tabs.addTab(AttributeTrainingTab(self._project_context), "8. 属性训练")
        tabs.addTab(ExportTab(self._project_context, self._smoke_context), "9. 导出")
        tabs.addTab(BenchmarkTab(self._project_context, self._smoke_context), "10. 基准测试")
        layout.addWidget(tabs, 1)

        self._refresh_project_list()

    def _refresh_project_list(self, selected_config_path: Path | None = None) -> None:
        previous_value = self._project_combo.currentData()
        desired_value = str(selected_config_path.resolve()) if selected_config_path else str(previous_value or "")
        self._project_combo.blockSignals(True)
        self._project_combo.clear()
        self._project_combo.addItem("默认 plot 工作区", "")
        for config_path in discover_project_config_paths():
            try:
                project_info = build_project_info(config_path)
            except Exception:
                continue
            project_meta = get_project_meta(project_info) or {}
            project_name = str(project_meta.get("project_name") or config_path.parent.name)
            project_label = f"{project_name} ({config_path.parent.name})"
            self._project_combo.addItem(project_label, str(config_path))
        target_index = 0
        for index in range(self._project_combo.count()):
            if str(self._project_combo.itemData(index) or "") == desired_value:
                target_index = index
                break
        self._project_combo.setCurrentIndex(target_index)
        self._project_combo.blockSignals(False)
        self._apply_project_selection(target_index)

    def _apply_project_selection(self, index: int) -> None:
        raw_value = str(self._project_combo.itemData(index) or "")
        if not raw_value:
            self._project_context.set_project(None)
            self._project_path_label.setText(f"当前路径: {AI_ROOT}")
            return
        config_path = Path(raw_value)
        try:
            project_info = build_project_info(config_path)
        except Exception as exc:
            QMessageBox.warning(self, "项目加载失败", f"无法加载项目配置:\n{config_path}\n\n{exc}")
            self._project_combo.blockSignals(True)
            self._project_combo.setCurrentIndex(0)
            self._project_combo.blockSignals(False)
            self._project_context.set_project(None)
            self._project_path_label.setText(f"当前路径: {AI_ROOT}")
            return
        self._project_context.set_project(project_info)
        self._project_path_label.setText(f"当前路径: {project_info['root']}")

    def _on_project_selection_changed(self, index: int) -> None:
        self._apply_project_selection(index)

    def _open_current_project(self) -> None:
        project_root = get_project_root(self._project_context.current_project())
        if project_root is None:
            open_local_path(DEFAULT_PROJECTS_ROOT if DEFAULT_PROJECTS_ROOT.exists() else AI_ROOT)
            return
        open_local_path(project_root)

    def _on_project_created(self, project_root: object) -> None:
        if not isinstance(project_root, Path):
            return
        self._refresh_project_list(project_root / PROJECT_META_FILENAME)


def main() -> int:
    app = QApplication(sys.argv)
    try:
        signal.signal(signal.SIGINT, lambda *_: app.quit())
        timer = QTimer(app)
        timer.setInterval(250)
        timer.timeout.connect(lambda: None)
        timer.start()
        app._sigint_timer = timer
    except (ValueError, AttributeError):
        pass
    window = AIWorkbenchWindow()
    window.show()
    try:
        return app.exec()
    except KeyboardInterrupt:
        window.close()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())