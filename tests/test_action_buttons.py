"""tests/test_action_buttons.py — 控制台快捷动作宏按键 API 单元测试"""
import unittest
from unittest.mock import patch

from webui.server import WebUIHandler
import webui.server as ws_mod


class TestActionButtonsAPI(unittest.TestCase):
    def test_get_action_buttons_default(self):
        handler = WebUIHandler.__new__(WebUIHandler)
        sent_response = None

        def mock_respond(data):
            nonlocal sent_response
            sent_response = data

        handler._respond = mock_respond
        with patch("lib.config_loader.get_config", return_value={}):
            handler._api_get_action_buttons()

        self.assertIsNotNone(sent_response)
        self.assertTrue(sent_response.get("ok"))
        buttons = sent_response.get("buttons")
        self.assertIsInstance(buttons, list)
        self.assertGreaterEqual(len(buttons), 3)
        self.assertTrue(any(b.get("id") == "day_weather" for b in buttons))
        # 确认 title 没有重复包含 icon
        day_btn = next(b for b in buttons if b.get("id") == "day_weather")
        self.assertEqual(day_btn.get("title"), "晴天白昼")

    def test_get_action_buttons_clean_legacy_icon_in_title(self):
        handler = WebUIHandler.__new__(WebUIHandler)
        sent_response = None

        def mock_respond(data):
            nonlocal sent_response
            sent_response = data

        handler._respond = mock_respond
        legacy_cfg = {
            "actionButtons": [
                {"id": "test_1", "title": "☀️ 晴天白昼", "icon": "☀️", "commands": ["/time set day"]},
                {"id": "test_2", "title": "普通按钮", "icon": "⚡", "commands": ["/help"]},
            ]
        }
        with patch("lib.config_loader.get_config", return_value=legacy_cfg):
            handler._api_get_action_buttons()

        self.assertTrue(sent_response.get("ok"))
        buttons = sent_response.get("buttons")
        self.assertEqual(buttons[0]["title"], "晴天白昼")
        self.assertEqual(buttons[1]["title"], "普通按钮")

    def test_save_action_buttons(self):
        handler = WebUIHandler.__new__(WebUIHandler)
        sent_response = None

        def mock_respond(data):
            nonlocal sent_response
            sent_response = data

        handler._respond = mock_respond
        orig_require = ws_mod._require_permission
        ws_mod._require_permission = lambda perm: (lambda h: True)

        saved_cfg = {}
        def mock_save_config(cfg):
            nonlocal saved_cfg
            saved_cfg = cfg

        test_buttons = [
            {"title": "测试一键白天", "icon": "☀️", "commands": ["/time set day"], "color": "#f59e0b"},
            {"title": "测试一键清理", "icon": "🧹", "commands": ["/kill @e[type=item]"], "color": "#ef4444"}
        ]
        handler._read_body = lambda: {"buttons": test_buttons}

        try:
            with patch("webui.server.save_config", mock_save_config), patch("lib.config_loader.get_config", return_value={}):
                handler._api_save_action_buttons()
                self.assertIsNotNone(sent_response)
                self.assertTrue(sent_response.get("ok"))
                self.assertEqual(len(sent_response.get("buttons")), 2)
                self.assertEqual(sent_response.get("buttons")[0]["title"], "测试一键白天")
                self.assertIn("actionButtons", saved_cfg)
                self.assertEqual(len(saved_cfg["actionButtons"]), 2)
        finally:
            ws_mod._require_permission = orig_require


if __name__ == "__main__":
    unittest.main()
