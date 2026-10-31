"""tests/test_world_backup_webui.py — 世界存档备份 WebUI 接口与路由单元测试"""

import json
import os
import io
import time
import pytest
from lib.world_backup import WorldBackupManager, WorldDetector
from webui.server import WebUIHandler
import webui.server as ws_mod


@pytest.fixture
def mock_mc_worlds_dir(tmp_path):
    """创建模拟 Minecraft 世界存储结构"""
    base = tmp_path / "minecraftWorlds"
    base.mkdir()

    w1 = base / "world_alpha"
    w1.mkdir()
    (w1 / "levelname.txt").write_text("生存测试服", encoding="utf-8")
    (w1 / "level.dat").write_bytes(b"MOCK_ALPHA_DAT")
    db1 = w1 / "db"
    db1.mkdir()
    (db1 / "0001.ldb").write_bytes(b"LDB_DATA")

    return str(base)


@pytest.fixture
def setup_webui_handler(tmp_path, mock_mc_worlds_dir, monkeypatch):
    """构造 mock 的 WebUIHandler 实例与隔离目录环境"""
    backup_dir = str(tmp_path / "backups_worlds")
    handler = WebUIHandler.__new__(WebUIHandler)
    handler.command = "GET"
    handler.path = "/api/world_backup/list"

    # Mock response collector
    sent = {}
    def mock_respond(data, status=200):
        sent["data"] = data
        sent["status"] = status
    handler._respond = mock_respond

    # Mock send_response & headers for download
    dl_headers = {}
    dl_status = []
    wfile = io.BytesIO()
    handler.send_response = lambda code: dl_status.append(code)
    handler.send_header = lambda k, v: dl_headers.update({k: v})
    handler.end_headers = lambda: None
    handler.wfile = wfile

    # 强制权限检查放行
    monkeypatch.setattr(ws_mod, "_require_permission", lambda perm: (lambda h: True))
    monkeypatch.setattr(ws_mod, "_require_write_permission", lambda perm: (lambda h: True))

    # 构造 WorldBackupManager 绑定
    mgr = WorldBackupManager(backup_dir=backup_dir, custom_world_dir=mock_mc_worlds_dir)
    monkeypatch.setattr(handler, "_get_world_backup_manager", lambda: mgr)

    # Mock load_config / save_config
    cfg_store = {
        "features": {
            "world_backup": {
                "enabled": True,
                "interval_minutes": 30,
                "max_snapshots": 5,
                "notify_in_game": True,
                "custom_world_dir": mock_mc_worlds_dir,
            }
        }
    }
    monkeypatch.setattr(ws_mod, "load_config", lambda: cfg_store)
    def mock_save_config(new_cfg):
        cfg_store.clear()
        cfg_store.update(new_cfg)
    monkeypatch.setattr(ws_mod, "save_config", mock_save_config)

    return handler, mgr, sent, dl_status, dl_headers, wfile


