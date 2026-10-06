"""tests/test_action_buttons.py — 控制台快捷动作宏按键 API 单元测试"""
import json
import pytest

from webui.server import WebUIHandler
import webui.server as ws_mod


class TestActionButtonsAPI:
    def test_get_action_buttons_default(self, monkeypatch):
        handler = WebUIHandler.__new__(WebUIHandler)
        sent_response = None

        def mock_respond(data):
            nonlocal sent_response
            sent_response = data

        handler._respond = mock_respond
        # Mock get_config 返回空配置
        monkeypatch.setattr("lib.config_loader.get_config", lambda: {})
        handler._api_get_action_buttons()

        assert sent_response is not None
        assert sent_response.get("ok") is True
        buttons = sent_response.get("buttons")
        assert isinstance(buttons, list)
        assert len(buttons) >= 3
        assert any(b.get("id") == "day_weather" for b in buttons)

    def test_save_action_buttons(self, monkeypatch):
        handler = WebUIHandler.__new__(WebUIHandler)
        sent_response = None

        def mock_respond(data):
            nonlocal sent_response
            sent_response = data

        handler._respond = mock_respond

        # 模拟具备 config 权限
        orig_require = ws_mod._require_permission
        ws_mod._require_permission = lambda perm: (lambda h: True)

        saved_cfg = {}
        def mock_save_config(cfg):
            nonlocal saved_cfg
            saved_cfg = cfg

        monkeypatch.setattr("webui.server.save_config", mock_save_config)
        monkeypatch.setattr("lib.config_loader.get_config", lambda: {})

        test_buttons = [
            {"title": "测试一键白天", "icon": "☀️", "commands": ["/time set day"], "color": "#f59e0b"},
            {"title": "测试一键清理", "icon": "🧹", "commands": ["/kill @e[type=item]"], "color": "#ef4444"}
        ]
        handler._read_body = lambda: {"buttons": test_buttons}

        try:
            handler._api_save_action_buttons()
            assert sent_response is not None
            assert sent_response.get("ok") is True
            assert len(sent_response.get("buttons")) == 2
            assert sent_response.get("buttons")[0]["title"] == "测试一键白天"
            assert "actionButtons" in saved_cfg
            assert len(saved_cfg["actionButtons"]) == 2
        finally:
            ws_mod._require_permission = orig_require
