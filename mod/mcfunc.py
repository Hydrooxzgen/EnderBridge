"""Minecraft 函数文件执行 Mod

支持加载和执行 .mcfunction 格式的指令文件,支持嵌套调用和循环执行
"""
import asyncio
import os

from config import basePath
from lib.command import Command


class Mod:
    """函数文件执行 Mod(客户端)"""

    def __init__(self, client):
        self.client = client
        # 存储循环执行的定时器任务: 循环名 -> asyncio.Task
        self.loops = {}

    # 返回命令定义
    def onCommand(self):
        return {
            "op": [
                Command.create("f:function", "运行 Function 文件")
                .add_string("文件路径", True)
                .set_func(self._cmd_run),

                Command.create("f:loop", "循环运行 Function")
                .add_string("文件路径", True)
                .add_string("循环名称", True)
                .add_float("间隔秒数", True)
                .set_func(self._cmd_loop),

                Command.create("f:stop", "停止循环（不带参数停止所有）")
                .add_optional_string("循环名称")
                .set_func(self._cmd_stop),
            ],
        }

    # ---- 命令实现 ----

    async def _cmd_run(self, _, file_path):
        await self.run(file_path)

    async def _cmd_loop(self, _, file_path, name, interval):
        await self.loop(file_path, name, interval)

    async def _cmd_stop(self, _, name):
        self.stop(name)

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
