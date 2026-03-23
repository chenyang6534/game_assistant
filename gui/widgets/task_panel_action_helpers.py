"""TaskPanel 动作展示与坐标配置辅助。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QLabel

from task.models import (
    CLICK_OFFSET_MODE_LABELS,
    GRID_MODE_LABELS,
    IMAGE_MATCH_MODE_LABELS,
    RECOGNITION_ROI_MODE_LABELS,
    REMOVE_COORD_MODE_LABELS,
    get_default_click_offset_mode,
    coerce_float,
    derive_screen_drag_vector,
    normalize_click_offset_mode,
    normalize_grid_mode,
    normalize_highlight_duration_ms,
    normalize_point_position_mode,
    normalize_remove_coord_mode,
    normalize_drag_vector_mode,
    normalize_image_match_mode,
    normalize_recognition_roi_mode,
)
from utils.number_utils import coerce_unit_ratio


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
    "game_logic": "逻辑坐标",
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


def _populate_combo_from_mapping(combo: QComboBox, labels: dict[str, str]) -> None:
    combo.blockSignals(True)
    try:
        combo.clear()
        for value, label in labels.items():
            combo.addItem(label, value)
    finally:
        combo.blockSignals(False)


def populate_grid_mode_combo(combo: QComboBox) -> None:
    _populate_combo_from_mapping(combo, GRID_MODE_LABELS)


def populate_image_match_mode_combo(combo: QComboBox) -> None:
    _populate_combo_from_mapping(combo, IMAGE_MATCH_MODE_LABELS)


def populate_recognition_roi_mode_combo(combo: QComboBox) -> None:
    _populate_combo_from_mapping(combo, RECOGNITION_ROI_MODE_LABELS)


def populate_remove_coord_mode_combo(combo: QComboBox) -> None:
    _populate_combo_from_mapping(combo, REMOVE_COORD_MODE_LABELS)


def _set_combo_item_enabled(combo: QComboBox, index: int, enabled: bool) -> None:
    model = combo.model()
    item = model.item(index) if hasattr(model, "item") else None
    if item is not None:
        item.setEnabled(enabled)


def populate_grouped_action_type_combo(combo: QComboBox, groups) -> None:
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


def set_combo_data(combo: QComboBox, value: str, default: str = "single") -> None:
    index = combo.findData(value)
    if index < 0:
        index = combo.findData(default)
    if index >= 0:
        combo.setCurrentIndex(index)


def grid_mode_display_text(mode: str) -> str:
    mode = normalize_grid_mode(mode)
    return GRID_MODE_LABELS.get(mode, mode)


def remove_coord_mode_display_text(mode: str) -> str:
    mode = normalize_remove_coord_mode(mode)
    return REMOVE_COORD_MODE_LABELS.get(mode, mode)


def image_match_mode_display_text(mode: str) -> str:
    mode = normalize_image_match_mode(mode)
    return IMAGE_MATCH_MODE_LABELS.get(mode, mode)


def recognition_roi_mode_display_text(mode: str) -> str:
    mode = normalize_recognition_roi_mode(mode)
    return RECOGNITION_ROI_MODE_LABELS.get(mode, mode)


def coerce_drag_start_ratio(value, default: float = 0.5) -> float:
    return coerce_unit_ratio(value, default)


def coerce_point_ratio(value, default: float = 0.5) -> float:
    return coerce_unit_ratio(value, default)


def coerce_drag_vector_component(value, default: float = 0.0) -> float:
    return coerce_float(value, default)


def coerce_highlight_duration_ms(value, default: int = 1200) -> int:
    return normalize_highlight_duration_ms(value, default)


def highlight_duration_seconds_from_ms(value, default_ms: int = 1200) -> float:
    return coerce_highlight_duration_ms(value, default_ms) / 1000.0


def format_highlight_duration_seconds(value) -> str:
    text = f"{highlight_duration_seconds_from_ms(value):.2f}".rstrip("0").rstrip(".")
    return f"{text or '0'}秒"


def extract_drag_config_value(source, key: str, default=None):
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def coerce_action_bool(source, key: str, default: bool = False) -> bool:
    value = extract_drag_config_value(source, key, default)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "y")
    return bool(value)


def format_drag_vector_component(value) -> str:
    text = f"{coerce_drag_vector_component(value, 0.0):.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def get_action_point_values(source):
    mode = normalize_point_position_mode(
        extract_drag_config_value(source, "point_position_mode", "recognition")
    )
    default_value = 0.5 if mode == "screen_percent" else 0.0
    point_x = coerce_float(extract_drag_config_value(source, "point_x", default_value), default_value)
    point_y = coerce_float(extract_drag_config_value(source, "point_y", default_value), default_value)
    if mode == "screen_percent":
        point_x = coerce_point_ratio(point_x, 0.5)
        point_y = coerce_point_ratio(point_y, 0.5)
    return mode, point_x, point_y


def get_highlight_point_values(source):
    return get_action_point_values(source)


def get_action_point_text(source) -> str:
    value = extract_drag_config_value(source, "point_coord_text", "")
    return str(value or "").strip()


def get_action_offset_mode(source, point_mode: str) -> str:
    return normalize_click_offset_mode(
        extract_drag_config_value(source, "click_offset_mode", ""),
        point_mode,
    )


def format_action_offset_summary(source, mode: str) -> str:
    offset_x = coerce_float(extract_drag_config_value(source, "click_offset_x", 0.0), 0.0)
    offset_y = coerce_float(extract_drag_config_value(source, "click_offset_y", 0.0), 0.0)
    if abs(offset_x) <= 1e-9 and abs(offset_y) <= 1e-9:
        return ""
    offset_mode = get_action_offset_mode(source, mode)
    label = CLICK_OFFSET_MODE_LABELS.get(offset_mode, "偏移")
    return (
        f" / {label}("
        f"{format_drag_vector_component(offset_x)}, {format_drag_vector_component(offset_y)})"
    )


def format_action_point_summary(source) -> str:
    mode, point_x, point_y = get_action_point_values(source)
    point_text = get_action_point_text(source)
    if mode == "recognition":
        offset_text = format_action_offset_summary(source, mode)
        return f"识别结果坐标{offset_text}"
    if point_text:
        if mode == "screen_percent":
            return f"目标窗口比例({point_text}){format_action_offset_summary(source, mode)}"
        return f"目标窗口({point_text}){format_action_offset_summary(source, mode)}"
    if mode == "screen_percent":
        return (
            f"目标窗口比例({point_x:.3f}, {point_y:.3f})"
            f"{format_action_offset_summary(source, mode)}"
        )
    return (
        f"目标窗口({int(round(point_x))}, {int(round(point_y))})"
        f"{format_action_offset_summary(source, mode)}"
    )


def format_highlight_match_summary(source) -> str:
    duration_text = format_highlight_duration_seconds(
        extract_drag_config_value(source, "duration_ms", 1200)
    )
    if coerce_action_bool(source, "show_ai_attributes", False):
        return f"{duration_text} / 显示AI属性"
    return duration_text


def format_highlight_point_summary(source) -> str:
    duration_text = format_highlight_duration_seconds(extract_drag_config_value(source, "duration_ms", 1200))
    return f"{format_action_point_summary(source)} / {duration_text}"


def configure_point_coordinate_spins(x_spin: QDoubleSpinBox, y_spin: QDoubleSpinBox, mode: str) -> None:
    mode = normalize_point_position_mode(mode)
    if mode == "screen_percent":
        configs = (
            (x_spin, coerce_point_ratio(x_spin.value(), 0.5)),
            (y_spin, coerce_point_ratio(y_spin.value(), 0.5)),
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


def configure_offset_spin(spin: QDoubleSpinBox, minimum: float, maximum: float, step: float, decimals: int) -> None:
    value = coerce_float(spin.value(), 0.0)
    spin.blockSignals(True)
    spin.setRange(min(minimum, value), max(maximum, value))
    spin.setSingleStep(step)
    spin.setDecimals(decimals)
    spin.setValue(value)
    spin.blockSignals(False)


def configure_click_offset_spins(
    x_spin: QDoubleSpinBox,
    y_spin: QDoubleSpinBox,
    offset_mode: str,
    hint_label: QLabel = None,
) -> None:
    offset_mode = normalize_click_offset_mode(offset_mode)
    if offset_mode == "screen_absolute":
        configure_offset_spin(x_spin, -100000.0, 100000.0, 1.0, 2)
        configure_offset_spin(y_spin, -100000.0, 100000.0, 1.0, 2)
        x_tip = "基于目标窗口客户区像素的偏移\nX 正数向右，负数向左"
        y_tip = "基于目标窗口客户区像素的偏移\nY 正数向下，负数向上"
        hint_text = CLICK_OFFSET_SCREEN_ABSOLUTE_HINT_TEXT
    elif offset_mode == "screen_percent":
        configure_offset_spin(x_spin, -5.0, 5.0, 0.05, 3)
        configure_offset_spin(y_spin, -5.0, 5.0, 0.05, 3)
        x_tip = "基于目标窗口客户区宽度比例的偏移\nX=0.5 表示额外向右偏移半个窗口宽度"
        y_tip = "基于目标窗口客户区高度比例的偏移\nY=0.5 表示额外向下偏移半个窗口高度"
        hint_text = CLICK_OFFSET_SCREEN_PERCENT_HINT_TEXT
    else:
        configure_offset_spin(x_spin, -5.0, 5.0, 0.1, 2)
        configure_offset_spin(y_spin, -10.0, 10.0, 0.1, 2)
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


def sync_click_offset_mode_combo_with_point_mode(dialog, point_mode: str) -> None:
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
        set_combo_data(
            dialog._click_offset_mode,
            get_default_click_offset_mode(point_mode),
            default=get_default_click_offset_mode(point_mode),
        )
    dialog._last_point_position_mode_for_offset = point_mode


def format_recognition_roi_summary(source) -> str:
    mode = normalize_recognition_roi_mode(getattr(source, "recognition_roi_mode", "full_window"))
    if mode != "window_percent":
        return ""

    roi_x = coerce_point_ratio(getattr(source, "recognition_roi_x", 0.0), 0.0)
    roi_y = coerce_point_ratio(getattr(source, "recognition_roi_y", 0.0), 0.0)
    roi_w = max(0.01, coerce_point_ratio(getattr(source, "recognition_roi_width", 1.0), 1.0))
    roi_h = max(0.01, coerce_point_ratio(getattr(source, "recognition_roi_height", 1.0), 1.0))
    return f"范围({roi_x:.2f},{roi_y:.2f},{roi_w:.2f},{roi_h:.2f})"


def coerce_grid_radius(value, default: int = 2) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(0, number)


def format_traverse_grid_detail(action: Optional[dict]) -> str:
    action = action or {}
    center_param = (action.get("center_param", "") or "").strip()
    target_array = (action.get("target_array", "") or "").strip()
    mode_text = grid_mode_display_text(action.get("mode", "hex"))
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


def format_surrounding_coords_detail(action: Optional[dict]) -> str:
    action = action or {}
    target_coord = (action.get("target_coord", "") or "").strip()
    result_array = (action.get("result_array", "") or "").strip()
    mode_text = grid_mode_display_text(action.get("mode", "hex"))
    radius = coerce_grid_radius(action.get("radius", 2), 2)

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


def format_remove_target_coords_detail(action: Optional[dict]) -> str:
    action = action or {}
    source_array = (action.get("source_array", "") or "").strip()
    target_value = (action.get("target_value", "") or "").strip()
    mode_text = remove_coord_mode_display_text(action.get("remove_mode", "single"))

    parts = []
    if source_array:
        parts.append(source_array)
    parts.append(mode_text)
    if target_value:
        parts.append(target_value)
    return " / ".join(part for part in parts if part)


def format_find_road_path_detail(action: Optional[dict]) -> str:
    action = action or {}
    start_array = (action.get("start_array", "") or "").strip()
    target_coord = (action.get("target_coord", "") or "").strip()
    passable_array = (action.get("passable_array", "") or "").strip()
    result_array = (action.get("result_array", "") or "").strip()
    mode_text = grid_mode_display_text(action.get("mode", "hex"))

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


def format_save_recognition_coords_detail(action: Optional[dict]) -> str:
    action = action or {}
    result_array = (action.get("result_array", "") or "").strip()
    return f"输出 {result_array}" if result_array else ""


def format_recognition_to_logic_summary(action: Optional[dict]) -> str:
    action = action or {}
    csv_path = (action.get("coordinate_csv_path", "") or "").strip()
    csv_name = str(csv_path).split("/")[-1].split("\\")[-1] if csv_path else ""
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


def get_screen_drag_vector_values(source):
    drag_coordinate_mode = extract_drag_config_value(source, "drag_coordinate_mode", "game_logic") or "game_logic"
    legacy_x, legacy_y = (0.0, 0.0)
    if drag_coordinate_mode == "screen":
        legacy_x, legacy_y = derive_screen_drag_vector(
            extract_drag_config_value(source, "drag_direction_x", 0),
            extract_drag_config_value(source, "drag_direction_y", 0),
            extract_drag_config_value(source, "drag_distance", 200),
        )
    vector_mode = normalize_drag_vector_mode(
        extract_drag_config_value(source, "drag_vector_mode", "pixel")
    )
    vector_x = coerce_drag_vector_component(
        extract_drag_config_value(source, "drag_vector_x", legacy_x),
        legacy_x,
    )
    vector_y = coerce_drag_vector_component(
        extract_drag_config_value(source, "drag_vector_y", legacy_y),
        legacy_y,
    )
    return vector_mode, vector_x, vector_y