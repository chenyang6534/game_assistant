"""
脚本列表控件
用于显示和管理录制的脚本
"""

from typing import Optional, List
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QGroupBox, QMessageBox, QInputDialog,
    QFileDialog, QMenu
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QAction

import sys
import os
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from recorder.storage import ScriptStorage, ScriptMetadata, Script


class ScriptListWidget(QWidget):
    """脚本列表控件"""
    
    # 信号
    script_selected = Signal(str)      # 脚本名称
    script_double_clicked = Signal(str)  # 双击脚本
    play_requested = Signal(str)       # 请求播放脚本
    
    def __init__(self, scripts_dir: str = None, parent=None):
        super().__init__(parent)
        
        self._storage = ScriptStorage(scripts_dir or "scripts")
        self._current_script: Optional[str] = None
        
        self._init_ui()
        self.refresh()
    
    def _init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        group = QGroupBox("脚本列表")
        group_layout = QVBoxLayout(group)
        
        # 列表
        self._list = QListWidget()
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        self._list.itemDoubleClicked.connect(self._on_double_clicked)
        group_layout.addWidget(self._list)
        
        # 信息标签
        self._info_label = QLabel("共 0 个脚本")
        group_layout.addWidget(self._info_label)
        
        # 按钮行
        btn_layout = QHBoxLayout()
        
        self._play_btn = QPushButton("播放")
        self._play_btn.clicked.connect(self._play_selected)
        self._play_btn.setEnabled(False)
        btn_layout.addWidget(self._play_btn)
        
        self._delete_btn = QPushButton("删除")
        self._delete_btn.clicked.connect(self._delete_selected)
        self._delete_btn.setEnabled(False)
        btn_layout.addWidget(self._delete_btn)
        
        self._rename_btn = QPushButton("重命名")
        self._rename_btn.clicked.connect(self._rename_selected)
        self._rename_btn.setEnabled(False)
        btn_layout.addWidget(self._rename_btn)
        
        btn_layout.addStretch()
        
        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.clicked.connect(self.refresh)
        btn_layout.addWidget(self._refresh_btn)
        
        self._import_btn = QPushButton("导入")
        self._import_btn.clicked.connect(self._import_script)
        btn_layout.addWidget(self._import_btn)
        
        self._export_btn = QPushButton("导出")
        self._export_btn.clicked.connect(self._export_selected)
        self._export_btn.setEnabled(False)
        btn_layout.addWidget(self._export_btn)
        
        group_layout.addLayout(btn_layout)
        
        layout.addWidget(group)
    
    def _show_context_menu(self, pos):
        """显示右键菜单"""
        item = self._list.itemAt(pos)
        if not item:
            return
        
        menu = QMenu(self)
        
        play_action = QAction("播放", self)
        play_action.triggered.connect(self._play_selected)
        menu.addAction(play_action)
        
        menu.addSeparator()
        
        rename_action = QAction("重命名", self)
        rename_action.triggered.connect(self._rename_selected)
        menu.addAction(rename_action)
        
        export_action = QAction("导出", self)
        export_action.triggered.connect(self._export_selected)
        menu.addAction(export_action)
        
        menu.addSeparator()
        
        delete_action = QAction("删除", self)
        delete_action.triggered.connect(self._delete_selected)
        menu.addAction(delete_action)
        
        menu.exec(self._list.mapToGlobal(pos))
    
    def _on_selection_changed(self):
        """选择变更处理"""
        items = self._list.selectedItems()
        has_selection = len(items) > 0
        
        self._play_btn.setEnabled(has_selection)
        self._delete_btn.setEnabled(has_selection)
        self._rename_btn.setEnabled(has_selection)
        self._export_btn.setEnabled(has_selection)
        
        if has_selection:
            self._current_script = items[0].data(Qt.ItemDataRole.UserRole)
            self.script_selected.emit(self._current_script)
            
            # 更新信息
            meta = self._storage.get_script_info(self._current_script)
            if meta:
                duration_sec = meta.duration_ms / 1000
                self._info_label.setText(
                    f"事件: {meta.event_count} | 时长: {duration_sec:.1f}秒 | "
                    f"创建: {meta.created_at[:10]}"
                )
        else:
            self._current_script = None
            self._update_count_label()
    
    def _on_double_clicked(self, item: QListWidgetItem):
        """双击脚本"""
        script_name = item.data(Qt.ItemDataRole.UserRole)
        self.script_double_clicked.emit(script_name)
        self.play_requested.emit(script_name)
    
    def _play_selected(self):
        """播放选中的脚本"""
        if self._current_script:
            self.play_requested.emit(self._current_script)
    
    def _delete_selected(self):
        """删除选中的脚本"""
        if not self._current_script:
            return
        
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除脚本 '{self._current_script}' 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            if self._storage.delete(self._current_script):
                self.refresh()
            else:
                QMessageBox.warning(self, "错误", "删除脚本失败")
    
    def _rename_selected(self):
        """重命名选中的脚本"""
        if not self._current_script:
            return
        
        new_name, ok = QInputDialog.getText(
            self, "重命名脚本",
            "新名称:",
            text=self._current_script
        )
        
        if ok and new_name and new_name != self._current_script:
            if self._storage.rename(self._current_script, new_name):
                self.refresh()
            else:
                QMessageBox.warning(self, "错误", "重命名失败")
    
    def _import_script(self):
        """导入脚本"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "导入脚本",
            "",
            "JSON脚本文件 (*.json);;所有文件 (*.*)"
        )
        
        if filepath:
            # 询问新名称
            default_name = os.path.splitext(os.path.basename(filepath))[0]
            new_name, ok = QInputDialog.getText(
                self, "导入脚本",
                "脚本名称:",
                text=default_name
            )
            
            if ok and new_name:
                if self._storage.import_script(filepath, new_name):
                    self.refresh()
                    QMessageBox.information(self, "成功", "脚本导入成功")
                else:
                    QMessageBox.warning(self, "错误", "导入脚本失败")
    
    def _export_selected(self):
        """导出选中的脚本"""
        if not self._current_script:
            return
        
        filepath, _ = QFileDialog.getSaveFileName(
            self, "导出脚本",
            f"{self._current_script}.json",
            "JSON脚本文件 (*.json);;所有文件 (*.*)"
        )
        
        if filepath:
            if self._storage.export_script(self._current_script, filepath):
                QMessageBox.information(self, "成功", "脚本导出成功")
            else:
                QMessageBox.warning(self, "错误", "导出脚本失败")
    
    def _update_count_label(self):
        """更新脚本数量标签"""
        count = self._list.count()
        self._info_label.setText(f"共 {count} 个脚本")
    
    def refresh(self):
        """刷新脚本列表"""
        self._list.clear()
        
        scripts = self._storage.list_scripts()
        
        for meta in scripts:
            item = QListWidgetItem(meta.name)
            item.setData(Qt.ItemDataRole.UserRole, meta.name)
            
            # 添加工具提示
            duration_sec = meta.duration_ms / 1000
            tooltip = (
                f"名称: {meta.name}\n"
                f"描述: {meta.description or '无'}\n"
                f"事件数: {meta.event_count}\n"
                f"时长: {duration_sec:.1f}秒\n"
                f"创建时间: {meta.created_at}"
            )
            item.setToolTip(tooltip)
            
            self._list.addItem(item)
        
        self._update_count_label()
    
    def get_selected_script(self) -> Optional[str]:
        """获取选中的脚本名称"""
        return self._current_script
    
    def load_script(self, name: str) -> Optional[Script]:
        """加载脚本"""
        return self._storage.load(name)
    
    def save_script(self, script: Script) -> bool:
        """保存脚本"""
        try:
            self._storage.save(script)
            self.refresh()
            return True
        except Exception:
            return False
