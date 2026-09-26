"""Studio 创意工坊核心服务模块

负责 MIDI 音乐、MCFunc 脚本、Ezmatic 蓝图模型、Image 像素画资产的
发现、元数据解析、安全文件存取、调色板服务及游戏内动作调度。
"""
import os
import re
import time
import json
import datetime
import asyncio
from pathlib import Path

# 项目根目录
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCK_TEXTURES_DIR = os.path.join(ROOT, "webui", "static", "textures", "blocks")

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


async def _async_execute_studio_action(action: str, category: str, filename: str, params: dict = None) -> dict:
    """在主事件循环中调度 Studio 动作，直接与 ClientModManager 及对应 Mod 实例交互"""
    params = params or {}
    safe_name = sanitize_filename(filename) if filename else ""

    from lib.current import Current
    client = Current.client
    if not client:
        return {"ok": False, "message": "当前无活跃 Minecraft 客户端连接。请先在游戏内执行 /connect 连接。"}

    manager = Current.client_mods.get(client)
    if not manager:
        return {"ok": False, "message": "当前客户端的 Mod 模块尚未加载"}

    try:
        if action == "play_midi":
            mod = manager.mod_instances.get("Music")
            if not mod:
                return {"ok": False, "message": "Music 模块未加载"}
            if params.get("percussion") is not None:
                mod.playPercussion = bool(params.get("percussion"))
            await mod._cmd_music("Studio", "run", safe_name)
            return {"ok": True, "message": f"已在游戏内点播: {safe_name}"}

        elif action == "stop_midi":
            mod = manager.mod_instances.get("Music")
            if mod:
                await mod._cmd_music("Studio", "stop")
            return {"ok": True, "message": "已停止音乐播放"}

        elif action == "run_mcfunc":
            mod = manager.mod_instances.get("MCFunc")
            if not mod:
                return {"ok": False, "message": "MCFunc 模块未加载"}
            loop_name = params.get("loopName")
            interval = params.get("interval")
            if loop_name and interval:
                await mod._cmd_function("Studio", "loop", safe_name, loop_name, str(interval))
            else:
                await mod._cmd_function("Studio", "function", safe_name)
            return {"ok": True, "message": f"已执行函数脚本: {safe_name}"}

        elif action == "stop_mcfunc":
            mod = manager.mod_instances.get("MCFunc")
            if mod:
                loop_name = params.get("loopName", "")
                await mod._cmd_function("Studio", "stop", loop_name)
            return {"ok": True, "message": "已停止函数循环"}

        elif action in ("preview_ezmatic", "toggle_preview_ezmatic"):
            mod = manager.mod_instances.get("Ezmatic")
            if not mod:
                return {"ok": False, "message": "Ezmatic 模块未加载"}

            # 若为 toggle 操作且当前正在预览该文件，则关闭全息
            if action == "toggle_preview_ezmatic" and getattr(mod, "preview_data", None):
                curr_file = mod.preview_data.get("file", "")
                if not safe_name or curr_file == safe_name or curr_file == safe_name.replace(".litematic", "") or curr_file.replace(".litematic", "") == safe_name.replace(".litematic", ""):
                    await mod.clear_preview("Studio")
                    return {"ok": True, "active": False, "message": "已关闭游戏内全息投影"}

            x = params.get("x")
            y = params.get("y")
            z = params.get("z")
            mode = params.get("mode") or "trim"
            await mod.preview(safe_name, "Studio", x, y, z, mode)
            if getattr(mod, "preview_data", None):
                origin = mod.preview_data.get("origin", {})
                return {
                    "ok": True,
                    "active": True,
                    "message": f"已在游戏内启动全息投影: {safe_name} (原点: {origin.get('x', '~')}, {origin.get('y', '~')}, {origin.get('z', '~')})"
                }
            return {"ok": True, "active": False, "message": f"已下发蓝图全息投影指令: {safe_name}"}

        elif action == "unpreview_ezmatic":
            mod = manager.mod_instances.get("Ezmatic")
            if mod:
                await mod.clear_preview("Studio")
            return {"ok": True, "active": False, "message": "已清除游戏内全息投影"}

        elif action == "build_ezmatic":
            mod = manager.mod_instances.get("Ezmatic")
            if not mod:
                return {"ok": False, "message": "Ezmatic 模块未加载"}
            x = params.get("x")
            y = params.get("y")
            z = params.get("z")
            mode = params.get("mode") or "trim"
            auto_confirm = params.get("auto_confirm", True)
            await mod.create(safe_name, "WebUI", x, y, z, mode)
            if getattr(mod, "pending", None):
                task_id = mod.pending.get("taskId", "")
                if auto_confirm:
                    loop = asyncio.get_running_loop()
                    loop.create_task(mod.run())
                    return {"ok": True, "message": f"已开始在游戏内建造蓝图: {safe_name} (任务 #{task_id})"}
                return {"ok": True, "message": f"已准备蓝图建造任务 #{task_id}，等待确认"}
            return {"ok": False, "message": "蓝图准备失败，请检查文件或坐标"}

        elif action == "draw_image":
            mod = manager.mod_instances.get("ImageMod")
            if not mod:
                return {"ok": False, "message": "ImageMod 模块未加载"}
            axis = params.get("axis", "x").lower()
            x = params.get("x", "~")
            y = params.get("y", "~")
            z = params.get("z", "~")
            await mod._cmd_image("Studio", "create", safe_name, axis, str(x), str(y), str(z))
            return {"ok": True, "message": f"已下发像素画绘制任务: {safe_name}"}

        elif action == "confirm_image":
            mod = manager.mod_instances.get("ImageMod")
            if mod:
                await mod._cmd_image("Studio", "y")
            return {"ok": True, "message": "已确认像素画绘制"}

        else:
            return {"ok": False, "message": f"未知的 Studio 动作指令: {action}"}

    except Exception as e:
        return {"ok": False, "message": f"执行动作失败: {e}"}


def execute_studio_action(action: str, category: str, filename: str, params: dict = None) -> dict:
    """调度游戏内动作 (播放音乐、执行投影、绘制像素画、运行函数)"""
    from lib.current import Current
    client = Current.client
    if not client:
        return {
            "ok": False,
            "message": "当前无活跃 Minecraft 客户端连接。游戏内投影与建造需在游戏内执行 /connect 连接。\n若仅查看蓝图外观，请点击「3D 预览」（完全无需连接游戏客户端）！"
        }

    import asyncio
    try:
        import webui.server as ws
        loop = getattr(ws, "_event_loop", None)
    except Exception:
        loop = None

    if loop is not None and not loop.is_closed():
        fut = asyncio.run_coroutine_threadsafe(
            _async_execute_studio_action(action, category, filename, params),
            loop
        )
        try:
            return fut.result(timeout=25)
        except Exception as e:
            return {"ok": False, "message": f"动作执行超时或异常: {e}"}
    else:
        # 无运行中循环时的回退(例如单元测试环境)
        try:
            cur_loop = asyncio.get_event_loop()
            if cur_loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(
                    _async_execute_studio_action(action, category, filename, params),
                    cur_loop
                )
                return fut.result(timeout=25)
            else:
                return cur_loop.run_until_complete(
                    _async_execute_studio_action(action, category, filename, params)
                )
        except Exception:
            try:
                return asyncio.run(
                    _async_execute_studio_action(action, category, filename, params)
                )
            except Exception as ex:
                return {"ok": False, "message": f"执行动作失败: {ex}"}


