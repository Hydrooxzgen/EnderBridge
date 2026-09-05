"""AI 对话 Mod

通过 OpenAI 兼容接口与 AI 模型交互,支持单次对话和上下文对话模式
同时作为服务端 Mod(静态清理)与客户端 Mod(对话命令)加载
"""
import asyncio
import copy
import json
import re
import time

from config import AIConfig
from lib.command import Command
from lib.current import Current
from lib.utils import Utils

# 初始化 OpenAI 客户端(无密钥时不构造,chat 时给出明确报错)
# 异步客户端:避免阻塞事件循环
_openai_client = None
if AIConfig.get("options", {}).get("apiKey"):
    try:
        from openai import AsyncOpenAI
        _opts = AIConfig["options"]
        _openai_client = AsyncOpenAI(
            api_key=_opts.get("apiKey"),
            base_url=_opts.get("baseURL") or None,
        )
    except Exception:
        _openai_client = None


# AI 对话核心实现
async def _ai_chat_impl(send_msg, mode, contents=None):
    """调用 AI 模型;mode 为 chat / command 模式,contents 为上下文列表"""
    if mode not in AIConfig.get("models", {}):
        raise ValueError("该模式不存在")

    send_data = copy.deepcopy(AIConfig["models"][mode])

    # 上文模式下将历史对话追加到请求中(过滤缺失 content 的异常历史,避免报 missing field)
    if contents:
        valid_contents = [m for m in contents if isinstance(m.get("content"), str)]
        send_data["messages"].extend(valid_contents)

    # 追加当前用户消息
    send_data["messages"].append({"role": "user", "content": send_msg})

    if _openai_client is None:
        raise ValueError("未配置 AI apiKey，请在 config.py 中填写")

    completion = await _openai_client.chat.completions.create(**send_data)

    # 提取回复内容(兼容字符串、数组及推理模型返回值)
    choice = completion.choices[0] if completion.choices else None
    raw_content = choice.message.content if choice else None
    if isinstance(raw_content, str):
        return_msg = raw_content
    elif isinstance(raw_content, list):
        parts = []
        for part in raw_content:
            if isinstance(part, dict):
                parts.append(part.get("text") or "")
            else:
                parts.append(str(part))
        return_msg = "".join(parts)
    else:
        return_msg = choice.message.reasoning_content if choice else ""

    # 上文模式下保存本次对话并限制历史长度
    if contents:
        contents.append({"role": "user", "content": send_msg})
        contents.append({"role": "assistant", "content": return_msg or ""})
        if len(contents) > 40:
            del contents[:len(contents) - 40]

    return return_msg


