"""
计划任务执行引擎
在独立线程中按顺序执行计划任务的每个步骤
"""

import time
import sys
import os
import re
import ast
import math
import threading
from typing import Any, Optional, Callable, List
from enum import Enum
from core.coordinate_transform import (
    build_relative_coordinate_profile_from_csv,
    match_relative_points_to_anchor_logical,
    reanchor_relative_coordinate_profile,
)
from core.recognition import ROI

from task.models import (
    GRID_MODE_LABELS,
    PlanTask,
    REMOVE_COORD_MODE_LABELS,
    SingleTask,
    TaskParameter,
    StepCondition,
    get_default_click_offset_mode,
    normalize_center_tolerance_px,
    normalize_action_type,
    normalize_click_offset_mode,
    coerce_float,
    coerce_array_item_value,
    derive_screen_drag_vector,
    get_struct_name_from_type,
    is_struct_param_type,
    is_struct_array_param_type,
    normalize_grid_mode,
    normalize_highlight_duration_ms,
    normalize_point_position_mode,
    normalize_recognition_roi_mode,
    normalize_remove_coord_mode,
    normalize_drag_vector_mode,
    normalize_recognition_target_mode,
    normalize_array_items,
)
from task.storage import format_persist_json
from utils.number_utils import coerce_unit_ratio


# 当前 hex 网格按 x 列奇偶使用两套邻接规则。
# 例如偶数列的 (994,718) 邻居为:
# (994,717)、(995,717)、(995,718)、(994,719)、(993,718)、(993,717)
HEX_GRID_NEIGHBOR_OFFSETS_BY_X_PARITY = (
    ((0, -1), (1, -1), (1, 0), (0, 1), (-1, 0), (-1, -1)),
    ((0, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0)),
)


