"""tests/test_warp.py — Home & Warp 传送模组单元测试"""
import asyncio
import json
import os
import pytest

from mod.warp import Mod, _read_warps, _save_warps, _read_homes, _save_homes, WARPS_JSON, HOMES_JSON
from lib.permission import PermissionManager
from lib.security_guard import _is_official_mod_allowed_target


class DummyClient:
    def __init__(self):
        self.sent_messages = []
        self.commands_run = []
        self.pos = {"x": 100.5, "y": 64.0, "z": 200.5, "dimension": 0}

    def tell(self, msg: str, target: str = "@a"):
        self.sent_messages.append((target, msg))

    async def runCommand(self, cmd: str):
        self.commands_run.append(cmd)
        return {"body": {"statusCode": 0, "statusMessage": "Command executed successfully"}}

    async def getLocation(self, target: str):
        return dict(self.pos)

    async def getPosition(self, target: str):
        return {"x": self.pos["x"], "y": self.pos["y"], "z": self.pos["z"]}


class TestWarpMod:
    @pytest.fixture(autouse=True)
    def setup_cleanup(self, tmp_path, monkeypatch):
        # 隔离 warps.json 与 homes.json 到临时目录
        test_warps_file = str(tmp_path / "warps.json")
        test_homes_file = str(tmp_path / "homes.json")
        monkeypatch.setattr("mod.warp.WARPS_JSON", test_warps_file)
        monkeypatch.setattr("mod.warp.HOMES_JSON", test_homes_file)
        yield

    def test_warp_command_structure(self):
        client = DummyClient()
        mod = Mod(client)
        cmds = mod.onCommand()
        assert "normal" in cmds
        cmd_names = [c.name for c in cmds["normal"]]
        assert "home" in cmd_names
        assert "warp" in cmd_names

    def test_home_set_and_tp_persistent(self):
        client = DummyClient()
        mod = Mod(client)

        # 1. 帮助说明
        asyncio.run(mod._cmd_home("Steve", "help"))
        assert any("家 (Home) 传送点帮助" in msg for _, msg in client.sent_messages)

        # 2. 设置家 (持久化存储)
        asyncio.run(mod._cmd_home("Steve", "set", "base"))
        saved = _read_homes()
        assert "Steve" in saved
        assert "base" in saved["Steve"]
        assert saved["Steve"]["base"]["x"] == 100.5

        # 3. 玩家数据隔离: Alex 查不到 Steve 的家
        asyncio.run(mod._cmd_home("Alex", "list"))
        assert any("还没有设置任何家" in msg for _, msg in client.sent_messages)

        # 4. 模拟程序重启: 重新创建 Mod 实例，数据依然从磁盘读取
        new_mod = Mod(client)
        asyncio.run(new_mod._cmd_home("Steve", "list"))
        assert any("我的家列表" in msg for _, msg in client.sent_messages)

        # 5. 传送到家
        asyncio.run(new_mod._cmd_home("Steve", "tp", "base"))
        tp_cmds = [cmd for cmd in client.commands_run if cmd.startswith("tp Steve")]
        assert len(tp_cmds) > 0
        assert "100.50 64.00 200.50" in tp_cmds[0]

        # 6. 简写 $home base
        asyncio.run(new_mod._cmd_home("Steve", "base"))
        assert len([cmd for cmd in client.commands_run if cmd.startswith("tp Steve")]) == 2

        # 7. 删除家
        asyncio.run(new_mod._cmd_home("Steve", "del", "base"))
        assert "base" not in _read_homes().get("Steve", {})

    def test_warp_set_perm_restricted(self, monkeypatch):
        client = DummyClient()
        mod = Mod(client)

        # 模拟普通玩家权限 (perm=0)
        async def mock_query(sender):
            return 0
        monkeypatch.setattr(PermissionManager, "query", mock_query)

        # 普通玩家 set 应该被拒绝，且返回状态 status 为 False
        res = asyncio.run(mod._cmd_warp("Alex", "set", "shop"))
        assert res.get("status") is False
        assert "权限受限" in res.get("message")
        assert any("权限受限" in msg for _, msg in client.sent_messages)
        assert _read_warps() == {}

        # 模拟 OP 玩家权限 (perm=2)
        async def mock_query_op(sender):
            return 2
        monkeypatch.setattr(PermissionManager, "query", mock_query_op)

        # OP 玩家 set 应该成功
        res_op = asyncio.run(mod._cmd_warp("Admin", "set", "shop"))
        assert res_op.get("status") is True
        warps = _read_warps()
        assert "shop" in warps
        assert warps["shop"]["x"] == 100.5

        # 传送
        res_tp = asyncio.run(mod._cmd_warp("Alex", "tp", "shop"))
        assert res_tp.get("status") is True
        assert any(cmd.startswith("tp Alex") for cmd in client.commands_run)

    def test_audit_log_records_fail_on_permission_denied(self, monkeypatch):
        """测试权限不足时，审计日志记录为 [FAIL] 且附带原因，而不是错误的 [OK]"""
        from lib.mods import ClientModManager
        from lib.logger import audit_log

        client = DummyClient()
        mgr = ClientModManager.__new__(ClientModManager)
        mgr.client = client
        mod = Mod(client)
        cmd_map = mod.onCommand()
        warp_cmd = cmd_map["normal"][1]  # warp command

        async def mock_query(sender):
            return 0

        monkeypatch.setattr(PermissionManager, "query", mock_query)

        # 异步执行 execute
        asyncio.run(mgr.execute("Alex", "$warp set secret_shop", [warp_cmd]))

        # 查询审计日志记录
        result = audit_log.query(type_="command")
        records = result["records"]
        assert len(records) > 0
        latest = records[0]
        assert "[FAIL]" in latest["message"]
        assert "权限受限" in latest["message"]
        assert "[OK]" not in latest["message"]

    def test_security_guard_allows_warp_data_files(self):
        """测试安全防护守卫允许官方 warp.py 操作 warps.json 与 homes.json，但阻止非法配置操作"""
        # 合法数据文件与临时文件应放行
        assert _is_official_mod_allowed_target("warp.py", "config/warps.json") is True
        assert _is_official_mod_allowed_target("warp.py", "config/warps.json.tmp_12345") is True
        assert _is_official_mod_allowed_target("warp.py", "config/homes.json") is True
        assert _is_official_mod_allowed_target("warp.py", "config/homes.json.tmp_12345") is True
        assert _is_official_mod_allowed_target("warp.py", "warps.json.tmp_123 -> warps.json") is True

        # 非法目标文件 (核心系统配置) 必须严禁放行
        assert _is_official_mod_allowed_target("warp.py", "config/config.json") is False
        assert _is_official_mod_allowed_target("warp.py", "config/users.json") is False
        assert _is_official_mod_allowed_target("warp.py", "config/permission.json") is False
        assert _is_official_mod_allowed_target("warp.py", "config/banlist.json") is False

        # 非官方 Mod 严禁放行任何文件
        assert _is_official_mod_allowed_target("thirdparty.py", "config/warps.json") is False
