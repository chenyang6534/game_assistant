"""
网络消息截取面板
截取目标窗口进程的网络收发消息，支持保存、编辑和模拟发送
"""

import os
import struct
import sys
from typing import Optional, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton,
    QLabel, QLineEdit, QComboBox, QCheckBox, QPlainTextEdit,
    QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QFileDialog, QDialog, QFormLayout,
    QAbstractItemView, QMenu, QSpinBox, QTabWidget,
    QScrollArea, QGridLayout,
)
from PySide6.QtCore import Qt, Signal, Slot, QObject
from PySide6.QtGui import QColor, QFont

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from core.network import NetworkSniffer, NetworkPacket, save_packets, load_packets


class _SnifferBridge(QObject):
    """将子线程回调安全转发到主线程的信号桥"""
    packet_received = Signal(object)
    error_occurred = Signal(str)


class PacketEditDialog(QDialog):
    """数据包编辑与发送对话框"""

    def __init__(self, packet: NetworkPacket = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑并发送数据包")
        self.setMinimumSize(500, 400)
        self._packet = packet
        self._init_ui()
        if packet:
            self._load_packet(packet)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._protocol_combo = QComboBox()
        self._protocol_combo.addItems(["TCP", "UDP"])
        form.addRow("协议:", self._protocol_combo)

        self._dst_ip_edit = QLineEdit()
        self._dst_ip_edit.setPlaceholderText("例如: 192.168.1.100")
        form.addRow("目标IP:", self._dst_ip_edit)

        self._dst_port_spin = QSpinBox()
        self._dst_port_spin.setRange(1, 65535)
        form.addRow("目标端口:", self._dst_port_spin)

        self._src_port_spin = QSpinBox()
        self._src_port_spin.setRange(0, 65535)
        self._src_port_spin.setSpecialValueText("自动")
        form.addRow("源端口:", self._src_port_spin)

        layout.addLayout(form)

        # 数据编辑区
        data_group = QGroupBox("数据内容")
        data_layout = QVBoxLayout(data_group)

        fmt_layout = QHBoxLayout()
        self._hex_mode = QCheckBox("Hex编辑模式")
        self._hex_mode.setChecked(False)
        fmt_layout.addWidget(self._hex_mode)
        fmt_layout.addStretch()
        data_layout.addLayout(fmt_layout)

        self._data_edit = QPlainTextEdit()
        self._data_edit.setFont(QFont("Consolas", 10))
        self._data_edit.setPlaceholderText("输入要发送的数据内容...")
        data_layout.addWidget(self._data_edit)

        layout.addWidget(data_group)

        # 发送方式
        send_group = QGroupBox("发送方式")
        send_layout = QVBoxLayout(send_group)
        self._use_socket = QCheckBox("使用标准Socket发送（推荐，无需管理员权限）")
        self._use_socket.setChecked(True)
        send_layout.addWidget(self._use_socket)
        layout.addWidget(send_group)

        # 按钮
        btn_layout = QHBoxLayout()
        self._send_btn = QPushButton("发送")
        self._send_btn.clicked.connect(self._on_send)
        btn_layout.addWidget(self._send_btn)

        self._close_btn = QPushButton("关闭")
        self._close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._close_btn)

        layout.addLayout(btn_layout)

        self._status_label = QLabel("")
        layout.addWidget(self._status_label)

    def _load_packet(self, pkt: NetworkPacket):
        idx = self._protocol_combo.findText(pkt.protocol)
        if idx >= 0:
            self._protocol_combo.setCurrentIndex(idx)

        if pkt.direction == "SEND":
            self._dst_ip_edit.setText(pkt.dst_ip)
            self._dst_port_spin.setValue(pkt.dst_port)
            self._src_port_spin.setValue(pkt.src_port)
        else:
            self._dst_ip_edit.setText(pkt.src_ip)
            self._dst_port_spin.setValue(pkt.src_port)
            self._src_port_spin.setValue(pkt.dst_port)

        if pkt.data:
            self._data_edit.setPlainText(pkt.data_text)

    def _get_data(self) -> bytes:
        text = self._data_edit.toPlainText()
        if self._hex_mode.isChecked():
            hex_str = text.replace(' ', '').replace('\n', '').replace('\r', '')
            return bytes.fromhex(hex_str)
        else:
            return text.encode('utf-8')

    def _on_send(self):
        protocol = self._protocol_combo.currentText()
        dst_ip = self._dst_ip_edit.text().strip()
        dst_port = self._dst_port_spin.value()
        src_port = self._src_port_spin.value()

        if not dst_ip:
            QMessageBox.warning(self, "提示", "请填写目标IP地址")
            return

        try:
            data = self._get_data()
        except ValueError as e:
            QMessageBox.warning(self, "数据格式错误", f"Hex数据格式不正确: {e}")
            return

        if self._use_socket.isChecked():
            ok = NetworkSniffer.send_socket_packet(protocol, dst_ip, dst_port, data)
        else:
            ok = NetworkSniffer.send_raw_packet(protocol, dst_ip, dst_port, data, src_port)

        if ok:
            self._status_label.setText("发送成功")
            self._status_label.setStyleSheet("color: green;")
        else:
            self._status_label.setText("发送失败")
            self._status_label.setStyleSheet("color: red;")


