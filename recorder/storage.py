"""
脚本存储模块
使用 JSON 格式保存和加载录制的脚本
"""

import os
import json
from typing import List, Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass, asdict
from pathlib import Path

from .listener import InputEvent, EventType


@dataclass
class ScriptMetadata:
    """脚本元数据"""
    name: str                       # 脚本名称
    description: str = ""           # 描述
    version: str = "1.0"            # 版本
    created_at: str = ""            # 创建时间
    modified_at: str = ""           # 修改时间
    duration_ms: float = 0          # 脚本时长（毫秒）
    event_count: int = 0            # 事件数量
    target_window: str = ""         # 目标窗口标题
    author: str = ""                # 作者
    tags: List[str] = None          # 标签
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.modified_at:
            self.modified_at = self.created_at


@dataclass
class Script:
    """脚本数据类"""
    metadata: ScriptMetadata
    events: List[InputEvent]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'metadata': asdict(self.metadata),
            'events': [e.to_dict() for e in self.events]
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Script':
        """从字典创建"""
        metadata = ScriptMetadata(**data['metadata'])
        events = [InputEvent.from_dict(e) for e in data['events']]
        return cls(metadata=metadata, events=events)
    
    def update_metadata(self):
        """更新元数据（事件数量、时长等）"""
        self.metadata.event_count = len(self.events)
        if self.events:
            self.metadata.duration_ms = self.events[-1].timestamp
        self.metadata.modified_at = datetime.now().isoformat()


