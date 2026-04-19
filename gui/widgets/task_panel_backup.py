"""
计划任务管理面板
提供计划任务的新增、编辑、删除、执行功能的完整GUI
"""

import copy
import os
import sys
import shutil
from typing import Optional, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton,
    QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox,
    QCheckBox, QTextEdit, QListWidget, QListWidgetItem, QSplitter,
    QMessageBox, QInputDialog, QFileDialog, QDialog, QDialogButtonBox,
    QFormLayout, QScrollArea, QFrame, QApplication, QMenu,
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer, QObject
from PySide6.QtGui import QAction

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from task.models import PlanTask, SingleTask
from task.storage import TaskStorage
from task.executor import TaskExecutor, TaskState


class _ExecutorSignalBridge(QObject):
    """
    用于将执行器回调（子线程）安全转发到主线程的信号桥。
    Qt 信号跨线程时自动使用 QueuedConnection，保证线程安全。
    """
    sig_log = Signal(str)
    sig_task_started = Signal(str)          # task_name
    sig_task_finished = Signal(str, bool)   # task_name, success
    sig_step_started = Signal(int, str)     # index, step_name
    sig_step_retried = Signal(int, str, int)  # index, step_name, retry_count


class StepEditDialog(QDialog):
    """单一步骤编辑对话框"""

    def __init__(self, step: SingleTask = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑步骤" if step else "新增步骤")
        self.setMinimumWidth(450)

        self._step = step or SingleTask()
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()

        # 步骤名称
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("例如：点击开始按钮")
        form.addRow("步骤名称:", self._name_edit)

        # 识别类型
        self._recognition_type = QComboBox()
        self._recognition_type.addItem("图像识别 (模板匹配)", "image")
        self._recognition_type.addItem("文字识别 (OCR)", "text")
        self._recognition_type.addItem("多图像识别 (任一匹配)", "multi_image")
        self._recognition_type.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("识别类型:", self._recognition_type)

        # 识别目标
        target_layout = QHBoxLayout()
        self._target_edit = QLineEdit()
        self._target_edit.setPlaceholderText("选择模板图片文件路径")
        target_layout.addWidget(self._target_edit)
        self._browse_btn = QPushButton("浏览...")
        self._browse_btn.setVisible(True)
        self._browse_btn.clicked.connect(self._browse_template)
        target_layout.addWidget(self._browse_btn)
        form.addRow("识别目标:", target_layout)

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

        # 操作类型
        self._action_type = QComboBox()
        self._action_type.addItem("左键单击", "click")
        self._action_type.addItem("左键双击", "double_click")
        self._action_type.addItem("右键单击", "right_click")
        self._action_type.addItem("输入文本", "input_text")
        self._action_type.addItem("按键/组合键", "press_key")
        self._action_type.addItem("拖动地图", "drag_map")
        self._action_type.addItem("标记不能攻击", "mark_blocked")
        self._action_type.addItem("不执行操作 (仅等待识别)", "none")
        self._action_type.currentIndexChanged.connect(self._on_action_type_changed)
        form.addRow("操作类型:", self._action_type)

        # 输入文本内容（仅 input_text 时可见）
        self._input_text_edit = QLineEdit()
        self._input_text_edit.setPlaceholderText("输入要填写的文本内容，如: 990")
        self._input_text_label = QLabel("输入内容:")
        form.addRow(self._input_text_label, self._input_text_edit)
        self._input_text_label.setVisible(False)
        self._input_text_edit.setVisible(False)

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

        # 偏移值
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
        form.addRow("偏移值:", offset_layout)

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

        # 确定/取消
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_action_type_changed(self, index=0):
        """操作类型变更 — 控制输入文本/按键/拖动字段的显隐"""
        action = self._action_type.currentData()
        is_input_text = action == "input_text"
        is_press_key = action == "press_key"
        is_drag_map = action == "drag_map"
        is_mark_blocked = action == "mark_blocked"

        # 输入文本和标记封锁都使用 input_text 字段
        show_input = is_input_text or is_mark_blocked
        self._input_text_label.setVisible(show_input)
        self._input_text_edit.setVisible(show_input)
        if is_mark_blocked:
            self._input_text_label.setText("封锁坐标:")
            self._input_text_edit.setPlaceholderText("格式: {x},{y}（支持参数替换）")
        elif is_input_text:
            self._input_text_label.setText("输入内容:")
            self._input_text_edit.setPlaceholderText("输入要填写的文本内容，如: 990")
        self._clear_method_label.setVisible(is_input_text)
        self._clear_method.setVisible(is_input_text)
        # 删除次数的显隐取决于清除方式
        self._on_clear_method_changed()

        # 按键相关
        self._press_keys_label.setVisible(is_press_key)
        self._press_keys_edit.setVisible(is_press_key)

        # 拖动地图相关
        self._drag_dir_label.setVisible(is_drag_map)
        self._drag_dir_x_spin.setVisible(is_drag_map)
        self._drag_dir_y_spin.setVisible(is_drag_map)
        self._drag_distance_label.setVisible(is_drag_map)
        self._drag_distance_spin.setVisible(is_drag_map)
        self._drag_duration_label.setVisible(is_drag_map)
        self._drag_duration_spin.setVisible(is_drag_map)

        # 点击偏移只在有点击动作时有意义
        has_click = action in ("click", "double_click", "right_click", "input_text")
        self._offset_x_spin.setEnabled(has_click)
        self._offset_y_spin.setEnabled(has_click)

    def _on_clear_method_changed(self, index=0):
        """清除方式变更 — 控制删除次数的显隐"""
        is_input_text = self._action_type.currentData() == "input_text"
        is_del_bs = self._clear_method.currentData() == "delete_backspace"
        show = is_input_text and is_del_bs
        self._clear_key_count_label.setVisible(show)
        self._clear_key_count_spin.setVisible(show)

    def _on_type_changed(self, index):
        """识别类型变更"""
        recognition_type = self._recognition_type.currentData()
        is_image = recognition_type == "image"
        is_multi_image = recognition_type == "multi_image"
        is_any_image = is_image or is_multi_image
        self._browse_btn.setVisible(is_any_image)
        self._exact_match.setVisible(not is_any_image)
        # 匹配序号和多匹配只对单图像识别有意义
        self._match_index_label.setVisible(is_image)
        self._match_index_spin.setVisible(is_image)
        self._has_multiple_matches_label.setVisible(is_image)
        self._has_multiple_matches.setVisible(is_image)
        if is_image:
            self._target_edit.setPlaceholderText("选择模板图片文件路径")
            self._threshold_spin.setValue(0.8)
            self._threshold_spin.setToolTip("图像识别的最低置信度，建议0.75-0.9。值越低越容易误匹配")
        elif is_multi_image:
            self._target_edit.setPlaceholderText("多张图片路径，用 | 分隔（点击浏览可多选）")
            self._threshold_spin.setValue(0.8)
            self._threshold_spin.setToolTip("多图像识别阈值，任一图片匹配即成功")
        else:
            self._target_edit.setPlaceholderText("输入要识别的文字")
            self._threshold_spin.setValue(0.5)
            self._threshold_spin.setToolTip("文字识别的最低置信度，建议0.5-0.7。值越低越容易匹配但可能误识别")

    def _browse_template(self):
        """浏览模板图片，自动复制到 pic/ 目录并存储相对路径"""
        is_multi = self._recognition_type.currentData() == "multi_image"

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

    def _load_data(self):
        """加载步骤数据到控件"""
        s = self._step
        self._name_edit.setText(s.name if s.name != "未命名步骤" else "")

        # 识别类型
        idx = self._recognition_type.findData(s.recognition_type)
        if idx >= 0:
            self._recognition_type.setCurrentIndex(idx)

        self._target_edit.setText(s.recognition_target)
        self._exact_match.setChecked(s.exact_match)
        self._threshold_spin.setValue(s.recognition_threshold)
        self._match_index_spin.setValue(s.match_index)
        self._has_multiple_matches.setChecked(s.has_multiple_matches)

        # 操作类型
        idx = self._action_type.findData(s.action_type)
        if idx >= 0:
            self._action_type.setCurrentIndex(idx)

        self._use_background.setChecked(s.use_background)
        self._timeout_spin.setValue(s.timeout)
        self._retry_spin.setValue(s.retry_interval)
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

        # 拖动地图字段
        self._drag_dir_x_spin.setValue(s.drag_direction_x)
        self._drag_dir_y_spin.setValue(s.drag_direction_y)
        self._drag_distance_spin.setValue(s.drag_distance)
        self._drag_duration_spin.setValue(s.drag_duration)

        # 刷新显隐状态
        self._on_type_changed(self._recognition_type.currentIndex())
        self._on_action_type_changed()
        
        # 重新设置阈值，避免被 _on_type_changed 覆盖
        self._threshold_spin.setValue(s.recognition_threshold)

    def get_step(self) -> SingleTask:
        """获取编辑后的步骤"""
        name = self._name_edit.text().strip()
        if not name:
            name = "未命名步骤"

        self._step.name = name
        self._step.recognition_type = self._recognition_type.currentData()
        self._step.recognition_target = self._target_edit.text().strip()
        self._step.exact_match = self._exact_match.isChecked()
        self._step.recognition_threshold = self._threshold_spin.value()
        self._step.match_index = self._match_index_spin.value()
        self._step.has_multiple_matches = self._has_multiple_matches.isChecked()
        self._step.action_type = self._action_type.currentData()
        self._step.input_text = self._input_text_edit.text().strip()
        self._step.press_keys = self._press_keys_edit.text().strip()
        self._step.clear_method = self._clear_method.currentData()
        self._step.clear_key_count = self._clear_key_count_spin.value()
        self._step.drag_direction_x = self._drag_dir_x_spin.value()
        self._step.drag_direction_y = self._drag_dir_y_spin.value()
        self._step.drag_distance = self._drag_distance_spin.value()
        self._step.drag_duration = self._drag_duration_spin.value()
        self._step.use_background = self._use_background.isChecked()
        self._step.timeout = self._timeout_spin.value()
        self._step.retry_interval = self._retry_spin.value()
        self._step.click_offset_x = self._offset_x_spin.value()
        self._step.click_offset_y = self._offset_y_spin.value()
        self._step.delay_after = self._delay_after_spin.value()
        return self._step


class TaskEditDialog(QDialog):
    """计划任务编辑对话框"""

    def __init__(self, task: PlanTask = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑计划任务" if task else "新建计划任务")
        self.setMinimumSize(600, 500)

        self._task = task or PlanTask()
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # === 任务基本信息 ===
        info_group = QGroupBox("任务信息")
        info_layout = QFormLayout(info_group)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("输入任务名称")
        info_layout.addRow("任务名称:", self._name_edit)

        self._desc_edit = QLineEdit()
        self._desc_edit.setPlaceholderText("可选的任务描述")
        info_layout.addRow("任务描述:", self._desc_edit)

        self._loop_spin = QSpinBox()
        self._loop_spin.setRange(0, 9999)
        self._loop_spin.setValue(1)
        self._loop_spin.setSpecialValueText("无限循环")
        info_layout.addRow("循环次数:", self._loop_spin)

        layout.addWidget(info_group)

        # === 任务参数 ===
        params_group = QGroupBox("任务参数（可在步骤中用 {参数名} 引用）")
        params_layout = QVBoxLayout(params_group)

        params_btn_layout = QHBoxLayout()
        self._add_param_btn = QPushButton("添加参数")
        self._add_param_btn.clicked.connect(self._add_param)
        params_btn_layout.addWidget(self._add_param_btn)
        self._del_param_btn = QPushButton("删除参数")
        self._del_param_btn.clicked.connect(self._del_param)
        params_btn_layout.addWidget(self._del_param_btn)
        params_btn_layout.addStretch()
        params_layout.addLayout(params_btn_layout)

        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
        self._params_table = QTableWidget(0, 2)
        self._params_table.setHorizontalHeaderLabels(["参数名", "参数值"])
        self._params_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._params_table.setMaximumHeight(150)
        params_layout.addWidget(self._params_table)

        layout.addWidget(params_group)

        # === 步骤列表 ===
        steps_group = QGroupBox("执行步骤（按顺序执行）")
        steps_layout = QVBoxLayout(steps_group)

        # 操作按钮
        btn_layout = QHBoxLayout()
        self._add_step_btn = QPushButton("添加步骤")
        self._add_step_btn.clicked.connect(self._add_step)
        btn_layout.addWidget(self._add_step_btn)

        self._edit_step_btn = QPushButton("编辑步骤")
        self._edit_step_btn.clicked.connect(self._edit_step)
        btn_layout.addWidget(self._edit_step_btn)

        self._del_step_btn = QPushButton("删除步骤")
        self._del_step_btn.clicked.connect(self._delete_step)
        btn_layout.addWidget(self._del_step_btn)

        self._copy_step_btn = QPushButton("复制步骤")
        self._copy_step_btn.clicked.connect(self._copy_steps)
        btn_layout.addWidget(self._copy_step_btn)

        self._move_up_btn = QPushButton("上移")
        self._move_up_btn.clicked.connect(self._move_step_up)
        btn_layout.addWidget(self._move_up_btn)

        self._move_down_btn = QPushButton("下移")
        self._move_down_btn.clicked.connect(self._move_step_down)
        btn_layout.addWidget(self._move_down_btn)

        btn_layout.addStretch()
        steps_layout.addLayout(btn_layout)

        # 步骤列表（支持多选）
        self._steps_list = QListWidget()
        self._steps_list.setSelectionMode(QListWidget.ExtendedSelection)
        self._steps_list.setMinimumHeight(200)
        self._steps_list.itemDoubleClicked.connect(self._edit_step)
        steps_layout.addWidget(self._steps_list)

        layout.addWidget(steps_group, 1)

        # 确定/取消
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_data(self):
        """加载任务数据"""
        self._name_edit.setText(self._task.name if self._task.name != "未命名任务" else "")
        self._desc_edit.setText(self._task.description)
        self._loop_spin.setValue(self._task.loop_count)
        self._load_params()
        self._refresh_steps_list()

    def _load_params(self):
        """加载参数到表格"""
        from PySide6.QtWidgets import QTableWidgetItem
        self._params_table.setRowCount(0)
        for key, value in self._task.parameters.items():
            row = self._params_table.rowCount()
            self._params_table.insertRow(row)
            self._params_table.setItem(row, 0, QTableWidgetItem(str(key)))
            self._params_table.setItem(row, 1, QTableWidgetItem(str(value)))

    def _add_param(self):
        """添加一行空参数"""
        from PySide6.QtWidgets import QTableWidgetItem
        row = self._params_table.rowCount()
        self._params_table.insertRow(row)
        self._params_table.setItem(row, 0, QTableWidgetItem(""))
        self._params_table.setItem(row, 1, QTableWidgetItem(""))
        self._params_table.editItem(self._params_table.item(row, 0))

    def _del_param(self):
        """删除选中的参数行"""
        rows = set(item.row() for item in self._params_table.selectedItems())
        for row in sorted(rows, reverse=True):
            self._params_table.removeRow(row)

    def _get_params(self) -> dict:
        """从表格读取参数字典"""
        params = {}
        for row in range(self._params_table.rowCount()):
            key_item = self._params_table.item(row, 0)
            val_item = self._params_table.item(row, 1)
            key = key_item.text().strip() if key_item else ""
            val = val_item.text().strip() if val_item else ""
            if key:
                params[key] = val
        return params

    def _refresh_steps_list(self):
        """刷新步骤列表"""
        self._steps_list.clear()
        for i, step in enumerate(self._task.steps):
            rec_type_names = {"text": "文字", "image": "图像", "multi_image": "多图像"}
            rec_type = rec_type_names.get(step.recognition_type, step.recognition_type)
            action_names = {
                "click": "点击", "double_click": "双击",
                "right_click": "右键", "none": "无操作",
                "input_text": "输入文本", "press_key": "按键",
                "drag_map": "拖动地图", "mark_blocked": "标记封锁",
            }
            action = action_names.get(step.action_type, step.action_type)
            mode = "后台" if step.use_background else "前台"
            extra = ""
            if step.action_type == "input_text" and step.input_text:
                extra = f' "{step.input_text}"'
            elif step.action_type == "press_key" and step.press_keys:
                extra = f' [{step.press_keys}]'
            item_text = (
                f"[{i + 1}] {step.name} | "
                f"{rec_type}识别: \"{step.recognition_target}\" → "
                f"{action}{extra} ({mode})"
            )
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, i)
            self._steps_list.addItem(item)

    def _add_step(self):
        """添加步骤"""
        dlg = StepEditDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            step = dlg.get_step()
            self._task.steps.append(step)
            self._refresh_steps_list()

    def _edit_step(self):
        """编辑步骤"""
        current = self._steps_list.currentItem()
        if current is None:
            QMessageBox.warning(self, "提示", "请先选择一个步骤")
            return
        idx = current.data(Qt.UserRole)
        step = self._task.steps[idx]
        dlg = StepEditDialog(step, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self._task.steps[idx] = dlg.get_step()
            self._refresh_steps_list()

    def _delete_step(self):
        """删除选中的步骤（支持多选）"""
        selected = self._steps_list.selectedItems()
        if not selected:
            QMessageBox.warning(self, "提示", "请先选择要删除的步骤")
            return
        indices = sorted([item.data(Qt.UserRole) for item in selected], reverse=True)
        count = len(indices)
        if count == 1:
            msg = f"确定要删除步骤 [{self._task.steps[indices[0]].name}] 吗？"
        else:
            msg = f"确定要删除选中的 {count} 个步骤吗？"
        reply = QMessageBox.question(self, "确认删除", msg)
        if reply == QMessageBox.Yes:
            for idx in indices:  # 从后往前删，避免索引错位
                self._task.steps.pop(idx)
            self._refresh_steps_list()

    def _copy_steps(self):
        """复制选中的步骤到末尾（支持多选）"""
        selected = self._steps_list.selectedItems()
        if not selected:
            QMessageBox.warning(self, "提示", "请先选择要复制的步骤")
            return
        # 按原始顺序排序
        indices = sorted([item.data(Qt.UserRole) for item in selected])
        for idx in indices:
            new_step = copy.deepcopy(self._task.steps[idx])
            # 生成新的唯一ID
            import uuid
            new_step.id = uuid.uuid4().hex[:8]
            self._task.steps.append(new_step)
        self._refresh_steps_list()
        # 选中新复制的步骤
        total = len(self._task.steps)
        copied_count = len(indices)
        for i in range(total - copied_count, total):
            self._steps_list.item(i).setSelected(True)

    def _move_step_up(self):
        """上移步骤"""
        current = self._steps_list.currentItem()
        if current is None:
            return
        idx = current.data(Qt.UserRole)
        if idx > 0:
            self._task.steps[idx], self._task.steps[idx - 1] = (
                self._task.steps[idx - 1], self._task.steps[idx]
            )
            self._refresh_steps_list()
            self._steps_list.setCurrentRow(idx - 1)

    def _move_step_down(self):
        """下移步骤"""
        current = self._steps_list.currentItem()
        if current is None:
            return
        idx = current.data(Qt.UserRole)
        if idx < len(self._task.steps) - 1:
            self._task.steps[idx], self._task.steps[idx + 1] = (
                self._task.steps[idx + 1], self._task.steps[idx]
            )
            self._refresh_steps_list()
            self._steps_list.setCurrentRow(idx + 1)

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
        self._input = None
        self._bg_input_class = None
        self._window_manager = None
        self._current_hwnd: Optional[int] = None

        # 线程安全的信号桥
        self._bridge = _ExecutorSignalBridge(self)
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

        self._init_ui()
        self._connect_executor()
        self._refresh_task_list()

    def setup_dependencies(self, capture, ocr, recognition, input_sim,
                           bg_input_class, window_manager):
        """注入依赖"""
        self._capture = capture
        self._ocr = ocr
        self._recognition = recognition
        self._input = input_sim
        self._bg_input_class = bg_input_class
        self._window_manager = window_manager

    def set_current_window(self, hwnd: Optional[int]):
        """设置当前目标窗口"""
        self._current_hwnd = hwnd

    def _init_ui(self):
        layout = QHBoxLayout(self)

        # === 左侧：任务列表 ===
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
        layout.addWidget(left_panel, 1)

        # === 中间：任务详情和执行控制 ===
        middle_panel = QWidget()
        middle_layout = QVBoxLayout(middle_panel)
        middle_layout.setContentsMargins(0, 0, 0, 0)

        # 任务信息
        info_group = QGroupBox("任务详情")
        info_layout = QVBoxLayout(info_group)

        self._info_label = QLabel("请选择一个任务")
        self._info_label.setWordWrap(True)
        info_layout.addWidget(self._info_label)

        self._steps_preview = QListWidget()
        self._steps_preview.setContextMenuPolicy(Qt.CustomContextMenu)
        self._steps_preview.customContextMenuRequested.connect(self._show_step_context_menu)
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

        middle_layout.addWidget(exec_group)
        middle_layout.addStretch()

        layout.addWidget(middle_panel, 1)

        # === 右侧：执行日志（占满整个高度） ===
        log_panel = QWidget()
        log_panel_layout = QVBoxLayout(log_panel)
        log_panel_layout.setContentsMargins(0, 0, 0, 0)

        log_group = QGroupBox("执行日志")
        log_layout = QVBoxLayout(log_group)

        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        log_layout.addWidget(self._log_text)

        clear_log_btn = QPushButton("清除日志")
        clear_log_btn.clicked.connect(self._log_text.clear)
        log_layout.addWidget(clear_log_btn)

        log_panel_layout.addWidget(log_group)

        layout.addWidget(log_panel, 1)

    def _connect_executor(self):
        """连接执行器回调（全部通过信号桥跨线程转发）"""
        self._executor.on_log = lambda msg: self._bridge.sig_log.emit(msg)
        self._executor.on_task_start = lambda t: self._bridge.sig_task_started.emit(t.name)
        self._executor.on_task_finish = lambda t, ok: self._bridge.sig_task_finished.emit(t.name, ok)
        self._executor.on_step_start = lambda idx, s: self._bridge.sig_step_started.emit(idx, s.name)
        self._executor.on_step_success = None
        self._executor.on_step_retry = lambda idx, s, cnt: self._bridge.sig_step_retried.emit(idx, s.name, cnt)

    # ==================== 任务列表操作 ====================

    def _refresh_task_list(self):
        """刷新任务列表"""
        self._task_list.clear()
        tasks = self._storage.list_tasks()
        for task in tasks:
            loop_info = f"循环{task.loop_count}次" if task.loop_count > 0 else "无限循环"
            item_text = f"{task.name}  ({len(task.steps)}步, {loop_info})"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, task.id)
            self._task_list.addItem(item)

    def _get_selected_task_id(self) -> Optional[str]:
        """获取当前选中的任务ID"""
        current = self._task_list.currentItem()
        if current:
            return current.data(Qt.UserRole)
        return None

    def _on_task_selected(self, current, previous):
        """任务选择变更"""
        if current is None:
            self._info_label.setText("请选择一个任务")
            self._steps_preview.clear()
            return

        task_id = current.data(Qt.UserRole)
        task = self._storage.load(task_id)
        if task is None:
            return

        loop_info = f"循环 {task.loop_count} 次" if task.loop_count > 0 else "无限循环"
        params_info = ""
        if task.parameters:
            params_info = f"\n参数: {task.parameters}"
        blocked_info = ""
        if task.blocked_coords:
            blocked_info = f"\n封锁坐标: {len(task.blocked_coords)} 个"
        info = (
            f"任务名称: {task.name}\n"
            f"描述: {task.description or '无'}\n"
            f"步骤数: {len(task.steps)}\n"
            f"循环: {loop_info}"
            f"{params_info}{blocked_info}\n"
            f"创建时间: {task.created_time}\n"
            f"修改时间: {task.modified_time}"
        )
        self._info_label.setText(info)

        # 显示步骤预览
        self._steps_preview.clear()
        for i, step in enumerate(task.steps):
            rec_type_names = {"text": "文字", "image": "图像", "multi_image": "多图像"}
            rec_type = rec_type_names.get(step.recognition_type, step.recognition_type)
            action_names = {
                "click": "点击", "double_click": "双击",
                "right_click": "右键", "none": "无操作",
                "input_text": "输入文本", "press_key": "按键",
                "drag_map": "拖动地图", "mark_blocked": "标记封锁",
            }
            action = action_names.get(step.action_type, step.action_type)
            extra = ""
            if step.action_type == "input_text" and step.input_text:
                extra = f' "{step.input_text}"'
            elif step.action_type == "press_key" and step.press_keys:
                extra = f' [{step.press_keys}]'
            item_text = f"{i + 1}. {step.name} | {rec_type}: \"{step.recognition_target}\" → {action}{extra}"
            self._steps_preview.addItem(item_text)

    def _new_task(self):
        """新建任务"""
        dlg = TaskEditDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            task = dlg.get_task()
            self._storage.save(task)
            self._refresh_task_list()
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

        dlg = TaskEditDialog(task, parent=self)
        if dlg.exec() == QDialog.Accepted:
            edited = dlg.get_task()
            self._storage.save(edited)
            self._refresh_task_list()
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
                self._refresh_task_list()
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

        step_index = self._steps_preview.row(item)
        menu = QMenu(self)
        test_action = QAction("🚩 测试此步骤", self)
        test_action.triggered.connect(lambda: self._test_single_step(step_index))
        menu.addAction(test_action)
        menu.exec(self._steps_preview.mapToGlobal(pos))

    def _test_single_step(self, step_index: int):
        """单独测试一个步骤（识别 + 点击）"""
        if not self._current_hwnd:
            QMessageBox.warning(self, "提示", "请先在顶部选择目标窗口")
            return

        # 获取当前任务和步骤
        task_id = self._get_selected_task_id()
        if not task_id:
            return
        task = self._storage.load(task_id)
        if task is None or step_index >= len(task.steps):
            return

        step = task.steps[step_index]
        self._append_log(f"--- 开始测试步骤 [{step_index + 1}] {step.name} ---")

        # 在工作线程中执行，避免卡UI
        import threading
        t = threading.Thread(
            target=self._test_step_worker,
            args=(step,),
            daemon=True,
        )
        t.start()

    def _test_step_worker(self, step: SingleTask):
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

            # 2. 识别
            center = None
            if step.recognition_type == "text":
                center = self._test_recognize_text(step, img)
            elif step.recognition_type == "image":
                center = self._test_recognize_image(step, img)

            if center is None:
                self._bridge.sig_log.emit("识别失败，未找到目标")
                return

            cx, cy, tpl_w, tpl_h = center
            self._bridge.sig_log.emit(f"识别成功，位置: ({cx}, {cy})")

            # 3. 执行操作（与图像识别页签完全一致的方式）
            if step.action_type == "none":
                self._bridge.sig_log.emit("操作类型为\u201c无操作\u201d，跳过")
                return

            # 比例偏移：offset * 模板尺寸，Y轴正方向为上
            click_x = int(cx + step.click_offset_x * tpl_w)
            click_y = int(cy + step.click_offset_y * tpl_h)

            if step.action_type == "press_key":
                # 按键/组合键 — 不需要点击坐标
                from core.input import BackgroundInputSimulator
                bg_input = BackgroundInputSimulator(self._current_hwnd)
                keys_str = step.press_keys.strip()
                for key_combo in keys_str.split(","):
                    key_combo = key_combo.strip()
                    if not key_combo:
                        continue
                    parts = [k.strip() for k in key_combo.split("+")]
                    if len(parts) > 1:
                        bg_input.hotkey(*parts)
                        self._bridge.sig_log.emit(f"后台组合键: {key_combo}")
                    else:
                        bg_input.press(parts[0])
                        self._bridge.sig_log.emit(f"后台按键: {parts[0]}")
                self._bridge.sig_log.emit("按键操作完成")
                return

            if step.use_background:
                # 后台操作——每次新建 BackgroundInputSimulator
                from core.input import BackgroundInputSimulator
                bg_input = BackgroundInputSimulator(self._current_hwnd)
                self._bridge.sig_log.emit(
                    f"[调试] 后台操作: hwnd=0x{self._current_hwnd:X}, "
                    f"坐标=({click_x}, {click_y})"
                )
                if step.action_type == "click":
                    bg_input.click(click_x, click_y)
                elif step.action_type == "double_click":
                    bg_input.double_click(click_x, click_y)
                elif step.action_type == "right_click":
                    bg_input.right_click(click_x, click_y)
                elif step.action_type == "input_text":
                    # 先点击输入框
                    bg_input.click(click_x, click_y)
                    import time as _time
                    _time.sleep(0.15)
                    # 清除旧内容
                    self._clear_input_field_test(bg_input, step)
                    # 输入文本
                    bg_input.type_text(step.input_text)
                    self._bridge.sig_log.emit(f"后台输入文本: \"{step.input_text}\"")
                elif step.action_type == "drag_map":
                    # 拖动地图操作（等距方向转换）
                    from task.executor import TaskExecutor
                    iso_x, iso_y = self._load_isometric_axes()
                    end_x, end_y = TaskExecutor._calc_isometric_drag(
                        click_x, click_y, step, iso_x, iso_y)
                    bg_input.drag(click_x, click_y, end_x, end_y, duration=step.drag_duration)
                    self._bridge.sig_log.emit(f"后台拖动地图: ({click_x}, {click_y}) -> ({end_x}, {end_y})")
            else:
                # 前台操作
                client_rect = self._window_manager.get_client_rect(self._current_hwnd)
                if client_rect:
                    screen_x = client_rect[0] + click_x
                    screen_y = client_rect[1] + click_y
                else:
                    screen_x, screen_y = click_x, click_y
                if step.action_type == "click":
                    self._input.click(screen_x, screen_y)
                elif step.action_type == "double_click":
                    self._input.double_click(screen_x, screen_y)
                elif step.action_type == "right_click":
                    self._input.right_click(screen_x, screen_y)
                elif step.action_type == "input_text":
                    self._input.click(screen_x, screen_y)
                    import time as _time
                    _time.sleep(0.15)
                    self._clear_input_field_test(self._input, step)
                    self._input.type_text(step.input_text)
                    self._bridge.sig_log.emit(f"前台输入文本: \"{step.input_text}\"")
                elif step.action_type == "drag_map":
                    # 前台拖动地图操作（等距方向转换）
                    from task.executor import TaskExecutor
                    iso_x, iso_y = self._load_isometric_axes()
                    end_screen_x, end_screen_y = TaskExecutor._calc_isometric_drag(
                        screen_x, screen_y, step, iso_x, iso_y)
                    self._input.drag(screen_x, screen_y, end_screen_x, end_screen_y, duration=step.drag_duration)
                    self._bridge.sig_log.emit(f"前台拖动地图: ({screen_x}, {screen_y}) -> ({end_screen_x}, {end_screen_y})")
            action_names = {
                "click": "单击", "double_click": "双击",
                "right_click": "右键", "none": "无操作",
                "input_text": "输入文本", "press_key": "按键",
                "drag_map": "拖动地图"
            }
            self._bridge.sig_log.emit(
                f"测试完成: {action_names.get(step.action_type, step.action_type)} ({click_x}, {click_y})"
            )

        except Exception as e:
            import traceback
            self._bridge.sig_log.emit(f"测试执行异常: {e}")
            self._bridge.sig_log.emit(traceback.format_exc())

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
        match_index = max(1, step.match_index)
        
        # 判断是否需要使用find_all：显式标记多匹配或索引>1
        use_find_all = step.has_multiple_matches or match_index > 1

        if not use_find_all:
            # 快速模式：单次匹配（最高置信度）
            result = self._recognition.find_template(
                img, target,
                threshold=step.recognition_threshold,
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

        # 设置执行器依赖
        self._executor.setup(
            hwnd=self._current_hwnd,
            capture=self._capture,
            ocr=self._ocr,
            recognition=self._recognition,
            input_sim=self._input,
            bg_input_class=self._bg_input_class,
            window_manager=self._window_manager,
            task_storage=self._storage,
        )

        # 启动执行
        self._executor.start(task)

    def _toggle_pause(self):
        """暂停/恢复"""
        if self._executor.is_running:
            self._executor.pause()
            self._pause_btn.setText("⏸ 恢复")
            self._exec_status.setText("状态: 已暂停")
        elif self._executor.is_paused:
            self._executor.resume()
            self._pause_btn.setText("⏸ 暂停")
            self._exec_status.setText("状态: 执行中")

    def _stop_task(self):
        """停止任务"""
        self._executor.stop()

    # ==================== 执行器回调（通过信号桥在主线程执行） ====================

    @Slot(int, str)
    def _on_step_started_main(self, index: int, step_name: str):
        """步骤开始（主线程）"""
        self._exec_status.setText(f"状态: 执行第 {index + 1} 步 - {step_name}")
        self._highlight_step(index)

    @Slot(int, str, int)
    def _on_step_retried_main(self, index: int, step_name: str, retry_count: int):
        """步骤重试（主线程）"""
        self._exec_status.setText(
            f"状态: 第 {index + 1} 步 [{step_name}] 识别中... 重试第 {retry_count} 次"
        )

    def _highlight_step(self, index: int):
        """高亮当前执行的步骤"""
        if index < self._steps_preview.count():
            self._steps_preview.setCurrentRow(index)

    def _update_ui_running(self, running: bool, info: str = ""):
        """更新UI状态"""
        if running:
            self._run_btn.setEnabled(False)
            self._pause_btn.setEnabled(True)
            self._stop_btn.setEnabled(True)
            self._new_task_btn.setEnabled(False)
            self._edit_task_btn.setEnabled(False)
            self._del_task_btn.setEnabled(False)
            self._exec_status.setText(f"状态: 正在执行 - {info}")
            self._pause_btn.setText("⏸ 暂停")
        else:
            self._run_btn.setEnabled(True)
            self._pause_btn.setEnabled(False)
            self._stop_btn.setEnabled(False)
            self._new_task_btn.setEnabled(True)
            self._edit_task_btn.setEnabled(True)
            self._del_task_btn.setEnabled(True)
            self._exec_status.setText(f"状态: {info}")

    def _append_log(self, message: str):
        """追加日志"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._log_text.append(f"[{timestamp}] {message}")
        # 自动滚动到底部
        scrollbar = self._log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        # 同时发送信号
        self.log_message.emit(message)

    def stop_executor(self):
        """停止执行器（供外部调用，如退出时）"""
        if self._executor.is_running or self._executor.is_paused:
            self._executor.stop()
