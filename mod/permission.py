"""权限管理命令 Mod

提供游戏内权限查询、添加、删除的命令接口
"""
from lib.command import Command
from lib.permission import PermissionManager


class Mod:
    """权限管理命令类(客户端 Mod)"""

    def __init__(self, client):
        self.client = client

    # 返回命令定义
    def onCommand(self):
        return {
            # 普通命令:权限查询
            "normal": [
                Command.create("perm", "权限管理命令（方法: query/add/remove）")
                .add_alias("p")
                .add_string("方法", False)
                .add_optional_string("参数1")
                .add_optional_string("参数2")
                .add_optional_string("参数3")
                .add_optional_string("参数4")
                .add_optional_string("参数5")
                .set_func(self._cmd_perm),
            ],
        }

    # ---- 命令分发器 ----

    # (方法, 参数格式, 说明, 所需权限等级)
    PERM_METHODS = [
        ("query", "[账号]", "查询权限等级(不带参数查询自身)", 0),
        ("add", "<权限类型> <账号>", "添加指定账号权限", 3),
        ("remove", "<权限类型> <账号>", "删除指定账号权限", 3),
    ]

    async def _cmd_perm(self, sender, method, p1=None, p2=None, p3=None, p4=None, p5=None):
        """$perm 方法分发器(方法内做权限检查)"""
        if method is None:
            self.client.tell(f"§cPermission | §fError > §i未知方法: 未指定（输入 {Command.command_prefix}perm help 查看全部方法）", sender)
            return

        # help 显示本模组方法列表
        if method == "help":
            lines = "\n".join(
                f"§a{Command.command_prefix}perm {mname}{' ' + margs if margs else ''} §7- §f{mdesc}"
                for mname, margs, mdesc, _l in self.PERM_METHODS
            )
            self.client.tell(f"§ePermission | §fHelp > §7可用方法\n{lines}", sender)
            return

        # 查询方法所需权限
        required = None
        for mname, _args, _desc, plevel in self.PERM_METHODS:
            if mname == method:
                required = plevel
                break
        if required is None:
            self.client.tell(f"§cPermission | §fError > §i未知方法: {method}（输入 {Command.command_prefix}perm help 查看全部方法）", sender)
            return

        # 权限检查
        perm = await PermissionManager.query(sender)
        if isinstance(perm, Exception):
            self.client.tell("§cPermission | §fError > §i权限查询失败", sender)
            return
        if perm < required:
            self.client.tell("§cPermission | §fError > §i权限不足", sender)
            return

        # 分发到具体实现
        if method == "query":
            await self._cmd_query(sender, p1)

        elif method == "add":
            if p1 is None or p2 is None:
                self.client.tell(f"§cPermission | §fError > §i参数不足：{Command.command_prefix}perm add <权限类型> <账号>", sender)
                return
            await self._cmd_add(sender, p1, p2)

        elif method == "remove":
            if p1 is None or p2 is None:
                self.client.tell(f"§cPermission | §fError > §i参数不足：{Command.command_prefix}perm remove <权限类型> <账号>", sender)
                return
            await self._cmd_remove(sender, p1, p2)

    async def _cmd_query(self, commander, queried):
        # 无参数查询自身权限;带参数查询指定账号
        target = queried or commander
        permission = await PermissionManager.query(target)
        self.client.tell(f"§ePermission | §fQuery > §i{target} 权限: {permission}", commander)

    async def _cmd_add(self, _, object_, value):
        result = await PermissionManager.add(object_, value)
        if isinstance(result, Exception):
            self.client.tellAll(f"§cPermission | §fError > §i{result}")
            return
        self.client.tellAll(f"§ePermission | §fAdd > §i{value} -> {object_}")

    async def _cmd_remove(self, _, object_, value):
        result = await PermissionManager.remove(object_, value)
        if isinstance(result, Exception):
            self.client.tellAll(f"§cPermission | §fError > §i{result}")
            return
        self.client.tellAll(f"§ePermission | §fRemove > §i{value} <- {object_}")
