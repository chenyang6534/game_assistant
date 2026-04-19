"""
全局热键管理模块
使用 Win32 RegisterHotKey API 注册全局热键

相比 keyboard 库的全局键盘钩子 (WH_KEYBOARD_LL):
- 不会拦截所有按键事件，不影响其他程序的热键（如 F1 截图工具）
- 只捕获已注册的特定热键
- 系统级API，更稳定可靠
"""

import time
import threading
import ctypes
import ctypes.wintypes
from typing import Dict, Callable, Optional, List
from dataclasses import dataclass

# Win32 常量
WM_HOTKEY = 0x0312
WM_USER = 0x0400
_WM_REGISTER = WM_USER + 1
_WM_UNREGISTER = WM_USER + 2
_WM_QUIT = WM_USER + 3

# 修饰键
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000  # 防止按住不放时重复触发

# VK 码映射
VK_MAP = {
    # F键
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73,
    'f5': 0x74, 'f6': 0x75, 'f7': 0x76, 'f8': 0x77,
    'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
    # 数字键
    '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34,
    '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
    # 字母键
    'a': 0x41, 'b': 0x42, 'c': 0x43, 'd': 0x44, 'e': 0x45,
    'f': 0x46, 'g': 0x47, 'h': 0x48, 'i': 0x49, 'j': 0x4A,
    'k': 0x4B, 'l': 0x4C, 'm': 0x4D, 'n': 0x4E, 'o': 0x4F,
    'p': 0x50, 'q': 0x51, 'r': 0x52, 's': 0x53, 't': 0x54,
    'u': 0x55, 'v': 0x56, 'w': 0x57, 'x': 0x58, 'y': 0x59,
    'z': 0x5A,
    # 特殊键
    'space': 0x20, 'enter': 0x0D, 'return': 0x0D,
    'tab': 0x09, 'escape': 0x1B, 'esc': 0x1B,
    'backspace': 0x08, 'delete': 0x2E, 'del': 0x2E,
    'insert': 0x2D, 'home': 0x24, 'end': 0x23,
    'pageup': 0x21, 'page_up': 0x21, 'pagedown': 0x22, 'page_down': 0x22,
    'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27,
    'numpad0': 0x60, 'numpad1': 0x61, 'numpad2': 0x62,
    'numpad3': 0x63, 'numpad4': 0x64, 'numpad5': 0x65,
    'numpad6': 0x66, 'numpad7': 0x67, 'numpad8': 0x68,
    'numpad9': 0x69,
    'pause': 0x13, 'capslock': 0x14, 'numlock': 0x90,
    'scrolllock': 0x91, 'printscreen': 0x2C,
}

# 修饰键名称映射
MODIFIER_MAP = {
    'ctrl': MOD_CONTROL,
    'control': MOD_CONTROL,
    'alt': MOD_ALT,
    'shift': MOD_SHIFT,
    'win': MOD_WIN,
    'windows': MOD_WIN,
}


@dataclass
class HotkeyBinding:
    """热键绑定"""
    hotkey: str             # 热键字符串，如 "ctrl+shift+f1"
    callback: Callable      # 回调函数
    description: str = ""   # 描述
    enabled: bool = True    # 是否启用


