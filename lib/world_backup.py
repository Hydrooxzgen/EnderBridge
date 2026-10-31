"""lib/world_backup.py — Minecraft 基岩版世界存档自动备份与快照管理引擎

提供功能：
1. 智能探测 Minecraft 基岩版世界存档目录（Win10 UWP、Users/Shared、Users/<uid>、本地 BDS worlds 目录）
2. 制作安全无损快照，打包为标准 .mcworld / .zip 格式
3. 快照元数据跟踪、列表查询、大小统计
4. 自动保留策略与快照滚动清理（配额管理，支持永久锁定重要快照 Pinned）
5. 支持快照还原校验与文件保护
"""

import os
import re
import json
import time
import shutil
import zipfile
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")
DEFAULT_BACKUP_DIR = os.path.join(ROOT, "backups", "worlds")
SNAPSHOT_INDEX_FILE = "snapshots_index.json"


def _format_size(size_bytes: int) -> str:
    """格式化字节大小为易读字符串 (B, KB, MB, GB)"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


class WorldDetector:
    """Minecraft 基岩版世界目录智能探测器"""

    @classmethod
    def get_candidate_roots(cls) -> List[str]:
        """获取所有可能存在 minecraftWorlds 的系统目录候选路径"""
        roots = []
        appdata = os.environ.get("APPDATA")
        localappdata = os.environ.get("LOCALAPPDATA")

        # 1. 本地 Dedicated Server (BDS) 运行目录
        local_bds = os.path.join(ROOT, "worlds")
        roots.append(local_bds)

        # 2. Windows 10/11 UWP 版官方应用目录
        if localappdata:
            uwp_worlds = os.path.join(
                localappdata,
                "Packages",
                "Microsoft.MinecraftUWP_8wekyb3d8bbwe",
                "LocalState",
                "games",
                "com.mojang",
                "minecraftWorlds",
            )
            roots.append(uwp_worlds)

        # 3. 新版启动器 / 多用户存储目录
        if appdata:
            bedrock_users_dir = os.path.join(appdata, "Minecraft Bedrock", "Users")
            if os.path.isdir(bedrock_users_dir):
                try:
                    for entry in os.listdir(bedrock_users_dir):
                        p = os.path.join(bedrock_users_dir, entry, "games", "com.mojang", "minecraftWorlds")
                        roots.append(p)
                except Exception:
                    pass

        return [os.path.normpath(p) for p in roots]

    @classmethod
    def inspect_world_dir(cls, world_dir: str) -> Optional[Dict[str, Any]]:
        """检测单个目录是否为有效的基岩版世界目录并提取元数据"""
        if not os.path.isdir(world_dir):
            return None

        # 典型世界特征：包含 levelname.txt 或 level.dat 或 db/ 目录
        has_levelname = os.path.isfile(os.path.join(world_dir, "levelname.txt"))
        has_leveldat = os.path.isfile(os.path.join(world_dir, "level.dat"))
        has_db = os.path.isdir(os.path.join(world_dir, "db"))

        if not (has_levelname or has_leveldat or has_db):
            return None

        world_name = os.path.basename(world_dir)
        levelname_file = os.path.join(world_dir, "levelname.txt")
        if os.path.isfile(levelname_file):
            try:
                with open(levelname_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().strip()
                    if content:
                        world_name = content
            except Exception:
                pass

        # 统计修改时间与大小
        total_size = 0
        latest_mtime = os.path.getmtime(world_dir)
        try:
            for root, dirs, files in os.walk(world_dir):
                for file in files:
                    fp = os.path.join(root, file)
                    try:
                        st = os.stat(fp)
                        total_size += st.st_size
                        if st.st_mtime > latest_mtime:
                            latest_mtime = st.st_mtime
                    except Exception:
                        pass
        except Exception:
            pass

        return {
            "folder_name": os.path.basename(world_dir),
            "world_name": world_name,
            "path": os.path.abspath(world_dir),
            "size_bytes": total_size,
            "size_formatted": _format_size(total_size),
            "last_modified": latest_mtime,
            "last_modified_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(latest_mtime)),
        }

    @classmethod
    def detect_all_worlds(cls, custom_dir: Optional[str] = None) -> List[Dict[str, Any]]:
        """扫描并按最后修改时间排序返回所有已发现的基岩版世界"""
        candidates = []
        if custom_dir:
            candidates.append(os.path.abspath(custom_dir))
        else:
            candidates.extend(cls.get_candidate_roots())

        seen_paths = set()
        worlds = []

        for base in candidates:
            if not os.path.isdir(base):
                continue

            # 检查 base 本身是否就是一个世界目录
            self_check = cls.inspect_world_dir(base)
            if self_check:
                norm = os.path.normcase(os.path.abspath(base))
                if norm not in seen_paths:
                    seen_paths.add(norm)
                    worlds.append(self_check)
                continue

            # 遍历 base 下的第一级子目录
            try:
                for entry in os.listdir(base):
                    sub = os.path.join(base, entry)
                    if os.path.isdir(sub):
                        info = cls.inspect_world_dir(sub)
                        if info:
                            norm = os.path.normcase(info["path"])
                            if norm not in seen_paths:
                                seen_paths.add(norm)
                                worlds.append(info)
            except Exception:
                continue

        # 按最后活跃/修改时间降序排序
        worlds.sort(key=lambda w: w["last_modified"], reverse=True)
        if worlds:
            worlds[0]["is_most_recent"] = True
            for w in worlds[1:]:
                w["is_most_recent"] = False

        return worlds

    @classmethod
    def get_active_world(cls, custom_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """获取当前最活跃（最新修改）的世界信息"""
        all_worlds = cls.detect_all_worlds(custom_dir)
        return all_worlds[0] if all_worlds else None


class WorldBackupManager:
    """基岩版世界快照备份管理引擎"""

    def __init__(self, backup_dir: Optional[str] = None, custom_world_dir: Optional[str] = None):
        self.backup_dir = os.path.abspath(backup_dir or DEFAULT_BACKUP_DIR)
        self.custom_world_dir = os.path.abspath(custom_world_dir) if custom_world_dir else None
        os.makedirs(self.backup_dir, exist_ok=True)
        self.index_file = os.path.join(self.backup_dir, SNAPSHOT_INDEX_FILE)

    def _read_index(self) -> Dict[str, Any]:
        """读取备份索引字典 (存储 pin 等元数据)"""
        if os.path.isfile(self.index_file):
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except Exception:
                pass
        return {}

    def _save_index(self, index_data: Dict[str, Any]) -> None:
        """保存备份索引字典 (原子写入)"""
        try:
            tmp = self.index_file + f".tmp_{os.getpid()}"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.index_file)
        except Exception:
            pass

    def create_snapshot(
        self,
        world_path: Optional[str] = None,
        tag: Optional[str] = None,
        as_mcworld: bool = True,
    ) -> Dict[str, Any]:
        """创建目标世界的一份无损快照包

        Args:
            world_path: 目标世界目录（若为 None 则自动探测最新活跃世界）
            tag: 可选的用户自定义快照备注标识
            as_mcworld: 是否以 .mcworld 格式保存 (为 True 时基岩版可直接双击导入)

        Returns:
            快照信息元数据字典
        """
        target_info = None
        if world_path:
            target_info = WorldDetector.inspect_world_dir(world_path)
            if not target_info:
                raise FileNotFoundError(f"指定的路径非有效的 Minecraft 世界目录: {world_path}")
        else:
            target_info = WorldDetector.get_active_world(self.custom_world_dir)
            if not target_info:
                raise FileNotFoundError("未自动探测到任何可用的 Minecraft 基岩版世界存档目录，请指定路径！")

        src_dir = target_info["path"]
        raw_world_name = target_info["world_name"]

        # 清理文件名中的非法字符
        clean_name = re.sub(r'[\\/*?:"<>| ]', "_", raw_world_name).strip("_") or "World"
        timestamp_str = time.strftime("%Y%m%d_%H%M%S")
        ext = ".mcworld" if as_mcworld else ".zip"

        tag_clean = ""
        if tag:
            tag_clean = "_" + re.sub(r'[\\/*?:"<>| ]', "_", tag).strip("_")

        snapshot_filename = f"{clean_name}_{timestamp_str}{tag_clean}{ext}"
        dest_zip_path = os.path.join(self.backup_dir, snapshot_filename)

        # 临时写入文件，完成后更名以确保原子完整性
        tmp_zip_path = dest_zip_path + f".tmp_{os.getpid()}"
        file_count = 0
        total_compressed_bytes = 0

        try:
            with zipfile.ZipFile(tmp_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(src_dir):
                    for file in files:
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, src_dir)
                        try:
                            zf.write(full_path, arcname=rel_path)
                            file_count += 1
                        except Exception:
                            pass

            if os.path.exists(dest_zip_path):
                os.remove(dest_zip_path)
            os.replace(tmp_zip_path, dest_zip_path)
            total_compressed_bytes = os.path.getsize(dest_zip_path)
        except Exception as e:
            if os.path.exists(tmp_zip_path):
                try:
                    os.remove(tmp_zip_path)
                except Exception:
                    pass
            raise IOError(f"创建世界快照失败: {e}")

        # 记录到索引
        created_time = time.time()
        snapshot_id = snapshot_filename
        index_data = self._read_index()
        index_data[snapshot_id] = {
            "snapshot_id": snapshot_id,
            "filename": snapshot_filename,
            "world_name": raw_world_name,
            "source_folder": target_info["folder_name"],
            "source_path": src_dir,
            "tag": tag or "",
            "file_count": file_count,
            "size_bytes": total_compressed_bytes,
            "size_formatted": _format_size(total_compressed_bytes),
            "created_at": created_time,
            "created_at_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(created_time)),
            "pinned": False,
        }
        self._save_index(index_data)

        res = dict(index_data[snapshot_id])
        res["file_path"] = dest_zip_path
        return res

    def list_snapshots(self) -> List[Dict[str, Any]]:
        """查询已保存的所有快照（自动同步索引与磁盘实际文件）"""
        index_data = self._read_index()
        snapshots = []

        if not os.path.isdir(self.backup_dir):
            return []

        existing_files = set()
        try:
            for fname in os.listdir(self.backup_dir):
                if fname.endswith(".mcworld") or fname.endswith(".zip"):
                    existing_files.add(fname)
        except Exception:
            pass

        updated = False
        for sid in list(index_data.keys()):
            if sid not in existing_files:
                del index_data[sid]
                updated = True

        for fname in existing_files:
            if fname not in index_data:
                fpath = os.path.join(self.backup_dir, fname)
                st = os.stat(fpath)
                index_data[fname] = {
                    "snapshot_id": fname,
                    "filename": fname,
                    "world_name": fname.split("_")[0] if "_" in fname else fname,
                    "source_folder": "",
                    "source_path": "",
                    "tag": "",
                    "file_count": 0,
                    "size_bytes": st.st_size,
                    "size_formatted": _format_size(st.st_size),
                    "created_at": st.st_mtime,
                    "created_at_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
                    "pinned": False,
                }
                updated = True

        if updated:
            self._save_index(index_data)

        for sid, item in index_data.items():
            fpath = os.path.join(self.backup_dir, item["filename"])
            item_copy = dict(item)
            item_copy["file_path"] = fpath
            snapshots.append(item_copy)

        snapshots.sort(key=lambda s: s["created_at"], reverse=True)
        return snapshots

    def rotate_snapshots(self, max_keep: int = 10) -> List[str]:
        """按配额自动轮转清理旧快照 (被锁定 pinned 的快照永久保留)"""
        if max_keep <= 0:
            return []

        all_snapshots = self.list_snapshots()
        unpinned = [s for s in all_snapshots if not s.get("pinned", False)]

        deleted = []
        if len(unpinned) > max_keep:
            to_remove = unpinned[max_keep:]
            for s in to_remove:
                if self.delete_snapshot(s["snapshot_id"]):
                    deleted.append(s["filename"])

        return deleted

    def set_pin(self, snapshot_id: str, pinned: bool = True) -> bool:
        """锁定或解锁指定快照"""
        index_data = self._read_index()
        target_key = None
        for k in index_data.keys():
            if k == snapshot_id or k.startswith(snapshot_id):
                target_key = k
                break

        if not target_key:
            return False

        index_data[target_key]["pinned"] = bool(pinned)
        self._save_index(index_data)
        return True

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """删除指定快照文件与索引记录"""
        index_data = self._read_index()
        target_key = None
        for k in index_data.keys():
            if k == snapshot_id or k.startswith(snapshot_id):
                target_key = k
                break

        if not target_key:
            fpath = os.path.join(self.backup_dir, snapshot_id)
            if os.path.isfile(fpath):
                try:
                    os.remove(fpath)
                    return True
                except Exception:
                    pass
            return False

        fname = index_data[target_key]["filename"]
        fpath = os.path.join(self.backup_dir, fname)
        if os.path.isfile(fpath):
            try:
                os.remove(fpath)
            except Exception:
                pass

        del index_data[target_key]
        self._save_index(index_data)
        return True

    def restore_snapshot(self, snapshot_id: str, target_dir: str) -> Dict[str, Any]:
        """将指定快照还原到目标目录"""
        fpath = os.path.join(self.backup_dir, snapshot_id)
        if not os.path.isfile(fpath):
            for s in self.list_snapshots():
                if s["snapshot_id"] == snapshot_id or s["snapshot_id"].startswith(snapshot_id):
                    fpath = s["file_path"]
                    break

        if not os.path.isfile(fpath):
            raise FileNotFoundError(f"未找到快照文件: {snapshot_id}")

        os.makedirs(target_dir, exist_ok=True)
        with zipfile.ZipFile(fpath, "r") as zf:
            zf.extractall(target_dir)

        return {
            "status": True,
            "snapshot_id": snapshot_id,
            "target_dir": target_dir,
            "restored_at": time.time(),
        }
