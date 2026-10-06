"""跨维度传送点与家管理 Mod (Home & Warp System)

提供玩家个人传送点 ($home) 与全服公共传送点 ($warp) 跨维度传送支持。
- $home: 玩家各自独立的家 (基于 StorageManager 持久化)
- $warp: 全服共享公共传送点 (存储于 config/warps.json)
"""
import asyncio
import json
import math
import os
import time

from lib import shared
from lib.command import Command, apply_config_aliases
from lib.permission import PermissionManager

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")
WARPS_JSON = os.path.join(CONFIG_DIR, "warps.json")
HOMES_JSON = os.path.join(CONFIG_DIR, "homes.json")


def _read_warps() -> dict:
    """读取公共传送点字典"""
    if os.path.isfile(WARPS_JSON):
        try:
            with open(WARPS_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            shared.logger.error(f"[Warp] 读取 warps.json 失败: {e}")
    return {}


def _save_warps(warps: dict) -> bool:
    """安全保存公共传送点"""
    try:
        from lib.file_lock import SystemFileLockManager
        with SystemFileLockManager.unlock_for_write(WARPS_JSON):
            tmp = WARPS_JSON + f".tmp_{os.getpid()}"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(warps, f, ensure_ascii=False, indent=2)
            os.replace(tmp, WARPS_JSON)
        return True
    except Exception as e:
        shared.logger.error(f"[Warp] 保存 warps.json 失败: {e}")
        return False


def _read_homes() -> dict:
    """读取所有玩家的家数据: {player_name: {home_name: home_data}}"""
    if os.path.isfile(HOMES_JSON):
        try:
            with open(HOMES_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            shared.logger.error(f"[Warp] 读取 homes.json 失败: {e}")
    return {}


def _save_homes(homes: dict) -> bool:
    """安全保存所有玩家的家数据"""
    try:
        from lib.file_lock import SystemFileLockManager
        with SystemFileLockManager.unlock_for_write(HOMES_JSON):
            tmp = HOMES_JSON + f".tmp_{os.getpid()}"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(homes, f, ensure_ascii=False, indent=2)
            os.replace(tmp, HOMES_JSON)
        return True
    except Exception as e:
        shared.logger.error(f"[Warp] 保存 homes.json 失败: {e}")
        return False


class Mod:
    """Home & Warp 系统客户端 Mod"""

    terminal_compatible = True  # 支持控制台与终端脱机执行管理与查询

    # 维度中文映射
    DIMENSION_NAMES = {
        0: "主世界 (Overworld)",
        1: "下界 (Nether)",
        2: "末地 (The End)",
        "overworld": "主世界 (Overworld)",
        "nether": "下界 (Nether)",
        "the_end": "末地 (The End)",
    }

    def __init__(self, client):
        self.client = client

    def onStart(self):
        """基础设施注入"""
        pass

    def onCommand(self):
        return {
            "normal": [
                apply_config_aliases(
                    Command.create("home", "家传送点命令（方法: set/tp/list/del）")
                    .add_string("方法", False)
                    .add_optional_string("名称")
                    .set_func(self._cmd_home)
                ),
                apply_config_aliases(
                    Command.create("warp", "公共传送点命令（方法: tp/list/set/del）")
                    .add_string("方法", False)
                    .add_optional_string("名称")
                    .set_func(self._cmd_warp)
                ),
            ]
        }

    # ==============================================================
    # 辅助方法: 执行安全精准跨维度传送
    # ==============================================================

    async def _safe_teleport(self, sender: str, target_pos: dict, point_name: str) -> bool:
        """执行传送，并播放音效与提示"""
        x = target_pos.get("x", 0.0)
        y = target_pos.get("y", 64.0)
        z = target_pos.get("z", 0.0)
        dim = target_pos.get("dimension")

        # 检查发送者与目标维度
        current_loc = await self.client.getLocation(sender) if hasattr(self.client, "getLocation") else None
        current_dim = current_loc.get("dimension") if current_loc else None

        # 如果跨维度且支持维度传送
        dim_str = ""
        if dim is not None:
            dim_str = f" in {dim}" if isinstance(dim, str) else ""

        # 执行传送命令
        tp_cmd = f"tp {sender} {x:.2f} {y:.2f} {z:.2f}"
        if current_dim is not None and dim is not None and current_dim != dim:
            # 基岩版跨维度传送语法: execute in <dimension> run tp <player> <x> <y> <z>
            tp_cmd = f"execute in {dim} run tp {sender} {x:.2f} {y:.2f} {z:.2f}"

        await self.client.runCommand(tp_cmd)

        # 播放传送提示音与视觉反馈
        try:
            await self.client.runCommand(f"playsound random.orb {sender} ~ ~ ~ 1 1")
        except Exception:
            pass

        dim_desc = self.DIMENSION_NAMES.get(dim, str(dim)) if dim is not None else "未知维度"
        self.client.tell(
            f"§a✨ 已成功传送到 §e[{point_name}]§a！§7(坐标: {x:.1f}, {y:.1f}, {z:.1f} | 维度: {dim_desc})",
            sender
        )
        return True

    # ==============================================================
    # $home 命令分派
    # ==============================================================

    async def _cmd_home(self, sender: str, method: str, name: str = None):
        # 兼容简写: 如果输入 $home [名字] 直接传送到指定家
        valid_methods = {"set", "tp", "list", "del", "delete", "remove", "help"}
        if method not in valid_methods:
            # 把 method 当作 home 名称进行传送
            name = method
            method = "tp"

        all_homes = _read_homes()
        user_homes = all_homes.setdefault(sender, {})

        # 1. 帮助说明
        if method == "help":
            help_text = (
                "§6===== 🏠 家 (Home) 传送点帮助 =====\n"
                f"§a{Command.command_prefix}home [名称] §7- 传送到指定家 (默认 main)\n"
                f"§a{Command.command_prefix}home set [名称] §7- 在当前位置设家\n"
                f"§a{Command.command_prefix}home list §7- 查看所有已设置的家\n"
                f"§a{Command.command_prefix}home del <名称> §7- 删除指定的家"
            )
            self.client.tell(help_text, sender)
            return {"status": True}

        # 2. 查看家列表
        if method == "list":
            if not user_homes:
                self.client.tell("§7你当前还没有设置任何家，可使用 §e$home set§7 创建一个。", sender)
                return {"status": True}
            lines = ["§6===== 🏠 我的家列表 ====="]
            for h_name, h_info in user_homes.items():
                x = h_info.get("x", 0.0)
                y = h_info.get("y", 0.0)
                z = h_info.get("z", 0.0)
                dim = self.DIMENSION_NAMES.get(h_info.get("dimension"), str(h_info.get("dimension", 0)))
                lines.append(f"§e• §a{h_name} §7- §fX={x:.1f}, Y={y:.1f}, Z={z:.1f} §8({dim})")
            self.client.tell("\n".join(lines), sender)
            return {"status": True}

        home_key = (name or "main").strip().lower()

        # 3. 设置家
        if method == "set":
            loc = await self.client.getLocation(sender) if hasattr(self.client, "getLocation") else None
            if not loc:
                err = "获取你的位置失败，请确认你在游戏中！"
                self.client.tell(f"§c{err}", sender)
                return {"status": False, "message": err, "quiet": True}

            user_homes[home_key] = {
                "name": home_key,
                "x": loc["x"],
                "y": loc["y"],
                "z": loc["z"],
                "dimension": loc.get("dimension", 0),
                "created_at": time.time(),
            }
            if _save_homes(all_homes):
                dim_desc = self.DIMENSION_NAMES.get(loc.get("dimension"), str(loc.get("dimension", 0)))
                self.client.tell(
                    f"§a✅ 已成功在当前位置设置家: §e[{home_key}] §7(维度: {dim_desc})",
                    sender
                )
                return {"status": True}
            else:
                self.client.tell("§c保存家数据失败，请查看后台日志！", sender)
                return {"status": False, "message": "保存家数据失败", "quiet": True}

        # 4. 删除家
        if method in ("del", "delete", "remove"):
            if home_key not in user_homes:
                err = f"未找到名为 [{home_key}] 的家！"
                self.client.tell(f"§c{err}", sender)
                return {"status": False, "message": err, "quiet": True}
            user_homes.pop(home_key, None)
            if _save_homes(all_homes):
                self.client.tell(f"§a🗑️ 已成功删除家: §e[{home_key}]", sender)
                return {"status": True}
            else:
                self.client.tell("§c删除家数据失败！", sender)
                return {"status": False, "message": "删除家数据失败", "quiet": True}

        # 5. 传送到家
        if method == "tp":
            if home_key not in user_homes:
                err = f"你尚未设置名为 [{home_key}] 的家！使用 §e$home set {home_key}§c 设置。"
                self.client.tell(f"§c{err}", sender)
                return {"status": False, "message": f"未设置名为 [{home_key}] 的家", "quiet": True}
            target_data = user_homes[home_key]
            await self._safe_teleport(sender, target_data, f"家:{home_key}")
            return {"status": True}

    # ==============================================================
    # $warp 命令分派
    # ==============================================================

    async def _cmd_warp(self, sender: str, method: str, name: str = None):
        valid_methods = {"set", "tp", "list", "del", "delete", "remove", "help"}
        if method not in valid_methods:
            name = method
            method = "tp"

        warps = _read_warps()

        # 1. 帮助说明
        if method == "help":
            help_text = (
                "§6===== 🌐 公共传送点 (Warp) 帮助 =====\n"
                f"§a{Command.command_prefix}warp [名称] §7- 传送到指定公共传送点\n"
                f"§a{Command.command_prefix}warp list §7- 查看所有全服公共传送点\n"
                f"§a{Command.command_prefix}warp set <名称> §7- 创建传送点 (需 OP/Owner)\n"
                f"§a{Command.command_prefix}warp del <名称> §7- 删除传送点 (需 OP/Owner)"
            )
            self.client.tell(help_text, sender)
            return {"status": True}

        # 2. 列出所有公共传送点
        if method == "list":
            if not warps:
                self.client.tell("§7当前暂无公共传送点。", sender)
                return {"status": True}
            lines = ["§6===== 🌐 全服公共传送点 ====="]
            for w_name, w_info in warps.items():
                x = w_info.get("x", 0.0)
                y = w_info.get("y", 0.0)
                z = w_info.get("z", 0.0)
                dim = self.DIMENSION_NAMES.get(w_info.get("dimension"), str(w_info.get("dimension", 0)))
                lines.append(f"§e• §b{w_name} §7- §fX={x:.1f}, Y={y:.1f}, Z={z:.1f} §8({dim})")
            self.client.tell("\n".join(lines), sender)
            return {"status": True}

        if not name:
            err = "请指定传送点名称！用法: $warp <名称> 或 $warp help"
            self.client.tell(f"§c{err}", sender)
            return {"status": False, "message": err, "quiet": True}

        warp_key = name.strip().lower()

        # 3. 设置公共传送点 (需 OP 或 Owner)
        if method == "set":
            perm = await PermissionManager.query(sender)
            if perm < 2:
                err = "权限受限：仅管理员 (OP/Owner) 可创建全服公共传送点！"
                self.client.tell(f"§c{err}", sender)
                return {"status": False, "message": err, "quiet": True}

            loc = await self.client.getLocation(sender) if hasattr(self.client, "getLocation") else None
            if not loc:
                err = "获取位置失败，请确认你在游戏中！"
                self.client.tell(f"§c{err}", sender)
                return {"status": False, "message": err, "quiet": True}

            warps[warp_key] = {
                "name": warp_key,
                "x": loc["x"],
                "y": loc["y"],
                "z": loc["z"],
                "dimension": loc.get("dimension", 0),
                "creator": sender,
                "created_at": time.time(),
            }
            if _save_warps(warps):
                dim_desc = self.DIMENSION_NAMES.get(loc.get("dimension"), str(loc.get("dimension", 0)))
                self.client.tell(
                    f"§a✅ 已成功创建全服公共传送点: §b[{warp_key}] §7(维度: {dim_desc})",
                    sender
                )
                return {"status": True}
            else:
                self.client.tell("§c保存传送点数据失败，请查看后台日志！", sender)
                return {"status": False, "message": "保存传送点数据失败", "quiet": True}

        # 4. 删除公共传送点 (需 OP 或 Owner)
        if method in ("del", "delete", "remove"):
            perm = await PermissionManager.query(sender)
            if perm < 2:
                err = "权限受限：仅管理员 (OP/Owner) 可删除公共传送点！"
                self.client.tell(f"§c{err}", sender)
                return {"status": False, "message": err, "quiet": True}

            if warp_key not in warps:
                err = f"未找到名为 [{warp_key}] 的公共传送点！"
                self.client.tell(f"§c{err}", sender)
                return {"status": False, "message": err, "quiet": True}

            warps.pop(warp_key, None)
            if _save_warps(warps):
                self.client.tell(f"§a🗑️ 已成功删除公共传送点: §b[{warp_key}]", sender)
                return {"status": True}
            else:
                self.client.tell("§c删除传送点数据失败！", sender)
                return {"status": False, "message": "删除传送点数据失败", "quiet": True}

        # 5. 传送到公共传送点
        if method == "tp":
            if warp_key not in warps:
                err = f"不存在名为 [{warp_key}] 的公共传送点！"
                self.client.tell(
                    f"§c{err}输入 §e$warp list§c 查看列表。",
                    sender
                )
                return {"status": False, "message": err, "quiet": True}
            target_data = warps[warp_key]
            await self._safe_teleport(sender, target_data, f"传送点:{warp_key}")
            return {"status": True}
