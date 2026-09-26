"""lib/sys_metrics.py — 跨平台系统资源与实时性能指标采集模块

无需第三方依赖(不依赖 psutil)，支持 Windows、Linux 与 Termux 跨平台。
负责采样 CPU 利用率、物理内存消耗、进程 WorkingSet 及消息吞吐速率，并维护 60 秒时序环形队列。
"""

import collections
import ctypes
import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional

_IS_WINDOWS = sys.platform.startswith("win")
_IS_LINUX = sys.platform.startswith("linux")

# ===== Windows Ctypes 结构定义 =====
if _IS_WINDOWS:
    from ctypes import wintypes

    class _FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    def _ft_to_int(ft: _FILETIME) -> int:
        return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

    class _MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_uint64),
            ("ullAvailPhys", ctypes.c_uint64),
            ("ullTotalPageFile", ctypes.c_uint64),
            ("ullAvailPageFile", ctypes.c_uint64),
            ("ullTotalVirtual", ctypes.c_uint64),
            ("ullAvailVirtual", ctypes.c_uint64),
            ("ullAvailExtendedVirtual", ctypes.c_uint64),
        ]

    class _PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]


class MetricsCollector:
    """性能与系统资源指标收集器"""

    def __init__(self, history_len: int = 60, interval: float = 1.0):
        self.history_len = history_len
        self.interval = interval
        self._history = collections.deque(maxlen=history_len)
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # 统计打点计数器
        self._msg_counter = 0
        self._last_msg_rate = 0.0

        # CPU 采样基准缓存
        self._last_sys_cpu_times: Optional[tuple] = None
        self._last_proc_cpu_time: Optional[float] = None
        self._last_sample_wall_time: Optional[float] = None

        # 初始化单次采样基准
        self._init_cpu_baseline()

    def _init_cpu_baseline(self) -> None:
        self._last_sample_wall_time = time.time()
        self._last_proc_cpu_time = time.process_time()
        if _IS_WINDOWS:
            try:
                idle, kernel, user = _FILETIME(), _FILETIME(), _FILETIME()
                ctypes.windll.kernel32.GetSystemTimes(
                    ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
                )
                self._last_sys_cpu_times = (
                    _ft_to_int(idle),
                    _ft_to_int(kernel),
                    _ft_to_int(user),
                )
            except Exception:
                self._last_sys_cpu_times = None
        elif _IS_LINUX:
            try:
                self._last_sys_cpu_times = self._read_linux_cpu_times()
            except Exception:
                self._last_sys_cpu_times = None

    def _read_linux_cpu_times(self) -> Optional[tuple]:
        """读取 /proc/stat 中的 cpu 统计数值"""
        if not os.path.exists("/proc/stat"):
            return None
        with open("/proc/stat", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("cpu "):
                    parts = line.split()[1:]
                    nums = [float(p) for p in parts if p.isdigit()]
                    if len(nums) >= 4:
                        # idle is index 3
                        idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
                        total = sum(nums)
                        return (idle, total)
        return None

    def _calc_system_cpu(self) -> float:
        """计算系统总 CPU 利用率 (0.0 ~ 100.0)"""
        if _IS_WINDOWS:
            try:
                idle, kernel, user = _FILETIME(), _FILETIME(), _FILETIME()
                if ctypes.windll.kernel32.GetSystemTimes(
                    ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
                ):
                    i, k, u = _ft_to_int(idle), _ft_to_int(kernel), _ft_to_int(user)
                    if self._last_sys_cpu_times:
                        li, lk, lu = self._last_sys_cpu_times
                        idle_delta = i - li
                        total_delta = (k - lk) + (u - lu)
                        self._last_sys_cpu_times = (i, k, u)
                        if total_delta > 0:
                            pct = 100.0 * (1.0 - (idle_delta / total_delta))
                            return max(0.0, min(100.0, round(pct, 1)))
                    else:
                        self._last_sys_cpu_times = (i, k, u)
            except Exception:
                pass
        elif _IS_LINUX:
            try:
                cur = self._read_linux_cpu_times()
                if cur and self._last_sys_cpu_times:
                    idle_delta = cur[0] - self._last_sys_cpu_times[0]
                    total_delta = cur[1] - self._last_sys_cpu_times[1]
                    self._last_sys_cpu_times = cur
                    if total_delta > 0:
                        pct = 100.0 * (1.0 - (idle_delta / total_delta))
                        return max(0.0, min(100.0, round(pct, 1)))
                self._last_sys_cpu_times = cur
            except Exception:
                pass

        return 0.0

    def _calc_process_cpu(self) -> float:
        """计算当前 Python 进程的 CPU 利用率 (0.0 ~ 100.0)"""
        now_wall = time.time()
        now_proc = time.process_time()
        pct = 0.0

        if self._last_sample_wall_time and self._last_proc_cpu_time:
            wall_delta = now_wall - self._last_sample_wall_time
            proc_delta = now_proc - self._last_proc_cpu_time
            if wall_delta > 0:
                cpu_count = os.cpu_count() or 1
                pct = (proc_delta / wall_delta) * 100.0 / cpu_count

        self._last_sample_wall_time = now_wall
        self._last_proc_cpu_time = now_proc
        return max(0.0, min(100.0, round(pct, 1)))

    def _get_memory(self) -> Dict[str, Any]:
        """获取物理内存及进程内存使用情况"""
        mem_percent = 0.0
        mem_used_mb = 0.0
        mem_total_mb = 0.0
        proc_mem_mb = 0.0

        if _IS_WINDOWS:
            try:
                stat = _MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                    mem_percent = float(stat.dwMemoryLoad)
                    mem_total_mb = round(stat.ullTotalPhys / (1024 * 1024), 1)
                    mem_used_mb = round(
                        (stat.ullTotalPhys - stat.ullAvailPhys) / (1024 * 1024), 1
                    )
            except Exception:
                pass

            try:
                pmc = _PROCESS_MEMORY_COUNTERS_EX()
                pmc.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS_EX)
                h = ctypes.windll.kernel32.OpenProcess(0x0410, False, os.getpid())
                if h:
                    if ctypes.windll.psapi.GetProcessMemoryInfo(
                        h, ctypes.byref(pmc), pmc.cb
                    ):
                        proc_mem_mb = round(pmc.WorkingSetSize / (1024 * 1024), 1)
                    ctypes.windll.kernel32.CloseHandle(h)
            except Exception:
                pass

        elif _IS_LINUX:
            try:
                if os.path.exists("/proc/meminfo"):
                    total, avail, free = 0.0, 0.0, 0.0
                    with open("/proc/meminfo", "r", encoding="utf-8") as f:
                        for line in f:
                            if line.startswith("MemTotal:"):
                                total = float(line.split()[1]) / 1024.0
                            elif line.startswith("MemAvailable:"):
                                avail = float(line.split()[1]) / 1024.0
                            elif line.startswith("MemFree:") and avail == 0:
                                free = float(line.split()[1]) / 1024.0
                    mem_total_mb = round(total, 1)
                    used = total - (avail if avail > 0 else free)
                    mem_used_mb = round(used, 1)
                    if total > 0:
                        mem_percent = round((used / total) * 100.0, 1)
            except Exception:
                pass

            try:
                if os.path.exists("/proc/self/statm"):
                    with open("/proc/self/statm", "r", encoding="utf-8") as f:
                        # 2nd column is resident pages
                        rss_pages = float(f.read().split()[1])
                        page_size_kb = os.sysconf("SC_PAGE_SIZE") / 1024.0
                        proc_mem_mb = round((rss_pages * page_size_kb) / 1024.0, 1)
            except Exception:
                pass

        return {
            "mem_percent": mem_percent,
            "mem_used_mb": mem_used_mb,
            "mem_total_mb": mem_total_mb,
            "proc_mem_mb": proc_mem_mb,
        }

    def record_message(self, count: int = 1) -> None:
        """记录发生的消息交互打点"""
        with self._lock:
            self._msg_counter += count

    def sample_once(self, clients_count: int = 0) -> Dict[str, Any]:
        """执行一次全指标采样并压入环形队列"""
        sys_cpu = self._calc_system_cpu()
        proc_cpu = self._calc_process_cpu()
        mem = self._get_memory()

        with self._lock:
            msg_rate = float(self._msg_counter)
            self._msg_counter = 0
            self._last_msg_rate = msg_rate

        point = {
            "time": int(time.time()),
            "cpu": sys_cpu,
            "proc_cpu": proc_cpu,
            "mem_percent": mem["mem_percent"],
            "mem_used_mb": mem["mem_used_mb"],
            "mem_total_mb": mem["mem_total_mb"],
            "proc_mem_mb": mem["proc_mem_mb"],
            "clients": clients_count,
            "msg_rate": msg_rate,
        }

        with self._lock:
            self._history.append(point)

        return point

    def _worker(self) -> None:
        """后台采样工作线程"""
        while self._running:
            time.sleep(self.interval)
            if not self._running:
                break
            try:
                # 获取连接数（如有 status provider）
                clients = 0
                try:
                    from webui import server
                    if server._status_provider:
                        st = server._status_provider() or {}
                        clients = int(st.get("clients", 0))
                except Exception:
                    pass

                self.sample_once(clients_count=clients)
            except Exception:
                pass

    def start(self) -> None:
        """启动后台定时采样"""
        if self._running:
            return
        self._running = True
        # 先采样一次填充初始基线
        try:
            self.sample_once()
        except Exception:
            pass
        self._thread = threading.Thread(target=self._worker, name="SysMetricsCollector", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """停止采集"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def get_snapshot(self) -> Dict[str, Any]:
        """获取当前指标快照与完整时序历史数据"""
        with self._lock:
            history_list = list(self._history)
            current = history_list[-1] if history_list else {
                "time": int(time.time()),
                "cpu": 0.0,
                "proc_cpu": 0.0,
                "mem_percent": 0.0,
                "mem_used_mb": 0.0,
                "mem_total_mb": 0.0,
                "proc_mem_mb": 0.0,
                "clients": 0,
                "msg_rate": 0.0,
            }

        mem_info = self._get_memory()
        return {
            "ok": True,
            "current": current,
            "history": history_list,
            "system": {
                "platform": sys.platform,
                "cpu_count": os.cpu_count() or 1,
                "total_memory_mb": mem_info.get("mem_total_mb", 0.0),
            },
        }


# 全局采集器单例
metrics_collector = MetricsCollector(history_len=60, interval=1.0)