class TestWorldBackupWebUI:
    def test_page_routing_served(self, monkeypatch):
        """测试 /world_backup 页面能够被正确路由至 world_backup.html"""
        handler = WebUIHandler.__new__(WebUIHandler)
        served_pages = []
        handler._serve_page = lambda page: served_pages.append(page)
        handler._check_ban = lambda: False
        handler.path = "/world_backup"
        handler.do_GET()
        assert "world_backup.html" in served_pages

    def test_api_world_backup_worlds(self, setup_webui_handler):
        """测试探测基岩版世界 API 返回正确列表"""
        handler, mgr, sent, _, _, _ = setup_webui_handler
        handler._api_world_backup_worlds()
        data = sent.get("data", {})
        assert data.get("ok") is True
        assert data.get("count") >= 1
        assert any(w["world_name"] == "生存测试服" for w in data.get("worlds", []))
        assert data.get("active_world") is not None

    def test_api_world_backup_create_list_flow(self, setup_webui_handler):
        """测试创建快照与列表查询完整生命周期"""
        handler, mgr, sent, _, _, _ = setup_webui_handler

        # 1. 创建快照
        handler.command = "POST"
        handler._read_body = lambda: {"tag": "WebUI_Snapshot_1", "flush_save": False}
        handler._api_world_backup_create()
        create_data = sent.get("data", {})
        assert create_data.get("ok") is True
        snap = create_data.get("snapshot")
        assert snap["tag"] == "WebUI_Snapshot_1"
        assert os.path.isfile(snap["file_path"])

        # 2. 查询列表
        handler.command = "GET"
        handler._api_world_backup_list()
        list_data = sent.get("data", {})
        assert list_data.get("ok") is True
        assert list_data.get("count") == 1
        assert list_data.get("snapshots")[0]["snapshot_id"] == snap["snapshot_id"]

    def test_api_world_backup_pin_and_delete(self, setup_webui_handler):
        """测试快照锁定、防误删保护与解锁后删除"""
        handler, mgr, sent, _, _, _ = setup_webui_handler

        # 先创建一个快照
        snap = mgr.create_snapshot(tag="pin_test")
        sid = snap["snapshot_id"]

        # 1. 锁定快照
        handler.command = "POST"
        handler._read_body = lambda: {"snapshot_id": sid, "pinned": True}
        handler._api_world_backup_pin()
        assert sent.get("data", {}).get("ok") is True
        assert sent.get("data", {}).get("pinned") is True

        # 2. 尝试删除处于锁定状态的快照 -> 拒绝删除
        sent.clear()
        handler._read_body = lambda: {"snapshot_id": sid}
        handler._api_world_backup_delete()
        assert sent.get("data", {}).get("ok") is False
        assert "锁定保护" in sent.get("data", {}).get("message", "")

        # 3. 解除锁定
        sent.clear()
        handler._read_body = lambda: {"snapshot_id": sid, "pinned": False}
        handler._api_world_backup_pin()
        assert sent.get("data", {}).get("ok") is True

        # 4. 再次删除 -> 成功
        sent.clear()
        handler._read_body = lambda: {"snapshot_id": sid}
        handler._api_world_backup_delete()
        assert sent.get("data", {}).get("ok") is True
        assert len(mgr.list_snapshots()) == 0

    def test_api_world_backup_download(self, setup_webui_handler):
        """测试下载快照文件及目录越权拦截防护"""
        handler, mgr, sent, dl_status, dl_headers, wfile = setup_webui_handler

        snap = mgr.create_snapshot(tag="dl_test")
        sid = snap["snapshot_id"]

        # 1. 正常下载
        handler.path = f"/api/world_backup/download?id={sid}"
        handler._api_world_backup_download()
        assert 200 in dl_status
        assert "attachment" in dl_headers.get("Content-Disposition", "")
        assert len(wfile.getvalue()) > 0

        # 2. 路径穿越与非法访问拦截
        sent.clear()
        handler.path = "/api/world_backup/download?file=../../secret.txt"
        handler._api_world_backup_download()
        assert sent.get("data", {}).get("ok") is False

    def test_api_world_backup_config(self, setup_webui_handler):
        """测试读取与更新自动定时备份配置"""
        handler, mgr, sent, _, _, _ = setup_webui_handler

        # 1. 读取配置
        handler._api_world_backup_get_config()
        cfg_data = sent.get("data", {})
        assert cfg_data.get("ok") is True
        assert cfg_data.get("config", {}).get("interval_minutes") == 30

        # 2. 保存新配置
        sent.clear()
        handler._read_body = lambda: {
            "enabled": True,
            "interval_minutes": 45,
            "max_snapshots": 8,
            "notify_in_game": False,
        }
        handler._api_world_backup_save_config()
        save_data = sent.get("data", {})
        assert save_data.get("ok") is True
        assert save_data.get("config", {}).get("interval_minutes") == 45
        assert save_data.get("config", {}).get("max_snapshots") == 8

