"""test_mods_config.py — Mod 专属配置文件解析、读取、保存与热重载测试"""

import json
import os
import pytest

from webui.server import WebUIHandler
from lib.config_loader import reload_config, get_config


class DummyHandler:
    def __init__(self, path="/api/mods/config", body=None, user_perms=None):
        self.path = path
        self._body = body or {}
        self.user_perms = user_perms if user_perms is not None else ["mods"]
        self.responses = []

    def _read_body(self):
        return self._body

    def _respond(self, data, status=200, content_type="application/json"):
        self.responses.append((status, data))

    def _respond_denied(self):
        self.responses.append((401, {"ok": False, "message": "未登录"}))


DummyHandler._resolve_mod_config = WebUIHandler._resolve_mod_config
DummyHandler._api_get_mod_config = WebUIHandler._api_get_mod_config
DummyHandler._api_save_mod_config = WebUIHandler._api_save_mod_config


@pytest.fixture(autouse=True)
def mock_perms(monkeypatch):
    monkeypatch.setattr(
        "webui.server._require_permission",
        lambda perm: (lambda handler: True if perm in handler.user_perms else (handler._respond({"ok": False, "message": f"需要 {perm} 权限"}, status=403) or False))
    )


class TestModConfigResolver:
    def test_resolve_known_section(self, tmp_path, monkeypatch):
        handler = DummyHandler()
        monkeypatch.setattr("webui.server.ROOT", str(tmp_path))
        monkeypatch.setattr("webui.server.CONFIG_JSON", str(tmp_path / "config" / "config.json"))

        res_ai = handler._resolve_mod_config("AI", "client")
        assert res_ai["configType"] == "section"
        assert res_ai["section"] == "AIConfig"

        res_bot = handler._resolve_mod_config("Bot", "client")
        assert res_bot["configType"] == "section"
        assert res_bot["section"] == "botConfig"

        res_msg = handler._resolve_mod_config("Message", "client")
        assert res_msg["configType"] == "section"
        assert res_msg["section"] == "messageConfig"

        res_spam = handler._resolve_mod_config("spam", "server")
        assert res_spam["configType"] == "section"
        assert res_spam["section"] == "spam"

        res_tool = handler._resolve_mod_config("Tool", "client")
        assert res_tool["configType"] == "section"
        assert res_tool["section"] == "utilsConfig"

    def test_resolve_standalone_file_precedence(self, tmp_path, monkeypatch):
        monkeypatch.setattr("webui.server.ROOT", str(tmp_path))
        monkeypatch.setattr("webui.server.CONFIG_JSON", str(tmp_path / "config" / "config.json"))

        mods_dir = tmp_path / "config" / "mods"
        mods_dir.mkdir(parents=True)
        custom_file = mods_dir / "AI.json"
        custom_file.write_text('{"custom": true}', encoding="utf-8")

        handler = DummyHandler()
        res = handler._resolve_mod_config("AI", "client")
        assert res["configType"] == "file"
        assert res["filePath"] == str(custom_file)
        assert res["section"] is None

    def test_resolve_custom_mod_defaults_to_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("webui.server.ROOT", str(tmp_path))
        monkeypatch.setattr("webui.server.CONFIG_JSON", str(tmp_path / "config" / "config.json"))

        handler = DummyHandler()
        res = handler._resolve_mod_config("CustomMod", "client")
        assert res["configType"] == "file"
        assert res["target"] == "config/mods/CustomMod.json"
        assert res["section"] is None