def _format_size(size_bytes: int) -> str:
    """人性化文件大小格式化"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def _hsl_to_rgb(h: float, s: float, l: float) -> tuple[int, int, int]:
    """HSL (0-360, 0-1, 0-1) 转换为 RGB (0-255)"""
    c = (1.0 - abs(2.0 * l - 1.0)) * s
    x = c * (1.0 - abs(((h / 60.0) % 2.0) - 1.0))
    m = l - c / 2.0
    if 0.0 <= h < 60.0:
        r, g, b = c, x, 0.0
    elif 60.0 <= h < 120.0:
        r, g, b = x, c, 0.0
    elif 120.0 <= h < 180.0:
        r, g, b = 0.0, c, x
    elif 180.0 <= h < 240.0:
        r, g, b = 0.0, x, c
    elif 240.0 <= h < 300.0:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    return int((r + m) * 255), int((g + m) * 255), int((b + m) * 255)


def get_block_color(block_identifier: str) -> str:
    """为 Minecraft 方块 ID 推断代表性 HEX 颜色"""
    import hashlib
    clean_id = re.sub(r"^minecraft:", "", str(block_identifier).lower().strip())

    # 1. 特殊与透明方块优先匹配
    if "glass" in clean_id:
        return "#99d9ea"

    # 2. 尝试从 mod/image/blocks.json 调色板匹配
    palette = get_block_palette()
    for item in palette:
        if item.get("id") == clean_id:
            rgb = item.get("rgb")
            if rgb and len(rgb) == 3:
                if rgb == [0, 0, 0] and "black" not in clean_id:
                    break
                return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"

    # 3. 关键词规则推断 (按精细度先后排序)
    KEYWORDS = [
        ("cherry", "#f4a6b8"),
        ("pink", "#ed8dac"),
        ("magenta", "#c74ebd"),
        ("purple", "#8932b8"),
        ("blue", "#3c44aa"),
        ("light_blue", "#3ab3da"),
        ("cyan", "#169c9c"),
        ("teal", "#169c9c"),
        ("green", "#5e7c16"),
        ("lime", "#80c71f"),
        ("yellow", "#fed83d"),
        ("orange", "#f9801d"),
        ("red", "#b02e26"),
        ("white", "#f9fffe"),
        ("light_gray", "#9d9d97"),
        ("gray", "#474f52"),
        ("black", "#1d1d21"),
        ("brown", "#835432"),
        ("leaf", "#567d34"),
        ("leaves", "#567d34"),
        ("grass", "#5c8e32"),
        ("dirt", "#866043"),
        ("mud", "#5c4436"),
        ("sand", "#d6c88f"),
        ("gravel", "#827f7f"),
        ("oak", "#b8945f"),
        ("spruce", "#725434"),
        ("birch", "#d7c185"),
        ("jungle", "#b88764"),
        ("acacia", "#ba6336"),
        ("dark_oak", "#4f3218"),
        ("mangrove", "#753630"),
        ("crimson", "#7e3954"),
        ("warped", "#2c6d75"),
        ("bamboo", "#e0c863"),
        ("wood", "#a07844"),
        ("log", "#6a4e32"),
        ("plank", "#a28250"),
        ("deepslate", "#4d4d52"),
        ("blackstone", "#2b262d"),
        ("basalt", "#515156"),
        ("obsidian", "#191325"),
        ("end_stone", "#dbdf9c"),
        ("purpur", "#a97d9a"),
        ("prismarine", "#5da39a"),
        ("quartz", "#ede6de"),
        ("amethyst", "#8d65c5"),
        ("copper", "#c06c4f"),
        ("iron", "#d8d8d8"),
        ("gold", "#f8d438"),
        ("diamond", "#5decf5"),
        ("emerald", "#17b850"),
        ("lapis", "#1a44a6"),
        ("redstone", "#e52020"),
        ("netherite", "#3e383a"),
        ("stone", "#828282"),
        ("cobble", "#737373"),
        ("diorite", "#c4c4c4"),
        ("andesite", "#888889"),
        ("granite", "#9c6d59"),
        ("brick", "#964d3c"),
        ("glass", "#99d9ea"),
        ("ice", "#8eb7f5"),
        ("water", "#3f76e4"),
        ("lava", "#e46014"),
        ("lantern", "#fce068"),
        ("torch", "#fce068"),
        ("glow", "#f8db60"),
        ("wool", "#e0e0e0"),
        ("concrete", "#7a7a7a"),
        ("terracotta", "#965d44"),
    ]
    for kw, col in KEYWORDS:
        if kw in clean_id:
            return col

    # 4. 稳定 HSL 散列降级 (色相散列, 饱和度 45%, 亮度 55%)
    h = int(hashlib.md5(clean_id.encode("utf-8")).hexdigest()[:4], 16) % 360
    r, g, b = _hsl_to_rgb(h, 0.45, 0.55)
    return f"#{r:02x}{g:02x}{b:02x}"


def get_textures_status() -> dict:
    """获取本地方块纹理包的当前状态与容量信息"""
    os.makedirs(BLOCK_TEXTURES_DIR, exist_ok=True)
    files = [f for f in os.listdir(BLOCK_TEXTURES_DIR) if f.lower().endswith((".png", ".jpg", ".webp"))]
    total_bytes = 0
    for f in files:
        fp = os.path.join(BLOCK_TEXTURES_DIR, f)
        if os.path.isfile(fp):
            total_bytes += os.path.getsize(fp)

    if total_bytes < 1024:
        size_fmt = f"{total_bytes} B"
    elif total_bytes < 1024 * 1024:
        size_fmt = f"{total_bytes / 1024:.1f} KB"
    else:
        size_fmt = f"{total_bytes / (1024 * 1024):.1f} MB"

    try:
        dir_display = os.path.relpath(BLOCK_TEXTURES_DIR, ROOT).replace("\\", "/")
    except ValueError:
        dir_display = BLOCK_TEXTURES_DIR.replace("\\", "/")

    return {
        "installed": len(files) > 0,
        "count": len(files),
        "size_bytes": total_bytes,
        "size_formatted": size_fmt,
        "directory": dir_display,
        "default_url": "https://github.com/InventivetalentDev/minecraft-assets/archive/refs/heads/1.20.4.zip",
    }


def uninstall_textures() -> dict:
    """卸载并清理本地所有已下载的方块纹理, 保留目录与 .gitkeep 占位"""
    os.makedirs(BLOCK_TEXTURES_DIR, exist_ok=True)
    deleted_count = 0
    import shutil
    for fname in os.listdir(BLOCK_TEXTURES_DIR):
        if fname == ".gitkeep":
            continue
        fp = os.path.join(BLOCK_TEXTURES_DIR, fname)
        try:
            if os.path.isfile(fp) or os.path.islink(fp):
                os.unlink(fp)
                deleted_count += 1
            elif os.path.isdir(fp):
                shutil.rmtree(fp, ignore_errors=True)
                deleted_count += 1
        except Exception:
            pass

    stat = get_textures_status()
    return {
        "ok": True,
        "deleted_count": deleted_count,
        "status": stat,
        "message": f"成功卸载 {deleted_count} 个方块纹理文件",
    }


def extract_local_minecraft_textures(force: bool = True) -> dict:
    """从本机 Minecraft 客户端的 .jar 提取 16x16 方块 PNG 纹理"""
    os.makedirs(BLOCK_TEXTURES_DIR, exist_ok=True)
    search_paths = []
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            search_paths.append(os.path.join(appdata, ".minecraft", "versions"))
    else:
        home = os.path.expanduser("~")
        search_paths.append(os.path.join(home, ".minecraft", "versions"))
        search_paths.append(os.path.join(home, "Library", "Application Support", "minecraft", "versions"))

    search_paths.append(os.path.join(ROOT, "mod", "bot", ".minecraft", "versions"))

    import glob
    import zipfile

    candidate_jars = []
    for sp in search_paths:
        if os.path.isdir(sp):
            candidate_jars.extend(glob.glob(os.path.join(sp, "*", "*.jar")))

    extracted_count = 0
    for jar_path in candidate_jars:
        try:
            with zipfile.ZipFile(jar_path, "r") as zf:
                for name in zf.namelist():
                    if name.startswith("assets/minecraft/textures/block/") and name.endswith(".png"):
                        base_name = os.path.basename(name)
                        if not base_name:
                            continue
                        out_path = os.path.join(BLOCK_TEXTURES_DIR, base_name)
                        if not os.path.exists(out_path) or force:
                            with open(out_path, "wb") as out_f:
                                out_f.write(zf.read(name))
                            extracted_count += 1
            if extracted_count >= 50:
                break
        except Exception:
            continue

    stat = get_textures_status()
    return {
        "ok": stat["installed"],
        "count": stat["count"],
        "extracted_count": extracted_count,
        "source": "local_client",
        "status": stat,
        "message": f"从本机客户端提取就绪 {stat['count']} 个纹理" if stat["installed"] else "未找到本机 Minecraft 客户端 jar 资源",
    }


def download_online_textures(source_url: str = None, fallback_local: bool = True) -> dict:
    """在线下载或更新方块纹理包 (支持 ZIP 压缩包或自定义 CDN 镜像)"""
    import urllib.request
    import io
    import zipfile

    url = (source_url or "").strip()
    if not url:
        url = "https://github.com/InventivetalentDev/minecraft-assets/archive/refs/heads/1.20.4.zip"

    download_count = 0
    error_msg = None

    if url.startswith(("http://", "https://")):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "EnderBridge-Studio/1.0 (Minecraft Texture Downloader)"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            if data[:4] == b"PK\x03\x04" or url.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
                    for name in zf.namelist():
                        if "textures/block/" in name and name.endswith(".png"):
                            base_name = os.path.basename(name)
                            if base_name:
                                out_path = os.path.join(BLOCK_TEXTURES_DIR, base_name)
                                with open(out_path, "wb") as out_f:
                                    out_f.write(zf.read(name))
                                download_count += 1
            elif url.endswith(".png"):
                base_name = os.path.basename(url)
                out_path = os.path.join(BLOCK_TEXTURES_DIR, base_name)
                with open(out_path, "wb") as out_f:
                    out_f.write(data)
                download_count = 1
        except Exception as e:
            error_msg = str(e)

    if download_count == 0 and fallback_local:
        local_res = extract_local_minecraft_textures(force=True)
        if local_res.get("ok"):
            local_res["notice"] = f"网络提示: {error_msg}，已自动从本机客户端提取就绪" if error_msg else "已从本机提取就绪"
            return local_res

    stat = get_textures_status()
    return {
        "ok": download_count > 0,
        "count": stat["count"],
        "download_count": download_count,
        "source": "online",
        "error": error_msg,
        "status": stat,
        "message": f"在线下载成功安装 {download_count} 个纹理" if download_count > 0 else f"下载失败: {error_msg or '未找到有效材质文件'}",
    }


def ensure_minecraft_textures(force: bool = False) -> int:
    """向后兼容接口: 返回当前已安装方块纹理数 (若指定 force=True 则从本机提取)"""
    if force:
        extract_local_minecraft_textures(force=True)
    return get_textures_status()["count"]


def resolve_block_texture_filenames(block_identifier: str, available_files: set[str] = None) -> tuple[str | None, str | None]:
    """解析方块的顶面与侧面纹理文件名 (top_tex, side_tex)"""
    if available_files is None:
        if os.path.isdir(BLOCK_TEXTURES_DIR):
            available_files = set(os.listdir(BLOCK_TEXTURES_DIR))
        else:
            available_files = set()

    clean = re.sub(r"^minecraft:", "", str(block_identifier).lower().strip())

    # 1. 经典特殊方块手工校准
    SPECIAL = {
        "chain": ("iron_chain.png", "iron_chain.png"),
        "bookshelf": ("oak_planks.png", "bookshelf.png"),
        "grass_block": ("grass_block_top.png", "grass_block_side.png"),
        "podzol": ("podzol_top.png", "podzol_side.png"),
        "mycelium": ("mycelium_top.png", "mycelium_side.png"),
        "dirt_path": ("dirt_path_top.png", "dirt_path_side.png"),
        "tnt": ("tnt_top.png", "tnt_side.png"),
        "crafting_table": ("crafting_table_top.png", "crafting_table_side.png"),
        "furnace": ("furnace_top.png", "furnace_front.png"),
        "blast_furnace": ("blast_furnace_top.png", "blast_furnace_front.png"),
        "smoker": ("smoker_top.png", "smoker_front.png"),
        "barrel": ("barrel_top.png", "barrel_side.png"),
        "hay_block": ("hay_block_top.png", "hay_block_side.png"),
        "bone_block": ("bone_block_top.png", "bone_block_side.png"),
        "chiseled_bookshelf": ("oak_planks.png", "chiseled_bookshelf_empty.png"),
    }
    if clean in SPECIAL:
        t, s = SPECIAL[clean]
        if t in available_files and s in available_files:
            return t, s

    # 2. 直观顶/侧/全同纹理匹配
    if f"{clean}_top.png" in available_files and f"{clean}.png" in available_files:
        return f"{clean}_top.png", f"{clean}.png"
    if f"{clean}_top.png" in available_files and f"{clean}_side.png" in available_files:
        return f"{clean}_top.png", f"{clean}_side.png"
    if f"{clean}.png" in available_files:
        return f"{clean}.png", f"{clean}.png"

    # 3. 台阶、楼梯、墙、栅栏等衍生方块 -> 查找基底材质
    for suffix in ["_stairs", "_slab", "_wall", "_fence_gate", "_fence", "_pressure_plate", "_button"]:
        if clean.endswith(suffix):
            stem = clean[:-len(suffix)]
            if f"{stem}_planks.png" in available_files:
                return f"{stem}_planks.png", f"{stem}_planks.png"
            if f"{stem}.png" in available_files:
                return f"{stem}.png", f"{stem}.png"
            if f"cobbled_{stem}.png" in available_files:
                return f"cobbled_{stem}.png", f"cobbled_{stem}.png"
            if f"polished_{stem}.png" in available_files:
                return f"polished_{stem}.png", f"polished_{stem}.png"

    # 4. 门与活板门
    if clean.endswith("_door"):
        if f"{clean}_top.png" in available_files:
            return f"{clean}_top.png", f"{clean}_bottom.png"
    if clean.endswith("_trapdoor"):
        if f"{clean}.png" in available_files:
            return f"{clean}.png", f"{clean}.png"

    # 5. 前缀模糊回退 (如 stripped_cherry_wood -> stripped_cherry_log)
    for stem_cand in [clean.replace("_wood", "_log"), clean.replace("stripped_", "")]:
        if f"{stem_cand}_top.png" in available_files and f"{stem_cand}.png" in available_files:
            return f"{stem_cand}_top.png", f"{stem_cand}.png"
        if f"{stem_cand}.png" in available_files:
            return f"{stem_cand}.png", f"{stem_cand}.png"

    return None, None


def parse_blueprint_voxels(category: str = "ezmatic", filename: str = "", file_path: str = None, max_blocks: int = 50000) -> dict:
    """提取蓝图文件的三维体素坐标与调色板信息 (供 WebUI / 本地离线 3D 渲染器使用)"""
    if file_path:
        full_path = os.path.abspath(file_path)
        if not os.path.isfile(full_path):
            raise FileNotFoundError(f"未找到蓝图文件: {file_path}")
        safe_name = os.path.basename(full_path)
    else:
        safe_name = sanitize_filename(filename)
        full_path = get_asset_file_path(category, safe_name)
    ext = Path(safe_name).suffix.lower()

    if ext != ".litematic":
        raise ValueError(f"目前仅支持预览 .litematic 格式蓝图 (当前为 {ext})")

    # 确保 config 虚拟模块加载
    try:
        from lib.config_loader import load_config
        load_config()
    except Exception:
        pass

    import asyncio
    from mod.ezmatic.main import parse_litematic

    # 异步解析 litematic (线程安全处理)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            data = pool.submit(asyncio.run, parse_litematic(full_path)).result()
    else:
        data = asyncio.run(parse_litematic(full_path))

    sx = int(data.get("sx", 0))
    sy = int(data.get("sy", 0))
    sz = int(data.get("sz", 0))
    raw_blocks = data.get("blocks") or []
    unmapped = data.get("unmappedBlocks") or []

    # 读取当前已安装纹理库 (若未安装则平滑使用调色板色彩着色)
    avail_tex = set(os.listdir(BLOCK_TEXTURES_DIR)) if os.path.isdir(BLOCK_TEXTURES_DIR) else set()

    palette_map = {}
    palette_list = []
    voxels = []

    def get_or_create_palette(raw_id: str) -> int:
        if raw_id in palette_map:
            idx = palette_map[raw_id]
            palette_list[idx]["count"] += 1
            return idx
        short_id = re.sub(r"^minecraft:", "", str(raw_id))
        color = get_block_color(raw_id)
        top_tex, side_tex = resolve_block_texture_filenames(raw_id, avail_tex)
        idx = len(palette_list)
        entry = {
            "id": raw_id,
            "shortId": short_id,
            "color": color,
            "count": 1,
            "textures": {
                "top": f"/static/textures/blocks/{top_tex}" if top_tex else None,
                "side": f"/static/textures/blocks/{side_tex}" if side_tex else None,
            },
        }
        palette_list.append(entry)
        palette_map[raw_id] = idx
        return idx


    # 合并 mapped 和 unmapped 方块
    all_raw = []
    for b in raw_blocks:
        all_raw.append((b["x"], b["y"], b["z"], b.get("identifier", "unknown")))
    for u in unmapped:
        all_raw.append((u["x"], u["y"], u["z"], u.get("name", "unknown")))

    truncated = False
    if len(all_raw) > max_blocks:
        truncated = True
        all_raw = all_raw[:max_blocks]

    min_y = sy
    max_y = 0
    for x, y, z, ident in all_raw:
        if y < min_y:
            min_y = y
        if y > max_y:
            max_y = y
        pal_idx = get_or_create_palette(ident)
        voxels.append([x, y, z, pal_idx])

    if min_y > max_y:
        min_y = 0
        max_y = max(0, sy - 1)

    return {
        "name": safe_name,
        "format": "litematic",
        "dimensions": {"x": sx, "y": sy, "z": sz},
        "minY": min_y,
        "maxY": max_y,
        "totalBlocks": len(raw_blocks) + len(unmapped),
        "renderedBlocks": len(voxels),
        "truncated": truncated,
        "palette": palette_list,
        "voxels": voxels,
    }


def generate_standalone_blueprint_html(data: dict) -> str:
    """生成完全独立的、零依赖的单文件 3D 离线蓝图预览 HTML (内嵌真实方块纹理与 Canvas 渲染器)"""
    import copy
    import base64

    export_data = copy.deepcopy(data)
    # 将调色板纹理转换为嵌入式 Base64 Data URL, 保证 100% 离线单文件运行
    for p in export_data.get("palette", []):
        texs = p.get("textures")
        if not texs:
            continue
        for face_key in ("top", "side"):
            tex_val = texs.get(face_key)
            if tex_val and not str(tex_val).startswith("data:"):
                fname = os.path.basename(str(tex_val))
                fpath = os.path.join(BLOCK_TEXTURES_DIR, fname)
                if os.path.isfile(fpath):
                    try:
                        with open(fpath, "rb") as tf:
                            b64 = base64.b64encode(tf.read()).decode("ascii")
                            texs[face_key] = f"data:image/png;base64,{b64}"
                    except Exception:
                        pass

    json_data = json.dumps(export_data, ensure_ascii=False)
    name = export_data.get("name", "Blueprint")
    dim = export_data.get("dimensions", {"x": 0, "y": 0, "z": 0})
    total = export_data.get("totalBlocks", 0)
    vol = dim.get("x", 0) * dim.get("y", 0) * dim.get("z", 0)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{name} - 3D 蓝图离线预览 (EnderBridge)</title>
  <style>
    :root {{
      --bg: #0f1117;
      --card: #181b24;
      --card-border: #282d3d;
      --text: #f1f5f9;
      --text-dim: #94a3b8;
      --primary: #3b82f6;
      --primary-hover: #2563eb;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
    body {{ background: var(--bg); color: var(--text); height: 100vh; display: flex; flex-direction: column; overflow: hidden; }}
    header {{ background: var(--card); border-bottom: 1px solid var(--card-border); padding: 10px 18px; display: flex; justify-content: space-between; align-items: center; flex-shrink: 0; }}
    .badge {{ font-size: 11px; padding: 2px 8px; border-radius: 6px; background: rgba(59,130,246,0.15); color: #60a5fa; border: 1px solid rgba(59,130,246,0.3); font-weight: 600; text-transform: uppercase; }}
    .main-layout {{ flex: 1; display: flex; overflow: hidden; position: relative; }}
    #canvasWrapper {{ flex: 1; position: relative; background: #15181e; overflow: hidden; user-select: none; }}
    canvas {{ display: block; width: 100%; height: 100%; cursor: grab; }}
    .sidebar {{ width: 320px; border-left: 1px solid var(--card-border); background: var(--card); display: flex; flex-direction: column; overflow: hidden; flex-shrink: 0; }}
    .side-section {{ padding: 14px; border-bottom: 1px solid var(--card-border); }}
    .btn {{ background: #282d3d; color: var(--text); border: 1px solid var(--card-border); padding: 5px 12px; border-radius: 6px; font-size: 11px; cursor: pointer; transition: all 0.15s; display: inline-flex; align-items: center; justify-content: center; gap: 4px; }}
    .btn:hover {{ background: #353b4f; }}
    .btn-primary {{ background: var(--primary); color: #fff; border-color: var(--primary); }}
    .btn-primary:hover {{ background: var(--primary-hover); }}
    .hud {{ position: absolute; bottom: 14px; left: 14px; background: rgba(20,22,28,0.85); backdrop-filter: blur(8px); padding: 6px 14px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.12); color: #e2e8f0; font-size: 11px; display: flex; align-items: center; gap: 14px; pointer-events: none; z-index: 5; }}
    .pal-list {{ flex: 1; overflow-y: auto; padding: 8px 12px; display: flex; flex-direction: column; gap: 5px; }}
    .pal-item {{ display: flex; align-items: center; gap: 8px; padding: 5px 8px; border-radius: 6px; background: #202430; font-size: 11px; border: 1px solid var(--card-border); cursor: pointer; }}
    input[type="range"] {{ accent-color: var(--primary); }}
  </style>
</head>
<body>
  <header>
    <div style="display:flex;align-items:center;gap:12px;">
      <div>
        <div style="display:flex;align-items:center;gap:8px;">
          <h2 style="font-size:15px;font-weight:700;">{name}</h2>
          <span class="badge">Litematic 3D</span>
        </div>
        <div style="font-size:11px;color:var(--text-dim);margin-top:2px;">
          尺寸: <strong>{dim.get("x")} × {dim.get("y")} × {dim.get("z")}</strong> | 体积: {vol:,} | 总方块: {total:,}
        </div>
      </div>
    </div>
    <div style="display:flex;gap:8px;">
      <button class="btn" id="btnToggleCam" title="切换透视 / 正交视角 (快捷键: P)">透视视角</button>
      <button class="btn btn-primary" id="btnToggleTex" title="快捷键: T">纹理: 开</button>
      <button class="btn" id="btnResetView">重置视角</button>
    </div>
  </header>

  <div class="main-layout">
    <div id="canvasWrapper">
      <canvas id="blueprintCanvas"></canvas>
      <div class="hud">
        <span>左键旋转</span>
        <span>右键平移</span>
        <span>滚轮缩放</span>
        <span>[T] 纹理 [P] 视角</span>
        <span id="voxelCountBadge" style="background:#3b82f6;color:#fff;padding:2px 8px;border-radius:10px;font-weight:600;">0 体素</span>
      </div>
    </div>

    <div class="sidebar">
      <div class="side-section">
        <div style="font-weight:600;font-size:12px;margin-bottom:8px;display:flex;justify-content:space-between;">
          <span>Y轴分层切片</span>
          <span id="sliceLabel" style="color:var(--primary);font-weight:700;">Y: 0 ~ 0</span>
        </div>
        <div style="display:flex;flex-direction:column;gap:6px;font-size:11px;">
          <div style="display:flex;align-items:center;gap:8px;">
            <span style="width:30px;color:var(--text-dim);">最低</span>
            <input type="range" id="sliceMin" style="flex:1;" />
            <span id="sliceMinVal" style="width:26px;text-align:right;font-weight:600;">0</span>
          </div>
          <div style="display:flex;align-items:center;gap:8px;">
            <span style="width:30px;color:var(--text-dim);">最高</span>
            <input type="range" id="sliceMax" style="flex:1;" />
            <span id="sliceMaxVal" style="width:26px;text-align:right;font-weight:600;">0</span>
          </div>
          <div style="display:flex;gap:6px;margin-top:4px;">
            <button class="btn" id="btnSliceDown" style="flex:1;">下一层</button>
            <button class="btn" id="btnSliceUp" style="flex:1;">上一层</button>
            <button class="btn" id="btnSliceReset" style="flex:1;">全部层</button>
          </div>
        </div>
      </div>

      <div style="padding:10px 14px 6px;display:flex;justify-content:space-between;align-items:center;">
        <span style="font-weight:600;font-size:12px;">材质与用量清单</span>
        <div style="display:flex;gap:4px;">
          <button class="btn" id="btnPalAll" style="font-size:10px;padding:2px 6px;">全选</button>
          <button class="btn" id="btnPalInvert" style="font-size:10px;padding:2px 6px;">反选</button>
        </div>
      </div>

      <div class="pal-list" id="palContainer"></div>
    </div>
  </div>

  <script>
    const DATA = {json_data};
    let visiblePalette = {{}};
    let sliceMin = DATA.minY, sliceMax = DATA.maxY;
    let cameraMode = "persp"; // "persp" | "ortho"

    let rotX = 0.55, rotY = 0.785, panX = 0, panY = 0;
    let distance = 25.0;
    let targetRotX = 0.55, targetRotY = 0.785, targetPanX = 0, targetPanY = 0;
    let targetDistance = 25.0;

    let showTextures = true;
    let texturesLoaded = false;
    let canvas = document.getElementById("blueprintCanvas");
    let gl = null, ctx2d = null;
    let isDragging = false, dragMode = "rotate", lastX = 0, lastY = 0, pinchDist = 0, isRendering = false;
    let colorCache = {{}};

    let progVoxel = null, progGrid = null;
    let bufPos = null, bufNormal = null, bufTex = null, bufColor = null;
    let bufGridPos = null, bufGridColor = null;
    let atlasTex = null, atlasCanvas = null;
    let voxelVertCount = 0, gridVertCount = 0;

    const Mat4 = {{
      create: function() {{
        let out = new Float32Array(16);
        out[0] = 1; out[5] = 1; out[10] = 1; out[15] = 1;
        return out;
      }},
      multiply: function(out, a, b) {{
        let a00 = a[0], a01 = a[1], a02 = a[2], a03 = a[3];
        let a10 = a[4], a11 = a[5], a12 = a[6], a13 = a[7];
        let a20 = a[8], a21 = a[9], a22 = a[10], a23 = a[11];
        let a30 = a[12], a31 = a[13], a32 = a[14], a33 = a[15];
        let b0 = b[0], b1 = b[1], b2 = b[2], b3 = b[3];
        out[0] = b0*a00 + b1*a10 + b2*a20 + b3*a30;
        out[1] = b0*a01 + b1*a11 + b2*a21 + b3*a31;
        out[2] = b0*a02 + b1*a12 + b2*a22 + b3*a32;
        out[3] = b0*a03 + b1*a13 + b2*a23 + b3*a33;
        b0 = b[4]; b1 = b[5]; b2 = b[6]; b3 = b[7];
        out[4] = b0*a00 + b1*a10 + b2*a20 + b3*a30;
        out[5] = b0*a01 + b1*a11 + b2*a21 + b3*a31;
        out[6] = b0*a02 + b1*a12 + b2*a22 + b3*a32;
        out[7] = b0*a03 + b1*a13 + b2*a23 + b3*a33;
        b0 = b[8]; b1 = b[9]; b2 = b[10]; b3 = b[11];
        out[8] = b0*a00 + b1*a10 + b2*a20 + b3*a30;
        out[9] = b0*a01 + b1*a11 + b2*a21 + b3*a31;
        out[10] = b0*a02 + b1*a12 + b2*a22 + b3*a32;
        out[11] = b0*a03 + b1*a13 + b2*a23 + b3*a33;
        b0 = b[12]; b1 = b[13]; b2 = b[14]; b3 = b[15];
        out[12] = b0*a00 + b1*a10 + b2*a20 + b3*a30;
        out[13] = b0*a01 + b1*a11 + b2*a21 + b3*a31;
        out[14] = b0*a02 + b1*a12 + b2*a22 + b3*a32;
        out[15] = b0*a03 + b1*a13 + b2*a23 + b3*a33;
        return out;
      }},
      perspective: function(out, fovy, aspect, near, far) {{
        let f = 1.0 / Math.tan(fovy / 2);
        let nf = 1 / (near - far);
        out[0] = f / aspect; out[1] = 0; out[2] = 0; out[3] = 0;
        out[4] = 0; out[5] = f; out[6] = 0; out[7] = 0;
        out[8] = 0; out[9] = 0; out[10] = (far + near) * nf; out[11] = -1;
        out[12] = 0; out[13] = 0; out[14] = (2 * far * near) * nf; out[15] = 0;
        return out;
      }},
      ortho: function(out, left, right, bottom, top, near, far) {{
        let lr = 1 / (left - right);
        let bt = 1 / (bottom - top);
        let nf = 1 / (near - far);
        out[0] = -2 * lr; out[1] = 0; out[2] = 0; out[3] = 0;
        out[4] = 0; out[5] = -2 * bt; out[6] = 0; out[7] = 0;
        out[8] = 0; out[9] = 0; out[10] = 2 * nf; out[11] = 0;
        out[12] = (left + right) * lr; out[13] = (top + bottom) * bt; out[14] = (far + near) * nf; out[15] = 1;
        return out;
      }},
      lookAt: function(out, eye, center, up) {{
        let eyex = eye[0], eyey = eye[1], eyez = eye[2];
        let upx = up[0], upy = up[1], upz = up[2];
        let centerx = center[0], centery = center[1], centerz = center[2];

        let z0 = eyex - centerx, z1 = eyey - centery, z2 = eyez - centerz;
        let len = Math.hypot(z0, z1, z2);
        if (len === 0) z2 = 1; else {{ z0 /= len; z1 /= len; z2 /= len; }}

        let x0 = upy * z2 - upz * z1, x1 = upz * z0 - upx * z2, x2 = upx * z1 - upy * z0;
        len = Math.hypot(x0, x1, x2);
        if (len === 0) {{ x0 = 0; x1 = 0; x2 = 0; }} else {{ x0 /= len; x1 /= len; x2 /= len; }}

        let y0 = z1 * x2 - z2 * x1, y1 = z2 * x0 - z0 * x2, y2 = z0 * x1 - z1 * x0;
        len = Math.hypot(y0, y1, y2);
        if (len === 0) {{ y0 = 0; y1 = 0; y2 = 0; }} else {{ y0 /= len; y1 /= len; y2 /= len; }}

        out[0] = x0; out[1] = y0; out[2] = z0; out[3] = 0;
        out[4] = x1; out[5] = y1; out[6] = z1; out[7] = 0;
        out[8] = x2; out[9] = y2; out[10] = z2; out[11] = 0;
        out[12] = -(x0 * eyex + x1 * eyey + x2 * eyez);
        out[13] = -(y0 * eyex + y1 * eyey + y2 * eyez);
        out[14] = -(z0 * eyex + z1 * eyey + z2 * eyez);
        out[15] = 1;
        return out;
      }}
    }};

    function initGL() {{
      try {{
        gl = canvas.getContext("webgl", {{ antialias: true, alpha: false }}) ||
             canvas.getContext("experimental-webgl", {{ antialias: true, alpha: false }});
      }} catch (e) {{ gl = null; }}
      if (!gl) {{
        ctx2d = canvas.getContext("2d");
        return false;
      }}

      function compile(type, src) {{
        let s = gl.createShader(type);
        gl.shaderSource(s, src);
        gl.compileShader(s);
        return s;
      }}
      function link(vsSrc, fsSrc) {{
        let p = gl.createProgram();
        gl.attachShader(p, compile(gl.VERTEX_SHADER, vsSrc));
        gl.attachShader(p, compile(gl.FRAGMENT_SHADER, fsSrc));
        gl.linkProgram(p);
        return p;
      }}

      const vsVoxel = `
        attribute vec3 aPosition;
        attribute vec3 aNormal;
        attribute vec2 aTexCoord;
        attribute vec4 aColor;
        uniform mat4 uMVP;
        varying vec2 vTexCoord;
        varying vec4 vColor;
        varying float vLight;
        void main() {{
          gl_Position = uMVP * vec4(aPosition, 1.0);
          vTexCoord = aTexCoord;
          vColor = aColor;
          float light = 0.82;
          if (aNormal.y > 0.5) light = 1.0;
          else if (aNormal.y < -0.5) light = 0.5;
          else if (abs(aNormal.x) > 0.5) light = 0.65;
          else if (abs(aNormal.z) > 0.5) light = 0.82;
          vLight = light;
        }}
      `;
      const fsVoxel = `
        precision mediump float;
        varying vec2 vTexCoord;
        varying vec4 vColor;
        varying float vLight;
        uniform sampler2D uSampler;
        uniform bool uUseTexture;
        void main() {{
          vec4 base = vColor;
          if (uUseTexture) {{
            vec4 tex = texture2D(uSampler, vTexCoord);
            if (tex.a < 0.15) discard;
            base = tex;
          }}
          gl_FragColor = vec4(base.rgb * vLight, base.a);
        }}
      `;
      progVoxel = link(vsVoxel, fsVoxel);
      progVoxel.aPosition = gl.getAttribLocation(progVoxel, "aPosition");
      progVoxel.aNormal = gl.getAttribLocation(progVoxel, "aNormal");
      progVoxel.aTexCoord = gl.getAttribLocation(progVoxel, "aTexCoord");
      progVoxel.aColor = gl.getAttribLocation(progVoxel, "aColor");
      progVoxel.uMVP = gl.getUniformLocation(progVoxel, "uMVP");
      progVoxel.uSampler = gl.getUniformLocation(progVoxel, "uSampler");
      progVoxel.uUseTexture = gl.getUniformLocation(progVoxel, "uUseTexture");

      const vsLine = `
        attribute vec3 aPosition;
        attribute vec4 aColor;
        uniform mat4 uMVP;
        varying vec4 vColor;
        void main() {{
          gl_Position = uMVP * vec4(aPosition, 1.0);
          vColor = aColor;
        }}
      `;
      const fsLine = `
        precision mediump float;
        varying vec4 vColor;
        void main() {{
          gl_FragColor = vColor;
        }}
      `;
      progGrid = link(vsLine, fsLine);
      progGrid.aPosition = gl.getAttribLocation(progGrid, "aPosition");
      progGrid.aColor = gl.getAttribLocation(progGrid, "aColor");
      progGrid.uMVP = gl.getUniformLocation(progGrid, "uMVP");

      bufPos = gl.createBuffer();
      bufNormal = gl.createBuffer();
      bufTex = gl.createBuffer();
      bufColor = gl.createBuffer();

      bufGridPos = gl.createBuffer();
      bufGridColor = gl.createBuffer();

      return true;
    }}

    function isTransparent(p) {{
      if (!p) return true;
      let id = (p.id || "").toLowerCase();
      return id.includes("glass") || id.includes("leave") || id.includes("leaf") ||
             id.includes("water") || id.includes("ice") || id.includes("chain") ||
             id.includes("bar") || id.includes("fence") || id.includes("door") ||
             id.includes("torch") || id.includes("lantern") || id.includes("slab") ||
             id.includes("stair") || id.includes("carpet") || id.includes("pane") ||
             id.includes("trapdoor") || id.includes("air");
    }}

    function parseHex(hex) {{
      let c = (hex || "#888888").replace("#", "");
      if (c.length === 3) c = c[0]+c[0]+c[1]+c[1]+c[2]+c[2];
      let num = parseInt(c, 16);
      if (isNaN(num)) return [0.7, 0.7, 0.7, 1.0];
      return [(num >> 16) / 255.0, ((num >> 8) & 0xff) / 255.0, (num & 0xff) / 255.0, 1.0];
    }}

    function buildAtlas() {{
      if (!gl || !DATA.palette) return;
      let tileSize = 16;
      let numTiles = DATA.palette.length * 2;
      let tilesPerRow = 16;
      while (tilesPerRow * tilesPerRow < numTiles && tilesPerRow < 64) tilesPerRow *= 2;
      let atlasSize = tilesPerRow * tileSize;

      if (!atlasCanvas) atlasCanvas = document.createElement("canvas");
      atlasCanvas.width = atlasSize; atlasCanvas.height = atlasSize;
      let actx = atlasCanvas.getContext("2d");
      actx.imageSmoothingEnabled = false;
      actx.clearRect(0, 0, atlasSize, atlasSize);

      let tileIdx = 0;
      DATA.palette.forEach(p => {{
        ["top", "side"].forEach(face => {{
          let col = tileIdx % tilesPerRow, row = Math.floor(tileIdx / tilesPerRow);
          let x = col * tileSize, y = row * tileSize;
          let img = p["_img_" + face];
          if (img && img.complete && img.naturalWidth > 0) {{
            actx.drawImage(img, 0, 0, Math.min(16, img.naturalWidth), Math.min(16, img.naturalHeight), x, y, tileSize, tileSize);
          }} else {{
            actx.fillStyle = p.color || "#888888";
            actx.fillRect(x, y, tileSize, tileSize);
          }}
          let eps = 0.1;
          let u0 = (x + eps) / atlasSize, v0 = (y + eps) / atlasSize;
          let u1 = (x + tileSize - eps) / atlasSize, v1 = (y + tileSize - eps) / atlasSize;
          if (face === "top") p._uvTop = [u0, v0, u1, v1];
          else p._uvSide = [u0, v0, u1, v1];
          tileIdx++;
        }});
      }});

      if (!atlasTex) atlasTex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, atlasTex);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, atlasCanvas);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    }}

    function rebuildMesh() {{
      if (!gl) return;
      let voxels = DATA.voxels || [];
      let palette = DATA.palette || [];
      let dim = DATA.dimensions || {{ x: 1, y: 1, z: 1 }};
      let cx = dim.x / 2.0, cy = (DATA.minY + DATA.maxY) / 2.0, cz = dim.z / 2.0;

      let spatial = {{}};
      for (let i = 0; i < voxels.length; i++) {{
        let v = voxels[i];
        spatial[v[0] + "_" + v[1] + "_" + v[2]] = v[3];
      }}

      let positions = [], normals = [], uvs = [], colors = [];
      let rendered = 0;

      function pushQuad(p0, p1, p2, p3, norm, uvRect, rgba) {{
        let u0 = uvRect[0], v0 = uvRect[1], u1 = uvRect[2], v1 = uvRect[3];
        let qVerts = [
          p0, [u0, v1], p1, [u1, v1], p2, [u1, v0],
          p0, [u0, v1], p2, [u1, v0], p3, [u0, v0]
        ];
        for (let vi = 0; vi < 6; vi++) {{
          let pt = qVerts[vi * 2], uv = qVerts[vi * 2 + 1];
          positions.push(pt[0], pt[1], pt[2]);
          normals.push(norm[0], norm[1], norm[2]);
          uvs.push(uv[0], uv[1]);
          colors.push(rgba[0], rgba[1], rgba[2], rgba[3]);
        }}
      }}

      for (let j = 0; j < voxels.length; j++) {{
        let v = voxels[j];
        let vx = v[0], vy = v[1], vz = v[2], palIdx = v[3];
        if (vy < sliceMin || vy > sliceMax || visiblePalette[palIdx] === false) continue;
        rendered++;

        let palEntry = palette[palIdx] || {{}};
        let rgba = parseHex(palEntry.color);
        let uvTop = palEntry._uvTop || [0, 0, 1, 1];
        let uvSide = palEntry._uvSide || [0, 0, 1, 1];

        let bx = vx - cx + 0.5, by = vy - cy + 0.5, bz = vz - cz + 0.5;
        let x0 = bx - 0.5, x1 = bx + 0.5;
        let y0 = by - 0.5, y1 = by + 0.5;
        let z0 = bz - 0.5, z1 = bz + 0.5;

        // Face Culling in 6 directions
        let nTop = spatial[vx + "_" + (vy + 1) + "_" + vz];
        if (vy + 1 > sliceMax || nTop === undefined || visiblePalette[nTop] === false || isTransparent(palette[nTop])) {{
          pushQuad([x0, y1, z1], [x1, y1, z1], [x1, y1, z0], [x0, y1, z0], [0, 1, 0], uvTop, rgba);
        }}
        let nBot = spatial[vx + "_" + (vy - 1) + "_" + vz];
        if (vy - 1 < sliceMin || nBot === undefined || visiblePalette[nBot] === false || isTransparent(palette[nBot])) {{
          pushQuad([x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1], [0, -1, 0], uvTop, rgba);
        }}
        let nEast = spatial[(vx + 1) + "_" + vy + "_" + vz];
        if (nEast === undefined || visiblePalette[nEast] === false || isTransparent(palette[nEast])) {{
          pushQuad([x1, y0, z1], [x1, y0, z0], [x1, y1, z0], [x1, y1, z1], [1, 0, 0], uvSide, rgba);
        }}
        let nWest = spatial[(vx - 1) + "_" + vy + "_" + vz];
        if (nWest === undefined || visiblePalette[nWest] === false || isTransparent(palette[nWest])) {{
          pushQuad([x0, y0, z0], [x0, y0, z1], [x0, y1, z1], [x0, y1, z0], [-1, 0, 0], uvSide, rgba);
        }}
        let nSouth = spatial[vx + "_" + vy + "_" + (vz + 1)];
        if (nSouth === undefined || visiblePalette[nSouth] === false || isTransparent(palette[nSouth])) {{
          pushQuad([x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1], [0, 0, 1], uvSide, rgba);
        }}
        let nNorth = spatial[vx + "_" + vy + "_" + (vz - 1)];
        if (nNorth === undefined || visiblePalette[nNorth] === false || isTransparent(palette[nNorth])) {{
          pushQuad([x1, y0, z0], [x0, y0, z0], [x0, y1, z0], [x1, y1, z0], [0, 0, -1], uvSide, rgba);
        }}
      }}

      document.getElementById("voxelCountBadge").textContent = rendered + " / " + DATA.totalBlocks + " 体素";
      voxelVertCount = positions.length / 3;

      gl.bindBuffer(gl.ARRAY_BUFFER, bufPos);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(positions), gl.DYNAMIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, bufNormal);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(normals), gl.DYNAMIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, bufTex);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(uvs), gl.DYNAMIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, bufColor);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(colors), gl.DYNAMIC_DRAW);

      // Grid mesh
      let gy = DATA.minY - cy;
      let step = Math.max(1, Math.floor(Math.max(dim.x, dim.z) / 10));
      let x0 = -cx, x1 = dim.x - cx, z0 = -cz, z1 = dim.z - cz;
      let gridPos = [], gridCol = [];
      for (let z = 0; z <= dim.z; z += step) {{
        gridPos.push(x0, gy, z - cz, x1, gy, z - cz);
        gridCol.push(0.6, 0.7, 0.9, 0.15, 0.6, 0.7, 0.9, 0.15);
      }}
      for (let x = 0; x <= dim.x; x += step) {{
        gridPos.push(x - cx, gy, z0, x - cx, gy, z1);
        gridCol.push(0.6, 0.7, 0.9, 0.15, 0.6, 0.7, 0.9, 0.15);
      }}
      gridVertCount = gridPos.length / 3;
      gl.bindBuffer(gl.ARRAY_BUFFER, bufGridPos);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(gridPos), gl.STATIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, bufGridColor);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(gridCol), gl.STATIC_DRAW);
    }}

    function renderWebGL() {{
      let rect = canvas.getBoundingClientRect();
      let dpr = window.devicePixelRatio || 1;
      let w = Math.floor(rect.width * dpr), h = Math.floor(rect.height * dpr);
      if (w <= 0 || h <= 0) return;
      if (canvas.width !== w || canvas.height !== h) {{ canvas.width = w; canvas.height = h; }}
      gl.viewport(0, 0, w, h);

      gl.enable(gl.DEPTH_TEST);
      gl.depthFunc(gl.LEQUAL);
      gl.enable(gl.CULL_FACE);
      gl.cullFace(gl.BACK);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

      gl.clearColor(0.082, 0.094, 0.118, 1.0);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

      let cosP = Math.cos(rotX), sinP = Math.sin(rotX);
      let cosY = Math.cos(rotY), sinY = Math.sin(rotY);

      let ex = distance * cosP * sinY, ey = distance * sinP, ez = distance * cosP * cosY;
      let fx = -ex, fy = -ey, fz = -ez;
      let flen = Math.hypot(fx, fy, fz) || 1;
      fx /= flen; fy /= flen; fz /= flen;

      let rx = -fz, ry = 0, rz = fx;
      let rlen = Math.hypot(rx, rz) || 1;
      rx /= rlen; rz /= rlen;

      let ux = ry * fz - rz * fy, uy = rz * fx - rx * fz, uz = rx * fy - ry * fx;
      let targetX = rx * panX + ux * panY;
      let targetY = ry * panX + uy * panY;
      let targetZ = rz * panX + uz * panY;

      let eyeX = targetX + ex, eyeY = targetY + ey, eyeZ = targetZ + ez;

      let viewMat = Mat4.create();
      Mat4.lookAt(viewMat, [eyeX, eyeY, eyeZ], [targetX, targetY, targetZ], [ux, uy, uz]);

      let projMat = Mat4.create();
      let aspect = w / h;
      let farDist = Math.max(3000, distance * 8);
      if (cameraMode === "persp") {{
        Mat4.perspective(projMat, 45 * Math.PI / 180, aspect, 0.5, farDist);
      }} else {{
        let orthoH = distance * 0.5;
        let orthoW = orthoH * aspect;
        Mat4.ortho(projMat, -orthoW, orthoW, -orthoH, orthoH, -farDist, farDist);
      }}

      let mvp = Mat4.create();
      Mat4.multiply(mvp, projMat, viewMat);

      if (gridVertCount > 0 && progGrid) {{
        gl.useProgram(progGrid);
        gl.uniformMatrix4fv(progGrid.uMVP, false, mvp);
        gl.bindBuffer(gl.ARRAY_BUFFER, bufGridPos);
        gl.vertexAttribPointer(progGrid.aPosition, 3, gl.FLOAT, false, 0, 0);
        gl.enableVertexAttribArray(progGrid.aPosition);
        gl.bindBuffer(gl.ARRAY_BUFFER, bufGridColor);
        gl.vertexAttribPointer(progGrid.aColor, 4, gl.FLOAT, false, 0, 0);
        gl.enableVertexAttribArray(progGrid.aColor);
        gl.drawArrays(gl.LINES, 0, gridVertCount);
      }}

      if (voxelVertCount > 0 && progVoxel) {{
        gl.useProgram(progVoxel);
        gl.uniformMatrix4fv(progVoxel.uMVP, false, mvp);
        gl.uniform1i(progVoxel.uUseTexture, showTextures ? 1 : 0);

        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, atlasTex);
        gl.uniform1i(progVoxel.uSampler, 0);

        gl.bindBuffer(gl.ARRAY_BUFFER, bufPos);
        gl.vertexAttribPointer(progVoxel.aPosition, 3, gl.FLOAT, false, 0, 0);
        gl.enableVertexAttribArray(progVoxel.aPosition);

        gl.bindBuffer(gl.ARRAY_BUFFER, bufNormal);
        gl.vertexAttribPointer(progVoxel.aNormal, 3, gl.FLOAT, false, 0, 0);
        gl.enableVertexAttribArray(progVoxel.aNormal);

        gl.bindBuffer(gl.ARRAY_BUFFER, bufTex);
        gl.vertexAttribPointer(progVoxel.aTexCoord, 2, gl.FLOAT, false, 0, 0);
        gl.enableVertexAttribArray(progVoxel.aTexCoord);

        gl.bindBuffer(gl.ARRAY_BUFFER, bufColor);
        gl.vertexAttribPointer(progVoxel.aColor, 4, gl.FLOAT, false, 0, 0);
        gl.enableVertexAttribArray(progVoxel.aColor);

        gl.drawArrays(gl.TRIANGLES, 0, voxelVertCount);
      }}
    }}

    // Canvas 2D Fallback
    function drawTexturedParallelogram(ctx, img, x0, y0, ux, uy, vx, vy, tint) {{
      ctx.save();
      ctx.transform(ux / 16.0, uy / 16.0, vx / 16.0, vy / 16.0, x0, y0);
      let sw = Math.min(16, img.naturalWidth || 16);
      let sh = Math.min(16, img.naturalHeight || 16);
      ctx.drawImage(img, 0, 0, sw, sh, 0, 0, 16, 16);
      if (tint) {{ ctx.fillStyle = tint; ctx.fillRect(0, 0, 16, 16); }}
      ctx.restore();
    }}

    function renderCanvas2D() {{
      if (!ctx2d) return;
      let rect = canvas.getBoundingClientRect();
      let dpr = window.devicePixelRatio || 1;
      let w = Math.floor(rect.width * dpr), h = Math.floor(rect.height * dpr);
      if (w <= 0 || h <= 0) return;
      if (canvas.width !== w || canvas.height !== h) {{ canvas.width = w; canvas.height = h; }}
      ctx2d.save();
      ctx2d.scale(dpr, dpr);
      ctx2d.fillStyle = "#15181e";
      ctx2d.fillRect(0, 0, rect.width, rect.height);
      ctx2d.restore();
    }}

    function requestRender() {{
      if (isRendering) return;
      isRendering = true;
      requestAnimationFrame(renderLoop);
    }}

    function renderLoop() {{
      let damp = 0.25;
      let dX = targetRotX - rotX, dY = targetRotY - rotY;
      let dPX = targetPanX - panX, dPY = targetPanY - panY;
      let dDist = targetDistance - distance;

      rotX += dX * damp; rotY += dY * damp;
      panX += dPX * damp; panY += dPY * damp;
      distance += dDist * damp;

      let isMoving = Math.abs(dX) > 0.0001 || Math.abs(dY) > 0.0001 ||
                     Math.abs(dPX) > 0.001 || Math.abs(dPY) > 0.001 ||
                     Math.abs(dDist) > 0.005;

      if (gl) renderWebGL();
      else renderCanvas2D();

      if (isMoving || isDragging) {{
        requestAnimationFrame(renderLoop);
      }} else {{
        isRendering = false;
      }}
    }}

    function updateSliceUI() {{
      document.getElementById("sliceLabel").textContent = "Y: " + sliceMin + " ~ " + sliceMax;
      document.getElementById("sliceMinVal").textContent = sliceMin;
      document.getElementById("sliceMaxVal").textContent = sliceMax;
      document.getElementById("sliceMin").value = sliceMin;
      document.getElementById("sliceMax").value = sliceMax;
    }}

    function resetCamera() {{
      rotX = targetRotX = 0.55;
      rotY = targetRotY = 0.785;
      panX = targetPanX = 0;
      panY = targetPanY = 0;
      let maxDim = Math.max(DATA.dimensions.x, DATA.dimensions.y, DATA.dimensions.z, 1);
      distance = targetDistance = Math.max(10, maxDim * 2.2);
      requestRender();
    }}

    function initUI() {{
      for (let i = 0; i < DATA.palette.length; i++) visiblePalette[i] = true;
      let sMin = document.getElementById("sliceMin");
      let sMax = document.getElementById("sliceMax");
      sMin.min = DATA.minY; sMin.max = DATA.maxY; sMin.value = DATA.minY;
      sMax.min = DATA.minY; sMax.max = DATA.maxY; sMax.value = DATA.maxY;
      updateSliceUI();

      sMin.addEventListener("input", e => {{
        sliceMin = Math.min(parseInt(e.target.value, 10), sliceMax);
        updateSliceUI(); rebuildMesh(); requestRender();
      }});
      sMax.addEventListener("input", e => {{
        sliceMax = Math.max(parseInt(e.target.value, 10), sliceMin);
        updateSliceUI(); rebuildMesh(); requestRender();
      }});

      document.getElementById("btnSliceUp").addEventListener("click", () => {{
        if (sliceMax < DATA.maxY) {{ sliceMax++; sliceMin = sliceMax; updateSliceUI(); rebuildMesh(); requestRender(); }}
      }});
      document.getElementById("btnSliceDown").addEventListener("click", () => {{
        if (sliceMin > DATA.minY) {{ sliceMin--; sliceMax = sliceMin; updateSliceUI(); rebuildMesh(); requestRender(); }}
      }});
      document.getElementById("btnSliceReset").addEventListener("click", () => {{
        sliceMin = DATA.minY; sliceMax = DATA.maxY; updateSliceUI(); rebuildMesh(); requestRender();
      }});

      let btnTex = document.getElementById("btnToggleTex");
      if (btnTex) {{
        btnTex.addEventListener("click", () => {{
          showTextures = !showTextures;
          btnTex.textContent = showTextures ? "纹理: 开" : "纹理: 关";
          btnTex.classList.toggle("btn-primary", showTextures);
          requestRender();
        }});
      }}

      let btnCam = document.getElementById("btnToggleCam");
      if (btnCam) {{
        btnCam.addEventListener("click", () => {{
          cameraMode = cameraMode === "persp" ? "ortho" : "persp";
          btnCam.textContent = cameraMode === "persp" ? "透视视角" : "正交等距";
          requestRender();
        }});
      }}

      window.addEventListener("keydown", e => {{
        if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA")) return;
        if (e.key === "t" || e.key === "T") {{
          if (btnTex) btnTex.click();
        }} else if (e.key === "p" || e.key === "P") {{
          if (btnCam) btnCam.click();
        }}
      }});

      let palContainer = document.getElementById("palContainer");
      palContainer.innerHTML = DATA.palette.map((p, i) => {{
        let iconHtml = "";
        let texSrc = p.textures ? (p.textures.side || p.textures.top) : null;
        if (texSrc) {{
          iconHtml = `<img src="${{texSrc}}" style="width:14px;height:14px;image-rendering:pixelated;object-fit:cover;border-radius:2px;border:1px solid rgba(0,0,0,0.2);flex-shrink:0;" onerror="this.style.display='none';this.nextElementSibling.style.display='inline-block';"><span style="display:none;width:12px;height:12px;border-radius:2px;background:${{p.color}};border:1px solid rgba(0,0,0,0.2);flex-shrink:0;"></span>`;
        }} else {{
          iconHtml = `<span style="display:inline-block;width:12px;height:12px;border-radius:2px;background:${{p.color}};border:1px solid rgba(0,0,0,0.2);flex-shrink:0;"></span>`;
        }}
        return `
        <label class="pal-item">
          <input type="checkbox" data-idx="${{i}}" checked>
          ${{iconHtml}}
          <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${{p.id}}">${{p.shortId || p.id}}</span>
          <strong style="color:var(--text-dim);font-size:10px;">×${{p.count}}</strong>
        </label>`;
      }}).join("");

      palContainer.querySelectorAll("input").forEach(cb => {{
        cb.addEventListener("change", () => {{
          visiblePalette[parseInt(cb.dataset.idx, 10)] = cb.checked;
          rebuildMesh(); requestRender();
        }});
      }});

      document.getElementById("btnPalAll").addEventListener("click", () => {{
        for (let i = 0; i < DATA.palette.length; i++) visiblePalette[i] = true;
        palContainer.querySelectorAll("input").forEach(cb => cb.checked = true);
        rebuildMesh(); requestRender();
      }});
      document.getElementById("btnPalInvert").addEventListener("click", () => {{
        for (let i = 0; i < DATA.palette.length; i++) visiblePalette[i] = !visiblePalette[i];
        palContainer.querySelectorAll("input").forEach((cb, i) => cb.checked = visiblePalette[i]);
        rebuildMesh(); requestRender();
      }});

      document.getElementById("btnResetView").addEventListener("click", resetCamera);
    }}

    function initEvents() {{
      let wrap = document.getElementById("canvasWrapper");
      wrap.addEventListener("contextmenu", e => e.preventDefault());
      wrap.addEventListener("mousedown", e => {{
        isDragging = true; lastX = e.clientX; lastY = e.clientY;
        dragMode = (e.button === 2 || e.shiftKey) ? "pan" : "rotate";
        wrap.style.cursor = dragMode === "pan" ? "move" : "grabbing";
      }});
      window.addEventListener("mousemove", e => {{
        if (!isDragging) return;
        let dx = e.clientX - lastX, dy = e.clientY - lastY;
        lastX = e.clientX; lastY = e.clientY;
        if (dragMode === "rotate") {{
          targetRotY -= dx * 0.008;
          targetRotX = Math.max(-1.48, Math.min(1.48, targetRotX + dy * 0.008));
        }} else {{
          let pSpeed = distance * 0.0018;
          targetPanX -= dx * pSpeed; targetPanY += dy * pSpeed;
        }}
        requestRender();
      }});
      window.addEventListener("mouseup", () => {{ if (isDragging) {{ isDragging = false; wrap.style.cursor = "grab"; }} }});
      wrap.addEventListener("wheel", e => {{
        e.preventDefault();
        let factor = e.deltaY < 0 ? 0.88 : 1.14;
        targetDistance = Math.max(2.0, Math.min(600.0, targetDistance * factor));
        requestRender();
      }}, {{ passive: false }});
      window.addEventListener("resize", () => {{ requestRender(); }});
    }}

    // Load textures & start
    initGL();
    initUI();
    initEvents();

    let toLoad = 0, loaded = 0;
    DATA.palette.forEach(p => {{
      if (p.textures) {{
        ["top", "side"].forEach(face => {{
          let url = p.textures[face];
          if (url) {{
            toLoad++;
            let img = new Image();
            img.onload = img.onerror = () => {{
              loaded++;
              if (loaded >= toLoad) {{
                texturesLoaded = true;
                buildAtlas();
                requestRender();
              }}
            }};
            img.src = url;
            p["_img_" + face] = img;
          }}
        }});
      }}
    }});
    buildAtlas();
    if (toLoad === 0) texturesLoaded = true;
    rebuildMesh();
    resetCamera();
  </script>
</body>
</html>
"""
    return html


