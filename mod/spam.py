"""刷屏 Mod

提供聊天刷屏、广告推送、清屏、倒计时等刷屏类命令
（与 mod/read.py 聊天 / 终端模组相互独立,可单独启用 / 禁用）
"""
import asyncio
import random
import re

from config import spam
from lib.command import Command
from lib.current import Current

# 清屏文本
CLEAR_TEXT = "\n§r\n" * 31


# ===== 命令实现(模块级函数,供 Mod.commands 引用) =====

def _cmd_c_attack(_):
    Mod.start_spam(10, lambda: Current.client.sendCommand(f"me {Mod.replace_zeros(spam['attack'])}"), "正在攻击客户端聊天…")


def _cmd_c_count(_):
    count = {"n": 10}

    def gen():
        if count["n"] <= 0:
            Current.get("loop").cancel()
            print("< 倒计时结束")
            return
        Current.client.tellAll(f"§uLUMINEPROXY TOP! §l§cTHIS SERVER WILL CRASH IN {count['n']} SECONDS!")
        count["n"] -= 1

    Mod.start_spam(1000, gen, "正在进行倒计时…")


def _cmd_c_crash(_):
    count = {"n": 10}

    def gen():
        if count["n"] <= 0:
            Current.get("loop").cancel()
            print("< 正在进行崩溃…")
            # 倒计时结束后启动攻击
            Mod.start_spam(10, lambda: Current.client.sendCommand(f"me {Mod.replace_zeros(spam['attack'])}"), "正在进行崩溃攻击…")
            return
        Current.client.tellAll(f"§uLUMINEPROXY TOP! §l§cTHIS SERVER WILL CRASH IN {count['n']} SECONDS!")
        count["n"] -= 1

    Mod.start_spam(1000, gen, "正在进行倒计时…")


def _cmd_c_clear(_):
    def gen():
        for _ in range(8):
            Current.client.tellAll(CLEAR_TEXT)

    Mod.start_spam(50, gen, "正在为客户端聊天清屏…")


def _cmd_c_ad(_):
    interval = spam.get("adInterval") or 60000
    Mod.start_spam(interval, lambda: Current.client.tellAll(spam["ad"][random.randrange(len(spam["ad"]))]), "正在为客户端推送 AD…")


def _cmd_c_repeat(_, text):
    Mod.start_spam(50, lambda: Current.client.tellAll(text), "正在为刷屏客户端…")


def _cmd_c_stop(_):
    if Current.has("loop") and Current.get("loop"):
        Current.get("loop").cancel()
    Current.set("loop", None)
    print("< 已停止客户端刷屏")


# ===== 命令分发器(单一入口 $spam) =====

# (方法, 参数格式, 说明, 游戏内所需权限;终端使用不检查权限)
SPAM_METHODS = [
    ("attack", "", "攻击客户端聊天", 2),
    ("count", "", "聊天室倒计时", 2),
    ("crash", "", "崩溃客户端聊天", 2),
    ("clear", "", "清屏聊天消息", 2),
    ("ad", "", "推送广告", 2),
    ("repeat", "<刷屏内容>", "刷屏指定内容", 2),
    ("stop", "", "停止所有刷屏", 2),
]


async def _cmd_spam(_, method, p1=None, p2=None, p3=None, p4=None, p5=None):
    """$spam 方法分发器(终端命令,无权限检查)"""
    if method is None:
        print(f"< 未知方法: 未指定（输入 {Command.command_prefix}spam help 查看全部方法）")
        return

    # help 显示本模组方法列表
    if method == "help":
        print("< 可用方法:")
        for mname, margs, mdesc, *_ in SPAM_METHODS:
            print(f"  {Command.command_prefix}spam {mname}{' ' + margs if margs else ''} - {mdesc}")
        return

    known = [m for m, *_ in SPAM_METHODS]
    if method not in known:
        print(f"< 未知方法: {method}（输入 {Command.command_prefix}spam help 查看全部方法）")
        return

    # 分发到具体实现
    if method == "attack":
        _cmd_c_attack(_)

    elif method == "count":
        _cmd_c_count(_)

    elif method == "crash":
        _cmd_c_crash(_)

    elif method == "clear":
        _cmd_c_clear(_)

    elif method == "ad":
        _cmd_c_ad(_)

    elif method == "repeat":
        if p1 is None:
            print(f"< 参数不足：{Command.command_prefix}spam repeat <刷屏内容>")
            return
        _cmd_c_repeat(_, p1)

    elif method == "stop":
        _cmd_c_stop(_)