class TaskState(str, Enum):
    """任务执行状态"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


class TaskExecutor:
    """
    计划任务执行器

    负责按顺序执行计划任务中的每个步骤：
    1. 截取目标窗口画面
    2. 根据步骤配置进行文字/图像识别
    3. 识别成功 → 执行指定操作 → 进入下一步
    4. 识别失败 → 等待重试间隔 → 重新识别
    """

    def __init__(self):
        self._state = TaskState.IDLE
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # 初始状态为未暂停
        self._step_mode = False  # 单步模式：执行一步后自动暂停

        # 运行时依赖（由外部注入）
        self._hwnd: Optional[int] = None
        self._capture = None           # ScreenCapture
        self._ocr = None               # OCRRecognition
        self._recognition = None       # ImageRecognition
        self._ai_tile_recognition = None  # AITileRecognition
        self._input = None             # InputSimulator
        self._bg_input = None          # BackgroundInputSimulator
        self._window_manager = None    # WindowManager

        # 回调
        self.on_task_start: Optional[Callable[[PlanTask], None]] = None
        self.on_task_finish: Optional[Callable[[PlanTask, bool], None]] = None
        self.on_step_start: Optional[Callable[[int, SingleTask], None]] = None
        self.on_step_success: Optional[Callable[[int, SingleTask], None]] = None
        self.on_step_fail: Optional[Callable[[int, SingleTask, str], None]] = None
        self.on_step_retry: Optional[Callable[[int, SingleTask, int], None]] = None
        self.on_log: Optional[Callable[[str], None]] = None
        self.on_loop_start: Optional[Callable[[int, int], None]] = None
        self.on_blocked_update: Optional[Callable[[PlanTask], None]] = None
        self.on_step_paused: Optional[Callable[[], None]] = None
        self.on_highlight_match: Optional[Callable[[int, int, int, int, int], None]] = None
        self.on_highlight_matches: Optional[Callable[[List[dict], int], None]] = None
        self.on_highlight_point: Optional[Callable[[int, int, int], None]] = None

        # 运行时上下文
        self._current_task: Optional[PlanTask] = None
        self._task_storage = None
        self._runtime_vars: dict = {}      # 运行时变量上下文
        self._jump_target: Optional[str] = None  # 跳转目标步骤 ID
        self._continue_loop = False  # 继续循环标志（跳过本次迭代的剩余子步骤）
        self._break_loop = False     # 跳出循环标志（完全退出当前循环）
        self._run_to_step_id: Optional[str] = None  # 执行到指定步骤后暂停
        self._last_recognition_metrics: dict = {}
        self._last_recognition_region: Optional[dict] = None
        self._last_recognition_regions: List[dict] = []
        self._coordinate_csv_profile_cache: dict = {}

    def setup(self, hwnd: int, capture, ocr, recognition, ai_tile_recognition, input_sim,
              bg_input_class, window_manager, task_storage=None):
        """
        设置运行依赖

        Args:
            hwnd: 目标窗口句柄
            capture: ScreenCapture 实例
            ocr: OCRRecognition 实例
            recognition: ImageRecognition 实例
            input_sim: InputSimulator 实例
            bg_input_class: BackgroundInputSimulator 类（用于创建实例）
            window_manager: WindowManager 实例
            task_storage: TaskStorage 实例（可选，用于 mark_blocked 存档）
        """
        self._hwnd = hwnd
        self._capture = capture
        self._ocr = ocr
        self._recognition = recognition
        self._ai_tile_recognition = ai_tile_recognition
        self._input = input_sim
        self._bg_input_class = bg_input_class
        self._bg_input = None
        self._window_manager = window_manager
        self._task_storage = task_storage
        # 加载等距地图轴方向配置
        self._load_isometric_config()

    @property
    def state(self) -> TaskState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state == TaskState.RUNNING

    @property
    def is_paused(self) -> bool:
        return self._state == TaskState.PAUSED

    def _log(self, message: str):
        """输出日志"""
        if self.on_log:
            self.on_log(message)

    @staticmethod
    def _display_name(step: SingleTask, step_index: int) -> str:
        """获取步骤显示名称，未命名步骤显示为步骤编号"""
        if step.name == "未命名步骤":
            return f"步骤{step_index + 1}"
        return step.name

    @staticmethod
    def _short_target_label(target: Any, limit: int = 32) -> str:
        text = "" if target is None else str(target).strip()
        if not text:
            return ""
        base = os.path.basename(text) or text
        if len(base) > limit:
            return base[:limit - 3] + "..."
        return base

    @staticmethod
    def _recognition_find_all_limit(match_index: int, keep_extra_matches: bool = False) -> int:
        match_index = max(1, int(match_index))
        min_limit = 10 if keep_extra_matches else 6
        buffer = 9 if keep_extra_matches else 4
        return min(30, max(min_limit, match_index + buffer))

    def _deduplicate_matched_entries(self, matched_entries: List[dict]) -> List[dict]:
        if len(matched_entries) <= 1 or not self._recognition:
            return matched_entries

        sorted_entries = sorted(
            matched_entries,
            key=lambda item: item["result"].confidence,
            reverse=True,
        )
        kept_entries = []
        overlap_threshold = getattr(self._recognition, "nms_iou_threshold", 0.45)

        for entry in sorted_entries:
            result = entry.get("result")
            if result is None:
                continue
            duplicate = False
            for kept_entry in kept_entries:
                kept_result = kept_entry.get("result")
                if kept_result is None:
                    continue
                if self._recognition._should_suppress_match(result, kept_result, overlap_threshold):
                    duplicate = True
                    break
            if not duplicate:
                kept_entries.append(entry)

        return kept_entries

    @staticmethod
    def _coerce_recognition_roi_ratio(value, default: float) -> float:
        return coerce_unit_ratio(value, default)

    @staticmethod
    def _intersect_roi(base_roi: Optional[ROI], extra_roi: Optional[ROI]) -> Optional[ROI]:
        if base_roi is None:
            return extra_roi
        if extra_roi is None:
            return base_roi

        left = max(base_roi.x, extra_roi.x)
        top = max(base_roi.y, extra_roi.y)
        right = min(base_roi.x + base_roi.width, extra_roi.x + extra_roi.width)
        bottom = min(base_roi.y + base_roi.height, extra_roi.y + extra_roi.height)
        if right <= left or bottom <= top:
            return None
        return ROI(x=left, y=top, width=right - left, height=bottom - top)

    def _build_recognition_roi(self, step: SingleTask, img) -> Optional[ROI]:
        mode = normalize_recognition_roi_mode(getattr(step, "recognition_roi_mode", "full_window"))
        if mode != "window_percent" or img is None or not hasattr(img, "shape"):
            return None

        img_height, img_width = img.shape[:2]
        if img_width <= 0 or img_height <= 0:
            return None

        roi_x = self._coerce_recognition_roi_ratio(getattr(step, "recognition_roi_x", 0.0), 0.0)
        roi_y = self._coerce_recognition_roi_ratio(getattr(step, "recognition_roi_y", 0.0), 0.0)
        roi_width = max(0.01, self._coerce_recognition_roi_ratio(getattr(step, "recognition_roi_width", 1.0), 1.0))
        roi_height = max(0.01, self._coerce_recognition_roi_ratio(getattr(step, "recognition_roi_height", 1.0), 1.0))

        left = min(img_width - 1, max(0, int(math.floor(img_width * roi_x))))
        top = min(img_height - 1, max(0, int(math.floor(img_height * roi_y))))
        right_ratio = min(1.0, roi_x + roi_width)
        bottom_ratio = min(1.0, roi_y + roi_height)
        right = min(img_width, max(left + 1, int(math.ceil(img_width * right_ratio))))
        bottom = min(img_height, max(top + 1, int(math.ceil(img_height * bottom_ratio))))
        return ROI(x=left, y=top, width=max(1, right - left), height=max(1, bottom - top))

    def _clear_last_recognition_metrics(self):
        self._last_recognition_metrics = {
            "current": None,
            "target": None,
            "matched": False,
            "source": "",
            "note": "",
            "template_confidence": None,
            "color_confidence": None,
            "color_validation_enabled": False,
            "color_validation_applied": False,
            "color_validation_threshold": None,
            "color_note": "",
        }

    def _clear_last_recognition_region(self):
        self._last_recognition_region = None
        self._last_recognition_regions = []
        self._sync_last_recognition_runtime_vars()

    @staticmethod
    def _normalize_recognition_region(region: Optional[dict]) -> Optional[dict]:
        if not isinstance(region, dict):
            return None
        normalized = {
            "x": max(0, int(region.get("x", 0))),
            "y": max(0, int(region.get("y", 0))),
            "width": max(1, int(region.get("width", 1))),
            "height": max(1, int(region.get("height", 1))),
            "recognition_type": region.get("recognition_type", "") or "",
            "label": region.get("label", "") or "",
        }
        for key, value in region.items():
            if key in normalized:
                continue
            if isinstance(value, dict):
                normalized[key] = dict(value)
            elif isinstance(value, (list, tuple)):
                normalized[key] = list(value)
            elif value is None or isinstance(value, (str, int, float, bool)):
                normalized[key] = value
        return normalized

    def _set_last_recognition_region(self, x: int, y: int, width: int, height: int,
                                     recognition_type: str = "", label: str = "",
                                     extra_fields: Optional[dict] = None):
        region = {
            "x": max(0, int(x)),
            "y": max(0, int(y)),
            "width": max(1, int(width)),
            "height": max(1, int(height)),
            "recognition_type": recognition_type or "",
            "label": label or "",
        }
        if extra_fields:
            region.update(dict(extra_fields))
        self._last_recognition_region = region
        self._last_recognition_regions = [dict(region)]
        self._sync_last_recognition_runtime_vars()

    def _set_last_recognition_regions(self, regions: List[dict], selected_index: int = 0):
        normalized = []
        for region in regions or []:
            normalized_region = self._normalize_recognition_region(region)
            if normalized_region:
                normalized.append(normalized_region)

        if not normalized:
            self._last_recognition_region = None
            self._last_recognition_regions = []
            self._sync_last_recognition_runtime_vars()
            return

        selected_index = min(max(0, int(selected_index)), len(normalized) - 1)
        self._last_recognition_regions = [dict(region) for region in normalized]
        self._last_recognition_region = dict(self._last_recognition_regions[selected_index])
        self._sync_last_recognition_runtime_vars()

    def _copy_last_recognition_region(self) -> Optional[dict]:
        if not self._last_recognition_region:
            return None
        return dict(self._last_recognition_region)

    def _copy_last_recognition_regions(self) -> List[dict]:
        return [dict(region) for region in (self._last_recognition_regions or [])]

    def _clear_last_recognition_runtime_vars(self):
        for name in ("last_recognition_result", "last_recognition_results", "ai_tile_result", "ai_tile_results"):
            self._runtime_vars.pop(name, None)
            self._clear_runtime_subfields(name)

    def _sync_last_recognition_runtime_vars(self):
        self._clear_last_recognition_runtime_vars()
        if not self._last_recognition_region:
            return

        current_region = dict(self._last_recognition_region)
        all_regions = [dict(region) for region in (self._last_recognition_regions or [])]
        self._set_runtime_var("last_recognition_result", current_region)
        self._set_runtime_var("last_recognition_results", all_regions)

        if str(current_region.get("recognition_type") or "") == "ai_tile":
            self._set_runtime_var("ai_tile_result", current_region)
            self._set_runtime_var("ai_tile_results", all_regions)

    def _set_last_recognition_metrics(
        self,
        current: Optional[float],
        target: Optional[float],
        matched: bool,
        source: str = "",
        note: str = "",
        template_confidence: Optional[float] = None,
        color_confidence: Optional[float] = None,
        color_validation_enabled: bool = False,
        color_validation_applied: bool = False,
        color_validation_threshold: Optional[float] = None,
        color_note: str = "",
    ):
        self._last_recognition_metrics = {
            "current": float(current) if current is not None else None,
            "target": float(target) if target is not None else None,
            "matched": bool(matched),
            "source": source or "",
            "note": note or "",
            "template_confidence": float(template_confidence) if template_confidence is not None else None,
            "color_confidence": float(color_confidence) if color_confidence is not None else None,
            "color_validation_enabled": bool(color_validation_enabled),
            "color_validation_applied": bool(color_validation_applied),
            "color_validation_threshold": (
                float(color_validation_threshold) if color_validation_threshold is not None else None
            ),
            "color_note": color_note or "",
        }

    def _copy_last_recognition_metrics(self) -> dict:
        return dict(self._last_recognition_metrics or {})

    @staticmethod
    def _format_recognition_metrics(metrics: Optional[dict]) -> str:
        if not metrics:
            return ""

        current = metrics.get("current")
        target = metrics.get("target")
        source = metrics.get("source", "")
        note = metrics.get("note", "")
        template_confidence = metrics.get("template_confidence")
        color_confidence = metrics.get("color_confidence")
        color_validation_enabled = metrics.get("color_validation_enabled", False)
        color_validation_applied = metrics.get("color_validation_applied", False)
        color_validation_threshold = metrics.get("color_validation_threshold")
        color_note = metrics.get("color_note", "")

        if template_confidence is not None and target is not None:
            compare = ">=" if template_confidence >= target else "<"
            text = f"模板置信度 {template_confidence:.2f} {compare} 目标阈值 {target:.2f}"
        elif current is not None and target is not None:
            compare = ">=" if current >= target else "<"
            text = f"当前置信度 {current:.2f} {compare} 目标阈值 {target:.2f}"
        elif target is not None:
            text = f"未获取到可比较置信度，目标阈值 {target:.2f}"
        else:
            text = ""

        if color_validation_enabled:
            if color_validation_applied and color_confidence is not None and color_validation_threshold is not None:
                compare = ">=" if color_confidence >= color_validation_threshold else "<"
                color_text = f"颜色一致性 {color_confidence:.2f} {compare} 校验阈值 {color_validation_threshold:.2f}"
            elif color_confidence is not None:
                color_text = f"颜色一致性 {color_confidence:.2f}"
            else:
                color_text = "颜色一致性 未参与计算"
            text = f"{text}，{color_text}" if text else color_text

        if source:
            text = f"{text}，{source}" if text else source

        if color_note:
            text = f"{text}，{color_note}" if text else color_note

        if note:
            return f"{text}，{note}" if text else note
        return text

    def _format_last_recognition_metrics(self) -> str:
        return self._format_recognition_metrics(self._last_recognition_metrics)

    @staticmethod
    def _format_match_debug_details(debug_info: Optional[dict], threshold: Optional[float] = None) -> str:
        if not debug_info:
            return ""

        parts = []
        match_mode = debug_info.get("match_mode")
        template_confidence = debug_info.get("template_confidence")
        raw_confidence = debug_info.get("raw_confidence")
        if template_confidence is not None:
            score_label = "综合分" if match_mode in ("foreground", "feature") else "模板分"
            if threshold is not None:
                parts.append(f"{score_label}={template_confidence:.2f} (阈值={threshold:.2f})")
            else:
                parts.append(f"{score_label}={template_confidence:.2f}")

        if raw_confidence is not None and match_mode in ("foreground", "feature"):
            parts.append(f"原始模板分={raw_confidence:.2f}")

        foreground_confidence = debug_info.get("foreground_confidence")
        if foreground_confidence is not None:
            parts.append(f"前景分={foreground_confidence:.2f}")

        feature_confidence = debug_info.get("feature_confidence")
        if feature_confidence is not None:
            parts.append(f"特征分={feature_confidence:.2f}")

        edge_confidence = debug_info.get("edge_confidence")
        if edge_confidence is not None:
            parts.append(f"边缘分={edge_confidence:.2f}")

        match_note = debug_info.get("match_note", "")
        if match_note:
            parts.append(match_note)

        if debug_info.get("color_validation_enabled"):
            color_confidence = debug_info.get("color_confidence")
            color_threshold = debug_info.get("color_validation_threshold")
            if color_confidence is not None and color_threshold is not None:
                parts.append(f"颜色分={color_confidence:.2f} (阈值={color_threshold:.2f})")
            elif color_confidence is not None:
                parts.append(f"颜色分={color_confidence:.2f}")

        color_note = debug_info.get("color_note", "")
        if color_note:
            parts.append(color_note)

        return "，".join(parts)

    def start(self, task: PlanTask):
        """
        开始执行计划任务

        Args:
            task: 要执行的计划任务
        """
        if self._state == TaskState.RUNNING:
            self._log("任务正在执行中，请先停止当前任务")
            return

        if not self._hwnd:
            self._log("错误：未设置目标窗口")
            return

        if not task.steps:
            self._log("错误：任务没有步骤")
            return

        self._stop_event.clear()
        self._pause_event.set()
        self._state = TaskState.RUNNING

        self._thread = threading.Thread(
            target=self._run_task, args=(task,), daemon=True
        )
        self._thread.start()

    def start_step_mode(self, task: PlanTask):
        """以单步模式开始执行（执行第一步后自动暂停）"""
        self._step_mode = True
        self.start(task)

    def stop(self):
        """停止执行"""
        if self._state in (TaskState.RUNNING, TaskState.PAUSED):
            self._stop_event.set()
            self._pause_event.set()  # 唤醒暂停中的线程
            self._step_mode = False
            self._run_to_step_id = None
            self._state = TaskState.STOPPED
            self._log("正在停止任务...")

    def pause(self):
        """暂停执行"""
        if self._state == TaskState.RUNNING:
            self._pause_event.clear()
            self._state = TaskState.PAUSED
            self._log("任务已暂停")

    def resume(self):
        """恢复执行"""
        if self._state == TaskState.PAUSED:
            self._step_mode = False
            self._run_to_step_id = None
            self._pause_event.set()
            self._state = TaskState.RUNNING
            self._log("任务已恢复")

    def step_once(self):
        """单步执行：执行一个步骤后自动暂停"""
        if self._state == TaskState.PAUSED:
            self._step_mode = True
            self._pause_event.set()
            self._state = TaskState.RUNNING
            self._log("单步执行...")

    def run_to_step(self, step_id: str):
        """执行到指定步骤后暂停"""
        self._run_to_step_id = step_id
        if self._state == TaskState.PAUSED:
            self._pause_event.set()
            self._state = TaskState.RUNNING
            self._log(f"继续执行到指定步骤...")

    def start_run_to_step(self, task: PlanTask, step_id: str):
        """从头开始执行到指定步骤后暂停"""
        self._run_to_step_id = step_id
        self.start(task)

    def _check_stopped(self) -> bool:
        """检查是否被停止"""
        return self._stop_event.is_set()

    def _wait_if_paused(self):
        """如果暂停则等待"""
        self._pause_event.wait()

    def _run_task(self, task: PlanTask):
        """在线程中执行任务"""
        try:
            self._current_task = task
            self._jump_target = None

            # 加载存档参数
            self._load_persist()
            # 构建运行时变量
            self._build_runtime_vars()

            if self.on_task_start:
                self.on_task_start(task)

            self._log(f"开始执行任务: {task.name}")

            if task.parameters:
                self._log(f"任务参数: {len(task.parameters)} 个")
            if task.blocked_coords:
                self._log(f"已封锁坐标: {len(task.blocked_coords)} 个")

            loop_count = task.loop_count
            current_loop = 0

            while True:
                current_loop += 1

                if loop_count > 0 and current_loop > loop_count:
                    break

                if self._check_stopped():
                    break

                loop_info = f"第 {current_loop} 轮"
                if loop_count > 0:
                    loop_info += f" / 共 {loop_count} 轮"
                else:
                    loop_info += " (无限循环)"
                self._log(f"--- {loop_info} ---")

                if self.on_loop_start:
                    self.on_loop_start(current_loop, loop_count)

                # 依次执行每个步骤（支持跳转）
                all_success = True
                step_index = 0
                while step_index < len(task.steps):
                    if self._check_stopped():
                        all_success = False
                        break

                    self._wait_if_paused()
                    if self._check_stopped():
                        all_success = False
                        break

                    step = task.steps[step_index]
                    self._jump_target = None

                    if step.is_loop:
                        success = self._execute_loop_step(step_index, step)
                    else:
                        success = self._execute_step(step_index, step)

                    if not success:
                        all_success = False
                        sn = self._display_name(step, step_index)
                        self._log(f"步骤 [{sn}] 执行失败，任务终止")
                        break

                    # 单步模式：执行完一步后自动暂停
                    if self._step_mode:
                        self._step_mode = False
                        self._pause_event.clear()
                        self._state = TaskState.PAUSED
                        self._log("单步执行完成，已暂停")
                        if self.on_step_paused:
                            self.on_step_paused()

                    # 执行到指定步骤：检查是否到达目标
                    if self._run_to_step_id and step.id == self._run_to_step_id:
                        self._run_to_step_id = None
                        self._pause_event.clear()
                        self._state = TaskState.PAUSED
                        sn2 = self._display_name(step, step_index)
                        self._log(f"已执行到目标步骤 [{sn2}]，已暂停")
                        if self.on_step_paused:
                            self.on_step_paused()

                    # 跳转处理
                    if self._jump_target:
                        target_idx = self._find_step_index(self._jump_target, task.steps)
                        if target_idx is not None:
                            self._log(f"跳转到步骤 [{self._display_name(task.steps[target_idx], target_idx)}]")
                            step_index = target_idx
                            self._jump_target = None
                            continue
                        else:
                            self._log(f"跳转目标 {self._jump_target} 未找到")

                    step_index += 1

                if not all_success and self._check_stopped():
                    break
                if not all_success:
                    break

            # 保存存档参数
            self._save_persist()

            finished_normally = not self._check_stopped()
            self._state = TaskState.IDLE
            self._log(f"任务 [{task.name}] {'执行完成' if finished_normally else '已停止'}")

            if self.on_task_finish:
                self.on_task_finish(task, finished_normally)

        except Exception as e:
            self._save_persist()
            self._state = TaskState.IDLE
            self._log(f"任务执行异常: {e}")
            if self.on_task_finish:
                self.on_task_finish(task, False)

    def _find_step_index(self, step_id: str, steps: List[SingleTask]) -> Optional[int]:
        """根据步骤 ID 查找索引"""
        for i, s in enumerate(steps):
            if s.id == step_id:
                return i
        return None

    def _clear_runtime_subfields(self, name: str):
        prefix = f"{name}."
        for key in [item for item in self._runtime_vars.keys() if item.startswith(prefix)]:
            self._runtime_vars.pop(key, None)

    def _set_runtime_subfields(self, name: str, value):
        if isinstance(value, dict):
            for field_name, field_value in value.items():
                child_name = f"{name}.{field_name}"
                self._runtime_vars[child_name] = field_value
                self._set_runtime_subfields(child_name, field_value)
            return

        if (
            isinstance(value, (list, tuple))
            and len(value) >= 2
            and not any(isinstance(item, (dict, list, tuple, set)) for item in value[:2])
        ):
            self._runtime_vars[f"{name}.x"] = value[0]
            self._runtime_vars[f"{name}.y"] = value[1]

    def _set_runtime_var(self, name: str, value):
        self._runtime_vars[name] = value
        self._clear_runtime_subfields(name)
        self._set_runtime_subfields(name, value)

    @staticmethod
    def _parse_literal_value(raw_value):
        if not isinstance(raw_value, str):
            return raw_value
        text = raw_value.strip()
        if not text:
            return ""
        try:
            return ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return raw_value

    def _coerce_param_value(self, param: Optional[TaskParameter], raw_value):
        if not param:
            return raw_value

        if param.param_type == "coordinate":
            parsed = self._parse_literal_value(raw_value)
            if isinstance(parsed, dict):
                try:
                    return {"x": int(parsed.get("x", 0)), "y": int(parsed.get("y", 0))}
                except (TypeError, ValueError):
                    return raw_value
            if isinstance(parsed, (list, tuple)) and len(parsed) >= 2:
                try:
                    return {"x": int(parsed[0]), "y": int(parsed[1])}
                except (TypeError, ValueError):
                    return raw_value
            if isinstance(raw_value, str) and "," in raw_value:
                parts = [part.strip() for part in raw_value.split(",", 1)]
                try:
                    return {"x": int(parts[0]), "y": int(parts[1])}
                except (TypeError, ValueError):
                    return raw_value

        if param.param_type == "array":
            parsed = self._parse_literal_value(raw_value)
            if isinstance(parsed, list):
                return normalize_array_items(parsed, param.array_item_type)

        if is_struct_param_type(param.param_type):
            parsed = self._parse_literal_value(raw_value)
            if isinstance(parsed, dict):
                if self._current_task:
                    struct_def = self._current_task.get_struct_def(get_struct_name_from_type(param.param_type))
                    if struct_def:
                        normalized = struct_def.build_default_value()
                        for field_def in struct_def.fields:
                            if field_def.name in parsed:
                                if field_def.field_type == "int":
                                    try:
                                        normalized[field_def.name] = int(parsed[field_def.name])
                                    except (TypeError, ValueError):
                                        normalized[field_def.name] = 0
                                else:
                                    normalized[field_def.name] = str(parsed[field_def.name])
                        return normalized
                return parsed

        if is_struct_array_param_type(param.param_type):
            parsed = self._parse_literal_value(raw_value)
            if isinstance(parsed, list):
                if self._current_task:
                    struct_def = self._current_task.get_struct_def(get_struct_name_from_type(param.param_type))
                    if struct_def:
                        normalized_list = []
                        for item in parsed:
                            if not isinstance(item, dict):
                                continue
                            normalized = struct_def.build_default_value()
                            for field_def in struct_def.fields:
                                if field_def.name in item:
                                    if field_def.field_type == "int":
                                        try:
                                            normalized[field_def.name] = int(item[field_def.name])
                                        except (TypeError, ValueError):
                                            normalized[field_def.name] = 0
                                    else:
                                        normalized[field_def.name] = str(item[field_def.name])
                            normalized_list.append(normalized)
                        return normalized_list
                return parsed

        return raw_value

    def _resolve_named_or_literal_value(self, raw_value):
        if not isinstance(raw_value, str):
            return raw_value

        text = raw_value.strip()
        if not text:
            return None

        direct_reference = re.fullmatch(r'\{([\w.]+)\}', text)
        if direct_reference:
            value = self._get_reference_value(direct_reference.group(1))
            if value is not None:
                return value

        direct_value = self._get_reference_value(text)
        if direct_value is not None:
            return direct_value

        resolved = self._resolve_params(text)
        return self._parse_literal_value(resolved)

    def _coerce_coord_tuple(self, raw_value):
        if isinstance(raw_value, str):
            parsed = self._parse_literal_value(raw_value)
            if parsed is not raw_value:
                return self._coerce_coord_tuple(parsed)
            if "," in raw_value:
                parts = [part.strip() for part in raw_value.split(",", 1)]
                try:
                    return int(parts[0]), int(parts[1])
                except (TypeError, ValueError):
                    return None
            return None

        if isinstance(raw_value, dict):
            try:
                return int(raw_value.get("x", 0)), int(raw_value.get("y", 0))
            except (TypeError, ValueError):
                return None

        if isinstance(raw_value, (list, tuple)) and len(raw_value) >= 2:
            try:
                return int(raw_value[0]), int(raw_value[1])
            except (TypeError, ValueError):
                return None

        return None

    def _get_coordinate_value(self, name: str):
        value = self._resolve_named_or_literal_value(name)
        return self._coerce_coord_tuple(value)

    @staticmethod
    def _coerce_number_pair(raw_value, integer: bool = False):
        if isinstance(raw_value, str):
            parsed = TaskExecutor._parse_literal_value(raw_value)
            if parsed is not raw_value:
                return TaskExecutor._coerce_number_pair(parsed, integer=integer)
            if "," in raw_value:
                parts = [part.strip() for part in raw_value.split(",", 1)]
                try:
                    first = float(parts[0])
                    second = float(parts[1])
                except (TypeError, ValueError):
                    return None
                if integer:
                    return int(round(first)), int(round(second))
                return first, second
            return None

        if isinstance(raw_value, dict):
            try:
                first = float(raw_value.get("x", 0))
                second = float(raw_value.get("y", 0))
            except (TypeError, ValueError):
                return None
            if integer:
                return int(round(first)), int(round(second))
            return first, second

        if isinstance(raw_value, (list, tuple)) and len(raw_value) >= 2:
            try:
                first = float(raw_value[0])
                second = float(raw_value[1])
            except (TypeError, ValueError):
                return None
            if integer:
                return int(round(first)), int(round(second))
            return first, second

        return None

    def _get_number_pair_value(self, name: str, integer: bool = False):
        if not name:
            return None
        value = self._resolve_named_or_literal_value(name)
        if value is None and isinstance(name, str):
            value = self._resolve_params(name)
        return self._coerce_number_pair(value, integer=integer)

    def _get_coord_array_value(self, name: str) -> list:
        value = self._resolve_named_or_literal_value(name)
        if value is None and isinstance(name, str):
            value = self._get_array_value(name.strip())

        if not isinstance(value, list):
            return []

        result = []
        for item in value:
            coord = self._coerce_coord_tuple(item)
            if coord is not None:
                result.append([coord[0], coord[1]])
        return result

    def _coerce_coord_list(self, raw_value) -> list:
        coord = self._coerce_coord_tuple(raw_value)
        if coord is not None:
            return [[coord[0], coord[1]]]

        if not isinstance(raw_value, list):
            return []

        result = []
        for item in raw_value:
            coord = self._coerce_coord_tuple(item)
            if coord is not None:
                result.append([coord[0], coord[1]])
        return result

    def _set_coord_array_value(self, name: str, coords: list, deduplicate: bool = True) -> bool:
        normalized = []
        seen = set()
        for item in coords or []:
            coord = self._coerce_coord_tuple(item)
            if coord is None:
                continue
            if deduplicate and coord in seen:
                continue
            normalized.append([coord[0], coord[1]])
            if deduplicate:
                seen.add(coord)

        param = self._current_task.get_param(name) if self._current_task else None
        if param and param.param_type != "coord_array":
            return False

        if param:
            param.value = normalized
        self._set_runtime_var(name, normalized)
        if param:
            self._save_persist()
        return True

    def _get_last_recognition_centers(self) -> List[tuple[int, int]]:
        regions = self._copy_last_recognition_regions()
        if not regions:
            region = self._copy_last_recognition_region()
            if region:
                regions = [region]

        centers: List[tuple[int, int]] = []
        seen = set()
        for region in regions:
            width = max(1, int(region.get("width", 1) or 1))
            height = max(1, int(region.get("height", 1) or 1))
            center_x = int(round(int(region.get("x", 0) or 0) + width / 2.0))
            center_y = int(round(int(region.get("y", 0) or 0) + height / 2.0))
            center = (center_x, center_y)
            if center in seen:
                continue
            seen.add(center)
            centers.append(center)
        return centers

    def _load_coordinate_csv_profile(self, csv_path: str):
        resolved_path = os.path.normpath(self._resolve_template_path(csv_path))
        try:
            modified_at = os.path.getmtime(resolved_path)
        except OSError:
            modified_at = None

        cache_key = os.path.normcase(os.path.abspath(resolved_path))
        cached = self._coordinate_csv_profile_cache.get(cache_key)
        if cached and cached[0] == modified_at:
            return cached[1], resolved_path

        profile = build_relative_coordinate_profile_from_csv(resolved_path)
        self._coordinate_csv_profile_cache[cache_key] = (modified_at, profile)
        return profile, resolved_path

    @staticmethod
    def _iter_hex_neighbors(coord):
        x, y = coord
        for dx, dy in HEX_GRID_NEIGHBOR_OFFSETS_BY_X_PARITY[x & 1]:
            yield x + dx, y + dy

    @staticmethod
    def _grid_mode_name(mode: str) -> str:
        mode = normalize_grid_mode(mode)
        return GRID_MODE_LABELS.get(mode, mode)

    @staticmethod
    def _iter_grid_neighbors(coord, mode: str):
        mode = normalize_grid_mode(mode)
        if mode == "hex":
            yield from TaskExecutor._iter_hex_neighbors(coord)

    def _expand_grid_bfs(
        self,
        center: tuple[int, int],
        mode: str,
        *,
        max_depth: Optional[int] = None,
        max_count: Optional[int] = None,
        include_center: bool = True,
    ) -> List[List[int]]:
        if max_count is not None and max_count <= 0:
            return []

        mode = normalize_grid_mode(mode)
        visited = {center}
        queue = [(center, 0)]
        result = [[center[0], center[1]]] if include_center else []
        qi = 0

        while qi < len(queue):
            current, depth = queue[qi]
            qi += 1
            if max_depth is not None and depth >= max_depth:
                continue

            next_depth = depth + 1
            for neighbor in self._iter_grid_neighbors(current, mode):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                queue.append((neighbor, next_depth))
                result.append([neighbor[0], neighbor[1]])
                if max_count is not None and len(result) >= max_count:
                    return result[:max_count]

        return result[:max_count] if max_count is not None else result

    def _append_value_to_array(self, arr_name: str, raw_value):
        arr = self._get_array_value(arr_name)
        appended_value = raw_value
        error_message = ""

        if self._current_task:
            p = self._current_task.get_param(arr_name)
            if p and p.param_type == "coord_array":
                coord = self._coerce_coord_tuple(raw_value)
                if coord is None:
                    return arr, raw_value, f"坐标格式错误: '{raw_value}'"
                appended_value = [coord[0], coord[1]]
                if appended_value not in arr:
                    arr.append(appended_value)
            elif p and is_struct_array_param_type(p.param_type):
                parsed_value = self._parse_literal_value(raw_value)
                if not isinstance(parsed_value, dict):
                    return arr, raw_value, f"结构体格式错误: '{raw_value}'"
                appended_value = parsed_value
                if appended_value not in arr:
                    arr.append(appended_value)
            elif p and p.param_type == "array":
                try:
                    appended_value = coerce_array_item_value(
                        p.array_item_type,
                        self._parse_literal_value(raw_value),
                    )
                except (TypeError, ValueError):
                    if p.array_item_type == "int":
                        return arr, raw_value, f"整数格式错误: '{raw_value}'"
                    return arr, raw_value, f"数组格式错误: '{raw_value}'"
                if appended_value not in arr:
                    arr.append(appended_value)
            else:
                if raw_value not in arr:
                    arr.append(raw_value)

            if p:
                p.value = arr
        else:
            if raw_value not in arr:
                arr.append(raw_value)

        self._set_runtime_var(arr_name, arr)
        return arr, appended_value, error_message

    def _expand_array_values_for_target(self, arr_name: str, raw_value):
        param = self._current_task.get_param(arr_name) if self._current_task else None

        if param and param.param_type == "coord_array":
            coords = self._coerce_coord_list(raw_value)
            if coords:
                return coords
            return [raw_value]

        if param and (param.param_type == "array" or is_struct_array_param_type(param.param_type)):
            return list(raw_value) if isinstance(raw_value, list) else [raw_value]

        if isinstance(raw_value, list):
            coord = self._coerce_coord_tuple(raw_value)
            if coord is not None and not any(isinstance(item, (list, tuple, dict)) for item in raw_value[:2]):
                return [raw_value]
            return list(raw_value)

        return [raw_value]

    def _append_values_to_array(self, arr_name: str, raw_value):
        values = self._expand_array_values_for_target(arr_name, raw_value)
        arr = self._get_array_value(arr_name)
        before_count = len(arr)
        added_values = []
        error_messages = []

        for value in values:
            arr, appended_value, error_message = self._append_value_to_array(arr_name, value)
            if error_message:
                error_messages.append(error_message)
                continue
            added_values.append(appended_value)

        return arr, added_values, error_messages, before_count, len(values)

    def _build_legacy_step_action(self, step: SingleTask) -> Optional[dict]:
        action_type = normalize_action_type(step.action_type or "none")
        if action_type == "none":
            return None

        action = {
            "type": action_type,
            "delay": 0.0,
        }
        if self._action_uses_click_offset(action_type):
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
        if action_type == "highlight_match":
            action["duration_ms"] = normalize_highlight_duration_ms(getattr(step, "highlight_duration_ms", 1200))
        if action_type == "highlight_point":
            action["duration_ms"] = normalize_highlight_duration_ms(getattr(step, "highlight_duration_ms", 1200))
        if self._action_uses_point_position_mode(action_type):
            action["point_position_mode"] = normalize_point_position_mode(
                getattr(step, "point_position_mode", "recognition")
            )
            action["point_x"] = coerce_float(getattr(step, "point_x", 0.5), 0.5)
            action["point_y"] = coerce_float(getattr(step, "point_y", 0.5), 0.5)
            action["point_coord_text"] = str(getattr(step, "point_coord_text", "") or "").strip()
        if action_type in ("drag_map", "drag_match_to_center", "hold_left_button"):
            action["drag_duration"] = step.drag_duration
        if action_type == "drag_match_to_center":
            action["center_tolerance_px"] = normalize_center_tolerance_px(
                getattr(step, "center_tolerance_px", 1)
            )
        if action_type == "drag_map":
            action["drag_coordinate_mode"] = getattr(step, "drag_coordinate_mode", "game_logic") or "game_logic"
            action["drag_start_mode"] = getattr(step, "drag_start_mode", "recognition") or "recognition"
            action["drag_start_x"] = getattr(step, "drag_start_x", 0.5)
            action["drag_start_y"] = getattr(step, "drag_start_y", 0.5)
            action["drag_direction_x"] = step.drag_direction_x
            action["drag_direction_y"] = step.drag_direction_y
            action["drag_distance"] = step.drag_distance
            action["drag_vector_mode"] = normalize_drag_vector_mode(getattr(step, "drag_vector_mode", "pixel"))
            action["drag_vector_x"] = coerce_float(getattr(step, "drag_vector_x", 0.0), 0.0)
            action["drag_vector_y"] = coerce_float(getattr(step, "drag_vector_y", 0.0), 0.0)
        if action_type == "modify_variable":
            action["var_name"] = step.modify_var_name
            action["var_value"] = step.modify_var_value
        if action_type == "add_to_array":
            action["items"] = list(step.add_to_array_items)
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
            action["radius"] = max(0, int(getattr(step, "surround_radius", 2) or 0))
            action["mode"] = normalize_grid_mode(getattr(step, "surround_mode", "hex"))
        if action_type == "find_road_path":
            action["target_coord"] = step.path_target_coord
            action["start_array"] = step.path_start_array
            action["passable_array"] = step.path_passable_array
            action["result_array"] = step.path_result_array
            action["mode"] = normalize_grid_mode(getattr(step, "path_mode", "hex"))
        return action

    @staticmethod
    def _normalize_action_dict(action_data: Optional[dict]) -> dict:
        normalized = dict(action_data or {})
        action_type = normalize_action_type(normalized.get("type", "none"))
        normalized["type"] = action_type
        point_mode = "recognition"
        if TaskExecutor._action_uses_point_position_mode(action_type):
            point_mode = normalize_point_position_mode(normalized.get("point_position_mode", "recognition"))
            normalized["point_position_mode"] = point_mode
            normalized["point_coord_text"] = str(normalized.get("point_coord_text", "") or "").strip()
            default_value = 0.5 if point_mode == "screen_percent" else 0.0
            point_x = coerce_float(normalized.get("point_x", default_value), default_value)
            point_y = coerce_float(normalized.get("point_y", default_value), default_value)
            if point_mode == "screen_percent":
                point_x = max(0.0, min(1.0, point_x))
                point_y = max(0.0, min(1.0, point_y))
            normalized["point_x"] = point_x
            normalized["point_y"] = point_y
        if TaskExecutor._action_uses_click_offset(action_type):
            normalized["click_offset_mode"] = normalize_click_offset_mode(
                normalized.get("click_offset_mode", ""),
                point_mode,
            )
            normalized["click_offset_x"] = coerce_float(normalized.get("click_offset_x", 0.0), 0.0)
            normalized["click_offset_y"] = coerce_float(normalized.get("click_offset_y", 0.0), 0.0)
        if action_type == "traverse_grid":
            normalized["mode"] = normalize_grid_mode(normalized.get("mode", "hex"))
        elif action_type == "remove_target_coords":
            normalized["remove_mode"] = normalize_remove_coord_mode(normalized.get("remove_mode", "single"))
        elif action_type == "get_surrounding_coords":
            normalized["mode"] = normalize_grid_mode(normalized.get("mode", "hex"))
            try:
                radius = int(normalized.get("radius", 2) or 0)
            except (TypeError, ValueError):
                radius = 2
            normalized["radius"] = max(0, radius)
        elif action_type == "find_road_path":
            normalized["mode"] = normalize_grid_mode(normalized.get("mode", "hex"))
        return normalized

    def _get_step_actions(self, step: SingleTask) -> List[dict]:
        actions = [self._normalize_action_dict(item) for item in step.actions if isinstance(item, dict) and item.get("type")]
        if actions:
            return actions
        legacy = self._build_legacy_step_action(step)
        return [legacy] if legacy else []

    @staticmethod
    def _action_uses_click_offset(action_type: str) -> bool:
        return action_type in (
            "click",
            "double_click",
            "right_click",
            "input_text",
            "highlight_point",
            "drag_map",
            "drag_match_to_center",
            "hold_left_button",
        )

    @staticmethod
    def _action_uses_point_position_mode(action_type: str) -> bool:
        return action_type in (
            "click",
            "double_click",
            "right_click",
            "input_text",
            "highlight_point",
            "hold_left_button",
        )

    def _coerce_field_value(self, param: TaskParameter, field_name: str, raw_value):
        parsed = self._parse_literal_value(raw_value)
        if param.param_type == "coordinate" and field_name in ("x", "y"):
            try:
                return int(parsed)
            except (TypeError, ValueError):
                return 0

        if is_struct_param_type(param.param_type) and self._current_task:
            struct_def = self._current_task.get_struct_def(get_struct_name_from_type(param.param_type))
            field_def = struct_def.get_field(field_name) if struct_def else None
            if field_def and field_def.field_type == "int":
                try:
                    return int(parsed)
                except (TypeError, ValueError):
                    return 0
            if field_def:
                return "" if parsed is None else str(parsed)

        if isinstance(param.value, dict):
            old_value = param.value.get(field_name)
            if isinstance(old_value, int):
                try:
                    return int(parsed)
                except (TypeError, ValueError):
                    return 0
        return parsed

    def _assign_variable_value(self, var_name: str, raw_value):
        if not var_name:
            return raw_value

        if self._current_task and "." in var_name:
            base_name, field_name = var_name.split(".", 1)
            param = self._current_task.get_param(base_name)
            if param and isinstance(param.value, dict):
                coerced = self._coerce_field_value(param, field_name, raw_value)
                updated = dict(param.value)
                updated[field_name] = coerced
                param.value = updated
                self._set_runtime_var(base_name, updated)
                return coerced

        if self._current_task:
            param = self._current_task.get_param(var_name)
            if param:
                coerced = self._coerce_param_value(param, raw_value)
                param.value = coerced
                self._set_runtime_var(var_name, coerced)
                return coerced

        self._set_runtime_var(var_name, raw_value)
        return raw_value

    def _get_reference_value(self, key: str):
        if not key:
            return None

        if key in self._runtime_vars:
            return self._runtime_vars[key]

        def _resolve_nested(value, parts):
            current = value
            for part in parts:
                if isinstance(current, dict):
                    if part not in current:
                        return None
                    current = current.get(part)
                    continue
                if isinstance(current, (list, tuple)) and part.isdigit():
                    index = int(part)
                    if index < 0 or index >= len(current):
                        return None
                    current = current[index]
                    continue
                return None
            return current

        if "." in key:
            parts = key.split(".")
            base = parts[0]
            remainder = parts[1:]
            if base in self._runtime_vars:
                resolved = _resolve_nested(self._runtime_vars[base], remainder)
                if resolved is not None:
                    return resolved
            if self._current_task:
                param = self._current_task.get_param(base)
                if param:
                    resolved = _resolve_nested(param.value, remainder)
                    if resolved is not None:
                        return resolved
                if param and param.param_type == "image" and len(remainder) == 1 and remainder[0] == "path":
                    return param.value
            return None

        if self._current_task:
            param = self._current_task.get_param(key)
            if param:
                return param.value
        return None

    def _resolve_params(self, text: str) -> str:
        """替换文本中的 {param} 占位符为任务参数值
        支持: {name} 文本参数, {name.x}/{name.y} 坐标子字段, 运行时变量"""
        if not text:
            return text
        def _replacer(m):
            key = m.group(1)
            value = self._get_reference_value(key)
            if value is None:
                return m.group(0)
            return str(value)
        return re.sub(r'\{([\w.]+)\}', _replacer, text)

    def _resolve_recognition_target(self, step: SingleTask):
        raw_target = step.recognition_target
        target_mode = normalize_recognition_target_mode(
            getattr(step, "recognition_target_mode", "single")
        )
        if not raw_target:
            return raw_target, target_mode

        direct_reference = re.fullmatch(r'\{([\w.]+)\}', raw_target.strip())
        if direct_reference:
            value = self._get_reference_value(direct_reference.group(1))
            if isinstance(value, list):
                if target_mode == "single":
                    target_mode = "array_any"
                return list(value), target_mode
            if value is not None:
                return value, target_mode

        resolved_target = self._resolve_params(raw_target)
        if target_mode in ("array_any", "array_all"):
            parsed = self._parse_literal_value(resolved_target)
            if isinstance(parsed, list):
                return parsed, target_mode
            if resolved_target:
                return [resolved_target], target_mode
            return [], target_mode
        return resolved_target, target_mode

    @staticmethod
    def _format_recognition_target_log(target: Any, target_mode: str = "single") -> str:
        if isinstance(target, list):
            preview = ", ".join(str(item) for item in target[:3])
            if len(target) > 3:
                preview = f"{preview}, ..."
            label = "数组任一" if target_mode == "array_any" else "数组全部"
            return f"{label}[{preview}]" if preview else f"{label}[]"
        return "" if target is None else str(target)

    @staticmethod
    def _format_coord_text(coord: Any) -> str:
        if isinstance(coord, (list, tuple)) and len(coord) >= 2:
            return f"({coord[0]},{coord[1]})"
        return str(coord)

    @staticmethod
    def _format_relative_point(relative_x: float, relative_y: float, decimals: int = 6) -> str:
        return f"({float(relative_x):.{decimals}f},{float(relative_y):.{decimals}f})"

    @staticmethod
    def _client_to_relative_point(
        client_x: float,
        client_y: float,
        client_size: tuple[int, int],
    ) -> tuple[float, float]:
        width = max(1.0, float(client_size[0]))
        height = max(1.0, float(client_size[1]))
        return float(client_x) / width, float(client_y) / height

    def _format_client_relative_point(
        self,
        client_x: float,
        client_y: float,
        client_size: Optional[tuple[int, int]] = None,
        decimals: int = 6,
    ) -> str:
        size = client_size
        if size is None:
            client_bounds = self._get_target_window_client_bounds()
            if client_bounds:
                size = (client_bounds[2], client_bounds[3])
        if not size:
            return f"({int(round(float(client_x)))},{int(round(float(client_y)))})"
        relative_x, relative_y = self._client_to_relative_point(client_x, client_y, size)
        return self._format_relative_point(relative_x, relative_y, decimals=decimals)

    def _format_coord_path_log(self, path_points: List[Any], target_coord: Optional[Any] = None) -> str:
        lines = ["路径明细（按顺序）:"]
        for idx, coord in enumerate(path_points, start=1):
            prefix = "起点 " if idx == 1 else ""
            lines.append(f"{idx}. {prefix}{self._format_coord_text(coord)}")
        if target_coord is not None:
            lines.append(f"{len(path_points) + 1}. 目标 {self._format_coord_text(target_coord)}")
        return "\n".join(lines)

    def _build_runtime_vars(self):
        """从任务参数构建运行时变量快照"""
        self._runtime_vars = {}
        if not self._current_task:
            return
        for p in self._current_task.parameters:
            self._set_runtime_var(p.name, p.value)

    # ── 参数存档 ──

    def _load_persist(self):
        """加载存档参数"""
        if not self._current_task or not self._task_storage:
            return
        import json
        persist_path = self._get_persist_path()
        if not os.path.exists(persist_path):
            return
        try:
            with open(persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._current_task.load_persist_data(data)
            self._log(f"已加载存档参数: {list(data.keys())}")
        except Exception as e:
            self._log(f"加载存档参数失败: {e}")

    def _save_persist(self):
        """保存需要存档的参数"""
        if not self._current_task:
            return
        data = self._current_task.get_persist_data()
        if not data:
            return
        import json
        persist_path = self._get_persist_path()
        try:
            os.makedirs(os.path.dirname(persist_path), exist_ok=True)
            with open(persist_path, "w", encoding="utf-8") as f:
                f.write(format_persist_json(data, indent=2))
        except Exception as e:
            self._log(f"保存存档参数失败: {e}")

    def _get_persist_path(self) -> str:
        if getattr(sys, 'frozen', False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "tasks", f"persist_{self._current_task.id}.json")

    # ── 条件判断 ──

    def _evaluate_conditions(self, conditions: List[dict], img=None) -> bool:
        """评估步骤条件列表，返回是否满足"""
        if not conditions:
            return True
        results = []
        logics = []
        for cond_dict in conditions:
            c = StepCondition.from_dict(cond_dict)
            result = self._evaluate_single_condition(c, img)
            results.append(result)
            logics.append(c.logic_next)
        # 组合逻辑: 按 and/or 从左到右求值
        final = results[0]
        for i in range(len(logics) - 1):
            logic = logics[i]
            next_val = results[i + 1]
            if logic == "and":
                final = final and next_val
            elif logic == "or":
                final = final or next_val
            else:
                final = final and next_val
        return final

    def _evaluate_single_condition(self, c: StepCondition, img=None) -> bool:
        """评估单个条件"""
        try:
            if c.condition_type == "variable":
                left = self._resolve_params(c.left_operand)
                right = self._resolve_params(c.right_operand)
                if getattr(c, "left_use_length", False):
                    left = self._get_operand_length(left)
                if getattr(c, "right_use_length", False):
                    right = self._get_operand_length(right)
                if left is None or right is None:
                    return False
                if getattr(c, "left_use_length", False) or getattr(c, "right_use_length", False):
                    return self._compare_numeric(left, c.operator, right)
                return self._compare(left, c.operator, right)
            elif c.condition_type == "image":
                target = self._resolve_params(c.rec_target)
                if img is None:
                    img = self._capture_window(True)
                if img is None:
                    return c.negate
                resolved = self._resolve_template_path(target)
                if not self._recognition or not os.path.isfile(resolved):
                    return c.negate
                result = self._recognition.find_template(
                    img,
                    resolved,
                    threshold=c.threshold,
                    validate_color=c.validate_color_consistency,
                )
                found = result is not None
                return (not found) if c.negate else found
            elif c.condition_type == "text":
                target = self._resolve_params(c.rec_target)
                if img is None:
                    img = self._capture_window(True)
                if img is None:
                    return c.negate
                if not self._ocr or not self._ocr.is_available:
                    return c.negate
                all_results = self._ocr.recognize(img, min_confidence=0.3)
                found = any(target in r.text for r in (all_results or []))
                return (not found) if c.negate else found
            elif c.condition_type == "array_contains":
                arr_name = self._resolve_params(c.array_name)
                search_val = self._resolve_params(c.search_value)
                arr = self._get_array_value(arr_name)
                found = False
                param = self._current_task.get_param(arr_name) if self._current_task else None
                if param and param.param_type == "array" and param.array_item_type == "int":
                    try:
                        search_num = coerce_array_item_value("int", self._parse_literal_value(search_val))
                        found = search_num in arr
                    except (TypeError, ValueError):
                        found = False
                else:
                    str_arr = [str(v) for v in arr]
                    if search_val in str_arr:
                        found = True
                    else:
                        try:
                            parts = [p.strip() for p in search_val.split(",")]
                            if len(parts) == 2:
                                sx, sy = int(parts[0]), int(parts[1])
                                for item in arr:
                                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                                        if int(item[0]) == sx and int(item[1]) == sy:
                                            found = True
                                            break
                                    elif isinstance(item, dict):
                                        if int(item.get("x", -1)) == sx and int(item.get("y", -1)) == sy:
                                            found = True
                                            break
                        except (ValueError, TypeError):
                            pass
                return (not found) if c.negate else found
            elif c.condition_type == "coord_in_array":
                arr_name = self._resolve_params(c.array_name)
                search_val = self._resolve_params(c.search_value)
                arr = self._get_array_value(arr_name)
                try:
                    parts = [int(p.strip()) for p in search_val.split(",")]
                    coord = parts[:2]
                    return coord in arr
                except (ValueError, IndexError):
                    return False
            return False
        except Exception as e:
            self._log(f"条件评估异常: {e}")
            return False

    def _compare(self, left: Any, op: str, right: Any) -> bool:
        """字符串/数值比较"""
        if op in (">", "<", ">=", "<="):
            try:
                lv, rv = float(left), float(right)
                if op == ">": return lv > rv
                if op == "<": return lv < rv
                if op == ">=": return lv >= rv
                if op == "<=": return lv <= rv
            except (TypeError, ValueError):
                return False
        if op == "==": return left == right
        if op == "!=": return left != right
        if op == "contains":
            try:
                return right in left
            except TypeError:
                return False
        if op == "not_contains":
            try:
                return right not in left
            except TypeError:
                return False
        return False

    def _get_operand_length(self, value: Any) -> Optional[int]:
        parsed = self._parse_literal_value(value)
        try:
            return len(parsed)
        except TypeError:
            return None

    def _compare_numeric(self, left: Any, op: str, right: Any) -> bool:
        """数值比较，支持长度等整型场景。"""
        try:
            lv = float(left)
            rv = float(self._parse_literal_value(right))
        except (TypeError, ValueError):
            return False

        if op == "==":
            return lv == rv
        if op == "!=":
            return lv != rv
        if op == ">":
            return lv > rv
        if op == "<":
            return lv < rv
        if op == ">=":
            return lv >= rv
        if op == "<=":
            return lv <= rv
        return False

    def _get_array_value(self, name: str) -> list:
        """获取数组参数值"""
        if name in self._runtime_vars:
            v = self._runtime_vars[name]
            return v if isinstance(v, list) else []
        if self._current_task:
            p = self._current_task.get_param(name)
            if p and isinstance(p.value, list):
                return p.value
        return []

    def _execute_step(self, step_index: int, step: SingleTask) -> bool:
        """执行单个步骤"""
        resolved_target, target_mode = self._resolve_recognition_target(step)
        resolved_input_text = self._resolve_params(step.input_text)
        resolved_press_keys = self._resolve_params(step.press_keys)

        rec_type_names = {
            'text': '文字', 'image': '图像', 'ai_tile': 'AI地块',
            'multi_image': '多图像(动画帧)', 'none': '无',
        }
        rec_name = rec_type_names.get(step.recognition_type, step.recognition_type)
        sname = self._display_name(step, step_index)
        target_text = self._format_recognition_target_log(resolved_target, target_mode)
        if step.recognition_type == "ai_tile" and not target_text:
            target_text = "(默认AI模型)"
        self._log(f"执行步骤 [{step_index + 1}] {sname}: "
               f"{rec_name}识别 -> {target_text or '(直接执行)'}")

        if self.on_step_start:
            self.on_step_start(step_index, step)

        # ── 识别类型为"无"时，直接检查条件后执行操作 ──
        if step.recognition_type == "none":
            # 条件检查（截一帧图用于图像/文字条件）
            img = None
            if step.conditions:
                img = self._capture_window(step.use_background)
                if not self._evaluate_conditions(step.conditions, img):
                    self._log(f"步骤 [{sname}] 条件不满足，跳过")
                    if self.on_step_success:
                        self.on_step_success(step_index, step)
                    return True
            self._do_action(step, 0, 0, 0, 0,
                            resolved_input_text, resolved_press_keys,
                            resolved_target, target_mode)
            if step.delay_after > 0:
                self._interruptible_sleep(step.delay_after)
            if self.on_step_success:
                self.on_step_success(step_index, step)
            return True

        # ── 需要识别的步骤 ──
        start_time = time.time()
        retry_count = 0

        while True:
            if self._check_stopped():
                return False
            self._wait_if_paused()
            if self._check_stopped():
                return False

            if step.timeout > 0:
                elapsed = time.time() - start_time
                if elapsed >= step.timeout:
                    timeout_text = f"{step.timeout:.2f}".rstrip("0").rstrip(".")
                    error_msg = f"步骤 [{sname}] 超时 ({timeout_text}秒)"
                    compare_text = self._format_last_recognition_metrics()
                    if compare_text:
                        error_msg = f"{error_msg}，最后一次识别: {compare_text}"
                    self._log(error_msg)
                    
                    # 检查是否启用识别失败操作
                    if step.on_fail_enabled:
                        self._log(f"步骤 [{sname}] 在 {retry_count} 次重试后仍识别失败，开始执行失败操作")
                        self._execute_on_fail_action(step)
                        # 失败操作执行后，步骤算成功（不终止任务）
                        if self.on_step_success:
                            self.on_step_success(step_index, step)
                        return True
                    
                    if self.on_step_fail:
                        self.on_step_fail(step_index, step, error_msg)
                    return False

            img = self._capture_window(step.use_background)
            if img is None:
                self._log(f"截图失败，{step.retry_interval}秒后重试...")
                retry_count += 1
                if self.on_step_retry:
                    self.on_step_retry(step_index, step, retry_count)
                self._interruptible_sleep(step.retry_interval)
                continue

            # 条件检查
            if step.conditions and not self._evaluate_conditions(step.conditions, img):
                self._log(f"步骤 [{sname}] 条件不满足，跳过")
                if self.on_step_success:
                    self.on_step_success(step_index, step)
                return True

            result = self._recognize(step, img, resolved_target, target_mode)

            if result is not None:
                center_x, center_y, tpl_w, tpl_h = result
                success_msg = (
                    f"步骤 [{sname}] 识别成功，位置(相对): "
                    f"{self._format_client_relative_point(center_x, center_y)}"
                )
                compare_text = self._format_last_recognition_metrics()
                if compare_text:
                    success_msg = f"{success_msg}，{compare_text}"
                self._log(success_msg)

                if self._get_step_actions(step):
                    self._do_action(step, center_x, center_y, tpl_w, tpl_h,
                                    resolved_input_text, resolved_press_keys,
                                    resolved_target, target_mode)

                if step.delay_after > 0:
                    self._interruptible_sleep(step.delay_after)

                if self.on_step_success:
                    self.on_step_success(step_index, step)
                return True
            else:
                retry_count += 1
                if retry_count == 1 or retry_count % 5 == 0:
                    elapsed = int(time.time() - start_time)
                    retry_msg = f"步骤 [{sname}] 第{retry_count}次识别未匹配"
                    compare_text = self._format_last_recognition_metrics()
                    if compare_text:
                        retry_msg = f"{retry_msg}，{compare_text}"
                    retry_msg = f"{retry_msg}，已用时{elapsed}秒，继续等待..."
                    self._log(retry_msg)
                if self.on_step_retry:
                    self.on_step_retry(step_index, step, retry_count)
                self._interruptible_sleep(step.retry_interval)

    def _execute_loop_step(self, step_index: int, step: SingleTask) -> bool:
        """执行循环步骤 — 遍历数组参数，对每个元素执行子步骤"""
        arr = self._get_array_value(step.loop_array)
        sname = self._display_name(step, step_index)
        if not arr:
            self._log(f"循环步骤 [{sname}]: 数组 '{step.loop_array}' 为空，跳过")
            return True

        self._log(f"循环步骤 [{sname}]: 遍历 '{step.loop_array}' ({len(arr)} 个元素)")

        # 保存循环变量的原始值，循环结束后恢复
        loop_var_name = step.loop_var
        original_value = None
        loop_var_param = None
        original_runtime_present = False
        original_runtime_value = None
        if loop_var_name:
            original_runtime_present = loop_var_name in self._runtime_vars
            original_runtime_value = self._runtime_vars.get(loop_var_name)
        if loop_var_name and self._current_task:
            loop_var_param = self._current_task.get_param(loop_var_name)
            if loop_var_param:
                original_value = loop_var_param.value

        for loop_idx, item in enumerate(arr):
            if self._check_stopped():
                return False

            # 检查是否需要跳出循环
            if self._break_loop:
                self._log(f"  循环中断：遇到跳出循环操作")
                self._break_loop = False  # 重置标志
                break

            # 更新任务变量的值，并同步到运行时变量
            if loop_var_name:
                if loop_var_param:
                    loop_var_param.value = item
                self._set_runtime_var(loop_var_name, item)

            if (loop_idx + 1) % 50 == 0 or loop_idx == 0:
                self._log(f"  循环 {loop_idx + 1}/{len(arr)}: {loop_var_name}={item}")

            child_idx = 0
            while child_idx < len(step.children):
                child = step.children[child_idx]
                if self._check_stopped():
                    return False
                self._wait_if_paused()

                # 检查是否需要继续循环（跳过本次迭代的剩余子步骤）
                if self._continue_loop:
                    self._log(f"  继续循环：跳过本次迭代的剩余子步骤")
                    self._continue_loop = False  # 重置标志
                    break

                # 检查是否需要跳出循环
                if self._break_loop:
                    break

                if child.is_loop:
                    success = self._execute_loop_step(child_idx, child)
                else:
                    success = self._execute_step(child_idx, child)

                if not success:
                    cname = self._display_name(child, child_idx)
                    self._log(f"  循环子步骤 [{cname}] 失败，终止循环")
                    return False

                # 单步模式：循环内子步骤执行完后也自动暂停
                if self._step_mode:
                    self._step_mode = False
                    self._pause_event.clear()
                    self._state = TaskState.PAUSED
                    self._log("单步执行完成，已暂停")
                    if self.on_step_paused:
                        self.on_step_paused()

                # 执行到指定步骤：检查是否到达目标
                if self._run_to_step_id and child.id == self._run_to_step_id:
                    self._run_to_step_id = None
                    self._pause_event.clear()
                    self._state = TaskState.PAUSED
                    cname2 = self._display_name(child, child_idx)
                    self._log(f"已执行到目标步骤 [{cname2}]，已暂停")
                    if self.on_step_paused:
                        self.on_step_paused()

                if self._jump_target:
                    local_target_idx = self._find_step_index(self._jump_target, step.children)
                    if local_target_idx is not None:
                        target_name = self._display_name(step.children[local_target_idx], local_target_idx)
                        self._log(f"  跳转到循环子步骤 [{target_name}]")
                        child_idx = local_target_idx
                        self._jump_target = None
                        continue
                    break

                child_idx += 1

            if self._jump_target:
                break

            # 如果 continue_loop 发生在当前循环的最后一个子步骤，while 会自然结束，
            # 这里要在当前层立即消费，避免标志冒泡到外层循环。
            if self._continue_loop:
                self._log(f"  继续循环：跳过本次迭代的剩余子步骤")
                self._continue_loop = False
                continue

            # 检查是否在子步骤循环后需要跳出
            if self._break_loop:
                self._log(f"  循环中断：遇到跳出循环操作")
                self._break_loop = False  # 重置标志
                break

        # 恢复循环变量的原始值
        if loop_var_name:
            if loop_var_param:
                loop_var_param.value = original_value
                self._set_runtime_var(loop_var_name, original_value)
            elif original_runtime_present:
                self._set_runtime_var(loop_var_name, original_runtime_value)
            else:
                self._runtime_vars.pop(loop_var_name, None)
                self._clear_runtime_subfields(loop_var_name)

        return True

    def _get_last_recognition_action_context(self):
        region = self._copy_last_recognition_region()
        if region is None:
            regions = self._copy_last_recognition_regions()
            if regions:
                region = regions[0]
        if not region:
            return None

        width = max(1, int(region.get("width", 1) or 1))
        height = max(1, int(region.get("height", 1) or 1))
        center_x = int(round(int(region.get("x", 0) or 0) + width / 2.0))
        center_y = int(round(int(region.get("y", 0) or 0) + height / 2.0))
        return center_x, center_y, width, height

    def _action_requires_recognition_context(self, step: SingleTask, action_data: Optional[dict], action_type: str) -> bool:
        action_data = action_data or {}
        action_type = normalize_action_type(action_type or "none")

        if action_type in ("highlight_match", "recognition_to_logic_coord", "save_recognition_coords", "drag_match_to_center"):
            return True

        if action_type in (
            "click",
            "double_click",
            "right_click",
            "input_text",
            "hold_left_button",
            "highlight_point",
        ):
            return self._resolve_action_point_mode(step, action_data) == "recognition"

        if action_type == "drag_map":
            start_mode = self._normalize_drag_start_mode(
                action_data.get("drag_start_mode", getattr(step, "drag_start_mode", "recognition"))
            )
            return start_mode != "screen_percent"

        return False

    def _resolve_action_point_mode(self, step: SingleTask, action_data: dict) -> str:
        return normalize_point_position_mode(
            action_data.get("point_position_mode", getattr(step, "point_position_mode", "recognition"))
        )

    def _resolve_action_offset_mode(self, step: SingleTask, action_data: dict, point_mode: str = "recognition") -> str:
        return normalize_click_offset_mode(
            action_data.get(
                "click_offset_mode",
                getattr(step, "click_offset_mode", get_default_click_offset_mode(point_mode)),
            ),
            point_mode,
        )

    def _resolve_action_point_pair(self, step: SingleTask, action_data: dict, mode: str):
        point_coord_text = str(action_data.get("point_coord_text", getattr(step, "point_coord_text", "")) or "").strip()
        if point_coord_text:
            pair = self._get_number_pair_value(point_coord_text, integer=(mode == "screen_absolute"))
            if pair is None:
                raise RuntimeError(f"无法解析坐标变量或引用 '{point_coord_text}'")
            return pair

        if mode == "screen_percent":
            ratio_x = self._coerce_screen_ratio(action_data.get("point_x", getattr(step, "point_x", 0.5)), 0.5)
            ratio_y = self._coerce_screen_ratio(action_data.get("point_y", getattr(step, "point_y", 0.5)), 0.5)
            return ratio_x, ratio_y

        client_x = int(round(coerce_float(action_data.get("point_x", getattr(step, "point_x", 0.0)), 0.0)))
        client_y = int(round(coerce_float(action_data.get("point_y", getattr(step, "point_y", 0.0)), 0.0)))
        return client_x, client_y

    def _execute_action_data(self, step: SingleTask, action_data: dict,
                             center_x: int, center_y: int,
                             tpl_w: int, tpl_h: int,
                             resolved_target: Any = None,
                             target_mode: str = "single") -> bool:
        action_data = self._normalize_action_dict(action_data)
        action = action_data.get("type", "none")
        resolved_action_input = self._resolve_params(action_data.get("input_text", ""))
        resolved_action_keys = self._resolve_params(action_data.get("press_keys", ""))
        stop_sequence = False
        action_x, action_y = self._resolve_action_point(
            step,
            action_data,
            action,
            center_x,
            center_y,
            tpl_w,
            tpl_h,
        )

        if action == "mark_blocked":
            self._mark_blocked(resolved_action_input)
        elif action == "modify_variable":
            self._action_modify_variable(step, action_data)
        elif action == "add_to_array":
            self._action_add_to_array(step, action_data)
        elif action == "save_recognition_coords":
            self._action_save_recognition_coords(step, action_data)
        elif action == "remove_target_coords":
            self._action_remove_target_coords(step, action_data)
        elif action == "clear_array_data":
            self._action_clear_array_data(step, action_data)
        elif action == "recognition_to_logic_coord":
            self._action_recognition_to_logic_coord(step, action_data)
        elif action == "jump_to_step":
            self._action_jump_to_step(step, action_data)
            stop_sequence = True
        elif action == "traverse_grid":
            self._action_traverse_grid(step, action_data)
        elif action == "get_surrounding_coords":
            self._action_get_surrounding_coords(step, action_data)
        elif action == "find_road_path":
            self._action_find_road_path(step, action_data)
        elif action == "highlight_match":
            self._action_highlight_match(action_data)
        elif action == "highlight_point":
            self._action_highlight_point(
                step,
                action_data,
                action_x,
                action_y,
                recognition_center_x=center_x,
                recognition_center_y=center_y,
            )
        elif action == "continue_loop":
            self._continue_loop = True
            self._log("执行：继续循环（跳过本次迭代的剩余子步骤）")
            stop_sequence = True
        elif action == "break_loop":
            self._break_loop = True
            self._log("执行：跳出循环（退出当前循环）")
            stop_sequence = True
        elif action != "none":
            self._perform_action(
                step,
                action_data,
                action_x,
                action_y,
                resolved_action_input,
                resolved_action_keys,
                recognition_center_x=center_x,
                recognition_center_y=center_y,
                template_width=tpl_w,
                template_height=tpl_h,
                resolved_target=resolved_target,
                target_mode=target_mode,
            )

        return stop_sequence

    def _do_action(self, step: SingleTask, center_x: int, center_y: int,
                   tpl_w: int, tpl_h: int,
                   resolved_input_text: str, resolved_press_keys: str,
                   resolved_target: Any = None, target_mode: str = "single"):
        """按顺序执行步骤操作列表"""
        actions = self._get_step_actions(step)
        if not actions:
            return

        for index, action_data in enumerate(actions):
            stop_sequence = self._execute_action_data(
                step,
                action_data,
                center_x,
                center_y,
                tpl_w,
                tpl_h,
                resolved_target=resolved_target,
                target_mode=target_mode,
            )

            if stop_sequence or self._check_stopped():
                break

            if index < len(actions) - 1:
                delay_seconds = float(action_data.get("delay", 0) or 0)
                if delay_seconds > 0:
                    self._log(f"操作间等待 {delay_seconds:.2f} 秒")
                    self._interruptible_sleep(delay_seconds)
                    if self._check_stopped():
                        break

    def _resolve_action_point(self, step: SingleTask, action_data: dict, action_type: str,
                              center_x: int, center_y: int, tpl_w: int, tpl_h: int):
        """根据识别中心点和偏移配置，计算动作起点。"""
        action_x = int(center_x)
        action_y = int(center_y)
        point_mode = "recognition"
        client_width = None
        client_height = None

        if self._action_uses_point_position_mode(action_type):
            point_mode = self._resolve_action_point_mode(step, action_data)
            if point_mode == "screen_percent":
                client_rect = self._window_manager.get_client_rect(self._hwnd)
                if not client_rect:
                    raise RuntimeError("无法获取目标窗口客户区大小，无法解析目标窗口百分比坐标")
                client_width = max(1, int(client_rect[2] - client_rect[0]))
                client_height = max(1, int(client_rect[3] - client_rect[1]))
                ratio_x, ratio_y = self._resolve_action_point_pair(step, action_data, point_mode)
                ratio_x = self._coerce_screen_ratio(ratio_x, 0.5)
                ratio_y = self._coerce_screen_ratio(ratio_y, 0.5)
                action_x = int(round(client_width * ratio_x))
                action_y = int(round(client_height * ratio_y))
            elif point_mode == "screen_absolute":
                action_x, action_y = self._resolve_action_point_pair(step, action_data, point_mode)

        if self._action_uses_click_offset(action_type):
            offset_mode = self._resolve_action_offset_mode(step, action_data, point_mode)
            offset_x = float(action_data.get("click_offset_x", step.click_offset_x) or 0)
            offset_y = float(action_data.get("click_offset_y", step.click_offset_y) or 0)
            if offset_mode == "screen_absolute":
                action_x = int(round(action_x + offset_x))
                action_y = int(round(action_y + offset_y))
            elif offset_mode == "screen_percent":
                if client_width is None or client_height is None:
                    client_rect = self._window_manager.get_client_rect(self._hwnd)
                    if not client_rect:
                        raise RuntimeError("无法获取目标窗口客户区大小，无法解析目标窗口百分比偏移")
                    client_width = max(1, int(client_rect[2] - client_rect[0]))
                    client_height = max(1, int(client_rect[3] - client_rect[1]))
                action_x = int(round(action_x + offset_x * client_width))
                action_y = int(round(action_y + offset_y * client_height))
            else:
                action_x = int(round(action_x + offset_x * tpl_w))
                action_y = int(round(action_y + offset_y * tpl_h))
        return action_x, action_y

    def _capture_window(self, use_background: bool):
        """截取目标窗口"""
        try:
            if use_background:
                img = self._capture.capture_window_background(self._hwnd)
                # 后台截图失败时回退前台
                if img is None:
                    self._log("后台截图失败，尝试前台截图...")
                    img = self._capture.capture_window(self._hwnd)
                elif self._is_black_or_empty_image(img):
                    self._log("后台截图返回黑图，尝试前台截图...")
                    img = self._capture.capture_window(self._hwnd)
            else:
                img = self._capture.capture_window(self._hwnd)
            
            # 检查图像是否有效
            if img is not None and self._is_black_or_empty_image(img):
                self._log("警告：截取的图像为黑图或空白，可能原因：窗口被遮挡/最小化/DX渲染")
            
            # 修正 DPI 缩放问题：确保截图尺寸与窗口客户区一致
            # mss 截图可能返回物理像素分辨率（DPI 放大），而 PostMessage
            # 坐标基于逻辑像素（客户区大小），分辨率不一致会导致点击偏移
            if img is not None:
                img = self._fix_capture_dpi(img)
            
            return img
        except Exception as e:
            self._log(f"截图异常: {e}")
            return None
    
    def _fix_capture_dpi(self, img):
        """
        修正截图 DPI 缩放：将截图缩放到窗口客户区尺寸
        
        当后台截图 fallback 到 mss 前台截图时，mss 返回的是物理像素分辨率，
        可能与 GetClientRect 返回的逻辑像素不一致（高 DPI 屏幕）。
        识别坐标必须与 PostMessage 坐标空间一致（逻辑像素），所以需要缩放。
        """
        import cv2
        try:
            import win32gui
            client_rect = win32gui.GetClientRect(self._hwnd)
            expected_w = client_rect[2]
            expected_h = client_rect[3]
            
            if expected_w <= 0 or expected_h <= 0:
                return img
            
            img_h, img_w = img.shape[:2]
            
            # 允许 2 像素误差
            if abs(img_w - expected_w) > 2 or abs(img_h - expected_h) > 2:
                self._log(
                    f"[调试] 截图尺寸 {img_w}x{img_h} 与客户区 {expected_w}x{expected_h} 不一致，"
                    f"自动缩放以修正 DPI 偏移"
                )
                img = cv2.resize(img, (expected_w, expected_h), interpolation=cv2.INTER_AREA)
            
            return img
        except Exception:
            return img
    
    def _is_black_or_empty_image(self, img) -> bool:
        """检查图像是否为空或几乎全黑"""
        import numpy as np
        if img is None or img.size == 0:
            return True
        
        # 检查图像是否几乎全黑（超过95%的像素值小于10）
        black_pixels = np.sum(img < 10)
        total_pixels = img.size
        
        return (black_pixels / total_pixels) > 0.95

    def _recognize(self, step: SingleTask, img, resolved_target: Any = None, target_mode: str = "single"):
        """
        执行识别

        Args:
            step: 步骤对象
            img: 截图图像
            resolved_target: 参数替换后的识别目标（可选，默认使用 step.recognition_target）
            target_mode: 识别目标匹配模式

        Returns:
            成功返回 (center_x, center_y, template_w, template_h)，失败返回 None
            template_w/h 为匹配区域的宽高，用于计算比例偏移
        """
        target = resolved_target if resolved_target is not None else step.recognition_target
        target_mode = normalize_recognition_target_mode(target_mode)
        recognition_roi = self._build_recognition_roi(step, img)
        self._clear_last_recognition_metrics()
        self._clear_last_recognition_region()
        try:
            if isinstance(target, (list, tuple)):
                if target_mode == "single":
                    target_mode = "array_any"
                return self._recognize_target_array(step, img, list(target), target_mode, recognition_roi)
            if target_mode in ("array_any", "array_all"):
                return self._recognize_target_array(step, img, target, target_mode, recognition_roi)
            return self._recognize_single_target(step, img, target, recognition_roi)
        except Exception as e:
            self._log(f"识别异常: {e}")
            return None

    def _recognize_single_target(self, step: SingleTask, img, target: Any, recognition_roi: Optional[ROI] = None):
        if step.recognition_type == "text":
            return self._recognize_text(step, img, "" if target is None else str(target), recognition_roi)
        if step.recognition_type == "image":
            return self._recognize_image(step, img, "" if target is None else str(target), recognition_roi)
        if step.recognition_type == "ai_tile":
            return self._recognize_ai_tile(step, img, "" if target is None else str(target), recognition_roi)
        if step.recognition_type == "multi_image":
            return self._recognize_multi_image(step, img, "" if target is None else str(target), recognition_roi)
        if step.recognition_type == "none":
            return (0, 0, 0, 0)
        self._log(f"未知的识别类型: {step.recognition_type}")
        return None

    def _recognize_ai_tile(self, step: SingleTask, img, target: str, recognition_roi: Optional[ROI] = None):
        if not self._ai_tile_recognition:
            self._log("AI 地块识别模块不可用")
            self._set_last_recognition_metrics(
                None,
                step.recognition_threshold,
                False,
                source="AI地块",
                note="AI 地块识别模块未初始化",
            )
            return None

        model_path = (target or "").strip() or None
        model_label = os.path.basename(model_path) if model_path else "default"
        match_index = max(1, int(getattr(step, "match_index", 1) or 1))
        result_limit = max(60, match_index + 12)
        if getattr(step, "has_multiple_matches", False):
            result_limit = max(result_limit, 200)
        result_limit = min(300, result_limit)

        results = self._ai_tile_recognition.find_tiles(
            img,
            model_path=model_path,
            threshold=step.recognition_threshold,
            roi=recognition_roi,
            max_count=result_limit,
        )
        initial_attribute_notice = self._ai_tile_recognition.get_last_attribute_notice().strip()
        if initial_attribute_notice:
            self._log(f"[AI地块] {initial_attribute_notice}")
        if not results:
            note = self._ai_tile_recognition.get_last_error() or "未检测到地块"
            self._set_last_recognition_metrics(
                None,
                step.recognition_threshold,
                False,
                source=f"AI地块[{model_label}]",
                note=note,
            )
            return None

        results.sort(key=lambda item: (item.center[1], item.center[0]))
        self._log(f"[AI地块] 找到 {len(results)} 个候选，需要第 {match_index} 个")

        if match_index > len(results):
            best_confidence = max((item.confidence for item in results), default=None)
            self._set_last_recognition_metrics(
                best_confidence,
                step.recognition_threshold,
                False,
                source=f"AI地块[{model_label}]",
                note=f"只找到 {len(results)} 个满足阈值的地块，目标第 {match_index} 个",
            )
            self._log(f"需要第 {match_index} 个 AI 地块结果，但只找到 {len(results)} 个")
            return None

        results = self._ai_tile_recognition.enrich_tiles(
            img,
            results,
            model_path=model_path,
            selected_indices=[match_index - 1],
            enrich_all=bool(getattr(step, "has_multiple_matches", False)),
        )
        post_enrich_notice = self._ai_tile_recognition.get_last_attribute_notice().strip()
        if post_enrich_notice and post_enrich_notice != initial_attribute_notice:
            if initial_attribute_notice and post_enrich_notice.startswith(f"{initial_attribute_notice}；"):
                delta_notice = post_enrich_notice[len(initial_attribute_notice) + 1 :].strip()
                if delta_notice:
                    self._log(f"[AI地块] {delta_notice}")
            else:
                self._log(f"[AI地块] {post_enrich_notice}")
        chosen = results[match_index - 1]
        note = f"使用第 {match_index} 个检测结果" if match_index > 1 else ""
        self._set_last_recognition_metrics(
            chosen.confidence,
            step.recognition_threshold,
            True,
            source=f"AI地块[{model_label}]",
            note=note,
        )

        self._log(
            f"[AI地块] 选择结果: 置信度={chosen.confidence:.3f}, "
            f"中心(相对)={self._format_client_relative_point(chosen.center[0], chosen.center[1], client_size=(img.shape[1], img.shape[0]))}"
        )
        if chosen.review_label:
            review_display = chosen.review_display or chosen.review_label
            review_confidence = chosen.review_confidence
            if review_confidence is None:
                self._log(f"[AI地块] 复检结果: {review_display}")
            else:
                self._log(f"[AI地块] 复检结果: {review_display}({review_confidence:.3f})")

        attribute_parts = []
        for entry in chosen.iter_attribute_results():
            display_name = str(entry.get("display_name") or entry.get("task_slug") or "属性").strip()
            display_value = str(entry.get("display") or entry.get("value") or "").strip()
            if display_value:
                confidence_value = entry.get("confidence")
                if confidence_value is None:
                    attribute_parts.append(f"{display_name}={display_value}")
                else:
                    attribute_parts.append(f"{display_name}={display_value}({confidence_value:.3f})")
        if attribute_parts:
            self._log(f"[AI地块] 属性结果: {'，'.join(attribute_parts)}")

        if getattr(step, "has_multiple_matches", False):
            self._set_last_recognition_regions(
                [dict(result.to_region_dict(), recognition_type="ai_tile") for result in results],
                selected_index=match_index - 1,
            )
        else:
            chosen_region = dict(chosen.to_region_dict(), recognition_type="ai_tile")
            self._set_last_recognition_region(
                chosen.x,
                chosen.y,
                chosen.width,
                chosen.height,
                recognition_type="ai_tile",
                label=chosen.label,
                extra_fields=chosen_region,
            )
        return (chosen.center[0], chosen.center[1], chosen.width, chosen.height)

    def _recognize_target_array(self, step: SingleTask, img, target, target_mode: str, recognition_roi: Optional[ROI] = None):
        raw_targets = target if isinstance(target, list) else [target]
        targets = []
        for item in raw_targets:
            text = "" if item is None else str(item).strip()
            if text:
                targets.append(text)

        if not targets:
            self._set_last_recognition_metrics(
                None,
                step.recognition_threshold,
                False,
                source="目标数组",
                note="识别目标数组为空",
            )
            return None

        if target_mode == "array_all":
            matched_results = []
            metrics_list = []
            first_region = None
            first_regions = []
            for index, item in enumerate(targets):
                result = self._recognize_single_target(step, img, item, recognition_roi)
                metrics = self._copy_last_recognition_metrics()
                metrics["source"] = f"第{index + 1}/{len(targets)}个目标[{self._short_target_label(item)}]"
                metrics_list.append(metrics)
                if result is None:
                    note = metrics.get("note", "") or "数组全部匹配未通过"
                    self._set_last_recognition_metrics(
                        metrics.get("current"),
                        metrics.get("target", step.recognition_threshold),
                        False,
                        source=metrics.get("source", "目标数组"),
                        note=note,
                    )
                    return None
                matched_results.append(result)
                if first_region is None:
                    first_region = self._copy_last_recognition_region()
                    first_regions = self._copy_last_recognition_regions()
            if len(matched_results) > 1:
                self._log("[目标数组] 全部目标匹配成功，后续操作坐标使用第1个目标位置")
            success_metrics = min(
                metrics_list,
                key=lambda item: item.get("current") if item.get("current") is not None else float("inf"),
            )
            self._set_last_recognition_metrics(
                success_metrics.get("current"),
                success_metrics.get("target", step.recognition_threshold),
                True,
                source=success_metrics.get("source", "目标数组"),
                note="数组全部目标均达到阈值",
            )
            if first_region is not None:
                self._last_recognition_region = first_region
                self._last_recognition_regions = first_regions or [dict(first_region)]
            return matched_results[0]

        best_metrics = None
        for index, item in enumerate(targets):
            result = self._recognize_single_target(step, img, item, recognition_roi)
            metrics = self._copy_last_recognition_metrics()
            metrics["source"] = f"第{index + 1}/{len(targets)}个目标[{self._short_target_label(item)}]"
            if best_metrics is None:
                best_metrics = metrics
            else:
                best_current = best_metrics.get("current")
                current = metrics.get("current")
                if current is not None and (best_current is None or current > best_current):
                    best_metrics = metrics
            if result is not None:
                if len(targets) > 1:
                    self._log(f"[目标数组] 第{index + 1}/{len(targets)}个目标匹配成功: {item}")
                self._set_last_recognition_metrics(
                    metrics.get("current"),
                    metrics.get("target", step.recognition_threshold),
                    True,
                    source=metrics.get("source", "目标数组"),
                    note=metrics.get("note", ""),
                )
                return result
        if best_metrics is not None:
            note = best_metrics.get("note", "") or "数组目标均未达到阈值"
            self._set_last_recognition_metrics(
                best_metrics.get("current"),
                best_metrics.get("target", step.recognition_threshold),
                False,
                source=best_metrics.get("source", "目标数组"),
                note=note,
            )
        return None

    def _recognize_text(self, step: SingleTask, img, target: str, recognition_roi: Optional[ROI] = None):
        """OCR文字识别"""
        if not self._ocr or not self._ocr.is_available:
            self._log("OCR不可用")
            self._set_last_recognition_metrics(
                None,
                step.recognition_threshold,
                False,
                source=f"目标[{self._short_target_label(target)}]",
                note="OCR不可用",
            )
            return None

        import cv2

        search_img = img if recognition_roi is None else recognition_roi.crop(img)
        offset_x = recognition_roi.x if recognition_roi else 0
        offset_y = recognition_roi.y if recognition_roi else 0

        # 图像预处理：大图缩放加速OCR
        ocr_img = search_img
        h, w = search_img.shape[:2]
        max_dim = 1080  # OCR处理的最大尺寸（保证中文小字可识别）
        scale = 1.0
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            ocr_img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

        # 只调用一次OCR识别
        all_results = self._ocr.recognize(ocr_img, min_confidence=0.0)

        if not all_results:
            self._set_last_recognition_metrics(
                None,
                step.recognition_threshold,
                False,
                source=f"目标[{self._short_target_label(target)}]",
                note="未识别到任何文字",
            )
            return None

        # 在结果中查找匹配文字
        matched = None
        for r in all_results:
            if step.exact_match:
                if r.text == target and r.confidence >= step.recognition_threshold:
                    matched = r
                    break
            else:
                if target in r.text and r.confidence >= step.recognition_threshold:
                    matched = r
                    break

        # 调试：如果未通过阈值，检查是否有低置信度匹配
        if matched is None:
            low_matches = [r for r in all_results if (r.text == target if step.exact_match else target in r.text)]
            if low_matches:
                best = max(low_matches, key=lambda r: r.confidence)
                self._set_last_recognition_metrics(
                    best.confidence,
                    step.recognition_threshold,
                    False,
                    source=f"目标[{self._short_target_label(target)}]",
                    note=f"最佳文字匹配 '{best.text}'",
                )
            else:
                self._set_last_recognition_metrics(
                    None,
                    step.recognition_threshold,
                    False,
                    source=f"目标[{self._short_target_label(target)}]",
                    note="未识别到目标文字",
                )
            return None

        self._set_last_recognition_metrics(
            matched.confidence,
            step.recognition_threshold,
            True,
            source=f"目标[{self._short_target_label(target)}]",
            note=f"匹配文字 '{matched.text}'",
        )

        # 坐标还原（如果做过缩放）
        if scale != 1.0:
            x = int(round(matched.x / scale)) + offset_x
            y = int(round(matched.y / scale)) + offset_y
            width = max(1, int(round(matched.width / scale)))
            height = max(1, int(round(matched.height / scale)))
            cx = int(matched.center[0] / scale) + offset_x
            cy = int(matched.center[1] / scale) + offset_y
        else:
            x = matched.x + offset_x
            y = matched.y + offset_y
            width = max(1, matched.width)
            height = max(1, matched.height)
            cx, cy = matched.center[0] + offset_x, matched.center[1] + offset_y

        self._set_last_recognition_region(
            x,
            y,
            width,
            height,
            recognition_type="text",
            label=matched.text,
        )

        # 文字识别没有模板尺寸概念，返回0
        return (cx, cy, 0, 0)

    def _recognize_image(self, step: SingleTask, img, target: str, recognition_roi: Optional[ROI] = None):
        """图像模板识别 — 支持匹配第N个结果"""
        if not self._recognition:
            self._log("图像识别模块不可用")
            self._set_last_recognition_metrics(
                None,
                step.recognition_threshold,
                False,
                source=f"目标[{self._short_target_label(target)}]",
                note="图像识别模块不可用",
            )
            return None

        target = self._resolve_template_path(target)
        target_label = self._short_target_label(target)
        match_mode = getattr(step, "image_match_mode", "template")
        if not os.path.isfile(target):
            self._set_last_recognition_metrics(
                None,
                step.recognition_threshold,
                False,
                source=f"目标[{target_label}]",
                note="模板文件不存在",
            )
            return None
        match_index = max(1, step.match_index)  # 从1开始

        # 判断是否需要使用 find_all_templates + 排序
        # 1. has_multiple_matches=True 时强制使用 find_all（即使 match_index=1）
        # 2. match_index > 1 时也必须使用 find_all
        use_find_all = step.has_multiple_matches or match_index > 1

        if not use_find_all:
            # 只需要第1个匹配且无多匹配标记，用 find_template（返回置信度最高的）
            result = self._recognition.find_template(
                img,
                target,
                threshold=step.recognition_threshold,
                roi=recognition_roi,
                validate_color=step.validate_color_consistency,
                match_mode=match_mode,
            )
            if result:
                result_debug = self._recognition.get_match_debug_info(
                    img,
                    target,
                    result,
                    validate_color=step.validate_color_consistency,
                    match_mode=match_mode,
                )
                self._set_last_recognition_metrics(
                    result.confidence,
                    step.recognition_threshold,
                    True,
                    source=f"目标[{target_label}]",
                    note="",
                    template_confidence=result_debug.get("template_confidence", result.confidence),
                    color_confidence=result_debug.get("color_confidence"),
                    color_validation_enabled=result_debug.get("color_validation_enabled", False),
                    color_validation_applied=result_debug.get("color_validation_applied", False),
                    color_validation_threshold=result_debug.get("color_validation_threshold"),
                    color_note=result_debug.get("color_note", ""),
                )
                self._log(
                    f"[调试] 模板匹配: {result.template_name}, "
                    f"{self._format_match_debug_details(result_debug, step.recognition_threshold)}, "
                    f"图像尺寸={img.shape[1]}x{img.shape[0]}, "
                    f"匹配位置=({result.x},{result.y}), 尺寸=({result.width}x{result.height}), "
                    f"中心(相对)={self._format_client_relative_point(result.center[0], result.center[1], client_size=(img.shape[1], img.shape[0]))}"
                )
                self._set_last_recognition_region(
                    result.x,
                    result.y,
                    result.width,
                    result.height,
                    recognition_type="image",
                    label=os.path.basename(target) or target_label,
                )
                return (result.center[0], result.center[1], result.width, result.height)

            diagnostic_result = self._recognition.find_template(
                img,
                target,
                threshold=1e-6,
                roi=recognition_roi,
                validate_color=False,
                match_mode=match_mode,
            )
            diagnostic_debug = self._recognition.get_match_debug_info(
                img,
                target,
                diagnostic_result,
                validate_color=step.validate_color_consistency,
                match_mode=match_mode,
            )
            if diagnostic_result:
                note = ""
                if (
                    step.validate_color_consistency
                    and diagnostic_result.confidence >= step.recognition_threshold
                ):
                    note = "颜色一致性校验未通过"
                self._set_last_recognition_metrics(
                    diagnostic_result.confidence,
                    step.recognition_threshold,
                    False,
                    source=f"目标[{target_label}]",
                    note=note,
                    template_confidence=diagnostic_debug.get("template_confidence", diagnostic_result.confidence),
                    color_confidence=diagnostic_debug.get("color_confidence"),
                    color_validation_enabled=diagnostic_debug.get("color_validation_enabled", False),
                    color_validation_applied=diagnostic_debug.get("color_validation_applied", False),
                    color_validation_threshold=diagnostic_debug.get("color_validation_threshold"),
                    color_note=diagnostic_debug.get("color_note", ""),
                )
            else:
                self._set_last_recognition_metrics(
                    None,
                    step.recognition_threshold,
                    False,
                    source=f"目标[{target_label}]",
                    note="未找到可比较的模板匹配",
                )
            return None
        else:
            # 使用 find_all_templates + 排序
            result_limit = self._recognition_find_all_limit(
                match_index,
                keep_extra_matches=step.has_multiple_matches,
            )
            results = self._recognition.find_all_templates(
                img,
                target,
                threshold=step.recognition_threshold,
                roi=recognition_roi,
                max_count=result_limit,
                validate_color=step.validate_color_consistency,
                match_mode=match_mode,
            )
            if not results:
                diagnostic_result = self._recognition.find_template(
                    img,
                    target,
                    threshold=1e-6,
                    roi=recognition_roi,
                    validate_color=False,
                    match_mode=match_mode,
                )
                diagnostic_debug = self._recognition.get_match_debug_info(
                    img,
                    target,
                    diagnostic_result,
                    validate_color=step.validate_color_consistency,
                    match_mode=match_mode,
                )
                if diagnostic_result:
                    note = ""
                    if (
                        step.validate_color_consistency
                        and diagnostic_result.confidence >= step.recognition_threshold
                    ):
                        note = "颜色一致性校验未通过"
                    self._set_last_recognition_metrics(
                        diagnostic_result.confidence,
                        step.recognition_threshold,
                        False,
                        source=f"目标[{target_label}]",
                        note=note,
                        template_confidence=diagnostic_debug.get("template_confidence", diagnostic_result.confidence),
                        color_confidence=diagnostic_debug.get("color_confidence"),
                        color_validation_enabled=diagnostic_debug.get("color_validation_enabled", False),
                        color_validation_applied=diagnostic_debug.get("color_validation_applied", False),
                        color_validation_threshold=diagnostic_debug.get("color_validation_threshold"),
                        color_note=diagnostic_debug.get("color_note", ""),
                    )
                else:
                    self._set_last_recognition_metrics(
                        None,
                        step.recognition_threshold,
                        False,
                        source=f"目标[{target_label}]",
                        note="未找到可比较的模板匹配",
                    )
                return None

            # 按从左到右、从上到下排序（先按y排，再按x排）
            results.sort(key=lambda r: (r.center[1], r.center[0]))

            self._log(
                f"[调试] 找到 {len(results)} 个匹配，需要第 {match_index} 个"
            )
            for i, r in enumerate(results):
                result_debug = self._recognition.get_match_debug_info(
                    img,
                    target,
                    r,
                    validate_color=step.validate_color_consistency,
                    match_mode=match_mode,
                )
                self._log(
                    f"[调试]   #{i+1}: {self._format_match_debug_details(result_debug, step.recognition_threshold)}, "
                    f"中心(相对)={self._format_client_relative_point(r.center[0], r.center[1], client_size=(img.shape[1], img.shape[0]))}"
                )

            if match_index > len(results):
                best_confidence = max((r.confidence for r in results), default=None)
                self._set_last_recognition_metrics(
                    best_confidence,
                    step.recognition_threshold,
                    False,
                    source=f"目标[{target_label}]",
                    note=f"只找到 {len(results)} 个满足阈值的匹配，目标第 {match_index} 个",
                )
                self._log(
                    f"需要第 {match_index} 个匹配，但只找到 {len(results)} 个"
                )
                return None

            chosen = results[match_index - 1]
            chosen_debug = self._recognition.get_match_debug_info(
                img,
                target,
                chosen,
                validate_color=step.validate_color_consistency,
                match_mode=match_mode,
            )
            self._set_last_recognition_metrics(
                chosen.confidence,
                step.recognition_threshold,
                True,
                source=f"目标[{target_label}]",
                note=(
                    f"使用第 {match_index} 个匹配" if match_index > 1 else ""
                ),
                template_confidence=chosen_debug.get("template_confidence", chosen.confidence),
                color_confidence=chosen_debug.get("color_confidence"),
                color_validation_enabled=chosen_debug.get("color_validation_enabled", False),
                color_validation_applied=chosen_debug.get("color_validation_applied", False),
                color_validation_threshold=chosen_debug.get("color_validation_threshold"),
                color_note=chosen_debug.get("color_note", ""),
            )
            self._log(
                f"[调试] 选择第 {match_index} 个匹配: "
                f"{self._format_match_debug_details(chosen_debug, step.recognition_threshold)}, "
                f"中心(相对)={self._format_client_relative_point(chosen.center[0], chosen.center[1], client_size=(img.shape[1], img.shape[0]))}"
            )
            region_label = os.path.basename(target) or target_label
            if step.has_multiple_matches:
                self._set_last_recognition_regions(
                    [
                        {
                            "x": result.x,
                            "y": result.y,
                            "width": result.width,
                            "height": result.height,
                            "recognition_type": "image",
                            "label": region_label,
                        }
                        for result in results
                    ],
                    selected_index=match_index - 1,
                )
            else:
                self._set_last_recognition_region(
                    chosen.x,
                    chosen.y,
                    chosen.width,
                    chosen.height,
                    recognition_type="image",
                    label=region_label,
                )
            return (chosen.center[0], chosen.center[1], chosen.width, chosen.height)

    def _recognize_multi_image(self, step: SingleTask, img, target: str, recognition_roi: Optional[ROI] = None):
        """多图像识别 — recognition_target 以 | 分隔多个图片路径，任一匹配即成功"""
        if not self._recognition:
            self._log("图像识别模块不可用")
            self._set_last_recognition_metrics(
                None,
                step.recognition_threshold,
                False,
                source="多图像目标",
                note="图像识别模块不可用",
            )
            return None

        paths = [p.strip() for p in target.split("|") if p.strip()]
        if not paths:
            self._log("多图像识别：未指定图片路径")
            self._set_last_recognition_metrics(
                None,
                step.recognition_threshold,
                False,
                source="多图像目标",
                note="未指定图片路径",
            )
            return None

        best_result = None
        best_label = ""
        best_debug = None
        match_mode = getattr(step, "image_match_mode", "template")
        match_index = max(1, step.match_index)
        use_find_all = step.has_multiple_matches or match_index > 1
        matched_entries = []
        diagnostic_candidates = []
        result_limit = self._recognition_find_all_limit(
            match_index,
            keep_extra_matches=step.has_multiple_matches,
        )

        for idx, path in enumerate(paths):
            resolved = self._resolve_template_path(path)
            if not os.path.isfile(resolved):
                continue

            target_label = self._short_target_label(path)
            region_label = os.path.basename(path) or target_label
            diagnostic_candidates.append((resolved, target_label))

            if not use_find_all:
                result = self._recognition.find_template(
                    img,
                    resolved,
                    threshold=step.recognition_threshold,
                    roi=recognition_roi,
                    validate_color=step.validate_color_consistency,
                    match_mode=match_mode,
                )
                if not result:
                    continue

                result_debug = self._recognition.get_match_debug_info(
                    img,
                    resolved,
                    result,
                    validate_color=step.validate_color_consistency,
                    match_mode=match_mode,
                )
                self._log(
                    f"[多图像] 第{idx+1}/{len(paths)}张匹配成功: {os.path.basename(path)}, "
                    f"{self._format_match_debug_details(result_debug, step.recognition_threshold)}, "
                    f"中心(相对)={self._format_client_relative_point(result.center[0], result.center[1], client_size=(img.shape[1], img.shape[0]))}"
                )
                matched_entries.append({
                    "path_index": idx,
                    "label": target_label,
                    "region_label": region_label,
                    "result": result,
                    "debug": result_debug,
                    "sort_key": (idx, result.center[1], result.center[0]),
                })
                continue

            results = self._recognition.find_all_templates(
                img,
                resolved,
                threshold=step.recognition_threshold,
                roi=recognition_roi,
                max_count=result_limit,
                validate_color=step.validate_color_consistency,
                match_mode=match_mode,
            )
            if not results:
                continue

            results.sort(key=lambda r: (r.center[1], r.center[0]))
            self._log(
                f"[多图像] 第{idx+1}/{len(paths)}张找到 {len(results)} 个匹配，需要第 {match_index} 个"
            )
            for result_idx, result_item in enumerate(results):
                result_item_debug = self._recognition.get_match_debug_info(
                    img,
                    resolved,
                    result_item,
                    validate_color=step.validate_color_consistency,
                    match_mode=match_mode,
                )
                self._log(
                    f"[多图像]   #{result_idx+1}: "
                    f"{self._format_match_debug_details(result_item_debug, step.recognition_threshold)}, "
                    f"中心(相对)={self._format_client_relative_point(result_item.center[0], result_item.center[1], client_size=(img.shape[1], img.shape[0]))}"
                )
                matched_entries.append({
                    "path_index": idx,
                    "label": target_label,
                    "region_label": region_label,
                    "result": result_item,
                    "debug": result_item_debug,
                    "sort_key": (result_item.center[1], result_item.center[0], idx, result_idx),
                })

        if matched_entries:
            deduped_entries = self._deduplicate_matched_entries(matched_entries)
            if len(deduped_entries) != len(matched_entries):
                self._log(
                    f"[多图像] 去重后保留 {len(deduped_entries)} 个匹配（原始 {len(matched_entries)} 个）"
                )
            matched_entries = deduped_entries
            if use_find_all:
                matched_entries.sort(key=lambda item: item["sort_key"])
                self._log(
                    f"[多图像] 总共识别到 {len(matched_entries)} 个匹配，需要第 {match_index} 个"
                )
                if match_index > len(matched_entries):
                    best_confidence = max(
                        (entry["result"].confidence for entry in matched_entries),
                        default=None,
                    )
                    self._set_last_recognition_metrics(
                        best_confidence,
                        step.recognition_threshold,
                        False,
                        source="多图像目标",
                        note=f"总共只找到 {len(matched_entries)} 个满足阈值的匹配，目标第 {match_index} 个",
                    )
                    return None
                chosen_entry = matched_entries[match_index - 1]
            else:
                chosen_entry = matched_entries[0]
                if len(matched_entries) > 1:
                    self._log(
                        f"[多图像] 共识别到 {len(matched_entries)} 张目标，后续操作坐标使用第1个匹配目标"
                    )

            chosen = chosen_entry["result"]
            chosen_debug = chosen_entry["debug"]
            chosen_label = chosen_entry["label"]
            chosen_region_label = chosen_entry["region_label"]
            note = ""
            if use_find_all and match_index > 1:
                note = f"使用第 {match_index} 个匹配"
            elif not use_find_all and len(matched_entries) > 1:
                note = f"共识别到 {len(matched_entries)} 张目标，操作使用第1个匹配目标"

            self._set_last_recognition_metrics(
                chosen.confidence,
                step.recognition_threshold,
                True,
                source=f"目标[{chosen_label}]",
                note=note,
                template_confidence=chosen_debug.get("template_confidence", chosen.confidence),
                color_confidence=chosen_debug.get("color_confidence"),
                color_validation_enabled=chosen_debug.get("color_validation_enabled", False),
                color_validation_applied=chosen_debug.get("color_validation_applied", False),
                color_validation_threshold=chosen_debug.get("color_validation_threshold"),
                color_note=chosen_debug.get("color_note", ""),
            )

            if len(matched_entries) > 1 or step.has_multiple_matches:
                selected_index = matched_entries.index(chosen_entry)
                self._set_last_recognition_regions(
                    [
                        {
                            "x": entry["result"].x,
                            "y": entry["result"].y,
                            "width": entry["result"].width,
                            "height": entry["result"].height,
                            "recognition_type": "image",
                            "label": entry["region_label"],
                        }
                        for entry in matched_entries
                    ],
                    selected_index=selected_index,
                )
            else:
                self._set_last_recognition_region(
                    chosen.x,
                    chosen.y,
                    chosen.width,
                    chosen.height,
                    recognition_type="image",
                    label=chosen_region_label,
                )

            self._log(
                f"[多图像] 选择目标: {chosen_region_label}, "
                f"{self._format_match_debug_details(chosen_debug, step.recognition_threshold)}, "
                f"中心(相对)={self._format_client_relative_point(chosen.center[0], chosen.center[1], client_size=(img.shape[1], img.shape[0]))}"
            )
            return (chosen.center[0], chosen.center[1], chosen.width, chosen.height)

        for resolved, target_label in diagnostic_candidates:
            diagnostic = self._recognition.find_template(
                img,
                resolved,
                threshold=1e-6,
                roi=recognition_roi,
                validate_color=False,
                match_mode=match_mode,
            )
            if not diagnostic:
                continue
            diagnostic_debug = self._recognition.get_match_debug_info(
                img,
                resolved,
                diagnostic,
                validate_color=step.validate_color_consistency,
                match_mode=match_mode,
            )
            if best_result is None or diagnostic.confidence > best_result.confidence:
                best_result = diagnostic
                best_label = target_label
                best_debug = diagnostic_debug

        if best_result is not None:
            note = ""
            if (
                step.validate_color_consistency
                and best_result.confidence >= step.recognition_threshold
            ):
                note = "颜色一致性校验未通过"
            elif use_find_all and match_index > 1:
                note = f"未找到第 {match_index} 个满足阈值的匹配"
            self._set_last_recognition_metrics(
                best_result.confidence,
                step.recognition_threshold,
                False,
                source=f"目标[{best_label}]",
                note=note,
                template_confidence=best_debug.get("template_confidence", best_result.confidence),
                color_confidence=best_debug.get("color_confidence"),
                color_validation_enabled=best_debug.get("color_validation_enabled", False),
                color_validation_applied=best_debug.get("color_validation_applied", False),
                color_validation_threshold=best_debug.get("color_validation_threshold"),
                color_note=best_debug.get("color_note", ""),
            )
        else:
            self._set_last_recognition_metrics(
                None,
                step.recognition_threshold,
                False,
                source="多图像目标",
                note="未找到可比较的模板匹配",
            )

        return None

    @staticmethod
    def _resolve_template_path(target: str) -> str:
        """解析模板路径：将相对路径转为绝对路径"""
        if os.path.isabs(target):
            return target
        # 相对路径：基于应用程序根目录解析
        if getattr(sys, 'frozen', False):
            app_dir = os.path.dirname(sys.executable)
        else:
            app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        resolved = os.path.join(app_dir, target)
        return os.path.normpath(resolved)

    @staticmethod
    def _coerce_action_flag(action_data: Optional[dict], key: str) -> bool:
        if not action_data:
            return False
        value = action_data.get(key, False)
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on", "y")
        return bool(value)

    @staticmethod
    def _iter_ai_tile_region_attribute_entries(region: dict) -> List[dict]:
        attribute_results = region.get("attribute_results")
        attribute_order = region.get("attribute_order")
        entries: List[dict] = []
        seen: set[str] = set()

        if isinstance(attribute_results, dict):
            candidate_slugs: List[str] = []
            if isinstance(attribute_order, (list, tuple)):
                candidate_slugs.extend(str(item).strip() for item in attribute_order if str(item).strip())
            candidate_slugs.extend(str(item).strip() for item in attribute_results.keys() if str(item).strip())
            for task_slug in candidate_slugs:
                if not task_slug or task_slug in seen:
                    continue
                seen.add(task_slug)
                entry = attribute_results.get(task_slug)
                if not isinstance(entry, dict):
                    continue
                display_value = str(entry.get("display") or entry.get("value") or "").strip()
                if not display_value:
                    continue
                entries.append(
                    {
                        "task_slug": task_slug,
                        "display_name": str(entry.get("display_name") or task_slug).strip() or task_slug,
                        "display": display_value,
                        "confidence": entry.get("confidence"),
                    }
                )

        if entries:
            return entries

        for task_slug, display_name in (("level", "等级"), ("resource_type", "类型"), ("relation", "关系")):
            display_value = str(region.get(f"{task_slug}_display") or region.get(task_slug) or "").strip()
            if not display_value:
                continue
            entries.append(
                {
                    "task_slug": task_slug,
                    "display_name": display_name,
                    "display": display_value,
                    "confidence": region.get(f"{task_slug}_confidence"),
                }
            )
        return entries

    @staticmethod
    def _build_ai_highlight_overlay_text(region: dict) -> str:
        if str(region.get("recognition_type") or "") != "ai_tile":
            return ""

        parts = []
        for entry in TaskExecutor._iter_ai_tile_region_attribute_entries(region):
            display_name = str(entry.get("display_name") or entry.get("task_slug") or "属性").strip()
            display_value = str(entry.get("display") or "").strip()
            if display_value:
                parts.append(f"{display_name}={display_value}")
        if len(parts) > 3:
            parts = parts[:3] + ["..."]
        return " / ".join(parts)

    def _action_highlight_match(self, action_data: Optional[dict] = None):
        """用红框高亮最近一次识别到的图像或文字区域。"""
        regions = self._copy_last_recognition_regions()
        if not regions:
            region = self._copy_last_recognition_region()
            if region:
                regions = [region]

        if not regions:
            self._log("红框标记识别结果失败：当前步骤没有可用的识别框")
            return

        if not self._window_manager or not self._hwnd:
            self._log("红框标记识别结果失败：窗口管理器未初始化")
            return

        client_rect = self._window_manager.get_client_rect(self._hwnd)
        if not client_rect:
            self._log("红框标记识别结果失败：无法获取窗口客户区位置")
            return

        duration_ms = 1200
        if action_data:
            try:
                duration_ms = max(100, int(float(action_data.get("duration_ms", 1200) or 1200)))
            except (TypeError, ValueError):
                duration_ms = 1200
        show_ai_attributes = self._coerce_action_flag(action_data, "show_ai_attributes")

        screen_regions = []
        labels = []
        for region in regions:
            screen_left = int(client_rect[0] + region["x"])
            screen_top = int(client_rect[1] + region["y"])
            width = max(1, int(region["width"]))
            height = max(1, int(region["height"]))
            overlay_text = self._build_ai_highlight_overlay_text(region) if show_ai_attributes else ""
            screen_regions.append({
                "left": screen_left,
                "top": screen_top,
                "width": width,
                "height": height,
                "label": region.get("label", "") or "",
                "overlay_text": overlay_text,
            })
            if region.get("label"):
                labels.append(region["label"])

        if self.on_highlight_matches:
            self.on_highlight_matches(screen_regions, duration_ms)
        elif self.on_highlight_match and screen_regions:
            first_region = screen_regions[0]
            self.on_highlight_match(
                first_region["left"],
                first_region["top"],
                first_region["width"],
                first_region["height"],
                duration_ms,
            )

        if len(screen_regions) == 1:
            region = screen_regions[0]
            suffix_parts = []
            if region["label"]:
                suffix_parts.append(f"[{region['label']}]")
            if region.get("overlay_text"):
                suffix_parts.append(region["overlay_text"])
            suffix = f" {' / '.join(suffix_parts)}" if suffix_parts else ""
            self._log(f"红框标记识别结果: ({region['left']}, {region['top']}) {region['width']}x{region['height']}{suffix}")
        else:
            label_summary = f" [{' / '.join(labels[:3])}]" if labels else ""
            if len(labels) > 3:
                label_summary = f" [{' / '.join(labels[:3])} / ...]"
            self._log(f"红框标记识别结果: 共 {len(screen_regions)} 个识别框{label_summary}")

            client_width = max(1.0, float(client_rect[2] - client_rect[0]))
            client_height = max(1.0, float(client_rect[3] - client_rect[1]))
            detailed_regions = []
            for region, screen_region in zip(regions, screen_regions):
                center_x = float(region["x"]) + float(region["width"]) / 2.0
                center_y = float(region["y"]) + float(region["height"]) / 2.0
                detailed_regions.append({
                    "label": screen_region.get("label", "") or "未标注模板",
                    "overlay_text": screen_region.get("overlay_text", "") or "",
                    "left": int(screen_region["left"]),
                    "top": int(screen_region["top"]),
                    "width": int(screen_region["width"]),
                    "height": int(screen_region["height"]),
                    "center_relative": (
                        center_x / client_width,
                        center_y / client_height,
                    ),
                })

            detailed_regions.sort(key=lambda item: (item["top"], item["left"]))
            for index, item in enumerate(detailed_regions, start=1):
                center_relative = item["center_relative"]
                attribute_suffix = f", 属性={item['overlay_text']}" if item.get("overlay_text") else ""
                self._log(
                    f"红框 #{index}: {item['label']}, 中心(相对)="
                    f"{self._format_relative_point(center_relative[0], center_relative[1])}, "
                    f"框=({item['left']},{item['top']}) {item['width']}x{item['height']}{attribute_suffix}"
                )

    def _perform_action(self, step: SingleTask, action_data: dict, x: int, y: int,
                        resolved_input_text: str = None, resolved_press_keys: str = None,
                        recognition_center_x: Optional[int] = None,
                        recognition_center_y: Optional[int] = None,
                        template_width: int = 0,
                        template_height: int = 0,
                        resolved_target: Any = None,
                        target_mode: str = "single"):
        """执行操作 — 支持点击、输入文本、按键、标记封锁等"""
        action = action_data.get("type", step.action_type)
        use_bg = step.use_background
        input_text = resolved_input_text if resolved_input_text is not None else action_data.get("input_text", step.input_text)
        press_keys = resolved_press_keys if resolved_press_keys is not None else action_data.get("press_keys", step.press_keys)
        clear_method = action_data.get("clear_method", step.clear_method)
        clear_key_count = action_data.get("clear_key_count", step.clear_key_count)
        drag_coordinate_mode = action_data.get("drag_coordinate_mode", getattr(step, "drag_coordinate_mode", "game_logic")) or "game_logic"
        drag_direction_x = action_data.get("drag_direction_x", step.drag_direction_x)
        drag_direction_y = action_data.get("drag_direction_y", step.drag_direction_y)
        drag_distance = action_data.get("drag_distance", step.drag_distance)
        drag_vector_mode, drag_vector_x, drag_vector_y = self._resolve_screen_drag_vector(step, action_data)
        drag_duration = action_data.get("drag_duration", step.drag_duration)

        try:
            # 标记坐标不能攻击 — 不需要窗口操作
            if action == "mark_blocked":
                self._mark_blocked(input_text)
                return

            # 按键/组合键 — 不需要坐标，直接发送
            if action == "press_key":
                self._bg_input = self._bg_input_class(self._hwnd)
                keys_str = press_keys.strip()
                for key_combo in keys_str.split(","):
                    key_combo = key_combo.strip()
                    if not key_combo:
                        continue
                    parts = [k.strip() for k in key_combo.split("+")]
                    if len(parts) > 1:
                        self._bg_input.hotkey(*parts)
                        self._log(f"后台组合键: {key_combo}")
                    else:
                        self._bg_input.press(parts[0])
                        self._log(f"后台按键: {parts[0]}")
                return

            if use_bg:
                # 后台操作 — 使用 PostMessage
                self._bg_input = self._bg_input_class(self._hwnd)

                self._log(f"[调试] 后台操作: hwnd=0x{self._hwnd:X}, 坐标=({x}, {y}), 动作={action}")

                if action == "click":
                    self._bg_input.click(x, y)
                elif action == "double_click":
                    self._bg_input.double_click(x, y)
                elif action == "right_click":
                    self._bg_input.right_click(x, y)
                elif action == "hold_left_button":
                    hold_seconds = max(0.05, float(drag_duration or 0.3))
                    self._bg_input.drag_begin(x, y)
                    try:
                        self._log(f"后台长按鼠标左键: ({x}, {y}), 时长={hold_seconds:.2f}秒")
                        self._interruptible_sleep(hold_seconds)
                    finally:
                        self._bg_input.drag_end(x, y)
                    return
                elif action == "input_text":
                    # 先点击输入框
                    self._bg_input.click(x, y)
                    time.sleep(0.15)
                    # 清除旧内容
                    self._clear_input_field(
                        self._bg_input,
                        step,
                        clear_method=clear_method,
                        clear_key_count=clear_key_count,
                    )
                    # 输入文本
                    self._bg_input.type_text(input_text)
                    self._log(f"后台输入文本: \"{input_text}\"")
                    return
                elif action == "drag_map":
                    start_x, start_y, start_label = self._resolve_drag_start_point(
                        step,
                        action_data,
                        x,
                        y,
                        use_background=True,
                    )
                    if drag_coordinate_mode == "screen":
                        end_x, end_y = self._calc_screen_drag(
                            start_x,
                            start_y,
                            drag_vector_mode,
                            drag_vector_x,
                            drag_vector_y,
                        )
                    else:
                        end_x, end_y = self._calc_isometric_drag(
                            start_x,
                            start_y,
                            step,
                            self._iso_axis_x,
                            self._iso_axis_y,
                            drag_direction_x=drag_direction_x,
                            drag_direction_y=drag_direction_y,
                            drag_distance=drag_distance,
                        )
                    self._bg_input.drag(start_x, start_y, end_x, end_y, duration=drag_duration)
                    if drag_coordinate_mode == "screen":
                        vector_label = "屏幕百分比向量" if drag_vector_mode == "screen_percent" else "像素向量"
                        self._log(
                            f"后台拖动地图: {start_label} ({start_x}, {start_y}) -> ({end_x}, {end_y}), "
                            f"{vector_label}=({self._format_drag_component(drag_vector_x)}, {self._format_drag_component(drag_vector_y)})"
                        )
                    else:
                        self._log(
                            f"后台拖动地图: {start_label} ({start_x}, {start_y}) -> ({end_x}, {end_y}), 逻辑方向=({drag_direction_x}, {drag_direction_y})"
                        )
                    return
                elif action == "drag_match_to_center":
                    self._action_drag_match_to_center(
                        step,
                        action_data,
                        x,
                        y,
                        recognition_center_x=recognition_center_x,
                        recognition_center_y=recognition_center_y,
                        template_width=template_width,
                        template_height=template_height,
                        resolved_target=resolved_target,
                        target_mode=target_mode,
                        drag_duration=drag_duration,
                        use_background=True,
                    )
                    return

                self._log(f"后台{self._action_name(action)} ({x}, {y})")
            else:
                # 前台操作 - 需要将窗口坐标转换为屏幕坐标
                client_rect = self._window_manager.get_client_rect(self._hwnd)
                if client_rect:
                    screen_x = client_rect[0] + x
                    screen_y = client_rect[1] + y
                else:
                    screen_x, screen_y = x, y

                if action == "click":
                    self._input.click(screen_x, screen_y)
                elif action == "double_click":
                    self._input.double_click(screen_x, screen_y)
                elif action == "right_click":
                    self._input.right_click(screen_x, screen_y)
                elif action == "hold_left_button":
                    hold_seconds = max(0.05, float(drag_duration or 0.3))
                    self._input.drag_begin(screen_x, screen_y)
                    try:
                        self._log(f"前台长按鼠标左键: ({screen_x}, {screen_y}), 时长={hold_seconds:.2f}秒")
                        self._interruptible_sleep(hold_seconds)
                    finally:
                        self._input.drag_end()
                    return
                elif action == "input_text":
                    self._input.click(screen_x, screen_y)
                    time.sleep(0.15)
                    self._clear_input_field(
                        self._input,
                        step,
                        clear_method=clear_method,
                        clear_key_count=clear_key_count,
                    )
                    self._input.type_text(input_text)
                    self._log(f"前台输入文本: \"{input_text}\"")
                    return
                elif action == "drag_map":
                    start_screen_x, start_screen_y, start_label = self._resolve_drag_start_point(
                        step,
                        action_data,
                        x,
                        y,
                        use_background=False,
                    )
                    if drag_coordinate_mode == "screen":
                        end_screen_x, end_screen_y = self._calc_screen_drag(
                            start_screen_x,
                            start_screen_y,
                            drag_vector_mode,
                            drag_vector_x,
                            drag_vector_y,
                        )
                    else:
                        end_screen_x, end_screen_y = self._calc_isometric_drag(
                            start_screen_x,
                            start_screen_y,
                            step,
                            self._iso_axis_x,
                            self._iso_axis_y,
                            drag_direction_x=drag_direction_x,
                            drag_direction_y=drag_direction_y,
                            drag_distance=drag_distance,
                        )
                    self._input.drag(start_screen_x, start_screen_y, end_screen_x, end_screen_y, duration=drag_duration)
                    if drag_coordinate_mode == "screen":
                        vector_label = "屏幕百分比向量" if drag_vector_mode == "screen_percent" else "像素向量"
                        self._log(
                            f"前台拖动地图: {start_label} ({start_screen_x}, {start_screen_y}) -> ({end_screen_x}, {end_screen_y}), "
                            f"{vector_label}=({self._format_drag_component(drag_vector_x)}, {self._format_drag_component(drag_vector_y)})"
                        )
                    else:
                        self._log(
                            f"前台拖动地图: {start_label} ({start_screen_x}, {start_screen_y}) -> ({end_screen_x}, {end_screen_y}), 逻辑方向=({drag_direction_x}, {drag_direction_y})"
                        )
                    return
                elif action == "drag_match_to_center":
                    self._action_drag_match_to_center(
                        step,
                        action_data,
                        x,
                        y,
                        recognition_center_x=recognition_center_x,
                        recognition_center_y=recognition_center_y,
                        template_width=template_width,
                        template_height=template_height,
                        resolved_target=resolved_target,
                        target_mode=target_mode,
                        drag_duration=drag_duration,
                        use_background=False,
                    )
                    return

                self._log(f"前台{self._action_name(action)} ({screen_x}, {screen_y})")

        except Exception as e:
            self._log(f"操作执行失败: {e}")
            import traceback
            self._log(f"[调试] 堆栈: {traceback.format_exc()}")
            if action == "drag_match_to_center":
                raise

    def _mark_blocked(self, coord_text: str):
        """标记坐标为不可攻击"""
        if not self._current_task:
            self._log("mark_blocked: 无当前任务上下文")
            return

        try:
            parts = [p.strip() for p in coord_text.split(",")]
            if len(parts) != 2:
                self._log(f"mark_blocked: 坐标格式错误，应为 'x,y'，实际: '{coord_text}'")
                return
            coord = [int(parts[0]), int(parts[1])]
        except ValueError:
            self._log(f"mark_blocked: 坐标解析失败: '{coord_text}'")
            return

        # 去重
        if coord not in self._current_task.blocked_coords:
            self._current_task.blocked_coords.append(coord)
            self._log(f"已标记坐标 ({coord[0]}, {coord[1]}) 为不可攻击，"
                       f"累计封锁 {len(self._current_task.blocked_coords)} 个")

            # 持久化保存
            if self._task_storage:
                self._task_storage.save(self._current_task)

            # 通知 GUI 更新
            if self.on_blocked_update:
                self.on_blocked_update(self._current_task)
        else:
            self._log(f"坐标 ({coord[0]}, {coord[1]}) 已在封锁列表中")

    def _action_modify_variable(self, step: SingleTask, action_data: Optional[dict] = None):
        """修改变量值"""
        action_data = action_data or {}
        var_name = self._resolve_params(action_data.get("var_name", step.modify_var_name))
        var_value = self._resolve_params(action_data.get("var_value", step.modify_var_value))
        if not var_name:
            self._log("modify_variable: 未指定变量名")
            return
        var_value = self._assign_variable_value(var_name, var_value)
        self._log(f"变量 {var_name} = {var_value}")
        self._save_persist()

    def _action_add_to_array(self, step: SingleTask, action_data: Optional[dict] = None):
        """向数组添加值"""
        action_data = action_data or {}
        items = action_data.get("items", step.add_to_array_items)
        for item in items:
            arr_name = self._resolve_params(item.get("array_name", ""))
            raw_value = self._resolve_named_or_literal_value(item.get("value", ""))
            if not arr_name:
                continue
            arr, added_values, error_messages, before_count, input_count = self._append_values_to_array(arr_name, raw_value)
            for error_message in error_messages:
                self._log(f"add_to_array: {error_message}")
            if input_count <= 1:
                if added_values:
                    self._log(f"数组 {arr_name} 添加 {added_values[0]}，当前 {len(arr)} 项")
                continue
            self._log(
                f"数组 {arr_name} 批量添加 {input_count} 项，实际新增 {max(0, len(arr) - before_count)} 项，当前 {len(arr)} 项"
            )
        self._save_persist()

    def _action_remove_target_coords(self, step: SingleTask, action_data: Optional[dict] = None):
        """从源坐标数组中删除单个或多个目标坐标。"""
        action_data = action_data or {}
        source_array_name = self._resolve_params(
            action_data.get("source_array", getattr(step, "remove_coord_source_array", ""))
        ).strip()
        remove_mode = normalize_remove_coord_mode(
            action_data.get("remove_mode", getattr(step, "remove_coord_mode", "single"))
        )
        raw_target_value = self._resolve_named_or_literal_value(
            action_data.get("target_value", getattr(step, "remove_coord_target_value", ""))
        )

        if not source_array_name:
            self._log("remove_target_coords: 未指定源坐标数组")
            return

        param = self._current_task.get_param(source_array_name) if self._current_task else None
        if param and param.param_type != "coord_array":
            self._log(f"remove_target_coords: '{source_array_name}' 不是坐标数组参数")
            return

        target_coords = self._coerce_coord_list(raw_target_value)
        if remove_mode == "single" and len(target_coords) > 1:
            target_coords = target_coords[:1]
        if not target_coords:
            self._log("remove_target_coords: 未解析出待删除坐标")
            return

        source_coords = self._get_coord_array_value(source_array_name)
        target_set = {(coord[0], coord[1]) for coord in target_coords}
        result_coords = [coord for coord in source_coords if (coord[0], coord[1]) not in target_set]
        removed_count = len(source_coords) - len(result_coords)
        mode_text = REMOVE_COORD_MODE_LABELS.get(remove_mode, remove_mode)

        if not self._set_coord_array_value(source_array_name, result_coords, deduplicate=False):
            self._log(f"remove_target_coords: '{source_array_name}' 不是坐标数组参数")
            return

        self._log(
            f"删除目标坐标: 来源='{source_array_name}'，模式={mode_text}，删除 {removed_count} 项，当前 {len(result_coords)} 项"
        )
        self._save_persist()

    def _action_clear_array_data(self, step: SingleTask, action_data: Optional[dict] = None):
        """清空数组数据"""
        action_data = action_data or {}
        array_name = self._resolve_params(action_data.get("array_name", step.clear_array_name))
        if not array_name:
            self._log("clear_array_data: 未指定目标数组")
            return

        param = self._current_task.get_param(array_name) if self._current_task else None
        is_array_param = bool(
            param and (
                param.param_type == "array"
                or param.param_type == "coord_array"
                or is_struct_array_param_type(param.param_type)
            )
        )
        runtime_value = self._runtime_vars.get(array_name)

        if is_array_param:
            param.value = []
            self._set_runtime_var(array_name, [])
            self._log(f"数组 {array_name} 已清空")
            self._save_persist()
            return

        if isinstance(runtime_value, list):
            self._set_runtime_var(array_name, [])
            self._log(f"运行时数组 {array_name} 已清空")
            self._save_persist()
            return

        self._log(f"clear_array_data: '{array_name}' 不是数组参数")

    def _action_recognition_to_logic_coord(self, step: SingleTask, action_data: Optional[dict] = None):
        """将当前识别结果中心点转换为逻辑坐标数组。"""
        action_data = action_data or {}
        csv_path = self._resolve_params(
            action_data.get("coordinate_csv_path", step.recognition_to_logic_csv_path)
        ).strip()
        anchor_logical_text = action_data.get(
            "anchor_logical_coord",
            step.recognition_to_logic_anchor_logical,
        )
        anchor_screen_text = action_data.get(
            "anchor_screen_coord",
            step.recognition_to_logic_anchor_screen,
        )
        result_array_name = self._resolve_params(
            action_data.get("result_array", step.recognition_to_logic_result_array)
        ).strip()

        if not csv_path or not anchor_logical_text or not anchor_screen_text or not result_array_name:
            self._log("recognition_to_logic_coord: 未指定 CSV、锚点逻辑坐标、锚点屏幕相对坐标或结果数组")
            return

        anchor_logical = self._get_number_pair_value(anchor_logical_text, integer=True)
        if anchor_logical is None:
            self._log(f"recognition_to_logic_coord: 无法解析锚点逻辑坐标 '{anchor_logical_text}'")
            return

        anchor_screen = self._get_number_pair_value(anchor_screen_text)
        if anchor_screen is None:
            self._log(f"recognition_to_logic_coord: 无法解析锚点屏幕相对坐标 '{anchor_screen_text}'")
            return

        client_bounds = self._get_target_window_client_bounds()
        if not client_bounds:
            self._log("recognition_to_logic_coord: 无法获取目标窗口客户区尺寸")
            return
        _window_left, _window_top, client_width, client_height = client_bounds

        recognition_centers = self._get_last_recognition_centers()
        if not recognition_centers:
            if self._set_coord_array_value(result_array_name, []):
                self._log(
                    f"识别坐标转逻辑坐标: 当前步骤没有可用识别结果，已清空 '{result_array_name}'"
                )
            else:
                self._log("recognition_to_logic_coord: 当前步骤没有可用识别结果")
            return

        try:
            base_profile, resolved_csv_path = self._load_coordinate_csv_profile(csv_path)
            runtime_profile = reanchor_relative_coordinate_profile(
                base_profile,
                anchor_logical,
                anchor_screen,
                name=f"{base_profile.name}-runtime",
            )
        except Exception as exc:
            self._log(f"recognition_to_logic_coord: 加载或拟合坐标 CSV 失败: {exc}")
            return

        distance_scale = 1.00
        converted_coords = []
        preview_lines = []
        skipped_lines = []
        client_size = (client_width, client_height)
        relative_points = [
            self._client_to_relative_point(center_x, center_y, client_size)
            for center_x, center_y in recognition_centers
        ]
        match_results = match_relative_points_to_anchor_logical(
            runtime_profile,
            relative_points,
            logical_origin=anchor_logical,
            max_distance_scale=distance_scale,
        )

        for (center_x, center_y), match_info in zip(recognition_centers, match_results):
            relative_x, relative_y = self._client_to_relative_point(center_x, center_y, client_size)
            relative_text = self._format_relative_point(relative_x, relative_y)
            if not match_info or not match_info.get("matched"):
                if len(skipped_lines) < 3:
                    if match_info:
                        anchor_relative = match_info.get("anchor_relative", (0.0, 0.0))
                        skipped_lines.append(
                            f"{relative_text} -> 最近CSV点"
                            f"{self._format_relative_point(anchor_relative[0], anchor_relative[1])}, "
                            f"距离={float(match_info.get('distance', 0.0)):.6f} > "
                            f"{float(match_info.get('max_distance', 0.0)):.6f}"
                        )
                    else:
                        skipped_lines.append(f"{relative_text} -> 未找到可用 CSV 锚点")
                continue

            logical_coord = [
                int(round(float(match_info["logical_coord"][0]))),
                int(round(float(match_info["logical_coord"][1]))),
            ]
            converted_coords.append(logical_coord)
            if len(preview_lines) < 5:
                anchor_relative = match_info.get("anchor_relative", (0.0, 0.0))
                preview_lines.append(
                    f"{relative_text} -> ({logical_coord[0]},{logical_coord[1]}), "
                    f"最近CSV点={self._format_relative_point(anchor_relative[0], anchor_relative[1])}, "
                    f"距离={float(match_info.get('distance', 0.0)):.6f}"
                )

        if not self._set_coord_array_value(result_array_name, converted_coords):
            self._log(f"recognition_to_logic_coord: '{result_array_name}' 不是坐标数组参数")
            return

        stored_coords = self._get_coord_array_value(result_array_name)
        preview_parts = []
        if preview_lines:
            preview_parts.append(f"示例: {'；'.join(preview_lines)}")
        if skipped_lines:
            preview_parts.append(f"超阈值跳过: {'；'.join(skipped_lines)}")
        self._log(
            f"识别坐标转逻辑坐标完成: 识别到 {len(recognition_centers)} 个中心，"
            f"命中 CSV {len(converted_coords)} 个，写入 '{result_array_name}' {len(stored_coords)} 个，"
            f"CSV={os.path.basename(resolved_csv_path)}，"
            f"锚点逻辑=({anchor_logical[0]:.3f},{anchor_logical[1]:.3f})，"
            f"锚点相对=({anchor_screen[0]:.6f},{anchor_screen[1]:.6f})，"
            f"规则=按相对坐标匹配最近 CSV 点并做整批唯一分配（距离上限=局部最近邻 x {distance_scale:.2f}，写入结果按逻辑坐标去重）"
            + (f"，{'；'.join(preview_parts)}" if preview_parts else "")
        )

    def _action_save_recognition_coords(self, step: SingleTask, action_data: Optional[dict] = None):
        """将当前识别结果中心点直接保存为坐标数组。"""
        action_data = action_data or {}
        result_array_name = self._resolve_params(
            action_data.get("result_array", getattr(step, "recognition_coord_result_array", ""))
        ).strip()

        if not result_array_name:
            self._log("save_recognition_coords: 未指定结果坐标数组")
            return

        recognition_centers = self._get_last_recognition_centers()
        if not recognition_centers:
            if self._set_coord_array_value(result_array_name, []):
                self._log(f"保存识别坐标: 当前步骤没有可用识别结果，已清空 '{result_array_name}'")
            else:
                self._log(f"save_recognition_coords: '{result_array_name}' 不是坐标数组参数")
            return

        coords = [[center_x, center_y] for center_x, center_y in recognition_centers]
        if not self._set_coord_array_value(result_array_name, coords):
            self._log(f"save_recognition_coords: '{result_array_name}' 不是坐标数组参数")
            return

        stored_coords = self._get_coord_array_value(result_array_name)
        preview = "；".join(self._format_coord_text(coord) for coord in stored_coords[:5])
        preview_text = f"，示例: {preview}" if preview else ""
        self._log(
            f"保存识别坐标完成: 识别到 {len(recognition_centers)} 个中心，"
            f"写入 '{result_array_name}' {len(stored_coords)} 个{preview_text}"
        )

    def _action_jump_to_step(self, step: SingleTask, action_data: Optional[dict] = None):
        """跳转到指定步骤"""
        action_data = action_data or {}
        target_id = action_data.get("target_id", step.jump_target_id)
        if not target_id:
            self._log("jump_to_step: 未指定目标步骤")
            return
        self._jump_target = target_id
        self._log(f"设置跳转目标: {target_id}")

    def _action_traverse_grid(self, step: SingleTask, action_data: Optional[dict] = None):
        """按指定网格模式遍历坐标，按固定邻接顺序做 BFS 从中心向外扩展。"""
        action_data = action_data or {}
        center_name = action_data.get("center_param", step.traverse_center_param)
        target_name = self._resolve_params(action_data.get("target_array", step.traverse_target_array)).strip()
        count = int(action_data.get("count", step.traverse_count) or 0)
        mode = normalize_grid_mode(action_data.get("mode", getattr(step, "traverse_mode", "hex")))
        mode_name = self._grid_mode_name(mode)
        log_prefix = f"遍历网格: 模式={mode_name}"

        if not center_name or not target_name:
            self._log(f"{log_prefix}，未指定中心坐标或目标数组")
            return

        if count <= 0:
            self._log(f"{log_prefix}，遍历数量必须大于 0")
            return

        center = self._get_coordinate_value(center_name)

        if center is None:
            self._log(f"{log_prefix}，无法获取中心坐标 '{center_name}'")
            return

        cx, cy = int(center[0]), int(center[1])
        self._log(f"{log_prefix}，中心({cx},{cy})，生成 {count} 个点")

        result = self._expand_grid_bfs((cx, cy), mode, max_count=count, include_center=True)

        self._log(f"{log_prefix}，生成了 {len(result)} 个坐标，已按邻接展开顺序排列")

        existing = self._get_coord_array_value(target_name)
        existing_set = {tuple(coord) for coord in existing}
        new_coords = []
        for coord in result:
            coord_tuple = tuple(coord)
            if coord_tuple not in existing_set:
                new_coords.append(coord)
                existing_set.add(coord_tuple)

        all_coords = existing + new_coords
        if not self._set_coord_array_value(target_name, all_coords):
            self._log(f"{log_prefix}，'{target_name}' 不是坐标数组参数")
            return

        self._log(
            f"{log_prefix}，遍历完成，新增 {len(new_coords)} 个点，数组 '{target_name}' 共 {len(all_coords)} 个坐标"
            f"（保持邻接展开顺序）"
        )

    def _action_traverse_hex(self, step: SingleTask, action_data: Optional[dict] = None):
        self._action_traverse_grid(step, action_data)

    def _action_get_surrounding_coords(self, step: SingleTask, action_data: Optional[dict] = None):
        """按指定网格模式获取目标坐标指定半径内的周围坐标，不包含中心点。"""
        action_data = action_data or {}
        target_name = action_data.get("target_coord", step.surround_target_coord or step.two_ring_target_coord)
        result_array_name = self._resolve_params(
            action_data.get("result_array", step.surround_result_array or step.two_ring_result_array)
        ).strip()
        radius = max(0, int(action_data.get("radius", getattr(step, "surround_radius", 2)) or 0))
        mode = normalize_grid_mode(action_data.get("mode", getattr(step, "surround_mode", "hex")))
        mode_name = self._grid_mode_name(mode)
        log_prefix = f"获取周围坐标: 模式={mode_name}"

        if not target_name or not result_array_name:
            self._log(f"{log_prefix}，未指定目标坐标或结果数组")
            return

        target = self._get_coordinate_value(target_name)
        if target is None:
            self._log(f"{log_prefix}，无法获取目标坐标 '{target_name}'")
            return

        center = (int(target[0]), int(target[1]))
        result_coords = self._expand_grid_bfs(center, mode, max_depth=radius, include_center=False)

        if not self._set_coord_array_value(result_array_name, result_coords):
            self._log(f"{log_prefix}，'{result_array_name}' 不是坐标数组参数")
            return

        preview = "；".join(f"({x},{y})" for x, y in result_coords[:6])
        self._log(
            f"{log_prefix}，完成，中心({center[0]},{center[1]})，半径={radius}，"
            f"共 {len(result_coords)} 个坐标，已写入 '{result_array_name}'"
            + (f"，前 6 个: {preview}" if preview else "")
        )

    def _action_get_two_ring_coords(self, step: SingleTask, action_data: Optional[dict] = None):
        merged_action = dict(action_data or {})
        merged_action.setdefault("radius", 2)
        merged_action.setdefault("mode", "hex")
        self._action_get_surrounding_coords(step, merged_action)

    def _action_find_road_path(self, step: SingleTask, action_data: Optional[dict] = None):
        """在指定网格模式的邻接规则下，从起始坐标数组中寻找一条通往目标坐标的最短路径。"""
        action_data = action_data or {}
        target_name = action_data.get("target_coord", step.path_target_coord)
        start_array_name = action_data.get("start_array", step.path_start_array)
        passable_array_name = action_data.get("passable_array", step.path_passable_array)
        result_array_name = self._resolve_params(action_data.get("result_array", step.path_result_array)).strip()
        mode = normalize_grid_mode(action_data.get("mode", getattr(step, "path_mode", "hex")))
        mode_name = self._grid_mode_name(mode)
        log_prefix = f"寻找铺路路径: 模式={mode_name}"

        if not target_name or not start_array_name or not passable_array_name or not result_array_name:
            self._log(f"{log_prefix}，未指定目标坐标、起始坐标数组、可通行坐标数组或结果数组")
            return

        target = self._get_coordinate_value(target_name)
        if target is None:
            self._log(f"{log_prefix}，无法获取目标坐标 '{target_name}'")
            return

        start_coords_raw = self._get_coord_array_value(start_array_name)
        if not start_coords_raw:
            self._log(f"{log_prefix}，起始坐标数组 '{start_array_name}' 为空或无有效坐标")
            self._set_coord_array_value(result_array_name, [])
            return

        passable_coords_raw = self._get_coord_array_value(passable_array_name)
        if not passable_coords_raw and target not in {tuple(item) for item in start_coords_raw}:
            self._log(f"{log_prefix}，可通行坐标数组 '{passable_array_name}' 为空")
            self._set_coord_array_value(result_array_name, [])
            return

        start_coords = []
        start_seen = set()
        for item in start_coords_raw:
            coord_tuple = tuple(item)
            if coord_tuple not in start_seen:
                start_coords.append(coord_tuple)
                start_seen.add(coord_tuple)

        target_tuple = (int(target[0]), int(target[1]))
        if target_tuple in start_seen:
            if not self._set_coord_array_value(result_array_name, []):
                self._log(f"{log_prefix}，'{result_array_name}' 不是坐标数组参数")
                return
            self._log(f"{log_prefix}，目标({target_tuple[0]},{target_tuple[1]}) 已在起始坐标数组中，结果为空")
            return

        passable_set = {tuple(item) for item in passable_coords_raw}
        allowed = set(start_coords)
        allowed.update(passable_set)
        allowed.add(target_tuple)

        queue = list(start_coords)
        visited = set(start_coords)
        parents = {}
        found = False
        qi = 0

        while qi < len(queue) and not found:
            current = queue[qi]
            qi += 1
            for neighbor in self._iter_grid_neighbors(current, mode):
                if neighbor in visited or neighbor not in allowed:
                    continue
                visited.add(neighbor)
                parents[neighbor] = current
                if neighbor == target_tuple:
                    found = True
                    break
                queue.append(neighbor)

        if not found:
            if not self._set_coord_array_value(result_array_name, []):
                self._log(f"{log_prefix}，'{result_array_name}' 不是坐标数组参数")
                return
            self._log(
                f"{log_prefix}，失败，起始数组 '{start_array_name}' 无法经 '{passable_array_name}' 连通到目标({target_tuple[0]},{target_tuple[1]})"
            )
            return

        path = [target_tuple]
        cursor = target_tuple
        while cursor not in start_seen:
            cursor = parents.get(cursor)
            if cursor is None:
                if not self._set_coord_array_value(result_array_name, []):
                    self._log(f"{log_prefix}，'{result_array_name}' 不是坐标数组参数")
                    return
                self._log(f"{log_prefix}，还原路径失败")
                return
            path.append(cursor)
        path.reverse()

        result_path = [list(coord) for coord in path[:-1]]
        if not self._set_coord_array_value(result_array_name, result_path):
            self._log(f"{log_prefix}，'{result_array_name}' 不是坐标数组参数")
            return

        start_coord = path[0]
        self._log(
            f"{log_prefix}，完成，起点({start_coord[0]},{start_coord[1]}) -> 目标({target_tuple[0]},{target_tuple[1]})，"
            f"路径 {len(result_path)} 个坐标（不含目标），已写入 '{result_array_name}'\n"
            f"{self._format_coord_path_log(path[:-1], target_tuple)}"
        )

    def _execute_on_fail_action(self, step: SingleTask):
        """执行识别失败时的操作列表"""
        if not step.on_fail_actions:
            # 向后兼容：如果没有新格式的actions，尝试使用旧格式
            action_type = step.on_fail_action_type if hasattr(step, 'on_fail_action_type') else ""
            if action_type and action_type != "none":
                self._log(f"使用旧格式失败操作: {action_type}")
                self._execute_legacy_fail_action(step)
            return
        
        self._log(f"执行 {len(step.on_fail_actions)} 个失败操作")
        recognition_context = self._get_last_recognition_action_context()
        
        for idx, action in enumerate(step.on_fail_actions):
            action = self._normalize_action_dict(action)
            action_type = action.get("type", "")
            self._log(f"失败操作 [{idx + 1}]: {action_type}")
            if self._action_requires_recognition_context(step, action, action_type) and recognition_context is None:
                self._log(
                    f"  失败操作: {self._action_name(action_type)} 依赖识别结果坐标，当前无可用识别结果，已跳过"
                )
                stop_sequence = False
            else:
                context = recognition_context or (0, 0, 0, 0)
                stop_sequence = self._execute_action_data(
                    step,
                    action,
                    context[0],
                    context[1],
                    context[2],
                    context[3],
                )

            if stop_sequence or self._check_stopped():
                break

            if idx < len(step.on_fail_actions) - 1:
                delay_seconds = float(action.get("delay", 0) or 0)
                if delay_seconds > 0:
                    self._log(f"  失败操作间等待 {delay_seconds:.2f} 秒")
                    self._interruptible_sleep(delay_seconds)
                    if self._check_stopped():
                        break

    def _execute_legacy_fail_action(self, step: SingleTask):
        """执行旧格式的失败操作（向后兼容）"""
        action = step.on_fail_action_type
        
        if action == "modify_variable":
            var_name = self._resolve_params(step.on_fail_modify_var_name)
            var_value = self._resolve_params(step.on_fail_modify_var_value)
            if not var_name:
                return
            var_value = self._assign_variable_value(var_name, var_value)
            self._log(f"失败操作: 变量 {var_name} = {var_value}")
            self._save_persist()
        
        elif action == "add_to_array":
            for item in step.on_fail_add_array_items:
                arr_name = self._resolve_params(item.get("array_name", ""))
                raw_value = self._resolve_named_or_literal_value(item.get("value", ""))
                if not arr_name:
                    continue
                arr, added_values, error_messages, before_count, input_count = self._append_values_to_array(arr_name, raw_value)
                for error_message in error_messages:
                    self._log(f"失败操作: add_to_array - {error_message}")
                if input_count <= 1:
                    if added_values:
                        self._log(f"失败操作: 数组 {arr_name} 添加 {added_values[0]}")
                    continue
                self._log(
                    f"失败操作: 数组 {arr_name} 批量添加 {input_count} 项，实际新增 {max(0, len(arr) - before_count)} 项，当前 {len(arr)} 项"
                )
            self._save_persist()
        
        elif action == "jump_to_step":
            target_id = step.on_fail_jump_target_id
            if target_id:
                self._jump_target = target_id
                self._log(f"失败操作: 设置跳转目标: {target_id}")
        
        elif action == "continue_loop":
            self._continue_loop = True
        
        elif action == "break_loop":
            self._break_loop = True

    def _clear_input_field(self, input_sim, step: SingleTask,
                           clear_method: Optional[str] = None,
                           clear_key_count: Optional[int] = None):
        """清除输入框旧内容"""
        method = clear_method if clear_method is not None else step.clear_method
        if method == "none":
            return
        elif method == "ctrl_a":
            input_sim.hotkey("ctrl", "a")
            time.sleep(0.05)
            self._log("清除方式: Ctrl+A 全选")
        elif method == "delete_backspace":
            count = clear_key_count if clear_key_count is not None else step.clear_key_count
            # 先按 End 确保光标在末尾，然后 Backspace 删除前面的内容
            input_sim.press("end")
            time.sleep(0.03)
            for _ in range(count):
                input_sim.press("backspace")
                time.sleep(0.02)
            # 再按 Home 到开头，Delete 删除后面可能残留的内容
            input_sim.press("home")
            time.sleep(0.03)
            for _ in range(count):
                input_sim.press("delete")
                time.sleep(0.02)
            self._log(f"清除方式: Delete+Backspace 各{count}次")

    def _load_isometric_config(self):
        """从 config.json 加载等距地图轴方向配置"""
        import json
        try:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "config.json"
            )
            if getattr(sys, 'frozen', False):
                config_path = os.path.join(
                    os.path.dirname(sys.executable), "config.json"
                )
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                iso = cfg.get("isometric", {})
                self._iso_axis_x = iso.get("axis_x", [-0.70, 0.72])
                self._iso_axis_y = iso.get("axis_y", [-0.11, 0.99])
                self._log(f"[配置] 等距地图轴: X={self._iso_axis_x}, Y={self._iso_axis_y}")
                return
        except Exception as e:
            self._log(f"[配置] 加载等距配置失败: {e}，使用默认值")
        # 默认值
        self._iso_axis_x = [-0.70, 0.72]
        self._iso_axis_y = [-0.11, 0.99]

    @staticmethod
    def _calc_isometric_drag(start_x: int, start_y: int, step: SingleTask,
                             iso_axis_x=None, iso_axis_y=None,
                             drag_direction_x=None, drag_direction_y=None,
                             drag_distance=None):
        """
        等距(isometric)地图：将逻辑坐标方向转换为屏幕拖动终点

        轴方向由 config.json 中的 isometric.axis_x / axis_y 定义：
          axis_x = [sx, sy] 表示逻辑 X+方向在屏幕上的单位向量
          axis_y = [sx, sy] 表示逻辑 Y+方向在屏幕上的单位向量

        镜头要向逻辑方向移动，鼠标需向相反方向拖动，因此取反。
        归一化后乘以 drag_distance 得到实际像素偏移。
        """
        import math

        if iso_axis_x is None:
            iso_axis_x = [-0.70, 0.72]
        if iso_axis_y is None:
            iso_axis_y = [-0.11, 0.99]

        game_dx = step.drag_direction_x if drag_direction_x is None else drag_direction_x
        game_dy = step.drag_direction_y if drag_direction_y is None else drag_direction_y
        drag_distance = step.drag_distance if drag_distance is None else drag_distance

        # 逻辑方向 → 屏幕方向（线性组合）
        screen_dx = game_dx * iso_axis_x[0] + game_dy * iso_axis_y[0]
        screen_dy = game_dx * iso_axis_x[1] + game_dy * iso_axis_y[1]

        # 取反：拖动方向与镜头移动方向相反
        drag_dx = -screen_dx
        drag_dy = -screen_dy

        magnitude = math.sqrt(drag_dx ** 2 + drag_dy ** 2)
        if magnitude > 0:
            end_x = int(start_x + (drag_dx / magnitude) * drag_distance)
            end_y = int(start_y + (drag_dy / magnitude) * drag_distance)
        else:
            end_x, end_y = start_x, start_y

        return end_x, end_y

    @staticmethod
    def _format_drag_component(value) -> str:
        text = f"{coerce_float(value, 0.0):.3f}".rstrip("0").rstrip(".")
        return "0" if text in ("", "-0") else text

    def _resolve_screen_drag_vector(self, step: SingleTask, action_data: dict):
        vector_mode = normalize_drag_vector_mode(
            action_data.get("drag_vector_mode", getattr(step, "drag_vector_mode", "pixel"))
        )
        legacy_x, legacy_y = derive_screen_drag_vector(
            action_data.get("drag_direction_x", getattr(step, "drag_direction_x", 0)),
            action_data.get("drag_direction_y", getattr(step, "drag_direction_y", 0)),
            action_data.get("drag_distance", getattr(step, "drag_distance", 200)),
        )
        vector_x = coerce_float(action_data.get("drag_vector_x", legacy_x), legacy_x)
        vector_y = coerce_float(action_data.get("drag_vector_y", legacy_y), legacy_y)
        return vector_mode, vector_x, vector_y

    def _calc_screen_drag(self, start_x: int, start_y: int,
                          drag_vector_mode: str, drag_vector_x: float, drag_vector_y: float):
        """按屏幕拖动向量计算拖动终点。"""
        vector_mode = normalize_drag_vector_mode(drag_vector_mode)
        screen_dx = coerce_float(drag_vector_x, 0.0)
        screen_dy = coerce_float(drag_vector_y, 0.0)

        if vector_mode == "screen_percent":
            screen_width, screen_height = self._get_screen_size()
            if screen_width <= 0 or screen_height <= 0:
                self._log("拖动向量: 无法获取屏幕尺寸，屏幕百分比向量按 0 位移处理")
                screen_dx, screen_dy = 0.0, 0.0
            else:
                screen_dx *= screen_width
                screen_dy *= screen_height

        return int(round(start_x + screen_dx)), int(round(start_y + screen_dy))

    @staticmethod
    def _normalize_drag_start_mode(mode: str) -> str:
        return "screen_percent" if mode == "screen_percent" else "recognition"

    @staticmethod
    def _coerce_drag_start_ratio(value, default: float = 0.5) -> float:
        return coerce_unit_ratio(value, default)

    def _get_screen_size(self):
        width = int(getattr(self._input, "screen_width", 0) or 0)
        height = int(getattr(self._input, "screen_height", 0) or 0)
        if width > 0 and height > 0:
            return width, height

        try:
            import ctypes
            user32 = ctypes.windll.user32
            return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
        except Exception:
            return 0, 0

    def _client_to_screen_point(self, client_x: int, client_y: int):
        client_rect = self._window_manager.get_client_rect(self._hwnd) if self._window_manager else None
        if client_rect:
            return int(client_rect[0] + client_x), int(client_rect[1] + client_y)
        return int(client_x), int(client_y)

    def _get_target_window_client_bounds(self):
        client_rect = self._window_manager.get_client_rect(self._hwnd) if self._window_manager else None
        if client_rect:
            left, top, right, bottom = client_rect
            return int(left), int(top), max(1, int(right - left)), max(1, int(bottom - top))

        try:
            import win32gui

            left, top = win32gui.ClientToScreen(self._hwnd, (0, 0))
            rect = win32gui.GetClientRect(self._hwnd)
            return int(left), int(top), max(1, int(rect[2] - rect[0])), max(1, int(rect[3] - rect[1]))
        except Exception:
            return None

    @staticmethod
    def _coerce_screen_ratio(value, default: float = 0.5) -> float:
        return coerce_unit_ratio(value, default)

    def _resolve_highlight_point(self, step: SingleTask, action_data: dict,
                                 action_x: int, action_y: int,
                                 recognition_center_x: Optional[int],
                                 recognition_center_y: Optional[int]):
        mode = normalize_point_position_mode(
            action_data.get("point_position_mode", getattr(step, "point_position_mode", "recognition"))
        )
        duration_ms = normalize_highlight_duration_ms(
            action_data.get("duration_ms", getattr(step, "highlight_duration_ms", 1200))
        )

        if mode == "recognition":
            if recognition_center_x is None or recognition_center_y is None or step.recognition_type == "none":
                self._log("显示红色原点失败：当前步骤没有可用的识别坐标")
                return None
            screen_x, screen_y = self._client_to_screen_point(action_x, action_y)
            detail = f"识别结果坐标 -> 屏幕({screen_x}, {screen_y})"
            return screen_x, screen_y, duration_ms, detail

        client_bounds = self._get_target_window_client_bounds()
        if not client_bounds:
            self._log("显示红色原点失败：无法获取目标窗口客户区位置")
            return None

        window_left, window_top, window_width, window_height = client_bounds

        if mode == "screen_percent":
            try:
                ratio_x, ratio_y = self._resolve_action_point_pair(step, action_data, mode)
            except RuntimeError as exc:
                self._log(f"显示红色原点失败：{exc}")
                return None
            ratio_x = self._coerce_screen_ratio(ratio_x, 0.5)
            ratio_y = self._coerce_screen_ratio(ratio_y, 0.5)
            client_x = int(round(window_width * ratio_x))
            client_y = int(round(window_height * ratio_y))
            screen_x = int(window_left + client_x)
            screen_y = int(window_top + client_y)
            detail = f"目标窗口百分比({ratio_x:.3f}, {ratio_y:.3f}) -> 客户区({client_x}, {client_y}) -> 屏幕({screen_x}, {screen_y})"
            return screen_x, screen_y, duration_ms, detail

        try:
            client_x, client_y = self._resolve_action_point_pair(step, action_data, mode)
        except RuntimeError as exc:
            self._log(f"显示红色原点失败：{exc}")
            return None
        screen_x = int(window_left + client_x)
        screen_y = int(window_top + client_y)
        detail = f"目标窗口坐标({client_x}, {client_y}) -> 屏幕({screen_x}, {screen_y})"
        return screen_x, screen_y, duration_ms, detail

    def _action_highlight_point(self, step: SingleTask, action_data: Optional[dict],
                                action_x: int, action_y: int,
                                recognition_center_x: Optional[int],
                                recognition_center_y: Optional[int]):
        action_data = action_data or {}
        resolved = self._resolve_highlight_point(
            step,
            action_data,
            action_x,
            action_y,
            recognition_center_x,
            recognition_center_y,
        )
        if not resolved:
            return

        screen_x, screen_y, duration_ms, detail = resolved
        if self.on_highlight_point:
            self.on_highlight_point(screen_x, screen_y, duration_ms)
        self._log(f"显示红色原点: {detail}")

    def _score_drag_tracking_candidates(self,
                                        results: List[Any],
                                        predicted_center_x: int,
                                        predicted_center_y: int,
                                        current_center_x: Optional[int] = None,
                                        current_center_y: Optional[int] = None,
                                        command_dx: int = 0,
                                        command_dy: int = 0,
                                        response_ratio_x: Optional[float] = None,
                                        response_ratio_y: Optional[float] = None,
                                        template_width: int = 0,
                                        template_height: int = 0):
        template_span = max(1, int(max(template_width or 0, template_height or 0, 1)))
        command_span = abs(int(command_dx)) + abs(int(command_dy))
        max_predicted_distance = max(template_span * 4, 48, int(command_span * 1.35 + 32))
        max_current_distance = max(template_span * 3, 40, int(command_span * 0.85 + 24))

        scored_results = []
        for result in results:
            center_x, center_y = result.center
            distance_to_predicted = abs(center_x - predicted_center_x) + abs(center_y - predicted_center_y)
            distance_to_current = None
            if current_center_x is not None and current_center_y is not None:
                distance_to_current = abs(center_x - current_center_x) + abs(center_y - current_center_y)

            plausible = True
            reject_reasons = []
            if distance_to_predicted > max_predicted_distance:
                if distance_to_current is None or distance_to_current > max_current_distance:
                    plausible = False
                    reject_reasons.append(
                        f"超出连续跟踪范围(参考={distance_to_predicted}, 当前={distance_to_current if distance_to_current is not None else '-'}, 上限={max_predicted_distance}/{max_current_distance})"
                    )

            if current_center_x is not None and command_dx != 0:
                observed_move_x = center_x - current_center_x
                if observed_move_x != 0 and observed_move_x * command_dx < 0:
                    plausible = False
                    reject_reasons.append("X方向与拖动方向相反")
                if abs(command_dx) >= 8 and response_ratio_x is not None:
                    observed_ratio_x = abs(observed_move_x / command_dx)
                    max_ratio_x = max(1.8, response_ratio_x * 2.4, response_ratio_x + 0.75)
                    if observed_ratio_x > max_ratio_x:
                        plausible = False
                        reject_reasons.append(f"X响应过大({observed_ratio_x:.2f}>{max_ratio_x:.2f})")

            if current_center_y is not None and command_dy != 0:
                observed_move_y = center_y - current_center_y
                if observed_move_y != 0 and observed_move_y * command_dy < 0:
                    plausible = False
                    reject_reasons.append("Y方向与拖动方向相反")
                if abs(command_dy) >= 8 and response_ratio_y is not None:
                    observed_ratio_y = abs(observed_move_y / command_dy)
                    max_ratio_y = max(1.8, response_ratio_y * 2.4, response_ratio_y + 0.75)
                    if observed_ratio_y > max_ratio_y:
                        plausible = False
                        reject_reasons.append(f"Y响应过大({observed_ratio_y:.2f}>{max_ratio_y:.2f})")

            scored_results.append(
                {
                    "result": result,
                    "distance_to_predicted": distance_to_predicted,
                    "distance_to_current": distance_to_current,
                    "plausible": plausible,
                    "reject_reasons": reject_reasons,
                }
            )

        scored_results.sort(
            key=lambda item: (
                0 if item["plausible"] else 1,
                item["distance_to_predicted"],
                item["distance_to_current"] if item["distance_to_current"] is not None else 10 ** 9,
                -item["result"].confidence,
            )
        )
        return scored_results, max_predicted_distance, max_current_distance

    def _recognize_drag_tracking_target(self, step: SingleTask, img,
                                        resolved_target: Any, target_mode: str,
                                        predicted_center_x: int,
                                        predicted_center_y: int,
                                        current_center_x: Optional[int] = None,
                                        current_center_y: Optional[int] = None,
                                        command_dx: int = 0,
                                        command_dy: int = 0,
                                        response_ratio_x: Optional[float] = None,
                                        response_ratio_y: Optional[float] = None,
                                        template_width: int = 0,
                                        template_height: int = 0):
        """拖动校正过程中的专用识别：优先跟踪最接近预期位置的同一目标。"""
        if step.recognition_type != "image" or target_mode != "single":
            return self._recognize(step, img, resolved_target, target_mode)

        if not self._recognition:
            return self._recognize(step, img, resolved_target, target_mode)

        target = "" if resolved_target is None else str(resolved_target).strip()
        if not target:
            return self._recognize(step, img, resolved_target, target_mode)

        target = self._resolve_template_path(target)
        target_label = self._short_target_label(target)
        match_mode = getattr(step, "image_match_mode", "template")
        recognition_roi = self._build_recognition_roi(step, img)
        if not os.path.isfile(target):
            return self._recognize(step, img, resolved_target, target_mode)

        results = self._recognition.find_all_templates(
            img,
            target,
            threshold=step.recognition_threshold,
            roi=recognition_roi,
            max_count=self._recognition_find_all_limit(1, keep_extra_matches=True),
            validate_color=step.validate_color_consistency,
            match_mode=match_mode,
        )
        if not results:
            return self._recognize(step, img, resolved_target, target_mode)

        scored_results, max_predicted_distance, max_current_distance = self._score_drag_tracking_candidates(
            results,
            predicted_center_x,
            predicted_center_y,
            current_center_x=current_center_x,
            current_center_y=current_center_y,
            command_dx=command_dx,
            command_dy=command_dy,
            response_ratio_x=response_ratio_x,
            response_ratio_y=response_ratio_y,
            template_width=template_width,
            template_height=template_height,
        )
        results = [item["result"] for item in scored_results]
        effective_threshold = float(step.recognition_threshold)
        recovery_note = ""

        if len(scored_results) > 1:
            self._log(
                f"[调试] 拖动跟踪候选 {len(results)} 个，参考中心=({predicted_center_x},{predicted_center_y})"
            )
            for index, item in enumerate(scored_results[:5], start=1):
                result = item["result"]
                result_debug = self._recognition.get_match_debug_info(
                    img,
                    target,
                    result,
                    validate_color=step.validate_color_consistency,
                    match_mode=match_mode,
                )
                status = "可跟踪"
                if not item["plausible"]:
                    status = "拒绝: " + " / ".join(item["reject_reasons"])
                self._log(
                    f"[调试]   跟踪#{index}: {self._format_match_debug_details(result_debug, step.recognition_threshold)}, "
                    f"中心=({result.center[0]},{result.center[1]}), 距参考={item['distance_to_predicted']}, "
                    f"距上一帧={item['distance_to_current'] if item['distance_to_current'] is not None else '-'}, {status}"
                )

        chosen_meta = next((item for item in scored_results if item["plausible"]), None)
        if chosen_meta is None:
            img_height, img_width = img.shape[:2]
            base_template_width = max(int(template_width or 0), 32)
            base_template_height = max(int(template_height or 0), 32)
            roi_half_width = max(96, int(base_template_width * 1.8), abs(int(command_dx)) * 2 + int(base_template_width * 0.8))
            roi_half_height = max(80, int(base_template_height * 1.8), abs(int(command_dy)) * 2 + int(base_template_height * 0.8))
            left = max(0, int(predicted_center_x - roi_half_width))
            top = max(0, int(predicted_center_y - roi_half_height))
            right = min(img_width, int(predicted_center_x + roi_half_width))
            bottom = min(img_height, int(predicted_center_y + roi_half_height))
            if right - left >= 12 and bottom - top >= 12:
                local_threshold = max(0.40, min(float(step.recognition_threshold), float(step.recognition_threshold) - 0.15))
                if local_threshold < float(step.recognition_threshold):
                    self._log(
                        f"[调试] 拖动跟踪启动局部恢复: ROI=({left},{top},{right-left},{bottom-top}), 阈值={local_threshold:.2f}"
                    )
                    local_roi = self._intersect_roi(
                        recognition_roi,
                        ROI(x=left, y=top, width=max(1, right - left), height=max(1, bottom - top)),
                    )
                    if recognition_roi is not None and local_roi is None:
                        local_results = []
                    else:
                        local_results = self._recognition.find_all_templates(
                            img,
                            target,
                            threshold=local_threshold,
                            roi=local_roi,
                            max_count=30,
                            validate_color=step.validate_color_consistency,
                            match_mode=match_mode,
                        )
                    if local_results:
                        local_scored_results, local_max_predicted_distance, local_max_current_distance = self._score_drag_tracking_candidates(
                            local_results,
                            predicted_center_x,
                            predicted_center_y,
                            current_center_x=current_center_x,
                            current_center_y=current_center_y,
                            command_dx=command_dx,
                            command_dy=command_dy,
                            response_ratio_x=response_ratio_x,
                            response_ratio_y=response_ratio_y,
                            template_width=template_width,
                            template_height=template_height,
                        )
                        self._log(
                            f"[调试] 拖动局部恢复候选 {len(local_scored_results)} 个，参考中心=({predicted_center_x},{predicted_center_y})"
                        )
                        for index, item in enumerate(local_scored_results[:5], start=1):
                            result = item["result"]
                            result_debug = self._recognition.get_match_debug_info(
                                img,
                                target,
                                result,
                                validate_color=step.validate_color_consistency,
                                match_mode=match_mode,
                            )
                            status = "可跟踪"
                            if not item["plausible"]:
                                status = "拒绝: " + " / ".join(item["reject_reasons"])
                            self._log(
                                f"[调试]   局部#{index}: {self._format_match_debug_details(result_debug, local_threshold)}, "
                                f"中心=({result.center[0]},{result.center[1]}), 距参考={item['distance_to_predicted']}, "
                                f"距上一帧={item['distance_to_current'] if item['distance_to_current'] is not None else '-'}, {status}"
                            )

                        local_chosen_meta = next((item for item in local_scored_results if item["plausible"]), None)
                        if local_chosen_meta is not None:
                            chosen_meta = local_chosen_meta
                            scored_results = local_scored_results
                            results = [item["result"] for item in local_scored_results]
                            max_predicted_distance = local_max_predicted_distance
                            max_current_distance = local_max_current_distance
                            effective_threshold = local_threshold
                            recovery_note = f"，局部恢复阈值={local_threshold:.2f}"
                            self._log("[调试] 拖动局部恢复成功，继续跟踪原目标")

        if chosen_meta is None:
            best_confidence = max((result.confidence for result in results), default=None)
            self._set_last_recognition_metrics(
                best_confidence,
                step.recognition_threshold,
                False,
                source=f"目标[{target_label}]",
                note=(
                    f"拖动跟踪未找到合理连续目标，参考中心=({predicted_center_x},{predicted_center_y})，"
                    f"连续性上限={max_predicted_distance}/{max_current_distance}"
                ),
            )

            self._log(
                f"[调试] 拖动跟踪未找到合理连续目标，已拒绝本轮全部候选，参考中心=({predicted_center_x},{predicted_center_y})"
            )
            return None

        chosen = chosen_meta["result"]
        chosen_debug = self._recognition.get_match_debug_info(
            img,
            target,
            chosen,
            validate_color=step.validate_color_consistency,
            match_mode=match_mode,
        )
        self._set_last_recognition_metrics(
            chosen.confidence,
            effective_threshold,
            True,
            source=f"目标[{target_label}]",
            note=f"拖动跟踪，参考中心=({predicted_center_x},{predicted_center_y}){recovery_note}",
            template_confidence=chosen_debug.get("template_confidence", chosen.confidence),
            color_confidence=chosen_debug.get("color_confidence"),
            color_validation_enabled=chosen_debug.get("color_validation_enabled", False),
            color_validation_applied=chosen_debug.get("color_validation_applied", False),
            color_validation_threshold=chosen_debug.get("color_validation_threshold"),
            color_note=chosen_debug.get("color_note", ""),
        )
        self._log(
            f"[调试] 拖动跟踪选择: {self._format_match_debug_details(chosen_debug, effective_threshold)}, 中心=({chosen.center[0]},{chosen.center[1]})"
        )
        region_label = os.path.basename(target) or target_label
        self._set_last_recognition_regions(
            [
                {
                    "x": result.x,
                    "y": result.y,
                    "width": result.width,
                    "height": result.height,
                    "recognition_type": "image",
                    "label": region_label,
                }
                for result in results
            ],
            selected_index=0,
        )
        return (chosen.center[0], chosen.center[1], chosen.width, chosen.height)

    def _resolve_drag_center_target(self):
        """返回目标窗口中心点的客户区/屏幕坐标。"""
        client_rect = self._window_manager.get_client_rect(self._hwnd) if self._window_manager else None
        if client_rect:
            left, top, right, bottom = client_rect
            width = max(1, int(right - left))
            height = max(1, int(bottom - top))
            client_x = width // 2
            client_y = height // 2
            return client_x, client_y, left + client_x, top + client_y, "目标窗口客户区中心"

        try:
            import win32gui

            rect = win32gui.GetClientRect(self._hwnd)
            width = max(1, int(rect[2]))
            height = max(1, int(rect[3]))
            client_x = width // 2
            client_y = height // 2
            return client_x, client_y, client_x, client_y, "目标窗口客户区中心"
        except Exception:
            screen_width, screen_height = self._get_screen_size()
            if screen_width > 0 and screen_height > 0:
                screen_x = screen_width // 2
                screen_y = screen_height // 2
                return screen_x, screen_y, screen_x, screen_y, "屏幕中心"

        self._log("拖动目标中心: 无法获取窗口或屏幕尺寸，回退到原点")
        return 0, 0, 0, 0, "原点"

    def _action_drag_match_to_center(self, step: SingleTask, action_data: dict,
                                     action_x: int, action_y: int,
                                     recognition_center_x: Optional[int],
                                     recognition_center_y: Optional[int],
                                     template_width: int, template_height: int,
                                     resolved_target: Any, target_mode: str,
                                     drag_duration: float, use_background: bool):
        """拖动识别目标到窗口中心，持续闭环校正直到进入允许误差范围。"""
        if recognition_center_x is None or recognition_center_y is None or step.recognition_type == "none":
            self._log("拖动识别目标到屏幕中心: 当前步骤未提供有效识别结果，已跳过")
            return

        tolerance_px = normalize_center_tolerance_px(
            action_data.get("center_tolerance_px", getattr(step, "center_tolerance_px", 1))
        )
        settle_delay = max(0.0, float(action_data.get("center_settle_delay", 0.03) or 0.03))
        max_corrections = max(1, int(float(action_data.get("max_corrections", 120) or 120)))
        stagnation_limit = max(3, int(float(action_data.get("center_stagnation_limit", 6) or 6)))
        client_center_x, client_center_y, _screen_center_x, _screen_center_y, center_label = self._resolve_drag_center_target()

        current_center_x = int(recognition_center_x)
        current_center_y = int(recognition_center_y)
        pointer_x = int(action_x)
        pointer_y = int(action_y)
        response_ratio_x = None
        response_ratio_y = None
        stagnation_count = 0
        attempt = 0

        while True:
            if self._check_stopped():
                return

            delta_x = int(client_center_x - current_center_x)
            delta_y = int(client_center_y - current_center_y)
            if abs(delta_x) <= tolerance_px and abs(delta_y) <= tolerance_px:
                if attempt == 0:
                    self._log(
                        f"拖动识别目标到屏幕中心: 目标已在{center_label}允许误差范围内，"
                        f"偏移=({delta_x}, {delta_y})，允许误差={tolerance_px}px"
                    )
                else:
                    self._log(
                        f"拖动识别目标到屏幕中心: 已校正到{center_label}允许误差范围内，"
                        f"总校正次数={attempt}，剩余偏移=({delta_x}, {delta_y})，允许误差={tolerance_px}px"
                    )
                return

            attempt += 1
            if attempt > max_corrections:
                raise RuntimeError(
                    f"拖动识别目标到屏幕中心失败：校正 {max_corrections} 次后仍未进入允许误差范围，"
                    f"当前偏移=({delta_x}, {delta_y})，允许误差={tolerance_px}px"
                )

            command_dx = delta_x
            command_dy = delta_y
            if response_ratio_x is not None and delta_x != 0:
                command_dx = int(round(delta_x / response_ratio_x))
            if response_ratio_y is not None and delta_y != 0:
                command_dy = int(round(delta_y / response_ratio_y))

            # 目标程序内拖动在接近中心时可能对 1px 指令没有响应。
            # 一旦检测到停滞，逐步放大这类微调指令，强制探测出最小有效拖动量。
            if stagnation_count > 0:
                probe_scale = min(stagnation_count + 1, 8)
                if delta_x != 0 and abs(delta_x) <= 3:
                    command_dx = (1 if delta_x > 0 else -1) * max(abs(command_dx), probe_scale)
                if delta_y != 0 and abs(delta_y) <= 3:
                    command_dy = (1 if delta_y > 0 else -1) * max(abs(command_dy), probe_scale)

            if command_dx == 0 and delta_x != 0:
                command_dx = 1 if delta_x > 0 else -1
            if command_dy == 0 and delta_y != 0:
                command_dy = 1 if delta_y > 0 else -1

            command_dx = int(max(-1200, min(1200, command_dx)))
            command_dy = int(max(-1200, min(1200, command_dy)))

            attempt_duration = float(drag_duration)
            if attempt > 1:
                attempt_duration = max(0.03, min(drag_duration * 0.25, 0.12))
                if max(abs(command_dx), abs(command_dy)) <= 3:
                    attempt_duration = min(attempt_duration, 0.06)

            self._do_single_drag(
                pointer_x,
                pointer_y,
                command_dx,
                command_dy,
                attempt_duration,
                use_background,
                f"校正#{attempt}",
                current_center_x,
                current_center_y,
                delta_x,
                delta_y,
            )
            pointer_x += command_dx
            pointer_y += command_dy

            if settle_delay > 0:
                self._interruptible_sleep(settle_delay)
                if self._check_stopped():
                    return

            predicted_center_x = current_center_x + int(round(
                command_dx * (response_ratio_x if response_ratio_x is not None else 1.0)
            ))
            predicted_center_y = current_center_y + int(round(
                command_dy * (response_ratio_y if response_ratio_y is not None else 1.0)
            ))

            retry_delays = (0.0, max(settle_delay, 0.08), max(settle_delay * 2, 0.16))
            next_result = None
            for retry_index, extra_wait in enumerate(retry_delays, start=1):
                if retry_index > 1:
                    self._log(
                        f"[调试] 第{attempt}次校正后未找到合理连续目标，补等 {extra_wait:.2f} 秒后重试识别 "
                        f"({retry_index - 1}/{len(retry_delays) - 1})"
                    )
                    self._interruptible_sleep(extra_wait)
                    if self._check_stopped():
                        return

                img = self._capture_window(step.use_background)
                if img is None:
                    raise RuntimeError(f"拖动识别目标到屏幕中心失败：第{attempt}次校正后截图失败")

                next_result = self._recognize_drag_tracking_target(
                    step,
                    img,
                    resolved_target,
                    target_mode,
                    predicted_center_x,
                    predicted_center_y,
                    current_center_x=current_center_x,
                    current_center_y=current_center_y,
                    command_dx=command_dx,
                    command_dy=command_dy,
                    response_ratio_x=response_ratio_x,
                    response_ratio_y=response_ratio_y,
                    template_width=template_width,
                    template_height=template_height,
                )
                if next_result is not None:
                    break

            compare_text = self._format_last_recognition_metrics()
            if next_result is None:
                suffix = f"，{compare_text}" if compare_text else ""
                raise RuntimeError(f"拖动识别目标到屏幕中心失败：第{attempt}次校正后重新识别失败{suffix}")

            prev_center_x = current_center_x
            prev_center_y = current_center_y
            current_center_x = int(next_result[0])
            current_center_y = int(next_result[1])
            template_width = max(1, int(next_result[2] or template_width or 1))
            template_height = max(1, int(next_result[3] or template_height or 1))

            moved_x = current_center_x - prev_center_x
            moved_y = current_center_y - prev_center_y
            if abs(command_dx) >= 1 and moved_x * command_dx > 0:
                observed_x = abs(moved_x / command_dx)
                if 0.05 <= observed_x <= 4.0:
                    if response_ratio_x is None:
                        response_ratio_x = observed_x
                    else:
                        response_ratio_x = response_ratio_x * 0.35 + observed_x * 0.65
            if abs(command_dy) >= 1 and moved_y * command_dy > 0:
                observed_y = abs(moved_y / command_dy)
                if 0.05 <= observed_y <= 4.0:
                    if response_ratio_y is None:
                        response_ratio_y = observed_y
                    else:
                        response_ratio_y = response_ratio_y * 0.35 + observed_y * 0.65

            if current_center_x == prev_center_x and current_center_y == prev_center_y:
                stagnation_count += 1
            else:
                stagnation_count = 0

            if stagnation_count >= stagnation_limit:
                raise RuntimeError(
                    f"拖动识别目标到屏幕中心失败：连续 {stagnation_limit} 次校正后识别中心不再变化，当前偏移=({client_center_x - current_center_x}, {client_center_y - current_center_y})"
                )

    def _do_single_drag(self, start_client_x: int, start_client_y: int,
                        dx: int, dy: int, duration: float,
                        use_background: bool, label: str,
                        rec_cx: int, rec_cy: int,
                        offset_x: int, offset_y: int):
        """执行一次完整拖动（按下 → 移动 → 松开）。"""
        end_client_x = start_client_x + dx
        end_client_y = start_client_y + dy
        if use_background:
            self._bg_input = self._bg_input_class(self._hwnd)
            self._bg_input.drag(start_client_x, start_client_y,
                                end_client_x, end_client_y, duration=duration)
            self._log(
                f"后台拖动识别目标到屏幕中心({label}): 起点=({start_client_x}, {start_client_y})，"
                f"终点=({end_client_x}, {end_client_y})，识别中心=({rec_cx}, {rec_cy})，偏移=({offset_x}, {offset_y})"
            )
        else:
            client_rect = self._window_manager.get_client_rect(self._hwnd) if self._window_manager else None
            if client_rect:
                sx = client_rect[0] + start_client_x
                sy = client_rect[1] + start_client_y
                ex = client_rect[0] + end_client_x
                ey = client_rect[1] + end_client_y
            else:
                sx, sy = start_client_x, start_client_y
                ex, ey = end_client_x, end_client_y
            self._input.drag(sx, sy, ex, ey, duration=duration)
            self._log(
                f"前台拖动识别目标到屏幕中心({label}): 起点=({sx}, {sy})，"
                f"终点=({ex}, {ey})，识别中心=({rec_cx}, {rec_cy})，偏移=({offset_x}, {offset_y})"
            )

    def _resolve_drag_center_point(self, use_background: bool):
        """获取拖动到中心动作的终点坐标。"""
        client_x, client_y, screen_x, screen_y, label = self._resolve_drag_center_target()
        if use_background:
            return client_x, client_y, label
        return screen_x, screen_y, label

    def _resolve_drag_start_point(self, step: SingleTask, action_data: dict,
                                  recognition_x: int, recognition_y: int,
                                  use_background: bool):
        start_mode = self._normalize_drag_start_mode(
            action_data.get("drag_start_mode", getattr(step, "drag_start_mode", "recognition"))
        )

        if start_mode != "screen_percent":
            if step.recognition_type == "none":
                self._log("拖动起点使用识别坐标，但当前步骤未配置识别，默认起点为 (0, 0)")
            if use_background:
                return int(recognition_x), int(recognition_y), "识别坐标"

            client_rect = self._window_manager.get_client_rect(self._hwnd) if self._window_manager else None
            if client_rect:
                return int(client_rect[0] + recognition_x), int(client_rect[1] + recognition_y), "识别坐标"
            return int(recognition_x), int(recognition_y), "识别坐标"

        ratio_x = self._coerce_drag_start_ratio(
            action_data.get("drag_start_x", getattr(step, "drag_start_x", 0.5)),
            0.5,
        )
        ratio_y = self._coerce_drag_start_ratio(
            action_data.get("drag_start_y", getattr(step, "drag_start_y", 0.5)),
            0.5,
        )
        client_bounds = self._get_target_window_client_bounds()
        if not client_bounds:
            self._log("拖动起点: 无法获取目标窗口客户区，回退到识别坐标")
            if use_background:
                return int(recognition_x), int(recognition_y), "识别坐标"
            client_rect = self._window_manager.get_client_rect(self._hwnd) if self._window_manager else None
            if client_rect:
                return int(client_rect[0] + recognition_x), int(client_rect[1] + recognition_y), "识别坐标"
            return int(recognition_x), int(recognition_y), "识别坐标"

        window_left, window_top, window_width, window_height = client_bounds
        client_x = int(round((window_width - 1) * ratio_x))
        client_y = int(round((window_height - 1) * ratio_y))
        label = f"目标窗口比例=({ratio_x:.3f}, {ratio_y:.3f})"

        if use_background:
            return client_x, client_y, label

        screen_x = int(window_left + client_x)
        screen_y = int(window_top + client_y)
        return screen_x, screen_y, label

    def _action_name(self, action: str) -> str:
        """获取操作名称"""
        action = normalize_action_type(action)
        names = {
            "click": "单击",
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
            "mark_blocked": "标记不能攻击",
            "modify_variable": "修改变量",
            "add_to_array": "添加到数组",
            "save_recognition_coords": "保存识别坐标到坐标数组",
            "remove_target_coords": "删除目标坐标",
            "clear_array_data": "清空数组数据",
            "recognition_to_logic_coord": "识别坐标转逻辑坐标",
            "jump_to_step": "跳转步骤",
            "traverse_grid": "按模式遍历网格",
            "get_surrounding_coords": "按半径获取周围坐标",
            "find_road_path": "寻找铺路路径",
            "continue_loop": "继续循环",
            "break_loop": "跳出循环",
        }
        return names.get(action, action)

    def _interruptible_sleep(self, seconds: float):
        """可中断的等待"""
        end_time = time.time() + seconds
        while time.time() < end_time:
            if self._check_stopped():
                return
            time.sleep(min(0.1, end_time - time.time()))