class NetworkPanel(QWidget):
    """网络消息截取面板"""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._sniffer = NetworkSniffer()
        self._bridge = _SnifferBridge()
        self._bridge.packet_received.connect(self._on_packet_received)
        self._bridge.error_occurred.connect(self._on_sniffer_error)

        self._packets: List[NetworkPacket] = []
        self._filtered_packets: List[NetworkPacket] = []
        self._auto_scroll = True
        self._max_packets = 10000
        self._pid: Optional[int] = None

        self._init_ui()

    @property
    def is_available(self) -> bool:
        return self._sniffer.is_available

    def set_pid(self, pid: Optional[int]):
        """设置目标进程PID"""
        self._pid = pid
        mode = self._sniffer.capture_mode
        if pid:
            self._pid_label.setText(f"目标进程PID: {pid}  |  抓包模式: {mode}")
        else:
            self._pid_label.setText("未选择目标进程")

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # 可用性警告 / 模式提示
        if not self._sniffer.is_available:
            warning = QLabel(
                "⚠️ 网络抓包功能不可用。\n"
                "请安装依赖: pip install scapy psutil"
            )
            warning.setStyleSheet("color: red; padding: 10px; font-size: 13px;")
            warning.setWordWrap(True)
            layout.addWidget(warning)
        elif not self._sniffer.is_full_capture:
            mode_banner = QLabel(
                "⚠️ 当前为有限模式：仅能捕获【发送方向】的数据包。\n"
                "如需捕获完整双向（收发）流量，请安装 Npcap 驱动（免费，约1MB）。\n"
                "下载地址: https://npcap.com/#download  —— 安装后重启本程序即可。"
            )
            mode_banner.setStyleSheet(
                "color: #856404; background-color: #fff3cd; border: 1px solid #ffc107;"
                "padding: 8px; border-radius: 4px; font-size: 12px;"
            )
            mode_banner.setWordWrap(True)
            mode_banner.setTextInteractionFlags(Qt.TextBrowserInteraction)
            mode_banner.setOpenExternalLinks(True)
            layout.addWidget(mode_banner)

        # === 控制栏 ===
        control_group = QGroupBox("抓包控制")
        control_layout = QVBoxLayout(control_group)

        # 第一行：PID & 启停
        row1 = QHBoxLayout()
        self._pid_label = QLabel("未选择目标进程")
        row1.addWidget(self._pid_label)
        row1.addStretch()

        self._start_btn = QPushButton("▶ 开始抓包")
        self._start_btn.clicked.connect(self._start_capture)
        self._start_btn.setMinimumWidth(100)
        self._start_btn.setEnabled(self._sniffer.is_available)
        row1.addWidget(self._start_btn)

        self._stop_btn = QPushButton("■ 停止抓包")
        self._stop_btn.clicked.connect(self._stop_capture)
        self._stop_btn.setEnabled(False)
        self._stop_btn.setMinimumWidth(100)
        row1.addWidget(self._stop_btn)

        self._clear_btn = QPushButton("清空")
        self._clear_btn.clicked.connect(self._clear_packets)
        row1.addWidget(self._clear_btn)

        control_layout.addLayout(row1)

        # 第二行：过滤
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("过滤:"))

        self._filter_protocol = QComboBox()
        self._filter_protocol.addItems(["全部", "TCP", "UDP"])
        self._filter_protocol.currentIndexChanged.connect(self._apply_filter)
        row2.addWidget(self._filter_protocol)

        self._filter_direction = QComboBox()
        self._filter_direction.addItems(["全部", "SEND", "RECV"])
        self._filter_direction.currentIndexChanged.connect(self._apply_filter)
        row2.addWidget(self._filter_direction)

        row2.addWidget(QLabel("关键字:"))
        self._filter_keyword = QLineEdit()
        self._filter_keyword.setPlaceholderText("搜索数据内容...")
        self._filter_keyword.setClearButtonEnabled(True)
        self._filter_keyword.textChanged.connect(self._apply_filter)
        row2.addWidget(self._filter_keyword, 1)

        self._only_data_check = QCheckBox("仅显示有数据的包")
        self._only_data_check.setChecked(True)
        self._only_data_check.stateChanged.connect(self._apply_filter)
        row2.addWidget(self._only_data_check)

        control_layout.addLayout(row2)
        layout.addWidget(control_group)

        # === 主体（上下分割） ===
        splitter = QSplitter(Qt.Vertical)

        # 上部：数据包列表
        self._packet_table = QTableWidget()
        self._packet_table.setColumnCount(7)
        self._packet_table.setHorizontalHeaderLabels([
            "#", "时间", "方向", "协议", "源地址", "目标地址", "数据长度"
        ])
        self._packet_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._packet_table.horizontalHeader().setStretchLastSection(True)
        self._packet_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._packet_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._packet_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._packet_table.setAlternatingRowColors(True)
        self._packet_table.verticalHeader().setVisible(False)
        self._packet_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._packet_table.customContextMenuRequested.connect(self._show_context_menu)
        self._packet_table.currentCellChanged.connect(self._on_packet_selected)

        self._packet_table.setColumnWidth(0, 50)
        self._packet_table.setColumnWidth(1, 100)
        self._packet_table.setColumnWidth(2, 60)
        self._packet_table.setColumnWidth(3, 50)
        self._packet_table.setColumnWidth(4, 160)
        self._packet_table.setColumnWidth(5, 160)
        self._packet_table.setColumnWidth(6, 80)

        splitter.addWidget(self._packet_table)

        # 下部：详情区域
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(0, 0, 0, 0)

        self._detail_tabs = QTabWidget()

        # --- Tab 1: Hex视图 ---
        self._hex_view = QPlainTextEdit()
        self._hex_view.setReadOnly(True)
        self._hex_view.setFont(QFont("Consolas", 10))
        self._hex_view.setPlaceholderText("选择数据包查看Hex数据...")
        self._detail_tabs.addTab(self._hex_view, "Hex视图")

        # --- Tab 2: 文本视图 ---
        self._text_view = QPlainTextEdit()
        self._text_view.setReadOnly(True)
        self._text_view.setFont(QFont("Consolas", 10))
        self._text_view.setPlaceholderText("选择数据包查看文本数据...")
        self._detail_tabs.addTab(self._text_view, "文本视图")

        # --- Tab 3: 数值搜索 ---
        search_widget = QWidget()
        search_layout = QVBoxLayout(search_widget)
        search_layout.setContentsMargins(4, 4, 4, 4)

        search_bar = QHBoxLayout()
        search_bar.addWidget(QLabel("搜索数值:"))
        self._search_value_input = QLineEdit()
        self._search_value_input.setPlaceholderText("输入已知数值，如 998 或 717")
        self._search_value_input.setClearButtonEnabled(True)
        search_bar.addWidget(self._search_value_input, 1)
        self._search_value_btn = QPushButton("搜索")
        self._search_value_btn.clicked.connect(self._search_value_in_packet)
        search_bar.addWidget(self._search_value_btn)
        self._search_value_input.returnPressed.connect(self._search_value_in_packet)
        search_layout.addLayout(search_bar)

        self._search_result_view = QPlainTextEdit()
        self._search_result_view.setReadOnly(True)
        self._search_result_view.setFont(QFont("Consolas", 10))
        self._search_result_view.setPlaceholderText(
            "输入一个已知数值（如坐标998），将在数据包中搜索所有可能的编码方式：\n"
            "  · int8 / int16 / int32 大端/小端\n"
            "  · float32 大端/小端\n"
            "  · Protobuf varint / zigzag varint\n"
            "  · XOR 单字节密钥 (0x01-0xFF) uint16\n"
            "  · 文本形式 (ASCII)\n\n"
            "用于逆向分析协议中数值字段的位置和编码格式。\n"
            "如果都没找到，说明数据可能已加密/压缩。\n"
            "建议：对同一操作抓多个包，使用「多包对比」找变化字节。"
        )
        search_layout.addWidget(self._search_result_view)
        self._detail_tabs.addTab(search_widget, "数值搜索")

        # --- Tab 4: 数据检视器 ---
        inspector_widget = QWidget()
        inspector_layout = QVBoxLayout(inspector_widget)
        inspector_layout.setContentsMargins(4, 4, 4, 4)

        offset_bar = QHBoxLayout()
        offset_bar.addWidget(QLabel("偏移量:"))
        self._inspector_offset_spin = QSpinBox()
        self._inspector_offset_spin.setRange(0, 0)
        self._inspector_offset_spin.valueChanged.connect(self._update_inspector)
        offset_bar.addWidget(self._inspector_offset_spin)
        offset_bar.addWidget(QLabel("(点击上方Hex视图中的偏移量可快速跳转)"))
        offset_bar.addStretch()
        inspector_layout.addLayout(offset_bar)

        self._inspector_table = QTableWidget()
        self._inspector_table.setColumnCount(3)
        self._inspector_table.setHorizontalHeaderLabels(["数据类型", "值", "Hex"])
        self._inspector_table.horizontalHeader().setStretchLastSection(True)
        self._inspector_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._inspector_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._inspector_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._inspector_table.setAlternatingRowColors(True)
        self._inspector_table.verticalHeader().setVisible(False)
        self._inspector_table.setFont(QFont("Consolas", 10))
        inspector_layout.addWidget(self._inspector_table)
        self._detail_tabs.addTab(inspector_widget, "数据检视器")

        # --- Tab 5: 结构化分析 ---
        struct_widget = QWidget()
        struct_layout = QVBoxLayout(struct_widget)
        struct_layout.setContentsMargins(4, 4, 4, 4)

        struct_bar = QHBoxLayout()
        struct_bar.addWidget(QLabel("字节序:"))
        self._struct_endian = QComboBox()
        self._struct_endian.addItems(["小端 (Little-Endian)", "大端 (Big-Endian)"])
        self._struct_endian.currentIndexChanged.connect(self._update_struct_view)
        struct_bar.addWidget(self._struct_endian)
        struct_bar.addStretch()
        struct_layout.addLayout(struct_bar)

        self._struct_table = QTableWidget()
        self._struct_table.setColumnCount(6)
        self._struct_table.setHorizontalHeaderLabels([
            "偏移", "Hex", "uint8", "int16", "int32", "float32"
        ])
        self._struct_table.horizontalHeader().setStretchLastSection(True)
        self._struct_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._struct_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._struct_table.setAlternatingRowColors(True)
        self._struct_table.verticalHeader().setVisible(False)
        self._struct_table.setFont(QFont("Consolas", 9))
        struct_layout.addWidget(self._struct_table)
        self._detail_tabs.addTab(struct_widget, "结构化分析")

        # --- Tab 6: Protobuf 裸解析 ---
        protobuf_widget = QWidget()
        protobuf_layout = QVBoxLayout(protobuf_widget)
        protobuf_layout.setContentsMargins(4, 4, 4, 4)

        pb_bar = QHBoxLayout()
        self._pb_decode_btn = QPushButton("尝试解析")
        self._pb_decode_btn.clicked.connect(self._decode_protobuf)
        pb_bar.addWidget(self._pb_decode_btn)
        self._pb_offset_spin = QSpinBox()
        self._pb_offset_spin.setPrefix("起始偏移: ")
        self._pb_offset_spin.setRange(0, 0)
        pb_bar.addWidget(self._pb_offset_spin)
        pb_bar.addWidget(QLabel("(某些协议在数据前有固定头部，可调整偏移跳过)"))
        pb_bar.addStretch()
        protobuf_layout.addLayout(pb_bar)

        self._protobuf_view = QPlainTextEdit()
        self._protobuf_view.setReadOnly(True)
        self._protobuf_view.setFont(QFont("Consolas", 10))
        self._protobuf_view.setPlaceholderText(
            "点击「尝试解析」将当前数据包按 Protobuf 格式裸解析。\n\n"
            "许多客户端程序使用 Protobuf (Protocol Buffers) 序列化网络消息。\n"
            "裸解析可以在没有 .proto 定义的情况下，提取出字段编号、\n"
            "wire type 和原始值，帮助逆向分析协议结构。\n\n"
            "如果解析失败或结果无意义，说明数据不是 Protobuf 格式\n"
            "（可能已加密/压缩/使用其他序列化格式）。"
        )
        protobuf_layout.addWidget(self._protobuf_view)
        self._detail_tabs.addTab(protobuf_widget, "Protobuf解析")

        # --- Tab 7: 多包对比 ---
        compare_widget = QWidget()
        compare_layout = QVBoxLayout(compare_widget)
        compare_layout.setContentsMargins(4, 4, 4, 4)

        cmp_bar = QHBoxLayout()
        cmp_bar.addWidget(QLabel("在数据包列表中选择2-10条消息，然后点击对比："))
        self._compare_btn = QPushButton("对比选中的数据包")
        self._compare_btn.clicked.connect(self._compare_selected_packets)
        cmp_bar.addWidget(self._compare_btn)
        cmp_bar.addStretch()
        compare_layout.addLayout(cmp_bar)

        self._compare_view = QPlainTextEdit()
        self._compare_view.setReadOnly(True)
        self._compare_view.setFont(QFont("Consolas", 10))
        self._compare_view.setPlaceholderText(
            "多包对比：选中多个数据包后，逐字节对比找出差异位置。\n\n"
            "用法：对同一操作（如移动到不同坐标）抓取多个包，\n"
            "对比后可以发现哪些字节位置发生了变化，\n"
            "从而定位出坐标等可变字段的偏移量。\n\n"
            "固定的字节 = 协议头/消息类型ID\n"
            "变化的字节 = 可变参数（坐标、数量等）"
        )
        compare_layout.addWidget(self._compare_view)
        self._detail_tabs.addTab(compare_widget, "多包对比")

        detail_layout.addWidget(self._detail_tabs)
        splitter.addWidget(detail_widget)

        # 缓存当前选中的数据包数据
        self._current_packet_data: bytes = b""

        splitter.setSizes([400, 200])
        layout.addWidget(splitter, 1)

        # === 操作栏 ===
        action_layout = QHBoxLayout()

        self._save_selected_btn = QPushButton("保存选中")
        self._save_selected_btn.clicked.connect(self._save_selected)
        action_layout.addWidget(self._save_selected_btn)

        self._save_all_btn = QPushButton("保存全部")
        self._save_all_btn.clicked.connect(self._save_all)
        action_layout.addWidget(self._save_all_btn)

        self._load_btn = QPushButton("加载消息")
        self._load_btn.clicked.connect(self._load_packets)
        action_layout.addWidget(self._load_btn)

        self._edit_send_btn = QPushButton("编辑并发送")
        self._edit_send_btn.clicked.connect(self._edit_and_send)
        action_layout.addWidget(self._edit_send_btn)

        self._new_send_btn = QPushButton("新建发送")
        self._new_send_btn.clicked.connect(self._new_send)
        action_layout.addWidget(self._new_send_btn)

        action_layout.addStretch()

        self._auto_scroll_check = QCheckBox("自动滚动")
        self._auto_scroll_check.setChecked(True)
        self._auto_scroll_check.stateChanged.connect(
            lambda state: setattr(self, '_auto_scroll', state == Qt.Checked)
        )
        action_layout.addWidget(self._auto_scroll_check)

        self._packet_count_label = QLabel("共 0 条消息")
        action_layout.addWidget(self._packet_count_label)

        layout.addLayout(action_layout)

    # ==================== 抓包控制 ====================

    def _start_capture(self):
        if not self._pid:
            QMessageBox.warning(self, "提示", "请先在顶部选择目标窗口")
            return
        if not self._sniffer.is_available:
            QMessageBox.warning(
                self, "依赖缺失",
                "网络抓包需要安装 scapy 和 psutil：\n"
                "pip install scapy psutil\n\n"
                "Windows还需安装 Npcap: https://npcap.com/"
            )
            return

        try:
            self._sniffer.start(
                self._pid,
                self._bridge.packet_received.emit,
                self._bridge.error_occurred.emit,
            )
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(True)
            mode = self._sniffer.capture_mode
            self._pid_label.setText(f"目标进程PID: {self._pid} [抓包中] | 模式: {mode}")
        except Exception as e:
            QMessageBox.critical(self, "启动失败", f"启动抓包失败:\n{e}")

    def _stop_capture(self):
        self._sniffer.stop()
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        if self._pid:
            mode = self._sniffer.capture_mode
            self._pid_label.setText(f"目标进程PID: {self._pid} [已停止] | 模式: {mode}")

    def _clear_packets(self):
        self._packets.clear()
        self._filtered_packets.clear()
        self._packet_table.setRowCount(0)
        self._hex_view.clear()
        self._text_view.clear()
        self._update_count_label()

    # ==================== 数据包处理 ====================

    @Slot(object)
    def _on_packet_received(self, packet: NetworkPacket):
        self._packets.append(packet)

        if len(self._packets) > self._max_packets:
            self._packets = self._packets[-self._max_packets:]

        if self._match_filter(packet):
            self._filtered_packets.append(packet)
            self._add_packet_row(packet, len(self._filtered_packets))

        self._update_count_label()

    @Slot(str)
    def _on_sniffer_error(self, msg: str):
        self._stop_capture()
        QMessageBox.warning(self, "抓包错误", msg)

    def _match_filter(self, pkt: NetworkPacket) -> bool:
        proto = self._filter_protocol.currentText()
        if proto != "全部" and pkt.protocol != proto:
            return False

        direction = self._filter_direction.currentText()
        if direction != "全部" and pkt.direction != direction:
            return False

        if self._only_data_check.isChecked() and len(pkt.data) == 0:
            return False

        keyword = self._filter_keyword.text().strip()
        if keyword:
            kw_lower = keyword.lower()
            if kw_lower not in pkt.data_text.lower() and \
               kw_lower not in pkt.data_hex.lower():
                return False

        return True

    def _add_packet_row(self, pkt: NetworkPacket, index: int):
        row = self._packet_table.rowCount()
        self._packet_table.insertRow(row)

        bg_color = QColor(230, 255, 230) if pkt.direction == "SEND" else QColor(230, 230, 255)

        items = [
            str(index),
            pkt.time_str,
            pkt.direction,
            pkt.protocol,
            f"{pkt.src_ip}:{pkt.src_port}",
            f"{pkt.dst_ip}:{pkt.dst_port}",
            str(pkt.length),
        ]

        for col, text in enumerate(items):
            item = QTableWidgetItem(text)
            item.setBackground(bg_color)
            self._packet_table.setItem(row, col, item)

        if self._auto_scroll:
            self._packet_table.scrollToBottom()

    def _apply_filter(self):
        """重新应用过滤器"""
        self._filtered_packets = [p for p in self._packets if self._match_filter(p)]
        self._packet_table.setRowCount(0)
        for i, pkt in enumerate(self._filtered_packets, 1):
            self._add_packet_row(pkt, i)
        self._update_count_label()

    def _update_count_label(self):
        total = len(self._packets)
        shown = len(self._filtered_packets)
        if total == shown:
            self._packet_count_label.setText(f"共 {total} 条消息")
        else:
            self._packet_count_label.setText(f"显示 {shown}/{total} 条消息")

    def _on_packet_selected(self, row, col, prev_row, prev_col):
        if row < 0 or row >= len(self._filtered_packets):
            return
        pkt = self._filtered_packets[row]
        self._show_packet_detail(pkt)

    def _show_packet_detail(self, pkt: NetworkPacket):
        self._current_packet_data = pkt.data or b""

        # Hex视图：每行16字节
        if pkt.data:
            hex_lines = []
            for i in range(0, len(pkt.data), 16):
                chunk = pkt.data[i:i + 16]
                hex_part = ' '.join(f'{b:02X}' for b in chunk)
                ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
                hex_lines.append(f'{i:08X}  {hex_part:<48s}  {ascii_part}')
            self._hex_view.setPlainText('\n'.join(hex_lines))
        else:
            self._hex_view.setPlainText("(无数据)")

        # 文本视图
        info = (
            f"方向: {pkt.direction}\n"
            f"协议: {pkt.protocol}\n"
            f"源: {pkt.src_ip}:{pkt.src_port}\n"
            f"目标: {pkt.dst_ip}:{pkt.dst_port}\n"
            f"时间: {pkt.time_str}\n"
            f"标志: {pkt.flags}\n"
            f"序列号: {pkt.seq}  确认号: {pkt.ack}\n"
            f"数据长度: {pkt.length} bytes\n"
            f"{'─' * 50}\n"
        )
        if pkt.data:
            info += pkt.data_text
        else:
            info += "(无数据)"
        self._text_view.setPlainText(info)

        # 更新检视器范围
        self._inspector_offset_spin.setMaximum(max(0, len(self._current_packet_data) - 1))
        self._inspector_offset_spin.setValue(0)
        self._update_inspector(0)

        # 更新 protobuf 偏移范围
        self._pb_offset_spin.setMaximum(max(0, len(self._current_packet_data) - 1))
        self._pb_offset_spin.setValue(0)

        # 更新结构化分析
        self._update_struct_view()

    # ==================== 数值搜索 ====================

    def _search_value_in_packet(self):
        """在当前数据包中搜索指定数值的所有可能编码"""
        text = self._search_value_input.text().strip()
        if not text:
            return
        data = self._current_packet_data
        if not data:
            self._search_result_view.setPlainText("当前没有选中的数据包，请先点击一个数据包。")
            return

        try:
            value = float(text) if '.' in text else int(text)
        except ValueError:
            self._search_result_view.setPlainText(f"无法解析 '{text}' 为数值。")
            return

        results = []
        is_int = isinstance(value, int)
        int_val = int(value)

        # 搜索策略列表：(描述, 字节数, pack格式)
        encodings = []
        if is_int:
            if -128 <= int_val <= 255:
                encodings.append(("uint8", 1, 'B', int_val & 0xFF))
                encodings.append(("int8", 1, 'b', int_val if -128 <= int_val <= 127 else None))
            if -32768 <= int_val <= 65535:
                encodings.append(("uint16 小端", 2, '<H', int_val & 0xFFFF))
                encodings.append(("uint16 大端", 2, '>H', int_val & 0xFFFF))
                encodings.append(("int16 小端", 2, '<h', int_val if -32768 <= int_val <= 32767 else None))
                encodings.append(("int16 大端", 2, '>h', int_val if -32768 <= int_val <= 32767 else None))
            if -2147483648 <= int_val <= 4294967295:
                encodings.append(("uint32 小端", 4, '<I', int_val & 0xFFFFFFFF))
                encodings.append(("uint32 大端", 4, '>I', int_val & 0xFFFFFFFF))
                encodings.append(("int32 小端", 4, '<i', int_val if -2147483648 <= int_val <= 2147483647 else None))
                encodings.append(("int32 大端", 4, '>i', int_val if -2147483648 <= int_val <= 2147483647 else None))

        # float 搜索
        try:
            encodings.append(("float32 小端", 4, '<f', float(value)))
            encodings.append(("float32 大端", 4, '>f', float(value)))
        except (ValueError, OverflowError):
            pass

        # 在数据中逐一搜索
        for desc, size, fmt, val in encodings:
            if val is None:
                continue
            try:
                needle = struct.pack(fmt, val)
            except (struct.error, OverflowError):
                continue
            offset = 0
            while offset <= len(data) - size:
                pos = data.find(needle, offset)
                if pos == -1:
                    break
                hex_str = ' '.join(f'{b:02X}' for b in needle)
                ctx_start = max(0, pos - 4)
                ctx_end = min(len(data), pos + size + 4)
                ctx_hex = ' '.join(
                    f'[{b:02X}]' if pos <= i < pos + size else f'{b:02X}'
                    for i, b in enumerate(data[ctx_start:ctx_end], ctx_start)
                )
                results.append(
                    f"  ✅ 偏移 0x{pos:04X} ({pos:>4d})  |  {desc:<14s}  |  "
                    f"字节: {hex_str}  |  上下文: {ctx_hex}"
                )
                offset = pos + 1

        # Protobuf varint 搜索
        if is_int and 0 <= int_val < (1 << 63):
            varint_bytes = self._encode_varint(int_val)
            needle = bytes(varint_bytes)
            offset = 0
            while offset <= len(data) - len(needle):
                pos = data.find(needle, offset)
                if pos == -1:
                    break
                hex_str = ' '.join(f'{b:02X}' for b in needle)
                ctx_start = max(0, pos - 4)
                ctx_end = min(len(data), pos + len(needle) + 4)
                ctx_hex = ' '.join(
                    f'[{b:02X}]' if pos <= i < pos + len(needle) else f'{b:02X}'
                    for i, b in enumerate(data[ctx_start:ctx_end], ctx_start)
                )
                results.append(
                    f"  ✅ 偏移 0x{pos:04X} ({pos:>4d})  |  {'varint':<14s}  |  "
                    f"字节: {hex_str}  |  上下文: {ctx_hex}"
                )
                offset = pos + 1

            # zigzag varint (protobuf sint32/sint64)
            zigzag_val = (int_val << 1) ^ (int_val >> 63) if int_val < 0 else (int_val << 1)
            if zigzag_val != int_val:
                zz_bytes = self._encode_varint(zigzag_val)
                needle = bytes(zz_bytes)
                offset = 0
                while offset <= len(data) - len(needle):
                    pos = data.find(needle, offset)
                    if pos == -1:
                        break
                    hex_str = ' '.join(f'{b:02X}' for b in needle)
                    ctx_start = max(0, pos - 4)
                    ctx_end = min(len(data), pos + len(needle) + 4)
                    ctx_hex = ' '.join(
                        f'[{b:02X}]' if pos <= i < pos + len(needle) else f'{b:02X}'
                        for i, b in enumerate(data[ctx_start:ctx_end], ctx_start)
                    )
                    results.append(
                        f"  ✅ 偏移 0x{pos:04X} ({pos:>4d})  |  {'zigzag varint':<14s}  |  "
                        f"字节: {hex_str}  |  上下文: {ctx_hex}"
                    )
                    offset = pos + 1

        # XOR 单字节密钥搜索 (尝试 0x01-0xFF 的 XOR key)
        if is_int and -32768 <= int_val <= 65535:
            for xor_key in range(1, 256):
                for desc_suffix, size, fmt, val in [
                    ("LE", 2, '<H', int_val & 0xFFFF),
                    ("BE", 2, '>H', int_val & 0xFFFF),
                ]:
                    try:
                        raw_needle = struct.pack(fmt, val)
                    except (struct.error, OverflowError):
                        continue
                    xored_needle = bytes(b ^ xor_key for b in raw_needle)
                    pos = data.find(xored_needle)
                    if pos != -1:
                        hex_str = ' '.join(f'{b:02X}' for b in xored_needle)
                        results.append(
                            f"  🔑 偏移 0x{pos:04X} ({pos:>4d})  |  "
                            f"{'XOR uint16 ' + desc_suffix:<14s}  |  "
                            f"XOR Key=0x{xor_key:02X}  |  字节: {hex_str}"
                        )

        # 搜索文本形式
        text_needle = str(text).encode('ascii')
        offset = 0
        while offset <= len(data) - len(text_needle):
            pos = data.find(text_needle, offset)
            if pos == -1:
                break
            hex_str = ' '.join(f'{b:02X}' for b in text_needle)
            results.append(
                f"  ✅ 偏移 0x{pos:04X} ({pos:>4d})  |  {'ASCII文本':<14s}  |  "
                f"字节: {hex_str}  |  文本: \"{text}\""
            )
            offset = pos + 1

        # 输出结果
        header = f"在 {len(data)} 字节数据中搜索数值 {text}:\n{'═' * 70}\n"
        if results:
            output = header + f"找到 {len(results)} 处匹配：\n\n" + '\n'.join(results)
        else:
            output = header + "未找到任何匹配。\n\n可能原因：\n" \
                     "  · 数据已加密或压缩\n" \
                     "  · 使用了复杂加密（多字节密钥/AES等）\n" \
                     "  · 该数值不在此数据包中\n" \
                     "  · 数据经过压缩（zlib/lz4等）"
        self._search_result_view.setPlainText(output)

    @staticmethod
    def _encode_varint(value: int) -> list:
        """编码一个整数为 protobuf varint 字节序列"""
        result = []
        while value > 0x7F:
            result.append((value & 0x7F) | 0x80)
            value >>= 7
        result.append(value & 0x7F)
        return result

    # ==================== 数据检视器 ====================

    def _update_inspector(self, offset: int = 0):
        """更新数据检视器：在指定偏移量处以各种类型解读数据"""
        data = self._current_packet_data
        self._inspector_table.setRowCount(0)
        if not data or offset < 0 or offset >= len(data):
            return

        remaining = len(data) - offset
        rows = []

        # uint8 / int8
        if remaining >= 1:
            v = data[offset]
            rows.append(("uint8", str(v), f"{v:02X}"))
            rows.append(("int8", str(struct.unpack_from('b', data, offset)[0]), f"{v:02X}"))

        # 16-bit
        if remaining >= 2:
            raw = data[offset:offset+2]
            hex_str = ' '.join(f'{b:02X}' for b in raw)
            rows.append(("uint16 小端", str(struct.unpack_from('<H', data, offset)[0]), hex_str))
            rows.append(("uint16 大端", str(struct.unpack_from('>H', data, offset)[0]), hex_str))
            rows.append(("int16 小端", str(struct.unpack_from('<h', data, offset)[0]), hex_str))
            rows.append(("int16 大端", str(struct.unpack_from('>h', data, offset)[0]), hex_str))

        # 32-bit
        if remaining >= 4:
            raw = data[offset:offset+4]
            hex_str = ' '.join(f'{b:02X}' for b in raw)
            rows.append(("uint32 小端", str(struct.unpack_from('<I', data, offset)[0]), hex_str))
            rows.append(("uint32 大端", str(struct.unpack_from('>I', data, offset)[0]), hex_str))
            rows.append(("int32 小端", str(struct.unpack_from('<i', data, offset)[0]), hex_str))
            rows.append(("int32 大端", str(struct.unpack_from('>i', data, offset)[0]), hex_str))
            fle = struct.unpack_from('<f', data, offset)[0]
            fbe = struct.unpack_from('>f', data, offset)[0]
            rows.append(("float32 小端", f"{fle:.6g}", hex_str))
            rows.append(("float32 大端", f"{fbe:.6g}", hex_str))

        # 64-bit
        if remaining >= 8:
            raw = data[offset:offset+8]
            hex_str = ' '.join(f'{b:02X}' for b in raw)
            rows.append(("int64 小端", str(struct.unpack_from('<q', data, offset)[0]), hex_str))
            rows.append(("int64 大端", str(struct.unpack_from('>q', data, offset)[0]), hex_str))
            dle = struct.unpack_from('<d', data, offset)[0]
            dbe = struct.unpack_from('>d', data, offset)[0]
            rows.append(("double 小端", f"{dle:.6g}", hex_str))
            rows.append(("double 大端", f"{dbe:.6g}", hex_str))

        # ASCII string preview
        str_bytes = []
        for i in range(offset, min(offset + 64, len(data))):
            if 32 <= data[i] < 127:
                str_bytes.append(chr(data[i]))
            else:
                break
        if str_bytes:
            rows.append(("ASCII字符串", ''.join(str_bytes), ""))

        self._inspector_table.setRowCount(len(rows))
        for r, (dtype, val, hx) in enumerate(rows):
            self._inspector_table.setItem(r, 0, QTableWidgetItem(dtype))
            self._inspector_table.setItem(r, 1, QTableWidgetItem(val))
            self._inspector_table.setItem(r, 2, QTableWidgetItem(hx))

    # ==================== 结构化分析 ====================

    def _update_struct_view(self):
        """逐字节显示所有可能的 int16/int32/float 值"""
        data = self._current_packet_data
        self._struct_table.setRowCount(0)
        if not data:
            return

        big_endian = self._struct_endian.currentIndex() == 1
        prefix = '>' if big_endian else '<'

        row_count = len(data)
        self._struct_table.setRowCount(row_count)

        for i in range(row_count):
            remaining = len(data) - i

            # 偏移
            self._struct_table.setItem(i, 0, QTableWidgetItem(f"0x{i:04X}"))

            # Hex (当前字节)
            self._struct_table.setItem(i, 1, QTableWidgetItem(f"{data[i]:02X}"))

            # uint8
            self._struct_table.setItem(i, 2, QTableWidgetItem(str(data[i])))

            # int16
            if remaining >= 2:
                val = struct.unpack_from(f'{prefix}h', data, i)[0]
                self._struct_table.setItem(i, 3, QTableWidgetItem(str(val)))
            else:
                self._struct_table.setItem(i, 3, QTableWidgetItem("-"))

            # int32
            if remaining >= 4:
                val = struct.unpack_from(f'{prefix}i', data, i)[0]
                self._struct_table.setItem(i, 4, QTableWidgetItem(str(val)))
            else:
                self._struct_table.setItem(i, 4, QTableWidgetItem("-"))

            # float32
            if remaining >= 4:
                val = struct.unpack_from(f'{prefix}f', data, i)[0]
                self._struct_table.setItem(i, 5, QTableWidgetItem(f"{val:.4g}"))
            else:
                self._struct_table.setItem(i, 5, QTableWidgetItem("-"))

    # ==================== Protobuf 裸解析 ====================

    @staticmethod
    def _decode_varint(data: bytes, pos: int):
        """解码 protobuf varint，返回 (value, new_pos) 或 None"""
        result = 0
        shift = 0
        start = pos
        while pos < len(data):
            b = data[pos]
            result |= (b & 0x7F) << shift
            pos += 1
            shift += 7
            if not (b & 0x80):
                return result, pos
            if shift > 63:
                return None  # 溢出
        return None  # 未终止

    def _decode_protobuf(self):
        """尝试将当前数据包作为 protobuf 裸解析"""
        data = self._current_packet_data
        if not data:
            self._protobuf_view.setPlainText("当前没有选中的数据包。")
            return

        start_offset = self._pb_offset_spin.value()
        data = data[start_offset:]
        if not data:
            self._protobuf_view.setPlainText("偏移量超出数据范围。")
            return

        lines = [f"Protobuf 裸解析 (数据长度: {len(data)} 字节, 起始偏移: {start_offset})",
                 "═" * 70, ""]

        fields = self._parse_protobuf_fields(data, indent=0, max_depth=5)
        if fields:
            for line in fields:
                lines.append(line)
            lines.append("")
            lines.append(f"共解析出 {sum(1 for l in fields if l.strip().startswith('Field'))} 个字段")
        else:
            lines.append("❌ 无法按 Protobuf 格式解析。")
            lines.append("")
            lines.append("可能原因：")
            lines.append("  · 数据不是 Protobuf 格式")
            lines.append("  · 数据已加密或压缩")
            lines.append("  · 需要调整起始偏移量跳过包头")

        self._protobuf_view.setPlainText('\n'.join(lines))

    def _parse_protobuf_fields(self, data: bytes, indent: int = 0, max_depth: int = 5) -> list:
        """递归解析 protobuf 字段，返回文本行列表"""
        if max_depth <= 0 or not data:
            return []

        lines = []
        pos = 0
        prefix = "  " * indent
        field_count = 0
        max_fields = 200  # 防止无限循环

        while pos < len(data) and field_count < max_fields:
            # 读取 tag (varint)
            ret = self._decode_varint(data, pos)
            if ret is None:
                if field_count == 0:
                    return []  # 第一个字段就解不出，说明不是 protobuf
                lines.append(f"{prefix}  (剩余 {len(data) - pos} 字节未解析)")
                break

            tag, pos = ret
            field_number = tag >> 3
            wire_type = tag & 0x07

            # 合理性检查
            if field_number <= 0 or field_number > 536870911:
                if field_count == 0:
                    return []
                lines.append(f"{prefix}  (偏移 0x{pos:04X} 处字段号异常: {field_number}，停止解析)")
                break

            if wire_type == 0:  # Varint
                ret = self._decode_varint(data, pos)
                if ret is None:
                    lines.append(f"{prefix}  Field {field_number}: varint 未完成")
                    break
                value, pos = ret
                # 尝试各种解读
                sint = (value >> 1) ^ -(value & 1)  # zigzag decode
                extra = f"  (sint={sint})" if sint != value else ""
                lines.append(f"{prefix}Field {field_number:>3d}  [varint]  = {value}{extra}")

            elif wire_type == 1:  # 64-bit
                if pos + 8 > len(data):
                    lines.append(f"{prefix}  Field {field_number}: 64-bit 数据不足")
                    break
                raw = data[pos:pos+8]
                pos += 8
                i64 = struct.unpack_from('<q', raw, 0)[0]
                f64 = struct.unpack_from('<d', raw, 0)[0]
                hex_str = ' '.join(f'{b:02X}' for b in raw)
                lines.append(f"{prefix}Field {field_number:>3d}  [64-bit]  = {i64}  "
                             f"(double: {f64:.6g})  [{hex_str}]")

            elif wire_type == 2:  # Length-delimited
                ret = self._decode_varint(data, pos)
                if ret is None:
                    lines.append(f"{prefix}  Field {field_number}: 长度 varint 未完成")
                    break
                length, pos = ret
                if length < 0 or pos + length > len(data):
                    if field_count == 0:
                        return []
                    lines.append(f"{prefix}  Field {field_number}: 长度 {length} 超出范围")
                    break
                payload = data[pos:pos+length]
                pos += length

                # 尝试解读为字符串
                try:
                    text = payload.decode('utf-8')
                    if all(32 <= ord(c) < 127 or c in '\n\r\t' for c in text) and text:
                        lines.append(f"{prefix}Field {field_number:>3d}  [string]  = \"{text}\"  "
                                     f"({length} bytes)")
                        field_count += 1
                        continue
                except (UnicodeDecodeError, ValueError):
                    pass

                # 尝试递归解析为嵌套 protobuf
                nested = self._parse_protobuf_fields(payload, indent + 1, max_depth - 1)
                if len(nested) >= 1:
                    lines.append(f"{prefix}Field {field_number:>3d}  [message] ({length} bytes) {{")
                    lines.extend(nested)
                    lines.append(f"{prefix}}}")
                else:
                    # 当做原始字节
                    hex_str = ' '.join(f'{b:02X}' for b in payload[:32])
                    suffix = "..." if length > 32 else ""
                    lines.append(f"{prefix}Field {field_number:>3d}  [bytes]   "
                                 f"({length} bytes)  {hex_str}{suffix}")

            elif wire_type == 5:  # 32-bit
                if pos + 4 > len(data):
                    lines.append(f"{prefix}  Field {field_number}: 32-bit 数据不足")
                    break
                raw = data[pos:pos+4]
                pos += 4
                i32 = struct.unpack_from('<i', raw, 0)[0]
                f32 = struct.unpack_from('<f', raw, 0)[0]
                hex_str = ' '.join(f'{b:02X}' for b in raw)
                lines.append(f"{prefix}Field {field_number:>3d}  [32-bit]  = {i32}  "
                             f"(float: {f32:.6g})  [{hex_str}]")

            else:
                # wire_type 3,4 (deprecated) 或未知
                if field_count == 0:
                    return []
                lines.append(f"{prefix}  Field {field_number}: 未知 wire_type={wire_type}")
                break

            field_count += 1

        if field_count == 0:
            return []
        return lines

    # ==================== 多包对比 ====================

    def _compare_selected_packets(self):
        """对比选中的多个数据包，找出差异字节"""
        selected = self._get_selected_packets()
        if len(selected) < 2:
            self._compare_view.setPlainText("请在上方列表中选择至少2条数据包进行对比。\n"
                                            "(按住 Ctrl 或 Shift 多选)")
            return
        if len(selected) > 10:
            self._compare_view.setPlainText("最多支持同时对比10条数据包。")
            return

        packets_data = []
        for pkt in selected:
            if pkt.data:
                packets_data.append(pkt.data)
            else:
                packets_data.append(b"")

        max_len = max(len(d) for d in packets_data)
        min_len = min(len(d) for d in packets_data)

        lines = [f"多包对比：{len(selected)} 条数据包",
                 f"数据长度: {', '.join(str(len(d)) for d in packets_data)} 字节",
                 "═" * 70, ""]

        # 对比表头
        header = f"{'偏移':>8s}  "
        for i in range(len(packets_data)):
            header += f"{'包' + str(i+1):>6s}  "
        header += "  状态"
        lines.append(header)
        lines.append("─" * (14 + 8 * len(packets_data) + 10))

        diff_offsets = []
        same_offsets = []

        for offset in range(max_len):
            values = []
            for d in packets_data:
                if offset < len(d):
                    values.append(d[offset])
                else:
                    values.append(None)

            valid_values = [v for v in values if v is not None]
            all_same = len(set(valid_values)) <= 1

            row = f"0x{offset:04X}    "
            for v in values:
                if v is not None:
                    row += f"  {v:02X}    "
                else:
                    row += f"  --    "

            if all_same:
                row += "  固定"
                same_offsets.append(offset)
            else:
                row += "  ★变化"
                diff_offsets.append(offset)

            lines.append(row)

        lines.append("")
        lines.append("═" * 70)
        lines.append(f"变化字节: {len(diff_offsets)} 处  |  固定字节: {len(same_offsets)} 处")

        if diff_offsets:
            lines.append("")
            lines.append("变化位置汇总:")
            # 将连续偏移合并为范围显示
            ranges = []
            start = diff_offsets[0]
            end = start
            for off in diff_offsets[1:]:
                if off == end + 1:
                    end = off
                else:
                    ranges.append((start, end))
                    start = off
                    end = off
            ranges.append((start, end))

            for s, e in ranges:
                if s == e:
                    vals_str = "  ".join(
                        f"包{i+1}={d[s]:02X}" if s < len(d) else f"包{i+1}=--"
                        for i, d in enumerate(packets_data)
                    )
                    lines.append(f"  偏移 0x{s:04X}: {vals_str}")
                else:
                    lines.append(f"  偏移 0x{s:04X} - 0x{e:04X} ({e - s + 1} 字节)")
                    for off in range(s, min(e + 1, s + 8)):
                        vals_str = "  ".join(
                            f"包{i+1}={d[off]:02X}" if off < len(d) else f"包{i+1}=--"
                            for i, d in enumerate(packets_data)
                        )
                        lines.append(f"    0x{off:04X}: {vals_str}")
                    if e - s + 1 > 8:
                        lines.append(f"    ... 省略 {e - s + 1 - 8} 字节")

            # 尝试解读变化字节
            lines.append("")
            lines.append("变化字节数值解读:")
            for i, d in enumerate(packets_data):
                lines.append(f"  包{i+1}:")
                for s, e in ranges:
                    chunk = d[s:e+1] if s < len(d) else b""
                    if len(chunk) >= 2:
                        le16 = struct.unpack_from('<h', chunk, 0)[0] if len(chunk) >= 2 else "?"
                        be16 = struct.unpack_from('>h', chunk, 0)[0] if len(chunk) >= 2 else "?"
                        le32 = struct.unpack_from('<i', chunk, 0)[0] if len(chunk) >= 4 else "?"
                        be32 = struct.unpack_from('>i', chunk, 0)[0] if len(chunk) >= 4 else "?"
                        lines.append(f"    偏移 0x{s:04X}: int16LE={le16}  int16BE={be16}  "
                                     f"int32LE={le32}  int32BE={be32}")

        self._compare_view.setPlainText('\n'.join(lines))

    # ==================== 右键菜单 ====================

    def _show_context_menu(self, pos):
        menu = QMenu(self)

        copy_hex_action = menu.addAction("复制数据 (Hex)")
        copy_text_action = menu.addAction("复制数据 (文本)")
        menu.addSeparator()
        save_action = menu.addAction("保存选中消息")
        menu.addSeparator()
        edit_action = menu.addAction("编辑并发送")
        resend_action = menu.addAction("原样重发")

        action = menu.exec_(self._packet_table.mapToGlobal(pos))

        if action == copy_hex_action:
            self._copy_selected_hex()
        elif action == copy_text_action:
            self._copy_selected_text()
        elif action == save_action:
            self._save_selected()
        elif action == edit_action:
            self._edit_and_send()
        elif action == resend_action:
            self._resend_selected()

    def _get_selected_packets(self) -> List[NetworkPacket]:
        rows = set()
        for item in self._packet_table.selectedItems():
            rows.add(item.row())
        return [self._filtered_packets[r] for r in sorted(rows)
                if r < len(self._filtered_packets)]

    def _copy_selected_hex(self):
        pkts = self._get_selected_packets()
        if pkts:
            from PySide6.QtWidgets import QApplication
            text = '\n'.join(p.data_hex for p in pkts)
            QApplication.clipboard().setText(text)

    def _copy_selected_text(self):
        pkts = self._get_selected_packets()
        if pkts:
            from PySide6.QtWidgets import QApplication
            text = '\n'.join(p.data_text for p in pkts)
            QApplication.clipboard().setText(text)

    # ==================== 保存/加载 ====================

    def _save_selected(self):
        pkts = self._get_selected_packets()
        if not pkts:
            QMessageBox.information(self, "提示", "请先选择要保存的消息")
            return
        self._do_save(pkts)

    def _save_all(self):
        if not self._filtered_packets:
            QMessageBox.information(self, "提示", "没有可保存的消息")
            return
        self._do_save(self._filtered_packets)

    def _do_save(self, pkts: List[NetworkPacket]):
        filepath, _ = QFileDialog.getSaveFileName(
            self, "保存网络消息", "", "JSON files (*.json);;All files (*)"
        )
        if filepath:
            try:
                save_packets(pkts, filepath)
                QMessageBox.information(
                    self, "成功", f"已保存 {len(pkts)} 条消息到:\n{filepath}"
                )
            except Exception as e:
                QMessageBox.critical(self, "保存失败", str(e))

    def _load_packets(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "加载网络消息", "", "JSON files (*.json);;All files (*)"
        )
        if filepath:
            try:
                loaded = load_packets(filepath)
                self._packets.extend(loaded)
                self._apply_filter()
                QMessageBox.information(self, "成功", f"已加载 {len(loaded)} 条消息")
            except Exception as e:
                QMessageBox.critical(self, "加载失败", str(e))

    # ==================== 编辑/发送 ====================

    def _edit_and_send(self):
        pkts = self._get_selected_packets()
        pkt = pkts[0] if pkts else None
        dlg = PacketEditDialog(pkt, self)
        dlg.exec()

    def _new_send(self):
        dlg = PacketEditDialog(None, self)
        dlg.exec()

    def _resend_selected(self):
        pkts = self._get_selected_packets()
        if not pkts:
            return
        pkt = pkts[0]
        if pkt.direction == "SEND":
            ok = NetworkSniffer.send_socket_packet(
                pkt.protocol, pkt.dst_ip, pkt.dst_port, pkt.data
            )
        else:
            ok = NetworkSniffer.send_socket_packet(
                pkt.protocol, pkt.src_ip, pkt.src_port, pkt.data
            )

        if ok:
            QMessageBox.information(self, "成功", "消息已重发")
        else:
            QMessageBox.warning(self, "失败", "消息重发失败")

    def cleanup(self):
        """清理资源"""
        if self._sniffer.is_running:
            self._sniffer.stop()
