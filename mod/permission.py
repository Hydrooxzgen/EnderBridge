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
                Command.create("p:query", "查询权限等级(不带参数查询自身)")
                .add_string("账号", True)
                .set_func(self._cmd_query),
            ],

            # Owner 命令:权限增删
            "owner": [
                Command.create("p:add", "添加指定账号权限")
                .add_string("权限类型", True)
                .add_string("账号", True)
                .set_func(self._cmd_add),

                Command.create("p:remove", "删除指定账号权限")
                .add_string("权限类型", True)
                .add_string("账号", True)
                .set_func(self._cmd_remove),
            ],
        }

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
