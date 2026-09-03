"""消息通知与协议 Mod

提供管理员消息通知（聊天/GUI 弹窗）和新玩家协议同意机制。

功能：
  $message text <msg>        — 向全体玩家发送聊天通知（需要 op 权限）
  $message box <msg>         — 向全体玩家发送 GUI 弹窗通知（需要 op 权限）
  $message reload            — 重新加载协议配置（需要 owner 权限）
  $message clear             — 清除所有已同意玩家（需要 owner 权限）
  $agree                     — 玩家同意服务器协议（任意玩家可用）

协议系统：
  新玩家加入时自动弹出协议窗口。未同意的玩家无法使用任何命令，
  每次发送命令时都会重新弹出协议窗口，直到点击"同意"。
  管理员（op 及以上）不受协议限制。
"""

import time

from lib.command import Command


class Mod:
    """消息通知与协议 Mod（客户端）"""

    # 协议弹窗冷却时间（秒），防止短时间内重复弹出
    _AGREEMENT_COOLDOWN = 3.0

    def __init__(self, client):
        self.client = client
        # 玩家最后收到协议弹窗的时间戳（内存级，重连后重置）
        self._dialog_cooldown: dict[str, float] = {}

    def onStart(self):
        """启动时订阅事件"""
        self._subscribe_join()
        self._subscribe_form_response()
        self.logger.info("Message mod 已启动")

    def onCommand(self):
        prefix = Command.command_prefix
        return {
            "normal": [
                # $agree — 任意玩家可用（包括未同意协议的玩家）
                Command.create("agree", "同意服务器协议")
                .set_func(self._cmd_agree),
                # $message — 管理命令（权限在处理函数中检查）
                Command.create("message", "消息通知（text=聊天 / box=弹窗）")
                .add_string("类型", False)
                .add_optional_string("消息内容")
                .set_func(self._cmd_message),
            ],
            "op": [],
            "owner": [],
        }

    # ===== 命令处理 =====

    async def _cmd_message(self, sender, msg_type, content=None):
        """$message 命令处理"""
        from lib.permission import PermissionManager

        perm = await PermissionManager.query(sender)
        if isinstance(perm, Exception) or perm < 2:
            self.client.tell(
                f"§cMessage | §fError > §i权限不足，需要 op 及以上", sender
            )
            return

        if msg_type == "text":
            if not content:
                self.client.tell(
                    f"§cMessage | §fError > §i用法: {Command.command_prefix}message text <消息内容>",
                    sender,
                )
                return
            self.client.tellAll(
                f"§e📢 通知 | §f{content}"
            )
            self.client.tell(
                f"§eMessage | §fInfo > §i已发送全体聊天通知", sender
            )

        elif msg_type == "box":
            if not content:
                self.client.tell(
                    f"§cMessage | §fError > §i用法: {Command.command_prefix}message box <消息内容>",
                    sender,
                )
                return
            await self._send_dialog("@a", "📢 管理员通知", content)
            self.client.tell(
                f"§eMessage | §fInfo > §i已发送全体弹窗通知", sender
            )

        elif msg_type == "reload":
            if perm < 3:
                self.client.tell(
                    f"§cMessage | §fError > §i需要 owner 权限", sender
                )
                return
            self._dialog_cooldown.clear()
            self.client.tell(
                f"§eMessage | §fInfo > §i协议配置已重新加载", sender
            )

        elif msg_type == "clear":
            if perm < 3:
                self.client.tell(
                    f"§cMessage | §fError > §i需要 owner 权限", sender
                )
                return
            self.storage.delete("agreed_players")
            self._dialog_cooldown.clear()
            self.client.tell(
                f"§eMessage | §fInfo > §i已清除所有玩家的协议同意状态", sender
            )
            self.client.tellAll(
                f"§e📢 通知 | §f协议同意状态已重置，请重新同意协议"
            )

        else:
            self.client.tell(
                f"§cMessage | §fError > §i未知类型: {msg_type}（可用: text / box / reload / clear）",
                sender,
            )

    async def _cmd_agree(self, sender):
        """$agree — 玩家同意协议"""
        agreed = self._get_agreed()
        if sender in agreed:
            self.client.tell(
                f"§aMessage | §fInfo > §i你已经同意过协议了", sender
            )
            return

        agreed.append(sender)
        self.storage.set("agreed_players", agreed)
        self._dialog_cooldown.pop(sender, None)
        self.client.tell(
            f"§aMessage | §fInfo > §i✅ 感谢同意协议，你现在可以使用所有命令了！",
            sender,
        )
        self.logger.info(f"玩家 {sender} 已同意协议")

    # ===== 协议检查（由 lib/mods.py 调用） =====

    def check_agreement(self, sender: str) -> bool:
        """检查玩家是否已同意协议

        Returns:
            True = 已同意或无需检查; False = 未同意（应阻止命令执行）
        """
        if not self._is_agreement_enabled():
            return True

        # 管理员不受协议限制
        try:
            from lib.permission import PermissionManager
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    # 在异步上下文中，使用同步版本
                    perm = asyncio.run_coroutine_threadsafe(
                        PermissionManager.query(sender), loop
                    ).result(timeout=2)
                else:
                    perm = asyncio.get_event_loop().run_until_complete(
                        PermissionManager.query(sender)
                    )
            except Exception:
                perm = 0

            if isinstance(perm, int) and perm >= 2:
                return True
        except Exception:
            pass

        agreed = self._get_agreed()
        return sender in agreed

    def show_agreement_dialog(self, sender: str):
        """向玩家显示协议弹窗（带冷却时间）"""
        now = time.time()
        last = self._dialog_cooldown.get(sender, 0)
        if now - last < self._AGREEMENT_COOLDOWN:
            return
        self._dialog_cooldown[sender] = now

        cfg = self._get_config()
        text = cfg.get("text", "请同意服务器协议后继续游戏。")
        title = cfg.get("title", "📋 服务器协议")

        # 优先使用 GUI 弹窗
        self._send_dialog(f"@a[name={sender}]", title, text)

    # ===== 事件订阅 =====

    def _subscribe_join(self):
        """订阅 PlayerJoin 事件，新玩家加入时检查协议"""

        async def _on_join(data):
            body = data.get("body", {})
            player = body.get("sender") or body.get("player")
            if not player:
                return
            self.logger.info(f"玩家 {player} 加入，检查协议状态")
            # 延迟发送，等待客户端加载完成
            import asyncio

            await asyncio.sleep(2.0)
            if not self._is_agreement_enabled():
                return
            agreed = self._get_agreed()
            if player not in agreed:
                self.show_agreement_dialog(player)
                self.client.tell(
                    f"§e📢 通知 | §f请先同意服务器协议（输入 {Command.command_prefix}agree）",
                    player,
                )

        self.client.subscribe("PlayerJoin", _on_join)

    def _subscribe_form_response(self):
        """订阅 PlayerFormResponse 事件，处理协议弹窗按钮点击"""

        def _on_form_response(data):
            body = data.get("body", {})
            player = body.get("sender") or body.get("playerName") or ""
            # form_id 用于区分不同类型的弹窗
            form_id = body.get("formId", "")
            # button_id: 0 = 第一个按钮（同意），1 = 第二个按钮（不同意/关闭）
            button_id = body.get("buttonId", -1)

            if button_id == 0:
                # 玩家点击了"同意"
                agreed = self._get_agreed()
                if player not in agreed:
                    agreed.append(player)
                    self.storage.set("agreed_players", agreed)
                    self._dialog_cooldown.pop(player, None)
                    self.client.tell(
                        f"§aMessage | §fInfo > §i✅ 感谢同意协议，你现在可以使用所有命令了！",
                        player,
                    )
                    self.logger.info(f"玩家 {player} 通过 GUI 同意了协议")
            else:
                # 玩家关闭了弹窗或点击了"不同意"，重新发送
                self._dialog_cooldown.pop(player, None)
                import asyncio

                asyncio.get_event_loop().call_later(
                    1.0, lambda: self.show_agreement_dialog(player)
                )

        self.client.subscribe("PlayerFormResponse", _on_form_response)

    # ===== 内部工具方法 =====

    def _get_config(self) -> dict:
        """读取 messageConfig 配置"""
        try:
            from config import messageConfig

            return messageConfig or {}
        except Exception:
            return {}

    def _is_agreement_enabled(self) -> bool:
        """协议功能是否开启"""
        return bool(self._get_config().get("agreement", {}).get("enabled", False))

    def _get_agreed(self) -> list:
        """获取已同意协议的玩家列表"""
        agreed = self.storage.get("agreed_players", [])
        return [p for p in agreed if isinstance(p, str) and p.strip()]

    async def _send_dialog(self, target: str, title: str, message: str):
        """发送 GUI 弹窗（MCBE /dialog 命令）

        如果 /dialog 命令不可用（旧版服务器），自动降级为聊天消息。
        """
        # 转义引号
        safe_title = title.replace('"', '\\"')
        safe_msg = message.replace('"', '\\"')
        cmd = f'/dialog {target} modal "{safe_title}" "{safe_msg}" "同意" "不同意"'
        try:
            result = await self.client.runCommand(cmd, 5000)
            # 检查命令是否成功（statusCode == 0 表示成功）
            if isinstance(result, dict):
                status = result.get("body", {}).get("statusCode", -1)
                if status != 0:
                    # /dialog 不可用，降级为聊天消息
                    await self._fallback_text(target, title, message)
        except Exception:
            # 命令超时或异常，降级
            await self._fallback_text(target, title, message)

    async def _fallback_text(self, target: str, title: str, message: str):
        """降级方案：用 tellraw 发送文本协议"""
        lines = message.split("\\n") if "\\n" in message else message.split("\n")
        header = f"§e{title} §7(§f/gui§7)"
        self.client.tell(header, target)
        for line in lines:
            if line.strip():
                self.client.tell(f"§f{line.strip()}", target)
        self.client.tell(
            f"§a输入 {Command.command_prefix}agree §f同意协议", target
        )
