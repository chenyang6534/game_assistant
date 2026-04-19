"""
窗口客户区坐标与逻辑坐标点的双向转换
"""

from __future__ import annotations

import csv
import json
import math
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from core.window import WindowInfo


def _resolve_app_dir() -> Path:
    """解析应用根目录。源码模式返回项目目录，打包模式返回 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resolve_default_mapping_path() -> Path:
    """默认的坐标映射文件路径。"""
    return _resolve_app_dir() / "coordinate_mappings.json"


def resolve_default_config_path() -> Path:
    """默认的配置文件路径。"""
    return _resolve_app_dir() / "config.json"


def resolve_default_workspace_state_path() -> Path:
    """默认的坐标转换工作状态文件路径。"""
    return _resolve_app_dir() / "coordinate_workspace_state.json"


def resolve_default_workspace_assets_dir() -> Path:
    """默认的坐标转换工作资源目录。"""
    return _resolve_app_dir() / "coordinate_workspace_assets"


def _logical_int(value: float) -> int:
    return int(round(float(value)))


def oddq_to_axial(logical_x: float, logical_y: float) -> Tuple[float, float]:
    """将 odd-q 垂直布局偏移坐标转换为轴坐标。"""
    q = _logical_int(logical_x)
    row = _logical_int(logical_y)
    r = row - (q - (q & 1)) / 2.0
    return float(q), float(r)


def axial_to_oddq(axial_q: float, axial_r: float) -> Tuple[float, float]:
    """将轴坐标转换回 odd-q 垂直布局偏移坐标。"""
    q = _logical_int(axial_q)
    row = float(axial_r) + (q - (q & 1)) / 2.0
    return float(q), row


def load_coordinate_anchors_from_csv(
    csv_path: os.PathLike[str] | str,
    client_size: Tuple[int, int] = (1, 1),
) -> List[GridCoordinateAnchor]:
    """从坐标转换页导出的 CSV 中读取坐标点。"""
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV 文件不存在: {path}")

    width = max(1.0, float(client_size[0]))
    height = max(1.0, float(client_size[1]))
    anchors: List[GridCoordinateAnchor] = []
    used_ids: set[str] = set()
    auto_index = 1

    with open(path, "r", encoding="utf-8-sig", newline="") as file_obj:
        rows = list(csv.reader(file_obj))

    if not rows:
        return []

    start_index = 0
    header = [str(cell).strip() for cell in rows[0]]
    if header:
        first_cell = header[0].lower()
        if header[0].startswith("点ID") or first_cell in ("pointid", "point_id", "id"):
            start_index = 1

    for raw_row in rows[start_index:]:
        row = [str(cell).strip() for cell in raw_row]
        if not row or not any(row):
            continue
        if len(row) < 4:
            continue

        try:
            logical_x = float(row[1])
            logical_y = float(row[2])
            relative_x = float(row[3])
            relative_y = float(row[4]) if len(row) >= 5 and row[4] != "" else 0.0
        except (TypeError, ValueError):
            continue

        point_id = row[0]
        while not point_id or point_id in used_ids:
            point_id = f"p{auto_index}"
            auto_index += 1
        used_ids.add(point_id)

        anchors.append(
            GridCoordinateAnchor(
                cell_id=point_id,
                center_client=(relative_x * width, relative_y * height),
                logical_coord=(logical_x, logical_y),
                label=f"({_logical_int(logical_x)},{_logical_int(logical_y)})",
            )
        )

    return anchors


def build_relative_coordinate_profile_from_csv(
    csv_path: os.PathLike[str] | str,
) -> CoordinateMappingProfile:
    """基于导出的 CSV 拟合仅包含相对坐标信息的映射。"""
    path = Path(csv_path)
    raw_anchors = load_coordinate_anchors_from_csv(path, client_size=(1, 1))
    if len(raw_anchors) < 3:
        raise ValueError("CSV 中至少需要 3 个有效坐标点")

    fit_anchors = [
        GridCoordinateAnchor(
            cell_id=anchor.cell_id,
            center_client=anchor.center_client,
            logical_coord=oddq_to_axial(anchor.logical_coord[0], anchor.logical_coord[1]),
            polygon=list(anchor.polygon),
            label=anchor.label,
        )
        for anchor in raw_anchors
    ]

    window = WindowInfo(
        hwnd=0,
        title=path.stem,
        class_name="coordinate_csv",
        x=0,
        y=0,
        width=1,
        height=1,
        pid=0,
        is_visible=False,
    )
    profile = CoordinateMappingProfile.from_anchor_points(
        name=path.stem or "导入坐标点",
        window=window,
        client_size=(1, 1),
        anchors=fit_anchors,
    )
    profile.anchor_cells = list(raw_anchors)
    return profile


def reanchor_relative_coordinate_profile(
    profile: CoordinateMappingProfile,
    anchor_logical: Tuple[float, float],
    anchor_relative: Tuple[float, float],
    *,
    name: Optional[str] = None,
) -> CoordinateMappingProfile:
    """基于当前画面的锚点，重建平移后的相对坐标映射。"""
    ax_x, ax_y = profile.axis_x_per_grid_relative
    ay_x, ay_y = profile.axis_y_per_grid_relative
    anchor_axial = oddq_to_axial(anchor_logical[0], anchor_logical[1])
    logical_dx = float(anchor_axial[0]) - profile.origin_logical[0]
    logical_dy = float(anchor_axial[1]) - profile.origin_logical[1]
    origin_relative = (
        float(anchor_relative[0]) - logical_dx * ax_x - logical_dy * ay_x,
        float(anchor_relative[1]) - logical_dx * ax_y - logical_dy * ay_y,
    )

    axis_x = AxisCalibration(
        start=origin_relative,
        end=(origin_relative[0] + ax_x, origin_relative[1] + ax_y),
        grid_count=1,
    )
    axis_y = AxisCalibration(
        start=origin_relative,
        end=(origin_relative[0] + ay_x, origin_relative[1] + ay_y),
        grid_count=1,
    )

    return CoordinateMappingProfile(
        profile_id=profile.profile_id,
        name=name or profile.name,
        window_title=profile.window_title,
        window_class_name=profile.window_class_name,
        client_size=(1, 1),
        origin_client=origin_relative,
        axis_x=axis_x,
        axis_y=axis_y,
        origin_logical=profile.origin_logical,
        created_at=profile.created_at,
        updated_at=time.time(),
        source=profile.source,
        anchor_cells=list(profile.anchor_cells),
        fit_error_px=profile.fit_error_px,
    )


def _fallback_anchor_match_distance(
    profile: CoordinateMappingProfile,
    scale: float = 0.55,
) -> float:
    axis_lengths = []
    for vector in (profile.axis_x_per_grid_relative, profile.axis_y_per_grid_relative):
        length = math.hypot(vector[0], vector[1])
        if length > 1e-9:
            axis_lengths.append(length)
    if axis_lengths:
        return max(1e-6, min(axis_lengths) * max(0.0, float(scale)))
    return 0.05


def _build_anchor_match_items(
    profile: CoordinateMappingProfile,
    *,
    logical_origin: Optional[Tuple[float, float]] = None,
    max_distance_scale: float = 0.55,
) -> List[Dict[str, Any]]:
    anchors = list(profile.anchor_cells or [])
    if not anchors:
        return []

    fallback_distance = _fallback_anchor_match_distance(profile, scale=max_distance_scale)
    translated_origin = logical_origin or (0.0, 0.0)
    origin_axial = oddq_to_axial(translated_origin[0], translated_origin[1])
    logical_offset_x = float(origin_axial[0]) - float(profile.origin_logical[0])
    logical_offset_y = float(origin_axial[1]) - float(profile.origin_logical[1])
    anchor_items: List[Dict[str, Any]] = []
    for anchor in anchors:
        anchor_axial = oddq_to_axial(anchor.logical_coord[0], anchor.logical_coord[1])
        translated_axial = (
            float(anchor_axial[0]) + logical_offset_x,
            float(anchor_axial[1]) + logical_offset_y,
        )
        translated_logical = axial_to_oddq(translated_axial[0], translated_axial[1])
        anchor_relative = profile.logical_to_relative(
            translated_axial[0],
            translated_axial[1],
        )
        anchor_items.append({
            "cell_id": anchor.cell_id,
            "label": anchor.label,
            "logical_coord": translated_logical,
            "anchor_relative": (
                float(anchor_relative[0]),
                float(anchor_relative[1]),
            ),
        })

    scale = max(0.0, float(max_distance_scale))
    for index, item in enumerate(anchor_items):
        nearest_distance = None
        ax, ay = item["anchor_relative"]
        for other_index, other in enumerate(anchor_items):
            if other_index == index:
                continue
            bx, by = other["anchor_relative"]
            distance = math.hypot(ax - bx, ay - by)
            if nearest_distance is None or distance < nearest_distance:
                nearest_distance = distance
        if nearest_distance is None or nearest_distance <= 1e-9:
            item["max_distance"] = fallback_distance
        else:
            item["max_distance"] = nearest_distance * scale

    return anchor_items


def _build_anchor_match_result(
    item: Dict[str, Any],
    point_x: float,
    point_y: float,
    distance: float,
    *,
    matched: bool,
) -> Dict[str, Any]:
    return {
        "cell_id": item["cell_id"],
        "label": item["label"],
        "logical_coord": item["logical_coord"],
        "anchor_relative": item["anchor_relative"],
        "relative_point": (point_x, point_y),
        "distance": float(distance),
        "max_distance": float(item.get("max_distance", 0.0) or 0.0),
        "matched": bool(matched),
    }


def _hungarian_assign(cost_matrix: List[List[float]]) -> List[int]:
    """求解矩形代价矩阵的最小总代价分配，要求列数不少于行数。"""
    if not cost_matrix:
        return []

    row_count = len(cost_matrix)
    column_count = len(cost_matrix[0]) if cost_matrix[0] else 0
    if column_count < row_count:
        raise ValueError("Hungarian assignment requires columns >= rows")

    u = [0.0] * (row_count + 1)
    v = [0.0] * (column_count + 1)
    p = [0] * (column_count + 1)
    way = [0] * (column_count + 1)

    for row in range(1, row_count + 1):
        p[0] = row
        column0 = 0
        min_values = [float("inf")] * (column_count + 1)
        used = [False] * (column_count + 1)

        while True:
            used[column0] = True
            row0 = p[column0]
            delta = float("inf")
            column1 = 0
            for column in range(1, column_count + 1):
                if used[column]:
                    continue
                current = cost_matrix[row0 - 1][column - 1] - u[row0] - v[column]
                if current < min_values[column]:
                    min_values[column] = current
                    way[column] = column0
                if min_values[column] < delta:
                    delta = min_values[column]
                    column1 = column
            for column in range(column_count + 1):
                if used[column]:
                    u[p[column]] += delta
                    v[column] -= delta
                else:
                    min_values[column] -= delta
            column0 = column1
            if p[column0] == 0:
                break

        while True:
            column1 = way[column0]
            p[column0] = p[column1]
            column0 = column1
            if column0 == 0:
                break

    assignment = [-1] * row_count
    for column in range(1, column_count + 1):
        if p[column] != 0:
            assignment[p[column] - 1] = column - 1
    return assignment


def match_relative_point_to_anchor_logical(
    profile: CoordinateMappingProfile,
    relative_point: Tuple[float, float],
    *,
    logical_origin: Optional[Tuple[float, float]] = None,
    max_distance_scale: float = 0.55,
) -> Optional[Dict[str, Any]]:
    """按相对坐标匹配最近的 CSV 锚点逻辑坐标。"""
    anchor_items = _build_anchor_match_items(
        profile,
        logical_origin=logical_origin,
        max_distance_scale=max_distance_scale,
    )
    if not anchor_items:
        return None

    point_x = float(relative_point[0])
    point_y = float(relative_point[1])
    best_item = None
    best_distance = None
    for item in anchor_items:
        anchor_x, anchor_y = item["anchor_relative"]
        distance = math.hypot(point_x - anchor_x, point_y - anchor_y)
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_item = item

    if best_item is None or best_distance is None:
        return None

    max_distance = float(best_item.get("max_distance", 0.0) or 0.0)
    return _build_anchor_match_result(
        best_item,
        point_x,
        point_y,
        float(best_distance),
        matched=bool(best_distance <= max_distance),
    )


def match_relative_points_to_anchor_logical(
    profile: CoordinateMappingProfile,
    relative_points: List[Tuple[float, float]],
    *,
    logical_origin: Optional[Tuple[float, float]] = None,
    max_distance_scale: float = 0.55,
) -> List[Optional[Dict[str, Any]]]:
    """将一批相对坐标唯一分配到最近的 CSV 锚点逻辑坐标。"""
    anchor_items = _build_anchor_match_items(
        profile,
        logical_origin=logical_origin,
        max_distance_scale=max_distance_scale,
    )
    if not anchor_items:
        return [None for _ in relative_points]

    point_records = []
    max_valid_distance = 0.0
    for point in relative_points:
        point_x = float(point[0])
        point_y = float(point[1])
        best_item = None
        best_distance = None
        candidates = []
        candidate_distances: Dict[int, float] = {}
        for anchor_index, item in enumerate(anchor_items):
            anchor_x, anchor_y = item["anchor_relative"]
            distance = math.hypot(point_x - anchor_x, point_y - anchor_y)
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_item = item
            if distance <= float(item.get("max_distance", 0.0) or 0.0):
                candidates.append((distance, anchor_index))
                candidate_distances[anchor_index] = float(distance)
                if distance > max_valid_distance:
                    max_valid_distance = float(distance)
        candidates.sort(key=lambda item: item[0])
        point_records.append({
            "point": (point_x, point_y),
            "best_item": best_item,
            "best_distance": float(best_distance) if best_distance is not None else None,
            "candidates": candidates,
            "candidate_distances": candidate_distances,
        })

    row_count = len(point_records)
    column_count = len(anchor_items) + row_count
    invalid_cost = 10 ** 6
    dummy_cost = max(1.0, max_valid_distance + 0.25)

    cost_matrix: List[List[float]] = []
    for record in point_records:
        row_costs = [invalid_cost] * column_count
        for _distance, anchor_index in record["candidates"]:
            row_costs[anchor_index] = float(_distance)
        for dummy_index in range(row_count):
            row_costs[len(anchor_items) + dummy_index] = dummy_cost
        cost_matrix.append(row_costs)

    assignment_columns = _hungarian_assign(cost_matrix)

    results: List[Optional[Dict[str, Any]]] = []
    for point_index, record in enumerate(point_records):
        point_x, point_y = record["point"]
        assigned_column = assignment_columns[point_index] if point_index < len(assignment_columns) else -1
        if 0 <= assigned_column < len(anchor_items):
            anchor_index = assigned_column
            anchor_item = anchor_items[anchor_index]
            distance = record["candidate_distances"].get(anchor_index, record["best_distance"] or 0.0)
            results.append(
                _build_anchor_match_result(
                    anchor_item,
                    point_x,
                    point_y,
                    float(distance),
                    matched=True,
                )
            )
            continue

        best_item = record["best_item"]
        best_distance = record["best_distance"]
        if best_item is None or best_distance is None:
            results.append(None)
            continue

        results.append(
            _build_anchor_match_result(
                best_item,
                point_x,
                point_y,
                float(best_distance),
                matched=False,
            )
        )

    return results


@dataclass
class AxisCalibration:
    """单条逻辑轴线的标定数据。"""

    start: Tuple[float, float]
    end: Tuple[float, float]
    grid_count: float

    def __post_init__(self):
        self.start = (float(self.start[0]), float(self.start[1]))
        self.end = (float(self.end[0]), float(self.end[1]))
        self.grid_count = float(self.grid_count)
        if self.grid_count <= 0:
            raise ValueError("格子数量必须大于 0")

    @property
    def vector(self) -> Tuple[float, float]:
        return (self.end[0] - self.start[0], self.end[1] - self.start[1])

    @property
    def pixel_length(self) -> float:
        dx, dy = self.vector
        return math.hypot(dx, dy)

    @property
    def per_grid_vector(self) -> Tuple[float, float]:
        dx, dy = self.vector
        if self.grid_count <= 0:
            raise ValueError("格子数量必须大于 0")
        return (dx / self.grid_count, dy / self.grid_count)

    @property
    def unit_vector(self) -> Tuple[float, float]:
        dx, dy = self.per_grid_vector
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            raise ValueError("轴线长度过短，无法计算单位向量")
        return (dx / length, dy / length)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start": [self.start[0], self.start[1]],
            "end": [self.end[0], self.end[1]],
            "grid_count": self.grid_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AxisCalibration":
        return cls(
            start=tuple(data.get("start", (0, 0))),
            end=tuple(data.get("end", (0, 0))),
            grid_count=data.get("grid_count", 1),
        )


@dataclass
class GridCoordinateAnchor:
    """单个坐标点的逻辑坐标锚点。"""

    cell_id: str
    center_client: Tuple[float, float]
    logical_coord: Tuple[float, float]
    polygon: List[Tuple[float, float]] = field(default_factory=list)
    label: str = ""

    def __post_init__(self):
        self.cell_id = str(self.cell_id or "")
        self.center_client = (float(self.center_client[0]), float(self.center_client[1]))
        self.logical_coord = (float(self.logical_coord[0]), float(self.logical_coord[1]))
        normalized_polygon = []
        for point in self.polygon or []:
            try:
                normalized_polygon.append((float(point[0]), float(point[1])))
            except Exception:
                continue
        self.polygon = normalized_polygon
        if not self.label:
            self.label = f"({self.logical_coord[0]:.0f}, {self.logical_coord[1]:.0f})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "center_client": [self.center_client[0], self.center_client[1]],
            "logical_coord": [self.logical_coord[0], self.logical_coord[1]],
            "polygon": [[point[0], point[1]] for point in self.polygon],
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GridCoordinateAnchor":
        return cls(
            cell_id=data.get("cell_id", ""),
            center_client=tuple(data.get("center_client", (0, 0))),
            logical_coord=tuple(data.get("logical_coord", (0, 0))),
            polygon=[tuple(point) for point in data.get("polygon", [])],
            label=data.get("label", ""),
        )


@dataclass
class CoordinateMappingProfile:
    """一组窗口逻辑坐标映射配置。"""

    profile_id: str
    name: str
    window_title: str
    window_class_name: str
    client_size: Tuple[int, int]
    origin_client: Tuple[float, float]
    axis_x: AxisCalibration
    axis_y: AxisCalibration
    origin_logical: Tuple[float, float] = (0.0, 0.0)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    source: str = "axes"
    anchor_cells: List[GridCoordinateAnchor] = field(default_factory=list)
    fit_error_px: float = 0.0

    def __post_init__(self):
        self.profile_id = str(self.profile_id or uuid.uuid4().hex)
        self.name = str(self.name or "未命名映射")
        self.window_title = str(self.window_title or "")
        self.window_class_name = str(self.window_class_name or "")
        self.client_size = (int(self.client_size[0]), int(self.client_size[1]))
        self.origin_client = (float(self.origin_client[0]), float(self.origin_client[1]))
        self.origin_logical = (float(self.origin_logical[0]), float(self.origin_logical[1]))
        self.created_at = float(self.created_at or time.time())
        self.updated_at = float(self.updated_at or time.time())
        self.source = str(self.source or "axes")
        self.fit_error_px = float(self.fit_error_px or 0.0)
        normalized_anchors: List[GridCoordinateAnchor] = []
        for anchor in self.anchor_cells or []:
            if isinstance(anchor, GridCoordinateAnchor):
                normalized_anchors.append(anchor)
            elif isinstance(anchor, dict):
                try:
                    normalized_anchors.append(GridCoordinateAnchor.from_dict(anchor))
                except Exception:
                    continue
        self.anchor_cells = normalized_anchors

    @property
    def axis_x_per_grid(self) -> Tuple[float, float]:
        return self.axis_x.per_grid_vector

    @property
    def axis_y_per_grid(self) -> Tuple[float, float]:
        return self.axis_y.per_grid_vector

    @property
    def axis_x_unit(self) -> Tuple[float, float]:
        return self.axis_x.unit_vector

    @property
    def axis_y_unit(self) -> Tuple[float, float]:
        return self.axis_y.unit_vector

    @property
    def origin_relative(self) -> Tuple[float, float]:
        return self.client_to_relative(self.origin_client[0], self.origin_client[1], self.client_size)

    @property
    def axis_x_per_grid_relative(self) -> Tuple[float, float]:
        width, height = self._normalize_client_size(self.client_size)
        vector = self.axis_x_per_grid
        return (vector[0] / width, vector[1] / height)

    @property
    def axis_y_per_grid_relative(self) -> Tuple[float, float]:
        width, height = self._normalize_client_size(self.client_size)
        vector = self.axis_y_per_grid
        return (vector[0] / width, vector[1] / height)

    @property
    def origin_alignment_error(self) -> float:
        dx = self.axis_x.start[0] - self.axis_y.start[0]
        dy = self.axis_x.start[1] - self.axis_y.start[1]
        return math.hypot(dx, dy)

    @property
    def anchor_count(self) -> int:
        return len(self.anchor_cells)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "name": self.name,
            "window_title": self.window_title,
            "window_class_name": self.window_class_name,
            "client_size": [self.client_size[0], self.client_size[1]],
            "origin_client": [self.origin_client[0], self.origin_client[1]],
            "origin_logical": [self.origin_logical[0], self.origin_logical[1]],
            "axis_x": self.axis_x.to_dict(),
            "axis_y": self.axis_y.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source": self.source,
            "fit_error_px": self.fit_error_px,
            "anchor_cells": [anchor.to_dict() for anchor in self.anchor_cells],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CoordinateMappingProfile":
        return cls(
            profile_id=data.get("profile_id") or uuid.uuid4().hex,
            name=data.get("name", "未命名映射"),
            window_title=data.get("window_title", ""),
            window_class_name=data.get("window_class_name", ""),
            client_size=tuple(data.get("client_size", (0, 0))),
            origin_client=tuple(data.get("origin_client", (0, 0))),
            origin_logical=tuple(data.get("origin_logical", (0, 0))),
            axis_x=AxisCalibration.from_dict(data.get("axis_x", {})),
            axis_y=AxisCalibration.from_dict(data.get("axis_y", {})),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            source=data.get("source", "axes"),
            fit_error_px=data.get("fit_error_px", 0.0),
            anchor_cells=[GridCoordinateAnchor.from_dict(item) for item in data.get("anchor_cells", [])],
        )

    @classmethod
    def from_axes(
        cls,
        *,
        name: str,
        window: WindowInfo,
        client_size: Tuple[int, int],
        axis_x: AxisCalibration,
        axis_y: AxisCalibration,
        profile_id: Optional[str] = None,
        created_at: Optional[float] = None,
        origin_logical: Tuple[float, float] = (0.0, 0.0),
    ) -> "CoordinateMappingProfile":
        if axis_x.pixel_length <= 1e-6 or axis_y.pixel_length <= 1e-6:
            raise ValueError("轴线长度过短，请重新标定")

        origin_client = (
            (axis_x.start[0] + axis_y.start[0]) / 2.0,
            (axis_x.start[1] + axis_y.start[1]) / 2.0,
        )

        profile = cls(
            profile_id=profile_id or uuid.uuid4().hex,
            name=name,
            window_title=window.title,
            window_class_name=window.class_name,
            client_size=client_size,
            origin_client=origin_client,
            axis_x=axis_x,
            axis_y=axis_y,
            origin_logical=origin_logical,
            created_at=created_at or time.time(),
            updated_at=time.time(),
            source="axes",
        )

        det = profile._basis_determinant()
        if abs(det) <= 1e-9:
            raise ValueError("X 轴和 Y 轴几乎平行，无法建立坐标映射")

        return profile

    @classmethod
    def from_anchor_points(
        cls,
        *,
        name: str,
        window: WindowInfo,
        client_size: Tuple[int, int],
        anchors: List[GridCoordinateAnchor],
        profile_id: Optional[str] = None,
        created_at: Optional[float] = None,
    ) -> "CoordinateMappingProfile":
        valid_anchors = [anchor for anchor in anchors if isinstance(anchor, GridCoordinateAnchor)]
        if len(valid_anchors) < 3:
            raise ValueError("至少需要 3 个坐标点")

        matrix = np.array(
            [
                [1.0, anchor.logical_coord[0], anchor.logical_coord[1]]
                for anchor in valid_anchors
            ],
            dtype=float,
        )
        if np.linalg.matrix_rank(matrix) < 3:
            raise ValueError("至少需要 3 个不共线的逻辑坐标点")

        target_x = np.array([anchor.center_client[0] for anchor in valid_anchors], dtype=float)
        target_y = np.array([anchor.center_client[1] for anchor in valid_anchors], dtype=float)

        params_x, _, _, _ = np.linalg.lstsq(matrix, target_x, rcond=None)
        params_y, _, _, _ = np.linalg.lstsq(matrix, target_y, rcond=None)

        origin_client = (float(params_x[0]), float(params_y[0]))
        axis_x = AxisCalibration(
            start=origin_client,
            end=(origin_client[0] + float(params_x[1]), origin_client[1] + float(params_y[1])),
            grid_count=1,
        )
        axis_y = AxisCalibration(
            start=origin_client,
            end=(origin_client[0] + float(params_x[2]), origin_client[1] + float(params_y[2])),
            grid_count=1,
        )

        predicted_x = matrix @ params_x
        predicted_y = matrix @ params_y
        errors = np.sqrt((predicted_x - target_x) ** 2 + (predicted_y - target_y) ** 2)

        profile = cls(
            profile_id=profile_id or uuid.uuid4().hex,
            name=name,
            window_title=window.title,
            window_class_name=window.class_name,
            client_size=client_size,
            origin_client=origin_client,
            axis_x=axis_x,
            axis_y=axis_y,
            origin_logical=(0.0, 0.0),
            created_at=created_at or time.time(),
            updated_at=time.time(),
            source="anchors",
            anchor_cells=list(valid_anchors),
            fit_error_px=float(np.mean(errors)) if len(errors) else 0.0,
        )

        det = profile._basis_determinant()
        if abs(det) <= 1e-9:
            raise ValueError("坐标点拟合后的 X/Y 轴几乎平行，无法建立映射")

        return profile

    def matches_window(self, window: WindowInfo) -> bool:
        return (
            self.window_title == window.title
            and self.window_class_name == window.class_name
        )

    def client_to_relative(
        self,
        client_x: float,
        client_y: float,
        client_size: Optional[Tuple[int, int]] = None,
    ) -> Tuple[float, float]:
        width, height = self._normalize_client_size(client_size or self.client_size)
        return (float(client_x) / width, float(client_y) / height)

    def relative_to_client(
        self,
        relative_x: float,
        relative_y: float,
        client_size: Optional[Tuple[int, int]] = None,
    ) -> Tuple[float, float]:
        width, height = self._normalize_client_size(client_size or self.client_size)
        return (float(relative_x) * width, float(relative_y) * height)

    def logical_to_relative(self, logical_x: float, logical_y: float) -> Tuple[float, float]:
        ax_x, ax_y = self.axis_x_per_grid_relative
        ay_x, ay_y = self.axis_y_per_grid_relative
        dx = float(logical_x) - self.origin_logical[0]
        dy = float(logical_y) - self.origin_logical[1]
        return (
            self.origin_relative[0] + dx * ax_x + dy * ay_x,
            self.origin_relative[1] + dx * ax_y + dy * ay_y,
        )

    def logical_to_client(
        self,
        logical_x: float,
        logical_y: float,
        client_size: Optional[Tuple[int, int]] = None,
    ) -> Tuple[float, float]:
        relative_x, relative_y = self.logical_to_relative(logical_x, logical_y)
        return self.relative_to_client(relative_x, relative_y, client_size)

    def relative_to_logical(self, relative_x: float, relative_y: float) -> Tuple[float, float]:
        ax_x, ax_y = self.axis_x_per_grid_relative
        ay_x, ay_y = self.axis_y_per_grid_relative
        det = self._basis_determinant()
        if abs(det) <= 1e-9:
            raise ValueError("当前映射不可逆，无法转换坐标")

        dx = float(relative_x) - self.origin_relative[0]
        dy = float(relative_y) - self.origin_relative[1]
        logical_dx = (dx * ay_y - dy * ay_x) / det
        logical_dy = (ax_x * dy - ax_y * dx) / det
        return (
            self.origin_logical[0] + logical_dx,
            self.origin_logical[1] + logical_dy,
        )

    def client_to_logical(
        self,
        client_x: float,
        client_y: float,
        client_size: Optional[Tuple[int, int]] = None,
    ) -> Tuple[float, float]:
        relative_x, relative_y = self.client_to_relative(client_x, client_y, client_size)
        return self.relative_to_logical(relative_x, relative_y)

    def logical_to_screen(
        self,
        logical_x: float,
        logical_y: float,
        client_rect: Tuple[int, int, int, int],
    ) -> Tuple[float, float]:
        current_client_size = (client_rect[2] - client_rect[0], client_rect[3] - client_rect[1])
        client_x, client_y = self.logical_to_client(logical_x, logical_y, current_client_size)
        return (
            client_rect[0] + client_x,
            client_rect[1] + client_y,
        )

    def screen_to_logical(
        self,
        screen_x: float,
        screen_y: float,
        client_rect: Tuple[int, int, int, int],
    ) -> Tuple[float, float]:
        current_client_size = (client_rect[2] - client_rect[0], client_rect[3] - client_rect[1])
        return self.client_to_logical(
            float(screen_x) - client_rect[0],
            float(screen_y) - client_rect[1],
            current_client_size,
        )

    def _basis_determinant(self) -> float:
        ax_x, ax_y = self.axis_x_per_grid_relative
        ay_x, ay_y = self.axis_y_per_grid_relative
        return ax_x * ay_y - ax_y * ay_x

    @staticmethod
    def _normalize_client_size(client_size: Tuple[int, int]) -> Tuple[float, float]:
        width = max(1.0, float(client_size[0]))
        height = max(1.0, float(client_size[1]))
        return (width, height)


@dataclass
class CoordinateWorkspaceState:
    """坐标转换页的完整工作状态。"""

    state_id: str = ""
    window_title: str = ""
    window_class_name: str = ""
    screenshot_path: str = ""
    axis_x: Optional[AxisCalibration] = None
    axis_y: Optional[AxisCalibration] = None
    axis_x_grid_count: int = 1
    axis_y_grid_count: int = 1
    manual_cells: List[Dict[str, Any]] = field(default_factory=list)
    anchor_cells: List[GridCoordinateAnchor] = field(default_factory=list)
    guide_lines: List[Dict[str, Any]] = field(default_factory=list)
    selected_cell_id: str = ""
    selected_line_id: str = ""
    marker_point: Optional[Tuple[float, float]] = None
    logical_input: Tuple[float, float] = (0.0, 0.0)
    screen_input: Tuple[float, float] = (0.0, 0.0)
    clicked_result: str = ""
    fit_view: bool = True
    zoom: float = 1.0
    active_profile_id: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self):
        self.state_id = str(self.state_id or uuid.uuid4().hex)
        self.window_title = str(self.window_title or "")
        self.window_class_name = str(self.window_class_name or "")
        self.screenshot_path = str(self.screenshot_path or "")
        self.axis_x_grid_count = max(1, int(self.axis_x_grid_count or 1))
        self.axis_y_grid_count = max(1, int(self.axis_y_grid_count or 1))
        self.selected_cell_id = str(self.selected_cell_id or "")
        self.selected_line_id = str(self.selected_line_id or "")
        self.clicked_result = str(self.clicked_result or "")
        self.fit_view = bool(self.fit_view)
        self.zoom = float(self.zoom or 1.0)
        self.active_profile_id = str(self.active_profile_id or "")
        self.created_at = float(self.created_at or time.time())
        self.updated_at = float(self.updated_at or time.time())

        if isinstance(self.axis_x, dict):
            self.axis_x = AxisCalibration.from_dict(self.axis_x)
        if isinstance(self.axis_y, dict):
            self.axis_y = AxisCalibration.from_dict(self.axis_y)

        if self.marker_point is not None:
            self.marker_point = (float(self.marker_point[0]), float(self.marker_point[1]))
        self.logical_input = (float(self.logical_input[0]), float(self.logical_input[1]))
        self.screen_input = (float(self.screen_input[0]), float(self.screen_input[1]))

        normalized_manual_cells: List[Dict[str, Any]] = []
        for cell in self.manual_cells or []:
            if not isinstance(cell, dict):
                continue
            polygon = []
            for point in cell.get("polygon", []):
                try:
                    polygon.append((float(point[0]), float(point[1])))
                except Exception:
                    continue
            center = cell.get("center", (0.0, 0.0))
            try:
                center_value = (float(center[0]), float(center[1]))
            except Exception:
                center_value = (0.0, 0.0)
            normalized_manual_cells.append(
                {
                    "cell_id": str(cell.get("cell_id", "")),
                    "center": [center_value[0], center_value[1]],
                    "polygon": [[point[0], point[1]] for point in polygon],
                    "source": str(cell.get("source", "manual") or "manual"),
                    "score": float(cell.get("score", 0.0) or 0.0),
                    "metadata": dict(cell.get("metadata", {}) or {}),
                }
            )
        self.manual_cells = normalized_manual_cells

        normalized_guide_lines: List[Dict[str, Any]] = []
        for line in self.guide_lines or []:
            if not isinstance(line, dict):
                continue
            start = line.get("start_client", (0.0, 0.0))
            end = line.get("end_client", (0.0, 0.0))
            try:
                start_value = (float(start[0]), float(start[1]))
                end_value = (float(end[0]), float(end[1]))
            except Exception:
                continue
            normalized_guide_lines.append(
                {
                    "line_id": str(line.get("line_id", "")),
                    "start_client": [start_value[0], start_value[1]],
                    "end_client": [end_value[0], end_value[1]],
                    "style": str(line.get("style", "default") or "default"),
                    "label": str(line.get("label", "") or ""),
                }
            )
        self.guide_lines = normalized_guide_lines

        normalized_anchors: List[GridCoordinateAnchor] = []
        for anchor in self.anchor_cells or []:
            if isinstance(anchor, GridCoordinateAnchor):
                normalized_anchors.append(anchor)
            elif isinstance(anchor, dict):
                try:
                    normalized_anchors.append(GridCoordinateAnchor.from_dict(anchor))
                except Exception:
                    continue
        self.anchor_cells = normalized_anchors

    def matches_window(self, window: WindowInfo) -> bool:
        return (
            self.window_title == window.title
            and self.window_class_name == window.class_name
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state_id": self.state_id,
            "window_title": self.window_title,
            "window_class_name": self.window_class_name,
            "screenshot_path": self.screenshot_path,
            "axis_x": self.axis_x.to_dict() if self.axis_x else None,
            "axis_y": self.axis_y.to_dict() if self.axis_y else None,
            "axis_x_grid_count": self.axis_x_grid_count,
            "axis_y_grid_count": self.axis_y_grid_count,
            "manual_cells": list(self.manual_cells),
            "anchor_cells": [anchor.to_dict() for anchor in self.anchor_cells],
            "guide_lines": list(self.guide_lines),
            "selected_cell_id": self.selected_cell_id,
            "selected_line_id": self.selected_line_id,
            "marker_point": list(self.marker_point) if self.marker_point else None,
            "logical_input": [self.logical_input[0], self.logical_input[1]],
            "screen_input": [self.screen_input[0], self.screen_input[1]],
            "clicked_result": self.clicked_result,
            "fit_view": self.fit_view,
            "zoom": self.zoom,
            "active_profile_id": self.active_profile_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CoordinateWorkspaceState":
        return cls(
            state_id=data.get("state_id", ""),
            window_title=data.get("window_title", ""),
            window_class_name=data.get("window_class_name", ""),
            screenshot_path=data.get("screenshot_path", ""),
            axis_x=data.get("axis_x"),
            axis_y=data.get("axis_y"),
            axis_x_grid_count=data.get("axis_x_grid_count", 1),
            axis_y_grid_count=data.get("axis_y_grid_count", 1),
            manual_cells=list(data.get("manual_cells", [])),
            anchor_cells=[GridCoordinateAnchor.from_dict(item) for item in data.get("anchor_cells", [])],
            guide_lines=list(data.get("guide_lines", [])),
            selected_cell_id=data.get("selected_cell_id", ""),
            selected_line_id=data.get("selected_line_id", ""),
            marker_point=tuple(data.get("marker_point")) if data.get("marker_point") else None,
            logical_input=tuple(data.get("logical_input", (0.0, 0.0))),
            screen_input=tuple(data.get("screen_input", (0.0, 0.0))),
            clicked_result=data.get("clicked_result", ""),
            fit_view=data.get("fit_view", True),
            zoom=data.get("zoom", 1.0),
            active_profile_id=data.get("active_profile_id", ""),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


class CoordinateMappingStorage:
    """坐标映射文件读写。"""

    def __init__(self, file_path: Optional[os.PathLike[str] | str] = None):
        self._file_path = Path(file_path) if file_path else resolve_default_mapping_path()

    @property
    def file_path(self) -> Path:
        return self._file_path

    def load_profiles(self) -> List[CoordinateMappingProfile]:
        data = self._load_data()
        profiles = []
        for raw_profile in data.get("profiles", []):
            try:
                profiles.append(CoordinateMappingProfile.from_dict(raw_profile))
            except Exception:
                continue
        profiles.sort(key=lambda item: item.updated_at, reverse=True)
        return profiles

    def find_profile_for_window(self, window: WindowInfo) -> Optional[CoordinateMappingProfile]:
        for profile in self.load_profiles():
            if profile.matches_window(window):
                return profile
        return None

    def save_profile(self, profile: CoordinateMappingProfile) -> CoordinateMappingProfile:
        data = self._load_data()
        raw_profiles = data.get("profiles", [])
        updated = False

        for index, raw_profile in enumerate(raw_profiles):
            existing_id = raw_profile.get("profile_id")
            same_window = (
                raw_profile.get("window_title") == profile.window_title
                and raw_profile.get("window_class_name") == profile.window_class_name
            )
            if existing_id == profile.profile_id or same_window:
                if not profile.profile_id:
                    profile.profile_id = existing_id or uuid.uuid4().hex
                if not profile.created_at:
                    profile.created_at = float(raw_profile.get("created_at") or time.time())
                profile.updated_at = time.time()
                raw_profiles[index] = profile.to_dict()
                updated = True
                break

        if not updated:
            profile.updated_at = time.time()
            raw_profiles.append(profile.to_dict())

        data["version"] = 1
        data["profiles"] = raw_profiles
        self._write_data(data)
        return profile

    def _load_data(self) -> Dict[str, Any]:
        if not self._file_path.exists():
            return {"version": 1, "profiles": []}

        try:
            with open(self._file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

        return {"version": 1, "profiles": []}

    def _write_data(self, data: Dict[str, Any]):
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)


class CoordinateWorkspaceStateStorage:
    """坐标转换工作状态读写。"""

    def __init__(self, file_path: Optional[os.PathLike[str] | str] = None):
        self._file_path = Path(file_path) if file_path else resolve_default_workspace_state_path()

    @property
    def file_path(self) -> Path:
        return self._file_path

    def load_states(self) -> List[CoordinateWorkspaceState]:
        data = self._load_data()
        states = []
        for raw_state in data.get("states", []):
            try:
                states.append(CoordinateWorkspaceState.from_dict(raw_state))
            except Exception:
                continue
        states.sort(key=lambda item: item.updated_at, reverse=True)
        return states

    def find_state_for_window(self, window: WindowInfo) -> Optional[CoordinateWorkspaceState]:
        for state in self.load_states():
            if state.matches_window(window):
                return state
        return None

    def save_state(self, state: CoordinateWorkspaceState) -> CoordinateWorkspaceState:
        data = self._load_data()
        raw_states = data.get("states", [])
        updated = False

        for index, raw_state in enumerate(raw_states):
            existing_id = raw_state.get("state_id")
            same_window = (
                raw_state.get("window_title") == state.window_title
                and raw_state.get("window_class_name") == state.window_class_name
            )
            if existing_id == state.state_id or same_window:
                if not state.state_id:
                    state.state_id = existing_id or uuid.uuid4().hex
                if not state.created_at:
                    state.created_at = float(raw_state.get("created_at") or time.time())
                state.updated_at = time.time()
                raw_states[index] = state.to_dict()
                updated = True
                break

        if not updated:
            state.updated_at = time.time()
            raw_states.append(state.to_dict())

        data["version"] = 1
        data["states"] = raw_states
        self._write_data(data)
        return state

    def _load_data(self) -> Dict[str, Any]:
        if not self._file_path.exists():
            return {"version": 1, "states": []}

        try:
            with open(self._file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

        return {"version": 1, "states": []}

    def _write_data(self, data: Dict[str, Any]):
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)


def sync_profile_to_isometric_config(
    profile: CoordinateMappingProfile,
    config_path: Optional[os.PathLike[str] | str] = None,
) -> Path:
    """将标定结果同步到 config.json 的 isometric 方向配置。"""
    path = Path(config_path) if config_path else resolve_default_config_path()
    config: Dict[str, Any] = {}

    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                config = loaded
        except Exception:
            config = {}

    config["isometric"] = {
        "axis_x": [round(value, 6) for value in profile.axis_x_unit],
        "axis_y": [round(value, 6) for value in profile.axis_y_unit],
    }
    config["coordinate_mapping"] = {
        "file": str(resolve_default_mapping_path().name),
        "active_profile_id": profile.profile_id,
        "active_window_title": profile.window_title,
        "active_window_class": profile.window_class_name,
        "updated_at": profile.updated_at,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)
    return path