"""
输入模拟模块
使用 ctypes 调用 Win32 API 的 SendInput 函数
实现鼠标和键盘的底层模拟，适用于 Windows 桌面自动化场景
"""

import ctypes
import ctypes.wintypes
import time
import random
import math
from typing import Tuple, List, Optional
from enum import IntEnum
from dataclasses import dataclass

# Windows API 常量
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000

KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_UNICODE = 0x0004

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

# 虚拟键码映射
VK_CODES = {
    'backspace': 0x08, 'tab': 0x09, 'enter': 0x0D, 'shift': 0x10,
    'ctrl': 0x11, 'alt': 0x12, 'pause': 0x13, 'capslock': 0x14,
    'escape': 0x1B, 'space': 0x20, 'pageup': 0x21, 'pagedown': 0x22,
    'end': 0x23, 'home': 0x24, 'left': 0x25, 'up': 0x26,
    'right': 0x27, 'down': 0x28, 'printscreen': 0x2C, 'insert': 0x2D,
    'delete': 0x2E,
    '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34,
    '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
    'a': 0x41, 'b': 0x42, 'c': 0x43, 'd': 0x44, 'e': 0x45,
    'f': 0x46, 'g': 0x47, 'h': 0x48, 'i': 0x49, 'j': 0x4A,
    'k': 0x4B, 'l': 0x4C, 'm': 0x4D, 'n': 0x4E, 'o': 0x4F,
    'p': 0x50, 'q': 0x51, 'r': 0x52, 's': 0x53, 't': 0x54,
    'u': 0x55, 'v': 0x56, 'w': 0x57, 'x': 0x58, 'y': 0x59,
    'z': 0x5A,
    'numpad0': 0x60, 'numpad1': 0x61, 'numpad2': 0x62, 'numpad3': 0x63,
    'numpad4': 0x64, 'numpad5': 0x65, 'numpad6': 0x66, 'numpad7': 0x67,
    'numpad8': 0x68, 'numpad9': 0x69,
    'multiply': 0x6A, 'add': 0x6B, 'subtract': 0x6D, 'decimal': 0x6E,
    'divide': 0x6F,
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73, 'f5': 0x74,
    'f6': 0x75, 'f7': 0x76, 'f8': 0x77, 'f9': 0x78, 'f10': 0x79,
    'f11': 0x7A, 'f12': 0x7B,
    'numlock': 0x90, 'scrolllock': 0x91,
    'lshift': 0xA0, 'rshift': 0xA1, 'lctrl': 0xA2, 'rctrl': 0xA3,
    'lalt': 0xA4, 'ralt': 0xA5,
    ';': 0xBA, '=': 0xBB, ',': 0xBC, '-': 0xBD, '.': 0xBE,
    '/': 0xBF, '`': 0xC0, '[': 0xDB, '\\': 0xDC, ']': 0xDD,
    "'": 0xDE,
}

# 扩展按键（需要设置 KEYEVENTF_EXTENDEDKEY）
EXTENDED_KEYS = {
    'insert', 'delete', 'home', 'end', 'pageup', 'pagedown',
    'left', 'right', 'up', 'down', 'numlock', 'printscreen',
    'divide', 'rctrl', 'ralt', 'enter'  # 小键盘Enter
}


# Windows API 结构体定义
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort)
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT)
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("union", INPUT_UNION)
    ]


class MouseButton(IntEnum):
    """鼠标按钮枚举"""
    LEFT = 1
    RIGHT = 2
    MIDDLE = 3


@dataclass
class InputConfig:
    """输入配置"""
    random_delay_min: int = 50      # 最小随机延迟(ms)
    random_delay_max: int = 150     # 最大随机延迟(ms)
    human_like_movement: bool = True  # 人类化鼠标移动
    movement_steps: int = 20        # 鼠标移动步数
    click_duration_min: int = 50    # 点击最小持续时间(ms)
    click_duration_max: int = 120   # 点击最大持续时间(ms)


