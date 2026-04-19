"""
网络消息截取模块
抓取目标进程的网络收发消息，支持保存、加载和发送

优先使用 scapy + Npcap（L2），若 Npcap 不可用则自动降级到
Windows 原生 raw socket + SIO_RCVALL（无需第三方驱动）。
"""

import json
import os
import select
import socket
import struct
import time
import threading
from dataclasses import dataclass
from typing import Optional, List, Callable, Set
from datetime import datetime

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    from scapy.all import sniff, send as scapy_send, conf
    from scapy.layers.inet import IP, TCP, UDP
    from scapy.packet import Raw
    SCAPY_AVAILABLE = True
    _L2_AVAILABLE = False
    try:
        _test_sock = conf.L2socket()
        _test_sock.close()
        _L2_AVAILABLE = True
    except Exception:
        _L2_AVAILABLE = False
except ImportError:
    SCAPY_AVAILABLE = False
    _L2_AVAILABLE = False


@dataclass
class NetworkPacket:
    """网络数据包"""
    timestamp: float
    direction: str        # "SEND" / "RECV"
    protocol: str         # "TCP" / "UDP"
    src_ip: str
    src_port: int
    dst_ip: str
    dst_port: int
    data: bytes = b""
    flags: str = ""
    seq: int = 0
    ack: int = 0

    @property
    def data_hex(self) -> str:
        return ' '.join(f'{b:02X}' for b in self.data) if self.data else ""

    @property
    def data_text(self) -> str:
        if not self.data:
            return ""
        try:
            return self.data.decode('utf-8', errors='replace')
        except Exception:
            return repr(self.data)

    @property
    def time_str(self) -> str:
        return datetime.fromtimestamp(self.timestamp).strftime('%H:%M:%S.%f')[:-3]

    @property
    def length(self) -> int:
        return len(self.data)

    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp,
            'time_str': self.time_str,
            'direction': self.direction,
            'protocol': self.protocol,
            'src_ip': self.src_ip,
            'src_port': self.src_port,
            'dst_ip': self.dst_ip,
            'dst_port': self.dst_port,
            'data_hex': self.data.hex() if self.data else "",
            'flags': self.flags,
            'seq': self.seq,
            'ack': self.ack,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'NetworkPacket':
        data = bytes.fromhex(d.get('data_hex', ''))
        return cls(
            timestamp=d['timestamp'],
            direction=d['direction'],
            protocol=d['protocol'],
            src_ip=d['src_ip'],
            src_port=d['src_port'],
            dst_ip=d['dst_ip'],
            dst_port=d['dst_port'],
            data=data,
            flags=d.get('flags', ''),
            seq=d.get('seq', 0),
            ack=d.get('ack', 0),
        )


