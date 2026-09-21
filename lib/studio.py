"""Studio 创意工坊核心服务模块

负责 MIDI 音乐、MCFunc 脚本、Ezmatic 蓝图模型、Image 像素画资产的
发现、元数据解析、安全文件存取、调色板服务及游戏内动作调度。
"""
import os
import re
import time
import json
import datetime
from pathlib import Path

# 项目根目录
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 支持的资产分类与扩展名
CATEGORIES = {
    "midi": {
        "config_key": "music",
        "default_dir": "resources/midi",
        "extensions": {".mid", ".midi"},
        "mime": "audio/midi",
    },
    "mcfunc": {
        "config_key": "mcfunc",
        "default_dir": "resources/mcfunc",
        "extensions": {".mcfunc", ".mcfunction"},
        "mime": "text/plain",
    },
    "ezmatic": {
        "config_key": "ezmatic",
        "default_dir": "resources/ezmatic",
        "extensions": {".litematic", ".schematic", ".mcstructure"},
        "mime": "application/octet-stream",
    },
    "image": {
        "config_key": "image",
        "default_dir": "resources/pictures",
        "extensions": {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"},
        "mime": "image/png",
    },
}

_PALETTE_CACHE = None


def sanitize_filename(name: str) -> str:
    """严格校验并清理文件名,防止路径穿越与非法注入"""
    if not isinstance(name, str):
        raise ValueError("文件名必须为字符串")
    s = name.strip()
    if not s:
        raise ValueError("文件名不能为空")
    if len(s) > 120:
        raise ValueError("文件名长度超出限制 (最大 120 字符)")
    if os.path.basename(s) != s:
        raise ValueError("文件名不得包含路径成分")
    if re.search(r"[\\/\0]", s):
        raise ValueError("文件名包含非法字符")
    if s.startswith(".") or s.startswith("~"):
        raise ValueError("文件名不得以 . 或 ~ 开头")
    return s


def get_base_path(category: str) -> str:
    """获取指定资产分类在当前配置下的物理存储目录"""
    cat = category.lower().strip()
    if cat not in CATEGORIES:
        raise ValueError(f"未知的资产分类: {category} (可选: {list(CATEGORIES.keys())})")

    info = CATEGORIES[cat]
    config_key = info["config_key"]
    default_dir = info["default_dir"]

    # 尝试从 config 中读取 basePath
    base_path_cfg = {}
    try:
        from lib.config_loader import get_config
        base_path_cfg = get_config().get("basePath") or {}
    except Exception:
        pass

    target_rel = base_path_cfg.get(config_key) or default_dir
    abs_dir = os.path.normpath(os.path.join(ROOT, target_rel))
    os.makedirs(abs_dir, exist_ok=True)
    return abs_dir


def extract_midi_metadata(file_path: str) -> dict:
    """提取 MIDI 音乐文件的时长、音轨数、PPQ 等元数据"""
    res = {
        "length_seconds": 0.0,
        "tracks": 1,
        "ticks_per_beat": 480,
        "notes_count": 0,
    }
    try:
        import mido
        mid = mido.MidiFile(file_path)
        res["tracks"] = len(mid.tracks)
        res["ticks_per_beat"] = mid.ticks_per_beat or 480
        # mido 自带 length 属性计算总秒数
        try:
            res["length_seconds"] = round(float(mid.length), 2)
        except Exception:
            res["length_seconds"] = 0.0

        # 统计音符总数
        note_count = 0
        for track in mid.tracks:
            for msg in track:
                if msg.type == "note_on" and getattr(msg, "velocity", 0) > 0:
                    note_count += 1
        res["notes_count"] = note_count
    except Exception as e:
        res["error"] = str(e)
    return res


def extract_mcfunc_metadata(file_path: str) -> dict:
    """提取 MCFunc 脚本的行数与指令概览"""
    res = {
        "total_lines": 0,
        "command_lines": 0,
        "comment_lines": 0,
    }
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        res["total_lines"] = len(lines)
        for line in lines:
            s = line.strip()
            if not s:
                continue
            if s.startswith("#"):
                res["comment_lines"] += 1
            else:
                res["command_lines"] += 1
    except Exception as e:
        res["error"] = str(e)
    return res


def extract_ezmatic_metadata(file_path: str) -> dict:
    """提取 Ezmatic Litematic / MCStructure 的三维体积与作者信息"""
    ext = Path(file_path).suffix.lower()
    res = {
        "format": ext.lstrip("."),
        "dimensions": {"x": 0, "y": 0, "z": 0},
        "volume": 0,
        "author": "Unknown",
        "name": Path(file_path).stem,
        "block_types": 0,
    }
    if ext == ".litematic":
        try:
            from mod.ezmatic.main import decompress_and_parse
            with open(file_path, "rb") as f:
                buf = f.read()
            nbt = decompress_and_parse(buf)
            meta = nbt.get("Metadata") or {}
            res["author"] = meta.get("Author") or "Unknown"
            res["name"] = meta.get("Name") or Path(file_path).stem
            res["volume"] = meta.get("TotalVolume") or 0
            enc = meta.get("EnclosingSize") or {}
            if enc and "x" in enc and "y" in enc and "z" in enc:
                res["dimensions"] = {
                    "x": abs(enc["x"]),
                    "y": abs(enc["y"]),
                    "z": abs(enc["z"]),
                }
            # 统计区域信息
            regions = nbt.get("Regions") or {}
            all_palettes = set()
            for r in regions.values():
                if not res["dimensions"]["x"] and "Size" in r:
                    res["dimensions"] = {
                        "x": abs(r["Size"]["x"]),
                        "y": abs(r["Size"]["y"]),
                        "z": abs(r["Size"]["z"]),
                    }
                pal = r.get("BlockStatePalette") or []
                for entry in pal:
                    if isinstance(entry, dict) and "Name" in entry:
                        all_palettes.add(entry["Name"])
            res["block_types"] = len(all_palettes)
            if not res["volume"] and res["dimensions"]["x"]:
                res["volume"] = res["dimensions"]["x"] * res["dimensions"]["y"] * res["dimensions"]["z"]
        except Exception as e:
            res["error"] = str(e)
    return res


def extract_image_metadata(file_path: str) -> dict:
    """提取图片分辨率与色彩信息"""
    res = {
        "width": 0,
        "height": 0,
        "format": "",
        "mode": "",
    }
    try:
        from PIL import Image
        with Image.open(file_path) as img:
            res["width"], res["height"] = img.size
            res["format"] = img.format or ""
            res["mode"] = img.mode or ""
    except Exception as e:
        res["error"] = str(e)
    return res


def list_assets(category: str) -> list[dict]:
    """统一列出指定分类的所有资产文件及其元数据"""
    cat = category.lower().strip()
    if cat not in CATEGORIES:
        raise ValueError(f"未知的资产分类: {category}")

    folder = get_base_path(cat)
    allowed_exts = CATEGORIES[cat]["extensions"]

    assets = []
    if not os.path.exists(folder):
        return assets

    for entry in os.scandir(folder):
        if not entry.is_file():
            continue
        ext = Path(entry.name).suffix.lower()
        if ext not in allowed_exts:
            continue

        try:
            stat = entry.stat()
            mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            asset_info = {
                "name": entry.name,
                "category": cat,
                "extension": ext,
                "size": stat.st_size,
                "size_formatted": _format_size(stat.st_size),
                "mtime": mtime,
                "mtime_ts": stat.st_mtime,
            }

            # 提取元数据
            fp = entry.path
            if cat == "midi":
                asset_info["metadata"] = extract_midi_metadata(fp)
            elif cat == "mcfunc":
                asset_info["metadata"] = extract_mcfunc_metadata(fp)
            elif cat == "ezmatic":
                asset_info["metadata"] = extract_ezmatic_metadata(fp)
            elif cat == "image":
                asset_info["metadata"] = extract_image_metadata(fp)

            assets.append(asset_info)
        except Exception:
            continue

    # 按修改时间最新排序
    assets.sort(key=lambda x: x.get("mtime_ts", 0), reverse=True)
    return assets


def get_asset_file_path(category: str, filename: str) -> str:
    """安全解析资产文件完整物理路径"""
    safe_name = sanitize_filename(filename)
    folder = get_base_path(category)
    full_path = os.path.normpath(os.path.join(folder, safe_name))
    # 确保没有跳出该分类目录
    if not full_path.startswith(folder):
        raise ValueError("非法的文件访问越界")
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        raise FileNotFoundError(f"文件不存在: {filename}")
    return full_path


def save_asset_file(category: str, filename: str, data: bytes) -> dict:
    """安全保存上传的二进制或文本资产文件"""
    safe_name = sanitize_filename(filename)
    cat = category.lower().strip()
    if cat not in CATEGORIES:
        raise ValueError(f"未知的资产分类: {category}")

    ext = Path(safe_name).suffix.lower()
    allowed_exts = CATEGORIES[cat]["extensions"]
    if ext not in allowed_exts:
        raise ValueError(f"不受支持的文件扩展名: {ext} (允许: {', '.join(allowed_exts)})")

    folder = get_base_path(cat)
    target_path = os.path.join(folder, safe_name)

    # 若已存在同名文件，备份为 .bak
    if os.path.exists(target_path):
        try:
            import shutil
            shutil.copy2(target_path, target_path + ".bak")
        except Exception:
            pass

    with open(target_path, "wb") as f:
        f.write(data)

    return {
        "ok": True,
        "name": safe_name,
        "category": cat,
        "size": len(data),
        "path": target_path,
    }


def delete_asset_file(category: str, filename: str) -> dict:
    """安全删除资产文件(保留 .bak 备份)"""
    safe_name = sanitize_filename(filename)
    full_path = get_asset_file_path(category, safe_name)

    # 移动为备份文件
    bak_path = full_path + ".bak"
    try:
        import shutil
        shutil.copy2(full_path, bak_path)
    except Exception:
        pass

    os.remove(full_path)
    return {"ok": True, "name": safe_name, "message": f"已安全删除 {safe_name}"}


def get_block_palette() -> list[dict]:
    """获取 mod/image/blocks.json 方块调色板数据(带内存缓存)"""
    global _PALETTE_CACHE
    if _PALETTE_CACHE is not None:
        return _PALETTE_CACHE

    palette_file = os.path.join(ROOT, "mod", "image", "blocks.json")
    if not os.path.exists(palette_file):
        return []

    try:
        with open(palette_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        blocks = data.get("blocks") or []
        _PALETTE_CACHE = blocks
        return blocks
    except Exception:
        return []


def execute_studio_action(action: str, category: str, filename: str, params: dict = None) -> dict:
    """调度游戏内动作 (播放音乐、执行投影、绘制像素画、运行函数)"""
    params = params or {}
    safe_name = sanitize_filename(filename) if filename else ""

    from lib.current import Current
    client = Current.client
    if not client:
        return {"ok": False, "message": "当前无活跃 Minecraft 客户端连接，无法在游戏内执行动作"}

    import asyncio
    from lib.command import Command
    Command.reload_prefix()
    cp = Command.command_prefix

    try:
        if action == "play_midi":
            # $music run <filename>
            cmd = f"{cp}music run {safe_name}"
            # 伴奏打击乐参数
            if params.get("percussion") is not None:
                perc_cmd = f"{cp}music percussion {'on' if params.get('percussion') else 'off'}"
                asyncio.run(client.runCommand(perc_cmd))
            res = asyncio.run(client.runCommand(cmd))
            return {"ok": True, "message": f"已在游戏内点播: {safe_name}", "raw": res}

        elif action == "stop_midi":
            cmd = f"{cp}music stop"
            res = asyncio.run(client.runCommand(cmd))
            return {"ok": True, "message": "已停止音乐播放", "raw": res}

        elif action == "run_mcfunc":
            # $function function <filename> 或 loop
            loop_name = params.get("loopName")
            interval = params.get("interval")
            if loop_name and interval:
                cmd = f"{cp}function loop {safe_name} {loop_name} {interval}"
            else:
                cmd = f"{cp}function function {safe_name}"
            res = asyncio.run(client.runCommand(cmd))
            return {"ok": True, "message": f"已执行函数脚本: {safe_name}", "raw": res}

        elif action == "stop_mcfunc":
            loop_name = params.get("loopName", "")
            cmd = f"{cp}function stop {loop_name}".strip()
            res = asyncio.run(client.runCommand(cmd))
            return {"ok": True, "message": "已停止函数循环", "raw": res}

        elif action == "preview_ezmatic":
            # $ezmatic preview <filename>
            cmd = f"{cp}ezmatic preview {safe_name}"
            res = asyncio.run(client.runCommand(cmd))
            return {"ok": True, "message": f"已在游戏内启动蓝图投影: {safe_name}", "raw": res}

        elif action == "build_ezmatic":
            # $ezmatic create <filename>
            cmd = f"{cp}ezmatic create {safe_name}"
            res = asyncio.run(client.runCommand(cmd))
            return {"ok": True, "message": f"已在游戏内触发蓝图建造: {safe_name}", "raw": res}

        elif action == "draw_image":
            # $image create <filename> [axis] [x] [y] [z]
            axis = params.get("axis", "x").lower()
            x = params.get("x", "~")
            y = params.get("y", "~")
            z = params.get("z", "~")
            cmd = f"{cp}image create {safe_name} {axis} {x} {y} {z}"
            res = asyncio.run(client.runCommand(cmd))
            return {"ok": True, "message": f"已下发像素画绘制任务: {safe_name}", "raw": res}

        elif action == "confirm_image":
            cmd = f"{cp}image y"
            res = asyncio.run(client.runCommand(cmd))
            return {"ok": True, "message": "已确认像素画绘制", "raw": res}

        else:
            return {"ok": False, "message": f"未知的 Studio 动作指令: {action}"}

    except Exception as e:
        return {"ok": False, "message": f"执行动作失败: {e}"}


def _format_size(size_bytes: int) -> str:
    """人性化文件大小格式化"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"