class InputSimulator:
    """输入模拟器"""
    
    def __init__(self, config: InputConfig = None):
        """
        初始化输入模拟器
        
        Args:
            config: 输入配置
        """
        self.config = config or InputConfig()
        
        # 获取屏幕分辨率
        self.user32 = ctypes.windll.user32
        self.screen_width = self.user32.GetSystemMetrics(0)
        self.screen_height = self.user32.GetSystemMetrics(1)
        
        # 设置DPI感知
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    
    def _send_input(self, *inputs):
        """发送输入事件"""
        n_inputs = len(inputs)
        input_array = (INPUT * n_inputs)(*inputs)
        self.user32.SendInput(n_inputs, ctypes.pointer(input_array), ctypes.sizeof(INPUT))
    
    def _random_delay(self, min_ms: int = None, max_ms: int = None):
        """添加随机延迟"""
        min_ms = min_ms or self.config.random_delay_min
        max_ms = max_ms or self.config.random_delay_max
        delay = random.randint(min_ms, max_ms) / 1000.0
        time.sleep(delay)
    
    def _to_absolute_coords(self, x: int, y: int) -> Tuple[int, int]:
        """转换为绝对坐标（0-65535范围）"""
        abs_x = int(x * 65536 / self.screen_width)
        abs_y = int(y * 65536 / self.screen_height)
        return (abs_x, abs_y)

    @staticmethod
    def _mouse_button_flags(button: MouseButton) -> Tuple[int, int]:
        if button == MouseButton.LEFT:
            return MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
        if button == MouseButton.RIGHT:
            return MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
        return MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP
    
    # ==================== 鼠标操作 ====================
    
    def get_mouse_position(self) -> Tuple[int, int]:
        """获取当前鼠标位置"""
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        
        point = POINT()
        self.user32.GetCursorPos(ctypes.byref(point))
        return (point.x, point.y)
    
    def move_to(self, x: int, y: int, duration: float = 0):
        """
        移动鼠标到指定位置
        
        Args:
            x, y: 目标位置
            duration: 移动持续时间（秒），0表示瞬移
        """
        if duration <= 0 or not self.config.human_like_movement:
            # 瞬时移动
            abs_x, abs_y = self._to_absolute_coords(x, y)
            
            inp = INPUT()
            inp.type = INPUT_MOUSE
            inp.union.mi.dx = abs_x
            inp.union.mi.dy = abs_y
            inp.union.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
            
            self._send_input(inp)
        else:
            # 人类化移动（贝塞尔曲线）
            self._human_like_move(x, y, duration)
    
    def _human_like_move(self, target_x: int, target_y: int, duration: float):
        """
        人类化鼠标移动（使用贝塞尔曲线）
        
        Args:
            target_x, target_y: 目标位置
            duration: 移动持续时间
        """
        start_x, start_y = self.get_mouse_position()
        
        # 生成贝塞尔曲线控制点
        points = self._generate_bezier_points(
            start_x, start_y, target_x, target_y,
            self.config.movement_steps
        )
        
        step_duration = duration / len(points)
        
        for px, py in points:
            abs_x, abs_y = self._to_absolute_coords(int(px), int(py))
            
            inp = INPUT()
            inp.type = INPUT_MOUSE
            inp.union.mi.dx = abs_x
            inp.union.mi.dy = abs_y
            inp.union.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
            
            self._send_input(inp)
            
            # 添加轻微的随机延迟
            time.sleep(step_duration * random.uniform(0.8, 1.2))
    
    def _generate_bezier_points(self, x1: int, y1: int, x2: int, y2: int, 
                                steps: int) -> List[Tuple[float, float]]:
        """
        生成贝塞尔曲线路径点
        
        使用二次贝塞尔曲线，控制点随机偏移
        """
        # 计算控制点（在中点附近随机偏移）
        mid_x = (x1 + x2) / 2
        mid_y = (y1 + y2) / 2
        
        # 偏移量与距离成比例
        distance = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
        offset_range = min(distance * 0.3, 100)
        
        ctrl_x = mid_x + random.uniform(-offset_range, offset_range)
        ctrl_y = mid_y + random.uniform(-offset_range, offset_range)
        
        # 生成曲线点
        points = []
        for i in range(steps + 1):
            t = i / steps
            # 二次贝塞尔曲线公式
            px = (1 - t) ** 2 * x1 + 2 * (1 - t) * t * ctrl_x + t ** 2 * x2
            py = (1 - t) ** 2 * y1 + 2 * (1 - t) * t * ctrl_y + t ** 2 * y2
            points.append((px, py))
        
        return points
    
    def click(self, x: int = None, y: int = None, 
              button: MouseButton = MouseButton.LEFT,
              clicks: int = 1):
        """
        点击鼠标
        
        Args:
            x, y: 点击位置（None则在当前位置点击）
            button: 鼠标按钮
            clicks: 点击次数
        """
        # 移动到位置
        if x is not None and y is not None:
            self.move_to(x, y, duration=0.1 if self.config.human_like_movement else 0)
            self._random_delay(30, 80)
        
        # 确定按钮标志
        if button == MouseButton.LEFT:
            down_flag = MOUSEEVENTF_LEFTDOWN
            up_flag = MOUSEEVENTF_LEFTUP
        elif button == MouseButton.RIGHT:
            down_flag = MOUSEEVENTF_RIGHTDOWN
            up_flag = MOUSEEVENTF_RIGHTUP
        else:
            down_flag = MOUSEEVENTF_MIDDLEDOWN
            up_flag = MOUSEEVENTF_MIDDLEUP
        
        # 执行点击
        for _ in range(clicks):
            # 按下
            inp_down = INPUT()
            inp_down.type = INPUT_MOUSE
            inp_down.union.mi.dwFlags = down_flag
            self._send_input(inp_down)
            
            # 点击持续时间
            click_time = random.randint(
                self.config.click_duration_min,
                self.config.click_duration_max
            ) / 1000.0
            time.sleep(click_time)
            
            # 释放
            inp_up = INPUT()
            inp_up.type = INPUT_MOUSE
            inp_up.union.mi.dwFlags = up_flag
            self._send_input(inp_up)
            
            # 多次点击间隔
            if clicks > 1:
                self._random_delay(50, 150)
    
    def double_click(self, x: int = None, y: int = None):
        """双击"""
        self.click(x, y, MouseButton.LEFT, clicks=2)
    
    def right_click(self, x: int = None, y: int = None):
        """右键点击"""
        self.click(x, y, MouseButton.RIGHT)

    def mouse_down(self, button: MouseButton = MouseButton.LEFT):
        """按下鼠标按钮但不释放。"""
        down_flag, _ = self._mouse_button_flags(button)
        inp_down = INPUT()
        inp_down.type = INPUT_MOUSE
        inp_down.union.mi.dwFlags = down_flag
        self._send_input(inp_down)

    def mouse_up(self, button: MouseButton = MouseButton.LEFT):
        """释放鼠标按钮。"""
        _, up_flag = self._mouse_button_flags(button)
        inp_up = INPUT()
        inp_up.type = INPUT_MOUSE
        inp_up.union.mi.dwFlags = up_flag
        self._send_input(inp_up)

    def drag_begin(self, start_x: int, start_y: int,
                   button: MouseButton = MouseButton.LEFT,
                   fast_mode: bool = False):
        """开始一次持续拖拽，会移动到起点并按下鼠标。"""
        self.move_to(start_x, start_y)
        if fast_mode:
            time.sleep(random.uniform(0.004, 0.012))
        else:
            self._random_delay(50, 100)
        self.mouse_down(button)
        if fast_mode:
            time.sleep(random.uniform(0.003, 0.01))
        else:
            self._random_delay(30, 80)

    def drag_move_to(self, x: int, y: int, duration: float = 0.0,
                     fast_mode: bool = False):
        """在保持按下状态的情况下继续拖到指定位置。"""
        self.move_to(x, y, duration=duration)
        if fast_mode:
            time.sleep(random.uniform(0.001, 0.006))

    def drag_end(self, button: MouseButton = MouseButton.LEFT,
                 fast_mode: bool = False):
        """结束一次持续拖拽并释放鼠标。"""
        if fast_mode:
            time.sleep(random.uniform(0.002, 0.008))
        else:
            self._random_delay(30, 80)
        self.mouse_up(button)
    
    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int,
             button: MouseButton = MouseButton.LEFT, duration: float = 0.5,
             fast_mode: bool = False):
        """
        拖拽操作
        
        Args:
            start_x, start_y: 起始位置
            end_x, end_y: 结束位置
            button: 使用的鼠标按钮
            duration: 拖拽持续时间
            fast_mode: 快速续拖模式，减少起手和收尾停顿
        """
        self.drag_begin(start_x, start_y, button=button, fast_mode=fast_mode)
        self.drag_move_to(end_x, end_y, duration=duration, fast_mode=fast_mode)
        self.drag_end(button=button, fast_mode=fast_mode)
    
    def scroll(self, clicks: int, x: int = None, y: int = None):
        """
        滚动鼠标滚轮
        
        Args:
            clicks: 滚动量（正数向上，负数向下）
            x, y: 滚动位置（None则在当前位置）
        """
        if x is not None and y is not None:
            self.move_to(x, y)
            self._random_delay(30, 80)
        
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi.dwFlags = MOUSEEVENTF_WHEEL
        inp.union.mi.mouseData = ctypes.c_ulong(clicks * 120)  # WHEEL_DELTA = 120
        
        self._send_input(inp)
    
    # ==================== 键盘操作 ====================
    
    def _get_vk_code(self, key: str) -> Tuple[int, bool]:
        """
        获取虚拟键码
        
        Args:
            key: 按键名称
            
        Returns:
            (虚拟键码, 是否扩展键)
        """
        key_lower = key.lower()
        
        if key_lower in VK_CODES:
            vk = VK_CODES[key_lower]
            extended = key_lower in EXTENDED_KEYS
            return (vk, extended)
        
        # 单个字符
        if len(key) == 1:
            vk = self.user32.VkKeyScanW(ord(key)) & 0xFF
            return (vk, False)
        
        raise ValueError(f"未知的按键: {key}")
    
    def key_down(self, key: str):
        """
        按下按键（不释放）
        
        Args:
            key: 按键名称
        """
        vk, extended = self._get_vk_code(key)
        
        flags = KEYEVENTF_KEYDOWN
        if extended:
            flags |= KEYEVENTF_EXTENDEDKEY
        
        # 获取扫描码
        scan = self.user32.MapVirtualKeyW(vk, 0)
        
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki.wVk = vk
        inp.union.ki.wScan = scan
        inp.union.ki.dwFlags = flags
        
        self._send_input(inp)
    
    def key_up(self, key: str):
        """
        释放按键
        
        Args:
            key: 按键名称
        """
        vk, extended = self._get_vk_code(key)
        
        flags = KEYEVENTF_KEYUP
        if extended:
            flags |= KEYEVENTF_EXTENDEDKEY
        
        scan = self.user32.MapVirtualKeyW(vk, 0)
        
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki.wVk = vk
        inp.union.ki.wScan = scan
        inp.union.ki.dwFlags = flags
        
        self._send_input(inp)
    
    def press(self, key: str, duration: float = None):
        """
        按下并释放按键
        
        Args:
            key: 按键名称
            duration: 按住时间（None则使用随机时间）
        """
        self.key_down(key)
        
        if duration is None:
            self._random_delay(50, 120)
        else:
            time.sleep(duration)
        
        self.key_up(key)
    
    def type_text(self, text: str, interval: float = None):
        """
        输入文本
        
        Args:
            text: 要输入的文本
            interval: 按键间隔（None则使用随机间隔）
        """
        for char in text:
            if char == '\n':
                self.press('enter')
            elif char == '\t':
                self.press('tab')
            elif char == ' ':
                self.press('space')
            else:
                # 使用Unicode输入
                inp_down = INPUT()
                inp_down.type = INPUT_KEYBOARD
                inp_down.union.ki.wVk = 0
                inp_down.union.ki.wScan = ord(char)
                inp_down.union.ki.dwFlags = KEYEVENTF_UNICODE
                
                inp_up = INPUT()
                inp_up.type = INPUT_KEYBOARD
                inp_up.union.ki.wVk = 0
                inp_up.union.ki.wScan = ord(char)
                inp_up.union.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
                
                self._send_input(inp_down)
                self._random_delay(20, 60)
                self._send_input(inp_up)
            
            # 字符间隔
            if interval is None:
                self._random_delay(30, 100)
            else:
                time.sleep(interval)
    
    def hotkey(self, *keys):
        """
        执行组合键
        
        Args:
            *keys: 按键序列，如 hotkey('ctrl', 'c')
        """
        # 按顺序按下所有键
        for key in keys:
            self.key_down(key)
            self._random_delay(20, 50)
        
        self._random_delay(30, 80)
        
        # 逆序释放所有键
        for key in reversed(keys):
            self.key_up(key)
            self._random_delay(20, 50)
    
    # ==================== 便捷方法 ====================
    
    def ctrl_c(self):
        """复制"""
        self.hotkey('ctrl', 'c')
    
    def ctrl_v(self):
        """粘贴"""
        self.hotkey('ctrl', 'v')
    
    def ctrl_a(self):
        """全选"""
        self.hotkey('ctrl', 'a')
    
    def ctrl_z(self):
        """撤销"""
        self.hotkey('ctrl', 'z')
    
    def alt_tab(self):
        """切换窗口"""
        self.hotkey('alt', 'tab')
    
    def alt_f4(self):
        """关闭窗口"""
        self.hotkey('alt', 'f4')


