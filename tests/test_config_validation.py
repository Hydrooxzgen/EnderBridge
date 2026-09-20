"""test_config_validation.py — 配置文件保存与 JSON 格式校验测试"""

import json
import os
import tempfile
import pytest

from webui.server import save_config, load_config


class TestConfigValidation:
    def test_save_config_merging(self, monkeypatch, tmp_path):
        """测试 save_config 能够正常合并表单字段并生成合法 JSON 文件"""
        fake_json = tmp_path / "config.json"
        monkeypatch.setattr("webui.server.CONFIG_JSON", str(fake_json))
        monkeypatch.setattr("webui.server.CONFIG_PY", str(tmp_path / "config.py"))

        form_data = {
            "name": "TestServer",
            "port": 9999,
            "commandPrefix": "#",
            "logLevel": "debug",
            "features": {"chat": True},
            "rateLimit": {"burst": 10},
            "mods": {"client": {"Test": "mod.test"}},
            "ai": {
                "baseURL": "https://api.openai.com/v1",
                "apiKey": "sk-fake",
                "chatModel": "gpt-4o",
            },
            "utils": {"tellAllToTell": True},
            "sapi": {"host": "127.0.0.1", "port": 19132},
            "webui": {"port": 18888, "localOnly": True},
        }

        save_config(form_data)

        assert fake_json.exists()
        with open(fake_json, "r", encoding="utf-8") as f:
            saved = json.load(f)

        assert saved["wsConfig"]["name"] == "TestServer"
        assert saved["wsConfig"]["port"] == 9999
        assert saved["commandPrefix"] == "#"
        assert saved["logLevel"] == "debug"
        assert saved["AIConfig"]["options"]["baseURL"] == "https://api.openai.com/v1"
        assert saved["AIConfig"]["options"]["apiKey"] == "sk-fake"
        assert saved["AIConfig"]["models"]["chat"]["model"] == "gpt-4o"
        assert saved["webuiConfig"]["port"] == 18888
        assert saved["webuiConfig"]["localOnly"] is True

    def test_save_config_handles_corrupt_existing_json(self, monkeypatch, tmp_path):
        """测试旧 config.json 损坏或为空时，save_config 不应崩溃且能安全恢复"""
        fake_json = tmp_path / "config.json"
        fake_json.write_text("{ corrupt json ...", encoding="utf-8")
        monkeypatch.setattr("webui.server.CONFIG_JSON", str(fake_json))
        monkeypatch.setattr("webui.server.CONFIG_PY", str(tmp_path / "nonexistent.py"))

        form_data = {
            "name": "RecoveredServer",
            "port": 8800,
        }

        save_config(form_data)

        with open(fake_json, "r", encoding="utf-8") as f:
            saved = json.load(f)

        assert saved["wsConfig"]["name"] == "RecoveredServer"
        assert saved["wsConfig"]["port"] == 8800

    def test_save_and_load_update_config_auto_backup(self, monkeypatch, tmp_path):
        """测试 updateConfig.autoBackup 的保存与加载"""
        fake_json = tmp_path / "config.json"
        monkeypatch.setattr("webui.server.CONFIG_JSON", str(fake_json))
        monkeypatch.setattr("webui.server.CONFIG_PY", str(tmp_path / "nonexistent.py"))

        # 测试关闭自动备份
        form_data = {
            "name": "TestServer",
            "updateConfig": {"autoBackup": False},
        }
        save_config(form_data)

        with open(fake_json, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved.get("updateConfig", {}).get("autoBackup") is False

        # 测试通过 load_config 读取
        loaded = load_config()
        assert loaded.get("updateConfig", {}).get("autoBackup") is False

        # 测试开启自动备份
        form_data["updateConfig"]["autoBackup"] = True
        save_config(form_data)
        loaded = load_config()
        assert loaded.get("updateConfig", {}).get("autoBackup") is True


