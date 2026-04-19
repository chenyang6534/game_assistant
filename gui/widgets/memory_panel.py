"""
内存扫描面板
扫描目标进程内存，搜索/筛选/监控指定数值
类似 Cheat Engine 的内存搜索功能
"""

import os
import sys
import threading
from typing import Optional, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton,
    QLabel, QLineEdit, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QMessageBox, QProgressBar,
    QSplitter, QPlainTextEdit, QSpinBox, QCheckBox, QMenu,
    QApplication,
)
from PySide6.QtCore import Qt, Signal, Slot, QObject, QTimer
from PySide6.QtGui import QFont, QColor

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from core.memory import MemoryScanner, SCAN_TYPES


class _ScanBridge(QObject):
    """将扫描线程的回调安全转发到主线程"""
    scan_progress = Signal(int, int)
    scan_finished = Signal(int)
    scan_error = Signal(str)


class MemoryPanel(QWidget):
    """内存扫描面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scanner = MemoryScanner()
        self._bridge = _ScanBridge()
        self._bridge.scan_progress.connect(self._on_scan_progress)
        self._bridge.scan_finished.connect(self._on_scan_finished)
        self._bridge.scan_error.connect(self._on_scan_error)

        self._pid: Optional[int] = None
        self._is_first_scan = True
        self._monitor_timer = QTimer(self)
        self._monitor_timer.timeout.connect(self._refresh_monitored)
        self._monitored_addresses: list = []  # [(address, data_type, label)]

        self._init_ui()

    def set_pid(self, pid: Optional[int]):
        """设置目标进程 PID"""
        self._pid = pid
        if pid:
            self._pid_label.setText(f"目标进程 PID: {pid}")
            ok = self._scanner.attach(pid)
            if ok:
                self._pid_label.setText(f"目标进程 PID: {pid} [已附加]")
                self._first_scan_btn.setEnabled(True)
            else:
                self._pid_label.setText(f"目标进程 PID: {pid} [附加失败，需要管理员权限？]")
                self._first_scan_btn.setEnabled(False)
        else:
            self._pid_label.setText("未选择目标进程")
            self._first_scan_btn.setEnabled(False)
            self._scanner.detach()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # 说明
        info = QLabel(
            "💡 内存扫描：在目标进程内存中搜索已知数值（如坐标），多次筛选定位精确地址。\n"
            "用法：输入已知值 → 首次扫描 → 在目标程序中改变该值 → 输入新值 → 再次扫描 → 重复直到结果收敛。"
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            "color: #0c5460; background-color: #d1ecf1; border: 1px solid #bee5eb;"
            "padding: 8px; border-radius: 4px; font-size: 12px;"
        )
        layout.addWidget(info)

        # === 控制区 ===
        control_group = QGroupBox("扫描控制")
        control_layout = QVBoxLayout(control_group)

        # 第一行：PID
        row1 = QHBoxLayout()
        self._pid_label = QLabel("未选择目标进程")
        row1.addWidget(self._pid_label)
        row1.addStretch()
        control_layout.addLayout(row1)

        # 第二行：搜索参数
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("数据类型:"))
        self._type_combo = QComboBox()
        self._type_combo.addItems([
            "int32", "uint32", "int16", "uint16",
            "float", "double",
            "int64", "uint64", "int8", "uint8",
            "int32_be", "uint32_be", "int16_be", "uint16_be", "float_be",
        ])
        self._type_combo.setCurrentIndex(0)
        row2.addWidget(self._type_combo)

        row2.addWidget(QLabel("值:"))
        self._value_input = QLineEdit()
        self._value_input.setPlaceholderText("输入要搜索的数值，如 998")
        self._value_input.setClearButtonEnabled(True)
        row2.addWidget(self._value_input, 1)

        control_layout.addLayout(row2)

        # 第三行：操作按钮
        row3 = QHBoxLayout()

        self._first_scan_btn = QPushButton("首次扫描")
        self._first_scan_btn.setMinimumWidth(100)
        self._first_scan_btn.setEnabled(False)
        self._first_scan_btn.clicked.connect(self._do_first_scan)
        self._first_scan_btn.setStyleSheet("QPushButton { font-weight: bold; }")
        row3.addWidget(self._first_scan_btn)

        self._next_scan_btn = QPushButton("再次扫描 (等于)")
        self._next_scan_btn.setMinimumWidth(120)
        self._next_scan_btn.setEnabled(False)
        self._next_scan_btn.clicked.connect(self._do_next_scan_eq)
        row3.addWidget(self._next_scan_btn)

        # 高级筛选
        self._filter_combo = QComboBox()
        self._filter_combo.addItems([
            "等于新值", "不等于新值", "大于新值", "小于新值",
            "值变化了", "值未变化",
        ])
        row3.addWidget(self._filter_combo)

        self._advanced_scan_btn = QPushButton("筛选")
        self._advanced_scan_btn.setEnabled(False)
        self._advanced_scan_btn.clicked.connect(self._do_next_scan_advanced)
        row3.addWidget(self._advanced_scan_btn)

        self._cancel_btn = QPushButton("取消扫描")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._cancel_scan)
        row3.addWidget(self._cancel_btn)

        self._reset_btn = QPushButton("重置")
        self._reset_btn.clicked.connect(self._reset_scan)
        row3.addWidget(self._reset_btn)

        control_layout.addLayout(row3)

        # 进度条
        self._progress_bar = QProgressBar()
        self._progress_bar.setMaximumHeight(16)
        self._progress_bar.setVisible(False)
        control_layout.addWidget(self._progress_bar)

        layout.addWidget(control_group)

        # === 上下分割 ===
        splitter = QSplitter(Qt.Vertical)

        # 上部：搜索结果表
        result_widget = QWidget()
        result_layout = QVBoxLayout(result_widget)
        result_layout.setContentsMargins(0, 0, 0, 0)

        self._result_label = QLabel("搜索结果: 0 条")
        result_layout.addWidget(self._result_label)

        self._result_table = QTableWidget()
        self._result_table.setColumnCount(5)
        self._result_table.setHorizontalHeaderLabels([
            "地址", "当前值", "数据类型", "上一次值", "变化"
        ])
        self._result_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._result_table.horizontalHeader().setStretchLastSection(True)
        self._result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._result_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._result_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._result_table.setAlternatingRowColors(True)
        self._result_table.verticalHeader().setVisible(False)
        self._result_table.setFont(QFont("Consolas", 10))
        self._result_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._result_table.customContextMenuRequested.connect(self._show_result_menu)

        self._result_table.setColumnWidth(0, 180)
        self._result_table.setColumnWidth(1, 120)
        self._result_table.setColumnWidth(2, 100)
        self._result_table.setColumnWidth(3, 120)
        self._result_table.setColumnWidth(4, 80)

        result_layout.addWidget(self._result_table)

        # 结果操作栏
        result_btn_layout = QHBoxLayout()
        self._refresh_btn = QPushButton("刷新值")
        self._refresh_btn.clicked.connect(self._refresh_results)
        result_btn_layout.addWidget(self._refresh_btn)

        self._add_monitor_btn = QPushButton("添加到监控")
        self._add_monitor_btn.clicked.connect(self._add_to_monitor)
        result_btn_layout.addWidget(self._add_monitor_btn)

        result_btn_layout.addStretch()

        self._result_count_info = QLabel("")
        result_btn_layout.addWidget(self._result_count_info)

        result_layout.addLayout(result_btn_layout)
        splitter.addWidget(result_widget)

        # 下部：地址监控
        monitor_widget = QWidget()
        monitor_layout = QVBoxLayout(monitor_widget)
        monitor_layout.setContentsMargins(0, 0, 0, 0)

        monitor_bar = QHBoxLayout()
        monitor_bar.addWidget(QLabel("地址监控 (实时刷新):"))

        self._monitor_check = QCheckBox("启用实时监控")
        self._monitor_check.stateChanged.connect(self._toggle_monitor)
        monitor_bar.addWidget(self._monitor_check)

        self._monitor_interval_spin = QSpinBox()
        self._monitor_interval_spin.setRange(100, 5000)
        self._monitor_interval_spin.setValue(500)
        self._monitor_interval_spin.setSuffix(" ms")
        self._monitor_interval_spin.valueChanged.connect(
            lambda v: self._monitor_timer.setInterval(v) if self._monitor_timer.isActive() else None
        )
        monitor_bar.addWidget(self._monitor_interval_spin)

        self._clear_monitor_btn = QPushButton("清空监控")
        self._clear_monitor_btn.clicked.connect(self._clear_monitor)
        monitor_bar.addWidget(self._clear_monitor_btn)

        monitor_bar.addStretch()
        monitor_layout.addLayout(monitor_bar)

        self._monitor_table = QTableWidget()
        self._monitor_table.setColumnCount(5)
        self._monitor_table.setHorizontalHeaderLabels([
            "备注", "地址", "数据类型", "当前值", "历史变化"
        ])
        self._monitor_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._monitor_table.horizontalHeader().setStretchLastSection(True)
        self._monitor_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._monitor_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._monitor_table.setAlternatingRowColors(True)
        self._monitor_table.verticalHeader().setVisible(False)
        self._monitor_table.setFont(QFont("Consolas", 10))

        self._monitor_table.setColumnWidth(0, 100)
        self._monitor_table.setColumnWidth(1, 180)
        self._monitor_table.setColumnWidth(2, 80)
        self._monitor_table.setColumnWidth(3, 120)

        monitor_layout.addWidget(self._monitor_table)
        splitter.addWidget(monitor_widget)

        splitter.setSizes([400, 200])
        layout.addWidget(splitter, 1)

    # ==================== 扫描操作 ====================

    def _parse_value(self):
        """解析输入框中的值"""
        text = self._value_input.text().strip()
        if not text:
            return None
        dtype = self._type_combo.currentText()
        try:
            if 'float' in dtype or 'double' in dtype:
                return float(text)
            else:
                # 支持十六进制输入
                if text.startswith('0x') or text.startswith('0X'):
                    return int(text, 16)
                return int(text)
        except ValueError:
            return None

    def _do_first_scan(self):
        """首次扫描"""
        value = self._parse_value()
        if value is None:
            QMessageBox.warning(self, "提示", "请输入有效数值")
            return

        if not self._scanner.attach(self._pid):
            QMessageBox.warning(self, "错误", "无法附加到进程，请以管理员身份运行程序。")
            return

        dtype = self._type_combo.currentText()

        self._set_scanning_state(True)
        self._is_first_scan = True
        self._result_table.setRowCount(0)

        def do_scan():
            try:
                count = self._scanner.first_scan(
                    value, dtype,
                    progress_cb=lambda done, total: self._bridge.scan_progress.emit(done, total)
                )
                self._bridge.scan_finished.emit(count)
            except Exception as e:
                self._bridge.scan_error.emit(str(e))

        t = threading.Thread(target=do_scan, daemon=True)
        t.start()

    def _do_next_scan_eq(self):
        """再次扫描 - 等于"""
        value = self._parse_value()
        if value is None:
            QMessageBox.warning(self, "提示", "请输入新的数值")
            return

        self._set_scanning_state(True)
        self._is_first_scan = False

        def do_scan():
            try:
                count = self._scanner.next_scan(
                    value, "eq",
                    progress_cb=lambda done, total: self._bridge.scan_progress.emit(done, total)
                )
                self._bridge.scan_finished.emit(count)
            except Exception as e:
                self._bridge.scan_error.emit(str(e))

        t = threading.Thread(target=do_scan, daemon=True)
        t.start()

    def _do_next_scan_advanced(self):
        """使用高级筛选条件扫描"""
        filter_map = {
            "等于新值": "eq",
            "不等于新值": "neq",
            "大于新值": "gt",
            "小于新值": "lt",
            "值变化了": "changed",
            "值未变化": "unchanged",
        }
        compare = filter_map.get(self._filter_combo.currentText(), "eq")

        value = None
        if compare in ("eq", "neq", "gt", "lt"):
            value = self._parse_value()
            if value is None:
                QMessageBox.warning(self, "提示", "此筛选条件需要输入数值")
                return
        else:
            value = 0  # unused for changed/unchanged

        self._set_scanning_state(True)
        self._is_first_scan = False

        def do_scan():
            try:
                count = self._scanner.next_scan(
                    value, compare,
                    progress_cb=lambda done, total: self._bridge.scan_progress.emit(done, total)
                )
                self._bridge.scan_finished.emit(count)
            except Exception as e:
                self._bridge.scan_error.emit(str(e))

        t = threading.Thread(target=do_scan, daemon=True)
        t.start()

    def _cancel_scan(self):
        self._scanner.cancel()

    def _reset_scan(self):
        """重置扫描"""
        self._scanner._results.clear()
        self._result_table.setRowCount(0)
        self._result_label.setText("搜索结果: 0 条")
        self._result_count_info.setText("")
        self._is_first_scan = True
        self._next_scan_btn.setEnabled(False)
        self._advanced_scan_btn.setEnabled(False)
        self._first_scan_btn.setEnabled(self._pid is not None)

    def _set_scanning_state(self, scanning: bool):
        self._first_scan_btn.setEnabled(not scanning)
        self._next_scan_btn.setEnabled(not scanning)
        self._advanced_scan_btn.setEnabled(not scanning)
        self._cancel_btn.setEnabled(scanning)
        self._progress_bar.setVisible(scanning)
        if scanning:
            self._progress_bar.setValue(0)
            self._result_label.setText("正在扫描...")

    @Slot(int, int)
    def _on_scan_progress(self, done, total):
        if total > 0:
            self._progress_bar.setMaximum(total)
            self._progress_bar.setValue(done)

    @Slot(int)
    def _on_scan_finished(self, count):
        self._set_scanning_state(False)
        self._result_label.setText(f"搜索结果: {count} 条")

        has_results = count > 0
        self._next_scan_btn.setEnabled(has_results)
        self._advanced_scan_btn.setEnabled(has_results)

        # 显示结果
        self._populate_result_table()

        if count == 0:
            self._result_count_info.setText("未找到匹配。试试其他数据类型？")
        elif count > 10000:
            self._result_count_info.setText(f"结果过多({count})，请先在目标程序中改变该数值后再次扫描缩小范围")
        else:
            self._result_count_info.setText("")

    @Slot(str)
    def _on_scan_error(self, msg):
        self._set_scanning_state(False)
        QMessageBox.warning(self, "扫描错误", msg)

    def _populate_result_table(self):
        """填充结果表格（最多显示5000行）"""
        results = self._scanner.results
        show_count = min(len(results), 5000)

        self._result_table.setRowCount(show_count)
        for i in range(show_count):
            res = results[i]

            self._result_table.setItem(i, 0, QTableWidgetItem(res.address_hex))

            # 显示值
            if 'float' in res.data_type or 'double' in res.data_type:
                val_str = f"{res.value:.6g}"
            else:
                val_str = str(int(res.value))
            self._result_table.setItem(i, 1, QTableWidgetItem(val_str))

            self._result_table.setItem(i, 2, QTableWidgetItem(res.data_type))

            # 上一次值
            if res.previous_values:
                prev = res.previous_values[-1]
                if 'float' in res.data_type or 'double' in res.data_type:
                    prev_str = f"{prev:.6g}"
                else:
                    prev_str = str(int(prev))
                self._result_table.setItem(i, 3, QTableWidgetItem(prev_str))

                # 变化
                diff = res.value - prev
                if diff > 0:
                    change_item = QTableWidgetItem(f"+{diff:.6g}" if 'float' in res.data_type else f"+{int(diff)}")
                    change_item.setForeground(QColor("green"))
                elif diff < 0:
                    change_item = QTableWidgetItem(f"{diff:.6g}" if 'float' in res.data_type else str(int(diff)))
                    change_item.setForeground(QColor("red"))
                else:
                    change_item = QTableWidgetItem("0")
                self._result_table.setItem(i, 4, change_item)
            else:
                self._result_table.setItem(i, 3, QTableWidgetItem("-"))
                self._result_table.setItem(i, 4, QTableWidgetItem("-"))

        if len(results) > 5000:
            info = f"(仅显示前 5000 条，共 {len(results)} 条)"
            self._result_count_info.setText(info)

    def _refresh_results(self):
        """刷新所有结果的当前值"""
        if not self._scanner.results:
            return
        self._scanner.refresh_values()
        self._populate_result_table()

    # ==================== 右键菜单 ====================

    def _show_result_menu(self, pos):
        menu = QMenu(self)
        add_monitor = menu.addAction("添加到监控")
        copy_addr = menu.addAction("复制地址")
        copy_val = menu.addAction("复制值")

        action = menu.exec_(self._result_table.mapToGlobal(pos))
        if action == add_monitor:
            self._add_to_monitor()
        elif action == copy_addr:
            rows = set(item.row() for item in self._result_table.selectedItems())
            results = self._scanner.results
            addrs = [results[r].address_hex for r in sorted(rows) if r < len(results)]
            QApplication.clipboard().setText('\n'.join(addrs))
        elif action == copy_val:
            rows = set(item.row() for item in self._result_table.selectedItems())
            results = self._scanner.results
            vals = [str(int(results[r].value)) if 'float' not in results[r].data_type
                    else f"{results[r].value:.6g}"
                    for r in sorted(rows) if r < len(results)]
            QApplication.clipboard().setText('\n'.join(vals))

    # ==================== 地址监控 ====================

    def _add_to_monitor(self):
        """将选中的结果添加到监控列表"""
        rows = set(item.row() for item in self._result_table.selectedItems())
        results = self._scanner.results

        for r in sorted(rows):
            if r >= len(results):
                continue
            res = results[r]
            # 避免重复
            if any(addr == res.address and dtype == res.data_type
                   for addr, dtype, _ in self._monitored_addresses):
                continue
            self._monitored_addresses.append((res.address, res.data_type, ""))

        self._update_monitor_table()

    def _clear_monitor(self):
        self._monitored_addresses.clear()
        self._monitor_table.setRowCount(0)

    def _toggle_monitor(self, state):
        if state == Qt.Checked:
            interval = self._monitor_interval_spin.value()
            self._monitor_timer.start(interval)
        else:
            self._monitor_timer.stop()

    def _refresh_monitored(self):
        """定时刷新监控地址的值"""
        if not self._scanner._handle or not self._monitored_addresses:
            return
        self._update_monitor_table()

    def _update_monitor_table(self):
        """更新监控表格"""
        self._monitor_table.setRowCount(len(self._monitored_addresses))
        for i, (addr, dtype, label) in enumerate(self._monitored_addresses):
            self._monitor_table.setItem(i, 0, QTableWidgetItem(label or f"地址{i+1}"))
            self._monitor_table.setItem(i, 1, QTableWidgetItem(f"0x{addr:016X}"))
            self._monitor_table.setItem(i, 2, QTableWidgetItem(dtype))

            val = self._scanner.read_value(addr, dtype)
            if val is not None:
                if 'float' in dtype or 'double' in dtype:
                    val_str = f"{val:.6g}"
                else:
                    val_str = str(int(val))
                self._monitor_table.setItem(i, 3, QTableWidgetItem(val_str))
            else:
                item = QTableWidgetItem("读取失败")
                item.setForeground(QColor("red"))
                self._monitor_table.setItem(i, 3, item)

            self._monitor_table.setItem(i, 4, QTableWidgetItem(""))

    def cleanup(self):
        """清理资源"""
        self._monitor_timer.stop()
        self._scanner.cancel()
        self._scanner.detach()
