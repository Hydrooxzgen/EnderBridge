"""test_watchdog.py — 挂起监控看门狗 (Watchdog) 与健康探针自动化测试"""

import asyncio
import os
import time
import pytest
from unittest.mock import MagicMock

from lib.watchdog import Watchdog
from webui.server import WebUIHandler, set_safe_mode


class DummyHandler(WebUIHandler):
    """测试用 WebUIHandler 替身"""
    def __init__(self, path="/api/health", user_perms=None, body=None):
        self.path = path
        self.headers = {}
        self.rfile = MagicMock()
        self.wfile = MagicMock()
        self.client_address = ("127.0.0.1", 12345)
        self.responses = []
        self._user_perms = user_perms if user_perms is not None else ["dashboard"]
        self._body = body or {}

    def _respond(self, data, status=200, content_type="application/json"):
        self.responses.append((status, data))

    def _check_ban(self):
        return False

    def _read_body(self):
        return self._body


class TestWatchdog:
    def test_watchdog_init(self):
        wd = Watchdog(check_interval=1.0, hang_threshold=5.0, auto_recover=False)
        assert wd.check_interval == 1.0
        assert wd.hang_threshold == 5.0
        assert wd.auto_recover is False
        assert wd.is_running is False
        status = wd.get_health_status()
        assert status["ok"] is True
        assert status["status"] == "healthy"

    def test_watchdog_start_stop(self):
        loop = asyncio.new_event_loop()
        wd = Watchdog(check_interval=0.1, hang_threshold=1.0, auto_recover=False)
        wd.start(loop)
        assert wd.is_running is True

        time.sleep(0.2)
        status = wd.get_health_status()
        assert status["ok"] is True
        assert "uptime" in status
        assert "process_memory_mb" in status

        wd.stop()
        assert wd.is_running is False
        loop.close()

    def test_hang_detection_and_dump(self, tmp_path, monkeypatch):
        restart_called = []
        log_file = tmp_path / "hang.log"

        wd = Watchdog(check_interval=0.1, hang_threshold=0.5, auto_recover=True)
        wd._restart_handler = lambda: restart_called.append(True)

        wd._last_beat = time.time() - 2.0
        wd._running = True

        monkeypatch.setattr("lib.watchdog.HANG_DUMP_FILE", str(log_file))

        wd._check_once()

        status = wd.get_health_status()
        assert status["ok"] is False
        assert status["status"] == "hanging"
        assert len(restart_called) == 1
        assert os.path.isfile(str(log_file))
        with open(str(log_file), "r", encoding="utf-8") as f:
            dump_content = f.read()
            assert "Watchdog Hang Report" in dump_content
            assert "--- Thread:" in dump_content


class TestHealthEndpoint:
    def test_api_health_public(self, monkeypatch):
        set_safe_mode(False)
        handler = DummyHandler(path="/api/health")
        handler._api_health()
        assert len(handler.responses) == 1
        status_code, data = handler.responses[0]
        assert status_code == 200
        assert data["ok"] is True
        assert data["status"] in ("healthy", "degraded")
        assert data["safeMode"] is False
        assert "uptime" in data

    def test_api_health_safe_mode(self):
        set_safe_mode(True)
        handler = DummyHandler(path="/api/health")
        handler._api_health()
        assert len(handler.responses) == 1
        status_code, data = handler.responses[0]
        assert status_code == 200
        assert data["safeMode"] is True
        set_safe_mode(False)

    def test_api_status_includes_health_and_safe_mode(self):
        set_safe_mode(True)
        handler = DummyHandler(path="/api/status")
        handler._api_status()
        assert len(handler.responses) == 1
        status_code, data = handler.responses[0]
        assert status_code == 200
        assert data["ok"] is True
        assert data["safeMode"] is True
        assert "health" in data
        assert data["health"]["ok"] is True
        set_safe_mode(False)
