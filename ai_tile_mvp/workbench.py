"""AI 地块识别可视化工作台。"""

from __future__ import annotations

import json
import random
import re
import signal
import shutil
import subprocess
import sys
from copy import deepcopy
from datetime import datetime
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QPoint, QProcess, QProcessEnvironment, QRect, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QKeySequence, QPainter, QPen, QPixmap, QShortcut
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
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
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
from ai_tile_mvp.model_package import import_model_package
from ai_tile_mvp.project_paths import (
    AI_ROOT as PROJECT_PATHS_AI_ROOT,
    ATTRIBUTE_DATA_ROOT,
    ATTRIBUTE_TASK_LABELS,
    DEFAULT_ATTRIBUTES_FILE,
    DEFAULT_CHECKLIST_FILE,
    DEFAULT_DETECTION_LABEL_NAME,
    DEFAULT_LABELS_FILE,
    DEFAULT_META_TEMPLATE_FILE,
    DEFAULT_SMOKE_LEVEL,
    DEFAULT_SMOKE_RELATION,
    DEFAULT_SMOKE_RESOURCE_TYPE,
    DETECTION_RAW_IMAGE_DIR,
    DETECTION_RAW_LABEL_DIR,
    FULL_DETECTION_RUN_NAME,
    PROJECT_META_FILENAME,
    REVIEW_IMAGE_EXTENSIONS,
    SMOKE_TESTS_ROOT,
    build_project_info,
    build_project_detector_output_path,
    collect_image_files,
    discover_project_config_paths,
    get_attribute_task_root,
    get_attribute_task_raw_root,
    get_default_smoke_benchmark_output_dir,
    get_default_smoke_detection_run_name,
    get_default_smoke_meta_path,
    get_default_smoke_model_path,
    get_default_smoke_root,
    get_default_smoke_weights_path,
    get_project_attribute_root,
    get_project_attribute_task_raw_root,
    get_project_attribute_task_root,
    get_project_attribute_tasks,
    get_project_attributes_file,
    get_project_checklist_file,
    get_project_default_smoke_target_values,
    get_project_detection_data_yaml,
    get_project_detection_label,
    get_project_detection_label_aliases,
    get_project_detection_model_path,
    get_project_detection_meta_path,
    get_project_detection_raw_images_dir,
    get_project_detection_raw_labels_dir,
    get_project_detection_root,
    get_project_detection_run_name,
    get_project_detection_unconfirmed_root,
    get_project_detection_weights_path,
    get_project_label_classes_file,
    get_project_meta,
    get_project_model_meta_template,
    get_project_model_package_output_dir,
    get_project_outputs_benchmark_dir,
    get_project_outputs_label_check_dir,
    get_project_outputs_train_attr_dir,
    get_project_outputs_train_dir,
    get_project_review_classifier_task,
    get_project_review_negative_class,
    get_project_review_negative_dir,
    get_project_review_positive_class,
    get_project_review_positive_dir,
    get_project_review_task_slug,
    get_project_root,
    get_project_smoke_detection_run_name,
    get_project_smoke_test_root,
    get_project_trainable_classifier_tasks,
)
from ai_tile_mvp.project_scaffold import (
    DEFAULT_ATTRIBUTE_SPEC_TEXT,
    DEFAULT_PROJECTS_ROOT,
    DEFAULT_REVIEW_DISPLAY_NAME,
    DEFAULT_REVIEW_TASK_SLUG,
    build_default_detection_label,
    create_project_scaffold,
    parse_attribute_spec_text,
)


ANYLABELING_RELEASES_URL = "https://github.com/CVHub520/X-AnyLabeling/releases"
ANYLABELING_WORK_DIR = AI_ROOT / ".xanylabeling_workdir"
assert PROJECT_PATHS_AI_ROOT == AI_ROOT
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