# ==================== 后台输入模拟器 ====================

# 后台消息常量
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_RBUTTONDBLCLK = 0x0206
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MBUTTONDBLCLK = 0x0209
WM_MOUSEWHEEL = 0x020A
WM_SETCURSOR = 0x0020
WM_MOUSEACTIVATE = 0x0021

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102

HTCLIENT = 0x0001
MA_ACTIVATE = 0x0001

MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002
MK_MBUTTON = 0x0010


class BackgroundInputSimulator:
    """
    后台输入模拟器
    
    使用 PostMessage/SendMessage 向目标窗口发送输入消息，
    不会真正移动物理鼠标或获取焦点，适用于后台操作。
    
    注意：
    1. 部分程序可能不响应 PostMessage（使用 DirectInput 等）
    2. 某些目标环境可能检测到这种方式
    3. 坐标是相对于窗口客户区的
    """
    
    def __init__(self, hwnd: int = None):
        """
        初始化后台输入模拟器
        
        Args:
            hwnd: 目标窗口句柄
        """
        self.hwnd = hwnd
        self.user32 = ctypes.windll.user32
        # 设置 PostMessageW / SendMessageW 正确的参数类型，
        # 避免 64 位系统上从工作线程调用时的类型转换问题
        self.user32.PostMessageW.argtypes = [
            ctypes.wintypes.HWND, ctypes.wintypes.UINT,
            ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
        ]
        self.user32.PostMessageW.restype = ctypes.wintypes.BOOL
        self.user32.SendMessageW.argtypes = [
            ctypes.wintypes.HWND, ctypes.wintypes.UINT,
            ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
        ]
        self.user32.SendMessageW.restype = ctypes.wintypes.LPARAM
        self.config = InputConfig()
        self._child_hwnd = None  # 缓存的子窗口句柄
        self._drag_wparam = 0
        self._drag_up_msg = 0
        self._drag_pos = None
        
    def set_window(self, hwnd: int):
        """设置目标窗口"""
        self.hwnd = hwnd
        self._child_hwnd = None  # 重置子窗口缓存
    
    def _check_hwnd(self):
        """检查窗口句柄有效性"""
        if self.hwnd is None:
            raise ValueError("未设置目标窗口句柄")
        if not self.user32.IsWindow(self.hwnd):
            raise ValueError("无效的窗口句柄")
    
    def _find_deepest_child_at_point(self, x: int, y: int) -> int:
        """
        查找指定坐标处最深层的子窗口
        
        Args:
            x, y: 相对于父窗口客户区的坐标
            
        Returns:
            子窗口句柄，如果没有子窗口则返回原窗口句柄
        """
        self._check_hwnd()
        
        # 转换为屏幕坐标
        import win32gui
        try:
            screen_x, screen_y = win32gui.ClientToScreen(self.hwnd, (x, y))
        except:
            return self.hwnd
        
        # 使用 WindowFromPoint 找到最顶层的窗口
        target_hwnd = self.user32.WindowFromPoint(ctypes.c_long(screen_x), ctypes.c_long(screen_y))
        
        if target_hwnd and target_hwnd != 0:
            # 检查找到的窗口是否是目标窗口的子窗口
            if self.user32.IsChild(self.hwnd, target_hwnd):
                return target_hwnd
            # 如果是目标窗口本身，直接返回
            if target_hwnd == self.hwnd:
                return self.hwnd
        
        # 尝试递归查找子窗口
        return self._find_child_recursive(self.hwnd, x, y) or self.hwnd
    
    def _find_child_recursive(self, parent_hwnd: int, x: int, y: int) -> Optional[int]:
        """递归查找包含指定点的子窗口"""
        import win32gui
        
        child_hwnds = []
        
        def enum_callback(hwnd, param):
            child_hwnds.append(hwnd)
            return True
        
        try:
            win32gui.EnumChildWindows(parent_hwnd, enum_callback, None)
        except:
            return None
        
        for child_hwnd in child_hwnds:
            try:
                # 获取子窗口相对于父窗口的位置
                rect = win32gui.GetWindowRect(child_hwnd)
                parent_rect = win32gui.GetWindowRect(parent_hwnd)
                
                # 转换为相对坐标
                rel_left = rect[0] - parent_rect[0]
                rel_top = rect[1] - parent_rect[1]
                rel_right = rect[2] - parent_rect[0]
                rel_bottom = rect[3] - parent_rect[1]
                
                if rel_left <= x <= rel_right and rel_top <= y <= rel_bottom:
                    # 递归检查这个子窗口的子窗口
                    deeper_child = self._find_child_recursive(child_hwnd, x - rel_left, y - rel_top)
                    return deeper_child or child_hwnd
            except:
                continue
        
        return None
    
    def _make_lparam(self, x: int, y: int) -> int:
        """创建 lParam（坐标打包）"""
        return (y << 16) | (x & 0xFFFF)
    
    def _post_message(self, msg: int, wparam: int, lparam: int) -> bool:
        """发送消息（异步，不等待响应）"""
        return bool(self.user32.PostMessageW(self.hwnd, msg, wparam, lparam))
    
    def _send_message(self, msg: int, wparam: int, lparam: int) -> int:
        """发送消息（同步，等待响应）"""
        return self.user32.SendMessageW(self.hwnd, msg, wparam, lparam)
    
    def _random_delay(self, min_ms: int = None, max_ms: int = None):
        """添加随机延迟"""
        min_ms = min_ms or self.config.random_delay_min
        max_ms = max_ms or self.config.random_delay_max
        delay = random.randint(min_ms, max_ms) / 1000.0
        time.sleep(delay)

    @staticmethod
    def _mouse_button_messages(button: MouseButton):
        if button == MouseButton.LEFT:
            return WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON
        if button == MouseButton.RIGHT:
            return WM_RBUTTONDOWN, WM_RBUTTONUP, MK_RBUTTON
        return WM_MBUTTONDOWN, WM_MBUTTONUP, MK_MBUTTON
    
    # ==================== 后台鼠标操作 ====================
    
    def move_to(self, x: int, y: int):
        """
        后台移动鼠标（仅发送消息，不移动真实鼠标）
        
        Args:
            x, y: 相对于窗口客户区的坐标
        """
        self._check_hwnd()
        lparam = self._make_lparam(x, y)
        self._post_message(WM_MOUSEMOVE, 0, lparam)
    
    def click(self, x: int, y: int, button: MouseButton = MouseButton.LEFT, clicks: int = 1):
        """
        后台点击（不移动真实鼠标）
        
        会自动查找坐标处的子窗口并发送消息，适配模拟器等多窗口应用。
        
        Args:
            x, y: 相对于窗口客户区的坐标
            button: 鼠标按钮
            clicks: 点击次数
        """
        self._check_hwnd()
        
        # 查找点击点所在的子窗口
        target_hwnd, child_x, child_y = self._resolve_click_target(x, y)
        
        lparam = self._make_lparam(child_x, child_y)
        
        # 确定消息类型
        if button == MouseButton.LEFT:
            down_msg = WM_LBUTTONDOWN
            up_msg = WM_LBUTTONUP
            wparam = MK_LBUTTON
        elif button == MouseButton.RIGHT:
            down_msg = WM_RBUTTONDOWN
            up_msg = WM_RBUTTONUP
            wparam = MK_RBUTTON
        else:
            down_msg = WM_MBUTTONDOWN
            up_msg = WM_MBUTTONUP
            wparam = MK_MBUTTON

        # 先同步父窗口与目标窗口的悬停状态，提升后台点击命中率
        self._prime_click_target(target_hwnd, x, y, child_x, child_y, down_msg)
        self._random_delay(10, 30)
        
        # 执行点击
        for _ in range(clicks):
            self._send_to(target_hwnd, down_msg, wparam, lparam)
            
            # 点击持续时间
            click_time = random.randint(
                self.config.click_duration_min,
                self.config.click_duration_max
            ) / 1000.0
            time.sleep(click_time)
            
            self._send_to(target_hwnd, up_msg, 0, lparam)
            
            if clicks > 1:
                self._random_delay(50, 150)
    
    def _resolve_click_target(self, x: int, y: int):
        """
        查找坐标点对应的实际目标窗口，并转换为相对坐标
        
        对于模拟器等应用，实际内容可能渲染在子窗口（甚至孙窗口）中，
        PostMessage 必须发到最深层的子窗口才能生效。
        
        搜索策略：枚举所有后代窗口，找到包含该点的面积最小的可见窗口
        （面积最小 = 嵌套最深的子窗口）
        
        Args:
            x, y: 相对于主窗口客户区的坐标
            
        Returns:
            (target_hwnd, rel_x, rel_y) 目标窗口句柄和相对坐标
        """
        import win32gui

        try:
            deepest_hwnd = self._find_deepest_child_at_point(x, y)
            if deepest_hwnd and deepest_hwnd != 0:
                if deepest_hwnd == self.hwnd:
                    return (self.hwnd, x, y)
                screen_x, screen_y = win32gui.ClientToScreen(self.hwnd, (x, y))
                child_x, child_y = win32gui.ScreenToClient(deepest_hwnd, (screen_x, screen_y))
                return (deepest_hwnd, child_x, child_y)
        except Exception:
            pass
        
        try:
            # 将客户区坐标转为屏幕坐标
            screen_x, screen_y = win32gui.ClientToScreen(self.hwnd, (x, y))
        except:
            return (self.hwnd, x, y)
        
        # 枚举所有后代窗口，找到包含该点的最小（最深层）可见窗口
        best_hwnd = None
        best_area = float('inf')
        
        def _enum_callback(child_hwnd, _):
            nonlocal best_hwnd, best_area
            try:
                # 跳过不可见的窗口
                if not win32gui.IsWindowVisible(child_hwnd):
                    return True
                    
                rect = win32gui.GetWindowRect(child_hwnd)
                left, top, right, bottom = rect
                
                # 检查点是否在窗口范围内
                if left <= screen_x <= right and top <= screen_y <= bottom:
                    area = (right - left) * (bottom - top)
                    if area > 0 and area < best_area:
                        best_area = area
                        best_hwnd = child_hwnd
            except:
                pass
            return True
        
        try:
            win32gui.EnumChildWindows(self.hwnd, _enum_callback, None)
        except:
            pass
        
        if best_hwnd and best_hwnd != self.hwnd:
            try:
                child_x, child_y = win32gui.ScreenToClient(best_hwnd, (screen_x, screen_y))
                return (best_hwnd, child_x, child_y)
            except:
                pass
        
        # 回退：直接用主窗口
        return (self.hwnd, x, y)
    
    def _post_to(self, hwnd: int, msg: int, wparam: int, lparam: int) -> bool:
        """向指定窗口发送消息"""
        return bool(self.user32.PostMessageW(hwnd, msg, wparam, lparam))

    def _send_to(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        """向指定窗口同步发送消息，确保关键鼠标事件按顺序处理。"""
        return self.user32.SendMessageW(hwnd, msg, wparam, lparam)

    def _prime_click_target(self, target_hwnd: int, root_x: int, root_y: int,
                            target_x: int, target_y: int, down_msg: int):
        """点击前先同步鼠标移动和激活消息，提高部分窗口/模拟器的后台点击响应率。"""
        root_lparam = self._make_lparam(root_x, root_y)
        target_lparam = self._make_lparam(target_x, target_y)

        if target_hwnd != self.hwnd:
            self._post_to(self.hwnd, WM_MOUSEMOVE, 0, root_lparam)
            time.sleep(0.005)

        self._post_to(target_hwnd, WM_MOUSEMOVE, 0, target_lparam)
        time.sleep(0.005)

        try:
            self._send_to(target_hwnd, WM_SETCURSOR, target_hwnd, (HTCLIENT & 0xFFFF) | (WM_MOUSEMOVE << 16))
            self._send_to(target_hwnd, WM_MOUSEACTIVATE, self.hwnd, (HTCLIENT & 0xFFFF) | (down_msg << 16))
        except Exception:
            pass
    
    def double_click(self, x: int, y: int):
        """后台双击"""
        self._check_hwnd()
        
        target_hwnd, child_x, child_y = self._resolve_click_target(x, y)
        lparam = self._make_lparam(child_x, child_y)

        self._prime_click_target(target_hwnd, x, y, child_x, child_y, WM_LBUTTONDBLCLK)
        self._random_delay(10, 30)
        self._send_to(target_hwnd, WM_LBUTTONDBLCLK, MK_LBUTTON, lparam)
        self._random_delay(30, 80)
        self._send_to(target_hwnd, WM_LBUTTONUP, 0, lparam)
    
    def right_click(self, x: int, y: int):
        """后台右键点击"""
        self.click(x, y, MouseButton.RIGHT)

    def drag_begin(self, start_x: int, start_y: int,
                   button: MouseButton = MouseButton.LEFT,
                   fast_mode: bool = False):
        """开始一次后台持续拖拽。"""
        self._check_hwnd()
        down_msg, up_msg, wparam = self._mouse_button_messages(button)
        start_lparam = self._make_lparam(start_x, start_y)
        self._post_message(WM_MOUSEMOVE, 0, start_lparam)
        if fast_mode:
            time.sleep(random.uniform(0.003, 0.01))
        else:
            self._random_delay(30, 80)
        self._post_message(down_msg, wparam, start_lparam)
        self._drag_wparam = wparam
        self._drag_up_msg = up_msg
        self._drag_pos = (int(start_x), int(start_y))

    def drag_move_to(self, end_x: int, end_y: int, duration: float = 0.0,
                     steps: int = 10, fast_mode: bool = False):
        """在保持按下状态的情况下继续后台拖拽。"""
        self._check_hwnd()
        if self._drag_pos is None:
            raise RuntimeError("后台拖拽尚未开始")

        start_x, start_y = self._drag_pos
        steps = max(3, int(steps if not fast_mode else min(steps, 6)))
        step_delay = duration / steps if steps > 0 else duration
        for i in range(1, steps + 1):
            progress = i / steps
            current_x = int(round(start_x + (end_x - start_x) * progress))
            current_y = int(round(start_y + (end_y - start_y) * progress))
            lparam = self._make_lparam(current_x, current_y)
            self._post_message(WM_MOUSEMOVE, self._drag_wparam, lparam)
            if step_delay > 0:
                time.sleep(step_delay * random.uniform(0.8, 1.2))
        self._drag_pos = (int(end_x), int(end_y))
        if fast_mode:
            time.sleep(random.uniform(0.001, 0.006))

    def drag_end(self, end_x: int = None, end_y: int = None,
                 fast_mode: bool = False):
        """结束后台持续拖拽并释放鼠标。"""
        self._check_hwnd()
        if self._drag_pos is None:
            return

        release_x, release_y = self._drag_pos
        if end_x is not None and end_y is not None:
            release_x = int(end_x)
            release_y = int(end_y)
            lparam = self._make_lparam(release_x, release_y)
            self._post_message(WM_MOUSEMOVE, self._drag_wparam, lparam)

        if fast_mode:
            time.sleep(random.uniform(0.002, 0.008))
        else:
            self._random_delay(30, 80)
        end_lparam = self._make_lparam(release_x, release_y)
        self._post_message(self._drag_up_msg, 0, end_lparam)
        self._drag_pos = None
        self._drag_wparam = 0
        self._drag_up_msg = 0
    
    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int,
             button: MouseButton = MouseButton.LEFT, steps: int = 10, duration: float = 0.3,
             fast_mode: bool = False):
        """
        后台拖拽
        
        Args:
            start_x, start_y: 起始位置
            end_x, end_y: 结束位置
            button: 鼠标按钮
            steps: 移动步数
            duration: 持续时间
            fast_mode: 快速续拖模式，减少起手和收尾停顿
        """
        self.drag_begin(start_x, start_y, button=button, fast_mode=fast_mode)
        self.drag_move_to(end_x, end_y, duration=duration, steps=steps, fast_mode=fast_mode)
        self.drag_end(end_x, end_y, fast_mode=fast_mode)
    
    def scroll(self, x: int, y: int, delta: int):
        """
        后台滚动
        
        Args:
            x, y: 滚动位置
            delta: 滚动量（正数向上，负数向下）
        """
        self._check_hwnd()
        lparam = self._make_lparam(x, y)
        wparam = (delta * 120) << 16  # WHEEL_DELTA = 120
        self._post_message(WM_MOUSEWHEEL, wparam, lparam)
    
    # ==================== 后台键盘操作 ====================
    
    def key_down(self, key: str):
        """后台按下按键"""
        self._check_hwnd()
        vk = self._get_vk_code(key)
        self._post_message(WM_KEYDOWN, vk, 0)
    
    def key_up(self, key: str):
        """后台释放按键"""
        self._check_hwnd()
        vk = self._get_vk_code(key)
        self._post_message(WM_KEYUP, vk, 0)
    
    def press(self, key: str, duration: float = None):
        """后台按下并释放按键"""
        self.key_down(key)
        
        if duration is None:
            self._random_delay(50, 120)
        else:
            time.sleep(duration)
        
        self.key_up(key)
    
    def type_text(self, text: str, interval: float = None):
        """
        后台输入文本
        
        Args:
            text: 要输入的文本
            interval: 按键间隔
        """
        self._check_hwnd()
        
        for char in text:
            if char == '\n':
                self.press('enter')
            elif char == '\t':
                self.press('tab')
            else:
                # 发送 WM_CHAR 消息
                self._post_message(WM_CHAR, ord(char), 0)
            
            if interval is None:
                self._random_delay(30, 100)
            else:
                time.sleep(interval)
    
    def hotkey(self, *keys):
        """后台执行组合键"""
        for key in keys:
            self.key_down(key)
            self._random_delay(20, 50)
        
        self._random_delay(30, 80)
        
        for key in reversed(keys):
            self.key_up(key)
            self._random_delay(20, 50)
    
    def _get_vk_code(self, key: str) -> int:
        """获取虚拟键码"""
        key_lower = key.lower()
        
        if key_lower in VK_CODES:
            return VK_CODES[key_lower]
        
        if len(key) == 1:
            return self.user32.VkKeyScanW(ord(key)) & 0xFF
        
        raise ValueError(f"未知的按键: {key}")


# 测试代码
if __name__ == "__main__":
    simulator = InputSimulator()
    
    print("输入模拟器测试")
    print(f"屏幕分辨率: {simulator.screen_width}x{simulator.screen_height}")
    
    current_pos = simulator.get_mouse_position()
    print(f"当前鼠标位置: {current_pos}")
    
    print("\n3秒后将移动鼠标到屏幕中央...")
    time.sleep(3)
    
    center_x = simulator.screen_width // 2
    center_y = simulator.screen_height // 2
    
    simulator.move_to(center_x, center_y, duration=0.5)
    print(f"已移动到: ({center_x}, {center_y})")
