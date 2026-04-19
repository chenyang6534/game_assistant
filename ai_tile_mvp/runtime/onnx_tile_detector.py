"""独立 ONNX 地块检测器。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

try:
    import onnxruntime as ort
except ImportError as exc:  # pragma: no cover - 依赖缺失时由用户安装
    raise ImportError("请安装 onnxruntime: pip install onnxruntime") from exc


@dataclass
class TileDetection:
    x: int
    y: int
    width: int
    height: int
    confidence: float
    class_id: int = 0
    label: str = "tile"

    @property
    def center(self) -> Tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    @property
    def rect(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)


class OnnxTileDetector:
    """用于离线验证的独立 ONNX 检测器。"""

    def __init__(
        self,
        model_path: str | Path,
        meta_path: str | Path | None = None,
        providers: Optional[Sequence[str]] = None,
    ):
        self.model_path = Path(model_path)
        if not self.model_path.exists():
            raise FileNotFoundError(f"模型文件不存在: {self.model_path}")

        if meta_path is None:
            candidate = self.model_path.with_suffix(".json")
            meta_path = candidate if candidate.exists() else None

        self.meta = self._load_meta(meta_path)
        self.input_size = int(self.meta.get("input_size", 640) or 640)
        self.conf_threshold = float(self.meta.get("conf_threshold", 0.35) or 0.35)
        self.iou_threshold = float(self.meta.get("iou_threshold", 0.50) or 0.50)
        self.max_detections = int(self.meta.get("max_detections", 300) or 300)
        class_names = self.meta.get("class_names", ["tile"]) or ["tile"]
        self.class_names = [str(item) for item in class_names]

        session_providers = list(providers) if providers else ["CPUExecutionProvider"]
        self.session = ort.InferenceSession(str(self.model_path), providers=session_providers)
        self.input_name = self.session.get_inputs()[0].name
        self.output_names = [item.name for item in self.session.get_outputs()]

    @staticmethod
    def _load_meta(meta_path: str | Path | None) -> dict:
        if meta_path is None:
            return {}
        path = Path(meta_path)
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as file_obj:
            return json.load(file_obj)

    @staticmethod
    def _letterbox(
        image: np.ndarray,
        target_size: int,
        color: Tuple[int, int, int] = (114, 114, 114),
    ) -> Tuple[np.ndarray, float, float, float]:
        height, width = image.shape[:2]
        scale = min(target_size / max(height, 1), target_size / max(width, 1))
        resized_width = max(1, int(round(width * scale)))
        resized_height = max(1, int(round(height * scale)))

        resized = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
        canvas = np.full((target_size, target_size, 3), color, dtype=np.uint8)

        pad_x = (target_size - resized_width) / 2.0
        pad_y = (target_size - resized_height) / 2.0
        left = int(round(pad_x - 0.1))
        top = int(round(pad_y - 0.1))

        canvas[top:top + resized_height, left:left + resized_width] = resized
        return canvas, scale, float(left), float(top)

    def _preprocess(self, image: np.ndarray) -> Tuple[np.ndarray, float, float, float]:
        padded, scale, pad_x, pad_y = self._letterbox(image, self.input_size)
        rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
        tensor = rgb.astype(np.float32) / 255.0
        tensor = np.transpose(tensor, (2, 0, 1))[np.newaxis, ...]
        return tensor, scale, pad_x, pad_y

    def predict(
        self,
        image: np.ndarray,
        conf_threshold: Optional[float] = None,
        iou_threshold: Optional[float] = None,
        max_detections: Optional[int] = None,
    ) -> List[TileDetection]:
        if image is None or getattr(image, "size", 0) == 0:
            return []

        threshold = self.conf_threshold if conf_threshold is None else float(conf_threshold)
        iou = self.iou_threshold if iou_threshold is None else float(iou_threshold)
        limit = self.max_detections if max_detections is None else int(max_detections)

        tensor, scale, pad_x, pad_y = self._preprocess(image)
        outputs = self.session.run(self.output_names, {self.input_name: tensor})
        predictions = self._standardize_predictions(outputs[0])

        if self._looks_like_nms_output(predictions):
            detections = self._decode_nms_predictions(
                predictions,
                original_width=image.shape[1],
                original_height=image.shape[0],
                conf_threshold=threshold,
                max_detections=limit,
            )
        else:
            detections = self._decode_raw_predictions(
                predictions,
                original_width=image.shape[1],
                original_height=image.shape[0],
                scale=scale,
                pad_x=pad_x,
                pad_y=pad_y,
                conf_threshold=threshold,
                iou_threshold=iou,
                max_detections=limit,
            )

        detections.sort(key=lambda item: item.confidence, reverse=True)
        return detections[:limit]

    @staticmethod
    def _standardize_predictions(output: np.ndarray) -> np.ndarray:
        predictions = np.asarray(output)
        predictions = np.squeeze(predictions)
        if predictions.ndim == 1:
            predictions = predictions[np.newaxis, :]
        if predictions.ndim != 2:
            raise ValueError(f"无法解析模型输出形状: {predictions.shape}")
        if predictions.shape[0] < predictions.shape[1] and predictions.shape[0] <= 32:
            predictions = predictions.T
        return predictions.astype(np.float32, copy=False)

    @staticmethod
    def _looks_like_nms_output(predictions: np.ndarray) -> bool:
        if predictions.ndim != 2 or predictions.shape[1] not in (6, 7):
            return False
        scores = predictions[:, 4]
        if np.any(scores < 0.0) or np.any(scores > 1.0):
            return False
        x1 = predictions[:, 0]
        y1 = predictions[:, 1]
        x2 = predictions[:, 2]
        y2 = predictions[:, 3]
        valid_ratio = np.mean((x2 >= x1) & (y2 >= y1))
        return float(valid_ratio) >= 0.9

    def _decode_nms_predictions(
        self,
        predictions: np.ndarray,
        *,
        original_width: int,
        original_height: int,
        conf_threshold: float,
        max_detections: int,
    ) -> List[TileDetection]:
        rows = predictions[predictions[:, 4] >= conf_threshold]
        detections: List[TileDetection] = []
        for row in rows[:max_detections]:
            class_id = int(round(float(row[5]))) if row.shape[0] >= 6 else 0
            x1 = int(np.clip(round(float(row[0])), 0, original_width - 1))
            y1 = int(np.clip(round(float(row[1])), 0, original_height - 1))
            x2 = int(np.clip(round(float(row[2])), x1 + 1, original_width))
            y2 = int(np.clip(round(float(row[3])), y1 + 1, original_height))
            detections.append(
                TileDetection(
                    x=x1,
                    y=y1,
                    width=max(1, x2 - x1),
                    height=max(1, y2 - y1),
                    confidence=float(row[4]),
                    class_id=class_id,
                    label=self._label_for_class(class_id),
                )
            )
        return detections

    def _decode_raw_predictions(
        self,
        predictions: np.ndarray,
        *,
        original_width: int,
        original_height: int,
        scale: float,
        pad_x: float,
        pad_y: float,
        conf_threshold: float,
        iou_threshold: float,
        max_detections: int,
    ) -> List[TileDetection]:
        if predictions.shape[1] < 5:
            return []

        boxes = predictions[:, :4]
        class_scores = predictions[:, 4:]
        if class_scores.shape[1] == 0:
            return []

        if class_scores.shape[1] == 1:
            scores = class_scores[:, 0]
            class_ids = np.zeros(scores.shape[0], dtype=np.int32)
        else:
            class_ids = np.argmax(class_scores, axis=1)
            scores = class_scores[np.arange(class_scores.shape[0]), class_ids]

        keep_mask = scores >= conf_threshold
        if not np.any(keep_mask):
            return []

        boxes = boxes[keep_mask]
        scores = scores[keep_mask]
        class_ids = class_ids[keep_mask]

        xyxy = self._xywh_to_xyxy(boxes)
        xyxy[:, [0, 2]] = (xyxy[:, [0, 2]] - pad_x) / max(scale, 1e-6)
        xyxy[:, [1, 3]] = (xyxy[:, [1, 3]] - pad_y) / max(scale, 1e-6)
        xyxy[:, 0] = np.clip(xyxy[:, 0], 0, original_width - 1)
        xyxy[:, 1] = np.clip(xyxy[:, 1], 0, original_height - 1)
        xyxy[:, 2] = np.clip(xyxy[:, 2], 0, original_width)
        xyxy[:, 3] = np.clip(xyxy[:, 3], 0, original_height)

        keep_indices = self._nms(xyxy, scores, iou_threshold=iou_threshold, max_detections=max_detections)
        detections: List[TileDetection] = []
        for index in keep_indices:
            x1, y1, x2, y2 = xyxy[index]
            x = int(round(float(x1)))
            y = int(round(float(y1)))
            width = max(1, int(round(float(x2 - x1))))
            height = max(1, int(round(float(y2 - y1))))
            class_id = int(class_ids[index])
            detections.append(
                TileDetection(
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                    confidence=float(scores[index]),
                    class_id=class_id,
                    label=self._label_for_class(class_id),
                )
            )
        return detections

    @staticmethod
    def _xywh_to_xyxy(boxes: np.ndarray) -> np.ndarray:
        converted = np.empty_like(boxes)
        converted[:, 0] = boxes[:, 0] - boxes[:, 2] / 2.0
        converted[:, 1] = boxes[:, 1] - boxes[:, 3] / 2.0
        converted[:, 2] = boxes[:, 0] + boxes[:, 2] / 2.0
        converted[:, 3] = boxes[:, 1] + boxes[:, 3] / 2.0
        return converted

    @staticmethod
    def _nms(
        boxes: np.ndarray,
        scores: np.ndarray,
        *,
        iou_threshold: float,
        max_detections: int,
    ) -> List[int]:
        if boxes.size == 0:
            return []

        order = scores.argsort()[::-1]
        keep: List[int] = []
        areas = np.maximum(0.0, boxes[:, 2] - boxes[:, 0]) * np.maximum(0.0, boxes[:, 3] - boxes[:, 1])

        while order.size > 0 and len(keep) < max_detections:
            current = int(order[0])
            keep.append(current)
            if order.size == 1:
                break

            others = order[1:]
            xx1 = np.maximum(boxes[current, 0], boxes[others, 0])
            yy1 = np.maximum(boxes[current, 1], boxes[others, 1])
            xx2 = np.minimum(boxes[current, 2], boxes[others, 2])
            yy2 = np.minimum(boxes[current, 3], boxes[others, 3])

            inter_w = np.maximum(0.0, xx2 - xx1)
            inter_h = np.maximum(0.0, yy2 - yy1)
            intersection = inter_w * inter_h
            union = areas[current] + areas[others] - intersection
            iou = np.divide(intersection, union, out=np.zeros_like(intersection), where=union > 0)
            order = others[iou < iou_threshold]

        return keep

    def _label_for_class(self, class_id: int) -> str:
        if 0 <= class_id < len(self.class_names):
            return self.class_names[class_id]
        return f"class_{class_id}"


def draw_detections(
    image: np.ndarray,
    detections: Iterable[TileDetection],
    color: Tuple[int, int, int] = (40, 200, 40),
) -> np.ndarray:
    canvas = image.copy()
    for detection in detections:
        x1 = int(detection.x)
        y1 = int(detection.y)
        x2 = int(detection.x + detection.width)
        y2 = int(detection.y + detection.height)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
        cv2.circle(canvas, detection.center, 3, (0, 0, 255), -1)
        text = f"{detection.label}:{detection.confidence:.2f}"
        text_y = max(12, y1 - 6)
        cv2.putText(canvas, text, (x1, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    return canvas


def load_image(image_path: str | Path) -> np.ndarray:
    path = Path(image_path)
    data = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法读取图片: {path}")
    return image


def save_image(image_path: str | Path, image: np.ndarray) -> None:
    path = Path(image_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower() or ".png"
    success, encoded = cv2.imencode(suffix, image)
    if not success:
        raise ValueError(f"无法编码图片: {path}")
    encoded.tofile(str(path))