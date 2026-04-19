"""
脚本回放模块
使用精确定时回放录制的脚本
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import threading
from typing import Optional, Callable, List
from enum import Enum, auto
from dataclasses import dataclass

from recorder.listener import InputEvent, EventType
from recorder.storage import Script
from core.input import InputSimulator, BackgroundInputSimulator, MouseButton


class PlayerState(Enum):
    """播放器状态"""
    STOPPED = auto()
    PLAYING = auto()
    PAUSED = auto()


@dataclass
class PlaybackConfig:
    """回放配置"""
    speed: float = 1.0          # 回放速度（1.0为原速）
    loop_count: int = 1         # 循环次数（0表示无限）
    loop_delay: float = 1.0     # 循环间隔（秒）
    skip_mouse_move: bool = False  # 跳过鼠标移动事件
    use_relative_coords: bool = False  # 使用相对坐标
    offset_x: int = 0           # X坐标偏移
    offset_y: int = 0           # Y坐标偏移
    background_mode: bool = False  # 后台模式（不移动真实鼠标）
    target_hwnd: int = None     # 目标窗口句柄（后台模式必需）


class ScriptPlayer:
    """脚本播放器"""
    
    def __init__(self, config: PlaybackConfig = None):
        """
        初始化播放器
        
        Args:
            config: 回放配置
        """
        self.config = config or PlaybackConfig()
        self.state = PlayerState.STOPPED
        
        # 根据配置选择输入模拟器
        self._input = InputSimulator()
        self._bg_input: Optional[BackgroundInputSimulator] = None
        
        if self.config.background_mode and self.config.target_hwnd:
            self._bg_input = BackgroundInputSimulator(self.config.target_hwnd)
        self._thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        self._pause_flag = threading.Event()
        
        # 当前播放状态
        self._current_script: Optional[Script] = None
        self._current_event_index: int = 0
        self._current_loop: int = 0
        
        # 回调函数
        self.on_start: Optional[Callable[[], None]] = None
        self.on_stop: Optional[Callable[[], None]] = None
        self.on_pause: Optional[Callable[[], None]] = None
        self.on_resume: Optional[Callable[[], None]] = None
        self.on_loop: Optional[Callable[[int], None]] = None  # 参数：当前循环次数
        self.on_event: Optional[Callable[[InputEvent, int], None]] = None  # 参数：事件，索引
        self.on_progress: Optional[Callable[[float], None]] = None  # 参数：进度0-1
        self.on_error: Optional[Callable[[Exception], None]] = None
    
    def play(self, script: Script, config: PlaybackConfig = None):
        """
        开始播放脚本
        
        Args:
            script: 要播放的脚本
            config: 回放配置（可选，覆盖默认配置）
        """
        if self.state == PlayerState.PLAYING:
            self.stop()
        
        if config:
            self.config = config
            # 更新后台输入模拟器
            if self.config.background_mode and self.config.target_hwnd:
                self._bg_input = BackgroundInputSimulator(self.config.target_hwnd)
            else:
                self._bg_input = None
        
        self._current_script = script
        self._current_event_index = 0
        self._current_loop = 0
        self._stop_flag.clear()
        self._pause_flag.clear()
        
        self.state = PlayerState.PLAYING
        
        # 启动播放线程
        self._thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._thread.start()
        
        if self.on_start:
            self.on_start()
    
    def play_events(self, events: List[InputEvent], config: PlaybackConfig = None):
        """
        播放事件列表（不需要完整脚本）
        
        Args:
            events: 事件列表
            config: 回放配置
        """
        from .storage import Script, ScriptMetadata
        
        metadata = ScriptMetadata(name="temp_script")
        script = Script(metadata=metadata, events=events)
        self.play(script, config)
    
    def stop(self):
        """停止播放"""
        if self.state == PlayerState.STOPPED:
            return
        
        self._stop_flag.set()
        self._pause_flag.clear()  # 确保暂停状态也能停止
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        
        self.state = PlayerState.STOPPED
        
        if self.on_stop:
            self.on_stop()
    
    def pause(self):
        """暂停播放"""
        if self.state != PlayerState.PLAYING:
            return
        
        self._pause_flag.set()
        self.state = PlayerState.PAUSED
        
        if self.on_pause:
            self.on_pause()
    
    def resume(self):
        """恢复播放"""
        if self.state != PlayerState.PAUSED:
            return
        
        self._pause_flag.clear()
        self.state = PlayerState.PLAYING
        
        if self.on_resume:
            self.on_resume()
    
    def toggle_pause(self):
        """切换暂停状态"""
        if self.state == PlayerState.PLAYING:
            self.pause()
        elif self.state == PlayerState.PAUSED:
            self.resume()
    
    def set_background_mode(self, enabled: bool, hwnd: int = None):
        """
        设置后台模式
        
        后台模式下，鼠标操作不会移动真实鼠标指针，
        而是直接向目标窗口发送消息。
        
        Args:
            enabled: 是否启用后台模式
            hwnd: 目标窗口句柄（启用时必须提供）
        """
        self.config.background_mode = enabled
        self.config.target_hwnd = hwnd
        
        if enabled and hwnd:
            self._bg_input = BackgroundInputSimulator(hwnd)
        else:
            self._bg_input = None
    
    def set_target_window(self, hwnd: int):
        """
        设置目标窗口（自动启用后台模式）
        
        Args:
            hwnd: 窗口句柄
        """
        self.set_background_mode(True, hwnd)

    def _playback_loop(self):
        """播放主循环"""
        try:
            while not self._stop_flag.is_set():
                # 执行一次循环
                self._play_once()
                
                self._current_loop += 1
                
                # 检查循环次数
                if self.config.loop_count > 0 and self._current_loop >= self.config.loop_count:
                    break
                
                # 触发循环回调
                if self.on_loop:
                    self.on_loop(self._current_loop)
                
                # 循环间隔
                if not self._stop_flag.is_set():
                    self._interruptible_sleep(self.config.loop_delay)
            
        except Exception as e:
            if self.on_error:
                self.on_error(e)
            else:
                print(f"播放错误: {e}")
        finally:
            self.state = PlayerState.STOPPED
            if self.on_stop:
                self.on_stop()
    
    def _play_once(self):
        """播放一次脚本"""
        events = self._current_script.events
        if not events:
            return
        
        total_events = len(events)
        last_timestamp = 0
        
        for i, event in enumerate(events):
            # 检查停止标志
            if self._stop_flag.is_set():
                return
            
            # 检查暂停
            while self._pause_flag.is_set():
                if self._stop_flag.is_set():
                    return
                time.sleep(0.01)
            
            # 计算等待时间
            wait_time = (event.timestamp - last_timestamp) / 1000.0 / self.config.speed
            if wait_time > 0:
                self._interruptible_sleep(wait_time)
            
            if self._stop_flag.is_set():
                return
            
            # 执行事件
            self._execute_event(event)
            
            last_timestamp = event.timestamp
            self._current_event_index = i
            
            # 触发回调
            if self.on_event:
                self.on_event(event, i)
            
            if self.on_progress:
                progress = (i + 1) / total_events
                self.on_progress(progress)
    
    def _interruptible_sleep(self, duration: float):
        """可中断的睡眠"""
        end_time = time.perf_counter() + duration
        while time.perf_counter() < end_time:
            if self._stop_flag.is_set():
                return
            remaining = end_time - time.perf_counter()
            time.sleep(min(remaining, 0.01))
    
    def _execute_event(self, event: InputEvent):
        """执行单个事件"""
        # 应用坐标偏移
        x = event.x + self.config.offset_x
        y = event.y + self.config.offset_y
        
        # 检查是否使用后台模式
        use_background = self.config.background_mode and self._bg_input is not None
        
        if event.event_type == EventType.MOUSE_MOVE:
            if not self.config.skip_mouse_move:
                if use_background:
                    self._bg_input.move_to(x, y)
                else:
                    self._input.move_to(x, y)
        
        elif event.event_type == EventType.MOUSE_CLICK:
            button_map = {
                'left': MouseButton.LEFT,
                'right': MouseButton.RIGHT,
                'middle': MouseButton.MIDDLE,
            }
            button = button_map.get(event.button, MouseButton.LEFT)
            
            if use_background:
                # 后台模式：使用 PostMessage
                if event.pressed:
                    self._bg_input.click(x, y, button, clicks=1)
                # 后台模式下按下和释放合并为一次 click，所以释放时不做操作
            else:
                # 前台模式：使用 SendInput
                if event.pressed:
                    # 移动到位置
                    self._input.move_to(x, y, duration=0)
                    # 按下
                    self._mouse_down(button)
                else:
                    # 释放
                    self._mouse_up(button)
        
        elif event.event_type == EventType.MOUSE_SCROLL:
            if use_background:
                self._bg_input.scroll(x, y, event.scroll_dy)
            else:
                self._input.move_to(x, y, duration=0)
                self._input.scroll(event.scroll_dy)
        
        elif event.event_type == EventType.KEY_PRESS:
            if use_background:
                self._bg_input.key_down(event.key or event.key_char)
            else:
                self._key_press(event.key, event.key_char)
        
        elif event.event_type == EventType.KEY_RELEASE:
            if use_background:
                self._bg_input.key_up(event.key or event.key_char)
            else:
                self._key_release(event.key, event.key_char)
    
    def _mouse_down(self, button: MouseButton):
        """鼠标按下"""
        import ctypes
        from core.input import (
            INPUT, INPUT_MOUSE, MOUSEEVENTF_LEFTDOWN, 
            MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_MIDDLEDOWN
        )
        
        flag_map = {
            MouseButton.LEFT: MOUSEEVENTF_LEFTDOWN,
            MouseButton.RIGHT: MOUSEEVENTF_RIGHTDOWN,
            MouseButton.MIDDLE: MOUSEEVENTF_MIDDLEDOWN,
        }
        
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi.dwFlags = flag_map.get(button, MOUSEEVENTF_LEFTDOWN)
        self._input._send_input(inp)
    
    def _mouse_up(self, button: MouseButton):
        """鼠标释放"""
        import ctypes
        from core.input import (
            INPUT, INPUT_MOUSE, MOUSEEVENTF_LEFTUP,
            MOUSEEVENTF_RIGHTUP, MOUSEEVENTF_MIDDLEUP
        )
        
        flag_map = {
            MouseButton.LEFT: MOUSEEVENTF_LEFTUP,
            MouseButton.RIGHT: MOUSEEVENTF_RIGHTUP,
            MouseButton.MIDDLE: MOUSEEVENTF_MIDDLEUP,
        }
        
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi.dwFlags = flag_map.get(button, MOUSEEVENTF_LEFTUP)
        self._input._send_input(inp)
    
    def _key_press(self, key: str, key_char: str = None):
        """按键按下"""
        if key_char and len(key_char) == 1:
            # 可打印字符
            self._input.key_down(key_char)
        elif key:
            # 特殊按键
            try:
                self._input.key_down(key)
            except ValueError:
                pass  # 忽略未知按键
    
    def _key_release(self, key: str, key_char: str = None):
        """按键释放"""
        if key_char and len(key_char) == 1:
            self._input.key_up(key_char)
        elif key:
            try:
                self._input.key_up(key)
            except ValueError:
                pass
    
    @property
    def is_playing(self) -> bool:
        """是否正在播放"""
        return self.state == PlayerState.PLAYING
    
    @property
    def is_paused(self) -> bool:
        """是否已暂停"""
        return self.state == PlayerState.PAUSED
    
    @property
    def current_loop(self) -> int:
        """当前循环次数"""
        return self._current_loop
    
    @property
    def current_event_index(self) -> int:
        """当前事件索引"""
        return self._current_event_index


class PlaybackScheduler:
    """回放调度器 - 支持定时和条件触发"""
    
    def __init__(self, player: ScriptPlayer):
        self.player = player
        self._scheduled_tasks: List[dict] = []
    
    def schedule_at(self, script: Script, run_time: str):
        """
        在指定时间播放脚本
        
        Args:
            script: 脚本
            run_time: 运行时间 (格式: "HH:MM:SS")
        """
        # TODO: 实现定时播放
        pass
    
    def schedule_interval(self, script: Script, interval: float, 
                         start_immediately: bool = True):
        """
        定间隔播放脚本
        
        Args:
            script: 脚本
            interval: 间隔（秒）
            start_immediately: 是否立即开始
        """
        # TODO: 实现间隔播放
        pass


# 测试代码
if __name__ == "__main__":
    from .listener import EventListener
    from .storage import create_script_from_events
    
    # 创建播放器
    player = ScriptPlayer()
    
    # 设置回调
    player.on_start = lambda: print("开始播放")
    player.on_stop = lambda: print("停止播放")
    player.on_progress = lambda p: print(f"进度: {p*100:.1f}%")
    
    # 创建测试事件
    test_events = [
        InputEvent(EventType.MOUSE_MOVE, 0, x=500, y=500),
        InputEvent(EventType.MOUSE_CLICK, 500, x=500, y=500, button='left', pressed=True),
        InputEvent(EventType.MOUSE_CLICK, 600, x=500, y=500, button='left', pressed=False),
        InputEvent(EventType.MOUSE_MOVE, 1000, x=600, y=400),
        InputEvent(EventType.KEY_PRESS, 1500, key='a', key_char='a'),
        InputEvent(EventType.KEY_RELEASE, 1600, key='a', key_char='a'),
    ]
    
    script = create_script_from_events(test_events, "test_playback")
    
    print("3秒后开始回放测试...")
    time.sleep(3)
    
    # 配置回放
    config = PlaybackConfig(
        speed=0.5,  # 半速播放
        loop_count=2  # 播放2次
    )
    
    # 开始播放
    player.play(script, config)
    
    # 等待播放完成
    while player.is_playing or player.is_paused:
        time.sleep(0.1)
    
    print("回放完成")
