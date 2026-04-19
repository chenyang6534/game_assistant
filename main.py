#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Game Assistant - 游戏辅助工具

主程序入口
"""

import sys
import os
import signal

# 确保项目根目录在路径中
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def check_dependencies():
    """检查必要的依赖"""
    missing = []
    
    try:
        import mss
    except ImportError:
        missing.append("mss")
    
    try:
        import cv2
    except ImportError:
        missing.append("opencv-python")
    
    try:
        import numpy
    except ImportError:
        missing.append("numpy")
    
    try:
        import win32gui
    except ImportError:
        missing.append("pywin32")
    
    try:
        import pynput
    except ImportError:
        missing.append("pynput")
    
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        missing.append("PySide6")
    
    if missing:
        # 不使用 print()，因为窗口程序没有控制台
        # 错误信息将由调用者通过 GUI 显示
        return False
    
    return True


def check_admin():
    """检查是否以管理员权限运行"""
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def _install_sigint_handler(app):
    """让控制台 Ctrl+C 优雅退出 Qt 事件循环。"""
    from PySide6.QtCore import QTimer

    try:
        signal.signal(signal.SIGINT, lambda *_: app.quit())
    except (ValueError, AttributeError):
        return

    timer = QTimer(app)
    timer.setInterval(250)
    timer.timeout.connect(lambda: None)
    timer.start()
    app._sigint_timer = timer


def main():
    """主函数"""
    # 先导入GUI模块（用于显示错误）
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtCore import Qt

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    # 创建应用（在检查依赖前创建，以便显示消息框）
    app = QApplication(sys.argv)
    
    # 检查依赖
    if not check_dependencies():
        QMessageBox.critical(
            None,
            "依赖检查失败",
            "缺少必要的依赖库，请运行 requirements.txt 安装依赖。\n\n"
            "详细信息请查看日志。",
            QMessageBox.Ok
        )
        sys.exit(1)
    
    # 检查管理员权限（不需要提示，只记录）
    # 避免使用 print()，因为窗口程序没有控制台
    
    # 设置应用信息
    app.setApplicationName("Game Assistant")
    app.setApplicationDisplayName("Game Assistant - 游戏辅助工具")
    _install_sigint_handler(app)
    
    # 设置样式
    app.setStyle("Fusion")
    
    # 创建并显示主窗口
    from gui.main_window import MainWindow
    
    window = MainWindow()
    window.show()
    
    # 运行事件循环
    try:
        return app.exec()
    except KeyboardInterrupt:
        window.close()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
