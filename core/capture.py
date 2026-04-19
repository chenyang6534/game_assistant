"""
屏幕捕获模块
使用 mss 库进行高性能屏幕截图
"""

import time
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass

import numpy as np

try:
    import mss
    import mss.tools
except ImportError:
    raise ImportError("请安装 mss: pip install mss")

try:
    from PIL import Image
except ImportError:
    raise ImportError("请安装 Pillow: pip install Pillow")

try:
    import win32gui
    import win32ui
    import win32con
except ImportError:
    raise ImportError("请安装 pywin32: pip install pywin32")


@dataclass
class CaptureRegion:
    """截图区域"""
    left: int
    top: int
    width: int
    height: int
    
    @property
    def right(self) -> int:
        return self.left + self.width
    
    @property
    def bottom(self) -> int:
        return self.top + self.height
    
    def to_dict(self) -> Dict[str, int]:
        """转换为mss所需的字典格式"""
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height
        }


class ScreenCapture:
    """屏幕捕获器"""
    
    def __init__(self):
        self._sct = mss.mss()
        self._last_capture_time = 0
        self._fps_limit = 60  # 默认FPS限制
    
    @property
    def monitors(self) -> list:
        """获取所有显示器信息"""
        return self._sct.monitors
    
    @property
    def primary_monitor(self) -> dict:
        """获取主显示器信息"""
        # monitors[0] 是所有显示器的组合，monitors[1] 是主显示器
        return self._sct.monitors[1] if len(self._sct.monitors) > 1 else self._sct.monitors[0]
    
    def set_fps_limit(self, fps: int):
        """设置截图FPS限制"""
        self._fps_limit = max(1, min(fps, 120))

    @staticmethod
    def _ensure_bgr_contiguous(img: np.ndarray) -> np.ndarray:
        """确保返回的 BGR 图像是连续内存，便于传给 Qt / PIL。"""
        bgr = img[:, :, :3]
        return np.ascontiguousarray(bgr)
    
    def capture_screen(self, monitor_index: int = 0) -> np.ndarray:
        """
        截取整个屏幕
        
        Args:
            monitor_index: 显示器索引 (0=所有显示器组合, 1=主显示器, 2+=其他显示器)
            
        Returns:
            BGR格式的numpy数组 (OpenCV兼容)
        """
        monitor = self._sct.monitors[monitor_index]
        return self._capture_region(monitor)
    
    def capture_region(self, region: CaptureRegion) -> np.ndarray:
        """
        截取指定区域
        
        Args:
            region: CaptureRegion对象
            
        Returns:
            BGR格式的numpy数组
        """
        return self._capture_region(region.to_dict())
    
    def capture_window(self, hwnd: int, client_only: bool = True) -> Optional[np.ndarray]:
        """
        截取指定窗口
        
        Args:
            hwnd: 窗口句柄
            client_only: 仅截取客户区域（不含标题栏和边框）
            
        Returns:
            BGR格式的numpy数组，失败返回None
        """
        try:
            if not win32gui.IsWindow(hwnd):
                return None
            
            if client_only:
                # 获取客户区域
                client_rect = win32gui.GetClientRect(hwnd)
                point = win32gui.ClientToScreen(hwnd, (0, 0))
                
                region = {
                    "left": point[0],
                    "top": point[1],
                    "width": client_rect[2],
                    "height": client_rect[3]
                }
            else:
                # 获取整个窗口区域
                rect = win32gui.GetWindowRect(hwnd)
                region = {
                    "left": rect[0],
                    "top": rect[1],
                    "width": rect[2] - rect[0],
                    "height": rect[3] - rect[1]
                }
            
            # 验证区域有效性
            if region["width"] <= 0 or region["height"] <= 0:
                return None
            
            return self._capture_region(region)
            
        except Exception as e:
            print(f"截取窗口失败: {e}")
            return None
    
    def capture_window_bitblt(self, hwnd: int) -> Optional[np.ndarray]:
        """
        使用BitBlt方式截取窗口（可以截取被遮挡的窗口）
        
        注意: 某些DirectX/OpenGL游戏可能无法使用此方法
        
        Args:
            hwnd: 窗口句柄
            
        Returns:
            BGR格式的numpy数组，失败返回None
        """
        try:
            if not win32gui.IsWindow(hwnd):
                return None
            
            # 获取窗口大小
            rect = win32gui.GetClientRect(hwnd)
            width = rect[2]
            height = rect[3]
            
            if width <= 0 or height <= 0:
                return None
            
            # 获取窗口DC
            hwnd_dc = win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()
            
            # 创建位图
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(bitmap)
            
            # 执行BitBlt
            save_dc.BitBlt((0, 0), (width, height), mfc_dc, (0, 0), win32con.SRCCOPY)
            
            # 转换为numpy数组
            bmp_info = bitmap.GetInfo()
            bmp_str = bitmap.GetBitmapBits(True)
            
            img = np.frombuffer(bmp_str, dtype=np.uint8)
            img = img.reshape((bmp_info['bmHeight'], bmp_info['bmWidth'], 4))
            
            # 清理资源
            win32gui.DeleteObject(bitmap.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)
            
            # BGRA -> BGR，并转为连续内存，避免 QImage 报错
            return self._ensure_bgr_contiguous(img)
            
        except Exception as e:
            print(f"BitBlt截图失败: {e}")
            return None
    
    def capture_window_printwindow(self, hwnd: int, client_only: bool = True) -> Optional[np.ndarray]:
        """
        使用PrintWindow方式截取窗口（适用于后台窗口，包括被遮挡/最小化的窗口）
        
        这是最可靠的后台截图方法，但某些使用硬件加速的程序可能返回黑屏。
        
        Args:
            hwnd: 窗口句柄
            client_only: 是否仅截取客户区
            
        Returns:
            BGR格式的numpy数组，失败返回None
        """
        import ctypes
        
        PW_CLIENTONLY = 0x00000001
        PW_RENDERFULLCONTENT = 0x00000002  # Windows 8.1+
        
        try:
            if not win32gui.IsWindow(hwnd):
                return None
            
            # 获取窗口大小
            if client_only:
                rect = win32gui.GetClientRect(hwnd)
                width = rect[2]
                height = rect[3]
            else:
                rect = win32gui.GetWindowRect(hwnd)
                width = rect[2] - rect[0]
                height = rect[3] - rect[1]
            
            if width <= 0 or height <= 0:
                return None
            
            # 创建设备上下文
            hwnd_dc = win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()
            
            # 创建位图
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(bitmap)
            
            # 使用PrintWindow捕获
            flags = PW_RENDERFULLCONTENT
            if client_only:
                flags |= PW_CLIENTONLY
            
            result = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), flags)
            
            if not result:
                # 回退到不带 PW_RENDERFULLCONTENT 的方式（兼容旧系统）
                flags = PW_CLIENTONLY if client_only else 0
                result = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), flags)
            
            if not result:
                raise Exception("PrintWindow 返回失败")
            
            # 转换为numpy数组
            bmp_info = bitmap.GetInfo()
            bmp_str = bitmap.GetBitmapBits(True)
            
            img = np.frombuffer(bmp_str, dtype=np.uint8)
            img = img.reshape((bmp_info['bmHeight'], bmp_info['bmWidth'], 4))
            
            # 清理资源
            win32gui.DeleteObject(bitmap.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)
            
            # BGRA -> BGR，并转为连续内存，避免 QImage 报错
            return self._ensure_bgr_contiguous(img)
            
        except Exception as e:
            print(f"PrintWindow截图失败: {e}")
            return None
    
    def capture_window_background(self, hwnd: int, method: str = "auto") -> Optional[np.ndarray]:
        """
        后台截取窗口（智能选择最佳方法）
        
        即使窗口被遮挡、在后台或最小化也能截取。
        
        Args:
            hwnd: 窗口句柄
            method: 截图方法
                - "auto": 自动选择最佳方法
                - "printwindow": 使用PrintWindow（最通用）
                - "bitblt": 使用BitBlt（较快但可能失败）
            
        Returns:
            BGR格式的numpy数组，失败返回None
        """
        if method == "auto":
            # 首先尝试PrintWindow（最可靠）
            result = self.capture_window_printwindow(hwnd)
            if result is not None and not self._is_black_image(result):
                return result
            
            # 回退到BitBlt
            result = self.capture_window_bitblt(hwnd)
            if result is not None and not self._is_black_image(result):
                return result
            
            # 最后尝试普通截图
            return self.capture_window(hwnd)
        
        elif method == "printwindow":
            return self.capture_window_printwindow(hwnd)
        
        elif method == "bitblt":
            return self.capture_window_bitblt(hwnd)
        
        else:
            raise ValueError(f"未知的截图方法: {method}")
    
    def _is_black_image(self, img: np.ndarray, threshold: float = 0.99) -> bool:
        """检查图像是否几乎全黑（可能是截图失败）"""
        if img is None or img.size == 0:
            return True
        
        # 计算黑色像素比例
        black_pixels = np.sum(img < 10)
        total_pixels = img.size
        
        return (black_pixels / total_pixels) > threshold
    
    def _capture_region(self, region: Dict[str, int]) -> np.ndarray:
        """
        内部方法：截取指定区域
        
        Args:
            region: 包含 left, top, width, height 的字典
            
        Returns:
            BGR格式的numpy数组
        """
        # FPS限制
        current_time = time.time()
        min_interval = 1.0 / self._fps_limit
        elapsed = current_time - self._last_capture_time
        
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        
        self._last_capture_time = time.time()
        
        # 执行截图
        sct_img = self._sct.grab(region)
        
        # 转换为numpy数组 (BGRA -> BGR)
        img = np.array(sct_img)
        return self._ensure_bgr_contiguous(img)
    
    def capture_to_pil(self, region: CaptureRegion = None) -> Image.Image:
        """
        截图并返回PIL Image对象
        
        Args:
            region: 截图区域，None则截取主显示器
            
        Returns:
            PIL Image对象
        """
        if region:
            img_np = self.capture_region(region)
        else:
            img_np = self.capture_screen(1)  # 主显示器
        
        # BGR -> RGB
        img_rgb = img_np[:, :, ::-1]
        return Image.fromarray(img_rgb)
    
    def save_screenshot(self, filepath: str, region: CaptureRegion = None) -> bool:
        """
        截图并保存到文件
        
        Args:
            filepath: 保存路径
            region: 截图区域
            
        Returns:
            是否成功
        """
        try:
            img = self.capture_to_pil(region)
            img.save(filepath)
            return True
        except Exception as e:
            print(f"保存截图失败: {e}")
            return False
    
    def __del__(self):
        """清理资源"""
        try:
            self._sct.close()
        except Exception:
            pass


