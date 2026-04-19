"""
计划任务数据模型
"""

from dataclasses import dataclass, field
from typing import List, Optional, Any
from enum import Enum
import math
import time
import uuid


# ────────────────── 枚举 ──────────────────

class ParamType(str, Enum):
    """参数类型"""
    TEXT = "text"                   # 文本 / 数值
    COORDINATE = "coordinate"      # 坐标 (自动含 x, y)
    IMAGE = "image"                # 图像路径
    ARRAY = "array"                # 普通数组
    COORD_ARRAY = "coord_array"    # 坐标数组 [[x,y], ...]


class RecognitionType(str, Enum):
    """识别类型"""
    TEXT = "text"                   # OCR 文字识别
    IMAGE = "image"                # 图像模板匹配
    MULTI_IMAGE = "multi_image"    # 多图像识别（任一匹配即成功）
    NONE = "none"                  # 无识别，直接执行操作


class ActionType(str, Enum):
    """操作类型"""
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    HOLD_LEFT_BUTTON = "hold_left_button"
    HIGHLIGHT_MATCH = "highlight_match"
    HIGHLIGHT_POINT = "highlight_point"
    INPUT_TEXT = "input_text"
    PRESS_KEY = "press_key"
    DRAG_MAP = "drag_map"
    DRAG_MATCH_TO_CENTER = "drag_match_to_center"
    MARK_BLOCKED = "mark_blocked"
    MODIFY_VARIABLE = "modify_variable"
    ADD_TO_ARRAY = "add_to_array"
    SAVE_RECOGNITION_COORDS = "save_recognition_coords"
    REMOVE_TARGET_COORDS = "remove_target_coords"
    CLEAR_ARRAY_DATA = "clear_array_data"
    RECOGNITION_TO_LOGIC_COORD = "recognition_to_logic_coord"
    JUMP_TO_STEP = "jump_to_step"
    TRAVERSE_HEX = "traverse_hex"
    TRAVERSE_GRID = "traverse_grid"
    GET_TWO_RING_COORDS = "get_two_ring_coords"
    GET_SURROUNDING_COORDS = "get_surrounding_coords"
    FIND_ROAD_PATH = "find_road_path"
    NONE = "none"


class ConditionType(str, Enum):
    """条件类型"""
    VARIABLE = "variable"
    IMAGE = "image"
    TEXT = "text"
    ARRAY_CONTAINS = "array_contains"
    COORD_IN_ARRAY = "coord_in_array"


BASE_PARAM_TYPE_LABELS = {
    "text": "文本",
    "coordinate": "坐标",
    "image": "图像",
    "array": "数组",
    "coord_array": "坐标数组",
}

ARRAY_ITEM_TYPE_LABELS = {
    "string": "文字",
    "image": "图像路径",
    "int": "整数",
}

REMOVE_COORD_MODE_LABELS = {
    "single": "单个坐标",
    "multiple": "多个坐标",
}

STRUCT_FIELD_TYPE_LABELS = {
    "int": "整形",
    "string": "字符串",
}

RECOGNITION_TARGET_MODE_LABELS = {
    "single": "单个目标",
    "array_any": "数组(仅需识别到1个就成功)",
    "array_all": "数组(识别到全部才成功)",
}

IMAGE_MATCH_MODE_LABELS = {
    "template": "普通模板匹配",
    "foreground": "前景优先匹配（忽略背景）",
}

RECOGNITION_ROI_MODE_LABELS = {
    "full_window": "整个目标窗口",
    "window_percent": "自定义窗口百分比范围",
}

GRID_MODE_LABELS = {
    "hex": "六方格",
}

CLICK_OFFSET_MODE_LABELS = {
    "template_ratio": "模板比例",
    "screen_absolute": "窗口像素",
    "screen_percent": "窗口比例",
}

ACTION_TYPE_ALIASES = {
    ActionType.TRAVERSE_HEX.value: ActionType.TRAVERSE_GRID.value,
    ActionType.GET_TWO_RING_COORDS.value: ActionType.GET_SURROUNDING_COORDS.value,
}


def normalize_recognition_target_mode(mode: str) -> str:
    if mode in RECOGNITION_TARGET_MODE_LABELS:
        return mode
    return "single"


def normalize_image_match_mode(mode: str) -> str:
    if mode == "feature":
        return "foreground"
    if mode in IMAGE_MATCH_MODE_LABELS:
        return mode
    return "template"


def normalize_recognition_roi_mode(mode: str) -> str:
    if mode in RECOGNITION_ROI_MODE_LABELS:
        return mode
    return "full_window"


