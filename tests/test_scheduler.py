"""test_scheduler.py — 自动化定时任务调度引擎与 WebUI 接口测试"""

import datetime
import json
import os
import pytest
from unittest.mock import MagicMock, patch

from lib.scheduler import CronMatcher, TaskScheduler
from webui.server import WebUIHandler


# ===== CronMatcher 测试 =====

class TestCronMatcher:
    def test_valid_expressions(self):
        # 通配符
        m1 = CronMatcher("* * * * *")
        assert len(m1.fields[0]) == 60
        assert len(m1.fields[1]) == 24
        assert len(m1.fields[2]) == 31
        assert len(m1.fields[3]) == 12
        assert len(m1.fields[4]) == 7

        # 步长
        m2 = CronMatcher("*/15 */6 * * *")
        assert m2.fields[0] == {0, 15, 30, 45}
        assert m2.fields[1] == {0, 6, 12, 18}

        # 范围与枚举
        m3 = CronMatcher("1-5,10 9-11 * * 1-5")
        assert m3.fields[0] == {1, 2, 3, 4, 5, 10}
        assert m3.fields[1] == {9, 10, 11}
        assert m3.fields[4] == {1, 2, 3, 4, 5}

    def test_invalid_expressions(self):
        # 字段数错误
        with pytest.raises(ValueError, match="5 个字段"):
            CronMatcher("* * * *")
        with pytest.raises(ValueError, match="5 个字段"):
            CronMatcher("* * * * * *")

        # 数值超出范围
        with pytest.raises(ValueError):
            CronMatcher("60 * * * *")
        with pytest.raises(ValueError):
            CronMatcher("* 25 * * *")

        # 语法非法
        with pytest.raises(ValueError):
            CronMatcher("abc * * * *")
        with pytest.raises(ValueError):
            CronMatcher("*/0 * * * *")

    def test_matches_datetime(self):
        m = CronMatcher("0 4 * * *")
        # 2026-09-25 04:00:00 -> 应该匹配
        dt_match = datetime.datetime(2026, 9, 25, 4, 0, 0)
        assert m.matches(dt_match) is True

        # 2026-09-25 04:01:00 -> 不匹配
        dt_nomatch = datetime.datetime(2026, 9, 25, 4, 1, 0)
        assert m.matches(dt_nomatch) is False

    def test_next_run(self):
        m = CronMatcher("0 4 * * *")
        from_dt = datetime.datetime(2026, 9, 25, 3, 50, 0)
        nxt = m.next_run(from_dt)
        assert nxt == datetime.datetime(2026, 9, 25, 4, 0, 0)

        # 跨天匹配
        from_dt2 = datetime.datetime(2026, 9, 25, 4, 1, 0)
        nxt2 = m.next_run(from_dt2)
        assert nxt2 == datetime.datetime(2026, 9, 26, 4, 0, 0)


# ===== TaskScheduler 核心功能测试 =====

@pytest.fixture
def scheduler(tmp_path, monkeypatch):
    import lib.scheduler as sched_mod
    fake_json = str(tmp_path / "scheduler.json")
    monkeypatch.setattr(sched_mod, "SCHEDULER_JSON", fake_json)
    monkeypatch.setattr(sched_mod, "TEMP_SCHEDULER_JSON", fake_json + ".tmp")
    s = sched_mod.TaskScheduler()
    return s


class TestTaskScheduler:
    def test_default_presets_loaded(self, scheduler):
        tasks = scheduler.get_tasks()
        assert len(tasks) >= 3
        preset_ids = [t["id"] for t in tasks]
        assert "task_preset_save_all" in preset_ids
        assert "task_preset_clear_items" in preset_ids

    def test_add_task_interval(self, scheduler):
        task = scheduler.add_task({
            "name": "测试间隔任务",
            "trigger_type": "interval",
            "interval_value": 10,
            "interval_unit": "s",
            "action_type": "command",
            "action_payload": "/time set day",
        })
        assert task["id"].startswith("task_")
        assert task["name"] == "测试间隔任务"
        assert task["enabled"] is True
        assert task["next_run"] is not None

        # 能通过 ID 查询到
        found = scheduler.get_task(task["id"])
        assert found is not None
        assert found["action_payload"] == "/time set day"

    def test_add_task_cron(self, scheduler):
        task = scheduler.add_task({
            "name": "测试 Cron 任务",
            "trigger_type": "cron",
            "cron_expr": "30 2 * * *",
            "action_type": "broadcast",
            "action_payload": "深夜好",
        })
        assert task["trigger_type"] == "cron"
        assert task["next_run"] is not None

    def test_update_task(self, scheduler):
        task = scheduler.add_task({
            "name": "旧名称",
            "trigger_type": "interval",
            "interval_value": 5,
        })
        updated = scheduler.update_task(task["id"], {
            "name": "新名称",
            "interval_value": 20,
        })
        assert updated is not None
        assert updated["name"] == "新名称"
        assert updated["interval_value"] == 20

    def test_toggle_task(self, scheduler):
        task = scheduler.add_task({
            "name": "待启停任务",
            "enabled": True,
        })
        new_state = scheduler.toggle_task(task["id"])
        assert new_state is False
        assert scheduler.get_task(task["id"])["enabled"] is False

        new_state2 = scheduler.toggle_task(task["id"])
        assert new_state2 is True
        assert scheduler.get_task(task["id"])["enabled"] is True

    def test_delete_task(self, scheduler):
        task = scheduler.add_task({"name": "待删除任务"})
        tid = task["id"]
        assert scheduler.delete_task(tid) is True
        assert scheduler.get_task(tid) is None
        assert scheduler.delete_task("not_exist") is False

    def test_execute_task_without_client_skipped(self, scheduler):
        import asyncio
        # 当无 Minecraft 客户端连接时且 skip_if_no_client=True, 状态应为 skipped
        task = scheduler.add_task({
            "name": "命令任务",
            "action_type": "command",
            "action_payload": "/say 123",
            "skip_if_no_client": True,
        })
        log = asyncio.run(scheduler.execute_task(task, trigger_source="test"))
        assert log["status"] == "skipped"
        assert "跳过" in log["message"]
        assert task["last_status"] == "skipped"

        # 检查日志被记录
        logs = scheduler.get_logs()
        assert len(logs) >= 1
        assert logs[0]["task_id"] == task["id"]

    def test_execute_task_without_client_failed(self, scheduler):
        import asyncio
        # 当无客户端且 skip_if_no_client=False 时, 状态为 failed
        task = scheduler.add_task({
            "name": "强要求客户端任务",
            "action_type": "command",
            "action_payload": "/say 123",
            "skip_if_no_client": False,
        })
        log = asyncio.run(scheduler.execute_task(task, trigger_source="test"))
        assert log["status"] == "failed"


