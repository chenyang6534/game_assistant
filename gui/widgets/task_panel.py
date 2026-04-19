"""
计划任务管理面板
提供计划任务的新增、编辑、删除、执行功能的完整GUI
"""

import ast
import copy
import json
import os
import re
import shutil
import sys
import threading
import textwrap
import traceback
from datetime import datetime
from typing import Any, Callable, List, Optional

from PySide6.QtCore import QMimeData, QObject, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QBrush, QColor, QKeySequence, QPainter, QPen, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QListView,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from task.executor import TaskExecutor
from task.models import (
    CLICK_OFFSET_MODE_LABELS,
    ARRAY_ITEM_TYPE_LABELS,
    GRID_MODE_LABELS,
    IMAGE_MATCH_MODE_LABELS,
    PlanTask,
    RECOGNITION_ROI_MODE_LABELS,
    RECOGNITION_TARGET_MODE_LABELS,
    REMOVE_COORD_MODE_LABELS,
    SingleTask,
    StepCondition,
    STRUCT_FIELD_TYPE_LABELS,
    StructDefinition,
    StructField,
    TaskParameter,
    build_param_default_value,
    coerce_float,
    coerce_array_item_value,
    derive_screen_drag_vector,
    get_default_click_offset_mode,
    get_array_param_type_label,
    get_param_type_label,
    get_struct_name_from_type,
    is_array_param_type,
    is_struct_array_param_type,
    is_struct_param_type,
    make_struct_array_param_type,
    make_struct_param_type,
    normalize_action_type,
    normalize_center_tolerance_px,
    normalize_click_offset_mode,
    normalize_grid_mode,
    normalize_highlight_duration_ms,
    normalize_point_position_mode,
    normalize_remove_coord_mode,
    normalize_drag_vector_mode,
    normalize_image_match_mode,
    normalize_recognition_roi_mode,
    normalize_recognition_target_mode,
    normalize_array_items,
)
from task.storage import TaskStorage


LOG_TIMESTAMP_ROLE = Qt.UserRole + 101
LOG_SUMMARY_ROLE = Qt.UserRole + 102
LOG_FULL_TEXT_ROLE = Qt.UserRole + 103
LOG_STEP_ID_ROLE = Qt.UserRole + 104
LOG_STEP_NAME_ROLE = Qt.UserRole + 105
LOG_BASE_TITLE_ROLE = Qt.UserRole + 106
STEP_ID_ROLE = Qt.UserRole + 120

ACTION_TYPE_LABELS = {
    "click": "点击",
    "double_click": "双击",
    "right_click": "右键",
    "hold_left_button": "长按鼠标左键",
    "highlight_match": "红框标记识别结果",
    "highlight_point": "显示红色原点",
    "none": "无操作",
    "input_text": "输入文本",
    "press_key": "按键",
    "drag_map": "拖动地图",
    "drag_match_to_center": "拖动识别目标到屏幕中心",
    "mark_blocked": "标记封锁",
    "modify_variable": "修改变量",
    "add_to_array": "添加到数组",
    "save_recognition_coords": "保存识别坐标到坐标数组",
    "remove_target_coords": "删除目标坐标",
    "clear_array_data": "清空数组数据",
    "recognition_to_logic_coord": "识别坐标转逻辑坐标",
    "jump_to_step": "跳转步骤",
    "traverse_hex": "按模式遍历网格",
    "traverse_grid": "按模式遍历网格",
    "get_two_ring_coords": "按半径获取周围坐标",
    "get_surrounding_coords": "按半径获取周围坐标",
    "find_road_path": "寻找铺路路径",
    "continue_loop": "继续循环",
    "break_loop": "跳出循环",
}

ACTION_CATEGORY_LABELS = {
    "data": "数据操作",
    "other": "其他",
}

MAIN_ACTION_TYPE_GROUPS = (
    (
        "other",
        (
            "click",
            "double_click",
            "right_click",
            "hold_left_button",
            "input_text",
            "press_key",
            "drag_map",
            "drag_match_to_center",
            "highlight_match",
            "highlight_point",
            "jump_to_step",
            "continue_loop",
            "break_loop",
            "none",
        ),
    ),
    (
        "data",
        (
            "mark_blocked",
            "modify_variable",
            "add_to_array",
            "save_recognition_coords",
            "remove_target_coords",
            "clear_array_data",
            "recognition_to_logic_coord",
            "traverse_grid",
            "get_surrounding_coords",
            "find_road_path",
        ),
    ),
)

FAIL_ACTION_TYPE_GROUPS = (
    (
        "data",
        (
            "modify_variable",
            "add_to_array",
            "remove_target_coords",
            "clear_array_data",
        ),
    ),
    (
        "other",
        (
            "jump_to_step",
            "continue_loop",
            "break_loop",
        ),
    ),
)

DRAG_COORDINATE_MODE_LABELS = {
    "game_logic": "游戏逻辑",
    "screen": "屏幕坐标",
}

DRAG_START_MODE_LABELS = {
    "recognition": "识别坐标",
    "screen_percent": "目标窗口百分比",
}

DRAG_VECTOR_MODE_LABELS = {
    "pixel": "像素",
    "screen_percent": "屏幕百分比",
}

POINT_POSITION_MODE_LABELS = {
    "recognition": "识别结果坐标",
    "screen_absolute": "目标窗口绝对坐标",
    "screen_percent": "目标窗口百分比坐标",
}

CLICK_OFFSET_HINT_TEXT = (
    "X 偏移: 0.5=右边缘，-0.5=左边缘，1.0=超出右边缘半个图像宽度\n"
    "Y 偏移: 0.5=下边缘，-0.5=上边缘，1.0=超出下边缘半个图像高度"
)

CLICK_OFFSET_SCREEN_ABSOLUTE_HINT_TEXT = (
    "X/Y 偏移单位为目标窗口客户区像素\n"
    "X 正数向右，Y 正数向下"
)

CLICK_OFFSET_SCREEN_PERCENT_HINT_TEXT = (
    "X/Y 偏移单位为目标窗口客户区宽高比例\n"
    "X 偏移 0.5=额外右移半个窗口宽度，Y 偏移 0.5=额外下移半个窗口高度"
)

RECOGNITION_TARGET_MODE_SHORT_LABELS = {
    "array_any": "数组任一",
    "array_all": "数组全部",
}

IMAGE_MATCH_MODE_SHORT_LABELS = {
    "foreground": "前景优先",
}

RECOGNITION_ROI_MODE_SHORT_LABELS = {
    "window_percent": "局部范围",
}


def _normalize_grid_action_type(action_type: str) -> str:
    return normalize_action_type(action_type)


def _grid_mode_display_text(mode: str) -> str:
    mode = normalize_grid_mode(mode)
    return GRID_MODE_LABELS.get(mode, mode)


def _populate_grid_mode_combo(combo: QComboBox):
    combo.blockSignals(True)
    combo.clear()
    for mode, label in GRID_MODE_LABELS.items():
        combo.addItem(label, mode)
    combo.blockSignals(False)


def _remove_coord_mode_display_text(mode: str) -> str:
    mode = normalize_remove_coord_mode(mode)
    return REMOVE_COORD_MODE_LABELS.get(mode, mode)


def _image_match_mode_display_text(mode: str) -> str:
    mode = normalize_image_match_mode(mode)
    return IMAGE_MATCH_MODE_LABELS.get(mode, mode)


def _populate_image_match_mode_combo(combo: QComboBox):
    combo.blockSignals(True)
    combo.clear()
    for mode, label in IMAGE_MATCH_MODE_LABELS.items():
        combo.addItem(label, mode)
    combo.blockSignals(False)


def _recognition_roi_mode_display_text(mode: str) -> str:
    mode = normalize_recognition_roi_mode(mode)
    return RECOGNITION_ROI_MODE_LABELS.get(mode, mode)


def _populate_recognition_roi_mode_combo(combo: QComboBox):
    combo.blockSignals(True)
    combo.clear()
    for mode, label in RECOGNITION_ROI_MODE_LABELS.items():
        combo.addItem(label, mode)
    combo.blockSignals(False)


def _format_recognition_roi_summary(source) -> str:
    mode = normalize_recognition_roi_mode(getattr(source, "recognition_roi_mode", "full_window"))
    if mode != "window_percent":
        return ""

    roi_x = _coerce_point_ratio(getattr(source, "recognition_roi_x", 0.0), 0.0)
    roi_y = _coerce_point_ratio(getattr(source, "recognition_roi_y", 0.0), 0.0)
    roi_w = max(0.01, _coerce_point_ratio(getattr(source, "recognition_roi_width", 1.0), 1.0))
    roi_h = max(0.01, _coerce_point_ratio(getattr(source, "recognition_roi_height", 1.0), 1.0))
    return f"范围({roi_x:.2f},{roi_y:.2f},{roi_w:.2f},{roi_h:.2f})"


def _populate_remove_coord_mode_combo(combo: QComboBox):
    combo.blockSignals(True)
    combo.clear()
    for mode, label in REMOVE_COORD_MODE_LABELS.items():
        combo.addItem(label, mode)
    combo.blockSignals(False)


def _set_combo_item_enabled(combo: QComboBox, index: int, enabled: bool):
    model = combo.model()
    item = model.item(index) if hasattr(model, "item") else None
    if item is not None:
        item.setEnabled(enabled)


def _populate_grouped_action_type_combo(combo: QComboBox, groups) -> None:
    combo.blockSignals(True)
    combo.clear()

    first_action_index = -1
    for group_index, (category, action_types) in enumerate(groups):
        if group_index > 0:
            combo.insertSeparator(combo.count())
        header_index = combo.count()
        combo.addItem(f"【{ACTION_CATEGORY_LABELS.get(category, category)}】", "")
        _set_combo_item_enabled(combo, header_index, False)
        for action_type in action_types:
            combo.addItem(ACTION_TYPE_LABELS.get(action_type, action_type), action_type)
            if first_action_index < 0:
                first_action_index = combo.count() - 1

    if first_action_index >= 0:
        combo.setCurrentIndex(first_action_index)
    combo.blockSignals(False)


def _coerce_grid_radius(value, default: int = 2) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(0, number)


def _format_traverse_grid_detail(action: Optional[dict]) -> str:
    action = action or {}
    center_param = (action.get("center_param", "") or "").strip()
    target_array = (action.get("target_array", "") or "").strip()
    mode_text = _grid_mode_display_text(action.get("mode", "hex"))
    count = max(0, int(action.get("count", 1000) or 0))

    if center_param and target_array:
        route = f"{center_param} -> {target_array}"
    else:
        route = center_param or target_array

    parts = []
    if route:
        parts.append(route)
    parts.append(mode_text)
    parts.append(f"{count} 个")
    return " / ".join(part for part in parts if part)


def _format_surrounding_coords_detail(action: Optional[dict]) -> str:
    action = action or {}
    target_coord = (action.get("target_coord", "") or "").strip()
    result_array = (action.get("result_array", "") or "").strip()
    mode_text = _grid_mode_display_text(action.get("mode", "hex"))
    radius = _coerce_grid_radius(action.get("radius", 2), 2)

    if target_coord and result_array:
        route = f"{target_coord} => {result_array}"
    else:
        route = target_coord or result_array

    parts = []
    if route:
        parts.append(route)
    parts.append(mode_text)
    parts.append(f"半径 {radius}")
    return " / ".join(part for part in parts if part)


def _format_remove_target_coords_detail(action: Optional[dict]) -> str:
    action = action or {}
    source_array = (action.get("source_array", "") or "").strip()
    target_value = (action.get("target_value", "") or "").strip()
    mode_text = _remove_coord_mode_display_text(action.get("remove_mode", "single"))

    parts = []
    if source_array:
        parts.append(source_array)
    parts.append(mode_text)
    if target_value:
        parts.append(target_value)
    return " / ".join(part for part in parts if part)


def _configure_remove_coord_target_editor(target_label: QLabel, target_edit: QLineEdit, mode: str):
    mode = normalize_remove_coord_mode(mode)
    if mode == "multiple":
        target_label.setText("待删除坐标组:")
        target_edit.setPlaceholderText("例如: [[100,200],[101,200]] 或 {coord_array}")
        return
    target_label.setText("待删除坐标:")
    target_edit.setPlaceholderText("例如: 100,200 或 {coord.x},{coord.y}")


def _pick_remove_coord_target_reference(parent, task_params: List[TaskParameter], task: Optional[PlanTask], mode: str) -> Optional[str]:
    mode = normalize_remove_coord_mode(mode)
    if mode == "multiple":
        param = _pick_task_param(
            parent,
            task_params,
            "选择坐标数组参数",
            "请选择一个坐标数组参数:",
            filter_type="coord_array",
            task=task,
            empty_message="当前任务没有坐标数组参数",
        )
        return f"{{{param.name}}}" if param else None

    param = _pick_task_param(
        parent,
        task_params,
        "选择坐标参数",
        "请选择一个坐标参数:",
        filter_type="coordinate",
        task=task,
        empty_message="当前任务没有坐标参数",
    )
    if not param:
        return None
    return _build_param_reference(parent, param, allow_coordinate_full=True)


def _format_find_road_path_detail(action: Optional[dict]) -> str:
    action = action or {}
    start_array = (action.get("start_array", "") or "").strip()
    target_coord = (action.get("target_coord", "") or "").strip()
    passable_array = (action.get("passable_array", "") or "").strip()
    result_array = (action.get("result_array", "") or "").strip()
    mode_text = _grid_mode_display_text(action.get("mode", "hex"))

    route = ""
    if start_array and target_coord:
        route = f"{start_array} -> {target_coord}"
    else:
        route = start_array or target_coord

    parts = []
    if route:
        parts.append(route)
    if passable_array:
        parts.append(f"经 {passable_array}")
    if result_array:
        parts.append(f"输出 {result_array}")
    parts.append(mode_text)
    return " / ".join(part for part in parts if part)


def _format_save_recognition_coords_detail(action: Optional[dict]) -> str:
    action = action or {}
    result_array = (action.get("result_array", "") or "").strip()
    return f"输出 {result_array}" if result_array else ""


class _ExecutorSignalBridge(QObject):
    sig_log = Signal(str)
    sig_task_started = Signal(str)
    sig_task_finished = Signal(str, bool)
    sig_step_started = Signal(str, str)
    sig_step_retried = Signal(str, str, int)
    sig_step_paused = Signal()
    sig_ai_warmup_tick = Signal()
    sig_highlight_match = Signal(int, int, int, int, int)
    sig_highlight_matches = Signal(object, int)
    sig_highlight_point = Signal(int, int, int)


class _RecognitionHighlightOverlay(QWidget):
    def __init__(self):
        super().__init__(None)
        flags = Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        if hasattr(Qt, "WindowDoesNotAcceptFocus"):
            flags |= Qt.WindowDoesNotAcceptFocus
        if hasattr(Qt, "WindowTransparentForInput"):
            flags |= Qt.WindowTransparentForInput
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.hide()

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)
        self._rects: List[dict] = []
        self._points: List[tuple] = []

    def _sync_native_topmost(self):
        try:
            import ctypes
            hwnd = int(self.winId())
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            user32.SetWindowPos(
                hwnd,
                -1,
                0,
                0,
                0,
                0,
                0x0001 | 0x0002 | 0x0010 | 0x0040,
            )
        except Exception:
            return

    def show_rect(self, left: int, top: int, width: int, height: int, duration_ms: int = 1200):
        self.show_rects([
            {
                "left": left,
                "top": top,
                "width": width,
                "height": height,
            }
        ], duration_ms)

    def show_rects(self, rects: List[dict], duration_ms: int = 1200):
        border = 3
        text_gap = 4
        text_padding_x = 6
        text_padding_y = 3
        metrics = self.fontMetrics()
        normalized = []
        self._points = []
        for rect in rects or []:
            if not isinstance(rect, dict):
                continue
            width = max(2, int(rect.get("width", 0) or 0))
            height = max(2, int(rect.get("height", 0) or 0))
            left = int(rect.get("left", 0) or 0)
            top = int(rect.get("top", 0) or 0)
            overlay_text = str(rect.get("overlay_text", "") or "").strip()
            text_width = metrics.horizontalAdvance(overlay_text) if overlay_text else 0
            text_height = metrics.height() if overlay_text else 0
            normalized.append({
                "left": left,
                "top": top,
                "width": width,
                "height": height,
                "overlay_text": overlay_text,
                "text_width": int(text_width),
                "text_height": int(text_height),
            })

        if not normalized:
            self.hide()
            return

        min_left = min(item["left"] for item in normalized)
        min_top = min(
            item["top"] - (item["text_height"] + text_padding_y * 2 + text_gap)
            if item["overlay_text"] else item["top"]
            for item in normalized
        )
        max_right = max(
            item["left"] + max(item["width"], item["text_width"] + text_padding_x * 2)
            for item in normalized
        )
        max_bottom = max(item["top"] + item["height"] for item in normalized)
        self._rects = [
            {
                "left": item["left"] - min_left + border,
                "top": item["top"] - min_top + border,
                "width": item["width"],
                "height": item["height"],
                "overlay_text": item["overlay_text"],
                "text_width": item["text_width"],
                "text_height": item["text_height"],
            }
            for item in normalized
        ]
        self.setGeometry(
            min_left - border,
            min_top - border,
            max(2, max_right - min_left + border * 2),
            max(2, max_bottom - min_top + border * 2),
        )
        self.show()
        self.raise_()
        self._sync_native_topmost()
        self.update()
        self._hide_timer.start(max(100, int(duration_ms)))

    def show_point(self, x: int, y: int, duration_ms: int = 1200):
        self.show_points([
            {
                "x": x,
                "y": y,
            }
        ], duration_ms)

    def show_points(self, points: List[dict], duration_ms: int = 1200):
        radius = 10
        border = radius + 4
        normalized = []
        self._rects = []
        for point in points or []:
            if not isinstance(point, dict):
                continue
            normalized.append((int(point.get("x", 0) or 0), int(point.get("y", 0) or 0)))

        if not normalized:
            self.hide()
            return

        min_x = min(x for x, _y in normalized)
        min_y = min(y for _x, y in normalized)
        max_x = max(x for x, _y in normalized)
        max_y = max(y for _x, y in normalized)
        self._points = [
            (x - min_x + border, y - min_y + border)
            for x, y in normalized
        ]
        self.setGeometry(
            min_x - border,
            min_y - border,
            max(2, max_x - min_x + border * 2),
            max(2, max_y - min_y + border * 2),
        )
        self.show()
        self.raise_()
        self._sync_native_topmost()
        self.update()
        self._hide_timer.start(max(100, int(duration_ms)))

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        box_pen = QPen(QColor(220, 32, 32))
        box_pen.setWidth(3)
        painter.setPen(box_pen)
        painter.setBrush(Qt.NoBrush)
        for rect in self._rects:
            left = int(rect.get("left", 0))
            top = int(rect.get("top", 0))
            width = max(1, int(rect.get("width", 0)))
            height = max(1, int(rect.get("height", 0)))
            painter.drawRect(left, top, width, height)

        text_gap = 4
        text_padding_x = 6
        text_padding_y = 3
        metrics = self.fontMetrics()
        text_pen = QPen(QColor(255, 255, 255))
        text_bg_pen = QPen(QColor(220, 32, 32))
        text_bg_brush = QColor(160, 20, 20, 220)
        for rect in self._rects:
            overlay_text = str(rect.get("overlay_text", "") or "").strip()
            if not overlay_text:
                continue
            bubble_width = max(1, int(rect.get("text_width", metrics.horizontalAdvance(overlay_text))) + text_padding_x * 2)
            bubble_height = max(1, int(rect.get("text_height", metrics.height())) + text_padding_y * 2)
            bubble_left = int(rect.get("left", 0))
            bubble_top = int(rect.get("top", 0)) - bubble_height - text_gap
            painter.setPen(text_bg_pen)
            painter.setBrush(text_bg_brush)
            painter.drawRoundedRect(bubble_left, bubble_top, bubble_width, bubble_height, 4, 4)
            painter.setPen(text_pen)
            painter.drawText(
                bubble_left + text_padding_x,
                bubble_top + text_padding_y + metrics.ascent(),
                overlay_text,
            )
            painter.setPen(box_pen)
            painter.setBrush(Qt.NoBrush)
        if self._points:
            dot_pen = QPen(QColor(255, 255, 255))
            dot_pen.setWidth(2)
            painter.setPen(dot_pen)
            painter.setBrush(QColor(220, 32, 32))
            for center_x, center_y in self._points:
                painter.drawEllipse(int(center_x - 10), int(center_y - 10), 20, 20)


class _TaskStepTreeWidget(QTreeWidget):
    stepsDropped = Signal(list, str, str)
    MIME_TYPE = "application/x-gameassistant-step-ids"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_step_ids: List[str] = []
        self._selection_snapshot: List[str] = []
        self.setDragEnabled(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragDropMode(QAbstractItemView.InternalMove)

    def _iter_items(self):
        def _walk(item: QTreeWidgetItem):
            yield item
            for child_index in range(item.childCount()):
                yield from _walk(item.child(child_index))

        for top_index in range(self.topLevelItemCount()):
            top_item = self.topLevelItem(top_index)
            yield from _walk(top_item)

    @staticmethod
    def _has_selected_ancestor(item: QTreeWidgetItem) -> bool:
        parent = item.parent()
        while parent is not None:
            if parent.isSelected():
                return True
            parent = parent.parent()
        return False

    def _selected_drag_items(self) -> List[QTreeWidgetItem]:
        items = []
        for item in self._iter_items():
            if item.isSelected() and not self._has_selected_ancestor(item):
                items.append(item)
        return items

    @staticmethod
    def _item_step_id(item: Optional[QTreeWidgetItem]) -> str:
        if item is None:
            return ""
        return item.data(0, STEP_ID_ROLE) or item.data(0, Qt.UserRole) or ""

    def _selected_drag_step_ids(self) -> List[str]:
        return [self._item_step_id(item) for item in self._selected_drag_items() if self._item_step_id(item)]

    def mousePressEvent(self, event):
        clicked_item = self.itemAt(event.position().toPoint()) if hasattr(event, "position") else self.itemAt(event.pos())
        keep_snapshot = bool(
            event.button() == Qt.LeftButton
            and clicked_item is not None
            and clicked_item.isSelected()
            and not (event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))
        )
        self._selection_snapshot = self._selected_drag_step_ids() if keep_snapshot else []
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self._selection_snapshot = []

    def startDrag(self, supportedActions):
        current_ids = self._selected_drag_step_ids()
        if len(self._selection_snapshot) > len(current_ids):
            current_ids = list(self._selection_snapshot)
        self._drag_step_ids = current_ids
        self._selection_snapshot = []
        super().startDrag(supportedActions)

    def mimeData(self, items):
        mime = super().mimeData(items)
        if mime is None:
            mime = QMimeData()

        step_ids = self._selected_drag_step_ids()
        if len(self._selection_snapshot) > len(step_ids):
            step_ids = list(self._selection_snapshot)
        if step_ids:
            mime.setData(self.MIME_TYPE, json.dumps(step_ids).encode("utf-8"))
        return mime

    @staticmethod
    def _drop_position_name(position) -> str:
        if position == QAbstractItemView.AboveItem:
            return "above"
        if position == QAbstractItemView.BelowItem:
            return "below"
        if position == QAbstractItemView.OnItem:
            return "on"
        return "viewport"

    def dropEvent(self, event):
        step_ids = []
        mime_data = event.mimeData()
        if mime_data is not None and mime_data.hasFormat(self.MIME_TYPE):
            try:
                raw_data = bytes(mime_data.data(self.MIME_TYPE)).decode("utf-8")
                parsed_ids = json.loads(raw_data)
                if isinstance(parsed_ids, list):
                    step_ids = [str(step_id) for step_id in parsed_ids if step_id]
            except Exception:
                step_ids = []

        if not step_ids:
            step_ids = list(self._drag_step_ids or self._selected_drag_step_ids())
        self._drag_step_ids = []
        self._selection_snapshot = []
        if not step_ids:
            event.ignore()
            return

        point = event.position().toPoint() if hasattr(event, "position") else event.pos()
        target_item = self.itemAt(point)
        target_step_id = ""
        if target_item is not None:
            target_step_id = self._item_step_id(target_item)
        drop_position = self._drop_position_name(self.dropIndicatorPosition())

        event.setDropAction(Qt.MoveAction)
        event.accept()
        deferred_step_ids = list(step_ids)
        deferred_target_step_id = target_step_id
        deferred_drop_position = drop_position
        QTimer.singleShot(
            0,
            lambda: self.stepsDropped.emit(
                deferred_step_ids,
                deferred_target_step_id,
                deferred_drop_position,
            ),
        )


def _parse_loose_value(value):
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return ""

    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in ("null", "none"):
        return None

    try:
        return json.loads(text)
    except Exception:
        pass

    try:
        return ast.literal_eval(text)
    except Exception:
        pass

    try:
        if "." in text:
            return float(text)
        return int(text)
    except (TypeError, ValueError):
        return value


def _coerce_struct_field_value(field_type: str, value):
    if field_type == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    return "" if value is None else str(value)


def _normalize_struct_item(struct_def: Optional[StructDefinition], value: dict) -> dict:
    raw = value if isinstance(value, dict) else {}
    if not struct_def:
        return dict(raw)

    normalized = {}
    for field in struct_def.fields:
        normalized[field.name] = _coerce_struct_field_value(
            field.field_type,
            raw.get(field.name),
        )
    return normalized


def _param_type_display_text(param: TaskParameter) -> str:
    if param.param_type == "text":
        return "文字"
    if param.param_type == "image":
        return "图片"
    if param.param_type == "coordinate":
        return "坐标"
    if param.param_type == "coord_array":
        return "坐标数组"
    if param.param_type == "array":
        return get_array_param_type_label(getattr(param, "array_item_type", "string"))
    if is_struct_param_type(param.param_type):
        return f"结构体<{get_struct_name_from_type(param.param_type)}>"
    if is_struct_array_param_type(param.param_type):
        return f"结构体数组<{get_struct_name_from_type(param.param_type)}>"
    return param.param_type


def _param_display_text(param: TaskParameter) -> str:
    return f"{param.name} ({_param_type_display_text(param)})"


def _extract_param_name(item_text: str) -> str:
    if not item_text:
        return ""
    return item_text.split(" (", 1)[0].strip()


def _format_param_value(param: TaskParameter) -> str:
    value = param.value
    if param.param_type == "image":
        return os.path.basename(value) if value else ""
    if param.param_type == "coordinate" and isinstance(value, dict):
        return f"({value.get('x', 0)}, {value.get('y', 0)})"
    if param.param_type == "coord_array" and isinstance(value, list):
        return f"{len(value)} 个坐标"
    if param.param_type == "array" and isinstance(value, list):
        preview_items = []
        for item in value[:3]:
            item_text = "" if item is None else str(item)
            if getattr(param, "array_item_type", "string") == "image":
                item_text = os.path.basename(item_text) or item_text
            preview_items.append(item_text)
        preview = ", ".join(preview_items)
        if len(value) > 3:
            preview = f"{preview}, ..."
        return f"[{preview}]" if preview else "[]"
    if is_struct_param_type(param.param_type) and isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if is_struct_array_param_type(param.param_type) and isinstance(value, list):
        return f"{len(value)} 个结构体项"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else str(value)


def _action_uses_click_offset(action_type: str) -> bool:
    return action_type in (
        "click",
        "double_click",
        "right_click",
        "hold_left_button",
        "input_text",
        "highlight_point",
        "drag_map",
        "drag_match_to_center",
    )


def _action_uses_point_position_mode(action_type: str) -> bool:
    return action_type in (
        "click",
        "double_click",
        "right_click",
        "hold_left_button",
        "input_text",
        "highlight_point",
    )


def _action_uses_highlight_duration(action_type: str) -> bool:
    return action_type in ("highlight_match", "highlight_point")


def _action_uses_drag_duration(action_type: str) -> bool:
    return action_type in ("drag_map", "drag_match_to_center", "hold_left_button")


def _action_uses_center_tolerance(action_type: str) -> bool:
    return action_type == "drag_match_to_center"


def _format_recognition_to_logic_summary(action: Optional[dict]) -> str:
    action = action or {}
    csv_path = (action.get("coordinate_csv_path", "") or "").strip()
    csv_name = os.path.basename(csv_path) if csv_path else ""
    anchor_logical = (action.get("anchor_logical_coord", "") or "").strip()
    anchor_screen = (action.get("anchor_screen_coord", "") or "").strip()
    result_array = (action.get("result_array", "") or "").strip()

    parts = []
    if csv_name or csv_path:
        parts.append(csv_name or csv_path)
    if anchor_logical:
        parts.append(f"锚逻辑 {anchor_logical}")
    if anchor_screen:
        parts.append(f"锚相对 {anchor_screen}")
    if result_array:
        parts.append(f"输出 {result_array}")
    return " / ".join(parts)


def _coerce_drag_start_ratio(value, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def _coerce_drag_vector_component(value, default: float = 0.0) -> float:
    return coerce_float(value, default)


def _coerce_highlight_duration_ms(value, default: int = 1200) -> int:
    return normalize_highlight_duration_ms(value, default)


def _highlight_duration_seconds_from_ms(value, default_ms: int = 1200) -> float:
    return _coerce_highlight_duration_ms(value, default_ms) / 1000.0


def _format_highlight_duration_seconds(value) -> str:
    text = f"{_highlight_duration_seconds_from_ms(value):.2f}".rstrip("0").rstrip(".")
    return f"{text or '0'}秒"


def _coerce_action_bool(source, key: str, default: bool = False) -> bool:
    value = _extract_drag_config_value(source, key, default)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "y")
    return bool(value)


def _format_highlight_match_summary(source) -> str:
    duration_text = _format_highlight_duration_seconds(
        _extract_drag_config_value(source, "duration_ms", 1200)
    )
    if _coerce_action_bool(source, "show_ai_attributes", False):
        return f"{duration_text} / 显示AI属性"
    return duration_text


def _format_drag_vector_component(value) -> str:
    text = f"{_coerce_drag_vector_component(value, 0.0):.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _extract_drag_config_value(source, key: str, default=None):
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def _coerce_point_ratio(value, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def _get_action_point_values(source):
    mode = normalize_point_position_mode(
        _extract_drag_config_value(source, "point_position_mode", "recognition")
    )
    default_value = 0.5 if mode == "screen_percent" else 0.0
    point_x = coerce_float(_extract_drag_config_value(source, "point_x", default_value), default_value)
    point_y = coerce_float(_extract_drag_config_value(source, "point_y", default_value), default_value)
    if mode == "screen_percent":
        point_x = _coerce_point_ratio(point_x, 0.5)
        point_y = _coerce_point_ratio(point_y, 0.5)
    return mode, point_x, point_y


def _get_highlight_point_values(source):
    return _get_action_point_values(source)


def _get_action_point_text(source) -> str:
    value = _extract_drag_config_value(source, "point_coord_text", "")
    return str(value or "").strip()


def _get_action_offset_mode(source, point_mode: str) -> str:
    return normalize_click_offset_mode(
        _extract_drag_config_value(source, "click_offset_mode", ""),
        point_mode,
    )


def _format_action_offset_summary(source, mode: str) -> str:
    offset_x = coerce_float(_extract_drag_config_value(source, "click_offset_x", 0.0), 0.0)
    offset_y = coerce_float(_extract_drag_config_value(source, "click_offset_y", 0.0), 0.0)
    if abs(offset_x) <= 1e-9 and abs(offset_y) <= 1e-9:
        return ""
    offset_mode = _get_action_offset_mode(source, mode)
    label = CLICK_OFFSET_MODE_LABELS.get(offset_mode, "偏移")
    return (
        f" / {label}("
        f"{_format_drag_vector_component(offset_x)}, {_format_drag_vector_component(offset_y)})"
    )


def _format_action_point_summary(source) -> str:
    mode, point_x, point_y = _get_action_point_values(source)
    point_text = _get_action_point_text(source)
    if mode == "recognition":
        offset_text = _format_action_offset_summary(source, mode)
        return f"识别结果坐标{offset_text}"
    if point_text:
        if mode == "screen_percent":
            return f"目标窗口比例({point_text}){_format_action_offset_summary(source, mode)}"
        return f"目标窗口({point_text}){_format_action_offset_summary(source, mode)}"
    if mode == "screen_percent":
        return (
            f"目标窗口比例({point_x:.3f}, {point_y:.3f})"
            f"{_format_action_offset_summary(source, mode)}"
        )
    return (
        f"目标窗口({int(round(point_x))}, {int(round(point_y))})"
        f"{_format_action_offset_summary(source, mode)}"
    )


def _format_highlight_point_summary(source) -> str:
    duration_text = _format_highlight_duration_seconds(_extract_drag_config_value(source, "duration_ms", 1200))
    return f"{_format_action_point_summary(source)} / {duration_text}"


def _configure_point_coordinate_spins(x_spin: QDoubleSpinBox, y_spin: QDoubleSpinBox, mode: str):
    mode = normalize_point_position_mode(mode)
    if mode == "screen_percent":
        configs = (
            (x_spin, _coerce_point_ratio(x_spin.value(), 0.5)),
            (y_spin, _coerce_point_ratio(y_spin.value(), 0.5)),
        )
        for spin, value in configs:
            spin.blockSignals(True)
            spin.setRange(0.0, 1.0)
            spin.setSingleStep(0.05)
            spin.setDecimals(3)
            spin.setValue(value)
            spin.blockSignals(False)
        x_spin.setToolTip("相对目标窗口客户区宽度的比例，例如 0.5 表示窗口水平中心")
        y_spin.setToolTip("相对目标窗口客户区高度的比例，例如 0.5 表示窗口垂直中心")
        return

    configs = (
        (x_spin, coerce_float(x_spin.value(), 0.0)),
        (y_spin, coerce_float(y_spin.value(), 0.0)),
    )
    for spin, value in configs:
        spin.blockSignals(True)
        spin.setRange(-100000.0, 100000.0)
        spin.setSingleStep(10.0)
        spin.setDecimals(0)
        spin.setValue(value)
        spin.blockSignals(False)
    x_spin.setToolTip("相对目标窗口客户区左上角的 X 坐标，单位为像素")
    y_spin.setToolTip("相对目标窗口客户区左上角的 Y 坐标，单位为像素")


def _configure_offset_spin(spin: QDoubleSpinBox, minimum: float, maximum: float, step: float, decimals: int):
    value = coerce_float(spin.value(), 0.0)
    spin.blockSignals(True)
    spin.setRange(min(minimum, value), max(maximum, value))
    spin.setSingleStep(step)
    spin.setDecimals(decimals)
    spin.setValue(value)
    spin.blockSignals(False)


def _configure_click_offset_spins(
    x_spin: QDoubleSpinBox,
    y_spin: QDoubleSpinBox,
    offset_mode: str,
    hint_label: QLabel = None,
):
    offset_mode = normalize_click_offset_mode(offset_mode)
    if offset_mode == "screen_absolute":
        _configure_offset_spin(x_spin, -100000.0, 100000.0, 1.0, 2)
        _configure_offset_spin(y_spin, -100000.0, 100000.0, 1.0, 2)
        x_tip = "基于目标窗口客户区像素的偏移\nX 正数向右，负数向左"
        y_tip = "基于目标窗口客户区像素的偏移\nY 正数向下，负数向上"
        hint_text = CLICK_OFFSET_SCREEN_ABSOLUTE_HINT_TEXT
    elif offset_mode == "screen_percent":
        _configure_offset_spin(x_spin, -5.0, 5.0, 0.05, 3)
        _configure_offset_spin(y_spin, -5.0, 5.0, 0.05, 3)
        x_tip = "基于目标窗口客户区宽度比例的偏移\nX=0.5 表示额外向右偏移半个窗口宽度"
        y_tip = "基于目标窗口客户区高度比例的偏移\nY=0.5 表示额外向下偏移半个窗口高度"
        hint_text = CLICK_OFFSET_SCREEN_PERCENT_HINT_TEXT
    else:
        _configure_offset_spin(x_spin, -5.0, 5.0, 0.1, 2)
        _configure_offset_spin(y_spin, -10.0, 10.0, 0.1, 2)
        x_tip = (
            "基于匹配图像尺寸的比例偏移\n"
            "0=中心, 0.5=右边缘, -0.5=左边缘\n"
            "1.0=超出右边缘半个图像宽度"
        )
        y_tip = "基于匹配图像尺寸的比例偏移\n0=中心, 0.5=下边缘, -0.5=上边缘"
        hint_text = CLICK_OFFSET_HINT_TEXT

    x_spin.setToolTip(x_tip)
    y_spin.setToolTip(y_tip)
    if hint_label is not None:
        hint_label.setText(hint_text)
        hint_label.setToolTip(hint_text)


def _sync_click_offset_mode_combo_with_point_mode(dialog, point_mode: str):
    if not hasattr(dialog, "_click_offset_mode"):
        return
    point_mode = normalize_point_position_mode(point_mode)
    previous_point_mode = getattr(dialog, "_last_point_position_mode_for_offset", None)
    raw_mode = dialog._click_offset_mode.currentData() or ""
    current_mode = normalize_click_offset_mode(raw_mode, previous_point_mode or point_mode)
    should_sync = False
    if previous_point_mode is None:
        should_sync = raw_mode not in CLICK_OFFSET_MODE_LABELS
    else:
        should_sync = raw_mode not in CLICK_OFFSET_MODE_LABELS or current_mode == get_default_click_offset_mode(previous_point_mode)
    if should_sync:
        _set_combo_data(
            dialog._click_offset_mode,
            get_default_click_offset_mode(point_mode),
            default=get_default_click_offset_mode(point_mode),
        )
    dialog._last_point_position_mode_for_offset = point_mode


def _get_screen_drag_vector_values(source):
    drag_coordinate_mode = _extract_drag_config_value(source, "drag_coordinate_mode", "game_logic") or "game_logic"
    legacy_x, legacy_y = (0.0, 0.0)
    if drag_coordinate_mode == "screen":
        legacy_x, legacy_y = derive_screen_drag_vector(
            _extract_drag_config_value(source, "drag_direction_x", 0),
            _extract_drag_config_value(source, "drag_direction_y", 0),
            _extract_drag_config_value(source, "drag_distance", 200),
        )
    vector_mode = normalize_drag_vector_mode(
        _extract_drag_config_value(source, "drag_vector_mode", "pixel")
    )
    vector_x = _coerce_drag_vector_component(
        _extract_drag_config_value(source, "drag_vector_x", legacy_x),
        legacy_x,
    )
    vector_y = _coerce_drag_vector_component(
        _extract_drag_config_value(source, "drag_vector_y", legacy_y),
        legacy_y,
    )
    return vector_mode, vector_x, vector_y


def _find_task_param(task_params: List[TaskParameter], param_name: str) -> Optional[TaskParameter]:
    return next((param for param in task_params if param.name == param_name), None)


def _normalize_param_filter_types(filter_type) -> Optional[tuple]:
    if not filter_type:
        return None
    if isinstance(filter_type, str):
        return (filter_type,)
    return tuple(filter_type)


def _param_matches_filter(param: TaskParameter, filter_type=None,
                          predicate: Optional[Callable[[TaskParameter], bool]] = None) -> bool:
    normalized_types = _normalize_param_filter_types(filter_type)
    if normalized_types and param.param_type not in normalized_types:
        return False
    if predicate and not predicate(param):
        return False
    return True


def _collect_task_params(task_params: List[TaskParameter], filter_type=None,
                         predicate: Optional[Callable[[TaskParameter], bool]] = None) -> List[TaskParameter]:
    return [param for param in (task_params or []) if _param_matches_filter(param, filter_type, predicate)]


def _populate_param_combo(combo: QComboBox, task_params: List[TaskParameter], empty_text: str,
                          filter_type=None, predicate: Optional[Callable[[TaskParameter], bool]] = None,
                          selected_name: Optional[str] = None) -> List[TaskParameter]:
    params = _collect_task_params(task_params, filter_type=filter_type, predicate=predicate)
    if selected_name is not None:
        current_name = selected_name
    elif combo.count():
        current_name = combo.currentData() or (combo.currentText().strip() if combo.isEditable() else "")
    else:
        current_name = ""

    combo.blockSignals(True)
    combo.clear()
    if params:
        for param in params:
            combo.addItem(_param_display_text(param), param.name)
        current_index = combo.findData(current_name)
        if current_index >= 0:
            combo.setCurrentIndex(current_index)
        elif combo.isEditable() and current_name:
            combo.setCurrentIndex(-1)
            combo.setEditText(str(current_name))
        else:
            combo.setCurrentIndex(0)
    else:
        combo.addItem(empty_text, "")
        if combo.isEditable() and current_name:
            combo.setEditText(str(current_name))
    combo.blockSignals(False)
    return params


def _inline_create_task_param(parent, task: Optional[PlanTask],
                              task_params: Optional[List[TaskParameter]] = None) -> Optional[TaskParameter]:
    if task is None:
        QMessageBox.information(parent, "提示", "当前场景无法直接创建变量")
        return None

    dlg = ParamEditDialog(task=task, parent=parent)
    if dlg.exec() != QDialog.Accepted:
        return None

    param = dlg.get_param()
    if not param.name:
        return None
    if _find_task_param(task.parameters, param.name):
        QMessageBox.warning(parent, "提示", f"变量 '{param.name}' 已存在")
        return None

    task.parameters.append(param)
    if task_params is not None and task_params is not task.parameters:
        task_params.append(param)

    ancestor = parent
    while ancestor is not None:
        if ancestor.__class__.__name__ == "TaskEditDialog" and hasattr(ancestor, "_load_params"):
            ancestor._load_params()
            break
        ancestor = ancestor.parent()

    return param


def _pick_task_param(parent, task_params: List[TaskParameter], title: str, prompt: str,
                     filter_type=None, predicate: Optional[Callable[[TaskParameter], bool]] = None,
                     task: Optional[PlanTask] = None, empty_message: str = "当前没有可用参数") -> Optional[TaskParameter]:
    params = _collect_task_params(task_params, filter_type=filter_type, predicate=predicate)
    if not params and task is None:
        QMessageBox.information(parent, "提示", empty_message)
        return None

    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(420)

    layout = QVBoxLayout(dlg)
    prompt_label = QLabel(prompt)
    prompt_label.setWordWrap(True)
    layout.addWidget(prompt_label)

    list_widget = QListWidget()
    layout.addWidget(list_widget)

    if task is not None:
        empty_text = f"{empty_message}。可点击下方“创建变量”。"
    else:
        empty_text = empty_message
    empty_label = QLabel(empty_text)
    empty_label.setWordWrap(True)
    empty_label.setStyleSheet("color: gray;")
    layout.addWidget(empty_label)

    button_row = QHBoxLayout()
    create_btn = QPushButton("创建变量")
    create_btn.setVisible(task is not None)
    button_row.addWidget(create_btn)
    button_row.addStretch()
    layout.addLayout(button_row)

    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    ok_button = buttons.button(QDialogButtonBox.Ok)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)

    list_widget.itemDoubleClicked.connect(lambda _item: dlg.accept())

    def refresh(selected_name: str = ""):
        filtered_params = _collect_task_params(task_params, filter_type=filter_type, predicate=predicate)
        list_widget.clear()
        for param in filtered_params:
            item = QListWidgetItem(_param_display_text(param))
            item.setData(Qt.UserRole, param.name)
            list_widget.addItem(item)

        if list_widget.count() > 0:
            target_name = selected_name or list_widget.item(0).data(Qt.UserRole)
            for row in range(list_widget.count()):
                item = list_widget.item(row)
                if item.data(Qt.UserRole) == target_name:
                    list_widget.setCurrentItem(item)
                    break

        has_items = list_widget.count() > 0
        empty_label.setVisible(not has_items)
        ok_button.setEnabled(has_items)

    def handle_create():
        new_param = _inline_create_task_param(dlg, task, task_params)
        if not new_param:
            return
        if not _param_matches_filter(new_param, filter_type=filter_type, predicate=predicate):
            refresh()
            QMessageBox.information(dlg, "提示", f"变量“{new_param.name}”已创建，但不在当前可选范围内")
            return
        refresh(new_param.name)

    create_btn.clicked.connect(handle_create)
    refresh()

    if dlg.exec() != QDialog.Accepted:
        return None

    current_item = list_widget.currentItem()
    if current_item is None:
        return None
    return _find_task_param(task_params, current_item.data(Qt.UserRole))


def _pick_array_task_param(parent, task_params: List[TaskParameter], title: str = "选择数组参数",
                           prompt: str = "请选择一个数组参数:", task: Optional[PlanTask] = None,
                           empty_message: str = "当前任务没有可用数组参数") -> Optional[TaskParameter]:
    return _pick_task_param(
        parent,
        task_params,
        title,
        prompt,
        predicate=lambda param: is_array_param_type(param.param_type),
        task=task,
        empty_message=empty_message,
    )


def _get_array_item_type(param: Optional[TaskParameter], default: str = "string") -> str:
    if not param or param.param_type != "array":
        return default
    return getattr(param, "array_item_type", default) or default


def _is_int_array_param(param: Optional[TaskParameter]) -> bool:
    return bool(param and param.param_type == "array" and _get_array_item_type(param) == "int")


def _is_image_array_param(param: Optional[TaskParameter]) -> bool:
    return bool(param and param.param_type == "array" and _get_array_item_type(param) == "image")


def _is_ai_tile_recognition_type(recognition_type: str) -> bool:
    return recognition_type == "ai_tile"


def _is_image_like_recognition_type(recognition_type: str) -> bool:
    return recognition_type in ("image", "multi_image", "ai_tile")


def _get_recognition_target_candidates(task_params: List[TaskParameter], recognition_type: str) -> List[TaskParameter]:
    candidates = []
    for param in task_params:
        array_item_type = _get_array_item_type(param)
        if recognition_type in ("image", "multi_image"):
            if param.param_type in ("image", "text"):
                candidates.append(param)
            elif param.param_type == "array" and array_item_type in ("image", "string"):
                candidates.append(param)
        elif recognition_type == "ai_tile":
            if param.param_type in ("image", "text"):
                candidates.append(param)
        elif recognition_type == "text":
            if param.param_type == "text":
                candidates.append(param)
            elif param.param_type == "array" and array_item_type == "string":
                candidates.append(param)
    return candidates


def _format_array_assignment_item(task_params: List[TaskParameter], item: dict) -> str:
    array_name = item.get("array_name", "")
    value = item.get("value", "")
    target_param = _find_task_param(task_params, array_name)
    display_value = value
    if _is_image_array_param(target_param) and isinstance(value, str) and value and "{" not in value:
        display_value = os.path.basename(value) or value
    return f"{array_name} ← {display_value}"


def _iter_steps_in_display_order(steps: List[SingleTask]):
    display_index = 0

    def _walk(step_list: List[SingleTask]):
        nonlocal display_index
        for step in step_list:
            display_index += 1
            yield display_index, step
            if step.is_loop and step.children:
                yield from _walk(step.children)

    yield from _walk(steps or [])


def _iter_jump_target_options(task_steps: List[SingleTask], step_list: Optional[List[SingleTask]] = None):
    current_list = task_steps if step_list is None else step_list
    for local_index, step in enumerate(current_list or [], start=1):
        label = _format_step_brief_text(
            step,
            local_index,
            task_steps=task_steps,
            include_step_id=True,
        )
        yield label, step.id
        if step.is_loop and step.children:
            yield from _iter_jump_target_options(task_steps, step.children)


def _populate_jump_target_combo(combo: QComboBox, task_steps: List[SingleTask]):
    current_target_id = combo.currentData() if combo.count() else ""

    combo.setMaxVisibleItems(18)
    combo.setView(QListView(combo))
    combo.view().setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    combo.view().setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    combo.view().setTextElideMode(Qt.ElideMiddle)

    combo.blockSignals(True)
    combo.clear()
    combo.addItem("-- 请选择步骤 --", "")
    combo.setItemData(0, "不跳转", Qt.ToolTipRole)

    for label, step_id in _iter_jump_target_options(task_steps or []):
        combo.addItem(label, step_id)
        combo.setItemData(combo.count() - 1, label, Qt.ToolTipRole)

    current_index = combo.findData(current_target_id)
    combo.setCurrentIndex(current_index if current_index >= 0 else 0)
    combo.blockSignals(False)

    width_hint = combo.width()
    try:
        width_hint = max(width_hint, (combo.view().sizeHintForColumn(0) or 0) + 36)
    except Exception:
        pass
    combo.view().setMinimumWidth(min(900, width_hint))


def _get_step_display_info(task_steps: List[SingleTask], target_id: str) -> Optional[dict]:
    if not target_id:
        return None

    def _walk(step_list: List[SingleTask], parent_step: Optional[SingleTask] = None, parent_index: Optional[int] = None):
        for local_index, step in enumerate(step_list or [], start=1):
            if step.id == target_id:
                display_name = step.name if step.name != "未命名步骤" else f"步骤{local_index}"
                return {
                    "index": local_index,
                    "name": display_name,
                    "step": step,
                    "parent_step": parent_step,
                    "parent_index": parent_index,
                }
            if step.is_loop and step.children:
                found = _walk(step.children, step, local_index)
                if found is not None:
                    return found
        return None

    return _walk(task_steps or [])


def _format_step_brief_text(step: SingleTask, index: int, task_steps: Optional[List[SingleTask]] = None,
                            include_step_id: bool = False, expand_jump_target: bool = True) -> str:
    rec_type_names = {
        "text": "文字", "image": "图像", "multi_image": "多图像(动画帧)", "ai_tile": "AI地块", "none": "无",
    }
    rec_type = rec_type_names.get(step.recognition_type, step.recognition_type)
    image_match_mode = normalize_image_match_mode(getattr(step, "image_match_mode", "template"))
    if step.recognition_type in ("image", "multi_image") and image_match_mode in IMAGE_MATCH_MODE_SHORT_LABELS:
        rec_type = f"{rec_type}/{IMAGE_MATCH_MODE_SHORT_LABELS[image_match_mode]}"
    roi_mode = normalize_recognition_roi_mode(getattr(step, "recognition_roi_mode", "full_window"))
    if step.recognition_type != "none" and roi_mode in RECOGNITION_ROI_MODE_SHORT_LABELS:
        rec_type = f"{rec_type}/{RECOGNITION_ROI_MODE_SHORT_LABELS[roi_mode]}"
    mode = "后台" if step.use_background else "前台"
    action_items = [action for action in step.actions if isinstance(action, dict) and action.get("type")]
    if not action_items:
        legacy_action = _legacy_step_action_to_dict(step)
        if legacy_action:
            action_items = [legacy_action]

    if action_items:
        first_action = action_items[0]
        first_action_type = _normalize_grid_action_type(first_action.get("type", "none"))
        action = ACTION_TYPE_LABELS.get(first_action_type, first_action_type)
        extra = ""
        if first_action_type in ("input_text", "mark_blocked") and first_action.get("input_text"):
            extra = f' "{first_action.get("input_text", "")}"'
        elif first_action_type == "press_key" and first_action.get("press_keys"):
            extra = f' [{first_action.get("press_keys", "")}]'
        elif first_action_type == "modify_variable":
            extra = f' {first_action.get("var_name", "")}={first_action.get("var_value", "")}'
        elif first_action_type == "remove_target_coords":
            detail = _format_remove_target_coords_detail(first_action)
            extra = f' {detail}' if detail else ""
        elif first_action_type == "clear_array_data":
            extra = f' {first_action.get("array_name", "")}'
        elif first_action_type == "save_recognition_coords":
            detail = _format_save_recognition_coords_detail(first_action)
            extra = f' {detail}' if detail else ""
        elif first_action_type == "recognition_to_logic_coord":
            detail = _format_recognition_to_logic_summary(first_action)
            extra = f' {detail}' if detail else ""
        elif first_action_type == "jump_to_step":
            if expand_jump_target:
                target_brief = _format_jump_target_brief(task_steps, first_action.get("target_id", ""))
                extra = f' →{target_brief}' if target_brief else ""
            else:
                target_id = first_action.get("target_id", "")
                extra = f' →{target_id}' if target_id else ""
        elif first_action_type == "traverse_grid":
            detail = _format_traverse_grid_detail(first_action)
            extra = f' {detail}' if detail else ""
        elif first_action_type == "get_surrounding_coords":
            detail = _format_surrounding_coords_detail(first_action)
            extra = f' {detail}' if detail else ""
        elif first_action_type == "find_road_path":
            detail = _format_find_road_path_detail(first_action)
            extra = f' {detail}' if detail else ""
        if len(action_items) > 1:
            extra = f"{extra} +{len(action_items) - 1}项"
    else:
        action = "无操作"
        extra = ""

    display_name = step.name if step.name != "未命名步骤" else f"步骤{index}"
    step_id_text = f" ({step.id})" if include_step_id else ""
    if step.is_loop:
        return f"[{index}] 循环 {display_name}{step_id_text} | 数组: {step.loop_array}, 变量: {step.loop_var}"

    target_text = step.recognition_target
    target_mode = normalize_recognition_target_mode(getattr(step, "recognition_target_mode", "single"))
    if target_mode in RECOGNITION_TARGET_MODE_SHORT_LABELS:
        target_text = f"{target_text} [{RECOGNITION_TARGET_MODE_SHORT_LABELS[target_mode]}]"
    return (
        f"[{index}] {display_name}{step_id_text} | "
        f"{rec_type}识别: \"{target_text}\" → "
        f"{action}{extra} ({mode})"
    )


def _format_jump_target_brief(task_steps: Optional[List[SingleTask]], target_id: str) -> str:
    if not target_id:
        return ""
    target_info = _get_step_display_info(task_steps or [], target_id)
    if not target_info:
        return target_id
    return _format_step_brief_text(
        target_info["step"],
        target_info["index"],
        task_steps=task_steps,
        include_step_id=True,
        expand_jump_target=False,
    )


def _set_jump_target_preview(source_widget: QWidget, target_id: str):
    parent = source_widget.parentWidget() if hasattr(source_widget, "parentWidget") else None
    while parent is not None:
        highlight = getattr(parent, "_highlight_jump_target_step", None)
        if callable(highlight):
            highlight(target_id)
            return
        parent = parent.parentWidget()


def _find_recognition_to_logic_preview_host(source_widget: QWidget):
    parent = source_widget.parentWidget() if hasattr(source_widget, "parentWidget") else None
    while parent is not None:
        preview = getattr(parent, "_preview_recognition_to_logic_action", None)
        if callable(preview):
            return parent
        parent = parent.parentWidget()
    return None


class _JumpTargetPickerDialog(QDialog):
    def __init__(self, task_steps: List[SingleTask], current_target_id: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择跳转步骤")
        self.resize(900, 560)
        self._task_steps = task_steps or []
        self._selected_step_id = current_target_id or ""

        layout = QVBoxLayout(self)

        hint_label = QLabel("双击步骤可直接确认")
        layout.addWidget(hint_label)

        self._steps_tree = QTreeWidget()
        self._steps_tree.setHeaderLabels(["步骤"])
        self._steps_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self._steps_tree.itemDoubleClicked.connect(self._accept_selected)
        layout.addWidget(self._steps_tree, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_selected)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate_steps()

    def _populate_steps(self):
        self._steps_tree.clear()

        def _add_items(parent_item: Optional[QTreeWidgetItem], step_list: List[SingleTask]):
            for local_index, step in enumerate(step_list or [], start=1):
                text = _format_step_brief_text(
                    step,
                    local_index,
                    task_steps=self._task_steps,
                    include_step_id=True,
                )
                item = QTreeWidgetItem([text])
                item.setData(0, STEP_ID_ROLE, step.id)
                if parent_item is None:
                    self._steps_tree.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)

                if step.id == self._selected_step_id:
                    self._steps_tree.setCurrentItem(item)
                    parent = item.parent()
                    while parent is not None:
                        parent.setExpanded(True)
                        parent = parent.parent()

                if step.is_loop and step.children:
                    _add_items(item, step.children)
                    item.setExpanded(True)

        _add_items(None, self._task_steps)
        self._steps_tree.resizeColumnToContents(0)

    def _accept_selected(self, *args):
        del args
        current = self._steps_tree.currentItem()
        if current is None:
            QMessageBox.warning(self, "提示", "请先选择一个步骤")
            return
        self._selected_step_id = current.data(0, STEP_ID_ROLE) or ""
        self.accept()

    def selected_step_id(self) -> str:
        return self._selected_step_id


class _JumpTargetPickerComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._task_steps: List[SingleTask] = []
        self.setView(QListView(self))
        self.view().setTextElideMode(Qt.ElideMiddle)

    def set_task_steps(self, task_steps: List[SingleTask]):
        self._task_steps = task_steps or []
        _populate_jump_target_combo(self, self._task_steps)

    def showPopup(self):
        dlg = _JumpTargetPickerDialog(self._task_steps, self.currentData() or "", self)
        if dlg.exec() != QDialog.Accepted:
            return
        target_id = dlg.selected_step_id()
        index = self.findData(target_id)
        if index >= 0:
            self.setCurrentIndex(index)


def _legacy_step_action_to_dict(step: SingleTask) -> Optional[dict]:
    action_type = _normalize_grid_action_type(step.action_type or "none")
    if action_type == "none":
        return None

    action = {
        "type": action_type,
        "delay": 0.0,
    }
    if _action_uses_click_offset(action_type):
        action["click_offset_mode"] = normalize_click_offset_mode(
            getattr(step, "click_offset_mode", get_default_click_offset_mode(getattr(step, "point_position_mode", "recognition"))),
            getattr(step, "point_position_mode", "recognition"),
        )
        action["click_offset_x"] = step.click_offset_x
        action["click_offset_y"] = step.click_offset_y
    if action_type in ("input_text", "mark_blocked"):
        action["input_text"] = step.input_text
    if action_type == "input_text":
        action["clear_method"] = step.clear_method
        action["clear_key_count"] = step.clear_key_count
    if action_type == "press_key":
        action["press_keys"] = step.press_keys
    if _action_uses_highlight_duration(action_type):
        action["duration_ms"] = _coerce_highlight_duration_ms(getattr(step, "highlight_duration_ms", 1200), 1200)
    if _action_uses_point_position_mode(action_type):
        action["point_position_mode"] = normalize_point_position_mode(
            getattr(step, "point_position_mode", "recognition")
        )
        action["point_x"] = coerce_float(getattr(step, "point_x", 0.5), 0.5)
        action["point_y"] = coerce_float(getattr(step, "point_y", 0.5), 0.5)
        action["point_coord_text"] = str(getattr(step, "point_coord_text", "") or "").strip()
    if _action_uses_drag_duration(action_type):
        action["drag_duration"] = step.drag_duration
    if _action_uses_center_tolerance(action_type):
        action["center_tolerance_px"] = normalize_center_tolerance_px(
            getattr(step, "center_tolerance_px", 1)
        )
    if action_type == "drag_map":
        action["drag_coordinate_mode"] = getattr(step, "drag_coordinate_mode", "game_logic") or "game_logic"
        action["drag_start_mode"] = getattr(step, "drag_start_mode", "recognition") or "recognition"
        action["drag_start_x"] = _coerce_drag_start_ratio(getattr(step, "drag_start_x", 0.5), 0.5)
        action["drag_start_y"] = _coerce_drag_start_ratio(getattr(step, "drag_start_y", 0.5), 0.5)
        action["drag_direction_x"] = step.drag_direction_x
        action["drag_direction_y"] = step.drag_direction_y
        action["drag_distance"] = step.drag_distance
        action["drag_vector_mode"] = normalize_drag_vector_mode(getattr(step, "drag_vector_mode", "pixel"))
        action["drag_vector_x"] = _coerce_drag_vector_component(getattr(step, "drag_vector_x", 0.0), 0.0)
        action["drag_vector_y"] = _coerce_drag_vector_component(getattr(step, "drag_vector_y", 0.0), 0.0)
    if action_type == "modify_variable":
        action["var_name"] = step.modify_var_name
        action["var_value"] = step.modify_var_value
    if action_type == "add_to_array":
        action["items"] = copy.deepcopy(step.add_to_array_items)
    if action_type == "save_recognition_coords":
        action["result_array"] = step.recognition_coord_result_array
    if action_type == "remove_target_coords":
        action["source_array"] = step.remove_coord_source_array
        action["target_value"] = step.remove_coord_target_value
        action["remove_mode"] = normalize_remove_coord_mode(getattr(step, "remove_coord_mode", "single"))
    if action_type == "clear_array_data":
        action["array_name"] = step.clear_array_name
    if action_type == "recognition_to_logic_coord":
        action["coordinate_csv_path"] = step.recognition_to_logic_csv_path
        action["anchor_logical_coord"] = step.recognition_to_logic_anchor_logical
        action["anchor_screen_coord"] = step.recognition_to_logic_anchor_screen
        action["result_array"] = step.recognition_to_logic_result_array
    if action_type == "jump_to_step":
        action["target_id"] = step.jump_target_id
    if action_type == "traverse_grid":
        action["center_param"] = step.traverse_center_param
        action["target_array"] = step.traverse_target_array
        action["count"] = step.traverse_count
        action["mode"] = normalize_grid_mode(getattr(step, "traverse_mode", "hex"))
    if action_type == "get_surrounding_coords":
        action["target_coord"] = step.surround_target_coord or step.two_ring_target_coord
        action["result_array"] = step.surround_result_array or step.two_ring_result_array
        action["radius"] = _coerce_grid_radius(getattr(step, "surround_radius", 2), 2)
        action["mode"] = normalize_grid_mode(getattr(step, "surround_mode", "hex"))
    if action_type == "find_road_path":
        action["target_coord"] = step.path_target_coord
        action["start_array"] = step.path_start_array
        action["passable_array"] = step.path_passable_array
        action["result_array"] = step.path_result_array
        action["mode"] = normalize_grid_mode(getattr(step, "path_mode", "hex"))
    return action


def _reset_step_legacy_action_fields(step: SingleTask):
    step.action_type = "none"
    step.click_offset_mode = get_default_click_offset_mode("recognition")
    step.click_offset_x = 0.0
    step.click_offset_y = 0.0
    step.input_text = ""
    step.press_keys = ""
    step.clear_method = "delete_backspace"
    step.clear_key_count = 3
    step.drag_coordinate_mode = "game_logic"
    step.drag_start_mode = "recognition"
    step.drag_start_x = 0.5
    step.drag_start_y = 0.5
    step.drag_direction_x = 0
    step.drag_direction_y = 0
    step.drag_distance = 200
    step.drag_vector_mode = "pixel"
    step.drag_vector_x = 0.0
    step.drag_vector_y = 0.0
    step.drag_duration = 0.3
    step.center_tolerance_px = 1
    step.highlight_duration_ms = 1200
    step.point_position_mode = "recognition"
    step.point_x = 0.5
    step.point_y = 0.5
    step.point_coord_text = ""
    step.modify_var_name = ""
    step.modify_var_value = ""
    step.add_to_array_items = []
    step.recognition_coord_result_array = ""
    step.remove_coord_source_array = ""
    step.remove_coord_target_value = ""
    step.remove_coord_mode = "single"
    step.clear_array_name = ""
    step.recognition_to_logic_csv_path = ""
    step.recognition_to_logic_anchor_logical = ""
    step.recognition_to_logic_anchor_screen = ""
    step.recognition_to_logic_result_array = ""
    step.jump_target_id = ""
    step.traverse_center_param = ""
    step.traverse_target_array = ""
    step.traverse_count = 1000
    step.traverse_mode = "hex"
    step.two_ring_target_coord = ""
    step.two_ring_result_array = ""
    step.surround_target_coord = ""
    step.surround_result_array = ""
    step.surround_radius = 2
    step.surround_mode = "hex"
    step.path_target_coord = ""
    step.path_start_array = ""
    step.path_passable_array = ""
    step.path_result_array = ""
    step.path_mode = "hex"


def _apply_action_dict_to_step(step: SingleTask, action: Optional[dict]):
    _reset_step_legacy_action_fields(step)
    if not action or not action.get("type"):
        return

    action_type = _normalize_grid_action_type(action.get("type", "none"))
    step.action_type = action_type
    if _action_uses_click_offset(action_type):
        step.click_offset_mode = normalize_click_offset_mode(
            action.get("click_offset_mode", ""),
            action.get("point_position_mode", getattr(step, "point_position_mode", "recognition")),
        )
        step.click_offset_x = float(action.get("click_offset_x", 0) or 0)
        step.click_offset_y = float(action.get("click_offset_y", 0) or 0)
    if action_type in ("input_text", "mark_blocked"):
        step.input_text = action.get("input_text", "")
    if action_type == "input_text":
        step.clear_method = action.get("clear_method", "delete_backspace")
        step.clear_key_count = int(action.get("clear_key_count", 3) or 3)
    if action_type == "press_key":
        step.press_keys = action.get("press_keys", "")
    if _action_uses_highlight_duration(action_type):
        step.highlight_duration_ms = _coerce_highlight_duration_ms(action.get("duration_ms", 1200), 1200)
    if _action_uses_point_position_mode(action_type):
        step.point_position_mode = normalize_point_position_mode(action.get("point_position_mode", "recognition"))
        step.point_x = coerce_float(action.get("point_x", 0.5), 0.5)
        step.point_y = coerce_float(action.get("point_y", 0.5), 0.5)
        step.point_coord_text = str(action.get("point_coord_text", "") or "").strip()
    if _action_uses_drag_duration(action_type):
        step.drag_duration = float(action.get("drag_duration", 0.3) or 0.3)
    if _action_uses_center_tolerance(action_type):
        step.center_tolerance_px = normalize_center_tolerance_px(action.get("center_tolerance_px", 1))
    if action_type == "drag_map":
        step.drag_coordinate_mode = action.get("drag_coordinate_mode", "game_logic") or "game_logic"
        step.drag_start_mode = action.get("drag_start_mode", "recognition") or "recognition"
        step.drag_start_x = _coerce_drag_start_ratio(action.get("drag_start_x", 0.5), 0.5)
        step.drag_start_y = _coerce_drag_start_ratio(action.get("drag_start_y", 0.5), 0.5)
        step.drag_direction_x = int(action.get("drag_direction_x", 0) or 0)
        step.drag_direction_y = int(action.get("drag_direction_y", 0) or 0)
        step.drag_distance = int(action.get("drag_distance", 200) or 200)
        vector_mode, vector_x, vector_y = _get_screen_drag_vector_values(action)
        step.drag_vector_mode = vector_mode
        step.drag_vector_x = vector_x
        step.drag_vector_y = vector_y
    if action_type == "modify_variable":
        step.modify_var_name = action.get("var_name", "")
        step.modify_var_value = action.get("var_value", "")
    if action_type == "add_to_array":
        step.add_to_array_items = copy.deepcopy(action.get("items", []))
    if action_type == "save_recognition_coords":
        step.recognition_coord_result_array = action.get("result_array", "")
    if action_type == "remove_target_coords":
        step.remove_coord_source_array = action.get("source_array", "")
        step.remove_coord_target_value = action.get("target_value", "")
        step.remove_coord_mode = normalize_remove_coord_mode(action.get("remove_mode", "single"))
    if action_type == "clear_array_data":
        step.clear_array_name = action.get("array_name", "")
    if action_type == "recognition_to_logic_coord":
        step.recognition_to_logic_csv_path = action.get("coordinate_csv_path", "")
        step.recognition_to_logic_anchor_logical = action.get("anchor_logical_coord", "")
        step.recognition_to_logic_anchor_screen = action.get("anchor_screen_coord", "")
        step.recognition_to_logic_result_array = action.get("result_array", "")
    if action_type == "jump_to_step":
        step.jump_target_id = action.get("target_id", "")
    if action_type == "traverse_grid":
        step.traverse_center_param = action.get("center_param", "")
        step.traverse_target_array = action.get("target_array", "")
        step.traverse_count = int(action.get("count", 1000) or 1000)
        step.traverse_mode = normalize_grid_mode(action.get("mode", "hex"))
    if action_type == "get_surrounding_coords":
        step.surround_target_coord = action.get("target_coord", "")
        step.surround_result_array = action.get("result_array", "")
        step.surround_radius = _coerce_grid_radius(action.get("radius", 2), 2)
        step.surround_mode = normalize_grid_mode(action.get("mode", "hex"))
        step.two_ring_target_coord = step.surround_target_coord
        step.two_ring_result_array = step.surround_result_array
    if action_type == "find_road_path":
        step.path_target_coord = action.get("target_coord", "")
        step.path_start_array = action.get("start_array", "")
        step.path_passable_array = action.get("passable_array", "")
        step.path_result_array = action.get("result_array", "")
        step.path_mode = normalize_grid_mode(action.get("mode", "hex"))


def _format_action_summary(action: Optional[dict], task_steps: Optional[List[SingleTask]] = None) -> str:
    action = action or {}
    action_type = _normalize_grid_action_type(action.get("type", "none"))
    name = ACTION_TYPE_LABELS.get(action_type, action_type or "无操作")
    detail = ""

    if action_type in ("click", "double_click", "right_click"):
        detail = _format_action_point_summary(action)
    elif action_type == "input_text":
        detail = _format_action_point_summary(action)
        input_text = action.get("input_text", "")
        if input_text:
            detail = f"{detail} / {input_text}" if detail else input_text
    elif action_type == "mark_blocked":
        detail = action.get("input_text", "")
    elif action_type == "press_key":
        detail = action.get("press_keys", "")
    elif action_type == "hold_left_button":
        duration_text = f"{float(action.get('drag_duration', 0.3) or 0.3):.2f}".rstrip("0").rstrip(".")
        point_text = _format_action_point_summary(action)
        detail = f"{point_text} / 按住 {duration_text or '0'} 秒后释放" if point_text else f"按住 {duration_text or '0'} 秒后释放"
    elif action_type == "highlight_match":
        detail = _format_highlight_match_summary(action)
    elif action_type == "highlight_point":
        detail = _format_highlight_point_summary(action)
    elif action_type == "drag_map":
        mode_text = DRAG_COORDINATE_MODE_LABELS.get(action.get("drag_coordinate_mode", "game_logic"), "游戏逻辑")
        start_mode = action.get("drag_start_mode", "recognition") or "recognition"
        if start_mode == "screen_percent":
            start_text = (
                f"窗口({_coerce_drag_start_ratio(action.get('drag_start_x', 0.5), 0.5):.2f}, "
                f"{_coerce_drag_start_ratio(action.get('drag_start_y', 0.5), 0.5):.2f})"
            )
        else:
            start_text = DRAG_START_MODE_LABELS.get(start_mode, "识别坐标")
        if (action.get("drag_coordinate_mode", "game_logic") or "game_logic") == "screen":
            vector_mode, vector_x, vector_y = _get_screen_drag_vector_values(action)
            vector_mode_text = DRAG_VECTOR_MODE_LABELS.get(vector_mode, "像素")
            detail = (
                f"{start_text} / {mode_text} / {vector_mode_text}向量"
                f"({_format_drag_vector_component(vector_x)}, {_format_drag_vector_component(vector_y)})"
            )
        else:
            detail = (
                f"{start_text} / {mode_text} ({action.get('drag_direction_x', 0)}, {action.get('drag_direction_y', 0)}) / "
                f"{action.get('drag_distance', 200)}px"
            )
    elif action_type == "drag_match_to_center":
        duration_text = f"{float(action.get('drag_duration', 0.3) or 0.3):.2f}".rstrip("0").rstrip(".")
        tolerance_px = normalize_center_tolerance_px(action.get("center_tolerance_px", 1))
        detail = f"自动校正到目标窗口中心 / {duration_text or '0'}秒/次 / 允许误差{tolerance_px}px"
    elif action_type == "modify_variable":
        detail = f"{action.get('var_name', '')} = {action.get('var_value', '')}"
    elif action_type == "add_to_array":
        detail = f"{len(action.get('items', []))} 个数组项"
    elif action_type == "save_recognition_coords":
        detail = _format_save_recognition_coords_detail(action)
    elif action_type == "remove_target_coords":
        detail = _format_remove_target_coords_detail(action)
    elif action_type == "clear_array_data":
        detail = action.get("array_name", "")
    elif action_type == "recognition_to_logic_coord":
        detail = _format_recognition_to_logic_summary(action)
    elif action_type == "jump_to_step":
        detail = _format_jump_target_brief(task_steps, action.get("target_id", ""))
    elif action_type == "traverse_grid":
        detail = _format_traverse_grid_detail(action)
    elif action_type == "get_surrounding_coords":
        detail = _format_surrounding_coords_detail(action)
    elif action_type == "find_road_path":
        detail = _format_find_road_path_detail(action)

    summary = f"{name}: {detail}" if detail else name
    delay = float(action.get("delay", 0) or 0)
    if delay > 0:
        summary = f"{summary}  [延时 {delay:.2f} 秒]"
    return summary


def _set_combo_data(combo: QComboBox, value: str, default: str = "single"):
    index = combo.findData(value)
    if index < 0:
        index = combo.findData(default)
    if index >= 0:
        combo.setCurrentIndex(index)


def _choose_member_path(parent, param: TaskParameter, include_whole: bool = True,
                        wrap_reference: bool = False, allow_coordinate_full: bool = False) -> Optional[str]:
    if param.param_type == "coordinate":
        options = []
        if include_whole:
            options.append(("整个坐标", param.name if not wrap_reference else f"{{{param.name}}}"))
        if allow_coordinate_full:
            options.append(("完整坐标 {x},{y}", f"{{{param.name}.x}},{{{param.name}.y}}"))
        options.extend([
            ("X 坐标", f"{param.name}.x" if not wrap_reference else f"{{{param.name}.x}}"),
            ("Y 坐标", f"{param.name}.y" if not wrap_reference else f"{{{param.name}.y}}"),
        ])
        labels = [label for label, _ in options]
        selected, ok = QInputDialog.getItem(parent, "选择坐标字段", "请选择坐标字段:", labels, 0, False)
        if ok and selected:
            return dict(options)[selected]
        return None

    if isinstance(param.value, dict) and param.value:
        options = []
        if include_whole:
            options.append(("整个结构体", param.name if not wrap_reference else f"{{{param.name}}}"))
        for field_name in param.value.keys():
            target = f"{param.name}.{field_name}"
            options.append((field_name, target if not wrap_reference else f"{{{target}}}"))
        labels = [label for label, _ in options]
        selected, ok = QInputDialog.getItem(parent, "选择结构体字段", "请选择结构体字段:", labels, 0, False)
        if ok and selected:
            return dict(options)[selected]
        return None

    return param.name if not wrap_reference else f"{{{param.name}}}"


def _build_param_reference(parent, param: TaskParameter, allow_coordinate_full: bool = False) -> Optional[str]:
    return _choose_member_path(
        parent,
        param,
        include_whole=not isinstance(param.value, dict),
        wrap_reference=True,
        allow_coordinate_full=allow_coordinate_full,
    )


class LoopStepEditDialog(QDialog):
    """循环步骤编辑对话框"""

    def __init__(self, step: SingleTask = None, task_params: List[TaskParameter] = None,
                 task: PlanTask = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑循环步骤" if step else "新增循环步骤")
        self.setMinimumWidth(500)

        self._step = step or SingleTask(is_loop=True, recognition_type="none", action_type="none")
        self._task = task
        self._task_params = task_params or []
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._form = form

        # 循环步骤名称
        name_layout = QHBoxLayout()
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("例如：遍历所有坐标点")
        name_layout.addWidget(self._name_edit)
        self._step_id_label = QLabel()
        self._step_id_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._step_id_label.setStyleSheet("color: gray;")
        name_layout.addWidget(self._step_id_label)
        form.addRow("循环名称:", name_layout)

        # 遍历的数组参数
        loop_array_layout = QHBoxLayout()
        self._loop_array_combo = QComboBox()
        self._loop_array_combo.setEditable(True)
        self._loop_array_combo.currentIndexChanged.connect(self._on_array_changed)
        loop_array_layout.addWidget(self._loop_array_combo)
        self._loop_array_create_btn = QPushButton("创建变量")
        self._loop_array_create_btn.clicked.connect(self._create_loop_array_param)
        self._loop_array_create_btn.setVisible(self._task is not None)
        loop_array_layout.addWidget(self._loop_array_create_btn)
        form.addRow("遍历数组:", loop_array_layout)

        # 元素变量（选择任务变量，每次循环自动更新该变量的值）
        loop_var_layout = QHBoxLayout()
        self._loop_var_combo = QComboBox()
        self._loop_var_combo.setEditable(True)
        loop_var_layout.addWidget(self._loop_var_combo)
        self._loop_var_create_btn = QPushButton("创建变量")
        self._loop_var_create_btn.clicked.connect(self._create_loop_var_param)
        self._loop_var_create_btn.setVisible(self._task is not None)
        loop_var_layout.addWidget(self._loop_var_create_btn)
        form.addRow("元素变量:", loop_var_layout)

        # 子步骤数量（只读，显示信息）
        self._children_count_label = QLabel("0")
        form.addRow("子步骤数量:", self._children_count_label)

        # 说明文字
        info_label = QLabel(
            "• 遍历数组：可选择数组参数，也可手输运行时数组名，例如 ai_tile_results\n"
            "• 元素变量：可选择已有变量，也可手输一个临时运行时变量名，例如 tile\n"
            "• 字典型元素可以用 {变量名.字段名} 访问成员，坐标数组仍可用 {变量名.x} 和 {变量名.y}"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: gray; font-size: 10pt; padding: 10px;")
        form.addRow("", info_label)

        if self._loop_array_combo.lineEdit() is not None:
            self._loop_array_combo.lineEdit().setPlaceholderText("数组参数或运行时数组名，例如 ai_tile_results")
        if self._loop_var_combo.lineEdit() is not None:
            self._loop_var_combo.lineEdit().setPlaceholderText("元素变量名，例如 tile")

        layout.addLayout(form)

        # 按钮
        btn_layout = QHBoxLayout()
        self._ok_btn = QPushButton("确定")
        self._ok_btn.clicked.connect(self.accept)
        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(self._ok_btn)
        btn_layout.addWidget(self._cancel_btn)
        layout.addLayout(btn_layout)

    def _on_array_changed(self, index):
        """数组选择变化时，自动建议名称"""
        if index < 0:
            return
        array_name = self._loop_array_combo.currentData() or self._loop_array_combo.currentText().strip()
        if not array_name:
            return
        
        # 自动建议循环名称（如果为空或是默认值）
        current_name = self._name_edit.text()
        if not current_name or current_name.startswith("遍历"):
            self._name_edit.setText(f"遍历{array_name}")

    def _refresh_param_combos(self, selected_array: Optional[str] = None, selected_var: Optional[str] = None):
        array_params = _populate_param_combo(
            self._loop_array_combo,
            self._task_params,
            "（无可用数组参数，请先添加）",
            predicate=lambda param: is_array_param_type(param.param_type),
            selected_name=selected_array,
        )
        _populate_param_combo(
            self._loop_var_combo,
            self._task_params,
            "（无可用参数，请先添加）",
            selected_name=selected_var,
        )
        selected_array_name = self._loop_array_combo.currentData() or self._loop_array_combo.currentText().strip()
        self._ok_btn.setEnabled(bool(array_params) or bool(selected_array_name))

    def _create_loop_array_param(self):
        new_param = _inline_create_task_param(self, self._task, self._task_params)
        if not new_param:
            return

        selected_array = self._loop_array_combo.currentData() or self._loop_array_combo.currentText().strip() or self._step.loop_array
        if is_array_param_type(new_param.param_type):
            selected_array = new_param.name
        else:
            QMessageBox.information(self, "提示", f"变量“{new_param.name}”已创建，但这里需要数组类型变量")

        self._refresh_param_combos(
            selected_array=selected_array,
            selected_var=self._loop_var_combo.currentData() or self._loop_var_combo.currentText().strip() or self._step.loop_var,
        )

    def _create_loop_var_param(self):
        new_param = _inline_create_task_param(self, self._task, self._task_params)
        if not new_param:
            return
        self._refresh_param_combos(
            selected_array=self._loop_array_combo.currentData() or self._loop_array_combo.currentText().strip() or self._step.loop_array,
            selected_var=new_param.name,
        )

    def _load_data(self):
        """加载数据到界面"""
        self._step_id_label.setText(f"ID: {self._step.id}")
        self._refresh_param_combos(
            selected_array=self._step.loop_array,
            selected_var=self._step.loop_var,
        )
        
        # 加载步骤数据
        if self._step.name:
            self._name_edit.setText(self._step.name)
        
        # 显示子步骤数量
        if hasattr(self._step, 'children'):
            self._children_count_label.setText(str(len(self._step.children)))

    def get_step(self) -> SingleTask:
        """获取编辑后的步骤"""
        self._step.name = self._name_edit.text().strip() or "循环步骤"
        self._step.loop_array = self._loop_array_combo.currentData() or self._loop_array_combo.currentText().strip()
        self._step.loop_var = self._loop_var_combo.currentData() or self._loop_var_combo.currentText().strip()
        self._step.is_loop = True
        self._step.recognition_type = "none"
        self._step.action_type = "none"
        return self._step


class StepEditDialog(QDialog):
    """单一步骤编辑对话框"""

    def __init__(self, step: SingleTask = None, task_params: List[TaskParameter] = None, 
                 task_steps: List[SingleTask] = None, task: PlanTask = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑步骤" if step else "新增步骤")
        self.setMinimumWidth(760)

        self._step = step or SingleTask()
        self._task = task
        self._task_params = task_params or []
        self._task_steps = task_steps or []
        self._actions = []
        self._selected_action_index = -1
        self._editing_add_to_array_items = []
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        form = QFormLayout()
        self._form = form
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        # 步骤名称
        name_layout = QHBoxLayout()
        name_layout.setSpacing(8)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("例如：点击开始按钮")
        name_layout.addWidget(self._name_edit)
        self._step_id_label = QLabel()
        self._step_id_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._step_id_label.setStyleSheet("color: gray;")
        self._step_id_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._step_id_label.setMinimumWidth(96)
        name_layout.addWidget(self._step_id_label)
        form.addRow("步骤名称:", name_layout)

        # 识别类型
        self._recognition_type = QComboBox()
        self._recognition_type.addItem("图像识别 (模板匹配)", "image")
        self._recognition_type.addItem("AI 地块识别", "ai_tile")
        self._recognition_type.addItem("文字识别 (OCR)", "text")
        self._recognition_type.addItem("多图像识别 (动画帧/任一匹配)", "multi_image")
        self._recognition_type.addItem("无识别 (直接执行)", "none")
        self._recognition_type.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("识别类型:", self._recognition_type)

        # 识别目标
        target_layout = QVBoxLayout()
        target_layout.setContentsMargins(0, 0, 0, 0)
        target_layout.setSpacing(6)
        target_input_layout = QHBoxLayout()
        target_input_layout.setSpacing(8)
        self._target_edit = QLineEdit()
        self._target_edit.setPlaceholderText("选择模板图片文件路径")
        target_input_layout.addWidget(self._target_edit)
        self._browse_btn = QPushButton("浏览...")
        self._browse_btn.setMinimumWidth(96)
        self._browse_btn.setVisible(True)
        self._browse_btn.clicked.connect(self._browse_template)
        target_input_layout.addWidget(self._browse_btn)
        self._browse_param_btn = QPushButton("从参数选择")
        self._browse_param_btn.setMinimumWidth(96)
        self._browse_param_btn.setVisible(False)
        self._browse_param_btn.clicked.connect(self._browse_target_param)
        target_input_layout.addWidget(self._browse_param_btn)
        target_layout.addLayout(target_input_layout)

        target_mode_layout = QHBoxLayout()
        target_mode_layout.setSpacing(8)
        self._target_mode_text = QLabel("匹配方式:")
        target_mode_layout.addWidget(self._target_mode_text)
        self._target_mode_combo = QComboBox()
        for mode, label in RECOGNITION_TARGET_MODE_LABELS.items():
            self._target_mode_combo.addItem(label, mode)
        self._target_mode_combo.setToolTip("当识别目标来自数组参数时，控制任一匹配成功还是全部匹配成功")
        self._target_mode_combo.setMinimumWidth(150)
        self._target_mode_combo.setMaximumWidth(180)
        target_mode_layout.addWidget(self._target_mode_combo)
        target_mode_layout.addStretch()
        target_layout.addLayout(target_mode_layout)
        form.addRow("识别目标:", target_layout)

        self._ai_tile_usage_hint = QLabel(
            "AI 地块识别成功后会自动写入运行时变量：{ai_tile_result.level}、{ai_tile_result.level_display}、"
            "{ai_tile_result.level_confidence}、{ai_tile_result.resource_type}、{ai_tile_result.resource_type_confidence}、"
            "{ai_tile_result.relation}、{ai_tile_result.relation_confidence}。如勾选“此图像有多个匹配”，还会写入数组 ai_tile_results。"
        )
        self._ai_tile_usage_hint.setWordWrap(True)
        self._ai_tile_usage_hint.setStyleSheet("color: gray;")
        self._ai_tile_usage_hint.setVisible(False)
        form.addRow("", self._ai_tile_usage_hint)

        # 精确匹配
        self._exact_match = QCheckBox("精确匹配文字")
        self._exact_match.setToolTip("勾选后必须完全匹配，否则包含即可")
        self._exact_match.setVisible(False)
        form.addRow("", self._exact_match)

        # 识别阈值
        self._threshold_spin = QDoubleSpinBox()
        self._threshold_spin.setRange(0.1, 1.0)
        self._threshold_spin.setSingleStep(0.05)
        self._threshold_spin.setValue(0.8)
        self._threshold_spin.setToolTip("图像识别的最低置信度，建议0.75-0.9。值越低越容易误匹配")
        form.addRow("识别阈值:", self._threshold_spin)

        self._validate_color_check = QCheckBox("验证颜色一致性")
        self._validate_color_check.setToolTip("勾选后会在模板匹配成功后再核对颜色分布，避免彩色图与其灰度图被当成同一目标")
        form.addRow("", self._validate_color_check)

        self._image_match_mode_combo = QComboBox()
        _populate_image_match_mode_combo(self._image_match_mode_combo)
        self._image_match_mode_combo.setToolTip("普通模板匹配会比对整张模板；前景优先匹配会根据模板边缘自动忽略背景，更适合地块和底图会变化的目标")
        self._image_match_mode_label = QLabel("图像匹配方式:")
        form.addRow(self._image_match_mode_label, self._image_match_mode_combo)

        self._recognition_roi_mode_combo = QComboBox()
        _populate_recognition_roi_mode_combo(self._recognition_roi_mode_combo)
        self._recognition_roi_mode_combo.currentIndexChanged.connect(self._on_recognition_roi_mode_changed)
        self._recognition_roi_mode_combo.setToolTip("默认搜索整个目标窗口；使用自定义范围时，只在指定的目标窗口百分比区域内搜索")
        self._recognition_roi_x_spin = QDoubleSpinBox()
        self._recognition_roi_y_spin = QDoubleSpinBox()
        self._recognition_roi_width_spin = QDoubleSpinBox()
        self._recognition_roi_height_spin = QDoubleSpinBox()
        for spin, value, tooltip in (
            (self._recognition_roi_x_spin, 0.0, "识别范围左上角 X，占目标窗口客户区宽度的比例"),
            (self._recognition_roi_y_spin, 0.0, "识别范围左上角 Y，占目标窗口客户区高度的比例"),
            (self._recognition_roi_width_spin, 1.0, "识别范围宽度，占目标窗口客户区宽度的比例"),
            (self._recognition_roi_height_spin, 1.0, "识别范围高度，占目标窗口客户区高度的比例"),
        ):
            spin.setRange(0.0, 1.0)
            spin.setSingleStep(0.05)
            spin.setDecimals(3)
            spin.setValue(value)
            spin.setToolTip(tooltip)
        self._recognition_roi_width_spin.setMinimum(0.01)
        self._recognition_roi_height_spin.setMinimum(0.01)
        self._recognition_roi_rect_widget = QWidget()
        roi_rect_layout = QHBoxLayout(self._recognition_roi_rect_widget)
        roi_rect_layout.setContentsMargins(0, 0, 0, 0)
        roi_rect_layout.setSpacing(6)
        roi_rect_layout.addWidget(QLabel("X"))
        roi_rect_layout.addWidget(self._recognition_roi_x_spin)
        roi_rect_layout.addWidget(QLabel("Y"))
        roi_rect_layout.addWidget(self._recognition_roi_y_spin)
        roi_rect_layout.addWidget(QLabel("宽"))
        roi_rect_layout.addWidget(self._recognition_roi_width_spin)
        roi_rect_layout.addWidget(QLabel("高"))
        roi_rect_layout.addWidget(self._recognition_roi_height_spin)
        roi_layout = QVBoxLayout()
        roi_layout.setContentsMargins(0, 0, 0, 0)
        roi_layout.setSpacing(6)
        roi_layout.addWidget(self._recognition_roi_mode_combo)
        roi_layout.addWidget(self._recognition_roi_rect_widget)
        self._recognition_roi_label = QLabel("识别范围:")
        form.addRow(self._recognition_roi_label, roi_layout)

        # 匹配序号（多个相同图像时，点击第几个，从左到右、从上到下排序）
        self._match_index_spin = QSpinBox()
        self._match_index_spin.setRange(1, 99)
        self._match_index_spin.setValue(1)
        self._match_index_spin.setToolTip("画面中有多个相同图像时，点击第几个（从左到右、从上到下排序）")
        self._match_index_label = QLabel("匹配序号:")
        form.addRow(self._match_index_label, self._match_index_spin)

        # 多个匹配（强制使用 find_all 排序）
        self._has_multiple_matches = QCheckBox("此图像有多个匹配")
        self._has_multiple_matches.setToolTip("勾选后强制使用 find_all + 排序，确保按从左到右、从上到下的顺序")
        self._has_multiple_matches_label = QLabel("")
        form.addRow(self._has_multiple_matches_label, self._has_multiple_matches)
        self._has_multiple_matches_label.setVisible(False)
        self._has_multiple_matches.setVisible(False)

        # 主操作列表
        self._actions_label = QLabel("识别成功操作:")
        actions_layout = QVBoxLayout()
        self._actions_list = QListWidget()
        self._actions_list.currentRowChanged.connect(self._select_main_action)
        self._actions_list.itemDoubleClicked.connect(lambda _item: self._edit_main_action())
        self._action_add_list_btn = QPushButton("添加操作")
        self._action_add_list_btn.clicked.connect(self._add_main_action)
        self._action_update_btn = QPushButton("编辑操作")
        self._action_update_btn.clicked.connect(self._edit_main_action)
        self._action_del_list_btn = QPushButton("删除操作")
        self._action_del_list_btn.clicked.connect(self._del_main_action)
        self._action_up_btn = QPushButton("上移")
        self._action_up_btn.clicked.connect(self._move_main_action_up)
        self._action_down_btn = QPushButton("下移")
        self._action_down_btn.clicked.connect(self._move_main_action_down)
        actions_layout.addWidget(
            self._create_compact_list_panel(
                self._actions_list,
                [
                    self._action_add_list_btn,
                    self._action_update_btn,
                    self._action_del_list_btn,
                    self._action_up_btn,
                    self._action_down_btn,
                ],
                list_height=96,
            )
        )
        self._action_editor_tip = QLabel("点击添加/编辑操作打开设置窗口，多个操作会按列表顺序执行")
        self._action_editor_tip.setStyleSheet("color: gray;")
        self._action_editor_tip.setWordWrap(True)
        actions_layout.addWidget(self._action_editor_tip)
        form.addRow(self._actions_label, actions_layout)

        # 操作类型
        self._action_type = QComboBox()
        _populate_grouped_action_type_combo(self._action_type, MAIN_ACTION_TYPE_GROUPS)
        self._action_type.currentIndexChanged.connect(self._on_action_type_changed)
        form.addRow("操作类型:", self._action_type)

        self._action_delay_spin = QDoubleSpinBox()
        self._action_delay_spin.setRange(0.0, 6000.0)
        self._action_delay_spin.setSingleStep(0.1)
        self._action_delay_spin.setDecimals(2)
        self._action_delay_spin.setValue(0.0)
        self._action_delay_spin.setSuffix(" 秒")
        self._action_delay_label = QLabel("指令间延时:")
        form.addRow(self._action_delay_label, self._action_delay_spin)

        self._highlight_duration_spin = QDoubleSpinBox()
        self._highlight_duration_spin.setRange(0.1, 60.0)
        self._highlight_duration_spin.setSingleStep(0.1)
        self._highlight_duration_spin.setDecimals(2)
        self._highlight_duration_spin.setValue(1.2)
        self._highlight_duration_spin.setSuffix(" 秒")
        self._highlight_duration_spin.setToolTip("红框或红点在屏幕上停留的时间")
        self._highlight_duration_label = QLabel("标记时长:")
        form.addRow(self._highlight_duration_label, self._highlight_duration_spin)
        self._highlight_duration_label.setVisible(False)
        self._highlight_duration_spin.setVisible(False)

        self._highlight_show_ai_attributes = QCheckBox("在红框旁显示 AI 地块属性")
        self._highlight_show_ai_attributes.setToolTip("仅对 AI 地块识别结果生效，显示等级、类型和关系")
        self._highlight_show_ai_attributes_label = QLabel("AI属性显示:")
        form.addRow(self._highlight_show_ai_attributes_label, self._highlight_show_ai_attributes)
        self._highlight_show_ai_attributes_label.setVisible(False)
        self._highlight_show_ai_attributes.setVisible(False)

        self._point_position_mode = QComboBox()
        self._point_position_mode.addItem("识别结果坐标", "recognition")
        self._point_position_mode.addItem("目标窗口绝对坐标", "screen_absolute")
        self._point_position_mode.addItem("目标窗口百分比坐标", "screen_percent")
        self._point_position_mode.setToolTip(
            "识别结果坐标：使用当前步骤识别出的中心点，可配合下方坐标偏移\n"
            "目标窗口绝对坐标：直接填写相对目标窗口客户区左上角的像素坐标\n"
            "目标窗口百分比坐标：0.5, 0.5 表示目标窗口中心"
        )
        self._point_position_mode.currentIndexChanged.connect(self._update_point_position_mode_ui)
        self._point_position_mode_label = QLabel("坐标来源:")
        form.addRow(self._point_position_mode_label, self._point_position_mode)
        self._point_position_mode_label.setVisible(False)
        self._point_position_mode.setVisible(False)

        self._point_coord_widget = QWidget()
        point_coord_layout = QHBoxLayout(self._point_coord_widget)
        point_coord_layout.setContentsMargins(0, 0, 0, 0)
        point_coord_layout.addWidget(QLabel("X:"))
        self._point_x_spin = QDoubleSpinBox()
        self._point_x_spin.setValue(0.5)
        point_coord_layout.addWidget(self._point_x_spin)
        point_coord_layout.addWidget(QLabel("Y:"))
        self._point_y_spin = QDoubleSpinBox()
        self._point_y_spin.setValue(0.5)
        point_coord_layout.addWidget(self._point_y_spin)
        point_coord_layout.addStretch()
        self._point_coord_label = QLabel("窗口比例:")
        form.addRow(self._point_coord_label, self._point_coord_widget)
        self._point_coord_label.setVisible(False)
        self._point_coord_widget.setVisible(False)
        _configure_point_coordinate_spins(self._point_x_spin, self._point_y_spin, "screen_percent")

        # 输入文本内容（仅 input_text 时可见）
        input_text_layout = QHBoxLayout()
        self._input_text_edit = QLineEdit()
        self._input_text_edit.setPlaceholderText("输入要填写的文本内容，如: 990 或 {param}")
        input_text_layout.addWidget(self._input_text_edit)
        self._input_text_browse_btn = QPushButton("从参数选择")
        self._input_text_browse_btn.clicked.connect(self._browse_input_text_param)
        input_text_layout.addWidget(self._input_text_browse_btn)
        self._input_text_label = QLabel("输入内容:")
        form.addRow(self._input_text_label, input_text_layout)
        self._input_text_label.setVisible(False)
        self._input_text_edit.setVisible(False)
        self._input_text_browse_btn.setVisible(False)

        # 输入前清除方式（仅 input_text 时可见）
        self._clear_method = QComboBox()
        self._clear_method.addItem("Delete+Backspace 逐个删除", "delete_backspace")
        self._clear_method.addItem("Ctrl+A 全选覆盖", "ctrl_a")
        self._clear_method.addItem("不清除（直接追加输入）", "none")
        self._clear_method_label = QLabel("清除方式:")
        form.addRow(self._clear_method_label, self._clear_method)
        self._clear_method_label.setVisible(False)
        self._clear_method.setVisible(False)

        # Delete/Backspace 按键次数（仅 delete_backspace 方式时可见）
        self._clear_key_count_spin = QSpinBox()
        self._clear_key_count_spin.setRange(1, 50)
        self._clear_key_count_spin.setValue(3)
        self._clear_key_count_spin.setToolTip("Delete 和 Backspace 各按这么多次，确保完全清空输入框")
        self._clear_key_count_label = QLabel("删除次数:")
        form.addRow(self._clear_key_count_label, self._clear_key_count_spin)
        self._clear_key_count_label.setVisible(False)
        self._clear_key_count_spin.setVisible(False)
        self._clear_method.currentIndexChanged.connect(self._on_clear_method_changed)

        # 按键/组合键（仅 press_key 时可见）
        self._press_keys_edit = QLineEdit()
        self._press_keys_edit.setPlaceholderText("例如: enter, ctrl+a, tab, escape")
        self._press_keys_edit.setToolTip(
            "单键: enter, tab, escape, space, backspace, delete\n"
            "组合键: ctrl+a, ctrl+c, alt+f4\n"
            "多个按键用逗号分隔: ctrl+a, delete"
        )
        self._press_keys_label = QLabel("按键内容:")
        form.addRow(self._press_keys_label, self._press_keys_edit)
        self._press_keys_label.setVisible(False)
        self._press_keys_edit.setVisible(False)

        self._drag_coordinate_mode = QComboBox()
        self._drag_coordinate_mode.addItem("游戏逻辑坐标偏移", "game_logic")
        self._drag_coordinate_mode.addItem("屏幕坐标偏移", "screen")
        self._drag_coordinate_mode.currentIndexChanged.connect(self._update_drag_coordinate_mode_ui)
        self._drag_coordinate_mode_label = QLabel("拖动坐标系:")
        form.addRow(self._drag_coordinate_mode_label, self._drag_coordinate_mode)
        self._drag_coordinate_mode_label.setVisible(False)
        self._drag_coordinate_mode.setVisible(False)

        self._drag_start_mode = QComboBox()
        self._drag_start_mode.addItem("识别结果中心点", "recognition")
        self._drag_start_mode.addItem("目标窗口百分比坐标", "screen_percent")
        self._drag_start_mode.setToolTip(
            "默认使用识别结果中心点作为拖动起点\n"
            "切换到目标窗口百分比后，可按目标窗口客户区宽高比例指定起点，例如 0.5, 0.5 表示窗口中心"
        )
        self._drag_start_mode.currentIndexChanged.connect(self._update_drag_start_mode_ui)
        self._drag_start_mode_label = QLabel("拖动起点:")
        form.addRow(self._drag_start_mode_label, self._drag_start_mode)
        self._drag_start_mode_label.setVisible(False)
        self._drag_start_mode.setVisible(False)

        self._drag_start_coord_widget = QWidget()
        drag_start_coord_layout = QHBoxLayout(self._drag_start_coord_widget)
        drag_start_coord_layout.setContentsMargins(0, 0, 0, 0)
        drag_start_coord_layout.addWidget(QLabel("X:"))
        self._drag_start_x_spin = QDoubleSpinBox()
        self._drag_start_x_spin.setRange(0.0, 1.0)
        self._drag_start_x_spin.setSingleStep(0.05)
        self._drag_start_x_spin.setDecimals(3)
        self._drag_start_x_spin.setValue(0.5)
        drag_start_coord_layout.addWidget(self._drag_start_x_spin)
        drag_start_coord_layout.addWidget(QLabel("Y:"))
        self._drag_start_y_spin = QDoubleSpinBox()
        self._drag_start_y_spin.setRange(0.0, 1.0)
        self._drag_start_y_spin.setSingleStep(0.05)
        self._drag_start_y_spin.setDecimals(3)
        self._drag_start_y_spin.setValue(0.5)
        drag_start_coord_layout.addWidget(self._drag_start_y_spin)
        drag_start_coord_layout.addStretch()
        self._drag_start_coord_label = QLabel("窗口比例:")
        form.addRow(self._drag_start_coord_label, self._drag_start_coord_widget)
        self._drag_start_coord_label.setVisible(False)
        self._drag_start_coord_widget.setVisible(False)

        self._drag_vector_mode = QComboBox()
        self._drag_vector_mode.addItem("像素", "pixel")
        self._drag_vector_mode.addItem("屏幕百分比", "screen_percent")
        self._drag_vector_mode.currentIndexChanged.connect(self._update_drag_vector_mode_ui)
        self._drag_vector_mode_label = QLabel("向量单位:")
        form.addRow(self._drag_vector_mode_label, self._drag_vector_mode)
        self._drag_vector_mode_label.setVisible(False)
        self._drag_vector_mode.setVisible(False)

        self._drag_vector_widget = QWidget()
        drag_vector_layout = QHBoxLayout(self._drag_vector_widget)
        drag_vector_layout.setContentsMargins(0, 0, 0, 0)
        drag_vector_layout.addWidget(QLabel("X:"))
        self._drag_vector_x_spin = QDoubleSpinBox()
        self._drag_vector_x_spin.setRange(-5000.0, 5000.0)
        self._drag_vector_x_spin.setSingleStep(10.0)
        self._drag_vector_x_spin.setDecimals(3)
        self._drag_vector_x_spin.setValue(0.0)
        drag_vector_layout.addWidget(self._drag_vector_x_spin)
        drag_vector_layout.addWidget(QLabel("Y:"))
        self._drag_vector_y_spin = QDoubleSpinBox()
        self._drag_vector_y_spin.setRange(-5000.0, 5000.0)
        self._drag_vector_y_spin.setSingleStep(10.0)
        self._drag_vector_y_spin.setDecimals(3)
        self._drag_vector_y_spin.setValue(0.0)
        drag_vector_layout.addWidget(self._drag_vector_y_spin)
        drag_vector_layout.addStretch()
        self._drag_vector_label = QLabel("拖动向量:")
        form.addRow(self._drag_vector_label, self._drag_vector_widget)
        self._drag_vector_label.setVisible(False)
        self._drag_vector_widget.setVisible(False)

        # 拖动地图方向（仅 drag_map 时可见）
        drag_dir_layout = QHBoxLayout()
        drag_dir_layout.addWidget(QLabel("X:  "))
        self._drag_dir_x_spin = QSpinBox()
        self._drag_dir_x_spin.setRange(-10, 10)
        self._drag_dir_x_spin.setValue(0)
        self._drag_dir_x_spin.setToolTip(
            "游戏地图X方向格数\n"
            "正数=镜头向X+方向移动（屏幕左下）\n"
            "负数=镜头向X-方向移动（屏幕右上）"
        )
        drag_dir_layout.addWidget(self._drag_dir_x_spin)
        drag_dir_layout.addWidget(QLabel("   Y:  "))
        self._drag_dir_y_spin = QSpinBox()
        self._drag_dir_y_spin.setRange(-10, 10)
        self._drag_dir_y_spin.setValue(0)
        self._drag_dir_y_spin.setToolTip(
            "游戏地图Y方向格数\n"
            "正数=镜头向Y+方向移动（屏幕右下）\n"
            "负数=镜头向Y-方向移动（屏幕左上）"
        )
        drag_dir_layout.addWidget(self._drag_dir_y_spin)
        drag_dir_layout.addStretch()
        self._drag_dir_label = QLabel("拖动方向:")
        form.addRow(self._drag_dir_label, drag_dir_layout)
        self._drag_dir_label.setVisible(False)
        self._drag_dir_x_spin.setVisible(False)
        self._drag_dir_y_spin.setVisible(False)

        # 拖动距离（仅 drag_map 时可见）
        self._drag_distance_spin = QSpinBox()
        self._drag_distance_spin.setRange(10, 2000)
        self._drag_distance_spin.setValue(200)
        self._drag_distance_spin.setSuffix(" 像素")
        self._drag_distance_spin.setToolTip("拖动的屏幕总像素距离（方向由等距坐标自动换算）")
        self._drag_distance_label = QLabel("拖动距离:")
        form.addRow(self._drag_distance_label, self._drag_distance_spin)
        self._drag_distance_label.setVisible(False)
        self._drag_distance_spin.setVisible(False)

        # 拖动持续时间（仅 drag_map 时可见）
        self._drag_duration_spin = QDoubleSpinBox()
        self._drag_duration_spin.setRange(0.1, 5.0)
        self._drag_duration_spin.setSingleStep(0.1)
        self._drag_duration_spin.setValue(0.3)
        self._drag_duration_spin.setSuffix(" 秒")
        self._drag_duration_spin.setToolTip("拖动动作的持续时间")
        self._drag_duration_label = QLabel("拖动时长:")
        form.addRow(self._drag_duration_label, self._drag_duration_spin)
        self._drag_duration_label.setVisible(False)
        self._drag_duration_spin.setVisible(False)

        self._drag_center_tolerance_spin = QSpinBox()
        self._drag_center_tolerance_spin.setRange(1, 200)
        self._drag_center_tolerance_spin.setValue(1)
        self._drag_center_tolerance_spin.setSuffix(" 像素")
        self._drag_center_tolerance_spin.setToolTip("拖动到中心时允许保留的最大误差，值越小校正次数越多，最小 1 像素")
        self._drag_center_tolerance_label = QLabel("允许误差:")
        form.addRow(self._drag_center_tolerance_label, self._drag_center_tolerance_spin)
        self._drag_center_tolerance_label.setVisible(False)
        self._drag_center_tolerance_spin.setVisible(False)
        self._update_point_position_mode_ui()
        self._update_drag_start_mode_ui()
        self._update_drag_vector_mode_ui()
        self._update_drag_coordinate_mode_ui()

        # ── 修改变量（仅 modify_variable 时可见）──
        modify_var_layout = QHBoxLayout()
        self._modify_var_name_edit = QLineEdit()
        self._modify_var_name_edit.setPlaceholderText("变量名（如: counter 或 info.level）")
        modify_var_layout.addWidget(self._modify_var_name_edit)
        self._modify_var_browse_btn = QPushButton("从参数选择")
        self._modify_var_browse_btn.clicked.connect(self._browse_variable_name)
        modify_var_layout.addWidget(self._modify_var_browse_btn)
        self._modify_var_name_label = QLabel("变量名:")
        form.addRow(self._modify_var_name_label, modify_var_layout)
        self._modify_var_name_label.setVisible(False)
        self._modify_var_name_edit.setVisible(False)
        self._modify_var_browse_btn.setVisible(False)

        self._modify_var_value_edit = QLineEdit()
        self._modify_var_value_edit.setPlaceholderText("新值（支持 {参数} 替换）")
        self._modify_var_value_label = QLabel("变量值:")
        modify_var_value_layout = QHBoxLayout()
        modify_var_value_layout.addWidget(self._modify_var_value_edit)
        self._modify_var_value_browse_btn = QPushButton("从参数选择")
        self._modify_var_value_browse_btn.clicked.connect(self._browse_modify_value)
        modify_var_value_layout.addWidget(self._modify_var_value_browse_btn)
        form.addRow(self._modify_var_value_label, modify_var_value_layout)
        self._modify_var_value_label.setVisible(False)
        self._modify_var_value_edit.setVisible(False)
        self._modify_var_value_browse_btn.setVisible(False)

        # ── 添加到数组（仅 add_to_array 时可见）──
        self._arr_items_label = QLabel("数组项目:")
        arr_items_layout = QVBoxLayout()
        self._arr_items_list = QListWidget()
        self._arr_items_list.setMaximumHeight(100)
        arr_items_layout.addWidget(self._arr_items_list)
        arr_btn_row = QHBoxLayout()
        self._arr_item_add_btn = QPushButton("添加项")
        self._arr_item_add_btn.clicked.connect(self._add_array_item)
        arr_btn_row.addWidget(self._arr_item_add_btn)
        self._arr_item_del_btn = QPushButton("删除项")
        self._arr_item_del_btn.clicked.connect(self._del_array_item)
        arr_btn_row.addWidget(self._arr_item_del_btn)
        arr_btn_row.addStretch()
        arr_items_layout.addLayout(arr_btn_row)
        form.addRow(self._arr_items_label, arr_items_layout)
        self._arr_items_label.setVisible(False)
        self._arr_items_list.setVisible(False)
        self._arr_item_add_btn.setVisible(False)
        self._arr_item_del_btn.setVisible(False)

        remove_coord_source_layout = QHBoxLayout()
        self._remove_coord_source_array_edit = QLineEdit()
        self._remove_coord_source_array_edit.setPlaceholderText("源坐标数组参数名")
        remove_coord_source_layout.addWidget(self._remove_coord_source_array_edit)
        self._remove_coord_source_array_browse_btn = QPushButton("从参数选择")
        self._remove_coord_source_array_browse_btn.clicked.connect(
            lambda: self._browse_param_name(self._remove_coord_source_array_edit, "coord_array")
        )
        remove_coord_source_layout.addWidget(self._remove_coord_source_array_browse_btn)
        self._remove_coord_source_array_label = QLabel("源坐标数组:")
        form.addRow(self._remove_coord_source_array_label, remove_coord_source_layout)
        self._remove_coord_source_array_label.setVisible(False)
        self._remove_coord_source_array_edit.setVisible(False)
        self._remove_coord_source_array_browse_btn.setVisible(False)

        self._remove_coord_mode_combo = QComboBox()
        _populate_remove_coord_mode_combo(self._remove_coord_mode_combo)
        self._remove_coord_mode_combo.currentIndexChanged.connect(self._on_remove_coord_mode_changed)
        self._remove_coord_mode_label = QLabel("删除模式:")
        form.addRow(self._remove_coord_mode_label, self._remove_coord_mode_combo)
        self._remove_coord_mode_label.setVisible(False)
        self._remove_coord_mode_combo.setVisible(False)

        remove_coord_target_layout = QHBoxLayout()
        self._remove_coord_target_value_edit = QLineEdit()
        remove_coord_target_layout.addWidget(self._remove_coord_target_value_edit)
        self._remove_coord_target_value_browse_btn = QPushButton("从参数选择")
        self._remove_coord_target_value_browse_btn.clicked.connect(self._browse_remove_coord_target_value)
        remove_coord_target_layout.addWidget(self._remove_coord_target_value_browse_btn)
        self._remove_coord_target_value_label = QLabel("待删除坐标:")
        form.addRow(self._remove_coord_target_value_label, remove_coord_target_layout)
        self._remove_coord_target_value_label.setVisible(False)
        self._remove_coord_target_value_edit.setVisible(False)
        self._remove_coord_target_value_browse_btn.setVisible(False)
        _configure_remove_coord_target_editor(
            self._remove_coord_target_value_label,
            self._remove_coord_target_value_edit,
            self._remove_coord_mode_combo.currentData() or "single",
        )

        clear_array_layout = QHBoxLayout()
        self._clear_array_edit = QLineEdit()
        self._clear_array_edit.setPlaceholderText("目标数组参数名")
        clear_array_layout.addWidget(self._clear_array_edit)
        self._clear_array_browse_btn = QPushButton("从参数选择")
        self._clear_array_browse_btn.clicked.connect(self._browse_clear_array_name)
        clear_array_layout.addWidget(self._clear_array_browse_btn)
        self._clear_array_label = QLabel("目标数组:")
        form.addRow(self._clear_array_label, clear_array_layout)
        self._clear_array_label.setVisible(False)
        self._clear_array_edit.setVisible(False)
        self._clear_array_browse_btn.setVisible(False)

        recognition_logic_csv_layout = QHBoxLayout()
        self._recognition_to_logic_csv_edit = QLineEdit()
        self._recognition_to_logic_csv_edit.setPlaceholderText("坐标转换导出的 CSV 文件路径")
        recognition_logic_csv_layout.addWidget(self._recognition_to_logic_csv_edit)
        self._recognition_to_logic_csv_browse_btn = QPushButton("浏览文件")
        self._recognition_to_logic_csv_browse_btn.clicked.connect(self._browse_recognition_to_logic_csv)
        recognition_logic_csv_layout.addWidget(self._recognition_to_logic_csv_browse_btn)
        self._recognition_to_logic_csv_label = QLabel("坐标 CSV:")
        form.addRow(self._recognition_to_logic_csv_label, recognition_logic_csv_layout)
        self._recognition_to_logic_csv_label.setVisible(False)
        self._recognition_to_logic_csv_edit.setVisible(False)
        self._recognition_to_logic_csv_browse_btn.setVisible(False)

        recognition_logic_anchor_layout = QHBoxLayout()
        self._recognition_to_logic_anchor_logical_edit = QLineEdit()
        self._recognition_to_logic_anchor_logical_edit.setPlaceholderText(
            "例如: 100,200 或 {anchor_coord.x},{anchor_coord.y}"
        )
        recognition_logic_anchor_layout.addWidget(self._recognition_to_logic_anchor_logical_edit)
        self._recognition_to_logic_anchor_logical_browse_btn = QPushButton("从参数选择")
        self._recognition_to_logic_anchor_logical_browse_btn.clicked.connect(
            lambda: self._browse_value_reference(self._recognition_to_logic_anchor_logical_edit, allow_coordinate_full=True)
        )
        recognition_logic_anchor_layout.addWidget(self._recognition_to_logic_anchor_logical_browse_btn)
        self._recognition_to_logic_anchor_logical_label = QLabel("锚点逻辑坐标:")
        form.addRow(self._recognition_to_logic_anchor_logical_label, recognition_logic_anchor_layout)
        self._recognition_to_logic_anchor_logical_label.setVisible(False)
        self._recognition_to_logic_anchor_logical_edit.setVisible(False)
        self._recognition_to_logic_anchor_logical_browse_btn.setVisible(False)

        recognition_screen_anchor_layout = QHBoxLayout()
        self._recognition_to_logic_anchor_screen_edit = QLineEdit()
        self._recognition_to_logic_anchor_screen_edit.setPlaceholderText(
            "例如: 0.532,0.418 或 {anchor_screen}"
        )
        recognition_screen_anchor_layout.addWidget(self._recognition_to_logic_anchor_screen_edit)
        self._recognition_to_logic_anchor_screen_browse_btn = QPushButton("从参数选择")
        self._recognition_to_logic_anchor_screen_browse_btn.clicked.connect(
            lambda: self._browse_value_reference(self._recognition_to_logic_anchor_screen_edit, allow_coordinate_full=True)
        )
        recognition_screen_anchor_layout.addWidget(self._recognition_to_logic_anchor_screen_browse_btn)
        self._recognition_to_logic_anchor_screen_label = QLabel("锚点屏幕相对坐标:")
        form.addRow(self._recognition_to_logic_anchor_screen_label, recognition_screen_anchor_layout)
        self._recognition_to_logic_anchor_screen_label.setVisible(False)
        self._recognition_to_logic_anchor_screen_edit.setVisible(False)
        self._recognition_to_logic_anchor_screen_browse_btn.setVisible(False)

        recognition_result_array_layout = QHBoxLayout()
        self._recognition_to_logic_result_array_edit = QLineEdit()
        self._recognition_to_logic_result_array_edit.setPlaceholderText("结果坐标数组参数名")
        recognition_result_array_layout.addWidget(self._recognition_to_logic_result_array_edit)
        self._recognition_to_logic_result_array_browse_btn = QPushButton("从参数选择")
        self._recognition_to_logic_result_array_browse_btn.clicked.connect(
            lambda: self._browse_param_name(self._recognition_to_logic_result_array_edit, "coord_array")
        )
        recognition_result_array_layout.addWidget(self._recognition_to_logic_result_array_browse_btn)
        self._recognition_to_logic_result_array_label = QLabel("结果数组:")
        form.addRow(self._recognition_to_logic_result_array_label, recognition_result_array_layout)
        self._recognition_to_logic_result_array_label.setVisible(False)
        self._recognition_to_logic_result_array_edit.setVisible(False)
        self._recognition_to_logic_result_array_browse_btn.setVisible(False)

        # ── 跳转步骤（仅 jump_to_step 时可见）──
        self._jump_target_combo = _JumpTargetPickerComboBox()
        self._populate_jump_targets()
        self._jump_target_combo.currentIndexChanged.connect(self._on_jump_target_changed)
        self._jump_target_label = QLabel("跳转目标:")
        form.addRow(self._jump_target_label, self._jump_target_combo)

        self._delay_spin = QDoubleSpinBox()
        self._delay_spin.setRange(0.0, 6000.0)
        self._delay_spin.setSingleStep(0.1)
        self._delay_spin.setDecimals(2)
        self._delay_spin.setValue(0.0)
        self._delay_spin.setSuffix(" 秒")
        form.addRow("指令间延时:", self._delay_spin)

        offset_layout = QHBoxLayout()
        offset_layout.addWidget(QLabel("X:"))
        self._click_offset_x_spin = QDoubleSpinBox()
        self._click_offset_x_spin.setRange(-5.0, 5.0)
        self._click_offset_x_spin.setSingleStep(0.1)
        self._click_offset_x_spin.setDecimals(2)
        self._click_offset_x_spin.setValue(0.0)
        self._click_offset_x_spin.setToolTip(
            "基于匹配图像尺寸的比例偏移\n"
            "0=中心, 0.5=右边缘, -0.5=左边缘"
        )
        offset_layout.addWidget(self._click_offset_x_spin)
        offset_layout.addWidget(QLabel("Y:"))
        self._click_offset_y_spin = QDoubleSpinBox()
        self._click_offset_y_spin.setRange(-10.0, 10.0)
        self._click_offset_y_spin.setSingleStep(0.1)
        self._click_offset_y_spin.setDecimals(2)
        self._click_offset_y_spin.setValue(0.0)
        self._click_offset_y_spin.setToolTip(
            "基于匹配图像尺寸的比例偏移\n"
            "0=中心, 0.5=下边缘, -0.5=上边缘"
        )
        offset_layout.addWidget(self._click_offset_y_spin)
        self._click_offset_label = QLabel("偏移值:")
        form.addRow(self._click_offset_label, offset_layout)
        self._jump_target_label.setVisible(False)
        self._jump_target_combo.setVisible(False)

        # ── 按模式遍历网格（仅 traverse_grid 时可见）──
        traverse_center_layout = QHBoxLayout()
        self._traverse_center_edit = QLineEdit()
        self._traverse_center_edit.setPlaceholderText("坐标参数名（如: base_coord）")
        traverse_center_layout.addWidget(self._traverse_center_edit)
        self._traverse_center_browse_btn = QPushButton("从参数选择")
        self._traverse_center_browse_btn.clicked.connect(lambda: self._browse_param_name(self._traverse_center_edit, "coordinate"))
        traverse_center_layout.addWidget(self._traverse_center_browse_btn)
        self._traverse_center_label = QLabel("中心坐标参数:")
        form.addRow(self._traverse_center_label, traverse_center_layout)
        self._traverse_center_label.setVisible(False)
        self._traverse_center_edit.setVisible(False)
        self._traverse_center_browse_btn.setVisible(False)

        traverse_array_layout = QHBoxLayout()
        self._traverse_array_edit = QLineEdit()
        self._traverse_array_edit.setPlaceholderText("目标坐标数组参数名")
        traverse_array_layout.addWidget(self._traverse_array_edit)
        self._traverse_array_browse_btn = QPushButton("从参数选择")
        self._traverse_array_browse_btn.clicked.connect(lambda: self._browse_param_name(self._traverse_array_edit, "coord_array"))
        traverse_array_layout.addWidget(self._traverse_array_browse_btn)
        self._traverse_array_label = QLabel("目标数组:")
        form.addRow(self._traverse_array_label, traverse_array_layout)
        self._traverse_array_label.setVisible(False)
        self._traverse_array_edit.setVisible(False)
        self._traverse_array_browse_btn.setVisible(False)

        self._traverse_count_spin = QSpinBox()
        self._traverse_count_spin.setRange(1, 100000)
        self._traverse_count_spin.setValue(1000)
        self._traverse_count_label = QLabel("遍历数量:")
        form.addRow(self._traverse_count_label, self._traverse_count_spin)
        self._traverse_count_label.setVisible(False)
        self._traverse_count_spin.setVisible(False)

        self._traverse_mode_combo = QComboBox()
        _populate_grid_mode_combo(self._traverse_mode_combo)
        self._traverse_mode_label = QLabel("网格模式:")
        form.addRow(self._traverse_mode_label, self._traverse_mode_combo)
        self._traverse_mode_label.setVisible(False)
        self._traverse_mode_combo.setVisible(False)

        two_ring_target_layout = QHBoxLayout()
        self._two_ring_target_coord_edit = QLineEdit()
        self._two_ring_target_coord_edit.setPlaceholderText("目标逻辑坐标参数名")
        two_ring_target_layout.addWidget(self._two_ring_target_coord_edit)
        self._two_ring_target_coord_browse_btn = QPushButton("从参数选择")
        self._two_ring_target_coord_browse_btn.clicked.connect(
            lambda: self._browse_param_name(self._two_ring_target_coord_edit, "coordinate")
        )
        two_ring_target_layout.addWidget(self._two_ring_target_coord_browse_btn)
        self._two_ring_target_coord_label = QLabel("目标坐标:")
        form.addRow(self._two_ring_target_coord_label, two_ring_target_layout)
        self._two_ring_target_coord_label.setVisible(False)
        self._two_ring_target_coord_edit.setVisible(False)
        self._two_ring_target_coord_browse_btn.setVisible(False)

        two_ring_result_layout = QHBoxLayout()
        self._two_ring_result_array_edit = QLineEdit()
        self._two_ring_result_array_edit.setPlaceholderText("周围坐标数组参数名")
        two_ring_result_layout.addWidget(self._two_ring_result_array_edit)
        self._two_ring_result_array_browse_btn = QPushButton("从参数选择")
        self._two_ring_result_array_browse_btn.clicked.connect(
            lambda: self._browse_param_name(self._two_ring_result_array_edit, "coord_array")
        )
        two_ring_result_layout.addWidget(self._two_ring_result_array_browse_btn)
        self._two_ring_result_array_label = QLabel("结果数组:")
        form.addRow(self._two_ring_result_array_label, two_ring_result_layout)
        self._two_ring_result_array_label.setVisible(False)
        self._two_ring_result_array_edit.setVisible(False)
        self._two_ring_result_array_browse_btn.setVisible(False)

        self._surround_radius_spin = QSpinBox()
        self._surround_radius_spin.setRange(0, 100000)
        self._surround_radius_spin.setValue(2)
        self._surround_radius_label = QLabel("半径:")
        form.addRow(self._surround_radius_label, self._surround_radius_spin)
        self._surround_radius_label.setVisible(False)
        self._surround_radius_spin.setVisible(False)

        self._surround_mode_combo = QComboBox()
        _populate_grid_mode_combo(self._surround_mode_combo)
        self._surround_mode_label = QLabel("网格模式:")
        form.addRow(self._surround_mode_label, self._surround_mode_combo)
        self._surround_mode_label.setVisible(False)
        self._surround_mode_combo.setVisible(False)

        # ── 寻找铺路路径（仅 find_road_path 时可见）──
        path_target_layout = QHBoxLayout()
        self._path_target_coord_edit = QLineEdit()
        self._path_target_coord_edit.setPlaceholderText("目标坐标参数名")
        path_target_layout.addWidget(self._path_target_coord_edit)
        self._path_target_coord_browse_btn = QPushButton("从参数选择")
        self._path_target_coord_browse_btn.clicked.connect(
            lambda: self._browse_param_name(self._path_target_coord_edit, "coordinate")
        )
        path_target_layout.addWidget(self._path_target_coord_browse_btn)
        self._path_target_coord_label = QLabel("目标坐标:")
        form.addRow(self._path_target_coord_label, path_target_layout)
        self._path_target_coord_label.setVisible(False)
        self._path_target_coord_edit.setVisible(False)
        self._path_target_coord_browse_btn.setVisible(False)

        path_start_layout = QHBoxLayout()
        self._path_start_array_edit = QLineEdit()
        self._path_start_array_edit.setPlaceholderText("起始坐标数组参数名")
        path_start_layout.addWidget(self._path_start_array_edit)
        self._path_start_array_browse_btn = QPushButton("从参数选择")
        self._path_start_array_browse_btn.clicked.connect(
            lambda: self._browse_param_name(self._path_start_array_edit, "coord_array")
        )
        path_start_layout.addWidget(self._path_start_array_browse_btn)
        self._path_start_array_label = QLabel("起始数组:")
        form.addRow(self._path_start_array_label, path_start_layout)
        self._path_start_array_label.setVisible(False)
        self._path_start_array_edit.setVisible(False)
        self._path_start_array_browse_btn.setVisible(False)

        path_passable_layout = QHBoxLayout()
        self._path_passable_array_edit = QLineEdit()
        self._path_passable_array_edit.setPlaceholderText("可通行坐标数组参数名")
        path_passable_layout.addWidget(self._path_passable_array_edit)
        self._path_passable_array_browse_btn = QPushButton("从参数选择")
        self._path_passable_array_browse_btn.clicked.connect(
            lambda: self._browse_param_name(self._path_passable_array_edit, "coord_array")
        )
        path_passable_layout.addWidget(self._path_passable_array_browse_btn)
        self._path_passable_array_label = QLabel("可通行数组:")
        form.addRow(self._path_passable_array_label, path_passable_layout)
        self._path_passable_array_label.setVisible(False)
        self._path_passable_array_edit.setVisible(False)
        self._path_passable_array_browse_btn.setVisible(False)

        path_result_layout = QHBoxLayout()
        self._path_result_array_edit = QLineEdit()
        self._path_result_array_edit.setPlaceholderText("结果坐标数组参数名")
        path_result_layout.addWidget(self._path_result_array_edit)
        self._path_result_array_browse_btn = QPushButton("从参数选择")
        self._path_result_array_browse_btn.clicked.connect(
            lambda: self._browse_param_name(self._path_result_array_edit, "coord_array")
        )
        path_result_layout.addWidget(self._path_result_array_browse_btn)
        self._path_result_array_label = QLabel("结果数组:")
        form.addRow(self._path_result_array_label, path_result_layout)
        self._path_result_array_label.setVisible(False)
        self._path_result_array_edit.setVisible(False)
        self._path_result_array_browse_btn.setVisible(False)

        self._path_mode_combo = QComboBox()
        _populate_grid_mode_combo(self._path_mode_combo)
        self._path_mode_label = QLabel("网格模式:")
        form.addRow(self._path_mode_label, self._path_mode_combo)
        self._path_mode_label.setVisible(False)
        self._path_mode_combo.setVisible(False)

        self._inline_action_row_start, _ = form.getWidgetPosition(self._action_type)
        self._inline_action_row_end, _ = form.getWidgetPosition(self._path_mode_label)

        # ── 条件栏目 ──
        self._cond_group = QGroupBox("执行条件（需满足条件才执行此步骤）")
        cond_layout = QVBoxLayout(self._cond_group)
        cond_layout.setContentsMargins(12, 12, 12, 10)
        cond_layout.setSpacing(8)
        self._cond_list = QListWidget()
        self._cond_add_btn = QPushButton("添加条件")
        self._cond_add_btn.clicked.connect(self._add_condition)
        self._cond_edit_btn = QPushButton("编辑条件")
        self._cond_edit_btn.clicked.connect(self._edit_condition)
        self._cond_del_btn = QPushButton("删除条件")
        self._cond_del_btn.clicked.connect(self._del_condition)
        cond_layout.addWidget(
            self._create_compact_list_panel(
                self._cond_list,
                [self._cond_add_btn, self._cond_edit_btn, self._cond_del_btn],
                list_height=84,
            )
        )
        form.insertRow(3, self._cond_group)

        # 后台模式
        self._use_background = QCheckBox("后台模式")
        self._use_background.setChecked(True)
        self._use_background.setToolTip("后台截图和点击，不移动真实鼠标")
        form.addRow("", self._use_background)

        # 超时时间
        self._timeout_spin = QDoubleSpinBox()
        self._timeout_spin.setRange(0.0, 3600.0)
        self._timeout_spin.setSingleStep(0.1)
        self._timeout_spin.setDecimals(2)
        self._timeout_spin.setValue(60.0)
        self._timeout_spin.setSuffix(" 秒")
        self._timeout_spin.setSpecialValueText("无限等待")
        self._timeout_spin.setToolTip("支持小于 1 秒；输入 0 表示无限等待")
        form.addRow("超时时间:", self._timeout_spin)

        # 重试间隔
        self._retry_spin = QDoubleSpinBox()
        self._retry_spin.setRange(0.1, 60.0)
        self._retry_spin.setSingleStep(0.5)
        self._retry_spin.setValue(0.1)
        self._retry_spin.setSuffix(" 秒")
        form.addRow("重试间隔:", self._retry_spin)

        # ── 识别失败操作 ──
        self._fail_group = QGroupBox("识别失败时的操作（仅在超时时间内完成全部重试后仍失败时执行）")
        fail_layout = QVBoxLayout(self._fail_group)
        fail_layout.setContentsMargins(12, 12, 12, 10)
        fail_layout.setSpacing(8)

        self._on_fail_enabled = QCheckBox("启用识别失败操作（完成全部重试后触发）")
        self._on_fail_enabled.setChecked(False)
        self._on_fail_enabled.stateChanged.connect(self._on_fail_enabled_changed)
        fail_layout.addWidget(self._on_fail_enabled)

        fail_hint = QLabel("只有识别步骤在超时时间内完成所有重试后仍未成功识别，才会执行这里的失败操作。")
        fail_hint.setWordWrap(True)
        fail_hint.setStyleSheet("color: gray;")
        fail_layout.addWidget(fail_hint)

        fail_actions_layout = QVBoxLayout()
        self._on_fail_actions_list = QListWidget()
        self._on_fail_actions_list.itemDoubleClicked.connect(lambda _item: self._edit_fail_action())
        self._on_fail_action_add_btn = QPushButton("添加操作")
        self._on_fail_action_add_btn.clicked.connect(self._add_fail_action)
        self._on_fail_action_edit_btn = QPushButton("编辑操作")
        self._on_fail_action_edit_btn.clicked.connect(self._edit_fail_action)
        self._on_fail_action_del_btn = QPushButton("删除操作")
        self._on_fail_action_del_btn.clicked.connect(self._del_fail_action)
        self._on_fail_action_up_btn = QPushButton("上移")
        self._on_fail_action_up_btn.clicked.connect(self._move_fail_action_up)
        self._on_fail_action_down_btn = QPushButton("下移")
        self._on_fail_action_down_btn.clicked.connect(self._move_fail_action_down)
        fail_actions_layout.addWidget(
            self._create_compact_list_panel(
                self._on_fail_actions_list,
                [
                    self._on_fail_action_add_btn,
                    self._on_fail_action_edit_btn,
                    self._on_fail_action_del_btn,
                    self._on_fail_action_up_btn,
                    self._on_fail_action_down_btn,
                ],
                list_height=96,
            )
        )
        fail_layout.addLayout(fail_actions_layout)
        form.addRow(self._fail_group)

        # 初始隐藏失败操作的所有控件
        self._on_fail_enabled_changed()

        self._click_offset_mode = QComboBox()
        for mode_value, mode_label in CLICK_OFFSET_MODE_LABELS.items():
            self._click_offset_mode.addItem(mode_label, mode_value)
        self._click_offset_mode.setToolTip(
            "模板比例：按识别模板宽高计算偏移\n"
            "窗口像素：按目标窗口客户区像素计算偏移\n"
            "窗口比例：按目标窗口客户区宽高比例计算偏移"
        )
        self._click_offset_mode.currentIndexChanged.connect(self._update_point_position_mode_ui)
        self._click_offset_mode_label = QLabel("偏移单位:")
        form.addRow(self._click_offset_mode_label, self._click_offset_mode)
        self._click_offset_mode_label.setVisible(False)
        self._click_offset_mode.setVisible(False)

        # 坐标偏移（基于模板尺寸的比例）
        offset_layout = QHBoxLayout()
        offset_layout.addWidget(QLabel("X:"))
        self._offset_x_spin = QDoubleSpinBox()
        self._offset_x_spin.setRange(-5.0, 5.0)
        self._offset_x_spin.setSingleStep(0.1)
        self._offset_x_spin.setDecimals(2)
        self._offset_x_spin.setValue(0.0)
        self._offset_x_spin.setToolTip(
            "基于匹配图像尺寸的比例偏移\n"
            "0=中心, 0.5=右边缘, -0.5=左边缘\n"
            "1.0=超出右边缘半个图像宽度"
        )
        offset_layout.addWidget(self._offset_x_spin)
        offset_layout.addWidget(QLabel("Y:"))
        self._offset_y_spin = QDoubleSpinBox()
        self._offset_y_spin.setRange(-10.0, 10.0)
        self._offset_y_spin.setSingleStep(0.1)
        self._offset_y_spin.setDecimals(2)
        self._offset_y_spin.setValue(0.0)
        self._offset_y_spin.setToolTip(
            "基于匹配图像尺寸的比例偏移\n"
            "0=中心, 0.5=下边缘, -0.5=上边缘\n"
            "1.0=超出下边缘半个图像高度"
        )
        offset_layout.addWidget(self._offset_y_spin)
        self._offset_row = form.rowCount()
        form.addRow("偏移值:", offset_layout)
        form.setRowVisible(self._offset_row, False)

        # 操作后等待
        self._delay_after_spin = QDoubleSpinBox()
        self._delay_after_spin.setRange(0.0, 6000.0)
        self._delay_after_spin.setSingleStep(0.5)
        self._delay_after_spin.setValue(0.5)
        self._delay_after_spin.setSuffix(" 秒")
        form.addRow("操作后等待:", self._delay_after_spin)

        layout.addLayout(form)

        # 初始状态刷新一次显隐
        self._on_action_type_changed()
        self._set_inline_action_editor_visible(False)
        self._update_compact_list_sizes()

        # 确定/取消
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _create_compact_list_panel(self, list_widget: QListWidget, buttons: List[QPushButton],
                                   list_height: int) -> QWidget:
        panel = QWidget()
        content_layout = QHBoxLayout(panel)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        list_widget.setFixedHeight(list_height)
        content_layout.addWidget(list_widget, 0, Qt.AlignTop)

        button_panel = QWidget()
        button_panel.setFixedWidth(188)
        button_grid = QGridLayout(button_panel)
        button_grid.setContentsMargins(0, 0, 0, 0)
        button_grid.setHorizontalSpacing(6)
        button_grid.setVerticalSpacing(6)
        for index, button in enumerate(buttons):
            button.setFixedWidth(88)
            button.setMinimumHeight(28)
            button_grid.addWidget(button, index // 2, index % 2)

        content_layout.addWidget(button_panel, 0, Qt.AlignTop)
        content_layout.addStretch(1)
        return panel

    def _update_compact_list_sizes(self):
        list_width = max(280, min(430, int(self.width() * 0.52)))
        for list_widget in (self._cond_list, self._actions_list, self._on_fail_actions_list):
            list_widget.setFixedWidth(list_width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_compact_list_sizes()

    def _on_action_type_changed(self, index=0):
        """操作类型变更 — 控制输入文本/按键/拖动字段的显隐"""
        action = _normalize_grid_action_type(self._action_type.currentData())
        is_input_text = action == "input_text"
        is_press_key = action == "press_key"
        is_hold_left_button = action == "hold_left_button"
        is_highlight_match = action == "highlight_match"
        is_highlight_point = action == "highlight_point"
        is_drag_match_to_center = action == "drag_match_to_center"
        uses_highlight_duration = _action_uses_highlight_duration(action)
        is_drag_map = action == "drag_map"
        has_drag_duration = _action_uses_drag_duration(action)
        is_mark_blocked = action == "mark_blocked"
        is_modify_var = action == "modify_variable"
        is_add_arr = action == "add_to_array"
        is_remove_coords = action == "remove_target_coords"
        is_clear_arr = action == "clear_array_data"
        is_recognition_to_logic = action == "recognition_to_logic_coord"
        is_jump = action == "jump_to_step"
        is_traverse = action == "traverse_grid"
        is_get_two_ring = action == "get_surrounding_coords"
        is_find_road_path = action == "find_road_path"

        # 输入文本和标记封锁都使用 input_text 字段
        show_input = is_input_text or is_mark_blocked
        self._input_text_label.setVisible(show_input)
        self._input_text_edit.setVisible(show_input)
        self._input_text_browse_btn.setVisible(is_input_text)  # 仅输入文本时显示参数选择按钮
        if is_mark_blocked:
            self._input_text_label.setText("封锁坐标:")
            self._input_text_edit.setPlaceholderText("格式: {x},{y}（支持参数替换）")
        elif is_input_text:
            self._input_text_label.setText("输入内容:")
            self._input_text_edit.setPlaceholderText("输入要填写的文本内容，如: 990 或 {param}")
        self._clear_method_label.setVisible(is_input_text)
        self._clear_method.setVisible(is_input_text)
        # 删除次数的显隐取决于清除方式
        self._on_clear_method_changed()

        # 按键相关
        self._press_keys_label.setVisible(is_press_key)
        self._press_keys_edit.setVisible(is_press_key)

        self._highlight_duration_label.setVisible(uses_highlight_duration)
        self._highlight_duration_spin.setVisible(uses_highlight_duration)
        if is_highlight_match:
            self._highlight_duration_label.setText("红框时长:")
        elif is_highlight_point:
            self._highlight_duration_label.setText("红点时长:")
        self._highlight_show_ai_attributes_label.setVisible(is_highlight_match)
        self._highlight_show_ai_attributes.setVisible(is_highlight_match)
        uses_point_position = _action_uses_point_position_mode(action)
        point_mode = normalize_point_position_mode(self._point_position_mode.currentData() or "recognition")
        self._point_position_mode_label.setVisible(uses_point_position)
        self._point_position_mode.setVisible(uses_point_position)

        # 拖动地图相关
        self._drag_coordinate_mode_label.setVisible(is_drag_map)
        self._drag_coordinate_mode.setVisible(is_drag_map)
        self._drag_start_mode_label.setVisible(is_drag_map)
        self._drag_start_mode.setVisible(is_drag_map)
        self._drag_vector_mode_label.setVisible(is_drag_map)
        self._drag_vector_mode.setVisible(is_drag_map)
        self._drag_vector_label.setVisible(is_drag_map)
        self._drag_vector_widget.setVisible(is_drag_map)
        self._drag_dir_label.setVisible(is_drag_map)
        self._drag_dir_x_spin.setVisible(is_drag_map)
        self._drag_dir_y_spin.setVisible(is_drag_map)
        self._drag_distance_label.setVisible(is_drag_map)
        self._drag_distance_spin.setVisible(is_drag_map)
        self._drag_duration_label.setVisible(has_drag_duration)
        self._drag_duration_spin.setVisible(has_drag_duration)
        if is_hold_left_button:
            self._drag_duration_label.setText("长按时长:")
            self._drag_duration_spin.setToolTip("按住鼠标左键后保持的时间，到时自动释放")
        else:
            self._drag_duration_label.setText("拖动时长:")
            self._drag_duration_spin.setToolTip("拖动动作的持续时间")
        self._drag_center_tolerance_label.setVisible(is_drag_match_to_center)
        self._drag_center_tolerance_spin.setVisible(is_drag_match_to_center)

        # 修改变量
        self._modify_var_name_label.setVisible(is_modify_var)
        self._modify_var_name_edit.setVisible(is_modify_var)
        self._modify_var_browse_btn.setVisible(is_modify_var)
        self._modify_var_value_label.setVisible(is_modify_var)
        self._modify_var_value_edit.setVisible(is_modify_var)
        self._modify_var_value_browse_btn.setVisible(is_modify_var)

        # 添加到数组
        self._arr_items_label.setVisible(is_add_arr)
        self._arr_items_list.setVisible(is_add_arr)
        self._arr_item_add_btn.setVisible(is_add_arr)
        self._arr_item_del_btn.setVisible(is_add_arr)

        self._remove_coord_source_array_label.setVisible(is_remove_coords)
        self._remove_coord_source_array_edit.setVisible(is_remove_coords)
        self._remove_coord_source_array_browse_btn.setVisible(is_remove_coords)
        self._remove_coord_mode_label.setVisible(is_remove_coords)
        self._remove_coord_mode_combo.setVisible(is_remove_coords)
        self._remove_coord_target_value_label.setVisible(is_remove_coords)
        self._remove_coord_target_value_edit.setVisible(is_remove_coords)
        self._remove_coord_target_value_browse_btn.setVisible(is_remove_coords)

        self._clear_array_label.setVisible(is_clear_arr)
        self._clear_array_edit.setVisible(is_clear_arr)
        self._clear_array_browse_btn.setVisible(is_clear_arr)

        self._recognition_to_logic_csv_label.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_csv_edit.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_csv_browse_btn.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_anchor_logical_label.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_anchor_logical_edit.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_anchor_logical_browse_btn.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_anchor_screen_label.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_anchor_screen_edit.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_anchor_screen_browse_btn.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_result_array_label.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_result_array_edit.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_result_array_browse_btn.setVisible(is_recognition_to_logic)

        # 跳转步骤
        self._jump_target_label.setVisible(is_jump)
        self._jump_target_combo.setVisible(is_jump)

        # 遍历网格
        self._traverse_center_label.setVisible(is_traverse)
        self._traverse_center_edit.setVisible(is_traverse)
        self._traverse_center_browse_btn.setVisible(is_traverse)
        self._traverse_array_label.setVisible(is_traverse)
        self._traverse_array_edit.setVisible(is_traverse)
        self._traverse_array_browse_btn.setVisible(is_traverse)
        self._traverse_count_label.setVisible(is_traverse)
        self._traverse_count_spin.setVisible(is_traverse)
        self._traverse_mode_label.setVisible(is_traverse)
        self._traverse_mode_combo.setVisible(is_traverse)

        self._two_ring_target_coord_label.setVisible(is_get_two_ring)
        self._two_ring_target_coord_edit.setVisible(is_get_two_ring)
        self._two_ring_target_coord_browse_btn.setVisible(is_get_two_ring)
        self._two_ring_result_array_label.setVisible(is_get_two_ring)
        self._two_ring_result_array_edit.setVisible(is_get_two_ring)
        self._two_ring_result_array_browse_btn.setVisible(is_get_two_ring)
        self._surround_radius_label.setVisible(is_get_two_ring)
        self._surround_radius_spin.setVisible(is_get_two_ring)
        self._surround_mode_label.setVisible(is_get_two_ring)
        self._surround_mode_combo.setVisible(is_get_two_ring)

        self._path_target_coord_label.setVisible(is_find_road_path)
        self._path_target_coord_edit.setVisible(is_find_road_path)
        self._path_target_coord_browse_btn.setVisible(is_find_road_path)
        self._path_start_array_label.setVisible(is_find_road_path)
        self._path_start_array_edit.setVisible(is_find_road_path)
        self._path_start_array_browse_btn.setVisible(is_find_road_path)
        self._path_passable_array_label.setVisible(is_find_road_path)
        self._path_passable_array_edit.setVisible(is_find_road_path)
        self._path_passable_array_browse_btn.setVisible(is_find_road_path)
        self._path_result_array_label.setVisible(is_find_road_path)
        self._path_result_array_edit.setVisible(is_find_road_path)
        self._path_result_array_browse_btn.setVisible(is_find_road_path)
        self._path_mode_label.setVisible(is_find_road_path)
        self._path_mode_combo.setVisible(is_find_road_path)

        # 点击偏移只在有点击动作时有意义
        uses_offset = _action_uses_click_offset(action)
        self._click_offset_mode_label.setVisible(uses_offset)
        self._click_offset_mode.setVisible(uses_offset)
        self._offset_x_spin.setEnabled(uses_offset)
        self._offset_y_spin.setEnabled(uses_offset)
        self._update_point_position_mode_ui()
        self._update_drag_start_mode_ui()
        self._update_drag_coordinate_mode_ui()
        self._on_jump_target_changed()

    def _populate_jump_targets(self):
        """填充跳转目标步骤下拉框"""
        self._jump_target_combo.set_task_steps(self._task_steps)

    def _on_clear_method_changed(self, index=0):
        """清除方式变更 — 控制删除次数的显隐"""
        is_input_text = self._action_type.currentData() == "input_text"
        is_del_bs = self._clear_method.currentData() == "delete_backspace"
        show = is_input_text and is_del_bs
        self._clear_key_count_label.setVisible(show)
        self._clear_key_count_spin.setVisible(show)

    def _update_drag_start_mode_ui(self, index=0):
        del index
        if not all(
            hasattr(self, attr)
            for attr in (
                "_action_type",
                "_drag_start_mode",
                "_drag_start_coord_label",
                "_drag_start_coord_widget",
                "_drag_start_x_spin",
                "_drag_start_y_spin",
            )
        ):
            return
        is_drag_map = self._action_type.currentData() == "drag_map"
        show_screen_ratio = is_drag_map and (self._drag_start_mode.currentData() == "screen_percent")
        self._drag_start_coord_label.setVisible(show_screen_ratio)
        self._drag_start_coord_widget.setVisible(show_screen_ratio)
        self._drag_start_x_spin.setToolTip("相对目标窗口客户区宽度的比例，例如 X=0.5 表示水平中心")
        self._drag_start_y_spin.setToolTip("相对目标窗口客户区高度的比例，例如 Y=0.5 表示垂直中心")

    def _update_point_position_mode_ui(self, index=0):
        del index
        if not all(
            hasattr(self, attr)
            for attr in (
                "_action_type",
                "_point_position_mode",
                "_point_coord_label",
                "_point_coord_widget",
                "_point_x_spin",
                "_point_y_spin",
            )
        ):
            return

        action_type = self._action_type.currentData()
        uses_point_position = _action_uses_point_position_mode(action_type)
        mode = normalize_point_position_mode(self._point_position_mode.currentData() or "recognition")
        _sync_click_offset_mode_combo_with_point_mode(self, mode if uses_point_position else "recognition")
        show_coords = uses_point_position and mode != "recognition"
        self._point_coord_label.setVisible(show_coords)
        self._point_coord_widget.setVisible(show_coords)
        if hasattr(self, "_offset_x_spin") and hasattr(self, "_offset_y_spin"):
            uses_offset = _action_uses_click_offset(action_type)
            self._offset_x_spin.setEnabled(uses_offset)
            self._offset_y_spin.setEnabled(uses_offset)
            _configure_click_offset_spins(
                self._offset_x_spin,
                self._offset_y_spin,
                self._click_offset_mode.currentData() or get_default_click_offset_mode(mode if uses_point_position else "recognition"),
            )
        if not show_coords:
            return

        _configure_point_coordinate_spins(self._point_x_spin, self._point_y_spin, mode)
        if mode == "screen_percent":
            self._point_coord_label.setText("窗口比例:")
        else:
            self._point_coord_label.setText("窗口坐标:")

    def _update_drag_vector_mode_ui(self, index=0):
        del index
        if not all(
            hasattr(self, attr)
            for attr in (
                "_drag_vector_mode",
                "_drag_vector_x_spin",
                "_drag_vector_y_spin",
                "_drag_vector_label",
            )
        ):
            return
        vector_mode = normalize_drag_vector_mode(self._drag_vector_mode.currentData() or "pixel")
        if vector_mode == "screen_percent":
            self._drag_vector_label.setText("拖动向量:")
            self._drag_vector_x_spin.setSingleStep(0.05)
            self._drag_vector_y_spin.setSingleStep(0.05)
            self._drag_vector_x_spin.setToolTip("相对整个屏幕宽度的拖动比例，例如 0.2 表示向右拖动 20% 屏幕宽度")
            self._drag_vector_y_spin.setToolTip("相对整个屏幕高度的拖动比例，例如 -0.1 表示向上拖动 10% 屏幕高度")
            self._drag_vector_mode.setToolTip("屏幕百分比向量：X/Y 同时表示方向和距离，按屏幕宽高比例计算")
        else:
            self._drag_vector_label.setText("拖动向量:")
            self._drag_vector_x_spin.setSingleStep(10.0)
            self._drag_vector_y_spin.setSingleStep(10.0)
            self._drag_vector_x_spin.setToolTip("屏幕像素向量 X，正数向右，负数向左")
            self._drag_vector_y_spin.setToolTip("屏幕像素向量 Y，正数向下，负数向上")
            self._drag_vector_mode.setToolTip("像素向量：X/Y 同时表示方向和距离，单位为屏幕像素")

    def _update_drag_coordinate_mode_ui(self, index=0):
        del index
        if not all(
            hasattr(self, attr)
            for attr in (
                "_action_type",
                "_drag_coordinate_mode",
                "_drag_vector_mode_label",
                "_drag_vector_mode",
                "_drag_vector_label",
                "_drag_vector_widget",
                "_drag_dir_label",
                "_drag_dir_x_spin",
                "_drag_dir_y_spin",
                "_drag_distance_spin",
            )
        ):
            return
        is_drag_map = self._action_type.currentData() == "drag_map"
        mode = self._drag_coordinate_mode.currentData() or "game_logic"
        show_screen_vector = is_drag_map and mode == "screen"
        show_game_logic = is_drag_map and mode != "screen"
        self._drag_vector_mode_label.setVisible(show_screen_vector)
        self._drag_vector_mode.setVisible(show_screen_vector)
        self._drag_vector_label.setVisible(show_screen_vector)
        self._drag_vector_widget.setVisible(show_screen_vector)
        self._drag_dir_label.setVisible(show_game_logic)
        self._drag_dir_x_spin.setVisible(show_game_logic)
        self._drag_dir_y_spin.setVisible(show_game_logic)
        self._drag_distance_label.setVisible(show_game_logic)
        self._drag_distance_spin.setVisible(show_game_logic)
        if mode == "screen":
            self._update_drag_vector_mode_ui()
        else:
            self._drag_dir_label.setText("拖动方向:")
            self._drag_dir_x_spin.setToolTip(
                "游戏地图X方向格数\n"
                "正数=镜头向X+方向移动（屏幕左下）\n"
                "负数=镜头向X-方向移动（屏幕右上）"
            )
            self._drag_dir_y_spin.setToolTip(
                "游戏地图Y方向格数\n"
                "正数=镜头向Y+方向移动（屏幕右下）\n"
                "负数=镜头向Y-方向移动（屏幕左上）"
            )
            self._drag_distance_spin.setToolTip("拖动的屏幕总像素距离（方向由等距坐标自动换算）")

    def _on_type_changed(self, index):
        """识别类型变更"""
        recognition_type = self._recognition_type.currentData()
        is_image = recognition_type == "image"
        is_multi_image = recognition_type == "multi_image"
        is_ai_tile = _is_ai_tile_recognition_type(recognition_type)
        is_none = recognition_type == "none"
        is_ocr = recognition_type == "text"  # 文字识别的type是"text"
        is_any_image = _is_image_like_recognition_type(recognition_type)
        is_template_image = is_image or is_multi_image
        self._browse_btn.setVisible(is_any_image)
        self._browse_param_btn.setVisible(not is_none)
        self._ai_tile_usage_hint.setVisible(is_ai_tile)
        self._exact_match.setVisible(not is_any_image and not is_none)
        self._target_mode_text.setVisible(not is_none and not is_ai_tile)
        self._target_mode_combo.setVisible(not is_none and not is_ai_tile)
        # 匹配序号和多匹配对单图像/多图像识别都生效
        self._match_index_label.setVisible(is_any_image)
        self._match_index_spin.setVisible(is_any_image)
        self._has_multiple_matches_label.setVisible(is_any_image)
        self._has_multiple_matches.setVisible(is_any_image)
        self._image_match_mode_label.setVisible(is_template_image)
        self._image_match_mode_combo.setVisible(is_template_image)
        self._recognition_roi_label.setVisible(not is_none)
        self._recognition_roi_mode_combo.setVisible(not is_none)
        # 无识别时隐藏目标、阈值
        self._target_edit.setVisible(not is_none)
        self._threshold_spin.setVisible(not is_none)
        self._validate_color_check.setVisible(is_template_image)
        # 找到 target 和 threshold 的 label 并控制显隐
        if is_none:
            self._target_edit.setPlaceholderText("")
        elif is_image:
            self._target_edit.setPlaceholderText("选择模板图片文件路径，或从参数中选择单图/图像数组")
            self._threshold_spin.setValue(0.8)
            self._threshold_spin.setToolTip("图像识别的最低置信度，建议0.75-0.9。值越低越容易误匹配")
            self._browse_btn.setText("浏览...")
        elif is_ai_tile:
            _set_combo_data(self._target_mode_combo, "single")
            self._target_edit.setPlaceholderText("可选：指定 onnx 模型路径；留空则使用 models/tile_detector 下最新 onnx 模型")
            self._threshold_spin.setValue(0.35)
            self._threshold_spin.setToolTip("AI 地块识别的最低置信度，建议 0.25-0.5；值越低召回越高，但误检也会增加")
            self._target_edit.setToolTip("使用项目内 detector onnx 时，若同项目 outputs/train_attr 下存在属性 best.pt，主程序会自动补全等级/类型/关系")
            self._browse_btn.setText("选择模型...")
        elif is_multi_image:
            self._target_edit.setPlaceholderText("多张图片路径，用 | 分隔；适合动画帧模板，任意一张命中即成功")
            self._threshold_spin.setValue(0.8)
            self._threshold_spin.setToolTip("多图像识别阈值，任一图片匹配即成功")
            self._browse_btn.setText("浏览多图...")
        else:
            self._target_edit.setPlaceholderText("输入要识别的文字，或从参数中选择文本/数组参数")
            self._threshold_spin.setValue(0.5)
            self._threshold_spin.setToolTip("文字识别的最低置信度，建议0.5-0.7。值越低越容易匹配但可能误识别")
            self._browse_btn.setText("浏览...")

        self._on_recognition_roi_mode_changed()

    def _on_recognition_roi_mode_changed(self, index=0):
        del index
        recognition_type = self._recognition_type.currentData()
        show_rect = (
            recognition_type != "none"
            and normalize_recognition_roi_mode(self._recognition_roi_mode_combo.currentData()) == "window_percent"
        )
        self._recognition_roi_rect_widget.setVisible(show_rect)

    def _browse_target_param(self):
        """从参数选择识别目标"""
        recognition_type = self._recognition_type.currentData()
        candidate_names = {param.name for param in _get_recognition_target_candidates(self._task_params, recognition_type)}
        type_name = {
            "image": "图像",
            "multi_image": "多图像",
            "ai_tile": "AI 地块",
            "text": "文字",
        }.get(recognition_type, "当前")
        param = _pick_task_param(
            self,
            self._task_params,
            "选择参数",
            "请选择一个参数作为识别目标:",
            predicate=lambda item: item.name in candidate_names,
            task=self._task,
            empty_message=f"当前没有可用于{type_name}识别的参数",
        )
        if not param:
            return

        reference = _choose_member_path(self, param, include_whole=True, wrap_reference=True, allow_coordinate_full=False)
        if not reference:
            return

        if is_array_param_type(param.param_type):
            current_mode = self._target_mode_combo.currentData()
            default_mode = current_mode if current_mode in ("array_any", "array_all") else "array_any"
            mode_labels = [
                RECOGNITION_TARGET_MODE_LABELS["array_any"],
                RECOGNITION_TARGET_MODE_LABELS["array_all"],
            ]
            default_index = 0 if default_mode == "array_any" else 1
            selected_mode, mode_ok = QInputDialog.getItem(
                self,
                "选择数组识别方式",
                "数组参数匹配成功条件:",
                mode_labels,
                default_index,
                False,
            )
            if not mode_ok or not selected_mode:
                return
            chosen_mode = next(
                (mode for mode, label in RECOGNITION_TARGET_MODE_LABELS.items() if label == selected_mode),
                "array_any",
            )
            _set_combo_data(self._target_mode_combo, chosen_mode)
        else:
            _set_combo_data(self._target_mode_combo, "single")

        self._target_edit.setText(reference)
    
    def _browse_template(self):
        """浏览模板图片，自动复制到 pic/ 目录并存储相对路径"""
        recognition_type = self._recognition_type.currentData()
        is_multi = recognition_type == "multi_image"

        if recognition_type == "ai_tile":
            filepath, _ = QFileDialog.getOpenFileName(
                self,
                "选择 AI 地块模型",
                "",
                "ONNX 模型 (*.onnx);;所有文件 (*.*)"
            )
            if not filepath:
                return

            app_dir = self._get_app_dir()
            abs_filepath = os.path.abspath(filepath)
            try:
                rel_path = os.path.relpath(abs_filepath, app_dir)
            except ValueError:
                rel_path = abs_filepath

            if rel_path.startswith(".."):
                self._target_edit.setText(abs_filepath)
            else:
                self._target_edit.setText(rel_path.replace("\\", "/"))
            return

        if is_multi:
            # 多图像模式：允许多选
            filepaths, _ = QFileDialog.getOpenFileNames(
                self, "选择模板图片（可多选）", "",
                "图像文件 (*.png *.jpg *.jpeg *.bmp);;所有文件 (*.*)"
            )
        else:
            filepath, _ = QFileDialog.getOpenFileName(
                self, "选择模板图片", "",
                "图像文件 (*.png *.jpg *.jpeg *.bmp);;所有文件 (*.*)"
            )
            filepaths = [filepath] if filepath else []

        if not filepaths:
            return

        app_dir = self._get_app_dir()
        pic_dir = os.path.join(app_dir, "pic")
        os.makedirs(pic_dir, exist_ok=True)

        rel_paths = []
        for filepath in filepaths:
            abs_filepath = os.path.abspath(filepath)
            abs_pic_dir = os.path.abspath(pic_dir)

            if abs_filepath.startswith(abs_pic_dir + os.sep):
                rel_path = os.path.relpath(abs_filepath, app_dir)
            else:
                filename = os.path.basename(filepath)
                dest_path = os.path.join(pic_dir, filename)

                if os.path.exists(dest_path) and not self._files_identical(abs_filepath, dest_path):
                    name, ext = os.path.splitext(filename)
                    counter = 1
                    while os.path.exists(dest_path):
                        dest_path = os.path.join(pic_dir, f"{name}_{counter}{ext}")
                        counter += 1

                if not os.path.exists(dest_path):
                    shutil.copy2(filepath, dest_path)

                rel_path = os.path.relpath(dest_path, app_dir)

            rel_paths.append(rel_path.replace("\\", "/"))

        if is_multi:
            # 多图像：追加到现有内容（用 | 分隔）
            existing = self._target_edit.text().strip()
            if existing:
                existing_paths = [p.strip() for p in existing.split("|") if p.strip()]
                for rp in rel_paths:
                    if rp not in existing_paths:
                        existing_paths.append(rp)
                self._target_edit.setText("|".join(existing_paths))
            else:
                self._target_edit.setText("|".join(rel_paths))
        else:
            self._target_edit.setText(rel_paths[0])

    @staticmethod
    def _files_identical(path1: str, path2: str) -> bool:
        """检查两个文件是否完全相同"""
        try:
            if os.path.getsize(path1) != os.path.getsize(path2):
                return False
            with open(path1, 'rb') as f1, open(path2, 'rb') as f2:
                return f1.read() == f2.read()
        except Exception:
            return False

    @staticmethod
    def _get_app_dir() -> str:
        """获取应用程序根目录（兼容打包后的 EXE 和开发环境）"""
        if getattr(sys, 'frozen', False):
            # PyInstaller 打包后
            return os.path.dirname(sys.executable)
        else:
            # 开发环境: game_assistant/ 目录
            return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # ── 参数浏览辅助方法 ──
    def _browse_variable_name(self):
        """从参数列表中选择变量名"""
        param = _pick_task_param(
            self,
            self._task_params,
            "选择变量",
            "请选择一个变量或结构体字段:",
            task=self._task,
            empty_message="当前任务还没有定义参数",
        )
        if not param:
            return
        target = _choose_member_path(self, param, include_whole=True, wrap_reference=False, allow_coordinate_full=False)
        if target:
            self._modify_var_name_edit.setText(target)

    def _browse_modify_value(self):
        """为修改变量选择参数或结构体字段作为新值"""
        param = _pick_task_param(
            self,
            self._task_params,
            "选择参数",
            "请选择一个参数或字段作为新值:",
            task=self._task,
            empty_message="当前任务还没有定义参数",
        )
        if not param:
            return
        reference = _choose_member_path(self, param, include_whole=True, wrap_reference=True, allow_coordinate_full=False)
        if reference:
            self._modify_var_value_edit.setText(reference)

    def _browse_clear_array_name(self):
        param = _pick_array_task_param(
            self,
            self._task_params,
            task=self._task,
            empty_message="当前任务没有可用数组参数",
        )
        if param:
            self._clear_array_edit.setText(param.name)

    def _browse_recognition_to_logic_csv(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "选择坐标转换 CSV",
            "",
            "CSV 文件 (*.csv);;All Files (*)",
        )
        if not filepath:
            return

        app_dir = os.path.abspath(self._get_app_dir())
        abs_filepath = os.path.abspath(filepath)
        if abs_filepath.startswith(app_dir + os.sep):
            target = os.path.relpath(abs_filepath, app_dir).replace("\\", "/")
        else:
            target = abs_filepath
        self._recognition_to_logic_csv_edit.setText(target)

    def _browse_value_reference(self, target_widget: QLineEdit, allow_coordinate_full: bool = False):
        param = _pick_task_param(
            self,
            self._task_params,
            "选择参数",
            "请选择一个参数或字段:",
            task=self._task,
            empty_message="当前任务还没有定义参数",
        )
        if not param:
            return
        reference = _build_param_reference(self, param, allow_coordinate_full=allow_coordinate_full)
        if reference:
            target_widget.setText(reference)

    def _browse_param_name(self, target_widget: QLineEdit, filter_type=None):
        """从参数列表中选择参数名并填入目标控件
        filter_type: 可选，过滤参数类型（如 "coordinate", "coord_array", "array"）
        """
        empty_message = "当前任务没有符合条件的参数" if filter_type else "当前任务还没有定义参数"
        param = _pick_task_param(
            self,
            self._task_params,
            "选择参数",
            "请选择一个参数:",
            filter_type=filter_type,
            task=self._task,
            empty_message=empty_message,
        )
        if param:
            target_widget.setText(param.name)

    def _browse_input_text_param(self):
        """为输入文本选择参数（支持坐标和结构体字段选择）"""
        param = _pick_task_param(
            self,
            self._task_params,
            "选择参数",
            "请选择一个参数:",
            task=self._task,
            empty_message="当前任务还没有定义参数",
        )
        if not param:
            return

        reference = _build_param_reference(self, param, allow_coordinate_full=False)
        if reference:
            self._input_text_edit.insert(reference)

    def _on_remove_coord_mode_changed(self, index=0):
        del index
        _configure_remove_coord_target_editor(
            self._remove_coord_target_value_label,
            self._remove_coord_target_value_edit,
            self._remove_coord_mode_combo.currentData() or "single",
        )

    def _browse_remove_coord_target_value(self):
        reference = _pick_remove_coord_target_reference(
            self,
            self._task_params,
            self._task,
            self._remove_coord_mode_combo.currentData() or "single",
        )
        if reference:
            self._remove_coord_target_value_edit.setText(reference)


    # ── 条件操作 ──
    def _add_condition(self):
        dlg = ConditionEditDialog(task_params=self._task_params, task=self._task, parent=self)
        if dlg.exec() == QDialog.Accepted:
            cond = dlg.get_condition()
            self._step.conditions.append(cond)
            self._refresh_cond_list()

    def _edit_condition(self):
        row = self._cond_list.currentRow()
        if row < 0 or row >= len(self._step.conditions):
            return
        cond_data = self._step.conditions[row]
        cond = StepCondition.from_dict(cond_data) if isinstance(cond_data, dict) else cond_data
        dlg = ConditionEditDialog(cond, task_params=self._task_params, task=self._task, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._step.conditions[row] = dlg.get_condition()
            self._refresh_cond_list()

    def _del_condition(self):
        row = self._cond_list.currentRow()
        if row >= 0 and row < len(self._step.conditions):
            self._step.conditions.pop(row)
            self._refresh_cond_list()

    def _refresh_cond_list(self):
        self._cond_list.clear()
        type_names = {
            "variable": "变量", "image": "图像", "text": "文字",
            "array_contains": "数组包含", "coord_in_array": "坐标在数组中",
        }
        def _format_operand(text: str, use_length: bool) -> str:
            value = text or ""
            return f"len({value})" if use_length else value

        for cond_data in self._step.conditions:
            cond = StepCondition.from_dict(cond_data) if isinstance(cond_data, dict) else cond_data
            ct = cond.condition_type
            neg = cond.negate
            logic = cond.logic_next
            if ct == "variable":
                desc = (
                    f"{_format_operand(cond.left_operand, getattr(cond, 'left_use_length', False))} "
                    f"{cond.operator} "
                    f"{_format_operand(cond.right_operand, getattr(cond, 'right_use_length', False))}"
                )
            elif ct in ("image", "text"):
                desc = f"识别: {cond.rec_target}"
            elif ct == "array_contains":
                desc = f"{cond.array_name} 包含 {cond.search_value}"
            elif ct == "coord_in_array":
                desc = f"坐标在 {cond.array_name}"
            else:
                desc = str(cond_data)
            prefix = "NOT " if neg else ""
            suffix = f" [{logic.upper()}]" if logic else ""
            self._cond_list.addItem(f"[{type_names.get(ct, ct)}] {prefix}{desc}{suffix}")

    def _build_preview_step_context(self) -> SingleTask:
        preview_step = copy.deepcopy(self._step)
        preview_step.name = self._name_edit.text().strip() or preview_step.name
        preview_step.recognition_type = self._recognition_type.currentData()
        preview_step.recognition_target = self._target_edit.text().strip()
        preview_step.recognition_target_mode = normalize_recognition_target_mode(
            self._target_mode_combo.currentData()
        )
        preview_step.image_match_mode = normalize_image_match_mode(self._image_match_mode_combo.currentData())
        preview_step.recognition_roi_mode = normalize_recognition_roi_mode(self._recognition_roi_mode_combo.currentData())
        preview_step.recognition_roi_x = _coerce_point_ratio(self._recognition_roi_x_spin.value(), 0.0)
        preview_step.recognition_roi_y = _coerce_point_ratio(self._recognition_roi_y_spin.value(), 0.0)
        preview_step.recognition_roi_width = max(0.01, _coerce_point_ratio(self._recognition_roi_width_spin.value(), 1.0))
        preview_step.recognition_roi_height = max(0.01, _coerce_point_ratio(self._recognition_roi_height_spin.value(), 1.0))
        preview_step.recognition_threshold = self._threshold_spin.value()
        preview_step.validate_color_consistency = self._validate_color_check.isChecked()
        preview_step.exact_match = self._exact_match.isChecked()
        preview_step.match_index = self._match_index_spin.value()
        preview_step.has_multiple_matches = self._has_multiple_matches.isChecked()
        preview_step.use_background = self._use_background.isChecked()
        preview_step.timeout = self._timeout_spin.value()
        preview_step.retry_interval = self._retry_spin.value()
        return preview_step

    # ── 主操作列表 ──
    def _get_action_from_editor(self) -> dict:
        action_type = _normalize_grid_action_type(self._action_type.currentData() or "none")
        action = {
            "type": action_type,
            "delay": self._action_delay_spin.value(),
        }
        if _action_uses_click_offset(action_type):
            action["click_offset_mode"] = normalize_click_offset_mode(
                self._click_offset_mode.currentData() or "",
                self._point_position_mode.currentData() or "recognition",
            )
            action["click_offset_x"] = self._offset_x_spin.value()
            action["click_offset_y"] = self._offset_y_spin.value()
        if action_type in ("input_text", "mark_blocked"):
            action["input_text"] = self._input_text_edit.text().strip()
        if action_type == "input_text":
            action["clear_method"] = self._clear_method.currentData()
            action["clear_key_count"] = self._clear_key_count_spin.value()
        if action_type == "press_key":
            action["press_keys"] = self._press_keys_edit.text().strip()
        if _action_uses_highlight_duration(action_type):
            action["duration_ms"] = int(round(self._highlight_duration_spin.value() * 1000))
        if action_type == "highlight_match":
            action["show_ai_attributes"] = self._highlight_show_ai_attributes.isChecked()
        if _action_uses_point_position_mode(action_type):
            action["point_position_mode"] = normalize_point_position_mode(
                self._point_position_mode.currentData() or "recognition"
            )
            action["point_x"] = self._point_x_spin.value()
            action["point_y"] = self._point_y_spin.value()
        if _action_uses_drag_duration(action_type):
            action["drag_duration"] = self._drag_duration_spin.value()
        if _action_uses_center_tolerance(action_type):
            action["center_tolerance_px"] = self._drag_center_tolerance_spin.value()
        if action_type == "drag_map":
            action["drag_coordinate_mode"] = self._drag_coordinate_mode.currentData() or "game_logic"
            action["drag_start_mode"] = self._drag_start_mode.currentData() or "recognition"
            action["drag_start_x"] = self._drag_start_x_spin.value()
            action["drag_start_y"] = self._drag_start_y_spin.value()
            action["drag_vector_mode"] = normalize_drag_vector_mode(self._drag_vector_mode.currentData() or "pixel")
            action["drag_vector_x"] = self._drag_vector_x_spin.value()
            action["drag_vector_y"] = self._drag_vector_y_spin.value()
            action["drag_direction_x"] = self._drag_dir_x_spin.value()
            action["drag_direction_y"] = self._drag_dir_y_spin.value()
            action["drag_distance"] = self._drag_distance_spin.value()
        if action_type == "modify_variable":
            action["var_name"] = self._modify_var_name_edit.text().strip()
            action["var_value"] = self._modify_var_value_edit.text().strip()
        if action_type == "add_to_array":
            action["items"] = copy.deepcopy(self._editing_add_to_array_items)
        if action_type == "remove_target_coords":
            action["source_array"] = self._remove_coord_source_array_edit.text().strip()
            action["target_value"] = self._remove_coord_target_value_edit.text().strip()
            action["remove_mode"] = normalize_remove_coord_mode(self._remove_coord_mode_combo.currentData() or "single")
        if action_type == "clear_array_data":
            action["array_name"] = self._clear_array_edit.text().strip()
        if action_type == "recognition_to_logic_coord":
            action["coordinate_csv_path"] = self._recognition_to_logic_csv_edit.text().strip()
            action["anchor_logical_coord"] = self._recognition_to_logic_anchor_logical_edit.text().strip()
            action["anchor_screen_coord"] = self._recognition_to_logic_anchor_screen_edit.text().strip()
            action["result_array"] = self._recognition_to_logic_result_array_edit.text().strip()
        if action_type == "jump_to_step":
            action["target_id"] = self._jump_target_combo.currentData() or ""
        if action_type == "traverse_grid":
            action["center_param"] = self._traverse_center_edit.text().strip()
            action["target_array"] = self._traverse_array_edit.text().strip()
            action["count"] = self._traverse_count_spin.value()
            action["mode"] = normalize_grid_mode(self._traverse_mode_combo.currentData() or "hex")
        if action_type == "get_surrounding_coords":
            action["target_coord"] = self._two_ring_target_coord_edit.text().strip()
            action["result_array"] = self._two_ring_result_array_edit.text().strip()
            action["radius"] = self._surround_radius_spin.value()
            action["mode"] = normalize_grid_mode(self._surround_mode_combo.currentData() or "hex")
        if action_type == "find_road_path":
            action["target_coord"] = self._path_target_coord_edit.text().strip()
            action["start_array"] = self._path_start_array_edit.text().strip()
            action["passable_array"] = self._path_passable_array_edit.text().strip()
            action["result_array"] = self._path_result_array_edit.text().strip()
            action["mode"] = normalize_grid_mode(self._path_mode_combo.currentData() or "hex")
        return action

    def _load_action_to_editor(self, action: Optional[dict]):
        action = action or {"type": "none", "delay": 0.0}
        action_type = _normalize_grid_action_type(action.get("type", "none"))
        idx = self._action_type.findData(action_type)
        if idx >= 0:
            self._action_type.setCurrentIndex(idx)
        self._action_delay_spin.setValue(float(action.get("delay", 0) or 0))
        self._input_text_edit.setText(action.get("input_text", ""))
        self._press_keys_edit.setText(action.get("press_keys", ""))
        self._highlight_duration_spin.setValue(_highlight_duration_seconds_from_ms(action.get("duration_ms", 1200)))
        self._highlight_show_ai_attributes.setChecked(_coerce_action_bool(action, "show_ai_attributes", False))
        _set_combo_data(self._point_position_mode, action.get("point_position_mode", "recognition"), default="recognition")
        _set_combo_data(
            self._click_offset_mode,
            action.get("click_offset_mode", get_default_click_offset_mode(action.get("point_position_mode", "recognition"))),
            default=get_default_click_offset_mode(action.get("point_position_mode", "recognition")),
        )
        self._offset_x_spin.setValue(float(action.get("click_offset_x", 0) or 0))
        self._offset_y_spin.setValue(float(action.get("click_offset_y", 0) or 0))
        self._update_point_position_mode_ui()
        point_mode, point_x, point_y = _get_highlight_point_values(action)
        if point_mode == "screen_percent":
            self._point_x_spin.setValue(_coerce_point_ratio(point_x, 0.5))
            self._point_y_spin.setValue(_coerce_point_ratio(point_y, 0.5))
        else:
            self._point_x_spin.setValue(coerce_float(point_x, 0.0))
            self._point_y_spin.setValue(coerce_float(point_y, 0.0))
        clear_idx = self._clear_method.findData(action.get("clear_method", "delete_backspace"))
        if clear_idx >= 0:
            self._clear_method.setCurrentIndex(clear_idx)
        self._clear_key_count_spin.setValue(int(action.get("clear_key_count", 3) or 3))
        _set_combo_data(self._drag_coordinate_mode, action.get("drag_coordinate_mode", "game_logic"), default="game_logic")
        _set_combo_data(self._drag_start_mode, action.get("drag_start_mode", "recognition"), default="recognition")
        self._drag_start_x_spin.setValue(_coerce_drag_start_ratio(action.get("drag_start_x", 0.5), 0.5))
        self._drag_start_y_spin.setValue(_coerce_drag_start_ratio(action.get("drag_start_y", 0.5), 0.5))
        drag_vector_mode, drag_vector_x, drag_vector_y = _get_screen_drag_vector_values(action)
        _set_combo_data(self._drag_vector_mode, drag_vector_mode, default="pixel")
        self._drag_vector_x_spin.setValue(drag_vector_x)
        self._drag_vector_y_spin.setValue(drag_vector_y)
        self._drag_dir_x_spin.setValue(int(action.get("drag_direction_x", 0) or 0))
        self._drag_dir_y_spin.setValue(int(action.get("drag_direction_y", 0) or 0))
        self._drag_distance_spin.setValue(int(action.get("drag_distance", 200) or 200))
        self._drag_duration_spin.setValue(float(action.get("drag_duration", 0.3) or 0.3))
        self._drag_center_tolerance_spin.setValue(normalize_center_tolerance_px(action.get("center_tolerance_px", 1)))
        self._modify_var_name_edit.setText(action.get("var_name", ""))
        self._modify_var_value_edit.setText(action.get("var_value", ""))
        self._remove_coord_source_array_edit.setText(action.get("source_array", ""))
        self._remove_coord_target_value_edit.setText(action.get("target_value", ""))
        _set_combo_data(self._remove_coord_mode_combo, normalize_remove_coord_mode(action.get("remove_mode", "single")), default="single")
        self._on_remove_coord_mode_changed()
        self._clear_array_edit.setText(action.get("array_name", ""))
        self._recognition_to_logic_csv_edit.setText(action.get("coordinate_csv_path", ""))
        self._recognition_to_logic_anchor_logical_edit.setText(action.get("anchor_logical_coord", ""))
        self._recognition_to_logic_anchor_screen_edit.setText(action.get("anchor_screen_coord", ""))
        self._recognition_to_logic_result_array_edit.setText(action.get("result_array", ""))
        jump_idx = self._jump_target_combo.findData(action.get("target_id", ""))
        if jump_idx >= 0:
            self._jump_target_combo.setCurrentIndex(jump_idx)
        else:
            self._jump_target_combo.setCurrentIndex(0)
        self._traverse_center_edit.setText(action.get("center_param", ""))
        self._traverse_array_edit.setText(action.get("target_array", ""))
        self._traverse_count_spin.setValue(int(action.get("count", 1000) or 1000))
        _set_combo_data(self._traverse_mode_combo, normalize_grid_mode(action.get("mode", "hex")), default="hex")
        self._two_ring_target_coord_edit.setText(action.get("target_coord", ""))
        self._two_ring_result_array_edit.setText(action.get("result_array", ""))
        self._surround_radius_spin.setValue(_coerce_grid_radius(action.get("radius", 2), 2))
        _set_combo_data(self._surround_mode_combo, normalize_grid_mode(action.get("mode", "hex")), default="hex")
        self._path_target_coord_edit.setText(action.get("target_coord", ""))
        self._path_start_array_edit.setText(action.get("start_array", ""))
        self._path_passable_array_edit.setText(action.get("passable_array", ""))
        self._path_result_array_edit.setText(action.get("result_array", ""))
        _set_combo_data(self._path_mode_combo, normalize_grid_mode(action.get("mode", "hex")), default="hex")
        self._editing_add_to_array_items = copy.deepcopy(action.get("items", []))
        self._refresh_arr_items()
        self._on_action_type_changed()
        self._set_inline_action_editor_visible(False)

    def _set_inline_action_editor_visible(self, visible: bool):
        if not hasattr(self, "_form"):
            return
        start_row, _ = self._form.getWidgetPosition(self._action_type)
        end_row, _ = self._form.getWidgetPosition(self._path_mode_label)
        if start_row < 0 or end_row < start_row:
            return
        for row in range(start_row, end_row + 1):
            self._form.setRowVisible(row, visible)

    def _refresh_main_actions(self):
        self._actions_list.clear()
        for action in self._actions:
            summary = _format_action_summary(action, self._task_steps)
            self._actions_list.addItem(QListWidgetItem(summary))

    def _select_main_action(self, row: int):
        self._selected_action_index = row
        if row < 0 or row >= len(self._actions):
            self._set_inline_action_editor_visible(False)
            return
        self._load_action_to_editor(self._actions[row])
        self._set_inline_action_editor_visible(False)

    def _add_main_action(self):
        dlg = MainActionEditDialog(
            task_params=self._task_params,
            task_steps=self._task_steps,
            task=self._task,
            step_context=self._build_preview_step_context(),
            parent=self,
        )
        if dlg.exec() == QDialog.Accepted:
            result = dlg.get_result()
            if result:
                self._actions.append(result)
                self._refresh_main_actions()
                self._actions_list.setCurrentRow(len(self._actions) - 1)
        self._set_inline_action_editor_visible(False)

    def _edit_main_action(self):
        row = self._actions_list.currentRow()
        if row < 0 or row >= len(self._actions):
            QMessageBox.warning(self, "提示", "请先选择一个操作")
            self._set_inline_action_editor_visible(False)
            return
        dlg = MainActionEditDialog(
            action=copy.deepcopy(self._actions[row]),
            task_params=self._task_params,
            task_steps=self._task_steps,
            task=self._task,
            step_context=self._build_preview_step_context(),
            parent=self,
        )
        if dlg.exec() == QDialog.Accepted:
            result = dlg.get_result()
            if result:
                self._actions[row] = result
                self._refresh_main_actions()
                self._actions_list.setCurrentRow(row)
        self._set_inline_action_editor_visible(False)

    def _update_main_action(self):
        self._edit_main_action()

    def _del_main_action(self):
        row = self._actions_list.currentRow()
        if row < 0 or row >= len(self._actions):
            self._set_inline_action_editor_visible(False)
            return
        self._actions.pop(row)
        self._refresh_main_actions()
        if self._actions:
            self._actions_list.setCurrentRow(min(row, len(self._actions) - 1))
        else:
            self._selected_action_index = -1
            self._load_action_to_editor({"type": "none", "delay": 0.0})
        self._set_inline_action_editor_visible(False)

    def _move_main_action_up(self):
        row = self._actions_list.currentRow()
        if row > 0:
            self._actions[row], self._actions[row - 1] = self._actions[row - 1], self._actions[row]
            self._refresh_main_actions()
            self._actions_list.setCurrentRow(row - 1)
        self._set_inline_action_editor_visible(False)

    def _move_main_action_down(self):
        row = self._actions_list.currentRow()
        if row >= 0 and row < len(self._actions) - 1:
            self._actions[row], self._actions[row + 1] = self._actions[row + 1], self._actions[row]
            self._refresh_main_actions()
            self._actions_list.setCurrentRow(row + 1)
        self._set_inline_action_editor_visible(False)

    # ── 数组项操作 ──
    def _add_array_item(self):
        """添加数组项 - 使用对话框选择"""
        dlg = AddArrayItemDialog(
            task_params=self._task_params,
            task=self._task,
            parent=self
        )
        if dlg.exec() == QDialog.Accepted:
            result = dlg.get_result()
            if result:
                self._editing_add_to_array_items.append(result)
                self._refresh_arr_items()

    def _del_array_item(self):
        row = self._arr_items_list.currentRow()
        if row >= 0 and row < len(self._editing_add_to_array_items):
            self._editing_add_to_array_items.pop(row)
            self._refresh_arr_items()

    def _refresh_arr_items(self):
        self._arr_items_list.clear()
        for item in self._editing_add_to_array_items:
            self._arr_items_list.addItem(_format_array_assignment_item(self._task_params, item))

    def _on_fail_enabled_changed(self):
        """启用/禁用识别失败操作"""
        enabled = self._on_fail_enabled.isChecked()
        self._on_fail_actions_list.setEnabled(enabled)
        self._on_fail_action_add_btn.setEnabled(enabled)
        self._on_fail_action_edit_btn.setEnabled(enabled)
        self._on_fail_action_del_btn.setEnabled(enabled)
        self._on_fail_action_up_btn.setEnabled(enabled)
        self._on_fail_action_down_btn.setEnabled(enabled)

    def _add_fail_action(self):
        """添加失败操作"""
        dlg = MainActionEditDialog(
            task_params=self._task_params,
            task_steps=self._task_steps,
            task=self._task,
            step_context=self._build_preview_step_context(),
            action_type_groups=MAIN_ACTION_TYPE_GROUPS,
            dialog_title="新增失败操作",
            parent=self
        )
        if dlg.exec() == QDialog.Accepted:
            result = dlg.get_result()
            if result:
                self._step.on_fail_actions.append(result)
                self._refresh_fail_actions()

    def _edit_fail_action(self):
        """编辑失败操作"""
        row = self._on_fail_actions_list.currentRow()
        if row < 0 or row >= len(self._step.on_fail_actions):
            QMessageBox.warning(self, "提示", "请先选择一个操作")
            return
        
        dlg = MainActionEditDialog(
            action=copy.deepcopy(self._step.on_fail_actions[row]),
            task_params=self._task_params,
            task_steps=self._task_steps,
            task=self._task,
            step_context=self._build_preview_step_context(),
            action_type_groups=MAIN_ACTION_TYPE_GROUPS,
            dialog_title="编辑失败操作",
            parent=self
        )
        if dlg.exec() == QDialog.Accepted:
            result = dlg.get_result()
            if result:
                self._step.on_fail_actions[row] = result
                self._refresh_fail_actions()

    def _del_fail_action(self):
        """删除失败操作"""
        row = self._on_fail_actions_list.currentRow()
        if row >= 0 and row < len(self._step.on_fail_actions):
            self._step.on_fail_actions.pop(row)
            self._refresh_fail_actions()

    def _move_fail_action_up(self):
        """上移失败操作"""
        row = self._on_fail_actions_list.currentRow()
        if row > 0:
            self._step.on_fail_actions[row], self._step.on_fail_actions[row - 1] = \
                self._step.on_fail_actions[row - 1], self._step.on_fail_actions[row]
            self._refresh_fail_actions()
            self._on_fail_actions_list.setCurrentRow(row - 1)

    def _move_fail_action_down(self):
        """下移失败操作"""
        row = self._on_fail_actions_list.currentRow()
        if row >= 0 and row < len(self._step.on_fail_actions) - 1:
            self._step.on_fail_actions[row], self._step.on_fail_actions[row + 1] = \
                self._step.on_fail_actions[row + 1], self._step.on_fail_actions[row]
            self._refresh_fail_actions()
            self._on_fail_actions_list.setCurrentRow(row + 1)

    def _refresh_fail_actions(self):
        """刷新失败操作列表"""
        self._on_fail_actions_list.clear()
        for action in self._step.on_fail_actions:
            summary = _format_action_summary(action, self._task_steps)
            self._on_fail_actions_list.addItem(QListWidgetItem(summary))

    def _on_jump_target_changed(self, index=0):
        del index
        target_id = ""
        if self._action_type.currentData() == "jump_to_step":
            target_id = self._jump_target_combo.currentData() or ""
        _set_jump_target_preview(self, target_id)

    def _load_data(self):
        """加载步骤数据到控件"""
        s = self._step
        self._step_id_label.setText(f"ID: {s.id}")
        self._name_edit.setText(s.name if s.name != "未命名步骤" else "")

        # 识别类型
        idx = self._recognition_type.findData(s.recognition_type)
        if idx >= 0:
            self._recognition_type.setCurrentIndex(idx)

        self._target_edit.setText(s.recognition_target)
        _set_combo_data(
            self._target_mode_combo,
            normalize_recognition_target_mode(getattr(s, "recognition_target_mode", "single")),
        )
        _set_combo_data(
            self._image_match_mode_combo,
            normalize_image_match_mode(getattr(s, "image_match_mode", "template")),
            default="template",
        )
        _set_combo_data(
            self._recognition_roi_mode_combo,
            normalize_recognition_roi_mode(getattr(s, "recognition_roi_mode", "full_window")),
            default="full_window",
        )
        self._recognition_roi_x_spin.setValue(_coerce_point_ratio(getattr(s, "recognition_roi_x", 0.0), 0.0))
        self._recognition_roi_y_spin.setValue(_coerce_point_ratio(getattr(s, "recognition_roi_y", 0.0), 0.0))
        self._recognition_roi_width_spin.setValue(max(0.01, _coerce_point_ratio(getattr(s, "recognition_roi_width", 1.0), 1.0)))
        self._recognition_roi_height_spin.setValue(max(0.01, _coerce_point_ratio(getattr(s, "recognition_roi_height", 1.0), 1.0)))
        self._exact_match.setChecked(s.exact_match)
        self._threshold_spin.setValue(s.recognition_threshold)
        self._validate_color_check.setChecked(getattr(s, "validate_color_consistency", False))
        self._match_index_spin.setValue(s.match_index)
        self._has_multiple_matches.setChecked(s.has_multiple_matches)

        # 操作类型
        idx = self._action_type.findData(_normalize_grid_action_type(s.action_type))
        if idx >= 0:
            self._action_type.setCurrentIndex(idx)
        self._action_delay_spin.setValue(0.0)

        self._use_background.setChecked(s.use_background)
        self._timeout_spin.setValue(s.timeout)
        self._retry_spin.setValue(s.retry_interval)
        _set_combo_data(
            self._click_offset_mode,
            getattr(s, "click_offset_mode", get_default_click_offset_mode(getattr(s, "point_position_mode", "recognition"))),
            default=get_default_click_offset_mode(getattr(s, "point_position_mode", "recognition")),
        )
        self._offset_x_spin.setValue(s.click_offset_x)
        self._offset_y_spin.setValue(s.click_offset_y)
        self._delay_after_spin.setValue(s.delay_after)

        # 新字段
        self._input_text_edit.setText(s.input_text)
        self._press_keys_edit.setText(s.press_keys)
        idx = self._clear_method.findData(s.clear_method)
        if idx >= 0:
            self._clear_method.setCurrentIndex(idx)
        self._clear_key_count_spin.setValue(s.clear_key_count)
        self._highlight_duration_spin.setValue(_highlight_duration_seconds_from_ms(getattr(s, "highlight_duration_ms", 1200)))

        # 拖动地图字段
        _set_combo_data(self._drag_coordinate_mode, getattr(s, "drag_coordinate_mode", "game_logic"), default="game_logic")
        _set_combo_data(self._drag_start_mode, getattr(s, "drag_start_mode", "recognition"), default="recognition")
        self._drag_start_x_spin.setValue(_coerce_drag_start_ratio(getattr(s, "drag_start_x", 0.5), 0.5))
        self._drag_start_y_spin.setValue(_coerce_drag_start_ratio(getattr(s, "drag_start_y", 0.5), 0.5))
        drag_vector_mode, drag_vector_x, drag_vector_y = _get_screen_drag_vector_values(s)
        _set_combo_data(self._drag_vector_mode, drag_vector_mode, default="pixel")
        self._drag_vector_x_spin.setValue(drag_vector_x)
        self._drag_vector_y_spin.setValue(drag_vector_y)
        self._drag_dir_x_spin.setValue(s.drag_direction_x)
        self._drag_dir_y_spin.setValue(s.drag_direction_y)
        self._drag_distance_spin.setValue(s.drag_distance)
        self._drag_duration_spin.setValue(s.drag_duration)
        self._drag_center_tolerance_spin.setValue(normalize_center_tolerance_px(getattr(s, "center_tolerance_px", 1)))

        # 新增：修改变量
        self._modify_var_name_edit.setText(s.modify_var_name)
        self._modify_var_value_edit.setText(s.modify_var_value)
        self._clear_array_edit.setText(s.clear_array_name)
        # 新增：跳转步骤
        idx = self._jump_target_combo.findData(s.jump_target_id)
        if idx >= 0:
            self._jump_target_combo.setCurrentIndex(idx)
        # 新增：遍历网格
        self._traverse_center_edit.setText(s.traverse_center_param)
        self._traverse_array_edit.setText(s.traverse_target_array)
        self._traverse_count_spin.setValue(s.traverse_count)
        _set_combo_data(self._traverse_mode_combo, normalize_grid_mode(getattr(s, "traverse_mode", "hex")), default="hex")
        self._two_ring_target_coord_edit.setText(getattr(s, "surround_target_coord", "") or s.two_ring_target_coord)
        self._two_ring_result_array_edit.setText(getattr(s, "surround_result_array", "") or s.two_ring_result_array)
        self._surround_radius_spin.setValue(_coerce_grid_radius(getattr(s, "surround_radius", 2), 2))
        _set_combo_data(self._surround_mode_combo, normalize_grid_mode(getattr(s, "surround_mode", "hex")), default="hex")
        self._path_target_coord_edit.setText(s.path_target_coord)
        self._path_start_array_edit.setText(s.path_start_array)
        self._path_passable_array_edit.setText(s.path_passable_array)
        self._path_result_array_edit.setText(s.path_result_array)
        _set_combo_data(self._path_mode_combo, normalize_grid_mode(getattr(s, "path_mode", "hex")), default="hex")
        self._actions = [copy.deepcopy(action) for action in s.actions if isinstance(action, dict)]
        if not self._actions:
            legacy_action = _legacy_step_action_to_dict(s)
            if legacy_action:
                self._actions.append(legacy_action)
        self._refresh_main_actions()
        if self._actions:
            self._actions_list.setCurrentRow(0)
        else:
            self._selected_action_index = -1
            self._load_action_to_editor({"type": s.action_type or "click", "delay": 0.0})
        # 新增：条件
        self._refresh_cond_list()
        
        # 新增：识别失败操作
        self._on_fail_enabled.setChecked(s.on_fail_enabled)
        # 向后兼容：如果有旧字段，转换为新格式
        if not s.on_fail_actions and s.on_fail_action_type:
            if s.on_fail_action_type == "modify_variable" and s.on_fail_modify_var_name:
                s.on_fail_actions.append({
                    "type": "modify_variable",
                    "var_name": s.on_fail_modify_var_name,
                    "var_value": s.on_fail_modify_var_value
                })
            elif s.on_fail_action_type == "add_to_array" and s.on_fail_add_array_items:
                s.on_fail_actions.append({
                    "type": "add_to_array",
                    "items": s.on_fail_add_array_items
                })
            elif s.on_fail_action_type == "jump_to_step" and s.on_fail_jump_target_id:
                s.on_fail_actions.append({
                    "type": "jump_to_step",
                    "target_id": s.on_fail_jump_target_id
                })
            elif s.on_fail_action_type in ("continue_loop", "break_loop"):
                s.on_fail_actions.append({"type": s.on_fail_action_type})
        self._refresh_fail_actions()

        # 刷新显隐状态
        self._on_type_changed(self._recognition_type.currentIndex())
        self._on_action_type_changed()
        self._on_fail_enabled_changed()
        self._set_inline_action_editor_visible(False)
        
        # 重新设置阈值，避免被 _on_type_changed 覆盖
        self._threshold_spin.setValue(s.recognition_threshold)

    def done(self, result):
        _set_jump_target_preview(self, "")
        super().done(result)

    def get_step(self) -> SingleTask:
        """获取编辑后的步骤"""
        name = self._name_edit.text().strip()
        if not name:
            name = "未命名步骤"

        self._step.name = name
        self._step.recognition_type = self._recognition_type.currentData()
        self._step.recognition_target = self._target_edit.text().strip()
        self._step.recognition_target_mode = normalize_recognition_target_mode(
            self._target_mode_combo.currentData()
        )
        self._step.image_match_mode = normalize_image_match_mode(self._image_match_mode_combo.currentData())
        self._step.recognition_roi_mode = normalize_recognition_roi_mode(self._recognition_roi_mode_combo.currentData())
        self._step.recognition_roi_x = _coerce_point_ratio(self._recognition_roi_x_spin.value(), 0.0)
        self._step.recognition_roi_y = _coerce_point_ratio(self._recognition_roi_y_spin.value(), 0.0)
        self._step.recognition_roi_width = max(0.01, _coerce_point_ratio(self._recognition_roi_width_spin.value(), 1.0))
        self._step.recognition_roi_height = max(0.01, _coerce_point_ratio(self._recognition_roi_height_spin.value(), 1.0))
        self._step.exact_match = self._exact_match.isChecked()
        self._step.recognition_threshold = self._threshold_spin.value()
        self._step.validate_color_consistency = self._validate_color_check.isChecked()
        self._step.match_index = self._match_index_spin.value()
        self._step.has_multiple_matches = self._has_multiple_matches.isChecked()
        self._step.action_type = _normalize_grid_action_type(self._action_type.currentData())
        self._step.input_text = self._input_text_edit.text().strip()
        self._step.press_keys = self._press_keys_edit.text().strip()
        self._step.clear_method = self._clear_method.currentData()
        self._step.clear_key_count = self._clear_key_count_spin.value()
        self._step.highlight_duration_ms = int(round(self._highlight_duration_spin.value() * 1000))
        self._step.drag_coordinate_mode = self._drag_coordinate_mode.currentData() or "game_logic"
        self._step.drag_start_mode = self._drag_start_mode.currentData() or "recognition"
        self._step.drag_start_x = self._drag_start_x_spin.value()
        self._step.drag_start_y = self._drag_start_y_spin.value()
        self._step.drag_vector_mode = normalize_drag_vector_mode(self._drag_vector_mode.currentData() or "pixel")
        self._step.drag_vector_x = self._drag_vector_x_spin.value()
        self._step.drag_vector_y = self._drag_vector_y_spin.value()
        self._step.drag_direction_x = self._drag_dir_x_spin.value()
        self._step.drag_direction_y = self._drag_dir_y_spin.value()
        self._step.drag_distance = self._drag_distance_spin.value()
        self._step.drag_duration = self._drag_duration_spin.value()
        self._step.center_tolerance_px = self._drag_center_tolerance_spin.value()
        self._step.use_background = self._use_background.isChecked()
        self._step.timeout = self._timeout_spin.value()
        self._step.retry_interval = self._retry_spin.value()
        self._step.click_offset_x = self._offset_x_spin.value()
        self._step.click_offset_y = self._offset_y_spin.value()
        self._step.delay_after = self._delay_after_spin.value()

        self._step.actions = copy.deepcopy(self._actions)
        _apply_action_dict_to_step(self._step, self._step.actions[0] if self._step.actions else None)
        # 识别失败操作
        self._step.on_fail_enabled = self._on_fail_enabled.isChecked()
        # conditions 和 on_fail_actions 已经在 _step 上直接修改
        return self._step


class ConditionEditDialog(QDialog):
    """条件编辑对话框"""

    def __init__(self, condition: StepCondition = None, task_params: List[TaskParameter] = None, 
                 task: PlanTask = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑条件" if condition else "新增条件")
        self.setMinimumWidth(450)
        self._cond = condition or StepCondition()
        self._task = task
        self._task_params = task_params or []
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._type_combo = QComboBox()
        self._type_combo.addItem("变量比较", "variable")
        self._type_combo.addItem("图像识别", "image")
        self._type_combo.addItem("文字识别", "text")
        self._type_combo.addItem("数组包含", "array_contains")
        self._type_combo.addItem("坐标在数组中", "coord_in_array")
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("条件类型:", self._type_combo)

        # 变量条件
        left_layout = QHBoxLayout()
        self._left_edit = QLineEdit()
        self._left_edit.setPlaceholderText("左操作数（变量名或 {参数}）")
        left_layout.addWidget(self._left_edit)
        self._left_browse_btn = QPushButton("选择")
        self._left_browse_btn.clicked.connect(self._browse_left_operand)
        left_layout.addWidget(self._left_browse_btn)
        self._left_length_check = QCheckBox("取长度")
        self._left_length_check.setToolTip("勾选后比较左操作数的长度，例如数组项数或文本长度")
        self._left_length_check.toggled.connect(self._refresh_variable_operator_options)
        left_layout.addWidget(self._left_length_check)
        self._left_label = QLabel("左操作数:")
        form.addRow(self._left_label, left_layout)

        self._op_combo = QComboBox()
        self._set_operator_options(["==", "!=", ">", "<", ">=", "<=", "contains"])
        self._op_label = QLabel("运算符:")
        form.addRow(self._op_label, self._op_combo)

        right_layout = QHBoxLayout()
        self._right_edit = QLineEdit()
        self._right_edit.setPlaceholderText("右操作数（值或 {参数}）")
        right_layout.addWidget(self._right_edit)
        self._right_browse_btn = QPushButton("选择")
        self._right_browse_btn.clicked.connect(self._browse_right_operand)
        right_layout.addWidget(self._right_browse_btn)
        self._right_length_check = QCheckBox("取长度")
        self._right_length_check.setToolTip("勾选后比较右操作数的长度，例如数组项数或文本长度")
        self._right_length_check.toggled.connect(self._refresh_variable_operator_options)
        right_layout.addWidget(self._right_length_check)
        self._right_label = QLabel("右操作数:")
        form.addRow(self._right_label, right_layout)

        # 图像/文字识别条件
        self._rec_target_edit = QLineEdit()
        self._rec_target_edit.setPlaceholderText("识别目标（图片路径或文字）")
        self._rec_target_label = QLabel("识别目标:")
        form.addRow(self._rec_target_label, self._rec_target_edit)

        self._threshold_spin = QDoubleSpinBox()
        self._threshold_spin.setRange(0.1, 1.0)
        self._threshold_spin.setSingleStep(0.05)
        self._threshold_spin.setValue(0.8)
        self._threshold_label = QLabel("识别阈值:")
        form.addRow(self._threshold_label, self._threshold_spin)

        self._validate_color_check = QCheckBox("验证颜色一致性")
        self._validate_color_check.setToolTip("勾选后会在图像条件匹配成功后再核对颜色分布，避免彩色图误匹配到灰度图")
        form.addRow("", self._validate_color_check)

        # 数组条件
        array_layout = QHBoxLayout()
        self._array_name_edit = QLineEdit()
        self._array_name_edit.setPlaceholderText("数组参数名")
        array_layout.addWidget(self._array_name_edit)
        self._array_browse_btn = QPushButton("选择")
        self._array_browse_btn.clicked.connect(self._browse_array_name)
        array_layout.addWidget(self._array_browse_btn)
        self._array_name_label = QLabel("数组名:")
        form.addRow(self._array_name_label, array_layout)

        # 搜索值（带选择功能）
        search_value_layout = QHBoxLayout()
        self._search_value_edit = QLineEdit()
        self._search_value_edit.setPlaceholderText("搜索值（支持 {参数}）")
        search_value_layout.addWidget(self._search_value_edit)
        self._search_value_browse_btn = QPushButton("从参数选择")
        self._search_value_browse_btn.clicked.connect(self._browse_search_value)
        search_value_layout.addWidget(self._search_value_browse_btn)
        self._search_value_label = QLabel("搜索值:")
        form.addRow(self._search_value_label, search_value_layout)

        # 取反
        self._negate_check = QCheckBox("取反（NOT）")
        form.addRow("", self._negate_check)

        # 逻辑连接
        self._logic_combo = QComboBox()
        self._logic_combo.addItem("（无，最后一个条件）", "")
        self._logic_combo.addItem("AND（并且）", "and")
        self._logic_combo.addItem("OR（或者）", "or")
        form.addRow("逻辑连接:", self._logic_combo)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._on_type_changed()

    def _browse_param_name(self, target_widget: QLineEdit, filter_type=None):
        """从参数列表中选择参数名
        filter_type: 可以是字符串或元组，用于过滤参数类型
        """
        empty_message = "当前任务没有符合条件的参数" if filter_type else "当前任务还没有定义参数"
        param = _pick_task_param(
            self,
            self._task_params,
            "选择参数",
            "请选择一个参数:",
            filter_type=filter_type,
            task=self._task,
            empty_message=empty_message,
        )
        if param:
            target_widget.setText(param.name)

    def _browse_left_operand(self):
        param = _pick_task_param(
            self,
            self._task_params,
            "选择变量",
            "请选择左操作数变量:",
            task=self._task,
            empty_message="当前任务还没有定义参数",
        )
        if not param:
            return
        reference = _build_param_reference(self, param, allow_coordinate_full=False)
        if reference:
            self._left_edit.setText(reference)

    def _browse_right_operand(self):
        param = _pick_task_param(
            self,
            self._task_params,
            "选择变量",
            "请选择右操作数变量:",
            task=self._task,
            empty_message="当前任务还没有定义参数",
        )
        if not param:
            return
        reference = _build_param_reference(self, param, allow_coordinate_full=False)
        if reference:
            self._right_edit.setText(reference)

    def _browse_array_name(self):
        param = _pick_task_param(
            self,
            self._task_params,
            "选择数组",
            "请选择一个数组参数:",
            predicate=lambda item: is_array_param_type(item.param_type),
            task=self._task,
            empty_message="当前任务没有数组或结构体数组参数",
        )
        if param:
            self._array_name_edit.setText(param.name)

    def _browse_search_value(self):
        """选择搜索值（支持参数和循环变量）"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QDialogButtonBox
        
        dlg = QDialog(self)
        dlg.setWindowTitle("选择搜索值")
        dlg.setMinimumWidth(400)
        layout = QVBoxLayout(dlg)
        form = QFormLayout()
        
        # 值来源
        source_combo = QComboBox()
        source_combo.addItem("直接输入", "direct")
        source_combo.addItem("选择参数", "param")
        form.addRow("值来源:", source_combo)
        
        # 直接输入
        direct_edit = QLineEdit()
        direct_edit.setText(self._search_value_edit.text())
        direct_label = QLabel("输入值:")
        form.addRow(direct_label, direct_edit)
        
        # 选择参数
        param_layout = QHBoxLayout()
        param_combo = QComboBox()
        param_layout.addWidget(param_combo)
        param_create_btn = QPushButton("创建变量")
        param_create_btn.setVisible(self._task is not None)
        param_layout.addWidget(param_create_btn)
        param_label = QLabel("选择参数:")
        form.addRow(param_label, param_layout)
        param_label.setVisible(False)
        param_combo.setVisible(False)
        param_create_btn.setVisible(False)
        
        # 坐标参数的 x/y 选择
        coord_part_combo = QComboBox()
        coord_part_combo.addItem("完整坐标 {x},{y}", "full")
        coord_part_combo.addItem("仅 X 坐标", "x")
        coord_part_combo.addItem("仅 Y 坐标", "y")
        coord_part_label = QLabel("坐标部分:")
        form.addRow(coord_part_label, coord_part_combo)
        coord_part_label.setVisible(False)
        coord_part_combo.setVisible(False)

        struct_field_combo = QComboBox()
        struct_field_label = QLabel("结构体字段:")
        form.addRow(struct_field_label, struct_field_combo)
        struct_field_label.setVisible(False)
        struct_field_combo.setVisible(False)
        
        # 预览
        preview_edit = QLineEdit()
        preview_edit.setReadOnly(True)
        form.addRow("预览:", preview_edit)
        
        layout.addLayout(form)

        def refresh_param_combo(selected_name: str = ""):
            _populate_param_combo(
                param_combo,
                self._task_params,
                "（无可用参数，请先创建）",
                selected_name=selected_name,
            )
        
        def update_visibility():
            source = source_combo.currentData()
            is_direct = source == "direct"
            is_param = source == "param"
            
            direct_label.setVisible(is_direct)
            direct_edit.setVisible(is_direct)
            param_label.setVisible(is_param)
            param_combo.setVisible(is_param)
            param_create_btn.setVisible(is_param and self._task is not None)
            
            if is_param:
                param_name = param_combo.currentData()
                if param_name:
                    param = next((p for p in self._task_params if p.name == param_name), None)
                    show_coord = param and param.param_type == "coordinate"
                    show_struct = bool(param and isinstance(param.value, dict) and param.param_type != "coordinate")
                    coord_part_label.setVisible(show_coord)
                    coord_part_combo.setVisible(show_coord)
                    struct_field_label.setVisible(show_struct)
                    struct_field_combo.setVisible(show_struct)
                    if show_struct:
                        struct_field_combo.blockSignals(True)
                        struct_field_combo.clear()
                        for field_name in param.value.keys():
                            struct_field_combo.addItem(field_name, field_name)
                        struct_field_combo.blockSignals(False)
                else:
                    coord_part_label.setVisible(False)
                    coord_part_combo.setVisible(False)
                    struct_field_label.setVisible(False)
                    struct_field_combo.setVisible(False)
            else:
                coord_part_label.setVisible(False)
                coord_part_combo.setVisible(False)
                struct_field_label.setVisible(False)
                struct_field_combo.setVisible(False)
            
            update_preview()

        def create_param():
            new_param = _inline_create_task_param(dlg, self._task, self._task_params)
            if not new_param:
                return
            refresh_param_combo(new_param.name)
            update_visibility()
        
        def update_preview():
            source = source_combo.currentData()
            if source == "direct":
                preview_edit.setText(direct_edit.text())
            elif source == "param":
                param_name = param_combo.currentData()
                if param_name:
                    param = next((p for p in self._task_params if p.name == param_name), None)
                    if param:
                        if param.param_type == "coordinate":
                            part = coord_part_combo.currentData()
                            if part == "x":
                                preview_edit.setText(f"{{{param_name}.x}}")
                            elif part == "y":
                                preview_edit.setText(f"{{{param_name}.y}}")
                            else:
                                preview_edit.setText(f"{{{param_name}.x}},{{{param_name}.y}}")
                        elif isinstance(param.value, dict) and struct_field_combo.currentData():
                            preview_edit.setText(f"{{{param_name}.{struct_field_combo.currentData()}}}")
                        else:
                            preview_edit.setText(f"{{{param_name}}}")
        
        source_combo.currentIndexChanged.connect(update_visibility)
        param_combo.currentIndexChanged.connect(update_visibility)
        coord_part_combo.currentIndexChanged.connect(update_preview)
        struct_field_combo.currentIndexChanged.connect(update_preview)
        direct_edit.textChanged.connect(update_preview)
        param_create_btn.clicked.connect(create_param)
        
        refresh_param_combo()
        update_visibility()
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        
        if dlg.exec() == QDialog.Accepted:
            self._search_value_edit.setText(preview_edit.text())

    def _set_operator_options(self, operators: List[str], preferred: str = None):
        current = preferred if preferred is not None else self._op_combo.currentData()
        self._op_combo.blockSignals(True)
        self._op_combo.clear()
        for op in operators:
            self._op_combo.addItem(op, op)
        idx = self._op_combo.findData(current)
        self._op_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._op_combo.blockSignals(False)

    def _refresh_variable_operator_options(self, checked=False):
        del checked
        if self._type_combo.currentData() != "variable":
            self._set_operator_options(["==", "!=", ">", "<", ">=", "<=", "contains"])
            return
        if self._left_length_check.isChecked() or self._right_length_check.isChecked():
            self._set_operator_options(["==", "!=", ">", "<", ">=", "<="])
            return
        self._set_operator_options(["==", "!=", ">", "<", ">=", "<=", "contains"])

    def _on_type_changed(self, index=0):
        ct = self._type_combo.currentData()
        is_var = ct == "variable"
        is_rec = ct in ("image", "text")
        is_image_rec = ct == "image"
        is_arr = ct in ("array_contains", "coord_in_array")

        self._refresh_variable_operator_options()
        self._right_label.setText("右操作数:")
        self._right_edit.setPlaceholderText("右操作数（值或 {参数}）")
        self._array_name_label.setText("数组名:")
        self._array_name_edit.setPlaceholderText("数组参数名")
        self._search_value_label.setText("搜索值:")
        self._search_value_edit.setPlaceholderText("搜索值（支持 {参数}）")

        if ct == "coord_in_array":
            self._search_value_label.setText("坐标值:")
            self._search_value_edit.setPlaceholderText("坐标值（如 100,200 或 {参数}）")

        self._left_label.setVisible(is_var)
        self._left_edit.setVisible(is_var)
        self._left_browse_btn.setVisible(is_var)
        self._left_length_check.setVisible(is_var)
        self._op_label.setVisible(is_var)
        self._op_combo.setVisible(is_var)
        self._right_label.setVisible(is_var)
        self._right_edit.setVisible(is_var)
        self._right_browse_btn.setVisible(is_var)
        self._right_length_check.setVisible(is_var)

        self._rec_target_label.setVisible(is_rec)
        self._rec_target_edit.setVisible(is_rec)
        self._threshold_label.setVisible(is_rec)
        self._threshold_spin.setVisible(is_rec)
        self._validate_color_check.setVisible(is_image_rec)

        self._array_name_label.setVisible(is_arr)
        self._array_name_edit.setVisible(is_arr)
        self._array_browse_btn.setVisible(is_arr)
        self._search_value_label.setVisible(is_arr)
        self._search_value_edit.setVisible(is_arr)
        self._search_value_browse_btn.setVisible(is_arr)

    def _load_data(self):
        c = self._cond
        idx = self._type_combo.findData(c.condition_type)
        if idx >= 0:
            self._type_combo.setCurrentIndex(idx)
        self._left_edit.setText(c.left_operand)
        self._right_edit.setText(c.right_operand)
        self._left_length_check.setChecked(getattr(c, "left_use_length", False))
        self._right_length_check.setChecked(getattr(c, "right_use_length", False))
        self._on_type_changed()
        idx = self._op_combo.findData(c.operator)
        if idx >= 0:
            self._op_combo.setCurrentIndex(idx)
        self._rec_target_edit.setText(c.rec_target)
        self._threshold_spin.setValue(c.threshold)
        self._validate_color_check.setChecked(getattr(c, "validate_color_consistency", False))
        self._array_name_edit.setText(c.array_name)
        self._search_value_edit.setText(c.search_value)
        self._negate_check.setChecked(c.negate)
        idx = self._logic_combo.findData(c.logic_next)
        if idx >= 0:
            self._logic_combo.setCurrentIndex(idx)

    def get_condition(self) -> dict:
        """返回条件字典（与 StepCondition.to_dict 格式一致）"""
        is_var = self._type_combo.currentData() == "variable"
        return {
            "condition_type": self._type_combo.currentData(),
            "left_operand": self._left_edit.text().strip(),
            "left_use_length": self._left_length_check.isChecked() if is_var else False,
            "operator": self._op_combo.currentData(),
            "right_operand": self._right_edit.text().strip(),
            "right_use_length": self._right_length_check.isChecked() if is_var else False,
            "rec_target": self._rec_target_edit.text().strip(),
            "threshold": self._threshold_spin.value(),
            "validate_color_consistency": self._validate_color_check.isChecked(),
            "negate": self._negate_check.isChecked(),
            "array_name": self._array_name_edit.text().strip(),
            "search_value": self._search_value_edit.text().strip(),
            "logic_next": self._logic_combo.currentData(),
        }


class StructFieldEditDialog(QDialog):
    """结构体成员编辑对话框"""

    def __init__(self, field_def: StructField = None, existing_names: List[str] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑成员" if field_def else "新增成员")
        self.setMinimumWidth(320)
        self._field_def = copy.deepcopy(field_def) if field_def else StructField()
        self._existing_names = set(existing_names or [])
        if self._field_def.name:
            self._existing_names.discard(self._field_def.name)
        self._result = None
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("成员名，例如：level")
        form.addRow("成员名:", self._name_edit)

        self._type_combo = QComboBox()
        self._type_combo.addItem("整形", "int")
        self._type_combo.addItem("字符串", "string")
        form.addRow("类型:", self._type_combo)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_data(self):
        self._name_edit.setText(self._field_def.name)
        idx = self._type_combo.findData(self._field_def.field_type)
        if idx >= 0:
            self._type_combo.setCurrentIndex(idx)

    def _on_accept(self):
        name = self._name_edit.text().strip()
        field_type = self._type_combo.currentData()
        if not name:
            QMessageBox.warning(self, "提示", "请输入成员名")
            return
        if name in self._existing_names:
            QMessageBox.warning(self, "提示", f"成员 '{name}' 已存在")
            return
        self._result = StructField(name=name, field_type=field_type)
        self.accept()

    def get_field(self) -> StructField:
        return copy.deepcopy(self._result or self._field_def)


class StructEditDialog(QDialog):
    """结构体定义编辑对话框"""

    def __init__(self, struct_def: StructDefinition = None, existing_names: List[str] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑结构体" if struct_def else "新增结构体")
        self.setMinimumWidth(460)
        self._struct_def = copy.deepcopy(struct_def) if struct_def else StructDefinition()
        self._existing_names = set(existing_names or [])
        if self._struct_def.name:
            self._existing_names.discard(self._struct_def.name)
        self._result = None
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("例如：地块信息")
        form.addRow("结构体名:", self._name_edit)
        layout.addLayout(form)

        field_group = QGroupBox("成员变量")
        field_layout = QVBoxLayout(field_group)
        field_btn_layout = QHBoxLayout()
        self._add_field_btn = QPushButton("添加变量")
        self._add_field_btn.clicked.connect(self._add_field)
        field_btn_layout.addWidget(self._add_field_btn)
        self._edit_field_btn = QPushButton("编辑变量")
        self._edit_field_btn.clicked.connect(self._edit_field)
        field_btn_layout.addWidget(self._edit_field_btn)
        self._del_field_btn = QPushButton("删除变量")
        self._del_field_btn.clicked.connect(self._del_field)
        field_btn_layout.addWidget(self._del_field_btn)
        field_btn_layout.addStretch()
        field_layout.addLayout(field_btn_layout)

        self._fields_table = QTableWidget(0, 2)
        self._fields_table.setHorizontalHeaderLabels(["变量名", "类型"])
        self._fields_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._fields_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._fields_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._fields_table.itemDoubleClicked.connect(self._edit_field)
        self._fields_table.setMaximumHeight(180)
        field_layout.addWidget(self._fields_table)

        layout.addWidget(field_group)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_data(self):
        self._name_edit.setText(self._struct_def.name)
        self._refresh_fields()

    def _refresh_fields(self):
        self._fields_table.setRowCount(0)
        for field_def in self._struct_def.fields:
            row = self._fields_table.rowCount()
            self._fields_table.insertRow(row)
            self._fields_table.setItem(row, 0, QTableWidgetItem(field_def.name))
            self._fields_table.setItem(row, 1, QTableWidgetItem(STRUCT_FIELD_TYPE_LABELS.get(field_def.field_type, field_def.field_type)))

    def _add_field(self):
        dlg = StructFieldEditDialog(
            existing_names=[field_def.name for field_def in self._struct_def.fields],
            parent=self,
        )
        if dlg.exec() == QDialog.Accepted:
            self._struct_def.fields.append(dlg.get_field())
            self._refresh_fields()

    def _edit_field(self):
        row = self._fields_table.currentRow()
        if row < 0 or row >= len(self._struct_def.fields):
            return
        dlg = StructFieldEditDialog(
            field_def=self._struct_def.fields[row],
            existing_names=[field_def.name for field_def in self._struct_def.fields],
            parent=self,
        )
        if dlg.exec() == QDialog.Accepted:
            self._struct_def.fields[row] = dlg.get_field()
            self._refresh_fields()

    def _del_field(self):
        row = self._fields_table.currentRow()
        if row < 0 or row >= len(self._struct_def.fields):
            return
        self._struct_def.fields.pop(row)
        self._refresh_fields()

    def _on_accept(self):
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入结构体名称")
            return
        if name in self._existing_names:
            QMessageBox.warning(self, "提示", f"结构体 '{name}' 已存在")
            return
        if not self._struct_def.fields:
            QMessageBox.warning(self, "提示", "请至少定义一个成员变量")
            return
        self._result = StructDefinition(name=name, fields=list(self._struct_def.fields))
        self.accept()

    def get_struct_def(self) -> StructDefinition:
        return copy.deepcopy(self._result or self._struct_def)


class StructValueEditDialog(QDialog):
    """结构体实例编辑对话框"""

    def __init__(self, struct_def: StructDefinition, value: dict = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"编辑 {struct_def.name}")
        self.setMinimumWidth(360)
        self._struct_def = struct_def
        self._value = _normalize_struct_item(struct_def, value or {})
        self._editors = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        for field_def in self._struct_def.fields:
            if field_def.field_type == "int":
                editor = QSpinBox()
                editor.setRange(-999999999, 999999999)
                editor.setValue(int(self._value.get(field_def.name, 0)))
            else:
                editor = QLineEdit()
                editor.setText(str(self._value.get(field_def.name, "")))
            self._editors[field_def.name] = editor
            form.addRow(f"{field_def.name} ({STRUCT_FIELD_TYPE_LABELS.get(field_def.field_type, field_def.field_type)}):", editor)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_value(self) -> dict:
        result = self._struct_def.build_default_value()
        for field_def in self._struct_def.fields:
            editor = self._editors[field_def.name]
            if field_def.field_type == "int":
                result[field_def.name] = editor.value()
            else:
                result[field_def.name] = editor.text()
        return result


class ParamEditDialog(QDialog):
    """参数编辑对话框（支持基础类型、结构体和结构体数组）"""

    def __init__(self, param: TaskParameter = None, task: PlanTask = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑参数" if param else "新增参数")
        self.setMinimumWidth(460)
        self._task = task or PlanTask()
        self._param = copy.deepcopy(param) if param else TaskParameter()
        self._array_items = []
        self._last_array_item_type = self._param.array_item_type or "string"
        self._struct_array_items = []
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("参数名称")
        form.addRow("参数名:", self._name_edit)

        self._type_combo = QComboBox()
        self._populate_type_combo()
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("类型:", self._type_combo)

        self._text_edit = QLineEdit()
        self._text_edit.setPlaceholderText("文本值")
        self._text_label = QLabel("值:")
        form.addRow(self._text_label, self._text_edit)

        coord_layout = QHBoxLayout()
        coord_layout.addWidget(QLabel("X:"))
        self._coord_x_spin = QSpinBox()
        self._coord_x_spin.setRange(-99999, 99999)
        coord_layout.addWidget(self._coord_x_spin)
        coord_layout.addWidget(QLabel("Y:"))
        self._coord_y_spin = QSpinBox()
        self._coord_y_spin.setRange(-99999, 99999)
        coord_layout.addWidget(self._coord_y_spin)
        self._coord_label = QLabel("坐标:")
        form.addRow(self._coord_label, coord_layout)

        img_layout = QHBoxLayout()
        self._img_edit = QLineEdit()
        img_layout.addWidget(self._img_edit)
        self._img_browse_btn = QPushButton("浏览...")
        self._img_browse_btn.clicked.connect(self._browse_image)
        img_layout.addWidget(self._img_browse_btn)
        self._img_label = QLabel("图像:")
        form.addRow(self._img_label, img_layout)

        self._array_label = QLabel("数组:")
        array_layout = QVBoxLayout()
        array_type_layout = QHBoxLayout()
        self._array_item_type_label = QLabel("元素类型:")
        array_type_layout.addWidget(self._array_item_type_label)
        self._array_item_type_combo = QComboBox()
        self._array_item_type_combo.addItem("文字数组", "string")
        self._array_item_type_combo.addItem("图像路径数组", "image")
        self._array_item_type_combo.addItem("整数数组", "int")
        self._array_item_type_combo.currentIndexChanged.connect(self._on_array_item_type_changed)
        array_type_layout.addWidget(self._array_item_type_combo)
        array_type_layout.addStretch()
        array_layout.addLayout(array_type_layout)

        self._array_items_list = QListWidget()
        self._array_items_list.setMaximumHeight(120)
        self._array_items_list.itemDoubleClicked.connect(self._edit_array_item)
        array_layout.addWidget(self._array_items_list)

        array_btn_layout = QHBoxLayout()
        self._array_add_btn = QPushButton("添加项")
        self._array_add_btn.clicked.connect(self._add_array_item)
        array_btn_layout.addWidget(self._array_add_btn)
        self._array_edit_btn = QPushButton("编辑项")
        self._array_edit_btn.clicked.connect(self._edit_array_item)
        array_btn_layout.addWidget(self._array_edit_btn)
        self._array_del_btn = QPushButton("删除项")
        self._array_del_btn.clicked.connect(self._del_array_item)
        array_btn_layout.addWidget(self._array_del_btn)
        self._array_batch_btn = QPushButton("批量添加")
        self._array_batch_btn.clicked.connect(self._batch_add_array_items)
        array_btn_layout.addWidget(self._array_batch_btn)
        array_btn_layout.addStretch()
        array_layout.addLayout(array_btn_layout)

        self._array_tip_label = QLabel("支持逐项添加，也支持按英文逗号、中文逗号、分号或换行批量添加")
        self._array_tip_label.setWordWrap(True)
        self._array_tip_label.setStyleSheet("color: gray;")
        array_layout.addWidget(self._array_tip_label)
        form.addRow(self._array_label, array_layout)

        self._coord_array_edit = QTextEdit()
        self._coord_array_edit.setPlaceholderText("每行一个坐标，格式: x,y")
        self._coord_array_edit.setMaximumHeight(100)
        self._coord_array_label = QLabel("坐标数组:")
        form.addRow(self._coord_array_label, self._coord_array_edit)

        self._struct_table = QTableWidget(0, 3)
        self._struct_table.setHorizontalHeaderLabels(["字段", "类型", "值"])
        self._struct_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._struct_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._struct_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._struct_table.verticalHeader().setVisible(False)
        self._struct_table.setMaximumHeight(180)
        self._struct_label = QLabel("结构体:")
        form.addRow(self._struct_label, self._struct_table)

        self._struct_array_label = QLabel("结构体数组:")
        struct_array_layout = QVBoxLayout()
        self._struct_array_table = QTableWidget(0, 0)
        self._struct_array_table.verticalHeader().setVisible(False)
        self._struct_array_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._struct_array_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._struct_array_table.setMaximumHeight(180)
        self._struct_array_table.itemDoubleClicked.connect(self._edit_struct_array_item)
        struct_array_layout.addWidget(self._struct_array_table)
        struct_array_btn_layout = QHBoxLayout()
        self._struct_array_add_btn = QPushButton("添加项")
        self._struct_array_add_btn.clicked.connect(self._add_struct_array_item)
        struct_array_btn_layout.addWidget(self._struct_array_add_btn)
        self._struct_array_edit_btn = QPushButton("编辑项")
        self._struct_array_edit_btn.clicked.connect(self._edit_struct_array_item)
        struct_array_btn_layout.addWidget(self._struct_array_edit_btn)
        self._struct_array_del_btn = QPushButton("删除项")
        self._struct_array_del_btn.clicked.connect(self._del_struct_array_item)
        struct_array_btn_layout.addWidget(self._struct_array_del_btn)
        struct_array_btn_layout.addStretch()
        struct_array_layout.addLayout(struct_array_btn_layout)
        form.addRow(self._struct_array_label, struct_array_layout)

        self._persist_check = QCheckBox("保存到文件（下次运行时自动加载）")
        form.addRow("存档:", self._persist_check)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._on_type_changed()

    def _populate_type_combo(self):
        self._type_combo.clear()
        self._type_combo.addItem("文本", "text")
        self._type_combo.addItem("坐标", "coordinate")
        self._type_combo.addItem("图像路径", "image")
        self._type_combo.addItem("数组", "array")
        self._type_combo.addItem("坐标数组", "coord_array")
        for struct_def in self._task.struct_defs:
            self._type_combo.addItem(f"结构体: {struct_def.name}", make_struct_param_type(struct_def.name))
            self._type_combo.addItem(f"结构体数组: {struct_def.name}[]", make_struct_array_param_type(struct_def.name))
        if self._param.param_type and self._type_combo.findData(self._param.param_type) < 0:
            if self._param.param_type == "array":
                self._type_combo.addItem(get_array_param_type_label(self._param.array_item_type), self._param.param_type)
            else:
                self._type_combo.addItem(get_param_type_label(self._param.param_type), self._param.param_type)

    def _refresh_array_items_list(self):
        self._array_items_list.clear()
        for item in self._array_items:
            item_type = self._array_item_type_combo.currentData() or "string"
            item_text = "" if item is None else str(item)
            display_text = os.path.basename(item_text) if item_type == "image" and item_text else item_text
            list_item = QListWidgetItem(display_text or item_text)
            list_item.setToolTip(str(item))
            self._array_items_list.addItem(list_item)

    @staticmethod
    def _pick_image_file(parent, current_value: str = "") -> str:
        start_path = ""
        if current_value:
            normalized = os.path.normpath(current_value)
            if os.path.isfile(normalized):
                start_path = normalized
            else:
                folder = os.path.dirname(normalized)
                if folder and os.path.isdir(folder):
                    start_path = folder
        file_path, _ = QFileDialog.getOpenFileName(
            parent,
            "选择图像文件",
            start_path,
            "图像文件 (*.png *.jpg *.jpeg *.bmp);;所有文件 (*.*)",
        )
        return file_path

    @staticmethod
    def _pick_image_files(parent) -> List[str]:
        file_paths, _ = QFileDialog.getOpenFileNames(
            parent,
            "选择图像文件",
            "",
            "图像文件 (*.png *.jpg *.jpeg *.bmp);;所有文件 (*.*)",
        )
        return file_paths

    def _update_array_tip_label(self):
        item_type = self._array_item_type_combo.currentData() or "string"
        if item_type == "image":
            tip_text = "支持逐项选择图片，也支持批量多选导入图像文件"
        elif item_type == "int":
            tip_text = "支持逐项添加，也支持按英文逗号、中文逗号、分号或换行批量添加整数"
        else:
            tip_text = "支持逐项添加，也支持按英文逗号、中文逗号、分号或换行批量添加"
        self._array_tip_label.setText(tip_text)

    def _coerce_array_input_value(self, raw_value, array_item_type: Optional[str] = None):
        item_type = array_item_type or self._array_item_type_combo.currentData() or "string"
        if item_type == "string":
            text = str(raw_value).strip() if raw_value is not None else ""
            if not text:
                raise ValueError("文本数组项不能为空")
            return text
        if item_type == "image":
            text = str(raw_value).strip() if raw_value is not None else ""
            if not text:
                raise ValueError("图像路径数组项不能为空")
            return text
        try:
            return coerce_array_item_value(item_type, raw_value)
        except (TypeError, ValueError):
            raise ValueError(f"'{raw_value}' 不是有效的整数")

    def _on_array_item_type_changed(self, index=0):
        del index
        new_type = self._array_item_type_combo.currentData() or "string"
        if not self._array_items:
            self._last_array_item_type = new_type
            return

        converted_items = []
        invalid_items = []
        for item in self._array_items:
            try:
                converted_items.append(self._coerce_array_input_value(item, new_type))
            except ValueError:
                invalid_items.append(str(item))

        if invalid_items:
            QMessageBox.warning(
                self,
                "提示",
                "当前数组中有值无法转换为该类型:\n" + "\n".join(invalid_items[:10]),
            )
            old_type = self._last_array_item_type or "string"
            self._array_item_type_combo.blockSignals(True)
            old_idx = self._array_item_type_combo.findData(old_type)
            self._array_item_type_combo.setCurrentIndex(old_idx if old_idx >= 0 else 0)
            self._array_item_type_combo.blockSignals(False)
            return

        self._array_items = converted_items
        self._last_array_item_type = new_type
        self._refresh_array_items_list()
        self._update_array_tip_label()

    def _add_array_item(self):
        item_type = self._array_item_type_combo.currentData() or "string"
        if item_type == "int":
            value, ok = QInputDialog.getInt(self, "添加数组项", "请输入整数值:", 0, -999999999, 999999999, 1)
            if not ok:
                return
            parsed_value = value
        elif item_type == "image":
            selected_path = self._pick_image_file(self)
            if not selected_path:
                return
            parsed_value = self._coerce_array_input_value(selected_path, item_type)
        else:
            text, ok = QInputDialog.getText(self, "添加数组项", "请输入文本值:")
            if not ok:
                return
            try:
                parsed_value = self._coerce_array_input_value(text, item_type)
            except ValueError as exc:
                QMessageBox.warning(self, "提示", str(exc))
                return

        self._array_items.append(parsed_value)
        self._refresh_array_items_list()
        self._array_items_list.setCurrentRow(len(self._array_items) - 1)

    def _edit_array_item(self, item=None):
        if item is not None:
            row = self._array_items_list.row(item)
        else:
            row = self._array_items_list.currentRow()
        if row < 0 or row >= len(self._array_items):
            return

        item_type = self._array_item_type_combo.currentData() or "string"
        current_value = self._array_items[row]
        if item_type == "int":
            value, ok = QInputDialog.getInt(
                self,
                "编辑数组项",
                "请输入整数值:",
                int(current_value),
                -999999999,
                999999999,
                1,
            )
            if not ok:
                return
            parsed_value = value
        elif item_type == "image":
            selected_path = self._pick_image_file(self, str(current_value))
            if not selected_path:
                return
            parsed_value = self._coerce_array_input_value(selected_path, item_type)
        else:
            text, ok = QInputDialog.getText(self, "编辑数组项", "请输入文本值:", text=str(current_value))
            if not ok:
                return
            try:
                parsed_value = self._coerce_array_input_value(text, item_type)
            except ValueError as exc:
                QMessageBox.warning(self, "提示", str(exc))
                return

        self._array_items[row] = parsed_value
        self._refresh_array_items_list()
        self._array_items_list.setCurrentRow(row)

    def _del_array_item(self):
        row = self._array_items_list.currentRow()
        if row < 0 or row >= len(self._array_items):
            return
        self._array_items.pop(row)
        self._refresh_array_items_list()
        if self._array_items:
            self._array_items_list.setCurrentRow(min(row, len(self._array_items) - 1))

    def _batch_add_array_items(self):
        item_type = self._array_item_type_combo.currentData() or "string"
        if item_type == "image":
            file_paths = self._pick_image_files(self)
            if not file_paths:
                return
            parsed_items = [self._coerce_array_input_value(path, item_type) for path in file_paths]
            self._array_items.extend(parsed_items)
            self._refresh_array_items_list()
            self._array_items_list.setCurrentRow(len(self._array_items) - 1)
            return

        hint = "请输入多个值，支持用英文逗号、中文逗号、分号或换行分隔。"
        raw_text, ok = QInputDialog.getMultiLineText(self, "批量添加数组项", hint)
        if not ok:
            return

        tokens = [token.strip() for token in re.split(r"[,，;；\n\r]+", raw_text) if token.strip()]
        if not tokens:
            QMessageBox.warning(self, "提示", "请至少输入一个有效值")
            return

        parsed_items = []
        invalid_items = []
        for token in tokens:
            try:
                parsed_items.append(self._coerce_array_input_value(token, item_type))
            except ValueError:
                invalid_items.append(token)

        if invalid_items:
            QMessageBox.warning(
                self,
                "格式错误",
                "以下值格式不正确，请检查后重试:\n" + "\n".join(invalid_items[:10]),
            )
            return

        self._array_items.extend(parsed_items)
        self._refresh_array_items_list()
        self._array_items_list.setCurrentRow(len(self._array_items) - 1)

    def _refresh_struct_editor(self):
        current_values = {}
        for row in range(self._struct_table.rowCount()):
            field_item = self._struct_table.item(row, 0)
            value_item = self._struct_table.item(row, 2)
            if field_item:
                current_values[field_item.text()] = value_item.text() if value_item else ""

        param_type = self._type_combo.currentData()
        struct_name = get_struct_name_from_type(param_type)
        struct_def = self._task.get_struct_def(struct_name) if hasattr(self._task, "get_struct_def") else None
        fields = struct_def.fields if struct_def else []

        self._struct_table.setRowCount(0)
        for field_def in fields:
            row = self._struct_table.rowCount()
            self._struct_table.insertRow(row)
            field_item = QTableWidgetItem(field_def.name)
            field_item.setFlags(field_item.flags() & ~Qt.ItemIsEditable)
            self._struct_table.setItem(row, 0, field_item)
            type_item = QTableWidgetItem(STRUCT_FIELD_TYPE_LABELS.get(field_def.field_type, field_def.field_type))
            type_item.setFlags(type_item.flags() & ~Qt.ItemIsEditable)
            self._struct_table.setItem(row, 1, type_item)
            self._struct_table.setItem(row, 2, QTableWidgetItem(current_values.get(field_def.name, "")))

    def _refresh_struct_array_table(self):
        param_type = self._type_combo.currentData()
        struct_name = get_struct_name_from_type(param_type)
        struct_def = self._task.get_struct_def(struct_name) if hasattr(self._task, "get_struct_def") else None
        fields = struct_def.fields if struct_def else []
        headers = [f"{field_def.name}\n{STRUCT_FIELD_TYPE_LABELS.get(field_def.field_type, field_def.field_type)}" for field_def in fields]
        self._struct_array_table.clear()
        self._struct_array_table.setColumnCount(len(headers))
        self._struct_array_table.setHorizontalHeaderLabels(headers)
        for col in range(len(headers)):
            self._struct_array_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Stretch)

        normalized_items = [_normalize_struct_item(struct_def, item) for item in self._struct_array_items if isinstance(item, dict)]
        self._struct_array_items = normalized_items
        self._struct_array_table.setRowCount(len(normalized_items))
        for row, item in enumerate(normalized_items):
            for col, field_def in enumerate(fields):
                value = item.get(field_def.name, field_def.default_value())
                self._struct_array_table.setItem(row, col, QTableWidgetItem(str(value)))

    def _add_struct_array_item(self):
        struct_name = get_struct_name_from_type(self._type_combo.currentData())
        struct_def = self._task.get_struct_def(struct_name) if hasattr(self._task, "get_struct_def") else None
        if not struct_def:
            return
        dlg = StructValueEditDialog(struct_def, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._struct_array_items.append(dlg.get_value())
            self._refresh_struct_array_table()

    def _edit_struct_array_item(self):
        row = self._struct_array_table.currentRow()
        if row < 0 or row >= len(self._struct_array_items):
            return
        struct_name = get_struct_name_from_type(self._type_combo.currentData())
        struct_def = self._task.get_struct_def(struct_name) if hasattr(self._task, "get_struct_def") else None
        if not struct_def:
            return
        dlg = StructValueEditDialog(struct_def, value=self._struct_array_items[row], parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._struct_array_items[row] = dlg.get_value()
            self._refresh_struct_array_table()
            self._struct_array_table.setCurrentCell(row, 0)

    def _del_struct_array_item(self):
        row = self._struct_array_table.currentRow()
        if row < 0 or row >= len(self._struct_array_items):
            return
        self._struct_array_items.pop(row)
        self._refresh_struct_array_table()

    def _on_type_changed(self, index=0):
        param_type = self._type_combo.currentData()
        self._text_label.setVisible(param_type == "text")
        self._text_edit.setVisible(param_type == "text")
        self._coord_label.setVisible(param_type == "coordinate")
        self._coord_x_spin.setVisible(param_type == "coordinate")
        self._coord_y_spin.setVisible(param_type == "coordinate")
        self._img_label.setVisible(param_type == "image")
        self._img_edit.setVisible(param_type == "image")
        self._img_browse_btn.setVisible(param_type == "image")
        self._array_label.setVisible(param_type == "array")
        self._array_item_type_label.setVisible(param_type == "array")
        self._array_item_type_combo.setVisible(param_type == "array")
        self._array_items_list.setVisible(param_type == "array")
        self._array_add_btn.setVisible(param_type == "array")
        self._array_edit_btn.setVisible(param_type == "array")
        self._array_del_btn.setVisible(param_type == "array")
        self._array_batch_btn.setVisible(param_type == "array")
        self._array_tip_label.setVisible(param_type == "array")
        self._coord_array_label.setVisible(param_type == "coord_array")
        self._coord_array_edit.setVisible(param_type == "coord_array")
        self._struct_label.setVisible(is_struct_param_type(param_type))
        self._struct_table.setVisible(is_struct_param_type(param_type))
        self._struct_array_label.setVisible(is_struct_array_param_type(param_type))
        self._struct_array_table.setVisible(is_struct_array_param_type(param_type))
        self._struct_array_add_btn.setVisible(is_struct_array_param_type(param_type))
        self._struct_array_edit_btn.setVisible(is_struct_array_param_type(param_type))
        self._struct_array_del_btn.setVisible(is_struct_array_param_type(param_type))
        self._update_array_tip_label()
        self._refresh_struct_editor()
        self._refresh_struct_array_table()

    def _load_data(self):
        param = self._param
        self._name_edit.setText(param.name)
        idx = self._type_combo.findData(param.param_type)
        if idx >= 0:
            self._type_combo.setCurrentIndex(idx)

        if param.param_type == "text":
            self._text_edit.setText(str(param.value) if param.value else "")
        elif param.param_type == "coordinate" and isinstance(param.value, dict):
            self._coord_x_spin.setValue(param.value.get("x", 0))
            self._coord_y_spin.setValue(param.value.get("y", 0))
        elif param.param_type == "image":
            self._img_edit.setText(str(param.value) if param.value else "")
        elif param.param_type == "array" and isinstance(param.value, list):
            type_idx = self._array_item_type_combo.findData(param.array_item_type)
            self._array_item_type_combo.setCurrentIndex(type_idx if type_idx >= 0 else 0)
            self._array_items = normalize_array_items(param.value, param.array_item_type)
            self._last_array_item_type = param.array_item_type or "string"
            self._refresh_array_items_list()
        elif param.param_type == "coord_array" and isinstance(param.value, list):
            lines = []
            for coord in param.value:
                if isinstance(coord, (list, tuple)) and len(coord) >= 2:
                    lines.append(f"{coord[0]},{coord[1]}")
            self._coord_array_edit.setPlainText("\n".join(lines))
        elif is_struct_param_type(param.param_type) and isinstance(param.value, dict):
            self._refresh_struct_editor()
            for row in range(self._struct_table.rowCount()):
                field_item = self._struct_table.item(row, 0)
                value_item = self._struct_table.item(row, 2)
                if field_item and value_item:
                    value = param.value.get(field_item.text(), "")
                    if isinstance(value, str):
                        value_item.setText(value)
                    else:
                        value_item.setText(json.dumps(value, ensure_ascii=False))
        elif is_struct_array_param_type(param.param_type) and isinstance(param.value, list):
            struct_def = self._task.get_struct_def(get_struct_name_from_type(param.param_type)) if hasattr(self._task, "get_struct_def") else None
            self._struct_array_items = [_normalize_struct_item(struct_def, item) for item in param.value if isinstance(item, dict)]

        self._persist_check.setChecked(param.persist)
        self._on_type_changed()

    def _browse_image(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "选择图像文件", "",
            "图像文件 (*.png *.jpg *.jpeg *.bmp);;所有文件 (*.*)"
        )
        if filepath:
            self._img_edit.setText(filepath)

    def _get_struct_value(self, param_type: str) -> dict:
        value = build_param_default_value(param_type, self._task.struct_defs)
        struct_def = self._task.get_struct_def(get_struct_name_from_type(param_type)) if hasattr(self._task, "get_struct_def") else None
        for row in range(self._struct_table.rowCount()):
            field_item = self._struct_table.item(row, 0)
            value_item = self._struct_table.item(row, 2)
            if not field_item:
                continue
            field_name = field_item.text()
            field_text = value_item.text().strip() if value_item else ""
            field_def = struct_def.get_field(field_name) if struct_def else None
            if field_text:
                parsed_value = _parse_loose_value(field_text)
                value[field_name] = _coerce_struct_field_value(field_def.field_type if field_def else "string", parsed_value)
            else:
                value[field_name] = field_def.default_value() if field_def else ""
        return value

    def _get_struct_array_value(self, param_type: str) -> list:
        struct_name = get_struct_name_from_type(param_type)
        struct_def = self._task.get_struct_def(struct_name) if hasattr(self._task, "get_struct_def") else None
        return [_normalize_struct_item(struct_def, item) for item in self._struct_array_items if isinstance(item, dict)]

    def _get_coord_array_value(self) -> list:
        value = []
        invalid_lines = []
        for line_no, line in enumerate(self._coord_array_edit.toPlainText().splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 2:
                invalid_lines.append(f"第 {line_no} 行: {line}")
                continue
            try:
                value.append([int(parts[0]), int(parts[1])])
            except ValueError:
                invalid_lines.append(f"第 {line_no} 行: {line}")
        if invalid_lines:
            raise ValueError("以下坐标格式不正确:\n" + "\n".join(invalid_lines[:10]))
        return value

    def _on_accept(self):
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入参数名称")
            return

        if self._type_combo.currentData() == "coord_array":
            try:
                self._get_coord_array_value()
            except ValueError as exc:
                QMessageBox.warning(self, "格式错误", str(exc))
                return

        self.accept()

    def get_param(self) -> TaskParameter:
        param_type = self._type_combo.currentData()
        name = self._name_edit.text().strip()
        array_item_type = self._array_item_type_combo.currentData() or "string"
        if param_type == "text":
            value = self._text_edit.text().strip()
        elif param_type == "coordinate":
            value = {"x": self._coord_x_spin.value(), "y": self._coord_y_spin.value()}
        elif param_type == "image":
            value = self._img_edit.text().strip()
        elif param_type == "array":
            value = list(self._array_items)
        elif param_type == "coord_array":
            value = self._get_coord_array_value()
        elif is_struct_param_type(param_type):
            value = self._get_struct_value(param_type)
        elif is_struct_array_param_type(param_type):
            value = self._get_struct_array_value(param_type)
        else:
            value = build_param_default_value(param_type, self._task.struct_defs)
        return TaskParameter(
            name=name,
            param_type=param_type,
            value=value,
            persist=self._persist_check.isChecked(),
            array_item_type=array_item_type,
        )


class MainActionEditDialog(QDialog):
    """主操作编辑对话框"""

    def __init__(self, action: dict = None, task_params: List[TaskParameter] = None,
                 task_steps: List[SingleTask] = None, task: PlanTask = None,
                 step_context: Optional[SingleTask] = None,
                 action_type_groups=None,
                 dialog_title: Optional[str] = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(dialog_title or ("编辑操作" if action else "新增操作"))
        self.setMinimumWidth(450)
        self._action = action or {}
        self._task = task
        self._task_params = task_params or []
        self._task_steps = task_steps or []
        self._step_context = copy.deepcopy(step_context) if step_context else SingleTask(recognition_type="none")
        self._action_type_groups = action_type_groups or MAIN_ACTION_TYPE_GROUPS
        self._temp_array_items = []
        self._result = None
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._action_type_combo = QComboBox()
        _populate_grouped_action_type_combo(self._action_type_combo, self._action_type_groups)
        self._action_type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("操作类型:", self._action_type_combo)

        self._delay_spin = QDoubleSpinBox()
        self._delay_spin.setRange(0.0, 6000.0)
        self._delay_spin.setSingleStep(0.1)
        self._delay_spin.setDecimals(2)
        self._delay_spin.setValue(0.0)
        self._delay_spin.setSuffix(" 秒")
        form.addRow("指令间延时:", self._delay_spin)

        self._highlight_duration_spin = QDoubleSpinBox()
        self._highlight_duration_spin.setRange(0.1, 60.0)
        self._highlight_duration_spin.setSingleStep(0.1)
        self._highlight_duration_spin.setDecimals(2)
        self._highlight_duration_spin.setValue(1.2)
        self._highlight_duration_spin.setSuffix(" 秒")
        self._highlight_duration_spin.setToolTip("红框或红点在屏幕上停留的时间")
        self._highlight_duration_label = QLabel("标记时长:")
        form.addRow(self._highlight_duration_label, self._highlight_duration_spin)

        self._highlight_show_ai_attributes = QCheckBox("在红框旁显示 AI 地块属性")
        self._highlight_show_ai_attributes.setToolTip("仅对 AI 地块识别结果生效，显示等级、类型和关系")
        self._highlight_show_ai_attributes_label = QLabel("AI属性显示:")
        form.addRow(self._highlight_show_ai_attributes_label, self._highlight_show_ai_attributes)

        self._point_position_mode = QComboBox()
        self._point_position_mode.addItem("识别结果坐标", "recognition")
        self._point_position_mode.addItem("目标窗口绝对坐标", "screen_absolute")
        self._point_position_mode.addItem("目标窗口百分比坐标", "screen_percent")
        self._point_position_mode.setToolTip(
            "识别结果坐标：使用当前步骤识别出的中心点，可配合坐标偏移\n"
            "目标窗口绝对坐标：直接填写相对目标窗口客户区左上角的像素坐标\n"
            "目标窗口百分比坐标：0.5, 0.5 表示目标窗口中心"
        )
        self._point_position_mode.currentIndexChanged.connect(self._update_point_position_mode_ui)
        self._point_position_mode_label = QLabel("坐标来源:")
        form.addRow(self._point_position_mode_label, self._point_position_mode)

        self._point_coord_widget = QWidget()
        point_coord_layout = QHBoxLayout(self._point_coord_widget)
        point_coord_layout.setContentsMargins(0, 0, 0, 0)
        point_coord_layout.addWidget(QLabel("X:"))
        self._point_x_spin = QDoubleSpinBox()
        self._point_x_spin.setValue(0.5)
        point_coord_layout.addWidget(self._point_x_spin)
        point_coord_layout.addWidget(QLabel("Y:"))
        self._point_y_spin = QDoubleSpinBox()
        self._point_y_spin.setValue(0.5)
        point_coord_layout.addWidget(self._point_y_spin)
        point_coord_layout.addStretch()
        self._point_coord_label = QLabel("窗口比例:")
        form.addRow(self._point_coord_label, self._point_coord_widget)
        _configure_point_coordinate_spins(self._point_x_spin, self._point_y_spin, "screen_percent")

        point_coord_ref_layout = QHBoxLayout()
        self._point_coord_ref_edit = QLineEdit()
        self._point_coord_ref_edit.setPlaceholderText("例如: {target_coord} 或 {target_coord.x},{target_coord.y}")
        self._point_coord_ref_edit.setToolTip("可填写变量或引用；填写后优先使用这里的坐标值，留空时使用上方 X/Y")
        point_coord_ref_layout.addWidget(self._point_coord_ref_edit)
        self._point_coord_ref_browse_btn = QPushButton("从参数选择")
        self._point_coord_ref_browse_btn.clicked.connect(self._browse_point_coord_reference)
        point_coord_ref_layout.addWidget(self._point_coord_ref_browse_btn)
        self._point_coord_ref_label = QLabel("坐标变量/引用:")
        form.addRow(self._point_coord_ref_label, point_coord_ref_layout)

        self._click_offset_mode = QComboBox()
        for mode_value, mode_label in CLICK_OFFSET_MODE_LABELS.items():
            self._click_offset_mode.addItem(mode_label, mode_value)
        self._click_offset_mode.setToolTip(
            "模板比例：按识别模板宽高计算偏移\n"
            "窗口像素：按目标窗口客户区像素计算偏移\n"
            "窗口比例：按目标窗口客户区宽高比例计算偏移"
        )
        self._click_offset_mode.currentIndexChanged.connect(self._update_point_position_mode_ui)
        self._click_offset_mode_label = QLabel("偏移单位:")
        form.addRow(self._click_offset_mode_label, self._click_offset_mode)

        click_offset_layout = QHBoxLayout()
        click_offset_layout.addWidget(QLabel("X:"))
        self._click_offset_x_spin = QDoubleSpinBox()
        self._click_offset_x_spin.setRange(-5.0, 5.0)
        self._click_offset_x_spin.setSingleStep(0.1)
        self._click_offset_x_spin.setDecimals(2)
        self._click_offset_x_spin.setValue(0.0)
        self._click_offset_x_spin.setToolTip(
            "基于匹配图像尺寸的比例偏移\n"
            "0=中心, 0.5=右边缘, -0.5=左边缘\n"
            "1.0=超出右边缘半个图像宽度"
        )
        click_offset_layout.addWidget(self._click_offset_x_spin)
        click_offset_layout.addWidget(QLabel("Y:"))
        self._click_offset_y_spin = QDoubleSpinBox()
        self._click_offset_y_spin.setRange(-10.0, 10.0)
        self._click_offset_y_spin.setSingleStep(0.1)
        self._click_offset_y_spin.setDecimals(2)
        self._click_offset_y_spin.setValue(0.0)
        self._click_offset_y_spin.setToolTip(
            "基于匹配图像尺寸的比例偏移\n"
            "0=中心, 0.5=下边缘, -0.5=上边缘"
        )
        click_offset_layout.addWidget(self._click_offset_y_spin)
        self._click_offset_label = QLabel("偏移值:")
        form.addRow(self._click_offset_label, click_offset_layout)

        self._click_offset_hint_label = QLabel(CLICK_OFFSET_HINT_TEXT)
        self._click_offset_hint_label.setWordWrap(True)
        self._click_offset_hint_label.setStyleSheet("color: #666666;")
        form.addRow("", self._click_offset_hint_label)

        input_text_layout = QHBoxLayout()
        self._input_text_edit = QLineEdit()
        self._input_text_edit.setPlaceholderText("输入要填写的文本内容，如: 990 或 {param}")
        input_text_layout.addWidget(self._input_text_edit)
        self._input_text_browse_btn = QPushButton("从参数选择")
        self._input_text_browse_btn.clicked.connect(self._browse_input_text_param)
        input_text_layout.addWidget(self._input_text_browse_btn)
        self._input_text_label = QLabel("输入内容:")
        form.addRow(self._input_text_label, input_text_layout)

        self._clear_method = QComboBox()
        self._clear_method.addItem("Delete+Backspace 逐个删除", "delete_backspace")
        self._clear_method.addItem("Ctrl+A 全选覆盖", "ctrl_a")
        self._clear_method.addItem("不清除（直接追加输入）", "none")
        self._clear_method.currentIndexChanged.connect(self._on_clear_method_changed)
        self._clear_method_label = QLabel("清除方式:")
        form.addRow(self._clear_method_label, self._clear_method)

        self._clear_key_count_spin = QSpinBox()
        self._clear_key_count_spin.setRange(1, 50)
        self._clear_key_count_spin.setValue(3)
        self._clear_key_count_spin.setToolTip("Delete 和 Backspace 各按这么多次，确保完全清空输入框")
        self._clear_key_count_label = QLabel("删除次数:")
        form.addRow(self._clear_key_count_label, self._clear_key_count_spin)

        self._press_keys_edit = QLineEdit()
        self._press_keys_edit.setPlaceholderText("例如: enter, ctrl+a, tab, escape")
        self._press_keys_edit.setToolTip(
            "单键: enter, tab, escape, space, backspace, delete\n"
            "组合键: ctrl+a, ctrl+c, alt+f4\n"
            "多个按键用逗号分隔: ctrl+a, delete"
        )
        self._press_keys_label = QLabel("按键内容:")
        form.addRow(self._press_keys_label, self._press_keys_edit)

        self._drag_coordinate_mode = QComboBox()
        self._drag_coordinate_mode.addItem("游戏逻辑坐标偏移", "game_logic")
        self._drag_coordinate_mode.addItem("屏幕坐标偏移", "screen")
        self._drag_coordinate_mode.currentIndexChanged.connect(self._update_drag_coordinate_mode_ui)
        self._drag_coordinate_mode_label = QLabel("拖动坐标系:")
        form.addRow(self._drag_coordinate_mode_label, self._drag_coordinate_mode)

        self._drag_start_mode = QComboBox()
        self._drag_start_mode.addItem("识别结果中心点", "recognition")
        self._drag_start_mode.addItem("目标窗口百分比坐标", "screen_percent")
        self._drag_start_mode.setToolTip(
            "默认使用识别结果中心点作为拖动起点\n"
            "切换到目标窗口百分比后，可按目标窗口客户区宽高比例指定起点，例如 0.5, 0.5 表示窗口中心"
        )
        self._drag_start_mode.currentIndexChanged.connect(self._update_drag_start_mode_ui)
        self._drag_start_mode_label = QLabel("拖动起点:")
        form.addRow(self._drag_start_mode_label, self._drag_start_mode)

        self._drag_start_coord_widget = QWidget()
        drag_start_coord_layout = QHBoxLayout(self._drag_start_coord_widget)
        drag_start_coord_layout.setContentsMargins(0, 0, 0, 0)
        drag_start_coord_layout.addWidget(QLabel("X:"))
        self._drag_start_x_spin = QDoubleSpinBox()
        self._drag_start_x_spin.setRange(0.0, 1.0)
        self._drag_start_x_spin.setSingleStep(0.05)
        self._drag_start_x_spin.setDecimals(3)
        self._drag_start_x_spin.setValue(0.5)
        drag_start_coord_layout.addWidget(self._drag_start_x_spin)
        drag_start_coord_layout.addWidget(QLabel("Y:"))
        self._drag_start_y_spin = QDoubleSpinBox()
        self._drag_start_y_spin.setRange(0.0, 1.0)
        self._drag_start_y_spin.setSingleStep(0.05)
        self._drag_start_y_spin.setDecimals(3)
        self._drag_start_y_spin.setValue(0.5)
        drag_start_coord_layout.addWidget(self._drag_start_y_spin)
        drag_start_coord_layout.addStretch()
        self._drag_start_coord_label = QLabel("窗口比例:")
        form.addRow(self._drag_start_coord_label, self._drag_start_coord_widget)

        self._drag_vector_mode = QComboBox()
        self._drag_vector_mode.addItem("像素", "pixel")
        self._drag_vector_mode.addItem("屏幕百分比", "screen_percent")
        self._drag_vector_mode.currentIndexChanged.connect(self._update_drag_vector_mode_ui)
        self._drag_vector_mode_label = QLabel("向量单位:")
        form.addRow(self._drag_vector_mode_label, self._drag_vector_mode)

        self._drag_vector_widget = QWidget()
        drag_vector_layout = QHBoxLayout(self._drag_vector_widget)
        drag_vector_layout.setContentsMargins(0, 0, 0, 0)
        drag_vector_layout.addWidget(QLabel("X:"))
        self._drag_vector_x_spin = QDoubleSpinBox()
        self._drag_vector_x_spin.setRange(-5000.0, 5000.0)
        self._drag_vector_x_spin.setSingleStep(10.0)
        self._drag_vector_x_spin.setDecimals(3)
        self._drag_vector_x_spin.setValue(0.0)
        drag_vector_layout.addWidget(self._drag_vector_x_spin)
        drag_vector_layout.addWidget(QLabel("Y:"))
        self._drag_vector_y_spin = QDoubleSpinBox()
        self._drag_vector_y_spin.setRange(-5000.0, 5000.0)
        self._drag_vector_y_spin.setSingleStep(10.0)
        self._drag_vector_y_spin.setDecimals(3)
        self._drag_vector_y_spin.setValue(0.0)
        drag_vector_layout.addWidget(self._drag_vector_y_spin)
        drag_vector_layout.addStretch()
        self._drag_vector_label = QLabel("拖动向量:")
        form.addRow(self._drag_vector_label, self._drag_vector_widget)

        drag_dir_layout = QHBoxLayout()
        drag_dir_layout.addWidget(QLabel("X:"))
        self._drag_dir_x_spin = QSpinBox()
        self._drag_dir_x_spin.setRange(-10, 10)
        drag_dir_layout.addWidget(self._drag_dir_x_spin)
        drag_dir_layout.addWidget(QLabel("Y:"))
        self._drag_dir_y_spin = QSpinBox()
        self._drag_dir_y_spin.setRange(-10, 10)
        drag_dir_layout.addWidget(self._drag_dir_y_spin)
        drag_dir_layout.addStretch()
        self._drag_dir_label = QLabel("拖动方向:")
        form.addRow(self._drag_dir_label, drag_dir_layout)

        self._drag_distance_spin = QSpinBox()
        self._drag_distance_spin.setRange(10, 2000)
        self._drag_distance_spin.setValue(200)
        self._drag_distance_spin.setSuffix(" 像素")
        self._drag_distance_label = QLabel("拖动距离:")
        form.addRow(self._drag_distance_label, self._drag_distance_spin)

        self._drag_duration_spin = QDoubleSpinBox()
        self._drag_duration_spin.setRange(0.1, 5.0)
        self._drag_duration_spin.setSingleStep(0.1)
        self._drag_duration_spin.setValue(0.3)
        self._drag_duration_spin.setSuffix(" 秒")
        self._drag_duration_label = QLabel("拖动时长:")
        form.addRow(self._drag_duration_label, self._drag_duration_spin)

        self._drag_center_tolerance_spin = QSpinBox()
        self._drag_center_tolerance_spin.setRange(1, 200)
        self._drag_center_tolerance_spin.setValue(1)
        self._drag_center_tolerance_spin.setSuffix(" 像素")
        self._drag_center_tolerance_spin.setToolTip("拖动到中心时允许保留的最大误差，值越小校正次数越多，最小 1 像素")
        self._drag_center_tolerance_label = QLabel("允许误差:")
        form.addRow(self._drag_center_tolerance_label, self._drag_center_tolerance_spin)
        self._update_point_position_mode_ui()
        self._update_drag_start_mode_ui()
        self._update_drag_vector_mode_ui()
        self._update_drag_coordinate_mode_ui()

        modify_var_layout = QHBoxLayout()
        self._modify_var_name_edit = QLineEdit()
        self._modify_var_name_edit.setPlaceholderText("变量名（如: counter 或 info.level）")
        modify_var_layout.addWidget(self._modify_var_name_edit)
        self._modify_var_browse_btn = QPushButton("从参数选择")
        self._modify_var_browse_btn.clicked.connect(self._browse_variable_name)
        modify_var_layout.addWidget(self._modify_var_browse_btn)
        self._modify_var_name_label = QLabel("变量名:")
        form.addRow(self._modify_var_name_label, modify_var_layout)

        modify_var_value_layout = QHBoxLayout()
        self._modify_var_value_edit = QLineEdit()
        self._modify_var_value_edit.setPlaceholderText("新值（支持 {参数} 替换）")
        modify_var_value_layout.addWidget(self._modify_var_value_edit)
        self._modify_var_value_browse_btn = QPushButton("从参数选择")
        self._modify_var_value_browse_btn.clicked.connect(self._browse_modify_value)
        modify_var_value_layout.addWidget(self._modify_var_value_browse_btn)
        self._modify_var_value_label = QLabel("变量值:")
        form.addRow(self._modify_var_value_label, modify_var_value_layout)

        self._arr_items_label = QLabel("数组项目:")
        arr_items_layout = QVBoxLayout()
        self._arr_items_list = QListWidget()
        self._arr_items_list.setMaximumHeight(100)
        arr_items_layout.addWidget(self._arr_items_list)
        arr_btn_row = QHBoxLayout()
        self._arr_item_add_btn = QPushButton("添加项")
        self._arr_item_add_btn.clicked.connect(self._add_array_item)
        arr_btn_row.addWidget(self._arr_item_add_btn)
        self._arr_item_del_btn = QPushButton("删除项")
        self._arr_item_del_btn.clicked.connect(self._del_array_item)
        arr_btn_row.addWidget(self._arr_item_del_btn)
        arr_btn_row.addStretch()
        arr_items_layout.addLayout(arr_btn_row)
        form.addRow(self._arr_items_label, arr_items_layout)

        save_recognition_array_layout = QHBoxLayout()
        self._save_recognition_result_array_edit = QLineEdit()
        self._save_recognition_result_array_edit.setPlaceholderText("结果坐标数组参数名")
        save_recognition_array_layout.addWidget(self._save_recognition_result_array_edit)
        self._save_recognition_result_array_browse_btn = QPushButton("从参数选择")
        self._save_recognition_result_array_browse_btn.clicked.connect(
            lambda: self._browse_param_name(self._save_recognition_result_array_edit, "coord_array")
        )
        save_recognition_array_layout.addWidget(self._save_recognition_result_array_browse_btn)
        self._save_recognition_result_array_label = QLabel("结果数组:")
        form.addRow(self._save_recognition_result_array_label, save_recognition_array_layout)

        remove_coord_source_layout = QHBoxLayout()
        self._remove_coord_source_array_edit = QLineEdit()
        self._remove_coord_source_array_edit.setPlaceholderText("源坐标数组参数名")
        remove_coord_source_layout.addWidget(self._remove_coord_source_array_edit)
        self._remove_coord_source_array_browse_btn = QPushButton("从参数选择")
        self._remove_coord_source_array_browse_btn.clicked.connect(
            lambda: self._browse_param_name(self._remove_coord_source_array_edit, "coord_array")
        )
        remove_coord_source_layout.addWidget(self._remove_coord_source_array_browse_btn)
        self._remove_coord_source_array_label = QLabel("源坐标数组:")
        form.addRow(self._remove_coord_source_array_label, remove_coord_source_layout)

        self._remove_coord_mode_combo = QComboBox()
        _populate_remove_coord_mode_combo(self._remove_coord_mode_combo)
        self._remove_coord_mode_combo.currentIndexChanged.connect(self._on_remove_coord_mode_changed)
        self._remove_coord_mode_label = QLabel("删除模式:")
        form.addRow(self._remove_coord_mode_label, self._remove_coord_mode_combo)

        remove_coord_target_layout = QHBoxLayout()
        self._remove_coord_target_value_edit = QLineEdit()
        remove_coord_target_layout.addWidget(self._remove_coord_target_value_edit)
        self._remove_coord_target_value_browse_btn = QPushButton("从参数选择")
        self._remove_coord_target_value_browse_btn.clicked.connect(self._browse_remove_coord_target_value)
        remove_coord_target_layout.addWidget(self._remove_coord_target_value_browse_btn)
        self._remove_coord_target_value_label = QLabel("待删除坐标:")
        form.addRow(self._remove_coord_target_value_label, remove_coord_target_layout)
        _configure_remove_coord_target_editor(
            self._remove_coord_target_value_label,
            self._remove_coord_target_value_edit,
            self._remove_coord_mode_combo.currentData() or "single",
        )

        clear_array_layout = QHBoxLayout()
        self._clear_array_edit = QLineEdit()
        self._clear_array_edit.setPlaceholderText("目标数组参数名")
        clear_array_layout.addWidget(self._clear_array_edit)
        self._clear_array_browse_btn = QPushButton("从参数选择")
        self._clear_array_browse_btn.clicked.connect(self._browse_clear_array_param)
        clear_array_layout.addWidget(self._clear_array_browse_btn)
        self._clear_array_label = QLabel("目标数组:")
        form.addRow(self._clear_array_label, clear_array_layout)

        recognition_logic_csv_layout = QHBoxLayout()
        self._recognition_to_logic_csv_edit = QLineEdit()
        self._recognition_to_logic_csv_edit.setPlaceholderText("坐标转换导出的 CSV 文件路径")
        recognition_logic_csv_layout.addWidget(self._recognition_to_logic_csv_edit)
        self._recognition_to_logic_csv_browse_btn = QPushButton("浏览文件")
        self._recognition_to_logic_csv_browse_btn.clicked.connect(self._browse_recognition_to_logic_csv)
        recognition_logic_csv_layout.addWidget(self._recognition_to_logic_csv_browse_btn)
        self._recognition_to_logic_csv_label = QLabel("坐标 CSV:")
        form.addRow(self._recognition_to_logic_csv_label, recognition_logic_csv_layout)

        recognition_logic_anchor_layout = QHBoxLayout()
        self._recognition_to_logic_anchor_logical_edit = QLineEdit()
        self._recognition_to_logic_anchor_logical_edit.setPlaceholderText(
            "例如: 100,200 或 {anchor_coord.x},{anchor_coord.y}"
        )
        recognition_logic_anchor_layout.addWidget(self._recognition_to_logic_anchor_logical_edit)
        self._recognition_to_logic_anchor_logical_browse_btn = QPushButton("从参数选择")
        self._recognition_to_logic_anchor_logical_browse_btn.clicked.connect(
            lambda: self._browse_value_reference(self._recognition_to_logic_anchor_logical_edit, allow_coordinate_full=True)
        )
        recognition_logic_anchor_layout.addWidget(self._recognition_to_logic_anchor_logical_browse_btn)
        self._recognition_to_logic_anchor_logical_label = QLabel("锚点逻辑坐标:")
        form.addRow(self._recognition_to_logic_anchor_logical_label, recognition_logic_anchor_layout)

        recognition_screen_anchor_layout = QHBoxLayout()
        self._recognition_to_logic_anchor_screen_edit = QLineEdit()
        self._recognition_to_logic_anchor_screen_edit.setPlaceholderText(
            "例如: 0.532,0.418 或 {anchor_screen}"
        )
        recognition_screen_anchor_layout.addWidget(self._recognition_to_logic_anchor_screen_edit)
        self._recognition_to_logic_anchor_screen_browse_btn = QPushButton("从参数选择")
        self._recognition_to_logic_anchor_screen_browse_btn.clicked.connect(
            lambda: self._browse_value_reference(self._recognition_to_logic_anchor_screen_edit, allow_coordinate_full=True)
        )
        recognition_screen_anchor_layout.addWidget(self._recognition_to_logic_anchor_screen_browse_btn)
        self._recognition_to_logic_anchor_screen_label = QLabel("锚点屏幕相对坐标:")
        form.addRow(self._recognition_to_logic_anchor_screen_label, recognition_screen_anchor_layout)

        recognition_result_array_layout = QHBoxLayout()
        self._recognition_to_logic_result_array_edit = QLineEdit()
        self._recognition_to_logic_result_array_edit.setPlaceholderText("结果坐标数组参数名")
        recognition_result_array_layout.addWidget(self._recognition_to_logic_result_array_edit)
        self._recognition_to_logic_result_array_browse_btn = QPushButton("从参数选择")
        self._recognition_to_logic_result_array_browse_btn.clicked.connect(
            lambda: self._browse_param_name(self._recognition_to_logic_result_array_edit, "coord_array")
        )
        recognition_result_array_layout.addWidget(self._recognition_to_logic_result_array_browse_btn)
        self._recognition_to_logic_result_array_label = QLabel("结果数组:")
        form.addRow(self._recognition_to_logic_result_array_label, recognition_result_array_layout)

        recognition_preview_button_layout = QHBoxLayout()
        self._recognition_to_logic_preview_btn = QPushButton("即时预览转换结果")
        self._recognition_to_logic_preview_btn.clicked.connect(self._preview_recognition_to_logic)
        recognition_preview_button_layout.addWidget(self._recognition_to_logic_preview_btn)
        recognition_preview_button_layout.addStretch()
        self._recognition_to_logic_preview_button_label = QLabel("预览:")
        form.addRow(self._recognition_to_logic_preview_button_label, recognition_preview_button_layout)

        self._recognition_to_logic_preview_output = QTextEdit()
        self._recognition_to_logic_preview_output.setReadOnly(True)
        self._recognition_to_logic_preview_output.setMinimumHeight(140)
        self._recognition_to_logic_preview_output.setPlaceholderText("点击“即时预览转换结果”后，这里会显示识别与转换结果")
        self._recognition_to_logic_preview_output_label = QLabel("预览结果:")
        form.addRow(self._recognition_to_logic_preview_output_label, self._recognition_to_logic_preview_output)

        self._jump_target_combo = _JumpTargetPickerComboBox()
        self._populate_jump_targets()
        self._jump_target_combo.currentIndexChanged.connect(self._on_jump_target_changed)
        self._jump_target_label = QLabel("跳转目标:")
        form.addRow(self._jump_target_label, self._jump_target_combo)

        traverse_center_layout = QHBoxLayout()
        self._traverse_center_edit = QLineEdit()
        self._traverse_center_edit.setPlaceholderText("坐标参数名（如: base_coord）")
        traverse_center_layout.addWidget(self._traverse_center_edit)
        self._traverse_center_browse_btn = QPushButton("从参数选择")
        self._traverse_center_browse_btn.clicked.connect(
            lambda: self._browse_param_name(self._traverse_center_edit, "coordinate")
        )
        traverse_center_layout.addWidget(self._traverse_center_browse_btn)
        self._traverse_center_label = QLabel("中心坐标参数:")
        form.addRow(self._traverse_center_label, traverse_center_layout)

        traverse_array_layout = QHBoxLayout()
        self._traverse_array_edit = QLineEdit()
        self._traverse_array_edit.setPlaceholderText("目标坐标数组参数名")
        traverse_array_layout.addWidget(self._traverse_array_edit)
        self._traverse_array_browse_btn = QPushButton("从参数选择")
        self._traverse_array_browse_btn.clicked.connect(
            lambda: self._browse_param_name(self._traverse_array_edit, "coord_array")
        )
        traverse_array_layout.addWidget(self._traverse_array_browse_btn)
        self._traverse_array_label = QLabel("目标数组:")
        form.addRow(self._traverse_array_label, traverse_array_layout)

        self._traverse_count_spin = QSpinBox()
        self._traverse_count_spin.setRange(1, 100000)
        self._traverse_count_spin.setValue(1000)
        self._traverse_count_label = QLabel("遍历数量:")
        form.addRow(self._traverse_count_label, self._traverse_count_spin)

        self._traverse_mode_combo = QComboBox()
        _populate_grid_mode_combo(self._traverse_mode_combo)
        self._traverse_mode_label = QLabel("网格模式:")
        form.addRow(self._traverse_mode_label, self._traverse_mode_combo)

        two_ring_target_layout = QHBoxLayout()
        self._two_ring_target_coord_edit = QLineEdit()
        self._two_ring_target_coord_edit.setPlaceholderText("目标逻辑坐标参数名")
        two_ring_target_layout.addWidget(self._two_ring_target_coord_edit)
        self._two_ring_target_coord_browse_btn = QPushButton("从参数选择")
        self._two_ring_target_coord_browse_btn.clicked.connect(
            lambda: self._browse_param_name(self._two_ring_target_coord_edit, "coordinate")
        )
        two_ring_target_layout.addWidget(self._two_ring_target_coord_browse_btn)
        self._two_ring_target_coord_label = QLabel("目标坐标:")
        form.addRow(self._two_ring_target_coord_label, two_ring_target_layout)

        two_ring_result_layout = QHBoxLayout()
        self._two_ring_result_array_edit = QLineEdit()
        self._two_ring_result_array_edit.setPlaceholderText("周围坐标数组参数名")
        two_ring_result_layout.addWidget(self._two_ring_result_array_edit)
        self._two_ring_result_array_browse_btn = QPushButton("从参数选择")
        self._two_ring_result_array_browse_btn.clicked.connect(
            lambda: self._browse_param_name(self._two_ring_result_array_edit, "coord_array")
        )
        two_ring_result_layout.addWidget(self._two_ring_result_array_browse_btn)
        self._two_ring_result_array_label = QLabel("结果数组:")
        form.addRow(self._two_ring_result_array_label, two_ring_result_layout)

        self._surround_radius_spin = QSpinBox()
        self._surround_radius_spin.setRange(0, 100000)
        self._surround_radius_spin.setValue(2)
        self._surround_radius_label = QLabel("半径:")
        form.addRow(self._surround_radius_label, self._surround_radius_spin)

        self._surround_mode_combo = QComboBox()
        _populate_grid_mode_combo(self._surround_mode_combo)
        self._surround_mode_label = QLabel("网格模式:")
        form.addRow(self._surround_mode_label, self._surround_mode_combo)

        path_target_layout = QHBoxLayout()
        self._path_target_coord_edit = QLineEdit()
        self._path_target_coord_edit.setPlaceholderText("目标坐标参数名")
        path_target_layout.addWidget(self._path_target_coord_edit)
        self._path_target_coord_browse_btn = QPushButton("从参数选择")
        self._path_target_coord_browse_btn.clicked.connect(
            lambda: self._browse_param_name(self._path_target_coord_edit, "coordinate")
        )
        path_target_layout.addWidget(self._path_target_coord_browse_btn)
        self._path_target_coord_label = QLabel("目标坐标:")
        form.addRow(self._path_target_coord_label, path_target_layout)

        path_start_layout = QHBoxLayout()
        self._path_start_array_edit = QLineEdit()
        self._path_start_array_edit.setPlaceholderText("起始坐标数组参数名")
        path_start_layout.addWidget(self._path_start_array_edit)
        self._path_start_array_browse_btn = QPushButton("从参数选择")
        self._path_start_array_browse_btn.clicked.connect(
            lambda: self._browse_param_name(self._path_start_array_edit, "coord_array")
        )
        path_start_layout.addWidget(self._path_start_array_browse_btn)
        self._path_start_array_label = QLabel("起始数组:")
        form.addRow(self._path_start_array_label, path_start_layout)

        path_passable_layout = QHBoxLayout()
        self._path_passable_array_edit = QLineEdit()
        self._path_passable_array_edit.setPlaceholderText("可通行坐标数组参数名")
        path_passable_layout.addWidget(self._path_passable_array_edit)
        self._path_passable_array_browse_btn = QPushButton("从参数选择")
        self._path_passable_array_browse_btn.clicked.connect(
            lambda: self._browse_param_name(self._path_passable_array_edit, "coord_array")
        )
        path_passable_layout.addWidget(self._path_passable_array_browse_btn)
        self._path_passable_array_label = QLabel("可通行数组:")
        form.addRow(self._path_passable_array_label, path_passable_layout)

        path_result_layout = QHBoxLayout()
        self._path_result_array_edit = QLineEdit()
        self._path_result_array_edit.setPlaceholderText("结果坐标数组参数名")
        path_result_layout.addWidget(self._path_result_array_edit)
        self._path_result_array_browse_btn = QPushButton("从参数选择")
        self._path_result_array_browse_btn.clicked.connect(
            lambda: self._browse_param_name(self._path_result_array_edit, "coord_array")
        )
        path_result_layout.addWidget(self._path_result_array_browse_btn)
        self._path_result_array_label = QLabel("结果数组:")
        form.addRow(self._path_result_array_label, path_result_layout)

        self._path_mode_combo = QComboBox()
        _populate_grid_mode_combo(self._path_mode_combo)
        self._path_mode_label = QLabel("网格模式:")
        form.addRow(self._path_mode_label, self._path_mode_combo)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._on_type_changed()

    def _on_type_changed(self):
        action_type = _normalize_grid_action_type(self._action_type_combo.currentData())
        is_input_text = action_type == "input_text"
        is_press_key = action_type == "press_key"
        is_hold_left_button = action_type == "hold_left_button"
        is_highlight_match = action_type == "highlight_match"
        is_highlight_point = action_type == "highlight_point"
        is_drag_match_to_center = action_type == "drag_match_to_center"
        uses_highlight_duration = _action_uses_highlight_duration(action_type)
        is_drag_map = action_type == "drag_map"
        has_drag_duration = _action_uses_drag_duration(action_type)
        is_mark_blocked = action_type == "mark_blocked"
        is_modify_var = action_type == "modify_variable"
        is_add_array = action_type == "add_to_array"
        is_save_recognition_coords = action_type == "save_recognition_coords"
        is_remove_coords = action_type == "remove_target_coords"
        is_clear_array = action_type == "clear_array_data"
        is_recognition_to_logic = action_type == "recognition_to_logic_coord"
        is_jump = action_type == "jump_to_step"
        is_traverse = action_type == "traverse_grid"
        is_get_two_ring = action_type == "get_surrounding_coords"
        is_find_road_path = action_type == "find_road_path"
        uses_click_offset = _action_uses_click_offset(action_type)

        show_input = is_input_text or is_mark_blocked
        self._input_text_label.setVisible(show_input)
        self._input_text_edit.setVisible(show_input)
        self._input_text_browse_btn.setVisible(is_input_text)
        if is_mark_blocked:
            self._input_text_label.setText("封锁坐标:")
            self._input_text_edit.setPlaceholderText("格式: {x},{y}（支持参数替换）")
        else:
            self._input_text_label.setText("输入内容:")
            self._input_text_edit.setPlaceholderText("输入要填写的文本内容，如: 990 或 {param}")

        self._clear_method_label.setVisible(is_input_text)
        self._clear_method.setVisible(is_input_text)
        self._on_clear_method_changed()

        self._press_keys_label.setVisible(is_press_key)
        self._press_keys_edit.setVisible(is_press_key)

        self._highlight_duration_label.setVisible(uses_highlight_duration)
        self._highlight_duration_spin.setVisible(uses_highlight_duration)
        if is_highlight_match:
            self._highlight_duration_label.setText("红框时长:")
        elif is_highlight_point:
            self._highlight_duration_label.setText("红点时长:")
        self._highlight_show_ai_attributes_label.setVisible(is_highlight_match)
        self._highlight_show_ai_attributes.setVisible(is_highlight_match)

        uses_point_position = _action_uses_point_position_mode(action_type)
        point_mode = normalize_point_position_mode(self._point_position_mode.currentData() or "recognition")
        self._point_position_mode_label.setVisible(uses_point_position)
        self._point_position_mode.setVisible(uses_point_position)

        self._drag_coordinate_mode_label.setVisible(is_drag_map)
        self._drag_coordinate_mode.setVisible(is_drag_map)
        self._drag_start_mode_label.setVisible(is_drag_map)
        self._drag_start_mode.setVisible(is_drag_map)
        self._drag_vector_mode_label.setVisible(is_drag_map)
        self._drag_vector_mode.setVisible(is_drag_map)
        self._drag_vector_label.setVisible(is_drag_map)
        self._drag_vector_widget.setVisible(is_drag_map)
        self._drag_dir_label.setVisible(is_drag_map)
        self._drag_dir_x_spin.setVisible(is_drag_map)
        self._drag_dir_y_spin.setVisible(is_drag_map)
        self._drag_distance_label.setVisible(is_drag_map)
        self._drag_distance_spin.setVisible(is_drag_map)
        self._drag_duration_label.setVisible(has_drag_duration)
        self._drag_duration_spin.setVisible(has_drag_duration)
        if is_hold_left_button:
            self._drag_duration_label.setText("长按时长:")
            self._drag_duration_spin.setToolTip("按住鼠标左键后保持的时间，到时自动释放")
        else:
            self._drag_duration_label.setText("拖动时长:")
            self._drag_duration_spin.setToolTip("拖动动作的持续时间")
        self._drag_center_tolerance_label.setVisible(is_drag_match_to_center)
        self._drag_center_tolerance_spin.setVisible(is_drag_match_to_center)

        self._modify_var_name_label.setVisible(is_modify_var)
        self._modify_var_name_edit.setVisible(is_modify_var)
        self._modify_var_browse_btn.setVisible(is_modify_var)
        self._modify_var_value_label.setVisible(is_modify_var)
        self._modify_var_value_edit.setVisible(is_modify_var)
        self._modify_var_value_browse_btn.setVisible(is_modify_var)

        self._arr_items_label.setVisible(is_add_array)
        self._arr_items_list.setVisible(is_add_array)
        self._arr_item_add_btn.setVisible(is_add_array)
        self._arr_item_del_btn.setVisible(is_add_array)

        self._save_recognition_result_array_label.setVisible(is_save_recognition_coords)
        self._save_recognition_result_array_edit.setVisible(is_save_recognition_coords)
        self._save_recognition_result_array_browse_btn.setVisible(is_save_recognition_coords)

        self._remove_coord_source_array_label.setVisible(is_remove_coords)
        self._remove_coord_source_array_edit.setVisible(is_remove_coords)
        self._remove_coord_source_array_browse_btn.setVisible(is_remove_coords)
        self._remove_coord_mode_label.setVisible(is_remove_coords)
        self._remove_coord_mode_combo.setVisible(is_remove_coords)
        self._remove_coord_target_value_label.setVisible(is_remove_coords)
        self._remove_coord_target_value_edit.setVisible(is_remove_coords)
        self._remove_coord_target_value_browse_btn.setVisible(is_remove_coords)

        self._clear_array_label.setVisible(is_clear_array)
        self._clear_array_edit.setVisible(is_clear_array)
        self._clear_array_browse_btn.setVisible(is_clear_array)

        self._recognition_to_logic_csv_label.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_csv_edit.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_csv_browse_btn.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_anchor_logical_label.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_anchor_logical_edit.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_anchor_logical_browse_btn.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_anchor_screen_label.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_anchor_screen_edit.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_anchor_screen_browse_btn.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_result_array_label.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_result_array_edit.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_result_array_browse_btn.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_preview_button_label.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_preview_btn.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_preview_output_label.setVisible(is_recognition_to_logic)
        self._recognition_to_logic_preview_output.setVisible(is_recognition_to_logic)

        self._jump_target_label.setVisible(is_jump)
        self._jump_target_combo.setVisible(is_jump)

        uses_offset = uses_click_offset
        self._click_offset_mode_label.setVisible(uses_offset)
        self._click_offset_mode.setVisible(uses_offset)
        self._click_offset_label.setVisible(uses_offset)
        self._click_offset_x_spin.setVisible(uses_offset)
        self._click_offset_y_spin.setVisible(uses_offset)
        self._click_offset_hint_label.setVisible(uses_offset)

        self._traverse_center_label.setVisible(is_traverse)
        self._traverse_center_edit.setVisible(is_traverse)
        self._traverse_center_browse_btn.setVisible(is_traverse)
        self._traverse_array_label.setVisible(is_traverse)
        self._traverse_array_edit.setVisible(is_traverse)
        self._traverse_array_browse_btn.setVisible(is_traverse)
        self._traverse_count_label.setVisible(is_traverse)
        self._traverse_count_spin.setVisible(is_traverse)
        self._traverse_mode_label.setVisible(is_traverse)
        self._traverse_mode_combo.setVisible(is_traverse)

        self._two_ring_target_coord_label.setVisible(is_get_two_ring)
        self._two_ring_target_coord_edit.setVisible(is_get_two_ring)
        self._two_ring_target_coord_browse_btn.setVisible(is_get_two_ring)
        self._two_ring_result_array_label.setVisible(is_get_two_ring)
        self._two_ring_result_array_edit.setVisible(is_get_two_ring)
        self._two_ring_result_array_browse_btn.setVisible(is_get_two_ring)
        self._surround_radius_label.setVisible(is_get_two_ring)
        self._surround_radius_spin.setVisible(is_get_two_ring)
        self._surround_mode_label.setVisible(is_get_two_ring)
        self._surround_mode_combo.setVisible(is_get_two_ring)

        self._path_target_coord_label.setVisible(is_find_road_path)
        self._path_target_coord_edit.setVisible(is_find_road_path)
        self._path_target_coord_browse_btn.setVisible(is_find_road_path)
        self._path_start_array_label.setVisible(is_find_road_path)
        self._path_start_array_edit.setVisible(is_find_road_path)
        self._path_start_array_browse_btn.setVisible(is_find_road_path)
        self._path_passable_array_label.setVisible(is_find_road_path)
        self._path_passable_array_edit.setVisible(is_find_road_path)
        self._path_passable_array_browse_btn.setVisible(is_find_road_path)
        self._path_result_array_label.setVisible(is_find_road_path)
        self._path_result_array_edit.setVisible(is_find_road_path)
        self._path_result_array_browse_btn.setVisible(is_find_road_path)
        self._path_mode_label.setVisible(is_find_road_path)
        self._path_mode_combo.setVisible(is_find_road_path)
        self._update_point_position_mode_ui()
        self._update_drag_start_mode_ui()
        self._update_drag_coordinate_mode_ui()
        self._on_jump_target_changed()

    def _on_jump_target_changed(self, index=0):
        del index
        target_id = ""
        if self._action_type_combo.currentData() == "jump_to_step":
            target_id = self._jump_target_combo.currentData() or ""
        _set_jump_target_preview(self, target_id)

    def _on_clear_method_changed(self):
        show = self._action_type_combo.currentData() == "input_text" and self._clear_method.currentData() == "delete_backspace"
        self._clear_key_count_label.setVisible(show)
        self._clear_key_count_spin.setVisible(show)

    def _update_point_position_mode_ui(self, index=0):
        del index
        if not all(
            hasattr(self, attr)
            for attr in (
                "_action_type_combo",
                "_point_position_mode",
                "_point_coord_label",
                "_point_coord_widget",
                "_point_x_spin",
                "_point_y_spin",
                "_point_coord_ref_label",
                "_point_coord_ref_edit",
                "_point_coord_ref_browse_btn",
            )
        ):
            return

        action_type = self._action_type_combo.currentData()
        uses_point_position = _action_uses_point_position_mode(action_type)
        mode = normalize_point_position_mode(self._point_position_mode.currentData() or "recognition")
        _sync_click_offset_mode_combo_with_point_mode(self, mode if uses_point_position else "recognition")
        show_coords = uses_point_position and mode != "recognition"
        self._point_coord_label.setVisible(show_coords)
        self._point_coord_widget.setVisible(show_coords)
        self._point_coord_ref_label.setVisible(show_coords)
        self._point_coord_ref_edit.setVisible(show_coords)
        self._point_coord_ref_browse_btn.setVisible(show_coords)
        if hasattr(self, "_click_offset_label"):
            uses_offset = _action_uses_click_offset(action_type)
            self._click_offset_label.setVisible(uses_offset)
            self._click_offset_x_spin.setVisible(uses_offset)
            self._click_offset_y_spin.setVisible(uses_offset)
            self._click_offset_hint_label.setVisible(uses_offset)
            _configure_click_offset_spins(
                self._click_offset_x_spin,
                self._click_offset_y_spin,
                self._click_offset_mode.currentData() or get_default_click_offset_mode(mode if uses_point_position else "recognition"),
                self._click_offset_hint_label,
            )
        if not show_coords:
            return

        _configure_point_coordinate_spins(self._point_x_spin, self._point_y_spin, mode)
        if mode == "screen_percent":
            self._point_coord_label.setText("窗口比例:")
            self._point_coord_ref_edit.setPlaceholderText("例如: {ratio_pair} 或 {ratio_pair.x},{ratio_pair.y}")
        else:
            self._point_coord_label.setText("窗口坐标:")
            self._point_coord_ref_edit.setPlaceholderText("例如: {target_coord} 或 {target_coord.x},{target_coord.y}")
        self._point_coord_ref_edit.setToolTip("可填写变量或引用；填写后优先使用这里的坐标值，留空时使用上方 X/Y")

    def _update_drag_start_mode_ui(self, index=0):
        del index
        if not all(
            hasattr(self, attr)
            for attr in (
                "_action_type_combo",
                "_drag_start_mode",
                "_drag_start_coord_label",
                "_drag_start_coord_widget",
                "_drag_start_x_spin",
                "_drag_start_y_spin",
            )
        ):
            return
        is_drag_map = self._action_type_combo.currentData() == "drag_map"
        show_screen_ratio = is_drag_map and (self._drag_start_mode.currentData() == "screen_percent")
        self._drag_start_coord_label.setVisible(show_screen_ratio)
        self._drag_start_coord_widget.setVisible(show_screen_ratio)
        self._drag_start_x_spin.setToolTip("相对目标窗口客户区宽度的比例，例如 X=0.5 表示水平中心")
        self._drag_start_y_spin.setToolTip("相对目标窗口客户区高度的比例，例如 Y=0.5 表示垂直中心")
        self._drag_start_coord_widget.setToolTip("例如 0.5, 0.5 表示屏幕中心")
        self._drag_start_coord_label.setToolTip("例如 0.5, 0.5 表示屏幕中心")

    def _update_drag_vector_mode_ui(self, index=0):
        del index
        if not all(
            hasattr(self, attr)
            for attr in (
                "_drag_vector_mode",
                "_drag_vector_x_spin",
                "_drag_vector_y_spin",
                "_drag_vector_label",
            )
        ):
            return
        vector_mode = normalize_drag_vector_mode(self._drag_vector_mode.currentData() or "pixel")
        if vector_mode == "screen_percent":
            self._drag_vector_label.setText("拖动向量:")
            self._drag_vector_x_spin.setSingleStep(0.05)
            self._drag_vector_y_spin.setSingleStep(0.05)
            self._drag_vector_x_spin.setToolTip("相对整个屏幕宽度的拖动比例，例如 0.2 表示向右拖动 20% 屏幕宽度")
            self._drag_vector_y_spin.setToolTip("相对整个屏幕高度的拖动比例，例如 -0.1 表示向上拖动 10% 屏幕高度")
            self._drag_vector_mode.setToolTip("屏幕百分比向量：X/Y 同时表示方向和距离，按屏幕宽高比例计算")
        else:
            self._drag_vector_label.setText("拖动向量:")
            self._drag_vector_x_spin.setSingleStep(10.0)
            self._drag_vector_y_spin.setSingleStep(10.0)
            self._drag_vector_x_spin.setToolTip("屏幕像素向量 X，正数向右，负数向左")
            self._drag_vector_y_spin.setToolTip("屏幕像素向量 Y，正数向下，负数向上")
            self._drag_vector_mode.setToolTip("像素向量：X/Y 同时表示方向和距离，单位为屏幕像素")

    def _update_drag_coordinate_mode_ui(self, index=0):
        del index
        if not all(
            hasattr(self, attr)
            for attr in (
                "_action_type_combo",
                "_drag_coordinate_mode",
                "_drag_vector_mode_label",
                "_drag_vector_mode",
                "_drag_vector_label",
                "_drag_vector_widget",
                "_drag_dir_label",
                "_drag_dir_x_spin",
                "_drag_dir_y_spin",
                "_drag_distance_spin",
            )
        ):
            return
        is_drag_map = self._action_type_combo.currentData() == "drag_map"
        mode = self._drag_coordinate_mode.currentData() or "game_logic"
        show_screen_vector = is_drag_map and mode == "screen"
        show_game_logic = is_drag_map and mode != "screen"
        self._drag_vector_mode_label.setVisible(show_screen_vector)
        self._drag_vector_mode.setVisible(show_screen_vector)
        self._drag_vector_label.setVisible(show_screen_vector)
        self._drag_vector_widget.setVisible(show_screen_vector)
        self._drag_dir_label.setVisible(show_game_logic)
        self._drag_dir_x_spin.setVisible(show_game_logic)
        self._drag_dir_y_spin.setVisible(show_game_logic)
        self._drag_distance_label.setVisible(show_game_logic)
        self._drag_distance_spin.setVisible(show_game_logic)
        if mode == "screen":
            self._update_drag_vector_mode_ui()
        else:
            self._drag_dir_label.setText("拖动方向:")
            self._drag_dir_x_spin.setToolTip(
                "游戏地图X方向格数\n"
                "正数=镜头向X+方向移动（屏幕左下）\n"
                "负数=镜头向X-方向移动（屏幕右上）"
            )
            self._drag_dir_y_spin.setToolTip(
                "游戏地图Y方向格数\n"
                "正数=镜头向Y+方向移动（屏幕右下）\n"
                "负数=镜头向Y-方向移动（屏幕左上）"
            )
            self._drag_distance_spin.setToolTip("拖动的屏幕总像素距离（方向由等距坐标自动换算）")

    def _populate_jump_targets(self):
        self._jump_target_combo.set_task_steps(self._task_steps)

    def _browse_variable_name(self):
        param = _pick_task_param(
            self,
            self._task_params,
            "选择变量",
            "请选择一个变量或结构体字段:",
            task=self._task,
            empty_message="当前任务还没有定义参数",
        )
        if not param:
            return
        target = _choose_member_path(self, param, include_whole=True, wrap_reference=False, allow_coordinate_full=False)
        if target:
            self._modify_var_name_edit.setText(target)

    def _browse_modify_value(self):
        param = _pick_task_param(
            self,
            self._task_params,
            "选择参数",
            "请选择一个参数或字段作为新值:",
            task=self._task,
            empty_message="当前任务还没有定义参数",
        )
        if not param:
            return
        reference = _choose_member_path(self, param, include_whole=True, wrap_reference=True, allow_coordinate_full=False)
        if reference:
            self._modify_var_value_edit.setText(reference)

    def _browse_clear_array_param(self):
        param = _pick_array_task_param(
            self,
            self._task_params,
            task=self._task,
            empty_message="当前任务没有可用数组参数",
        )
        if param:
            self._clear_array_edit.setText(param.name)

    def _browse_recognition_to_logic_csv(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "选择坐标转换 CSV",
            "",
            "CSV 文件 (*.csv);;All Files (*)",
        )
        if not filepath:
            return

        app_dir = os.path.abspath(StepEditDialog._get_app_dir())
        abs_filepath = os.path.abspath(filepath)
        if abs_filepath.startswith(app_dir + os.sep):
            target = os.path.relpath(abs_filepath, app_dir).replace("\\", "/")
        else:
            target = abs_filepath
        self._recognition_to_logic_csv_edit.setText(target)

    def _browse_value_reference(self, target_widget: QLineEdit, allow_coordinate_full: bool = False):
        param = _pick_task_param(
            self,
            self._task_params,
            "选择参数",
            "请选择一个参数或字段:",
            task=self._task,
            empty_message="当前任务还没有定义参数",
        )
        if not param:
            return
        reference = _build_param_reference(self, param, allow_coordinate_full=allow_coordinate_full)
        if reference:
            target_widget.setText(reference)

    def _browse_point_coord_reference(self):
        self._browse_value_reference(self._point_coord_ref_edit, allow_coordinate_full=True)

    def _browse_param_name(self, target_widget: QLineEdit, filter_type=None):
        empty_message = "当前任务没有符合条件的参数" if filter_type else "当前任务还没有定义参数"
        param = _pick_task_param(
            self,
            self._task_params,
            "选择参数",
            "请选择一个参数:",
            filter_type=filter_type,
            task=self._task,
            empty_message=empty_message,
        )
        if param:
            target_widget.setText(param.name)

    def _browse_input_text_param(self):
        param = _pick_task_param(
            self,
            self._task_params,
            "选择参数",
            "请选择一个参数:",
            task=self._task,
            empty_message="当前任务还没有定义参数",
        )
        if not param:
            return
        reference = _build_param_reference(self, param, allow_coordinate_full=False)
        if reference:
            self._input_text_edit.insert(reference)

    def _on_remove_coord_mode_changed(self, index=0):
        del index
        _configure_remove_coord_target_editor(
            self._remove_coord_target_value_label,
            self._remove_coord_target_value_edit,
            self._remove_coord_mode_combo.currentData() or "single",
        )

    def _browse_remove_coord_target_value(self):
        reference = _pick_remove_coord_target_reference(
            self,
            self._task_params,
            self._task,
            self._remove_coord_mode_combo.currentData() or "single",
        )
        if reference:
            self._remove_coord_target_value_edit.setText(reference)

    def _add_array_item(self):
        dlg = AddArrayItemDialog(task_params=self._task_params, task=self._task, parent=self)
        if dlg.exec() == QDialog.Accepted:
            result = dlg.get_result()
            if result:
                self._temp_array_items.append(result)
                self._refresh_arr_items()

    def _del_array_item(self):
        row = self._arr_items_list.currentRow()
        if row >= 0 and row < len(self._temp_array_items):
            self._temp_array_items.pop(row)
            self._refresh_arr_items()

    def _refresh_arr_items(self):
        self._arr_items_list.clear()
        for item in self._temp_array_items:
            self._arr_items_list.addItem(_format_array_assignment_item(self._task_params, item))

    def _build_recognition_to_logic_preview_action(self) -> Optional[dict]:
        coordinate_csv_path = self._recognition_to_logic_csv_edit.text().strip()
        anchor_logical_coord = self._recognition_to_logic_anchor_logical_edit.text().strip()
        anchor_screen_coord = self._recognition_to_logic_anchor_screen_edit.text().strip()
        result_array = self._recognition_to_logic_result_array_edit.text().strip()

        if not coordinate_csv_path or not anchor_logical_coord or not anchor_screen_coord or not result_array:
            return None

        return {
            "type": "recognition_to_logic_coord",
            "delay": self._delay_spin.value(),
            "coordinate_csv_path": coordinate_csv_path,
            "anchor_logical_coord": anchor_logical_coord,
            "anchor_screen_coord": anchor_screen_coord,
            "result_array": result_array,
        }

    def _preview_recognition_to_logic(self):
        if self._action_type_combo.currentData() != "recognition_to_logic_coord":
            return

        action = self._build_recognition_to_logic_preview_action()
        if action is None:
            QMessageBox.warning(self, "提示", "请先填写坐标 CSV、锚点逻辑坐标、锚点屏幕相对坐标和结果数组")
            return

        preview_host = _find_recognition_to_logic_preview_host(self)
        if preview_host is None:
            QMessageBox.warning(self, "提示", "当前界面不支持即时预览")
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            success, preview_text = preview_host._preview_recognition_to_logic_action(
                self._step_context,
                self._task,
                action,
            )
        finally:
            QApplication.restoreOverrideCursor()

        self._recognition_to_logic_preview_output.setPlainText(preview_text)
        self._recognition_to_logic_preview_output.moveCursor(QTextCursor.MoveOperation.Start)
        if not success:
            QMessageBox.warning(self, "预览失败", preview_text or "未获取到转换结果")

    def _load_data(self):
        action_type = _normalize_grid_action_type(self._action.get("type", "click"))
        idx = self._action_type_combo.findData(action_type)
        if idx >= 0:
            self._action_type_combo.setCurrentIndex(idx)

        self._delay_spin.setValue(float(self._action.get("delay", 0) or 0))
        self._highlight_duration_spin.setValue(_highlight_duration_seconds_from_ms(self._action.get("duration_ms", 1200)))
        self._highlight_show_ai_attributes.setChecked(_coerce_action_bool(self._action, "show_ai_attributes", False))
        _set_combo_data(
            self._click_offset_mode,
            self._action.get("click_offset_mode", get_default_click_offset_mode(self._action.get("point_position_mode", "recognition"))),
            default=get_default_click_offset_mode(self._action.get("point_position_mode", "recognition")),
        )
        self._click_offset_x_spin.setValue(float(self._action.get("click_offset_x", 0) or 0))
        self._click_offset_y_spin.setValue(float(self._action.get("click_offset_y", 0) or 0))
        _set_combo_data(self._point_position_mode, self._action.get("point_position_mode", "recognition"), default="recognition")
        self._update_point_position_mode_ui()
        point_mode, point_x, point_y = _get_action_point_values(self._action)
        if point_mode == "screen_percent":
            self._point_x_spin.setValue(_coerce_point_ratio(point_x, 0.5))
            self._point_y_spin.setValue(_coerce_point_ratio(point_y, 0.5))
        else:
            self._point_x_spin.setValue(coerce_float(point_x, 0.0))
            self._point_y_spin.setValue(coerce_float(point_y, 0.0))
        self._point_coord_ref_edit.setText(str(self._action.get("point_coord_text", "") or "").strip())
        self._input_text_edit.setText(self._action.get("input_text", ""))
        clear_idx = self._clear_method.findData(self._action.get("clear_method", "delete_backspace"))
        if clear_idx >= 0:
            self._clear_method.setCurrentIndex(clear_idx)
        self._clear_key_count_spin.setValue(int(self._action.get("clear_key_count", 3) or 3))
        _set_combo_data(self._drag_coordinate_mode, self._action.get("drag_coordinate_mode", "game_logic"), default="game_logic")
        _set_combo_data(self._drag_start_mode, self._action.get("drag_start_mode", "recognition"), default="recognition")
        self._drag_start_x_spin.setValue(_coerce_drag_start_ratio(self._action.get("drag_start_x", 0.5), 0.5))
        self._drag_start_y_spin.setValue(_coerce_drag_start_ratio(self._action.get("drag_start_y", 0.5), 0.5))
        drag_vector_mode, drag_vector_x, drag_vector_y = _get_screen_drag_vector_values(self._action)
        _set_combo_data(self._drag_vector_mode, drag_vector_mode, default="pixel")
        self._drag_vector_x_spin.setValue(drag_vector_x)
        self._drag_vector_y_spin.setValue(drag_vector_y)
        self._press_keys_edit.setText(self._action.get("press_keys", ""))
        self._drag_dir_x_spin.setValue(int(self._action.get("drag_direction_x", 0) or 0))
        self._drag_dir_y_spin.setValue(int(self._action.get("drag_direction_y", 0) or 0))
        self._drag_distance_spin.setValue(int(self._action.get("drag_distance", 200) or 200))
        self._drag_duration_spin.setValue(float(self._action.get("drag_duration", 0.3) or 0.3))
        self._drag_center_tolerance_spin.setValue(normalize_center_tolerance_px(self._action.get("center_tolerance_px", 1)))
        self._modify_var_name_edit.setText(self._action.get("var_name", ""))
        self._modify_var_value_edit.setText(self._action.get("var_value", ""))
        self._remove_coord_source_array_edit.setText(self._action.get("source_array", ""))
        self._remove_coord_target_value_edit.setText(self._action.get("target_value", ""))
        _set_combo_data(self._remove_coord_mode_combo, normalize_remove_coord_mode(self._action.get("remove_mode", "single")), default="single")
        self._on_remove_coord_mode_changed()
        self._clear_array_edit.setText(self._action.get("array_name", ""))
        self._save_recognition_result_array_edit.setText(self._action.get("result_array", ""))
        self._recognition_to_logic_csv_edit.setText(self._action.get("coordinate_csv_path", ""))
        self._recognition_to_logic_anchor_logical_edit.setText(self._action.get("anchor_logical_coord", ""))
        self._recognition_to_logic_anchor_screen_edit.setText(self._action.get("anchor_screen_coord", ""))
        self._recognition_to_logic_result_array_edit.setText(self._action.get("result_array", ""))
        jump_idx = self._jump_target_combo.findData(self._action.get("target_id", ""))
        if jump_idx >= 0:
            self._jump_target_combo.setCurrentIndex(jump_idx)
        self._traverse_center_edit.setText(self._action.get("center_param", ""))
        self._traverse_array_edit.setText(self._action.get("target_array", ""))
        self._traverse_count_spin.setValue(int(self._action.get("count", 1000) or 1000))
        _set_combo_data(self._traverse_mode_combo, normalize_grid_mode(self._action.get("mode", "hex")), default="hex")
        self._two_ring_target_coord_edit.setText(self._action.get("target_coord", ""))
        self._two_ring_result_array_edit.setText(self._action.get("result_array", ""))
        self._surround_radius_spin.setValue(_coerce_grid_radius(self._action.get("radius", 2), 2))
        _set_combo_data(self._surround_mode_combo, normalize_grid_mode(self._action.get("mode", "hex")), default="hex")
        self._path_target_coord_edit.setText(self._action.get("target_coord", ""))
        self._path_start_array_edit.setText(self._action.get("start_array", ""))
        self._path_passable_array_edit.setText(self._action.get("passable_array", ""))
        self._path_result_array_edit.setText(self._action.get("result_array", ""))
        _set_combo_data(self._path_mode_combo, normalize_grid_mode(self._action.get("mode", "hex")), default="hex")
        self._temp_array_items = copy.deepcopy(self._action.get("items", []))
        self._recognition_to_logic_preview_output.clear()
        self._refresh_arr_items()
        self._on_type_changed()

    def done(self, result):
        _set_jump_target_preview(self, "")
        super().done(result)

    def _on_accept(self):
        action_type = _normalize_grid_action_type(self._action_type_combo.currentData() or "none")
        result = {
            "type": action_type,
            "delay": self._delay_spin.value(),
        }
        if _action_uses_click_offset(action_type):
            result["click_offset_mode"] = normalize_click_offset_mode(
                self._click_offset_mode.currentData() or "",
                self._point_position_mode.currentData() or "recognition",
            )
            result["click_offset_x"] = self._click_offset_x_spin.value()
            result["click_offset_y"] = self._click_offset_y_spin.value()
        if action_type in ("input_text", "mark_blocked"):
            result["input_text"] = self._input_text_edit.text().strip()
        if action_type == "input_text":
            result["clear_method"] = self._clear_method.currentData()
            result["clear_key_count"] = self._clear_key_count_spin.value()
        if action_type == "press_key":
            result["press_keys"] = self._press_keys_edit.text().strip()
        if _action_uses_highlight_duration(action_type):
            result["duration_ms"] = int(round(self._highlight_duration_spin.value() * 1000))
        if action_type == "highlight_match":
            result["show_ai_attributes"] = self._highlight_show_ai_attributes.isChecked()
        if _action_uses_point_position_mode(action_type):
            result["point_position_mode"] = normalize_point_position_mode(
                self._point_position_mode.currentData() or "recognition"
            )
            result["point_x"] = self._point_x_spin.value()
            result["point_y"] = self._point_y_spin.value()
            result["point_coord_text"] = self._point_coord_ref_edit.text().strip()
        if _action_uses_drag_duration(action_type):
            result["drag_duration"] = self._drag_duration_spin.value()
        if _action_uses_center_tolerance(action_type):
            result["center_tolerance_px"] = self._drag_center_tolerance_spin.value()
        if action_type == "drag_map":
            result["drag_coordinate_mode"] = self._drag_coordinate_mode.currentData() or "game_logic"
            result["drag_start_mode"] = self._drag_start_mode.currentData() or "recognition"
            result["drag_start_x"] = self._drag_start_x_spin.value()
            result["drag_start_y"] = self._drag_start_y_spin.value()
            result["drag_vector_mode"] = normalize_drag_vector_mode(self._drag_vector_mode.currentData() or "pixel")
            result["drag_vector_x"] = self._drag_vector_x_spin.value()
            result["drag_vector_y"] = self._drag_vector_y_spin.value()
            result["drag_direction_x"] = self._drag_dir_x_spin.value()
            result["drag_direction_y"] = self._drag_dir_y_spin.value()
            result["drag_distance"] = self._drag_distance_spin.value()
        if action_type == "modify_variable":
            var_name = self._modify_var_name_edit.text().strip()
            if not var_name:
                QMessageBox.warning(self, "提示", "请输入变量名")
                return
            result["var_name"] = var_name
            result["var_value"] = self._modify_var_value_edit.text().strip()
        if action_type == "add_to_array":
            if not self._temp_array_items:
                QMessageBox.warning(self, "提示", "请至少添加一个数组项")
                return
            result["items"] = copy.deepcopy(self._temp_array_items)
        if action_type == "save_recognition_coords":
            result_array = self._save_recognition_result_array_edit.text().strip()
            if not result_array:
                QMessageBox.warning(self, "提示", "请选择结果坐标数组")
                return
            result["result_array"] = result_array
        if action_type == "remove_target_coords":
            source_array = self._remove_coord_source_array_edit.text().strip()
            target_value = self._remove_coord_target_value_edit.text().strip()
            if not source_array or not target_value:
                QMessageBox.warning(self, "提示", "请填写源坐标数组和待删除坐标")
                return
            result["source_array"] = source_array
            result["target_value"] = target_value
            result["remove_mode"] = normalize_remove_coord_mode(self._remove_coord_mode_combo.currentData() or "single")
        if action_type == "clear_array_data":
            array_name = self._clear_array_edit.text().strip()
            if not array_name:
                QMessageBox.warning(self, "提示", "请选择目标数组")
                return
            result["array_name"] = array_name
        if action_type == "recognition_to_logic_coord":
            coordinate_csv_path = self._recognition_to_logic_csv_edit.text().strip()
            anchor_logical_coord = self._recognition_to_logic_anchor_logical_edit.text().strip()
            anchor_screen_coord = self._recognition_to_logic_anchor_screen_edit.text().strip()
            result_array = self._recognition_to_logic_result_array_edit.text().strip()
            if not coordinate_csv_path or not anchor_logical_coord or not anchor_screen_coord or not result_array:
                QMessageBox.warning(self, "提示", "请填写坐标 CSV、锚点逻辑坐标、锚点屏幕相对坐标和结果数组")
                return
            result["coordinate_csv_path"] = coordinate_csv_path
            result["anchor_logical_coord"] = anchor_logical_coord
            result["anchor_screen_coord"] = anchor_screen_coord
            result["result_array"] = result_array
        if action_type == "jump_to_step":
            target_id = self._jump_target_combo.currentData() or ""
            if not target_id:
                QMessageBox.warning(self, "提示", "请选择目标步骤")
                return
            result["target_id"] = target_id
        if action_type == "traverse_grid":
            center_param = self._traverse_center_edit.text().strip()
            target_array = self._traverse_array_edit.text().strip()
            if not center_param or not target_array:
                QMessageBox.warning(self, "提示", "请填写中心坐标参数和目标数组")
                return
            result["center_param"] = center_param
            result["target_array"] = target_array
            result["count"] = self._traverse_count_spin.value()
            result["mode"] = normalize_grid_mode(self._traverse_mode_combo.currentData() or "hex")
        if action_type == "get_surrounding_coords":
            target_coord = self._two_ring_target_coord_edit.text().strip()
            result_array = self._two_ring_result_array_edit.text().strip()
            if not target_coord or not result_array:
                QMessageBox.warning(self, "提示", "请填写目标坐标和结果数组")
                return
            result["target_coord"] = target_coord
            result["result_array"] = result_array
            result["radius"] = self._surround_radius_spin.value()
            result["mode"] = normalize_grid_mode(self._surround_mode_combo.currentData() or "hex")
        if action_type == "find_road_path":
            target_coord = self._path_target_coord_edit.text().strip()
            start_array = self._path_start_array_edit.text().strip()
            passable_array = self._path_passable_array_edit.text().strip()
            result_array = self._path_result_array_edit.text().strip()
            if not target_coord or not start_array or not passable_array or not result_array:
                QMessageBox.warning(self, "提示", "请填写目标坐标、起始数组、可通行数组和结果数组")
                return
            result["target_coord"] = target_coord
            result["start_array"] = start_array
            result["passable_array"] = passable_array
            result["result_array"] = result_array
            result["mode"] = normalize_grid_mode(self._path_mode_combo.currentData() or "hex")
        self._result = result
        self.accept()

    def get_result(self):
        return self._result


class FailActionEditDialog(QDialog):
    """识别失败操作编辑对话框"""

    def __init__(self, action: dict = None, task_params: List[TaskParameter] = None, 
                 task_steps: List[SingleTask] = None, task: PlanTask = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑失败操作" if action else "新增失败操作")
        self.setMinimumWidth(450)
        self._action = action or {}
        self._task = task
        self._task_params = task_params or []
        self._task_steps = task_steps or []
        self._result = None
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        # 操作类型
        self._action_type_combo = QComboBox()
        _populate_grouped_action_type_combo(self._action_type_combo, FAIL_ACTION_TYPE_GROUPS)
        self._action_type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("操作类型:", self._action_type_combo)

        # ── 修改变量 ──
        var_name_layout = QHBoxLayout()
        self._modify_var_name_edit = QLineEdit()
        self._modify_var_name_edit.setPlaceholderText("变量名（如: counter 或 info.level）")
        var_name_layout.addWidget(self._modify_var_name_edit)
        self._modify_var_browse_btn = QPushButton("从参数选择")
        self._modify_var_browse_btn.clicked.connect(self._browse_var_param)
        var_name_layout.addWidget(self._modify_var_browse_btn)
        self._modify_var_name_label = QLabel("变量名:")
        form.addRow(self._modify_var_name_label, var_name_layout)

        self._modify_var_value_edit = QLineEdit()
        self._modify_var_value_edit.setPlaceholderText("新值（支持 {参数} 替换）")
        self._modify_var_value_label = QLabel("变量值:")
        fail_modify_value_layout = QHBoxLayout()
        fail_modify_value_layout.addWidget(self._modify_var_value_edit)
        self._modify_var_value_browse_btn = QPushButton("从参数选择")
        self._modify_var_value_browse_btn.clicked.connect(self._browse_var_value)
        fail_modify_value_layout.addWidget(self._modify_var_value_browse_btn)
        form.addRow(self._modify_var_value_label, fail_modify_value_layout)

        # ── 添加到数组 ──
        self._add_array_label = QLabel("数组项目:")
        add_array_layout = QVBoxLayout()
        self._add_array_items_list = QListWidget()
        self._add_array_items_list.setMaximumHeight(100)
        add_array_layout.addWidget(self._add_array_items_list)
        add_array_btn_row = QHBoxLayout()
        self._add_array_item_btn = QPushButton("添加项")
        self._add_array_item_btn.clicked.connect(self._add_array_item)
        add_array_btn_row.addWidget(self._add_array_item_btn)
        self._del_array_item_btn = QPushButton("删除项")
        self._del_array_item_btn.clicked.connect(self._del_array_item)
        add_array_btn_row.addWidget(self._del_array_item_btn)
        add_array_btn_row.addStretch()
        add_array_layout.addLayout(add_array_btn_row)
        form.addRow(self._add_array_label, add_array_layout)

        remove_coord_source_layout = QHBoxLayout()
        self._remove_coord_source_array_edit = QLineEdit()
        self._remove_coord_source_array_edit.setPlaceholderText("源坐标数组参数名")
        remove_coord_source_layout.addWidget(self._remove_coord_source_array_edit)
        self._remove_coord_source_array_browse_btn = QPushButton("从参数选择")
        self._remove_coord_source_array_browse_btn.clicked.connect(self._browse_remove_source_array)
        remove_coord_source_layout.addWidget(self._remove_coord_source_array_browse_btn)
        self._remove_coord_source_array_label = QLabel("源坐标数组:")
        form.addRow(self._remove_coord_source_array_label, remove_coord_source_layout)

        self._remove_coord_mode_combo = QComboBox()
        _populate_remove_coord_mode_combo(self._remove_coord_mode_combo)
        self._remove_coord_mode_combo.currentIndexChanged.connect(self._on_remove_coord_mode_changed)
        self._remove_coord_mode_label = QLabel("删除模式:")
        form.addRow(self._remove_coord_mode_label, self._remove_coord_mode_combo)

        remove_coord_target_layout = QHBoxLayout()
        self._remove_coord_target_value_edit = QLineEdit()
        remove_coord_target_layout.addWidget(self._remove_coord_target_value_edit)
        self._remove_coord_target_value_browse_btn = QPushButton("从参数选择")
        self._remove_coord_target_value_browse_btn.clicked.connect(self._browse_remove_target_value)
        remove_coord_target_layout.addWidget(self._remove_coord_target_value_browse_btn)
        self._remove_coord_target_value_label = QLabel("待删除坐标:")
        form.addRow(self._remove_coord_target_value_label, remove_coord_target_layout)
        _configure_remove_coord_target_editor(
            self._remove_coord_target_value_label,
            self._remove_coord_target_value_edit,
            self._remove_coord_mode_combo.currentData() or "single",
        )

        clear_array_layout = QHBoxLayout()
        self._clear_array_edit = QLineEdit()
        self._clear_array_edit.setPlaceholderText("目标数组参数名")
        clear_array_layout.addWidget(self._clear_array_edit)
        self._clear_array_browse_btn = QPushButton("从参数选择")
        self._clear_array_browse_btn.clicked.connect(self._browse_clear_array_param)
        clear_array_layout.addWidget(self._clear_array_browse_btn)
        self._clear_array_label = QLabel("目标数组:")
        form.addRow(self._clear_array_label, clear_array_layout)

        # ── 跳转步骤 ──
        self._jump_target_combo = _JumpTargetPickerComboBox()
        self._populate_jump_targets()
        self._jump_target_combo.currentIndexChanged.connect(self._on_jump_target_changed)
        self._jump_target_label = QLabel("跳转目标:")
        form.addRow(self._jump_target_label, self._jump_target_combo)

        self._delay_spin = QDoubleSpinBox()
        self._delay_spin.setRange(0.0, 6000.0)
        self._delay_spin.setSingleStep(0.1)
        self._delay_spin.setDecimals(2)
        self._delay_spin.setValue(0.0)
        self._delay_spin.setSuffix(" 秒")
        form.addRow("指令间延时:", self._delay_spin)

        layout.addLayout(form)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._on_type_changed()

    def _on_type_changed(self):
        """操作类型变更"""
        action_type = self._action_type_combo.currentData()
        
        is_modify_var = action_type == "modify_variable"
        is_add_array = action_type == "add_to_array"
        is_remove_coords = action_type == "remove_target_coords"
        is_clear_array = action_type == "clear_array_data"
        is_jump = action_type == "jump_to_step"
        
        # 修改变量
        self._modify_var_name_label.setVisible(is_modify_var)
        self._modify_var_name_edit.setVisible(is_modify_var)
        self._modify_var_browse_btn.setVisible(is_modify_var)
        self._modify_var_value_label.setVisible(is_modify_var)
        self._modify_var_value_edit.setVisible(is_modify_var)
        self._modify_var_value_browse_btn.setVisible(is_modify_var)
        
        # 添加到数组
        self._add_array_label.setVisible(is_add_array)
        self._add_array_items_list.setVisible(is_add_array)
        self._add_array_item_btn.setVisible(is_add_array)
        self._del_array_item_btn.setVisible(is_add_array)

        self._remove_coord_source_array_label.setVisible(is_remove_coords)
        self._remove_coord_source_array_edit.setVisible(is_remove_coords)
        self._remove_coord_source_array_browse_btn.setVisible(is_remove_coords)
        self._remove_coord_mode_label.setVisible(is_remove_coords)
        self._remove_coord_mode_combo.setVisible(is_remove_coords)
        self._remove_coord_target_value_label.setVisible(is_remove_coords)
        self._remove_coord_target_value_edit.setVisible(is_remove_coords)
        self._remove_coord_target_value_browse_btn.setVisible(is_remove_coords)

        self._clear_array_label.setVisible(is_clear_array)
        self._clear_array_edit.setVisible(is_clear_array)
        self._clear_array_browse_btn.setVisible(is_clear_array)
        
        # 跳转步骤
        self._jump_target_label.setVisible(is_jump)
        self._jump_target_combo.setVisible(is_jump)
        self._on_jump_target_changed()

    def _on_jump_target_changed(self, index=0):
        del index
        target_id = ""
        if self._action_type_combo.currentData() == "jump_to_step":
            target_id = self._jump_target_combo.currentData() or ""
        _set_jump_target_preview(self, target_id)

    def _populate_jump_targets(self):
        """填充跳转目标步骤下拉框"""
        self._jump_target_combo.set_task_steps(self._task_steps)

    def _browse_var_param(self):
        """从参数选择变量"""
        param = _pick_task_param(
            self,
            self._task_params,
            "选择参数",
            "请选择一个参数:",
            task=self._task,
            empty_message="当前任务还没有定义参数",
        )
        if not param:
            return
        target = _choose_member_path(self, param, include_whole=True, wrap_reference=False, allow_coordinate_full=False)
        if target:
            self._modify_var_name_edit.setText(target)

    def _browse_var_value(self):
        param = _pick_task_param(
            self,
            self._task_params,
            "选择参数",
            "请选择一个参数或字段作为新值:",
            task=self._task,
            empty_message="当前任务还没有定义参数",
        )
        if not param:
            return
        reference = _choose_member_path(self, param, include_whole=True, wrap_reference=True, allow_coordinate_full=False)
        if reference:
            self._modify_var_value_edit.setText(reference)

    def _browse_clear_array_param(self):
        param = _pick_array_task_param(
            self,
            self._task_params,
            task=self._task,
            empty_message="当前任务没有可用数组参数",
        )
        if param:
            self._clear_array_edit.setText(param.name)

    def _browse_remove_source_array(self):
        param = _pick_task_param(
            self,
            self._task_params,
            "选择坐标数组参数",
            "请选择一个坐标数组参数:",
            filter_type="coord_array",
            task=self._task,
            empty_message="当前任务没有坐标数组参数",
        )
        if param:
            self._remove_coord_source_array_edit.setText(param.name)

    def _on_remove_coord_mode_changed(self, index=0):
        del index
        _configure_remove_coord_target_editor(
            self._remove_coord_target_value_label,
            self._remove_coord_target_value_edit,
            self._remove_coord_mode_combo.currentData() or "single",
        )

    def _browse_remove_target_value(self):
        reference = _pick_remove_coord_target_reference(
            self,
            self._task_params,
            self._task,
            self._remove_coord_mode_combo.currentData() or "single",
        )
        if reference:
            self._remove_coord_target_value_edit.setText(reference)

    def _add_array_item(self):
        """添加数组项"""
        dlg = AddArrayItemDialog(
            task_params=self._task_params,
            task=self._task,
            parent=self
        )
        if dlg.exec() == QDialog.Accepted:
            result = dlg.get_result()
            if result:
                if not hasattr(self, '_temp_array_items'):
                    self._temp_array_items = []
                self._temp_array_items.append(result)
                self._refresh_array_items()

    def _del_array_item(self):
        """删除数组项"""
        row = self._add_array_items_list.currentRow()
        if row >= 0 and hasattr(self, '_temp_array_items') and row < len(self._temp_array_items):
            self._temp_array_items.pop(row)
            self._refresh_array_items()

    def _refresh_array_items(self):
        """刷新数组项列表"""
        self._add_array_items_list.clear()
        if hasattr(self, '_temp_array_items'):
            for item in self._temp_array_items:
                self._add_array_items_list.addItem(_format_array_assignment_item(self._task_params, item))

    def _load_data(self):
        """加载数据"""
        if not self._action:
            self._temp_array_items = []
            return
        
        action_type = self._action.get("type", "modify_variable")
        idx = self._action_type_combo.findData(action_type)
        if idx >= 0:
            self._action_type_combo.setCurrentIndex(idx)
        
        if action_type == "modify_variable":
            self._modify_var_name_edit.setText(self._action.get("var_name", ""))
            self._modify_var_value_edit.setText(self._action.get("var_value", ""))
        elif action_type == "add_to_array":
            self._temp_array_items = list(self._action.get("items", []))
            self._refresh_array_items()
        elif action_type == "remove_target_coords":
            self._remove_coord_source_array_edit.setText(self._action.get("source_array", ""))
            self._remove_coord_target_value_edit.setText(self._action.get("target_value", ""))
            _set_combo_data(self._remove_coord_mode_combo, normalize_remove_coord_mode(self._action.get("remove_mode", "single")), default="single")
            self._on_remove_coord_mode_changed()
        elif action_type == "clear_array_data":
            self._clear_array_edit.setText(self._action.get("array_name", ""))
        elif action_type == "jump_to_step":
            idx = self._jump_target_combo.findData(self._action.get("target_id", ""))
            if idx >= 0:
                self._jump_target_combo.setCurrentIndex(idx)
        self._delay_spin.setValue(float(self._action.get("delay", 0) or 0))
        
        self._on_type_changed()

    def done(self, result):
        _set_jump_target_preview(self, "")
        super().done(result)

    def _on_accept(self):
        """确认"""
        action_type = self._action_type_combo.currentData()
        
        result = {"type": action_type}
        result["delay"] = self._delay_spin.value()
        
        if action_type == "modify_variable":
            var_name = self._modify_var_name_edit.text().strip()
            var_value = self._modify_var_value_edit.text().strip()
            if not var_name:
                QMessageBox.warning(self, "提示", "请输入变量名")
                return
            result["var_name"] = var_name
            result["var_value"] = var_value
        
        elif action_type == "add_to_array":
            if not hasattr(self, '_temp_array_items') or not self._temp_array_items:
                QMessageBox.warning(self, "提示", "请至少添加一个数组项")
                return
            result["items"] = self._temp_array_items

        elif action_type == "remove_target_coords":
            source_array = self._remove_coord_source_array_edit.text().strip()
            target_value = self._remove_coord_target_value_edit.text().strip()
            if not source_array or not target_value:
                QMessageBox.warning(self, "提示", "请填写源坐标数组和待删除坐标")
                return
            result["source_array"] = source_array
            result["target_value"] = target_value
            result["remove_mode"] = normalize_remove_coord_mode(self._remove_coord_mode_combo.currentData() or "single")

        elif action_type == "clear_array_data":
            array_name = self._clear_array_edit.text().strip()
            if not array_name:
                QMessageBox.warning(self, "提示", "请选择目标数组")
                return
            result["array_name"] = array_name
        
        elif action_type == "jump_to_step":
            target_id = self._jump_target_combo.currentData()
            if not target_id:
                QMessageBox.warning(self, "提示", "请选择目标步骤")
                return
            result["target_id"] = target_id
        
        # continue_loop 和 break_loop 不需要额外参数
        
        self._result = result
        self.accept()

    def get_result(self):
        """获取结果"""
        return self._result


class AddArrayItemDialog(QDialog):
    """添加数组项对话框（用于失败操作）"""

    def __init__(self, task_params: List[TaskParameter] = None, task: PlanTask = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加数组项")
        self.setMinimumWidth(450)
        self._task = task
        self._task_params = task_params or []
        self._result = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        # 目标数组选择
        array_layout = QHBoxLayout()
        self._array_combo = QComboBox()
        self._array_combo.currentIndexChanged.connect(self._on_array_changed)
        array_layout.addWidget(self._array_combo)
        self._array_create_btn = QPushButton("创建变量")
        self._array_create_btn.clicked.connect(self._create_target_array_param)
        self._array_create_btn.setVisible(self._task is not None)
        array_layout.addWidget(self._array_create_btn)
        form.addRow("目标数组:", array_layout)

        # 手动输入数组名（当没有数组参数时）
        self._manual_array_edit = QLineEdit()
        self._manual_array_edit.setPlaceholderText("手动输入数组参数名")
        self._manual_array_label = QLabel("数组名:")
        form.addRow(self._manual_array_label, self._manual_array_edit)
        self._manual_array_label.setVisible(False)
        self._manual_array_edit.setVisible(False)

        # 值来源选择
        self._value_source_combo = QComboBox()
        self._value_source_combo.addItem("直接输入", "direct")
        self._value_source_combo.addItem("选择参数", "param")
        self._value_source_combo.currentIndexChanged.connect(self._on_value_source_changed)
        form.addRow("值来源:", self._value_source_combo)

        # 直接输入值
        direct_value_layout = QHBoxLayout()
        self._direct_value_edit = QLineEdit()
        self._direct_value_edit.setPlaceholderText("输入值（支持 {参数} 替换）")
        direct_value_layout.addWidget(self._direct_value_edit)
        self._direct_value_browse_btn = QPushButton("浏览...")
        self._direct_value_browse_btn.clicked.connect(self._browse_direct_value)
        direct_value_layout.addWidget(self._direct_value_browse_btn)
        self._direct_value_label = QLabel("输入值:")
        form.addRow(self._direct_value_label, direct_value_layout)

        # 选择参数
        param_layout = QHBoxLayout()
        self._param_combo = QComboBox()
        param_layout.addWidget(self._param_combo)
        self._param_create_btn = QPushButton("创建变量")
        self._param_create_btn.clicked.connect(self._create_source_param)
        self._param_create_btn.setVisible(False)
        param_layout.addWidget(self._param_create_btn)
        self._param_combo.currentIndexChanged.connect(self._on_param_changed)
        self._param_label = QLabel("选择参数:")
        form.addRow(self._param_label, param_layout)
        self._param_label.setVisible(False)
        self._param_combo.setVisible(False)

        # 坐标参数的 x/y 选择
        self._coord_part_combo = QComboBox()
        self._coord_part_combo.addItem("完整坐标 {x},{y}", "full")
        self._coord_part_combo.addItem("仅 X 坐标", "x")
        self._coord_part_combo.addItem("仅 Y 坐标", "y")
        self._coord_part_label = QLabel("坐标部分:")
        form.addRow(self._coord_part_label, self._coord_part_combo)
        self._coord_part_label.setVisible(False)
        self._coord_part_combo.setVisible(False)

        self._struct_field_combo = QComboBox()
        self._struct_field_label = QLabel("结构体字段:")
        form.addRow(self._struct_field_label, self._struct_field_combo)
        self._struct_field_label.setVisible(False)
        self._struct_field_combo.setVisible(False)

        # 预览
        self._preview_edit = QLineEdit()
        self._preview_edit.setReadOnly(True)
        self._preview_edit.setPlaceholderText("值预览")
        form.addRow("预览:", self._preview_edit)

        layout.addLayout(form)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._direct_value_edit.textChanged.connect(self._update_preview)
        self._coord_part_combo.currentIndexChanged.connect(self._update_preview)
        self._struct_field_combo.currentIndexChanged.connect(self._update_preview)

        # 初始化显示
        self._refresh_target_array_combo()
        self._refresh_source_param_combo()
        self._on_value_source_changed()
        self._on_array_changed()

    def _refresh_target_array_combo(self, selected_name: Optional[str] = None):
        array_params = _populate_param_combo(
            self._array_combo,
            self._task_params,
            "（任务中没有数组参数，请手动输入）",
            predicate=lambda param: is_array_param_type(param.param_type),
            selected_name=selected_name,
        )
        has_array_params = bool(array_params)
        self._manual_array_label.setVisible(not has_array_params)
        self._manual_array_edit.setVisible(not has_array_params)

    def _refresh_source_param_combo(self, selected_name: Optional[str] = None):
        _populate_param_combo(
            self._param_combo,
            self._task_params,
            "（无可用参数，请先创建）",
            selected_name=selected_name,
        )

    def _create_target_array_param(self):
        new_param = _inline_create_task_param(self, self._task, self._task_params)
        if not new_param:
            return

        selected_array = self._array_combo.currentData()
        if is_array_param_type(new_param.param_type):
            selected_array = new_param.name
        else:
            QMessageBox.information(self, "提示", f"变量“{new_param.name}”已创建，但这里需要数组类型变量")

        self._refresh_target_array_combo(selected_array)
        self._refresh_source_param_combo(self._param_combo.currentData())
        self._on_array_changed()

    def _create_source_param(self):
        new_param = _inline_create_task_param(self, self._task, self._task_params)
        if not new_param:
            return
        self._refresh_target_array_combo(self._array_combo.currentData())
        self._refresh_source_param_combo(new_param.name)
        self._on_param_changed()

    def _on_array_changed(self):
        """数组选择变化"""
        array_name = self._array_combo.currentData()
        target_param = _find_task_param(self._task_params, array_name)
        if _is_int_array_param(target_param):
            self._direct_value_edit.setPlaceholderText("输入整数值（支持 {参数} 替换）")
        elif _is_image_array_param(target_param):
            self._direct_value_edit.setPlaceholderText("输入图像路径，或点击浏览选择文件")
        else:
            self._direct_value_edit.setPlaceholderText("输入值（支持 {参数} 替换）")
        self._direct_value_browse_btn.setVisible(
            _is_image_array_param(target_param) and self._value_source_combo.currentData() == "direct"
        )
        self._update_preview()

    def _on_value_source_changed(self):
        """值来源变化"""
        source = self._value_source_combo.currentData()
        
        is_direct = source == "direct"
        is_param = source == "param"
        
        self._direct_value_label.setVisible(is_direct)
        self._direct_value_edit.setVisible(is_direct)
        self._direct_value_browse_btn.setVisible(False)
        
        self._param_label.setVisible(is_param)
        self._param_combo.setVisible(is_param)
        self._param_create_btn.setVisible(is_param and self._task is not None)
        
        # 根据参数类型显示坐标选择
        if is_param:
            self._on_param_changed()
        else:
            self._coord_part_label.setVisible(False)
            self._coord_part_combo.setVisible(False)
            self._struct_field_label.setVisible(False)
            self._struct_field_combo.setVisible(False)
        
        self._on_array_changed()
        self._update_preview()

    def _browse_direct_value(self):
        array_name = self._array_combo.currentData()
        target_param = _find_task_param(self._task_params, array_name)
        if not _is_image_array_param(target_param):
            return

        current_value = self._direct_value_edit.text().strip()
        start_path = ""
        if current_value:
            normalized = os.path.normpath(current_value)
            if os.path.isfile(normalized):
                start_path = normalized
            else:
                folder = os.path.dirname(normalized)
                if folder and os.path.isdir(folder):
                    start_path = folder

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择图像文件",
            start_path,
            "图像文件 (*.png *.jpg *.jpeg *.bmp);;所有文件 (*.*)",
        )
        if file_path:
            self._direct_value_edit.setText(file_path)

    def _on_param_changed(self):
        """参数选择变化"""
        param_name = self._param_combo.currentData()
        if param_name:
            param = next((p for p in self._task_params if p.name == param_name), None)
            if param and param.param_type == "coordinate":
                self._coord_part_label.setVisible(True)
                self._coord_part_combo.setVisible(True)
                self._struct_field_label.setVisible(False)
                self._struct_field_combo.setVisible(False)
            elif param and isinstance(param.value, dict):
                self._coord_part_label.setVisible(False)
                self._coord_part_combo.setVisible(False)
                self._struct_field_label.setVisible(True)
                self._struct_field_combo.setVisible(True)
                self._struct_field_combo.blockSignals(True)
                self._struct_field_combo.clear()
                self._struct_field_combo.addItem("整个结构体", "full")
                for field_name in param.value.keys():
                    self._struct_field_combo.addItem(field_name, field_name)
                self._struct_field_combo.blockSignals(False)
            else:
                self._coord_part_label.setVisible(False)
                self._coord_part_combo.setVisible(False)
                self._struct_field_label.setVisible(False)
                self._struct_field_combo.setVisible(False)
        self._update_preview()

    def _update_preview(self):
        """更新预览"""
        value = self._get_value()
        self._preview_edit.setText(value)

    def _get_value(self) -> str:
        """获取当前配置的值"""
        source = self._value_source_combo.currentData()
        
        if source == "direct":
            return self._direct_value_edit.text().strip()
        
        elif source == "param":
            param_name = self._param_combo.currentData()
            if not param_name:
                return ""
            
            param = next((p for p in self._task_params if p.name == param_name), None)
            if param and param.param_type == "coordinate":
                part = self._coord_part_combo.currentData()
                if part == "x":
                    return f"{{{param_name}.x}}"
                elif part == "y":
                    return f"{{{param_name}.y}}"
                else:  # full
                    return f"{{{param_name}.x}},{{{param_name}.y}}"
            elif param and isinstance(param.value, dict):
                field_name = self._struct_field_combo.currentData()
                if field_name == "full":
                    return f"{{{param_name}}}"
                if field_name:
                    return f"{{{param_name}.{field_name}}}"
                return f"{{{param_name}}}"
            else:
                return f"{{{param_name}}}"
        
        return ""

    def _on_accept(self):
        """确认"""
        # 获取数组名
        array_name = self._array_combo.currentData()
        if not array_name:
            array_name = self._manual_array_edit.text().strip()
        
        if not array_name:
            QMessageBox.warning(self, "提示", "请选择或输入目标数组名")
            return
        
        # 获取值
        value = self._get_value()
        if not value:
            QMessageBox.warning(self, "提示", "请输入或选择值")
            return

        target_param = _find_task_param(self._task_params, array_name)
        if (
            target_param
            and target_param.param_type == "array"
            and self._value_source_combo.currentData() == "direct"
            and "{" not in value
        ):
            try:
                raw_value = _parse_loose_value(value) if _is_int_array_param(target_param) else value
                coerce_array_item_value(target_param.array_item_type, raw_value)
            except (TypeError, ValueError):
                if _is_int_array_param(target_param):
                    message = "该目标数组是整数数组，请输入有效整数"
                elif _is_image_array_param(target_param):
                    message = "该目标数组是图像路径数组，请输入有效图像路径"
                else:
                    message = "请输入有效的数组项值"
                QMessageBox.warning(self, "格式错误", message)
                return
        
        self._result = {"array_name": array_name, "value": value}
        self.accept()

    def get_result(self):
        """获取结果"""
        return self._result


class TaskEditDialog(QDialog):
    """计划任务编辑对话框"""

    task_saved = Signal(str)

    def __init__(self, task: PlanTask = None, task_storage: TaskStorage = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑计划任务" if task else "新建计划任务")
        self.setMinimumSize(600, 500)

        self._is_existing_task = task is not None
        self._task_storage = task_storage
        self._task = task or PlanTask()
        self._highlighted_step_id = ""
        self._copied_steps: List[SingleTask] = []
        self._init_ui()
        self._load_data()

    def _auto_save_param_changes(self) -> bool:
        """参数小窗口确认后，立即将参数相关改动同步到已存在的任务文件。"""
        if not self._is_existing_task or self._task_storage is None:
            return False

        stored_task = self._task_storage.load(self._task.id)
        if stored_task is None:
            return False

        stored_task.parameters = copy.deepcopy(self._task.parameters)
        stored_task.struct_defs = copy.deepcopy(self._task.struct_defs)
        if self._task_storage.save(stored_task):
            self._task.modified_time = stored_task.modified_time
            return True
        return False

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # === 任务基本信息 ===
        info_group = QGroupBox("任务信息")
        info_layout = QHBoxLayout(info_group)
        info_layout.setContentsMargins(8, 8, 8, 8)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("输入任务名称")
        info_layout.addWidget(QLabel("任务名称:"))
        info_layout.addWidget(self._name_edit, 3)

        self._desc_edit = QLineEdit()
        self._desc_edit.setPlaceholderText("可选的任务描述")
        info_layout.addWidget(QLabel("任务描述:"))
        info_layout.addWidget(self._desc_edit, 4)

        self._loop_spin = QSpinBox()
        self._loop_spin.setRange(0, 9999)
        self._loop_spin.setValue(1)
        self._loop_spin.setSpecialValueText("无限循环")
        self._loop_spin.setMaximumWidth(110)
        info_layout.addWidget(QLabel("循环次数:"))
        info_layout.addWidget(self._loop_spin)

        layout.addWidget(info_group)

        # === 结构体定义 ===
        structs_group = QGroupBox("结构体定义")
        structs_layout = QVBoxLayout(structs_group)

        structs_btn_layout = QHBoxLayout()
        self._add_struct_btn = QPushButton("添加结构体")
        self._add_struct_btn.clicked.connect(self._add_struct)
        structs_btn_layout.addWidget(self._add_struct_btn)
        self._edit_struct_btn = QPushButton("编辑结构体")
        self._edit_struct_btn.clicked.connect(self._edit_struct)
        structs_btn_layout.addWidget(self._edit_struct_btn)
        self._del_struct_btn = QPushButton("删除结构体")
        self._del_struct_btn.clicked.connect(self._del_struct)
        structs_btn_layout.addWidget(self._del_struct_btn)
        structs_btn_layout.addStretch()
        structs_layout.addLayout(structs_btn_layout)

        self._structs_table = QTableWidget(0, 2)
        self._structs_table.setHorizontalHeaderLabels(["结构体名", "成员变量"])
        self._structs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._structs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._structs_table.setMaximumHeight(140)
        self._structs_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._structs_table.itemDoubleClicked.connect(self._edit_struct)
        structs_layout.addWidget(self._structs_table)

        # === 任务参数 ===
        params_group = QGroupBox("任务参数（可在步骤中用 {参数名} 引用，字典型参数可用 {名.字段名}）")
        params_layout = QVBoxLayout(params_group)

        params_btn_layout = QHBoxLayout()
        self._add_param_btn = QPushButton("添加参数")
        self._add_param_btn.clicked.connect(self._add_param)
        params_btn_layout.addWidget(self._add_param_btn)
        self._del_param_btn = QPushButton("删除参数")
        self._del_param_btn.clicked.connect(self._del_param)
        params_btn_layout.addWidget(self._del_param_btn)
        self._edit_param_btn = QPushButton("编辑参数")
        self._edit_param_btn.clicked.connect(self._edit_param)
        params_btn_layout.addWidget(self._edit_param_btn)
        params_btn_layout.addStretch()
        params_layout.addLayout(params_btn_layout)

        self._params_table = QTableWidget(0, 4)
        self._params_table.setHorizontalHeaderLabels(["参数名", "类型", "值", "存档"])
        self._params_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._params_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._params_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._params_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._params_table.setMaximumHeight(180)
        self._params_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._params_table.itemDoubleClicked.connect(self._edit_param)
        params_layout.addWidget(self._params_table)

        data_tabs = QTabWidget()
        struct_tab = QWidget()
        struct_tab_layout = QVBoxLayout(struct_tab)
        struct_tab_layout.setContentsMargins(0, 0, 0, 0)
        struct_tab_layout.addWidget(structs_group)
        params_tab = QWidget()
        params_tab_layout = QVBoxLayout(params_tab)
        params_tab_layout.setContentsMargins(0, 0, 0, 0)
        params_tab_layout.addWidget(params_group)

        # === 步骤列表 ===
        steps_group = QGroupBox("执行步骤（按顺序执行）")
        steps_layout = QVBoxLayout(steps_group)

        # 操作按钮
        btn_layout = QHBoxLayout()
        self._add_step_btn = QPushButton("添加步骤")
        self._add_step_btn.clicked.connect(self._add_step)
        btn_layout.addWidget(self._add_step_btn)

        self._add_loop_btn = QPushButton("添加循环步骤")
        self._add_loop_btn.clicked.connect(self._add_loop_step)
        btn_layout.addWidget(self._add_loop_btn)

        self._edit_step_btn = QPushButton("编辑步骤")
        self._edit_step_btn.clicked.connect(self._edit_step)
        btn_layout.addWidget(self._edit_step_btn)

        self._del_step_btn = QPushButton("删除步骤")
        self._del_step_btn.clicked.connect(self._delete_step)
        btn_layout.addWidget(self._del_step_btn)

        self._copy_step_btn = QPushButton("复制步骤")
        self._copy_step_btn.clicked.connect(self._copy_steps)
        btn_layout.addWidget(self._copy_step_btn)

        self._paste_step_btn = QPushButton("粘贴步骤")
        self._paste_step_btn.clicked.connect(self._paste_steps)
        self._paste_step_btn.setEnabled(False)
        btn_layout.addWidget(self._paste_step_btn)

        self._move_up_btn = QPushButton("上移")
        self._move_up_btn.clicked.connect(self._move_step_up)
        btn_layout.addWidget(self._move_up_btn)

        self._move_down_btn = QPushButton("下移")
        self._move_down_btn.clicked.connect(self._move_step_down)
        btn_layout.addWidget(self._move_down_btn)

        self._move_into_loop_btn = QPushButton("移入循环")
        self._move_into_loop_btn.clicked.connect(self._move_into_loop)
        btn_layout.addWidget(self._move_into_loop_btn)

        self._move_out_loop_btn = QPushButton("移出循环")
        self._move_out_loop_btn.clicked.connect(self._move_out_of_loop)
        btn_layout.addWidget(self._move_out_loop_btn)

        btn_layout.addStretch()
        steps_layout.addLayout(btn_layout)

        # 步骤树（支持循环嵌套）
        self._steps_tree = _TaskStepTreeWidget()
        self._steps_tree.setHeaderLabels(["步骤"])
        self._steps_tree.setMinimumHeight(200)
        self._steps_tree.setToolTip("支持鼠标拖动一个或多个步骤到指定位置；拖到循环步骤上可移入循环内部")
        self._steps_tree.itemDoubleClicked.connect(self._edit_step)
        self._steps_tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self._steps_tree.stepsDropped.connect(self._on_steps_tree_dropped)
        steps_layout.addWidget(self._steps_tree)

        steps_tab = QWidget()
        steps_tab_layout = QVBoxLayout(steps_tab)
        steps_tab_layout.setContentsMargins(0, 0, 0, 0)
        steps_tab_layout.addWidget(steps_group, 1)

        data_tabs.addTab(struct_tab, "结构体")
        data_tabs.addTab(params_tab, "变量")
        data_tabs.addTab(steps_tab, "执行步骤")
        data_tabs.setCurrentWidget(steps_tab)

        layout.addWidget(data_tabs, 1)

        # 底部按钮
        bottom_btn_layout = QHBoxLayout()
        bottom_btn_layout.addStretch()

        self._ok_btn = QPushButton("OK")
        self._ok_btn.clicked.connect(self._on_accept)
        bottom_btn_layout.addWidget(self._ok_btn)

        self._save_btn = QPushButton("保存")
        self._save_btn.clicked.connect(self._save_task)
        bottom_btn_layout.addWidget(self._save_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        bottom_btn_layout.addWidget(self._cancel_btn)

        layout.addLayout(bottom_btn_layout)

    def _load_data(self):
        """加载任务数据"""
        self._name_edit.setText(self._task.name if self._task.name != "未命名任务" else "")
        self._desc_edit.setText(self._task.description)
        self._loop_spin.setValue(self._task.loop_count)
        self._load_structs()
        self._load_params()
        self._refresh_steps_list()

    def _load_structs(self):
        self._structs_table.setRowCount(0)
        for struct_def in self._task.struct_defs:
            row = self._structs_table.rowCount()
            self._structs_table.insertRow(row)
            self._structs_table.setItem(row, 0, QTableWidgetItem(struct_def.name))
            self._structs_table.setItem(
                row,
                1,
                QTableWidgetItem(", ".join(
                    f"{field_def.name}:{STRUCT_FIELD_TYPE_LABELS.get(field_def.field_type, field_def.field_type)}"
                    for field_def in struct_def.fields
                )),
            )

    def _sync_struct_param_values(self, struct_name: str):
        struct_def = self._task.get_struct_def(struct_name)
        if not struct_def:
            return
        for param in self._task.parameters:
            if get_struct_name_from_type(param.param_type) != struct_name:
                continue
            if is_struct_param_type(param.param_type):
                param.value = _normalize_struct_item(struct_def, param.value)
            elif is_struct_array_param_type(param.param_type):
                if not isinstance(param.value, list):
                    param.value = []
                    continue
                param.value = [_normalize_struct_item(struct_def, item) for item in param.value if isinstance(item, dict)]

    def _add_struct(self):
        dlg = StructEditDialog(
            existing_names=[struct_def.name for struct_def in self._task.struct_defs],
            parent=self,
        )
        if dlg.exec() == QDialog.Accepted:
            self._task.struct_defs.append(dlg.get_struct_def())
            self._load_structs()

    def _edit_struct(self):
        row = self._structs_table.currentRow()
        if row < 0 or row >= len(self._task.struct_defs):
            return
        old_struct = self._task.struct_defs[row]
        dlg = StructEditDialog(
            struct_def=old_struct,
            existing_names=[struct_def.name for struct_def in self._task.struct_defs],
            parent=self,
        )
        if dlg.exec() == QDialog.Accepted:
            new_struct = dlg.get_struct_def()
            self._task.struct_defs[row] = new_struct
            if old_struct.name != new_struct.name:
                for param in self._task.parameters:
                    if param.param_type == make_struct_param_type(old_struct.name):
                        param.param_type = make_struct_param_type(new_struct.name)
                    elif param.param_type == make_struct_array_param_type(old_struct.name):
                        param.param_type = make_struct_array_param_type(new_struct.name)
            self._sync_struct_param_values(new_struct.name)
            self._load_structs()
            self._load_params()

    def _del_struct(self):
        row = self._structs_table.currentRow()
        if row < 0 or row >= len(self._task.struct_defs):
            return
        struct_def = self._task.struct_defs[row]
        used_params = [
            param.name for param in self._task.parameters
            if get_struct_name_from_type(param.param_type) == struct_def.name
        ]
        if used_params:
            QMessageBox.warning(
                self,
                "提示",
                f"结构体 '{struct_def.name}' 仍被这些参数使用：{', '.join(used_params)}",
            )
            return
        self._task.struct_defs.pop(row)
        self._load_structs()

    def _load_params(self):
        """加载参数到表格（支持新的 List[TaskParameter] 格式）"""
        self._params_table.setRowCount(0)
        for p in self._task.parameters:
            row = self._params_table.rowCount()
            self._params_table.insertRow(row)
            self._params_table.setItem(row, 0, QTableWidgetItem(p.name))
            self._params_table.setItem(row, 1, QTableWidgetItem(_param_type_display_text(p)))
            self._params_table.setItem(row, 2, QTableWidgetItem(_format_param_value(p)))
            persist_item = QTableWidgetItem("是" if p.persist else "否")
            self._params_table.setItem(row, 3, persist_item)

    def _add_param(self):
        """添加参数 — 弹出参数编辑对话框"""
        dlg = ParamEditDialog(task=self._task, parent=self)
        if dlg.exec() == QDialog.Accepted:
            param = dlg.get_param()
            if param.name:
                self._task.parameters.append(param)
                self._load_params()
                self._auto_save_param_changes()

    def _edit_param(self):
        """编辑选中的参数"""
        row = self._params_table.currentRow()
        if row < 0 or row >= len(self._task.parameters):
            return
        dlg = ParamEditDialog(self._task.parameters[row], task=self._task, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._task.parameters[row] = dlg.get_param()
            self._load_params()
            self._auto_save_param_changes()

    def _del_param(self):
        """删除选中的参数行"""
        rows = set(item.row() for item in self._params_table.selectedItems())
        for row in sorted(rows, reverse=True):
            if row < len(self._task.parameters):
                self._task.parameters.pop(row)
        self._load_params()

    def _get_params(self) -> List[TaskParameter]:
        """返回当前参数列表"""
        return list(self._task.parameters)

    # ── 共用的步骤描述生成 ──
    @staticmethod
    def _step_text(step: SingleTask, index: int, task_steps: Optional[List[SingleTask]] = None,
                   include_step_id: bool = False) -> str:
        return _format_step_brief_text(
            step,
            index,
            task_steps=task_steps,
            include_step_id=include_step_id,
        )

    def _refresh_steps_list(self):
        """刷新步骤树"""
        current_item = self._steps_tree.currentItem()
        selected_step_id = ""
        if current_item is not None:
            selected_step_id = current_item.data(0, STEP_ID_ROLE) or current_item.data(0, Qt.UserRole) or ""

        self._steps_tree.clear()
        self._step_map = {}  # step.id -> (parent_list, index_in_list)

        def _add_items(parent_item: Optional[QTreeWidgetItem], step_list: List[SingleTask]):
            for index, step in enumerate(step_list, start=1):
                text = self._step_text(step, index, self._task.steps, include_step_id=True)
                item = QTreeWidgetItem([text])
                item.setData(0, Qt.UserRole, step.id)
                item.setData(0, STEP_ID_ROLE, step.id)
                item_flags = item.flags() | Qt.ItemIsDragEnabled
                if step.is_loop:
                    item_flags |= Qt.ItemIsDropEnabled
                else:
                    item_flags &= ~Qt.ItemIsDropEnabled
                item.setFlags(item_flags)
                if parent_item is None:
                    self._steps_tree.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)
                self._step_map[step.id] = (step_list, index - 1)

                if step.is_loop and step.children:
                    _add_items(item, step.children)
                    item.setExpanded(True)

        _add_items(None, self._task.steps)
        self._apply_step_highlight()
        if selected_step_id:
            self._select_step_in_tree(selected_step_id)

    def _select_step_in_tree(self, step_id: str):
        if not step_id:
            return
        for item in self._iter_step_tree_items():
            item_step_id = item.data(0, STEP_ID_ROLE) or item.data(0, Qt.UserRole)
            if item_step_id != step_id:
                continue
            parent = item.parent()
            while parent is not None:
                parent.setExpanded(True)
                parent = parent.parent()
            self._steps_tree.setCurrentItem(item)
            self._steps_tree.scrollToItem(item)
            return

    def _select_steps_in_tree(self, step_ids: List[str]):
        if not step_ids:
            return
        target_ids = set(step_ids)
        self._steps_tree.clearSelection()
        first_item = None
        for item in self._iter_step_tree_items():
            item_step_id = item.data(0, STEP_ID_ROLE) or item.data(0, Qt.UserRole)
            if item_step_id not in target_ids:
                continue
            parent = item.parent()
            while parent is not None:
                parent.setExpanded(True)
                parent = parent.parent()
            item.setSelected(True)
            if first_item is None:
                first_item = item

        if first_item is not None:
            self._steps_tree.setCurrentItem(first_item)
            self._steps_tree.scrollToItem(first_item)

    def _iter_step_tree_items(self):
        def _walk(item: QTreeWidgetItem):
            yield item
            for child_index in range(item.childCount()):
                yield from _walk(item.child(child_index))

        for top_index in range(self._steps_tree.topLevelItemCount()):
            top_item = self._steps_tree.topLevelItem(top_index)
            yield from _walk(top_item)

    def _apply_step_highlight(self):
        highlight_bg = QBrush(QColor("#fff1b8"))
        highlight_fg = QBrush(QColor("#8c5a00"))
        empty_brush = QBrush()
        for item in self._iter_step_tree_items():
            item.setBackground(0, empty_brush)
            item.setForeground(0, empty_brush)
            item_step_id = item.data(0, STEP_ID_ROLE) or item.data(0, Qt.UserRole)
            if self._highlighted_step_id and item_step_id == self._highlighted_step_id:
                item.setBackground(0, highlight_bg)
                item.setForeground(0, highlight_fg)
                parent = item.parent()
                while parent is not None:
                    parent.setExpanded(True)
                    parent = parent.parent()
                self._steps_tree.scrollToItem(item)

    def _highlight_jump_target_step(self, step_id: str):
        self._highlighted_step_id = step_id or ""
        self._apply_step_highlight()

    def _find_step_by_id(self, step_id: str):
        """根据 ID 找到步骤及其所在列表和索引"""
        found = self._find_step_context(step_id)
        if not found:
            return None, None, -1
        return found["step"], found["parent_list"], found["index"]

    def _find_step_context(self, step_id: str, step_list: Optional[List[SingleTask]] = None,
                           parent_loop: Optional[SingleTask] = None,
                           parent_loop_list: Optional[List[SingleTask]] = None,
                           parent_loop_index: int = -1):
        current_list = self._task.steps if step_list is None else step_list
        for index, step in enumerate(current_list):
            if step.id == step_id:
                return {
                    "step": step,
                    "parent_list": current_list,
                    "index": index,
                    "parent_loop": parent_loop,
                    "parent_loop_list": parent_loop_list,
                    "parent_loop_index": parent_loop_index,
                }
            if step.is_loop and step.children:
                found = self._find_step_context(
                    step_id,
                    step.children,
                    parent_loop=step,
                    parent_loop_list=current_list,
                    parent_loop_index=index,
                )
                if found:
                    return found
        return None

    @staticmethod
    def _step_contains_target(step: SingleTask, target_id: str) -> bool:
        for child in step.children:
            if child.id == target_id or TaskEditDialog._step_contains_target(child, target_id):
                return True
        return False

    def _resolve_drag_destination(self, target_step_id: str, drop_position: str):
        if drop_position == "viewport" or not target_step_id:
            return self._task.steps, len(self._task.steps)

        target_context = self._find_step_context(target_step_id)
        if not target_context:
            return self._task.steps, len(self._task.steps)

        target_step = target_context["step"]
        if drop_position == "on" and target_step.is_loop:
            return target_step.children, len(target_step.children)
        if drop_position == "above":
            return target_context["parent_list"], target_context["index"]
        return target_context["parent_list"], target_context["index"] + 1

    def _on_steps_tree_dropped(self, step_ids: List[str], target_step_id: str, drop_position: str):
        move_ids = [step_id for step_id in step_ids if step_id]
        if not move_ids:
            return

        contexts = []
        for step_id in move_ids:
            context = self._find_step_context(step_id)
            if not context:
                return
            contexts.append(context)

        moving_steps = [context["step"] for context in contexts]
        if target_step_id and any(
            step.id == target_step_id or self._step_contains_target(step, target_step_id)
            for step in moving_steps
        ):
            self._refresh_steps_list()
            self._select_steps_in_tree(move_ids)
            return

        target_list, insert_index = self._resolve_drag_destination(target_step_id, drop_position)

        if len(contexts) > 1 and drop_position == "on" and target_step_id:
            target_context = self._find_step_context(target_step_id)
            if target_context and not target_context["step"].is_loop:
                drop_position = "below"

        same_target_list_contexts = [context for context in contexts if context["parent_list"] is target_list]
        if same_target_list_contexts:
            for context in same_target_list_contexts:
                if context["index"] < insert_index:
                    insert_index -= 1

        removal_groups = []
        for context in contexts:
            group = next((item for item in removal_groups if item["parent_list"] is context["parent_list"]), None)
            if group is None:
                group = {"parent_list": context["parent_list"], "indexes": []}
                removal_groups.append(group)
            group["indexes"].append(context["index"])

        for group in removal_groups:
            for index in sorted(group["indexes"], reverse=True):
                group["parent_list"].pop(index)

        for offset, step in enumerate(moving_steps):
            target_list.insert(insert_index + offset, step)

        self._refresh_steps_list()
        self._select_steps_in_tree(move_ids)

    def _get_selected_step(self):
        """获取当前选中步骤的 (step, parent_list, index)"""
        current = self._steps_tree.currentItem()
        if current is None:
            return None, None, -1
        step_id = current.data(0, Qt.UserRole)
        return self._find_step_by_id(step_id)

    def _add_step(self):
        """添加普通步骤（插入到选中步骤后面）"""
        dlg = StepEditDialog(task_params=self._task.parameters, task_steps=self._task.steps, task=self._task, parent=self)
        if dlg.exec() == QDialog.Accepted:
            step = dlg.get_step()
            sel_step, sel_list, sel_idx = self._get_selected_step()
            if sel_step is None:
                # 无选中，追加到末尾
                self._task.steps.append(step)
            elif sel_step.is_loop:
                # 选中的是循环步骤本身，添加为其子步骤末尾
                sel_step.children.append(step)
            elif sel_list is not self._task.steps:
                # 选中的是循环内的子步骤，插入到该子步骤后面
                sel_list.insert(sel_idx + 1, step)
            else:
                # 选中的是顶层普通步骤，插入到其后面
                self._task.steps.insert(sel_idx + 1, step)
            self._refresh_steps_list()

    def _add_loop_step(self):
        """添加循环步骤（插入到选中步骤后面）"""
        # 检查是否有数组参数
        array_params = [p for p in self._task.parameters if is_array_param_type(p.param_type)]
        if not array_params:
            QMessageBox.warning(self, "提示", "当前任务没有数组或结构体数组参数，请先添加参数")
            return
        
        dlg = LoopStepEditDialog(task_params=self._task.parameters, task=self._task, parent=self)
        if dlg.exec() == QDialog.Accepted:
            step = dlg.get_step()
            sel_step, sel_list, sel_idx = self._get_selected_step()
            if sel_step is None:
                self._task.steps.append(step)
            elif sel_step.is_loop:
                sel_step.children.append(step)
            else:
                sel_list.insert(sel_idx + 1, step)
            self._refresh_steps_list()

    def _edit_step(self):
        """编辑步骤"""
        step, parent_list, idx = self._get_selected_step()
        if step is None:
            QMessageBox.warning(self, "提示", "请先选择一个步骤")
            return
        if step.is_loop:
            # 编辑循环步骤
            dlg = LoopStepEditDialog(step, task_params=self._task.parameters, task=self._task, parent=self)
            if dlg.exec() == QDialog.Accepted:
                parent_list[idx] = dlg.get_step()
            self._refresh_steps_list()
            return
        
        # 编辑普通步骤
        dlg = StepEditDialog(step, task_params=self._task.parameters, task_steps=self._task.steps, task=self._task, parent=self)
        if dlg.exec() == QDialog.Accepted:
            parent_list[idx] = dlg.get_step()
            self._refresh_steps_list()

    def _delete_step(self):
        """删除选中的步骤"""
        selected = self._steps_tree.selectedItems()
        if not selected:
            QMessageBox.warning(self, "提示", "请先选择要删除的步骤")
            return
        step_ids = [item.data(0, Qt.UserRole) for item in selected]
        reply = QMessageBox.question(self, "确认删除", f"确定要删除选中的 {len(step_ids)} 个步骤吗？")
        if reply == QMessageBox.Yes:
            for sid in step_ids:
                step, plist, idx = self._find_step_by_id(sid)
                if step and plist is not None and idx >= 0:
                    plist.pop(idx)
            self._refresh_steps_list()

    def _copy_steps(self):
        """复制选中的步骤到待粘贴缓存。"""

        def _has_selected_ancestor(item: QTreeWidgetItem) -> bool:
            parent = item.parent()
            while parent is not None:
                if parent.isSelected():
                    return True
                parent = parent.parent()
            return False

        selected = [
            item for item in self._iter_step_tree_items()
            if item.isSelected() and not _has_selected_ancestor(item)
        ]
        if not selected:
            QMessageBox.warning(self, "提示", "请先选择要复制的步骤")
            return

        copied_steps = []
        for item in selected:
            sid = item.data(0, Qt.UserRole)
            context = self._find_step_context(sid)
            if not context:
                continue

            copied_steps.append(copy.deepcopy(context["step"]))

        if not copied_steps:
            QMessageBox.warning(self, "提示", "未找到可复制的步骤")
            return

        self._copied_steps = copied_steps
        self._paste_step_btn.setEnabled(True)

    @staticmethod
    def _reset_step_ids(target_step: SingleTask):
        import uuid as _uuid

        target_step.id = _uuid.uuid4().hex[:8]
        for child in target_step.children:
            TaskEditDialog._reset_step_ids(child)

    def _paste_steps(self):
        """将已复制的步骤粘贴到当前选中步骤后面。"""
        if not self._copied_steps:
            QMessageBox.warning(self, "提示", "请先复制步骤")
            self._paste_step_btn.setEnabled(False)
            return

        current_step, parent_list, index = self._get_selected_step()
        if parent_list is None:
            target_list = self._task.steps
            insert_index = len(target_list)
        else:
            target_list = parent_list
            insert_index = index + 1 if current_step is not None else len(target_list)

        new_steps = []
        new_step_ids = []
        for template_step in self._copied_steps:
            new_step = copy.deepcopy(template_step)
            self._reset_step_ids(new_step)
            new_steps.append(new_step)
            new_step_ids.append(new_step.id)

        for offset, new_step in enumerate(new_steps):
            target_list.insert(insert_index + offset, new_step)

        self._refresh_steps_list()
        self._select_steps_in_tree(new_step_ids)

    def _move_step_up(self):
        """上移步骤"""
        step, plist, idx = self._get_selected_step()
        if step is None or idx <= 0:
            return
        plist[idx], plist[idx - 1] = plist[idx - 1], plist[idx]
        self._refresh_steps_list()

    def _move_step_down(self):
        """下移步骤"""
        step, plist, idx = self._get_selected_step()
        if step is None or plist is None or idx >= len(plist) - 1:
            return
        plist[idx], plist[idx + 1] = plist[idx + 1], plist[idx]
        self._refresh_steps_list()

    def _move_into_loop(self):
        """把选中步骤移入同层级相邻或最近的循环步骤"""
        step, plist, idx = self._get_selected_step()
        if step is None or plist is None:
            return

        loop_step = None
        insert_at_front = False

        if idx > 0 and plist[idx - 1].is_loop:
            loop_step = plist[idx - 1]
        elif idx < len(plist) - 1 and plist[idx + 1].is_loop:
            loop_step = plist[idx + 1]
            insert_at_front = True
        else:
            for i in range(idx - 1, -1, -1):
                if plist[i].is_loop:
                    loop_step = plist[i]
                    break
            if loop_step is None:
                for i in range(idx + 1, len(plist)):
                    if plist[i].is_loop:
                        loop_step = plist[i]
                        insert_at_front = True
                        break

        if loop_step is None:
            QMessageBox.warning(self, "提示", "同层级没有找到可移入的循环步骤")
            return

        plist.pop(idx)
        if insert_at_front:
            loop_step.children.insert(0, step)
        else:
            loop_step.children.append(step)
        self._refresh_steps_list()

    def _move_out_of_loop(self):
        """把选中的子步骤移出循环"""
        current = self._steps_tree.currentItem()
        if current is None:
            return
        step_id = current.data(0, STEP_ID_ROLE) or current.data(0, Qt.UserRole)
        context = self._find_step_context(step_id)
        if not context or context["parent_loop"] is None:
            return  # 已经在顶层

        step = context["step"]
        parent_list = context["parent_list"]
        parent_index = context["index"]
        parent_loop_list = context["parent_loop_list"]
        parent_loop_index = context["parent_loop_index"]
        if parent_loop_list is None or parent_loop_index < 0:
            return

        parent_list.pop(parent_index)
        parent_loop_list.insert(parent_loop_index + 1, step)
        self._refresh_steps_list()

    def _on_accept(self):
        """确认按钮"""
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入任务名称")
            return
        if not self._task.steps:
            QMessageBox.warning(self, "提示", "请至少添加一个步骤")
            return
        self.accept()

    def _save_task(self):
        """保存当前任务但不关闭对话框。"""
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入任务名称")
            return
        if not self._task.steps:
            QMessageBox.warning(self, "提示", "请至少添加一个步骤")
            return
        if self._task_storage is None:
            QMessageBox.warning(self, "提示", "当前不可保存任务")
            return

        task = self.get_task()
        if not self._task_storage.save(task):
            QMessageBox.warning(self, "提示", "保存任务失败")
            return

        self._is_existing_task = True
        self.setWindowTitle("编辑计划任务")
        self.task_saved.emit(task.id)
        QMessageBox.information(self, "提示", "已经保存")

    def get_task(self) -> PlanTask:
        """获取编辑后的任务"""
        self._task.name = self._name_edit.text().strip() or "未命名任务"
        self._task.description = self._desc_edit.text().strip()
        self._task.loop_count = self._loop_spin.value()
        self._task.parameters = self._get_params()
        return self._task


class TaskPanel(QWidget):
    """
    计划任务管理面板

    用于主窗口的选项卡，提供完整的计划任务管理和执行功能。
    """

    # 请求获取当前选中的窗口信息
    request_window_info = Signal()
    # 日志信号
    log_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._storage = TaskStorage()
        self._executor = TaskExecutor()

        # 外部依赖（由主窗口注入）
        self._capture = None
        self._ocr = None
        self._recognition = None
        self._ai_tile_recognition = None
        self._input = None
        self._bg_input_class = None
        self._window_manager = None
        self._current_hwnd: Optional[int] = None

        # 线程安全的信号桥
        self._bridge = _ExecutorSignalBridge(self)
        self._step_id_to_item = {}
        self._active_preview_step_id = ""
        self._jump_preview_step_id = ""
        self._active_log_item = None
        self._active_task_id_for_logs: Optional[str] = None
        self._ai_tile_warmup_lock = threading.Lock()
        self._ai_tile_warmup_pending: set[str] = set()
        self._ai_tile_warmup_running = False
        self._ai_tile_warmup_last_error = ""
        self._pending_ai_start_mode = ""
        self._pending_ai_start_task_id = ""
        self._pending_ai_start_step_id = ""
        self._bridge.sig_log.connect(self._append_log)
        self._bridge.sig_task_started.connect(
            lambda name: self._update_ui_running(True, name)
        )
        self._bridge.sig_task_finished.connect(
            lambda name, ok: self._update_ui_running(
                False, f"{name} - {'完成' if ok else '停止/失败'}"
            )
        )
        self._bridge.sig_step_started.connect(self._on_step_started_main)
        self._bridge.sig_step_retried.connect(self._on_step_retried_main)
        self._bridge.sig_step_paused.connect(self._on_step_paused_main)
        self._bridge.sig_ai_warmup_tick.connect(self._on_ai_warmup_tick_main)
        self._bridge.sig_highlight_match.connect(self._show_recognition_highlight)
        self._bridge.sig_highlight_matches.connect(self._show_recognition_highlights)
        self._bridge.sig_highlight_point.connect(self._show_highlight_point)
        self._highlight_overlay = _RecognitionHighlightOverlay()
        self._point_overlay = _RecognitionHighlightOverlay()

        self._init_ui()
        self._connect_executor()
        self._refresh_task_list()

    def setup_dependencies(self, capture, ocr, recognition, ai_tile_recognition, input_sim,
                           bg_input_class, window_manager):
        """注入依赖"""
        self._capture = capture
        self._ocr = ocr
        self._recognition = recognition
        self._ai_tile_recognition = ai_tile_recognition
        self._input = input_sim
        self._bg_input_class = bg_input_class
        self._window_manager = window_manager

        task_id = self._get_selected_task_id()
        if task_id:
            self._queue_ai_tile_warmup_for_task(self._storage.load(task_id))
        self._refresh_ai_warmup_status()

    def set_current_window(self, hwnd: Optional[int]):
        """设置当前目标窗口"""
        self._current_hwnd = hwnd

    def _get_selected_task(self) -> Optional[PlanTask]:
        task_id = self._get_selected_task_id()
        if not task_id:
            return None
        return self._storage.load(task_id)

    @staticmethod
    def _iter_task_steps(steps: List[SingleTask]):
        for step in steps or []:
            yield step
            if getattr(step, "is_loop", False) and getattr(step, "children", None):
                yield from TaskPanel._iter_task_steps(step.children)

    def _collect_ai_tile_warmup_targets(self, task: Optional[PlanTask]) -> list[str]:
        if task is None:
            return []

        targets: list[str] = []
        for step in self._iter_task_steps(task.steps):
            if str(getattr(step, "recognition_type", "") or "") != "ai_tile":
                continue

            raw_target = str(getattr(step, "recognition_target", "") or "").strip()
            if not raw_target or "{" in raw_target or "}" in raw_target:
                targets.append("")
            else:
                targets.append(raw_target)
        return targets

    def _resolve_ai_tile_warmup_targets(self, task: Optional[PlanTask]) -> list[str]:
        if self._ai_tile_recognition is None:
            return []

        resolved: list[str] = []
        seen: set[str] = set()
        for raw_target in self._collect_ai_tile_warmup_targets(task):
            model_path = str(self._ai_tile_recognition.resolve_model_path(raw_target or None))
            if model_path in seen:
                continue
            seen.add(model_path)
            resolved.append(model_path)
        return resolved

    def _get_ai_warmup_progress(self, task: Optional[PlanTask]) -> dict[str, int]:
        if self._ai_tile_recognition is None:
            return {"requested": 0, "warmed": 0, "pending": 0}
        return self._ai_tile_recognition.get_warmup_progress(self._resolve_ai_tile_warmup_targets(task))

    def _is_ai_warmup_ready_for_task(self, task: Optional[PlanTask]) -> bool:
        progress = self._get_ai_warmup_progress(task)
        return int(progress.get("requested", 0) or 0) == 0 or int(progress.get("pending", 0) or 0) == 0

    def _has_pending_ai_start(self) -> bool:
        return bool(self._pending_ai_start_mode and self._pending_ai_start_task_id)

    def _clear_pending_ai_start(self) -> None:
        self._pending_ai_start_mode = ""
        self._pending_ai_start_task_id = ""
        self._pending_ai_start_step_id = ""

    def _set_pending_ai_start(self, task: PlanTask, mode: str, step_id: str = "") -> None:
        self._pending_ai_start_mode = mode
        self._pending_ai_start_task_id = task.id
        self._pending_ai_start_step_id = step_id or ""

    def _refresh_ai_warmup_status(self, task: Optional[PlanTask] = None) -> None:
        task = task or self._get_selected_task()
        if task is None:
            self._ai_warmup_status.setText("AI 预热: 未选择任务")
            self._ai_warmup_status.setStyleSheet("color: gray;")
            return

        targets = self._resolve_ai_tile_warmup_targets(task)
        if not targets:
            self._ai_warmup_status.setText("AI 预热: 当前任务无需预热")
            self._ai_warmup_status.setStyleSheet("color: gray;")
            return

        progress = self._get_ai_warmup_progress(task)
        requested = int(progress.get("requested", 0) or 0)
        warmed = int(progress.get("warmed", 0) or 0)
        pending = int(progress.get("pending", 0) or 0)
        waiting_suffix = "，完成后自动执行" if self._pending_ai_start_task_id == task.id else ""

        if pending <= 0:
            self._ai_warmup_status.setText(f"AI 预热: 已就绪 {warmed}/{requested}")
            self._ai_warmup_status.setStyleSheet("color: #2e7d32;")
            return

        if self._ai_tile_warmup_running:
            self._ai_warmup_status.setText(f"AI 预热: 后台预热中 {warmed}/{requested}{waiting_suffix}")
            self._ai_warmup_status.setStyleSheet("color: #1565c0;")
            return

        if self._ai_tile_warmup_last_error:
            self._ai_warmup_status.setText(f"AI 预热: 未完成 {warmed}/{requested}，最近失败：{self._ai_tile_warmup_last_error}")
            self._ai_warmup_status.setStyleSheet("color: #c62828;")
            return

        self._ai_warmup_status.setText(f"AI 预热: 待预热 {warmed}/{requested}")
        self._ai_warmup_status.setStyleSheet("color: #ef6c00;")

    def _start_task_execution_now(self, task: PlanTask, mode: str = "run", step_id: str = "") -> None:
        self._active_task_id_for_logs = task.id

        self._executor.setup(
            hwnd=self._current_hwnd,
            capture=self._capture,
            ocr=self._ocr,
            recognition=self._recognition,
            ai_tile_recognition=self._ai_tile_recognition,
            input_sim=self._input,
            bg_input_class=self._bg_input_class,
            window_manager=self._window_manager,
            task_storage=self._storage,
        )

        if mode == "step":
            self._executor.start_step_mode(task)
            self._pause_btn.setText("⏸ 暂停")
            self._exec_status.setText("状态: 单步执行中")
            self._step_btn.setEnabled(False)
            return

        if mode == "run_to":
            self._executor.start_run_to_step(task, step_id)
            self._exec_status.setText("状态: 执行到指定步骤中")
            return

        self._executor.start(task)

    def _request_task_start(self, task: PlanTask, mode: str = "run", step_id: str = "") -> bool:
        self._queue_ai_tile_warmup_for_task(task)
        self._refresh_ai_warmup_status(task)

        if self._is_ai_warmup_ready_for_task(task):
            self._clear_pending_ai_start()
            self._start_task_execution_now(task, mode=mode, step_id=step_id)
            return True

        self._set_pending_ai_start(task, mode, step_id)
        self._exec_status.setText("状态: 等待 AI 预热完成")
        self._run_btn.setEnabled(False)
        self._step_btn.setEnabled(False)
        self._pause_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._refresh_ai_warmup_status(task)
        self._append_log("[AI地块] 正在后台预热模型，完成后自动开始执行")
        return False

    def _queue_ai_tile_warmup_for_task(self, task: Optional[PlanTask]) -> None:
        if self._ai_tile_recognition is None:
            return

        targets = self._collect_ai_tile_warmup_targets(task)
        if not targets:
            return

        should_start = False
        with self._ai_tile_warmup_lock:
            self._ai_tile_warmup_last_error = ""
            self._ai_tile_warmup_pending.update(targets)
            if not self._ai_tile_warmup_running:
                self._ai_tile_warmup_running = True
                should_start = True

        if should_start:
            threading.Thread(target=self._run_ai_tile_warmup_worker, daemon=True).start()

    def _run_ai_tile_warmup_worker(self) -> None:
        while True:
            with self._ai_tile_warmup_lock:
                targets = list(self._ai_tile_warmup_pending)
                self._ai_tile_warmup_pending.clear()
                if not targets:
                    self._ai_tile_warmup_running = False
                    return

            try:
                summary = self._ai_tile_recognition.warmup_model_paths(targets)
            except Exception as exc:
                self._ai_tile_warmup_last_error = str(exc)
                self._bridge.sig_log.emit(f"[AI地块] 后台 warm-up 失败: {exc}")
                self._bridge.sig_ai_warmup_tick.emit()
                continue

            warmed = int(summary.get("warmed", 0) or 0)
            failed = list(summary.get("failed", []) or [])
            self._ai_tile_warmup_last_error = failed[0] if failed else ""
            if warmed > 0:
                self._bridge.sig_log.emit(f"[AI地块] 后台 warm-up 完成：已预热 {warmed} 个模型")
            for message in failed[:3]:
                self._bridge.sig_log.emit(f"[AI地块] 后台 warm-up 失败: {message}")
            self._bridge.sig_ai_warmup_tick.emit()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        self._task_workspace_tabs = QTabWidget()

        # === 任务列表页签 ===
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        list_group = QGroupBox("计划任务列表")
        list_layout = QVBoxLayout(list_group)

        self._task_list = QListWidget()
        self._task_list.currentItemChanged.connect(self._on_task_selected)
        list_layout.addWidget(self._task_list)

        # 任务操作按钮
        task_btn_layout = QHBoxLayout()

        self._new_task_btn = QPushButton("新建任务")
        self._new_task_btn.clicked.connect(self._new_task)
        task_btn_layout.addWidget(self._new_task_btn)

        self._edit_task_btn = QPushButton("编辑任务")
        self._edit_task_btn.clicked.connect(self._edit_task)
        task_btn_layout.addWidget(self._edit_task_btn)

        self._del_task_btn = QPushButton("删除任务")
        self._del_task_btn.clicked.connect(self._delete_task)
        task_btn_layout.addWidget(self._del_task_btn)

        list_layout.addLayout(task_btn_layout)

        # 导入导出
        io_btn_layout = QHBoxLayout()
        self._import_btn = QPushButton("导入")
        self._import_btn.clicked.connect(self._import_task)
        io_btn_layout.addWidget(self._import_btn)

        self._export_btn = QPushButton("导出")
        self._export_btn.clicked.connect(self._export_task)
        io_btn_layout.addWidget(self._export_btn)

        io_btn_layout.addStretch()
        list_layout.addLayout(io_btn_layout)

        left_layout.addWidget(list_group)
        self._task_list_tab = left_panel
        self._task_workspace_tabs.addTab(self._task_list_tab, "任务列表")

        # === 任务详情页签 ===
        middle_panel = QWidget()
        middle_layout = QVBoxLayout(middle_panel)
        middle_layout.setContentsMargins(0, 0, 0, 0)

        # 任务信息
        info_group = QGroupBox("任务详情")
        info_layout = QVBoxLayout(info_group)

        self._info_label = QLabel("请选择一个任务")
        self._info_label.setWordWrap(True)
        info_layout.addWidget(self._info_label)

        step_tip_layout = QHBoxLayout()
        step_tip = QLabel("双击步骤可直接修改，保存后立即生效。")
        step_tip.setStyleSheet("color: gray;")
        step_tip_layout.addWidget(step_tip)
        step_tip_layout.addStretch()

        self._detail_edit_task_btn = QPushButton("编辑任务")
        self._detail_edit_task_btn.clicked.connect(self._edit_task)
        step_tip_layout.addWidget(self._detail_edit_task_btn)

        self._edit_step_btn = QPushButton("编辑选中步骤")
        self._edit_step_btn.setEnabled(False)
        self._edit_step_btn.clicked.connect(self._edit_selected_step_from_preview)
        step_tip_layout.addWidget(self._edit_step_btn)
        info_layout.addLayout(step_tip_layout)

        self._steps_preview = QTreeWidget()
        self._steps_preview.setHeaderHidden(True)
        self._steps_preview.setExpandsOnDoubleClick(False)
        self._steps_preview.setContextMenuPolicy(Qt.CustomContextMenu)
        self._steps_preview.customContextMenuRequested.connect(self._show_step_context_menu)
        self._steps_preview.itemDoubleClicked.connect(self._on_step_item_double_clicked)
        self._steps_preview.itemSelectionChanged.connect(self._sync_step_action_state)
        info_layout.addWidget(self._steps_preview)

        middle_layout.addWidget(info_group)

        # 执行控制
        exec_group = QGroupBox("执行控制")
        exec_layout = QVBoxLayout(exec_group)

        exec_btn_layout = QHBoxLayout()

        self._run_btn = QPushButton("▶ 执行任务")
        self._run_btn.setMinimumHeight(40)
        self._run_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }"
            "QPushButton:hover { background-color: #45a049; }"
            "QPushButton:disabled { background-color: #cccccc; }"
        )
        self._run_btn.clicked.connect(self._run_task)
        exec_btn_layout.addWidget(self._run_btn)

        self._pause_btn = QPushButton("⏸ 暂停")
        self._pause_btn.setMinimumHeight(40)
        self._pause_btn.setEnabled(False)
        self._pause_btn.clicked.connect(self._toggle_pause)
        exec_btn_layout.addWidget(self._pause_btn)

        self._step_btn = QPushButton("▶| 执行一步")
        self._step_btn.setMinimumHeight(40)
        self._step_btn.setStyleSheet(
            "QPushButton { background-color: #2196F3; color: white; font-weight: bold; }"
            "QPushButton:hover { background-color: #1976D2; }"
            "QPushButton:disabled { background-color: #cccccc; }"
        )
        self._step_btn.clicked.connect(self._step_once)
        exec_btn_layout.addWidget(self._step_btn)

        self._stop_btn = QPushButton("⏹ 停止")
        self._stop_btn.setMinimumHeight(40)
        self._stop_btn.setEnabled(False)
        self._stop_btn.setStyleSheet(
            "QPushButton { background-color: #f44336; color: white; font-weight: bold; }"
            "QPushButton:hover { background-color: #d32f2f; }"
            "QPushButton:disabled { background-color: #cccccc; }"
        )
        self._stop_btn.clicked.connect(self._stop_task)
        exec_btn_layout.addWidget(self._stop_btn)

        exec_layout.addLayout(exec_btn_layout)

        # 执行状态
        self._exec_status = QLabel("状态: 空闲")
        exec_layout.addWidget(self._exec_status)

        self._ai_warmup_status = QLabel("AI 预热: 未选择任务")
        self._ai_warmup_status.setWordWrap(True)
        self._ai_warmup_status.setStyleSheet("color: gray;")
        exec_layout.addWidget(self._ai_warmup_status)

        middle_layout.addWidget(exec_group)
        middle_layout.addStretch()
        self._task_detail_tab = middle_panel
        self._task_workspace_tabs.addTab(self._task_detail_tab, "任务详情")

        self._task_list.itemDoubleClicked.connect(
            lambda _item: self._task_workspace_tabs.setCurrentWidget(self._task_detail_tab)
        )

        layout.addWidget(self._task_workspace_tabs, 2)

        # === 右侧：执行日志（占满整个高度） ===
        log_panel = QWidget()
        log_panel_layout = QVBoxLayout(log_panel)
        log_panel_layout.setContentsMargins(0, 0, 0, 0)

        log_group = QGroupBox("执行日志")
        log_layout = QVBoxLayout(log_group)

        self._log_tree = QTreeWidget()
        self._log_tree.setColumnCount(2)
        self._log_tree.setHeaderLabels(["时间", "内容"])
        self._log_tree.setHeaderHidden(True)
        self._log_tree.setUniformRowHeights(False)
        self._log_tree.setWordWrap(False)
        self._log_tree.setTextElideMode(Qt.ElideNone)
        self._log_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._log_tree.header().setStretchLastSection(False)
        self._log_tree.header().setSectionResizeMode(0, QHeaderView.Fixed)
        self._log_tree.setColumnWidth(0, 110)
        self._log_tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self._log_tree.setExpandsOnDoubleClick(False)
        self._log_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._log_tree.itemDoubleClicked.connect(self._toggle_log_item)
        self._log_tree.currentItemChanged.connect(self._on_log_item_changed)
        log_layout.addWidget(self._log_tree)

        self._copy_logs_shortcut = QShortcut(QKeySequence.Copy, self._log_tree)
        self._copy_logs_shortcut.activated.connect(self._copy_selected_logs)

        self._log_detail = QTextEdit()
        self._log_detail.setReadOnly(True)
        self._log_detail.hide()

        log_btn_row = QHBoxLayout()
        copy_log_btn = QPushButton("复制选中日志")
        copy_log_btn.clicked.connect(self._copy_selected_logs)
        log_btn_row.addWidget(copy_log_btn)

        clear_log_btn = QPushButton("清除日志")
        clear_log_btn.clicked.connect(self._clear_logs)
        log_btn_row.addWidget(clear_log_btn)
        log_layout.addLayout(log_btn_row)

        log_panel_layout.addWidget(log_group)

        layout.addWidget(log_panel, 3)

    def _connect_executor(self):
        """连接执行器回调（全部通过信号桥跨线程转发）"""
        self._executor.on_log = lambda msg: self._bridge.sig_log.emit(msg)
        self._executor.on_task_start = lambda t: self._bridge.sig_task_started.emit(t.name)
        self._executor.on_task_finish = lambda t, ok: self._bridge.sig_task_finished.emit(t.name, ok)
        self._executor.on_step_start = lambda idx, s: self._bridge.sig_step_started.emit(
            s.id, s.name if s.name != "未命名步骤" else f"步骤{idx + 1}"
        )
        self._executor.on_step_success = None
        self._executor.on_step_retry = lambda idx, s, cnt: self._bridge.sig_step_retried.emit(
            s.id, s.name if s.name != "未命名步骤" else f"步骤{idx + 1}", cnt
        )
        self._executor.on_step_paused = lambda: self._bridge.sig_step_paused.emit()
        self._executor.on_highlight_match = lambda left, top, width, height, duration: self._bridge.sig_highlight_match.emit(
            left, top, width, height, duration
        )
        self._executor.on_highlight_matches = lambda regions, duration: self._bridge.sig_highlight_matches.emit(
            regions, duration
        )
        self._executor.on_highlight_point = lambda x, y, duration: self._bridge.sig_highlight_point.emit(
            x, y, duration
        )

    def _show_recognition_highlight(self, left: int, top: int, width: int, height: int, duration_ms: int):
        if width <= 0 or height <= 0:
            return
        self._highlight_overlay.show_rect(left, top, width, height, duration_ms)

    def _show_recognition_highlights(self, regions: List[dict], duration_ms: int):
        if not regions:
            return
        self._highlight_overlay.show_rects(regions, duration_ms)

    def _show_highlight_point(self, x: int, y: int, duration_ms: int):
        self._point_overlay.show_point(x, y, duration_ms)

    # ==================== 任务列表操作 ====================

    def _refresh_task_list(self, selected_task_id: Optional[str] = None):
        """刷新任务列表"""
        if selected_task_id is None:
            selected_task_id = self._get_selected_task_id()

        self._task_list.clear()
        selected_item = None
        tasks = self._storage.list_tasks()
        for task in tasks:
            loop_info = f"循环{task.loop_count}次" if task.loop_count > 0 else "无限循环"
            item_text = f"{task.name}  ({len(task.steps)}步, {loop_info})"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, task.id)
            self._task_list.addItem(item)
            if task.id == selected_task_id:
                selected_item = item

        if selected_item is not None:
            self._task_list.setCurrentItem(selected_item)
        elif self._task_list.count() == 0:
            self._info_label.setText("请选择一个任务")
            self._steps_preview.clear()
            self._step_id_to_item.clear()
            self._sync_step_action_state()

    def _get_selected_task_id(self) -> Optional[str]:
        """获取当前选中的任务ID"""
        current = self._task_list.currentItem()
        if current:
            return current.data(Qt.UserRole)
        return None

    def _build_task_info_text(self, task: PlanTask) -> str:
        loop_info = f"循环 {task.loop_count} 次" if task.loop_count > 0 else "无限循环"
        blocked_info = ""
        if task.blocked_coords:
            blocked_info = f"\n封锁坐标: {len(task.blocked_coords)} 个"
        return (
            f"任务名称: {task.name}\n"
            f"描述: {task.description or '无'}\n"
            f"步骤数: {len(task.steps)}\n"
            f"循环: {loop_info}"
            f"{blocked_info}\n"
            f"创建时间: {task.created_time}\n"
            f"修改时间: {task.modified_time}"
        )

    def _populate_steps_preview(self, task: PlanTask):
        """刷新任务详情区的步骤树"""
        self._steps_preview.clear()
        self._step_id_to_item.clear()
        for index, step in enumerate(task.steps, start=1):
            self._add_step_preview_item(None, step, index, task.steps)
        self._apply_preview_step_highlight()

    def _add_step_preview_item(self, parent_item: Optional[QTreeWidgetItem], step: SingleTask, index: int,
                               task_steps: Optional[List[SingleTask]] = None):
        text = TaskEditDialog._step_text(step, index, task_steps)
        item = QTreeWidgetItem([text])
        item.setData(0, STEP_ID_ROLE, step.id)
        self._step_id_to_item[step.id] = item

        if parent_item is None:
            self._steps_preview.addTopLevelItem(item)
        else:
            parent_item.addChild(item)

        if step.is_loop and step.children:
            for child_index, child in enumerate(step.children, start=1):
                self._add_step_preview_item(item, child, child_index, task_steps)
            item.setExpanded(True)

    def _select_step_in_preview(self, step_id: Optional[str]):
        """在详情区选中指定步骤"""
        if not step_id:
            return
        item = self._step_id_to_item.get(step_id)
        if item is None:
            return
        if item.parent() is not None:
            item.parent().setExpanded(True)
        self._steps_preview.setCurrentItem(item)
        self._steps_preview.scrollToItem(item)

    def _apply_preview_step_highlight(self):
        default_bg = QBrush()
        default_fg = QBrush()
        active_bg = QBrush(QColor(144, 238, 144))
        jump_bg = QBrush(QColor("#fff1b8"))
        jump_fg = QBrush(QColor("#8c5a00"))
        merged_bg = QBrush(QColor("#ffd591"))
        merged_fg = QBrush(QColor("#8c5a00"))

        for item in self._step_id_to_item.values():
            item.setBackground(0, default_bg)
            item.setForeground(0, default_fg)

        active_item = self._step_id_to_item.get(self._active_preview_step_id)
        jump_item = self._step_id_to_item.get(self._jump_preview_step_id)

        if active_item is not None:
            active_item.setBackground(0, active_bg)

        if jump_item is not None:
            if jump_item is active_item:
                jump_item.setBackground(0, merged_bg)
                jump_item.setForeground(0, merged_fg)
            else:
                jump_item.setBackground(0, jump_bg)
                jump_item.setForeground(0, jump_fg)
            if jump_item.parent() is not None:
                jump_item.parent().setExpanded(True)
            self._steps_preview.scrollToItem(jump_item)

    def _highlight_jump_target_step(self, step_id: str):
        self._jump_preview_step_id = step_id or ""
        self._apply_preview_step_highlight()

    def _get_selected_step_id(self) -> Optional[str]:
        current = self._steps_preview.currentItem()
        if current is None:
            return None
        return current.data(0, STEP_ID_ROLE)

    def _find_step_by_id(self, steps: List[SingleTask], step_id: str):
        for idx, step in enumerate(steps):
            if step.id == step_id:
                return step, steps, idx
            if step.children:
                found_step, found_list, found_idx = self._find_step_by_id(step.children, step_id)
                if found_step is not None:
                    return found_step, found_list, found_idx
        return None, None, -1

    def _sync_step_action_state(self):
        has_step = self._steps_preview.currentItem() is not None
        can_edit = has_step
        self._edit_step_btn.setEnabled(can_edit)

    def _apply_step_update_to_running_task(self, task_id: str, updated_step: SingleTask) -> bool:
        runtime_task = self._executor._current_task
        if runtime_task is None or runtime_task.id != task_id:
            return False

        runtime_step, _, _ = self._find_step_by_id(runtime_task.steps, updated_step.id)
        if runtime_step is None:
            return False

        for key, value in vars(updated_step).items():
            setattr(runtime_step, key, copy.deepcopy(value))
        return True

    def _on_step_item_double_clicked(self, item, column):
        del column
        if item is None:
            return
        self._edit_selected_step_from_preview(item.data(0, STEP_ID_ROLE))

    def _edit_selected_step_from_preview(self, step_id: Optional[str] = None):
        """在主面板直接编辑步骤并即时保存"""
        task_id = self._get_selected_task_id()
        if not task_id:
            QMessageBox.warning(self, "提示", "请先选择一个任务")
            return

        step_id = step_id or self._get_selected_step_id()
        if not step_id:
            QMessageBox.warning(self, "提示", "请先选择一个步骤")
            return

        task = self._storage.load(task_id)
        if task is None:
            QMessageBox.warning(self, "错误", "无法加载任务")
            return

        step, parent_list, idx = self._find_step_by_id(task.steps, step_id)
        if step is None or parent_list is None or idx < 0:
            QMessageBox.warning(self, "错误", "无法定位该步骤")
            return

        if step.is_loop:
            dlg = LoopStepEditDialog(step, task_params=task.parameters, task=task, parent=self)
        else:
            dlg = StepEditDialog(step, task_params=task.parameters, task_steps=task.steps, task=task, parent=self)

        if dlg.exec() != QDialog.Accepted:
            return

        parent_list[idx] = dlg.get_step()
        updated_step = parent_list[idx]
        if not self._storage.save(task):
            QMessageBox.warning(self, "错误", "保存步骤失败")
            return

        runtime_synced = self._apply_step_update_to_running_task(task.id, updated_step)

        self._refresh_task_list(task.id)
        self._select_step_in_preview(updated_step.id)

        display_name = updated_step.name if updated_step.name != "未命名步骤" else f"步骤{idx + 1}"
        if runtime_synced:
            self._append_log(f"已保存步骤: {display_name}（已同步到正在执行的任务）")
        else:
            self._append_log(f"已保存步骤: {display_name}")

    def _on_task_selected(self, current, previous):
        """任务选择变更"""
        del previous
        if current is None:
            if self._has_pending_ai_start():
                self._clear_pending_ai_start()
            self._info_label.setText("请选择一个任务")
            self._steps_preview.clear()
            self._step_id_to_item.clear()
            self._sync_step_action_state()
            self._refresh_ai_warmup_status(None)
            return

        task_id = current.data(Qt.UserRole)
        if self._has_pending_ai_start() and self._pending_ai_start_task_id != task_id:
            self._clear_pending_ai_start()
            self._update_ui_running(False, "已取消等待中的自动执行")
        task = self._storage.load(task_id)
        if task is None:
            self._refresh_ai_warmup_status(None)
            return

        self._info_label.setText(self._build_task_info_text(task))
        self._populate_steps_preview(task)
        self._sync_step_action_state()
        self._queue_ai_tile_warmup_for_task(task)
        self._refresh_ai_warmup_status(task)

    def _new_task(self):
        """新建任务"""
        dlg = TaskEditDialog(task_storage=self._storage, parent=self)
        dlg.task_saved.connect(self._refresh_task_list)
        if dlg.exec() == QDialog.Accepted:
            task = dlg.get_task()
            self._storage.save(task)
            self._refresh_task_list(task.id)
            self._append_log(f"已创建任务: {task.name}")

    def _edit_task(self):
        """编辑任务"""
        task_id = self._get_selected_task_id()
        if not task_id:
            QMessageBox.warning(self, "提示", "请先选择一个任务")
            return

        task = self._storage.load(task_id)
        if task is None:
            QMessageBox.warning(self, "错误", "无法加载任务")
            return

        dlg = TaskEditDialog(task, task_storage=self._storage, parent=self)
        dlg.task_saved.connect(self._refresh_task_list)
        if dlg.exec() == QDialog.Accepted:
            edited = dlg.get_task()
            self._storage.save(edited)
            self._refresh_task_list(edited.id)
            self._append_log(f"已修改任务: {edited.name}")

    def _delete_task(self):
        """删除任务"""
        task_id = self._get_selected_task_id()
        if not task_id:
            QMessageBox.warning(self, "提示", "请先选择一个任务")
            return

        task = self._storage.load(task_id)
        name = task.name if task else task_id

        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除任务 [{name}] 吗？\n此操作不可撤销。",
        )
        if reply == QMessageBox.Yes:
            self._storage.delete(task_id)
            self._refresh_task_list()
            self._info_label.setText("请选择一个任务")
            self._steps_preview.clear()
            self._step_id_to_item.clear()
            self._sync_step_action_state()
            self._append_log(f"已删除任务: {name}")

    def _import_task(self):
        """导入任务"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "导入计划任务", "",
            "JSON文件 (*.json);;所有文件 (*.*)"
        )
        if filepath:
            task = self._storage.import_task(filepath)
            if task:
                self._refresh_task_list(task.id)
                self._append_log(f"已导入任务: {task.name}")
                QMessageBox.information(self, "成功", f"任务 [{task.name}] 导入成功")
            else:
                QMessageBox.warning(self, "错误", "导入任务失败")

    def _export_task(self):
        """导出任务"""
        task_id = self._get_selected_task_id()
        if not task_id:
            QMessageBox.warning(self, "提示", "请先选择一个任务")
            return

        task = self._storage.load(task_id)
        if task is None:
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self, "导出计划任务", f"{task.name}.json",
            "JSON文件 (*.json);;所有文件 (*.*)"
        )
        if filepath:
            if self._storage.export_task(task_id, filepath):
                QMessageBox.information(self, "成功", "任务导出成功")
            else:
                QMessageBox.warning(self, "错误", "导出任务失败")

    # ==================== 步骤右键菜单 & 单步测试 ====================

    def _show_step_context_menu(self, pos):
        """步骤列表右键菜单"""
        item = self._steps_preview.itemAt(pos)
        if item is None:
            return

        step_id = item.data(0, STEP_ID_ROLE)
        if not step_id:
            return

        task_id = self._get_selected_task_id()
        task = self._storage.load(task_id) if task_id else None
        step, _, _ = self._find_step_by_id(task.steps, step_id) if task else (None, None, -1)
        if step is None:
            return

        menu = QMenu(self)

        edit_action = QAction("编辑此步骤", self)
        edit_action.triggered.connect(lambda: self._edit_selected_step_from_preview(step_id))
        menu.addAction(edit_action)

        if not step.is_loop:
            test_action = QAction("🚩 测试此步骤", self)
            test_action.triggered.connect(lambda: self._test_single_step(step_id))
            menu.addAction(test_action)

        if item.parent() is None:
            run_to_action = QAction("⏩ 执行到此步骤", self)
            run_to_action.triggered.connect(lambda: self._run_to_step(step_id))
            menu.addAction(run_to_action)

        menu.exec(self._steps_preview.viewport().mapToGlobal(pos))

    def _run_to_step(self, step_id: str):
        """执行到指定步骤后暂停"""
        if self._executor.is_paused:
            # 已暂停状态：继续执行到指定步骤
            self._executor.run_to_step(step_id)
            self._pause_btn.setText("⏸ 暂停")
            self._step_btn.setEnabled(False)
            self._exec_status.setText("状态: 执行到指定步骤中")
        elif self._executor.is_running:
            # 正在运行：设置目标步骤
            self._executor.run_to_step(step_id)
        else:
            # 空闲状态：启动任务并执行到指定步骤
            if self._has_pending_ai_start():
                self._append_log("[AI地块] 当前已有等待中的自动执行，请等待预热完成或点停止取消")
                return

            task_id = self._get_selected_task_id()
            if not task_id:
                QMessageBox.warning(self, "提示", "请先选择一个任务")
                return

            if not self._current_hwnd:
                QMessageBox.warning(self, "提示", "请先在顶部选择目标窗口")
                return

            task = self._storage.load(task_id)
            if task is None:
                QMessageBox.warning(self, "错误", "无法加载任务")
                return

            self._request_task_start(task, mode="run_to", step_id=step_id)

    def _test_single_step(self, step_id: str):
        """单独测试一个步骤（识别 + 点击）"""
        if not self._current_hwnd:
            QMessageBox.warning(self, "提示", "请先在顶部选择目标窗口")
            return

        # 获取当前任务和步骤
        task_id = self._get_selected_task_id()
        if not task_id:
            return
        task = self._storage.load(task_id)
        if task is None:
            return

        self._active_task_id_for_logs = task.id

        step, parent_list, idx = self._find_step_by_id(task.steps, step_id)
        if step is None or parent_list is None or idx < 0:
            return

        display_name = step.name if step.name != "未命名步骤" else f"步骤{idx + 1}"
        self._append_log(f"--- 开始测试步骤 [{idx + 1}] {display_name} ---")

        # 在工作线程中执行，避免卡UI
        import threading
        t = threading.Thread(
            target=self._test_step_worker,
            args=(step, task),
            daemon=True,
        )
        t.start()

    def _preview_recognition_to_logic_action(self, step: SingleTask, task: PlanTask, action: dict):
        """即时预览识别坐标转逻辑坐标动作，不发送任何输入。"""
        logs = []

        def _log(message: str):
            logs.append(message)

        if not self._current_hwnd:
            return False, "请先在顶部选择目标窗口"
        if self._capture is None or self._window_manager is None:
            return False, "截图或窗口依赖未初始化，无法预览"
        if step is None:
            return False, "缺少步骤上下文，无法预览"
        if task is None:
            return False, "缺少任务上下文，无法预览"

        preview_step = copy.deepcopy(step)
        preview_action = copy.deepcopy(action)
        preview_step.actions = [preview_action]
        _apply_action_dict_to_step(preview_step, preview_action)

        if preview_step.recognition_type == "none":
            return False, "当前步骤的识别类型为“无识别”，无法预览识别坐标转逻辑坐标"

        preview_task = copy.deepcopy(task)
        preview_task.steps = [preview_step]

        try:
            if preview_step.use_background:
                img = self._capture.capture_window_background(self._current_hwnd)
            else:
                img = self._capture.capture_window(self._current_hwnd)

            if img is None:
                return False, "截图失败，无法预览"

            _log(f"截图成功: {img.shape[1]}x{img.shape[0]}")

            import cv2
            import win32gui

            try:
                client_rect = win32gui.GetClientRect(self._current_hwnd)
                expected_w, expected_h = client_rect[2], client_rect[3]
                img_h, img_w = img.shape[:2]
                if expected_w > 0 and expected_h > 0:
                    if abs(img_w - expected_w) > 2 or abs(img_h - expected_h) > 2:
                        _log(
                            f"[调试] 截图 {img_w}x{img_h} 与客户区 {expected_w}x{expected_h} 不一致，自动缩放"
                        )
                        img = cv2.resize(img, (expected_w, expected_h), interpolation=cv2.INTER_AREA)
            except Exception:
                pass

            bg_input_class = self._bg_input_class
            if bg_input_class is None:
                from core.input import BackgroundInputSimulator
                bg_input_class = BackgroundInputSimulator

            action_executor = TaskExecutor()
            action_executor.setup(
                hwnd=self._current_hwnd,
                capture=self._capture,
                ocr=self._ocr,
                recognition=self._recognition,
                ai_tile_recognition=self._ai_tile_recognition,
                input_sim=self._input,
                bg_input_class=bg_input_class,
                window_manager=self._window_manager,
                task_storage=self._storage,
            )
            action_executor.on_log = _log
            action_executor._current_task = preview_task
            action_executor._save_persist = lambda: None
            action_executor._build_runtime_vars()

            resolved_target, target_mode = action_executor._resolve_recognition_target(preview_step)
            _log(
                f"测试识别目标: {action_executor._format_recognition_target_log(resolved_target, target_mode)}"
            )
            center = action_executor._recognize(preview_step, img, resolved_target, target_mode)
            compare_text = action_executor._format_last_recognition_metrics()
            if center is None:
                fail_message = "识别失败，未找到目标"
                if compare_text:
                    fail_message = f"{fail_message}，{compare_text}"
                _log(fail_message)
                return False, "\n".join(logs)

            cx, cy, tpl_w, tpl_h = center
            success_message = (
                f"识别成功，位置(相对): "
                f"{action_executor._format_client_relative_point(cx, cy, client_size=(img.shape[1], img.shape[0]))}"
            )
            if compare_text:
                success_message = f"{success_message}，{compare_text}"
            _log(success_message)

            action_executor._do_action(
                preview_step,
                cx,
                cy,
                tpl_w,
                tpl_h,
                action_executor._resolve_params(preview_step.input_text),
                action_executor._resolve_params(preview_step.press_keys),
                resolved_target,
                target_mode,
            )

            result_array_name = action_executor._resolve_params(preview_action.get("result_array", "")).strip()
            result_coords = action_executor._get_coord_array_value(result_array_name) if result_array_name else []
            if result_array_name:
                _log(f"预览结果数组 {result_array_name}: {result_coords}")
            if not result_coords:
                return False, "\n".join(logs)
            return True, "\n".join(logs)
        except Exception as exc:
            import traceback

            _log(f"预览执行异常: {exc}")
            _log(traceback.format_exc())
            return False, "\n".join(logs)

    def _test_step_worker(self, step: SingleTask, task: "PlanTask"):
        """在工作线程中执行单步测试"""
        import time
        import cv2
        try:
            # 1. 截图
            if step.use_background:
                img = self._capture.capture_window_background(self._current_hwnd)
            else:
                img = self._capture.capture_window(self._current_hwnd)

            if img is None:
                self._bridge.sig_log.emit("截图失败，无法测试")
                return

            self._bridge.sig_log.emit(f"截图成功: {img.shape[1]}x{img.shape[0]}")

            # 修正 DPI 缩放：确保截图尺寸与客户区一致
            import win32gui
            try:
                client_rect = win32gui.GetClientRect(self._current_hwnd)
                expected_w, expected_h = client_rect[2], client_rect[3]
                img_h, img_w = img.shape[:2]
                if expected_w > 0 and expected_h > 0:
                    if abs(img_w - expected_w) > 2 or abs(img_h - expected_h) > 2:
                        self._bridge.sig_log.emit(
                            f"[调试] 截图 {img_w}x{img_h} 与客户区 {expected_w}x{expected_h} 不一致，自动缩放"
                        )
                        img = cv2.resize(img, (expected_w, expected_h), interpolation=cv2.INTER_AREA)
            except Exception:
                pass

            # 2. 准备正式执行器：识别与动作都复用同一套逻辑
            bg_input_class = self._bg_input_class
            if bg_input_class is None:
                from core.input import BackgroundInputSimulator
                bg_input_class = BackgroundInputSimulator

            action_executor = TaskExecutor()
            action_executor.setup(
                hwnd=self._current_hwnd,
                capture=self._capture,
                ocr=self._ocr,
                recognition=self._recognition,
                ai_tile_recognition=self._ai_tile_recognition,
                input_sim=self._input,
                bg_input_class=bg_input_class,
                window_manager=self._window_manager,
                task_storage=self._storage,
            )
            action_executor.on_log = self._bridge.sig_log.emit
            action_executor.on_highlight_match = lambda left, top, width, height, duration: self._bridge.sig_highlight_match.emit(
                left, top, width, height, duration
            )
            action_executor.on_highlight_matches = lambda regions, duration: self._bridge.sig_highlight_matches.emit(
                regions, duration
            )
            action_executor.on_highlight_point = lambda x, y, duration: self._bridge.sig_highlight_point.emit(
                x, y, duration
            )
            action_executor._current_task = task
            action_executor._build_runtime_vars()
            resolved_target = step.recognition_target
            target_mode = normalize_recognition_target_mode(
                getattr(step, "recognition_target_mode", "single")
            )

            # 3. 识别
            if step.recognition_type == "none":
                center = (0, 0, 0, 0)
                self._bridge.sig_log.emit("识别类型为'无识别'，直接执行操作")
            else:
                resolved_target, target_mode = action_executor._resolve_recognition_target(step)
                self._bridge.sig_log.emit(
                    f"测试识别目标: {action_executor._format_recognition_target_log(resolved_target, target_mode)}"
                )
                center = action_executor._recognize(step, img, resolved_target, target_mode)

            compare_text = action_executor._format_last_recognition_metrics()

            if center is None:
                fail_message = "识别失败，未找到目标"
                if compare_text:
                    fail_message = f"{fail_message}，{compare_text}"
                self._bridge.sig_log.emit(fail_message)
                return

            cx, cy, tpl_w, tpl_h = center
            if step.recognition_type != "none":
                success_message = (
                    f"识别成功，位置(相对): "
                    f"{action_executor._format_client_relative_point(cx, cy, client_size=(img.shape[1], img.shape[0]))}"
                )
                if compare_text:
                    success_message = f"{success_message}，{compare_text}"
                self._bridge.sig_log.emit(success_message)

            actions = action_executor._get_step_actions(step)
            if not actions:
                self._bridge.sig_log.emit("操作类型为“无操作”，跳过")
                return

            action_executor._do_action(
                step,
                cx,
                cy,
                tpl_w,
                tpl_h,
                action_executor._resolve_params(step.input_text),
                action_executor._resolve_params(step.press_keys),
                resolved_target,
                target_mode,
            )
            self._storage.save(task)

            if any(_action_uses_click_offset(action.get("type", "")) for action in actions):
                self._bridge.sig_log.emit(f"测试完成: 已执行 {len(actions)} 个操作，点击坐标按各操作自己的坐标配置计算")
            else:
                self._bridge.sig_log.emit(f"测试完成: 已执行 {len(actions)} 个操作")

        except Exception as e:
            import traceback
            self._bridge.sig_log.emit(f"测试执行异常: {e}")
            self._bridge.sig_log.emit(traceback.format_exc())

    def _save_persist_for_task(self, task: "PlanTask"):
        """保存任务的持久化参数"""
        import json
        data = task.get_persist_data()
        if not data:
            return
        try:
            persist_path = self._get_persist_path_for_task(task)
            os.makedirs(os.path.dirname(persist_path), exist_ok=True)
            with open(persist_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._bridge.sig_log.emit(f"保存存档参数失败: {e}")

    def _get_persist_path_for_task(self, task: "PlanTask") -> str:
        """获取任务的持久化参数文件路径"""
        base = self._get_app_dir()
        return os.path.join(base, "tasks", f"persist_{task.id}.json")

    def _load_isometric_axes(self):
        """从 config.json 加载等距地图轴方向配置"""
        import json
        try:
            config_path = os.path.join(self._get_app_dir(), "config.json")
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                iso = cfg.get("isometric", {})
                return iso.get("axis_x", [-0.70, 0.72]), iso.get("axis_y", [-0.11, 0.99])
        except Exception:
            pass
        return [-0.70, 0.72], [-0.11, 0.99]

    @staticmethod
    def _get_app_dir() -> str:
        """获取应用程序根目录"""
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _clear_input_field_test(self, input_sim, step):
        """清除输入框旧内容（测试用）"""
        import time as _time
        method = step.clear_method
        if method == "none":
            return
        elif method == "ctrl_a":
            input_sim.hotkey("ctrl", "a")
            _time.sleep(0.05)
            self._bridge.sig_log.emit("清除方式: Ctrl+A 全选")
        elif method == "delete_backspace":
            count = step.clear_key_count
            input_sim.press("end")
            _time.sleep(0.03)
            for _ in range(count):
                input_sim.press("backspace")
                _time.sleep(0.02)
            input_sim.press("home")
            _time.sleep(0.03)
            for _ in range(count):
                input_sim.press("delete")
                _time.sleep(0.02)
            self._bridge.sig_log.emit(f"清除方式: Delete+Backspace 各{count}次")

    def _test_recognize_text(self, step: SingleTask, img):
        """测试文字识别，返回 (cx, cy, 0, 0)"""
        import cv2
        if not self._ocr:
            self._bridge.sig_log.emit("OCR 模块不可用")
            return None

        h, w = img.shape[:2]
        max_dim = 1080
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            ocr_img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        else:
            scale = 1.0
            ocr_img = img

        all_results = self._ocr.recognize(ocr_img, min_confidence=0.3)
        if not all_results:
            return None

        target = step.recognition_target
        for r in all_results:
            if step.exact_match:
                if r.text == target and r.confidence >= step.recognition_threshold:
                    if scale != 1.0:
                        return (int(r.center[0] / scale), int(r.center[1] / scale), 0, 0)
                    return (r.center[0], r.center[1], 0, 0)
            else:
                if target in r.text and r.confidence >= step.recognition_threshold:
                    if scale != 1.0:
                        return (int(r.center[0] / scale), int(r.center[1] / scale), 0, 0)
                    return (r.center[0], r.center[1], 0, 0)
        return None

    def _test_recognize_image(self, step: SingleTask, img):
        """测试图像识别 — 支持匹配第N个结果，返回 (cx, cy, w, h)"""
        if not self._recognition:
            self._bridge.sig_log.emit("图像识别模块不可用")
            return None

        # 解析相对路径
        target = self._resolve_template_path(step.recognition_target)
        match_mode = normalize_image_match_mode(getattr(step, "image_match_mode", "template"))
        match_index = max(1, step.match_index)
        
        # 判断是否需要使用find_all：显式标记多匹配或索引>1
        use_find_all = step.has_multiple_matches or match_index > 1
        result_limit = min(
            30,
            max(
                10 if step.has_multiple_matches else 6,
                match_index + (9 if step.has_multiple_matches else 4),
            ),
        )

        if not use_find_all:
            # 快速模式：单次匹配（最高置信度）
            result = self._recognition.find_template(
                img, target,
                threshold=step.recognition_threshold,
                validate_color=step.validate_color_consistency,
                match_mode=match_mode,
            )
            if result:
                self._bridge.sig_log.emit(
                    f"模板匹配成功: {result.template_name}, "
                    f"置信度={result.confidence:.2f}, 位置=({result.center[0]}, {result.center[1]})"
                )
                return (result.center[0], result.center[1], result.width, result.height)
            return None
        else:
            # 多匹配模式：查找所有匹配并按空间位置排序
            results = self._recognition.find_all_templates(
                img, target,
                threshold=step.recognition_threshold,
                max_count=result_limit,
                validate_color=step.validate_color_consistency,
                match_mode=match_mode,
            )
            if not results:
                return None
            # 按从左到右、从上到下排序
            results.sort(key=lambda r: (r.center[1], r.center[0]))
            self._bridge.sig_log.emit(f"找到 {len(results)} 个匹配，需要第 {match_index} 个")
            for i, r in enumerate(results):
                self._bridge.sig_log.emit(
                    f"  #{i+1}: 置信度={r.confidence:.2f}, 位置=({r.center[0]}, {r.center[1]})"
                )
            if match_index > len(results):
                self._bridge.sig_log.emit(f"需要第 {match_index} 个匹配，但只找到 {len(results)} 个")
                return None
            chosen = results[match_index - 1]
            self._bridge.sig_log.emit(
                f"选择第 {match_index} 个: 置信度={chosen.confidence:.2f}, "
                f"位置=({chosen.center[0]}, {chosen.center[1]})"
            )
            return (chosen.center[0], chosen.center[1], chosen.width, chosen.height)

    @staticmethod
    def _resolve_template_path(target: str) -> str:
        """解析模板路径：将相对路径转为绝对路径"""
        if os.path.isabs(target):
            return target
        app_dir = StepEditDialog._get_app_dir()
        resolved = os.path.join(app_dir, target)
        return os.path.normpath(resolved)

    # ==================== 执行控制 ====================

    def _run_task(self):
        """执行任务"""
        try:
            if self._has_pending_ai_start():
                self._append_log("[AI地块] 当前已有等待中的自动执行，请等待预热完成或点停止取消")
                return

            task_id = self._get_selected_task_id()
            if not task_id:
                QMessageBox.warning(self, "提示", "请先选择一个任务")
                return

            if not self._current_hwnd:
                QMessageBox.warning(self, "提示", "请先在顶部选择目标窗口")
                return

            task = self._storage.load(task_id)
            if task is None:
                QMessageBox.warning(self, "错误", "无法加载任务")
                return

            self._request_task_start(task, mode="run")
        except Exception as e:
            self._append_log(f"执行任务启动失败: {e}")
            self._append_log(traceback.format_exc())
            QMessageBox.critical(self, "错误", f"执行任务启动失败:\n{e}")

    def _toggle_pause(self):
        """暂停/恢复"""
        if self._executor.is_running:
            self._executor.pause()
            self._pause_btn.setText("⏸ 恢复")
            self._step_btn.setEnabled(True)
            self._exec_status.setText("状态: 已暂停")
        elif self._executor.is_paused:
            self._executor.resume()
            self._pause_btn.setText("⏸ 暂停")
            self._step_btn.setEnabled(False)
            self._exec_status.setText("状态: 执行中")

    def _stop_task(self):
        """停止任务"""
        if self._has_pending_ai_start() and not (self._executor.is_running or self._executor.is_paused):
            self._clear_pending_ai_start()
            self._update_ui_running(False, "已取消等待中的自动执行")
            self._refresh_ai_warmup_status()
            return
        self._executor.stop()

    def _step_once(self):
        """单步执行：执行一个步骤后自动暂停"""
        if self._executor.is_paused:
            # 已暂停状态：继续执行一步
            self._executor.step_once()
            self._pause_btn.setText("⏸ 暂停")
            self._exec_status.setText("状态: 单步执行中")
            self._step_btn.setEnabled(False)
        else:
            # 空闲状态：以单步模式启动任务
            try:
                if self._has_pending_ai_start():
                    self._append_log("[AI地块] 当前已有等待中的自动执行，请等待预热完成或点停止取消")
                    return

                task_id = self._get_selected_task_id()
                if not task_id:
                    QMessageBox.warning(self, "提示", "请先选择一个任务")
                    return

                if not self._current_hwnd:
                    QMessageBox.warning(self, "提示", "请先在顶部选择目标窗口")
                    return

                task = self._storage.load(task_id)
                if task is None:
                    QMessageBox.warning(self, "错误", "无法加载任务")
                    return

                self._request_task_start(task, mode="step")
            except Exception as e:
                self._append_log(f"单步执行启动失败: {e}")
                self._append_log(traceback.format_exc())
                QMessageBox.critical(self, "错误", f"单步执行启动失败:\n{e}")

    # ==================== 执行器回调（通过信号桥在主线程执行） ====================

    @Slot(str, str)
    def _on_step_started_main(self, step_id: str, step_name: str):
        """步骤开始（主线程）"""
        self._exec_status.setText(f"状态: 执行步骤 - {step_name}")
        self._highlight_step(step_id)
        self._bind_active_log_item(step_id, step_name)

    @Slot(str, str, int)
    def _on_step_retried_main(self, step_id: str, step_name: str, retry_count: int):
        """步骤重试（主线程）"""
        self._exec_status.setText(
            f"状态: 步骤 [{step_name}] 识别中... 重试第 {retry_count} 次"
        )

    @Slot()
    def _on_step_paused_main(self):
        """单步执行后自动暂停（主线程）"""
        self._pause_btn.setText("⏸ 恢复")
        self._pause_btn.setEnabled(True)
        self._step_btn.setEnabled(True)
        self._stop_btn.setEnabled(True)
        self._exec_status.setText("状态: 单步执行完成，已暂停")

    @Slot()
    def _on_ai_warmup_tick_main(self):
        task = self._get_selected_task()
        self._refresh_ai_warmup_status(task)

        if not self._has_pending_ai_start():
            return

        pending_task = self._storage.load(self._pending_ai_start_task_id)
        if pending_task is None:
            self._clear_pending_ai_start()
            self._update_ui_running(False, "等待中的自动执行任务已不存在")
            return

        if self._is_ai_warmup_ready_for_task(pending_task):
            mode = self._pending_ai_start_mode or "run"
            step_id = self._pending_ai_start_step_id
            self._clear_pending_ai_start()
            self._append_log("[AI地块] 后台预热已就绪，开始执行任务")
            self._start_task_execution_now(pending_task, mode=mode, step_id=step_id)
            self._refresh_ai_warmup_status(task)
            return

        if not self._ai_tile_warmup_running and self._ai_tile_warmup_last_error:
            self._clear_pending_ai_start()
            self._update_ui_running(False, f"AI 预热失败: {self._ai_tile_warmup_last_error}")
            self._refresh_ai_warmup_status(task)

    def _highlight_step(self, step_id: str):
        """高亮当前执行的步骤"""
        self._active_preview_step_id = step_id or ""
        item = self._step_id_to_item.get(step_id)
        if item is None:
            self._apply_preview_step_highlight()
            return

        if item.parent() is not None:
            item.parent().setExpanded(True)
        self._steps_preview.setCurrentItem(item)
        self._steps_preview.scrollToItem(item)
        self._apply_preview_step_highlight()

    def _update_ui_running(self, running: bool, info: str = ""):
        """更新UI状态"""
        if running:
            self._run_btn.setEnabled(False)
            self._pause_btn.setEnabled(True)
            self._stop_btn.setEnabled(True)
            self._step_btn.setEnabled(False)
            self._exec_status.setText(f"状态: 执行中 - {info}" if info else "状态: 执行中")
            return

        self._run_btn.setEnabled(True)
        self._pause_btn.setEnabled(False)
        self._pause_btn.setText("⏸ 暂停")
        self._stop_btn.setEnabled(False)
        self._step_btn.setEnabled(True)
        self._active_preview_step_id = ""
        self._apply_preview_step_highlight()
        self._exec_status.setText(f"状态: {info}" if info else "状态: 空闲")
        self._refresh_ai_warmup_status()

    def _toggle_log_item(self, item, column):
        del column
        if item is None or item.childCount() <= 0:
            return
        item.setExpanded(not item.isExpanded())

    def _on_log_item_changed(self, current, previous):
        del previous
        if current is None:
            self._log_detail.clear()
            return
        full_text = current.data(0, LOG_FULL_TEXT_ROLE) or current.text(0)
        self._log_detail.setPlainText(full_text)

    @staticmethod
    def _set_log_item_full_text(item: QTreeWidgetItem, full_text: str):
        text = str(full_text or "")
        item.setData(0, LOG_FULL_TEXT_ROLE, text)
        item.setToolTip(0, "")

    def _append_log_item_full_text(self, item: QTreeWidgetItem, full_text: str):
        existing_text = item.data(0, LOG_FULL_TEXT_ROLE) or ""
        merged_text = f"{existing_text}\n{full_text}" if existing_text else str(full_text)
        self._set_log_item_full_text(item, merged_text)
        if self._log_tree.currentItem() is item:
            self._log_detail.setPlainText(merged_text)

    def _clear_logs(self):
        self._log_tree.clear()
        self._active_log_item = None
        self._log_detail.clear()

    @staticmethod
    def _is_log_item_ancestor_selected(item: Optional[QTreeWidgetItem]) -> bool:
        parent = item.parent() if item is not None else None
        while parent is not None:
            if parent.isSelected():
                return True
            parent = parent.parent()
        return False

    def _iter_log_items(self):
        def _walk(item: QTreeWidgetItem):
            yield item
            for child_index in range(item.childCount()):
                yield from _walk(item.child(child_index))

        for top_index in range(self._log_tree.topLevelItemCount()):
            top_item = self._log_tree.topLevelItem(top_index)
            yield from _walk(top_item)

    def _copy_selected_logs(self):
        selected_items = self._log_tree.selectedItems()
        if not selected_items:
            current = self._log_tree.currentItem()
            if current is not None:
                selected_items = [current]
            else:
                return

        selected_ids = {id(item) for item in selected_items}
        ordered_items = []
        for item in self._iter_log_items():
            if id(item) not in selected_ids:
                continue
            if self._is_log_item_ancestor_selected(item):
                continue
            ordered_items.append(item)

        if not ordered_items:
            return

        texts = []
        for item in ordered_items:
            full_text = item.data(0, LOG_FULL_TEXT_ROLE)
            if not full_text:
                prefix = item.text(0).strip()
                content = item.text(1).strip()
                full_text = f"{prefix} {content}".strip()
            if full_text:
                texts.append(str(full_text))

        if not texts:
            return

        QApplication.clipboard().setText("\n\n".join(texts))
        self._append_log(f"已复制 {len(texts)} 条日志到剪贴板")

    @staticmethod
    def _get_log_color(message: str) -> str:
        if message.startswith("执行步骤") or message.startswith("--- "):
            return "#1565C0"
        if "识别成功" in message or "执行完成" in message:
            return "#2E7D32"
        if "失败" in message or "超时" in message or "错误" in message or "异常" in message:
            return "#C62828"
        if "条件不满足" in message or "跳过" in message:
            return "#E65100"
        if "已暂停" in message or "已停止" in message:
            return "#6A1B9A"
        return ""

    @staticmethod
    def _summarize_log_text(message: str, limit: int = 70) -> str:
        summary = " ".join(str(message).splitlines()).strip()
        if len(summary) <= limit:
            return summary
        return summary[:limit - 3] + "..."

    @staticmethod
    def _parse_step_log_header(message: str):
        prefix = "执行步骤 ["
        if not message.startswith(prefix):
            return None

        end_idx = message.find("] ")
        if end_idx < 0:
            return None

        colon_idx = message.find(": ", end_idx + 2)
        if colon_idx < 0:
            return None

        step_index = message[len(prefix):end_idx]
        step_name = message[end_idx + 2:colon_idx].strip() or f"步骤{step_index}"
        return step_index, step_name

    def _find_step_path(self, steps: List[SingleTask], step_id: str, prefix: Optional[List[int]] = None):
        path_prefix = list(prefix or [])
        for idx, step in enumerate(steps, start=1):
            current_path = path_prefix + [idx]
            if step.id == step_id:
                return current_path
            if step.children:
                found = self._find_step_path(step.children, step_id, current_path)
                if found:
                    return found
        return None

    def _get_log_task_id(self) -> Optional[str]:
        return self._active_task_id_for_logs or self._get_selected_task_id()

    def _get_step_compact_label(self, step_id: str, fallback_label: str = "") -> str:
        task_id = self._get_log_task_id()
        if not task_id:
            return fallback_label

        task = self._storage.load(task_id)
        if task is None:
            return fallback_label

        path = self._find_step_path(task.steps, step_id)
        if not path:
            return fallback_label
        return "-".join(str(item) for item in path)

    @staticmethod
    def _is_standalone_log(message: str) -> bool:
        prefixes = (
            "--- ",
            "任务 [",
            "任务已暂停",
            "任务已恢复",
            "单步执行...",
            "继续执行到指定步骤",
            "正在停止任务",
            "错误：",
            "任务执行异常:",
            "已创建任务:",
            "已修改任务:",
            "已删除任务:",
            "已导入任务:",
            "已保存步骤:",
        )
        return message.startswith(prefixes)

    @staticmethod
    def _should_close_active_log_group(message: str) -> bool:
        return message.startswith("任务 [") or message.startswith("任务执行异常:")

    @staticmethod
    def _summarize_step_group_message(message: str) -> str:
        if message.startswith("执行步骤 ["):
            return "开始执行"
        if message.startswith("步骤 ["):
            parts = message.split("] ", 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
        if message.startswith("循环步骤 ["):
            parts = message.split(": ", 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
        return TaskPanel._summarize_log_text(message)

    def _refresh_step_log_title(self, item: QTreeWidgetItem):
        base_title = item.data(0, LOG_BASE_TITLE_ROLE) or "日志"
        summary = item.data(0, LOG_SUMMARY_ROLE) or "开始执行"
        self._set_log_item_display_text(item, f"{base_title} | {summary} ({item.childCount()}条)")

    def _get_log_item_depth(self, item: Optional[QTreeWidgetItem]) -> int:
        depth = 0
        current = item
        while current is not None and current.parent() is not None:
            depth += 1
            current = current.parent()
        return depth

    @staticmethod
    def _split_log_display_text(text: str):
        raw_text = str(text or "")
        if raw_text.startswith("[") and "] " in raw_text:
            prefix, content = raw_text.split("] ", 1)
            return f"{prefix}]", content
        return "", raw_text

    def _wrap_log_display_text(self, text: str, depth: int = 0) -> str:
        raw_text = str(text or "")
        if not raw_text:
            return ""

        font_metrics = self._log_tree.fontMetrics()
        avg_char_width = max(
            1,
            font_metrics.horizontalAdvance("测") or font_metrics.horizontalAdvance("M") or 8,
        )
        indent_pixels = 20 + depth * self._log_tree.indentation()
        available_pixels = max(
            180,
            self._log_tree.viewport().width() - self._log_tree.columnWidth(0) - indent_pixels - 24,
        )
        width_chars = max(24, available_pixels // avg_char_width)

        wrapped_lines = []
        for raw_line in raw_text.splitlines() or [""]:
            wrapper = textwrap.TextWrapper(
                width=width_chars,
                break_long_words=True,
                break_on_hyphens=False,
                replace_whitespace=False,
                drop_whitespace=False,
            )
            wrapped = wrapper.wrap(raw_line)
            wrapped_lines.extend(wrapped or [raw_line])

        return "\n".join(wrapped_lines)

    def _set_log_item_display_text(self, item: QTreeWidgetItem, text: str):
        prefix, content = self._split_log_display_text(text)
        is_detail_row = item.parent() is not None
        if is_detail_row:
            display_text = self._wrap_log_display_text(content, self._get_log_item_depth(item))
        else:
            display_text = " ".join(str(content or "").splitlines()).strip()
        item.setText(0, prefix)
        item.setText(1, display_text)
        item.setTextAlignment(0, int(Qt.AlignLeft | Qt.AlignTop))
        item.setTextAlignment(1, int(Qt.AlignLeft | Qt.AlignTop))
        line_count = max(1, prefix.count("\n") + 1, display_text.count("\n") + 1)
        size_hint = QSize(0, self._log_tree.fontMetrics().lineSpacing() * line_count + 8)
        item.setSizeHint(0, size_hint)
        item.setSizeHint(1, size_hint)

    def _create_step_log_group(self, step_label: str, step_name: str, timestamp: str, step_id: str = ""):
        base_title = f"[{timestamp}] {step_label}"
        item = QTreeWidgetItem([""])
        item.setData(0, LOG_STEP_ID_ROLE, step_id)
        item.setData(0, LOG_STEP_NAME_ROLE, step_name)
        item.setData(0, LOG_BASE_TITLE_ROLE, base_title)
        item.setData(0, LOG_TIMESTAMP_ROLE, timestamp)
        item.setData(0, LOG_SUMMARY_ROLE, "开始执行")
        self._set_log_item_full_text(item, "")
        self._log_tree.addTopLevelItem(item)
        item.setExpanded(False)
        self._active_log_item = item
        return item

    def _bind_active_log_item(self, step_id: str, step_name: str) -> bool:
        if self._active_log_item is None:
            return False

        active_step_id = self._active_log_item.data(0, LOG_STEP_ID_ROLE)
        active_step_name = self._active_log_item.data(0, LOG_STEP_NAME_ROLE)
        if not active_step_id and active_step_name == step_name:
            self._active_log_item.setData(0, LOG_STEP_ID_ROLE, step_id)
            compact_label = self._get_step_compact_label(step_id, active_step_name)
            timestamp = self._active_log_item.data(0, LOG_TIMESTAMP_ROLE) or ""
            base_title = f"[{timestamp}] {compact_label}" if timestamp else compact_label
            self._active_log_item.setData(0, LOG_BASE_TITLE_ROLE, base_title)
            self._refresh_step_log_title(self._active_log_item)
            return True
        return active_step_id == step_id

    def _append_step_log_detail(self, parent_item: QTreeWidgetItem, message: str, timestamp: str, color: str):
        lines = [line for line in str(message).splitlines() if line.strip()] or [""]
        brush = QBrush(QColor(color)) if color else None
        full_lines = []

        for idx, line in enumerate(lines):
            text = f"[{timestamp}] {line}" if idx == 0 else f"           {line}"
            child = QTreeWidgetItem([""])
            parent_item.addChild(child)
            self._set_log_item_display_text(child, text)
            self._set_log_item_full_text(child, text)
            if brush is not None:
                child.setForeground(0, brush)
                child.setForeground(1, brush)
            full_lines.append(text)

        self._append_log_item_full_text(parent_item, "\n".join(full_lines))

        summary = self._summarize_step_group_message(message)
        parent_item.setData(0, LOG_SUMMARY_ROLE, summary)
        self._refresh_step_log_title(parent_item)
        if brush is not None:
            parent_item.setForeground(0, brush)

    def _append_standalone_log(self, message: str, timestamp: str, color: str):
        lines = [line for line in str(message).splitlines() if line.strip()] or [""]
        summary = self._summarize_log_text(message)
        item = QTreeWidgetItem([""])
        self._set_log_item_display_text(item, f"[{timestamp}] {summary}")
        brush = QBrush(QColor(color)) if color else None
        full_lines = []
        if brush is not None:
            item.setForeground(0, brush)

        if len(lines) > 1 or summary != (lines[0] if lines else ""):
            for idx, line in enumerate(lines):
                detail_text = f"[{timestamp}] {line}" if idx == 0 else f"           {line}"
                child = QTreeWidgetItem([""])
                item.addChild(child)
                self._set_log_item_display_text(child, detail_text)
                self._set_log_item_full_text(child, detail_text)
                if brush is not None:
                    child.setForeground(0, brush)
                    child.setForeground(1, brush)
                full_lines.append(detail_text)
            item.setExpanded(False)
        else:
            full_lines.append(f"[{timestamp}] {lines[0]}")

        self._set_log_item_full_text(item, "\n".join(full_lines))

        self._log_tree.addTopLevelItem(item)
        return item

    def _append_log(self, message: str):
        """追加日志，并按步骤分组显示详情"""
        from datetime import datetime

        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        color = self._get_log_color(message)
        step_log = self._parse_step_log_header(message)

        if step_log is not None:
            step_label, step_name = step_log
            group_item = self._create_step_log_group(step_label, step_name, timestamp)
            self._append_step_log_detail(group_item, message, timestamp, color)
            target_item = group_item
        elif self._is_standalone_log(message):
            target_item = self._append_standalone_log(message, timestamp, color)
        elif self._active_log_item is not None:
            self._append_step_log_detail(self._active_log_item, message, timestamp, color)
            target_item = self._active_log_item
        else:
            target_item = self._append_standalone_log(message, timestamp, color)

        if self._should_close_active_log_group(message):
            self._active_log_item = None

        self._log_tree.scrollToItem(target_item)
        scrollbar = self._log_tree.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self.log_message.emit(message)

    def stop_executor(self):
        """停止执行器（供外部调用，如退出时）"""
        if self._executor.is_running or self._executor.is_paused:
            self._executor.stop()
