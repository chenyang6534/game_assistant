"""
事件监听模块
使用 pynput 监听鼠标和键盘事件
"""

import time
import threading
from typing import List, Callable, Optional
from enum import Enum, auto
from dataclasses import dataclass, field
from datetime import datetime

try:
    from pynput import mouse, keyboard
    from pynput.mouse import Button as MouseButton
    from pynput.keyboard import Key, KeyCode
except ImportError:
    raise ImportError("请安装 pynput: pip install pynput")


class EventType(Enum):
    """事件类型枚举"""
    # 鼠标事件
    MOUSE_MOVE = auto()
    MOUSE_CLICK = auto()
    MOUSE_SCROLL = auto()
    
    # 键盘事件
    KEY_PRESS = auto()
    KEY_RELEASE = auto()


@dataclass
class InputEvent:
    """输入事件数据类"""
    event_type: EventType
    timestamp: float          # 相对时间戳（相对于录制开始，毫秒）
    
    # 鼠标相关
    x: int = 0
    y: int = 0
    button: str = None        # 'left', 'right', 'middle'
    pressed: bool = True      # 点击事件：按下/释放
    scroll_dx: int = 0
    scroll_dy: int = 0
    
    # 键盘相关
    key: str = None           # 按键名称
    key_char: str = None      # 字符（如果是可打印字符）
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'event_type': self.event_type.name,
            'timestamp': self.timestamp,
            'x': self.x,
            'y': self.y,
            'button': self.button,
            'pressed': self.pressed,
            'scroll_dx': self.scroll_dx,
            'scroll_dy': self.scroll_dy,
            'key': self.key,
            'key_char': self.key_char,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'InputEvent':
        """从字典创建"""
        return cls(
            event_type=EventType[data['event_type']],
            timestamp=data['timestamp'],
            x=data.get('x', 0),
            y=data.get('y', 0),
            button=data.get('button'),
            pressed=data.get('pressed', True),
            scroll_dx=data.get('scroll_dx', 0),
            scroll_dy=data.get('scroll_dy', 0),
            key=data.get('key'),
            key_char=data.get('key_char'),
        )


class EventListener:
    """事件监听器"""
    
    def __init__(self):
        self.events: List[InputEvent] = []
        self.is_recording = False
        self.is_paused = False
        self.start_time: float = 0
        
        self._mouse_listener: Optional[mouse.Listener] = None
        self._keyboard_listener: Optional[keyboard.Listener] = None
        self._lock = threading.Lock()
        
        # 配置
        self.record_mouse_move = True   # 是否录制鼠标移动
        self.move_interval = 50         # 鼠标移动记录间隔（毫秒）
        self._last_move_time = 0
        
        # 回调函数
        self.on_event: Optional[Callable[[InputEvent], None]] = None
    
    def start_recording(self):
        """开始录制"""
        if self.is_recording:
            return
        
        with self._lock:
            self.events.clear()
            self.is_recording = True
            self.is_paused = False
            self.start_time = time.perf_counter() * 1000  # 转换为毫秒
            self._last_move_time = 0
        
        # 启动鼠标监听
        self._mouse_listener = mouse.Listener(
            on_move=self._on_mouse_move,
            on_click=self._on_mouse_click,
            on_scroll=self._on_mouse_scroll
        )
        self._mouse_listener.start()
        
        # 启动键盘监听
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release
        )
        self._keyboard_listener.start()
    
    def stop_recording(self) -> List[InputEvent]:
        """
        停止录制
        
        Returns:
            录制的事件列表
        """
        if not self.is_recording:
            return self.events
        
        with self._lock:
            self.is_recording = False
        
        # 停止监听器
        if self._mouse_listener:
            self._mouse_listener.stop()
            self._mouse_listener = None
        
        if self._keyboard_listener:
            self._keyboard_listener.stop()
            self._keyboard_listener = None
        
        return self.events.copy()
    
    def pause_recording(self):
        """暂停录制"""
        self.is_paused = True
    
    def resume_recording(self):
        """恢复录制"""
        self.is_paused = False
    
    def _get_timestamp(self) -> float:
        """获取相对时间戳（毫秒）"""
        return time.perf_counter() * 1000 - self.start_time
    
    def _add_event(self, event: InputEvent):
        """添加事件"""
        if not self.is_recording or self.is_paused:
            return
        
        with self._lock:
            self.events.append(event)
        
        # 触发回调
        if self.on_event:
            self.on_event(event)
    
    def _on_mouse_move(self, x: int, y: int):
        """鼠标移动事件"""
        if not self.record_mouse_move:
            return
        
        # 限制记录频率
        current_time = self._get_timestamp()
        if current_time - self._last_move_time < self.move_interval:
            return
        self._last_move_time = current_time
        
        event = InputEvent(
            event_type=EventType.MOUSE_MOVE,
            timestamp=current_time,
            x=x,
            y=y
        )
        self._add_event(event)
    
    def _on_mouse_click(self, x: int, y: int, button: MouseButton, pressed: bool):
        """鼠标点击事件"""
        button_name = {
            MouseButton.left: 'left',
            MouseButton.right: 'right',
            MouseButton.middle: 'middle',
        }.get(button, str(button))
        
        event = InputEvent(
            event_type=EventType.MOUSE_CLICK,
            timestamp=self._get_timestamp(),
            x=x,
            y=y,
            button=button_name,
            pressed=pressed
        )
        self._add_event(event)
    
    def _on_mouse_scroll(self, x: int, y: int, dx: int, dy: int):
        """鼠标滚动事件"""
        event = InputEvent(
            event_type=EventType.MOUSE_SCROLL,
            timestamp=self._get_timestamp(),
            x=x,
            y=y,
            scroll_dx=dx,
            scroll_dy=dy
        )
        self._add_event(event)
    
    def _key_to_string(self, key) -> tuple:
        """
        将按键转换为字符串
        
        Returns:
            (按键名称, 字符或None)
        """
        if isinstance(key, KeyCode):
            if key.char:
                return (key.char, key.char)
            elif key.vk:
                return (f'vk_{key.vk}', None)
        elif isinstance(key, Key):
            return (key.name, None)
        
        return (str(key), None)
    
    def _on_key_press(self, key):
        """按键按下事件"""
        key_name, key_char = self._key_to_string(key)
        
        event = InputEvent(
            event_type=EventType.KEY_PRESS,
            timestamp=self._get_timestamp(),
            key=key_name,
            key_char=key_char,
            pressed=True
        )
        self._add_event(event)
    
    def _on_key_release(self, key):
        """按键释放事件"""
        key_name, key_char = self._key_to_string(key)
        
        event = InputEvent(
            event_type=EventType.KEY_RELEASE,
            timestamp=self._get_timestamp(),
            key=key_name,
            key_char=key_char,
            pressed=False
        )
        self._add_event(event)
    
    @property
    def event_count(self) -> int:
        """获取已录制的事件数量"""
        return len(self.events)
    
    @property
    def duration(self) -> float:
        """获取录制时长（毫秒）"""
        if not self.events:
            return 0
        return self.events[-1].timestamp