# ===== WebUI API 端点集成测试 =====

class DummyWfile:
    def __init__(self):
        self.data = b""

    def write(self, b):
        self.data += b


class DummyHandler:
    def __init__(self, path="/api/scheduler/tasks", body=None, user_perms=None):
        self.path = path
        self._body = body or {}
        self.user_perms = user_perms if user_perms is not None else ["scheduler"]
        self.headers = {"Content-Type": "application/json"}
        self.responses = []
        self.status = 200
        self.wfile = DummyWfile()

    def send_response(self, status):
        self.status = status

    def send_header(self, k, v):
        pass

    def end_headers(self):
        pass

    def _read_body(self):
        return self._body

    def _respond(self, data, status=200, content_type="application/json"):
        self.responses.append((status, data))

    def _respond_denied(self):
        self.responses.append((401, {"ok": False, "message": "未授权"}))


# 动态绑定 WebUIHandler 对应的方法
DummyHandler._api_scheduler_get_tasks = WebUIHandler._api_scheduler_get_tasks
DummyHandler._api_scheduler_get_logs = WebUIHandler._api_scheduler_get_logs
DummyHandler._api_scheduler_add_task = WebUIHandler._api_scheduler_add_task
DummyHandler._api_scheduler_update_task = WebUIHandler._api_scheduler_update_task
DummyHandler._api_scheduler_delete_task = WebUIHandler._api_scheduler_delete_task
DummyHandler._api_scheduler_toggle_task = WebUIHandler._api_scheduler_toggle_task
DummyHandler._api_scheduler_run_task = WebUIHandler._api_scheduler_run_task


class TestSchedulerApi:
    @pytest.fixture(autouse=True)
    def setup_api_auth(self, monkeypatch):
        def fake_auth(handler):
            return {
                "username": "tester",
                "role": "admin",
                "permissions": handler.user_perms,
                "is_guest": False,
            }
        monkeypatch.setattr("webui.server._auth_user", fake_auth)
        monkeypatch.setattr("webui.server._audit", lambda *args, **kwargs: None)

    def test_api_permission_denied(self):
        handler = DummyHandler(user_perms=["dashboard"])  # 缺少 scheduler 权限
        handler._api_scheduler_get_tasks()
        assert len(handler.responses) == 1
        status, data = handler.responses[0]
        assert status == 403
        assert data["ok"] is False

    def test_api_get_tasks_and_logs(self):
        handler = DummyHandler()
        handler._api_scheduler_get_tasks()
        assert len(handler.responses) == 1
        status, data = handler.responses[0]
        assert status == 200
        assert data["ok"] is True
        assert isinstance(data["tasks"], list)

        log_handler = DummyHandler(path="/api/scheduler/logs")
        log_handler._api_scheduler_get_logs()
        status, log_data = log_handler.responses[0]
        assert status == 200
        assert log_data["ok"] is True
        assert isinstance(log_data["logs"], list)

    def test_api_crud_task(self):
        # 1. 创建任务
        create_h = DummyHandler(body={
            "name": "API 任务",
            "trigger_type": "interval",
            "interval_value": 60,
            "action_type": "command",
            "action_payload": "/save-all",
        })
        create_h._api_scheduler_add_task()
        status, res = create_h.responses[0]
        assert status == 200
        assert res["ok"] is True
        task_id = res["task"]["id"]

        # 2. 修改任务
        update_h = DummyHandler(body={
            "id": task_id,
            "name": "API 任务改名",
            "interval_value": 120,
        })
        update_h._api_scheduler_update_task()
        assert update_h.responses[0][1]["ok"] is True
        assert update_h.responses[0][1]["task"]["name"] == "API 任务改名"

        # 3. 切换状态
        toggle_h = DummyHandler(body={"id": task_id})
        toggle_h._api_scheduler_toggle_task()
        assert toggle_h.responses[0][1]["ok"] is True
        assert "enabled" in toggle_h.responses[0][1]

        # 4. 删除任务
        del_h = DummyHandler(body={"id": task_id})
        del_h._api_scheduler_delete_task()
        assert del_h.responses[0][1]["ok"] is True
