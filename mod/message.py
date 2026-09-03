"""消息通知 Mod

提供管理员从终端向全体玩家发送聊天通知的功能。

功能：
  $message <消息内容>  — 向全体玩家发送聊天通知（仅终端可用）
"""

from lib.command import Command


class Mod:
    """消息通知 Mod（客户端）"""

    logger = None  # 由 ModManager 注入,类型: lib.mods.ModLogger

    def __init__(self, client):
        self.client = client

    def onStart(self):
        self.logger.info("Message mod 已启动")  # type: ignore[union-attr]

    def onCommand(self):
        return {
            "normal": [
                Command.create("message", "向全体玩家发送聊天通知")
                .add_string("消息内容", True)
                .set_func(self._cmd_message),
            ],
            "op": [],
            "owner": [],
        }

    def _cmd_message(self, sender, content):
        """$message — 管理员发送全体聊天通知(仅终端可用)"""
        # 游戏内调用:静默忽略,不返回任何消息
        if getattr(self.client, "id", None) != "terminal":
            return

        from main import console_out

        if not content:
            console_out("§cMessage | §fError > §i用法: $message <消息内容>")
            return

        # 通过游戏客户端广播
        from lib.current import Current
        if Current.client:
            Current.client.tellAll(f"§e📢 通知 | §f{content}")
            console_out(f"§eMessage | §f已发送全体通知: {content}")
        else:
            console_out("§cMessage | §fError > §i无在线客户端，无法发送通知")
