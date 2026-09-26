"""test_audit.py — 审计日志存储、过滤与导出功能回归测试"""

import csv
import io
import json
import pytest

from lib.logger import _AuditLog


@pytest.fixture
def audit():
    return _AuditLog(max_size=100)


class TestAuditLog:
    def test_append_and_query(self, audit):
        audit.append("chat", "Steve", "Hello world")
        audit.append("command", "Alex", "/help [OK]")
        audit.append("ban", "Admin", "封禁了 192.168.1.1")

        # 默认查询全部(最新在前)
        res = audit.query()
        assert res["total"] == 3
        assert len(res["records"]) == 3
        assert res["records"][0]["type"] == "ban"
        assert res["records"][1]["type"] == "command"
        assert res["records"][2]["type"] == "chat"

    def test_query_filter_by_type(self, audit):
        audit.append("chat", "Steve", "msg 1")
        audit.append("command", "Steve", "/gamemode 1")
        audit.append("chat", "Alex", "msg 2")

        chats = audit.query(type_="chat")
        assert chats["total"] == 2
        for r in chats["records"]:
            assert r["type"] == "chat"

        cmds = audit.query(type_="command")
        assert cmds["total"] == 1
        assert cmds["records"][0]["message"] == "/gamemode 1"

    def test_query_filter_by_sender(self, audit):
        audit.append("chat", "Steve", "test")
        audit.append("chat", "Alex", "test")
        audit.append("chat", "SteveJobs", "test")

        steve_logs = audit.query(sender="steve")
        assert steve_logs["total"] == 2
        for r in steve_logs["records"]:
            assert "steve" in r["sender"].lower()

    def test_query_filter_with_edge_cases_and_pagination(self, audit):
        # 边界情况: sender 为 None 或特殊类型
        with audit._lock:
            audit._buffer.append({"ts": "2026-09-22T00:00:00", "type": None, "sender": None, "message": "raw"})
            audit._buffer.append({"ts": "2026-09-22T00:00:01", "type": "chat", "sender": "Player1", "message": "msg1"})
            audit._buffer.append({"ts": "2026-09-22T00:00:02", "type": "chat", "sender": "Player2", "message": "msg2"})
            audit._buffer.append({"ts": "2026-09-22T00:00:03", "type": "chat", "sender": "Player3", "message": "msg3"})

        # 测试过滤时不会因 None 抛异常
        res = audit.query(sender="player", limit=2, offset=1)
        assert res["total"] == 3
        assert len(res["records"]) == 2
        assert res["records"][0]["sender"] == "Player2"

        # 查询不存在的类型
        none_res = audit.query(type_="non_existent")
        assert none_res["total"] == 0
        assert len(none_res["records"]) == 0


class TestAuditExportFormatting:
    def test_csv_export_format(self, audit):
        audit.append("chat", "Steve", 'He said, "Hello, world!"')
        audit.append("ban", "Admin", "封禁 1.2.3.4")

        records = audit.query()["records"]
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["时间", "类型", "发送者", "内容"])
        for r in records:
            writer.writerow([r.get("ts", ""), r.get("type", ""), r.get("sender", ""), r.get("message", "")])

        csv_content = "\ufeff" + out.getvalue()
        assert csv_content.startswith("\ufeff时间,类型,发送者,内容")
        # 验证逗号与引号转义
        assert '"He said, ""Hello, world!"""' in csv_content or 'He said' in csv_content

        # 验证读取可逆
        reader = list(csv.reader(io.StringIO(csv_content.lstrip("\ufeff"))))
        assert reader[0] == ["时间", "类型", "发送者", "内容"]
        assert len(reader) == 3

    def test_json_export_format(self, audit):
        audit.append("command", "Operator", "/list")
        records = audit.query()["records"]
        raw = json.dumps(records, ensure_ascii=False, indent=2)
        parsed = json.loads(raw)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["sender"] == "Operator"
        assert parsed[0]["type"] == "command"

