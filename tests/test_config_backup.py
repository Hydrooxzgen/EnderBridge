"""test_config_backup.py — 测试 WebUI 功能设置中的立即备份与恢复/删除/下载接口"""

import io
import json
import os
import shutil
import tempfile
import urllib.parse
import pytest
from unittest.mock import MagicMock, patch

from webui.server import WebUIHandler, ROOT
from version_manager.package import BACKUP_PREFIX


class DummyRequest:
    def makefile(self, *args, **kwargs):
        return io.BytesIO(b"")


def create_mock_handler(path="/", body=None, user_perms=None, headers=None):
    """构建用于测试 WebUIHandler 的轻量实例"""
    if headers is None:
        headers = {}
    if body is not None:
        if isinstance(body, (dict, list)):
            body_bytes = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif isinstance(body, bytes):
            body_bytes = body
        else:
            body_bytes = str(body).encode("utf-8")
        headers["Content-Length"] = str(len(body_bytes))
        rfile = io.BytesIO(body_bytes)
    else:
        rfile = io.BytesIO(b"")

    wfile = io.BytesIO()

    # 创建一个未初始化的 WebUIHandler 对象，手动装配属性
    handler = WebUIHandler.__new__(WebUIHandler)
    handler.path = path
    handler.headers = headers
    handler.rfile = rfile
    handler.wfile = wfile
    handler.client_address = ("127.0.0.1", 12345)
    handler.command = "POST"
    handler.close_connection = False

    # 模拟响应方法
    response_data = {"status": None, "headers": {}, "body": b""}

    def fake_send_response(code, message=None):
        response_data["status"] = code

    def fake_send_header(key, val):
        response_data["headers"][key] = val

    def fake_end_headers():
        pass

    handler.send_response = fake_send_response
    handler.send_header = fake_send_header
    handler.end_headers = fake_end_headers
    handler._response_data = response_data

    # 模拟用户权限
    if user_perms is None:
        user_perms = ["config", "admin"]
    handler._mock_user = {
        "username": "admin",
        "role": "admin",
        "permissions": user_perms,
    }

    return handler


@pytest.fixture
def temp_backup_env(tmp_path, monkeypatch):
    """隔离环境，确保测试不会触碰真实项目备份目录"""
    fake_root = tmp_path / "app"
    fake_root.mkdir()
    (fake_root / "main.py").write_text("# main\n")
    (fake_root / "lib").mkdir()
    (fake_root / "lib" / "test.py").write_text("# test\n")

    fake_backups_dir = fake_root / "backups"
    fake_backups_dir.mkdir()

    monkeypatch.setattr("webui.server.ROOT", str(fake_root))
    monkeypatch.setattr("webui.server._auth_user", lambda h: getattr(h, "_mock_user", {"role": None, "permissions": []}))
    monkeypatch.setattr("webui.server._audit", lambda *args, **kwargs: None)

    return fake_root, fake_backups_dir


class TestConfigBackupEndpoints:
    def test_backup_create_permission_denied(self, temp_backup_env):
        handler = create_mock_handler(path="/api/backups/create", user_perms=["chat_only"])
        handler._api_backup_create()
        output = handler.wfile.getvalue().decode("utf-8")
        assert "403" in output or "未授权" in output

    def test_backup_create_success(self, temp_backup_env):
        fake_root, _ = temp_backup_env
        handler = create_mock_handler(path="/api/backups/create", user_perms=["config"])
        handler._api_backup_create()
        output = handler.wfile.getvalue().decode("utf-8")
        res = json.loads(output)
        assert res.get("ok") is True
        assert res.get("filename").startswith(BACKUP_PREFIX)
        assert os.path.isfile(res.get("path"))

    def test_backups_list(self, temp_backup_env):
        fake_root, fake_backups_dir = temp_backup_env
        # 在 fake_backups_dir 中预置两个 zip
        b1 = fake_backups_dir / f"{BACKUP_PREFIX}20260926_100000.zip"
        b1.write_text("dummy zip content 1")
        b2 = fake_backups_dir / f"{BACKUP_PREFIX}20260926_110000.zip"
        b2.write_text("dummy zip content 2")
        os.utime(str(b1), (1000, 1000))
        os.utime(str(b2), (2000, 2000))

        handler = create_mock_handler(path="/api/update/backups", user_perms=["config"])
        handler._api_update_backups()
        output = handler.wfile.getvalue().decode("utf-8")
        res = json.loads(output)
        assert res.get("ok") is True
        backups = res.get("backups")
        assert len(backups) == 2
        assert backups[0]["filename"] == b2.name  # 最新排前面

    def test_backup_delete_path_traversal_protection(self, temp_backup_env):
        fake_root, _ = temp_backup_env
        # 尝试使用路径穿越删除系统敏感文件
        malicious_path = str(fake_root / "main.py")
        handler = create_mock_handler(
            path="/api/backups/delete",
            body={"path": malicious_path},
            user_perms=["config"]
        )
        handler._api_backup_delete()
        output = handler.wfile.getvalue().decode("utf-8")
        res = json.loads(output)
        assert res.get("ok") is False
        assert "非法备份文件名" in res.get("message")

    def test_backup_delete_success(self, temp_backup_env):
        _, fake_backups_dir = temp_backup_env
        b1 = fake_backups_dir / f"{BACKUP_PREFIX}20260926_120000.zip"
        b1.write_text("dummy zip content")

        handler = create_mock_handler(
            path="/api/backups/delete",
            body={"path": str(b1)},
            user_perms=["config"]
        )
        handler._api_backup_delete()
        output = handler.wfile.getvalue().decode("utf-8")
        res = json.loads(output)
        assert res.get("ok") is True
        assert not b1.exists()

    def test_backup_download_success(self, temp_backup_env):
        _, fake_backups_dir = temp_backup_env
        b1 = fake_backups_dir / f"{BACKUP_PREFIX}20260926_130000.zip"
        sample_bytes = b"PK\x03\x04test_zip_payload"
        b1.write_bytes(sample_bytes)

        query = urllib.parse.urlencode({"path": str(b1)})
        handler = create_mock_handler(
            path=f"/api/backups/download?{query}",
            user_perms=["config"]
        )
        handler._api_backup_download()
        output = handler.wfile.getvalue()
        assert output == sample_bytes
        assert handler._response_data["headers"].get("Content-Disposition") is not None
