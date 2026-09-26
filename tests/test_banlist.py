"""test_banlist.py — IP 封禁与自动封禁核心逻辑回归测试"""

import os
import time
import pytest
from unittest.mock import patch

import lib.banlist as banlist


@pytest.fixture(autouse=True)
def clean_banlist(tmp_path):
    """每个测试隔离 banlist 存储"""
    orig_file = banlist.BANLIST_JSON
    banlist.BANLIST_JSON = str(tmp_path / "banlist.json")
    with banlist._lock:
        banlist._banned_ips.clear()
        banlist._fail_log.clear()
    banlist.set_auto_ban(True)
    banlist.set_auto_ban_config({"window": 60, "threshold": 5, "banDuration": 10})
    yield
    banlist.BANLIST_JSON = orig_file
    with banlist._lock:
        banlist._banned_ips.clear()
        banlist._fail_log.clear()


class TestBanlistBasic:
    def test_ban_and_unban(self):
        assert not banlist.is_banned("192.168.1.100")
        assert banlist.ban("192.168.1.100", reason="测试封禁", duration=0)
        assert banlist.is_banned("192.168.1.100")
        assert banlist.count() == 1

        # 重复封禁返回 False
        assert not banlist.ban("192.168.1.100", reason="重复封禁")

        # 解封
        assert banlist.unban("192.168.1.100")
        assert not banlist.is_banned("192.168.1.100")
        assert banlist.count() == 0

        # 解封不存在的 IP 返回 False
        assert not banlist.unban("192.168.1.100")

    def test_protected_ips(self):
        assert not banlist.ban("127.0.0.1")
        assert not banlist.ban("::1")
        assert not banlist.is_banned("127.0.0.1")
        assert not banlist.is_banned("::1")
        assert banlist.count() == 0


class TestBanlistDurationAndExpiration:
    def test_temporary_ban_expiration(self):
        # 封禁 10 分钟
        banlist.ban("10.0.0.1", reason="临时封禁", duration=10)
        assert banlist.is_banned("10.0.0.1")

        # 模拟时间快进 11 分钟 (660 秒)
        future_time = time.time() + 660
        with patch("time.time", return_value=future_time):
            # 应该已过期并自动清理
            assert not banlist.is_banned("10.0.0.1")
            assert "10.0.0.1" not in banlist.list_bans()

    def test_set_ban_duration(self):
        banlist.ban("10.0.0.2", reason="初始永久", duration=0)
        bans = banlist.list_bans()
        assert bans["10.0.0.2"]["expires"] is None

        # 改为 30 分钟
        assert banlist.set_ban_duration("10.0.0.2", 30)
        bans2 = banlist.list_bans()
        assert bans2["10.0.0.2"]["expires"] is not None

        # 修改不存在的 IP 返回 False
        assert not banlist.set_ban_duration("10.0.0.99", 10)


class TestAutoBan:
    def test_auto_ban_triggers_at_threshold(self):
        ip = "192.168.10.50"
        for i in range(4):
            res = banlist.record_auth_failure(ip)
            assert not res["banned"]
            assert res["remaining"] == (4 - i)
            assert not banlist.is_banned(ip)

        # 第 5 次达到阈值，触发自动封禁
        res5 = banlist.record_auth_failure(ip)
        assert res5["banned"]
        assert res5["remaining"] == 0
        assert banlist.is_banned(ip)

    def test_clear_failures(self):
        ip = "192.168.10.51"
        banlist.record_auth_failure(ip)
        banlist.record_auth_failure(ip)
        assert banlist.get_fail_count(ip) == 2
        banlist.clear_auth_failures(ip)
        assert banlist.get_fail_count(ip) == 0


class TestBatchOperations:
    def test_batch_ban_and_batch_unban(self):
        ips = ["172.16.0.1", "172.16.0.2", "172.16.0.3", "172.16.0.4"]
        for ip in ips:
            banlist.ban(ip, reason="批量测试", duration=0)
        assert banlist.count() == 4

        # 批量解封部分
        for ip in ["172.16.0.1", "172.16.0.3"]:
            banlist.unban(ip)

        assert banlist.count() == 2
        assert not banlist.is_banned("172.16.0.1")
        assert banlist.is_banned("172.16.0.2")
        assert not banlist.is_banned("172.16.0.3")
        assert banlist.is_banned("172.16.0.4")


class TestBannedHtmlResponse:
    def test_check_ban_chinese(self):
        import io
        from webui.server import WebUIHandler
        banlist.ban("10.0.0.99", reason="测试封禁", duration=0)
        handler = WebUIHandler.__new__(WebUIHandler)
        handler.client_address = ("10.0.0.99", 12345)
        handler.headers = {"Accept-Language": "zh-CN,zh;q=0.9"}
        handler.wfile = io.BytesIO()
        handler.send_response = lambda code: None
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None
        assert handler._check_ban() is True
        body = handler.wfile.getvalue().decode("utf-8")
        assert "永久" in body
        assert 'data-i18n="banned.permanent"' in body

    def test_check_ban_english(self):
        import io
        from webui.server import WebUIHandler
        banlist.ban("10.0.0.98", reason="Test ban", duration=0)
        handler = WebUIHandler.__new__(WebUIHandler)
        handler.client_address = ("10.0.0.98", 12345)
        handler.headers = {"Accept-Language": "en-US,en;q=0.9"}
        handler.wfile = io.BytesIO()
        handler.send_response = lambda code: None
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None
        assert handler._check_ban() is True
        body = handler.wfile.getvalue().decode("utf-8")
        assert "Permanent" in body
        assert 'data-i18n="banned.permanent"' in body

