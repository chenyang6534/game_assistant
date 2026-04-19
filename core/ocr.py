"""
OCR文字识别模块
使用 rapidocr-onnxruntime 进行文字识别
"""

import os
from typing import List, Tuple, Optional
from dataclasses import dataclass

import numpy as np

try:
    from rapidocr_onnxruntime import RapidOCR
    HAS_RAPIDOCR = True
except ImportError:
    HAS_RAPIDOCR = False

try:
    import cv2
except ImportError:
    raise ImportError("请安装 opencv-python: pip install opencv-python")


@dataclass
class TextResult:
    """文字识别结果"""
    text: str           # 识别的文字
    x: int              # 左上角X坐标
    y: int              # 左上角Y坐标
    width: int          # 宽度
    height: int         # 高度
    confidence: float   # 置信度 (0-1)
    
    @property
    def center(self) -> Tuple[int, int]:
        """返回中心点坐标"""
        return (self.x + self.width // 2, self.y + self.height // 2)
    
    @property
    def rect(self) -> Tuple[int, int, int, int]:
        """返回矩形 (x, y, width, height)"""
        return (self.x, self.y, self.width, self.height)
    
    def __str__(self):
        return f"'{self.text}' at ({self.x}, {self.y}) conf={self.confidence:.2f}"


class OCRRecognition:
    """OCR文字识别器"""
    
    def __init__(self):
        """初始化OCR识别器"""
        self._ocr = None
        self._initialized = False
        self._init_error = None
        self._warmup_done = False
        
        # 尝试初始化OCR引擎
        self._init_ocr()
    
    def _init_ocr(self):
        """初始化OCR引擎"""
        if not HAS_RAPIDOCR:
            self._init_error = "未安装rapidocr-onnxruntime，请运行: pip install rapidocr-onnxruntime"
            return
        
        try:
            self._ocr = RapidOCR()
            self._initialized = True
            # 预热引擎：第一次调用加载模型较慢，用小图预热
            self._warmup()
        except Exception as e:
            self._init_error = f"初始化OCR失败: {e}"
    
    def _warmup(self):
        """预热OCR引擎，加载模型到内存"""
        if self._warmup_done or not self._initialized:
            return
        try:
            # 用一个很小的图片预热，强制加载所有模型
            dummy = np.zeros((32, 100, 3), dtype=np.uint8)
            # 写一些白色文字模拟内容
            dummy[8:24, 10:90] = 255
            self._ocr(dummy, use_det=True, use_cls=False, use_rec=True)
            self._warmup_done = True
        except Exception:
            # 预热失败不影响正常使用
            self._warmup_done = True
    
    @property
    def is_available(self) -> bool:
        """OCR是否可用"""
        return self._initialized
    
    @property
    def error_message(self) -> Optional[str]:
        """获取错误信息"""
        return self._init_error
    
    def recognize(self, image: np.ndarray, 
                  min_confidence: float = 0.5) -> List[TextResult]:
        """
        识别图像中的文字
        
        Args:
            image: 图像 (BGR格式的numpy数组)
            min_confidence: 最小置信度阈值
            
        Returns:
            TextResult列表
        """
        if not self._initialized:
            return []
        
        if image is None or image.size == 0:
            return []
        
        try:
            # 确保图像是正确的格式
            if len(image.shape) == 2:
                # 灰度图，转换为BGR
                image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            elif image.shape[2] == 4:
                # BGRA格式，转换为BGR
                image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
            
            # 执行OCR识别（跳过文字方向分类器cls，游戏文字总是水平的）
            result, elapse = self._ocr(image, use_det=True, use_cls=False, use_rec=True)
            
            if result is None:
                return []
            
            text_results = []
            for item in result:
                # item格式: [box, text, confidence]
                # box格式: [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
                box = item[0]
                text = item[1]
                confidence = float(item[2]) if item[2] is not None else 0.0
                
                if confidence < min_confidence:
                    continue
                
                # 计算边界框
                x_coords = [p[0] for p in box]
                y_coords = [p[1] for p in box]
                
                x = int(min(x_coords))
                y = int(min(y_coords))
                width = int(max(x_coords) - x)
                height = int(max(y_coords) - y)
                
                text_results.append(TextResult(
                    text=text,
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                    confidence=confidence
                ))
            
            # 按y坐标排序（从上到下），再按x坐标排序（从左到右）
            text_results.sort(key=lambda r: (r.y // 20, r.x))
            
            return text_results
            
        except Exception as e:
            print(f"OCR识别失败: {e}")
            return []
    
    def find_text(self, image: np.ndarray, 
                  target_text: str,
                  exact_match: bool = False,
                  min_confidence: float = 0.5) -> Optional[TextResult]:
        """
        在图像中查找指定文字
        
        Args:
            image: 图像
            target_text: 要查找的文字
            exact_match: 是否精确匹配
            min_confidence: 最小置信度
            
        Returns:
            找到的TextResult或None
        """
        results = self.recognize(image, min_confidence)
        
        for result in results:
            if exact_match:
                if result.text == target_text:
                    return result
            else:
                if target_text in result.text:
                    return result
        
        return None
    
    def find_all_text(self, image: np.ndarray,
                      target_text: str,
                      exact_match: bool = False,
                      min_confidence: float = 0.5) -> List[TextResult]:
        """
        在图像中查找所有匹配的文字
        
        Args:
            image: 图像
            target_text: 要查找的文字
            exact_match: 是否精确匹配
            min_confidence: 最小置信度
            
        Returns:
            匹配的TextResult列表
        """
        results = self.recognize(image, min_confidence)
        
        matches = []
        for result in results:
            if exact_match:
                if result.text == target_text:
                    matches.append(result)
            else:
                if target_text in result.text:
                    matches.append(result)
        
        return matches
    
    def draw_results(self, image: np.ndarray, 
                     results: List[TextResult],
                     color: Tuple[int, int, int] = (0, 255, 0),
                     thickness: int = 2) -> np.ndarray:
        """
        在图像上绘制识别结果
        
        Args:
            image: 原始图像
            results: 识别结果列表
            color: 边框颜色 (BGR)
            thickness: 边框粗细
            
        Returns:
            绘制后的图像
        """
        output = image.copy()
        
        for result in results:
            # 绘制边框
            cv2.rectangle(
                output,
                (result.x, result.y),
                (result.x + result.width, result.y + result.height),
                color,
                thickness
            )
            
            # 绘制文字（在框上方）
            label = f"{result.text} ({result.confidence:.2f})"
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.5
            
            # 获取文字大小
            (text_width, text_height), baseline = cv2.getTextSize(
                label, font, font_scale, 1
            )
            
            # 绘制文字背景
            cv2.rectangle(
                output,
                (result.x, result.y - text_height - 5),
                (result.x + text_width, result.y),
                color,
                -1
            )
            
            # 绘制文字
            cv2.putText(
                output,
                label,
                (result.x, result.y - 5),
                font,
                font_scale,
                (0, 0, 0),
                1
            )
        
        return output


# 测试代码
if __name__ == "__main__":
    ocr = OCRRecognition()
    
    if not ocr.is_available:
        print(f"OCR不可用: {ocr.error_message}")
    else:
        print("OCR初始化成功!")
        
        # 测试识别
        import mss
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            screenshot = sct.grab(monitor)
            image = np.array(screenshot)
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
            
            results = ocr.recognize(image)
            print(f"识别到 {len(results)} 个文字区域:")
            for r in results:
                print(f"  {r}")