def normalize_recognition_roi_size(value, default: float = 1.0) -> float:
    return max(0.01, clamp_unit_float(value, default))


def normalize_action_type(action_type: str) -> str:
    if action_type in ACTION_TYPE_ALIASES:
        return ACTION_TYPE_ALIASES[action_type]
    return action_type or "none"


def normalize_remove_coord_mode(mode: str) -> str:
    if mode in REMOVE_COORD_MODE_LABELS:
        return mode
    return "single"


def normalize_grid_mode(mode: str) -> str:
    if mode in GRID_MODE_LABELS:
        return mode
    return "hex"


def normalize_drag_start_mode(mode: str) -> str:
    if mode in ("recognition", "screen_percent"):
        return mode
    return "recognition"


def normalize_drag_vector_mode(mode: str) -> str:
    if mode in ("pixel", "screen_percent"):
        return mode
    return "pixel"


def normalize_point_position_mode(mode: str) -> str:
    if mode in ("recognition", "screen_absolute", "screen_percent"):
        return mode
    return "recognition"


def get_default_click_offset_mode(point_mode: str = "recognition") -> str:
    point_mode = normalize_point_position_mode(point_mode)
    if point_mode == "screen_absolute":
        return "screen_absolute"
    if point_mode == "screen_percent":
        return "screen_percent"
    return "template_ratio"


def normalize_click_offset_mode(mode: str, point_mode: str = "recognition") -> str:
    if mode in CLICK_OFFSET_MODE_LABELS:
        return mode
    return get_default_click_offset_mode(point_mode)


def normalize_highlight_duration_ms(value, default: int = 1200) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(100, number)


def normalize_center_tolerance_px(value, default: int = 1) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(1, number)


def clamp_unit_float(value, default: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def coerce_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def derive_screen_drag_vector(direction_x, direction_y, distance):
    screen_dx = coerce_float(direction_x, 0.0)
    screen_dy = coerce_float(direction_y, 0.0)
    total_distance = max(0.0, coerce_float(distance, 0.0))
    magnitude = math.sqrt(screen_dx ** 2 + screen_dy ** 2)
    if magnitude <= 0 or total_distance <= 0:
        return 0.0, 0.0
    return (screen_dx / magnitude) * total_distance, (screen_dy / magnitude) * total_distance


def make_struct_param_type(struct_name: str) -> str:
    return f"struct:{struct_name}"


def make_struct_array_param_type(struct_name: str) -> str:
    return f"struct_array:{struct_name}"


def is_struct_param_type(param_type: str) -> bool:
    return isinstance(param_type, str) and param_type.startswith("struct:")


def is_struct_array_param_type(param_type: str) -> bool:
    return isinstance(param_type, str) and param_type.startswith("struct_array:")


def is_array_param_type(param_type: str) -> bool:
    return param_type in ("array", "coord_array") or is_struct_array_param_type(param_type)


def get_struct_name_from_type(param_type: str) -> str:
    if is_struct_param_type(param_type) or is_struct_array_param_type(param_type):
        return param_type.split(":", 1)[1]
    return ""


def get_param_type_label(param_type: str) -> str:
    if param_type == "array":
        return BASE_PARAM_TYPE_LABELS.get(param_type, param_type)
    if is_struct_param_type(param_type):
        return f"结构体<{get_struct_name_from_type(param_type)}>"
    if is_struct_array_param_type(param_type):
        return f"结构体数组<{get_struct_name_from_type(param_type)}>"
    return BASE_PARAM_TYPE_LABELS.get(param_type, param_type)


def get_array_param_type_label(array_item_type: str) -> str:
    return f"数组<{ARRAY_ITEM_TYPE_LABELS.get(array_item_type, array_item_type)}>"


def coerce_array_item_value(array_item_type: str, raw_value):
    if array_item_type == "int":
        if isinstance(raw_value, str):
            raw_value = raw_value.strip()
        if raw_value in (None, ""):
            raise ValueError("整数数组项不能为空")
        return int(raw_value)

    if array_item_type == "image":
        text = "" if raw_value is None else str(raw_value).strip()
        if not text:
            raise ValueError("图像路径数组项不能为空")
        return text

    if raw_value is None:
        return ""
    return str(raw_value)


def normalize_array_items(raw_items, array_item_type: str) -> List[Any]:
    if not isinstance(raw_items, list):
        return []

    normalized = []
    for item in raw_items:
        try:
            normalized.append(coerce_array_item_value(array_item_type, item))
        except (TypeError, ValueError):
            continue
    return normalized


@dataclass
class StructField:
    """结构体成员定义"""
    name: str = ""
    field_type: str = "string"

    def __post_init__(self):
        self.name = str(self.name).strip()
        if self.field_type not in STRUCT_FIELD_TYPE_LABELS:
            self.field_type = "string"

    def default_value(self):
        return 0 if self.field_type == "int" else ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "field_type": self.field_type,
        }

    @staticmethod
    def from_dict(data: dict) -> "StructField":
        return StructField(
            name=data.get("name", ""),
            field_type=data.get("field_type", "string"),
        )


