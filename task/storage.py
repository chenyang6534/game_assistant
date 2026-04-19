"""
计划任务存储模块
将任务数据保存为JSON文件
"""

import os
import json
import time
from typing import List, Optional
from pathlib import Path

from task.models import PlanTask


def _is_coord_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_coord_pair(value) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and _is_coord_number(value[0])
        and _is_coord_number(value[1])
    )


def _format_coord_array_inline(items, level: int, indent: int, max_width: int) -> str:
    if not items:
        return "[]"

    child_indent = " " * ((level + 1) * indent)
    closing_indent = " " * (level * indent)
    pair_texts = [json.dumps([item[0], item[1]], ensure_ascii=False) for item in items]

    rows = []
    current_row = []
    for pair_text in pair_texts:
        trial = ", ".join(current_row + [pair_text])
        if current_row and len(child_indent) + len(trial) > max_width:
            rows.append(", ".join(current_row))
            current_row = [pair_text]
        else:
            current_row.append(pair_text)
    if current_row:
        rows.append(", ".join(current_row))

    return "[\n" + ",\n".join(f"{child_indent}{row}" for row in rows) + f"\n{closing_indent}]"


def _format_persist_json_value(value, level: int, indent: int, max_width: int, coord_array_hint: bool = False) -> str:
    if value is None or isinstance(value, (str, int, float, bool)):
        return json.dumps(value, ensure_ascii=False)

    if isinstance(value, dict):
        if not value:
            return "{}"
        child_indent = " " * ((level + 1) * indent)
        closing_indent = " " * (level * indent)
        param_type = value.get("param_type")
        lines = []
        for key, item in value.items():
            rendered = _format_persist_json_value(
                item,
                level + 1,
                indent,
                max_width,
                coord_array_hint=(key == "value" and param_type == "coord_array"),
            )
            lines.append(f"{child_indent}{json.dumps(key, ensure_ascii=False)}: {rendered}")
        return "{\n" + ",\n".join(lines) + f"\n{closing_indent}}}"

    if isinstance(value, list):
        if coord_array_hint or all(_is_coord_pair(item) for item in value):
            return _format_coord_array_inline(value, level, indent, max_width)
        if not value:
            return "[]"
        child_indent = " " * ((level + 1) * indent)
        closing_indent = " " * (level * indent)
        lines = [
            f"{child_indent}{_format_persist_json_value(item, level + 1, indent, max_width)}"
            for item in value
        ]
        return "[\n" + ",\n".join(lines) + f"\n{closing_indent}]"

    return json.dumps(value, ensure_ascii=False)


def format_persist_json(data: dict, indent: int = 2, max_width: int = 120) -> str:
    return _format_persist_json_value(data, level=0, indent=indent, max_width=max_width)


class TaskStorage:
    """计划任务存储"""

    def __init__(self, save_dir: str = None):
        """
        初始化任务存储

        Args:
            save_dir: 存储目录，默认为项目根目录下的 tasks/
        """
        if save_dir is None:
            save_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "tasks"
            )
        self.save_dir = save_dir
        os.makedirs(self.save_dir, exist_ok=True)

    def _get_filepath(self, task_id: str) -> str:
        """获取任务文件路径"""
        return os.path.join(self.save_dir, f"task_{task_id}.json")

    def _get_persist_filepath(self, task_id: str) -> str:
        """获取持久化参数文件路径"""
        return os.path.join(self.save_dir, f"persist_{task_id}.json")

    def _apply_persist(self, task: PlanTask):
        """从存档文件加载持久化参数并应用到任务"""
        persist_path = self._get_persist_filepath(task.id)
        if not os.path.exists(persist_path):
            return
        try:
            with open(persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            task.load_persist_data(data)
        except Exception:
            pass

    def _sync_persist_file(self, task: PlanTask):
        """同步任务的持久化参数文件，避免旧存档覆盖新编辑值"""
        persist_path = self._get_persist_filepath(task.id)
        persist_data = task.get_persist_data()

        if not persist_data:
            if os.path.exists(persist_path):
                try:
                    os.remove(persist_path)
                except Exception as e:
                    print(f"删除持久化参数文件失败: {e}")
            return

        try:
            with open(persist_path, "w", encoding="utf-8") as f:
                f.write(format_persist_json(persist_data, indent=2))
        except Exception as e:
            print(f"保存持久化参数失败: {e}")

    def save(self, task: PlanTask) -> bool:
        """
        保存计划任务

        Args:
            task: 计划任务对象

        Returns:
            是否保存成功
        """
        try:
            task.update_modified_time()
            filepath = self._get_filepath(task.id)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(task.to_dict(), f, ensure_ascii=False, indent=2)
            self._sync_persist_file(task)
            return True
        except Exception as e:
            print(f"保存任务失败: {e}")
            return False

    def load(self, task_id: str) -> Optional[PlanTask]:
        """
        加载计划任务

        Args:
            task_id: 任务ID

        Returns:
            计划任务对象，失败返回None
        """
        filepath = self._get_filepath(task_id)
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            task = PlanTask.from_dict(data)
            self._apply_persist(task)
            return task
        except Exception as e:
            print(f"加载任务失败: {e}")
            return None

    def delete(self, task_id: str) -> bool:
        """
        删除计划任务

        Args:
            task_id: 任务ID

        Returns:
            是否删除成功
        """
        filepath = self._get_filepath(task_id)
        persist_path = self._get_persist_filepath(task_id)
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                if os.path.exists(persist_path):
                    os.remove(persist_path)
                return True
            except Exception as e:
                print(f"删除任务失败: {e}")
                return False
        return False

    def list_tasks(self) -> List[PlanTask]:
        """
        列出所有计划任务

        Returns:
            计划任务列表
        """
        tasks = []
        if not os.path.isdir(self.save_dir):
            return tasks

        for filename in os.listdir(self.save_dir):
            if filename.startswith("task_") and filename.endswith(".json"):
                filepath = os.path.join(self.save_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    task = PlanTask.from_dict(data)
                    self._apply_persist(task)
                    tasks.append(task)
                except Exception as e:
                    print(f"加载任务文件 {filename} 失败: {e}")

        # 按修改时间降序排列
        tasks.sort(key=lambda t: t.modified_time, reverse=True)
        return tasks

    def get_task_by_name(self, name: str) -> Optional[PlanTask]:
        """
        按名称查找任务

        Args:
            name: 任务名称

        Returns:
            计划任务对象，未找到返回None
        """
        for task in self.list_tasks():
            if task.name == name:
                return task
        return None

    def export_task(self, task_id: str, filepath: str) -> bool:
        """导出任务到指定路径"""
        task = self.load(task_id)
        if task is None:
            return False
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(task.to_dict(), f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"导出任务失败: {e}")
            return False

    def import_task(self, filepath: str) -> Optional[PlanTask]:
        """从文件导入任务"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            task = PlanTask.from_dict(data)
            # 生成新ID避免冲突
            import uuid
            task.id = uuid.uuid4().hex[:8]
            self.save(task)
            return task
        except Exception as e:
            print(f"导入任务失败: {e}")
            return None