class CapturePerformanceMonitor:
    """截图性能监控"""
    
    def __init__(self):
        self._frame_times = []
        self._max_samples = 60
    
    def record_frame(self, capture_time: float):
        """记录一帧的截图时间"""
        self._frame_times.append(capture_time)
        if len(self._frame_times) > self._max_samples:
            self._frame_times.pop(0)
    
    @property
    def average_fps(self) -> float:
        """计算平均FPS"""
        if len(self._frame_times) < 2:
            return 0.0
        
        total_time = self._frame_times[-1] - self._frame_times[0]
        if total_time <= 0:
            return 0.0
        
        return (len(self._frame_times) - 1) / total_time
    
    @property
    def average_frame_time(self) -> float:
        """计算平均帧时间（毫秒）"""
        if self.average_fps <= 0:
            return 0.0
        return 1000.0 / self.average_fps


# 测试代码
if __name__ == "__main__":
    import cv2
    
    capture = ScreenCapture()
    
    print("=== 显示器信息 ===")
    for i, mon in enumerate(capture.monitors):
        print(f"显示器 {i}: {mon}")
    
    print("\n=== 截取主显示器 ===")
    img = capture.capture_screen(1)
    print(f"截图大小: {img.shape}")
    
    # 保存测试截图
    cv2.imwrite("test_screenshot.png", img)
    print("已保存 test_screenshot.png")
    
    print("\n=== 性能测试 ===")
    monitor = CapturePerformanceMonitor()
    capture.set_fps_limit(60)
    
    for i in range(30):
        start = time.time()
        img = capture.capture_screen(1)
        monitor.record_frame(time.time())
    
    print(f"平均FPS: {monitor.average_fps:.1f}")
    print(f"平均帧时间: {monitor.average_frame_time:.2f}ms")
