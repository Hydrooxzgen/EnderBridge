"""tests/test_tpa.py — TPA 玩家互传系统单元测试"""
import asyncio
import time
import pytest

from mod.tpa import Mod


class DummyClient:
    def __init__(self):
        self.sent_messages = []
        self.commands_run = []
        self.players = {
            '"Steve"': {"x": 100.0, "y": 64.0, "z": 200.0, "dimension": 0},
            '"Alex"': {"x": 500.0, "y": 70.0, "z": -300.0, "dimension": 0},
            '"NetherBob"': {"x": 50.0, "y": 120.0, "z": 80.0, "dimension": 1},
        }

    def tell(self, msg: str, target: str = "@a"):
        self.sent_messages.append((target, msg))

    async def runCommand(self, cmd: str):
        self.commands_run.append(cmd)
        return {"body": {"statusCode": 0, "statusMessage": "Command executed successfully"}}

    async def getLocation(self, target: str):
        return self.players.get(target)


class TestTPAMod:
    def test_tpa_command_structure(self):
        client = DummyClient()
        mod = Mod(client)
        cmds = mod.onCommand()
        assert "normal" in cmds
        cmd_names = [c.name for c in cmds["normal"]]
        assert "tpa" in cmd_names
        assert "tpahere" in cmd_names
        assert "tpaccept" in cmd_names
        assert "tpdeny" in cmd_names
        assert "tpcancel" in cmd_names

        # Check aliases
        tpa_cmd = next(c for c in cmds["normal"] if c.name == "tpa")
        assert "call" in tpa_cmd.aliases
        tpaccept_cmd = next(c for c in cmds["normal"] if c.name == "tpaccept")
        assert "tpyes" in tpaccept_cmd.aliases
        assert "agree" in tpaccept_cmd.aliases

    def test_cannot_tpa_to_self(self):
        client = DummyClient()
        mod = Mod(client)
        res = asyncio.run(mod._cmd_tpa("Steve", "Steve"))
        assert res["status"] is False
        assert any("不能对自己发起传送" in msg for _, msg in client.sent_messages)

    def test_tpa_offline_player(self):
        client = DummyClient()
        mod = Mod(client)
        res = asyncio.run(mod._cmd_tpa("Steve", "UnknownPlayer"))
        assert res["status"] is False
        assert any("未找到玩家" in msg for _, msg in client.sent_messages)

    def test_successful_tpa_and_accept(self):
        client = DummyClient()
        mod = Mod(client)

        # 1. Steve 发起 tpa 到 Alex
        res = asyncio.run(mod._cmd_tpa("Steve", "Alex"))
        assert res["status"] is True
        assert any("已向玩家" in msg for t, msg in client.sent_messages if t == "Steve")
        assert any("请求传送到你所在位置" in msg for t, msg in client.sent_messages if t == "Alex")

        # 2. Alex 同意请求
        client.sent_messages.clear()
        res_accept = asyncio.run(mod._cmd_tpaccept("Alex"))
        assert res_accept["status"] is True
        # 应该执行 tp Steve Alex
        assert any('tp "Steve" "Alex"' in cmd for cmd in client.commands_run)
        assert any("传送完成" in msg for t, msg in client.sent_messages if t == "Steve")
        assert any("已同意传送请求" in msg for t, msg in client.sent_messages if t == "Alex")

    def test_cross_dimension_tpa(self):
        client = DummyClient()
        mod = Mod(client)

        # Steve (Overworld, 0) 请求传送到 NetherBob (Nether, 1)
        res = asyncio.run(mod._cmd_tpa("Steve", "NetherBob"))
        assert res["status"] is True

        res_accept = asyncio.run(mod._cmd_tpaccept("NetherBob"))
        assert res_accept["status"] is True
        # 跨维度传送应使用 execute in 1 run tp
        assert any("execute in 1 run tp" in cmd for cmd in client.commands_run)

    def test_tpahere_flow(self):
        client = DummyClient()
        mod = Mod(client)

        # Steve 邀请 Alex 传送到 Steve 身边
        res = asyncio.run(mod._cmd_tpahere("Steve", "Alex"))
        assert res["status"] is True
        assert any("邀请你传送到对方身边" in msg for t, msg in client.sent_messages if t == "Alex")

        # Alex 同意前往 -> Alex 传送到 Steve
        client.commands_run.clear()
        res_accept = asyncio.run(mod._cmd_tpaccept("Alex"))
        assert res_accept["status"] is True
        assert any('tp "Alex" "Steve"' in cmd for cmd in client.commands_run)

    def test_tpa_deny(self):
        client = DummyClient()
        mod = Mod(client)

        # Steve 发起 tpa 到 Alex
        asyncio.run(mod._cmd_tpa("Steve", "Alex"))
        client.sent_messages.clear()

        # Alex 拒绝
        res_deny = asyncio.run(mod._cmd_tpdeny("Alex"))
        assert res_deny["status"] is True
        assert any("已拒绝来自玩家" in msg for t, msg in client.sent_messages if t == "Alex")
        assert any("拒绝了你的传送请求" in msg for t, msg in client.sent_messages if t == "Steve")

        # 再次同意应提示无请求
        res_accept = asyncio.run(mod._cmd_tpaccept("Alex"))
        assert res_accept["status"] is False

    def test_tpa_cancel(self):
        client = DummyClient()
        mod = Mod(client)

        # Steve 发起 tpa 到 Alex，随后取消
        asyncio.run(mod._cmd_tpa("Steve", "Alex"))
        res_cancel = asyncio.run(mod._cmd_tpcancel("Steve"))
        assert res_cancel["status"] is True
        assert any("已取消向玩家" in msg for t, msg in client.sent_messages if t == "Steve")

        # Alex 此时同意应失败
        res_accept = asyncio.run(mod._cmd_tpaccept("Alex"))
        assert res_accept["status"] is False

    def test_tpa_timeout(self):
        client = DummyClient()
        mod = Mod(client)

        # Steve 发起请求
        asyncio.run(mod._cmd_tpa("Steve", "Alex"))
        key = ("steve", "alex")
        assert key in mod.requests

        # 模拟超时 (超过 60 秒)
        mod.requests[key]["created_at"] = time.time() - 70

        # Alex 尝试同意 -> 应判定为超时并拒绝
        res_accept = asyncio.run(mod._cmd_tpaccept("Alex"))
        assert res_accept["status"] is False
        assert any("请求已超时" in msg for _, msg in client.sent_messages)

    def test_cooldown_rejection(self):
        client = DummyClient()
        mod = Mod(client)

        # 第一次成功
        res1 = asyncio.run(mod._cmd_tpa("Steve", "Alex"))
        assert res1["status"] is True

        # 取消请求后立即重新发起 -> 触发冷却
        asyncio.run(mod._cmd_tpcancel("Steve"))
        res2 = asyncio.run(mod._cmd_tpa("Steve", "Alex"))
        assert res2["status"] is False
        assert any("操作过于频繁" in msg for _, msg in client.sent_messages)

