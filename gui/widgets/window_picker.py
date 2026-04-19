"""
窗口选择器控件
用于选择目标游戏窗口
"""

from typing import Optional, List
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QComboBox, 
    QPushButton, QLabel, QGroupBox, QMessageBox
)
from PySide6.QtCore import Signal, QTimer
from PySide6.QtGui import QPixmap, QImage

import numpy as np

import sys
import os
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from core.window import WindowManager, WindowInfo
from core.capture import ScreenCapture


class WindowPicker(QWidget):
    """窗口选择器控件"""
    
    # 信号
    window_selected = Signal(object)  # WindowInfo
    window_changed = Signal(object)   # WindowInfo
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._window_manager = WindowManager()
        self._capture = ScreenCapture()
        self._current_window: Optional[WindowInfo] = None
        self._windows: List[WindowInfo] = []
        
        self._init_ui()
        self._refresh_windows()
    
    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 窗口选择组
        group = QGroupBox("目标窗口")
        group_layout = QVBoxLayout(group)
        
        # 下拉框和按钮行
        select_layout = QHBoxLayout()
        
        self._combo = QComboBox()
        self._combo.setMinimumWidth(300)
        self._combo.currentIndexChanged.connect(self._on_selection_changed)
        select_layout.addWidget(self._combo, 1)
        
        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.clicked.connect(self._refresh_windows)
        select_layout.addWidget(self._refresh_btn)
        
        self._focus_btn = QPushButton("激活窗口")
        self._focus_btn.clicked.connect(self._focus_window)
        select_layout.addWidget(self._focus_btn)
        
        group_layout.addLayout(select_layout)
        
        # 窗口信息
        info_layout = QHBoxLayout()
        
        self._info_label = QLabel("未选择窗口")
        info_layout.addWidget(self._info_label, 1)
        
        # 预览按钮
        self._preview_btn = QPushButton("预览")
        self._preview_btn.clicked.connect(self._show_preview)
        info_layout.addWidget(self._preview_btn)
        
        group_layout.addLayout(info_layout)
        
        layout.addWidget(group)
        
        # 定时刷新（检测窗口是否仍然有效）
        self._check_timer = QTimer(self)
        self._check_timer.timeout.connect(self._check_window_valid)
        self._check_timer.start(5000)  # 每5秒检查一次
    
    def _refresh_windows(self):
        """刷新窗口列表"""
        self._combo.blockSignals(True)
        self._combo.clear()
        
        self._windows = self._window_manager.get_game_windows()
        
        self._combo.addItem("-- 请选择窗口 --", None)
        
        for win in self._windows:
            display_text = f"{win.title} ({win.width}x{win.height})"
            self._combo.addItem(display_text, win.hwnd)
        
        # 恢复之前的选择
        if self._current_window:
            for i in range(self._combo.count()):
                if self._combo.itemData(i) == self._current_window.hwnd:
                    self._combo.setCurrentIndex(i)
                    break
        
        self._combo.blockSignals(False)
    
    def _on_selection_changed(self, index: int):
        """选择变更处理"""
        hwnd = self._combo.itemData(index)
        
        if hwnd is None:
            self._current_window = None
            self._info_label.setText("未选择窗口")
            return
        
        # 查找对应的WindowInfo
        for win in self._windows:
            if win.hwnd == hwnd:
                self._current_window = win
                self._update_info()
                self.window_selected.emit(win)
                self.window_changed.emit(win)
                return
    
    def _update_info(self):
        """更新窗口信息显示"""
        if not self._current_window:
            self._info_label.setText("未选择窗口")
            return
        
        win = self._current_window
        info = f"句柄: {win.hwnd} | 位置: ({win.x}, {win.y}) | 大小: {win.width}x{win.height}"
        self._info_label.setText(info)
    
    def _focus_window(self):
        """激活选中的窗口"""
        if not self._current_window:
            return
        
        success = self._window_manager.bring_to_front(self._current_window.hwnd)
        if not success:
            QMessageBox.warning(self, "警告", "无法激活窗口，窗口可能已关闭")
            self._refresh_windows()
    
    def _show_preview(self):
        """显示窗口预览"""
        if not self._current_window:
            QMessageBox.information(self, "提示", "请先选择一个窗口")
            return
        
        # 使用后台截图方式截取窗口（支持被遮挡的窗口）
        img = self._capture.capture_window_background(self._current_window.hwnd)
        if img is None:
            QMessageBox.warning(self, "警告", "无法截取窗口画面")
            return
        
        # 创建预览对话框
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QScrollArea
        
        dialog = QDialog(self)
        dialog.setWindowTitle(f"窗口预览 - {self._current_window.title}")
        dialog.setMinimumSize(400, 300)
        
        layout = QVBoxLayout(dialog)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        
        label = QLabel()
        
        # 转换为QPixmap
        img = np.ascontiguousarray(img)
        h, w, ch = img.shape
        bytes_per_line = ch * w
        q_img = QImage(img.data, w, h, bytes_per_line, QImage.Format.Format_BGR888)
        
        # 缩放预览图
        max_size = 800
        if w > max_size or h > max_size:
            scale = max_size / max(w, h)
            q_img = q_img.scaled(int(w * scale), int(h * scale))
        
        label.setPixmap(QPixmap.fromImage(q_img))
        scroll.setWidget(label)
        
        layout.addWidget(scroll)
        dialog.exec()
    
    def _check_window_valid(self):
        """检查当前窗口是否仍然有效"""
        if not self._current_window:
            return
        
        if not self._window_manager.is_window_valid(self._current_window.hwnd):
            self._current_window = None
            self._info_label.setText("窗口已关闭")
            self._combo.setCurrentIndex(0)
    
    @property
    def current_window(self) -> Optional[WindowInfo]:
        """获取当前选中的窗口"""
        return self._current_window
    
    @property
    def current_hwnd(self) -> Optional[int]:
        """获取当前选中的窗口句柄"""
        return self._current_window.hwnd if self._current_window else None
    
    def set_window_by_hwnd(self, hwnd: int):
        """通过句柄设置选中的窗口"""
        for i in range(self._combo.count()):
            if self._combo.itemData(i) == hwnd:
                self._combo.setCurrentIndex(i)
                return
    
    def set_window_by_title(self, title: str, exact: bool = False):
        """通过标题设置选中的窗口"""
        win = self._window_manager.get_window_by_title(title, exact)
        if win:
            self._refresh_windows()
            self.set_window_by_hwnd(win.hwnd)