@dataclass
class StructDefinition:
    """任务内可复用的结构体定义"""
    name: str = ""
    fields: List[StructField] = field(default_factory=list)

    def __post_init__(self):
        normalized = []
        seen = set()
        for member in self.fields:
            if isinstance(member, StructField):
                field_item = member
            elif isinstance(member, dict):
                field_item = StructField.from_dict(member)
            else:
                field_item = StructField(name=str(member).strip(), field_type="string")
            if field_item.name and field_item.name not in seen:
                normalized.append(field_item)
                seen.add(field_item.name)
        self.fields = normalized

    def get_field(self, name: str) -> Optional[StructField]:
        for field_item in self.fields:
            if field_item.name == name:
                return field_item
        return None

    def build_default_value(self) -> dict:
        return {field_item.name: field_item.default_value() for field_item in self.fields}

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "fields": [field_item.to_dict() for field_item in self.fields],
        }

    @staticmethod
    def from_dict(data: dict) -> "StructDefinition":
        raw_fields = data.get("fields", [])
        return StructDefinition(
            name=data.get("name", ""),
            fields=raw_fields,
        )


def build_param_default_value(param_type: str, struct_defs: List[StructDefinition] = None) -> Any:
    if param_type == "text":
        return ""
    if param_type == "coordinate":
        return {"x": 0, "y": 0}
    if param_type == "image":
        return ""
    if param_type == "array":
        return []
    if param_type == "coord_array":
        return []
    if is_struct_param_type(param_type):
        struct_name = get_struct_name_from_type(param_type)
        for struct_def in struct_defs or []:
            if struct_def.name == struct_name:
                return struct_def.build_default_value()
        return {}
    if is_struct_array_param_type(param_type):
        return []
    return ""


# ────────────────── 参数 ──────────────────

@dataclass
class TaskParameter:
    """任务参数"""
    name: str = ""
    param_type: str = "text"
    value: Any = None
    persist: bool = False
    array_item_type: str = "string"

    def __post_init__(self):
        if self.array_item_type not in ARRAY_ITEM_TYPE_LABELS:
            self.array_item_type = "string"
        if self.value is None:
            self.value = build_param_default_value(self.param_type)
        elif self.param_type == "array":
            self.value = normalize_array_items(self.value, self.array_item_type)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "param_type": self.param_type,
            "value": self.value,
            "persist": self.persist,
            "array_item_type": self.array_item_type,
        }

    @staticmethod
    def from_dict(data: dict) -> "TaskParameter":
        return TaskParameter(
            name=data.get("name", ""),
            param_type=data.get("param_type", "text"),
            value=data.get("value"),
            persist=data.get("persist", False),
            array_item_type=data.get("array_item_type", "string"),
        )


# ────────────────── 条件 ──────────────────

@dataclass
class StepCondition:
    """步骤执行条件"""
    condition_type: str = "variable"
    # 变量条件
    left_operand: str = ""
    left_use_length: bool = False
    operator: str = "=="
    right_operand: str = ""
    right_use_length: bool = False
    # 图像 / 文字识别条件
    rec_target: str = ""
    threshold: float = 0.8
    validate_color_consistency: bool = False
    negate: bool = False
    # 数组条件
    array_name: str = ""
    search_value: str = ""
    # 逻辑连接
    logic_next: str = ""

    def to_dict(self) -> dict:
        return {
            "condition_type": self.condition_type,
            "left_operand": self.left_operand,
            "left_use_length": self.left_use_length,
            "operator": self.operator,
            "right_operand": self.right_operand,
            "right_use_length": self.right_use_length,
            "rec_target": self.rec_target,
            "threshold": self.threshold,
            "validate_color_consistency": self.validate_color_consistency,
            "negate": self.negate,
            "array_name": self.array_name,
            "search_value": self.search_value,
            "logic_next": self.logic_next,
        }

    @staticmethod
    def from_dict(data: dict) -> "StepCondition":
        condition_type = data.get("condition_type", "variable")
        if condition_type == "array_length":
            return StepCondition(
                condition_type="variable",
                left_operand=data.get("array_name", ""),
                left_use_length=True,
                operator=data.get("operator", "=="),
                right_operand=data.get("right_operand", ""),
                right_use_length=False,
                negate=data.get("negate", False),
                logic_next=data.get("logic_next", ""),
            )
        return StepCondition(
            condition_type=condition_type,
            left_operand=data.get("left_operand", ""),
            left_use_length=data.get("left_use_length", False),
            operator=data.get("operator", "=="),
            right_operand=data.get("right_operand", ""),
            right_use_length=data.get("right_use_length", False),
            rec_target=data.get("rec_target", ""),
            threshold=data.get("threshold", 0.8),
            validate_color_consistency=data.get("validate_color_consistency", False),
            negate=data.get("negate", False),
            array_name=data.get("array_name", ""),
            search_value=data.get("search_value", ""),
            logic_next=data.get("logic_next", ""),
        )


