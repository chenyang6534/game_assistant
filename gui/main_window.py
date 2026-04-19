"""
主窗口
Windows 自动化与识别工具的主界面
"""

import sys
import os
import json
from typing import Optional
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QGroupBox, QPushButton, QLabel, QSpinBox, QDoubleSpinBox,
    QCheckBox, QStatusBar, QMessageBox, QFileDialog, QSplitter,
    QTextEdit, QProgressBar, QSlider, QComboBox, QApplication,
    QListWidget, QListWidgetItem, QDialog, QDialogButtonBox, QLineEdit
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QThread
from PySide6.QtGui import QIcon, QCloseEvent

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.window import WindowManager, WindowInfo
from core.ai_tile_recognition import AITileRecognition
from core.capture import ScreenCapture
from core.recognition import ImageRecognition
from core.input import InputSimulator, BackgroundInputSimulator
from core.ocr import OCRRecognition, TextResult

from recorder.listener import EventListener
from recorder.player import ScriptPlayer, PlaybackConfig, PlayerState
from recorder.storage import ScriptStorage, Script, create_script_from_events

from utils.hotkey import HotkeyManager
from utils.logger import get_logger
from utils.tray import TrayIcon, MenuItem
from utils.app_meta import APP_DISPLAY_NAME, APP_TOOLTIP

from gui.widgets.window_picker import WindowPicker
from gui.widgets.hotkey_editor import HotkeyEditor
from gui.widgets.script_list import ScriptListWidget
from gui.widgets.coordinate_transform_panel import CoordinateTransformPanel
from gui.widgets.task_panel import TaskPanel
from gui.widgets.network_panel import NetworkPanel
from gui.widgets.memory_panel import MemoryPanel
from task.models import IMAGE_MATCH_MODE_LABELS