class ImageSelectionWidget(QWidget):
    selectionChanged = Signal(object)
    annotationsChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._image_path: Path | None = None
        self._annotations: list[dict[str, Any]] = []
        self._active_index = -1
        self._drag_start: QPoint | None = None
        self._drag_mode = ""
        self._resize_handle = ""
        self._drag_original_rect = QRect()
        self._positive_label = "正确样本"
        self._negative_label = "错误样本"
        self.setMinimumSize(520, 360)
        self.setMouseTracking(True)

    def current_image_path(self) -> Path | None:
        return self._image_path

    def image_size_text(self) -> str:
        if self._pixmap.isNull():
            return "0 x 0"
        return f"{self._pixmap.width()} x {self._pixmap.height()}"

    def set_sample_labels(self, positive_label: str, negative_label: str) -> None:
        self._positive_label = positive_label or "正确样本"
        self._negative_label = negative_label or "错误样本"
        self.update()

    def set_image_path(self, image_path: Path | None) -> None:
        self._reset_interaction_state()
        self._annotations = []
        self._active_index = -1
        self._image_path = None
        self._pixmap = QPixmap()

        if image_path is not None and image_path.exists():
            pixmap = QPixmap(str(image_path))
            if not pixmap.isNull():
                self._image_path = image_path.resolve()
                self._pixmap = pixmap

        self.update()
        self._emit_state_changed()

    def set_annotations(self, states: list[dict[str, Any]] | None) -> None:
        self._reset_interaction_state()
        self._annotations = []
        self._active_index = -1

        if self._pixmap.isNull():
            self.update()
            self._emit_state_changed()
            return

        active_index = -1
        for state in states or []:
            if not isinstance(state, dict):
                continue
            try:
                rect = QRect(
                    int(state.get("x", 0)),
                    int(state.get("y", 0)),
                    int(state.get("w", 0)),
                    int(state.get("h", 0)),
                )
            except (TypeError, ValueError):
                continue

            normalized = self._normalized_selection_rect(rect)
            if normalized is None:
                continue

            status = str(state.get("status") or "unsaved")
            self._annotations.append(
                {
                    "rect": normalized,
                    "status": status if status in {"positive", "negative", "unsaved"} else "unsaved",
                    "saved_path": str(state.get("saved_path") or ""),
                    "saved_status": str(state.get("saved_status") or ""),
                }
            )
            if active_index < 0 and bool(state.get("active")):
                active_index = len(self._annotations) - 1

        if self._annotations:
            self._active_index = active_index if active_index >= 0 else len(self._annotations) - 1

        self.update()
        self._emit_state_changed()

    def clear_selection(self) -> None:
        if not self._has_active_annotation():
            return

        annotation = self._annotations[self._active_index]
        saved_path_text = str(annotation.get("saved_path") or "").strip()
        if saved_path_text:
            try:
                saved_path = Path(saved_path_text)
                if saved_path.exists():
                    saved_path.unlink()
            except OSError:
                pass

        del self._annotations[self._active_index]
        if self._annotations:
            self._active_index = min(self._active_index, len(self._annotations) - 1)
        else:
            self._active_index = -1

        self._reset_interaction_state()
        self.update()
        self._emit_state_changed()

    def selection_rect(self) -> QRect | None:
        annotation = self._active_annotation()
        if annotation is None:
            return None
        return self._normalized_selection_rect(annotation["rect"])

    def active_annotation_index(self) -> int:
        return self._active_index

    def set_active_annotation_index(self, index: int) -> None:
        if not self._annotations:
            if self._active_index != -1:
                self._active_index = -1
                self.update()
                self._emit_state_changed()
            return

        target_index = int(index)
        if target_index < 0 or target_index >= len(self._annotations):
            target_index = -1
        if target_index == self._active_index:
            return

        self._active_index = target_index
        self.update()
        self._emit_state_changed()

    def active_selection_info(self) -> dict[str, Any] | None:
        selection = self.selection_rect()
        annotation = self._active_annotation()
        if selection is None or annotation is None:
            return None
        return {
            "index": self._active_index,
            "total": len(self._annotations),
            "status": str(annotation.get("status") or "unsaved"),
            "saved_path": str(annotation.get("saved_path") or ""),
            "saved_status": str(annotation.get("saved_status") or ""),
            "rect": QRect(selection),
        }

    def annotation_states(self) -> list[dict[str, Any]]:
        states: list[dict[str, Any]] = []
        for index, annotation in enumerate(self._annotations):
            rect = self._normalized_selection_rect(annotation.get("rect"))
            if rect is None:
                continue
            states.append(
                {
                    "x": rect.x(),
                    "y": rect.y(),
                    "w": rect.width(),
                    "h": rect.height(),
                    "status": str(annotation.get("status") or "unsaved"),
                    "active": index == self._active_index,
                    "saved_path": str(annotation.get("saved_path") or ""),
                    "saved_status": str(annotation.get("saved_status") or ""),
                }
            )
        return states

    def save_selection(self, output_path: Path, status: str | None = None) -> bool:
        selection = self.selection_rect()
        if selection is None or self._pixmap.isNull():
            return False
        annotation = self._active_annotation()
        previous_path_text = str(annotation.get("saved_path") or "").strip() if annotation is not None else ""
        if previous_path_text:
            try:
                previous_path = Path(previous_path_text)
                same_path = previous_path.resolve() == output_path.resolve()
            except OSError:
                previous_path = Path(previous_path_text)
                same_path = previous_path == output_path
            if previous_path.exists() and not same_path:
                try:
                    previous_path.unlink()
                except OSError:
                    return False
        output_path.parent.mkdir(parents=True, exist_ok=True)
        crop = self._pixmap.copy(selection)
        saved = crop.save(str(output_path), "PNG")
        if saved and status in {"positive", "negative"}:
            if annotation is not None:
                annotation["status"] = status
                annotation["saved_path"] = str(output_path)
                annotation["saved_status"] = status
                self.update()
                self._emit_state_changed()
        return saved

    def _emit_state_changed(self) -> None:
        self.selectionChanged.emit(self.selection_rect())
        self.annotationsChanged.emit(self.annotation_states())

    def _reset_interaction_state(self) -> None:
        self._drag_start = None
        self._drag_mode = ""
        self._resize_handle = ""
        self._drag_original_rect = QRect()
        self.unsetCursor()

    def _has_active_annotation(self) -> bool:
        return 0 <= self._active_index < len(self._annotations)

    def _active_annotation(self) -> dict[str, Any] | None:
        if not self._has_active_annotation():
            return None
        return self._annotations[self._active_index]

    def _image_bounds(self) -> QRect:
        if self._pixmap.isNull():
            return QRect()
        return QRect(0, 0, self._pixmap.width(), self._pixmap.height())

    def _bounded_rect(self, rect: QRect | None) -> QRect:
        if self._pixmap.isNull() or rect is None or rect.isNull():
            return QRect()
        return rect.normalized().intersected(self._image_bounds())

    def _normalized_selection_rect(self, rect: QRect | None) -> QRect | None:
        normalized = self._bounded_rect(rect)
        if normalized.isNull() or normalized.width() < 4 or normalized.height() < 4:
            return None
        return normalized

    def _status_text(self, status: str) -> str:
        if status == "positive":
            return self._positive_label
        if status == "negative":
            return self._negative_label
        return "未保存"

    def _status_colors(self, status: str) -> tuple[QColor, QColor, QColor]:
        if status == "positive":
            return QColor(56, 176, 0, 52), QColor(78, 201, 76), QColor(45, 122, 37, 220)
        if status == "negative":
            return QColor(220, 68, 55, 52), QColor(231, 98, 84), QColor(168, 54, 43, 220)
        return QColor(255, 174, 0, 44), QColor(255, 196, 66), QColor(190, 126, 0, 220)

    @staticmethod
    def _handle_size() -> int:
        return 10

    def _handle_rects(self, rect: QRect) -> dict[str, QRect]:
        size = self._handle_size()
        half = size // 2
        points = {
            "top_left": rect.topLeft(),
            "top_right": rect.topRight(),
            "bottom_left": rect.bottomLeft(),
            "bottom_right": rect.bottomRight(),
        }
        return {
            handle: QRect(point.x() - half, point.y() - half, size, size)
            for handle, point in points.items()
        }

    def _hit_test(self, point: QPoint) -> tuple[int, str]:
        if self._pixmap.isNull() or self._display_rect().isNull():
            return -1, ""

        for index in range(len(self._annotations) - 1, -1, -1):
            annotation = self._annotations[index]
            rect = self._normalized_selection_rect(annotation.get("rect"))
            if rect is None:
                continue
            overlay_rect = self._image_rect_to_display_rect(rect)
            if overlay_rect.isNull():
                continue

            for handle, handle_rect in self._handle_rects(overlay_rect).items():
                if handle_rect.contains(point):
                    return index, handle

            if overlay_rect.contains(point):
                return index, "move"

        return -1, ""

    def _cursor_for_hit(self, hit_type: str) -> Qt.CursorShape:
        if hit_type in {"top_left", "bottom_right"}:
            return Qt.CursorShape.SizeFDiagCursor
        if hit_type in {"top_right", "bottom_left"}:
            return Qt.CursorShape.SizeBDiagCursor
        if hit_type == "move":
            return Qt.CursorShape.SizeAllCursor
        return Qt.CursorShape.CrossCursor

    def _update_hover_cursor(self, point: QPoint) -> None:
        if self._pixmap.isNull():
            self.unsetCursor()
            return

        index, hit_type = self._hit_test(point)
        if index >= 0:
            self.setCursor(self._cursor_for_hit(hit_type))
            return
        if self._display_rect().contains(point):
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        self.unsetCursor()

    def _move_rect(self, rect: QRect, delta: QPoint) -> QRect:
        if self._pixmap.isNull():
            return QRect()
        width = rect.width()
        height = rect.height()
        max_left = max(0, self._pixmap.width() - width)
        max_top = max(0, self._pixmap.height() - height)
        left = min(max(rect.x() + delta.x(), 0), max_left)
        top = min(max(rect.y() + delta.y(), 0), max_top)
        return QRect(left, top, width, height)

    def _resize_rect(self, rect: QRect, handle: str, point: QPoint) -> QRect:
        if self._pixmap.isNull():
            return QRect()

        min_size = 4
        max_right = self._pixmap.width()
        max_bottom = self._pixmap.height()
        left = rect.left()
        top = rect.top()
        right = rect.right() + 1
        bottom = rect.bottom() + 1

        if handle == "top_left":
            left = min(max(point.x(), 0), right - min_size)
            top = min(max(point.y(), 0), bottom - min_size)
        elif handle == "top_right":
            right = max(min(point.x() + 1, max_right), left + min_size)
            top = min(max(point.y(), 0), bottom - min_size)
        elif handle == "bottom_left":
            left = min(max(point.x(), 0), right - min_size)
            bottom = max(min(point.y() + 1, max_bottom), top + min_size)
        elif handle == "bottom_right":
            right = max(min(point.x() + 1, max_right), left + min_size)
            bottom = max(min(point.y() + 1, max_bottom), top + min_size)

        return QRect(left, top, right - left, bottom - top)

    def _display_rect(self) -> QRect:
        if self._pixmap.isNull():
            return QRect()
        area = self.rect().adjusted(12, 12, -12, -12)
        if area.width() <= 0 or area.height() <= 0:
            return QRect()

        scale = min(area.width() / max(1, self._pixmap.width()), area.height() / max(1, self._pixmap.height()))
        width = max(1, int(self._pixmap.width() * scale))
        height = max(1, int(self._pixmap.height() * scale))
        x = area.x() + max(0, (area.width() - width) // 2)
        y = area.y() + max(0, (area.height() - height) // 2)
        return QRect(x, y, width, height)

    def _clamp_to_display(self, point: QPoint) -> QPoint:
        display_rect = self._display_rect()
        if display_rect.isNull():
            return point
        return QPoint(
            min(max(point.x(), display_rect.left()), display_rect.right()),
            min(max(point.y(), display_rect.top()), display_rect.bottom()),
        )

    def _display_point_to_image_point(self, point: QPoint) -> QPoint | None:
        if self._pixmap.isNull():
            return None
        display_rect = self._display_rect()
        if display_rect.isNull() or not display_rect.contains(point):
            return None

        relative_x = (point.x() - display_rect.x()) / max(1, display_rect.width())
        relative_y = (point.y() - display_rect.y()) / max(1, display_rect.height())
        image_x = int(round(relative_x * max(0, self._pixmap.width() - 1)))
        image_y = int(round(relative_y * max(0, self._pixmap.height() - 1)))
        return QPoint(
            min(max(image_x, 0), max(0, self._pixmap.width() - 1)),
            min(max(image_y, 0), max(0, self._pixmap.height() - 1)),
        )

    def _image_rect_to_display_rect(self, rect: QRect) -> QRect:
        display_rect = self._display_rect()
        if display_rect.isNull() or self._pixmap.isNull():
            return QRect()

        left = display_rect.x() + int(rect.left() * display_rect.width() / max(1, self._pixmap.width()))
        top = display_rect.y() + int(rect.top() * display_rect.height() / max(1, self._pixmap.height()))
        right = display_rect.x() + int((rect.right() + 1) * display_rect.width() / max(1, self._pixmap.width()))
        bottom = display_rect.y() + int((rect.bottom() + 1) * display_rect.height() / max(1, self._pixmap.height()))
        return QRect(left, top, max(1, right - left), max(1, bottom - top))

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(22, 22, 22))

        if self._pixmap.isNull():
            painter.setPen(QColor(190, 190, 190))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "左侧选择图片后，在这里拖拽框选区域\n左键可连续框多个区域，拖四角可调大小，右键可删除当前框",
            )
            return

        display_rect = self._display_rect()
        painter.drawPixmap(display_rect, self._pixmap)
        painter.setPen(QPen(QColor(110, 110, 110), 1, Qt.PenStyle.DashLine))
        painter.drawRect(display_rect.adjusted(0, 0, -1, -1))

        for index, annotation in enumerate(self._annotations):
            selection = self._normalized_selection_rect(annotation.get("rect"))
            if selection is None:
                continue

            overlay_rect = self._image_rect_to_display_rect(selection)
            if overlay_rect.isNull():
                continue

            fill_color, border_color, label_color = self._status_colors(str(annotation.get("status") or "unsaved"))
            painter.fillRect(overlay_rect, fill_color)
            painter.setPen(QPen(border_color, 3 if index == self._active_index else 2))
            painter.drawRect(overlay_rect)

            label_text = f"{index + 1}. {self._status_text(str(annotation.get('status') or 'unsaved'))}"
            metrics = painter.fontMetrics()
            label_width = min(
                max(metrics.horizontalAdvance(label_text) + 14, 60),
                max(60, display_rect.right() - overlay_rect.x() + 1),
            )
            label_height = metrics.height() + 6
            label_top = overlay_rect.y() - label_height
            if label_top < display_rect.y():
                label_top = overlay_rect.y()
            label_rect = QRect(overlay_rect.x(), label_top, label_width, label_height)

            painter.fillRect(label_rect, label_color)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(
                label_rect.adjusted(6, 0, -6, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label_text,
            )

            if index == self._active_index:
                painter.setBrush(QColor(255, 255, 255))
                painter.setPen(QPen(border_color, 1))
                for handle_rect in self._handle_rects(overlay_rect).values():
                    painter.drawRect(handle_rect)
                painter.setBrush(Qt.BrushStyle.NoBrush)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            point = event.position().toPoint()
            index, _hit_type = self._hit_test(point)
            if index >= 0:
                self._active_index = index
                self.clear_selection()
            return

        if event.button() != Qt.MouseButton.LeftButton or self._pixmap.isNull():
            return

        point = event.position().toPoint()
        mapped = self._display_point_to_image_point(point)
        if mapped is None:
            return

        index, hit_type = self._hit_test(point)
        if index >= 0:
            self._active_index = index
            self._drag_start = mapped
            self._drag_mode = "move" if hit_type == "move" else "resize"
            self._resize_handle = "" if hit_type == "move" else hit_type
            self._drag_original_rect = QRect(self._annotations[index]["rect"])
            self.update()
            self._emit_state_changed()
            return

        self._drag_start = mapped
        self._drag_mode = "draw"
        self._resize_handle = ""
        self._drag_original_rect = QRect(mapped, mapped)
        self._annotations.append({"rect": QRect(mapped, mapped), "status": "unsaved"})
        self._active_index = len(self._annotations) - 1
        self.update()
        self._emit_state_changed()

    def mouseMoveEvent(self, event) -> None:
        if self._pixmap.isNull():
            return

        point = event.position().toPoint()
        if self._drag_start is None or not self._drag_mode:
            self._update_hover_cursor(point)
            return

        point = self._clamp_to_display(point)
        mapped = self._display_point_to_image_point(point)
        if mapped is None:
            return

        annotation = self._active_annotation()
        if annotation is None:
            return

        next_rect = QRect(annotation["rect"])
        if self._drag_mode == "draw":
            next_rect = self._bounded_rect(QRect(self._drag_start, mapped))
        elif self._drag_mode == "move":
            next_rect = self._move_rect(self._drag_original_rect, mapped - self._drag_start)
        elif self._drag_mode == "resize":
            next_rect = self._resize_rect(self._drag_original_rect, self._resize_handle, mapped)

        if next_rect == annotation.get("rect"):
            return

        annotation["rect"] = next_rect
        if self._drag_mode in {"move", "resize"} and annotation.get("status") != "unsaved":
            annotation["status"] = "unsaved"
        self.update()
        self._emit_state_changed()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._drag_start is None or not self._drag_mode:
            return

        if self._drag_mode == "draw" and self.selection_rect() is None and self._has_active_annotation():
            del self._annotations[self._active_index]
            if self._annotations:
                self._active_index = len(self._annotations) - 1
            else:
                self._active_index = -1

        self._reset_interaction_state()
        self.update()
        self._update_hover_cursor(event.position().toPoint())
        self._emit_state_changed()


class ReviewImageListWidget(QListWidget):
    imagePathsDropped = Signal(object)
    pasteRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(False)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    @staticmethod
    def _extract_local_paths(mime_data) -> list[str]:
        if not mime_data.hasUrls():
            return []
        paths: list[str] = []
        for url in mime_data.urls():
            local_path = url.toLocalFile()
            if local_path:
                paths.append(local_path)
        return paths

    def dragEnterEvent(self, event) -> None:
        if self._extract_local_paths(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self._extract_local_paths(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        paths = self._extract_local_paths(event.mimeData())
        if paths:
            self.imagePathsDropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Paste):
            self.pasteRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

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
        self._overwrite_check = QCheckBox("允许覆盖同名项目目录里的已生成文件")
        self._open_after_create_check = QCheckBox("创建/导入后自动打开项目目录")
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
        self._import_package_button = QPushButton("导入模型包")
        self._import_package_button.clicked.connect(self._import_model_package)
        self._open_project_button = QPushButton("打开项目目录")
        self._open_project_button.clicked.connect(self._open_project_root)

        note = QLabel(
            "这里用来创建独立 AI 训练项目。项目名例如 test1，创建后会在该目录下生成 configs、datasets、models、outputs、scripts、README 等整套文件。"
            "现在改成表格编辑属性。左列填属性名，右列填可选值列表。"
            "如果你想手动指定 slug，也支持在单元格里写“属性名=>task_slug”或“值=>slug”。"
            "如果别人已经给了你 .zip 或 .gaimodel.json 模型包，也可以直接点下面的“导入模型包”，工作台会自动解压、复制到项目目录并刷新项目列表。"
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
        button_row.addWidget(self._import_package_button)
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

    def _import_model_package(self) -> None:
        package_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择模型包",
            self._base_dir_edit.text().strip() or str(DEFAULT_PROJECTS_ROOT),
            "AI 模型包 (*.zip *.gaimodel.json);;ZIP 压缩包 (*.zip);;模型包清单 (*.gaimodel.json);;项目配置 (*.json);;所有文件 (*.*)",
        )
        if not package_path:
            return

        self._log_edit.clear()
        self._status_label.setText("状态: 导入中")
        self._set_running_state(True)
        try:
            result = import_model_package(
                package_path,
                self._base_dir_edit.text().strip() or str(DEFAULT_PROJECTS_ROOT),
                allow_overwrite=self._overwrite_check.isChecked(),
            )
        except Exception as exc:
            self._status_label.setText("状态: 导入失败")
            self._append_log(f"导入模型包失败: {exc}\n")
            QMessageBox.critical(self, "导入失败", str(exc))
            self._set_running_state(False)
            return

        project_root = Path(result["project_root"])
        project_meta = result["project_meta"]
        warnings = list(result.get("warnings") or [])

        self._status_label.setText("状态: 已导入")
        self._append_log(f"模型包来源: {result['source_path']}\n")
        self._append_log(f"导入方式: {result['source_type']}\n")
        self._append_log(f"项目目录: {project_root}\n")
        self._append_log(f"项目名: {project_meta.get('project_name') or project_root.name}\n")
        self._append_log(f"属性任务数: {len(project_meta.get('attribute_tasks') or [])}\n")
        if warnings:
            self._append_log("\n导入警告:\n")
            for item in warnings:
                self._append_log(f"- {item}\n")

        self._set_running_state(False)
        self.projectCreated.emit(project_root)
        if self._open_after_create_check.isChecked():
            open_local_path(project_root)
        QMessageBox.information(
            self,
            "导入完成",
            f"模型包已导入:\n{project_root}\n\n"
            f"项目名: {project_meta.get('project_name') or project_root.name}\n"
            f"属性任务数: {len(project_meta.get('attribute_tasks') or [])}",
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
        self._import_package_button.setEnabled(not running)
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
            "像树林、石头堆、道路纹理这类容易误检成目标候选的区域，不要单独画负类框；正确做法是保留整张图，只标真正的目标框，"
            "如果整张图都没有目标，也保存一个空 JSON，让它在同步后生成空 txt，作为困难负样本参与训练。"
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


class ReviewCollectionTab(ProjectAwareTabBase):
    def __init__(self, project_context: ProjectContext | None = None, parent=None):
        super().__init__(project_context, parent)
        self._image_annotation_states: dict[str, list[dict[str, Any]]] = {}
        self._file_item_label_role = int(Qt.ItemDataRole.UserRole) + 1
        self._annotation_item_index_role = int(Qt.ItemDataRole.UserRole) + 2
        self._source_dir_edit = QLineEdit(str(get_project_detection_raw_images_dir(None)))
        self._positive_dir_edit = QLineEdit(str(get_project_review_positive_dir(None)))
        self._negative_dir_edit = QLineEdit(str(get_project_review_negative_dir(None)))
        self._task_info_label = QLabel(f"当前复检任务: {DEFAULT_REVIEW_TASK_SLUG}")
        self._task_info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._positive_seed_task_combo = QComboBox()
        self._positive_seed_limit_spin = QSpinBox()
        self._positive_seed_limit_spin.setRange(0, 999999)
        self._positive_seed_limit_spin.setValue(0)
        self._positive_seed_limit_spin.setSpecialValueText("全部")
        self._positive_seed_limit_spin.setMinimumWidth(88)
        self._positive_seed_limit_spin.setToolTip("0 表示导入全部；大于 0 时按数量导入")
        self._positive_seed_random_check = QCheckBox("随机抽样")
        self._positive_seed_random_check.setChecked(True)
        self._positive_seed_import_button = QPushButton("导入已有正确样本")
        self._positive_seed_import_button.clicked.connect(self._import_existing_positive_samples)

        self._file_list = ReviewImageListWidget()
        self._file_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._file_list.currentItemChanged.connect(self._on_current_image_changed)
        self._file_list.imagePathsDropped.connect(self._import_dropped_paths)
        self._file_list.pasteRequested.connect(self._paste_from_clipboard)

        self._image_view = ImageSelectionWidget()
        self._image_view.selectionChanged.connect(self._on_selection_changed)
        self._image_view.annotationsChanged.connect(self._on_annotations_changed)

        self._image_info_label = QLabel("当前图片: 无")
        self._selection_info_label = QLabel("当前框选: 无")
        self._annotation_list = QListWidget()
        self._annotation_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._annotation_list.setMinimumHeight(120)
        self._annotation_list.setMinimumWidth(220)
        self._annotation_list.currentItemChanged.connect(self._on_current_annotation_item_changed)
        self._annotation_filter_combo = QComboBox()
        self._annotation_filter_combo.setMinimumWidth(150)
        self._annotation_filter_combo.currentIndexChanged.connect(self._refresh_annotation_list)
        self._annotation_delete_button = QPushButton("删除选中框")
        self._annotation_delete_button.clicked.connect(self._image_view.clear_selection)
        self._dataset_info_label = QLabel("源图 0 张 | 正确样本 0 张 | 错误样本 0 张")

        self._refresh_button = QPushButton("刷新图片列表")
        self._refresh_button.clicked.connect(self._refresh_image_list)
        self._paste_button = QPushButton("粘贴剪贴板")
        self._paste_button.clicked.connect(self._paste_from_clipboard)
        self._paste_shortcut = QShortcut(QKeySequence.StandardKey.Paste, self)
        self._paste_shortcut.activated.connect(self._paste_from_clipboard)
        self._open_source_button = QPushButton("打开截图目录")
        self._open_source_button.clicked.connect(lambda: open_local_path(Path(self._source_dir_edit.text().strip() or AI_ROOT)))
        self._open_current_image_button = QPushButton("打开当前图片")
        self._open_current_image_button.clicked.connect(self._open_current_image)
        self._open_positive_button = QPushButton("打开正确样本目录")
        self._open_positive_button.clicked.connect(lambda: open_local_path(self._sample_directory("positive")))
        self._open_negative_button = QPushButton("打开错误样本目录")
        self._open_negative_button.clicked.connect(lambda: open_local_path(self._sample_directory("negative")))
        self._prev_button = QPushButton("上一张")
        self._prev_button.clicked.connect(lambda: self._select_relative_image(-1))
        self._next_button = QPushButton("下一张")
        self._next_button.clicked.connect(lambda: self._select_relative_image(1))
        self._clear_selection_button = QPushButton("删除当前框")
        self._clear_selection_button.clicked.connect(self._image_view.clear_selection)
        self._save_positive_button = QPushButton("保存为正确样本")
        self._save_positive_button.clicked.connect(lambda: self._save_current_selection("positive"))
        self._save_negative_button = QPushButton("保存为错误样本")
        self._save_negative_button.clicked.connect(lambda: self._save_current_selection("negative"))
        self._auto_next_check = QCheckBox("当前图处理完后自动切下一张")
        self._auto_next_check.setChecked(False)

        self._note_label = QLabel()
        self._note_label.setWordWrap(True)
        self._note_label.setStyleSheet("color: #444;")

        source_row, self._source_browse_button = build_path_row(
            self._source_dir_edit,
            "浏览...",
            self._choose_source_dir,
        )
        positive_row, self._positive_browse_button = build_path_row(
            self._positive_dir_edit,
            "浏览...",
            lambda: self._choose_directory(self._positive_dir_edit),
        )
        negative_row, self._negative_browse_button = build_path_row(
            self._negative_dir_edit,
            "浏览...",
            lambda: self._choose_directory(self._negative_dir_edit),
        )

        self._positive_dir_label = QLabel("正确样本输出目录:")
        self._negative_dir_label = QLabel("错误样本输出目录:")
        positive_seed_row = QHBoxLayout()
        positive_seed_row.setContentsMargins(0, 0, 0, 0)
        positive_seed_row.setSpacing(8)
        positive_seed_row.addWidget(self._positive_seed_task_combo, 1)
        positive_seed_row.addWidget(QLabel("数量:"))
        positive_seed_row.addWidget(self._positive_seed_limit_spin)
        positive_seed_row.addWidget(self._positive_seed_random_check)
        positive_seed_row.addWidget(self._positive_seed_import_button)

        config_group = QGroupBox("复检数据采集")
        config_layout = QFormLayout(config_group)
        config_layout.addRow("截图目录:", source_row)
        config_layout.addRow(self._positive_dir_label, positive_row)
        config_layout.addRow(self._negative_dir_label, negative_row)
        config_layout.addRow("复用已有正样本:", positive_seed_row)
        config_layout.addRow("任务信息:", self._task_info_label)

        top_button_row = QHBoxLayout()
        top_button_row.addWidget(self._refresh_button)
        top_button_row.addWidget(self._paste_button)
        top_button_row.addWidget(self._open_source_button)
        top_button_row.addWidget(self._open_positive_button)
        top_button_row.addWidget(self._open_negative_button)
        top_button_row.addStretch()

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("截图列表（来自截图目录）"))
        left_layout.addWidget(self._file_list, 1)
        nav_row = QHBoxLayout()
        nav_row.addWidget(self._prev_button)
        nav_row.addWidget(self._next_button)
        nav_row.addWidget(self._open_current_image_button)
        left_layout.addLayout(nav_row)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self._dataset_info_label)
        right_layout.addWidget(self._image_info_label)
        right_layout.addWidget(self._selection_info_label)
        annotation_toolbar = QHBoxLayout()
        annotation_toolbar.addWidget(QLabel("当前图片的框列表"))
        annotation_toolbar.addStretch()
        annotation_toolbar.addWidget(QLabel("筛选:"))
        annotation_toolbar.addWidget(self._annotation_filter_combo)
        annotation_toolbar.addWidget(self._annotation_delete_button)

        annotation_panel = QWidget()
        annotation_panel.setMinimumWidth(220)
        annotation_panel.setMaximumWidth(340)
        annotation_layout = QVBoxLayout(annotation_panel)
        annotation_layout.setContentsMargins(0, 0, 0, 0)
        annotation_layout.setSpacing(6)
        annotation_layout.addLayout(annotation_toolbar)
        annotation_layout.addWidget(self._annotation_list, 1)

        self._viewer_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._viewer_splitter.addWidget(self._image_view)
        self._viewer_splitter.addWidget(annotation_panel)
        self._viewer_splitter.setStretchFactor(0, 1)
        self._viewer_splitter.setStretchFactor(1, 0)
        self._viewer_splitter.setSizes([820, 280])
        right_layout.addWidget(self._viewer_splitter, 1)
        action_row = QHBoxLayout()
        action_row.addWidget(self._clear_selection_button)
        action_row.addWidget(self._save_positive_button)
        action_row.addWidget(self._save_negative_button)
        action_row.addWidget(self._auto_next_check)
        action_row.addStretch()
        right_layout.addLayout(action_row)

        splitter = QSplitter()
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self._note_label)
        main_layout.addWidget(config_group)
        main_layout.addLayout(top_button_row)
        main_layout.addWidget(splitter, 1)
        main_layout.addWidget(self._create_log_group("采集日志"), 1)
        self._status_label.setText("状态: 等待加载图片")
        self._bind_project_context()

    def _choose_source_dir(self) -> None:
        self._choose_directory(self._source_dir_edit)
        self._refresh_image_list()

    def _review_task_display(self) -> str:
        review_task = get_project_review_classifier_task(self._project_info)
        if review_task is None:
            return f"{DEFAULT_REVIEW_DISPLAY_NAME} ({DEFAULT_REVIEW_TASK_SLUG})"
        display_name = str(review_task.get("display_name") or DEFAULT_REVIEW_DISPLAY_NAME)
        task_slug = str(review_task.get("slug") or DEFAULT_REVIEW_TASK_SLUG)
        return f"{display_name} ({task_slug})"

    def _sample_display_name(self, role: str) -> str:
        class_info = get_project_review_positive_class(self._project_info) if role == "positive" else get_project_review_negative_class(self._project_info)
        fallback = "正确样本" if role == "positive" else "错误样本"
        return str(class_info.get("display_name") or fallback)

    def _sample_slug(self, role: str) -> str:
        class_info = get_project_review_positive_class(self._project_info) if role == "positive" else get_project_review_negative_class(self._project_info)
        fallback = "positive" if role == "positive" else "negative"
        return str(class_info.get("slug") or fallback)

    def _sample_directory(self, role: str) -> Path:
        if role == "positive":
            return Path(self._positive_dir_edit.text().strip() or get_project_review_positive_dir(self._project_info))
        return Path(self._negative_dir_edit.text().strip() or get_project_review_negative_dir(self._project_info))

    def _refresh_review_ui_texts(self) -> None:
        positive_name = self._sample_display_name("positive")
        negative_name = self._sample_display_name("negative")
        task_slug = get_project_review_task_slug(self._project_info)
        positive_slug = self._sample_slug("positive")
        negative_slug = self._sample_slug("negative")

        self._open_positive_button.setText(f"打开{positive_name}目录")
        self._open_negative_button.setText(f"打开{negative_name}目录")
        self._save_positive_button.setText(f"保存为{positive_name}")
        self._save_negative_button.setText(f"保存为{negative_name}")
        self._positive_seed_import_button.setText(f"导入已有{positive_name}")
        self._positive_dir_label.setText(f"{positive_name}输出目录:")
        self._negative_dir_label.setText(f"{negative_name}输出目录:")
        self._refresh_annotation_filter_items()
        self._note_label.setText(
            f"左侧选图，右侧支持多框、拖动、缩放；图片列表会标记已存/待存数量，框列表支持按未保存/{positive_name}/{negative_name}筛选。"
            f"保存后会写入 {task_slug}/raw/{positive_slug} 或 {task_slug}/raw/{negative_slug}，切回图片会自动回显已保存框；也支持拖图、Ctrl+V 和“导入已有{positive_name}”。"
        )
        self._image_view.set_sample_labels(positive_name, negative_name)

    def _refresh_annotation_filter_items(self) -> None:
        current_value = str(self._annotation_filter_combo.currentData() or "all")
        positive_name = self._sample_display_name("positive")
        negative_name = self._sample_display_name("negative")

        self._annotation_filter_combo.blockSignals(True)
        self._annotation_filter_combo.clear()
        self._annotation_filter_combo.addItem("全部框", "all")
        self._annotation_filter_combo.addItem("只看未保存", "unsaved")
        self._annotation_filter_combo.addItem(f"只看{positive_name}", "positive")
        self._annotation_filter_combo.addItem(f"只看{negative_name}", "negative")

        target_index = 0
        for index in range(self._annotation_filter_combo.count()):
            if self._annotation_filter_combo.itemData(index) == current_value:
                target_index = index
                break
        self._annotation_filter_combo.setCurrentIndex(target_index)
        self._annotation_filter_combo.blockSignals(False)

    def _reload_positive_seed_task_items(self) -> None:
        current_task = str(self._positive_seed_task_combo.currentData() or "").strip()
        tasks = get_project_attribute_tasks(self._project_info)

        self._positive_seed_task_combo.blockSignals(True)
        self._positive_seed_task_combo.clear()

        valid_task_slugs: list[str] = []
        for task in tasks:
            task_slug = str(task.get("slug") or "").strip()
            if not task_slug:
                continue
            task_label = str(task.get("display_name") or task_slug)
            self._positive_seed_task_combo.addItem(f"{task_label} ({task_slug})", task_slug)
            valid_task_slugs.append(task_slug)

        if valid_task_slugs:
            preferred_task = current_task if current_task in valid_task_slugs else ("level" if "level" in valid_task_slugs else valid_task_slugs[0])
            target_index = 0
            for index in range(self._positive_seed_task_combo.count()):
                if self._positive_seed_task_combo.itemData(index) == preferred_task:
                    target_index = index
                    break
            self._positive_seed_task_combo.setCurrentIndex(target_index)
            self._positive_seed_task_combo.setEnabled(True)
            self._positive_seed_import_button.setEnabled(True)
        else:
            self._positive_seed_task_combo.addItem("无可复用属性任务", "")
            self._positive_seed_task_combo.setCurrentIndex(0)
            self._positive_seed_task_combo.setEnabled(False)
            self._positive_seed_import_button.setEnabled(False)

        self._positive_seed_task_combo.blockSignals(False)

    def _current_positive_seed_task_name(self) -> str:
        return str(self._positive_seed_task_combo.currentData() or "").strip()

    def _current_positive_seed_task_label(self) -> str:
        task_name = self._current_positive_seed_task_name()
        if not task_name:
            return ""
        for task in get_project_attribute_tasks(self._project_info):
            task_slug = str(task.get("slug") or "").strip()
            if task_slug == task_name:
                return str(task.get("display_name") or task_slug)
        return task_name

    def _ensure_target_dirs(self) -> None:
        self._sample_directory("positive").mkdir(parents=True, exist_ok=True)
        self._sample_directory("negative").mkdir(parents=True, exist_ok=True)

    def _ensure_source_dir(self) -> Path:
        source_dir = Path(self._source_dir_edit.text().strip() or get_project_detection_raw_images_dir(self._project_info))
        source_dir.mkdir(parents=True, exist_ok=True)
        self._source_dir_edit.setText(str(source_dir))
        return source_dir

    @staticmethod
    def _iter_import_source_images(paths: list[Path]) -> list[Path]:
        images: list[Path] = []
        seen: set[str] = set()
        for raw_path in paths:
            try:
                candidate = raw_path.resolve()
            except OSError:
                candidate = raw_path
            if candidate.is_dir():
                nested = collect_image_files(candidate)
                for image_path in nested:
                    marker = str(image_path).lower()
                    if marker in seen:
                        continue
                    seen.add(marker)
                    images.append(image_path)
                continue
            if candidate.is_file() and candidate.suffix.lower() in REVIEW_IMAGE_EXTENSIONS:
                marker = str(candidate).lower()
                if marker in seen:
                    continue
                seen.add(marker)
                images.append(candidate)
        return images

    @staticmethod
    def _build_unique_file_path(target_dir: Path, file_name: str) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        candidate = target_dir / file_name
        if not candidate.exists():
            return candidate

        stem = candidate.stem
        suffix = candidate.suffix or ".png"
        index = 2
        while True:
            numbered = target_dir / f"{stem}__{index:02d}{suffix}"
            if not numbered.exists():
                return numbered
            index += 1

    def _import_images_to_sample_role(self, image_paths: list[Path], role: str, source_label: str) -> tuple[list[Path], int]:
        target_dir = self._sample_directory(role)
        target_dir.mkdir(parents=True, exist_ok=True)
        imported: list[Path] = []
        skipped = 0

        for image_path in self._iter_import_source_images(image_paths):
            try:
                resolved_image = image_path.resolve()
            except OSError:
                resolved_image = image_path

            target_path = target_dir / resolved_image.name
            if target_path.exists():
                skipped += 1
                continue

            try:
                shutil.copy2(resolved_image, target_path)
            except Exception as exc:
                self._append_log(f"[导入失败] {resolved_image}: {exc}\n")
                continue
            imported.append(target_path.resolve())

        sample_display_name = self._sample_display_name(role)
        if imported:
            self._append_log(f"[导入] 来自{source_label}，新增 {len(imported)} 张{sample_display_name}\n")
        if skipped:
            self._append_log(f"[跳过] {source_label} 中已有 {skipped} 张{sample_display_name}同名文件\n")

        if imported:
            self._status_label.setText(f"状态: 已导入 {len(imported)} 张{sample_display_name}")
        elif skipped:
            self._status_label.setText(f"状态: 没有新增{sample_display_name}，已有同名文件 {skipped} 张")
        else:
            self._status_label.setText(f"状态: 没有导入新的{sample_display_name}")

        self._update_dataset_info()
        return imported, skipped

    def _select_positive_seed_images(self, image_paths: list[Path]) -> list[Path]:
        selected = list(image_paths)
        limit = max(0, int(self._positive_seed_limit_spin.value()))
        if limit == 0 or len(selected) <= limit:
            return selected
        if not self._positive_seed_random_check.isChecked():
            return selected[:limit]

        chosen_indices = sorted(random.sample(range(len(selected)), limit))
        return [selected[index] for index in chosen_indices]

    def _import_existing_positive_samples(self) -> None:
        task_name = self._current_positive_seed_task_name()
        if not task_name:
            QMessageBox.information(self, "提示", "当前没有可复用的属性裁剪任务")
            return

        source_root = get_project_attribute_task_raw_root(self._project_info, task_name)
        if not source_root.exists():
            QMessageBox.information(self, "提示", f"属性裁剪目录不存在:\n{source_root}")
            return

        source_images = collect_image_files(source_root)
        image_count = len(source_images)
        if image_count == 0:
            QMessageBox.information(self, "提示", f"{source_root} 里还没有可导入的小图")
            return

        selected_images = self._select_positive_seed_images(source_images)
        selected_count = len(selected_images)
        if selected_count == 0:
            QMessageBox.information(self, "提示", "当前导入数量为 0，且没有可导入样本")
            return

        task_label = self._current_positive_seed_task_label() or task_name
        positive_name = self._sample_display_name("positive")
        limit = max(0, int(self._positive_seed_limit_spin.value()))
        if limit > 0 and selected_count < image_count:
            select_mode_text = "随机抽样" if self._positive_seed_random_check.isChecked() else "按顺序截取"
            question_text = (
                f"将从 {task_label} 裁剪目录里{select_mode_text}导入 {selected_count}/{image_count} 张现成小图到{positive_name}目录，是否继续？"
            )
        else:
            question_text = f"将从 {task_label} 裁剪目录导入 {image_count} 张现成小图到{positive_name}目录，是否继续？"
        answer = QMessageBox.question(
            self,
            "导入已有正确样本",
            question_text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        source_label = f"{task_label}裁剪"
        if limit > 0 and selected_count < image_count:
            source_label += f"({selected_count}/{image_count})"
        imported, skipped = self._import_images_to_sample_role(selected_images, "positive", source_label)
        if imported:
            QMessageBox.information(
                self,
                "导入完成",
                f"已导入 {len(imported)} 张{positive_name}。"
                + (f"\n跳过同名文件 {skipped} 张。" if skipped else ""),
            )
        else:
            QMessageBox.information(
                self,
                "提示",
                f"没有新增{positive_name}。"
                + (f"\n已有同名文件 {skipped} 张。" if skipped else ""),
            )

    def _refresh_image_list(self, selected_path: Path | None = None) -> None:
        source_dir = Path(self._source_dir_edit.text().strip() or AI_ROOT)
        previous_path = str(selected_path.resolve()) if selected_path is not None else str(self._current_image_path() or "")
        images = collect_image_files(source_dir)

        self._file_list.blockSignals(True)
        self._file_list.clear()
        selected_row = 0
        for index, image_path in enumerate(images):
            display_label = str(image_path.relative_to(source_dir)).replace("\\", "/")
            item = QListWidgetItem(display_label)
            item.setData(Qt.ItemDataRole.UserRole, str(image_path))
            item.setData(self._file_item_label_role, display_label)
            self._file_list.addItem(item)
            if str(image_path.resolve()) == previous_path:
                selected_row = index
        self._file_list.blockSignals(False)

        self._refresh_file_list_markers()

        if images:
            self._file_list.setCurrentRow(selected_row)
            self._status_label.setText(f"状态: 已加载 {len(images)} 张图片")
        else:
            self._image_view.set_image_path(None)
            self._image_info_label.setText("当前图片: 无")
            self._selection_info_label.setText("当前框选: 无")
            self._annotation_list.clear()
            self._status_label.setText("状态: 当前目录下没有可采集图片")

        self._update_dataset_info()

    def _import_source_images(self, image_paths: list[Path], source_label: str) -> list[Path]:
        source_dir = self._ensure_source_dir()
        imported: list[Path] = []
        for image_path in self._iter_import_source_images(image_paths):
            try:
                resolved_image = image_path.resolve()
            except OSError:
                resolved_image = image_path
            try:
                if resolved_image.parent.resolve() == source_dir.resolve():
                    target_path = resolved_image
                else:
                    target_path = self._build_unique_file_path(source_dir, resolved_image.name)
                    shutil.copy2(resolved_image, target_path)
            except Exception as exc:
                self._append_log(f"[导入失败] {resolved_image}: {exc}\n")
                continue
            imported.append(target_path.resolve())

        if imported:
            self._append_log(f"[导入] 来自{source_label}，新增 {len(imported)} 张图片\n")
            self._status_label.setText(f"状态: 已导入 {len(imported)} 张图片")
            self._refresh_image_list(imported[-1])
        else:
            self._status_label.setText("状态: 没有导入新图片")
        return imported

    def _import_dropped_paths(self, raw_paths: object) -> None:
        if not isinstance(raw_paths, list):
            return
        image_paths = [Path(str(path)) for path in raw_paths if str(path).strip()]
        if not image_paths:
            return
        self._import_source_images(image_paths, "拖拽")

    def _paste_from_clipboard(self) -> None:
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()

        if mime_data.hasUrls():
            raw_paths = [
                Path(url.toLocalFile())
                for url in mime_data.urls()
                if url.isLocalFile() and url.toLocalFile().strip()
            ]
            if raw_paths:
                self._import_source_images(raw_paths, "剪贴板文件")
                return

        if mime_data.hasImage():
            source_dir = self._ensure_source_dir()
            timestamp = datetime.now().strftime("clipboard_%Y%m%d_%H%M%S_%f")
            output_path = self._build_unique_file_path(source_dir, f"{timestamp}.png")
            pixmap = clipboard.pixmap()
            saved = False
            if not pixmap.isNull():
                saved = pixmap.save(str(output_path), "PNG")
            else:
                image = clipboard.image()
                if not image.isNull():
                    saved = image.save(str(output_path), "PNG")
            if saved:
                self._append_log(f"[导入] 来自剪贴板图像，新增 1 张图片: {output_path.name}\n")
                self._status_label.setText("状态: 已导入 1 张剪贴板图片")
                self._refresh_image_list(output_path)
                return

        if mime_data.hasText():
            raw_text = mime_data.text().strip()
            if raw_text:
                text_paths = [Path(line.strip().strip('"')) for line in raw_text.splitlines() if line.strip()]
                if text_paths:
                    imported = self._import_source_images(text_paths, "剪贴板路径")
                    if imported:
                        return

        QMessageBox.information(self, "提示", "剪贴板里没有可导入的图片或本地图片文件")

    def _current_image_path(self) -> Path | None:
        item = self._file_list.currentItem()
        if item is None:
            return None
        raw_path = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not raw_path:
            return None
        return Path(raw_path)

    @staticmethod
    def _image_state_key(image_path: Path | None) -> str:
        if image_path is None:
            return ""
        try:
            return str(image_path.resolve())
        except OSError:
            return str(image_path)

    def _store_image_annotations(self, image_path: Path | None, states: list[dict[str, Any]] | None = None) -> None:
        state_key = self._image_state_key(image_path)
        if not state_key:
            return
        normalized_states = deepcopy(states if states is not None else self._image_view.annotation_states())
        if normalized_states:
            self._image_annotation_states[state_key] = normalized_states
        else:
            self._image_annotation_states.pop(state_key, None)

    def _states_for_image(self, image_path: Path | None) -> list[dict[str, Any]]:
        return self._load_image_annotations(image_path)

    @staticmethod
    def _annotation_counts(states: list[dict[str, Any]]) -> tuple[int, int, int, int, int]:
        positive_count = sum(1 for state in states if str(state.get("status") or "unsaved") == "positive")
        negative_count = sum(1 for state in states if str(state.get("status") or "unsaved") == "negative")
        unsaved_count = sum(1 for state in states if str(state.get("status") or "unsaved") == "unsaved")
        saved_count = positive_count + negative_count
        return len(states), positive_count, negative_count, unsaved_count, saved_count

    @staticmethod
    def _apply_item_palette(item: QListWidgetItem, foreground: QColor | None = None, background: QColor | None = None) -> None:
        item.setData(Qt.ItemDataRole.ForegroundRole, QBrush(foreground) if foreground is not None else None)
        item.setData(Qt.ItemDataRole.BackgroundRole, QBrush(background) if background is not None else None)

    def _file_item_palette(self, saved_count: int, unsaved_count: int) -> tuple[QColor | None, QColor | None]:
        if unsaved_count > 0:
            return QColor(176, 102, 0), QColor(255, 245, 214)
        if saved_count > 0:
            return QColor(24, 114, 58), QColor(229, 247, 236)
        return None, None

    def _annotation_item_palette(self, state: dict[str, Any]) -> tuple[QColor | None, QColor | None]:
        status = str(state.get("status") or "unsaved")
        if status == "positive":
            return QColor(24, 114, 58), QColor(229, 247, 236)
        if status == "negative":
            return QColor(166, 46, 39), QColor(252, 234, 234)
        return QColor(176, 102, 0), QColor(255, 245, 214)

    def _annotation_matches_filter(self, state: dict[str, Any]) -> bool:
        filter_value = str(self._annotation_filter_combo.currentData() or "all")
        if filter_value == "all":
            return True
        return str(state.get("status") or "unsaved") == filter_value

    def _annotation_item_status_text(self, state: dict[str, Any]) -> str:
        status = str(state.get("status") or "unsaved")
        if status == "unsaved":
            saved_status = str(state.get("saved_status") or "")
            if saved_status in {"positive", "negative"}:
                return f"未保存(原{self._selection_status_text(saved_status)})"
        return self._selection_status_text(status)

    def _format_annotation_item_text(self, state: dict[str, Any], index: int) -> str:
        x = int(state.get("x") or 0)
        y = int(state.get("y") or 0)
        w = int(state.get("w") or 0)
        h = int(state.get("h") or 0)
        return f"#{index + 1} {self._annotation_item_status_text(state)} | x={x}, y={y}, w={w}, h={h}"

    def _refresh_annotation_list(self) -> None:
        states = self._image_view.annotation_states()
        active_index = self._image_view.active_annotation_index()

        self._annotation_list.blockSignals(True)
        self._annotation_list.clear()
        active_row = -1
        for index, state in enumerate(states):
            if not self._annotation_matches_filter(state):
                continue
            item = QListWidgetItem(self._format_annotation_item_text(state, index))
            item.setData(self._annotation_item_index_role, index)
            saved_path = str(state.get("saved_path") or "").strip()
            if saved_path:
                item.setToolTip(saved_path)
            foreground, background = self._annotation_item_palette(state)
            self._apply_item_palette(item, foreground, background)
            self._annotation_list.addItem(item)
            if index == active_index:
                active_row = self._annotation_list.count() - 1
        if 0 <= active_row < self._annotation_list.count():
            self._annotation_list.setCurrentRow(active_row)
        self._annotation_list.blockSignals(False)

    def _update_file_item_marker(self, item: QListWidgetItem | None, states: list[dict[str, Any]] | None = None) -> None:
        if item is None:
            return
        base_label = str(item.data(self._file_item_label_role) or item.text())
        raw_path = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        image_path = Path(raw_path) if raw_path else None
        annotation_states = list(states) if states is not None else self._states_for_image(image_path)
        total_count, positive_count, negative_count, unsaved_count, saved_count = self._annotation_counts(annotation_states)

        if total_count == 0:
            item.setText(base_label)
            item.setToolTip(base_label)
            self._apply_item_palette(item)
            return

        parts: list[str] = []
        if saved_count:
            parts.append(f"已存{saved_count}")
        if unsaved_count:
            parts.append(f"待存{unsaved_count}")
        marker_text = " | ".join(parts)
        item.setText(f"{base_label}  [{marker_text}]")
        positive_name = self._sample_display_name("positive")
        negative_name = self._sample_display_name("negative")
        item.setToolTip(
            f"{base_label}\n共 {total_count} 个框 | 未保存 {unsaved_count} | {positive_name} {positive_count} | {negative_name} {negative_count}"
        )
        foreground, background = self._file_item_palette(saved_count, unsaved_count)
        self._apply_item_palette(item, foreground, background)

    def _refresh_file_list_markers(self) -> None:
        for index in range(self._file_list.count()):
            item = self._file_list.item(index)
            self._update_file_item_marker(item)

    def _load_image_annotations(self, image_path: Path | None) -> list[dict[str, Any]]:
        state_key = self._image_state_key(image_path)
        if not state_key:
            return []
        if state_key in self._image_annotation_states:
            return deepcopy(self._image_annotation_states[state_key])
        return self._load_saved_annotations(image_path)

    def _parse_saved_annotation(self, image_path: Path, sample_path: Path, role: str) -> dict[str, Any] | None:
        sample_slug = re.escape(self._sample_slug(role))
        image_stem = re.escape(image_path.stem)
        match = re.fullmatch(
            rf"{image_stem}__{sample_slug}__x(?P<x>-?\d+)_y(?P<y>-?\d+)_w(?P<w>\d+)_h(?P<h>\d+)(?:__\d+)?",
            sample_path.stem,
        )
        if match is None:
            return None

        try:
            x = int(match.group("x"))
            y = int(match.group("y"))
            w = int(match.group("w"))
            h = int(match.group("h"))
        except (TypeError, ValueError):
            return None

        return {
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "status": role,
            "active": False,
            "saved_path": str(sample_path.resolve()),
            "saved_status": role,
        }

    def _load_saved_annotations(self, image_path: Path | None) -> list[dict[str, Any]]:
        if image_path is None:
            return []

        states: list[dict[str, Any]] = []
        for role in ("positive", "negative"):
            sample_dir = self._sample_directory(role)
            if not sample_dir.exists():
                continue
            for sample_path in sorted(collect_image_files(sample_dir), key=lambda path: path.name.lower()):
                state = self._parse_saved_annotation(image_path, sample_path, role)
                if state is not None:
                    states.append(state)

        return states

    def _selection_status_text(self, status: str) -> str:
        if status == "positive":
            return self._sample_display_name("positive")
        if status == "negative":
            return self._sample_display_name("negative")
        return "未保存"

    def _update_selection_info_label(self) -> None:
        states = self._image_view.annotation_states()
        if not states:
            self._selection_info_label.setText("当前框选: 无")
            return

        positive_count = sum(1 for state in states if str(state.get("status") or "unsaved") == "positive")
        negative_count = sum(1 for state in states if str(state.get("status") or "unsaved") == "negative")
        unsaved_count = sum(1 for state in states if str(state.get("status") or "unsaved") == "unsaved")
        positive_name = self._sample_display_name("positive")
        negative_name = self._sample_display_name("negative")
        active_info = self._image_view.active_selection_info()

        if active_info is None:
            self._selection_info_label.setText(
                f"当前框选: 未选中 | 共 {len(states)} 个 | 未保存 {unsaved_count} | {positive_name} {positive_count} | {negative_name} {negative_count}"
            )
            return

        rect = active_info["rect"]
        status_text = self._selection_status_text(str(active_info.get("status") or "unsaved"))
        self._selection_info_label.setText(
            f"当前框选: {active_info['index'] + 1}/{active_info['total']} | 状态: {status_text} | "
            f"x={rect.x()}, y={rect.y()}, w={rect.width()}, h={rect.height()} | "
            f"未保存 {unsaved_count} | {positive_name} {positive_count} | {negative_name} {negative_count}"
        )

    def _on_current_image_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if previous is not None:
            previous_path = Path(str(previous.data(Qt.ItemDataRole.UserRole) or "").strip())
            self._store_image_annotations(previous_path)
            self._update_file_item_marker(previous)

        if current is None:
            self._image_view.set_image_path(None)
            self._image_info_label.setText("当前图片: 无")
            self._selection_info_label.setText("当前框选: 无")
            self._annotation_list.clear()
            return

        image_path = Path(str(current.data(Qt.ItemDataRole.UserRole) or "").strip())
        self._image_view.set_image_path(image_path)
        self._image_view.set_annotations(self._load_image_annotations(image_path))
        index_text = f"{self._file_list.currentRow() + 1}/{self._file_list.count()}"
        self._image_info_label.setText(
            f"当前图片: {image_path.name} | 尺寸: {self._image_view.image_size_text()} | 序号: {index_text}"
        )
        self._update_selection_info_label()
        self._refresh_annotation_list()
        self._update_file_item_marker(current)

    def _on_selection_changed(self, selection: object) -> None:
        del selection
        self._update_selection_info_label()
        self._refresh_annotation_list()

    def _on_annotations_changed(self, states: object) -> None:
        image_path = self._current_image_path()
        if image_path is not None and isinstance(states, list):
            self._store_image_annotations(image_path, states)
        self._update_selection_info_label()
        self._refresh_annotation_list()
        self._update_file_item_marker(self._file_list.currentItem(), states if isinstance(states, list) else None)

    def _on_current_annotation_item_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        try:
            annotation_index = int(current.data(self._annotation_item_index_role))
        except (TypeError, ValueError):
            return
        self._image_view.set_active_annotation_index(annotation_index)

    def _select_relative_image(self, offset: int) -> None:
        if self._file_list.count() == 0:
            return
        target_row = min(max(0, self._file_list.currentRow() + offset), self._file_list.count() - 1)
        self._file_list.setCurrentRow(target_row)

    def _open_current_image(self) -> None:
        image_path = self._current_image_path()
        if image_path is None or not image_path.exists():
            QMessageBox.information(self, "提示", "当前没有选中图片")
            return
        open_local_path(image_path)

    def _build_output_path(self, label_name: str) -> Path:
        image_path = self._current_image_path()
        selection = self._image_view.selection_rect()
        active_info = self._image_view.active_selection_info()
        assert image_path is not None
        assert selection is not None

        target_dir = self._sample_directory(label_name)
        target_dir.mkdir(parents=True, exist_ok=True)
        sample_slug = self._sample_slug(label_name)

        saved_path_text = str(active_info.get("saved_path") or "").strip() if active_info is not None else ""
        saved_status = str(active_info.get("saved_status") or "").strip() if active_info is not None else ""
        current_status = str(active_info.get("status") or "").strip() if active_info is not None else ""
        if saved_path_text and saved_status == label_name and current_status == label_name:
            return Path(saved_path_text)

        base_name = (
            f"{image_path.stem}__{sample_slug}__x{selection.x()}_y{selection.y()}_"
            f"w{selection.width()}_h{selection.height()}"
        )
        candidate = target_dir / f"{base_name}.png"
        suffix = 2
        while candidate.exists():
            candidate = target_dir / f"{base_name}__{suffix:02d}.png"
            suffix += 1
        return candidate

    def _save_current_selection(self, label_name: str) -> None:
        image_path = self._current_image_path()
        selection = self._image_view.selection_rect()
        if image_path is None:
            QMessageBox.information(self, "提示", "请先在左侧选择一张图片")
            return
        if selection is None:
            QMessageBox.information(self, "提示", "请先在右侧图片上拖拽框选区域")
            return

        self._ensure_target_dirs()
        output_path = self._build_output_path(label_name)
        if not self._image_view.save_selection(output_path, label_name):
            QMessageBox.warning(self, "保存失败", f"无法保存裁剪结果:\n{output_path}")
            return

        sample_display_name = self._sample_display_name(label_name)
        self._append_log(
            f"[{sample_display_name}] {output_path.name} <- {image_path.name} "
            f"(x={selection.x()}, y={selection.y()}, w={selection.width()}, h={selection.height()})\n"
        )
        self._status_label.setText(f"状态: 已保存为{sample_display_name}")
        self._update_dataset_info()
        if self._auto_next_check.isChecked() and not any(
            str(state.get("status") or "unsaved") == "unsaved"
            for state in self._image_view.annotation_states()
        ):
            self._select_relative_image(1)

    def _update_dataset_info(self) -> None:
        source_count = len(collect_image_files(Path(self._source_dir_edit.text().strip() or AI_ROOT)))
        positive_count = len(collect_image_files(self._sample_directory("positive")))
        negative_count = len(collect_image_files(self._sample_directory("negative")))
        positive_name = self._sample_display_name("positive")
        negative_name = self._sample_display_name("negative")
        self._dataset_info_label.setText(
            f"源图 {source_count} 张 | {positive_name} {positive_count} 张 | {negative_name} {negative_count} 张"
        )

    def apply_project_context(self, project_info: dict[str, Any] | None) -> None:
        self._image_annotation_states = {}
        self._source_dir_edit.setText(str(get_project_detection_raw_images_dir(project_info)))
        self._positive_dir_edit.setText(str(get_project_review_positive_dir(project_info)))
        self._negative_dir_edit.setText(str(get_project_review_negative_dir(project_info)))
        self._reload_positive_seed_task_items()
        self._task_info_label.setText(self._review_task_display())
        self._refresh_review_ui_texts()
        self._ensure_target_dirs()
        self._refresh_image_list()


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

        note = QLabel("这里既可以切分等级/类型/关系分类数据，也可以切分候选框复检这类二分类数据集。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #444;")

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
        tasks = get_project_trainable_classifier_tasks(project_info)
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

        note = QLabel("这里训练的是等级、类型、关系，以及可选的候选框复检分类器。对应任务目录里需要先有 train/val/test 三个子目录。")
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
        tasks = get_project_trainable_classifier_tasks(project_info)
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
        self._package_output_edit = QLineEdit(str(get_project_model_package_output_dir(None, Path(get_default_smoke_model_path()))))
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
        self._package_zip_check = QCheckBox("导出模型包后同时生成 ZIP 压缩包")
        self._package_zip_check.setChecked(True)

        self._export_button = QPushButton("导出 ONNX")
        self._export_button.clicked.connect(self._run_export)
        self._export_package_button = QPushButton("导出模型包")
        self._export_package_button.clicked.connect(self._run_export_package)
        self._stop_button = QPushButton("停止")
        self._stop_button.clicked.connect(self._stop_process)
        self._open_output_button = QPushButton("打开模型目录")
        self._open_output_button.clicked.connect(lambda: open_local_path(Path(self._output_edit.text().strip()).parent))
        self._open_package_button = QPushButton("打开模型包目录")
        self._open_package_button.clicked.connect(lambda: open_local_path(Path(self._package_output_edit.text().strip()).parent))
        self._use_smoke_defaults_button = QPushButton("套用当前快测数据")
        self._use_smoke_defaults_button.clicked.connect(self._apply_smoke_defaults)
        self._use_full_defaults_button = QPushButton("切回完整检测数据")
        self._use_full_defaults_button.clicked.connect(self._apply_full_defaults)

        note = QLabel("这里可以导出检测 ONNX，也可以额外导出一个可分发的模型包。模型包会同时带上 project_meta、属性 best.pt 和候选框复检 best.pt，适合直接发给别人运行主程序。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #444;")

        config_group = QGroupBox("导出设置")
        config_layout = QFormLayout(config_group)
        weights_row, self._weights_browse_button = build_path_row(self._weights_edit, "浏览...", lambda: self._choose_open_file(self._weights_edit, "选择权重文件", "PyTorch 权重 (*.pt);;所有文件 (*.*)"))
        output_row, self._output_browse_button = build_path_row(self._output_edit, "保存为...", lambda: self._choose_save_file(self._output_edit, "保存 ONNX 模型", "ONNX 模型 (*.onnx)"))
        meta_row, self._meta_browse_button = build_path_row(self._meta_output_edit, "保存为...", lambda: self._choose_save_file(self._meta_output_edit, "保存模型元数据", "JSON 文件 (*.json)"))
        package_row, self._package_output_browse_button = build_path_row(self._package_output_edit, "浏览...", lambda: self._choose_directory(self._package_output_edit))
        config_layout.addRow("权重文件:", weights_row)
        config_layout.addRow("ONNX 输出:", output_row)
        config_layout.addRow("元数据输出:", meta_row)
        config_layout.addRow("模型包输出目录:", package_row)
        config_layout.addRow("输入尺寸:", self._imgsz_spin)
        config_layout.addRow("默认置信度阈值:", self._conf_spin)
        config_layout.addRow("默认 IoU 阈值:", self._iou_spin)
        config_layout.addRow("最大检测数:", self._max_detections_spin)
        config_layout.addRow("", self._simplify_check)
        config_layout.addRow("", self._dynamic_check)
        config_layout.addRow("", self._half_check)
        config_layout.addRow("", self._nms_check)
        config_layout.addRow("", self._package_zip_check)

        button_row = QHBoxLayout()
        button_row.addWidget(self._use_smoke_defaults_button)
        button_row.addWidget(self._use_full_defaults_button)
        button_row.addWidget(self._export_button)
        button_row.addWidget(self._export_package_button)
        button_row.addWidget(self._stop_button)
        button_row.addWidget(self._open_output_button)
        button_row.addWidget(self._open_package_button)
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
        self._output_edit.setText(
            str(build_project_detector_output_path(get_project_root(self._project_info), smoke_run_name, "onnx", get_default_smoke_model_path()))
        )
        self._meta_output_edit.setText("")
        self._sync_package_output_path()

    def _apply_full_defaults(self) -> None:
        self._weights_edit.setText(str(get_project_detection_weights_path(self._project_info)))
        self._output_edit.setText(str(get_project_detection_model_path(self._project_info)))
        self._meta_output_edit.setText("")
        self._sync_package_output_path()

    def _sync_package_output_path(self) -> None:
        model_text = self._output_edit.text().strip()
        model_path = Path(model_text) if model_text else None
        self._package_output_edit.setText(str(get_project_model_package_output_dir(self._project_info, model_path)))

    def _set_running_state(self, running: bool) -> None:
        self._export_button.setEnabled(not running)
        self._export_package_button.setEnabled(not running)
        self._weights_browse_button.setEnabled(not running)
        self._output_browse_button.setEnabled(not running)
        self._meta_browse_button.setEnabled(not running)
        self._package_output_browse_button.setEnabled(not running)
        self._use_smoke_defaults_button.setEnabled(not running)
        self._use_full_defaults_button.setEnabled(not running)
        self._package_zip_check.setEnabled(not running)
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

    def _run_export_package(self) -> None:
        if not self._project_info:
            QMessageBox.warning(self, "提示", "导出模型包需要先选择一个项目")
            return

        project_root = get_project_root(self._project_info)
        if project_root is None:
            QMessageBox.warning(self, "提示", "当前项目路径无效，无法导出模型包")
            return

        script_path = AI_ROOT / "scripts" / "export_model_package.py"
        args = [
            "--project-config",
            str(project_root / PROJECT_META_FILENAME),
            "--detector-model",
            self._output_edit.text().strip() or str(get_project_detection_model_path(self._project_info)),
            "--output-dir",
            self._package_output_edit.text().strip(),
            "--overwrite",
        ]
        meta_output = self._meta_output_edit.text().strip()
        if meta_output:
            args.extend(["--detector-meta", meta_output])
        if self._package_zip_check.isChecked():
            args.append("--zip")
        self._run_python_script(script_path, args, "导出可分发模型包")

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
            project_root = get_project_root(self._project_info)
            self._model_edit.setText(str(build_project_detector_output_path(project_root, smoke_run_name, "onnx", get_default_smoke_model_path())))
            self._meta_edit.setText(str(build_project_detector_output_path(project_root, smoke_run_name, "json", get_default_smoke_meta_path())))
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
            "如果你已经手里有误检截图，可以直接进入‘复检采集’页，把局部区域裁成正确样本 / 错误样本。"
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
        tabs.addTab(ReviewCollectionTab(self._project_context), "5. 复检采集")
        tabs.addTab(DatasetSplitTab(self._project_context, self._smoke_context), "6. 检测切分")
        tabs.addTab(TrainingTab(self._project_context, self._smoke_context), "7. 检测训练")
        tabs.addTab(AttributeSplitTab(self._project_context), "8. 属性切分")
        tabs.addTab(AttributeTrainingTab(self._project_context), "9. 属性训练")
        tabs.addTab(ExportTab(self._project_context, self._smoke_context), "10. 导出")
        tabs.addTab(BenchmarkTab(self._project_context, self._smoke_context), "11. 基准测试")
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