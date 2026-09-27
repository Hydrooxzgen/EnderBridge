"""test_mods_config.py — Mod 专属配置文件解析、读取、保存与热重载测试"""

import json
import os
import pytest

from webui.server import WebUIHandler
from lib.config_loader import reload_config, get_config


class DummyHandler:
    def __init__(self, path="/api/mods/config", body=None, user_perms=None, role="admin", is_guest=False):
        self.path = path
        self._body = body or {}
        self.user_perms = user_perms if user_perms is not None else ["mods"]
        self.user_role = role
        self.is_guest = is_guest
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
DummyHandler._api_get_mods = WebUIHandler._api_get_mods
DummyHandler._api_toggle_mod = WebUIHandler._api_toggle_mod
DummyHandler._api_scan_mods = WebUIHandler._api_scan_mods
DummyHandler._api_import_mod = WebUIHandler._api_import_mod
DummyHandler._api_remove_mod = WebUIHandler._api_remove_mod
DummyHandler._api_upload_mod = WebUIHandler._api_upload_mod


@pytest.fixture(autouse=True)
def mock_perms(monkeypatch):
    monkeypatch.setattr(
        "webui.server._auth_user",
        lambda handler: {
            "username": getattr(handler, "user_name", "admin"),
            "role": getattr(handler, "user_role", "admin"),
            "permissions": getattr(handler, "user_perms", ["mods"]),
            "is_guest": getattr(handler, "is_guest", False),
        }
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


class TestModTimeoutProtection:
    def test_stuck_mod_import_timeout(self):
        from lib.mods import _run_with_timeout
        import time

        def stuck_func():
            while True:
                time.sleep(0.5)

        with pytest.raises(TimeoutError, match="耗时超过"):
            _run_with_timeout(stuck_func, timeout=0.3, action_name="死循环测试")


class TestModManagementAPIs:
    """测试 WebUI Mod 管理新功能：禁用/启用、扫描、导入、移除以及防卡死状态查询"""

    def test_get_mods_does_not_hang_on_stuck_mod(self, monkeypatch, tmp_path):
        """确保 GET /api/mods 绝不会因为恶意/死循环 Mod 文件而卡死"""
        fake_mod_file = tmp_path / "stuck_mod.py"
        fake_mod_file.write_text("import time\nwhile True: time.sleep(1)\n", encoding="utf-8")

        fake_config = {
            "mods": {
                "server": {"StuckMod": str(fake_mod_file)},
                "client": {},
                "disabled": {}
            }
        }
        monkeypatch.setattr("lib.config_loader.get_config", lambda *args, **kwargs: fake_config)

        from lib.mods import ServerModManager
        ServerModManager.failed_mods["StuckMod"] = {
            "status": "timeout",
            "error": "加载超时 (超过 5.0s，疑似死循环)，已自动熔断",
            "path": str(fake_mod_file)
        }

        handler = DummyHandler(path="/api/mods")
        handler._api_get_mods()

        status, data = handler.responses[0]
        assert status == 200
        assert data["ok"] is True
        stuck_info = data["mods"]["server"]["StuckMod"]
        assert stuck_info["status"] == "timeout"
        assert stuck_info["importable"] is False
        assert "超时" in stuck_info["error"]

    def test_toggle_mod_disable_and_enable(self, monkeypatch, tmp_path):
        """测试 WebUI 禁用与启用 Mod 功能"""
        cfg_file = tmp_path / "config.json"
        initial_cfg = {
            "mods": {
                "server": {"chat": "mod.read"},
                "client": {"Tool": "mod.tool"},
                "disabled": {"server": {}, "client": {}}
            }
        }
        cfg_file.write_text(json.dumps(initial_cfg), encoding="utf-8")
        monkeypatch.setattr("lib.config_loader.CONFIG_JSON", cfg_file)
        reload_config()

        # 1. 禁用 server mod: chat
        h_disable = DummyHandler(path="/api/mods/toggle", body={"name": "chat", "side": "server", "enabled": False})
        h_disable._api_toggle_mod()
        s1, d1 = h_disable.responses[0]
        assert s1 == 200
        assert d1["ok"] is True
        assert d1["enabled"] is False

        saved_cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert "chat" not in saved_cfg["mods"]["server"]
        assert saved_cfg["mods"]["disabled"]["server"]["chat"] == "mod.read"

        # 2. 重新启用 server mod: chat
        h_enable = DummyHandler(path="/api/mods/toggle", body={"name": "chat", "side": "server", "enabled": True})
        h_enable._api_toggle_mod()
        s2, d2 = h_enable.responses[0]
        assert s2 == 200
        assert d2["ok"] is True
        assert d2["enabled"] is True

        saved_cfg2 = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert saved_cfg2["mods"]["server"]["chat"] == "mod.read"
        assert "chat" not in saved_cfg2["mods"]["disabled"]["server"]

    def test_import_and_remove_mod(self, monkeypatch, tmp_path):
        """测试 WebUI 导入与移除 Mod"""
        cfg_file = tmp_path / "config.json"
        initial_cfg = {
            "mods": {
                "server": {},
                "client": {},
                "disabled": {"server": {}, "client": {}}
            }
        }
        cfg_file.write_text(json.dumps(initial_cfg), encoding="utf-8")
        monkeypatch.setattr("lib.config_loader.CONFIG_JSON", cfg_file)
        reload_config()

        # 1. 导入 Mod
        h_import = DummyHandler(path="/api/mods/import", body={
            "name": "CustomMod",
            "side": "client",
            "path": "mod.custom",
            "auto_enable": True
        })
        h_import._api_import_mod()
        s1, d1 = h_import.responses[0]
        assert s1 == 200
        assert d1["ok"] is True

        saved_cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert saved_cfg["mods"]["client"]["CustomMod"] == "mod.custom"

        # 2. 移除 Mod
        h_remove = DummyHandler(path="/api/mods/remove", body={
            "name": "CustomMod",
            "side": "client"
        })
        h_remove._api_remove_mod()
        s2, d2 = h_remove.responses[0]
        assert s2 == 200
        assert d2["ok"] is True

        saved_cfg2 = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert "CustomMod" not in saved_cfg2["mods"]["client"]

    def test_scan_mods(self, monkeypatch, tmp_path):
        """测试扫描 mod/ 目录获取未配置的可用 Mod"""
        mod_dir = tmp_path / "mod"
        mod_dir.mkdir(parents=True)
        (mod_dir / "unconfigured_mod.py").write_text("class Mod:\n    pass\n", encoding="utf-8")
        monkeypatch.setattr("webui.server.ROOT", str(tmp_path))

        fake_cfg = {"mods": {"client": {}, "server": {}, "disabled": {}}}
        monkeypatch.setattr("lib.config_loader.get_config", lambda *args, **kwargs: fake_cfg)

        h_scan = DummyHandler(path="/api/mods/scan")
        h_scan._api_scan_mods()
        s, d = h_scan.responses[0]
        assert s == 200
        assert d["ok"] is True
        names = [item["name"] for item in d["unconfigured"]]
        assert "unconfigured_mod" in names

    def test_upload_mod_file(self, monkeypatch, tmp_path):
        """测试上传 Python Mod 文件"""
        mod_dir = tmp_path / "mod"
        mod_dir.mkdir(parents=True)
        monkeypatch.setattr("webui.server.ROOT", str(tmp_path))

        h_upload = DummyHandler(path="/api/mods/upload", body={
            "filename": "my_uploaded_mod.py",
            "content": "class Mod:\n    pass\n"
        })
        h_upload._api_upload_mod()
        s, d = h_upload.responses[0]
        assert s == 200
        assert d["ok"] is True
        assert (mod_dir / "my_uploaded_mod.py").exists()
        assert (mod_dir / "my_uploaded_mod.py").read_text(encoding="utf-8") == "class Mod:\n    pass\n"


class TestModReadOnlySecurity:
    """测试访客 (guest) 与观察者 (viewer) 的严格只读防护"""

    def test_guest_cannot_toggle_mod(self):
        h = DummyHandler(path="/api/mods/toggle", body={"name": "test", "side": "client", "enabled": False}, is_guest=True)
        h._api_toggle_mod()
        s, d = h.responses[0]
        assert s == 403
        assert "无操作权限" in d["message"]

    def test_viewer_cannot_remove_mod(self):
        h = DummyHandler(path="/api/mods/remove", body={"name": "test", "side": "client"}, role="viewer")
        h._api_remove_mod()
        s, d = h.responses[0]
        assert s == 403
        assert "无操作权限" in d["message"]

    def test_guest_cannot_save_mod_config(self):
        h = DummyHandler(path="/api/mods/config", body={"name": "test", "side": "client", "content": "{}"}, is_guest=True)
        h._api_save_mod_config()
        s, d = h.responses[0]
        assert s == 403
        assert "无操作权限" in d["message"]

    def test_guest_cannot_get_mod_config(self):
        """确保访客无法读取 Mod 配置文件 (防止泄露 API Key、Token 等敏感凭据)"""
        h = DummyHandler(path="/api/mods/config?name=AI&side=client", is_guest=True)
        h._api_get_mod_config()
        s, d = h.responses[0]
        assert s == 403
        assert d["ok"] is False
        assert "访客" in d["message"]

    def test_viewer_cannot_get_mod_config(self):
        """确保只读角色 viewer 也无法读取 Mod 配置文件 (防止泄露 API Key)"""
        h = DummyHandler(path="/api/mods/config?name=AI&side=client", role="viewer")
        h._api_get_mod_config()
        s, d = h.responses[0]
        assert s == 403
        assert d["ok"] is False
        assert "访客或只读角色" in d["message"]

    def test_guest_cannot_import_or_upload(self):
        h_import = DummyHandler(path="/api/mods/import", body={"name": "test", "side": "client", "path": "mod.test"}, is_guest=True)
        h_import._api_import_mod()
        assert h_import.responses[0][0] == 403

        h_upload = DummyHandler(path="/api/mods/upload", body={"filename": "test.py", "content": "pass"}, is_guest=True)
        h_upload._api_upload_mod()
        assert h_upload.responses[0][0] == 403

    def test_guest_can_read_mods(self, monkeypatch):
        fake_cfg = {"mods": {"client": {}, "server": {}, "disabled": {}}}
        monkeypatch.setattr("lib.config_loader.get_config", lambda *args, **kwargs: fake_cfg)
        h_get = DummyHandler(path="/api/mods", is_guest=True)
        h_get._api_get_mods()
        s, d = h_get.responses[0]
        assert s == 200
        assert d["ok"] is True



