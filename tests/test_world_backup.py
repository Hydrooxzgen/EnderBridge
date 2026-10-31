"""tests/test_world_backup.py — 世界存档备份与快照管理引擎单元测试"""

import asyncio
import os
import shutil
import time
import zipfile
import pytest

from lib.world_backup import WorldDetector, WorldBackupManager, _format_size
from mod.backup import Mod
from lib.permission import PermissionManager


class DummyClient:
    def __init__(self):
        self.sent_messages = []
        self.commands_run = []
        self.is_open = True

    def tell(self, msg: str, target: str = "@a"):
        self.sent_messages.append((target, msg))

    async def runCommand(self, cmd: str):
        self.commands_run.append(cmd)
        return {"body": {"statusCode": 0, "statusMessage": "Command executed successfully"}}


@pytest.fixture
def mock_mc_worlds_dir(tmp_path):
    """创建一个模拟的 Minecraft 世界存储目录结构"""
    base = tmp_path / "mock_minecraftWorlds"
    base.mkdir()

    # 世界 1: SurvivalWorld (较早修改)
    w1 = base / "world_alpha_1"
    w1.mkdir()
    (w1 / "levelname.txt").write_text("我的生存世界", encoding="utf-8")
    (w1 / "level.dat").write_bytes(b"MOCK_LEVEL_DAT_ALPHA")
    db1 = w1 / "db"
    db1.mkdir()
    (db1 / "000001.ldb").write_bytes(b"LDB_CHUNK_DATA_1")

    time.sleep(0.05)

    # 世界 2: CreativeServer (较新修改)
    w2 = base / "world_beta_2"
    w2.mkdir()
    (w2 / "levelname.txt").write_text("创造建筑大厅", encoding="utf-8")
    (w2 / "level.dat").write_bytes(b"MOCK_LEVEL_DAT_BETA")
    db2 = w2 / "db"
    db2.mkdir()
    (db2 / "CURRENT").write_bytes(b"MANIFEST-000001")

    # 非世界目录 (干扰项)
    fake = base / "not_a_world"
    fake.mkdir()
    (fake / "readme.txt").write_text("hello", encoding="utf-8")

    return str(base)


class TestWorldDetector:
    def test_inspect_world_dir(self, mock_mc_worlds_dir):
        w1_path = os.path.join(mock_mc_worlds_dir, "world_alpha_1")
        info = WorldDetector.inspect_world_dir(w1_path)
        assert info is not None
        assert info["world_name"] == "我的生存世界"
        assert info["folder_name"] == "world_alpha_1"
        assert info["size_bytes"] > 0
        assert "B" in info["size_formatted"] or "KB" in info["size_formatted"]

        # 非法目录返回 None
        fake_path = os.path.join(mock_mc_worlds_dir, "not_a_world")
        assert WorldDetector.inspect_world_dir(fake_path) is None

    def test_detect_all_worlds(self, mock_mc_worlds_dir):
        worlds = WorldDetector.detect_all_worlds(custom_dir=mock_mc_worlds_dir)
        assert len(worlds) == 2
        # 按修改时间降序排序，后创建修改的在前面
        assert worlds[0]["world_name"] == "创造建筑大厅"
        assert worlds[0]["is_most_recent"] is True
        assert worlds[1]["world_name"] == "我的生存世界"
        assert worlds[1]["is_most_recent"] is False

    def test_get_active_world(self, mock_mc_worlds_dir):
        active = WorldDetector.get_active_world(custom_dir=mock_mc_worlds_dir)
        assert active is not None
        assert active["world_name"] == "创造建筑大厅"


class TestWorldBackupManager:
    @pytest.fixture
    def manager_setup(self, tmp_path, mock_mc_worlds_dir):
        backup_dir = str(tmp_path / "backups")
        mgr = WorldBackupManager(backup_dir=backup_dir, custom_world_dir=mock_mc_worlds_dir)
        return mgr, mock_mc_worlds_dir, backup_dir

    def test_create_and_list_snapshot(self, manager_setup):
        mgr, worlds_dir, backup_dir = manager_setup

        # 1. 自动针对活跃世界制作快照
        snap = mgr.create_snapshot(tag="test_point")
        assert snap["world_name"] == "创造建筑大厅"
        assert snap["filename"].endswith(".mcworld")
        assert "test_point" in snap["filename"]
        assert os.path.isfile(snap["file_path"])
        assert snap["file_count"] >= 3

        # 校验 zip 内文件结构
        with zipfile.ZipFile(snap["file_path"], "r") as zf:
            namelist = zf.namelist()
            assert "levelname.txt" in namelist
            assert "level.dat" in namelist
            assert any(f.startswith("db/") for f in namelist)

        # 2. 查询列表
        snapshots = mgr.list_snapshots()
        assert len(snapshots) == 1
        assert snapshots[0]["snapshot_id"] == snap["snapshot_id"]
        assert snapshots[0]["tag"] == "test_point"

    def test_pin_and_rotation(self, manager_setup):
        mgr, worlds_dir, backup_dir = manager_setup

        # 创建 4 个快照
        s1 = mgr.create_snapshot(tag="first")
        s2 = mgr.create_snapshot(tag="second")
        s3 = mgr.create_snapshot(tag="third")
        s4 = mgr.create_snapshot(tag="fourth")

        # 锁定第 1 个快照
        assert mgr.set_pin(s1["snapshot_id"], pinned=True) is True
        assert mgr.list_snapshots()[-1]["pinned"] is True

        # 设置配额为 2 (非 pinned 应该只保留最新的 2 个: s4, s3; s2 应该被清理; s1 锁定永久保留)
        cleaned = mgr.rotate_snapshots(max_keep=2)
        assert s2["filename"] in cleaned
        assert s1["filename"] not in cleaned

        remaining_ids = [s["snapshot_id"] for s in mgr.list_snapshots()]
        assert s1["snapshot_id"] in remaining_ids
        assert s3["snapshot_id"] in remaining_ids
        assert s4["snapshot_id"] in remaining_ids
        assert s2["snapshot_id"] not in remaining_ids

    def test_delete_and_restore(self, manager_setup, tmp_path):
        mgr, worlds_dir, backup_dir = manager_setup

        snap = mgr.create_snapshot(tag="restore_test")
        sid = snap["snapshot_id"]

        # 测试解压恢复
        restore_dir = str(tmp_path / "restored_world")
        res = mgr.restore_snapshot(sid, restore_dir)
        assert res["status"] is True
        assert os.path.isfile(os.path.join(restore_dir, "levelname.txt"))
        assert os.path.isfile(os.path.join(restore_dir, "level.dat"))

        # 测试删除
        assert mgr.delete_snapshot(sid) is True
        assert not os.path.isfile(snap["file_path"])
        assert len(mgr.list_snapshots()) == 0