class Mod:
    """AI 对话类(客户端 Mod;静态部分服务端共用)"""

    # 玩家数据存储
    # 结构: {玩家名: {lastAIChat: int, AIChatContents: [], AICommandContents: []}}
    player_data = {}

    # 清理任务
    cleanup_task = None

    # 启动自动清理
    # 注意:不绑定具体客户端,实时取当前主客户端,避免主客户端重连后清理逻辑对着已断开连接空转
    @classmethod
    def start_cleanup(cls):
        if cls.cleanup_task and not cls.cleanup_task.done():
            return

        async def _loop():
            while True:
                await asyncio.sleep(45_000)
                client = Current.client
                if not client:
                    continue

                # 获取当前在线玩家列表
                try:
                    data = await client.runCommand("list")
                except Exception:
                    continue

                online_players = set()
                players_raw = (data.get("body") or {}).get("players")
                if players_raw:
                    online_players.update(players_raw.split(", "))

                # 销毁不在线玩家的数据
                for name in list(cls.player_data):
                    if name not in online_players:
                        del cls.player_data[name]

        cls.cleanup_task = asyncio.get_running_loop().create_task(_loop())

    # 停止自动清理
    @classmethod
    def stop_cleanup(cls):
        if cls.cleanup_task:
            cls.cleanup_task.cancel()
            cls.cleanup_task = None

    # 获取或创建玩家数据
    @classmethod
    def get_player_data(cls, name):
        if name not in cls.player_data:
            cls.player_data[name] = {
                "lastAIChat": 0,
                "AIChatContents": [],
                "AICommandContents": [],
            }
        return cls.player_data[name]

    # 构造函数
    def __init__(self, client=None):
        self.client = client
        Mod.start_cleanup()

    # 返回命令定义
    def onCommand(self):
        return {
            "normal": [
                Command.create("ai", "AI 对话命令（方法: chat/reset/cmd）")
                .add_alias("a")
                .add_string("方法", False)
                .add_optional_string("参数1")
                .add_optional_string("参数2")
                .add_optional_string("参数3")
                .add_optional_string("参数4")
                .add_optional_string("参数5")
                .set_func(self._cmd_ai),
            ],
        }

    # ---- 命令分发器 ----

    # (方法, 参数格式, 说明, 所需权限等级)
    AI_METHODS = [
        ("chat", "<对话内容>", "与 AI 进行对话(带空格内容请用双引号包裹)", 0),
        ("reset", "", "重置对话上下文", 0),
        ("cmd", "<对话内容>", "让 AI 执行基岩版命令(带空格内容请用双引号包裹)", 2),
    ]

    async def _cmd_ai(self, sender, method, p1=None, p2=None, p3=None, p4=None, p5=None):
        """$ai 方法分发器(方法内做权限检查)"""
        if method is None:
            self.client.tell(f"§cAI | §fError > §i未知方法: 未指定（输入 {Command.command_prefix}ai help 查看全部方法）", sender)
            return

        # help 显示本模组方法列表
        if method == "help":
            lines = "\n".join(
                f"§a{Command.command_prefix}ai {mname}{' ' + margs if margs else ''} §7- §f{mdesc}"
                for mname, margs, mdesc, _l in self.AI_METHODS
            )
            self.client.tell(f"§eAI | §fHelp > §7可用方法\n{lines}", sender)
            return

        # 查询方法所需权限
        required = None
        for mname, _args, _desc, plevel in self.AI_METHODS:
            if mname == method:
                required = plevel
                break
        if required is None:
            self.client.tell(f"§cAI | §fError > §i未知方法: {method}（输入 {Command.command_prefix}ai help 查看全部方法）", sender)
            return

        # 权限检查
        from lib.permission import PermissionManager
        perm = await PermissionManager.query(sender)
        if isinstance(perm, Exception):
            self.client.tell("§cAI | §fError > §i权限查询失败", sender)
            return
        if perm < required:
            self.client.tell("§cAI | §fError > §i权限不足", sender)
            return

        # 分发到具体实现
        if method == "chat":
            if p1 is None:
                self.client.tell(f"§cAI | §fError > §i参数不足：{Command.command_prefix}ai chat <对话内容>", sender)
                return
            await self.chat(p1, sender)

        elif method == "reset":
            await self._cmd_reset(sender)

        elif method == "cmd":
            if p1 is None:
                self.client.tell(f"§cAI | §fError > §i参数不足：{Command.command_prefix}ai cmd <对话内容>", sender)
                return
            await self.command(p1, sender)

    async def _cmd_reset(self, commander):
        self.reset(commander)
        self.client.tellAll("§eAI | §fSystem > §i对话上下文已重置")

    # 冷却检查函数
    def cooldown_test(self, name):
        data = Mod.get_player_data(name)
        now = time.time() * 1000
        last_time = data["lastAIChat"] or 0

        # 发言过快检测(先判定,通过后再更新时间,避免冷却被每次失败发言后移)
        if now - last_time < AIConfig.get("chatCooldown", 5000):
            try:
                asyncio.get_running_loop().create_task(self.client.tellAll("§cAI | §fCooldown > §i聊天速度过快"))
            except RuntimeError:
                pass
            return False

        data["lastAIChat"] = now
        return True

    # 聊天方法
    async def chat(self, send_msg, name):
        if not self.cooldown_test(name):
            return

        data = Mod.get_player_data(name)
        contents = data["AIChatContents"]

        try:
            result = await _ai_chat_impl(send_msg, "chat", contents)
            for msg in Utils.splitByBytes(result, 300):
                self.client.tellAll(f"§bAI | §f{name} > §i{msg}")
        except Exception as e:
            self.client.tellAll(f"§cAI | §fError > §i{e}")

    # 命令方法
    async def command(self, send_msg, name):
        if not self.cooldown_test(name):
            return

        data = Mod.get_player_data(name)
        contents = data["AICommandContents"]

        try:
            result = await _ai_chat_impl(send_msg, "command", contents)
            result = result.strip()
            result = re.sub(r"^```(?:json)?\s*", "", result, flags=re.IGNORECASE)
            result = re.sub(r"\s*```$", "", result)
            result_object = json.loads(result)
            for msg in Utils.splitByBytes(result_object.get("message", ""), 300):
                self.client.tellAll(f"§bAI | §f{name} > §i{msg}")
            for command in result_object.get("commands", []):
                await self.client.sendCommand(command)
                self.client.tellAll(f"§bAI | §fCommand > §i{command if command.startswith('/') else '/' + command}")
        except Exception as e:
            self.client.tellAll(f"§cAI | §fError > §i{e}")

    # 清空对话上下文
    def reset(self, name):
        data = Mod.get_player_data(name)
        data["AIChatContents"] = []
        data["AICommandContents"] = []

    # 销毁方法(服务端与客户端共用)
    def onDestroy(self):
        Mod.stop_cleanup()
        Mod.player_data.clear()
        self.client = None