class NetworkSniffer:
    """网络嗅探器，基于进程PID过滤网络流量"""

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._pid: Optional[int] = None
        self._callback: Optional[Callable[[NetworkPacket], None]] = None
        self._error_callback: Optional[Callable[[str], None]] = None
        self._local_ports: Set[int] = set()
        self._local_ips: Set[str] = set()
        self._lock = threading.Lock()
        self._conn_refresh_interval = 2.0
        self._last_conn_refresh = 0.0

        self._init_local_ips()

    def _init_local_ips(self):
        """初始化本机IP地址集合"""
        self._local_ips = {'127.0.0.1', '::1'}
        try:
            hostname = socket.gethostname()
            for addr_info in socket.getaddrinfo(hostname, None):
                self._local_ips.add(addr_info[4][0])
        except Exception:
            pass
        if PSUTIL_AVAILABLE:
            try:
                for _name, addrs in psutil.net_if_addrs().items():
                    for addr in addrs:
                        if addr.family in (socket.AF_INET, socket.AF_INET6):
                            self._local_ips.add(addr.address)
            except Exception:
                pass

    @property
    def is_available(self) -> bool:
        # psutil 是必须的（用于获取进程端口）
        # 抓包引擎：Npcap > Windows raw socket，至少需要一种可用
        return PSUTIL_AVAILABLE and (SCAPY_AVAILABLE or os.name == 'nt')

    @property
    def is_full_capture(self) -> bool:
        """是否支持完整双向抓包（需要 Npcap）"""
        return _L2_AVAILABLE

    @property
    def capture_mode(self) -> str:
        """当前抓包模式描述"""
        if _L2_AVAILABLE:
            return "完整模式 (Npcap)"
        elif os.name == 'nt':
            return "有限模式 (仅发送方向)"
        return "不可用"

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, pid: int, callback: Callable[[NetworkPacket], None],
              error_callback: Optional[Callable[[str], None]] = None):
        """开始抓包"""
        if not self.is_available:
            raise RuntimeError("scapy 或 psutil 未安装，无法启动网络抓包")
        if self._running:
            self.stop()

        self._pid = pid
        self._callback = callback
        self._error_callback = error_callback
        self._running = True
        self._update_connections()

        self._thread = threading.Thread(target=self._sniff_thread, daemon=True)
        self._thread.start()

    def stop(self):
        """停止抓包"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None

    def _update_connections(self):
        """更新目标进程的网络连接端口表"""
        if not PSUTIL_AVAILABLE or not self._pid:
            return

        now = time.time()
        if now - self._last_conn_refresh < self._conn_refresh_interval:
            return
        self._last_conn_refresh = now

        try:
            proc = psutil.Process(self._pid)
            connections = proc.net_connections()
            new_ports = set()
            for conn in connections:
                if conn.laddr:
                    new_ports.add(conn.laddr.port)
            with self._lock:
                self._local_ports = new_ports
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    def _sniff_thread(self):
        """抓包线程：优先 scapy+Npcap，否则用 Windows raw socket"""
        if _L2_AVAILABLE:
            self._sniff_scapy()
        else:
            self._sniff_raw_socket()

    # ---------- scapy (Npcap) 模式 ----------

    def _sniff_scapy(self):
        try:
            sniff(
                prn=self._process_scapy_packet,
                stop_filter=lambda _: not self._running,
                store=False,
            )
        except Exception as e:
            if self._running and self._error_callback:
                self._error_callback(f"抓包异常: {e}")

    def _process_scapy_packet(self, pkt):
        """处理 scapy 捕获的数据包"""
        if not self._running:
            return
        self._update_connections()
        if not pkt.haslayer(IP):
            return

        ip = pkt[IP]
        src_ip = ip.src
        dst_ip = ip.dst
        protocol = ""
        src_port = 0
        dst_port = 0
        flags = ""
        seq = 0
        ack_num = 0
        data = b""

        if pkt.haslayer(TCP):
            tcp = pkt[TCP]
            src_port = tcp.sport
            dst_port = tcp.dport
            protocol = "TCP"
            flags = str(tcp.flags)
            seq = tcp.seq
            ack_num = tcp.ack
        elif pkt.haslayer(UDP):
            udp = pkt[UDP]
            src_port = udp.sport
            dst_port = udp.dport
            protocol = "UDP"
        else:
            return

        self._dispatch_packet(protocol, src_ip, src_port, dst_ip, dst_port,
                              data if not pkt.haslayer(Raw) else bytes(pkt[Raw].load),
                              flags, seq, ack_num)

    # ---------- Windows raw socket 模式 ----------

    def _get_bind_ips(self) -> List[str]:
        """获取所有本机 IPv4 地址（用于绑定 raw socket）"""
        ips = set()
        if PSUTIL_AVAILABLE:
            try:
                for _name, addrs in psutil.net_if_addrs().items():
                    for a in addrs:
                        if a.family == socket.AF_INET and not a.address.startswith('127.'):
                            ips.add(a.address)
            except Exception:
                pass
        if not ips:
            try:
                hostname = socket.gethostname()
                for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                    addr = info[4][0]
                    if not addr.startswith('127.'):
                        ips.add(addr)
            except Exception:
                pass
        return list(ips)

    def _sniff_raw_socket(self):
        """使用 Windows 原生 raw socket 抓双向流量"""
        raw_sockets: list = []
        try:
            bind_ips = self._get_bind_ips()
            if not bind_ips:
                if self._error_callback:
                    self._error_callback("无法获取本机网络接口地址")
                return

            for ip in bind_ips:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
                    s.bind((ip, 0))
                    # 接收所有 IP 包（包含 IP 头）
                    s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
                    # 开启混杂模式 —— 接收本接口上所有进出流量
                    s.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
                    s.setblocking(False)
                    raw_sockets.append(s)
                except OSError:
                    # 某些虚拟/VPN 接口可能失败，跳过
                    pass

            if not raw_sockets:
                if self._error_callback:
                    self._error_callback(
                        "无法创建原始套接字，请以管理员权限运行程序"
                    )
                return

            while self._running:
                # 用 select 等待数据，超时 0.5s 以便检查 _running
                readable, _, _ = select.select(raw_sockets, [], [], 0.5)
                for s in readable:
                    if not self._running:
                        break
                    try:
                        raw_data = s.recv(65535)
                        if raw_data:
                            self._parse_raw_ip(raw_data)
                    except (BlockingIOError, OSError):
                        continue

        except Exception as e:
            if self._running and self._error_callback:
                self._error_callback(f"抓包异常: {e}")
        finally:
            for s in raw_sockets:
                try:
                    s.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
                    s.close()
                except Exception:
                    pass

    def _parse_raw_ip(self, raw: bytes):
        """从原始 IP 包中解析 TCP/UDP 信息"""
        if len(raw) < 20:
            return

        # IP 头
        ihl = (raw[0] & 0x0F) * 4
        if len(raw) < ihl:
            return
        proto = raw[9]
        src_ip = socket.inet_ntoa(raw[12:16])
        dst_ip = socket.inet_ntoa(raw[16:20])

        ip_total_len = struct.unpack('!H', raw[2:4])[0]
        payload = raw[ihl:ip_total_len] if ip_total_len <= len(raw) else raw[ihl:]

        protocol = ""
        src_port = 0
        dst_port = 0
        flags = ""
        seq = 0
        ack_num = 0
        data = b""

        if proto == 6 and len(payload) >= 20:
            # TCP
            protocol = "TCP"
            src_port = struct.unpack('!H', payload[0:2])[0]
            dst_port = struct.unpack('!H', payload[2:4])[0]
            seq = struct.unpack('!I', payload[4:8])[0]
            ack_num = struct.unpack('!I', payload[8:12])[0]
            tcp_header_len = ((payload[12] >> 4) & 0x0F) * 4
            flag_byte = payload[13]
            flag_parts = []
            if flag_byte & 0x01: flag_parts.append('F')
            if flag_byte & 0x02: flag_parts.append('S')
            if flag_byte & 0x04: flag_parts.append('R')
            if flag_byte & 0x08: flag_parts.append('P')
            if flag_byte & 0x10: flag_parts.append('A')
            if flag_byte & 0x20: flag_parts.append('U')
            flags = ''.join(flag_parts)
            data = payload[tcp_header_len:] if tcp_header_len <= len(payload) else b""

        elif proto == 17 and len(payload) >= 8:
            # UDP
            protocol = "UDP"
            src_port = struct.unpack('!H', payload[0:2])[0]
            dst_port = struct.unpack('!H', payload[2:4])[0]
            udp_len = struct.unpack('!H', payload[4:6])[0]
            data = payload[8:udp_len] if udp_len <= len(payload) else payload[8:]
        else:
            return

        self._update_connections()
        self._dispatch_packet(protocol, src_ip, src_port, dst_ip, dst_port,
                              data, flags, seq, ack_num)

    # ---------- 公共派发 ----------

    def _dispatch_packet(self, protocol: str, src_ip: str, src_port: int,
                         dst_ip: str, dst_port: int, data: bytes,
                         flags: str, seq: int, ack_num: int):
        with self._lock:
            local_ports = self._local_ports.copy()

        if not local_ports:
            return

        direction = None
        if src_port in local_ports and src_ip in self._local_ips:
            direction = "SEND"
        elif dst_port in local_ports and dst_ip in self._local_ips:
            direction = "RECV"
        else:
            return

        packet = NetworkPacket(
            timestamp=time.time(),
            direction=direction,
            protocol=protocol,
            src_ip=src_ip,
            src_port=src_port,
            dst_ip=dst_ip,
            dst_port=dst_port,
            data=data,
            flags=flags,
            seq=seq,
            ack=ack_num,
        )

        if self._callback:
            self._callback(packet)

    @staticmethod
    def send_raw_packet(protocol: str, dst_ip: str, dst_port: int,
                        data: bytes, src_port: int = 0) -> bool:
        """使用 scapy 发送原始数据包（需要管理员权限）"""
        if not SCAPY_AVAILABLE:
            return False
        try:
            if protocol.upper() == "TCP":
                pkt = IP(dst=dst_ip) / TCP(dport=dst_port, sport=src_port or 12345, flags='PA') / Raw(load=data)
            elif protocol.upper() == "UDP":
                pkt = IP(dst=dst_ip) / UDP(dport=dst_port, sport=src_port or 12345) / Raw(load=data)
            else:
                return False
            scapy_send(pkt, verbose=False)
            return True
        except Exception:
            return False

    @staticmethod
    def send_socket_packet(protocol: str, dst_ip: str, dst_port: int,
                           data: bytes) -> bool:
        """通过标准 socket 发送数据包（无需管理员权限）"""
        try:
            if protocol.upper() == "TCP":
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(5)
                    s.connect((dst_ip, dst_port))
                    s.sendall(data)
                    return True
            elif protocol.upper() == "UDP":
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.sendto(data, (dst_ip, dst_port))
                    return True
        except Exception:
            return False
        return False


def save_packets(packets: List[NetworkPacket], filepath: str):
    """保存数据包列表到 JSON 文件"""
    data = [p.to_dict() for p in packets]
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_packets(filepath: str) -> List[NetworkPacket]:
    """从 JSON 文件加载数据包列表"""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return [NetworkPacket.from_dict(d) for d in data]