# ────────────────── 步骤 ──────────────────

@dataclass
class SingleTask:
    """单一任务（计划任务中的一个步骤）"""
    name: str = "未命名步骤"
    recognition_type: str = "image"
    recognition_target: str = ""
    recognition_target_mode: str = "single"
    image_match_mode: str = "template"
    recognition_roi_mode: str = "full_window"
    recognition_roi_x: float = 0.0
    recognition_roi_y: float = 0.0
    recognition_roi_width: float = 1.0
    recognition_roi_height: float = 1.0
    recognition_threshold: float = 0.8
    validate_color_consistency: bool = False
    exact_match: bool = False
    action_type: str = "click"
    input_text: str = ""
    press_keys: str = ""
    clear_method: str = "delete_backspace"
    clear_key_count: int = 3
    drag_coordinate_mode: str = "game_logic"
    drag_start_mode: str = "recognition"
    drag_start_x: float = 0.5
    drag_start_y: float = 0.5
    drag_direction_x: int = 0
    drag_direction_y: int = 0
    drag_distance: int = 200
    drag_vector_mode: str = "pixel"
    drag_vector_x: float = 0.0
    drag_vector_y: float = 0.0
    drag_duration: float = 0.3
    center_tolerance_px: int = 1
    highlight_duration_ms: int = 1200
    point_position_mode: str = "recognition"
    point_x: float = 0.5
    point_y: float = 0.5
    point_coord_text: str = ""
    match_index: int = 1
    has_multiple_matches: bool = False
    use_background: bool = True
    timeout: float = 5.0
    retry_interval: float = 1.0
    click_offset_mode: str = "template_ratio"
    click_offset_x: float = 0.0
    click_offset_y: float = 0.0
    delay_after: float = 0.2
    id: str = ""
    # 条件
    conditions: List[dict] = field(default_factory=list)
    # 主操作列表（按顺序执行）
    actions: List[dict] = field(default_factory=list)
    # 循环
    is_loop: bool = False
    loop_array: str = ""
    loop_var: str = ""
    children: List["SingleTask"] = field(default_factory=list)
    # 跳转
    jump_target_id: str = ""
    # 修改变量
    modify_var_name: str = ""
    modify_var_value: str = ""
    # 添加到数组
    add_to_array_items: List[dict] = field(default_factory=list)
    # 保存识别坐标
    recognition_coord_result_array: str = ""
    # 删除目标坐标
    remove_coord_source_array: str = ""
    remove_coord_target_value: str = ""
    remove_coord_mode: str = "single"
    # 清空数组
    clear_array_name: str = ""
    # 识别坐标转逻辑坐标
    recognition_to_logic_csv_path: str = ""
    recognition_to_logic_anchor_logical: str = ""
    recognition_to_logic_anchor_screen: str = ""
    recognition_to_logic_result_array: str = ""
    # 遍历网格
    traverse_center_param: str = ""
    traverse_target_array: str = ""
    traverse_count: int = 1000
    traverse_mode: str = "hex"
    # 按半径获取周围坐标
    two_ring_target_coord: str = ""
    two_ring_result_array: str = ""
    surround_target_coord: str = ""
    surround_result_array: str = ""
    surround_radius: int = 2
    surround_mode: str = "hex"
    # 寻找铺路路径
    path_target_coord: str = ""
    path_start_array: str = ""
    path_passable_array: str = ""
    path_result_array: str = ""
    path_mode: str = "hex"
    # 识别失败时的操作
    on_fail_enabled: bool = False
    on_fail_actions: List[dict] = field(default_factory=list)
    # 向后兼容旧字段（会在加载时转换为on_fail_actions）
    on_fail_action_type: str = ""
    on_fail_modify_var_name: str = ""
    on_fail_modify_var_value: str = ""
    on_fail_jump_target_id: str = ""
    on_fail_add_array_items: List[dict] = field(default_factory=list)

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:8]
        self.recognition_target_mode = normalize_recognition_target_mode(self.recognition_target_mode)
        self.image_match_mode = normalize_image_match_mode(getattr(self, "image_match_mode", "template"))
        self.recognition_roi_mode = normalize_recognition_roi_mode(getattr(self, "recognition_roi_mode", "full_window"))
        self.recognition_roi_x = clamp_unit_float(getattr(self, "recognition_roi_x", 0.0), 0.0)
        self.recognition_roi_y = clamp_unit_float(getattr(self, "recognition_roi_y", 0.0), 0.0)
        self.recognition_roi_width = normalize_recognition_roi_size(getattr(self, "recognition_roi_width", 1.0), 1.0)
        self.recognition_roi_height = normalize_recognition_roi_size(getattr(self, "recognition_roi_height", 1.0), 1.0)
        if self.drag_coordinate_mode not in ("game_logic", "screen"):
            self.drag_coordinate_mode = "game_logic"
        self.drag_start_mode = normalize_drag_start_mode(self.drag_start_mode)
        self.drag_start_x = clamp_unit_float(self.drag_start_x, 0.5)
        self.drag_start_y = clamp_unit_float(self.drag_start_y, 0.5)
        self.drag_vector_mode = normalize_drag_vector_mode(self.drag_vector_mode)
        self.drag_vector_x = coerce_float(self.drag_vector_x, 0.0)
        self.drag_vector_y = coerce_float(self.drag_vector_y, 0.0)
        self.center_tolerance_px = normalize_center_tolerance_px(self.center_tolerance_px)
        self.highlight_duration_ms = normalize_highlight_duration_ms(self.highlight_duration_ms)
        self.point_position_mode = normalize_point_position_mode(self.point_position_mode)
        self.point_x = coerce_float(self.point_x, 0.5)
        self.point_y = coerce_float(self.point_y, 0.5)
        self.point_coord_text = str(getattr(self, "point_coord_text", "") or "").strip()
        self.click_offset_mode = normalize_click_offset_mode(
            getattr(self, "click_offset_mode", get_default_click_offset_mode(self.point_position_mode)),
            self.point_position_mode,
        )
        self.timeout = max(0.0, coerce_float(getattr(self, "timeout", 5.0), 5.0))
        self.remove_coord_mode = normalize_remove_coord_mode(getattr(self, "remove_coord_mode", "single"))
        self.traverse_mode = normalize_grid_mode(getattr(self, "traverse_mode", "hex"))
        self.surround_mode = normalize_grid_mode(getattr(self, "surround_mode", "hex"))
        self.path_mode = normalize_grid_mode(getattr(self, "path_mode", "hex"))
        try:
            self.surround_radius = int(getattr(self, "surround_radius", 2) or 0)
        except (TypeError, ValueError):
            self.surround_radius = 2
        self.surround_radius = max(0, self.surround_radius)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "recognition_type": self.recognition_type,
            "recognition_target": self.recognition_target,
            "recognition_target_mode": self.recognition_target_mode,
            "image_match_mode": self.image_match_mode,
            "recognition_roi_mode": self.recognition_roi_mode,
            "recognition_roi_x": self.recognition_roi_x,
            "recognition_roi_y": self.recognition_roi_y,
            "recognition_roi_width": self.recognition_roi_width,
            "recognition_roi_height": self.recognition_roi_height,
            "recognition_threshold": self.recognition_threshold,
            "validate_color_consistency": self.validate_color_consistency,
            "exact_match": self.exact_match,
            "action_type": self.action_type,
            "input_text": self.input_text,
            "press_keys": self.press_keys,
            "clear_method": self.clear_method,
            "clear_key_count": self.clear_key_count,
            "drag_coordinate_mode": self.drag_coordinate_mode,
            "drag_start_mode": self.drag_start_mode,
            "drag_start_x": self.drag_start_x,
            "drag_start_y": self.drag_start_y,
            "drag_direction_x": self.drag_direction_x,
            "drag_direction_y": self.drag_direction_y,
            "drag_distance": self.drag_distance,
            "drag_vector_mode": self.drag_vector_mode,
            "drag_vector_x": self.drag_vector_x,
            "drag_vector_y": self.drag_vector_y,
            "drag_duration": self.drag_duration,
            "center_tolerance_px": self.center_tolerance_px,
            "highlight_duration_ms": self.highlight_duration_ms,
            "point_position_mode": self.point_position_mode,
            "point_x": self.point_x,
            "point_y": self.point_y,
            "point_coord_text": self.point_coord_text,
            "match_index": self.match_index,
            "has_multiple_matches": self.has_multiple_matches,
            "use_background": self.use_background,
            "timeout": self.timeout,
            "retry_interval": self.retry_interval,
            "click_offset_mode": self.click_offset_mode,
            "click_offset_x": self.click_offset_x,
            "click_offset_y": self.click_offset_y,
            "delay_after": self.delay_after,
            "conditions": self.conditions,
            "actions": self.actions,
            "is_loop": self.is_loop,
            "loop_array": self.loop_array,
            "loop_var": self.loop_var,
            "children": [c.to_dict() for c in self.children],
            "jump_target_id": self.jump_target_id,
            "modify_var_name": self.modify_var_name,
            "modify_var_value": self.modify_var_value,
            "add_to_array_items": self.add_to_array_items,
            "recognition_coord_result_array": self.recognition_coord_result_array,
            "remove_coord_source_array": self.remove_coord_source_array,
            "remove_coord_target_value": self.remove_coord_target_value,
            "remove_coord_mode": self.remove_coord_mode,
            "clear_array_name": self.clear_array_name,
            "recognition_to_logic_csv_path": self.recognition_to_logic_csv_path,
            "recognition_to_logic_anchor_logical": self.recognition_to_logic_anchor_logical,
            "recognition_to_logic_anchor_screen": self.recognition_to_logic_anchor_screen,
            "recognition_to_logic_result_array": self.recognition_to_logic_result_array,
            "traverse_center_param": self.traverse_center_param,
            "traverse_target_array": self.traverse_target_array,
            "traverse_count": self.traverse_count,
            "traverse_mode": self.traverse_mode,
            "two_ring_target_coord": self.two_ring_target_coord,
            "two_ring_result_array": self.two_ring_result_array,
            "surround_target_coord": self.surround_target_coord,
            "surround_result_array": self.surround_result_array,
            "surround_radius": self.surround_radius,
            "surround_mode": self.surround_mode,
            "path_target_coord": self.path_target_coord,
            "path_start_array": self.path_start_array,
            "path_passable_array": self.path_passable_array,
            "path_result_array": self.path_result_array,
            "path_mode": self.path_mode,
            "on_fail_enabled": self.on_fail_enabled,
            "on_fail_actions": self.on_fail_actions,
        }

    @staticmethod
    def from_dict(data: dict) -> "SingleTask":
        children = [SingleTask.from_dict(c) for c in data.get("children", [])]
        drag_coordinate_mode = data.get("drag_coordinate_mode", "game_logic")
        legacy_vector_x, legacy_vector_y = derive_screen_drag_vector(
            data.get("drag_direction_x", 0),
            data.get("drag_direction_y", 0),
            data.get("drag_distance", 200),
        ) if drag_coordinate_mode == "screen" else (0.0, 0.0)
        return SingleTask(
            id=data.get("id", ""),
            name=data.get("name", "未命名步骤"),
            recognition_type=data.get("recognition_type", "image"),
            recognition_target=data.get("recognition_target", ""),
            recognition_target_mode=data.get("recognition_target_mode", "single"),
            image_match_mode=data.get("image_match_mode", "template"),
            recognition_roi_mode=data.get("recognition_roi_mode", "full_window"),
            recognition_roi_x=data.get("recognition_roi_x", 0.0),
            recognition_roi_y=data.get("recognition_roi_y", 0.0),
            recognition_roi_width=data.get("recognition_roi_width", 1.0),
            recognition_roi_height=data.get("recognition_roi_height", 1.0),
            recognition_threshold=data.get("recognition_threshold", 0.8),
            validate_color_consistency=data.get("validate_color_consistency", False),
            exact_match=data.get("exact_match", False),
            action_type=data.get("action_type", "click"),
            input_text=data.get("input_text", ""),
            press_keys=data.get("press_keys", ""),
            clear_method=data.get("clear_method", "delete_backspace"),
            clear_key_count=data.get("clear_key_count", 3),
            drag_coordinate_mode=drag_coordinate_mode,
            drag_start_mode=data.get("drag_start_mode", "recognition"),
            drag_start_x=data.get("drag_start_x", 0.5),
            drag_start_y=data.get("drag_start_y", 0.5),
            drag_direction_x=data.get("drag_direction_x", 0),
            drag_direction_y=data.get("drag_direction_y", 0),
            drag_distance=data.get("drag_distance", 200),
            drag_vector_mode=data.get("drag_vector_mode", "pixel"),
            drag_vector_x=data.get("drag_vector_x", legacy_vector_x),
            drag_vector_y=data.get("drag_vector_y", legacy_vector_y),
            drag_duration=data.get("drag_duration", 0.3),
            center_tolerance_px=data.get("center_tolerance_px", 1),
            highlight_duration_ms=data.get("highlight_duration_ms", 1200),
            point_position_mode=data.get("point_position_mode", "recognition"),
            point_x=data.get("point_x", 0.5),
            point_y=data.get("point_y", 0.5),
            point_coord_text=data.get("point_coord_text", ""),
            match_index=data.get("match_index", 1),
            has_multiple_matches=data.get("has_multiple_matches", False),
            use_background=data.get("use_background", True),
            timeout=coerce_float(data.get("timeout", 5.0), 5.0),
            retry_interval=data.get("retry_interval", 1.0),
            click_offset_mode=data.get(
                "click_offset_mode",
                get_default_click_offset_mode(data.get("point_position_mode", "recognition")),
            ),
            click_offset_x=float(data.get("click_offset_x", 0)),
            click_offset_y=float(data.get("click_offset_y", 0)),
            delay_after=data.get("delay_after", 0.2),
            conditions=data.get("conditions", []),
            actions=data.get("actions", []),
            is_loop=data.get("is_loop", False),
            loop_array=data.get("loop_array", ""),
            loop_var=data.get("loop_var", ""),
            children=children,
            jump_target_id=data.get("jump_target_id", ""),
            on_fail_enabled=data.get("on_fail_enabled", False),
            on_fail_actions=data.get("on_fail_actions", []),
            # 向后兼容：如果有旧字段，转换为新格式
            on_fail_action_type=data.get("on_fail_action_type", ""),
            on_fail_modify_var_name=data.get("on_fail_modify_var_name", ""),
            on_fail_modify_var_value=data.get("on_fail_modify_var_value", ""),
            on_fail_jump_target_id=data.get("on_fail_jump_target_id", ""),
            on_fail_add_array_items=data.get("on_fail_add_array_items", []),
            modify_var_name=data.get("modify_var_name", ""),
            modify_var_value=data.get("modify_var_value", ""),
            add_to_array_items=data.get("add_to_array_items", []),
            recognition_coord_result_array=data.get("recognition_coord_result_array", ""),
            remove_coord_source_array=data.get("remove_coord_source_array", ""),
            remove_coord_target_value=data.get("remove_coord_target_value", ""),
            remove_coord_mode=data.get("remove_coord_mode", "single"),
            clear_array_name=data.get("clear_array_name", ""),
            recognition_to_logic_csv_path=data.get("recognition_to_logic_csv_path", ""),
            recognition_to_logic_anchor_logical=data.get("recognition_to_logic_anchor_logical", ""),
            recognition_to_logic_anchor_screen=data.get("recognition_to_logic_anchor_screen", ""),
            recognition_to_logic_result_array=data.get("recognition_to_logic_result_array", ""),
            traverse_center_param=data.get("traverse_center_param", ""),
            traverse_target_array=data.get("traverse_target_array", ""),
            traverse_count=data.get("traverse_count", 1000),
            traverse_mode=data.get("traverse_mode", "hex"),
            two_ring_target_coord=data.get("two_ring_target_coord", ""),
            two_ring_result_array=data.get("two_ring_result_array", ""),
            surround_target_coord=data.get("surround_target_coord", data.get("two_ring_target_coord", "")),
            surround_result_array=data.get("surround_result_array", data.get("two_ring_result_array", "")),
            surround_radius=data.get("surround_radius", 2),
            surround_mode=data.get("surround_mode", "hex"),
            path_target_coord=data.get("path_target_coord", ""),
            path_start_array=data.get("path_start_array", ""),
            path_passable_array=data.get("path_passable_array", ""),
            path_result_array=data.get("path_result_array", ""),
            path_mode=data.get("path_mode", "hex"),
        )