class HotkeyManager:
    """
    全局热键管理器 - 使用 Win32 RegisterHotKey API

    不安装全局键盘钩子，不影响其他程序的按键接收
    """

    DEFAULT_HOTKEYS = {
        'start_stop': 'F9',
        'pause': 'F10',
        'emergency_stop': 'F12',
    }

    def __init__(self):
        self._bindings: Dict[str, HotkeyBinding] = {}
        self._hotkey_ids: Dict[str, int] = {}  # name -> hotkey_id
        self._id_to_name: Dict[int, str] = {}  # hotkey_id -> name
        self._next_id = 0xBFF0
        self._lock = threading.RLock()
        self._enabled = True

        # 消息循环线程
        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None
        self._ready_event = threading.Event()

        self._start_thread()

    def _start_thread(self):
        """启动消息循环线程"""
        self._thread = threading.Thread(
            target=self._message_loop, daemon=True, name="HotkeyThread"
        )
        self._thread.start()
        self._ready_event.wait(timeout=5)

    def _message_loop(self):
        """Win32 消息循环，处理 WM_HOTKEY"""
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        self._thread_id = kernel32.GetCurrentThreadId()
        self._ready_event.set()

        msg = ctypes.wintypes.MSG()

        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break

            if msg.message == WM_HOTKEY:
                hotkey_id = msg.wParam
                self._handle_hotkey(hotkey_id)

            elif msg.message == _WM_REGISTER:
                hotkey_id = msg.wParam
                name = self._id_to_name.get(hotkey_id)
                if name:
                    info = self._bindings.get(name)
                    if info:
                        modifiers, vk = self._parse_hotkey(info.hotkey)
                        if vk is not None:
                            success = user32.RegisterHotKey(
                                None, hotkey_id,
                                modifiers | MOD_NOREPEAT, vk
                            )
                            if not success:
                                err = kernel32.GetLastError()
                                print(f"注册热键失败 [{name}] {info.hotkey}: "
                                      f"错误码 {err}")

            elif msg.message == _WM_UNREGISTER:
                hotkey_id = msg.wParam
                user32.UnregisterHotKey(None, hotkey_id)

            elif msg.message == _WM_QUIT:
                break

    def _handle_hotkey(self, hotkey_id: int):
        """处理热键触发"""
        if not self._enabled:
            return

        name = self._id_to_name.get(hotkey_id)
        if not name:
            return

        binding = self._bindings.get(name)
        if not binding or not binding.enabled:
            return

        try:
            binding.callback()
        except Exception as e:
            print(f"热键回调错误 [{name}]: {e}")

    @staticmethod
    def _parse_hotkey(hotkey_str: str):
        """
        解析热键字符串为 (modifiers, vk)

        Args:
            hotkey_str: 如 "F9", "ctrl+shift+a", "alt+F1"

        Returns:
            (modifiers, vk) 元组，解析失败返回 (0, None)
        """
        parts = [k.strip().lower() for k in hotkey_str.split('+')]

        modifiers = 0
        vk = None

        for part in parts:
            if part in MODIFIER_MAP:
                modifiers |= MODIFIER_MAP[part]
            elif part in VK_MAP:
                vk = VK_MAP[part]
            else:
                print(f"未知按键: {part}")
                return (0, None)

        return (modifiers, vk)

    def register(self, name: str, hotkey: str, callback: Callable,
                 description: str = "", suppress: bool = False) -> bool:
        """
        注册热键

        Args:
            name: 热键名称（唯一标识）
            hotkey: 热键字符串，如 "ctrl+shift+f1", "F9"
            callback: 回调函数
            description: 描述
            suppress: 保留参数（兼容旧接口）

        Returns:
            是否成功
        """
        modifiers, vk = self._parse_hotkey(hotkey)
        if vk is None:
            print(f"无法解析热键: {hotkey}")
            return False

        with self._lock:
            if name in self._bindings:
                self.unregister(name)

            hotkey_id = self._next_id
            self._next_id += 1

            binding = HotkeyBinding(
                hotkey=hotkey,
                callback=callback,
                description=description,
                enabled=True
            )

            self._bindings[name] = binding
            self._hotkey_ids[name] = hotkey_id
            self._id_to_name[hotkey_id] = name

            if self._thread_id:
                ctypes.windll.user32.PostThreadMessageW(
                    self._thread_id, _WM_REGISTER, hotkey_id, 0
                )

            return True

    def unregister(self, name: str) -> bool:
        """
        注销热键

        Args:
            name: 热键名称

        Returns:
            是否成功
        """
        with self._lock:
            if name not in self._bindings:
                return False

            hotkey_id = self._hotkey_ids.get(name)

            if hotkey_id is not None and self._thread_id:
                ctypes.windll.user32.PostThreadMessageW(
                    self._thread_id, _WM_UNREGISTER, hotkey_id, 0
                )

            if hotkey_id is not None:
                self._id_to_name.pop(hotkey_id, None)
                self._hotkey_ids.pop(name, None)
            self._bindings.pop(name, None)

            return True

    def unregister_all(self):
        """注销所有热键"""
        with self._lock:
            for name in list(self._bindings.keys()):
                self.unregister(name)

    def enable(self, name: str = None):
        """
        启用热键

        Args:
            name: 热键名称，None表示全部启用
        """
        if name is None:
            self._enabled = True
        elif name in self._bindings:
            self._bindings[name].enabled = True

    def disable(self, name: str = None):
        """
        禁用热键

        Args:
            name: 热键名称，None表示全部禁用
        """
        if name is None:
            self._enabled = False
        elif name in self._bindings:
            self._bindings[name].enabled = False

    def update_hotkey(self, name: str, new_hotkey: str) -> bool:
        """
        更新热键

        Args:
            name: 热键名称
            new_hotkey: 新的热键字符串

        Returns:
            是否成功
        """
        if name not in self._bindings:
            return False

        binding = self._bindings[name]
        return self.register(
            name, new_hotkey,
            binding.callback,
            binding.description
        )

    def get_binding(self, name: str) -> Optional[HotkeyBinding]:
        """获取热键绑定信息"""
        return self._bindings.get(name)

    def list_bindings(self) -> List[HotkeyBinding]:
        """获取所有热键绑定"""
        return list(self._bindings.values())

    @staticmethod
    def parse_hotkey(hotkey_str: str) -> List[str]:
        """
        解析热键字符串为按键列表

        Args:
            hotkey_str: 热键字符串，如 "ctrl+shift+a"

        Returns:
            按键列表 ["ctrl", "shift", "a"]
        """
        return [k.strip().lower() for k in hotkey_str.split('+')]

    @staticmethod
    def format_hotkey(keys: List[str]) -> str:
        """
        格式化热键字符串

        Args:
            keys: 按键列表

        Returns:
            热键字符串
        """
        return '+'.join(keys)

    @staticmethod
    def validate_hotkey(hotkey_str: str) -> bool:
        """
        验证热键字符串是否有效

        Args:
            hotkey_str: 热键字符串

        Returns:
            是否有效
        """
        parts = [k.strip().lower() for k in hotkey_str.split('+')]
        for part in parts:
            if part not in MODIFIER_MAP and part not in VK_MAP:
                return False
        has_key = any(p in VK_MAP for p in parts if p not in MODIFIER_MAP)
        return has_key

    def shutdown(self):
        """关闭热键管理器"""
        self.unregister_all()
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(
                self._thread_id, _WM_QUIT, 0, 0
            )


# 便捷函数
_global_manager: Optional[HotkeyManager] = None

def get_hotkey_manager() -> HotkeyManager:
    """获取全局热键管理器实例"""
    global _global_manager
    if _global_manager is None:
        _global_manager = HotkeyManager()
    return _global_manager


# 测试代码
if __name__ == "__main__":
    manager = HotkeyManager()

    def on_f9():
        print("F9 被按下!")

    def on_ctrl_shift_a():
        print("Ctrl+Shift+A 被按下!")

    manager.register("test_f9", "F9", on_f9, "测试热键F9")
    manager.register("test_combo", "ctrl+shift+a", on_ctrl_shift_a, "测试组合键")

    print("热键已注册 (使用 RegisterHotKey API，不影响其他程序热键):")
    for binding in manager.list_bindings():
        print(f"  - {binding.hotkey}: {binding.description}")

    print("\n按 F9 或 Ctrl+Shift+A 测试热键")
    print("按 Ctrl+C 退出\n")

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        manager.shutdown()
