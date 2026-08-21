"""QQ 互通命令 Mod

提供 q:send / q:check / q:toggle 命令(仅主客户端可用)。
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
                # q:send <消息内容> — 向 QQ 群发送消息
                Command.create("q:send", "向 QQ 群发送消息")
                .add_string("消息内容", True)
                .set_func(self._cmd_send),
            ],

            "owner": [
                # q:check — 检测并手动重连 QQ
                Command.create("q:check", "检测并手动重连 QQ")
                .set_func(self._cmd_check),

                # q:toggle <true|false> — 开启/关闭 QQ 互通功能
                Command.create("q:toggle", "开启/关闭 QQ 互通功能")
                .add_boolean("启用或禁用", True)
                .set_func(self._cmd_toggle),
            ],
        }

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
