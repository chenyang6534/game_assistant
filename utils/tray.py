"""
系统托盘模块
使用 PySide6 的 QSystemTrayIcon 实现系统托盘功能
"""

from typing import Optional, Callable, List, Tuple
from dataclasses import dataclass
import os

try:
    from PySide6.QtWidgets import (
        QApplication, QSystemTrayIcon, QMenu, QWidget
    )
    from PySide6.QtGui import QIcon, QAction, QPixmap, QImage
    from PySide6.QtCore import QObject, Signal, QSize
except ImportError:
    raise ImportError("请安装 PySide6: pip install PySide6")


@dataclass
class MenuItem:
    """菜单项"""
    text: str
    callback: Optional[Callable] = None
    icon: Optional[str] = None
    checkable: bool = False
    checked: bool = False
    enabled: bool = True
    separator_after: bool = False


class TrayIcon(QObject):
    """系统托盘图标"""
    
    # 信号
    activated = Signal()        # 左键点击
    double_clicked = Signal()   # 双击
    middle_clicked = Signal()   # 中键点击
    
    def __init__(self, 
                 icon_path: str = None,
                 tooltip: str = "Game Assistant",
                 parent: QWidget = None):
        """
        初始化系统托盘
        
        Args:
            icon_path: 图标路径
            tooltip: 鼠标悬停提示
            parent: 父窗口
        """
        super().__init__(parent)
        
        self._tray = QSystemTrayIcon(parent)
        self._menu = QMenu()
        self._actions: dict = {}
        
        # 设置图标
        if icon_path and os.path.exists(icon_path):
            self._tray.setIcon(QIcon(icon_path))
        else:
            # 使用默认图标（创建一个简单的图标）
            self._tray.setIcon(self._create_default_icon())
        
        # 设置提示
        self._tray.setToolTip(tooltip)
        
        # 连接信号
        self._tray.activated.connect(self._on_activated)
        
        # 设置菜单
        self._tray.setContextMenu(self._menu)
    
    def _create_default_icon(self) -> QIcon:
        """创建默认图标"""
        # 创建一个简单的蓝色方块图标
        size = 64
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(0xFF4A90D9)  # 蓝色
        
        # 绘制简单的"G"字母效果
        for y in range(size):
            for x in range(size):
                # 边框
                if x < 4 or x >= size - 4 or y < 4 or y >= size - 4:
                    image.setPixelColor(x, y, 0xFF2E5C8A)
        
        pixmap = QPixmap.fromImage(image)
        return QIcon(pixmap)
    
    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason):
        """托盘图标激活事件"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.activated.emit()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.double_clicked.emit()
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self.middle_clicked.emit()
    
    def show(self):
        """显示托盘图标"""
        self._tray.show()
    
    def hide(self):
        """隐藏托盘图标"""
        self._tray.hide()
    
    def set_icon(self, icon_path: str):
        """设置图标"""
        if os.path.exists(icon_path):
            self._tray.setIcon(QIcon(icon_path))
    
    def set_tooltip(self, tooltip: str):
        """设置提示文字"""
        self._tray.setToolTip(tooltip)
    
    def add_menu_item(self, name: str, item: MenuItem) -> QAction:
        """
        添加菜单项
        
        Args:
            name: 菜单项名称（用于后续引用）
            item: MenuItem对象
            
        Returns:
            QAction对象
        """
        action = QAction(item.text, self._menu)
        
        if item.icon and os.path.exists(item.icon):
            action.setIcon(QIcon(item.icon))
        
        if item.callback:
            action.triggered.connect(item.callback)
        
        action.setCheckable(item.checkable)
        action.setChecked(item.checked)
        action.setEnabled(item.enabled)
        
        self._menu.addAction(action)
        
        if item.separator_after:
            self._menu.addSeparator()
        
        self._actions[name] = action
        return action
    
    def add_separator(self):
        """添加分隔线"""
        self._menu.addSeparator()
    
    def remove_menu_item(self, name: str):
        """移除菜单项"""
        if name in self._actions:
            self._menu.removeAction(self._actions[name])
            del self._actions[name]
    
    def set_menu_item_enabled(self, name: str, enabled: bool):
        """设置菜单项启用状态"""
        if name in self._actions:
            self._actions[name].setEnabled(enabled)
    
    def set_menu_item_checked(self, name: str, checked: bool):
        """设置菜单项选中状态"""
        if name in self._actions:
            self._actions[name].setChecked(checked)
    
    def set_menu_item_text(self, name: str, text: str):
        """设置菜单项文本"""
        if name in self._actions:
            self._actions[name].setText(text)
    
    def get_action(self, name: str) -> Optional[QAction]:
        """获取菜单项Action"""
        return self._actions.get(name)
    
    def clear_menu(self):
        """清空菜单"""
        self._menu.clear()
        self._actions.clear()
    
    def show_message(self, title: str, message: str, 
                    icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information,
                    duration_ms: int = 3000):
        """
        显示气泡消息
        
        Args:
            title: 标题
            message: 消息内容
            icon: 图标类型
            duration_ms: 显示时长（毫秒）
        """
        self._tray.showMessage(title, message, icon, duration_ms)
    
    def show_info(self, title: str, message: str, duration_ms: int = 3000):
        """显示信息提示"""
        self.show_message(title, message, 
                         QSystemTrayIcon.MessageIcon.Information, duration_ms)
    
    def show_warning(self, title: str, message: str, duration_ms: int = 3000):
        """显示警告提示"""
        self.show_message(title, message,
                         QSystemTrayIcon.MessageIcon.Warning, duration_ms)
    
    def show_error(self, title: str, message: str, duration_ms: int = 3000):
        """显示错误提示"""
        self.show_message(title, message,
                         QSystemTrayIcon.MessageIcon.Critical, duration_ms)
    
    @property
    def is_visible(self) -> bool:
        """是否可见"""
        return self._tray.isVisible()
    
    @staticmethod
    def is_available() -> bool:
        """系统托盘是否可用"""
        return QSystemTrayIcon.isSystemTrayAvailable()


def create_standard_tray(on_show: Callable = None,
                        on_start_stop: Callable = None,
                        on_pause: Callable = None,
                        on_exit: Callable = None,
                        tooltip: str = "Game Assistant") -> TrayIcon:
    """
    创建标准托盘图标（带常用菜单项）
    
    Args:
        on_show: 显示主窗口回调
        on_start_stop: 开始/停止回调
        on_pause: 暂停回调
        on_exit: 退出回调
        tooltip: 提示文字
        
    Returns:
        TrayIcon实例
    """
    tray = TrayIcon(tooltip=tooltip)
    
    # 显示主窗口
    if on_show:
        tray.add_menu_item("show", MenuItem(
            text="显示主窗口",
            callback=on_show,
            separator_after=True
        ))
    
    # 开始/停止
    if on_start_stop:
        tray.add_menu_item("start_stop", MenuItem(
            text="开始运行",
            callback=on_start_stop
        ))
    
    # 暂停
    if on_pause:
        tray.add_menu_item("pause", MenuItem(
            text="暂停",
            callback=on_pause,
            checkable=True,
            separator_after=True
        ))
    
    # 退出
    if on_exit:
        tray.add_menu_item("exit", MenuItem(
            text="退出",
            callback=on_exit
        ))
    
    return tray


# 测试代码
if __name__ == "__main__":
    import sys
    
    app = QApplication(sys.argv)
    
    def on_show():
        print("显示主窗口")
    
    def on_start():
        print("开始/停止")
    
    def on_pause():
        print("暂停")
    
    def on_exit():
        print("退出")
        app.quit()
    
    # 检查系统托盘是否可用
    if not TrayIcon.is_available():
        print("系统托盘不可用!")
        sys.exit(1)
    
    # 创建托盘
    tray = create_standard_tray(
        on_show=on_show,
        on_start_stop=on_start,
        on_pause=on_pause,
        on_exit=on_exit
    )
    
    # 连接信号
    tray.activated.connect(on_show)
    tray.double_clicked.connect(on_show)
    
    tray.show()
    tray.show_info("Game Assistant", "程序已启动，点击托盘图标显示主窗口")
    
    print("系统托盘已启动，右键点击托盘图标查看菜单")
    
    sys.exit(app.exec())
