"""世界存档自动定时备份与快照管理 Mod (World Backup & Snapshot System)

提供功能：
- $backup create [备注]: 刷新游戏缓存并创建当前世界无损快照 (.mcworld)
- $backup list: 列出已保存的快照历史
- $backup worlds: 探测并列出系统内所有基岩版世界
- $backup pin <序号/名称>: 锁定快照以防被自动轮转清理
- $backup unpin <序号/名称>: 解除快照锁定
- $backup delete <序号/名称>: 删除指定快照
- 自动后台定时静默备份 (基于 config.json 中的 features.world_backup 配置)
"""

import asyncio
import os
import time

from lib import shared
from lib.command import Command, apply_config_aliases
from lib.permission import PermissionManager
from lib.world_backup import WorldBackupManager, WorldDetector


def _load_backup_feature_config() -> dict:
    """读取备份功能配置"""
    try:
        from lib.config_loader import get_config
        cfg = get_config()
        features = cfg.get("features", {})
        return features.get("world_backup", {})
    except Exception:
        return {}


class Mod:
    """World Backup 系统客户端 Mod"""

    terminal_compatible = True  # 控制台/终端同样可用

    def __init__(self, client):
        self.client = client
        self.manager = WorldBackupManager()
        self._auto_task = None

    def onStart(self):
        """Mod 启动时启动后台自动定时备份任务 (若开启)"""
        cfg = _load_backup_feature_config()
        if cfg.get("enabled", False):
            custom_dir = cfg.get("custom_world_dir")
            if custom_dir:
                self.manager.custom_world_dir = custom_dir
            interval_mins = max(5, int(cfg.get("interval_minutes", 60)))
            self._auto_task = asyncio.create_task(self._auto_backup_loop(interval_mins))
            shared.logger.info(f"[WorldBackup] 后台自动世界存档备份已启动，每 {interval_mins} 分钟创建一次快照")

    async def _auto_backup_loop(self, interval_mins: int):
        """后台静默定时备份循环"""
        while True:
            try:
                await asyncio.sleep(interval_mins * 60)
                cfg = _load_backup_feature_config()
                if not cfg.get("enabled", True):
                    break

                # 检查是否有客户端连接或允许无客户端时备份
                if self.client and hasattr(self.client, "is_open") and self.client.is_open:
                    try:
                        await self.client.runCommand("save-all")
                        await asyncio.sleep(1.0)
                    except Exception:
                        pass

                # 执行快照
                max_keep = int(cfg.get("max_snapshots", 10))
                tag = "auto"
                snap = self.manager.create_snapshot(tag=tag)
                cleaned = self.manager.rotate_snapshots(max_keep=max_keep)

                shared.logger.info(
                    f"[WorldBackup] 自动定时快照已完成: {snap['filename']} ({snap['size_formatted']})"
                    + (f"，已轮转清理旧快照: {', '.join(cleaned)}" if cleaned else "")
                )

                if cfg.get("notify_in_game", False) and self.client:
                    self.client.tell(
                        f"§a📦 [系统提示] 世界存档定时快照已完成: §e{snap['world_name']} §7({snap['size_formatted']})",
                        "@a",
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                shared.logger.error(f"[WorldBackup] 自动定时备份执行异常: {e}")

    def onCommand(self):
        return {
            "normal": [
                apply_config_aliases(
                    Command.create("backup", "世界存档备份与快照管理（方法: create/list/worlds/pin/unpin/delete/help）")
                    .add_string("操作", False)
                    .add_optional_string("参数")
                    .set_func(self._cmd_backup)
                    .add_alias("bak")
                    .add_alias("snapshot")
                )
            ]
        }

    async def _cmd_backup(self, sender: str, action: str, param: str = None):
        action = (action or "").strip().lower()

        # 1. 帮助说明
        if action in ("help", "?"):
            prefix = Command.command_prefix
            msg = (
                f"§b==== §l世界存档备份与快照帮助 §r§b====\n"
                f"§e{prefix}backup create [备注] §7- 创建当前世界无损快照 (.mcworld)\n"
                f"§e{prefix}backup list §7- 查看所有快照历史列表\n"
                f"§e{prefix}backup worlds §7- 列出探测到的所有基岩版世界\n"
                f"§e{prefix}backup pin <序号> §7- 锁定快照（防止被自动轮转清理）\n"
                f"§e{prefix}backup unpin <序号> §7- 解除快照锁定\n"
                f"§e{prefix}backup delete <序号> §7- 删除指定快照\n"
                f"§7(别名支持: {prefix}bak, {prefix}snapshot)"
            )
            self.client.tell(msg, sender)
            return {"status": True}

        # 2. 查询快照列表 (全体玩家可看)
        if action in ("list", "ls"):
            snapshots = self.manager.list_snapshots()
            if not snapshots:
                self.client.tell("§e当前暂无已保存的世界快照。输入 §b$backup create §e创建第一个快照！", sender)
                return {"status": True}

            lines = [f"§b==== §l世界快照列表 (共 {len(snapshots)} 个) §r§b===="]
            for i, s in enumerate(snapshots, 1):
                pin_mark = "§c📌 " if s.get("pinned") else ""
                tag_mark = f" §6[{s['tag']}]" if s.get("tag") else ""
                lines.append(
                    f"§e{i}. {pin_mark}§f{s['world_name']}{tag_mark} §7({s['size_formatted']} | {s['created_at_str']})"
                )
            lines.append("§7提示: 带 📌 的快照已被锁定，不会被自动清理")
            self.client.tell("\n".join(lines), sender)
            return {"status": True}

        # 3. 列出探测到的世界 (全体玩家可看)
        if action in ("worlds", "world"):
            worlds = WorldDetector.detect_all_worlds(self.manager.custom_world_dir)
            if not worlds:
                self.client.tell("§c未自动探测到任何基岩版世界存档目录！", sender)
                return {"status": False, "message": "未探测到世界目录", "quiet": True}

            lines = [f"§b==== §l已探测到的世界存档 (共 {len(worlds)} 个) §r§b===="]
            for i, w in enumerate(worlds, 1):
                active_mark = " §a[当前活跃/最新]" if w.get("is_most_recent") else ""
                lines.append(
                    f"§e{i}. §f{w['world_name']}{active_mark} §7({w['size_formatted']} | {w['last_modified_str']})\n"
                    f"   §8目录: {w['path']}"
                )
            self.client.tell("\n".join(lines), sender)
            return {"status": True}

        # ---- 管理员权限检查 (create, delete, pin, unpin 需管理员 OP) ----
        perm = await PermissionManager.query(sender)
        if perm < 2:
            err = "权限受限：仅管理员 (OP/Owner) 可执行快照创建与管理操作！"
            self.client.tell(f"§c{err}", sender)
            return {"status": False, "message": err, "quiet": True}

        # 4. 创建快照
        if action in ("create", "make", "save", "new"):
            tag = param.strip() if param else None
            self.client.tell("§b正在请求游戏刷新世界数据并创建快照包，请稍候...", sender)

            # 刷新世界写入
            try:
                if hasattr(self.client, "runCommand"):
                    await self.client.runCommand("save-all")
                    await asyncio.sleep(0.5)
            except Exception:
                pass

            try:
                # 在协程线程池中运行避免阻塞
                loop = asyncio.get_running_loop()
                snap = await loop.run_in_executor(None, lambda: self.manager.create_snapshot(tag=tag))

                # 自动轮转旧快照
                cfg = _load_backup_feature_config()
                max_keep = int(cfg.get("max_snapshots", 10))
                cleaned = await loop.run_in_executor(None, lambda: self.manager.rotate_snapshots(max_keep=max_keep))

                # 播报成功与音效
                try:
                    await self.client.runCommand(f'playsound random.levelup "{sender}" ~ ~ ~ 1 1')
                except Exception:
                    pass

                clean_msg = f"\n§7(已按配额自动轮转清理 {len(cleaned)} 个旧快照)" if cleaned else ""
                self.client.tell(
                    f"§a✨ 世界快照已成功创建！\n"
                    f"§f• 世界名称: §e{snap['world_name']}\n"
                    f"§f• 快照文件: §b{snap['filename']}\n"
                    f"§f• 压缩大小: §e{snap['size_formatted']} §7(包含 {snap['file_count']} 个文件){clean_msg}",
                    sender,
                )
                shared.logger.info(f"[WorldBackup] 玩家 {sender} 创建了世界快照: {snap['filename']}")
                return {"status": True}
            except Exception as e:
                err_msg = f"创建快照失败: {e}"
                self.client.tell(f"§c❌ {err_msg}", sender)
                shared.logger.error(f"[WorldBackup] {err_msg}")
                return {"status": False, "message": err_msg, "quiet": True}

        # 5. 锁定/解锁快照 (pin / unpin)
        if action in ("pin", "lock", "unpin", "unlock"):
            if not param:
                self.client.tell("§c用法: $backup pin/unpin <快照序号或文件名>", sender)
                return {"status": False, "message": "缺少参数", "quiet": True}

            snapshots = self.manager.list_snapshots()
            target_id = param.strip()

            # 支持通过序号选择 (例如 $backup pin 1)
            if target_id.isdigit():
                idx = int(target_id)
                if 1 <= idx <= len(snapshots):
                    target_id = snapshots[idx - 1]["snapshot_id"]
                else:
                    self.client.tell(f"§c无效的快照序号: {idx} (有效范围: 1 ~ {len(snapshots)})", sender)
                    return {"status": False, "message": "无效序号", "quiet": True}

            is_pin = action in ("pin", "lock")
            success = self.manager.set_pin(target_id, pinned=is_pin)
            if success:
                act_desc = "已锁定 (免于自动轮转清理)" if is_pin else "已解除锁定"
                self.client.tell(f"§a✅ 快照 §e[{target_id}] §a{act_desc}！", sender)
                return {"status": True}
            else:
                self.client.tell(f"§c未找到指定的快照: {target_id}", sender)
                return {"status": False, "message": "未找到快照", "quiet": True}

        # 6. 删除快照
        if action in ("delete", "del", "remove", "rm"):
            if not param:
                self.client.tell("§c用法: $backup delete <快照序号或文件名>", sender)
                return {"status": False, "message": "缺少参数", "quiet": True}

            snapshots = self.manager.list_snapshots()
            target_id = param.strip()

            if target_id.isdigit():
                idx = int(target_id)
                if 1 <= idx <= len(snapshots):
                    target_id = snapshots[idx - 1]["snapshot_id"]
                else:
                    self.client.tell(f"§c无效的快照序号: {idx} (有效范围: 1 ~ {len(snapshots)})", sender)
                    return {"status": False, "message": "无效序号", "quiet": True}

            # 检查是否处于锁定保护状态
            for s in snapshots:
                if (s["snapshot_id"] == target_id or s["filename"] == target_id) and s.get("pinned"):
                    self.client.tell(f"§c快照 §e[{target_id}] §c当前处于锁定保护状态！请先执行 §b$backup unpin {target_id} §c解锁后再删除。", sender)
                    return {"status": False, "message": "快照处于锁定状态", "quiet": True}

            success = self.manager.delete_snapshot(target_id)
            if success:
                self.client.tell(f"§a🗑️ 已成功删除快照: §e{target_id}", sender)
                shared.logger.info(f"[WorldBackup] 玩家 {sender} 删除了世界快照: {target_id}")
                return {"status": True}
            else:
                self.client.tell(f"§c删除失败，未找到快照: {target_id}", sender)
                return {"status": False, "message": "删除失败", "quiet": True}

        self.client.tell(f"§c未知的备份子命令: {action}。输入 §b$backup help §c查看帮助。", sender)
        return {"status": False, "message": f"未知命令: {action}", "quiet": True}

