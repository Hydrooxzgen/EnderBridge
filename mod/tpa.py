# Author: Hydrooxzgen
# Github: https://github.com/Hydrooxzgen
# This project uses the GPL-3.0 license, you can modify/distribute this project according to the GPL-3.0 license
"""玩家传送请求系统 Mod (TPA System)

提供无 OP 权限的玩家间传送请求与响应功能:
- $tpa <玩家名>: 请求传送到指定玩家身边 (附别名 $call)
- $tpahere <玩家名>: 请求指定玩家传送到自己身边 (附别名 $tphere)
- $tpaccept [玩家名]: 同意传送请求 (附别名 $tpyes, $agree)
- $tpdeny [玩家名]: 拒绝传送请求 (附别名 $tpno, $refuse)
- $tpcancel [玩家名]: 取消发出的传送请求 (附别名 $cancel)
"""
import time

from lib import shared
from lib.command import Command, apply_config_aliases


class Mod:
    """TPA 系统客户端 Mod"""

    terminal_compatible = False  # 仅游戏内玩家可用

    TIMEOUT_SECONDS = 60
    COOLDOWN_SECONDS = 5

    DIMENSION_NAMES = {
        0: "主世界",
        1: "下界",
        2: "末地",
        "overworld": "主世界",
        "nether": "下界",
        "the_end": "末地",
    }

    def __init__(self, client):
        self.client = client
        # key: (sender.lower(), target.lower()) -> request dict
        self.requests: dict[tuple[str, str], dict] = {}
        # key: sender.lower() -> timestamp
        self.cooldowns: dict[str, float] = {}

    def onStart(self):
        pass

    def onCommand(self):
        return {
            "normal": [
                apply_config_aliases(
                    Command.create("tpa", "请求传送到指定玩家身边")
                    .add_string("目标玩家", False)
                    .set_func(self._cmd_tpa)
                    .add_alias("call")
                ),
                apply_config_aliases(
                    Command.create("tpahere", "请求指定玩家传送到自己身边")
                    .add_string("目标玩家", False)
                    .set_func(self._cmd_tpahere)
                    .add_alias("tphere")
                ),
                apply_config_aliases(
                    Command.create("tpaccept", "同意传送请求")
                    .add_optional_string("玩家名")
                    .set_func(self._cmd_tpaccept)
                    .add_alias("tpyes")
                    .add_alias("agree")
                ),
                apply_config_aliases(
                    Command.create("tpdeny", "拒绝传送请求")
                    .add_optional_string("玩家名")
                    .set_func(self._cmd_tpdeny)
                    .add_alias("tpno")
                    .add_alias("refuse")
                ),
                apply_config_aliases(
                    Command.create("tpcancel", "取消发出的传送请求")
                    .add_optional_string("目标玩家")
                    .set_func(self._cmd_tpcancel)
                    .add_alias("cancel")
                ),
            ]
        }

    # ==============================================================
    # 内部辅助方法
    # ==============================================================

    def _clean_expired(self):
        """清理已超时的请求"""
        now = time.time()
        expired_keys = [
            k for k, req in self.requests.items()
            if now - req["created_at"] > self.TIMEOUT_SECONDS
        ]
        for k in expired_keys:
            del self.requests[k]

    def _get_incoming_requests(self, target_player: str) -> list[dict]:
        """获取某玩家收到的有效请求列表（按创建时间从新到旧排序）"""
        self._clean_expired()
        target_lower = target_player.lower()
        reqs = [
            req for (s, t), req in self.requests.items()
            if t == target_lower
        ]
        reqs.sort(key=lambda r: r["created_at"], reverse=True)
        return reqs

    def _get_outgoing_requests(self, sender_player: str) -> list[dict]:
        """获取某玩家发出的有效请求列表"""
        self._clean_expired()
        sender_lower = sender_player.lower()
        reqs = [
            req for (s, t), req in self.requests.items()
            if s == sender_lower
        ]
        reqs.sort(key=lambda r: r["created_at"], reverse=True)
        return reqs

    async def _check_player_online(self, player_name: str) -> dict | None:
        """检查玩家是否在线并获取坐标"""
        if not hasattr(self.client, "getLocation"):
            return None
        return await self.client.getLocation(f'"{player_name}"')

    # ==============================================================
    # $tpa 命令: 请求传送到对方身边
    # ==============================================================

    async def _cmd_tpa(self, sender: str, target: str):
        target = target.strip().strip('"')
        if sender.lower() == target.lower():
            self.client.tell("§c你不能对自己发起传送请求！", sender)
            return {"status": False, "message": "不能对自己发起传送", "quiet": True}

        # 限流冷却检查
        now = time.time()
        last_time = self.cooldowns.get(sender.lower(), 0.0)
        if now - last_time < self.COOLDOWN_SECONDS:
            remain = int(self.COOLDOWN_SECONDS - (now - last_time)) + 1
            self.client.tell(f"§c操作过于频繁，请等待 §e{remain} §c秒后再试！", sender)
            return {"status": False, "message": "操作过于频繁", "quiet": True}

        # 检查目标玩家是否在线
        target_loc = await self._check_player_online(target)
        if target_loc is None:
            self.client.tell(f"§c未找到玩家 §f[{target}] §c或该玩家不在线！", sender)
            return {"status": False, "message": "玩家不在线", "quiet": True}

        self._clean_expired()
        key = (sender.lower(), target.lower())

        # 检查是否已有未处理的请求
        if key in self.requests:
            self.client.tell(f"§e你已向 §f[{target}] §e发送过请求，请等待对方处理（输入 §b$tpcancel §e可取消）。", sender)
            return {"status": False, "message": "已有待处理请求", "quiet": True}

        # 记录请求
        self.requests[key] = {
            "sender": sender,
            "target": target,
            "type": "tpa",
            "created_at": now,
        }
        self.cooldowns[sender.lower()] = now

        prefix = Command.command_prefix
        # 提示发送者
        self.client.tell(
            f"§a✅ 已向玩家 §e{target} §a发送传送请求（§e{self.TIMEOUT_SECONDS}秒§a内有效）。\n§7输入 §b{prefix}tpcancel §7可随时取消。",
            sender
        )

        # 提示目标接收者
        self.client.tell(
            f"§e┌──────────────────────────────────────────────┐\n"
            f"§e│ §6[TPA 传送请求] §f玩家 §b{sender} §e请求传送到你所在位置！\n"
            f"§e│ §a• 输入 §f{prefix}tpaccept §a同意请求\n"
            f"§e│ §c• 输入 §f{prefix}tpdeny §c拒绝请求\n"
            f"§e│ §7(请求将在 {self.TIMEOUT_SECONDS} 秒后自动失效)\n"
            f"§e└──────────────────────────────────────────────┘",
            target
        )

        try:
            await self.client.runCommand(f'playsound random.orb "{target}" ~ ~ ~ 1 1')
        except Exception:
            pass

        return {"status": True}

    # ==============================================================
    # $tpahere 命令: 请求对方传送到自己身边
    # ==============================================================

    async def _cmd_tpahere(self, sender: str, target: str):
        target = target.strip().strip('"')
        if sender.lower() == target.lower():
            self.client.tell("§c你不能对自己发起传送请求！", sender)
            return {"status": False, "message": "不能对自己发起传送", "quiet": True}

        now = time.time()
        last_time = self.cooldowns.get(sender.lower(), 0.0)
        if now - last_time < self.COOLDOWN_SECONDS:
            remain = int(self.COOLDOWN_SECONDS - (now - last_time)) + 1
            self.client.tell(f"§c操作过于频繁，请等待 §e{remain} §c秒后再试！", sender)
            return {"status": False, "message": "操作过于频繁", "quiet": True}

        target_loc = await self._check_player_online(target)
        if target_loc is None:
            self.client.tell(f"§c未找到玩家 §f[{target}] §c或该玩家不在线！", sender)
            return {"status": False, "message": "玩家不在线", "quiet": True}

        self._clean_expired()
        key = (sender.lower(), target.lower())

        if key in self.requests:
            self.client.tell(f"§e你已向 §f[{target}] §e发送过请求，请等待对方处理（输入 §b$tpcancel §e可取消）。", sender)
            return {"status": False, "message": "已有待处理请求", "quiet": True}

        self.requests[key] = {
            "sender": sender,
            "target": target,
            "type": "tpahere",
            "created_at": now,
        }
        self.cooldowns[sender.lower()] = now

        prefix = Command.command_prefix
        self.client.tell(
            f"§a✅ 已向玩家 §e{target} §a发送请求对方传送至你身边的邀请（§e{self.TIMEOUT_SECONDS}秒§a内有效）。",
            sender
        )

        self.client.tell(
            f"§e┌──────────────────────────────────────────────┐\n"
            f"§e│ §6[TPA 邀请传送] §f玩家 §b{sender} §e邀请你传送到对方身边！\n"
            f"§e│ §a• 输入 §f{prefix}tpaccept §a同意前往\n"
            f"§e│ §c• 输入 §f{prefix}tpdeny §c拒绝邀请\n"
            f"§e│ §7(请求将在 {self.TIMEOUT_SECONDS} 秒后自动失效)\n"
            f"§e└──────────────────────────────────────────────┘",
            target
        )

        try:
            await self.client.runCommand(f'playsound random.orb "{target}" ~ ~ ~ 1 1')
        except Exception:
            pass

        return {"status": True}

    # ==============================================================
    # $tpaccept 命令: 接受传送请求并安全执行跨维度传送
    # ==============================================================

    async def _cmd_tpaccept(self, sender: str, player_name: str = None):
        incoming = self._get_incoming_requests(sender)
        if not incoming:
            self.client.tell("§c当前没有任何待处理的传送请求，或请求已超时！", sender)
            return {"status": False, "message": "无待处理请求", "quiet": True}

        # 匹配特定玩家或取最新的一个请求
        selected_req = None
        if player_name:
            p_clean = player_name.strip().strip('"').lower()
            for req in incoming:
                if req["sender"].lower() == p_clean:
                    selected_req = req
                    break
            if not selected_req:
                self.client.tell(f"§c未找到来自玩家 §f[{player_name}] §c的有效传送请求！", sender)
                return {"status": False, "message": "未匹配到指定玩家请求", "quiet": True}
        else:
            selected_req = incoming[0]

        # 移除已处理请求
        key = (selected_req["sender"].lower(), selected_req["target"].lower())
        self.requests.pop(key, None)

        req_type = selected_req["type"]
        sender_player = selected_req["sender"]
        target_player = selected_req["target"]

        # 确定谁被传送到谁身边
        if req_type == "tpa":
            who = sender_player  # 发起者传送到接收者身边
            destination = target_player
        else:
            who = target_player  # 接收者传送到发起者身边
            destination = sender_player

        # 查询双方坐标与维度
        loc_who = await self._check_player_online(who)
        loc_dest = await self._check_player_online(destination)

        if not loc_who:
            self.client.tell(f"§c传送失败: 玩家 §f[{who}] §c已离线！", sender)
            return {"status": False, "message": "玩家已离线", "quiet": True}

        if not loc_dest:
            self.client.tell(f"§c传送失败: 目标位置玩家 §f[{destination}] §c已离线！", sender)
            return {"status": False, "message": "目标玩家已离线", "quiet": True}

        dim_who = loc_who.get("dimension")
        dim_dest = loc_dest.get("dimension")
        x = loc_dest["x"]
        y = loc_dest["y"]
        z = loc_dest["z"]

        # 执行跨维度或同维度传送
        try:
            if dim_who is not None and dim_dest is not None and dim_who != dim_dest:
                cmd = f'execute in {dim_dest} run tp "{who}" {x:.2f} {y:.2f} {z:.2f}'
            else:
                cmd = f'tp "{who}" "{destination}"'
            await self.client.runCommand(cmd)

            # 播放传送提示音
            await self.client.runCommand(f'playsound random.levelup "{who}" ~ ~ ~ 1 1')
            await self.client.runCommand(f'playsound random.levelup "{destination}" ~ ~ ~ 1 1')
        except Exception as e:
            shared.logger.error(f"[TPA] 传送命令执行异常: {e}")

        # 告知双方
        self.client.tell(f"§a✨ 已同意传送请求，玩家 §e{who} §a已成功传送至 §e{destination} §a身边！", sender)
        if who != sender:
            self.client.tell(f"§a✨ 玩家 §e{sender} §a已同意你的传送请求，传送完成！", who)
        else:
            self.client.tell(f"§a✨ 玩家 §e{sender} §a已接受邀请并传送至你身边！", destination)

        shared.logger.info(f"[TPA] 成功执行传送: {who} -> {destination}")
        return {"status": True}

    # ==============================================================
    # $tpdeny 命令: 拒绝传送请求
    # ==============================================================

    async def _cmd_tpdeny(self, sender: str, player_name: str = None):
        incoming = self._get_incoming_requests(sender)
        if not incoming:
            self.client.tell("§c当前没有任何待处理的传送请求，或请求已超时！", sender)
            return {"status": False, "message": "无待处理请求", "quiet": True}

        selected_req = None
        if player_name:
            p_clean = player_name.strip().strip('"').lower()
            for req in incoming:
                if req["sender"].lower() == p_clean:
                    selected_req = req
                    break
            if not selected_req:
                self.client.tell(f"§c未找到来自玩家 §f[{player_name}] §c的有效传送请求！", sender)
                return {"status": False, "message": "未匹配到指定玩家请求", "quiet": True}
        else:
            selected_req = incoming[0]

        key = (selected_req["sender"].lower(), selected_req["target"].lower())
        self.requests.pop(key, None)

        req_sender = selected_req["sender"]
        self.client.tell(f"§e已拒绝来自玩家 §f[{req_sender}] §e的传送请求。", sender)
        self.client.tell(f"§c玩家 §f[{sender}] §c拒绝了你的传送请求。", req_sender)

        try:
            await self.client.runCommand(f'playsound note.bass "{req_sender}" ~ ~ ~ 1 1')
        except Exception:
            pass

        return {"status": True}

    # ==============================================================
    # $tpcancel 命令: 取消发出的传送请求
    # ==============================================================

    async def _cmd_tpcancel(self, sender: str, target_player: str = None):
        outgoing = self._get_outgoing_requests(sender)
        if not outgoing:
            self.client.tell("§c你当前没有发出任何待处理的传送请求！", sender)
            return {"status": False, "message": "无发出的请求", "quiet": True}

        selected_req = None
        if target_player:
            t_clean = target_player.strip().strip('"').lower()
            for req in outgoing:
                if req["target"].lower() == t_clean:
                    selected_req = req
                    break
            if not selected_req:
                self.client.tell(f"§c未找到发给玩家 §f[{target_player}] §c的待处理请求！", sender)
                return {"status": False, "message": "未匹配到指定玩家请求", "quiet": True}
        else:
            selected_req = outgoing[0]

        key = (selected_req["sender"].lower(), selected_req["target"].lower())
        self.requests.pop(key, None)

        target = selected_req["target"]
        self.client.tell(f"§a已取消向玩家 §e[{target}] §a发送的传送请求。", sender)
        self.client.tell(f"§7玩家 §f[{sender}] §7取消了此前发送的传送请求。", target)
        return {"status": True}

