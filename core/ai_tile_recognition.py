"""可选的 AI 地块识别封装。"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np


@dataclass
class AITileMatchResult:
    x: int
    y: int
    width: int
    height: int
    confidence: float
    label: str = "tile"
    model_path: str = ""
    project_name: str = ""
    level: str = ""
    level_display: str = ""
    level_confidence: Optional[float] = None
    resource_type: str = ""
    resource_type_display: str = ""
    resource_type_confidence: Optional[float] = None
    relation: str = ""
    relation_display: str = ""
    relation_confidence: Optional[float] = None

    @property
    def center(self):
        return (self.x + self.width // 2, self.y + self.height // 2)

    def to_region_dict(self) -> dict[str, object]:
        region: dict[str, object] = {
            "x": int(self.x),
            "y": int(self.y),
            "width": int(self.width),
            "height": int(self.height),
            "label": self.label or "tile",
            "model_path": self.model_path or "",
            "confidence": float(self.confidence),
        }
        if self.project_name:
            region["project_name"] = self.project_name
        for field_name in (
            "level",
            "level_display",
            "resource_type",
            "resource_type_display",
            "relation",
            "relation_display",
        ):
            value = getattr(self, field_name, "")
            if value:
                region[field_name] = value
        for field_name in (
            "level_confidence",
            "resource_type_confidence",
            "relation_confidence",
        ):
            value = getattr(self, field_name, None)
            if value is not None:
                region[field_name] = float(value)
        return region


@dataclass
class _AttributeTaskRuntime:
    task_slug: str
    display_name: str
    weights_path: Path
    class_display_map: Dict[str, str]
    model: object | None = None


@dataclass
class _AttributeBundle:
    project_name: str
    tasks: Dict[str, _AttributeTaskRuntime]


class AITileRecognition:
    """懒加载 ONNX 地块检测器，缺失依赖或模型时优雅降级。"""

    def __init__(self):
        self._detector_cache: Dict[str, object] = {}
        self._attribute_bundle_cache: Dict[str, _AttributeBundle | None] = {}
        self._cache_lock = threading.RLock()
        self._warmed_model_paths: set[str] = set()
        self._init_error: str = ""
        self._last_error: str = ""
        self._last_attribute_notice: str = ""

    @staticmethod
    def _resolve_app_dir() -> Path:
        return Path(__file__).resolve().parent.parent

    def get_default_model_path(self) -> Path:
        model_dir = self._resolve_app_dir() / "ai_tile_mvp" / "models" / "tile_detector"
        if model_dir.exists():
            candidates = sorted(
                (path for path in model_dir.glob("*.onnx") if path.is_file()),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                return candidates[0]
        return model_dir / "tile_yolov8n_640.onnx"

    @staticmethod
    def get_default_meta_path(model_path: Path) -> Path:
        return model_path.with_suffix(".json")

    def resolve_model_path(self, model_path: Optional[str]) -> Path:
        return self._resolve_model_path(model_path)

    def get_last_error(self) -> str:
        return self._last_error or self._init_error

    def get_last_attribute_notice(self) -> str:
        return self._last_attribute_notice

    def get_warmup_progress(self, model_paths: Optional[Sequence[str | Path]] = None) -> dict[str, int]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_path in model_paths or [""]:
            path_text = str(raw_path).strip() if raw_path is not None else ""
            resolved = self._resolve_model_path(path_text or None)
            cache_key = str(resolved)
            if cache_key in seen:
                continue
            seen.add(cache_key)
            normalized.append(cache_key)

        with self._cache_lock:
            warmed = sum(1 for item in normalized if item in self._warmed_model_paths)

        return {
            "requested": len(normalized),
            "warmed": warmed,
            "pending": max(0, len(normalized) - warmed),
        }

    def _import_detector_class(self):
        try:
            from ai_tile_mvp.runtime.onnx_tile_detector import OnnxTileDetector
        except Exception as exc:  # pragma: no cover - 依赖缺失时由运行日志提示
            self._init_error = f"AI 地块识别依赖不可用: {exc}"
            return None
        return OnnxTileDetector

    def _import_classifier_class(self):
        try:
            from ultralytics import YOLO
        except Exception as exc:  # pragma: no cover - 依赖缺失时由运行日志提示
            self._last_attribute_notice = f"AI 地块属性分类依赖不可用: {exc}"
            return None
        return YOLO

    def _resolve_model_path(self, model_path: Optional[str]) -> Path:
        if model_path:
            candidate = Path(model_path)
            if not candidate.is_absolute():
                candidate = self._resolve_app_dir() / candidate
            return candidate.resolve()
        return self.get_default_model_path().resolve()

    def _get_detector(self, model_path: Optional[str]):
        resolved_model = self._resolve_model_path(model_path)
        self._last_error = ""
        self._last_attribute_notice = ""
        if not resolved_model.exists():
            self._last_error = f"AI 地块模型不存在: {resolved_model}"
            return None, resolved_model

        cache_key = str(resolved_model)
        with self._cache_lock:
            if cache_key in self._detector_cache:
                return self._detector_cache[cache_key], resolved_model

            detector_class = self._import_detector_class()
            if detector_class is None:
                self._last_error = self._init_error
                return None, resolved_model

            meta_path = self.get_default_meta_path(resolved_model)
            try:
                detector = detector_class(resolved_model, meta_path=meta_path if meta_path.exists() else None)
            except Exception as exc:
                self._last_error = f"加载 AI 地块模型失败: {exc}"
                return None, resolved_model

            self._detector_cache[cache_key] = detector
            return detector, resolved_model

    @staticmethod
    def _find_project_root(resolved_model: Path) -> Optional[Path]:
        for parent in (resolved_model.parent, *resolved_model.parents):
            if (parent / "project_meta.json").exists():
                return parent
        return None

    @staticmethod
    def _find_attribute_weights(train_attr_root: Path, task_slug: str) -> Optional[Path]:
        direct = train_attr_root / f"{task_slug}_yolov8n_cls" / "weights" / "best.pt"
        if direct.exists():
            return direct

        candidates: list[Path] = []
        if train_attr_root.exists():
            for candidate in train_attr_root.rglob("best.pt"):
                run_name = candidate.parent.parent.name.lower()
                if task_slug.lower() in run_name:
                    candidates.append(candidate)

        if not candidates:
            return None
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return candidates[0]

    def _load_attribute_bundle(self, resolved_model: Path) -> _AttributeBundle | None:
        project_root = self._find_project_root(resolved_model)
        cache_key = str(project_root.resolve()) if project_root else f"missing::{resolved_model}"
        with self._cache_lock:
            if cache_key in self._attribute_bundle_cache:
                return self._attribute_bundle_cache[cache_key]

            if project_root is None:
                self._attribute_bundle_cache[cache_key] = None
                return None

            project_meta_path = project_root / "project_meta.json"
            try:
                project_meta = json.loads(project_meta_path.read_text(encoding="utf-8"))
            except Exception as exc:
                self._last_attribute_notice = f"读取项目属性配置失败: {exc}"
                self._attribute_bundle_cache[cache_key] = None
                return None

            train_attr_root = project_root / "outputs" / "train_attr"
            tasks: Dict[str, _AttributeTaskRuntime] = {}
            for task in project_meta.get("attribute_tasks") or []:
                task_slug = str(task.get("slug") or "").strip()
                if not task_slug:
                    continue

                weights_path = self._find_attribute_weights(train_attr_root, task_slug)
                if weights_path is None:
                    continue

                class_display_map = {
                    str(class_info.get("slug") or "").strip(): str(class_info.get("display_name") or "").strip()
                    for class_info in (task.get("classes") or [])
                    if str(class_info.get("slug") or "").strip()
                }
                tasks[task_slug] = _AttributeTaskRuntime(
                    task_slug=task_slug,
                    display_name=str(task.get("display_name") or task_slug),
                    weights_path=weights_path,
                    class_display_map=class_display_map,
                )

            bundle = _AttributeBundle(
                project_name=str(project_meta.get("project_name") or project_root.name),
                tasks=tasks,
            )
            self._attribute_bundle_cache[cache_key] = bundle if tasks else None
            return self._attribute_bundle_cache[cache_key]

    def _get_attribute_model(self, task_runtime: _AttributeTaskRuntime):
        with self._cache_lock:
            if task_runtime.model is not None:
                return task_runtime.model

            classifier_class = self._import_classifier_class()
            if classifier_class is None:
                return None

            try:
                task_runtime.model = classifier_class(str(task_runtime.weights_path))
            except Exception as exc:
                self._last_attribute_notice = f"加载 {task_runtime.display_name} 属性模型失败: {exc}"
                task_runtime.model = None
            return task_runtime.model

    def _warmup_single_model(self, model_path: Optional[str]) -> tuple[bool, bool, str]:
        resolved_model = self._resolve_model_path(model_path)
        cache_key = str(resolved_model)
        with self._cache_lock:
            if cache_key in self._warmed_model_paths:
                return True, False, ""

        detector, resolved_model = self._get_detector(model_path)
        if detector is None:
            return False, False, self.get_last_error()

        try:
            input_size = int(getattr(detector, "input_size", 640) or 640)
            warmup_image = np.zeros((input_size, input_size, 3), dtype=np.uint8)
            detector.predict(warmup_image, max_detections=1)
        except Exception as exc:
            return False, False, f"AI 地块检测模型预热失败: {exc}"

        bundle = self._load_attribute_bundle(resolved_model)
        if bundle is not None and bundle.tasks:
            warmup_crop = np.zeros((224, 224, 3), dtype=np.uint8)
            for task_runtime in bundle.tasks.values():
                model = self._get_attribute_model(task_runtime)
                if model is None:
                    continue
                try:
                    try:
                        model.predict(source=[warmup_crop], verbose=False, device="cpu")
                    except TypeError:
                        model.predict(source=[warmup_crop], verbose=False)
                except Exception as exc:
                    return False, False, f"AI 地块属性模型预热失败({task_runtime.display_name}): {exc}"

        with self._cache_lock:
            self._warmed_model_paths.add(cache_key)
        return True, True, ""

    def warmup_model_paths(self, model_paths: Optional[Sequence[str | Path]] = None) -> dict[str, object]:
        summary: dict[str, object] = {
            "requested": 0,
            "warmed": 0,
            "skipped": 0,
            "failed": [],
        }
        raw_targets = list(model_paths or [""])
        seen: set[str] = set()
        for raw_target in raw_targets:
            target_text = str(raw_target).strip() if raw_target is not None else ""
            resolved_model = self._resolve_model_path(target_text or None)
            cache_key = str(resolved_model)
            if cache_key in seen:
                continue
            seen.add(cache_key)
            summary["requested"] = int(summary["requested"]) + 1
            ok, warmed_now, message = self._warmup_single_model(target_text or None)
            if ok and warmed_now:
                summary["warmed"] = int(summary["warmed"]) + 1
            elif ok:
                summary["skipped"] = int(summary["skipped"]) + 1
            elif message:
                cast_failed = summary["failed"]
                if isinstance(cast_failed, list):
                    cast_failed.append(message)
        return summary

    @staticmethod
    def _crop_match_image(image: np.ndarray, match: AITileMatchResult) -> Optional[np.ndarray]:
        height, width = image.shape[:2]
        x1 = max(0, int(match.x))
        y1 = max(0, int(match.y))
        x2 = min(width, int(match.x + match.width))
        y2 = min(height, int(match.y + match.height))
        if x2 <= x1 or y2 <= y1:
            return None
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        return crop.copy()

    @staticmethod
    def _resolve_class_name(class_names: Any, class_index: int) -> str:
        if isinstance(class_names, dict):
            value = class_names.get(class_index)
            return str(value) if value is not None else str(class_index)
        if isinstance(class_names, (list, tuple)) and 0 <= class_index < len(class_names):
            return str(class_names[class_index])
        return str(class_index)

    def _predict_attribute_labels(
        self,
        task_runtime: _AttributeTaskRuntime,
        crops: Sequence[np.ndarray],
    ) -> List[Tuple[str, float]]:
        if not crops:
            return []

        model = self._get_attribute_model(task_runtime)
        if model is None:
            return [("", 0.0) for _ in crops]

        try:
            results = model.predict(source=list(crops), verbose=False, device="cpu")
        except TypeError:
            results = model.predict(source=list(crops), verbose=False)
        except Exception:
            results = []
            for crop in crops:
                try:
                    single_result = model.predict(source=crop, verbose=False, device="cpu")
                except TypeError:
                    single_result = model.predict(source=crop, verbose=False)
                results.append(single_result[0] if single_result else None)

        predictions: List[Tuple[str, float]] = []
        for index in range(len(crops)):
            result = results[index] if index < len(results) else None
            probs = getattr(result, "probs", None)
            if probs is None:
                predictions.append(("", 0.0))
                continue

            class_index = int(getattr(probs, "top1", 0) or 0)
            confidence = float(getattr(probs, "top1conf", 0.0) or 0.0)
            class_names = getattr(result, "names", None) or getattr(model, "names", None) or {}
            predictions.append((self._resolve_class_name(class_names, class_index), confidence))
        return predictions

    @staticmethod
    def _apply_attribute_prediction(
        match: AITileMatchResult,
        task_slug: str,
        predicted_slug: str,
        predicted_display: str,
        confidence: float,
    ) -> None:
        if hasattr(match, task_slug):
            setattr(match, task_slug, predicted_slug)
        display_field = f"{task_slug}_display"
        if hasattr(match, display_field):
            setattr(match, display_field, predicted_display)
        confidence_field = f"{task_slug}_confidence"
        if hasattr(match, confidence_field):
            setattr(match, confidence_field, float(confidence))

    def enrich_tiles(
        self,
        image: np.ndarray,
        matches: Sequence[AITileMatchResult],
        *,
        model_path: Optional[str] = None,
        selected_indices: Optional[Sequence[int]] = None,
        enrich_all: bool = False,
    ) -> List[AITileMatchResult]:
        if not matches:
            return list(matches)

        resolved_model = self._resolve_model_path(model_path)
        bundle = self._load_attribute_bundle(resolved_model)
        if bundle is None or not bundle.tasks:
            return list(matches)

        if enrich_all:
            target_indices = list(range(len(matches)))
        else:
            target_indices = sorted({int(index) for index in (selected_indices or []) if 0 <= int(index) < len(matches)})

        if not target_indices:
            return list(matches)

        enriched = [match for match in matches]
        crops: List[np.ndarray] = []
        crop_indices: List[int] = []
        for index in target_indices:
            crop = self._crop_match_image(image, enriched[index])
            if crop is None:
                continue
            enriched[index].project_name = bundle.project_name
            crops.append(crop)
            crop_indices.append(index)

        if not crops:
            return enriched

        for task_runtime in bundle.tasks.values():
            predictions = self._predict_attribute_labels(task_runtime, crops)
            for crop_position, (predicted_slug, confidence) in enumerate(predictions):
                if not predicted_slug:
                    continue
                result_index = crop_indices[crop_position]
                predicted_display = task_runtime.class_display_map.get(predicted_slug, predicted_slug)
                self._apply_attribute_prediction(
                    enriched[result_index],
                    task_runtime.task_slug,
                    predicted_slug,
                    predicted_display,
                    confidence,
                )

        return enriched

    def find_tiles(
        self,
        image: np.ndarray,
        *,
        model_path: Optional[str] = None,
        threshold: Optional[float] = None,
        roi=None,
        max_count: int = 100,
    ) -> List[AITileMatchResult]:
        if image is None or getattr(image, "size", 0) == 0:
            self._last_error = "当前没有可用于 AI 地块识别的图像"
            return []

        detector, resolved_model = self._get_detector(model_path)
        if detector is None:
            return []

        search_image = image
        offset_x = 0
        offset_y = 0
        if roi is not None:
            search_image = roi.crop(image)
            offset_x = int(getattr(roi, "x", 0) or 0)
            offset_y = int(getattr(roi, "y", 0) or 0)

        try:
            detections = detector.predict(
                search_image,
                conf_threshold=threshold,
                max_detections=max_count,
            )
        except Exception as exc:
            self._last_error = f"AI 地块识别推理失败: {exc}"
            return []

        results: List[AITileMatchResult] = []
        for detection in detections:
            results.append(
                AITileMatchResult(
                    x=int(detection.x) + offset_x,
                    y=int(detection.y) + offset_y,
                    width=int(detection.width),
                    height=int(detection.height),
                    confidence=float(detection.confidence),
                    label=str(getattr(detection, "label", "tile") or "tile"),
                    model_path=str(resolved_model),
                )
            )

        results.sort(key=lambda item: item.confidence, reverse=True)
        return results