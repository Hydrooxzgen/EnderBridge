"""lib/watchdog.py — 挂起检测看门狗与系统自愈探针 (Watchdog & Health Probe)

负责监控 asyncio 事件循环活跃度、检测线程死锁与长时间卡死，
并在系统挂起时自动抓取线程堆栈轨迹、触发保护性自愈重启。
同时提供标准健康检查探针数据 (Health Probe)，供外部监控系统及 Docker/K8s 集成。
"""

import asyncio
import os
import sys
import threading
import time
import traceback
from typing import Any, Callable, Dict, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "logs")
HANG_DUMP_FILE = os.path.join(LOG_DIR, "watchdog_hang.log")


class Watchdog:
    """事件循环看门狗与健康探针"""

    def __init__(
        self,
        check_interval: float = 10.0,
        hang_timeout: float = 60.0,
        auto_recover: bool = True,
        hang_threshold: Optional[float] = None,
    ):
        if hang_threshold is not None:
            hang_timeout = hang_threshold
        self.check_interval = max(0.05, float(check_interval))
        self.hang_timeout = max(0.1, float(hang_timeout))
        self.auto_recover = bool(auto_recover)

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._restart_handler: Optional[Callable[[], None]] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

        self._boot_time = time.time()
        self._last_beat = time.time()
        self._last_lag_ms = 0.0
        self._hang_detected = False
        self._hang_count = 0
        self._recovery_triggered = False

    @property
    def hang_threshold(self) -> float:
        return self.hang_timeout

    @property
    def is_running(self) -> bool:
        return self._running

    def start(
        self,
        loop: asyncio.AbstractEventLoop,
        restart_handler: Optional[Callable[[], None]] = None,
    ) -> None:
        """启动看门狗后台守护线程"""
        if self._running:
            return
        self._loop = loop
        self._restart_handler = restart_handler
        self._boot_time = time.time()
        self._last_beat = time.time()
        self._running = True
        self._recovery_triggered = False

        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="EnderBridge-Watchdog",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """停止看门狗监控"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def tick(self) -> None:
        """由事件循环调用的心跳刷新"""
        self._last_beat = time.time()

    def _monitor_loop(self) -> None:
        """独立后台线程：定期向事件循环派发心跳探针"""
        while self._running:
            time.sleep(self.check_interval)
            if not self._running or self._loop is None:
                break

            send_time = time.time()

            def _on_tick():
                now = time.time()
                self._last_beat = now
                self._last_lag_ms = max(0.0, (now - send_time) * 1000.0)

            try:
                if not self._loop.is_closed():
                    self._loop.call_soon_threadsafe(_on_tick)
                else:
                    break
            except Exception:
                pass

            # 检查上一次成功心跳距今的时间
            self._check_once()

    def _check_once(self) -> None:
        """执行单次挂起检测与状态刷新"""
        silence_sec = time.time() - self._last_beat
        if silence_sec > self.hang_timeout:
            self._on_hang_detected(silence_sec)
        else:
            self._hang_detected = False
            self._recovery_triggered = False

    def _on_hang_detected(self, silence_sec: float) -> None:
        """检测到主事件循环挂起时的处理逻辑"""
        self._hang_detected = True
        self._hang_count += 1

        # 1. 抓取并保存所有存活线程的调用栈
        dump_path = self._dump_thread_stacks(silence_sec)

        from lib import shared
        if hasattr(shared, "logger"):
            shared.logger.error(
                f"[Watchdog] 严重告警: 主事件循环已静默 {silence_sec:.1f} 秒 "
                f"(阈值 {self.hang_timeout}s)，系统疑似死锁或重度挂起！"
                f"线程堆栈快照已转储至: {dump_path}"
            )

        # 2. 如果开启了自动自愈且未重复触发，调用重启处理器
        if self.auto_recover and not self._recovery_triggered:
            self._recovery_triggered = True
            if hasattr(shared, "logger"):
                shared.logger.warning("[Watchdog] 正在触发自愈恢复流程...")
            if self._restart_handler:
                try:
                    self._restart_handler()
                except Exception as e:
                    if hasattr(shared, "logger"):
                        shared.logger.error(f"[Watchdog] 触发自愈重启失败: {e}")

    def _dump_thread_stacks(self, silence_sec: float) -> str:
        """转储全线程堆栈至日志文件"""
        dump_file = HANG_DUMP_FILE
        os.makedirs(os.path.dirname(dump_file), exist_ok=True)
        try:
            with open(dump_file, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 60}\n")
                f.write(f"[Watchdog Hang Report] {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Silence Duration: {silence_sec:.2f}s (Threshold: {self.hang_timeout}s)\n")
                f.write(f"Active Threads Count: {threading.active_count()}\n")
                f.write(f"{'-' * 60}\n")

                frames = sys._current_frames()
                for thread_id, frame in frames.items():
                    # 尝试匹配线程名称
                    thread_name = str(thread_id)
                    for t in threading.enumerate():
                        if t.ident == thread_id:
                            thread_name = f"{t.name} (id={thread_id}, daemon={t.daemon})"
                            break
                    f.write(f"\n--- Thread: {thread_name} ---\n")
                    traceback.print_stack(frame, file=f)
                f.write(f"{'=' * 60}\n")
        except Exception:
            pass
        return dump_file

    def get_health_status(self) -> Dict[str, Any]:
        """获取综合健康探针快照 (供 WebUI 仪表盘与 /api/health 使用)"""
        now = time.time()
        uptime = int(now - self._boot_time)
        silence_sec = round(now - self._last_beat, 2)

        if self._hang_detected:
            status = "hanging"
        elif silence_sec > (self.check_interval * 2.5):
            status = "degraded"
        else:
            status = "healthy"

        # 尝试获取系统资源与内存
        mem_mb = None
        try:
            from lib.sys_metrics import metrics_collector
            snap = metrics_collector.get_snapshot()
            cur = snap.get("current", {})
            mem_mb = cur.get("process_memory_mb")
        except Exception:
            pass

        return {
            "ok": (status != "hanging"),
            "status": status,
            "uptime": uptime,
            "loop_lag_ms": round(self._last_lag_ms, 1),
            "heartbeat_age_s": silence_sec,
            "hang_count": self._hang_count,
            "auto_recover": self.auto_recover,
            "hang_timeout": self.hang_timeout,
            "process_memory_mb": mem_mb,
            "active_threads": threading.active_count(),
        }


# 全局单例
watchdog = Watchdog()
