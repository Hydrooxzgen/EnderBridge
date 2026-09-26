"""自动化定时任务计划引擎 (Task Scheduler)

纯 Python 原生实现,支持固定时间间隔 (Interval) 与标准 5 字段 Cron 表达式,
无需依赖任何外部第三方 pip 库。
持久化存储于 config/scheduler.json,支持热增删改查、手动测试运行与执行历史审计。
"""

import asyncio
import datetime
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")
SCHEDULER_JSON = os.path.join(CONFIG_DIR, "scheduler.json")
TEMP_SCHEDULER_JSON = os.path.join(CONFIG_DIR, "scheduler.json.tmp")

# ===== 纯 Python 原生 5 字段 Cron 表达式解析与匹配器 =====

class CronMatcher:
    """标准 5 字段 Cron 匹配器: 分 时 日 月 周

    字段定义:
      - 分钟: 0-59
      - 小时: 0-23
      - 日期: 1-31
      - 月份: 1-12
      - 星期: 0-6 (0=周日, 1=周一, ..., 6=周六; 兼容 7=周日)
    支持语法:
      - 通配符: *
      - 步长: */5, 1-30/2
      - 范围: 1-5, 9-17
      - 列表: 1,3,5
    """

    RANGES = [
        (0, 59),  # minute
        (0, 23),  # hour
        (1, 31),  # day of month
        (1, 12),  # month
        (0, 6),   # day of week (0=Sunday)
    ]

    def __init__(self, expr: str):
        self.expr = (expr or "").strip()
        parts = self.expr.split()
        if len(parts) != 5:
            raise ValueError(f"Cron 表达式必须包含 5 个字段 (当前为 {len(parts)} 个): '{expr}'")
        self.fields = [self._parse_field(parts[i], self.RANGES[i][0], self.RANGES[i][1], is_dow=(i == 4)) for i in range(5)]

    @classmethod
    def _parse_field(cls, part: str, min_val: int, max_val: int, is_dow: bool = False) -> set:
        values = set()
        for sub in part.split(","):
            sub = sub.strip()
            if not sub:
                continue
            step = 1
            if "/" in sub:
                base, step_str = sub.split("/", 1)
                try:
                    step = int(step_str)
                    if step <= 0:
                        raise ValueError()
                except ValueError:
                    raise ValueError(f"Cron 步长必须为正整数: '{sub}'")
            else:
                base = sub

            if base == "*":
                start, end = min_val, max_val
            elif "-" in base:
                start_str, end_str = base.split("-", 1)
                try:
                    start, end = int(start_str), int(end_str)
                except ValueError:
                    raise ValueError(f"Cron 范围格式错误: '{base}'")
            else:
                try:
                    val = int(base)
                    start, end = val, val
                except ValueError:
                    raise ValueError(f"Cron 字段数值非法: '{base}'")

            if is_dow:
                if start == 7:
                    start = 0
                if end == 7:
                    end = 0

            if start > end and base != "*":
                raise ValueError(f"Cron 起始值大于结束值: '{base}'")

            start = max(min_val, start)
            end = min(max_val, end)
            for v in range(start, end + 1, step):
                values.add(v)

        if not values:
            raise ValueError(f"Cron 字段无有效取值: '{part}'")
        return values

    def matches(self, dt: datetime.datetime) -> bool:
        """检查指定 datetime 是否满足 Cron 触发规则"""
        dow = dt.weekday()
        dow_cron = 0 if dow == 6 else dow + 1  # Python: 0=Mon..6=Sun -> Cron: 0=Sun..6=Sat
        return (
            dt.minute in self.fields[0] and
            dt.hour in self.fields[1] and
            dt.day in self.fields[2] and
            dt.month in self.fields[3] and
            dow_cron in self.fields[4]
        )

    def next_run(self, from_dt: Optional[datetime.datetime] = None) -> datetime.datetime:
        """计算下一次触发的 datetime (精度为整分钟)"""
        if from_dt is None:
            from_dt = datetime.datetime.now()
        # 从下一分钟第 0 秒开始搜索
        cur = from_dt.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)
        # 最多搜索 366 天 (527040 分钟),防止死循环
        max_minutes = 527040
        for _ in range(max_minutes):
            if self.matches(cur):
                return cur
            cur += datetime.timedelta(minutes=1)
        return cur