class Mod:
    """刷屏 Mod(服务端)"""

    # 0 值替换
    @staticmethod
    def replace_zeros(text):
        """把字符串中的 0 替换为随机非数字字符(绕过聊天敏感词过滤)"""
        chars = [chr(i) for i in range(33, 127) if i < 48 or i > 57]
        random.shuffle(chars)
        idx = 0

        def _rep(_m):
            nonlocal idx
            if idx >= len(chars):
                idx = 0
            c = chars[idx]
            idx += 1
            return c

        return re.sub(r"0", _rep, text)

    # 通用刷屏启动方法
    @staticmethod
    def start_spam(interval, generator, log_message):
        """启动一个周期性任务;已有任务会被替换"""
        if Current.has("loop") and Current.get("loop"):
            Current.get("loop").cancel()
        print(f"< {log_message}")

        async def _run():
            try:
                while True:
                    await asyncio.sleep(interval / 1000)
                    ret = generator()
                    if asyncio.iscoroutine(ret):
                        await ret
            except asyncio.CancelledError:
                pass

        Current.set("loop", asyncio.get_running_loop().create_task(_run()))

    # 命令定义(单一入口 $spam,方法见 SPAM_METHODS)
    commands = {
        "normal": [
            Command.create("spam", "刷屏命令（方法: attack/count/crash/clear/ad/repeat/stop）")
                .add_alias("s")
            .add_string("方法", False)
            .add_optional_string("参数1")
            .add_optional_string("参数2")
            .add_optional_string("参数3")
            .add_optional_string("参数4")
            .add_optional_string("参数5")
            .set_func(_cmd_spam),
        ],
    }

    # 命令执行
    def execute(self, msg, cmds):
        try:
            for cmd in cmds:
                # 异步命令出错时输出到终端
                def on_error(e, self=self):
                    print(e)
                    if getattr(self, "logger", None):
                        self.logger.error(f"Command {e}")

                cmd.on_error = on_error

                result = cmd.execute("Terminal", msg)

                if result:
                    if not result.get("status") and result.get("message"):
                        print(result["message"])
                    return False
        except Exception as e:
            print(e)
            return False

        return True

    # 游戏内 $spam 命令(服务端 Mod 专属命令,客户端命令系统不拦截)
    # 终端使用无权限限制;游戏内按 SPAM_METHODS 中各方法的权限等级检查
    async def onMessage(self, client, data):
        """处理游戏内玩家发送的 $spam 命令(执行结果输出到服务器终端)"""
        body = data.get("body", {})
        sender = body.get("sender")
        msg = body.get("message")
        if not msg or not sender or body.get("type") != "chat" or len(msg) >= 256:
            return
        if not msg.startswith(Command.command_prefix + "spam"):
            return

        # 解析方法名
        rest = msg[len(Command.command_prefix + "spam"):].strip()
        method = rest.split(" ", 1)[0] if rest else None

        # help 直接反馈给发送者
        if method == "help":
            lines = "\n".join(
                f"§a{Command.command_prefix}spam {mname}{' ' + margs if margs else ''} §7- §f{mdesc}"
                for mname, margs, mdesc, _l in SPAM_METHODS
            )
            client.tell(f"§eSpam | §fHelp > §7可用方法\n{lines}", sender)
            return

        # 查询方法所需权限
        required = None
        for mname, _a, _d, plevel in SPAM_METHODS:
            if mname == method:
                required = plevel
                break
        if required is None:
            client.tell(f"§cSpam | §fError > §i未知方法: {method}（输入 {Command.command_prefix}spam help 查看全部方法）", sender)
            return

        # 权限检查
        from lib.permission import PermissionManager
        perm = await PermissionManager.query(sender)
        if isinstance(perm, Exception):
            client.tell("§cSpam | §fError > §i权限查询失败", sender)
            return
        if perm < required:
            client.tell("§cSpam | §fError > §i权限不足", sender)
            return

        # 复用命令分发执行(print 输出到服务器终端)
        self.execute(msg, self.commands["normal"])

    # 销毁方法:清理刷屏任务,防止 reload 或关闭后任务继续回调
    def onDestroy(self):
        if Current.has("loop") and Current.get("loop"):
            Current.get("loop").cancel()
            Current.set("loop", None)
