"""
窗口坐标点映射与辅助线面板
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

from PySide6.QtCore import QEvent, QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from core.capture import ScreenCapture
from core.coordinate_transform import (
    CoordinateMappingProfile,
    CoordinateMappingStorage,
    CoordinateWorkspaceState,
    CoordinateWorkspaceStateStorage,
    GridCoordinateAnchor,
    resolve_default_workspace_assets_dir,
    sync_profile_to_isometric_config,
)
from core.window import WindowInfo, WindowManager


GUIDE_LINE_STYLES: Dict[str, Dict[str, object]] = {
    "default": {"label": "白色实线", "color": "#f5f5f5", "pen_style": Qt.SolidLine},
    "red": {"label": "红色实线", "color": "#ff4d4f", "pen_style": Qt.SolidLine},
    "green": {"label": "绿色实线", "color": "#52c41a", "pen_style": Qt.SolidLine},
    "blue": {"label": "蓝色实线", "color": "#40a9ff", "pen_style": Qt.SolidLine},
    "yellow": {"label": "黄色实线", "color": "#fadb14", "pen_style": Qt.SolidLine},
    "dashed": {"label": "黄色虚线", "color": "#ffd666", "pen_style": Qt.DashLine},
}


def _distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _logical_int(value: float) -> int:
    return int(round(float(value)))


def _format_logical_pair(logical_coord: Tuple[float, float]) -> str:
    return f"({_logical_int(logical_coord[0])},{_logical_int(logical_coord[1])})"


def _distance_to_segment(
    point: Tuple[float, float],
    start: Tuple[float, float],
    end: Tuple[float, float],
) -> float:
    px, py = float(point[0]), float(point[1])
    x1, y1 = float(start[0]), float(start[1])
    x2, y2 = float(end[0]), float(end[1])
    dx = x2 - x1
    dy = y2 - y1
    if abs(dx) <= 1e-9 and abs(dy) <= 1e-9:
        return math.hypot(px - x1, py - y1)
    ratio = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    ratio = max(0.0, min(1.0, ratio))
    cx = x1 + ratio * dx
    cy = y1 + ratio * dy
    return math.hypot(px - cx, py - cy)


@dataclass
class PointMappingEntry:
    point_id: str
    center_client: Tuple[float, float]
    logical_coord: Tuple[float, float] = (0.0, 0.0)
    label: str = ""

    def __post_init__(self):
        self.point_id = str(self.point_id or "")
        self.center_client = (float(self.center_client[0]), float(self.center_client[1]))
        self.logical_coord = (float(self.logical_coord[0]), float(self.logical_coord[1]))
        self.label = str(self.label or self.point_id or "")

    def copy(self) -> "PointMappingEntry":
        return PointMappingEntry(
            point_id=self.point_id,
            center_client=self.center_client,
            logical_coord=self.logical_coord,
            label=self.label,
        )

    def to_anchor(self) -> GridCoordinateAnchor:
        return GridCoordinateAnchor(
            cell_id=self.point_id,
            center_client=self.center_client,
            logical_coord=self.logical_coord,
            polygon=[],
            label=self.label or self.point_id,
        )

    @classmethod
    def from_anchor(cls, anchor: GridCoordinateAnchor) -> "PointMappingEntry":
        return cls(
            point_id=anchor.cell_id,
            center_client=anchor.center_client,
            logical_coord=anchor.logical_coord,
            label=anchor.label,
        )


@dataclass
class GuideLineModel:
    line_id: str
    start_client: Tuple[float, float]
    end_client: Tuple[float, float]
    style: str = "default"
    label: str = ""

    def __post_init__(self):
        self.line_id = str(self.line_id or "")
        self.start_client = (float(self.start_client[0]), float(self.start_client[1]))
        self.end_client = (float(self.end_client[0]), float(self.end_client[1]))
        self.style = self.style if self.style in GUIDE_LINE_STYLES else "default"
        self.label = str(self.label or GUIDE_LINE_STYLES[self.style]["label"])

    def copy(self) -> "GuideLineModel":
        return GuideLineModel(
            line_id=self.line_id,
            start_client=self.start_client,
            end_client=self.end_client,
            style=self.style,
            label=self.label,
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "line_id": self.line_id,
            "start_client": [self.start_client[0], self.start_client[1]],
            "end_client": [self.end_client[0], self.end_client[1]],
            "style": self.style,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> Optional["GuideLineModel"]:
        if not isinstance(data, dict):
            return None
        try:
            return cls(
                line_id=str(data.get("line_id", "")),
                start_client=tuple(data.get("start_client", (0.0, 0.0))),
                end_client=tuple(data.get("end_client", (0.0, 0.0))),
                style=str(data.get("style", "default") or "default"),
                label=str(data.get("label", "") or ""),
            )
        except Exception:
            return None


class NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
            return
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
            return
        event.ignore()


class PointMappingCanvas(QWidget):
    point_clicked = Signal(int, int)
    point_add_requested = Signal(float, float)
    guide_line_created = Signal(object, object)
    point_selected = Signal(str)
    line_selected = Signal(str)
    points_changed = Signal()
    lines_changed = Signal()

    _DRAG_NONE = 0
    _DRAG_LINE_START = 1
    _DRAG_LINE_END = 2
    _DRAG_LINE_BODY = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._default_size = QSize(960, 640)
        self._pixmap: Optional[QPixmap] = None
        self._image_size = QSize()
        self._zoom = 1.0
        self._marker_point: Optional[Tuple[float, float]] = None

        self._points: List[PointMappingEntry] = []
        self._guide_lines: List[GuideLineModel] = []
        self._selected_point_id: Optional[str] = None
        self._selected_line_id: Optional[str] = None

        self._add_point_mode = False
        self._add_line_mode = False
        self._pending_line_start: Optional[Tuple[float, float]] = None
        self._drag_point_id: Optional[str] = None

        self._drag_line_id: Optional[str] = None
        self._drag_line_mode: int = self._DRAG_NONE
        self._drag_line_anchor: Optional[Tuple[float, float]] = None

        self.setMouseTracking(True)
        self.setFixedSize(self._default_size)

    def set_image(self, image) -> None:
        if image is None or getattr(image, "size", 0) == 0:
            self.clear_image()
            return

        image = np.ascontiguousarray(image)
        height, width = image.shape[:2]
        bytes_per_line = image.shape[2] * width
        q_image = QImage(
            image.data,
            width,
            height,
            bytes_per_line,
            QImage.Format.Format_BGR888,
        ).copy()
        self._pixmap = QPixmap.fromImage(q_image)
        self._image_size = QSize(width, height)
        self._apply_scaled_size()
        self.update()

    def clear_image(self) -> None:
        self._pixmap = None
        self._image_size = QSize()
        self._pending_line_start = None
        self._drag_point_id = None
        self._drag_line_id = None
        self._drag_line_mode = self._DRAG_NONE
        self._drag_line_anchor = None
        self._marker_point = None
        self.setFixedSize(self._default_size)
        self.update()

    def image_size(self) -> QSize:
        return QSize(self._image_size)

    def set_zoom(self, scale: float) -> None:
        self._zoom = max(0.05, min(8.0, float(scale)))
        self._apply_scaled_size()
        self.update()

    def zoom(self) -> float:
        return self._zoom

    def set_marker_point(self, point: Optional[Tuple[float, float]]) -> None:
        self._marker_point = None if point is None else (float(point[0]), float(point[1]))
        self.update()

    def marker_point(self) -> Optional[Tuple[float, float]]:
        return None if self._marker_point is None else (self._marker_point[0], self._marker_point[1])

    def set_points(self, points: List[PointMappingEntry]) -> None:
        self._points = [point.copy() for point in points]
        if self._selected_point_id and not self._find_point(self._selected_point_id):
            self._selected_point_id = None
        self.update()

    def points(self) -> List[PointMappingEntry]:
        return [point.copy() for point in self._points]

    def set_guide_lines(self, guide_lines: List[GuideLineModel]) -> None:
        self._guide_lines = [line.copy() for line in guide_lines]
        if self._selected_line_id and not self._find_line(self._selected_line_id):
            self._selected_line_id = None
        self.update()

    def guide_lines(self) -> List[GuideLineModel]:
        return [line.copy() for line in self._guide_lines]

    def set_selected_point(self, point_id: Optional[str]) -> None:
        self._selected_point_id = point_id if point_id and self._find_point(point_id) else None
        if self._selected_point_id:
            self._selected_line_id = None
        self.update()

    def set_selected_line(self, line_id: Optional[str]) -> None:
        self._selected_line_id = line_id if line_id and self._find_line(line_id) else None
        if self._selected_line_id:
            self._selected_point_id = None
        self.update()

    def set_add_point_mode(self, enabled: bool) -> None:
        self._add_point_mode = bool(enabled)
        if enabled:
            self._add_line_mode = False
            self._pending_line_start = None
        self.update()

    def set_add_line_mode(self, enabled: bool) -> None:
        self._add_line_mode = bool(enabled)
        if enabled:
            self._add_point_mode = False
        if not enabled:
            self._pending_line_start = None
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)

        point = self._widget_to_image(event.position())
        if point is None:
            return super().mousePressEvent(event)

        image_point = (point.x(), point.y())
        self._marker_point = image_point
        self.point_clicked.emit(int(round(image_point[0])), int(round(image_point[1])))

        if self._add_point_mode:
            self.point_add_requested.emit(image_point[0], image_point[1])
            self.update()
            return

        if self._add_line_mode:
            if self._pending_line_start is None:
                self._pending_line_start = image_point
            else:
                start = self._pending_line_start
                self._pending_line_start = None
                self.guide_line_created.emit(start, image_point)
            self.update()
            return

        hit_point = self._hit_test_point(image_point)
        if hit_point is not None:
            self._selected_point_id = hit_point
            self._selected_line_id = None
            self._drag_point_id = hit_point
            self.point_selected.emit(hit_point)
            self.line_selected.emit("")
            self.update()
            return

        line_endpoint_hit = self._hit_test_line_endpoint(image_point)
        if line_endpoint_hit is not None:
            line_id, endpoint_type = line_endpoint_hit
            self._selected_line_id = line_id
            self._selected_point_id = None
            self._drag_line_id = line_id
            self._drag_line_mode = endpoint_type
            self.line_selected.emit(line_id)
            self.point_selected.emit("")
            self.update()
            return

        hit_line = self._hit_test_line(image_point)
        if hit_line is not None:
            self._selected_line_id = hit_line
            self._selected_point_id = None
            self._drag_line_id = hit_line
            self._drag_line_mode = self._DRAG_LINE_BODY
            self._drag_line_anchor = image_point
            self.line_selected.emit(hit_line)
            self.point_selected.emit("")
            self.update()
            return

        self._selected_point_id = None
        self._selected_line_id = None
        self.point_selected.emit("")
        self.line_selected.emit("")
        self.update()
        return super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        point = self._widget_to_image(event.position())
        if self._drag_point_id and point is not None:
            target = self._find_point(self._drag_point_id)
            if target is not None:
                target.center_client = (point.x(), point.y())
                self.points_changed.emit()
                self.update()
                return

        if self._drag_line_id and point is not None:
            target_line = self._find_line(self._drag_line_id)
            if target_line is not None:
                new_pos = (point.x(), point.y())
                if self._drag_line_mode == self._DRAG_LINE_START:
                    target_line.start_client = new_pos
                elif self._drag_line_mode == self._DRAG_LINE_END:
                    target_line.end_client = new_pos
                elif self._drag_line_mode == self._DRAG_LINE_BODY and self._drag_line_anchor is not None:
                    dx = new_pos[0] - self._drag_line_anchor[0]
                    dy = new_pos[1] - self._drag_line_anchor[1]
                    target_line.start_client = (
                        target_line.start_client[0] + dx,
                        target_line.start_client[1] + dy,
                    )
                    target_line.end_client = (
                        target_line.end_client[0] + dx,
                        target_line.end_client[1] + dy,
                    )
                    self._drag_line_anchor = new_pos
                self.lines_changed.emit()
                self.update()
                return

        if self._add_line_mode and self._pending_line_start is not None and point is not None:
            self._marker_point = (point.x(), point.y())
            self.setCursor(Qt.CrossCursor)
            self.update()
            return

        if self._add_point_mode or self._add_line_mode:
            self.setCursor(Qt.CrossCursor)
        elif point is not None:
            img_pt = (point.x(), point.y())
            if self._hit_test_point(img_pt) is not None:
                self.setCursor(Qt.OpenHandCursor)
            elif self._hit_test_line_endpoint(img_pt) is not None:
                self.setCursor(Qt.SizeAllCursor)
            elif self._hit_test_line(img_pt) is not None:
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
        return super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_point_id = None
            self._drag_line_id = None
            self._drag_line_mode = self._DRAG_NONE
            self._drag_line_anchor = None
            self.update()
        return super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if (
            not self._add_point_mode
            and not self._add_line_mode
            and self._drag_point_id is None
            and self._drag_line_id is None
        ):
            self.setCursor(Qt.ArrowCursor)
        return super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#111111"))

        if self._pixmap is None:
            painter.setPen(QColor("#cccccc"))
            painter.drawText(self.rect(), Qt.AlignCenter, "请先截取目标窗口图像")
            return

        painter.save()
        painter.scale(self._zoom, self._zoom)
        painter.drawPixmap(0, 0, self._pixmap)
        self._draw_guide_lines(painter)
        self._draw_pending_line(painter)
        self._draw_points(painter)
        self._draw_marker(painter)
        painter.restore()

    def _draw_guide_lines(self, painter: QPainter) -> None:
        endpoint_radius = 4.5 / max(self._zoom, 1e-6)
        for line in self._guide_lines:
            config = GUIDE_LINE_STYLES.get(line.style, GUIDE_LINE_STYLES["default"])
            is_selected = line.line_id == self._selected_line_id
            width = 2.6 if is_selected else 1.7
            line_color = QColor(str(config["color"]))
            pen = QPen(line_color, width / max(self._zoom, 1e-6), config["pen_style"])
            pen.setCosmetic(False)
            painter.setPen(pen)
            painter.drawLine(
                QPointF(line.start_client[0], line.start_client[1]),
                QPointF(line.end_client[0], line.end_client[1]),
            )
            if is_selected:
                ep_pen = QPen(QColor("#ffffff"), 1.5 / max(self._zoom, 1e-6))
                ep_pen.setCosmetic(False)
                painter.setPen(ep_pen)
                painter.setBrush(line_color)
                painter.drawEllipse(
                    QPointF(line.start_client[0], line.start_client[1]),
                    endpoint_radius,
                    endpoint_radius,
                )
                painter.drawEllipse(
                    QPointF(line.end_client[0], line.end_client[1]),
                    endpoint_radius,
                    endpoint_radius,
                )
                painter.setBrush(Qt.NoBrush)

    def _draw_pending_line(self, painter: QPainter) -> None:
        if self._pending_line_start is None or self._marker_point is None:
            return
        pen = QPen(QColor("#73d13d"), 1.4 / max(self._zoom, 1e-6), Qt.DashLine)
        pen.setCosmetic(False)
        painter.setPen(pen)
        painter.drawLine(
            QPointF(self._pending_line_start[0], self._pending_line_start[1]),
            QPointF(self._marker_point[0], self._marker_point[1]),
        )

    def _draw_points(self, painter: QPainter) -> None:
        radius = 5.2 / max(self._zoom, 1e-6)
        for point in self._points:
            selected = point.point_id == self._selected_point_id
            color = QColor("#fa8c16") if selected else QColor("#40a9ff")
            pen = QPen(color, 2.0 / max(self._zoom, 1e-6))
            pen.setCosmetic(False)
            painter.setPen(pen)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(point.center_client[0], point.center_client[1]), radius, radius)
            label = _format_logical_pair(point.logical_coord)
            painter.drawText(point.center_client[0] + 8, point.center_client[1] - 8, label)

    def _draw_marker(self, painter: QPainter) -> None:
        if self._marker_point is None:
            return
        x, y = self._marker_point
        pen = QPen(QColor("#ffffff"), 1.4 / max(self._zoom, 1e-6))
        pen.setCosmetic(False)
        painter.setPen(pen)
        offset = 8.0 / max(self._zoom, 1e-6)
        painter.drawLine(QPointF(x - offset, y), QPointF(x + offset, y))
        painter.drawLine(QPointF(x, y - offset), QPointF(x, y + offset))

    def _apply_scaled_size(self) -> None:
        if self._pixmap is None:
            self.setFixedSize(self._default_size)
            return
        width = max(1, int(round(self._image_size.width() * self._zoom)))
        height = max(1, int(round(self._image_size.height() * self._zoom)))
        self.setFixedSize(width, height)

    def _widget_to_image(self, position) -> Optional[QPointF]:
        if self._pixmap is None or self._zoom <= 0:
            return None
        image_x = float(position.x()) / self._zoom
        image_y = float(position.y()) / self._zoom
        if 0 <= image_x < self._image_size.width() and 0 <= image_y < self._image_size.height():
            return QPointF(image_x, image_y)
        return None

    def _find_point(self, point_id: Optional[str]) -> Optional[PointMappingEntry]:
        if not point_id:
            return None
        for point in self._points:
            if point.point_id == point_id:
                return point
        return None

    def _find_line(self, line_id: Optional[str]) -> Optional[GuideLineModel]:
        if not line_id:
            return None
        for line in self._guide_lines:
            if line.line_id == line_id:
                return line
        return None

    def _hit_test_point(self, image_point: Tuple[float, float]) -> Optional[str]:
        threshold = max(6.0, 10.0 / max(self._zoom, 1e-6))
        for point in self._points:
            if _distance(image_point, point.center_client) <= threshold:
                return point.point_id
        return None

    def _hit_test_line_endpoint(
        self, image_point: Tuple[float, float]
    ) -> Optional[Tuple[str, int]]:
        threshold = max(8.0, 12.0 / max(self._zoom, 1e-6))
        for line in self._guide_lines:
            if _distance(image_point, line.start_client) <= threshold:
                return (line.line_id, self._DRAG_LINE_START)
            if _distance(image_point, line.end_client) <= threshold:
                return (line.line_id, self._DRAG_LINE_END)
        return None

    def _hit_test_line(self, image_point: Tuple[float, float]) -> Optional[str]:
        threshold = max(5.0, 8.0 / max(self._zoom, 1e-6))
        best_id = None
        best_distance = float("inf")
        for line in self._guide_lines:
            distance = _distance_to_segment(image_point, line.start_client, line.end_client)
            if distance <= threshold and distance < best_distance:
                best_distance = distance
                best_id = line.line_id
        return best_id


class CoordinateTransformPanel(QWidget):
    """窗口坐标点映射与辅助线工具页。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._capture: Optional[ScreenCapture] = None
        self._window_manager: Optional[WindowManager] = None
        self._current_window: Optional[WindowInfo] = None

        self._storage = CoordinateMappingStorage()
        self._workspace_storage = CoordinateWorkspaceStateStorage()
        self._current_image = None
        self._point_entries: List[PointMappingEntry] = []
        self._guide_lines: List[GuideLineModel] = []
        self._selected_point_id: Optional[str] = None
        self._selected_line_id: Optional[str] = None
        self._active_workspace_state: Optional[CoordinateWorkspaceState] = None

        self._active_profile: Optional[CoordinateMappingProfile] = None
        self._pending_profile: Optional[CoordinateMappingProfile] = None
        self._last_fit_error = ""

        self._init_ui()
        self._refresh_point_table()
        self._refresh_guide_line_table()
        self._refresh_selected_point_info()
        self._refresh_profile_info_label()
        self._refresh_profile_summary()
        self._update_status("请先选择目标窗口，然后截图。")

    def setup_dependencies(self, capture: ScreenCapture, window_manager: WindowManager):
        self._capture = capture
        self._window_manager = window_manager

    def set_current_window(self, window: Optional[WindowInfo]):
        self._current_window = window
        self._current_image = None
        self._point_entries = []
        self._guide_lines = []
        self._selected_point_id = None
        self._selected_line_id = None
        self._active_profile = None
        self._pending_profile = None
        self._active_workspace_state = None
        self._last_fit_error = ""

        self._canvas.clear_image()
        self._canvas.set_points([])
        self._canvas.set_guide_lines([])
        self._canvas.set_selected_point(None)
        self._canvas.set_selected_line(None)
        self._canvas.set_marker_point(None)

        if not window:
            self._window_info_label.setText("未选择窗口")
            self._refresh_point_table()
            self._refresh_guide_line_table()
            self._refresh_selected_point_info()
            self._refresh_profile_info_label()
            self._refresh_profile_summary()
            self._update_status("请先选择目标窗口。")
            return

        self._window_info_label.setText(
            f"{window.title}\n类名: {window.class_name}\n句柄: 0x{window.hwnd:X}"
        )
        self._load_profile_for_current_window()
        self._load_workspace_state_for_current_window()
        self._refresh_point_table()
        self._refresh_guide_line_table()
        self._refresh_selected_point_info()
        self._refresh_profile_info_label()
        self._refresh_profile_summary()
        self._convert_logical_to_screen(auto=True)
        self._convert_relative_to_logical(auto=True)

    def eventFilter(self, watched, event):
        if watched is self._image_scroll.viewport() and event.type() == QEvent.Resize:
            if self._fit_view_check.isChecked():
                self._refresh_canvas_zoom()
        return super().eventFilter(watched, event)

    def _init_ui(self):
        layout = QHBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)

        info_group = QGroupBox("当前窗口")
        info_form = QFormLayout(info_group)
        self._window_info_label = QLabel("未选择窗口")
        self._window_info_label.setWordWrap(True)
        info_form.addRow("窗口:", self._window_info_label)

        self._mapping_path_label = QLabel(str(self._storage.file_path))
        self._mapping_path_label.setWordWrap(True)
        info_form.addRow("映射文件:", self._mapping_path_label)

        self._workspace_path_label = QLabel(str(self._workspace_storage.file_path))
        self._workspace_path_label.setWordWrap(True)
        info_form.addRow("状态文件:", self._workspace_path_label)

        self._profile_info_label = QLabel("未加载映射")
        self._profile_info_label.setWordWrap(True)
        info_form.addRow("当前映射:", self._profile_info_label)

        capture_row = QHBoxLayout()
        self._capture_btn = QPushButton("截图")
        self._capture_btn.clicked.connect(self._capture_window_image)
        capture_row.addWidget(self._capture_btn)

        self._use_background_capture = QCheckBox("优先后台截图")
        self._use_background_capture.setChecked(True)
        capture_row.addWidget(self._use_background_capture)
        info_form.addRow("截图:", capture_row)
        left_layout.addWidget(info_group)

        point_group = QGroupBox("坐标点映射")
        point_layout = QVBoxLayout(point_group)
        point_hint = QLabel("点击“添加坐标点”后，在右侧截图上点击即可新增一个坐标点。坐标点由逻辑坐标和屏幕相对坐标组成，可拖动修改屏幕位置。")
        point_hint.setWordWrap(True)
        point_layout.addWidget(point_hint)

        point_button_row = QHBoxLayout()
        self._add_point_btn = QPushButton("添加坐标点")
        self._add_point_btn.setCheckable(True)
        self._add_point_btn.toggled.connect(self._on_add_point_toggled)
        point_button_row.addWidget(self._add_point_btn)

        self._delete_selected_point_btn = QPushButton("删除选中点")
        self._delete_selected_point_btn.clicked.connect(self._delete_selected_point)
        point_button_row.addWidget(self._delete_selected_point_btn)

        self._clear_points_btn = QPushButton("清空坐标点")
        self._clear_points_btn.clicked.connect(self._clear_points)
        point_button_row.addWidget(self._clear_points_btn)
        point_layout.addLayout(point_button_row)

        io_button_row = QHBoxLayout()
        self._export_points_btn = QPushButton("导出坐标点")
        self._export_points_btn.clicked.connect(self._export_points)
        io_button_row.addWidget(self._export_points_btn)

        self._import_points_btn = QPushButton("导入坐标点")
        self._import_points_btn.clicked.connect(self._import_points)
        io_button_row.addWidget(self._import_points_btn)
        point_layout.addLayout(io_button_row)

        self._point_summary_label = QLabel("尚未添加坐标点")
        self._point_summary_label.setWordWrap(True)
        point_layout.addWidget(self._point_summary_label)
        left_layout.addWidget(point_group)

        selected_group = QGroupBox("选中坐标点")
        selected_form = QFormLayout(selected_group)
        self._selected_point_label = QLabel("未选中")
        self._selected_point_label.setWordWrap(True)
        selected_form.addRow("点ID:", self._selected_point_label)

        self._selected_point_relative_label = QLabel("-")
        self._selected_point_relative_label.setWordWrap(True)
        selected_form.addRow("相对坐标:", self._selected_point_relative_label)

        self._logical_x_spin = NoWheelSpinBox()
        self._logical_x_spin.setRange(-999999, 999999)
        self._logical_x_spin.setSingleStep(1)
        self._logical_x_spin.setFixedWidth(130)
        self._logical_x_spin.valueChanged.connect(lambda _: self._convert_logical_to_screen(auto=True))
        selected_form.addRow("逻辑 X:", self._logical_x_spin)

        self._logical_y_spin = NoWheelSpinBox()
        self._logical_y_spin.setRange(-999999, 999999)
        self._logical_y_spin.setSingleStep(1)
        self._logical_y_spin.setFixedWidth(130)
        self._logical_y_spin.valueChanged.connect(lambda _: self._convert_logical_to_screen(auto=True))
        selected_form.addRow("逻辑 Y:", self._logical_y_spin)

        selected_button_row = QHBoxLayout()
        self._save_selected_point_btn = QPushButton("保存到选中点")
        self._save_selected_point_btn.clicked.connect(self._save_selected_point)
        selected_button_row.addWidget(self._save_selected_point_btn)

        self._delete_selected_point_from_section_btn = QPushButton("移除当前点")
        self._delete_selected_point_from_section_btn.clicked.connect(self._delete_selected_point)
        selected_button_row.addWidget(self._delete_selected_point_from_section_btn)
        selected_form.addRow(selected_button_row)
        left_layout.addWidget(selected_group)

        points_table_group = QGroupBox("坐标点列表")
        points_table_layout = QVBoxLayout(points_table_group)
        self._point_table = QTableWidget(0, 5)
        self._point_table.setHorizontalHeaderLabels(["点ID", "逻辑X", "逻辑Y", "相对X", "相对Y"])
        self._point_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._point_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._point_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._point_table.verticalHeader().setVisible(False)
        self._point_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._point_table.itemSelectionChanged.connect(self._on_point_table_selection_changed)
        points_table_layout.addWidget(self._point_table)
        left_layout.addWidget(points_table_group)

        line_group = QGroupBox("辅助线")
        line_layout = QVBoxLayout(line_group)
        line_hint = QLabel("点击“绘制辅助线”后，先左键确定第一个点，移动鼠标可实时预览辅助线，再次左键确定第二个点。不同样式会用不同颜色或线型显示。")
        line_hint.setWordWrap(True)
        line_layout.addWidget(line_hint)

        line_style_row = QHBoxLayout()
        line_style_row.addWidget(QLabel("样式:"))
        self._line_style_combo = QComboBox()
        for style_key, config in GUIDE_LINE_STYLES.items():
            self._line_style_combo.addItem(str(config["label"]), style_key)
        line_style_row.addWidget(self._line_style_combo)
        line_style_row.addStretch()
        line_layout.addLayout(line_style_row)

        line_button_row = QHBoxLayout()
        self._add_line_btn = QPushButton("绘制辅助线")
        self._add_line_btn.setCheckable(True)
        self._add_line_btn.toggled.connect(self._on_add_line_toggled)
        line_button_row.addWidget(self._add_line_btn)

        self._delete_selected_line_btn = QPushButton("删除选中线")
        self._delete_selected_line_btn.clicked.connect(self._delete_selected_line)
        line_button_row.addWidget(self._delete_selected_line_btn)

        self._clear_lines_btn = QPushButton("清空辅助线")
        self._clear_lines_btn.clicked.connect(self._clear_guide_lines)
        line_button_row.addWidget(self._clear_lines_btn)
        line_layout.addLayout(line_button_row)

        self._guide_line_table = QTableWidget(0, 4)
        self._guide_line_table.setHorizontalHeaderLabels(["线ID", "样式", "起点", "终点"])
        self._guide_line_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._guide_line_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._guide_line_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._guide_line_table.verticalHeader().setVisible(False)
        self._guide_line_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._guide_line_table.itemSelectionChanged.connect(self._on_guide_line_table_selection_changed)
        line_layout.addWidget(self._guide_line_table)
        left_layout.addWidget(line_group)

        summary_group = QGroupBox("当前映射预览")
        summary_layout = QVBoxLayout(summary_group)
        self._profile_summary_label = QLabel("尚未生成映射")
        self._profile_summary_label.setWordWrap(True)
        self._profile_summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        summary_layout.addWidget(self._profile_summary_label)

        self._save_mapping_btn = QPushButton("保存当前状态")
        self._save_mapping_btn.clicked.connect(self._save_mapping)
        summary_layout.addWidget(self._save_mapping_btn)
        left_layout.addWidget(summary_group)

        convert_group = QGroupBox("逻辑坐标 -> 相对坐标/当前窗口坐标")
        convert_form = QFormLayout(convert_group)
        self._logical_convert_btn = QPushButton("转换并标记")
        self._logical_convert_btn.clicked.connect(self._convert_logical_to_screen)
        convert_form.addRow(self._logical_convert_btn)

        self._logical_result_label = QLabel("结果: -")
        self._logical_result_label.setWordWrap(True)
        convert_form.addRow("输出:", self._logical_result_label)
        left_layout.addWidget(convert_group)

        reverse_group = QGroupBox("相对坐标 -> 逻辑坐标")
        reverse_form = QFormLayout(reverse_group)
        self._screen_x_spin = NoWheelDoubleSpinBox()
        self._screen_x_spin.setDecimals(6)
        self._screen_x_spin.setRange(-9999.0, 9999.0)
        self._screen_x_spin.setSingleStep(0.01)
        self._screen_x_spin.setFixedWidth(130)
        self._screen_x_spin.valueChanged.connect(lambda _: self._convert_relative_to_logical(auto=True))
        reverse_form.addRow("相对 X:", self._screen_x_spin)

        self._screen_y_spin = NoWheelDoubleSpinBox()
        self._screen_y_spin.setDecimals(6)
        self._screen_y_spin.setRange(-9999.0, 9999.0)
        self._screen_y_spin.setSingleStep(0.01)
        self._screen_y_spin.setFixedWidth(130)
        self._screen_y_spin.valueChanged.connect(lambda _: self._convert_relative_to_logical(auto=True))
        reverse_form.addRow("相对 Y:", self._screen_y_spin)

        self._screen_convert_btn = QPushButton("转换")
        self._screen_convert_btn.clicked.connect(self._convert_relative_to_logical)
        reverse_form.addRow(self._screen_convert_btn)

        self._screen_result_label = QLabel("结果: -")
        self._screen_result_label.setWordWrap(True)
        reverse_form.addRow("输出:", self._screen_result_label)
        left_layout.addWidget(reverse_group)

        click_group = QGroupBox("图像点击结果")
        click_layout = QVBoxLayout(click_group)
        self._clicked_result_label = QLabel("点击截图后，会显示截图坐标、相对坐标、当前窗口像素坐标和逻辑坐标。")
        self._clicked_result_label.setWordWrap(True)
        self._clicked_result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        click_layout.addWidget(self._clicked_result_label)
        left_layout.addWidget(click_group)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        left_layout.addWidget(self._status_label)
        left_layout.addStretch()

        left_scroll.setWidget(left_container)
        splitter.addWidget(left_scroll)

        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)

        self._selection_label = QLabel("右侧截图支持等比缩放。点击“添加坐标点”后在图上点击可新增点；默认模式下拖动点可以调整屏幕相对坐标。")
        self._selection_label.setWordWrap(True)
        right_layout.addWidget(self._selection_label)

        zoom_row = QHBoxLayout()
        self._fit_view_check = QCheckBox("适应窗口")
        self._fit_view_check.setChecked(True)
        self._fit_view_check.toggled.connect(self._on_fit_view_toggled)
        zoom_row.addWidget(self._fit_view_check)

        self._zoom_out_btn = QToolButton()
        self._zoom_out_btn.setText("-")
        self._zoom_out_btn.clicked.connect(lambda: self._change_zoom(1 / 1.2))
        zoom_row.addWidget(self._zoom_out_btn)

        self._zoom_reset_btn = QToolButton()
        self._zoom_reset_btn.setText("100%")
        self._zoom_reset_btn.clicked.connect(self._reset_zoom)
        zoom_row.addWidget(self._zoom_reset_btn)

        self._zoom_in_btn = QToolButton()
        self._zoom_in_btn.setText("+")
        self._zoom_in_btn.clicked.connect(lambda: self._change_zoom(1.2))
        zoom_row.addWidget(self._zoom_in_btn)

        self._zoom_percent_label = QLabel("100%")
        zoom_row.addWidget(self._zoom_percent_label)
        zoom_row.addStretch()
        right_layout.addLayout(zoom_row)

        self._image_scroll = QScrollArea()
        self._image_scroll.setWidgetResizable(False)
        self._image_scroll.viewport().installEventFilter(self)

        self._canvas = PointMappingCanvas()
        self._canvas.point_clicked.connect(self._on_canvas_point_clicked)
        self._canvas.point_add_requested.connect(self._add_point_at)
        self._canvas.guide_line_created.connect(self._add_guide_line_between)
        self._canvas.point_selected.connect(self._on_canvas_point_selected)
        self._canvas.line_selected.connect(self._on_canvas_line_selected)
        self._canvas.points_changed.connect(self._on_canvas_points_changed)
        self._canvas.lines_changed.connect(self._on_canvas_lines_changed)
        self._image_scroll.setWidget(self._canvas)
        right_layout.addWidget(self._image_scroll, 1)

        splitter.addWidget(right_container)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([500, 1020])

        self._on_fit_view_toggled(True)

    def _capture_window_image(self):
        if not self._current_window:
            QMessageBox.warning(self, "警告", "请先选择目标窗口")
            return
        if not self._capture:
            QMessageBox.warning(self, "警告", "截图模块尚未初始化")
            return

        self._capture_btn.setEnabled(False)
        self._update_status("正在截取目标窗口图像...")
        QApplication.processEvents()

        try:
            previous_size = self._get_current_client_size()
            if self._use_background_capture.isChecked():
                image = self._capture.capture_window_background(self._current_window.hwnd)
                method = "后台优先"
            else:
                image = self._capture.capture_window(self._current_window.hwnd)
                method = "前台"

            if image is None:
                QMessageBox.warning(self, "警告", "截图失败，请确认目标窗口仍然有效")
                self._update_status("截图失败，请确认目标窗口仍然有效。", error=True)
                return

            new_size = (int(image.shape[1]), int(image.shape[0]))
            if previous_size and tuple(previous_size) != tuple(new_size):
                self._rescale_workspace_geometry(previous_size, new_size)

            self._current_image = image
            self._canvas.set_image(image)
            self._canvas.set_points(self._point_entries)
            self._canvas.set_guide_lines(self._guide_lines)
            self._canvas.set_selected_point(self._selected_point_id)
            self._canvas.set_selected_line(self._selected_line_id)
            self._rebuild_pending_profile()
            self._refresh_canvas_zoom()
            self._refresh_point_table()
            self._refresh_guide_line_table()
            self._refresh_selected_point_info()
            self._update_status(
                f"截图成功：{image.shape[1]}x{image.shape[0]}。相对坐标范围按当前截图归一化为 0 到 1。截图方式：{method}。"
            )
        except Exception as e:
            QMessageBox.critical(self, "错误", f"截图失败: {e}")
            self._update_status(f"截图失败: {e}", error=True)
        finally:
            self._capture_btn.setEnabled(True)

    def _on_add_point_toggled(self, checked: bool):
        if checked and self._add_line_btn.isChecked():
            self._add_line_btn.blockSignals(True)
            self._add_line_btn.setChecked(False)
            self._add_line_btn.blockSignals(False)
            self._canvas.set_add_line_mode(False)
        self._canvas.set_add_point_mode(checked)
        if checked:
            self._selection_label.setText("添加坐标点模式已开启：在右侧截图上点击即可新增一个坐标点。")
            self._update_status("添加坐标点模式已开启。")
        else:
            self._selection_label.setText("右侧截图支持等比缩放。点击“添加坐标点”后在图上点击可新增点；默认模式下拖动点可以调整屏幕相对坐标。")

    def _on_add_line_toggled(self, checked: bool):
        if checked and self._add_point_btn.isChecked():
            self._add_point_btn.blockSignals(True)
            self._add_point_btn.setChecked(False)
            self._add_point_btn.blockSignals(False)
            self._canvas.set_add_point_mode(False)
        self._canvas.set_add_line_mode(checked)
        if checked:
            self._selection_label.setText("绘制辅助线模式已开启：先左键确定第一个点，移动鼠标可实时预览辅助线，再次左键完成绘制。")
            self._update_status("绘制辅助线模式已开启。")
        else:
            self._selection_label.setText("右侧截图支持等比缩放。点击“添加坐标点”后在图上点击可新增点；默认模式下拖动点可以调整屏幕相对坐标。")

    def _add_point_at(self, x: float, y: float):
        point_id = self._next_point_id()
        new_point = PointMappingEntry(
            point_id=point_id,
            center_client=(x, y),
            logical_coord=(_logical_int(self._logical_x_spin.value()), _logical_int(self._logical_y_spin.value())),
            label=point_id,
        )
        self._point_entries.append(new_point)
        self._selected_point_id = point_id
        self._selected_line_id = None
        self._canvas.set_points(self._point_entries)
        self._canvas.set_selected_point(point_id)
        self._canvas.set_selected_line(None)
        self._refresh_point_table()
        self._refresh_selected_point_info()
        self._rebuild_pending_profile()
        self._update_status(f"已添加坐标点 {point_id}。")

    def _save_selected_point(self):
        point = self._find_point(self._selected_point_id)
        if point is None:
            QMessageBox.information(self, "提示", "请先选中一个坐标点")
            return

        point.logical_coord = (_logical_int(self._logical_x_spin.value()), _logical_int(self._logical_y_spin.value()))
        self._canvas.set_points(self._point_entries)
        self._refresh_point_table()
        self._refresh_selected_point_info()
        self._rebuild_pending_profile()
        self._update_status(f"已更新坐标点 {point.point_id} 的逻辑坐标。")

    def _delete_selected_point(self):
        if not self._selected_point_id:
            QMessageBox.information(self, "提示", "请先选中一个坐标点")
            return

        target_id = self._selected_point_id
        self._point_entries = [point for point in self._point_entries if point.point_id != target_id]
        self._selected_point_id = None
        self._canvas.set_points(self._point_entries)
        self._canvas.set_selected_point(None)
        self._refresh_point_table()
        self._refresh_selected_point_info()
        self._rebuild_pending_profile()
        self._update_status(f"已删除坐标点 {target_id}。")

    def _clear_points(self):
        self._point_entries = []
        self._selected_point_id = None
        self._canvas.set_points([])
        self._canvas.set_selected_point(None)
        self._refresh_point_table()
        self._refresh_selected_point_info()
        self._rebuild_pending_profile()
        self._update_status("已清空所有坐标点。")

    def _export_points(self):
        if not self._point_entries:
            QMessageBox.information(self, "提示", "当前没有坐标点可导出")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "导出坐标点", "", "CSV 文件 (*.csv);;All Files (*)"
        )
        if not path:
            return

        try:
            client_size = self._get_current_client_size()
            with open(path, "w", encoding="utf-8-sig") as f:
                f.write("点ID,逻辑X,逻辑Y,相对X,相对Y\n")
                for point in self._point_entries:
                    rx, ry = self._point_relative_tuple(point.center_client)
                    f.write(
                        f"{point.point_id},{_logical_int(point.logical_coord[0])},"
                        f"{_logical_int(point.logical_coord[1])},{rx:.6f},{ry:.6f}\n"
                    )
            self._update_status(f"已导出 {len(self._point_entries)} 个坐标点到 {os.path.basename(path)}。")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {e}")

    def _import_points(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入坐标点", "", "CSV 文件 (*.csv);;All Files (*)"
        )
        if not path:
            return

        client_size = self._get_current_client_size()
        if not client_size:
            QMessageBox.warning(self, "警告", "请先截图，以便将相对坐标转为客户区坐标")
            return

        try:
            imported: List[PointMappingEntry] = []
            used_ids = {point.point_id for point in self._point_entries}
            with open(path, "r", encoding="utf-8-sig") as f:
                lines = f.read().strip().splitlines()

            if not lines:
                QMessageBox.information(self, "提示", "文件为空")
                return

            start_index = 0
            header = lines[0].strip()
            if header.startswith("点ID") or header.lower().startswith("point"):
                start_index = 1

            for line_text in lines[start_index:]:
                line_text = line_text.strip()
                if not line_text:
                    continue
                parts = line_text.split(",")
                if len(parts) < 4:
                    continue

                point_id = parts[0].strip()
                logical_x = _logical_int(float(parts[1].strip()))
                logical_y = _logical_int(float(parts[2].strip()))
                relative_x = float(parts[3].strip())
                relative_y = float(parts[4].strip()) if len(parts) >= 5 else 0.0

                client_x = relative_x * client_size[0]
                client_y = relative_y * client_size[1]

                if not point_id or point_id in used_ids:
                    point_id = self._next_point_id_from(used_ids)
                used_ids.add(point_id)

                imported.append(
                    PointMappingEntry(
                        point_id=point_id,
                        center_client=(client_x, client_y),
                        logical_coord=(logical_x, logical_y),
                        label=point_id,
                    )
                )

            if not imported:
                QMessageBox.information(self, "提示", "未从文件中解析到有效坐标点")
                return

            self._point_entries.extend(imported)
            self._canvas.set_points(self._point_entries)
            self._refresh_point_table()
            self._refresh_selected_point_info()
            self._rebuild_pending_profile()
            self._update_status(f"已导入 {len(imported)} 个坐标点。")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导入失败: {e}")

    def _add_guide_line_between(self, start, end):
        line_id = self._next_line_id()
        style = str(self._line_style_combo.currentData() or "default")
        line = GuideLineModel(
            line_id=line_id,
            start_client=tuple(start),
            end_client=tuple(end),
            style=style,
            label=str(GUIDE_LINE_STYLES[style]["label"]),
        )
        self._guide_lines.append(line)
        self._selected_line_id = line_id
        self._selected_point_id = None
        self._canvas.set_guide_lines(self._guide_lines)
        self._canvas.set_selected_line(line_id)
        self._canvas.set_selected_point(None)
        self._refresh_guide_line_table()
        self._update_status(f"已新增辅助线 {line_id}。")

    def _delete_selected_line(self):
        if not self._selected_line_id:
            QMessageBox.information(self, "提示", "请先选中一条辅助线")
            return

        target_id = self._selected_line_id
        self._guide_lines = [line for line in self._guide_lines if line.line_id != target_id]
        self._selected_line_id = None
        self._canvas.set_guide_lines(self._guide_lines)
        self._canvas.set_selected_line(None)
        self._refresh_guide_line_table()
        self._update_status(f"已删除辅助线 {target_id}。")

    def _clear_guide_lines(self):
        self._guide_lines = []
        self._selected_line_id = None
        self._canvas.set_guide_lines([])
        self._canvas.set_selected_line(None)
        self._refresh_guide_line_table()
        self._update_status("已清空所有辅助线。")

    def _on_canvas_point_clicked(self, x: int, y: int):
        self._canvas.set_marker_point((x, y))
        client_rect = self._get_current_client_rect()
        profile = self._effective_profile()
        image_client_size = self._get_current_client_size()

        result = [f"截图坐标: ({x}, {y})"]
        relative_x = None
        relative_y = None
        if image_client_size:
            relative_x = x / image_client_size[0]
            relative_y = y / image_client_size[1]
            result.append(f"相对坐标: ({relative_x:.6f}, {relative_y:.6f})")
            self._screen_x_spin.blockSignals(True)
            self._screen_y_spin.blockSignals(True)
            self._screen_x_spin.setValue(relative_x)
            self._screen_y_spin.setValue(relative_y)
            self._screen_x_spin.blockSignals(False)
            self._screen_y_spin.blockSignals(False)
        else:
            result.append("相对坐标: 当前无法计算")

        if client_rect:
            if relative_x is not None and relative_y is not None:
                live_width = client_rect[2] - client_rect[0]
                live_height = client_rect[3] - client_rect[1]
                screen_x = int(round(client_rect[0] + relative_x * live_width))
                screen_y = int(round(client_rect[1] + relative_y * live_height))
            else:
                screen_x = int(round(client_rect[0] + x))
                screen_y = int(round(client_rect[1] + y))
            result.append(f"当前窗口像素坐标: ({screen_x}, {screen_y})")
        else:
            result.append("当前窗口像素坐标: 当前无法获取")

        if profile:
            try:
                logical_x, logical_y = profile.client_to_logical(x, y, image_client_size)
                result.append(f"逻辑坐标: ({_logical_int(logical_x)}, {_logical_int(logical_y)})")
            except Exception as e:
                result.append(f"逻辑坐标: 转换失败 ({e})")
        else:
            result.append("逻辑坐标: 需要至少 3 个不共线的坐标点")

        self._clicked_result_label.setText("\n".join(result))

    def _on_canvas_point_selected(self, point_id: str):
        self._selected_point_id = point_id or None
        self._selected_line_id = None
        self._canvas.set_selected_point(self._selected_point_id)
        self._canvas.set_selected_line(None)
        self._select_table_row(self._point_table, 0, self._selected_point_id)
        self._clear_table_selection(self._guide_line_table)
        self._refresh_selected_point_info()

    def _on_canvas_line_selected(self, line_id: str):
        self._selected_line_id = line_id or None
        if self._selected_line_id:
            self._selected_point_id = None
            self._canvas.set_selected_point(None)
            self._refresh_selected_point_info()
        self._canvas.set_selected_line(self._selected_line_id)
        self._select_table_row(self._guide_line_table, 0, self._selected_line_id)
        if self._selected_line_id:
            self._clear_table_selection(self._point_table)

    def _on_canvas_points_changed(self):
        self._point_entries = self._canvas.points()
        self._refresh_point_table()
        self._refresh_selected_point_info()
        self._rebuild_pending_profile()

    def _on_canvas_lines_changed(self):
        self._guide_lines = self._canvas.guide_lines()
        self._refresh_guide_line_table()

    def _on_point_table_selection_changed(self):
        rows = sorted({item.row() for item in self._point_table.selectedItems()})
        if not rows:
            return
        item = self._point_table.item(rows[0], 0)
        if item is None:
            return
        self._selected_point_id = item.text()
        self._selected_line_id = None
        self._canvas.set_selected_point(self._selected_point_id)
        self._canvas.set_selected_line(None)
        self._clear_table_selection(self._guide_line_table)
        self._refresh_selected_point_info()

    def _on_guide_line_table_selection_changed(self):
        rows = sorted({item.row() for item in self._guide_line_table.selectedItems()})
        if not rows:
            return
        item = self._guide_line_table.item(rows[0], 0)
        if item is None:
            return
        self._selected_line_id = item.text()
        self._selected_point_id = None
        self._canvas.set_selected_line(self._selected_line_id)
        self._canvas.set_selected_point(None)
        self._clear_table_selection(self._point_table)
        self._refresh_selected_point_info()

    def _load_profile_for_current_window(self):
        if not self._current_window:
            return

        profile = self._storage.find_profile_for_window(self._current_window)
        self._active_profile = profile
        self._pending_profile = None
        self._point_entries = []

        if profile and profile.anchor_cells:
            self._point_entries = [PointMappingEntry.from_anchor(anchor) for anchor in profile.anchor_cells]

    def _load_workspace_state_for_current_window(self):
        if not self._current_window:
            return

        state = self._workspace_storage.find_state_for_window(self._current_window)
        self._active_workspace_state = state
        if state is None:
            self._canvas.set_points(self._point_entries)
            self._canvas.set_guide_lines(self._guide_lines)
            self._rebuild_pending_profile()
            return

        self._guide_lines = []
        for raw_line in state.guide_lines:
            line = GuideLineModel.from_dict(raw_line)
            if line is not None:
                self._guide_lines.append(line)

        self._point_entries = [PointMappingEntry.from_anchor(anchor) for anchor in state.anchor_cells]
        self._selected_point_id = state.selected_cell_id or None
        self._selected_line_id = state.selected_line_id or None

        screenshot_image = self._load_workspace_screenshot(state.screenshot_path)
        self._current_image = screenshot_image
        if screenshot_image is not None:
            self._canvas.set_image(screenshot_image)
        else:
            self._canvas.clear_image()

        self._canvas.set_points(self._point_entries)
        self._canvas.set_guide_lines(self._guide_lines)
        self._canvas.set_selected_point(self._selected_point_id)
        self._canvas.set_selected_line(self._selected_line_id)
        self._canvas.set_marker_point(state.marker_point)

        self._logical_x_spin.blockSignals(True)
        self._logical_y_spin.blockSignals(True)
        self._screen_x_spin.blockSignals(True)
        self._screen_y_spin.blockSignals(True)
        self._logical_x_spin.setValue(_logical_int(state.logical_input[0]))
        self._logical_y_spin.setValue(_logical_int(state.logical_input[1]))
        self._screen_x_spin.setValue(state.screen_input[0])
        self._screen_y_spin.setValue(state.screen_input[1])
        self._logical_x_spin.blockSignals(False)
        self._logical_y_spin.blockSignals(False)
        self._screen_x_spin.blockSignals(False)
        self._screen_y_spin.blockSignals(False)

        self._clicked_result_label.setText(
            state.clicked_result or "点击截图后，会显示截图坐标、相对坐标、当前窗口像素坐标和逻辑坐标。"
        )

        self._fit_view_check.blockSignals(True)
        self._fit_view_check.setChecked(state.fit_view)
        self._fit_view_check.blockSignals(False)
        self._on_fit_view_toggled(state.fit_view)
        if screenshot_image is not None and not state.fit_view:
            self._canvas.set_zoom(state.zoom)
            self._zoom_percent_label.setText(f"{self._canvas.zoom() * 100:.0f}%")

        self._rebuild_pending_profile()
        image_text = "已恢复截图" if screenshot_image is not None else "未找到已保存截图"
        self._update_status(f"已从 {self._workspace_storage.file_path.name} 恢复当前窗口的工作状态，{image_text}。")

    def _rebuild_pending_profile(self):
        self._pending_profile = None
        self._last_fit_error = ""

        if not self._current_window:
            self._refresh_profile_info_label()
            self._refresh_profile_summary()
            return

        client_size = self._get_current_client_size()
        if client_size is None:
            self._refresh_profile_info_label()
            self._refresh_profile_summary("无法获取目标窗口客户区尺寸，暂时不能生成映射。")
            return

        if len(self._point_entries) >= 3:
            try:
                self._pending_profile = CoordinateMappingProfile.from_anchor_points(
                    name=self._current_window.title or "当前窗口映射",
                    window=self._current_window,
                    client_size=client_size,
                    anchors=[point.to_anchor() for point in self._point_entries],
                    profile_id=self._active_profile.profile_id if self._active_profile else None,
                    created_at=self._active_profile.created_at if self._active_profile else None,
                )
            except Exception as e:
                self._last_fit_error = str(e)

        self._refresh_profile_info_label()
        self._refresh_profile_summary()
        self._refresh_point_summary()
        self._convert_logical_to_screen(auto=True)
        self._convert_relative_to_logical(auto=True)

    def _save_mapping(self):
        if not self._current_window:
            QMessageBox.warning(self, "警告", "请先选择目标窗口")
            return

        profile = self._pending_profile
        try:
            saved_state = self._save_workspace_state(profile)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存当前状态失败: {e}")
            self._update_status(f"保存当前状态失败: {e}", error=True)
            return

        if profile is None:
            self._active_workspace_state = saved_state
            self._refresh_profile_info_label()
            self._refresh_profile_summary()
            self._update_status(
                f"当前状态已保存到 {self._workspace_storage.file_path.name}，但当前坐标点不足以生成映射。"
            )
            return

        try:
            saved_profile = self._storage.save_profile(profile)
            config_path = sync_profile_to_isometric_config(saved_profile)
        except Exception as e:
            self._active_workspace_state = saved_state
            QMessageBox.critical(self, "错误", f"状态已保存，但坐标映射保存失败: {e}")
            self._update_status(
                f"状态已保存到 {self._workspace_storage.file_path.name}，但映射保存失败: {e}",
                error=True,
            )
            return

        saved_state.active_profile_id = saved_profile.profile_id
        self._active_workspace_state = self._workspace_storage.save_state(saved_state)
        self._active_profile = saved_profile
        self._pending_profile = None
        self._refresh_profile_info_label()
        self._refresh_profile_summary()
        self._update_status(
            f"当前状态已保存到 {self._workspace_storage.file_path.name}，映射已保存到 {self._storage.file_path.name}，并同步更新 {config_path.name}。"
        )

    def _convert_logical_to_screen(self, auto: bool = False):
        profile = self._effective_profile()
        if profile is None:
            if not auto:
                QMessageBox.information(self, "提示", "请至少设置 3 个不共线的坐标点")
            self._logical_result_label.setText("结果: 当前还没有可用映射")
            return

        logical_x = self._logical_x_spin.value()
        logical_y = self._logical_y_spin.value()
        try:
            relative_x, relative_y = profile.logical_to_relative(logical_x, logical_y)
            result = [f"相对坐标 ({relative_x:.6f}, {relative_y:.6f})"]

            image_client_size = self._get_current_client_size()
            if image_client_size:
                client_x, client_y = profile.logical_to_client(logical_x, logical_y, image_client_size)
                result.append(f"截图坐标 ({client_x:.2f}, {client_y:.2f})")
                self._canvas.set_marker_point((client_x, client_y))

            client_rect = self._get_current_client_rect()
            if client_rect:
                screen_x, screen_y = profile.logical_to_screen(logical_x, logical_y, client_rect)
                result.append(f"当前窗口像素坐标 ({screen_x:.2f}, {screen_y:.2f})")

            self._logical_result_label.setText("\n".join(result))
            self._screen_x_spin.blockSignals(True)
            self._screen_y_spin.blockSignals(True)
            self._screen_x_spin.setValue(relative_x)
            self._screen_y_spin.setValue(relative_y)
            self._screen_x_spin.blockSignals(False)
            self._screen_y_spin.blockSignals(False)
        except Exception as e:
            self._logical_result_label.setText(f"结果: 转换失败 ({e})")
            if not auto:
                QMessageBox.warning(self, "警告", f"逻辑坐标转换失败: {e}")

    def _convert_relative_to_logical(self, auto: bool = False):
        profile = self._effective_profile()
        if profile is None:
            if not auto:
                QMessageBox.information(self, "提示", "请至少设置 3 个不共线的坐标点")
            self._screen_result_label.setText("结果: 当前还没有可用映射")
            return

        relative_x = self._screen_x_spin.value()
        relative_y = self._screen_y_spin.value()
        try:
            logical_x, logical_y = profile.relative_to_logical(relative_x, relative_y)
            result = [f"逻辑坐标 ({_logical_int(logical_x)}, {_logical_int(logical_y)})"]

            image_client_size = self._get_current_client_size()
            if image_client_size:
                client_x, client_y = profile.relative_to_client(relative_x, relative_y, image_client_size)
                result.append(f"截图坐标 ({client_x:.2f}, {client_y:.2f})")
                self._canvas.set_marker_point((client_x, client_y))

            client_rect = self._get_current_client_rect()
            if client_rect:
                live_size = (client_rect[2] - client_rect[0], client_rect[3] - client_rect[1])
                screen_x, screen_y = profile.relative_to_client(relative_x, relative_y, live_size)
                result.append(
                    f"当前窗口像素坐标 ({client_rect[0] + screen_x:.2f}, {client_rect[1] + screen_y:.2f})"
                )

            self._screen_result_label.setText("\n".join(result))
        except Exception as e:
            self._screen_result_label.setText(f"结果: 转换失败 ({e})")
            if not auto:
                QMessageBox.warning(self, "警告", f"相对坐标转换失败: {e}")

    def _refresh_point_summary(self):
        point_count = len(self._point_entries)
        if point_count == 0:
            self._point_summary_label.setText("尚未添加坐标点")
            return
        self._point_summary_label.setText(f"当前共有 {point_count} 个坐标点。至少需要 3 个不共线点才能生成映射。")

    def _refresh_selected_point_info(self):
        point = self._find_point(self._selected_point_id)
        if point is None:
            self._selected_point_label.setText("未选中")
            self._selected_point_relative_label.setText("-")
            return
        self._selected_point_label.setText(point.point_id)
        self._selected_point_relative_label.setText(self._format_relative_point(point.center_client))
        self._logical_x_spin.blockSignals(True)
        self._logical_y_spin.blockSignals(True)
        self._logical_x_spin.setValue(_logical_int(point.logical_coord[0]))
        self._logical_y_spin.setValue(_logical_int(point.logical_coord[1]))
        self._logical_x_spin.blockSignals(False)
        self._logical_y_spin.blockSignals(False)

    def _refresh_point_table(self):
        self._refresh_point_summary()
        self._point_table.setRowCount(len(self._point_entries))
        for row, point in enumerate(self._point_entries):
            relative_x, relative_y = self._point_relative_tuple(point.center_client)
            self._point_table.setItem(row, 0, QTableWidgetItem(point.point_id))
            self._point_table.setItem(row, 1, QTableWidgetItem(str(_logical_int(point.logical_coord[0]))))
            self._point_table.setItem(row, 2, QTableWidgetItem(str(_logical_int(point.logical_coord[1]))))
            self._point_table.setItem(row, 3, QTableWidgetItem(f"{relative_x:.6f}"))
            self._point_table.setItem(row, 4, QTableWidgetItem(f"{relative_y:.6f}"))
        self._select_table_row(self._point_table, 0, self._selected_point_id)

    def _refresh_guide_line_table(self):
        self._guide_line_table.setRowCount(len(self._guide_lines))
        for row, line in enumerate(self._guide_lines):
            config = GUIDE_LINE_STYLES.get(line.style, GUIDE_LINE_STYLES["default"])
            self._guide_line_table.setItem(row, 0, QTableWidgetItem(line.line_id))
            self._guide_line_table.setItem(row, 1, QTableWidgetItem(str(config["label"])))
            self._guide_line_table.setItem(row, 2, QTableWidgetItem(self._format_relative_point(line.start_client)))
            self._guide_line_table.setItem(row, 3, QTableWidgetItem(self._format_relative_point(line.end_client)))
        self._select_table_row(self._guide_line_table, 0, self._selected_line_id)

    def _refresh_profile_summary(self, message: Optional[str] = None):
        if message:
            self._profile_summary_label.setText(message)
            return

        profile = self._effective_profile()
        if profile is None:
            if self._point_entries:
                if self._last_fit_error:
                    self._profile_summary_label.setText(f"当前还没有可用映射。\n最近一次点拟合失败: {self._last_fit_error}")
                else:
                    self._profile_summary_label.setText("当前还没有可用映射。至少需要 3 个不共线的坐标点。")
            elif self._active_profile is not None:
                self._profile_summary_label.setText("已加载兼容旧映射，但当前没有点映射编辑数据。")
            else:
                self._profile_summary_label.setText("当前还没有可用映射。请先截图并添加坐标点。")
            return

        source_text = "点拟合" if getattr(profile, "source", "axes") == "anchors" else "兼容旧映射"
        summary = [
            f"来源: {source_text}",
            f"原点(相对坐标): ({profile.origin_relative[0]:.6f}, {profile.origin_relative[1]:.6f})",
            f"X方向相对向量: ({profile.axis_x_per_grid_relative[0]:.6f}, {profile.axis_x_per_grid_relative[1]:.6f})",
            f"Y方向相对向量: ({profile.axis_y_per_grid_relative[0]:.6f}, {profile.axis_y_per_grid_relative[1]:.6f})",
            f"标定客户区尺寸: {profile.client_size[0]}x{profile.client_size[1]}",
        ]
        if getattr(profile, "source", "axes") == "anchors":
            summary.append(f"坐标点数量: {profile.anchor_count}")
            summary.append(f"拟合平均误差: {profile.fit_error_px:.3f}px")
        if self._last_fit_error:
            summary.append(f"最近一次点拟合失败: {self._last_fit_error}")
        self._profile_summary_label.setText("\n".join(summary))

    def _refresh_profile_info_label(self):
        if self._pending_profile is not None:
            self._profile_info_label.setText("未保存临时映射\n来源: 点拟合")
            return
        if self._active_profile is not None:
            source_text = "点拟合" if getattr(self._active_profile, "source", "axes") == "anchors" else "兼容旧映射"
            self._profile_info_label.setText(
                f"{self._active_profile.name}\n来源: {source_text}\n更新时间: {self._format_timestamp(self._active_profile.updated_at)}"
            )
            return
        self._profile_info_label.setText("未加载映射")

    def _save_workspace_state(self, profile: Optional[CoordinateMappingProfile]) -> CoordinateWorkspaceState:
        baseline = self._active_workspace_state
        state = CoordinateWorkspaceState(
            state_id=baseline.state_id if baseline else "",
            window_title=self._current_window.title if self._current_window else "",
            window_class_name=self._current_window.class_name if self._current_window else "",
            screenshot_path=baseline.screenshot_path if baseline else "",
            axis_x=None,
            axis_y=None,
            axis_x_grid_count=1,
            axis_y_grid_count=1,
            manual_cells=[],
            anchor_cells=[point.to_anchor() for point in self._point_entries],
            guide_lines=[line.to_dict() for line in self._guide_lines],
            selected_cell_id=self._selected_point_id or "",
            selected_line_id=self._selected_line_id or "",
            marker_point=self._canvas.marker_point(),
            logical_input=(self._logical_x_spin.value(), self._logical_y_spin.value()),
            screen_input=(self._screen_x_spin.value(), self._screen_y_spin.value()),
            clicked_result=self._clicked_result_label.text(),
            fit_view=self._fit_view_check.isChecked(),
            zoom=self._canvas.zoom(),
            active_profile_id=profile.profile_id if profile else "",
            created_at=baseline.created_at if baseline else 0.0,
        )
        state.screenshot_path = self._save_workspace_screenshot(state.state_id, state.screenshot_path)
        self._active_workspace_state = self._workspace_storage.save_state(state)
        return self._active_workspace_state

    def _save_workspace_screenshot(self, state_id: str, existing_path: str = "") -> str:
        if self._current_image is None:
            return existing_path or ""

        assets_dir = resolve_default_workspace_assets_dir()
        assets_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = assets_dir / f"{state_id}.png"
        rgb_image = np.ascontiguousarray(self._current_image[:, :, ::-1])
        Image.fromarray(rgb_image).save(screenshot_path)
        return screenshot_path.relative_to(assets_dir.parent).as_posix()

    def _load_workspace_screenshot(self, relative_path: str):
        if not relative_path:
            return None
        path = resolve_default_workspace_assets_dir().parent / relative_path
        if not path.exists():
            return None
        try:
            with Image.open(path) as image:
                rgb = np.array(image.convert("RGB"))
            return np.ascontiguousarray(rgb[:, :, ::-1])
        except Exception:
            return None

    def _effective_profile(self) -> Optional[CoordinateMappingProfile]:
        if self._point_entries:
            if len(self._point_entries) < 3:
                return None
            return self._pending_profile or self._active_profile
        return self._pending_profile or self._active_profile

    def _point_relative_tuple(self, client_point: Tuple[float, float]) -> Tuple[float, float]:
        client_size = self._get_current_client_size()
        if not client_size:
            profile = self._active_profile or self._pending_profile
            client_size = profile.client_size if profile else (1, 1)
        width = max(1.0, float(client_size[0]))
        height = max(1.0, float(client_size[1]))
        return (float(client_point[0]) / width, float(client_point[1]) / height)

    def _format_relative_point(self, client_point: Tuple[float, float]) -> str:
        relative_x, relative_y = self._point_relative_tuple(client_point)
        return f"({relative_x:.6f}, {relative_y:.6f})"

    def _find_point(self, point_id: Optional[str]) -> Optional[PointMappingEntry]:
        if not point_id:
            return None
        for point in self._point_entries:
            if point.point_id == point_id:
                return point
        return None

    def _find_line(self, line_id: Optional[str]) -> Optional[GuideLineModel]:
        if not line_id:
            return None
        for line in self._guide_lines:
            if line.line_id == line_id:
                return line
        return None

    def _next_point_id(self) -> str:
        used = {point.point_id for point in self._point_entries}
        return self._next_point_id_from(used)

    @staticmethod
    def _next_point_id_from(used: set) -> str:
        index = 1
        while True:
            candidate = f"point_{index}"
            if candidate not in used:
                return candidate
            index += 1

    def _next_line_id(self) -> str:
        used = {line.line_id for line in self._guide_lines}
        index = 1
        while True:
            candidate = f"line_{index}"
            if candidate not in used:
                return candidate
            index += 1

    def _get_current_client_rect(self) -> Optional[Tuple[int, int, int, int]]:
        if not self._window_manager or not self._current_window:
            return None
        return self._window_manager.get_client_rect(self._current_window.hwnd)

    def _get_current_client_size(self) -> Optional[Tuple[int, int]]:
        if self._current_image is not None:
            return (int(self._current_image.shape[1]), int(self._current_image.shape[0]))
        rect = self._get_current_client_rect()
        if not rect:
            return None
        return (int(rect[2] - rect[0]), int(rect[3] - rect[1]))

    def _rescale_workspace_geometry(self, from_size: Tuple[int, int], to_size: Tuple[int, int]) -> None:
        if from_size[0] <= 0 or from_size[1] <= 0:
            return
        if tuple(from_size) == tuple(to_size):
            return

        scaled_points = []
        for point in self._point_entries:
            scaled_points.append(
                PointMappingEntry(
                    point_id=point.point_id,
                    center_client=self._scale_point(point.center_client, from_size, to_size),
                    logical_coord=point.logical_coord,
                    label=point.label,
                )
            )
        self._point_entries = scaled_points

        scaled_lines = []
        for line in self._guide_lines:
            scaled_lines.append(
                GuideLineModel(
                    line_id=line.line_id,
                    start_client=self._scale_point(line.start_client, from_size, to_size),
                    end_client=self._scale_point(line.end_client, from_size, to_size),
                    style=line.style,
                    label=line.label,
                )
            )
        self._guide_lines = scaled_lines

        marker = self._canvas.marker_point()
        if marker is not None:
            self._canvas.set_marker_point(self._scale_point(marker, from_size, to_size))

    @staticmethod
    def _scale_point(
        point: Tuple[float, float],
        from_size: Tuple[int, int],
        to_size: Tuple[int, int],
    ) -> Tuple[float, float]:
        from_width = max(1.0, float(from_size[0]))
        from_height = max(1.0, float(from_size[1]))
        to_width = float(to_size[0])
        to_height = float(to_size[1])
        return (
            float(point[0]) / from_width * to_width,
            float(point[1]) / from_height * to_height,
        )

    def _select_table_row(self, table: QTableWidget, column: int, value: Optional[str]) -> None:
        table.blockSignals(True)
        table.clearSelection()
        if value:
            for row in range(table.rowCount()):
                item = table.item(row, column)
                if item is not None and item.text() == value:
                    table.selectRow(row)
                    break
        table.blockSignals(False)

    def _clear_table_selection(self, table: QTableWidget) -> None:
        table.blockSignals(True)
        table.clearSelection()
        table.blockSignals(False)

    def _update_status(self, message: str, error: bool = False):
        color = "#cf1322" if error else "#595959"
        self._status_label.setStyleSheet(f"color: {color};")
        self._status_label.setText(message)

    def _on_fit_view_toggled(self, checked: bool):
        self._zoom_out_btn.setEnabled(not checked)
        self._zoom_in_btn.setEnabled(not checked)
        self._zoom_reset_btn.setEnabled(not checked)
        self._refresh_canvas_zoom()

    def _refresh_canvas_zoom(self):
        image_size = self._canvas.image_size()
        if image_size.isEmpty():
            self._zoom_percent_label.setText("100%")
            return
        if self._fit_view_check.isChecked():
            viewport_size = self._image_scroll.viewport().size()
            available_w = max(1, viewport_size.width() - 8)
            available_h = max(1, viewport_size.height() - 8)
            scale = min(available_w / image_size.width(), available_h / image_size.height())
            self._canvas.set_zoom(scale)
        self._zoom_percent_label.setText(f"{self._canvas.zoom() * 100:.0f}%")

    def _change_zoom(self, factor: float):
        if self._canvas.image_size().isEmpty():
            return
        if self._fit_view_check.isChecked():
            self._fit_view_check.setChecked(False)
        self._canvas.set_zoom(self._canvas.zoom() * factor)
        self._zoom_percent_label.setText(f"{self._canvas.zoom() * 100:.0f}%")

    def _reset_zoom(self):
        if self._canvas.image_size().isEmpty():
            return
        if self._fit_view_check.isChecked():
            self._fit_view_check.setChecked(False)
        self._canvas.set_zoom(1.0)
        self._zoom_percent_label.setText("100%")

    @staticmethod
    def _format_timestamp(timestamp: float) -> str:
        import time

        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        except Exception:
            return "-"