# ===== 默认预置任务示例 =====
DEFAULT_PRESET_TASKS = [
    {
        "id": "task_preset_save_all",
        "name": "定时全服自动保存",
        "enabled": False,
        "trigger_type": "interval",
        "interval_value": 30,
        "interval_unit": "m",
        "cron_expr": "",
        "action_type": "command",
        "action_payload": "/save-all\n/say [系统] 全服数据自动保存完成",
        "skip_if_no_client": True,
        "broadcast_type": "chat",
        "description": "每 30 分钟触发一次游戏世界保存指令并广播提示",
    },
    {
        "id": "task_preset_clear_items",
        "name": "每日地面掉落物清理",
        "enabled": False,
        "trigger_type": "cron",
        "interval_value": 1,
        "interval_unit": "d",
        "cron_expr": "0 4 * * *",
        "action_type": "command",
        "action_payload": "/say [警告] 地面掉落物将在 10 秒后自动清理！\n/kill @e[type=item]",
        "skip_if_no_client": True,
        "broadcast_type": "chat",
        "description": "每天凌晨 04:00 清理无用地面实体掉落物以优化服务器性能",
    },
    {
        "id": "task_preset_announcement",
        "name": "服规与温馨提示轮播",
        "enabled": False,
        "trigger_type": "interval",
        "interval_value": 15,
        "interval_unit": "m",
        "cron_expr": "",
        "action_type": "broadcast",
        "action_payload": "§b[EnderBridge] §f欢迎来到服务器！请遵守服规，文明游戏。遇到问题可联系管理员。",
        "skip_if_no_client": True,
        "broadcast_type": "chat",
        "description": "每 15 分钟向全服玩家发送一条温馨提示广播",
    }
]


