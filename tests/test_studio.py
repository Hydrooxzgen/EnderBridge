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
    get_block_color,
    parse_blueprint_voxels,
    generate_standalone_blueprint_html,
    preview_blueprint_locally,
    CATEGORIES,
)
from webui.server import WebUIHandler


class DummyWfile:
    def __init__(self):
        self.data = b""

    def write(self, b):
        self.data += b


class DummyHandler:
    def __init__(self, path="/api/studio/assets", body=None, user_perms=None, headers=None):
        self.path = path
        self._body = body or {}
        self.user_perms = user_perms if user_perms is not None else ["mods"]
        self.headers = headers or {"Content-Type": "application/json"}
        self.responses = []
        self.response_headers = {}
        self.wfile = DummyWfile()
        self.status = 200

    def send_response(self, status):
        self.status = status

    def send_header(self, k, v):
        self.response_headers[k] = v

    def end_headers(self):
        pass

    def _read_body(self):
        return self._body

    def _respond(self, data, status=200, content_type="application/json"):
        self.responses.append((status, data))

    def _respond_denied(self):
        self.responses.append((401, {"ok": False, "message": "未登录"}))


DummyHandler._api_studio_get_assets = WebUIHandler._api_studio_get_assets
DummyHandler._api_studio_get_palette = WebUIHandler._api_studio_get_palette
DummyHandler._api_studio_get_blueprint_voxels = WebUIHandler._api_studio_get_blueprint_voxels
DummyHandler._api_studio_post_blueprint_voxels = WebUIHandler._api_studio_post_blueprint_voxels
DummyHandler._api_studio_get_blueprint_html = WebUIHandler._api_studio_get_blueprint_html
DummyHandler._api_studio_upload = WebUIHandler._api_studio_upload
DummyHandler._api_studio_save_text = WebUIHandler._api_studio_save_text
DummyHandler._api_studio_delete_asset = WebUIHandler._api_studio_delete_asset
DummyHandler._api_studio_action = WebUIHandler._api_studio_action
DummyHandler._api_studio_textures_status = WebUIHandler._api_studio_textures_status
DummyHandler._api_studio_textures_download = WebUIHandler._api_studio_textures_download
DummyHandler._api_studio_textures_uninstall = WebUIHandler._api_studio_textures_uninstall


