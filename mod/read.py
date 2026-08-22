"""终端交互 Mod

监听标准输入,提供终端级别的命令执行和消息发送功能
支持游戏命令转发、聊天刷屏、Lumine 广告推送等
"""
import asyncio
import random
import re
import sys

from config import spam
from lib.command import Command
from lib.current import Current
from lib.mods import ClientModManager, ServerModManager

# 清屏文本
CLEAR_TEXT = "\n§r\n" * 31


# ===== 命令实现(模块级函数,供 Mod.commands 引用) =====

def _cmd_test(_):
    print("< 测试成功")


def _cmd_p_list(_):
    if not Current.client_mods:
        print("< 无已连接客户端")
        return
    print(f"< 当前连接 ({len(Current.client_mods)}):")
    index = 0
    for conn in Current.client_mods:
        index += 1
        is_main = "主客户端" if conn is Current.client else f"编号 {index}"
        try:
            ip = conn.ws.remote_address[0] if conn.ws.remote_address else "未知 IP"
        except Exception:
            ip = "未知 IP"
        print(f"  §b{is_main} §f- §e{ip}")


async def _cmd_p_reload(_):
    print("< 正在重载所有 Mod...")
    server_result = await ServerModManager.reload_all()
    print(f"< §a服务端成功: {', '.join(server_result['success']) or '无'}")
    if server_result["failed"]:
        print(f"< §c服务端失败: {', '.join(server_result['failed'])}")

    client_result = await ClientModManager.reload_all_clients()
    print(f"< §a客户端成功: {len(client_result['success'])} 个实例")
    for f in client_result["failed"]:
        print(f"  §c{f}")


def _cmd_p_mod(_):
    server_mods = ServerModManager.get_loaded_mod_names()
    print(f"< 服务端 Mod ({len(server_mods)}):")
    if not server_mods:
        print("  §7无")
    else:
        for name in server_mods:
            print(f"  §b{name}")

    client_mods = list((ClientModManager.loaded_mod or {}).keys())
    print(f"< 客户端 Mod ({len(client_mods)}):")
    if not client_mods:
        print("  §7无")
    else:
        for name in client_mods:
            print(f"  §b{name}")


def _cmd_bye(_):
    # 发送大量重复文本触发断开
    Current.client.utils.sendCommandUnsafe("/me 正在尝试退出..." * 100 + "退出失败")


def _cmd_testx(_):
    # 发送超长文本测试
    Current.client.utils.sendCommandUnsafe(
        "/me testtesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttest"
        "testtesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttest"
        "testtesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttest"
        "testtesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttest"
        "testtesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttest"
        "testtesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttesttestte"
    )


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


def _cmd_c_line(_, text):
    # 在消息前插入换行以实现换行效果
    Current.client.tellAll(f"\n§r\n{text}")


# ===== 命令分发器(单一入口 $chat) =====

# (方法, 参数格式, 说明)
READ_METHODS = [
    ("test", "", "测试命令"),
    ("list", "", "列出所有连接(主客户端 + IP 或 编号 + IP)"),
    ("reload", "", "重载所有服务端 Mod + 所有客户端 Mod 全部实例"),
    ("mod", "", "列出所有服务端 Mod 与客户端 Mod"),
    ("bye", "", "强制退出当前房间 (WebSocket 专用)"),
    ("testx", "", "小测试 (WebSocket 专用)"),
    ("attack", "", "攻击客户端聊天"),
    ("count", "", "聊天室倒计时"),
    ("crash", "", "崩溃客户端聊天"),
    ("clear", "", "清屏聊天消息"),
    ("ad", "", "推送广告"),
    ("repeat", "<刷屏内容>", "刷屏指定内容"),
    ("stop", "", "停止所有刷屏"),
    ("line", "<发言内容>", "换行发言"),
]


async def _cmd_read(_, method, p1=None, p2=None, p3=None, p4=None, p5=None):
    """$chat 方法分发器(终端命令,无权限检查)"""
    if method is None:
        print(f"< 未知方法: 未指定（输入 {Command.command_prefix}chat help 查看全部方法）")
        return

    # help 显示本模组方法列表
    if method == "help":
        print("< 可用方法:")
        for mname, margs, mdesc, *_ in READ_METHODS:
            print(f"  {Command.command_prefix}chat {mname}{' ' + margs if margs else ''} - {mdesc}")
        return

    known = [m for m, _a, _d in READ_METHODS]
    if method not in known:
        print(f"< 未知方法: {method}（输入 {Command.command_prefix}chat help 查看全部方法）")
        return

    # 分发到具体实现
    if method == "test":
        _cmd_test(_)

    elif method == "list":
        _cmd_p_list(_)

    elif method == "reload":
        await _cmd_p_reload(_)

    elif method == "mod":
        _cmd_p_mod(_)

    elif method == "bye":
        _cmd_bye(_)

    elif method == "testx":
        _cmd_testx(_)

    elif method == "attack":
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
            print(f"< 参数不足：{Command.command_prefix}chat repeat <刷屏内容>")
            return
        _cmd_c_repeat(_, p1)

    elif method == "stop":
        _cmd_c_stop(_)

    elif method == "line":
        if p1 is None:
            print(f"< 参数不足：{Command.command_prefix}chat line <发言内容>")
            return
        _cmd_c_line(_, p1)


class Mod:
    """终端读取 Mod(服务端)"""

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

    # 命令定义(单一入口 $chat,方法见 READ_METHODS)
    commands = {
        "normal": [
            Command.create("chat", "终端命令（方法: test/list/reload/mod/bye/testx/attack/count/crash/clear/ad/repeat/stop/line）")
            .add_string("方法", False)
            .add_optional_string("参数1")
            .add_optional_string("参数2")
            .add_optional_string("参数3")
            .add_optional_string("参数4")
            .add_optional_string("参数5")
            .set_func(_cmd_read),
        ],
    }

    # 启动终端交互监听(由 ServerModManager 在 onStart/start 阶段调用)
    def start(self):
        self._read_task = asyncio.get_running_loop().create_task(self._read_loop())

    async def _read_loop(self):
        while True:
            try:
                line = await asyncio.to_thread(sys.stdin.readline)
            except Exception:
                break
            if not line:
                break
            await self.read(line.rstrip("\n"))

    # 处理终端输入
    async def read(self, input_text):
        is_command = input_text.startswith(Command.command_prefix)

        # 执行命令(单一入口 $chat)
        if is_command:
            result = self.execute(input_text, self.commands["normal"])
            if not result:
                # 无匹配命令提示
                print(f"未知的命令 {input_text.split(' ')[0]}")
            return

        # 检测主客户端连接状态
        if not Current.client:
            print("主客户端未连接")
            return

        # 游戏命令转发(以 / 开头)
        if input_text.startswith("/"):
            try:
                data = await Current.client.runCommand(input_text)
                body = data.get("body", {})
                print(f"CMD {body.get('statusCode')} -> {body.get('statusMessage') or 'Null'}")
            except Exception as e:
                print(f"CMD 执行失败: {e}")
            return

        # 非命令文本作为聊天消息发送
        Current.client.tellAll(input_text)

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

    # 销毁方法:取消终端读取任务与刷屏任务
    def onDestroy(self):
        if getattr(self, "_read_task", None):
            self._read_task.cancel()
            self._read_task = None
        # 清理刷屏任务,防止 reload 或关闭后任务继续回调
        if Current.has("loop") and Current.get("loop"):
            Current.get("loop").cancel()
            Current.set("loop", None)
