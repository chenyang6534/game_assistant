"""
格子轮廓识别与默认六边形轮廓生成
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover - 依赖缺失时由 UI 提示
    cv2 = None


@dataclass
class GridCellModel:
    """单个识别到的格子。"""

    cell_id: str
    center: Tuple[float, float]
    polygon: List[Tuple[float, float]]
    source: str = "detected"
    score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.cell_id = str(self.cell_id or "")
        self.center = (float(self.center[0]), float(self.center[1]))
        self.polygon = [(float(point[0]), float(point[1])) for point in self.polygon]
        self.source = str(self.source or "detected")
        self.score = float(self.score or 0.0)

    def copy(self) -> "GridCellModel":
        return GridCellModel(
            cell_id=self.cell_id,
            center=self.center,
            polygon=list(self.polygon),
            source=self.source,
            score=self.score,
            metadata=dict(self.metadata),
        )


@dataclass
class GridCellDetectionResult:
    """格子识别结果。"""

    cells: List[GridCellModel]
    summary: str
    debug: Dict[str, Any] = field(default_factory=dict)


def hex_polygon_from_basis(
    center: Tuple[float, float],
    basis_x: Tuple[float, float],
    basis_y: Tuple[float, float],
) -> List[Tuple[float, float]]:
    """根据两条逻辑轴的相邻中心向量，生成一个默认六边形轮廓。"""
    cx, cy = float(center[0]), float(center[1])
    ax_x, ax_y = float(basis_x[0]), float(basis_x[1])
    ay_x, ay_y = float(basis_y[0]), float(basis_y[1])
    offsets = [
        ((ax_x + ay_x) / 3.0, (ax_y + ay_y) / 3.0),
        ((-ax_x + 2.0 * ay_x) / 3.0, (-ax_y + 2.0 * ay_y) / 3.0),
        ((-2.0 * ax_x + ay_x) / 3.0, (-2.0 * ax_y + ay_y) / 3.0),
        ((-ax_x - ay_x) / 3.0, (-ax_y - ay_y) / 3.0),
        ((ax_x - 2.0 * ay_x) / 3.0, (ax_y - 2.0 * ay_y) / 3.0),
        ((2.0 * ax_x - ay_x) / 3.0, (2.0 * ax_y - ay_y) / 3.0),
    ]
    return [(cx + dx, cy + dy) for dx, dy in offsets]


def detect_grid_cells(
    image: np.ndarray,
    basis_x: Optional[Tuple[float, float]] = None,
    basis_y: Optional[Tuple[float, float]] = None,
    origin_client: Optional[Tuple[float, float]] = None,
    max_cells: int = 500,
) -> GridCellDetectionResult:
    """识别截图中的格子轮廓。优先用轮廓中心，若已有逻辑轴则补全可见六边格。"""
    if image is None or getattr(image, "size", 0) == 0:
        return GridCellDetectionResult([], "当前没有可识别的截图")

    image = np.ascontiguousarray(image)
    expected_area = None
    if basis_x and basis_y:
        expected_area = abs(float(basis_x[0]) * float(basis_y[1]) - float(basis_x[1]) * float(basis_y[0]))

    detected = _detect_contour_cells(image, basis_x, basis_y, expected_area, max_cells)

    if basis_x and basis_y and origin_client:
        generated = generate_visible_hex_cells(
            image_size=(image.shape[1], image.shape[0]),
            origin_client=origin_client,
            basis_x=basis_x,
            basis_y=basis_y,
            max_cells=max_cells,
        )
        merged = _merge_detected_and_generated(detected, generated, basis_x, basis_y)
        contour_count = sum(1 for cell in merged if cell.source == "detected")
        generated_count = len(merged) - contour_count
        summary = (
            f"识别到 {contour_count} 个图像轮廓，按当前坐标轴补全 {generated_count} 个可见格子，"
            f"共 {len(merged)} 个格子。"
        )
        return GridCellDetectionResult(
            merged[:max_cells],
            summary,
            debug={
                "contour_cells": len(detected),
                "generated_cells": len(generated),
                "merged_cells": len(merged),
            },
        )

    if detected:
        return GridCellDetectionResult(
            detected[:max_cells],
            f"从图像中识别到 {len(detected[:max_cells])} 个格子轮廓。",
            debug={"contour_cells": len(detected)},
        )

    return GridCellDetectionResult([], "未识别到明显格子轮廓；若先完成 X/Y 轴标定，系统可按逻辑轴补全可见格子。")


def generate_visible_hex_cells(
    image_size: Tuple[int, int],
    origin_client: Tuple[float, float],
    basis_x: Tuple[float, float],
    basis_y: Tuple[float, float],
    max_cells: int = 500,
) -> List[GridCellModel]:
    """根据逻辑轴方向生成当前视野内的默认六边格。"""
    width, height = int(image_size[0]), int(image_size[1])
    if width <= 0 or height <= 0:
        return []

    corners = [(0.0, 0.0), (float(width), 0.0), (0.0, float(height)), (float(width), float(height))]
    logical_corners = [_solve_logical(point, origin_client, basis_x, basis_y) for point in corners]
    xs = [point[0] for point in logical_corners]
    ys = [point[1] for point in logical_corners]

    min_x = math.floor(min(xs)) - 2
    max_x = math.ceil(max(xs)) + 2
    min_y = math.floor(min(ys)) - 2
    max_y = math.ceil(max(ys)) + 2

    cells: List[GridCellModel] = []
    for logical_x in range(min_x, max_x + 1):
        for logical_y in range(min_y, max_y + 1):
            center_x = origin_client[0] + logical_x * basis_x[0] + logical_y * basis_y[0]
            center_y = origin_client[1] + logical_x * basis_x[1] + logical_y * basis_y[1]
            polygon = hex_polygon_from_basis((center_x, center_y), basis_x, basis_y)
            if not _polygon_intersects_rect(polygon, width, height):
                continue

            cells.append(
                GridCellModel(
                    cell_id=f"cell_{logical_x}_{logical_y}",
                    center=(center_x, center_y),
                    polygon=polygon,
                    source="generated",
                    score=0.0,
                    metadata={"logical_hint": (logical_x, logical_y)},
                )
            )

            if len(cells) >= max_cells:
                return cells

    return cells


def _detect_contour_cells(
    image: np.ndarray,
    basis_x: Optional[Tuple[float, float]],
    basis_y: Optional[Tuple[float, float]],
    expected_area: Optional[float],
    max_cells: int,
) -> List[GridCellModel]:
    if cv2 is None:
        return []

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(blurred)
    edges = cv2.Canny(enhanced, 30, 100)
    thresh = cv2.adaptiveThreshold(
        enhanced,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        21,
        3,
    )
    mask = cv2.bitwise_or(edges, thresh)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    image_area = float(image.shape[0] * image.shape[1])
    if expected_area and expected_area > 1.0:
        min_area = max(40.0, expected_area * 0.25)
        max_area = max(min_area * 1.5, expected_area * 3.5)
        merge_distance = max(6.0, math.sqrt(expected_area) * 0.35)
    else:
        min_area = max(60.0, image_area / 25000.0)
        max_area = max(min_area * 2.0, image_area / 35.0)
        merge_distance = 12.0

    candidates: List[GridCellModel] = []
    for contour in contours:
        hull = cv2.convexHull(contour)
        area = float(cv2.contourArea(hull))
        if area < min_area or area > max_area:
            continue

        perimeter = float(cv2.arcLength(hull, True))
        if perimeter < 20.0:
            continue

        approx = cv2.approxPolyDP(hull, 0.03 * perimeter, True)
        vertex_count = len(approx)
        if vertex_count < 4 or vertex_count > 10:
            continue

        x, y, w, h = cv2.boundingRect(approx)
        if w <= 2 or h <= 2:
            continue
        ratio = max(w, h) / max(1.0, min(w, h))
        if ratio > 3.8:
            continue

        moments = cv2.moments(hull)
        if abs(moments.get("m00", 0.0)) <= 1e-6:
            continue

        center = (
            float(moments["m10"] / moments["m00"]),
            float(moments["m01"] / moments["m00"]),
        )
        polygon = [(float(point[0][0]), float(point[0][1])) for point in approx]
        if basis_x and basis_y and (vertex_count < 5 or vertex_count > 7):
            polygon = hex_polygon_from_basis(center, basis_x, basis_y)

        if expected_area and expected_area > 1.0:
            area_score = 1.0 / (1.0 + abs(area - expected_area) / expected_area)
        else:
            area_score = 1.0
        shape_score = 1.0 - min(abs(vertex_count - 6), 6) / 6.0
        score = shape_score * 0.55 + area_score * 0.45

        candidates.append(
            GridCellModel(
                cell_id=f"detected_{len(candidates)}",
                center=center,
                polygon=polygon,
                source="detected",
                score=score,
                metadata={"vertex_count": vertex_count, "area": area},
            )
        )

    candidates.sort(key=lambda item: item.score, reverse=True)
    filtered: List[GridCellModel] = []
    for candidate in candidates:
        too_close = False
        for existing in filtered:
            if math.hypot(candidate.center[0] - existing.center[0], candidate.center[1] - existing.center[1]) < merge_distance:
                too_close = True
                break
        if too_close:
            continue
        filtered.append(candidate)
        if len(filtered) >= max_cells:
            break
    return filtered


def _merge_detected_and_generated(
    detected: List[GridCellModel],
    generated: List[GridCellModel],
    basis_x: Tuple[float, float],
    basis_y: Tuple[float, float],
) -> List[GridCellModel]:
    if not generated:
        return [cell.copy() for cell in detected]

    merge_distance = max(
        8.0,
        min(_vector_length(basis_x), _vector_length(basis_y)) * 0.4,
    )
    remaining = [cell.copy() for cell in detected]
    merged: List[GridCellModel] = []

    for generated_cell in generated:
        nearest_index = None
        nearest_distance = None
        for index, detected_cell in enumerate(remaining):
            distance = math.hypot(
                generated_cell.center[0] - detected_cell.center[0],
                generated_cell.center[1] - detected_cell.center[1],
            )
            if nearest_distance is None or distance < nearest_distance:
                nearest_distance = distance
                nearest_index = index

        if nearest_index is not None and nearest_distance is not None and nearest_distance <= merge_distance:
            detected_cell = remaining.pop(nearest_index)
            merged.append(
                GridCellModel(
                    cell_id=generated_cell.cell_id,
                    center=detected_cell.center,
                    polygon=detected_cell.polygon,
                    source="detected",
                    score=detected_cell.score,
                    metadata={**generated_cell.metadata, **detected_cell.metadata},
                )
            )
        else:
            merged.append(generated_cell.copy())

    return merged


def _solve_logical(
    point: Tuple[float, float],
    origin_client: Tuple[float, float],
    basis_x: Tuple[float, float],
    basis_y: Tuple[float, float],
) -> Tuple[float, float]:
    dx = float(point[0]) - float(origin_client[0])
    dy = float(point[1]) - float(origin_client[1])
    det = float(basis_x[0]) * float(basis_y[1]) - float(basis_x[1]) * float(basis_y[0])
    if abs(det) <= 1e-9:
        return (0.0, 0.0)
    logical_x = (dx * float(basis_y[1]) - dy * float(basis_y[0])) / det
    logical_y = (float(basis_x[0]) * dy - float(basis_x[1]) * dx) / det
    return (logical_x, logical_y)


def _polygon_intersects_rect(polygon: List[Tuple[float, float]], width: int, height: int) -> bool:
    if not polygon:
        return False
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return not (max(xs) < 0 or max(ys) < 0 or min(xs) > width or min(ys) > height)


def _vector_length(vector: Tuple[float, float]) -> float:
    return math.hypot(float(vector[0]), float(vector[1]))