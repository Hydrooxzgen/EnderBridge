"""tests/test_xbox_account_switch.py — 测试 Xbox 账号切换与移除在 config.py 不存在时的稳定性"""

import json
import os
import pytest
from webui.server import WebUIHandler, CONFIG_JSON, CONFIG_PY, save_config
import webui.server as ws_mod


class TestXboxAccountSwitch:
    @pytest.fixture(autouse=True)
    def setup_config(self, tmp_path, monkeypatch):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        json_file = cfg_dir / "config.json"
        py_file = cfg_dir / "config.py"  # 确保不存在

        initial_config = {
            "botConfig": {
                "enabled": True,
                "username": "AccountA",
                "activeXboxAccount": "AccountA",
                "xboxAccounts": [
                    {"username": "AccountA"},
                    {"username": "AccountB"},
                ],
            }
        }
        with open(str(json_file), "w", encoding="utf-8") as f:
            json.dump(initial_config, f, indent=2)

        monkeypatch.setattr(ws_mod, "CONFIG_DIR", str(cfg_dir))
        monkeypatch.setattr(ws_mod, "CONFIG_JSON", str(json_file))
        monkeypatch.setattr(ws_mod, "CONFIG_PY", str(py_file))
        monkeypatch.setattr(ws_mod, "CONFIG_PY_BAK", str(py_file) + ".bak")

        # 确保 config.py 真的不存在
        assert not os.path.exists(str(py_file))

    def test_switch_xbox_account_without_config_py(self, monkeypatch):
        """测试在只有 config.json 时切换 Xbox 账号成功且无 Errno 2 报错"""
        handler = WebUIHandler.__new__(WebUIHandler)
        handler._read_body = lambda: {"username": "AccountB"}
        sent_response = None
        handler._respond = lambda d: nonlocal_sent(d)
        def nonlocal_sent(d):
            nonlocal sent_response
            sent_response = d

        monkeypatch.setattr(ws_mod, "_require_permission", lambda perm: (lambda h: True))

        handler._api_bot_xbox_account_switch()
        assert sent_response is not None
        assert sent_response.get("ok") is True, f"Response: {sent_response}"
        assert "已切换到账号 AccountB" in sent_response.get("message", "")

        # 验证 config.json 中的 activeXboxAccount 已更新
        with open(ws_mod.CONFIG_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["botConfig"]["activeXboxAccount"] == "AccountB"
        assert data["botConfig"]["username"] == "AccountB"

    def test_remove_xbox_account_without_config_py(self, monkeypatch):
        """测试在只有 config.json 时移除 Xbox 账号成功且无 Errno 2 报错"""
        handler = WebUIHandler.__new__(WebUIHandler)
        handler._read_body = lambda: {"username": "AccountA"}
        sent_response = None
        def nonlocal_sent(d):
            nonlocal sent_response
            sent_response = d
        handler._respond = nonlocal_sent

        monkeypatch.setattr(ws_mod, "_require_permission", lambda perm: (lambda h: True))
        monkeypatch.setattr(handler, "_delete_account_cache", lambda u, c: None)

        handler._api_bot_xbox_account_remove()
        assert sent_response is not None
        assert sent_response.get("ok") is True, f"Response: {sent_response}"
        assert "已移除账号 AccountA" in sent_response.get("message", "")

        # 验证 config.json 中 AccountA 已被移除，activeXboxAccount 自动切换到 AccountB
        with open(ws_mod.CONFIG_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data["botConfig"]["xboxAccounts"]) == 1
        assert data["botConfig"]["xboxAccounts"][0]["username"] == "AccountB"
        assert data["botConfig"]["activeXboxAccount"] == "AccountB"
