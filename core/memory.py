"""
内存扫描模块
使用 Windows API 扫描目标进程内存，搜索/监控指定数值
类似 Cheat Engine 的内存扫描功能
"""

import ctypes
import ctypes.wintypes as wintypes
import struct
import threading
from dataclasses import dataclass, field
from typing import List, Optional, Callable

# Windows API 常量
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
PAGE_READWRITE = 0x04
PAGE_EXECUTE_READWRITE = 0x40
PAGE_READONLY = 0x02
PAGE_EXECUTE_READ = 0x20
PAGE_WRITECOPY = 0x08
PAGE_EXECUTE_WRITECOPY = 0x80

# 可读的内存保护标志
READABLE_PROTECTIONS = (
    PAGE_READWRITE, PAGE_EXECUTE_READWRITE,
    PAGE_READONLY, PAGE_EXECUTE_READ,
    PAGE_WRITECOPY, PAGE_EXECUTE_WRITECOPY,
)


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


kernel32 = ctypes.windll.kernel32

OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
OpenProcess.restype = wintypes.HANDLE

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL

ReadProcessMemory = kernel32.ReadProcessMemory
ReadProcessMemory.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p,
    ctypes.c_void_p, ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
ReadProcessMemory.restype = wintypes.BOOL

VirtualQueryEx = kernel32.VirtualQueryEx
VirtualQueryEx.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p,
    ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t,
]
VirtualQueryEx.restype = ctypes.c_size_t


# 数据类型定义
SCAN_TYPES = {
    "int8":    (1, 'b'),
    "uint8":   (1, 'B'),
    "int16":   (2, '<h'),
    "uint16":  (2, '<H'),
    "int32":   (4, '<i'),
    "uint32":  (4, '<I'),
    "int64":   (8, '<q'),
    "uint64":  (8, '<Q'),
    "float":   (4, '<f'),
    "double":  (8, '<d'),

    "int16_be":   (2, '>h'),
    "uint16_be":  (2, '>H'),
    "int32_be":   (4, '>i'),
    "uint32_be":  (4, '>I'),
    "float_be":   (4, '>f'),
}


@dataclass
class ScanResult:
    """一个扫描结果"""
    address: int
    value: float  # 当前值（统一转为 float 存储）
    data_type: str
    previous_values: List[float] = field(default_factory=list)

    @property
    def address_hex(self) -> str:
        return f"0x{self.address:016X}"