class EventFilter:
    """事件过滤器"""
    
    @staticmethod
    def filter_by_type(events: List[InputEvent], 
                      event_types: List[EventType]) -> List[InputEvent]:
        """按事件类型过滤"""
        return [e for e in events if e.event_type in event_types]
    
    @staticmethod
    def remove_redundant_moves(events: List[InputEvent], 
                              min_distance: int = 5) -> List[InputEvent]:
        """
        移除冗余的鼠标移动事件
        
        Args:
            events: 事件列表
            min_distance: 最小移动距离
            
        Returns:
            过滤后的事件列表
        """
        result = []
        last_move = None
        
        for event in events:
            if event.event_type == EventType.MOUSE_MOVE:
                if last_move is None:
                    result.append(event)
                    last_move = event
                else:
                    # 计算距离
                    dx = event.x - last_move.x
                    dy = event.y - last_move.y
                    distance = (dx * dx + dy * dy) ** 0.5
                    
                    if distance >= min_distance:
                        result.append(event)
                        last_move = event
            else:
                result.append(event)
                # 非移动事件前的最后一个位置也保留
                last_move = None
        
        return result
    
    @staticmethod
    def merge_key_events(events: List[InputEvent]) -> List[InputEvent]:
        """
        合并按键事件（将 KEY_PRESS + KEY_RELEASE 合并为单个事件）
        
        仅用于简化脚本查看，实际回放应使用原始事件
        """
        result = []
        pending_press = {}  # key_name -> event
        
        for event in events:
            if event.event_type == EventType.KEY_PRESS:
                pending_press[event.key] = event
            elif event.event_type == EventType.KEY_RELEASE:
                if event.key in pending_press:
                    # 已有按下事件，保留按下和释放
                    result.append(pending_press.pop(event.key))
                    result.append(event)
                else:
                    result.append(event)
            else:
                result.append(event)
        
        # 添加未释放的按键
        result.extend(pending_press.values())
        
        return result


# 测试代码
if __name__ == "__main__":
    listener = EventListener()
    listener.record_mouse_move = False  # 测试时不录制鼠标移动
    
    def on_event(event: InputEvent):
        print(f"[{event.timestamp:.0f}ms] {event.event_type.name}: ", end="")
        if event.event_type in (EventType.MOUSE_CLICK, EventType.MOUSE_SCROLL):
            print(f"({event.x}, {event.y}) button={event.button} pressed={event.pressed}")
        elif event.event_type in (EventType.KEY_PRESS, EventType.KEY_RELEASE):
            print(f"key={event.key} char={event.key_char}")
        else:
            print(f"({event.x}, {event.y})")
    
    listener.on_event = on_event
    
    print("开始录制（5秒后自动停止）...")
    print("请进行一些鼠标点击和键盘操作...\n")
    
    listener.start_recording()
    time.sleep(5)
    events = listener.stop_recording()
    
    print(f"\n录制完成，共 {len(events)} 个事件")
    print(f"录制时长: {listener.duration:.0f}ms")
