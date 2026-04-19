"""
图像识别模块
使用 OpenCV 进行模板匹配和图像处理
"""

import os
from typing import List, Tuple, Optional, Union
from dataclasses import dataclass
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:
    raise ImportError("请安装 opencv-python: pip install opencv-python")


@dataclass
class MatchResult:
    """匹配结果"""
    x: int              # 左上角X坐标
    y: int              # 左上角Y坐标
    width: int          # 宽度
    height: int         # 高度
    confidence: float   # 置信度 (0-1)
    template_name: str  # 模板名称
    
    @property
    def center(self) -> Tuple[int, int]:
        """返回中心点坐标"""
        return (self.x + self.width // 2, self.y + self.height // 2)
    
    @property
    def rect(self) -> Tuple[int, int, int, int]:
        """返回矩形 (x, y, width, height)"""
        return (self.x, self.y, self.width, self.height)
    
    def __str__(self):
        return f"{self.template_name} at ({self.x}, {self.y}) conf={self.confidence:.2f}"


@dataclass
class ROI:
    """感兴趣区域 (Region of Interest)"""
    x: int
    y: int
    width: int
    height: int
    
    def crop(self, image: np.ndarray) -> np.ndarray:
        """从图像中裁剪ROI区域"""
        return image[self.y:self.y+self.height, self.x:self.x+self.width]
    
    def offset_result(self, result: MatchResult) -> MatchResult:
        """将ROI内的匹配结果转换为全图坐标"""
        return MatchResult(
            x=result.x + self.x,
            y=result.y + self.y,
            width=result.width,
            height=result.height,
            confidence=result.confidence,
            template_name=result.template_name
        )


class ImageRecognition:
    """图像识别器"""
    
    # OpenCV模板匹配方法
    MATCH_METHODS = {
        'ccoeff_normed': cv2.TM_CCOEFF_NORMED,  # 推荐，归一化相关系数
        'ccorr_normed': cv2.TM_CCORR_NORMED,   # 归一化相关匹配
        'sqdiff_normed': cv2.TM_SQDIFF_NORMED, # 归一化平方差（值越小越好）
    }
    
    def __init__(self, templates_dir: str = None):
        """
        初始化图像识别器
        
        Args:
            templates_dir: 模板图像目录
        """
        self.templates_dir = templates_dir
        self.template_cache: dict = {}  # 模板缓存
        self.template_mask_cache: dict = {}  # 模板掩码缓存
        self.default_threshold = 0.8
        self.default_method = 'ccoeff_normed'
        self.default_match_mode = 'template'
        self.use_grayscale = True  # 使用灰度图加速匹配
        self.validate_color_consistency = False  # 可选：在灰度匹配后再校验颜色一致性
        self.color_compare_max_side = 64
        self.min_template_colorfulness_for_validation = 0.08
        self.min_color_consistency = 0.55
        self.min_template_saturation_for_validation = 0.18
        self.max_low_saturation_target_ratio = 0.35
        self.max_low_colorfulness_target_ratio = 0.45
        self.min_foreground_mask_ratio = 0.08
        self.max_foreground_mask_ratio = 0.82
        self._edge_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        
        # 多尺度匹配配置
        self.multiscale_enabled = True  # 默认启用多尺度匹配
        self.scale_range = (0.5, 1.5)   # 缩放范围 (最小50%, 最大150%)，避免极小尺度误匹配
        self.scale_steps = 20            # 缩放步数
        self.foreground_scale_steps = 8  # 前景优先匹配使用更少尺度，避免多匹配时耗时过高
        self.foreground_perspective_variants = (
            (0.96, 1.06),
            (1.06, 0.96),
        )
        self.nms_iou_threshold = 0.45
        self.nms_cover_threshold = 0.72
        self.nms_center_ratio_threshold = 0.28
        self.nms_min_area_ratio = 0.55
    
    def load_template(self, path: str, name: str = None) -> Optional[np.ndarray]:
        """
        加载模板图像
        
        Args:
            path: 图像路径
            name: 模板名称（用于缓存，默认使用文件名）
            
        Returns:
            模板图像或None
        """
        try:
            if name is None:
                name = Path(path).stem
            
            # 检查缓存
            if name in self.template_cache:
                return self.template_cache[name]
            
            # 加载图像（使用imdecode支持中文路径）
            img_array = np.fromfile(path, dtype=np.uint8)
            template = cv2.imdecode(img_array, cv2.IMREAD_UNCHANGED)
            if template is None:
                print(f"无法加载模板: {path}")
                return None
            
            # 缓存
            self.template_cache[name] = template
            return template
            
        except Exception as e:
            print(f"加载模板失败: {e}")
            return None
    
    def load_templates_from_dir(self, directory: str = None) -> int:
        """
        从目录加载所有模板
        
        Args:
            directory: 模板目录，None则使用默认目录
            
        Returns:
            加载的模板数量
        """
        dir_path = directory or self.templates_dir
        if not dir_path or not os.path.isdir(dir_path):
            return 0
        
        count = 0
        extensions = ('.png', '.jpg', '.jpeg', '.bmp')
        
        for file in os.listdir(dir_path):
            if file.lower().endswith(extensions):
                path = os.path.join(dir_path, file)
                if self.load_template(path):
                    count += 1
        
        return count

    @staticmethod
    def _ensure_bgr(image: np.ndarray) -> Optional[np.ndarray]:
        """确保图像为 BGR 三通道。"""
        if image is None:
            return None
        if len(image.shape) == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if len(image.shape) == 3:
            if image.shape[2] == 3:
                return image
            if image.shape[2] == 4:
                return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        return None

    def _resolve_match_mode(self, match_mode: Optional[str]) -> str:
        mode = self.default_match_mode if match_mode is None else match_mode
        if mode == 'feature':
            return 'foreground'
        if mode in ('template', 'foreground'):
            return mode
        return 'template'

    def _prepare_match_image(self, image: np.ndarray, match_mode: Optional[str] = None) -> Optional[np.ndarray]:
        bgr_image = self._ensure_bgr(image)
        if bgr_image is None:
            return None
        resolved_mode = self._resolve_match_mode(match_mode)
        if resolved_mode == 'feature':
            gray_image = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2GRAY)
            return self._build_gradient_feature_map(gray_image)
        if self.use_grayscale:
            return cv2.cvtColor(bgr_image, cv2.COLOR_BGR2GRAY)
        return bgr_image

    @staticmethod
    def _compute_gradient_data(gray_image: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        grad_x = cv2.Sobel(gray_image, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(gray_image, cv2.CV_32F, 0, 1, ksize=3)
        grad_mag = cv2.magnitude(grad_x, grad_y)
        return grad_x, grad_y, grad_mag

    def _build_gradient_feature_map(self, gray_image: np.ndarray) -> np.ndarray:
        _, _, grad_mag = self._compute_gradient_data(gray_image)
        scale_base = max(1.0, float(np.percentile(grad_mag, 95)))
        feature_map = np.clip((grad_mag / scale_base) * 255.0, 0.0, 255.0)
        return feature_map.astype(np.uint8)

    def _build_feature_mask(self, template: np.ndarray) -> Optional[np.ndarray]:
        template_bgr = self._ensure_bgr(template)
        if template_bgr is None:
            return None

        gray = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY)
        _, _, grad_mag = self._compute_gradient_data(gray)
        grad_threshold = max(8.0, float(np.percentile(grad_mag, 68)))
        mask = np.where(grad_mag >= grad_threshold, 255, 0).astype(np.uint8)
        mask = cv2.dilate(mask, self._edge_kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._edge_kernel, iterations=1)

        ratio = float(np.mean(mask > 0))
        if ratio < 0.04:
            mask = np.full(gray.shape, 255, dtype=np.uint8)
        return mask

    @staticmethod
    def _circular_distance(values: np.ndarray, center: float, period: float) -> np.ndarray:
        diff = np.abs(values.astype(np.float32) - np.float32(center))
        return np.minimum(diff, period - diff)

    def _build_adaptive_foreground_mask(self, template: np.ndarray) -> Optional[np.ndarray]:
        template_bgr = self._ensure_bgr(template)
        if template_bgr is None:
            return None

        height, width = template_bgr.shape[:2]
        if height < 12 or width < 12:
            return None

        border = max(1, min(6, int(round(min(height, width) * 0.12))))
        hsv = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
        border_mask = np.zeros((height, width), dtype=bool)
        border_mask[:border, :] = True
        border_mask[-border:, :] = True
        border_mask[:, :border] = True
        border_mask[:, -border:] = True

        border_pixels = hsv[border_mask]
        if border_pixels.size == 0:
            return None

        border_h = border_pixels[:, 0]
        border_s = border_pixels[:, 1]
        border_v = border_pixels[:, 2]
        center_h = float(np.median(border_h))
        center_s = float(np.median(border_s))
        center_v = float(np.median(border_v))

        border_h_diff = self._circular_distance(border_h, center_h, 180.0)
        border_s_diff = np.abs(border_s - center_s)
        border_v_diff = np.abs(border_v - center_v)
        hue_tolerance = float(np.clip(np.percentile(border_h_diff, 85) + 8.0, 8.0, 36.0))
        sat_tolerance = float(np.clip(np.percentile(border_s_diff, 85) + 18.0, 18.0, 96.0))
        val_tolerance = float(np.clip(np.percentile(border_v_diff, 85) + 18.0, 18.0, 96.0))

        full_h_diff = self._circular_distance(hsv[:, :, 0], center_h, 180.0)
        full_s_diff = np.abs(hsv[:, :, 1] - center_s)
        full_v_diff = np.abs(hsv[:, :, 2] - center_v)
        background_mask = (
            (full_h_diff <= hue_tolerance)
            & (full_s_diff <= sat_tolerance)
            & (full_v_diff <= val_tolerance)
        )

        gray = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY)
        grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        gradient_magnitude = cv2.magnitude(grad_x, grad_y)
        gradient_threshold = max(12.0, float(np.percentile(gradient_magnitude, 72)))
        edge_mask = gradient_magnitude >= gradient_threshold

        foreground_mask = np.logical_or(~background_mask, edge_mask)
        mask = (foreground_mask.astype(np.uint8) * 255)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.dilate(mask, kernel, iterations=1)

        ratio = float(np.mean(mask > 0))
        if ratio < self.min_foreground_mask_ratio or ratio > self.max_foreground_mask_ratio:
            return None
        return mask

    def _get_template_mask(self,
                           template: np.ndarray,
                           cache_key: Optional[str],
                           match_mode: Optional[str]) -> Optional[np.ndarray]:
        resolved_mode = self._resolve_match_mode(match_mode)
        if resolved_mode not in ('foreground', 'feature'):
            return None

        if cache_key and cache_key in self.template_mask_cache:
            return self.template_mask_cache[cache_key]

        mask = None
        if len(template.shape) == 3 and template.shape[2] == 4:
            alpha = template[:, :, 3]
            if np.any(alpha > 0) and np.any(alpha < 255):
                mask = np.where(alpha > 10, 255, 0).astype(np.uint8)
            elif np.any(alpha == 0):
                mask = np.where(alpha > 0, 255, 0).astype(np.uint8)

        if mask is None:
            if resolved_mode == 'feature':
                mask = self._build_adaptive_foreground_mask(template)
                if mask is None:
                    mask = self._build_feature_mask(template)
            else:
                mask = self._build_adaptive_foreground_mask(template)

        if cache_key:
            self.template_mask_cache[cache_key] = mask
        return mask

    @staticmethod
    def _resize_mask(mask: np.ndarray, width: int, height: int) -> np.ndarray:
        resized = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
        return np.where(resized > 0, 255, 0).astype(np.uint8)

    def _get_multiscale_scales(self, match_mode: Optional[str]) -> np.ndarray:
        min_scale, max_scale = self.scale_range
        steps = self.scale_steps
        if self._resolve_match_mode(match_mode) == 'foreground':
            steps = self.foreground_scale_steps
        return np.linspace(min_scale, max_scale, max(2, int(steps)))

    def _get_foreground_variant_passes(self, match_mode: Optional[str]) -> List[Tuple[Tuple[float, float], ...]]:
        if self._resolve_match_mode(match_mode) != 'foreground':
            return [((1.0, 1.0),)]
        return [
            ((1.0, 1.0),),
            tuple(self.foreground_perspective_variants),
        ]

    def _run_template_match(self,
                            search_image: np.ndarray,
                            template: np.ndarray,
                            method: str,
                            mask: Optional[np.ndarray] = None):
        effective_method = 'sqdiff_normed' if mask is not None else method
        cv_method = self.MATCH_METHODS.get(effective_method, cv2.TM_CCOEFF_NORMED)
        if mask is not None:
            result = cv2.matchTemplate(search_image, template, cv_method, mask=mask)
        else:
            result = cv2.matchTemplate(search_image, template, cv_method)
        return result, effective_method

    def _prepare_search_features(self, search_image: np.ndarray) -> Optional[dict]:
        search_bgr = self._ensure_bgr(search_image)
        if search_bgr is None:
            return None
        search_gray_u8 = cv2.cvtColor(search_bgr, cv2.COLOR_BGR2GRAY)
        search_grad_x, search_grad_y, search_grad_mag = self._compute_gradient_data(search_gray_u8)
        search_edges = cv2.dilate(cv2.Canny(search_gray_u8, 48, 128), self._edge_kernel, iterations=1) > 0
        return {
            "bgr": search_bgr,
            "gray_u8": search_gray_u8,
            "gray": search_gray_u8.astype(np.float32),
            "lab": cv2.cvtColor(search_bgr, cv2.COLOR_BGR2LAB).astype(np.float32),
            "grad_x": search_grad_x,
            "grad_y": search_grad_y,
            "grad_mag": search_grad_mag,
            "feature_map": self._build_gradient_feature_map(search_gray_u8),
            "edges": search_edges,
        }

    def _build_template_features(self,
                                 template: np.ndarray,
                                 mask: Optional[np.ndarray]) -> Optional[dict]:
        if mask is None:
            return None

        template_bgr = self._ensure_bgr(template)
        if template_bgr is None:
            return None

        if mask.shape[:2] != template_bgr.shape[:2]:
            mask = self._resize_mask(mask, template_bgr.shape[1], template_bgr.shape[0])

        valid = mask > 0
        valid_ratio = float(np.mean(valid))
        if valid_ratio < self.min_foreground_mask_ratio:
            return None

        template_gray_u8 = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY)
        template_grad_x, template_grad_y, template_grad_mag = self._compute_gradient_data(template_gray_u8)
        template_gray = template_gray_u8.astype(np.float32)
        template_values = template_gray[valid]
        if template_values.size == 0:
            return None

        template_mean = float(template_values.mean())
        template_centered = template_values - template_mean
        template_var = float(np.mean(template_centered ** 2))
        template_lab = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
        grad_threshold = max(6.0, float(np.percentile(template_grad_mag[valid], 55)))
        gradient_valid = valid & (template_grad_mag >= grad_threshold)
        if int(np.count_nonzero(gradient_valid)) < 12:
            gradient_valid = valid
        template_edges = cv2.bitwise_and(
            cv2.dilate(cv2.Canny(template_gray_u8, 48, 128), self._edge_kernel, iterations=1),
            mask,
        ) > 0

        return {
            "bgr": template_bgr,
            "gray": template_gray,
            "gray_u8": template_gray_u8,
            "lab": template_lab,
            "mask": mask,
            "valid": valid,
            "valid_ratio": valid_ratio,
            "template_values": template_values,
            "template_centered": template_centered,
            "template_var": template_var,
            "template_lab_ab": template_lab[:, :, 1:][valid],
            "grad_x": template_grad_x,
            "grad_y": template_grad_y,
            "grad_mag": template_grad_mag,
            "feature_map": self._build_gradient_feature_map(template_gray_u8),
            "gradient_valid": gradient_valid,
            "edges": template_edges,
            "edge_count": int(np.count_nonzero(template_edges)),
        }

    def _resize_template_and_mask(self,
                                  template: np.ndarray,
                                  mask: Optional[np.ndarray],
                                  width: int,
                                  height: int) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        template_bgr = self._ensure_bgr(template)
        if template_bgr is None:
            return None, None

        if template_bgr.shape[:2] == (height, width):
            resized_template = template_bgr
        else:
            interpolation = cv2.INTER_AREA if (
                template_bgr.shape[0] > height or template_bgr.shape[1] > width
            ) else cv2.INTER_LINEAR
            resized_template = cv2.resize(template_bgr, (width, height), interpolation=interpolation)

        resized_mask = None
        if mask is not None:
            if mask.shape[:2] == (height, width):
                resized_mask = mask
            else:
                resized_mask = self._resize_mask(mask, width, height)

        return resized_template, resized_mask

    def _get_match_component_scores(self,
                                    image: np.ndarray,
                                    template: np.ndarray,
                                    match: MatchResult,
                                    match_mode: str,
                                    template_mask: Optional[np.ndarray]) -> dict:
        scores = {
            "raw_confidence": None,
            "foreground_confidence": None,
            "feature_confidence": None,
            "edge_confidence": None,
        }

        if match is None or match.width <= 0 or match.height <= 0:
            return scores

        search_image = self._ensure_bgr(image)
        resized_template, resized_mask = self._resize_template_and_mask(
            template,
            template_mask,
            match.width,
            match.height,
        )
        if search_image is None or resized_template is None:
            return scores

        match_search_image = self._prepare_match_image(search_image, match_mode)
        match_template = self._prepare_match_image(resized_template, match_mode)
        if match_search_image is None or match_template is None:
            return scores

        result_map, effective_method = self._run_template_match(
            match_search_image,
            match_template,
            self.default_method,
            resized_mask,
        )
        if 0 <= match.y < result_map.shape[0] and 0 <= match.x < result_map.shape[1]:
            raw_value = float(result_map[match.y, match.x])
            scores["raw_confidence"] = 1.0 - raw_value if effective_method == 'sqdiff_normed' else raw_value

        if resized_mask is None:
            return scores

        search_features = self._prepare_search_features(search_image)
        template_features = self._build_template_features(resized_template, resized_mask)
        if search_features is None or template_features is None:
            return scores

        if match_mode == 'feature':
            scores["feature_confidence"] = self._calculate_feature_consistency_fast(
                search_features,
                template_features,
                match.x,
                match.y,
                match.width,
                match.height,
            )
        elif match_mode == 'foreground':
            scores["foreground_confidence"] = self._calculate_foreground_consistency_fast(
                search_features,
                template_features,
                match.x,
                match.y,
                match.width,
                match.height,
            )

        scores["edge_confidence"] = self._calculate_edge_consistency_fast(
            search_features,
            template_features,
            match.x,
            match.y,
            match.width,
            match.height,
        )
        return scores

    def _calculate_feature_consistency_fast(self,
                                            search_features: Optional[dict],
                                            template_features: Optional[dict],
                                            x: int,
                                            y: int,
                                            width: int,
                                            height: int) -> Optional[float]:
        if not search_features or not template_features:
            return None

        search_grad_x = search_features["grad_x"]
        search_grad_y = search_features["grad_y"]
        search_grad_mag = search_features["grad_mag"]
        search_feature_map = search_features["feature_map"]
        if x < 0 or y < 0 or x + width > search_grad_mag.shape[1] or y + height > search_grad_mag.shape[0]:
            return None

        region_grad_x = search_grad_x[y:y + height, x:x + width]
        region_grad_y = search_grad_y[y:y + height, x:x + width]
        region_grad_mag = search_grad_mag[y:y + height, x:x + width]
        region_feature_map = search_feature_map[y:y + height, x:x + width]

        gradient_valid = template_features["gradient_valid"]
        valid = template_features["valid"]
        if region_grad_mag.shape[:2] != gradient_valid.shape[:2]:
            return None

        template_grad_x = template_features["grad_x"][gradient_valid]
        template_grad_y = template_features["grad_y"][gradient_valid]
        template_grad_mag = template_features["grad_mag"][gradient_valid]
        region_grad_x_values = region_grad_x[gradient_valid]
        region_grad_y_values = region_grad_y[gradient_valid]
        region_grad_mag_values = region_grad_mag[gradient_valid]
        if template_grad_mag.size == 0 or region_grad_mag_values.size == 0:
            return None

        template_norm = np.sqrt(template_grad_x ** 2 + template_grad_y ** 2)
        region_norm = np.sqrt(region_grad_x_values ** 2 + region_grad_y_values ** 2)
        valid_orientation = (template_norm > 1e-3) & (region_norm > 1e-3)
        if np.any(valid_orientation):
            cosine = (
                template_grad_x[valid_orientation] * region_grad_x_values[valid_orientation]
                + template_grad_y[valid_orientation] * region_grad_y_values[valid_orientation]
            ) / (template_norm[valid_orientation] * region_norm[valid_orientation] + 1e-6)
            weights = np.maximum(template_norm[valid_orientation], 1.0)
            orientation_score = float(np.average(np.clip(cosine, 0.0, 1.0), weights=weights))
        else:
            orientation_score = 0.0

        magnitude_ratio = np.minimum(template_grad_mag, region_grad_mag_values) / (
            np.maximum(template_grad_mag, region_grad_mag_values) + 1e-6
        )
        magnitude_score = float(np.average(magnitude_ratio, weights=np.maximum(template_grad_mag, 1.0)))

        template_feature_values = template_features["feature_map"][valid].astype(np.float32)
        region_feature_values = region_feature_map[valid].astype(np.float32)
        if template_feature_values.size == 0 or region_feature_values.size == 0:
            return None

        feature_abs_score = 1.0 - min(
            1.0,
            float(np.mean(np.abs(template_feature_values - region_feature_values))) / 255.0,
        )

        activation_threshold = max(20.0, float(np.percentile(template_feature_values, 60)))
        template_active = template_feature_values >= activation_threshold
        region_active = region_feature_values >= activation_threshold
        union_count = int(np.count_nonzero(template_active | region_active))
        if union_count <= 0:
            feature_iou_score = 1.0
        else:
            intersection_count = int(np.count_nonzero(template_active & region_active))
            feature_iou_score = intersection_count / union_count

        feature_map_score = feature_abs_score * 0.45 + feature_iou_score * 0.55

        return float(max(0.0, min(1.0, orientation_score * 0.55 + magnitude_score * 0.20 + feature_map_score * 0.25)))

    @staticmethod
    def _combine_feature_match_confidence(raw_confidence: float,
                                          feature_confidence: Optional[float],
                                          edge_confidence: Optional[float]) -> float:
        weighted_scores = [(0.45, float(raw_confidence))]
        if feature_confidence is not None:
            weighted_scores.append((0.47, float(feature_confidence)))
        if edge_confidence is not None:
            weighted_scores.append((0.08, float(edge_confidence)))

        total_weight = sum(weight for weight, _ in weighted_scores)
        if total_weight <= 1e-6:
            return float(max(0.0, min(1.0, raw_confidence)))

        combined = sum(weight * value for weight, value in weighted_scores) / total_weight
        return float(max(0.0, min(1.0, combined)))

    def _calculate_foreground_consistency_fast(self,
                                               search_features: Optional[dict],
                                               template_features: Optional[dict],
                                               x: int,
                                               y: int,
                                               width: int,
                                               height: int) -> Optional[float]:
        if not search_features or not template_features:
            return None
        search_gray = search_features["gray"]
        search_lab = search_features["lab"]
        if x < 0 or y < 0 or x + width > search_gray.shape[1] or y + height > search_gray.shape[0]:
            return None

        region_gray = search_gray[y:y + height, x:x + width]
        region_lab = search_lab[y:y + height, x:x + width]
        valid = template_features["valid"]
        if region_gray.shape[:2] != valid.shape[:2]:
            return None

        region_values = region_gray[valid]
        if region_values.size == 0:
            return None

        template_values = template_features["template_values"]
        intensity_score = 1.0 - min(1.0, float(np.mean(np.abs(template_values - region_values))) / 255.0)

        template_centered = template_features["template_centered"]
        template_var = template_features["template_var"]
        region_centered = region_values - float(region_values.mean())
        region_var = float(np.mean(region_centered ** 2))
        denominator = float(np.sqrt(max(template_var, 1e-6) * max(region_var, 1e-6)))
        if denominator > 1e-6:
            structure_score = float(np.mean(template_centered * region_centered) / denominator)
            structure_score = max(-1.0, min(1.0, structure_score))
            structure_score = (structure_score + 1.0) / 2.0
        else:
            structure_score = intensity_score

        region_lab_ab = region_lab[:, :, 1:][valid]
        color_score = 1.0 - min(1.0, float(np.mean(np.abs(template_features["template_lab_ab"] - region_lab_ab))) / 255.0)
        return float(max(0.0, min(1.0, intensity_score * 0.30 + structure_score * 0.40 + color_score * 0.30)))

    def _calculate_edge_consistency_fast(self,
                                         search_features: Optional[dict],
                                         template_features: Optional[dict],
                                         x: int,
                                         y: int,
                                         width: int,
                                         height: int) -> Optional[float]:
        if not search_features or not template_features:
            return None
        search_edges = search_features["edges"]
        if x < 0 or y < 0 or x + width > search_edges.shape[1] or y + height > search_edges.shape[0]:
            return None

        region_edges = search_edges[y:y + height, x:x + width]
        template_edges = template_features["edges"]
        if region_edges.shape[:2] != template_edges.shape[:2]:
            return None

        region_binary = region_edges & template_features["valid"]
        region_count = int(np.count_nonzero(region_binary))
        template_count = template_features["edge_count"]
        if template_count == 0 and region_count == 0:
            return 1.0
        if template_count == 0 or region_count == 0:
            return 0.0

        intersection = int(np.count_nonzero(template_edges & region_binary))
        precision = intersection / max(1, region_count)
        recall = intersection / max(1, template_count)
        if precision + recall <= 1e-6:
            return 0.0
        return float((2.0 * precision * recall) / (precision + recall))

    @staticmethod
    def _select_top_candidate_locations(result: np.ndarray,
                                        effective_method: str,
                                        threshold: float,
                                        max_candidates: int) -> List[Tuple[int, int, float]]:
        flat = result.reshape(-1)
        total = flat.size
        if total == 0:
            return []

        max_candidates = max(1, min(int(max_candidates), total))

        if effective_method == 'sqdiff_normed':
            raw_indices = np.flatnonzero(flat <= (1.0 - float(threshold)))
            if raw_indices.size == 0:
                return []
            raw_values = flat[raw_indices]
            if raw_indices.size > max_candidates:
                selected = np.argpartition(raw_values, max_candidates - 1)[:max_candidates]
                raw_indices = raw_indices[selected]
                raw_values = raw_values[selected]
            order = np.argsort(raw_values)
            raw_indices = raw_indices[order]
            confidences = 1.0 - raw_values[order]
        else:
            raw_indices = np.flatnonzero(flat >= float(threshold))
            if raw_indices.size == 0:
                return []
            raw_values = flat[raw_indices]
            if raw_indices.size > max_candidates:
                selected = np.argpartition(-raw_values, max_candidates - 1)[:max_candidates]
                raw_indices = raw_indices[selected]
                raw_values = raw_values[selected]
            order = np.argsort(-raw_values)
            raw_indices = raw_indices[order]
            confidences = raw_values[order]

        ys, xs = np.unravel_index(raw_indices, result.shape)
        return [
            (int(y), int(x), float(confidence))
            for y, x, confidence in zip(ys.tolist(), xs.tolist(), confidences.tolist())
        ]

    def _calculate_foreground_consistency(self,
                                          search_image: np.ndarray,
                                          template: np.ndarray,
                                          mask: Optional[np.ndarray],
                                          x: int,
                                          y: int,
                                          width: int,
                                          height: int) -> Optional[float]:
        if mask is None:
            return None

        search_bgr = self._ensure_bgr(search_image)
        template_bgr = self._ensure_bgr(template)
        if search_bgr is None or template_bgr is None:
            return None
        if x < 0 or y < 0 or x + width > search_bgr.shape[1] or y + height > search_bgr.shape[0]:
            return None

        region = search_bgr[y:y + height, x:x + width]
        if region.size == 0:
            return None

        if template_bgr.shape[:2] != region.shape[:2]:
            interpolation = cv2.INTER_AREA if (
                template_bgr.shape[0] > region.shape[0] or template_bgr.shape[1] > region.shape[1]
            ) else cv2.INTER_LINEAR
            template_bgr = cv2.resize(template_bgr, (region.shape[1], region.shape[0]), interpolation=interpolation)

        if mask.shape[:2] != region.shape[:2]:
            mask = self._resize_mask(mask, region.shape[1], region.shape[0])

        valid = mask > 0
        valid_ratio = float(np.mean(valid))
        if valid_ratio < self.min_foreground_mask_ratio:
            return None

        template_gray = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        region_gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY).astype(np.float32)
        template_values = template_gray[valid]
        region_values = region_gray[valid]
        if template_values.size == 0 or region_values.size == 0:
            return None

        intensity_score = 1.0 - min(1.0, float(np.mean(np.abs(template_values - region_values))) / 255.0)

        template_centered = template_values - float(template_values.mean())
        region_centered = region_values - float(region_values.mean())
        denominator = float(np.sqrt(np.mean(template_centered ** 2) * np.mean(region_centered ** 2)))
        if denominator > 1e-6:
            structure_score = float(np.mean(template_centered * region_centered) / denominator)
            structure_score = max(-1.0, min(1.0, structure_score))
            structure_score = (structure_score + 1.0) / 2.0
        else:
            structure_score = intensity_score

        template_lab = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
        region_lab = cv2.cvtColor(region, cv2.COLOR_BGR2LAB).astype(np.float32)
        chroma_diff = np.abs(template_lab[:, :, 1:] - region_lab[:, :, 1:])
        color_score = 1.0 - min(1.0, float(np.mean(chroma_diff[valid])) / 255.0)

        return float(max(0.0, min(1.0, intensity_score * 0.30 + structure_score * 0.40 + color_score * 0.30)))

    def _calculate_edge_consistency(self,
                                    search_image: np.ndarray,
                                    template: np.ndarray,
                                    mask: Optional[np.ndarray],
                                    x: int,
                                    y: int,
                                    width: int,
                                    height: int) -> Optional[float]:
        if mask is None:
            return None

        search_bgr = self._ensure_bgr(search_image)
        template_bgr = self._ensure_bgr(template)
        if search_bgr is None or template_bgr is None:
            return None
        if x < 0 or y < 0 or x + width > search_bgr.shape[1] or y + height > search_bgr.shape[0]:
            return None

        region = search_bgr[y:y + height, x:x + width]
        if region.size == 0:
            return None

        if template_bgr.shape[:2] != region.shape[:2]:
            interpolation = cv2.INTER_AREA if (
                template_bgr.shape[0] > region.shape[0] or template_bgr.shape[1] > region.shape[1]
            ) else cv2.INTER_LINEAR
            template_bgr = cv2.resize(template_bgr, (region.shape[1], region.shape[0]), interpolation=interpolation)

        if mask.shape[:2] != region.shape[:2]:
            mask = self._resize_mask(mask, region.shape[1], region.shape[0])

        valid = (mask > 0).astype(np.uint8) * 255
        if float(np.mean(valid > 0)) < self.min_foreground_mask_ratio:
            return None

        template_gray = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY)
        region_gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        template_edges = cv2.Canny(template_gray, 48, 128)
        region_edges = cv2.Canny(region_gray, 48, 128)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        template_edges = cv2.bitwise_and(cv2.dilate(template_edges, kernel, iterations=1), valid)
        region_edges = cv2.bitwise_and(cv2.dilate(region_edges, kernel, iterations=1), valid)

        template_binary = template_edges > 0
        region_binary = region_edges > 0
        template_count = int(np.count_nonzero(template_binary))
        region_count = int(np.count_nonzero(region_binary))
        if template_count == 0 and region_count == 0:
            return 1.0
        if template_count == 0 or region_count == 0:
            return 0.0

        intersection = int(np.count_nonzero(template_binary & region_binary))
        precision = intersection / max(1, region_count)
        recall = intersection / max(1, template_count)
        if precision + recall <= 1e-6:
            return 0.0
        return float((2.0 * precision * recall) / (precision + recall))

    @staticmethod
    def _colorfulness(image: np.ndarray) -> float:
        """计算图像色彩丰富度，用于区分彩色与黑白灰图。"""
        img = image.astype(np.float32)
        b, g, r = cv2.split(img)
        rg = np.abs(r - g)
        yb = np.abs(0.5 * (r + g) - b)
        std_root = np.sqrt(np.var(rg) + np.var(yb))
        mean_root = np.sqrt(np.mean(rg) ** 2 + np.mean(yb) ** 2)
        return float((std_root + 0.3 * mean_root) / 255.0)

    def _resize_for_color_compare(self, image: np.ndarray) -> np.ndarray:
        """颜色对比前缩小图像，降低额外开销。"""
        height, width = image.shape[:2]
        max_side = max(height, width)
        if max_side <= self.color_compare_max_side:
            return image
        scale = self.color_compare_max_side / max_side
        new_width = max(1, int(round(width * scale)))
        new_height = max(1, int(round(height * scale)))
        return cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_AREA)

    def _calculate_color_consistency(self,
                                     search_image: np.ndarray,
                                     template: np.ndarray,
                                     x: int,
                                     y: int,
                                     width: int,
                                     height: int) -> Optional[float]:
        """计算模板与候选区域的颜色一致性，返回 0-1 分数。"""
        search_bgr = self._ensure_bgr(search_image)
        template_bgr = self._ensure_bgr(template)
        if search_bgr is None or template_bgr is None:
            return None

        if x < 0 or y < 0 or x + width > search_bgr.shape[1] or y + height > search_bgr.shape[0]:
            return None

        region = search_bgr[y:y + height, x:x + width]
        if region.size == 0:
            return None

        if template_bgr.shape[:2] != region.shape[:2]:
            interpolation = cv2.INTER_AREA if (
                template_bgr.shape[0] > region.shape[0] or template_bgr.shape[1] > region.shape[1]
            ) else cv2.INTER_LINEAR
            template_bgr = cv2.resize(template_bgr, (region.shape[1], region.shape[0]), interpolation=interpolation)

        template_bgr = self._resize_for_color_compare(template_bgr)
        region = self._resize_for_color_compare(region)
        if template_bgr.shape[:2] != region.shape[:2]:
            region = cv2.resize(region, (template_bgr.shape[1], template_bgr.shape[0]), interpolation=cv2.INTER_LINEAR)

        template_lab = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
        region_lab = cv2.cvtColor(region, cv2.COLOR_BGR2LAB).astype(np.float32)
        template_hsv = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
        region_hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV).astype(np.float32)

        chroma_diff = float(np.mean(np.abs(template_lab[:, :, 1:] - region_lab[:, :, 1:]))) / 255.0
        saturation_diff = float(np.mean(np.abs(template_hsv[:, :, 1] - region_hsv[:, :, 1]))) / 255.0

        template_colorfulness = self._colorfulness(template_bgr)
        region_colorfulness = self._colorfulness(region)
        colorfulness_base = max(template_colorfulness, region_colorfulness, 1e-6)
        colorfulness_diff = min(1.0, abs(template_colorfulness - region_colorfulness) / colorfulness_base)

        penalty = min(1.0, chroma_diff * 0.5 + saturation_diff * 0.25 + colorfulness_diff * 0.25)
        return float(max(0.0, 1.0 - penalty))

    def _apply_color_validation(self,
                                search_image: np.ndarray,
                                template: np.ndarray,
                                x: int,
                                y: int,
                                width: int,
                                height: int,
                                base_confidence: float,
                                threshold: float,
                                validate_color: Optional[bool]) -> Optional[float]:
        """按需执行颜色一致性校验，通过后保留原始模板匹配置信度。"""
        enabled = self.validate_color_consistency if validate_color is None else validate_color
        final_confidence = float(base_confidence)
        if not enabled:
            return final_confidence if final_confidence >= threshold else None

        template_bgr = self._ensure_bgr(template)
        if template_bgr is None:
            return final_confidence if final_confidence >= threshold else None

        template_hsv = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
        template_saturation_mean = float(template_hsv[:, :, 1].mean()) / 255.0
        template_colorfulness = self._colorfulness(template_bgr)

        if template_colorfulness < self.min_template_colorfulness_for_validation:
            return final_confidence if final_confidence >= threshold else None

        search_bgr = self._ensure_bgr(search_image)
        if search_bgr is None:
            return final_confidence if final_confidence >= threshold else None
        if x < 0 or y < 0 or x + width > search_bgr.shape[1] or y + height > search_bgr.shape[0]:
            return final_confidence if final_confidence >= threshold else None

        region = search_bgr[y:y + height, x:x + width]
        if region.size == 0:
            return final_confidence if final_confidence >= threshold else None
        if region.shape[:2] != template_bgr.shape[:2]:
            interpolation = cv2.INTER_AREA if (
                region.shape[0] > template_bgr.shape[0] or region.shape[1] > template_bgr.shape[1]
            ) else cv2.INTER_LINEAR
            region = cv2.resize(region, (template_bgr.shape[1], template_bgr.shape[0]), interpolation=interpolation)

        region_hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV).astype(np.float32)
        region_saturation_mean = float(region_hsv[:, :, 1].mean()) / 255.0
        region_colorfulness = self._colorfulness(region)

        if template_saturation_mean >= self.min_template_saturation_for_validation:
            if region_saturation_mean <= template_saturation_mean * self.max_low_saturation_target_ratio:
                return None
            if region_colorfulness <= template_colorfulness * self.max_low_colorfulness_target_ratio:
                return None

        color_confidence = self._calculate_color_consistency(search_image, template, x, y, width, height)
        if color_confidence is None:
            return final_confidence if final_confidence >= threshold else None
        if color_confidence < self.min_color_consistency:
            return None
        return final_confidence if final_confidence >= threshold else None

    def get_match_debug_info(self,
                             image: np.ndarray,
                             template: Union[np.ndarray, str],
                             match: Optional[MatchResult],
                             validate_color: Optional[bool] = None,
                             match_mode: Optional[str] = None) -> dict:
        """返回匹配结果的调试信息，包含模板分和颜色一致性分。"""
        resolved_match_mode = self._resolve_match_mode(match_mode)
        info = {
            "template_confidence": None,
            "raw_confidence": None,
            "match_mode": resolved_match_mode,
            "match_note": "",
            "foreground_confidence": None,
            "feature_confidence": None,
            "edge_confidence": None,
            "color_confidence": None,
            "color_validation_enabled": bool(
                self.validate_color_consistency if validate_color is None else validate_color
            ),
            "color_validation_applied": False,
            "color_validation_threshold": self.min_color_consistency,
            "color_note": "",
        }
        if match is None:
            return info

        info["template_confidence"] = float(match.confidence)
        template_image = template
        template_cache_key = None
        if isinstance(template, str):
            template_cache_key = template
            if template in self.template_cache:
                template_image = self.template_cache[template]
            else:
                template_image = self.load_template(template, template)
        if template_image is None:
            info["color_note"] = "模板加载失败"
            return info

        template_mask = self._get_template_mask(template_image, template_cache_key, resolved_match_mode)
        if resolved_match_mode in ('foreground', 'feature'):
            if template_mask is None:
                fallback_label = "特征优先匹配" if resolved_match_mode == 'feature' else "前景优先匹配"
                info["match_note"] = f"{fallback_label}已回退为普通模板匹配"
            else:
                ratio_text = float(np.mean(template_mask > 0))
                component_scores = self._get_match_component_scores(
                    image,
                    template_image,
                    match,
                    resolved_match_mode,
                    template_mask,
                )
                raw_confidence = component_scores.get("raw_confidence")
                if raw_confidence is not None:
                    info["raw_confidence"] = raw_confidence
                if resolved_match_mode == 'feature':
                    info["match_note"] = f"特征优先匹配，特征区域占比={ratio_text:.0%}"
                    info["feature_confidence"] = component_scores.get("feature_confidence")
                else:
                    info["match_note"] = f"前景优先匹配，前景占比={ratio_text:.0%}"
                    info["foreground_confidence"] = component_scores.get("foreground_confidence")
                info["edge_confidence"] = component_scores.get("edge_confidence")

        enabled = info["color_validation_enabled"]
        if not enabled:
            return info

        template_bgr = self._ensure_bgr(template_image)
        search_bgr = self._ensure_bgr(image)
        if template_bgr is None or search_bgr is None:
            info["color_note"] = "图像格式不支持颜色校验"
            return info

        template_hsv = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
        template_saturation_mean = float(template_hsv[:, :, 1].mean()) / 255.0
        template_colorfulness = self._colorfulness(template_bgr)
        if template_colorfulness < self.min_template_colorfulness_for_validation:
            info["color_note"] = "模板色彩较弱，跳过颜色校验"
            return info

        color_confidence = self._calculate_color_consistency(
            search_bgr,
            template_bgr,
            match.x,
            match.y,
            match.width,
            match.height,
        )
        if color_confidence is None:
            info["color_note"] = "无法计算颜色一致性"
            return info

        info["color_validation_applied"] = True
        info["color_confidence"] = float(color_confidence)

        if (
            match.x < 0 or match.y < 0 or
            match.x + match.width > search_bgr.shape[1] or
            match.y + match.height > search_bgr.shape[0]
        ):
            info["color_note"] = "匹配区域超出截图范围"
            return info

        region = search_bgr[match.y:match.y + match.height, match.x:match.x + match.width]
        if region.size == 0:
            info["color_note"] = "匹配区域为空"
            return info
        if region.shape[:2] != template_bgr.shape[:2]:
            interpolation = cv2.INTER_AREA if (
                region.shape[0] > template_bgr.shape[0] or region.shape[1] > template_bgr.shape[1]
            ) else cv2.INTER_LINEAR
            region = cv2.resize(region, (template_bgr.shape[1], template_bgr.shape[0]), interpolation=interpolation)

        region_hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV).astype(np.float32)
        region_saturation_mean = float(region_hsv[:, :, 1].mean()) / 255.0
        region_colorfulness = self._colorfulness(region)

        if template_saturation_mean >= self.min_template_saturation_for_validation:
            if region_saturation_mean <= template_saturation_mean * self.max_low_saturation_target_ratio:
                info["color_note"] = "目标区域饱和度过低"
                return info
            if region_colorfulness <= template_colorfulness * self.max_low_colorfulness_target_ratio:
                info["color_note"] = "目标区域颜色变化过弱"
                return info

        if color_confidence < self.min_color_consistency:
            info["color_note"] = "颜色一致性低于校验阈值"
            return info

        info["color_note"] = "颜色一致性校验通过"
        return info
    
    def find_template(self, 
                     image: np.ndarray, 
                     template: Union[np.ndarray, str],
                     threshold: float = None,
                     method: str = None,
                     roi: ROI = None,
                     use_multiscale: bool = None,
                     validate_color: Optional[bool] = None,
                     match_mode: Optional[str] = None) -> Optional[MatchResult]:
        """
        在图像中查找模板（单个匹配）
        
        Args:
            image: 搜索图像 (BGR或灰度)
            template: 模板图像或模板名称
            threshold: 匹配阈值 (0-1)
            method: 匹配方法
            roi: 限定搜索区域
            use_multiscale: 是否使用多尺度匹配，None则使用默认设置
            
        Returns:
            MatchResult 或 None
        """
        # 判断是否使用多尺度匹配
        if use_multiscale is None:
            use_multiscale = self.multiscale_enabled
        
        if use_multiscale:
            return self.find_template_multiscale(image, template, threshold, method, roi, validate_color, match_mode)
        
        threshold = threshold or self.default_threshold
        method = method or self.default_method
        
        # 处理模板参数
        template_name = "unknown"
        template_cache_key = None
        if isinstance(template, str):
            template_name = template
            template_cache_key = template
            if template in self.template_cache:
                template = self.template_cache[template]
            else:
                template = self.load_template(template, template)
                if template is None:
                    return None
        
        # 处理ROI
        search_image = image
        if roi:
            search_image = roi.crop(image)
        
        # 保留彩色原图用于可选的颜色一致性校验，匹配本身仍可走灰度加速
        resolved_match_mode = self._resolve_match_mode(match_mode)
        match_search_image = self._prepare_match_image(search_image, resolved_match_mode)
        match_template = self._prepare_match_image(template, resolved_match_mode)
        if match_search_image is None or match_template is None:
            return None
        template_mask = self._get_template_mask(template, template_cache_key, match_mode)
        search_features = None
        template_features = None
        if template_mask is not None:
            template_features = self._build_template_features(template, template_mask)
            if template_features is None:
                template_mask = None
            else:
                template_mask = template_features["mask"]
                search_features = self._prepare_search_features(search_image)
        
        # 检查模板大小
        if match_template.shape[0] > match_search_image.shape[0] or match_template.shape[1] > match_search_image.shape[1]:
            return None
        
        # 执行模板匹配
        result, effective_method = self._run_template_match(match_search_image, match_template, method, template_mask)
        
        # 找最佳匹配
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        
        # 根据方法选择最佳值
        if effective_method == 'sqdiff_normed':
            confidence = 1 - min_val
            location = min_loc
        else:
            confidence = max_val
            location = max_loc

        if template_features is not None:
            if resolved_match_mode == 'feature':
                feature_confidence = self._calculate_feature_consistency_fast(
                    search_features,
                    template_features,
                    location[0],
                    location[1],
                    match_template.shape[1],
                    match_template.shape[0],
                )
                edge_confidence = self._calculate_edge_consistency_fast(
                    search_features,
                    template_features,
                    location[0],
                    location[1],
                    match_template.shape[1],
                    match_template.shape[0],
                )
                confidence = self._combine_feature_match_confidence(
                    confidence,
                    feature_confidence,
                    edge_confidence,
                )
            else:
                foreground_confidence = self._calculate_foreground_consistency_fast(
                    search_features,
                    template_features,
                    location[0],
                    location[1],
                    match_template.shape[1],
                    match_template.shape[0],
                )
                edge_confidence = self._calculate_edge_consistency_fast(
                    search_features,
                    template_features,
                    location[0],
                    location[1],
                    match_template.shape[1],
                    match_template.shape[0],
                )
                if foreground_confidence is not None:
                    confidence *= foreground_confidence
                if edge_confidence is not None:
                    confidence *= max(0.35, edge_confidence)
        
        final_confidence = self._apply_color_validation(
            search_image,
            template,
            location[0],
            location[1],
            match_template.shape[1],
            match_template.shape[0],
            confidence,
            threshold,
            validate_color,
        )
        if final_confidence is None:
            return None
        
        # 创建结果
        match_result = MatchResult(
            x=location[0],
            y=location[1],
            width=match_template.shape[1],
            height=match_template.shape[0],
            confidence=final_confidence,
            template_name=template_name
        )
        
        # 如果使用了ROI，转换坐标
        if roi:
            match_result = roi.offset_result(match_result)
        
        return match_result
    
    def find_template_multiscale(self,
                                 image: np.ndarray,
                                 template: Union[np.ndarray, str],
                                 threshold: float = None,
                                 method: str = None,
                                 roi: ROI = None,
                                 validate_color: Optional[bool] = None,
                                 match_mode: Optional[str] = None) -> Optional[MatchResult]:
        """
        多尺度模板匹配 - 支持窗口缩放后的图像识别
        
        Args:
            image: 搜索图像 (BGR或灰度)
            template: 模板图像或模板名称
            threshold: 匹配阈值 (0-1)
            method: 匹配方法
            roi: 限定搜索区域
            
        Returns:
            MatchResult 或 None
        """
        threshold = threshold or self.default_threshold
        method = method or self.default_method
        
        # 处理模板参数
        template_name = "unknown"
        template_cache_key = None
        if isinstance(template, str):
            template_name = template
            template_cache_key = template
            if template in self.template_cache:
                template = self.template_cache[template]
            else:
                template = self.load_template(template, template)
                if template is None:
                    return None
        
        # 处理ROI
        search_image = image
        if roi:
            search_image = roi.crop(image)
        
        # 保留彩色图做颜色校验，匹配本身仍可走灰度图
        resolved_match_mode = self._resolve_match_mode(match_mode)
        match_search_image = self._prepare_match_image(search_image, resolved_match_mode)
        match_template = self._prepare_match_image(template, resolved_match_mode)
        if match_search_image is None or match_template is None:
            return None
        base_template_mask = self._get_template_mask(template, template_cache_key, match_mode)
        search_features = self._prepare_search_features(search_image) if base_template_mask is not None else None
        
        best_match = None
        best_confidence = 0 if method != 'sqdiff_normed' else float('inf')
        best_scale = 1.0
        
        # 生成缩放比例列表
        scales = self._get_multiscale_scales(match_mode)
        variant_passes = self._get_foreground_variant_passes(resolved_match_mode)
        
        template_h, template_w = match_template.shape[:2]
        search_h, search_w = match_search_image.shape[:2]
        
        for aspect_variants in variant_passes:
            found_in_pass = False
            for scale in scales:
                for aspect_x, aspect_y in aspect_variants:
                    # 缩放模板
                    new_w = int(template_w * scale * aspect_x)
                    new_h = int(template_h * scale * aspect_y)

                    # 跳过太小或太大的模板
                    if new_w < 10 or new_h < 10:
                        continue
                    if new_w > search_w or new_h > search_h:
                        continue

                    effective_scale = scale * max(aspect_x, aspect_y)
                    interpolation = cv2.INTER_AREA if effective_scale < 1 else cv2.INTER_LINEAR
                    resized_template = cv2.resize(match_template, (new_w, new_h), interpolation=interpolation)
                    resized_color_template = cv2.resize(template, (new_w, new_h), interpolation=interpolation)
                    resized_mask = None
                    resized_features = None
                    if base_template_mask is not None:
                        resized_mask = self._resize_mask(base_template_mask, new_w, new_h)
                        resized_features = self._build_template_features(resized_color_template, resized_mask)
                        if resized_features is None:
                            resized_mask = None
                        else:
                            resized_mask = resized_features["mask"]

                    # 执行模板匹配
                    result, effective_method = self._run_template_match(match_search_image, resized_template, method, resized_mask)
                    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

                    # 根据方法选择最佳值
                    if effective_method == 'sqdiff_normed':
                        confidence = 1 - min_val
                        location = min_loc
                        is_better = confidence > best_confidence
                    else:
                        confidence = max_val
                        location = max_loc
                        is_better = confidence > best_confidence

                    if resized_features is not None:
                        if resolved_match_mode == 'feature':
                            feature_confidence = self._calculate_feature_consistency_fast(
                                search_features,
                                resized_features,
                                location[0],
                                location[1],
                                new_w,
                                new_h,
                            )
                            edge_confidence = self._calculate_edge_consistency_fast(
                                search_features,
                                resized_features,
                                location[0],
                                location[1],
                                new_w,
                                new_h,
                            )
                            confidence = self._combine_feature_match_confidence(
                                confidence,
                                feature_confidence,
                                edge_confidence,
                            )
                        else:
                            foreground_confidence = self._calculate_foreground_consistency_fast(
                                search_features,
                                resized_features,
                                location[0],
                                location[1],
                                new_w,
                                new_h,
                            )
                            edge_confidence = self._calculate_edge_consistency_fast(
                                search_features,
                                resized_features,
                                location[0],
                                location[1],
                                new_w,
                                new_h,
                            )
                            if foreground_confidence is not None:
                                confidence *= foreground_confidence
                            if edge_confidence is not None:
                                confidence *= max(0.35, edge_confidence)
                        is_better = confidence > best_confidence

                    if is_better and confidence >= threshold:
                        final_confidence = self._apply_color_validation(
                            search_image,
                            resized_color_template,
                            location[0],
                            location[1],
                            new_w,
                            new_h,
                            confidence,
                            threshold,
                            validate_color,
                        )
                        if final_confidence is not None and final_confidence > best_confidence:
                            best_confidence = final_confidence
                            best_scale = effective_scale
                            best_match = MatchResult(
                                x=location[0],
                                y=location[1],
                                width=new_w,
                                height=new_h,
                                confidence=final_confidence,
                                template_name=template_name
                            )
                            found_in_pass = True
            if found_in_pass:
                break
        
        # 如果使用了ROI，转换坐标
        if best_match and roi:
            best_match = roi.offset_result(best_match)
        
        return best_match
    
    def find_all_templates(self,
                          image: np.ndarray,
                          template: Union[np.ndarray, str],
                          threshold: float = None,
                          method: str = None,
                          roi: ROI = None,
                          max_count: int = 100,
                          use_multiscale: bool = None,
                          validate_color: Optional[bool] = None,
                          match_mode: Optional[str] = None) -> List[MatchResult]:
        """
        在图像中查找所有匹配的模板
        
        Args:
            image: 搜索图像
            template: 模板图像或模板名称
            threshold: 匹配阈值
            method: 匹配方法
            roi: 限定搜索区域
            max_count: 最大返回数量
            use_multiscale: 是否使用多尺度匹配,None则使用默认设置
            
        Returns:
            MatchResult列表
        """
        # 判断是否使用多尺度匹配
        if use_multiscale is None:
            use_multiscale = self.multiscale_enabled
        
        if use_multiscale:
            return self.find_all_templates_multiscale(image, template, threshold, method, roi, max_count, validate_color, match_mode)
        
        threshold = threshold or self.default_threshold
        method = method or self.default_method
        
        # 处理模板参数
        template_name = "unknown"
        template_cache_key = None
        if isinstance(template, str):
            template_name = template
            template_cache_key = template
            if template in self.template_cache:
                template = self.template_cache[template]
            else:
                template = self.load_template(template, template)
                if template is None:
                    return []
        
        # 处理ROI
        search_image = image
        if roi:
            search_image = roi.crop(image)
        
        # 保留彩色图做颜色校验，匹配本身仍可走灰度图
        resolved_match_mode = self._resolve_match_mode(match_mode)
        match_search_image = self._prepare_match_image(search_image, resolved_match_mode)
        match_template = self._prepare_match_image(template, resolved_match_mode)
        if match_search_image is None or match_template is None:
            return []
        template_mask = self._get_template_mask(template, template_cache_key, match_mode)
        search_features = None
        template_features = None
        if template_mask is not None:
            template_features = self._build_template_features(template, template_mask)
            if template_features is None:
                template_mask = None
            else:
                template_mask = template_features["mask"]
                search_features = self._prepare_search_features(search_image)
        
        # 检查模板大小
        if match_template.shape[0] > match_search_image.shape[0] or match_template.shape[1] > match_search_image.shape[1]:
            return []
        
        # 执行模板匹配
        result, effective_method = self._run_template_match(match_search_image, match_template, method, template_mask)

        candidate_limit = max(200, max_count * 10)
        candidates = self._select_top_candidate_locations(result, effective_method, threshold, candidate_limit)
        
        # 转换为坐标列表
        matches = []
        h, w = match_template.shape[:2]

        for y, x, raw_confidence in candidates:
            if len(matches) >= max_count:
                break
            confidence = float(raw_confidence)
            if template_features is not None:
                if resolved_match_mode == 'feature':
                    feature_confidence = self._calculate_feature_consistency_fast(
                        search_features,
                        template_features,
                        x,
                        y,
                        w,
                        h,
                    )
                    edge_confidence = self._calculate_edge_consistency_fast(
                        search_features,
                        template_features,
                        x,
                        y,
                        w,
                        h,
                    )
                    confidence = self._combine_feature_match_confidence(
                        confidence,
                        feature_confidence,
                        edge_confidence,
                    )
                else:
                    foreground_confidence = self._calculate_foreground_consistency_fast(
                        search_features,
                        template_features,
                        x,
                        y,
                        w,
                        h,
                    )
                    edge_confidence = self._calculate_edge_consistency_fast(
                        search_features,
                        template_features,
                        x,
                        y,
                        w,
                        h,
                    )
                    if foreground_confidence is not None:
                        confidence *= foreground_confidence
                    if edge_confidence is not None:
                        confidence *= max(0.35, edge_confidence)
            final_confidence = self._apply_color_validation(
                search_image,
                template,
                x,
                y,
                w,
                h,
                confidence,
                threshold,
                validate_color,
            )
            if final_confidence is None:
                continue
            
            match_result = MatchResult(
                x=x,
                y=y,
                width=w,
                height=h,
                confidence=final_confidence,
                template_name=template_name
            )
            
            # 如果使用了ROI，转换坐标
            if roi:
                match_result = roi.offset_result(match_result)
            
            matches.append(match_result)
        
        # 非极大值抑制，去除重叠匹配
        matches = self._non_max_suppression(matches)
        
        return matches
    
    def find_all_templates_multiscale(self,
                                      image: np.ndarray,
                                      template: Union[np.ndarray, str],
                                      threshold: float = None,
                                      method: str = None,
                                      roi: ROI = None,
                                      max_count: int = 100,
                                      validate_color: Optional[bool] = None,
                                      match_mode: Optional[str] = None) -> List[MatchResult]:
        """
        多尺度模板匹配 - 查找所有匹配，支持窗口缩放后的图像识别
        
        Args:
            image: 搜索图像
            template: 模板图像或模板名称
            threshold: 匹配阈值
            method: 匹配方法
            roi: 限定搜索区域
            max_count: 最大返回数量
            
        Returns:
            MatchResult列表
        """
        threshold = threshold or self.default_threshold
        method = method or self.default_method
        
        # 处理模板参数
        template_name = "unknown"
        template_cache_key = None
        if isinstance(template, str):
            template_name = template
            template_cache_key = template
            if template in self.template_cache:
                template = self.template_cache[template]
            else:
                template = self.load_template(template, template)
                if template is None:
                    return []
        
        # 处理ROI
        search_image = image
        if roi:
            search_image = roi.crop(image)
        
        # 保留彩色图做颜色校验，匹配本身仍可走灰度图
        resolved_match_mode = self._resolve_match_mode(match_mode)
        match_search_image = self._prepare_match_image(search_image, resolved_match_mode)
        match_template = self._prepare_match_image(template, resolved_match_mode)
        if match_search_image is None or match_template is None:
            return []
        base_template_mask = self._get_template_mask(template, template_cache_key, match_mode)
        search_features = self._prepare_search_features(search_image) if base_template_mask is not None else None
        
        all_matches = []
        
        # 生成缩放比例列表
        scales = self._get_multiscale_scales(match_mode)
        variant_passes = self._get_foreground_variant_passes(resolved_match_mode)
        
        template_h, template_w = match_template.shape[:2]
        search_h, search_w = match_search_image.shape[:2]
        
        for aspect_variants in variant_passes:
            initial_match_count = len(all_matches)
            for scale in scales:
                if len(all_matches) >= max_count * 3:
                    break
                for aspect_x, aspect_y in aspect_variants:
                    if len(all_matches) >= max_count * 3:
                        break

                    # 缩放模板
                    new_w = int(template_w * scale * aspect_x)
                    new_h = int(template_h * scale * aspect_y)

                    # 跳过太小或太大的模板
                    if new_w < 10 or new_h < 10:
                        continue
                    if new_w > search_w or new_h > search_h:
                        continue

                    effective_scale = scale * max(aspect_x, aspect_y)
                    interpolation = cv2.INTER_AREA if effective_scale < 1 else cv2.INTER_LINEAR
                    resized_template = cv2.resize(match_template, (new_w, new_h), interpolation=interpolation)
                    resized_color_template = cv2.resize(template, (new_w, new_h), interpolation=interpolation)
                    resized_mask = None
                    resized_features = None
                    if base_template_mask is not None:
                        resized_mask = self._resize_mask(base_template_mask, new_w, new_h)
                        resized_features = self._build_template_features(resized_color_template, resized_mask)
                        if resized_features is None:
                            resized_mask = None
                        else:
                            resized_mask = resized_features["mask"]

                    # 执行模板匹配
                    result, effective_method = self._run_template_match(match_search_image, resized_template, method, resized_mask)
                    candidate_limit = max(120, max_count * 4)
                    candidates = self._select_top_candidate_locations(result, effective_method, threshold, candidate_limit)

                    # 转换为坐标列表
                    for y, x, raw_confidence in candidates:
                        if len(all_matches) >= max_count * 3:  # 收集更多，后续过滤
                            break
                        confidence = float(raw_confidence)
                        if resized_features is not None:
                            if resolved_match_mode == 'feature':
                                feature_confidence = self._calculate_feature_consistency_fast(
                                    search_features,
                                    resized_features,
                                    x,
                                    y,
                                    new_w,
                                    new_h,
                                )
                                edge_confidence = self._calculate_edge_consistency_fast(
                                    search_features,
                                    resized_features,
                                    x,
                                    y,
                                    new_w,
                                    new_h,
                                )
                                confidence = self._combine_feature_match_confidence(
                                    confidence,
                                    feature_confidence,
                                    edge_confidence,
                                )
                            else:
                                foreground_confidence = self._calculate_foreground_consistency_fast(
                                    search_features,
                                    resized_features,
                                    x,
                                    y,
                                    new_w,
                                    new_h,
                                )
                                edge_confidence = self._calculate_edge_consistency_fast(
                                    search_features,
                                    resized_features,
                                    x,
                                    y,
                                    new_w,
                                    new_h,
                                )
                                if foreground_confidence is not None:
                                    confidence *= foreground_confidence
                                if edge_confidence is not None:
                                    confidence *= max(0.35, edge_confidence)
                        final_confidence = self._apply_color_validation(
                            search_image,
                            resized_color_template,
                            x,
                            y,
                            new_w,
                            new_h,
                            confidence,
                            threshold,
                            validate_color,
                        )
                        if final_confidence is None:
                            continue

                        match_result = MatchResult(
                            x=x,
                            y=y,
                            width=new_w,
                            height=new_h,
                            confidence=final_confidence,
                            template_name=template_name
                        )

                        # 如果使用了ROI，转换坐标
                        if roi:
                            match_result = roi.offset_result(match_result)

                        all_matches.append(match_result)
            if len(all_matches) > initial_match_count:
                break
        
        # 非极大值抑制，去除重叠匹配
        all_matches = self._non_max_suppression(all_matches)
        
        # 限制返回数量
        return all_matches[:max_count]
    
    def _non_max_suppression(self, matches: List[MatchResult], 
                            overlap_thresh: float = 0.5) -> List[MatchResult]:
        """
        非极大值抑制，去除重叠的匹配结果
        
        Args:
            matches: 匹配结果列表
            overlap_thresh: 重叠阈值
            
        Returns:
            过滤后的匹配结果
        """
        if len(matches) == 0:
            return matches
        
        # 按置信度排序
        matches = sorted(matches, key=lambda m: m.confidence, reverse=True)
        
        keep = []
        for match in matches:
            is_overlap = False
            
            for kept in keep:
                if self._should_suppress_match(match, kept, overlap_thresh):
                    is_overlap = True
                    break
            
            if not is_overlap:
                keep.append(match)
        
        return keep

    def _should_suppress_match(self,
                               match: MatchResult,
                               kept: MatchResult,
                               overlap_thresh: float) -> bool:
        iou = self._calculate_iou(match, kept)
        if iou >= min(overlap_thresh, self.nms_iou_threshold):
            return True

        overlap_on_smaller = self._calculate_overlap_on_smaller(match, kept)
        if overlap_on_smaller >= self.nms_cover_threshold:
            return True

        area1 = match.width * match.height
        area2 = kept.width * kept.height
        if area1 <= 0 or area2 <= 0:
            return False

        area_ratio = min(area1, area2) / max(area1, area2)
        if area_ratio < self.nms_min_area_ratio:
            return False

        center_dx = abs(match.center[0] - kept.center[0])
        center_dy = abs(match.center[1] - kept.center[1])
        min_width = max(1, min(match.width, kept.width))
        min_height = max(1, min(match.height, kept.height))
        return (
            center_dx <= min_width * self.nms_center_ratio_threshold
            and center_dy <= min_height * self.nms_center_ratio_threshold
        )

    def _calculate_overlap_on_smaller(self, match1: MatchResult, match2: MatchResult) -> float:
        x1 = max(match1.x, match2.x)
        y1 = max(match1.y, match2.y)
        x2 = min(match1.x + match1.width, match2.x + match2.width)
        y2 = min(match1.y + match1.height, match2.y + match2.height)

        if x2 <= x1 or y2 <= y1:
            return 0.0

        intersection = (x2 - x1) * (y2 - y1)
        smaller_area = min(match1.width * match1.height, match2.width * match2.height)
        if smaller_area <= 0:
            return 0.0
        return intersection / smaller_area
    
    def _calculate_iou(self, match1: MatchResult, match2: MatchResult) -> float:
        """计算两个矩形的IoU"""
        x1 = max(match1.x, match2.x)
        y1 = max(match1.y, match2.y)
        x2 = min(match1.x + match1.width, match2.x + match2.width)
        y2 = min(match1.y + match1.height, match2.y + match2.height)
        
        if x2 <= x1 or y2 <= y1:
            return 0.0
        
        intersection = (x2 - x1) * (y2 - y1)
        area1 = match1.width * match1.height
        area2 = match2.width * match2.height
        union = area1 + area2 - intersection
        
        return intersection / union if union > 0 else 0.0
    
    def find_color(self, 
                   image: np.ndarray, 
                   color_bgr: Tuple[int, int, int],
                   tolerance: int = 10,
                   roi: ROI = None) -> List[Tuple[int, int]]:
        """
        查找指定颜色的像素位置
        
        Args:
            image: BGR图像
            color_bgr: 目标颜色 (B, G, R)
            tolerance: 颜色容差
            roi: 限定搜索区域
            
        Returns:
            匹配像素的坐标列表 [(x, y), ...]
        """
        search_image = image
        offset_x, offset_y = 0, 0
        
        if roi:
            search_image = roi.crop(image)
            offset_x, offset_y = roi.x, roi.y
        
        # 创建颜色范围
        lower = np.array([max(0, c - tolerance) for c in color_bgr])
        upper = np.array([min(255, c + tolerance) for c in color_bgr])
        
        # 创建掩码
        mask = cv2.inRange(search_image, lower, upper)
        
        # 找到所有匹配点
        locations = cv2.findNonZero(mask)
        
        if locations is None:
            return []
        
        # 转换坐标
        points = [(int(pt[0][0]) + offset_x, int(pt[0][1]) + offset_y) 
                  for pt in locations]
        
        return points
    
    def wait_for_template(self,
                         capture_func,
                         template: Union[np.ndarray, str],
                         timeout: float = 10.0,
                         interval: float = 0.1,
                         threshold: float = None) -> Optional[MatchResult]:
        """
        等待模板出现
        
        Args:
            capture_func: 截图函数（无参数，返回图像）
            template: 模板图像或名称
            timeout: 超时时间（秒）
            interval: 检查间隔（秒）
            threshold: 匹配阈值
            
        Returns:
            MatchResult 或 None（超时）
        """
        import time
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            image = capture_func()
            if image is not None:
                result = self.find_template(image, template, threshold)
                if result:
                    return result
            
            time.sleep(interval)
        
        return None
    
    def compare_images(self, 
                      image1: np.ndarray, 
                      image2: np.ndarray) -> float:
        """
        比较两张图像的相似度
        
        Args:
            image1, image2: 要比较的图像
            
        Returns:
            相似度 (0-1)
        """
        # 确保大小相同
        if image1.shape != image2.shape:
            image2 = cv2.resize(image2, (image1.shape[1], image1.shape[0]))
        
        # 转换为灰度图
        if len(image1.shape) == 3:
            image1 = cv2.cvtColor(image1, cv2.COLOR_BGR2GRAY)
        if len(image2.shape) == 3:
            image2 = cv2.cvtColor(image2, cv2.COLOR_BGR2GRAY)
        
        # 使用结构相似度
        result = cv2.matchTemplate(image1, image2, cv2.TM_CCOEFF_NORMED)
        return float(result[0][0])
    
    def clear_cache(self):
        """清空模板缓存"""
        self.template_cache.clear()
        self.template_mask_cache.clear()


# 测试代码
if __name__ == "__main__":
    recognizer = ImageRecognition()
    
    print("图像识别模块测试")
    print(f"支持的匹配方法: {list(recognizer.MATCH_METHODS.keys())}")
    
    # 创建测试图像
    test_image = np.zeros((300, 400, 3), dtype=np.uint8)
    cv2.rectangle(test_image, (100, 100), (150, 150), (0, 255, 0), -1)
    cv2.rectangle(test_image, (200, 150), (250, 200), (0, 255, 0), -1)
    
    # 创建模板
    template = np.zeros((50, 50, 3), dtype=np.uint8)
    cv2.rectangle(template, (0, 0), (50, 50), (0, 255, 0), -1)
    
    # 测试匹配
    recognizer.template_cache['green_box'] = template
    results = recognizer.find_all_templates(test_image, 'green_box', threshold=0.8)
    
    print(f"\n找到 {len(results)} 个匹配:")
    for result in results:
        print(f"  - {result}")
