"""消息通知 Mod

提供管理员从终端向全体玩家发送聊天通知的功能，以及定时公告轮播。

功能：
  $message <消息内容>  — 向全体玩家发送聊天通知（仅终端可用）
  $message reload      — 重载定时公告配置（仅终端可用）
"""

import asyncio
import os

from lib.command import Command, apply_config_aliases
from lib.current import Current


def _load_announcement_config():
    """从 config.py 读取定时公告配置"""
    try:
        import config
        return getattr(config, "messageConfig", {}).get("announcements", {})
    except Exception:
        return {}


class Mod:
    """消息通知 Mod -- (client)"""

    logger = None  # 由 ModManager 注入,类型: lib.mods.ModLogger

    def __init__(self, client):
        self.client = client
        self._announce_task = None
        self._announce_config = {}
        self._announce_index = 0

    def onStart(self):
        self.logger.info("Message mod 已启动")  # type: ignore[union-attr]
        self._load_and_start_announcements()

    def _load_and_start_announcements(self):
        """加载配置并启动定时公告任务"""
        # 取消旧任务
        if self._announce_task and not self._announce_task.done():
            self._announce_task.cancel()

        self._announce_config = _load_announcement_config()
        self._announce_index = 0

        if not self._announce_config.get("enabled", False):
            return

        interval = self._announce_config.get("interval", 300)
        messages = self._announce_config.get("messages", [])
        if not messages:
            return

        async def _announce_loop():
            try:
                while True:
                    await asyncio.sleep(interval)
                    if not Current.client:
                        continue
                    msg = messages[self._announce_index % len(messages)]
                    self._announce_index += 1
                    Current.client.tellAll(f"§e[公告] §f{msg}")
            except asyncio.CancelledError:
                pass
            except Exception as e:
                self.logger.error(f"定时公告任务异常: {e}")  # type: ignore[union-attr]

        self._announce_task = asyncio.create_task(_announce_loop())
        self.logger.info(f"定时公告已启动: 间隔 {interval}s, 共 {len(messages)} 条")  # type: ignore[union-attr]

    def reload_announcements(self):
        """重载定时公告配置（供终端命令调用）"""
        self._load_and_start_announcements()
        return "定时公告配置已重载"

    def onCommand(self):
        return {
            "normal": [
                apply_config_aliases(
                    Command.create("message", "向全体玩家发送聊天通知 / 管理定时公告")
                    .add_string("消息内容或子命令", True)
                    .add_optional_string("参数")
                    .set_func(self._cmd_message)
                ),
            ],
            "op": [],
            "owner": [],
        }

    def _cmd_message(self, sender, content, arg2=None):
        """$message — 管理员发送全体聊天通知 / 管理定时公告（仅终端可用）"""
        # 游戏内调用:静默忽略,不返回任何消息
        if getattr(self.client, "id", None) != "terminal":
            return

        from main import console_out

        # 子命令: reload
        if content == "reload":
            result = self.reload_announcements()
            console_out(f"§eMessage | §f{result}")
            return

        if not content:
            console_out("§cMessage | §fError > §i用法: $message <消息内容> | $message reload")
            return

        # 通过游戏客户端广播
        if Current.client:
            Current.client.tellAll(f"§e通知 | §f{content}")
            console_out(f"§eMessage | §f已发送全体通知: {content}")
        else:
            console_out("§cMessage | §fError > §i无在线客户端，无法发送通知")