class TestModConfigAPI:
    def test_get_mod_config_section(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True)
        cfg_file = config_dir / "config.json"
        cfg_file.write_text(json.dumps({
            "AIConfig": {
                "options": {"apiKey": "test-key-123"},
                "models": {"chat": {"model": "test-chat"}}
            }
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        monkeypatch.setattr("webui.server.ROOT", str(tmp_path))
        monkeypatch.setattr("webui.server.CONFIG_JSON", str(cfg_file))
        monkeypatch.setattr("webui.server.CONFIG_DIR", str(config_dir))

        handler = DummyHandler(path="/api/mods/config?name=AI&side=client")
        handler._api_get_mod_config()

        assert len(handler.responses) == 1
        status, data = handler.responses[0]
        assert status == 200
        assert data["ok"] is True
        assert data["name"] == "AI"
        assert data["configType"] == "section"
        parsed = json.loads(data["content"])
        assert parsed["options"]["apiKey"] == "test-key-123"

    def test_get_mod_config_file_default_template(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr("webui.server.ROOT", str(tmp_path))
        monkeypatch.setattr("webui.server.CONFIG_JSON", str(config_dir / "config.json"))
        monkeypatch.setattr("webui.server.CONFIG_DIR", str(config_dir))

        handler = DummyHandler(path="/api/mods/config?name=NewMod&side=client")
        handler._api_get_mod_config()

        status, data = handler.responses[0]
        assert status == 200
        assert data["ok"] is True
        assert data["configType"] == "file"
        parsed = json.loads(data["content"])
        assert parsed["enabled"] is True
        assert parsed["name"] == "NewMod"

    def test_save_mod_config_syntax_error_validation(self):
        handler = DummyHandler(body={
            "name": "AI",
            "side": "client",
            "content": '{\n  "options": {\n    "key": 123,\n  }\n}',  # Trailing comma is invalid JSON
        })
        handler._api_save_mod_config()

        status, data = handler.responses[0]
        assert status == 200
        assert data["ok"] is False
        assert "JSON 语法错误" in data["message"]
        assert "error" in data
        assert data["error"]["line"] >= 1

    def test_save_mod_config_section_with_backup(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True)
        cfg_file = config_dir / "config.json"
        cfg_file.write_text(json.dumps({
            "AIConfig": {"options": {"apiKey": "old-key"}}
        }), encoding="utf-8")

        monkeypatch.setattr("webui.server.ROOT", str(tmp_path))
        monkeypatch.setattr("webui.server.CONFIG_JSON", str(cfg_file))
        monkeypatch.setattr("webui.server.CONFIG_DIR", str(config_dir))

        new_content = json.dumps({"options": {"apiKey": "new-secret-key"}}, indent=2)
        handler = DummyHandler(body={
            "name": "AI",
            "side": "client",
            "content": new_content,
            "reload": False,
        })
        handler._api_save_mod_config()

        status, data = handler.responses[0]
        assert status == 200
        assert data["ok"] is True

        # 检查备份与新内容
        bak_file = config_dir / "config.json.bak"
        assert bak_file.exists()
        with open(cfg_file, "r", encoding="utf-8") as f:
            updated = json.load(f)
        assert updated["AIConfig"]["options"]["apiKey"] == "new-secret-key"

    def test_save_mod_config_standalone_file(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True)
        monkeypatch.setattr("webui.server.ROOT", str(tmp_path))
        monkeypatch.setattr("webui.server.CONFIG_JSON", str(config_dir / "config.json"))
        monkeypatch.setattr("webui.server.CONFIG_DIR", str(config_dir))

        mod_cfg_content = json.dumps({"custom": "value", "speed": 10}, indent=2)
        handler = DummyHandler(body={
            "name": "MyCustomMod",
            "side": "client",
            "content": mod_cfg_content,
            "reload": False,
        })
        handler._api_save_mod_config()

        status, data = handler.responses[0]
        assert status == 200
        assert data["ok"] is True
        assert data["configType"] == "file"

        target_file = tmp_path / "config" / "mods" / "MyCustomMod.json"
        assert target_file.exists()
        with open(target_file, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["custom"] == "value"
        assert saved["speed"] == 10

    def test_permission_denied_without_mods_perm(self):
        handler = DummyHandler(path="/api/mods/config?name=AI", user_perms=["dashboard"])
        handler._api_get_mod_config()

        status, data = handler.responses[0]
        assert status == 403
        assert data["ok"] is False


class TestConfigLoaderSync:
    def test_reload_config_syncs_sys_modules(self, monkeypatch, tmp_path):
        import sys
        fake_json = tmp_path / "config.json"
        fake_json.write_text(json.dumps({
            "testProp": 999
        }), encoding="utf-8")

        monkeypatch.setattr("lib.config_loader.CONFIG_JSON", fake_json)
        monkeypatch.setattr("lib.config_loader.CONFIG_PY", tmp_path / "none.py")

        reload_config()
        cfg = get_config()
        assert cfg.get("testProp") == 999

        if "config" in sys.modules:
            assert getattr(sys.modules["config"], "testProp", None) == 999