class TaskScheduler:
    """自动化定时任务计划调度中心 (单例)"""

    def __init__(self):
        self._tasks: List[Dict[str, Any]] = []
        self._logs: List[Dict[str, Any]] = []
        self._max_logs = 100
        self._running = False
        self._loop_task: Optional[asyncio.Task] = None
        self._last_cron_minute: Optional[str] = None
        self._lock = asyncio.Lock()
        self.load()

    def load(self) -> None:
        """从 scheduler.json 加载任务配置,不存在时初始化默认配置"""
        if not os.path.exists(CONFIG_DIR):
            os.makedirs(CONFIG_DIR, exist_ok=True)

        if not os.path.isfile(SCHEDULER_JSON):
            self._tasks = [dict(t) for t in DEFAULT_PRESET_TASKS]
            self._recalculate_all_next_runs()
            self.save()
            return

        try:
            with open(SCHEDULER_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._tasks = data
            elif isinstance(data, dict) and "tasks" in data:
                self._tasks = data["tasks"]
            else:
                self._tasks = [dict(t) for t in DEFAULT_PRESET_TASKS]
        except Exception:
            self._tasks = [dict(t) for t in DEFAULT_PRESET_TASKS]

        self._recalculate_all_next_runs()

    def save(self) -> None:
        """持久化保存任务列表至 scheduler.json (原子写入)"""
        try:
            with open(TEMP_SCHEDULER_JSON, "w", encoding="utf-8") as f:
                json.dump(self._tasks, f, ensure_ascii=False, indent=2)
            os.replace(TEMP_SCHEDULER_JSON, SCHEDULER_JSON)
        except Exception as e:
            pass

    def get_tasks(self) -> List[Dict[str, Any]]:
        """获取所有任务列表"""
        return self._tasks

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """根据 ID 获取特定任务"""
        for t in self._tasks:
            if t.get("id") == task_id:
                return t
        return None

    def get_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最近执行流水日志"""
        return list(reversed(self._logs[-limit:]))

    def _append_log(self, record: Dict[str, Any]) -> None:
        """记录一条执行流水"""
        self._logs.append(record)
        if len(self._logs) > self._max_logs:
            self._logs.pop(0)

    def calculate_next_run(self, task: Dict[str, Any], from_time: Optional[float] = None) -> Optional[str]:
        """计算任务的下一次预估触发时间 (返回 ISO 字符串)"""
        if not task.get("enabled", False):
            return None

        now_ts = from_time if from_time is not None else time.time()
        ttype = task.get("trigger_type", "interval")

        if ttype == "interval":
            val = max(1, int(task.get("interval_value", 30)))
            unit = task.get("interval_unit", "m")
            mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(unit, 60)
            interval_sec = val * mult

            last_ts = task.get("last_run_ts")
            if not last_ts:
                # 尚未运行过:下一次在创建后或当前时间 + interval
                next_ts = now_ts + interval_sec
            else:
                next_ts = last_ts + interval_sec
                if next_ts <= now_ts:
                    # 如果已经过期,从当前对齐下一次
                    next_ts = now_ts + interval_sec
            return datetime.datetime.fromtimestamp(next_ts).isoformat(timespec="seconds")

        elif ttype == "cron":
            expr = task.get("cron_expr", "").strip()
            if not expr:
                return None
            try:
                matcher = CronMatcher(expr)
                from_dt = datetime.datetime.fromtimestamp(now_ts)
                nxt = matcher.next_run(from_dt)
                return nxt.isoformat(timespec="seconds")
            except Exception:
                return None

        return None

    def _recalculate_all_next_runs(self) -> None:
        for t in self._tasks:
            t["next_run"] = self.calculate_next_run(t)

    def add_task(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """创建新任务"""
        task_id = "task_" + uuid.uuid4().hex[:12]
        task = {
            "id": task_id,
            "name": data.get("name") or "未命名定时任务",
            "enabled": bool(data.get("enabled", True)),
            "trigger_type": data.get("trigger_type", "interval"),
            "interval_value": int(data.get("interval_value", 30)),
            "interval_unit": data.get("interval_unit", "m"),
            "cron_expr": (data.get("cron_expr") or "").strip(),
            "action_type": data.get("action_type", "command"),
            "action_payload": data.get("action_payload", ""),
            "broadcast_type": data.get("broadcast_type", "chat"),
            "skip_if_no_client": bool(data.get("skip_if_no_client", True)),
            "description": data.get("description", ""),
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "last_run": None,
            "last_run_ts": None,
            "last_status": None,
            "last_message": None,
        }
        # 校验 cron 语法
        if task["trigger_type"] == "cron":
            CronMatcher(task["cron_expr"])  # 抛出 ValueError 如果非法

        task["next_run"] = self.calculate_next_run(task)
        self._tasks.append(task)
        self.save()
        return task

    def update_task(self, task_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """修改指定任务"""
        task = self.get_task(task_id)
        if not task:
            return None

        for k in ["name", "trigger_type", "interval_unit", "action_type", "action_payload", "broadcast_type", "description"]:
            if k in data:
                task[k] = data[k]

        if "interval_value" in data:
            task["interval_value"] = max(1, int(data["interval_value"]))

        if "cron_expr" in data:
            expr = (data["cron_expr"] or "").strip()
            if task.get("trigger_type") == "cron":
                CronMatcher(expr)  # 校验合法性
            task["cron_expr"] = expr

        if "enabled" in data:
            task["enabled"] = bool(data["enabled"])

        if "skip_if_no_client" in data:
            task["skip_if_no_client"] = bool(data["skip_if_no_client"])

        task["next_run"] = self.calculate_next_run(task)
        self.save()
        return task

    def delete_task(self, task_id: str) -> bool:
        """删除指定任务"""
        for i, t in enumerate(self._tasks):
            if t.get("id") == task_id:
                self._tasks.pop(i)
                self.save()
                return True
        return False

    def toggle_task(self, task_id: str) -> Optional[bool]:
        """一键启用/禁用任务"""
        task = self.get_task(task_id)
        if not task:
            return None
        task["enabled"] = not task.get("enabled", False)
        task["next_run"] = self.calculate_next_run(task)
        self.save()
        return task["enabled"]

    async def execute_task(self, task: Dict[str, Any], trigger_source: str = "auto") -> Dict[str, Any]:
        """执行特定任务并记录日志流水"""
        from lib.current import Current

        start_time = time.time()
        task_id = task.get("id")
        task_name = task.get("name")
        action_type = task.get("action_type", "command")
        action_payload = task.get("action_payload", "")
        skip_if_no_client = task.get("skip_if_no_client", True)

        client = Current.client
        has_client = client is not None

        status = "success"
        message = ""
        output = ""

        # 检查客户端前置要求
        if action_type in ("command", "broadcast", "mcfunc") and not has_client:
            if skip_if_no_client:
                status = "skipped"
                message = "Minecraft 客户端未连接，已安全跳过执行"
            else:
                status = "failed"
                message = "无客户端连接，指令执行失败"

        if status not in ("skipped", "failed"):
            try:
                if action_type == "command":
                    # 支持多行命令顺序执行
                    lines = [l.strip() for l in action_payload.split("\n") if l.strip()]
                    results = []
                    for line in lines:
                        cmd = line
                        if cmd.startswith("$"):
                            # Mod 命令
                            from lib.command import Command
                            cmd_obj = Command(client)
                            await cmd_obj.execute(cmd, sender="Scheduler")
                            results.append(f"{cmd} -> OK")
                        else:
                            # MC 原生命令
                            res = await client.runCommand(cmd)
                            body = res.get("body", {}) if isinstance(res, dict) else {}
                            results.append(f"{cmd} -> {body.get('statusMessage') or 'OK'}")
                    output = "\n".join(results)
                    message = f"成功执行 {len(lines)} 条游戏指令"

                elif action_type == "broadcast":
                    # 广播消息
                    btype = task.get("broadcast_type", "chat")
                    text = action_payload.strip()
                    if btype == "title":
                        raw_json = json.dumps({"rawtext": [{"text": text}]})
                        await client.runCommand(f"titleraw @a title {raw_json}")
                    elif btype == "actionbar":
                        raw_json = json.dumps({"rawtext": [{"text": text}]})
                        await client.runCommand(f"titleraw @a actionbar {raw_json}")
                    else:
                        await client.runCommand(f'say {text}')
                    output = f"已广播 ({btype}): {text}"
                    message = f"已成功向全服广播消息"

                elif action_type == "mcfunc":
                    # 执行 MCFunc 脚本宏
                    from lib.studio import get_asset_file_path
                    script_name = action_payload.strip()
                    if not script_name.endswith(".mcfunc"):
                        script_name += ".mcfunc"
                    filepath = get_asset_file_path("mcfunc", script_name)
                    if not os.path.isfile(filepath):
                        raise FileNotFoundError(f"MCFunc 脚本不存在: {script_name}")
                    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                        lines = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
                    for cmd in lines:
                        await client.runCommand(cmd)
                    output = f"已执行 {len(lines)} 条指令 ({script_name})"
                    message = f"MCFunc 脚本 {script_name} 执行完毕"

                elif action_type == "backup":
                    # 自动备份配置与数据
                    from lib.package import create_export_zip
                    zip_name = f"auto_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
                    zip_path = os.path.join(ROOT, "backups", zip_name)
                    os.makedirs(os.path.join(ROOT, "backups"), exist_ok=True)
                    create_export_zip(zip_path)
                    output = f"备份文件已生成: backups/{zip_name}"
                    message = "自动化备份生成成功"

                else:
                    status = "failed"
                    message = f"未知的动作类型: {action_type}"

            except Exception as e:
                status = "failed"
                message = f"执行异常: {e}"
                output = str(e)

        cost_ms = int((time.time() - start_time) * 1000)
        now_iso = datetime.datetime.now().isoformat(timespec="seconds")

        # 更新任务状态
        task["last_run"] = now_iso
        task["last_run_ts"] = time.time()
        task["last_status"] = status
        task["last_message"] = message
        task["next_run"] = self.calculate_next_run(task)
        self.save()

        # 写入历史日志
        log_entry = {
            "id": uuid.uuid4().hex[:10],
            "task_id": task_id,
            "task_name": task_name,
            "trigger_source": trigger_source,
            "action_type": action_type,
            "status": status,
            "message": message,
            "output": output,
            "cost_ms": cost_ms,
            "timestamp": now_iso,
        }
        self._append_log(log_entry)
        return log_entry

    async def run_loop(self) -> None:
        """调度器主轮询协程 (挂载在 main.py 的事件循环中)"""
        self._running = True
        while self._running:
            try:
                now_ts = time.time()
                now_dt = datetime.datetime.fromtimestamp(now_ts)
                current_minute_str = now_dt.strftime("%Y-%m-%d %H:%M")

                is_new_minute = (current_minute_str != self._last_cron_minute)
                if is_new_minute:
                    self._last_cron_minute = current_minute_str

                for task in list(self._tasks):
                    if not task.get("enabled", False):
                        continue

                    ttype = task.get("trigger_type", "interval")
                    should_run = False

                    if ttype == "interval":
                        val = max(1, int(task.get("interval_value", 30)))
                        unit = task.get("interval_unit", "m")
                        mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(unit, 60)
                        interval_sec = val * mult

                        last_ts = task.get("last_run_ts")
                        if last_ts is None:
                            # 首次启动：更新 next_run，在满足一个周期后触发
                            task["last_run_ts"] = now_ts
                            task["next_run"] = self.calculate_next_run(task, now_ts)
                            self.save()
                        elif now_ts - last_ts >= interval_sec:
                            should_run = True

                    elif ttype == "cron" and is_new_minute:
                        expr = task.get("cron_expr", "").strip()
                        if expr:
                            try:
                                matcher = CronMatcher(expr)
                                if matcher.matches(now_dt):
                                    should_run = True
                            except Exception:
                                pass

                    if should_run:
                        asyncio.create_task(self.execute_task(task, trigger_source="auto"))

            except Exception:
                pass

            await asyncio.sleep(1)

    def stop(self) -> None:
        """停止调度器"""
        self._running = False


# 全局单例
task_scheduler = TaskScheduler()