class MainWindow(QMainWindow):
    """主窗口"""
    
    def __init__(self):
        super().__init__()
        
        self._logger = get_logger()
        self._config = self._load_config()
        
        # 核心组件
        self._window_manager = WindowManager()
        self._capture = ScreenCapture()
        self._recognition = ImageRecognition()
        self._ai_tile_recognition = AITileRecognition()
        self._input = InputSimulator()
        self._bg_input: Optional[BackgroundInputSimulator] = None
        self._ocr = OCRRecognition()  # OCR识别器
        self._ocr_results: list = []  # OCR识别结果缓存
        
        # 录制组件
        self._listener = EventListener()
        self._player = ScriptPlayer()
        self._storage = ScriptStorage()
        
        # 热键管理
        self._hotkey_manager = HotkeyManager()
        
        # 系统托盘
        self._tray: Optional[TrayIcon] = None
        
        # 状态
        self._is_recording = False
        self._is_running = False
        self._current_window: Optional[WindowInfo] = None
        self._coordinate_transform_panel: Optional[CoordinateTransformPanel] = None
        self._task_panel: Optional[TaskPanel] = None
        self._network_panel: Optional[NetworkPanel] = None
        self._memory_panel: Optional[MemoryPanel] = None
        self._lazy_tab_hosts: dict = {}
        self._lazy_tab_placeholders: dict = {}
        self._lazy_tab_indices: dict = {}
        
        self._init_ui()
        self._init_hotkeys()
        self._init_tray()
        self._connect_signals()
        
        self._logger.info("自动化工具启动")
    
    def _load_config(self) -> dict:
        """加载配置文件"""
        config_path = Path(__file__).parent.parent / "config.json"
        
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self._logger.warning(f"加载配置失败: {e}")
        
        return {
            "hotkeys": {
                "start_stop": "F9",
                "pause": "F10",
                "emergency_stop": "F12"
            },
            "window": {
                "width": 900,
                "height": 700
            }
        }
    
    def _save_config(self):
        """保存配置文件"""
        config_path = Path(__file__).parent.parent / "config.json"
        
        try:
            # 重新加载现有配置，避免覆盖其他页面刚写入的新字段
            latest_config = self._load_config()
            latest_config["hotkeys"] = self._hotkey_editor.get_hotkeys()
            self._config = latest_config
            
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(latest_config, f, ensure_ascii=False, indent=4)
        except Exception as e:
            self._logger.warning(f"保存配置失败: {e}")
    
    def _init_ui(self):
        """初始化UI"""
        self.setWindowTitle(APP_DISPLAY_NAME)
        self.setMinimumSize(800, 600)
        
        # 设置窗口大小
        win_config = self._config.get("window", {})
        self.resize(win_config.get("width", 900), win_config.get("height", 700))
        
        # 中央控件
        central = QWidget()
        self.setCentralWidget(central)
        
        layout = QVBoxLayout(central)
        
        # 窗口选择器
        self._window_picker = WindowPicker()
        layout.addWidget(self._window_picker)
        
        # 选项卡
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs, 1)
        
        # 脚本录制选项卡
        self._tabs.addTab(self._create_recorder_tab(), "脚本录制")
        
        # 图像识别选项卡
        self._tabs.addTab(self._create_recognition_tab(), "图像识别")
        
        # OCR文字识别选项卡
        self._tabs.addTab(self._create_ocr_tab(), "文字识别")

        # 窗口坐标转换选项卡
        self._tabs.addTab(self._create_lazy_tab_host("coordinate_transform"), "坐标转换")
        self._lazy_tab_indices["coordinate_transform"] = self._tabs.count() - 1
        
        # 计划任务选项卡
        self._tabs.addTab(self._create_lazy_tab_host("task"), "计划任务")
        self._lazy_tab_indices["task"] = self._tabs.count() - 1
        
        # 网络消息选项卡
        self._tabs.addTab(self._create_lazy_tab_host("network"), "网络消息")
        self._lazy_tab_indices["network"] = self._tabs.count() - 1

        # 内存扫描选项卡
        self._tabs.addTab(self._create_lazy_tab_host("memory"), "内存扫描")
        self._lazy_tab_indices["memory"] = self._tabs.count() - 1
        
        # 设置选项卡
        self._tabs.addTab(self._create_settings_tab(), "设置")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        
        # 状态栏
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("就绪")
        
        # 状态指示器
        self._status_label = QLabel("状态: 空闲")
        self._status_bar.addPermanentWidget(self._status_label)

    def _create_lazy_tab_host(self, key: str) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(12, 12, 12, 12)
        placeholder = QLabel("首次打开该页签时再初始化，以减少主窗口启动卡顿")
        placeholder.setWordWrap(True)
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("color: gray; font-size: 12px;")
        layout.addStretch()
        layout.addWidget(placeholder)
        layout.addStretch()
        self._lazy_tab_hosts[key] = host
        self._lazy_tab_placeholders[key] = placeholder
        return host

    def _on_tab_changed(self, index: int):
        key = next((name for name, tab_index in self._lazy_tab_indices.items() if tab_index == index), None)
        if key:
            self._ensure_lazy_tab_loaded(key)

    def _ensure_lazy_tab_loaded(self, key: str):
        if key == "coordinate_transform" and self._coordinate_transform_panel is not None:
            return self._coordinate_transform_panel
        if key == "task" and self._task_panel is not None:
            return self._task_panel
        if key == "network" and self._network_panel is not None:
            return self._network_panel
        if key == "memory" and self._memory_panel is not None:
            return self._memory_panel

        host = self._lazy_tab_hosts.get(key)
        if host is None:
            return None

        layout = host.layout()
        placeholder = self._lazy_tab_placeholders.pop(key, None)
        if placeholder is not None:
            layout.removeWidget(placeholder)
            placeholder.deleteLater()
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        panel = None
        if key == "coordinate_transform":
            panel = CoordinateTransformPanel(host)
            panel.setup_dependencies(
                capture=self._capture,
                window_manager=self._window_manager,
            )
            self._coordinate_transform_panel = panel
            if self._current_window:
                panel.set_current_window(self._current_window)
        elif key == "task":
            panel = TaskPanel(host)
            panel.setup_dependencies(
                capture=self._capture,
                ocr=self._ocr,
                recognition=self._recognition,
                ai_tile_recognition=self._ai_tile_recognition,
                input_sim=self._input,
                bg_input_class=BackgroundInputSimulator,
                window_manager=self._window_manager,
            )
            self._task_panel = panel
            if self._current_window:
                panel.set_current_window(self._current_window.hwnd if self._current_window else None)
        elif key == "network":
            panel = NetworkPanel(host)
            self._network_panel = panel
            if self._current_window:
                panel.set_pid(self._current_window.pid if self._current_window else None)
        elif key == "memory":
            panel = MemoryPanel(host)
            self._memory_panel = panel
            if self._current_window:
                panel.set_pid(self._current_window.pid if self._current_window else None)

        if panel is not None:
            layout.addWidget(panel)
        return panel
    
    def _create_recorder_tab(self) -> QWidget:
        """创建脚本录制选项卡"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        
        # 左侧：脚本列表
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        self._script_list = ScriptListWidget()
        left_layout.addWidget(self._script_list)
        
        layout.addWidget(left_panel, 1)
        
        # 右侧：控制面板
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # 录制控制
        record_group = QGroupBox("录制控制")
        record_layout = QVBoxLayout(record_group)
        
        # 录制选项
        self._record_mouse_move = QCheckBox("录制鼠标移动")
        self._record_mouse_move.setChecked(False)
        record_layout.addWidget(self._record_mouse_move)
        
        # 录制按钮
        record_btn_layout = QHBoxLayout()
        
        self._record_btn = QPushButton("开始录制")
        self._record_btn.setMinimumHeight(40)
        self._record_btn.clicked.connect(self._toggle_recording)
        record_btn_layout.addWidget(self._record_btn)
        
        self._save_record_btn = QPushButton("保存录制")
        self._save_record_btn.setEnabled(False)
        self._save_record_btn.clicked.connect(self._save_recording)
        record_btn_layout.addWidget(self._save_record_btn)
        
        record_layout.addLayout(record_btn_layout)
        
        # 录制状态
        self._record_status = QLabel("未录制")
        record_layout.addWidget(self._record_status)
        
        right_layout.addWidget(record_group)
        
        # 回放控制
        play_group = QGroupBox("回放控制")
        play_layout = QVBoxLayout(play_group)
        
        # 回放设置
        settings_layout = QHBoxLayout()
        
        settings_layout.addWidget(QLabel("速度:"))
        self._speed_spin = QDoubleSpinBox()
        self._speed_spin.setRange(0.1, 5.0)
        self._speed_spin.setValue(1.0)
        self._speed_spin.setSingleStep(0.1)
        settings_layout.addWidget(self._speed_spin)
        
        settings_layout.addWidget(QLabel("循环:"))
        self._loop_spin = QSpinBox()
        self._loop_spin.setRange(0, 9999)
        self._loop_spin.setValue(1)
        self._loop_spin.setSpecialValueText("无限")
        settings_layout.addWidget(self._loop_spin)
        
        settings_layout.addStretch()
        play_layout.addLayout(settings_layout)
        
        # 回放按钮
        play_btn_layout = QHBoxLayout()
        
        self._play_btn = QPushButton("播放")
        self._play_btn.setMinimumHeight(40)
        self._play_btn.clicked.connect(self._play_script)
        play_btn_layout.addWidget(self._play_btn)
        
        self._pause_btn = QPushButton("暂停")
        self._pause_btn.setEnabled(False)
        self._pause_btn.clicked.connect(self._toggle_pause)
        play_btn_layout.addWidget(self._pause_btn)
        
        self._stop_btn = QPushButton("停止")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop_playback)
        play_btn_layout.addWidget(self._stop_btn)
        
        play_layout.addLayout(play_btn_layout)
        
        # 进度条
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        play_layout.addWidget(self._progress_bar)
        
        self._play_status = QLabel("未播放")
        play_layout.addWidget(self._play_status)
        
        right_layout.addWidget(play_group)
        
        right_layout.addStretch()
        
        layout.addWidget(right_panel, 1)
        
        return widget
    
    def _create_recognition_tab(self) -> QWidget:
        """创建图像识别选项卡"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 模板管理
        template_group = QGroupBox("模板图像")
        template_layout = QVBoxLayout(template_group)
        
        btn_layout = QHBoxLayout()
        
        self._add_template_btn = QPushButton("添加模板")
        self._add_template_btn.clicked.connect(self._add_template)
        btn_layout.addWidget(self._add_template_btn)
        
        self._capture_template_btn = QPushButton("截取模板")
        self._capture_template_btn.clicked.connect(self._capture_template)
        btn_layout.addWidget(self._capture_template_btn)
        
        btn_layout.addStretch()
        template_layout.addLayout(btn_layout)
        
        # 模板列表
        self._template_list = QComboBox()
        template_layout.addWidget(self._template_list)
        
        layout.addWidget(template_group)
        
        # 识别设置
        settings_group = QGroupBox("识别设置")
        settings_layout = QHBoxLayout(settings_group)
        
        settings_layout.addWidget(QLabel("匹配阈值:"))
        self._threshold_spin = QDoubleSpinBox()
        self._threshold_spin.setRange(0.1, 1.0)
        self._threshold_spin.setValue(0.8)
        self._threshold_spin.setSingleStep(0.05)
        settings_layout.addWidget(self._threshold_spin)
        
        self._grayscale_check = QCheckBox("灰度匹配")
        self._grayscale_check.setChecked(True)
        settings_layout.addWidget(self._grayscale_check)

        self._validate_color_check = QCheckBox("验证颜色一致性")
        self._validate_color_check.setToolTip("勾选后会在模板匹配成功后再核对颜色分布，避免彩色模板误匹配到灰度目标")
        self._validate_color_check.setChecked(False)
        settings_layout.addWidget(self._validate_color_check)

        settings_layout.addWidget(QLabel("图像匹配方式:"))
        self._image_match_mode_combo = QComboBox()
        self._image_match_mode_combo.addItem(IMAGE_MATCH_MODE_LABELS["template"], "template")
        self._image_match_mode_combo.addItem(IMAGE_MATCH_MODE_LABELS["foreground"], "foreground")
        self._image_match_mode_combo.setToolTip(
            "普通模板：按整体像素匹配；前景优先：尽量忽略背景，更适合地块和底图会变化的目标"
        )
        settings_layout.addWidget(self._image_match_mode_combo)
        
        settings_layout.addStretch()
        layout.addWidget(settings_group)
        
        # 匹配后操作
        action_group = QGroupBox("匹配后操作")
        action_layout = QVBoxLayout(action_group)
        
        self._click_on_match = QCheckBox("点击匹配位置")
        self._click_on_match.setChecked(True)
        action_layout.addWidget(self._click_on_match)
        
        self._background_mode = QCheckBox("后台模式（窗口被遮挡也能操作）")
        self._background_mode.setChecked(True)
        self._background_mode.setToolTip("启用后，截图和点击都在后台进行，不会移动真实鼠标")
        action_layout.addWidget(self._background_mode)
        
        layout.addWidget(action_group)
        
        # 测试按钮
        test_btn = QPushButton("测试识别")
        test_btn.clicked.connect(self._test_recognition)
        layout.addWidget(test_btn)
        
        layout.addStretch()
        
        return widget
    
    def _create_ocr_tab(self) -> QWidget:
        """创建OCR文字识别选项卡"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # OCR状态提示
        if not self._ocr.is_available:
            warning_label = QLabel(f"⚠️ OCR不可用: {self._ocr.error_message}")
            warning_label.setStyleSheet("color: red; padding: 10px;")
            warning_label.setWordWrap(True)
            layout.addWidget(warning_label)
        
        # 识别控制
        control_group = QGroupBox("文字识别")
        control_layout = QVBoxLayout(control_group)
        
        btn_layout = QHBoxLayout()
        
        self._ocr_recognize_btn = QPushButton("识别文字")
        self._ocr_recognize_btn.clicked.connect(self._ocr_recognize)
        self._ocr_recognize_btn.setEnabled(self._ocr.is_available)
        btn_layout.addWidget(self._ocr_recognize_btn)
        
        self._ocr_clear_btn = QPushButton("清除结果")
        self._ocr_clear_btn.clicked.connect(self._ocr_clear_results)
        btn_layout.addWidget(self._ocr_clear_btn)
        
        self._ocr_save_screenshot_btn = QPushButton("保存截图")
        self._ocr_save_screenshot_btn.clicked.connect(self._ocr_save_screenshot)
        self._ocr_save_screenshot_btn.setToolTip("保存当前窗口截图用于调试")
        btn_layout.addWidget(self._ocr_save_screenshot_btn)
        
        btn_layout.addStretch()
        control_layout.addLayout(btn_layout)
        
        # 置信度设置
        conf_layout = QHBoxLayout()
        conf_layout.addWidget(QLabel("最小置信度:"))
        self._ocr_confidence_spin = QDoubleSpinBox()
        self._ocr_confidence_spin.setRange(0.1, 1.0)
        self._ocr_confidence_spin.setValue(0.5)
        self._ocr_confidence_spin.setSingleStep(0.1)
        conf_layout.addWidget(self._ocr_confidence_spin)
        conf_layout.addStretch()
        control_layout.addLayout(conf_layout)
        
        # 后台模式
        self._ocr_background_mode = QCheckBox("后台模式（窗口被遮挡也能操作）")
        self._ocr_background_mode.setChecked(True)
        self._ocr_background_mode.setToolTip("后台截图和点击，对某些模拟器或特殊渲染程序可能无效")
        control_layout.addWidget(self._ocr_background_mode)
        
        # 激活窗口选项
        self._ocr_activate_window = QCheckBox("点击前激活窗口（推荐用于模拟器或特殊渲染程序）")
        self._ocr_activate_window.setChecked(False)
        self._ocr_activate_window.setToolTip("点击前先激活目标窗口，对模拟器或特殊渲染程序更可靠")
        control_layout.addWidget(self._ocr_activate_window)
        
        layout.addWidget(control_group)
        
        # 识别结果列表
        result_group = QGroupBox("识别结果（双击点击该文字位置）")
        result_layout = QVBoxLayout(result_group)
        
        # 搜索框
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("🔍 搜索:"))
        self._ocr_search_input = QLineEdit()
        self._ocr_search_input.setPlaceholderText("输入文字进行筛选...")
        self._ocr_search_input.textChanged.connect(self._ocr_filter_results)
        self._ocr_search_input.setClearButtonEnabled(True)
        search_layout.addWidget(self._ocr_search_input)
        result_layout.addLayout(search_layout)
        
        # 过滤状态标签
        self._ocr_filter_status = QLabel("")
        self._ocr_filter_status.setStyleSheet("color: gray; font-size: 11px;")
        result_layout.addWidget(self._ocr_filter_status)
        
        self._ocr_result_list = QListWidget()
        self._ocr_result_list.setMinimumHeight(200)
        self._ocr_result_list.itemDoubleClicked.connect(self._ocr_click_text)
        result_layout.addWidget(self._ocr_result_list)
        
        # 点击按钮
        click_btn_layout = QHBoxLayout()
        self._ocr_click_btn = QPushButton("点击选中的文字")
        self._ocr_click_btn.clicked.connect(self._ocr_click_selected)
        click_btn_layout.addWidget(self._ocr_click_btn)
        
        self._ocr_swipe_up_btn = QPushButton("向上滑动")
        self._ocr_swipe_up_btn.clicked.connect(self._ocr_swipe_up_selected)
        self._ocr_swipe_up_btn.setToolTip("在选中文字位置向上滑动半个窗口高度")
        click_btn_layout.addWidget(self._ocr_swipe_up_btn)
        
        click_btn_layout.addStretch()
        result_layout.addLayout(click_btn_layout)
        
        layout.addWidget(result_group)
        
        # 状态显示
        self._ocr_status_label = QLabel("状态: 就绪")
        layout.addWidget(self._ocr_status_label)
        
        layout.addStretch()
        
        return widget
    
    def _create_settings_tab(self) -> QWidget:
        """创建设置选项卡"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 热键设置
        self._hotkey_editor = HotkeyEditor()
        self._hotkey_editor.set_hotkeys(self._config.get("hotkeys", {}))
        self._hotkey_editor.hotkeys_changed.connect(self._on_hotkeys_changed)
        layout.addWidget(self._hotkey_editor)
        
        # 其他设置
        other_group = QGroupBox("其他设置")
        other_layout = QVBoxLayout(other_group)
        
        self._minimize_to_tray = QCheckBox("关闭时最小化到托盘")
        self._minimize_to_tray.setChecked(True)
        other_layout.addWidget(self._minimize_to_tray)
        
        self._start_minimized = QCheckBox("启动时最小化")
        other_layout.addWidget(self._start_minimized)
        
        layout.addWidget(other_group)
        
        layout.addStretch()
        
        return widget
    
    def _init_hotkeys(self):
        """初始化热键"""
        hotkeys = self._config.get("hotkeys", {})
        
        if hotkeys.get("start_stop"):
            self._hotkey_manager.register(
                "start_stop",
                hotkeys["start_stop"],
                self._toggle_start_stop,
                "开始/停止"
            )
        
        if hotkeys.get("pause"):
            self._hotkey_manager.register(
                "pause",
                hotkeys["pause"],
                self._toggle_pause,
                "暂停/继续"
            )
        
        if hotkeys.get("emergency_stop"):
            self._hotkey_manager.register(
                "emergency_stop",
                hotkeys["emergency_stop"],
                self._emergency_stop,
                "紧急停止"
            )
    
    def _init_tray(self):
        """初始化系统托盘"""
        if not TrayIcon.is_available():
            self._logger.warning("系统托盘不可用")
            return
        
        self._tray = TrayIcon(tooltip=APP_TOOLTIP)
        
        # 添加菜单项
        self._tray.add_menu_item("show", MenuItem(
            text="显示主窗口",
            callback=self._show_from_tray,
            separator_after=True
        ))
        
        self._tray.add_menu_item("start_stop", MenuItem(
            text="开始",
            callback=self._toggle_start_stop
        ))
        
        self._tray.add_menu_item("pause", MenuItem(
            text="暂停",
            callback=self._toggle_pause,
            checkable=True,
            separator_after=True
        ))
        
        self._tray.add_menu_item("exit", MenuItem(
            text="退出",
            callback=self._quit_app
        ))
        
        # 连接信号
        self._tray.activated.connect(self._show_from_tray)
        self._tray.double_clicked.connect(self._show_from_tray)
        
        self._tray.show()
    
    def _connect_signals(self):
        """连接信号"""
        # 窗口选择器
        self._window_picker.window_selected.connect(self._on_window_selected)
        
        # 脚本列表
        self._script_list.play_requested.connect(self._on_play_requested)
        
        # 播放器
        self._player.on_start = self._on_playback_started
        self._player.on_stop = self._on_playback_stopped
        self._player.on_progress = self._on_playback_progress
        self._player.on_pause = self._on_playback_paused
        self._player.on_resume = self._on_playback_resumed
        
        # 录制器
        self._listener.on_event = self._on_record_event
    
    # ==================== 事件处理 ====================
    
    def _on_window_selected(self, window: WindowInfo):
        """窗口选择变更"""
        self._current_window = window
        if self._coordinate_transform_panel is not None:
            self._coordinate_transform_panel.set_current_window(window)
        if self._task_panel is not None:
            self._task_panel.set_current_window(window.hwnd if window else None)
        if self._network_panel is not None:
            self._network_panel.set_pid(window.pid if window else None)
        if self._memory_panel is not None:
            self._memory_panel.set_pid(window.pid if window else None)
        self._logger.info(f"选择窗口: {window.title}")
    
    def _on_hotkeys_changed(self, hotkeys: dict):
        """热键配置变更"""
        # 重新注册热键
        self._hotkey_manager.unregister_all()
        
        if hotkeys.get("start_stop"):
            self._hotkey_manager.register(
                "start_stop", hotkeys["start_stop"],
                self._toggle_start_stop
            )
        
        if hotkeys.get("pause"):
            self._hotkey_manager.register(
                "pause", hotkeys["pause"],
                self._toggle_pause
            )
        
        if hotkeys.get("emergency_stop"):
            self._hotkey_manager.register(
                "emergency_stop", hotkeys["emergency_stop"],
                self._emergency_stop
            )
        
        self._save_config()
    
    def _on_play_requested(self, script_name: str):
        """请求播放脚本"""
        script = self._script_list.load_script(script_name)
        if script:
            self._play_script_obj(script)
    
    def _on_record_event(self, event):
        """录制事件"""
        count = self._listener.event_count
        duration = self._listener.duration / 1000
        self._record_status.setText(f"录制中: {count}个事件, {duration:.1f}秒")
    
    def _on_playback_started(self):
        """播放开始"""
        self._is_running = True
        self._play_btn.setEnabled(False)
        self._pause_btn.setEnabled(True)
        self._stop_btn.setEnabled(True)
        self._status_label.setText("状态: 播放中")
        self._play_status.setText("播放中...")
        
        if self._tray:
            self._tray.set_menu_item_text("start_stop", "停止")
    
    def _on_playback_stopped(self):
        """播放停止"""
        self._is_running = False
        self._play_btn.setEnabled(True)
        self._pause_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._progress_bar.setValue(0)
        self._status_label.setText("状态: 空闲")
        self._play_status.setText("已停止")
        
        if self._tray:
            self._tray.set_menu_item_text("start_stop", "开始")
            self._tray.set_menu_item_checked("pause", False)
    
    def _on_playback_progress(self, progress: float):
        """播放进度更新"""
        self._progress_bar.setValue(int(progress * 100))
    
    def _on_playback_paused(self):
        """播放暂停"""
        self._pause_btn.setText("继续")
        self._status_label.setText("状态: 已暂停")
        self._play_status.setText("已暂停")
        
        if self._tray:
            self._tray.set_menu_item_checked("pause", True)
    
    def _on_playback_resumed(self):
        """播放恢复"""
        self._pause_btn.setText("暂停")
        self._status_label.setText("状态: 播放中")
        self._play_status.setText("播放中...")
        
        if self._tray:
            self._tray.set_menu_item_checked("pause", False)
    
    # ==================== 操作方法 ====================
    
    def _toggle_recording(self):
        """切换录制状态"""
        if not self._is_recording:
            self._start_recording()
        else:
            self._stop_recording()
    
    def _start_recording(self):
        """开始录制"""
        self._listener.record_mouse_move = self._record_mouse_move.isChecked()
        self._listener.start_recording()
        
        self._is_recording = True
        self._record_btn.setText("停止录制")
        self._save_record_btn.setEnabled(False)
        self._record_status.setText("录制中: 0个事件")
        self._status_label.setText("状态: 录制中")
        
        self._logger.info("开始录制")
    
    def _stop_recording(self):
        """停止录制"""
        events = self._listener.stop_recording()
        
        self._is_recording = False
        self._record_btn.setText("开始录制")
        self._save_record_btn.setEnabled(len(events) > 0)
        self._record_status.setText(f"录制完成: {len(events)}个事件")
        self._status_label.setText("状态: 空闲")
        
        self._logger.info(f"停止录制，共{len(events)}个事件")
    
    def _save_recording(self):
        """保存录制"""
        events = self._listener.events
        if not events:
            QMessageBox.warning(self, "警告", "没有可保存的录制内容")
            return
        
        from PySide6.QtWidgets import QInputDialog
        
        name, ok = QInputDialog.getText(
            self, "保存录制",
            "脚本名称:",
            text=f"script_{len(self._storage.list_scripts()) + 1}"
        )
        
        if ok and name:
            target_window = self._current_window.title if self._current_window else ""
            script = create_script_from_events(events, name, target_window=target_window)
            
            self._storage.save(script)
            self._script_list.refresh()
            self._save_record_btn.setEnabled(False)
            
            QMessageBox.information(self, "成功", "脚本保存成功")
            self._logger.info(f"保存脚本: {name}")
    
    def _play_script(self):
        """播放选中的脚本"""
        script_name = self._script_list.get_selected_script()
        if not script_name:
            QMessageBox.warning(self, "警告", "请先选择一个脚本")
            return
        
        script = self._script_list.load_script(script_name)
        if script:
            self._play_script_obj(script)
    
    def _play_script_obj(self, script: Script):
        """播放脚本对象"""
        config = PlaybackConfig(
            speed=self._speed_spin.value(),
            loop_count=self._loop_spin.value()
        )
        
        self._player.play(script, config)
        self._logger.info(f"开始播放脚本: {script.metadata.name}")
    
    def _toggle_pause(self):
        """切换暂停状态"""
        if self._player.is_playing:
            self._player.pause()
        elif self._player.is_paused:
            self._player.resume()
    
    def _stop_playback(self):
        """停止播放"""
        self._player.stop()
    
    def _toggle_start_stop(self):
        """热键：切换开始/停止"""
        if self._is_running:
            self._stop_playback()
        else:
            self._play_script()
    
    def _emergency_stop(self):
        """紧急停止"""
        self._logger.warning("紧急停止")
        
        if self._is_recording:
            self._stop_recording()
        
        if self._is_running:
            self._stop_playback()
        
        # 停止计划任务
        if self._task_panel is not None:
            self._task_panel.stop_executor()
        
        # 停止网络抓包
        if self._network_panel is not None:
            self._network_panel.cleanup()

        # 停止内存扫描
        if self._memory_panel is not None:
            self._memory_panel.cleanup()
        
        self._status_bar.showMessage("紧急停止！", 3000)
        
        if self._tray:
            self._tray.show_warning("紧急停止", "已停止所有操作")
    
    def _add_template(self):
        """添加模板图像"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "选择模板图像",
            "",
            "图像文件 (*.png *.jpg *.bmp);;所有文件 (*.*)"
        )
        
        if filepath:
            name = os.path.splitext(os.path.basename(filepath))[0]
            result = self._recognition.load_template(filepath, name)
            if result is not None:
                self._template_list.addItem(name)
                self._logger.info(f"添加模板: {name}")
                QMessageBox.information(self, "成功", f"模板 '{name}' 加载成功")
            else:
                QMessageBox.warning(self, "错误", f"无法加载模板图像: {filepath}")
    
    def _capture_template(self):
        """截取模板"""
        if not self._current_window:
            QMessageBox.warning(self, "警告", "请先选择目标窗口")
            return
        
        # 截取当前窗口（使用后台截图）
        if self._background_mode.isChecked():
            img = self._capture.capture_window_background(self._current_window.hwnd)
        else:
            img = self._capture.capture_window(self._current_window.hwnd)
        
        if img is None:
            QMessageBox.warning(self, "警告", "无法截取窗口")
            return
        
        # TODO: 实现区域选择对话框
        QMessageBox.information(
            self, "提示",
            "截取模板功能待实现\n请使用'添加模板'按钮选择已有图像"
        )
    
    def _test_recognition(self):
        """测试图像识别"""
        if not self._current_window:
            QMessageBox.warning(self, "警告", "请先选择目标窗口")
            return
        
        if self._template_list.count() == 0:
            QMessageBox.warning(self, "警告", "请先添加模板图像")
            return
        
        template_name = self._template_list.currentText()
        if not template_name:
            return
        
        # 截取窗口（后台模式下使用后台截图）
        use_background = self._background_mode.isChecked()
        if use_background:
            img = self._capture.capture_window_background(self._current_window.hwnd)
        else:
            img = self._capture.capture_window(self._current_window.hwnd)
        
        if img is None:
            QMessageBox.warning(self, "警告", "无法截取窗口（后台截图可能不支持此程序）")
            return
        
        # 执行识别
        self._recognition.default_threshold = self._threshold_spin.value()
        self._recognition.use_grayscale = self._grayscale_check.isChecked()
        self._recognition.validate_color_consistency = self._validate_color_check.isChecked()
        
        result = self._recognition.find_template(
            img,
            template_name,
            validate_color=self._validate_color_check.isChecked(),
            match_mode=self._image_match_mode_combo.currentData() or 'template',
        )
        
        if result:
            QMessageBox.information(
                self, "识别成功",
                f"找到模板: {template_name}\n"
                f"位置: ({result.x}, {result.y})\n"
                f"置信度: {result.confidence:.2f}"
            )
            
            # 如果启用了点击
            if self._click_on_match.isChecked():
                if use_background:
                    # 后台模式：使用窗口相对坐标，不移动真实鼠标
                    if self._bg_input is None or self._bg_input.hwnd != self._current_window.hwnd:
                        self._bg_input = BackgroundInputSimulator(self._current_window.hwnd)
                    self._bg_input.click(result.center[0], result.center[1])
                else:
                    # 前台模式：转换为屏幕坐标
                    client_rect = self._window_manager.get_client_rect(self._current_window.hwnd)
                    if client_rect:
                        screen_x = client_rect[0] + result.center[0]
                        screen_y = client_rect[1] + result.center[1]
                        self._input.click(screen_x, screen_y)
        else:
            QMessageBox.information(self, "识别结果", "未找到匹配的模板")
    
    # ==================== OCR文字识别 ====================
    
    def _ocr_recognize(self):
        """OCR识别目标窗口的文字"""
        if not self._current_window:
            QMessageBox.warning(self, "警告", "请先选择目标窗口")
            return
        
        if not self._ocr.is_available:
            QMessageBox.warning(self, "警告", f"OCR不可用: {self._ocr.error_message}")
            return
        
        self._ocr_status_label.setText("状态: 正在截图...")
        self._ocr_recognize_btn.setEnabled(False)
        QApplication.processEvents()
        
        try:
            # 截取窗口
            use_background = self._ocr_background_mode.isChecked()
            img = None
            capture_method = ""
            
            if use_background:
                # 尝试后台截图
                img = self._capture.capture_window_background(self._current_window.hwnd)
                capture_method = "后台截图"
                
                # 如果后台截图失败或返回黑图，回退到前台截图
                if img is None or self._is_black_or_empty_image(img):
                    self._ocr_status_label.setText("状态: 后台截图失败，尝试前台截图...")
                    QApplication.processEvents()
                    img = self._capture.capture_window(self._current_window.hwnd)
                    capture_method = "前台截图(后台失败)"
            else:
                img = self._capture.capture_window(self._current_window.hwnd)
                capture_method = "前台截图"
            
            if img is None:
                QMessageBox.warning(self, "警告", "无法截取窗口，请确保窗口可见")
                return
            
            # 检查图像是否有效
            if self._is_black_or_empty_image(img):
                QMessageBox.warning(
                    self, "警告", 
                    "截取的图像为空或全黑\n\n"
                    "可能原因：\n"
                    "1. 目标窗口使用了DirectX/OpenGL渲染\n"
                    "2. 窗口处于最小化状态\n"
                    "3. 目标程序有反截图保护\n\n"
                    "建议：取消勾选'后台模式'后重试"
                )
                return
            
            self._ocr_status_label.setText(f"状态: 正在识别文字... ({capture_method})")
            QApplication.processEvents()
            
            # 执行OCR识别
            min_confidence = self._ocr_confidence_spin.value()
            results = self._ocr.recognize(img, min_confidence)
            
            # 缓存结果
            self._ocr_results = results
            
            # 更新列表（不过滤）
            self._ocr_search_input.clear()  # 清空搜索框
            self._ocr_update_result_list()
            
            self._ocr_status_label.setText(f"状态: 识别完成，找到 {len(results)} 个文字区域 ({capture_method})")
            
            if len(results) == 0:
                QMessageBox.information(self, "识别结果", "未识别到任何文字")
                
        except Exception as e:
            QMessageBox.warning(self, "错误", f"OCR识别失败: {e}")
            self._ocr_status_label.setText("状态: 识别失败")
        finally:
            self._ocr_recognize_btn.setEnabled(True)
    
    def _is_black_or_empty_image(self, img) -> bool:
        """检查图像是否为空或几乎全黑"""
        import numpy as np
        if img is None or img.size == 0:
            return True
        
        # 检查图像是否几乎全黑（超过95%的像素值小于10）
        black_pixels = np.sum(img < 10)
        total_pixels = img.size
        
        return (black_pixels / total_pixels) > 0.95
    
    def _ocr_update_result_list(self):
        """更新 OCR 结果列表显示（不带过滤）"""
        self._ocr_result_list.clear()
        for i, result in enumerate(self._ocr_results):
            item_text = f"[{i+1}] {result.text}  (置信度: {result.confidence:.2f}, 位置: {result.x},{result.y})"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, i)  # 存储索引
            self._ocr_result_list.addItem(item)
        self._ocr_filter_status.setText("")
    
    def _ocr_filter_results(self, search_text: str):
        """根据搜索文字过滤 OCR 结果"""
        search_text = search_text.strip().lower()
        
        self._ocr_result_list.clear()
        
        if not search_text:
            # 无搜索词，显示全部
            for i, result in enumerate(self._ocr_results):
                item_text = f"[{i+1}] {result.text}  (置信度: {result.confidence:.2f}, 位置: {result.x},{result.y})"
                item = QListWidgetItem(item_text)
                item.setData(Qt.UserRole, i)
                self._ocr_result_list.addItem(item)
            self._ocr_filter_status.setText("")
        else:
            # 按搜索词过滤
            matched_count = 0
            for i, result in enumerate(self._ocr_results):
                if search_text in result.text.lower():
                    matched_count += 1
                    item_text = f"[{i+1}] {result.text}  (置信度: {result.confidence:.2f}, 位置: {result.x},{result.y})"
                    item = QListWidgetItem(item_text)
                    item.setData(Qt.UserRole, i)
                    self._ocr_result_list.addItem(item)
            
            # 更新过滤状态
            total = len(self._ocr_results)
            if matched_count == 0:
                self._ocr_filter_status.setText(f"❌ 未找到包含 \"{search_text}\" 的文字")
            else:
                self._ocr_filter_status.setText(f"✅ 找到 {matched_count} / {total} 个匹配项")
    
    def _ocr_clear_results(self):
        """清除OCR识别结果"""
        self._ocr_result_list.clear()
        self._ocr_results = []
        self._ocr_search_input.clear()
        self._ocr_filter_status.setText("")
        self._ocr_status_label.setText("状态: 就绪")
    
    def _ocr_save_screenshot(self):
        """保存当前窗口截图用于调试"""
        if not self._current_window:
            QMessageBox.warning(self, "警告", "请先选择目标窗口")
            return
        
        use_background = self._ocr_background_mode.isChecked()
        
        try:
            # 尝试截图
            if use_background:
                screenshot = self._capture.capture_window_background(self._current_window.hwnd)
            else:
                screenshot = self._capture.capture_window(self._current_window.hwnd)
            
            if screenshot is None:
                QMessageBox.warning(self, "警告", "截图失败，请检查目标窗口是否有效")
                return
            
            # 检测是否是黑屏
            is_black = self._is_black_or_empty_image(screenshot)
            
            # 获取保存路径
            import os
            save_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "debug_screenshots")
            os.makedirs(save_dir, exist_ok=True)
            
            import time
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            mode_str = "background" if use_background else "foreground"
            filename = f"screenshot_{mode_str}_{timestamp}.png"
            save_path = os.path.join(save_dir, filename)
            
            # 保存图片
            import cv2
            cv2.imwrite(save_path, screenshot)
            
            # 显示结果
            h, w = screenshot.shape[:2]
            black_info = " (检测为黑屏/空白图像!)" if is_black else ""
            QMessageBox.information(
                self, "截图已保存", 
                f"截图已保存到:\n{save_path}\n\n"
                f"图像尺寸: {w}x{h}\n"
                f"模式: {'后台模式' if use_background else '前台模式'}{black_info}"
            )
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存截图失败: {e}")
    
    def _ocr_click_text(self, item: QListWidgetItem):
        """双击列表项，点击对应的文字位置"""
        self._ocr_click_at_index(item.data(Qt.UserRole))
    
    def _ocr_click_selected(self):
        """点击选中的文字"""
        current_item = self._ocr_result_list.currentItem()
        if current_item is None:
            QMessageBox.warning(self, "警告", "请先选择一个文字")
            return
        self._ocr_click_at_index(current_item.data(Qt.UserRole))
    
    def _ocr_swipe_up_selected(self):
        """在选中文字位置向上滑动"""
        current_item = self._ocr_result_list.currentItem()
        if current_item is None:
            QMessageBox.warning(self, "警告", "请先选择一个文字")
            return
        self._ocr_swipe_up_at_index(current_item.data(Qt.UserRole))
    
    def _ocr_swipe_up_at_index(self, index: int):
        """在指定索引的文字位置向上滑动半个窗口高度"""
        if index < 0 or index >= len(self._ocr_results):
            return
        
        if not self._current_window:
            QMessageBox.warning(self, "警告", "请先选择目标窗口")
            return
        
        result = self._ocr_results[index]
        center_x, center_y = result.center
        
        use_background = self._ocr_background_mode.isChecked()
        activate_window = self._ocr_activate_window.isChecked()
        
        try:
            import win32gui
            import win32con
            
            # 获取窗口客户区大小
            client_rect = self._window_manager.get_client_rect(self._current_window.hwnd)
            if not client_rect:
                QMessageBox.warning(self, "错误", "无法获取窗口位置")
                return
            
            window_height = client_rect[3] - client_rect[1]
            swipe_distance = window_height // 2  # 半个窗口高度
            
            # 计算滑动终点（向上滑动）
            end_y = max(0, center_y - swipe_distance)
            
            if activate_window or not use_background:
                # 前台模式：激活窗口后拖动
                try:
                    if win32gui.IsIconic(self._current_window.hwnd):
                        win32gui.ShowWindow(self._current_window.hwnd, win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(self._current_window.hwnd)
                    import time
                    time.sleep(0.1)
                except Exception as e:
                    print(f"激活窗口失败: {e}")
                
                # 转换为屏幕坐标
                screen_start_x = client_rect[0] + center_x
                screen_start_y = client_rect[1] + center_y
                screen_end_y = client_rect[1] + end_y
                
                # 使用前台输入模拟器拖动
                self._input.drag(screen_start_x, screen_start_y, screen_start_x, screen_end_y)
                self._ocr_status_label.setText(
                    f"状态: 已在 '{result.text}' 位置向上滑动 {swipe_distance}px [前台模式]"
                )
            else:
                # 后台模式
                if self._bg_input is None or self._bg_input.hwnd != self._current_window.hwnd:
                    self._bg_input = BackgroundInputSimulator(self._current_window.hwnd)
                self._bg_input.drag(center_x, center_y, center_x, end_y)
                self._ocr_status_label.setText(
                    f"状态: 已在 '{result.text}' 位置向上滑动 {swipe_distance}px [后台模式]"
                )
                
        except Exception as e:
            QMessageBox.warning(self, "错误", f"滑动失败: {e}")
    
    def _ocr_click_at_index(self, index: int):
        """点击指定索引的文字位置"""
        if index < 0 or index >= len(self._ocr_results):
            return
        
        if not self._current_window:
            QMessageBox.warning(self, "警告", "请先选择目标窗口")
            return
        
        result = self._ocr_results[index]
        center_x, center_y = result.center
        
        use_background = self._ocr_background_mode.isChecked()
        activate_window = self._ocr_activate_window.isChecked()
        
        try:
            import win32gui
            import win32con
            
            # 如果勾选了激活窗口选项，或者使用前台模式
            if activate_window or not use_background:
                # 激活目标窗口
                try:
                    # 确保窗口不是最小化状态
                    if win32gui.IsIconic(self._current_window.hwnd):
                        win32gui.ShowWindow(self._current_window.hwnd, win32con.SW_RESTORE)
                    
                    # 激活窗口
                    win32gui.SetForegroundWindow(self._current_window.hwnd)
                    
                    # 等待窗口激活
                    import time
                    time.sleep(0.1)
                except Exception as e:
                    print(f"激活窗口失败: {e}")
                
                # 使用前台点击方式（更可靠）
                client_rect = self._window_manager.get_client_rect(self._current_window.hwnd)
                if client_rect:
                    screen_x = client_rect[0] + center_x
                    screen_y = client_rect[1] + center_y
                    self._input.click(screen_x, screen_y)
                    self._ocr_status_label.setText(f"状态: 已点击 '{result.text}' 位置 ({center_x}, {center_y}) [前台模式]")
                else:
                    QMessageBox.warning(self, "错误", "无法获取窗口位置")
                    return
            else:
                # 纯后台模式：使用窗口相对坐标发送消息
                if self._bg_input is None or self._bg_input.hwnd != self._current_window.hwnd:
                    self._bg_input = BackgroundInputSimulator(self._current_window.hwnd)
                self._bg_input.click(center_x, center_y)
                self._ocr_status_label.setText(f"状态: 已点击 '{result.text}' 位置 ({center_x}, {center_y}) [后台模式]")
            
        except Exception as e:
            QMessageBox.warning(self, "错误", f"点击失败: {e}")
    
    def _show_from_tray(self):
        """从托盘显示窗口"""
        self.showNormal()
        self.activateWindow()
        self.raise_()
    
    def _quit_app(self):
        """退出应用"""
        import os
        try:
            if self._task_panel is not None:
                self._task_panel.stop_executor()
        except:
            pass
        try:
            self._save_config()
        except:
            pass
        
        try:
            self._hotkey_manager.unregister_all()
        except:
            pass
        
        try:
            if self._network_panel is not None:
                self._network_panel.cleanup()
        except:
            pass

        try:
            if self._memory_panel is not None:
                self._memory_panel.cleanup()
        except:
            pass
        
        try:
            if self._tray:
                self._tray.hide()
        except:
            pass
        
        # 强制终止进程
        os._exit(0)
    
    # ==================== 窗口事件 ====================
    
    def closeEvent(self, event: QCloseEvent):
        """关闭事件"""
        reply = QMessageBox.question(
            self,
            "确认退出",
            "是否关闭该程序？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            event.accept()
            self._quit_app()
        else:
            event.ignore()
