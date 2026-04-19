"""
热键编辑器控件
用于设置和编辑全局热键
"""

from typing import Optional, Dict
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox, QMessageBox
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QKeySequence

import sys
import os
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


class HotkeyLineEdit(QLineEdit):
    """热键输入框"""
    
    hotkey_changed = Signal(str)  # 热键字符串
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setReadOnly(True)
        self.setPlaceholderText("点击后按下热键...")
        self._recording = False
        self._keys = []
    
    def mousePressEvent(self, event):
        """鼠标点击开始录制"""
        super().mousePressEvent(event)
        self._start_recording()
    
    def _start_recording(self):
        """开始录制热键"""
        self._recording = True
        self._keys = []
        self.setText("请按下热键...")
        self.setStyleSheet("background-color: #ffffcc;")
    
    def _stop_recording(self):
        """停止录制热键"""
        self._recording = False
        self.setStyleSheet("")
        
        if self._keys:
            hotkey = '+'.join(self._keys)
            self.setText(hotkey.upper())
            self.hotkey_changed.emit(hotkey)
        else:
            self.clear()
    
    def keyPressEvent(self, event):
        """按键按下事件"""
        if not self._recording:
            return
        
        key = event.key()
        modifiers = event.modifiers()
        
        # 解析修饰键
        mod_names = []
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            mod_names.append("ctrl")
        if modifiers & Qt.KeyboardModifier.AltModifier:
            mod_names.append("alt")
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            mod_names.append("shift")
        if modifiers & Qt.KeyboardModifier.MetaModifier:
            mod_names.append("win")
        
        # 解析主键
        key_name = self._key_to_name(key)
        
        if key_name:
            self._keys = mod_names + [key_name]
            hotkey = '+'.join(self._keys)
            self.setText(hotkey.upper())
    
    def keyReleaseEvent(self, event):
        """按键释放事件"""
        if self._recording and self._keys:
            self._stop_recording()
    
    def _key_to_name(self, key: int) -> Optional[str]:
        """将Qt键码转换为键名"""
        # 特殊键映射
        special_keys = {
            Qt.Key.Key_Escape: 'escape',
            Qt.Key.Key_Tab: 'tab',
            Qt.Key.Key_Backspace: 'backspace',
            Qt.Key.Key_Return: 'enter',
            Qt.Key.Key_Enter: 'enter',
            Qt.Key.Key_Insert: 'insert',
            Qt.Key.Key_Delete: 'delete',
            Qt.Key.Key_Pause: 'pause',
            Qt.Key.Key_Print: 'printscreen',
            Qt.Key.Key_Home: 'home',
            Qt.Key.Key_End: 'end',
            Qt.Key.Key_Left: 'left',
            Qt.Key.Key_Up: 'up',
            Qt.Key.Key_Right: 'right',
            Qt.Key.Key_Down: 'down',
            Qt.Key.Key_PageUp: 'pageup',
            Qt.Key.Key_PageDown: 'pagedown',
            Qt.Key.Key_CapsLock: 'capslock',
            Qt.Key.Key_NumLock: 'numlock',
            Qt.Key.Key_ScrollLock: 'scrolllock',
            Qt.Key.Key_Space: 'space',
        }
        
        if key in special_keys:
            return special_keys[key]
        
        # F1-F12
        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
            return f'f{key - Qt.Key.Key_F1 + 1}'
        
        # 字母和数字
        if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            return chr(key).lower()
        
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            return chr(key)
        
        # 小键盘
        if Qt.Key.Key_0 <= key - 0x01000000 <= Qt.Key.Key_9:
            return f'numpad{key - 0x01000000 - Qt.Key.Key_0}'
        
        # 忽略单独的修饰键
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift, Qt.Key.Key_Meta):
            return None
        
        return None
    
    def set_hotkey(self, hotkey: str):
        """设置热键"""
        self.setText(hotkey.upper() if hotkey else "")
        self._keys = hotkey.lower().split('+') if hotkey else []
    
    def get_hotkey(self) -> str:
        """获取当前热键"""
        return '+'.join(self._keys)
    
    def clear_hotkey(self):
        """清除热键"""
        self._keys = []
        self.clear()


