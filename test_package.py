#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试打包后的程序是否能正常运行
"""

import sys
import os

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

def test_imports():
    """测试所有导入"""
    print("Testing imports...")
    
    try:
        import mss
        print("✓ mss")
    except ImportError as e:
        print(f"✗ mss: {e}")
    
    try:
        import cv2
        print("✓ opencv-python")
    except ImportError as e:
        print(f"✗ opencv-python: {e}")
    
    try:
        import numpy
        print("✓ numpy")
    except ImportError as e:
        print(f"✗ numpy: {e}")
    
    try:
        import win32gui
        print("✓ pywin32")
    except ImportError as e:
        print(f"✗ pywin32: {e}")
    
    try:
        import pynput
        print("✓ pynput")
    except ImportError as e:
        print(f"✗ pynput: {e}")
    
    try:
        from PySide6.QtWidgets import QApplication
        print("✓ PySide6")
    except ImportError as e:
        print(f"✗ PySide6: {e}")
    
    print("\nAll imports tested!")

def test_gui():
    """测试GUI启动"""
    print("\nTesting GUI startup...")
    
    from PySide6.QtWidgets import QApplication, QMessageBox
    
    app = QApplication(sys.argv)
    
    msg = QMessageBox()
    msg.setWindowTitle("Test")
    msg.setText("GUI test successful!")
    msg.setIcon(QMessageBox.Information)
    msg.setStandardButtons(QMessageBox.Ok)
    result = msg.exec()
    
    print("GUI test completed!")

if __name__ == "__main__":
    test_imports()
    
    # 询问是否测试GUI
    print("\nTest GUI? (y/n): ", end="")
    try:
        choice = input().lower()
        if choice == 'y':
            test_gui()
    except:
        print("Skipping GUI test (no console available)")