class TestWorldBackupMod:
    @pytest.fixture(autouse=True)
    def setup_mod(self, tmp_path, mock_mc_worlds_dir, monkeypatch):
        backup_dir = str(tmp_path / "backups")
        self.client = DummyClient()
        self.mod = Mod(self.client)
        self.mod.manager = WorldBackupManager(backup_dir=backup_dir, custom_world_dir=mock_mc_worlds_dir)

        # 默认模拟管理员权限 (OP: perm=2)
        async def mock_admin_perm(sender):
            return 2

        monkeypatch.setattr(PermissionManager, "query", mock_admin_perm)

    def test_backup_command_structure(self):
        cmds = self.mod.onCommand()
        assert "normal" in cmds
        cmd_names = [c.name for c in cmds["normal"]]
        assert "backup" in cmd_names

        b_cmd = next(c for c in cmds["normal"] if c.name == "backup")
        assert "bak" in b_cmd.aliases
        assert "snapshot" in b_cmd.aliases

    def test_backup_help(self):
        res = asyncio.run(self.mod._cmd_backup("Admin", "help"))
        assert res["status"] is True
        assert any("世界存档备份与快照帮助" in msg for _, msg in self.client.sent_messages)

    def test_backup_worlds_listing(self):
        res = asyncio.run(self.mod._cmd_backup("Admin", "worlds"))
        assert res["status"] is True
        assert any("已探测到的世界存档" in msg for _, msg in self.client.sent_messages)
        assert any("创造建筑大厅" in msg for _, msg in self.client.sent_messages)

    def test_backup_create_and_list_flow(self):
        # 1. 创建快照
        res = asyncio.run(self.mod._cmd_backup("Admin", "create", "manual_backup"))
        assert res["status"] is True
        assert "save-all" in self.client.commands_run
        assert any("世界快照已成功创建" in msg for _, msg in self.client.sent_messages)

        # 2. 查看快照列表
        self.client.sent_messages.clear()
        res_list = asyncio.run(self.mod._cmd_backup("Admin", "list"))
        assert res_list["status"] is True
        assert any("世界快照列表" in msg for _, msg in self.client.sent_messages)
        assert any("manual_backup" in msg for _, msg in self.client.sent_messages)

    def test_backup_pin_unpin_delete(self):
        # 先创建一个快照
        asyncio.run(self.mod._cmd_backup("Admin", "create"))
        self.client.sent_messages.clear()

        # 锁定第 1 个快照
        res_pin = asyncio.run(self.mod._cmd_backup("Admin", "pin", "1"))
        assert res_pin["status"] is True
        assert any("已锁定" in msg for _, msg in self.client.sent_messages)

        # 尝试删除处于锁定状态的快照 -> 应当被拒绝
        self.client.sent_messages.clear()
        res_del_blocked = asyncio.run(self.mod._cmd_backup("Admin", "delete", "1"))
        assert res_del_blocked["status"] is False
        assert any("处于锁定保护状态" in msg for _, msg in self.client.sent_messages)

        # 解锁
        self.client.sent_messages.clear()
        res_unpin = asyncio.run(self.mod._cmd_backup("Admin", "unpin", "1"))
        assert res_unpin["status"] is True
        assert any("已解除锁定" in msg for _, msg in self.client.sent_messages)

        # 再次删除 -> 成功
        self.client.sent_messages.clear()
        res_del = asyncio.run(self.mod._cmd_backup("Admin", "delete", "1"))
        assert res_del["status"] is True
        assert any("已成功删除快照" in msg for _, msg in self.client.sent_messages)

    def test_non_admin_permission_denied(self, monkeypatch):
        async def mock_normal_perm(sender):
            return 1

        monkeypatch.setattr(PermissionManager, "query", mock_normal_perm)
        res = asyncio.run(self.mod._cmd_backup("NormalPlayer", "create"))
        assert res["status"] is False
        assert any("仅管理员" in msg for _, msg in self.client.sent_messages)
