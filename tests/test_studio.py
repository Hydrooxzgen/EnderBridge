"""test_studio.py — 游戏资产与蓝图工坊 (Studio) 核心服务与 WebUI 接口测试"""

import os
import json
import pytest
from pathlib import Path
from PIL import Image

from lib.studio import (
    sanitize_filename,
    get_base_path,
    save_asset_file,
    delete_asset_file,
    get_asset_file_path,
    list_assets,
    extract_mcfunc_metadata,
    extract_image_metadata,
    get_block_palette,
    CATEGORIES,
)
from webui.server import WebUIHandler


class DummyHandler:
    def __init__(self, path="/api/studio/assets", body=None, user_perms=None, headers=None):
        self.path = path
        self._body = body or {}
        self.user_perms = user_perms if user_perms is not None else ["mods"]
        self.headers = headers or {"Content-Type": "application/json"}
        self.responses = []

    def _read_body(self):
        return self._body

    def _respond(self, data, status=200, content_type="application/json"):
        self.responses.append((status, data))

    def _respond_denied(self):
        self.responses.append((401, {"ok": False, "message": "未登录"}))


DummyHandler._api_studio_get_assets = WebUIHandler._api_studio_get_assets
DummyHandler._api_studio_get_palette = WebUIHandler._api_studio_get_palette
DummyHandler._api_studio_upload = WebUIHandler._api_studio_upload
DummyHandler._api_studio_save_text = WebUIHandler._api_studio_save_text
DummyHandler._api_studio_delete_asset = WebUIHandler._api_studio_delete_asset
DummyHandler._api_studio_action = WebUIHandler._api_studio_action


@pytest.fixture(autouse=True)
def mock_perms(monkeypatch):
    monkeypatch.setattr(
        "webui.server._require_permission",
        lambda perm: (lambda handler: True if perm in handler.user_perms else (handler._respond({"ok": False, "message": f"需要 {perm} 权限"}, status=403) or False))
    )


class TestStudioSecurity:
    def test_sanitize_filename_valid(self):
        assert sanitize_filename("song.mid") == "song.mid"
        assert sanitize_filename("my_blueprint.litematic") == "my_blueprint.litematic"
        assert sanitize_filename("中文测试.mcfunc") == "中文测试.mcfunc"

    def test_sanitize_filename_path_traversal(self):
        with pytest.raises(ValueError):
            sanitize_filename("../secret.json")
        with pytest.raises(ValueError):
            sanitize_filename("folder/file.mid")
        with pytest.raises(ValueError):
            sanitize_filename("folder\\file.mid")
        with pytest.raises(ValueError):
            sanitize_filename(".hidden")
        with pytest.raises(ValueError):
            sanitize_filename("")
        with pytest.raises(ValueError):
            sanitize_filename("a" * 150)


class TestStudioFileOperations:
    def test_save_and_delete_asset(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.studio.ROOT", str(tmp_path))
        cat_dir = tmp_path / "resources" / "mcfunc"
        cat_dir.mkdir(parents=True)

        # 1. 保存文件
        content = b"# Test MCFunc\nsay Hello World\n"
        res = save_asset_file("mcfunc", "test.mcfunc", content)
        assert res["ok"] is True
        saved_file = cat_dir / "test.mcfunc"
        assert saved_file.exists()
        assert saved_file.read_bytes() == content

        # 2. 覆盖保存生成 .bak 备份
        new_content = b"say New Command\n"
        save_asset_file("mcfunc", "test.mcfunc", new_content)
        bak_file = cat_dir / "test.mcfunc.bak"
        assert bak_file.exists()
        assert bak_file.read_bytes() == content
        assert saved_file.read_bytes() == new_content

        # 3. 删除文件
        del_res = delete_asset_file("mcfunc", "test.mcfunc")
        assert del_res["ok"] is True
        assert not saved_file.exists()

    def test_save_invalid_extension(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.studio.ROOT", str(tmp_path))
        with pytest.raises(ValueError, match="不受支持的文件扩展名"):
            save_asset_file("midi", "virus.exe", b"malicious data")


class TestStudioMetadata:
    def test_extract_mcfunc_metadata(self, tmp_path):
        f = tmp_path / "sample.mcfunc"
        f.write_text(
            "# Header comment\n\nsay 1\nsay 2\n# Footer comment\n",
            encoding="utf-8"
        )
        meta = extract_mcfunc_metadata(str(f))
        assert meta["total_lines"] == 5
        assert meta["command_lines"] == 2
        assert meta["comment_lines"] == 2

    def test_extract_image_metadata(self, tmp_path):
        img_path = tmp_path / "test.png"
        img = Image.new("RGB", (120, 80), color="blue")
        img.save(str(img_path))

        meta = extract_image_metadata(str(img_path))
        assert meta["width"] == 120
        assert meta["height"] == 80
        assert meta["format"] == "PNG"

    def test_get_block_palette(self):
        palette = get_block_palette()
        assert isinstance(palette, list)
        assert len(palette) > 0
        assert "id" in palette[0]
        assert "rgb" in palette[0]


class TestStudioAPI:
    def test_api_get_assets_and_palette(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.studio.ROOT", str(tmp_path))
        midi_dir = tmp_path / "resources" / "midi"
        midi_dir.mkdir(parents=True)
        (midi_dir / "dummy.mid").write_bytes(b"MThd\x00\x00\x00\x06\x00\x00\x00\x01\x01\xe0")

        handler = DummyHandler(path="/api/studio/assets?category=midi")
        handler._api_studio_get_assets()
        status, data = handler.responses[0]
        assert status == 200
        assert data["ok"] is True
        assert len(data["assets"]) == 1
        assert data["assets"][0]["name"] == "dummy.mid"

        # 测试获取调色板
        h_palette = DummyHandler()
        h_palette._api_studio_get_palette()
        p_status, p_data = h_palette.responses[0]
        assert p_status == 200
        assert p_data["ok"] is True
        assert len(p_data["blocks"]) > 0

    def test_api_save_text_and_delete(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.studio.ROOT", str(tmp_path))
        (tmp_path / "resources" / "mcfunc").mkdir(parents=True)

        # 保存
        handler = DummyHandler(body={
            "category": "mcfunc",
            "filename": "hello.mcfunc",
            "content": "say Studio Online\n",
        })
        handler._api_studio_save_text()
        status, data = handler.responses[0]
        assert status == 200
        assert data["ok"] is True

        # 删除
        h_del = DummyHandler(body={
            "category": "mcfunc",
            "filename": "hello.mcfunc",
        })
        h_del._api_studio_delete_asset()
        d_status, d_data = h_del.responses[0]
        assert d_status == 200
        assert d_data["ok"] is True

    def test_permission_denied_for_guest(self):
        handler = DummyHandler(path="/api/studio/assets", user_perms=["dashboard"])
        handler._api_studio_get_assets()
        status, data = handler.responses[0]
        assert status == 403
        assert data["ok"] is False

