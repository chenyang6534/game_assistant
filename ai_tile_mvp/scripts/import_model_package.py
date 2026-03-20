"""导入可分发的 AI 模型包。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

AI_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = AI_ROOT.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ai_tile_mvp.model_package import import_model_package
from ai_tile_mvp.project_scaffold import DEFAULT_PROJECTS_ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导入 AI 模型包")
    parser.add_argument("--package", required=True, help="模型包 zip、.gaimodel.json、project_meta.json 或已解压目录")
    parser.add_argument("--destination-root", default=str(DEFAULT_PROJECTS_ROOT), help="导入到哪个项目根目录")
    parser.add_argument("--overwrite", action="store_true", help="同名项目存在时允许覆盖")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = import_model_package(
        args.package,
        args.destination_root,
        allow_overwrite=args.overwrite,
    )

    project_root = Path(result["project_root"])
    project_meta = result["project_meta"]
    print(f"模型包来源: {result['source_path']}")
    print(f"导入方式: {result['source_type']}")
    print(f"项目目录: {project_root}")
    print(f"项目名: {project_meta.get('project_name') or project_root.name}")
    print(f"属性任务数: {len(project_meta.get('attribute_tasks') or [])}")
    warnings = list(result.get("warnings") or [])
    if warnings:
        print("警告:")
        for item in warnings:
            print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())