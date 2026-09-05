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
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot")
_BOT_SCRIPT = os.path.join(_BOT_DIR, "bot.js")


def _needs_npm_install():
    """检查 Bot npm 依赖是否需要(重新)安装。

    返回 (是否需要, 原因)。旧版本升级后 node_modules 可能仍是旧版
    (axios 老版本 / prismarine-auth 补丁缺失),仅检查目录存在无法发现,
    这里通过补丁标记与 package.json 变更时间双重判断。
    """
    node_modules = os.path.join(_BOT_DIR, "node_modules")
    if not os.path.isdir(node_modules):
        return True, "node_modules 不存在"

    # 1. 依赖补丁是否已应用(缺失 = 依赖是旧版安装的,升级后必现 400/401)
    missing = []
    auth_flow = os.path.join(
        node_modules, "prismarine-auth", "src", "MicrosoftAuthFlow.js"
    )
    if os.path.isfile(auth_flow):
        try:
            with open(auth_flow, "r", encoding="utf-8", errors="replace") as f:
                if "PATCH_TITLE_TOKEN_FALLBACK" not in f.read():
                    missing.append("prismarine-auth")
        except OSError:
            pass
    else:
        missing.append("prismarine-auth")
    bedrock_opt = os.path.join(node_modules, "bedrock-protocol", "src", "options.js")
    if os.path.isfile(bedrock_opt):
        try:
            with open(bedrock_opt, "r", encoding="utf-8", errors="replace") as f:
                if "EXTRA_VERSIONS" not in f.read():
                    missing.append("bedrock-protocol")
        except OSError:
            pass
    else:
        missing.append("bedrock-protocol")
    if missing:
        return True, f"依赖补丁未应用: {', '.join(missing)}"

    # 2. package.json 比安装标记新 = 依赖声明有变更
    pkg = os.path.join(_BOT_DIR, "package.json")
    marker = os.path.join(node_modules, ".package-lock.json")
    if os.path.isfile(pkg) and os.path.isfile(marker):
        if os.path.getmtime(pkg) > os.path.getmtime(marker):
            return True, "package.json 已更新"

    return False, ""