class HotkeyEditor(QWidget):
    """热键编辑器控件"""
    
    # 信号
    hotkeys_changed = Signal(dict)  # {name: hotkey}
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self._hotkey_inputs: Dict[str, HotkeyLineEdit] = {}
        self._default_hotkeys = {
            'start_stop': 'F9',
            'pause': 'F10',
            'emergency_stop': 'F12',
        }
        
        self._init_ui()
    
    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        group = QGroupBox("热键设置")
        group_layout = QGridLayout(group)
        
        # 热键配置项
        hotkey_configs = [
            ('start_stop', '开始/停止', '启动或停止自动化任务'),
            ('pause', '暂停/继续', '暂停或继续当前任务'),
            ('emergency_stop', '紧急停止', '立即停止所有操作'),
        ]
        
        for row, (name, label, tooltip) in enumerate(hotkey_configs):
            # 标签
            lbl = QLabel(f"{label}:")
            lbl.setToolTip(tooltip)
            group_layout.addWidget(lbl, row, 0)
            
            # 热键输入框
            hotkey_input = HotkeyLineEdit()
            hotkey_input.set_hotkey(self._default_hotkeys.get(name, ''))
            hotkey_input.hotkey_changed.connect(
                lambda hk, n=name: self._on_hotkey_changed(n, hk)
            )
            self._hotkey_inputs[name] = hotkey_input
            group_layout.addWidget(hotkey_input, row, 1)
            
            # 清除按钮
            clear_btn = QPushButton("清除")
            clear_btn.setFixedWidth(60)
            clear_btn.clicked.connect(
                lambda checked, n=name: self._clear_hotkey(n)
            )
            group_layout.addWidget(clear_btn, row, 2)
        
        # 按钮行
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        reset_btn = QPushButton("重置为默认")
        reset_btn.clicked.connect(self._reset_to_default)
        btn_layout.addWidget(reset_btn)
        
        group_layout.addLayout(btn_layout, len(hotkey_configs), 0, 1, 3)
        
        layout.addWidget(group)
    
    def _on_hotkey_changed(self, name: str, hotkey: str):
        """热键变更处理"""
        # 检查冲突
        for other_name, other_input in self._hotkey_inputs.items():
            if other_name != name and other_input.get_hotkey() == hotkey:
                QMessageBox.warning(
                    self, "热键冲突", 
                    f"热键 {hotkey.upper()} 已被其他功能使用！"
                )
                self._hotkey_inputs[name].set_hotkey('')
                return
        
        self.hotkeys_changed.emit(self.get_hotkeys())
    
    def _clear_hotkey(self, name: str):
        """清除指定热键"""
        if name in self._hotkey_inputs:
            self._hotkey_inputs[name].clear_hotkey()
            self.hotkeys_changed.emit(self.get_hotkeys())
    
    def _reset_to_default(self):
        """重置为默认热键"""
        for name, hotkey in self._default_hotkeys.items():
            if name in self._hotkey_inputs:
                self._hotkey_inputs[name].set_hotkey(hotkey)
        
        self.hotkeys_changed.emit(self.get_hotkeys())
    
    def get_hotkeys(self) -> Dict[str, str]:
        """获取所有热键配置"""
        return {
            name: input.get_hotkey()
            for name, input in self._hotkey_inputs.items()
        }
    
    def set_hotkeys(self, hotkeys: Dict[str, str]):
        """设置热键配置"""
        for name, hotkey in hotkeys.items():
            if name in self._hotkey_inputs:
                self._hotkey_inputs[name].set_hotkey(hotkey)
    
    def get_hotkey(self, name: str) -> str:
        """获取指定热键"""
        if name in self._hotkey_inputs:
            return self._hotkey_inputs[name].get_hotkey()
        return ''
