"""工具 Mod

提供命令帮助、搜索、终端执行、SAPI 控制、主客户端切换等管理功能
"""
import asyncio
import asyncio.subprocess
import re
import time
from datetime import datetime, timedelta, timezone

from lib.command import Command
from lib.current import Current
from lib.mods import ClientModManager, ServerModManager
from lib.permission import PermissionManager

# QQ 互通为可选依赖,导入失败时置 None(tool move 会跳过 QQ 切换)
try:
    from mod.qq.main import Mod as QQMod
except Exception:
    QQMod = None


class Mod:
    """工具 Mod(客户端)"""

    @staticmethod
    def format_help(commands, page=1, per_page=5, nav_command="tool", title="命令帮助"):
        """格式化命令帮助列表

        Args:
            commands: 命令对象列表
            page: 页码(从 1 开始)
            per_page: 每页显示数量
            nav_command: 翻页导航命令(不含页码,默认 tool)
            title: 列表标题

        Returns:
            格式化后的帮助信息行列表
        """
        prefix = Command.command_prefix
        # tool 排最前,其余按名称字典序
        sorted_ = sorted(commands, key=lambda c: (c.name != "tool", c.name))

        total = len(sorted_)
        total_pages = max(1, (total + per_page - 1) // per_page)
        p = min(max(1, page), total_pages)
        start = (p - 1) * per_page
        page_items = sorted_[start:start + per_page]

        lines = []
        lines.append(f"§d─── {prefix}{title} §f[{p}/{total_pages}] §d───")

        for cmd in page_items:
            desc = cmd.description or "§7无描述"
            lines.append(f"§c{prefix}{cmd.name} §f- §b{desc}")
            if cmd.parameters and len(cmd.parameters) > 0:
                param_strs = []
                for param in cmd.parameters:
                    now_type, now_desc = param[0], param[1]
                    optional = param[2] if len(param) > 2 else False
                    type_name = "|".join(now_type) if isinstance(now_type, list) else now_type
                    desc_part = f" §7{now_desc}" if now_desc else ""
                    param_strs.append(
                        f"§u({type_name}§u){desc_part}" if optional else f"§b{type_name}{desc_part}"
                    )
                lines.append(f"  §iParams: {' '.join(param_strs)}")

        if p < total_pages:
            lines.append(f"§7输入 {prefix}{nav_command} {p + 1} 查看下一页")
        return lines

    def __init__(self, client):
        self.client = client

    def onCommand(self):
        return {
            "normal": [
                Command.create("tool", "工具命令（方法: help/search/send/tellall/cmd/ping/time/start/move/reload/mod/exec）")
                .add_string("方法", False)
                .add_optional_string("参数1")
                .add_optional_string("参数2")
                .add_optional_string("参数3")
                .add_optional_string("参数4")
                .add_optional_string("参数5")
                .set_func(self._cmd_tool),
            ],
        }

    # ---- 命令分发器 ----

    # 方法所需权限等级: 0=normal 1=user 2=op 3=owner
    TOOL_METHODS = [
        ("help", "[页码]", "查看命令帮助", 0),
        ("search", "<关键词> [页码]", "搜索命令", 0),
        ("send", "<消息内容>", "向外部发送消息", 2),
        ("tellall", "<true|false>", "查看/切换本客户端 tellAll 转发模式", 2),
        ("cmd", "<命令内容>", "执行基岩版命令", 2),
        ("ping", "", "检测与服务器的延迟", 3),
        ("time", "", "查看当前时间(北京时间)", 3),
        ("start", "", "重新开始 SAPI 轮询", 3),
        ("move", "", "将当前客户端设为主客户端", 3),
        ("reload", "[Mod 名称]", "重载客户端 Mod(带名称重载单个,不带重载全部客户端)", 3),
        ("mod", "", "显示所有客户端 Mod", 3),
        ("exec", "<命令内容>", "在服务器终端执行命令", 3),
    ]

    async def _cmd_tool(self, sender, method, p1=None, p2=None, p3=None, p4=None, p5=None):
        """$tool 方法分发器(方法内做权限检查)"""
        if method is None:
            self.client.tell(f"§cTool | §fError > §i未知方法: 未指定（输入 {Command.command_prefix}tool help 查看全部方法）", sender)
            return

        # 查询方法所需权限
        required = None
        for mname, _args, _desc, plevel in self.TOOL_METHODS:
            if mname == method:
                required = plevel
                break
        if required is None:
            self.client.tell(f"§cTool | §fError > §i未知方法: {method}（输入 {Command.command_prefix}tool help 查看全部方法）", sender)
            return

        # 权限检查
        perm = await PermissionManager.query(sender)
        if isinstance(perm, Exception):
            self.client.tell("§cTool | §fError > §i权限查询失败", sender)
            return
        if perm < required:
            self.client.tell("§cTool | §fError > §i权限不足", sender)
            return

        # 分发到具体实现
        if method == "help":
            page = None
            if p1 is not None:
                if not re.fullmatch(r"-?\d+", p1):
                    self.client.tell(f'§cTool | §fError > §i"{p1}" 处应为整型', sender)
                    return
                page = int(p1)
            await self._cmd_help(sender, page)

        elif method == "search":
            if p1 is None:
                self.client.tell(f"§cTool | §fError > §i参数不足：{Command.command_prefix}tool search <关键词> [页码]", sender)
                return
            page = None
            if p2 is not None:
                if not re.fullmatch(r"-?\d+", p2):
                    self.client.tell(f'§cTool | §fError > §i"{p2}" 处应为整型', sender)
                    return
                page = int(p2)
            await self._cmd_search(sender, p1, page)

        elif method == "send":
            if p1 is None:
                self.client.tell(f"§cTool | §fError > §i参数不足：{Command.command_prefix}tool send <消息内容>", sender)
                return
            await self._cmd_send(sender, p1)

        elif method == "tellall":
            mode = None
            if p1 is not None:
                if p1 not in ("true", "false"):
                    self.client.tell(f'§cTool | §fError > §i"{p1}" 处应为布尔型', sender)
                    return
                mode = p1 == "true"
            await self._cmd_tellall(sender, mode)

        elif method == "cmd":
            if p1 is None:
                self.client.tell(f"§cTool | §fError > §i参数不足：{Command.command_prefix}tool cmd <命令内容>", sender)
                return
            await self._cmd_cmd(sender, p1)

        elif method == "ping":
            await self._cmd_ping(sender)

        elif method == "time":
            await self._cmd_time(sender)

        elif method == "start":
            await self._cmd_start(sender)

        elif method == "move":
            await self._cmd_move(sender)

        elif method == "reload":
            await self._cmd_reload(sender, p1)

        elif method == "mod":
            await self._cmd_mod(sender)

        elif method == "exec":
            if p1 is None:
                self.client.tell(f"§cTool | §fError > §i参数不足：{Command.command_prefix}tool exec <命令内容>", sender)
                return
            await self._cmd_exec(sender, p1)

    # ---- 命令实现 ----

    async def _cmd_help(self, sender, page):
        perm = await PermissionManager.query(sender)
        if isinstance(perm, Exception):
            self.client.tell("§cTool | §fError > §i权限查询失败", sender)
            return

        cmd_map = self.client.clientMod.commands
        cmds = list(cmd_map["normal"])

        if perm >= 1:
            cmds.extend(cmd_map["user"])
        if perm >= 2:
            cmds.extend(cmd_map["op"])
        if perm >= 3:
            cmds.extend(cmd_map["owner"])

        lines = Mod.format_help(cmds, page or 1, 5)
        for line in lines:
            self.client.tell(line, sender)

    async def _cmd_search(self, sender, keyword, page):
        perm = await PermissionManager.query(sender)
        if isinstance(perm, Exception):
            self.client.tell("§cTool | §fError > §i权限查询失败", sender)
            return

        cmd_map = self.client.clientMod.commands
        cmds = list(cmd_map["normal"])

        if perm >= 1:
            cmds.extend(cmd_map["user"])
        if perm >= 2:
            cmds.extend(cmd_map["op"])
        if perm >= 3:
            cmds.extend(cmd_map["owner"])

        kw = keyword.lower()
        matched = [
            cmd for cmd in cmds
            if (cmd.name and kw in cmd.name.lower())
            or (cmd.description and kw in cmd.description.lower())
        ]

        if not matched:
            self.client.tell(f'§cTool | §fSearch > §i没有找到与 "{keyword}" 相关的命令', sender)
            return

        lines = Mod.format_help(matched, page or 1, 5, f"tool search {keyword}", f'命令搜索 "{keyword}"')
        for line in lines:
            self.client.tell(line, sender)

    async def _cmd_send(self, _, text):
        self.client.tellAll(text)

    async def _cmd_tellall(self, sender, mode):
        utils = self.client.utils
        if not utils or not hasattr(utils, "setTellAllMode"):
            self.client.tell("§cTool | §fError > §i当前客户端不支持此设置", sender)
            return
        # 未提供参数:显示当前模式
        if mode is None:
            cur = utils.getTellAllMode()
            self.client.tell(f"§eTool | §fTellAll > §i当前 {'转发为 tell' if cur else '按原样广播'}", sender)
            return
        utils.setTellAllMode(mode)
        self.client.tell(f"§eTool | §fTellAll > §i已{'开启转发' if mode else '恢复原样'}", sender)

    async def _cmd_cmd(self, _, command):
        try:
            data = await self.client.runCommand(command)
            body = data.get("body", {}) if isinstance(data, dict) else {}
            status = body.get("statusCode")
            msg = body.get("statusMessage") or "无返回消息"
            self.client.tellAll(f"§eTool | §fCommand > §i[{status}] {msg}")
        except Exception as e:
            self.client.tellAll(f"§cTool | §fError > §i命令执行失败: {e}")

    async def _cmd_ping(self, _):
        start = time.time() * 1000
        try:
            await self.client.runCommand("list")
            ms = time.time() * 1000 - start
            self.client.tellAll(f"§eTool | §fPing > §i{ms:.0f}ms")
        except Exception:
            self.client.tellAll("§cTool | §fError > §i命令执行失败")

    async def _cmd_time(self, sender):
        bj = datetime.now(timezone.utc) + timedelta(hours=8)
        self.client.tell(f"§eTool | §fTime > §i{bj:%Y-%m-%d %H:%M:%S}", sender)

    async def _cmd_start(self, sender):
        # 重置当前客户端与主客户端的统一 SAPI 轮询器
        local_hub = self.client.clientMod.sapi if self.client.clientMod else None
        main_hub = Current.client.clientMod.sapi if (Current.client and Current.client.clientMod) else None

        hubs = []
        for hub in (local_hub, main_hub):
            if hub and hub not in hubs:
                hubs.append(hub)

        for hub in hubs:
            hub.command_exists = None
            hub.start()

        self.client.tell(f"§eTool | §fSAPI > §i已重新开始 {len(hubs)} 个 SAPI 轮询器", sender)

    async def _cmd_move(self, sender):
        if self.client is Current.client:
            self.client.tell("§cTool | §fError > §i你已经是主客户端", sender)
            return

        old_mods = Current.client_mods.get(Current.client)
        if old_mods:
            old_mods.destroy()
            del Current.client_mods[Current.client]

        try:
            await Current.client.close()
        except Exception:
            pass

        Current.client = self.client
        if QQMod is not None:
            QQMod.set_main_client(self.client)
        # 主客户端切换后重新挂载服务端 Mod 的 SAPI
        ServerModManager.attach_main_client(self.client)

        self.client.tellAll(f"§eTool | §fMove > §i主客户端已切换至 {sender}")

    async def _cmd_reload(self, sender, mod_name):
        client = self.client
        if mod_name:
            manager = client.clientMod
            if not manager or not hasattr(manager, "reload"):
                client.tell("§cTool | §fError > §i无法重载：客户端 Mod 管理器不可用", sender)
                return
            result = await manager.reload(mod_name)
            client.tellAll(f"§eTool | §fReload > §i{result.get('message', '')}")
        else:
            result = await ClientModManager.reload_all_clients()
            client.tellAll(
                f"§eTool | §fReload > §i客户端 Mod 全量重载完成 成功: {len(result['success']) or 0} 失败: {len(result['failed']) or 0}"
            )
            for f in result["failed"]:
                client.tellAll(f"§cTool | §fError > §i{f}")

    async def _cmd_mod(self, sender):
        client = self.client
        mod_names = list((ClientModManager.loaded_mod or {}).keys())
        client.tell(f"§eTool | §fMods > §i共 {len(mod_names)} 个", sender)
        if not mod_names:
            client.tell("§i无", sender)
        else:
            for name in mod_names:
                client.tell(f"§f{name}", sender)

    async def _cmd_exec(self, _, command):
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            except asyncio.TimeoutError:
                proc.kill()
                stdout, stderr = await proc.communicate()

            output = (stdout or b"").decode(errors="replace") or (stderr or b"").decode(errors="replace") or ""
            lines = [line for line in output.split("\n") if line]

            if not lines:
                self.client.tellAll("§i(无输出)")
                return

            for line in lines:
                self.client.tellAll(line)
        except Exception as e:
            self.client.tellAll(f"§cTool | §fError > §i{e}")

    def onDestroy(self):
        self.client = None
