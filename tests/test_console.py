"""tests/test_console.py — 控制台与 EB 指令分发单元测试"""

import asyncio
import pytest

from lib.command import Command
from main import _dispatch_console_command


class TestConsoleDispatch:
    def test_eb_prefix_help_command_handled(self):
        """测试以 prefix 开头的 $help 指令分发执行成功"""
        Command.reload_prefix()
        cp = Command.command_prefix
        res = asyncio.run(_dispatch_console_command(f"{cp}help"))
        assert isinstance(res, dict)
        assert res.get("ok") is True
        assert res.get("handled") is True
        assert "帮助" in res.get("message", "")

    def test_eb_prefix_status_command_handled(self):
        """测试以 prefix 开头的 $status 指令执行成功"""
        Command.reload_prefix()
        cp = Command.command_prefix
        res = asyncio.run(_dispatch_console_command(f"{cp}status"))
        assert isinstance(res, dict)
        assert res.get("ok") is True
        assert res.get("handled") is True

    def test_eb_prefix_bot_help_command_handled(self):
        """测试以 prefix 开头的 $bot help 指令执行成功，无需 MCBE 客户端连接"""
        Command.reload_prefix()
        cp = Command.command_prefix
        res = asyncio.run(_dispatch_console_command(f"{cp}bot help"))
        assert isinstance(res, dict)
        assert res.get("ok") is True

    def test_eb_unknown_command_returns_error(self):
        """测试未知 EB 指令返回 ok: False"""
        Command.reload_prefix()
        cp = Command.command_prefix
        res = asyncio.run(_dispatch_console_command(f"{cp}unknown_invalid_cmd_12345"))
        assert isinstance(res, dict)
        assert res.get("ok") is False
        assert res.get("handled") is False

    def test_webui_console_executes_eb_prefix_command(self):
        """测试 WebUI console 接口收到 EB 前缀命令时正确分发执行并返回结果"""
        import threading
        from webui.server import set_console_handler, set_event_loop, WebUIHandler
        import webui.server as ws_mod

        loop = asyncio.new_event_loop()
        threading.Thread(target=loop.run_forever, daemon=True).start()
        set_event_loop(loop)
        set_console_handler(_dispatch_console_command)

        handler = WebUIHandler.__new__(WebUIHandler)
        handler._read_body = lambda: {"command": "$help"}
        sent_response = None
        def mock_respond(data):
            nonlocal sent_response
            sent_response = data
        handler._respond = mock_respond

        orig_require = ws_mod._require_permission
        ws_mod._require_permission = lambda perm: (lambda h: True)
        try:
            handler._api_console()
            assert sent_response is not None
            assert sent_response.get("ok") is True
            assert sent_response.get("statusCode") == 0
        finally:
            ws_mod._require_permission = orig_require
            loop.call_soon_threadsafe(loop.stop)
            set_event_loop(None)
            set_console_handler(None)
