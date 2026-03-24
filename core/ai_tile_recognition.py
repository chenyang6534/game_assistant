"""可选的 AI 目标识别封装。"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import tempfile
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ai_tile_mvp.project_scaffold import (
    DEFAULT_REVIEW_DISPLAY_NAME,
    DEFAULT_REVIEW_TASK_SLUG,
    DEFAULT_REVIEW_THRESHOLD,
    get_review_classifier_config,
)


LEGACY_ATTRIBUTE_DISPLAY_NAMES = {
    "level": "等级",
    "resource_type": "类型",
    "relation": "关系",
}

MODEL_PACKAGE_MANIFEST_NAME = "model_package.gaimodel.json"
MODEL_PACKAGE_CACHE_DIR_NAME = "game_assistant_ai_model_package_cache"


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
    review_label: str = ""
    review_display: str = ""
    review_confidence: Optional[float] = None
    review_passed: Optional[bool] = None
    attribute_values: Dict[str, str] = field(default_factory=dict)
    attribute_displays: Dict[str, str] = field(default_factory=dict)
    attribute_confidences: Dict[str, Optional[float]] = field(default_factory=dict)
    attribute_display_names: Dict[str, str] = field(default_factory=dict)
    attribute_order: List[str] = field(default_factory=list)

    @property
    def center(self):
        return (self.x + self.width // 2, self.y + self.height // 2)

    def set_attribute_result(
        self,
        task_slug: str,
        display_name: str,
        predicted_slug: str,
        predicted_display: str,
        confidence: Optional[float],
    ) -> None:
        task_key = str(task_slug or "").strip()
        if not task_key:
            return

        if task_key not in self.attribute_order:
            self.attribute_order.append(task_key)

        value_text = str(predicted_slug or "").strip()
        display_text = str(predicted_display or value_text).strip()
        display_name_text = str(display_name or task_key).strip() or task_key

        self.attribute_values[task_key] = value_text
        self.attribute_displays[task_key] = display_text
        self.attribute_display_names[task_key] = display_name_text
        if confidence is None:
            self.attribute_confidences.pop(task_key, None)
        else:
            self.attribute_confidences[task_key] = float(confidence)

        if task_key in LEGACY_ATTRIBUTE_DISPLAY_NAMES:
            setattr(self, task_key, value_text)
            setattr(self, f"{task_key}_display", display_text)
            setattr(self, f"{task_key}_confidence", None if confidence is None else float(confidence))

    def _iter_attribute_slugs(self) -> List[str]:
        ordered: List[str] = []
        seen: set[str] = set()

        def _append(task_slug: object) -> None:
            text = str(task_slug or "").strip()
            if not text or text in seen:
                return
            seen.add(text)
            ordered.append(text)

        for task_slug in self.attribute_order:
            _append(task_slug)
        for task_slug in self.attribute_values.keys():
            _append(task_slug)
        for task_slug in self.attribute_displays.keys():
            _append(task_slug)
        for task_slug in self.attribute_confidences.keys():
            _append(task_slug)
        for task_slug in LEGACY_ATTRIBUTE_DISPLAY_NAMES:
            if (
                getattr(self, task_slug, "")
                or getattr(self, f"{task_slug}_display", "")
                or getattr(self, f"{task_slug}_confidence", None) is not None
            ):
                _append(task_slug)
        return ordered

    def iter_attribute_results(self) -> List[dict[str, object]]:
        results: List[dict[str, object]] = []
        for task_slug in self._iter_attribute_slugs():
            value_text = str(self.attribute_values.get(task_slug, getattr(self, task_slug, "")) or "").strip()
            display_text = str(
                self.attribute_displays.get(task_slug, getattr(self, f"{task_slug}_display", "")) or value_text
            ).strip()
            display_name_text = str(
                self.attribute_display_names.get(task_slug)
                or LEGACY_ATTRIBUTE_DISPLAY_NAMES.get(task_slug)
                or task_slug
            ).strip() or task_slug
            confidence_value = self.attribute_confidences.get(
                task_slug,
                getattr(self, f"{task_slug}_confidence", None),
            )
            if not value_text and not display_text and confidence_value is None:
                continue
            results.append(
                {
                    "task_slug": task_slug,
                    "display_name": display_name_text,
                    "value": value_text,
                    "display": display_text,
                    "confidence": None if confidence_value is None else float(confidence_value),
                }
            )
        return results

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

        attribute_entries = self.iter_attribute_results()
        if attribute_entries:
            attribute_order: List[str] = []
            attribute_values: Dict[str, str] = {}
            attribute_displays: Dict[str, str] = {}
            attribute_display_names: Dict[str, str] = {}
            attribute_confidences: Dict[str, float] = {}
            attribute_results: Dict[str, dict[str, object]] = {}
            for entry in attribute_entries:
                task_slug = str(entry.get("task_slug") or "").strip()
                if not task_slug:
                    continue
                value_text = str(entry.get("value") or "").strip()
                display_text = str(entry.get("display") or value_text).strip()
                display_name_text = str(entry.get("display_name") or task_slug).strip() or task_slug
                confidence_value = entry.get("confidence")

                attribute_order.append(task_slug)
                attribute_display_names[task_slug] = display_name_text
                if value_text:
                    region[task_slug] = value_text
                    attribute_values[task_slug] = value_text
                if display_text:
                    region[f"{task_slug}_display"] = display_text
                    attribute_displays[task_slug] = display_text
                if confidence_value is not None:
                    region[f"{task_slug}_confidence"] = float(confidence_value)
                    attribute_confidences[task_slug] = float(confidence_value)

                result_entry: dict[str, object] = {
                    "display_name": display_name_text,
                    "value": value_text,
                    "display": display_text,
                }
                if confidence_value is not None:
                    result_entry["confidence"] = float(confidence_value)
                attribute_results[task_slug] = result_entry

            region["attribute_order"] = attribute_order
            region["attributes"] = attribute_values
            region["attribute_displays"] = attribute_displays
            region["attribute_display_names"] = attribute_display_names
            region["attribute_results"] = attribute_results
            if attribute_confidences:
                region["attribute_confidences"] = attribute_confidences

        for field_name in ("review_label", "review_display"):
            value = getattr(self, field_name, "")
            if value:
                region[field_name] = value
        for field_name in ("review_confidence",):
            value = getattr(self, field_name, None)
            if value is not None:
                region[field_name] = float(value)

        review_info: dict[str, object] = {}
        if self.review_label:
            review_info["label"] = self.review_label
        if self.review_display:
            review_info["display"] = self.review_display
        if self.review_confidence is not None:
            review_info["confidence"] = float(self.review_confidence)
        if self.review_passed is not None:
            region["review_passed"] = bool(self.review_passed)
            review_info["passed"] = bool(self.review_passed)
        if review_info:
            region["review"] = review_info
        return region


@dataclass
class _ClassifierTaskRuntime:
    task_slug: str
    display_name: str
    weights_path: Path
    class_display_map: Dict[str, str]
    model: object | None = None


@dataclass
class _AttributeTaskRuntime(_ClassifierTaskRuntime):
    pass


@dataclass
class _ReviewTaskRuntime(_ClassifierTaskRuntime):
    positive_classes: set[str] = field(default_factory=set)
    negative_classes: set[str] = field(default_factory=set)
    confidence_threshold: float = DEFAULT_REVIEW_THRESHOLD


@dataclass
class _AttributeBundle:
    project_name: str
    tasks: Dict[str, _AttributeTaskRuntime]
    review_task: _ReviewTaskRuntime | None = None


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

    @staticmethod
    def _get_model_package_cache_root() -> Path:
        return Path(tempfile.gettempdir()) / MODEL_PACKAGE_CACHE_DIR_NAME

    @staticmethod
    def _find_model_package_root(directory: Path) -> Path:
        direct_manifest = directory / MODEL_PACKAGE_MANIFEST_NAME
        if direct_manifest.exists() or (directory / "project_meta.json").exists():
            return directory.resolve()

        manifest_candidates = sorted(path.parent for path in directory.rglob(MODEL_PACKAGE_MANIFEST_NAME) if path.is_file())
        if len(manifest_candidates) == 1:
            return manifest_candidates[0].resolve()
        if len(manifest_candidates) > 1:
            raise ValueError(f"模型包里找到多个 {MODEL_PACKAGE_MANIFEST_NAME}，无法确定主入口")

        meta_candidates = sorted(path.parent for path in directory.rglob("project_meta.json") if path.is_file())
        if len(meta_candidates) == 1:
            return meta_candidates[0].resolve()
        if len(meta_candidates) > 1:
            raise ValueError("模型包里找到多个 project_meta.json，无法确定主入口")

        raise FileNotFoundError(f"未在 {directory} 中找到 {MODEL_PACKAGE_MANIFEST_NAME} 或 project_meta.json")

    @staticmethod
    def _resolve_model_package_manifest(candidate: Path) -> Path:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"读取模型包清单失败: {exc}") from exc

        detector_model = str(payload.get("detector_model") or "").strip()
        if not detector_model:
            raise ValueError(f"模型包清单缺少 detector_model: {candidate}")

        detector_path = Path(detector_model)
        if not detector_path.is_absolute():
            detector_path = candidate.parent / detector_path
        detector_path = detector_path.resolve()
        if not detector_path.exists():
            raise FileNotFoundError(f"模型包清单指向的检测模型不存在: {detector_path}")
        return detector_path

    @classmethod
    def _resolve_model_package_root_model(cls, package_root: Path) -> Path:
        manifest_path = package_root / MODEL_PACKAGE_MANIFEST_NAME
        if manifest_path.exists():
            return cls._resolve_model_package_manifest(manifest_path)

        detector_dir = package_root / "models" / "detector"
        search_roots = [detector_dir] if detector_dir.exists() else [package_root]
        for search_root in search_roots:
            candidates = sorted(
                (path for path in search_root.rglob("*.onnx") if path.is_file()),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                return candidates[0].resolve()

        raise FileNotFoundError(f"模型包中未找到可用的 ONNX 检测模型: {package_root}")

    @staticmethod
    def _build_model_package_cache_key(source_zip: Path) -> str:
        zip_stat = source_zip.stat()
        digest_source = f"v1|{source_zip.resolve()}|{zip_stat.st_mtime_ns}|{zip_stat.st_size}"
        digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:16]
        safe_name = re.sub(r"[^0-9A-Za-z._-]+", "_", source_zip.stem).strip("._") or "model_package"
        return f"{safe_name}_{digest}"

    @classmethod
    def _extract_model_package_zip(cls, source_zip: Path) -> Path:
        cache_root = cls._get_model_package_cache_root()
        cache_root.mkdir(parents=True, exist_ok=True)
        cache_dir = cache_root / cls._build_model_package_cache_key(source_zip)
        if cache_dir.exists():
            try:
                return cls._find_model_package_root(cache_dir)
            except Exception:
                shutil.rmtree(cache_dir, ignore_errors=True)

        temp_dir = Path(tempfile.mkdtemp(prefix="ga_model_zip_", dir=str(cache_root)))
        try:
            try:
                with zipfile.ZipFile(source_zip, "r") as archive:
                    archive.extractall(temp_dir)
            except zipfile.BadZipFile as exc:
                raise ValueError(f"不是有效的 ZIP 模型包: {source_zip}") from exc

            package_root = cls._find_model_package_root(temp_dir)
            if cache_dir.exists():
                shutil.rmtree(cache_dir, ignore_errors=True)
            shutil.copytree(package_root, cache_dir)
            return cache_dir.resolve()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _resolve_model_target(self, model_path: Optional[str]) -> tuple[Path, str]:
        if not model_path:
            return self.get_default_model_path().resolve(), ""

        candidate = Path(model_path)
        if not candidate.is_absolute():
            candidate = self._resolve_app_dir() / candidate
        candidate = candidate.resolve()

        lower_name = candidate.name.lower()
        try:
            if candidate.is_dir() and candidate.exists():
                package_root = self._find_model_package_root(candidate)
                return self._resolve_model_package_root_model(package_root), ""

            if lower_name.endswith(".zip") and candidate.exists():
                with self._cache_lock:
                    package_root = self._extract_model_package_zip(candidate)
                return self._resolve_model_package_root_model(package_root), ""

            if lower_name.endswith(".gaimodel.json") and candidate.exists():
                return self._resolve_model_package_manifest(candidate), ""

            if lower_name == "project_meta.json" and candidate.exists():
                return self._resolve_model_package_root_model(candidate.parent), ""
        except Exception as exc:
            return candidate, f"解析 AI 模型包失败: {exc}"

        return candidate, ""

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
        return self._resolve_model_target(model_path)[0]

    def get_last_error(self) -> str:
        return self._last_error or self._init_error

    def get_last_attribute_notice(self) -> str:
        return self._last_attribute_notice

    def _append_attribute_notice(self, message: str) -> None:
        text = str(message or "").strip()
        if not text:
            return
        if not self._last_attribute_notice:
            self._last_attribute_notice = text
            return
        parts = [part.strip() for part in self._last_attribute_notice.split("；") if part.strip()]
        if text in parts:
            return
        self._last_attribute_notice = f"{self._last_attribute_notice}；{text}"

    def get_warmup_progress(self, model_paths: Optional[Sequence[str | Path]] = None) -> dict[str, int]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_path in model_paths or [""]:
            path_text = str(raw_path).strip() if raw_path is not None else ""
            resolved, _ = self._resolve_model_target(path_text or None)
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
            self._init_error = f"AI 目标识别依赖不可用: {exc}"
            return None
        return OnnxTileDetector

    def _import_classifier_class(self):
        try:
            from ultralytics import YOLO
        except Exception as exc:  # pragma: no cover - 依赖缺失时由运行日志提示
            self._append_attribute_notice(f"AI 目标属性分类依赖不可用: {exc}")
            return None
        return YOLO

    @staticmethod
    def _normalize_class_token(value: object) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return ""
        return re.sub(r"\W+", "_", text, flags=re.UNICODE).strip("_")

    @classmethod
    def _normalize_class_tokens(cls, values: Sequence[object]) -> set[str]:
        normalized: set[str] = set()
        for value in values:
            token = cls._normalize_class_token(value)
            if token:
                normalized.add(token)
        return normalized

    @staticmethod
    def _resolve_optional_project_path(project_root: Path, raw_path: object) -> Path | None:
        path_text = str(raw_path or "").strip()
        if not path_text:
            return None
        candidate = Path(path_text)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        return candidate.resolve()

    def _build_review_task_runtime(
        self,
        project_root: Path,
        project_meta: dict[str, Any],
        train_attr_root: Path,
    ) -> _ReviewTaskRuntime | None:
        review_config = get_review_classifier_config(project_meta)
        if review_config is None:
            return None

        task_slug = str(review_config.get("task_slug") or DEFAULT_REVIEW_TASK_SLUG).strip()
        if not task_slug:
            return None

        weights_path = self._resolve_optional_project_path(project_root, review_config.get("weights"))
        if weights_path is not None and not weights_path.exists():
            self._append_attribute_notice(f"AI 候选框复检模型不存在: {weights_path}")
            return None
        if weights_path is None:
            weights_path = self._find_attribute_weights(train_attr_root, task_slug)
        if weights_path is None:
            return None

        raw_display_map = review_config.get("class_display_map") or {}
        class_display_map = {
            str(key).strip(): str(value).strip()
            for key, value in raw_display_map.items()
            if str(key).strip() and str(value).strip()
        } if isinstance(raw_display_map, dict) else {}

        positive_aliases = review_config.get("positive_aliases") or [review_config.get("positive_class_slug") or "positive"]
        negative_aliases = review_config.get("negative_aliases") or [review_config.get("negative_class_slug") or "negative"]
        positive_classes = self._normalize_class_tokens(positive_aliases)
        negative_classes = self._normalize_class_tokens(negative_aliases)
        if not positive_classes:
            positive_classes = self._normalize_class_tokens([review_config.get("positive_class_slug") or "positive"])

        try:
            confidence_threshold = float(review_config.get("threshold", DEFAULT_REVIEW_THRESHOLD) or DEFAULT_REVIEW_THRESHOLD)
        except (TypeError, ValueError):
            confidence_threshold = DEFAULT_REVIEW_THRESHOLD

        return _ReviewTaskRuntime(
            task_slug=task_slug,
            display_name=str(review_config.get("display_name") or DEFAULT_REVIEW_DISPLAY_NAME),
            weights_path=weights_path,
            class_display_map=class_display_map,
            positive_classes=positive_classes,
            negative_classes=negative_classes,
            confidence_threshold=max(0.0, min(1.0, confidence_threshold)),
        )

    @staticmethod
    def _iter_classifier_runtimes(bundle: _AttributeBundle) -> list[_ClassifierTaskRuntime]:
        runtimes: list[_ClassifierTaskRuntime] = list(bundle.tasks.values())
        if bundle.review_task is not None:
            runtimes.append(bundle.review_task)
        return runtimes

    def _resolve_model_path(self, model_path: Optional[str]) -> Path:
        return self._resolve_model_target(model_path)[0]

    def _get_detector(self, model_path: Optional[str]):
        resolved_model, resolve_error = self._resolve_model_target(model_path)
        self._last_error = ""
        self._last_attribute_notice = ""
        if resolve_error:
            self._last_error = resolve_error
            return None, resolved_model
        if not resolved_model.exists():
            self._last_error = f"AI 目标模型不存在: {resolved_model}"
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
                self._last_error = f"加载 AI 目标模型失败: {exc}"
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
                self._append_attribute_notice(f"读取项目属性配置失败: {exc}")
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

            review_task = self._build_review_task_runtime(project_root, project_meta, train_attr_root)

            bundle = _AttributeBundle(
                project_name=str(project_meta.get("project_name") or project_root.name),
                tasks=tasks,
                review_task=review_task,
            )
            self._attribute_bundle_cache[cache_key] = bundle if tasks or review_task is not None else None
            return self._attribute_bundle_cache[cache_key]

    def _get_attribute_model(self, task_runtime: _ClassifierTaskRuntime):
        with self._cache_lock:
            if task_runtime.model is not None:
                return task_runtime.model

            classifier_class = self._import_classifier_class()
            if classifier_class is None:
                return None

            try:
                task_runtime.model = classifier_class(str(task_runtime.weights_path))
            except Exception as exc:
                self._append_attribute_notice(f"加载 {task_runtime.display_name} 属性模型失败: {exc}")
                task_runtime.model = None
            return task_runtime.model

    def _warmup_single_model(self, model_path: Optional[str]) -> tuple[bool, bool, str]:
        resolved_model, resolve_error = self._resolve_model_target(model_path)
        if resolve_error:
            return False, False, resolve_error
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
            return False, False, f"AI 目标检测模型预热失败: {exc}"

        bundle = self._load_attribute_bundle(resolved_model)
        if bundle is not None:
            warmup_crop = np.zeros((224, 224, 3), dtype=np.uint8)
            for task_runtime in self._iter_classifier_runtimes(bundle):
                model = self._get_attribute_model(task_runtime)
                if model is None:
                    continue
                try:
                    try:
                        model.predict(source=[warmup_crop], verbose=False, device="cpu")
                    except TypeError:
                        model.predict(source=[warmup_crop], verbose=False)
                except Exception as exc:
                    return False, False, f"AI 目标属性模型预热失败({task_runtime.display_name}): {exc}"

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
            resolved_model, _ = self._resolve_model_target(target_text or None)
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
        task_runtime: _ClassifierTaskRuntime,
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

    def _apply_review_prediction(
        self,
        match: AITileMatchResult,
        task_runtime: _ReviewTaskRuntime,
        predicted_slug: str,
        confidence: float,
        review_threshold: float | None = None,
    ) -> bool:
        predicted_display = task_runtime.class_display_map.get(predicted_slug, predicted_slug)
        match.review_label = predicted_slug
        match.review_display = predicted_display
        match.review_confidence = float(confidence)

        active_threshold = task_runtime.confidence_threshold
        if review_threshold is not None:
            active_threshold = max(0.0, min(1.0, float(review_threshold)))

        normalized = self._normalize_class_token(predicted_slug)
        if normalized in task_runtime.negative_classes:
            match.review_passed = False
            return False
        if normalized in task_runtime.positive_classes:
            passed = float(confidence) >= float(active_threshold)
            match.review_passed = passed
            return passed

        match.review_passed = True
        return True

    def _filter_matches_with_review(
        self,
        image: np.ndarray,
        matches: Sequence[AITileMatchResult],
        resolved_model: Path,
        *,
        apply_review: bool = True,
        review_threshold: float | None = None,
    ) -> List[AITileMatchResult]:
        if not matches:
            return list(matches)
        if not apply_review:
            return list(matches)

        bundle = self._load_attribute_bundle(resolved_model)
        if bundle is None or bundle.review_task is None:
            return list(matches)

        review_task = bundle.review_task
        reviewed = [match for match in matches]
        crops: List[np.ndarray] = []
        crop_indices: List[int] = []
        for index, match in enumerate(reviewed):
            crop = self._crop_match_image(image, match)
            if crop is None:
                continue
            crops.append(crop)
            crop_indices.append(index)

        if not crops:
            return reviewed

        predictions = self._predict_attribute_labels(review_task, crops)
        kept_indices: set[int] = set(range(len(reviewed)))
        filtered_count = 0
        reviewed_count = 0
        for crop_position, (predicted_slug, confidence) in enumerate(predictions):
            result_index = crop_indices[crop_position]
            if not predicted_slug:
                continue
            reviewed_count += 1
            passed = self._apply_review_prediction(
                reviewed[result_index],
                review_task,
                predicted_slug,
                confidence,
                review_threshold=review_threshold,
            )
            if not passed:
                kept_indices.discard(result_index)
                filtered_count += 1

        if filtered_count > 0:
            self._append_attribute_notice(
                f"AI 候选框复检过滤 {filtered_count}/{len(reviewed)} 个候选框"
            )
        if reviewed_count == 0:
            return reviewed
        return [reviewed[index] for index in range(len(reviewed)) if index in kept_indices]

    @staticmethod
    def _apply_attribute_prediction(
        match: AITileMatchResult,
        task_runtime: _AttributeTaskRuntime,
        predicted_slug: str,
        predicted_display: str,
        confidence: float,
    ) -> None:
        match.set_attribute_result(
            task_runtime.task_slug,
            task_runtime.display_name,
            predicted_slug,
            predicted_display,
            confidence,
        )

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

        resolved_model, resolve_error = self._resolve_model_target(model_path)
        if resolve_error:
            self._append_attribute_notice(resolve_error)
            return list(matches)
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
                    task_runtime,
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
        apply_review: bool = True,
        review_threshold: float | None = None,
    ) -> List[AITileMatchResult]:
        if image is None or getattr(image, "size", 0) == 0:
            self._last_error = "当前没有可用于 AI 目标识别的图像"
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
            self._last_error = f"AI 目标识别推理失败: {exc}"
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

        results = self._filter_matches_with_review(
            image,
            results,
            resolved_model,
            apply_review=apply_review,
            review_threshold=review_threshold,
        )
        if not results and detections:
            self._last_error = "AI 候选框复检已过滤全部候选框"

        results.sort(key=lambda item: item.confidence, reverse=True)
        return results