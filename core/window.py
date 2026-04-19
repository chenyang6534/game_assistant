"""
窗口管理模块
使用 win32gui 枚举和管理 Windows 窗口
"""

import ctypes
from typing import List, Tuple, Optional, NamedTuple
from dataclasses import dataclass

try:
    import win32gui
    import win32con
    import win32process
except ImportError:
    raise ImportError("请安装 pywin32: pip install pywin32")


@dataclass
class WindowInfo:
    """窗口信息数据类"""
    hwnd: int           # 窗口句柄
    title: str          # 窗口标题
    class_name: str     # 窗口类名
    x: int              # 左上角X坐标
    y: int              # 左上角Y坐标
    width: int          # 宽度
    height: int         # 高度
    pid: int            # 进程ID
    is_visible: bool    # 是否可见
    
    def __str__(self):
        return f"{self.title} ({self.width}x{self.height})"
    
    @property
    def rect(self) -> Tuple[int, int, int, int]:
        """返回窗口矩形 (left, top, right, bottom)"""
        return (self.x, self.y, self.x + self.width, self.y + self.height)


class WindowManager:
    """Windows窗口管理器"""
    
    def __init__(self):
        # 设置DPI感知，避免高DPI屏幕坐标错位
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    
    def get_all_windows(self, visible_only: bool = True, 
                        with_title_only: bool = True) -> List[WindowInfo]:
        """
        获取所有窗口列表
        
        Args:
            visible_only: 仅返回可见窗口
            with_title_only: 仅返回有标题的窗口
            
        Returns:
            WindowInfo列表
        """
        windows = []
        
        def enum_callback(hwnd, _):
            try:
                # 检查可见性
                is_visible = win32gui.IsWindowVisible(hwnd)
                if visible_only and not is_visible:
                    return True
                
                # 获取标题
                title = win32gui.GetWindowText(hwnd)
                if with_title_only and not title.strip():
                    return True
                
                # 获取窗口类名
                class_name = win32gui.GetClassName(hwnd)
                
                # 获取窗口位置和大小
                rect = win32gui.GetWindowRect(hwnd)
                x, y = rect[0], rect[1]
                width = rect[2] - rect[0]
                height = rect[3] - rect[1]
                
                # 过滤掉最小化或无效大小的窗口
                if width <= 0 or height <= 0:
                    return True
                
                # 获取进程ID
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                
                window_info = WindowInfo(
                    hwnd=hwnd,
                    title=title,
                    class_name=class_name,
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                    pid=pid,
                    is_visible=is_visible
                )
                windows.append(window_info)
                
            except Exception:
                pass
            
            return True
        
        win32gui.EnumWindows(enum_callback, None)
        return windows
    
    def get_game_windows(self) -> List[WindowInfo]:
        """
        获取可能是游戏的窗口（过滤系统窗口）
        
        Returns:
            过滤后的WindowInfo列表
        """
        # 常见系统窗口类名，需要排除
        system_classes = {
            'Shell_TrayWnd',           # 任务栏
            'Progman',                  # 桌面
            'WorkerW',                  # 桌面
            'Windows.UI.Core.CoreWindow',  # UWP应用
            'ApplicationFrameWindow',   # 部分UWP
            'tooltips_class32',         # 工具提示
            'TaskManagerWindow',        # 任务管理器
        }
        
        # 常见系统窗口标题关键词
        system_titles = {
            'Program Manager',
            'NVIDIA GeForce Overlay',
            'MSCTFIME UI',
            'Default IME',
        }
        
        all_windows = self.get_all_windows()
        game_windows = []
        
        for win in all_windows:
            # 排除系统类
            if win.class_name in system_classes:
                continue
            
            # 排除系统标题
            if any(st in win.title for st in system_titles):
                continue
            
            # 排除太小的窗口（可能是工具提示等）
            if win.width < 200 or win.height < 150:
                continue
            
            game_windows.append(win)
        
        return game_windows
    
    def get_window_by_hwnd(self, hwnd: int) -> Optional[WindowInfo]:
        """
        根据句柄获取窗口信息
        
        Args:
            hwnd: 窗口句柄
            
        Returns:
            WindowInfo 或 None
        """
        try:
            if not win32gui.IsWindow(hwnd):
                return None
            
            title = win32gui.GetWindowText(hwnd)
            class_name = win32gui.GetClassName(hwnd)
            rect = win32gui.GetWindowRect(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            
            return WindowInfo(
                hwnd=hwnd,
                title=title,
                class_name=class_name,
                x=rect[0],
                y=rect[1],
                width=rect[2] - rect[0],
                height=rect[3] - rect[1],
                pid=pid,
                is_visible=win32gui.IsWindowVisible(hwnd)
            )
        except Exception:
            return None
    
    def get_window_by_title(self, title: str, exact: bool = False) -> Optional[WindowInfo]:
        """
        根据标题查找窗口
        
        Args:
            title: 窗口标题（或部分标题）
            exact: 是否精确匹配
            
        Returns:
            WindowInfo 或 None
        """
        windows = self.get_all_windows()
        
        for win in windows:
            if exact:
                if win.title == title:
                    return win
            else:
                if title.lower() in win.title.lower():
                    return win
        
        return None
    
    def bring_to_front(self, hwnd: int) -> bool:
        """
        将窗口置于前台
        
        Args:
            hwnd: 窗口句柄
            
        Returns:
            是否成功
        """
        try:
            # 如果窗口最小化，先恢复
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            
            # 设置为前台窗口
            win32gui.SetForegroundWindow(hwnd)
            return True
        except Exception:
            return False
    
    def set_window_position(self, hwnd: int, x: int, y: int, 
                           width: int = None, height: int = None) -> bool:
        """
        设置窗口位置和大小
        
        Args:
            hwnd: 窗口句柄
            x, y: 新位置
            width, height: 新大小（可选）
            
        Returns:
            是否成功
        """
        try:
            flags = win32con.SWP_NOZORDER
            
            if width is None or height is None:
                flags |= win32con.SWP_NOSIZE
                width = 0
                height = 0
            
            win32gui.SetWindowPos(hwnd, None, x, y, width, height, flags)
            return True
        except Exception:
            return False
    
    def get_client_rect(self, hwnd: int) -> Optional[Tuple[int, int, int, int]]:
        """
        获取窗口客户区域（不含标题栏和边框）的屏幕坐标
        
        Args:
            hwnd: 窗口句柄
            
        Returns:
            (left, top, right, bottom) 或 None
        """
        try:
            # 获取客户区域大小
            client_rect = win32gui.GetClientRect(hwnd)
            
            # 将客户区域左上角转换为屏幕坐标
            point = win32gui.ClientToScreen(hwnd, (0, 0))
            
            left = point[0]
            top = point[1]
            right = left + client_rect[2]
            bottom = top + client_rect[3]
            
            return (left, top, right, bottom)
        except Exception:
            return None
    
    def is_window_valid(self, hwnd: int) -> bool:
        """检查窗口是否有效"""
        try:
            return win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd)
        except Exception:
            return False


# 测试代码
if __name__ == "__main__":
    manager = WindowManager()
    
    print("=== 所有游戏窗口 ===")
    windows = manager.get_game_windows()
    
    for i, win in enumerate(windows[:10]):  # 显示前10个
        print(f"{i+1}. [{win.hwnd}] {win.title}")
        print(f"   类名: {win.class_name}")
        print(f"   位置: ({win.x}, {win.y}) 大小: {win.width}x{win.height}")
        print()