class ScriptStorage:
    """脚本存储管理器"""
    
    SCRIPT_EXTENSION = ".json"
    
    def __init__(self, scripts_dir: str = None):
        """
        初始化脚本存储
        
        Args:
            scripts_dir: 脚本保存目录
        """
        self.scripts_dir = scripts_dir or "scripts"
        self._ensure_directory()
    
    def _ensure_directory(self):
        """确保脚本目录存在"""
        os.makedirs(self.scripts_dir, exist_ok=True)
    
    def _get_filepath(self, name: str) -> str:
        """获取脚本文件路径"""
        if not name.endswith(self.SCRIPT_EXTENSION):
            name += self.SCRIPT_EXTENSION
        return os.path.join(self.scripts_dir, name)
    
    def save(self, script: Script, filename: str = None) -> str:
        """
        保存脚本
        
        Args:
            script: 脚本对象
            filename: 文件名（不含扩展名），默认使用脚本名称
            
        Returns:
            保存的文件路径
        """
        if filename is None:
            filename = script.metadata.name
        
        # 更新元数据
        script.update_metadata()
        
        filepath = self._get_filepath(filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(script.to_dict(), f, ensure_ascii=False, indent=2)
        
        return filepath
    
    def load(self, filename: str) -> Optional[Script]:
        """
        加载脚本
        
        Args:
            filename: 文件名（不含扩展名）
            
        Returns:
            Script 对象或 None
        """
        filepath = self._get_filepath(filename)
        
        if not os.path.exists(filepath):
            print(f"脚本文件不存在: {filepath}")
            return None
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return Script.from_dict(data)
        except Exception as e:
            print(f"加载脚本失败: {e}")
            return None
    
    def delete(self, filename: str) -> bool:
        """
        删除脚本
        
        Args:
            filename: 文件名
            
        Returns:
            是否成功
        """
        filepath = self._get_filepath(filename)
        
        if not os.path.exists(filepath):
            return False
        
        try:
            os.remove(filepath)
            return True
        except Exception as e:
            print(f"删除脚本失败: {e}")
            return False
    
    def rename(self, old_name: str, new_name: str) -> bool:
        """
        重命名脚本
        
        Args:
            old_name: 原文件名
            new_name: 新文件名
            
        Returns:
            是否成功
        """
        old_path = self._get_filepath(old_name)
        new_path = self._get_filepath(new_name)
        
        if not os.path.exists(old_path):
            return False
        
        if os.path.exists(new_path):
            print(f"目标文件已存在: {new_path}")
            return False
        
        try:
            # 加载并更新名称
            script = self.load(old_name)
            if script:
                script.metadata.name = Path(new_name).stem
                self.save(script, new_name)
                os.remove(old_path)
                return True
            return False
        except Exception as e:
            print(f"重命名失败: {e}")
            return False
    
    def list_scripts(self) -> List[ScriptMetadata]:
        """
        列出所有脚本
        
        Returns:
            脚本元数据列表
        """
        scripts = []
        
        if not os.path.exists(self.scripts_dir):
            return scripts
        
        for filename in os.listdir(self.scripts_dir):
            if filename.endswith(self.SCRIPT_EXTENSION):
                script = self.load(filename[:-len(self.SCRIPT_EXTENSION)])
                if script:
                    scripts.append(script.metadata)
        
        return scripts
    
    def get_script_info(self, filename: str) -> Optional[ScriptMetadata]:
        """
        获取脚本信息（不加载事件）
        
        Args:
            filename: 文件名
            
        Returns:
            ScriptMetadata 或 None
        """
        filepath = self._get_filepath(filename)
        
        if not os.path.exists(filepath):
            return None
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return ScriptMetadata(**data['metadata'])
        except Exception:
            return None
    
    def export_script(self, filename: str, export_path: str) -> bool:
        """
        导出脚本到指定路径
        
        Args:
            filename: 脚本文件名
            export_path: 导出路径
            
        Returns:
            是否成功
        """
        script = self.load(filename)
        if not script:
            return False
        
        try:
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(script.to_dict(), f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"导出失败: {e}")
            return False
    
    def import_script(self, import_path: str, new_name: str = None) -> Optional[str]:
        """
        从指定路径导入脚本
        
        Args:
            import_path: 导入文件路径
            new_name: 新的脚本名称（可选）
            
        Returns:
            保存的文件路径或 None
        """
        try:
            with open(import_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            script = Script.from_dict(data)
            
            if new_name:
                script.metadata.name = new_name
            
            return self.save(script, new_name or script.metadata.name)
        except Exception as e:
            print(f"导入失败: {e}")
            return None


def create_script_from_events(events: List[InputEvent], 
                             name: str, 
                             description: str = "",
                             target_window: str = "") -> Script:
    """
    从事件列表创建脚本
    
    Args:
        events: 事件列表
        name: 脚本名称
        description: 描述
        target_window: 目标窗口
        
    Returns:
        Script 对象
    """
    metadata = ScriptMetadata(
        name=name,
        description=description,
        target_window=target_window,
        event_count=len(events),
        duration_ms=events[-1].timestamp if events else 0
    )
    
    return Script(metadata=metadata, events=events)


# 测试代码
if __name__ == "__main__":
    from .listener import EventType
    
    # 创建测试事件
    test_events = [
        InputEvent(EventType.MOUSE_CLICK, 0, x=100, y=100, button='left', pressed=True),
        InputEvent(EventType.MOUSE_CLICK, 100, x=100, y=100, button='left', pressed=False),
        InputEvent(EventType.KEY_PRESS, 500, key='a', key_char='a'),
        InputEvent(EventType.KEY_RELEASE, 600, key='a', key_char='a'),
    ]
    
    # 创建脚本
    script = create_script_from_events(
        test_events, 
        name="test_script",
        description="测试脚本",
        target_window="Notepad"
    )
    
    # 测试存储
    storage = ScriptStorage("test_scripts")
    
    # 保存
    path = storage.save(script)
    print(f"脚本保存到: {path}")
    
    # 列出脚本
    scripts = storage.list_scripts()
    print(f"\n现有脚本:")
    for meta in scripts:
        print(f"  - {meta.name}: {meta.event_count}个事件, {meta.duration_ms}ms")
    
    # 加载
    loaded = storage.load("test_script")
    if loaded:
        print(f"\n加载成功: {loaded.metadata.name}")
        print(f"事件数量: {len(loaded.events)}")