@pytest.fixture(autouse=True)
def mock_perms(monkeypatch):
    monkeypatch.setattr(
        "webui.server._require_permission",
        lambda perm: (lambda handler: True if perm in handler.user_perms else (handler._respond({"ok": False, "message": f"需要 {perm} 权限"}, status=403) or False))
    )
    monkeypatch.setattr(
        "webui.server._auth_user",
        lambda handler: {
            "role": "admin" if getattr(handler, "user_perms", None) else None,
            "permissions": getattr(handler, "user_perms", []) or [],
        }
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


class TestStudioBlueprint:
    def test_get_block_color(self):
        # 1. 关键词推断
        assert get_block_color("minecraft:cherry_stairs") == "#f4a6b8"
        assert get_block_color("oak_planks") == "#b8945f"
        assert get_block_color("deepslate_tiles") == "#4d4d52"
        assert get_block_color("glass") == "#99d9ea"

        # 2. blocks.json 调色板匹配
        assert get_block_color("black_concrete") == "#151515"

        # 3. 未知方块哈希稳定降级 (返回以 # 开头的 7 位 HEX 颜色)
        col = get_block_color("unknown_custom_block_xyz")
        assert col.startswith("#")
        assert len(col) == 7

    def test_parse_blueprint_voxels_real(self):
        # 使用项目内自带的真实蓝图: 樱花塔.litematic
        res = parse_blueprint_voxels("ezmatic", "樱花塔.litematic")
        assert res["name"] == "樱花塔.litematic"
        assert res["format"] == "litematic"
        assert res["dimensions"]["x"] == 15
        assert res["dimensions"]["y"] == 46
        assert res["dimensions"]["z"] == 15
        assert res["totalBlocks"] == 1050
        assert res["renderedBlocks"] == 1050
        assert res["minY"] == 0
        assert res["maxY"] == 45
        assert len(res["palette"]) > 0
        assert len(res["voxels"]) == 1050
        # 验证每个体素结构为 [x, y, z, pal_idx]
        first_voxel = res["voxels"][0]
        assert len(first_voxel) == 4
        pal_idx = first_voxel[3]
        assert 0 <= pal_idx < len(res["palette"])
        assert "color" in res["palette"][pal_idx]

    def test_api_blueprint_voxels(self):
        # 测试 WebUI API 接口
        handler = DummyHandler(path="/api/studio/blueprint-voxels?file=樱花塔.litematic")
        handler._api_studio_get_blueprint_voxels()
        status, data = handler.responses[0]
        assert status == 200
        assert data["ok"] is True
        assert data["name"] == "樱花塔.litematic"
        assert len(data["voxels"]) == 1050

    def test_api_blueprint_voxels_not_found(self):
        handler = DummyHandler(path="/api/studio/blueprint-voxels?file=nonexistent.litematic")
        handler._api_studio_get_blueprint_voxels()
        status, data = handler.responses[0]
        assert status == 404
        assert data["ok"] is False

    def test_api_blueprint_voxels_invalid_format(self, tmp_path, monkeypatch):
        monkeypatch.setattr("lib.studio.ROOT", str(tmp_path))
        (tmp_path / "resources" / "ezmatic").mkdir(parents=True)
        (tmp_path / "resources" / "ezmatic" / "sample.mcstructure").write_bytes(b"dummy")

        handler = DummyHandler(path="/api/studio/blueprint-voxels?file=sample.mcstructure")
        handler._api_studio_get_blueprint_voxels()
        status, data = handler.responses[0]
        assert status == 400
        assert data["ok"] is False

    def test_parse_blueprint_voxels_from_arbitrary_path(self):
        real_file = os.path.abspath("resources/ezmatic/樱花塔.litematic")
        res = parse_blueprint_voxels(file_path=real_file)
        assert res["name"] == "樱花塔.litematic"
        assert res["totalBlocks"] == 1050

    def test_generate_standalone_blueprint_html(self):
        real_file = os.path.abspath("resources/ezmatic/樱花塔.litematic")
        data = parse_blueprint_voxels(file_path=real_file)
        html = generate_standalone_blueprint_html(data)
        assert "<!DOCTYPE html>" in html
        assert "樱花塔.litematic" in html
        assert "const DATA =" in html
        assert "blueprintCanvas" in html

    def test_preview_blueprint_locally(self, tmp_path):
        out_file = str(tmp_path / "custom_preview.html")
        path = preview_blueprint_locally(
            target="樱花塔.litematic",
            export_path=out_file,
            open_browser=False
        )
        assert path == out_file
        assert os.path.isfile(out_file)
        assert os.path.getsize(out_file) > 1000

    def test_api_post_blueprint_voxels(self):
        import base64
        real_file = "resources/ezmatic/樱花塔.litematic"
        with open(real_file, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("ascii")

        handler = DummyHandler(body={
            "filename": "uploaded_cherry.litematic",
            "dataBase64": b64_data,
        })
        handler._api_studio_post_blueprint_voxels()
        status, data = handler.responses[0]
        assert status == 200
        assert data["ok"] is True
        assert data["name"] == "uploaded_cherry.litematic"
        assert len(data["voxels"]) == 1050

    def test_api_get_blueprint_html(self):
        handler = DummyHandler(path="/api/studio/blueprint-html?file=樱花塔.litematic")
        handler._api_studio_get_blueprint_html()
        assert handler.status == 200
        assert "text/html" in handler.response_headers.get("Content-Type", "")
        assert b"<!DOCTYPE html>" in handler.wfile.data
        assert b"const DATA =" in handler.wfile.data

    def test_resolve_block_texture_filenames(self):
        from lib.studio import resolve_block_texture_filenames
        sample_avail = {
            "cherry_planks.png", "cherry_log.png", "cherry_log_top.png",
            "stripped_cherry_log.png", "stripped_cherry_log_top.png",
            "andesite.png", "iron_chain.png", "oak_planks.png", "bookshelf.png",
            "grass_block_top.png", "grass_block_side.png"
        }
        # 直接匹配
        top, side = resolve_block_texture_filenames("minecraft:cherry_planks", sample_avail)
        assert top == "cherry_planks.png"
        assert side == "cherry_planks.png"

        # 原木顶面与侧面
        top, side = resolve_block_texture_filenames("minecraft:cherry_log", sample_avail)
        assert top == "cherry_log_top.png"
        assert side == "cherry_log.png"

        # 台阶/楼梯推断
        top, side = resolve_block_texture_filenames("minecraft:cherry_stairs", sample_avail)
        assert top == "cherry_planks.png"

        # 墙推断
        top, side = resolve_block_texture_filenames("minecraft:andesite_wall", sample_avail)
        assert top == "andesite.png"

        # 特殊方块
        top, side = resolve_block_texture_filenames("minecraft:chain", sample_avail)
        assert top == "iron_chain.png"
        top, side = resolve_block_texture_filenames("minecraft:bookshelf", sample_avail)
        assert top == "oak_planks.png"
        assert side == "bookshelf.png"

    def test_ensure_minecraft_textures(self):
        from lib.studio import ensure_minecraft_textures
        count = ensure_minecraft_textures()
        assert count > 50

    def test_blueprint_palette_has_textures(self):
        res = parse_blueprint_voxels("ezmatic", "樱花塔.litematic")
        first_pal = res["palette"][0]
        assert "textures" in first_pal
        assert "top" in first_pal["textures"]
        assert "side" in first_pal["textures"]

    def test_standalone_html_with_embedded_textures(self):
        real_file = os.path.abspath("resources/ezmatic/樱花塔.litematic")
        data = parse_blueprint_voxels(file_path=real_file)
        html = generate_standalone_blueprint_html(data)
        assert "data:image/png;base64" in html
        assert "btnToggleTex" in html
        assert "drawTexturedParallelogram" in html


class TestStudioTextureManagement:
    def test_get_textures_status(self):
        from lib.studio import get_textures_status
        stat = get_textures_status()
        assert "installed" in stat
        assert "count" in stat
        assert "size_bytes" in stat
        assert "size_formatted" in stat
        assert "directory" in stat
        assert "default_url" in stat

    def test_uninstall_and_get_status(self, tmp_path, monkeypatch):
        import lib.studio as studio_mod
        test_dir = tmp_path / "textures" / "blocks"
        test_dir.mkdir(parents=True, exist_ok=True)
        # 写入假纹理和 .gitkeep
        (test_dir / ".gitkeep").write_text("# keep")
        (test_dir / "stone.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
        (test_dir / "dirt.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")

        monkeypatch.setattr(studio_mod, "BLOCK_TEXTURES_DIR", str(test_dir))

        stat_before = studio_mod.get_textures_status()
        assert stat_before["installed"] is True
        assert stat_before["count"] == 2

        # 卸载
        res = studio_mod.uninstall_textures()
        assert res["ok"] is True
        assert res["deleted_count"] == 2

        # 验证 .gitkeep 仍保留
        assert (test_dir / ".gitkeep").exists()
        assert not (test_dir / "stone.png").exists()
        assert not (test_dir / "dirt.png").exists()

        stat_after = studio_mod.get_textures_status()
        assert stat_after["installed"] is False
        assert stat_after["count"] == 0
        assert stat_after["size_bytes"] == 0

    def test_download_online_textures_mock(self, tmp_path, monkeypatch):
        import lib.studio as studio_mod
        import zipfile
        import io

        test_dir = tmp_path / "textures" / "blocks"
        test_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(studio_mod, "BLOCK_TEXTURES_DIR", str(test_dir))

        # 构建模拟的 ZIP 压缩包数据
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("assets/minecraft/textures/block/oak_planks.png", b"\x89PNG\r\nfake_oak")
            zf.writestr("assets/minecraft/textures/block/stone.png", b"\x89PNG\r\nfake_stone")
        zip_bytes = zip_buffer.getvalue()

        class MockResponse:
            def __init__(self, data):
                self.data = data
            def read(self):
                return self.data
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=15: MockResponse(zip_bytes))

        res = studio_mod.download_online_textures(source_url="https://example.com/assets.zip")
        assert res["ok"] is True
        assert res["download_count"] == 2
        assert (test_dir / "oak_planks.png").exists()
        assert (test_dir / "stone.png").exists()

    def test_api_texture_endpoints_and_permissions(self, tmp_path, monkeypatch):
        import lib.studio as studio_mod
        test_dir = tmp_path / "textures" / "blocks"
        test_dir.mkdir(parents=True, exist_ok=True)
        (test_dir / "glass.png").write_bytes(b"test")
        monkeypatch.setattr(studio_mod, "BLOCK_TEXTURES_DIR", str(test_dir))

        # 1. 正常具有 config 权限
        h_status = DummyHandler(path="/api/studio/textures/status", user_perms=["config"])
        h_status._api_studio_textures_status()
        s, data = h_status.responses[0]
        assert s == 200
        assert data["ok"] is True
        assert data["data"]["count"] == 1

        # 2. 正常具有 mods 权限
        h_mods = DummyHandler(path="/api/studio/textures/status", user_perms=["mods"])
        h_mods._api_studio_textures_status()
        s, data = h_mods.responses[0]
        assert s == 200
        assert data["ok"] is True

        # 3. 访客无权限
        h_guest = DummyHandler(path="/api/studio/textures/status", user_perms=[])
        h_guest._api_studio_textures_status()
        s, data = h_guest.responses[0]
        assert s == 401
        assert data["ok"] is False

        # 4. 卸载 API
        h_un = DummyHandler(path="/api/studio/textures/uninstall", user_perms=["config"])
        h_un._api_studio_textures_uninstall()
        s, data = h_un.responses[0]
        assert s == 200
        assert data["ok"] is True
        assert not (test_dir / "glass.png").exists()


