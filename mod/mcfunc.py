"""Minecraft 函数文件执行 Mod

支持加载和执行 .mcfunction 格式的指令文件,支持嵌套调用和循环执行
"""
import asyncio
import math
import os
import re

from config import basePath
from lib.command import Command


class Mod:
    """函数文件执行 Mod(客户端)"""

    def __init__(self, client):
        self.client = client
        # 存储循环执行的定时器任务: 循环名 -> asyncio.Task
        self.loops = {}
        self.page = 1

    # 返回命令定义
    def onCommand(self):
        return {
            "op": [
                Command.create("function", "Function 执行命令（方法: function/loop/stop/list/search）")
                .add_string("方法", False)
                .add_optional_string("参数1")
                .add_optional_string("参数2")
                .add_optional_string("参数3")
                .add_optional_string("参数4")
                .add_optional_string("参数5")
                .set_func(self._cmd_function),
            ],
        }

    # ---- 命令分发器 ----

    FUNCTION_METHODS = [
        ("function", "<文件路径>", "运行 Function 文件"),
        ("loop", "<文件路径> <循环名称> <间隔秒数>", "循环运行 Function"),
        ("stop", "[循环名称]", "停止循环（不带参数停止所有）"),
        ("list", "[页码]", "查看函数文件列表"),
        ("search", "<关键词> [页码]", "搜索函数文件"),
    ]

    async def _cmd_function(self, sender, method, p1=None, p2=None, p3=None, p4=None, p5=None):
        """$function 方法分发器"""
        if method is None:
            self.client.tell(f"§cFunction | §fError > §i未知方法: 未指定（输入 {Command.command_prefix}function help 查看全部方法）", sender)
            return

        known = [m for m, _a, _d in self.FUNCTION_METHODS]
        if method not in known:
            self.client.tell(f"§cFunction | §fError > §i未知方法: {method}（输入 {Command.command_prefix}function help 查看全部方法）", sender)
            return

        # 分发到具体实现(全部为 op 权限,注册在 op 等级无需再查)
        if method == "function":
            if p1 is None:
                self.client.tell(f"§cFunction | §fError > §i参数不足：{Command.command_prefix}function function <文件路径>", sender)
                return
            await self._cmd_run(sender, p1)

        elif method == "loop":
            if p1 is None or p2 is None or p3 is None:
                self.client.tell(f"§cFunction | §fError > §i参数不足：{Command.command_prefix}function loop <文件路径> <循环名称> <间隔秒数>", sender)
                return
            try:
                interval = float(p3)
            except ValueError:
                self.client.tell(f'§cFunction | §fError > §i"{p3}" 处应为浮点型', sender)
                return
            await self._cmd_loop(sender, p1, p2, interval)

        elif method == "stop":
            await self._cmd_stop(sender, p1)

        elif method == "list":
            page = None
            if p1 is not None:
                try:
                    page = int(p1)
                except ValueError:
                    self.client.tell(f'§cFunction | §fError > §i"{p1}" 处应为整型', sender)
                    return
            await self._cmd_list(sender, page)

        elif method == "search":
            if p1 is None:
                self.client.tell(f"§cFunction | §fError > §i参数不足：{Command.command_prefix}function search <关键词> [页码]", sender)
                return
            page = None
            if p2 is not None:
                try:
                    page = int(p2)
                except ValueError:
                    self.client.tell(f'§cFunction | §fError > §i"{p2}" 处应为整型', sender)
                    return
            await self._cmd_search(sender, p1, page)

    # ---- 命令实现 ----

    async def _cmd_run(self, _, file_path):
        await self.run(file_path)

    async def _cmd_loop(self, _, file_path, name, interval):
        await self.loop(file_path, name, interval)

    async def _cmd_stop(self, _, name):
        self.stop(name)

    async def _cmd_list(self, sender, page):
        self.list_files(page, sender)

    async def _cmd_search(self, sender, keyword, page):
        self.search_files(keyword, page, sender)

    # ---- 文件列表 ----

    def format_size(self, size):
        """格式化文件大小(字节 → 可读单位)"""
        size = float(size or 0)
        if size >= 1024 * 1024:
            return f"{size / 1024 / 1024:.1f}MB"
        if size >= 1024:
            return f"{size / 1024:.1f}KB"
        return f"{int(size)}B"

    def show_files(self, sender, files, header):
        """分页展示文件列表(每页 5 个)"""
        if not files:
            self.client.tell("§cMCFunc | §fError > §i没有找到函数文件", sender)
            return

        page_size = 5
        total_pages = math.ceil(len(files) / page_size)
        page = self.page or 1
        pn = max(1, min(page, total_pages))
        self.page = pn

        start_index = (pn - 1) * page_size
        page_files = files[start_index:start_index + page_size]

        items = []
        for i, f in enumerate(page_files):
            num = str(start_index + i + 1).rjust(2, " ")
            file_path = os.path.join(basePath["mcfunc"], f)
            size = "?"
            try:
                size = self.format_size(os.path.getsize(file_path))
            except Exception:
                pass
            items.append(f"{num}. {f} §f{size}")
        items_text = "\n".join(items)

        self.client.tell(f"{header} §f({pn}/{total_pages}页) §i共 {len(files)} 个\n{items_text}", sender)

    def list_files(self, page, sender):
        """列出所有 .mcfunction 函数文件"""
        if page is not None:
            try:
                self.page = int(page) or 1
            except (ValueError, TypeError):
                self.page = 1
        else:
            self.page = 1
        dir_ = basePath["mcfunc"]
        files = sorted([
            f for f in os.listdir(dir_)
            if f.endswith(".mcfunction")
        ]) if os.path.exists(dir_) else []
        self.show_files(sender, files, "§eMCFunc | §fList")

    def search_files(self, keyword, page, sender):
        """搜索 .mcfunction 函数文件"""
        if page is not None:
            try:
                self.page = int(page) or 1
            except (ValueError, TypeError):
                self.page = 1
        else:
            self.page = 1
        dir_ = basePath["mcfunc"]
        files = sorted([
            f for f in os.listdir(dir_)
            if f.endswith(".mcfunction") and keyword.lower() in f.lower()
        ]) if os.path.exists(dir_) else []
        self.show_files(sender, files, f'§eMCFunc | §fSearch > §i"{keyword}"')

    # 加载函数文件
    # 返回按行分割的指令数组,失败返回 False
    async def load(self, file_name):
        try:
            with open(os.path.join(basePath["mcfunc"], file_name), "r", encoding="utf-8") as f:
                file = f.read()
            commands = file.split("\n")
            return commands
        except Exception:
            return False

    # 执行函数文件
    # deep: 当前嵌套深度(防止无限递归,上限 16)
    # commands: 已加载的指令数组(首次调用时为 None,内部加载)
    async def run(self, file_name, deep=0, commands=None):
        if commands is None:
            commands = await self.load(file_name)

            if not commands:
                self.client.tellAll(f'§cMCFunc | §fError > §i函数文件 "{file_name}" 加载失败')
                return

            if deep == 0:
                self.client.tellAll(f'§eMCFunc | §fRun > §i函数文件 "{file_name}" 已运行')

        # 嵌套深度限制
        if deep >= 16:
            return

        for command in commands:
            # 跳过注释行(以 # 开头)
            if command.startswith("#"):
                continue

            # 嵌套调用其他函数文件
            if command.startswith("function "):
                await self.run(command[len("function "):], deep + 1)
                continue

            # 执行普通指令
            await self.client.sendCommand(command)

    # 循环执行函数文件
    # loop_name: 循环标识名称
    # loop_interval: 循环间隔(秒),未指定则默认 50ms
    async def loop(self, file_name, loop_name=None, loop_interval=None):
        # 未指定名称时使用文件名作为循环名
        if not loop_name:
            loop_name = file_name

        commands = await self.load(file_name)

        if not commands:
            self.client.tellAll(f'§cMCFunc | §fError > §i函数文件 "{file_name}" 加载失败')
            return

        # 检查循环名是否已存在
        if loop_name in self.loops:
            self.client.tellAll(f'§cMCFunc | §fError > §i循环 "{loop_name}" 已存在')
            return

        # 默认间隔 50ms,否则将秒转换为毫秒(负数/异常值按 0 处理,避免循环空转)
        try:
            interval_ok = loop_interval is not None and float(loop_interval) > 0
        except Exception:
            interval_ok = False

        if not interval_ok:
            interval_ms = 50
        else:
            interval_ms = float(loop_interval) * 1000

        self.client.tellAll(f'§eMCFunc | §fLoop > §i循环 "{loop_name}" 已开启')

        # 创建定时任务循环执行
        async def _loop_worker():
            try:
                while True:
                    await self.run(file_name, 0, commands)
                    await asyncio.sleep(interval_ms / 1000)
            except asyncio.CancelledError:
                pass

        self.loops[loop_name] = asyncio.get_running_loop().create_task(_loop_worker())

    # 停止循环
    # loop_name: 指定循环名停止,为 None 时停止全部
    def stop(self, loop_name=None):
        if loop_name is None:
            # 停止所有循环
            for task in self.loops.values():
                task.cancel()
            self.loops.clear()
            self.client.tellAll("§eMCFunc | §fLoop > §i已停止所有循环")
            return

        if loop_name in self.loops:
            task = self.loops.pop(loop_name)
            task.cancel()
            self.client.tellAll(f'§eMCFunc | §fLoop > §i循环 "{loop_name}" 已关闭')
        else:
            self.client.tellAll(f'§cMCFunc | §fError > §i循环 "{loop_name}" 不存在')

    # 销毁方法 - 停止所有循环并释放引用
    def onDestroy(self):
        self.stop()
        self.client = None
