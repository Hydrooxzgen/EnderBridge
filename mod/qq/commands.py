"""QQ 互通命令 Mod

提供 $qq send / $qq check / $qq toggle 命令(仅主客户端可用)。
"""
from config import features
from lib.command import Command
from lib.current import Current
from mod.qq.detector import Detector
from mod.qq.main import Mod as QQ


class Mod:
    """QQ 命令客户端 Mod(客户端,与主客户端绑定)"""

    def __init__(self, client):
        self.client = client
        self._is_main = client is Current.client
        if self._is_main:
            QQ.set_main_client(client)

    def onCommand(self):
        return {
            "user": [
                # qq send <消息内容> — 向 QQ 群发送消息
                Command.create("qq", "QQ 互通命令（方法: send/check/toggle，仅主客户端可用）")
                .add_string("方法", False)
                .add_optional_string("参数1")
                .add_optional_string("参数2")
                .add_optional_string("参数3")
                .add_optional_string("参数4")
                .add_optional_string("参数5")
                .set_func(self._cmd_qq),
            ],
        }

    # ---- 命令分发器 ----

    # (方法, 参数格式, 说明, 所需权限等级)
    QQ_METHODS = [
        ("send", "<消息内容>", "向 QQ 群发送消息", 1),
        ("check", "", "检测并手动重连 QQ", 3),
        ("toggle", "<true|false>", "开启/关闭 QQ 互通功能", 3),
    ]

    async def _cmd_qq(self, sender, method, p1=None, p2=None, p3=None, p4=None, p5=None):
        """$qq 方法分发器(方法内做权限检查)"""
        if method is None:
            self.client.tell(f"§cQQ | §fError > §i未知方法: 未指定（输入 {Command.command_prefix}qq help 查看全部方法）", sender)
            return

        # help 显示本模组方法列表
        if method == "help":
            lines = "\n".join(
                f"§a{Command.command_prefix}qq {mname}{' ' + margs if margs else ''} §7- §f{mdesc}"
                for mname, margs, mdesc, _l in self.QQ_METHODS
            )
            self.client.tell(f"§eQQ | §fHelp > §7可用方法\n{lines}", sender)
            return

        # 查询方法所需权限
        required = None
        for mname, _args, _desc, plevel in self.QQ_METHODS:
            if mname == method:
                required = plevel
                break
        if required is None:
            self.client.tell(f"§cQQ | §fError > §i未知方法: {method}（输入 {Command.command_prefix}qq help 查看全部方法）", sender)
            return

        # 权限检查
        from lib.permission import PermissionManager
        perm = await PermissionManager.query(sender)
        if isinstance(perm, Exception):
            self.client.tell("§cQQ | §fError > §i权限查询失败", sender)
            return
        if perm < required:
            self.client.tell("§cQQ | §fError > §i权限不足", sender)
            return

        # 分发到具体实现
        if method == "send":
            if p1 is None:
                self.client.tell(f"§cQQ | §fError > §i参数不足：{Command.command_prefix}qq send <消息内容>", sender)
                return
            await self._cmd_send(sender, p1)

        elif method == "check":
            await self._cmd_check(sender)

        elif method == "toggle":
            if p1 is None:
                self.client.tell(f"§cQQ | §fError > §i参数不足：{Command.command_prefix}qq toggle <true|false>", sender)
                return
            if p1 not in ("true", "false"):
                self.client.tell(f'§cQQ | §fError > §i"{p1}" 处应为布尔值 true/false', sender)
                return
            await self._cmd_toggle(sender, p1 == "true")

    async def _cmd_send(self, sender, text):
        if not self._is_main:
            self.client.tell("§cQQ | §fError > §i仅主客户端可使用此命令", sender)
            return

        check = Detector.detect(text)
        if not check["passed"]:
            self.client.tell(f"§cQQ | §fError > §i消息未通过检测: {check['reason']}", sender)
            return

        ok = await QQ.send_to_group(f"[MCBE]<{sender}> {text}")
        if ok:
            self.client.tell("§eQQ | §fSend > §i消息已发送", sender)
        else:
            self.client.tell("§cQQ | §fError > §i消息发送失败", sender)

    async def _cmd_check(self, sender):
        if not self._is_main:
            self.client.tell("§cQQ | §fError > §i仅主客户端可使用此命令", sender)
            return

        result = await QQ.check()
        if result["ok"]:
            self.client.tell(f"§eQQ | §fCheck > §i连接正常 ({result['nickname']})", sender)
        else:
            self.client.tell(f"§cQQ | §fError > §i自愈失败: {result['reason']}", sender)

    def _cmd_toggle(self, sender, enabled):
        if not self._is_main:
            self.client.tell("§cQQ | §fError > §i仅主客户端可使用此命令", sender)
            return
        features.qq["enabled"] = enabled
        self.client.tellAll(f"§eQQ | §fToggle > §i互通已{'启用' if enabled else '禁用'}")

    def onDestroy(self):
        if self._is_main:
            QQ.set_main_client(None)
            QQ.destroy()
        self.client = None
