"""AI 模型包导入导出辅助。"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from ai_tile_mvp.project_scaffold import load_project_meta, slugify_identifier, validate_project_name


PACKAGE_MANIFEST_NAME = "model_package.gaimodel.json"
PACKAGE_README_NAME = "README.txt"


def _find_package_root(directory: Path) -> Path:
    direct_manifest = directory / PACKAGE_MANIFEST_NAME
    if direct_manifest.exists():
        return directory.resolve()

    direct_meta = directory / "project_meta.json"
    if direct_meta.exists():
        return directory.resolve()

    manifest_candidates = sorted(path.parent for path in directory.rglob(PACKAGE_MANIFEST_NAME) if path.is_file())
    if len(manifest_candidates) == 1:
        return manifest_candidates[0].resolve()
    if len(manifest_candidates) > 1:
        raise ValueError(f"压缩包里找到多个 {PACKAGE_MANIFEST_NAME}，无法确定要导入哪一个")

    meta_candidates = sorted(path.parent for path in directory.rglob("project_meta.json") if path.is_file())
    if len(meta_candidates) == 1:
        return meta_candidates[0].resolve()
    if len(meta_candidates) > 1:
        raise ValueError("压缩包里找到多个 project_meta.json，无法确定要导入哪一个")

    raise FileNotFoundError(f"未在 {directory} 中找到 {PACKAGE_MANIFEST_NAME} 或 project_meta.json")


def _resolve_source_package_root(source_path: Path) -> tuple[Path, tempfile.TemporaryDirectory[str] | None, str]:
    lower_name = source_path.name.lower()
    if source_path.is_dir():
        return _find_package_root(source_path), None, "directory"

    if lower_name.endswith(".gaimodel.json") or lower_name == "project_meta.json":
        return source_path.parent.resolve(), None, "manifest"

    if source_path.suffix.lower() == ".zip":
        temp_dir = tempfile.TemporaryDirectory(prefix="ga_model_pkg_")
        temp_root = Path(temp_dir.name)
        with zipfile.ZipFile(source_path, "r") as archive:
            archive.extractall(temp_root)
        return _find_package_root(temp_root), temp_dir, "zip"

    raise ValueError("只支持导入 .zip、.gaimodel.json、project_meta.json 或已解压目录")


def _suggest_target_dir_name(project_meta: dict[str, Any], fallback_name: str) -> str:
    project_slug = str(project_meta.get("project_slug") or "").strip()
    if project_slug:
        return project_slug

    project_name = str(project_meta.get("project_name") or "").strip()
    if project_name:
        try:
            return validate_project_name(project_name)
        except Exception:
            slug = slugify_identifier(project_name, "imported_project")
            if slug:
                return slug

    return fallback_name


def _resolve_import_target(base_dir: Path, preferred_name: str, allow_overwrite: bool) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    preferred = base_dir / preferred_name
    if allow_overwrite or not preferred.exists():
        return preferred

    imported_name = f"{preferred_name}_imported"
    candidate = base_dir / imported_name
    if not candidate.exists():
        return candidate

    counter = 2
    while True:
        candidate = base_dir / f"{imported_name}_{counter}"
        if not candidate.exists():
            return candidate
        counter += 1


def import_model_package(
    package_source: Path | str,
    destination_root: Path | str,
    *,
    allow_overwrite: bool = False,
) -> dict[str, Any]:
    source_path = Path(package_source).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"模型包不存在: {source_path}")

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        package_root, temp_dir, source_type = _resolve_source_package_root(source_path)
        project_meta_path = package_root / "project_meta.json"
        if not project_meta_path.exists():
            raise FileNotFoundError(f"模型包里缺少 project_meta.json: {package_root}")

        project_meta = load_project_meta(project_meta_path)
        destination_base = Path(destination_root).resolve()
        target_name = _suggest_target_dir_name(project_meta, package_root.name or "imported_project")
        project_root = _resolve_import_target(destination_base, target_name, allow_overwrite)

        if project_root.exists():
            if not allow_overwrite:
                raise FileExistsError(f"目标项目目录已存在: {project_root}")
            if project_root.is_dir():
                shutil.rmtree(project_root)
            else:
                project_root.unlink()

        shutil.copytree(package_root, project_root)

        warnings: list[str] = []
        manifest_path = project_root / PACKAGE_MANIFEST_NAME
        if not manifest_path.exists():
            warnings.append(f"导入源中未找到 {PACKAGE_MANIFEST_NAME}，已按 project_meta.json 目录导入")

        return {
            "project_root": project_root,
            "project_config_path": project_root / "project_meta.json",
            "project_meta": project_meta,
            "source_path": source_path,
            "source_type": source_type,
            "package_root": package_root,
            "warnings": warnings,
        }
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()