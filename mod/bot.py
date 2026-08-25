"""假人 Mod

通过 Node.js 子进程运行 bedrock-protocol bot,让假人作为独立玩家出现在
MCBE 服务器的 Tab 列表和游戏世界中。

命令:
  $bot spawn <名称>   - 在当前位置生成假人
  $bot remove <名称>  - 移除指定假人
  $bot move <名称>    - 将假人传送到当前位置
  $bot chat <消息>    - 以假人身份发送聊天消息
  $bot list           - 列出所有假人
  $bot start          - 启动 Bot 进程
  $bot stop           - 停止 Bot 进程
"""
import asyncio
import json
import os
import subprocess
import sys

from lib import shared
from lib.command import Command

# bot.js 路径
_BOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot")
_BOT_SCRIPT = os.path.join(_BOT_DIR, "bot.js")


def _bot_config() -> dict:
    """读取 botConfig 配置"""
    try:
        from config import botConfig
        return botConfig or {}
    except Exception:
        return {}


class BotProcess:
    """管理 Node.js bot 子进程的单例"""

    _instance = None

    def __init__(self):
        self.proc = None          # asyncio.subprocess.Process
        self.ready = False        # bot 是否已 join 游戏
        self.players = {}         # name → {x, y, z}
        self._read_task = None    # stdout 读取任务
        self._line_buf = ""       # 行缓冲

    @classmethod
    def get(cls) -> "BotProcess":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def start(self) -> dict:
        """启动 bot 子进程"""
        if self.proc and self.proc.returncode is None:
            return {"ok": False, "message": "Bot 已在运行中"}

        cfg = _bot_config()
        if not cfg:
            return {"ok": False, "message": "未配置 botConfig,请在 config.py 中添加"}

        host = cfg.get("host", "127.0.0.1")
        port = cfg.get("port", 19132)
        username = cfg.get("username", "FakeBot")
        offline = cfg.get("offline", True)
        version = cfg.get("version", None)

        # 检查 node 可用
        try:
            r = subprocess.run(["node", "--version"], capture_output=True, timeout=5)
            if r.returncode != 0:
                return {"ok": False, "message": "Node.js 不可用,请安装 Node.js"}
        except FileNotFoundError:
            return {"ok": False, "message": "未找到 node 命令,请安装 Node.js"}
        except Exception as e:
            return {"ok": False, "message": f"Node.js 检测失败: {e}"}

        # 检查依赖是否安装
        node_modules = os.path.join(_BOT_DIR, "node_modules")
        if not os.path.isdir(node_modules):
            shared.logger.info("[Bot] 首次运行,正在安装 npm 依赖...")
            try:
                r = subprocess.run(
                    ["npm", "install"],
                    cwd=_BOT_DIR,
                    capture_output=True,
                    timeout=60,
                )
                if r.returncode != 0:
                    err = r.stderr.decode("utf-8", errors="replace")[:200]
                    return {"ok": False, "message": f"npm install 失败: {err}"}
                shared.logger.info("[Bot] npm 依赖安装完成")
            except Exception as e:
                return {"ok": False, "message": f"npm install 异常: {e}"}

        # 启动子进程
        config_payload = json.dumps({
            "host": host,
            "port": port,
            "username": username,
            "offline": offline,
            "version": version,
        }, ensure_ascii=False)

        try:
            self.proc = await asyncio.create_subprocess_exec(
                "node", _BOT_SCRIPT,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=_BOT_DIR,
            )
            # 发送配置
            self.proc.stdin.write((config_payload + "\n").encode("utf-8"))
            await self.proc.stdin.drain()
        except Exception as e:
            return {"ok": False, "message": f"启动 bot 进程失败: {e}"}

        self.ready = False
        self.players = {}

        # 启动 stdout 读取
        self._read_task = asyncio.get_running_loop().create_task(self._read_stdout())

        # 启动 stderr 读取(日志)
        asyncio.get_running_loop().create_task(self._read_stderr())

        return {"ok": True, "message": f"Bot 正在连接 {host}:{port}..."}

    async def stop(self) -> dict:
        """停止 bot 子进程"""
        if not self.proc or self.proc.returncode is not None:
            return {"ok": False, "message": "Bot 未在运行"}

        try:
            self.proc.stdin.write((json.dumps({"type": "quit"}) + "\n").encode("utf-8"))
            await self.proc.stdin.drain()
            await asyncio.wait_for(self.proc.wait(), timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass

        self.ready = False
        self.players = {}
        return {"ok": True, "message": "Bot 已停止"}

    async def send_command(self, cmd: dict) -> dict:
        """向 bot 发送命令并等待响应"""
        if not self.proc or self.proc.returncode is not None:
            return {"ok": False, "message": "Bot 未运行,请先 $bot start"}

        try:
            self.proc.stdin.write((json.dumps(cmd, ensure_ascii=False) + "\n").encode("utf-8"))
            await self.proc.stdin.drain()
        except Exception as e:
            return {"ok": False, "message": f"发送命令失败: {e}"}

        # 等待响应(最多 5 秒)
        try:
            resp = await asyncio.wait_for(self._wait_response(), timeout=5)
            return resp
        except asyncio.TimeoutError:
            return {"ok": False, "message": "Bot 响应超时"}

    async def _wait_response(self) -> dict:
        """等待下一个 stdout 响应"""
        # 简单实现:轮询 self._last_resp
        # 实际用 Future 更优雅,这里用事件替代
        fut = asyncio.get_running_loop().create_future()
        self._resp_fut = fut
        try:
            return await asyncio.wait_for(fut, timeout=5)
        except asyncio.TimeoutError:
            return {"ok": False, "message": "响应超时"}

    def _on_response(self, resp: dict):
        """收到 bot 响应时调用"""
        if resp.get("type") == "join":
            self.ready = True
            shared.logger.info("[Bot] 已加入游戏")
        elif resp.get("type") == "disconnect":
            self.ready = False
            shared.logger.info(f"[Bot] 已断开: {resp.get('reason', '?')}")
        elif resp.get("type") == "error":
            shared.logger.warning(f"[Bot] 错误: {resp.get('message', '?')}")

        # 更新 players 缓存
        if resp.get("action") == "spawn" and resp.get("ok"):
            name = resp.get("name", "")
            if name not in self.players:
                self.players[name] = {"x": 0, "y": 0, "z": 0}
        elif resp.get("action") == "remove" and resp.get("ok"):
            self.players.pop(resp.get("name", ""), None)
        elif resp.get("action") == "move" and resp.get("ok"):
            name = resp.get("name", "")
            if name in self.players:
                self.players[name] = {
                    "x": resp.get("x", 0),
                    "y": resp.get("y", 0),
                    "z": resp.get("z", 0),
                }
        elif resp.get("action") == "list":
            self.players = {
                p["name"]: {"x": p["x"], "y": p["y"], "z": p["z"]}
                for p in resp.get("players", [])
            }

        # 解除 Future 等待
        fut = getattr(self, "_resp_fut", None)
        if fut and not fut.done():
            fut.set_result(resp)

    async def _read_stdout(self):
        """持续读取 bot stdout"""
        try:
            while True:
                line = await self.proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    resp = json.loads(text)
                    self._on_response(resp)
                except json.JSONDecodeError:
                    pass
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _read_stderr(self):
        """持续读取 bot stderr(日志)"""
        try:
            while True:
                line = await self.proc.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    shared.logger.debug(f"[Bot] {text}")
        except asyncio.CancelledError:
            pass
        except Exception:
            pass


class Mod:
    """假人 Mod（客户端）"""

    def __init__(self, client):
        self.client = client

    def onCommand(self):
        return {
            "op": [
                Command.create("bot", "假人管理（start/stop/spawn/remove/move/chat/list）")
                .add_string("方法", False)
                .add_optional_string("参数1")
                .add_optional_string("参数2")
                .set_func(self._cmd_bot),
            ],
        }

    # ---- 方法权限: 2=op ----
    BOT_METHODS = [
        ("start", "", "启动 Bot 进程(连接 MCBE 服务器)", 2),
        ("stop", "", "停止 Bot 进程", 2),
        ("spawn", "<名称>", "在当前位置生成假人(出现在 Tab 列表)", 2),
        ("remove", "<名称>", "移除指定假人", 2),
        ("move", "<名称>", "将假人传送到当前位置", 2),
        ("chat", "<消息>", "以假人身份发送聊天消息", 2),
        ("list", "", "列出所有假人", 2),
    ]

    async def _cmd_bot(self, sender, method, p1=None, p2=None):
        """$bot 方法分发器"""
        if method is None:
            self.client.tell(
                "§cBot | §fError > §i未指定方法（输入 $bot help 查看全部方法）",
                sender,
            )
            return

        # help
        if method == "help":
            lines = "\n".join(
                f"§a$bot {mname}{' ' + margs if margs else ''} §7- §f{mdesc}"
                for mname, margs, mdesc, _ in self.BOT_METHODS
            )
            self.client.tell(
                f"§eBot | §fHelp > §7可用方法\n{lines}",
                sender,
            )
            return

        # 权限检查
        required = None
        for mname, _args, _desc, plevel in self.BOT_METHODS:
            if mname == method:
                required = plevel
                break
        if required is None:
            self.client.tell(
                f"§cBot | §fError > §i未知方法: {method}（输入 $bot help 查看全部方法）",
                sender,
            )
            return

        from lib.permission import PermissionManager
        perm = await PermissionManager.query(sender)
        if isinstance(perm, Exception):
            self.client.tell("§cBot | §fError > §i权限查询失败", sender)
            return
        if perm < required:
            self.client.tell("§cBot | §fError > §i权限不足", sender)
            return

        # 分发
        if method == "start":
            await self._cmd_start(sender)
        elif method == "stop":
            await self._cmd_stop(sender)
        elif method == "spawn":
            if p1 is None:
                self.client.tell("§cBot | §fError > §i参数不足: $bot spawn <名称>", sender)
                return
            await self._cmd_spawn(sender, p1)
        elif method == "remove":
            if p1 is None:
                self.client.tell("§cBot | §fError > §i参数不足: $bot remove <名称>", sender)
                return
            await self._cmd_remove(sender, p1)
        elif method == "move":
            if p1 is None:
                self.client.tell("§cBot | §fError > §i参数不足: $bot move <名称>", sender)
                return
            await self._cmd_move(sender, p1)
        elif method == "chat":
            if p1 is None:
                self.client.tell("§cBot | §fError > §i参数不足: $bot chat <消息>", sender)
                return
            # 合并 p1 + p2 作为完整消息(支持含空格的消息)
            msg = p1 if p2 is None else f"{p1} {p2}"
            await self._cmd_chat(sender, msg)
        elif method == "list":
            await self._cmd_list(sender)

    # ---- 实现 ----

    async def _cmd_start(self, sender):
        bot = BotProcess.get()
        result = await bot.start()
        if result["ok"]:
            self.client.tell(f"§aBot | §fStart > §7{result['message']}", sender)
        else:
            self.client.tell(f"§cBot | §fError > §i{result['message']}", sender)

    async def _cmd_stop(self, sender):
        bot = BotProcess.get()
        result = await bot.stop()
        if result["ok"]:
            self.client.tell(f"§aBot | §fStop > §7{result['message']}", sender)
        else:
            self.client.tell(f"§cBot | §fError > §i{result['message']}", sender)

    async def _cmd_spawn(self, sender, name: str):
        name = name.strip()
        if not name:
            self.client.tell("§cBot | §fError > §i名称不能为空", sender)
            return

        # 获取玩家位置
        pos = await self.client.getPosition("@s")
        x, y, z = (pos["x"], pos["y"], pos["z"]) if pos else (0, 4, 0)

        bot = BotProcess.get()
        result = await bot.send_command({
            "type": "spawn",
            "name": name,
            "x": round(x, 2),
            "y": round(y, 2),
            "z": round(z, 2),
        })

        if result.get("ok"):
            self.client.tell(
                f"§aBot | §fSpawn > §7假人 §f{name} §7已加入游戏(出现在 Tab 列表)",
                sender,
            )
        else:
            self.client.tell(
                f"§cBot | §fError > §i{result.get('message', '生成失败')}",
                sender,
            )

    async def _cmd_remove(self, sender, name: str):
        name = name.strip()
        bot = BotProcess.get()
        result = await bot.send_command({"type": "remove", "name": name})

        if result.get("ok"):
            self.client.tell(f"§aBot | §fRemove > §7假人 §f{name} §7已移除", sender)
        else:
            self.client.tell(
                f"§cBot | §fError > §i{result.get('message', '移除失败')}",
                sender,
            )

    async def _cmd_move(self, sender, name: str):
        name = name.strip()
        pos = await self.client.getPosition("@s")
        x, y, z = (pos["x"], pos["y"], pos["z"]) if pos else (0, 4, 0)

        bot = BotProcess.get()
        result = await bot.send_command({
            "type": "move",
            "name": name,
            "x": round(x, 2),
            "y": round(y, 2),
            "z": round(z, 2),
        })

        if result.get("ok"):
            self.client.tell(
                f"§aBot | §fMove > §7假人 §f{name} §7已传送至 §b({x:.1f}, {y:.1f}, {z:.1f})",
                sender,
            )
        else:
            self.client.tell(
                f"§cBot | §fError > §i{result.get('message', '移动失败')}",
                sender,
            )

    async def _cmd_chat(self, sender, message: str):
        bot = BotProcess.get()
        result = await bot.send_command({
            "type": "chat",
            "message": message,
        })

        if result.get("ok"):
            self.client.tell(f"§aBot | §fChat > §7消息已发送", sender)
        else:
            self.client.tell(
                f"§cBot | §fError > §i{result.get('message', '发送失败')}",
                sender,
            )

    async def _cmd_list(self, sender):
        bot = BotProcess.get()
        if not bot.proc or bot.proc.returncode is not None:
            self.client.tell("§cBot | §fError > §iBot 未运行,请先 $bot start", sender)
            return

        result = await bot.send_command({"type": "list"})
        players = result.get("players", []) if result.get("ok") else []

        if not players:
            self.client.tell("§eBot | §fList > §7当前无假人", sender)
        else:
            lines = "\n".join(
                f"§7  §f{p['name']} §7@ §b({p['x']:.0f}, {p['y']:.0f}, {p['z']:.0f})"
                for p in players
            )
            self.client.tell(f"§eBot | §fList > §7假人列表:\n{lines}", sender)

    def onDestroy(self):
        """Mod 销毁时停止 bot"""
        bot = BotProcess.get()
        if bot.proc and bot.proc.returncode is None:
            try:
                bot.proc.kill()
            except Exception:
                pass
        self.client = None