class MemoryScanner:
    """进程内存扫描器"""

    def __init__(self):
        self._pid: Optional[int] = None
        self._handle: Optional[int] = None
        self._results: List[ScanResult] = []
        self._scanning = False
        self._cancel_flag = False
        self._lock = threading.Lock()

    @property
    def is_scanning(self) -> bool:
        return self._scanning

    @property
    def results(self) -> List[ScanResult]:
        return self._results

    @property
    def result_count(self) -> int:
        return len(self._results)

    def attach(self, pid: int) -> bool:
        """附加到目标进程"""
        self.detach()
        handle = OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not handle:
            return False
        self._pid = pid
        self._handle = handle
        return True

    def detach(self):
        """断开"""
        if self._handle:
            CloseHandle(self._handle)
        self._handle = None
        self._pid = None
        self._results.clear()

    def cancel(self):
        """取消当前扫描"""
        self._cancel_flag = True

    def _get_readable_regions(self) -> list:
        """枚举进程中可读的内存区域"""
        regions = []
        if not self._handle:
            return regions

        mbi = MEMORY_BASIC_INFORMATION()
        mbi_size = ctypes.sizeof(mbi)
        address = 0

        # 仅扫描用户空间 (0 ~ 0x7FFFFFFFFFFF for 64-bit)
        max_address = 0x7FFFFFFFFFFF

        while address < max_address:
            result = VirtualQueryEx(
                self._handle, ctypes.c_void_p(address),
                ctypes.byref(mbi), mbi_size
            )
            if result == 0:
                break

            if (mbi.State == MEM_COMMIT and
                    mbi.Protect in READABLE_PROTECTIONS and
                    mbi.RegionSize > 0):
                regions.append((mbi.BaseAddress, mbi.RegionSize))

            address = mbi.BaseAddress + mbi.RegionSize
            if address <= mbi.BaseAddress:
                break

        return regions

    def _read_memory(self, address: int, size: int) -> Optional[bytes]:
        """读取进程内存"""
        if not self._handle:
            return None
        buf = ctypes.create_string_buffer(size)
        bytes_read = ctypes.c_size_t(0)
        ok = ReadProcessMemory(
            self._handle, ctypes.c_void_p(address),
            buf, size, ctypes.byref(bytes_read)
        )
        if ok and bytes_read.value == size:
            return buf.raw
        return None

    def read_value(self, address: int, data_type: str):
        """读取指定地址的值"""
        if data_type not in SCAN_TYPES:
            return None
        size, fmt = SCAN_TYPES[data_type]
        raw = self._read_memory(address, size)
        if raw is None:
            return None
        try:
            return struct.unpack(fmt, raw)[0]
        except struct.error:
            return None

    def first_scan(self, value, data_type: str,
                   progress_cb: Optional[Callable[[int, int], None]] = None) -> int:
        """
        首次扫描：在整个进程内存中搜索指定值
        progress_cb(scanned_regions, total_regions)
        返回找到的匹配数量
        """
        if not self._handle:
            return 0
        if data_type not in SCAN_TYPES:
            return 0

        self._scanning = True
        self._cancel_flag = False
        self._results.clear()

        size, fmt = SCAN_TYPES[data_type]

        try:
            needle = struct.pack(fmt, value)
        except (struct.error, OverflowError):
            self._scanning = False
            return 0

        regions = self._get_readable_regions()
        total = len(regions)

        CHUNK_SIZE = 1024 * 1024  # 1MB per read

        for idx, (base, region_size) in enumerate(regions):
            if self._cancel_flag:
                break

            if progress_cb and idx % 50 == 0:
                progress_cb(idx, total)

            offset = 0
            while offset < region_size:
                if self._cancel_flag:
                    break

                read_size = min(CHUNK_SIZE, region_size - offset)
                chunk = self._read_memory(base + offset, read_size)
                if chunk is None:
                    break

                # 在 chunk 中搜索 needle
                search_pos = 0
                while search_pos <= len(chunk) - size:
                    pos = chunk.find(needle, search_pos)
                    if pos == -1:
                        break

                    addr = base + offset + pos
                    val = struct.unpack(fmt, chunk[pos:pos + size])[0]
                    self._results.append(ScanResult(
                        address=addr,
                        value=float(val),
                        data_type=data_type,
                    ))

                    # 上限保护
                    if len(self._results) >= 5000000:
                        self._scanning = False
                        if progress_cb:
                            progress_cb(total, total)
                        return len(self._results)

                    search_pos = pos + 1

                offset += read_size

        self._scanning = False
        if progress_cb:
            progress_cb(total, total)
        return len(self._results)

    def next_scan(self, value, compare: str = "eq",
                  progress_cb: Optional[Callable[[int, int], None]] = None) -> int:
        """
        再次扫描：在上次结果中筛选
        compare: "eq"(等于), "neq"(不等于), "gt"(大于), "lt"(小于),
                 "changed"(变化了), "unchanged"(未变化)
        """
        if not self._handle:
            return 0

        self._scanning = True
        self._cancel_flag = False
        old_results = self._results
        new_results = []
        total = len(old_results)

        for idx, res in enumerate(old_results):
            if self._cancel_flag:
                break
            if progress_cb and idx % 10000 == 0:
                progress_cb(idx, total)

            current = self.read_value(res.address, res.data_type)
            if current is None:
                continue

            current_f = float(current)
            match = False

            if compare == "eq":
                if isinstance(value, float):
                    match = abs(current_f - value) < 0.001
                else:
                    match = current_f == float(value)
            elif compare == "neq":
                match = current_f != float(value)
            elif compare == "gt":
                match = current_f > float(value)
            elif compare == "lt":
                match = current_f < float(value)
            elif compare == "changed":
                match = current_f != res.value
            elif compare == "unchanged":
                match = current_f == res.value

            if match:
                res.previous_values.append(res.value)
                res.value = current_f
                new_results.append(res)

        self._results = new_results
        self._scanning = False
        if progress_cb:
            progress_cb(total, total)
        return len(self._results)

    def refresh_values(self) -> int:
        """刷新所有结果的当前值"""
        if not self._handle:
            return 0
        count = 0
        for res in self._results:
            current = self.read_value(res.address, res.data_type)
            if current is not None:
                res.value = float(current)
                count += 1
        return count

    def __del__(self):
        self.detach()