def _find_npm() -> str:
    """跨平台查找 npm 可执行文件路径"""
    import shutil
    # 优先查找 npm.cmd (Windows) 或 npm (Unix)
    for name in ("npm.cmd", "npm"):
        path = shutil.which(name)
        if path:
            return path
    return "npm"  # 回退,让 subprocess 报明确错误


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
        self._resp_queue = None   # asyncio.Queue — 命令响应队列

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
        if cfg.get("enabled") is False:
            return {"ok": False, "message": "Bot 已在配置中禁用,请在 config.py 中设置 botConfig.enabled = True 并重启"}

        mode = cfg.get("mode", "server")
        host = cfg.get("host", "127.0.0.1")
        port = cfg.get("port", 19132)
        username = cfg.get("username", "FakeBot")
        offline = cfg.get("offline", True)
        # 有活跃 Xbox 账号时使用其用户名,但 offline 完全由配置控制
        active_xbox = cfg.get("activeXboxAccount")
        if active_xbox:
            username = active_xbox
        version = cfg.get("version", None)
        auth_title = cfg.get("authTitle", None)
        profiles_folder = cfg.get("profilesFolder", None)
        realm_id = cfg.get("realmId", None)
        realm_invite = cfg.get("realmInvite", None)

        # Realm 模式强制 online
        is_realm = mode == "realm"
        effective_offline = False if is_realm else offline

        # 检查 node 可用
        try:
            r = subprocess.run(["node", "--version"], capture_output=True, timeout=5)
            if r.returncode != 0:
                return {"ok": False, "message": "Node.js 不可用,请安装 Node.js"}
        except FileNotFoundError:
            return {"ok": False, "message": "未找到 node 命令,请安装 Node.js"}
        except Exception as e:
            return {"ok": False, "message": f"Node.js 检测失败: {e}"}

        # 检查依赖是否安装/是否需要重装(旧版升级后自愈)
        need_install, install_reason = _needs_npm_install()
        if need_install:
            shared.logger.info(f"[Bot] npm 依赖需要安装({install_reason}),正在安装...")
            try:
                npm_path = _find_npm()
                r = subprocess.run(
                    [npm_path, "install"],
                    cwd=_BOT_DIR,
                    capture_output=True,
                    timeout=300,
                )
                if r.returncode != 0:
                    err = r.stderr.decode("utf-8", errors="replace")[:200]
                    return {"ok": False, "message": f"npm install 失败: {err}"}
                shared.logger.info("[Bot] npm 依赖安装完成(补丁已自动应用)")
            except Exception as e:
                return {"ok": False, "message": f"npm install 异常: {e}"}

        # 启动子进程
        config_payload = json.dumps({
            "mode": mode,
            "host": host,
            "port": port,
            "username": username,
            "offline": effective_offline,
            "version": version,
            "authTitle": auth_title,
            "profilesFolder": profiles_folder,
            "realmId": realm_id,
            "realmInvite": realm_invite,
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
        self._resp_queue = asyncio.Queue()

        # 启动 stdout 读取
        self._read_task = asyncio.get_running_loop().create_task(self._read_stdout())

        # 启动 stderr 读取(日志)
        asyncio.get_running_loop().create_task(self._read_stderr())

        if is_realm:
            return {"ok": True, "message": f"Bot 正在加入 Realm ({realm_id or realm_invite})..."}
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
        self._resp_queue = None
        return {"ok": True, "message": "Bot 已停止"}

    async def send_command(self, cmd: dict) -> dict:
        """向 bot 发送命令并等待响应"""
        if not self.proc or self.proc.returncode is not None:
            return {"ok": False, "message": "Bot 未运行,请先 $bot start"}
        if not self._resp_queue:
            return {"ok": False, "message": "Bot 响应队列未初始化"}

        try:
            self.proc.stdin.write((json.dumps(cmd, ensure_ascii=False) + "\n").encode("utf-8"))
            await self.proc.stdin.drain()
        except Exception as e:
            return {"ok": False, "message": f"发送命令失败: {e}"}

        # 从队列等待响应(最多 5 秒),丢弃非命令响应(如 join/disconnect/auth 通知)
        try:
            deadline = asyncio.get_running_loop().time() + 5
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    return {"ok": False, "message": "Bot 响应超时"}
                resp = await asyncio.wait_for(self._resp_queue.get(), timeout=remaining)
                # 命令响应:有 action 字段的是命令响应;join/disconnect/auth 是事件通知,跳过
                if resp.get("action") or resp.get("type") == "error":
                    return resp
        except asyncio.TimeoutError:
            return {"ok": False, "message": "Bot 响应超时"}

    def _on_response(self, resp: dict):
        """收到 bot 响应时调用"""
        if resp.get("type") == "auth":
            # Xbox Live 认证信息 — 醒目提示
            user_code = resp.get("user_code", "")
            verification_uri = resp.get("verification_uri", "")
            shared.logger.warning(
                f"[Bot] ========================================\n"
                f"[Bot]   Xbox Live 认证需要你的操作！\n"
                f"[Bot]   1. 在浏览器中打开: {verification_uri}\n"
                f"[Bot]   2. 输入验证码: {user_code}\n"
                f"[Bot]   3. 使用 Microsoft 账号登录\n"
                f"[Bot]   完成后 Bot 将自动继续连接\n"
                f"[Bot] ========================================"
            )
            if self._resp_queue is not None:
                self._resp_queue.put_nowait(resp)
        elif resp.get("type") == "join":
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

        # 放入响应队列,供 send_command 消费
        if self._resp_queue is not None:
            self._resp_queue.put_nowait(resp)

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
                    # 包含 error/stack/throw 的是致命错误,用 warning 级别确保可见
                    lower = text.lower()
                    if any(kw in lower for kw in ('error', 'stack', 'throw', 'crash')):
                        shared.logger.warning(f"[Bot] {text}")
                    else:
                        shared.logger.debug(f"[Bot] {text}")
        except asyncio.CancelledError:
            pass
        except Exception:
            pass


class XboxLoginManager:
    """管理 Xbox Live 登录流程(独立于 BotProcess)"""

    _instance = None

    def __init__(self):
        self.proc = None
        self.status = "idle"  # idle | waiting | done | error
        self.user_code = ""
        self.verification_uri = ""
        self.username = ""
        self.error = ""

    @classmethod
    def get(cls) -> "XboxLoginManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # 临时用户名(与 bot.js 中的 TEMP_USER 一致)
    TEMP_USER = "__xbox_login_pending__"

    async def start_login(self, auth_title: str = None) -> dict:
        """启动 Xbox Live 登录流程 — 不需要传入用户名,Gamertag 从认证响应中自动获取"""
        if self.proc and self.proc.returncode is None:
            return {"ok": False, "message": "登录流程已在进行中"}

        cfg = _bot_config()
        profiles_folder = cfg.get("profilesFolder") or None
        effective_auth_title = auth_title or cfg.get("authTitle") or None

        # 检查 node 可用
        try:
            r = subprocess.run(["node", "--version"], capture_output=True, timeout=5)
            if r.returncode != 0:
                return {"ok": False, "message": "Node.js 不可用"}
        except FileNotFoundError:
            return {"ok": False, "message": "未找到 node 命令,请安装 Node.js"}

        config_payload = json.dumps({
            "mode": "server",
            "host": "127.0.0.1",
            "port": 19132,
            "username": self.TEMP_USER,
            "offline": False,
            "version": None,
            "authTitle": effective_auth_title,
            "profilesFolder": profiles_folder,
            "realmId": None,
            "realmInvite": None,
            "loginOnly": True,
        }, ensure_ascii=False)

        try:
            self.proc = await asyncio.create_subprocess_exec(
                "node", _BOT_SCRIPT,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=_BOT_DIR,
            )
            self.proc.stdin.write((config_payload + "\n").encode("utf-8"))
            await self.proc.stdin.drain()
        except Exception as e:
            return {"ok": False, "message": f"启动登录进程失败: {e}"}

        self.status = "waiting"
        self.user_code = ""
        self.verification_uri = ""
        self.username = ""
        self.error = ""

        # 启动 stdout/stderr 读取
        asyncio.get_running_loop().create_task(self._read_stdout())
        asyncio.get_running_loop().create_task(self._read_stderr())

        return {"ok": True, "message": "正在启动 Xbox Live 登录..."}

    def get_status(self) -> dict:
        return {
            "status": self.status,
            "user_code": self.user_code,
            "verification_uri": self.verification_uri,
            "username": self.username,
            "error": self.error,
        }

    async def stop_login(self) -> dict:
        if not self.proc or self.proc.returncode is not None:
            self.status = "idle"
            return {"ok": True, "message": "登录进程未运行"}
        try:
            self.proc.kill()
        except Exception:
            pass
        self.status = "idle"
        return {"ok": True, "message": "登录已取消"}

    async def _read_stdout(self):
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
                    if resp.get("type") == "auth":
                        self.user_code = resp.get("user_code", "")
                        self.verification_uri = resp.get("verification_uri", "")
                        self.status = "waiting"
                    elif resp.get("type") == "login-ok":
                        self.status = "done"
                        self.username = resp.get("username", self.username)
                        # 自动保存到 config.py
                        self._save_account(self.username)
                    elif resp.get("type") == "login-fail":
                        self.status = "error"
                        self.error = resp.get("message", "认证失败")
                except json.JSONDecodeError:
                    pass
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _read_stderr(self):
        try:
            while True:
                line = await self.proc.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    shared.logger.debug(f"[XboxLogin] {text}")
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    def _save_account(self, username: str):
        """将已认证的 Xbox 账号保存到 config.py"""
        try:
            import importlib.util
            ns = {}
            spec = importlib.util.spec_from_file_location("config", os.path.join(ROOT, "config.py"))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            ns = module.__dict__

            bot_cfg = dict(ns.get("botConfig") or {})
            accounts = list(bot_cfg.get("xboxAccounts") or [])

            # 检查是否已存在
            exists = any(a.get("username") == username for a in accounts)
            if not exists:
                accounts.append({"username": username})
                bot_cfg["xboxAccounts"] = accounts

            # 登录成功后总是将新账号设为活跃 — 用户登录新账号就是希望立即使用它,
            # 这样 web 显示的账号与实际 bot 连接的账号保持一致
            bot_cfg["activeXboxAccount"] = username
            bot_cfg["username"] = username
            # 登录了 Xbox 账号必须使用 online 模式,否则 bot 还是离线连接
            bot_cfg["offline"] = False

            # 写回 config.py
            config_path = os.path.join(ROOT, "config.py")
            from webui.server import _replace_block
            src = ""
            with open(config_path, "r", encoding="utf-8") as f:
                src = f.read()
            src, ok = _replace_block(src, "botConfig", bot_cfg)
            if ok:
                import shutil
                bak_path = config_path + ".bak"
                if os.path.exists(config_path):
                    shutil.copy2(config_path, bak_path)
                with open(config_path, "w", encoding="utf-8") as f:
                    f.write(src)
                shared.logger.info(f"[XboxLogin] 账号 {username} 已保存到配置")
            else:
                shared.logger.warning(f"[XboxLogin] 无法保存账号: config.py 中未找到 botConfig")
        except Exception as e:
            shared.logger.warning(f"[XboxLogin] 保存账号失败: {e}")


class Mod:
    """假人 Mod（客户端）"""

    def __init__(self, client):
        self.client = client

    def onCommand(self):
        return {
            "op": [
                Command.create("bot", "假人管理（start/stop/spawn/remove/move/chat/list）")
                .add_alias("b")
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
        ("shell", "", "进入 Bot Shell 交互模式(直接执行 MCBE 命令)", 2),
    ]

    async def _cmd_bot(self, sender, method, p1=None, p2=None):
        """$bot 方法分发器"""
        if method is None:
            self.client.tell(
                "Bot | Error > 未指定方法（输入 $bot help 查看全部方法）",
                sender,
            )
            return

        # help
        if method == "help":
            lines = "\n".join(
                f"  $bot {mname}{' ' + margs if margs else ''}  -  {mdesc}"
                for mname, margs, mdesc, _ in self.BOT_METHODS
            )
            self.client.tell(
                f"Bot | Help > 可用方法:\n{lines}",
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
                f"Bot | Error > 未知方法: {method}（输入 $bot help 查看全部方法）",
                sender,
            )
            return

        from lib.permission import PermissionManager
        perm = await PermissionManager.query(sender)
        if isinstance(perm, Exception):
            self.client.tell("Bot | Error > 权限查询失败", sender)
            return
        if perm < required:
            self.client.tell("Bot | Error > 权限不足", sender)
            return

        # 分发
        if method == "start":
            await self._cmd_start(sender)
        elif method == "stop":
            await self._cmd_stop(sender)
        elif method == "spawn":
            if p1 is None:
                self.client.tell("Bot | Error > 参数不足: $bot spawn <名称>", sender)
                return
            await self._cmd_spawn(sender, p1)
        elif method == "remove":
            if p1 is None:
                self.client.tell("Bot | Error > 参数不足: $bot remove <名称>", sender)
                return
            await self._cmd_remove(sender, p1)
        elif method == "move":
            if p1 is None:
                self.client.tell("Bot | Error > 参数不足: $bot move <名称>", sender)
                return
            await self._cmd_move(sender, p1)
        elif method == "chat":
            if p1 is None:
                self.client.tell("Bot | Error > 参数不足: $bot chat <消息>", sender)
                return
            # 合并 p1 + p2 作为完整消息(支持含空格的消息)
            msg = p1 if p2 is None else f"{p1} {p2}"
            await self._cmd_chat(sender, msg)
        elif method == "list":
            await self._cmd_list(sender)
        elif method == "shell":
            await self._cmd_shell(sender)

    # ---- 实现 ----

    async def _cmd_start(self, sender):
        bot = BotProcess.get()
        result = await bot.start()
        if result["ok"]:
            self.client.tell(f"Bot | Start > {result['message']}", sender)
        else:
            self.client.tell(f"Bot | Error > {result['message']}", sender)

    async def _cmd_stop(self, sender):
        bot = BotProcess.get()
        result = await bot.stop()
        if result["ok"]:
            self.client.tell(f"Bot | Stop > {result['message']}", sender)
        else:
            self.client.tell(f"Bot | Error > {result['message']}", sender)

    async def _cmd_spawn(self, sender, name: str):
        name = name.strip()
        if not name:
            self.client.tell("Bot | Error > 名称不能为空", sender)
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
                f"Bot | Spawn > 假人 {name} 已加入游戏(出现在 Tab 列表)",
                sender,
            )
        else:
            self.client.tell(
                f"Bot | Error > {result.get('message', '生成失败')}",
                sender,
            )

    async def _cmd_remove(self, sender, name: str):
        name = name.strip()
        bot = BotProcess.get()
        result = await bot.send_command({"type": "remove", "name": name})

        if result.get("ok"):
            self.client.tell(f"Bot | Remove > 假人 {name} 已移除", sender)
        else:
            self.client.tell(
                f"Bot | Error > {result.get('message', '移除失败')}",
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
                f"Bot | Move > 假人 {name} 已传送至 ({x:.1f}, {y:.1f}, {z:.1f})",
                sender,
            )
        else:
            self.client.tell(
                f"Bot | Error > {result.get('message', '移动失败')}",
                sender,
            )

    async def _cmd_chat(self, sender, message: str):
        bot = BotProcess.get()
        result = await bot.send_command({
            "type": "chat",
            "message": message,
        })

        if result.get("ok"):
            self.client.tell(f"Bot | Chat > 消息已发送", sender)
        else:
            self.client.tell(
                f"Bot | Error > {result.get('message', '发送失败')}",
                sender,
            )

    async def _cmd_list(self, sender):
        bot = BotProcess.get()
        if not bot.proc or bot.proc.returncode is not None:
            self.client.tell("Bot | Error > Bot 未运行,请先 $bot start", sender)
            return

        result = await bot.send_command({"type": "list"})
        players = result.get("players", []) if result.get("ok") else []

        if not players:
            self.client.tell("Bot | List > 当前无假人", sender)
        else:
            lines = "\n".join(
                f"  {p['name']} @ ({p['x']:.0f}, {p['y']:.0f}, {p['z']:.0f})"
                for p in players
            )
            self.client.tell(f"Bot | List > 假人列表:\n{lines}", sender)

    async def _cmd_shell(self, sender):
        """进入 Bot Shell 交互模式"""
        bot = BotProcess.get()
        if not bot.proc or bot.proc.returncode is not None:
            self.client.tell("Bot | Error > Bot 未运行,请先 $bot start", sender)
            return

        # 设置 shell 模式
        shared.bot_shell_mode = True
        shared.bot_shell_queue = asyncio.Queue()
        self.client.tell(
            "Bot | Shell > 已进入交互模式,直接输入 MCBE 命令(如 /tp /say /execute),输入 exit 退出",
            sender,
        )

        try:
            while True:
                line = await shared.bot_shell_queue.get()
                line = line.strip()
                if not line:
                    continue
                if line.lower() == "exit":
                    break

                # 自动加 / 前缀(如果没有)
                cmd_str = line if line.startswith("/") else f"/{line}"
                result = await bot.send_command({
                    "type": "command",
                    "command": cmd_str,
                })

                if result.get("ok"):
                    self.client.tell(f"[Shell] > {cmd_str}", sender)
                else:
                    self.client.tell(
                        f"[Shell] Error > {result.get('message', '命令发送失败')}",
                        sender,
                    )
        finally:
            shared.bot_shell_mode = False
            shared.bot_shell_queue = None
            self.client.tell("Bot | Shell > 已退出交互模式", sender)

    def onDestroy(self):
        """Mod 销毁时停止 bot"""
        bot = BotProcess.get()
        if bot.proc and bot.proc.returncode is None:
            try:
                bot.proc.kill()
            except Exception:
                pass
        self.client = None