def preview_blueprint_locally(target: str = "", export_path: str = None, open_browser: bool = True) -> str:
    """在本地离线生成 3D 蓝图预览 HTML 并可选唤起浏览器 (无需连接任何 MC 客户端)"""
    ez_dir = get_base_path("ezmatic")

    resolved_path = None
    if target:
        cand = os.path.abspath(target)
        if os.path.isfile(cand):
            resolved_path = cand
        elif os.path.isfile(os.path.join(ROOT, target)):
            resolved_path = os.path.join(ROOT, target)
        elif os.path.isfile(os.path.join(ez_dir, target)):
            resolved_path = os.path.join(ez_dir, target)
        elif os.path.isfile(os.path.join(ez_dir, target + ".litematic")):
            resolved_path = os.path.join(ez_dir, target + ".litematic")

    if not resolved_path:
        # 尝试自动寻找 ez_dir 下的首个 .litematic
        if os.path.isdir(ez_dir):
            for entry in os.scandir(ez_dir):
                if entry.is_file() and entry.name.lower().endswith(".litematic"):
                    resolved_path = entry.path
                    break

    if not resolved_path:
        raise FileNotFoundError(f"未找到指定的蓝图文件: '{target}' (搜索目录: {ez_dir})")

    data = parse_blueprint_voxels(file_path=resolved_path)
    html_content = generate_standalone_blueprint_html(data)

    if export_path:
        out_file = os.path.abspath(export_path)
    else:
        logs_dir = os.path.join(ROOT, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        stem = Path(resolved_path).stem
        out_file = os.path.join(logs_dir, f"blueprint_preview_{stem}.html")

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    if open_browser:
        import webbrowser
        webbrowser.open(Path(out_file).as_uri())

    return out_file