# ────────────────── 计划任务 ──────────────────

@dataclass
class PlanTask:
    """计划任务"""
    name: str = "未命名任务"
    description: str = ""
    steps: List[SingleTask] = field(default_factory=list)
    loop_count: int = 1
    parameters: List[TaskParameter] = field(default_factory=list)
    struct_defs: List[StructDefinition] = field(default_factory=list)
    blocked_coords: List[List[int]] = field(default_factory=list)
    created_time: str = ""
    modified_time: str = ""
    id: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:8]
        if not self.created_time:
            self.created_time = time.strftime("%Y-%m-%d %H:%M:%S")
        if not self.modified_time:
            self.modified_time = self.created_time
        self._normalize_parameter_values()

    def get_struct_def(self, name: str) -> Optional[StructDefinition]:
        for struct_def in self.struct_defs:
            if struct_def.name == name:
                return struct_def
        return None

    def _normalize_parameter_values(self):
        for param in self.parameters:
            if param.value is None:
                param.value = build_param_default_value(param.param_type, self.struct_defs)
                continue

            if is_struct_param_type(param.param_type):
                struct_def = self.get_struct_def(get_struct_name_from_type(param.param_type))
                default_value = build_param_default_value(param.param_type, self.struct_defs)
                if not isinstance(param.value, dict):
                    param.value = default_value
                    continue
                normalized = dict(default_value)
                for field_name, default_item in default_value.items():
                    field_def = struct_def.get_field(field_name) if struct_def else None
                    raw_value = param.value.get(field_name, default_item)
                    if field_def and field_def.field_type == "int":
                        try:
                            normalized[field_name] = int(raw_value)
                        except (TypeError, ValueError):
                            normalized[field_name] = 0
                    else:
                        normalized[field_name] = "" if raw_value is None else str(raw_value)
                param.value = normalized

            if is_struct_array_param_type(param.param_type):
                if not isinstance(param.value, list):
                    param.value = []
                    continue
                struct_def = self.get_struct_def(get_struct_name_from_type(param.param_type))
                default_value = build_param_default_value(make_struct_param_type(get_struct_name_from_type(param.param_type)), self.struct_defs)
                normalized_items = []
                for item in param.value:
                    if not isinstance(item, dict):
                        continue
                    normalized = dict(default_value)
                    for field_name, default_item in default_value.items():
                        field_def = struct_def.get_field(field_name) if struct_def else None
                        raw_value = item.get(field_name, default_item)
                        if field_def and field_def.field_type == "int":
                            try:
                                normalized[field_name] = int(raw_value)
                            except (TypeError, ValueError):
                                normalized[field_name] = 0
                        else:
                            normalized[field_name] = "" if raw_value is None else str(raw_value)
                    normalized_items.append(normalized)
                param.value = normalized_items

            if param.param_type == "array":
                param.value = normalize_array_items(param.value, param.array_item_type)

    def get_param(self, name: str) -> Optional[TaskParameter]:
        for p in self.parameters:
            if p.name == name:
                return p
        return None

    def get_param_value(self, name: str, default=None):
        p = self.get_param(name)
        return p.value if p else default

    def set_param_value(self, name: str, value):
        p = self.get_param(name)
        if p:
            p.value = value

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "loop_count": self.loop_count,
            "parameters": [p.to_dict() for p in self.parameters],
            "struct_defs": [s.to_dict() for s in self.struct_defs],
            "blocked_coords": self.blocked_coords,
            "created_time": self.created_time,
            "modified_time": self.modified_time,
        }

    @staticmethod
    def from_dict(data: dict) -> "PlanTask":
        steps = [SingleTask.from_dict(s) for s in data.get("steps", [])]
        struct_defs = [StructDefinition.from_dict(s) for s in data.get("struct_defs", [])]
        raw_params = data.get("parameters", [])
        if isinstance(raw_params, dict):
            params = [TaskParameter(name=k, value=v) for k, v in raw_params.items()]
        else:
            params = [TaskParameter.from_dict(p) for p in raw_params]
        return PlanTask(
            id=data.get("id", ""),
            name=data.get("name", "未命名任务"),
            description=data.get("description", ""),
            steps=steps,
            loop_count=data.get("loop_count", 1),
            parameters=params,
            struct_defs=struct_defs,
            blocked_coords=data.get("blocked_coords", []),
            created_time=data.get("created_time", ""),
            modified_time=data.get("modified_time", ""),
        )

    def update_modified_time(self):
        self.modified_time = time.strftime("%Y-%m-%d %H:%M:%S")

    def get_persist_data(self) -> dict:
        """获取需要存档的参数数据"""
        data = {}
        for p in self.parameters:
            if p.persist:
                data[p.name] = {
                    "param_type": p.param_type,
                    "value": p.value,
                    "array_item_type": p.array_item_type,
                }
        return data

    def load_persist_data(self, data: dict):
        """从存档数据恢复参数值"""
        for p in self.parameters:
            if p.persist and p.name in data:
                saved = data[p.name]
                if saved.get("param_type") == p.param_type and saved.get("array_item_type", "string") == p.array_item_type:
                    p.value = saved["value"]
