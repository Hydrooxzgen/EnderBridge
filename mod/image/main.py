"""图片像素画转换 Mod

将图片转换为 Minecraft 像素画(基于 setblock/fill 命令)
"""
import asyncio
import json
import math
import os
import re
import shutil
import time

from PIL import Image

from config import basePath
from lib.command import Command
from lib.command import apply_config_aliases

MAX_IMAGE_DIM = 256
MAX_CHUNKS = 100
FILL_LIMIT = 32767

# 颜色缓存
color_cache = {}


# ---- 颜色工具 ----

def rgb_to_hsv(r, g, b):
    r /= 255
    g /= 255
    b /= 255
    max_ = max(r, g, b)
    min_ = min(r, g, b)
    d = max_ - min_
    h = 0
    s = 0 if max_ == 0 else d / max_
    v = max_
    if d != 0:
        if max_ == r:
            h = (g - b) / d + (6 if g < b else 0)
        elif max_ == g:
            h = (b - r) / d + 2
        else:
            h = (r - g) / d + 4
        h /= 6
    return [h, s, v]


def rgb_to_lab(r, g, b):
    r /= 255
    g /= 255
    b /= 255
    r = ((r + 0.055) / 1.055) ** 2.4 if r > 0.04045 else r / 12.92
    g = ((g + 0.055) / 1.055) ** 2.4 if g > 0.04045 else g / 12.92
    b = ((b + 0.055) / 1.055) ** 2.4 if b > 0.04045 else b / 12.92
    x = (r * 0.4124564 + g * 0.3575761 + b * 0.1804375) / 0.95047
    y = (r * 0.2126729 + g * 0.7151522 + b * 0.0721750) / 1.00000
    z = (r * 0.0193339 + g * 0.1191920 + b * 0.9503041) / 1.08883
    x = x ** (1 / 3) if x > 0.008856 else (7.787 * x) + 16 / 116
    y = y ** (1 / 3) if y > 0.008856 else (7.787 * y) + 16 / 116
    z = z ** (1 / 3) if z > 0.008856 else (7.787 * z) + 16 / 116
    return [116 * y - 16, 500 * (x - y), 200 * (y - z)]


def _find_best_block(r, g, b, palette):
    lab = rgb_to_lab(r, g, b)
    min_dist = float("inf")
    best = palette[0]

    for block in palette:
        block_lab = rgb_to_lab(block["rgb"][0], block["rgb"][1], block["rgb"][2])
        dist = (lab[0] - block_lab[0]) ** 2 + (lab[1] - block_lab[1]) ** 2 + (lab[2] - block_lab[2]) ** 2
        if dist < min_dist:
            min_dist = dist
            best = block

    return best


def find_nearest_block(r, g, b, palette):
    cache_key = f"{r},{g},{b}"
    if cache_key in color_cache:
        return color_cache[cache_key]

    h, s, v = rgb_to_hsv(r, g, b)
    best = None

    if s < 0.12:
        if v > 0.9:
            best = next((b_ for b_ in palette if b_["id"] == "white_concrete"), None)
        elif v > 0.7:
            best = next((b_ for b_ in palette if b_["id"] == "light_gray_concrete"), None)
        elif v > 0.4:
            best = next((b_ for b_ in palette if b_["id"] == "gray_concrete"), None)
        else:
            best = next((b_ for b_ in palette if b_["id"] == "black_concrete"), None)
        if not best:
            best = palette[0]
    else:
        best = _find_best_block(r, g, b, palette)

    color_cache[cache_key] = best
    return best


# ---- 调色板 ----

def load_block_palette():
    blocks_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blocks.json")
    if not os.path.exists(blocks_path):
        raise ValueError(f"方块调色板文件不存在: {blocks_path}")
    with open(blocks_path, "r", encoding="utf-8") as f:
        raw = f.read()
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("blocks"), list):
        raise ValueError("blocks.json 格式不正确，需要 { blocks: [...] }")
    palette = [
        b for b in data["blocks"]
        if isinstance(b, dict) and b.get("id") and isinstance(b.get("rgb"), list) and len(b["rgb"]) == 3
    ]
    return palette


# ---- 图片处理 ----

def ffmpeg_available():
    """检测系统中是否可执行 ffmpeg"""
    return shutil.which("ffmpeg") is not None


def process_image(file_path, max_dim=MAX_IMAGE_DIM):
    """处理图片:加载、限制尺寸、转换为方块网格"""
    # Pillow 原生支持 PNG/JPEG/WEBP 解码
    img = Image.open(file_path)
    fmt = (img.format or "").upper()
    if fmt not in ("PNG", "JPEG", "WEBP"):
        raise ValueError("不支持的图片格式 (需要 PNG/JPEG/WEBP)")

    img = img.convert("RGBA")
    width, height = img.size

    if max_dim and (width > max_dim or height > max_dim):
        ratio = min(max_dim / width, max_dim / height)
        new_width = max(1, round(width * ratio))
        new_height = max(1, round(height * ratio))
        img = img.resize((new_width, new_height), Image.BILINEAR)
        width, height = new_width, new_height

    # RGBA 像素数组
    data = img.tobytes()  # 每像素 4 字节 R G B A

    palette = load_block_palette()
    if len(palette) == 0:
        raise ValueError("方块调色板为空，请检查 blocks.json")

    grid = []
    non_transparent = 0
    for z in range(height):
        row = []
        for x in range(width):
            idx = (z * width + x) * 4
            r = data[idx]
            g = data[idx + 1]
            b = data[idx + 2]
            a = data[idx + 3]

            if a == 0:
                row.append(None)
            else:
                block = find_nearest_block(r, g, b, palette)
                row.append(block["id"])
                non_transparent += 1
        grid.append(row)

    blocks = []
    for z in range(height):
        for x in range(width):
            if grid[z][x]:
                blocks.append({"x": x, "z": z, "cmd": grid[z][x]})

    return {"width": width, "height": height, "grid": grid, "blocks": blocks, "nonTransparent": non_transparent}


# 矩形合并优化
def merge_blocks_to_rects(blocks, width, height):
    grid = [[None] * width for _ in range(height)]
    for b in blocks:
        grid[b["z"]][b["x"]] = b["cmd"]

    used = [[False] * width for _ in range(height)]
    rects = []

    for z in range(height):
        for x in range(width):
            if used[z][x] or not grid[z][x]:
                continue
            cmd = grid[z][x]

            max_x = x
            while max_x + 1 < width and grid[z][max_x + 1] == cmd and not used[z][max_x + 1]:
                max_x += 1

            max_z = z
            can_extend = True
            while can_extend and max_z + 1 < height:
                for tx in range(x, max_x + 1):
                    if grid[max_z + 1][tx] != cmd or used[max_z + 1][tx]:
                        can_extend = False
                        break
                if can_extend:
                    max_z += 1

            area = (max_x - x + 1) * (max_z - z + 1)
            if area <= FILL_LIMIT:
                for tz in range(z, max_z + 1):
                    for tx in range(x, max_x + 1):
                        used[tz][tx] = True
                if area == 1:
                    rects.append({"type": "setblock", "x": x, "z": z, "cmd": cmd, "count": 1})
                else:
                    rects.append({"type": "fill", "x1": x, "z1": z, "x2": max_x, "z2": max_z, "cmd": cmd, "count": area})
            else:
                h = max_z - z + 1
                stripe_w = max(1, FILL_LIMIT // h)
                sx = x
                while sx <= max_x:
                    ex = min(sx + stripe_w - 1, max_x)
                    stripe_area = (ex - sx + 1) * h
                    for tz in range(z, max_z + 1):
                        for tx in range(sx, ex + 1):
                            used[tz][tx] = True
                    if stripe_area == 1:
                        rects.append({"type": "setblock", "x": sx, "z": z, "cmd": cmd, "count": 1})
                    else:
                        rects.append({"type": "fill", "x1": sx, "z1": z, "x2": ex, "z2": max_z, "cmd": cmd, "count": stripe_area})
                    sx += stripe_w

    return rects


# Area Chunking
def compute_areas(origin, width, height, dir_):
    if dir_ == "y":
        start_chunk_a = origin["x"] // 16
        start_chunk_b = origin["y"] // 16
        end_chunk_a = (origin["x"] + width - 1) // 16
        end_chunk_b = (origin["y"] + height - 1) // 16
    elif dir_ == "z":
        start_chunk_a = origin["z"] // 16
        start_chunk_b = origin["x"] // 16
        end_chunk_a = (origin["z"] + width - 1) // 16
        end_chunk_b = (origin["x"] + height - 1) // 16
    else:  # "x"
        start_chunk_a = origin["x"] // 16
        start_chunk_b = origin["z"] // 16
        end_chunk_a = (origin["x"] + width - 1) // 16
        end_chunk_b = (origin["z"] + height - 1) // 16

    total_chunks_a = end_chunk_a - start_chunk_a + 1
    total_chunks_b = end_chunk_b - start_chunk_b + 1
    total_chunks = total_chunks_a * total_chunks_b

    areas = []
    if total_chunks <= MAX_CHUNKS:
        areas.append({"a1": start_chunk_a, "b1": start_chunk_b, "a2": end_chunk_a, "b2": end_chunk_b})
    elif total_chunks_b > MAX_CHUNKS:
        max_chunks_b = MAX_CHUNKS
        b = start_chunk_b
        while b <= end_chunk_b:
            b2 = min(b + max_chunks_b - 1, end_chunk_b)
            areas.append({"a1": start_chunk_a, "b1": b, "a2": end_chunk_a, "b2": b2})
            b += max_chunks_b
    else:
        max_chunks_a = max(1, MAX_CHUNKS // total_chunks_b)
        a = start_chunk_a
        while a <= end_chunk_a:
            a2 = min(a + max_chunks_a - 1, end_chunk_a)
            areas.append({"a1": a, "b1": start_chunk_b, "a2": a2, "b2": end_chunk_b})
            a += max_chunks_a

    return areas


class Mod:
    """图片像素画转换 Mod(客户端)"""

    def __init__(self, client):
        self.client = client
        self.pending = None
        self.job = None
        self.page = 1

    def onCommand(self):
        return {
            "op": [
                apply_config_aliases(
                    Command.create("image", "图片像素画命令（方法: create/raw/y/n/status/list/search）")
                    .add_string("方法", False)
                    .add_optional_string("参数1")
                    .add_optional_string("参数2")
                    .add_optional_string("参数3")
                    .add_optional_string("参数4")
                    .add_optional_string("参数5")
                    .set_func(self._cmd_image)
                ),
            ],
        }

    # ---- 命令分发器 ----

    IMAGE_METHODS = [
        ("create", "<文件> [x|y|z] [X] [Y] [Z]", "将图片转换为像素画"),
        ("raw", "<文件> [x|z] [X] [Y] [Z]", "将图片转换为像素画（原始尺寸，仅支持 x/z）"),
        ("y", "", "确认转换操作"),
        ("n", "", "取消/中断转换"),
        ("status", "", "查看转换进度"),
        ("list", "[页码]", "查看像素画文件列表"),
        ("search", "<关键词> [页码]", "搜索像素画文件"),
    ]

    async def _cmd_image(self, sender, method, p1=None, p2=None, p3=None, p4=None, p5=None):
        """$image 方法分发器"""
        if method is None:
            self.client.tell(f"§cImage | §fError > §i未知方法: 未指定（输入 {Command.command_prefix}image help 查看全部方法）", sender)
            return

        # help 显示本模组方法列表
        if method == "help":
            lines = "\n".join(
                f"§a{Command.command_prefix}image {mname}{' ' + margs if margs else ''} §7- §f{mdesc}"
                for mname, margs, mdesc, *_ in self.IMAGE_METHODS
            )
            self.client.tell(f"§eImage | §fHelp > §7可用方法\n{lines}", sender)
            return

        known = [m for m, _a, _d in self.IMAGE_METHODS]
        if method not in known:
            self.client.tell(f"§cImage | §fError > §i未知方法: {method}（输入 {Command.command_prefix}image help 查看全部方法）", sender)
            return

        # 方法内做权限检查(全部为 op)
        from lib.permission import PermissionManager
        perm = await PermissionManager.query(sender)
        if isinstance(perm, Exception):
            self.client.tell("§cImage | §fError > §i权限查询失败", sender)
            return
        if perm < 2:
            self.client.tell("§cImage | §fError > §i权限不足", sender)
            return

        # 分发到具体实现
        if method in ("create", "raw"):
            if p1 is None:
                self.client.tell(f"§cImage | §fError > §i参数不足：{Command.command_prefix}image {method} <文件> [方向] [X] [Y] [Z]", sender)
                return
            file_name = p1
            dir_value = p2 or "x"
            coords = []
            for v in (p3, p4, p5):
                if v is None:
                    coords.append(None)
                else:
                    try:
                        coords.append(float(v))
                    except ValueError:
                        self.client.tell(f'§cImage | §fError > §i"{v}" 处应为浮点型', sender)
                        return
            x, y, z = coords
            if method == "create":
                await self._cmd_create(sender, file_name, dir_value, x, y, z)
            else:
                await self._cmd_create_raw(sender, file_name, dir_value, x, y, z)

        elif method == "y":
            await self._cmd_confirm(sender)

        elif method == "n":
            await self._cmd_cancel(sender)

        elif method == "status":
            await self._cmd_status(sender)

        elif method == "list":
            page = None
            if p1 is not None:
                try:
                    page = int(p1)
                except ValueError:
                    self.client.tell(f'§cImage | §fError > §i"{p1}" 处应为整型', sender)
                    return
            await self._cmd_list(sender, page)

        elif method == "search":
            if p1 is None:
                self.client.tell(f"§cImage | §fError > §i参数不足：{Command.command_prefix}image search <关键词> [页码]", sender)
                return
            page = None
            if p2 is not None:
                try:
                    page = int(p2)
                except ValueError:
                    self.client.tell(f'§cImage | §fError > §i"{p2}" 处应为整型', sender)
                    return
            await self._cmd_search(sender, p1, page)

    # ---- 命令实现 ----

    async def _cmd_create(self, sender, file_name, dir_, x, y, z):
        if self.job:
            self.client.tell(f"§cImage | §fError > §i已有转换进程运行中，请等待完成或 {Command.command_prefix}image n 中断", sender)
            return
        await self.create(file_name, sender, dir_, x, y, z)

    async def _cmd_create_raw(self, sender, file_name, dir_, x, y, z):
        if self.job:
            self.client.tell(f"§cImage | §fError > §i已有转换进程运行中，请等待完成或 {Command.command_prefix}image n 中断", sender)
            return
        await self.create_raw(file_name, sender, dir_, x, y, z)

    async def _cmd_confirm(self, sender):
        if not self.pending:
            self.client.tell("§cImage | §fError > §i没有待确认的转换任务", sender)
            return
        self.client.tell("§eImage | §fConvert > §i已确认，开始转换…", sender)
        try:
            await self.run()
        except Exception as e:
            self.client.tell(f"§cImage | §fError > §i转换出错: {e}", sender)
            self.job = None

    async def _cmd_cancel(self, sender):
        if self.job:
            self.job["cancelled"] = True
            self.client.tell("§cImage | §fCancel > §i正在中断转换…", sender)
        elif self.pending:
            self.pending = None
            self.client.tell("§cImage | §fCancel > §i已取消转换", sender)
        else:
            self.client.tell("§cImage | §fError > §i没有进行中的操作", sender)

    async def _cmd_status(self, sender):
        if not self.job:
            self.client.tell("§cImage | §fError > §i没有进行中的转换任务", sender)
            return
        job = self.job
        elapsed = (time.time() * 1000 - job["startTime"]) / 1000
        total = job["total"]
        phase_placed = job["phasePlaced"]
        total_pct = f"{(phase_placed / total * 100):.1f}" if total > 0 else "0.0"
        cmd_speed = round(phase_placed / elapsed) if phase_placed > 0 and elapsed > 0 else 0
        total_eta = f"{(total - phase_placed) / cmd_speed:.1f}" if cmd_speed > 0 else "∞"
        phase_total = job["phaseTotal"]
        phase_pct = f"{(phase_placed / phase_total * 100):.1f}" if phase_total > 0 else "0.0"
        self.client.tellAll(
            f"§eImage | §fStatus > §i正在转换 {job['fileName']} | 总进度 {total_pct}% ({phase_placed}/{total} 命令)\n"
            f"§f阶段: {job['phase']} ({job['areaIndex']}/{job['areaTotal']} 区域)\n"
            f"§f当前区域: {phase_pct}% | {phase_placed} / {phase_total} 命令 | 方块 {job['phaseBlocksPlaced']} / {job['phaseBlockTotal']}\n"
            f"§f速度: {cmd_speed} 命令/s | {elapsed:.1f}s | 预计 {total_eta}s"
        )

    async def _cmd_list(self, sender, page):
        self.list_files(page, sender)

    async def _cmd_search(self, sender, keyword, page):
        self.search_files(keyword, page, sender)

    # ---- 文件列表 ----

    def format_size(self, size):
        """格式化文件大小(字节 → 可读单位)"""
        size = float(size or 0)
        if size >= 1024 * 1024:
            return f"{size / 1024 / 1024:.1f}MB"
        if size >= 1024:
            return f"{size / 1024:.1f}KB"
        return f"{int(size)}B"

    def show_files(self, sender, files, header):
        """分页展示文件列表(每页 5 个)"""
        if not files:
            self.client.tell("§cImage | §fError > §i没有找到图片文件", sender)
            return

        page_size = 5
        total_pages = math.ceil(len(files) / page_size)
        page = self.page or 1
        pn = max(1, min(page, total_pages))
        self.page = pn

        start_index = (pn - 1) * page_size
        page_files = files[start_index:start_index + page_size]

        items = []
        for i, f in enumerate(page_files):
            num = str(start_index + i + 1).rjust(2, " ")
            file_path = os.path.join(basePath["image"], f)
            size = "?"
            try:
                size = self.format_size(os.path.getsize(file_path))
            except Exception:
                pass
            items.append(f"{num}. {f} §f{size}")
        items_text = "\n".join(items)

        self.client.tell(f"{header} §f({pn}/{total_pages}页) §i共 {len(files)} 个\n{items_text}", sender)

    def list_files(self, page, sender):
        """列出所有像素画图片文件"""
        if page is not None:
            try:
                self.page = int(page) or 1
            except (ValueError, TypeError):
                self.page = 1
        else:
            self.page = 1
        dir_ = basePath["image"]
        files = sorted([
            f for f in os.listdir(dir_)
            if re.search(r"\.(png|jpg|jpeg|gif|bmp|webp|tiff)$", f, re.I)
        ]) if os.path.exists(dir_) else []
        self.show_files(sender, files, "§eImage | §fList")

    def search_files(self, keyword, page, sender):
        """搜索像素画图片文件"""
        if page is not None:
            try:
                self.page = int(page) or 1
            except (ValueError, TypeError):
                self.page = 1
        else:
            self.page = 1
        dir_ = basePath["image"]
        files = sorted([
            f for f in os.listdir(dir_)
            if re.search(r"\.(png|jpg|jpeg|gif|bmp|webp|tiff)$", f, re.I)
            and keyword.lower() in f.lower()
        ]) if os.path.exists(dir_) else []
        self.show_files(sender, files, f'§eImage | §fSearch > §i"{keyword}"')

    # ---- 创建流程 ----

    async def create(self, file_name, sender, dir_, x, y, z):
        await self._create("create", file_name, sender, dir_, x, y, z, MAX_IMAGE_DIM, ["x", "y", "z"])

    async def create_raw(self, file_name, sender, dir_, x, y, z):
        await self._create("raw", file_name, sender, dir_, x, y, z, None, ["x", "z"])

    async def _create(self, mode, file_name, sender, dir_, x, y, z, max_dim, allowed_dirs):
        dir_value = dir_ or "x"
        if dir_value not in allowed_dirs:
            self.client.tell(f"§cImage | §fError > §i该模式不支持方向 {dir_value}，支持: {'/'.join(allowed_dirs)}", sender)
            return

        coords = [x, y, z]
        coord_count = sum(1 for v in coords if v is not None)

        if coord_count > 0 and coord_count < 3:
            self.client.tell("§cImage | §fError > §i坐标参数不完整，需要同时提供 X Y Z 或都不提供（使用自身坐标）", sender)
            return

        # 路径穿越防护:只允许单层合法文件名
        if (not isinstance(file_name, str) or not file_name
                or file_name != os.path.basename(file_name)
                or re_search_sep(file_name) or file_name.startswith(".")):
            self.client.tell(f"§cImage | §fError > §i非法的文件名: {file_name}", sender)
            return

        file_path = os.path.join(basePath["image"], file_name)
        if not os.path.exists(file_path):
            self.client.tell(f"§cImage | §fError > §i文件不存在: {file_name}", sender)
            return

        self.client.tell("§i正在处理图片…", sender)

        try:
            data = process_image(file_path, max_dim)
        except Exception as e:
            self.client.tell(f"§cImage | §fError > §i图片处理失败: {e}", sender)
            return

        if mode == "raw":
            max_side = max(data["width"], data["height"])
            if max_side > 2048:
                self.client.tell(f"§cImage | §fError > §i图片太大: {data['width']}×{data['height']} (raw 模式最大 2048px)", sender)
                return

        if coord_count == 3:
            origin = {"x": math.floor(x), "y": math.floor(y), "z": math.floor(z)}
        else:
            try:
                pos = await self.client.getPosition("@s")
                if not pos:
                    self.client.tell("§cImage | §fError > §i无法获取你的坐标", sender)
                    return
                origin = {"x": math.floor(pos["x"]), "y": math.floor(pos["y"]), "z": math.floor(pos["z"])}
            except Exception:
                self.client.tell("§cImage | §fError > §i无法获取你的坐标", sender)
                return

        if origin["y"] < -64 or origin["y"] > 320:
            self.client.tell(f"§cImage | §fError > §iY 轴超出限制: {origin['y']} (允许 -64 ~ 320)", sender)
            return

        width = data["width"]
        height = data["height"]

        if dir_value == "y":
            max_y = origin["y"] + height - 1
            if max_y > 320:
                self.client.tell(f"§cImage | §fError > §iY 轴超出限制: {origin['y']} + {height - 1} = {max_y} (允许最大 320)", sender)
                return

        if dir_value == "y":
            min_x, min_y, min_z = origin["x"], origin["y"], origin["z"]
            max_x, max_y, max_z = origin["x"] + width - 1, origin["y"] + height - 1, origin["z"]
        elif dir_value == "z":
            min_x, min_y, min_z = origin["x"], origin["y"], origin["z"]
            max_x, max_y, max_z = origin["x"] + height - 1, origin["y"], origin["z"] + width - 1
        else:  # "x"
            min_x, min_y, min_z = origin["x"], origin["y"], origin["z"]
            max_x, max_y, max_z = origin["x"] + width - 1, origin["y"], origin["z"] + height - 1

        est_time = f"{data['nonTransparent'] * 0.001:.1f}"

        preview_rects = merge_blocks_to_rects(data["blocks"], width, height)
        preview_areas = compute_areas(origin, width, height, dir_value)

        self.pending = {"fileName": file_name, "origin": origin, "data": data, "dir": dir_value, "mode": mode}

        self.client.tellAll(
            f"§eImage | §fPreview > §i文件: {file_name} | 尺寸: {width}×{height} = {width * height} 像素\n"
            f"§f非透明像素: {data['nonTransparent']} → {len(preview_rects)} 条指令\n"
            f"§f方向: {dir_value} | 区块: {len(preview_areas)} 个区域\n"
            f"§f范围: ({min_x}, {min_y}, {min_z}) → ({max_x}, {max_y}, {max_z})\n"
            f"§f预计耗时: {est_time}s\n"
            f"§f确认请发送 §e{Command.command_prefix}image y§f，取消请发送 §c{Command.command_prefix}image n"
        )

    # ---- 执行转换 ----

    async def run(self):
        task = self.pending
        self.pending = None

        data = task["data"]
        origin = task["origin"]
        file_name = task["fileName"]
        dir_ = task["dir"]
        blocks = data["blocks"]
        width = data["width"]
        height = data["height"]

        rects = merge_blocks_to_rects(blocks, width, height)
        total_cmds = len(rects)

        areas = compute_areas(origin, width, height, dir_)

        self.job = {
            "fileName": file_name,
            "total": total_cmds,
            "cancelled": False,
            "startTime": time.time() * 1000,
            "blockTotal": data["nonTransparent"],
            "phase": "准备",
            "areaIndex": 0,
            "areaTotal": len(areas),
            "phasePlaced": 0,
            "phaseTotal": 0,
            "phaseBlocksPlaced": 0,
            "phaseBlockTotal": 0,
        }

        for i, area in enumerate(areas):
            if self.job["cancelled"]:
                break

            self.job["areaIndex"] = i + 1

            if dir_ == "x":
                abs_x1 = area["a1"] * 16
                abs_z1 = area["b1"] * 16
                abs_x2 = (area["a2"] + 1) * 16 - 1
                abs_z2 = (area["b2"] + 1) * 16 - 1
            elif dir_ == "z":
                abs_x1 = area["b1"] * 16
                abs_z1 = area["a1"] * 16
                abs_x2 = (area["b2"] + 1) * 16 - 1
                abs_z2 = (area["a2"] + 1) * 16 - 1
            else:  # "y"
                abs_x1 = area["a1"] * 16
                abs_z1 = origin["z"]
                abs_x2 = (area["a2"] + 1) * 16 - 1
                abs_z2 = origin["z"]

            abs_y1 = area["b1"] * 16 if dir_ == "y" else origin["y"]
            abs_y2 = (area["b2"] + 1) * 16 - 1 if dir_ == "y" else origin["y"]

            tick_name = f"img_{i}"
            self.job["phase"] = "创建常加载区块"
            self.job["phasePlaced"] = 0
            self.job["phaseTotal"] = 1
            self.job["phaseBlocksPlaced"] = 0
            self.job["phaseBlockTotal"] = 0

            try:
                await self.client.runCommand(f"/tickingarea add {abs_x1} {abs_y1} {abs_z1} {abs_x2} {abs_y2} {abs_z2} {tick_name}")
            except Exception:
                pass

            chunk_rects = []
            for r in rects:
                if r["type"] == "setblock":
                    if dir_ == "x":
                        rx1 = origin["x"] + r["x"]
                        rz1 = origin["z"] + r["z"]
                        ry1 = origin["y"]
                    elif dir_ == "z":
                        rx1 = origin["x"] + r["z"]
                        rz1 = origin["z"] + r["x"]
                        ry1 = origin["y"]
                    else:  # "y"
                        rx1 = origin["x"] + r["x"]
                        rz1 = origin["z"]
                        ry1 = origin["y"] + (height - 1 - r["z"])
                    if abs_x1 <= rx1 <= abs_x2 and abs_y1 <= ry1 <= abs_y2 and abs_z1 <= rz1 <= abs_z2:
                        chunk_rects.append({"r": r, "cx1": rx1, "cy1": ry1, "cz1": rz1, "cx2": rx1, "cy2": ry1, "cz2": rz1})
                else:
                    if dir_ == "x":
                        rx1 = origin["x"] + r["x1"]
                        rx2 = origin["x"] + r["x2"]
                        rz1 = origin["z"] + r["z1"]
                        rz2 = origin["z"] + r["z2"]
                        ry1 = origin["y"]
                        ry2 = ry1
                    elif dir_ == "z":
                        rx1 = origin["x"] + r["z1"]
                        rx2 = origin["x"] + r["z2"]
                        rz1 = origin["z"] + r["x1"]
                        rz2 = origin["z"] + r["x2"]
                        ry1 = origin["y"]
                        ry2 = ry1
                    else:  # "y"
                        rx1 = origin["x"] + r["x1"]
                        rx2 = origin["x"] + r["x2"]
                        rz1 = origin["z"]
                        rz2 = rz1
                        ry1 = origin["y"] + (height - 1 - r["z2"])
                        ry2 = origin["y"] + (height - 1 - r["z1"])
                    if rx2 >= abs_x1 and rx1 <= abs_x2 and ry2 >= abs_y1 and ry1 <= abs_y2 and rz2 >= abs_z1 and rz1 <= abs_z2:
                        cx1 = max(rx1, abs_x1)
                        cy1 = max(ry1, abs_y1)
                        cz1 = max(rz1, abs_z1)
                        cx2 = min(rx2, abs_x2)
                        cy2 = min(ry2, abs_y2)
                        cz2 = min(rz2, abs_z2)
                        clipped_count = (cx2 - cx1 + 1) * (cy2 - cy1 + 1) * (cz2 - cz1 + 1)
                        chunk_rects.append({"r": r, "cx1": cx1, "cy1": cy1, "cz1": cz1, "cx2": cx2, "cy2": cy2, "cz2": cz2, "clippedCount": clipped_count})

            self.job["phase"] = "放置方块"
            self.job["phaseTotal"] = len(chunk_rects)
            self.job["phasePlaced"] = 0
            self.job["phaseBlocksPlaced"] = 0
            self.job["phaseBlockTotal"] = sum(cr.get("clippedCount") or 1 for cr in chunk_rects)

            for cr in chunk_rects:
                if self.job["cancelled"]:
                    break

                r = cr["r"]

                if r["type"] == "setblock":
                    await self.client.sendCommand(f"/setblock {cr['cx1']} {cr['cy1']} {cr['cz1']} {r['cmd']}")
                else:
                    await self.client.sendCommand(f"/fill {cr['cx1']} {cr['cy1']} {cr['cz1']} {cr['cx2']} {cr['cy2']} {cr['cz2']} {r['cmd']}")

                self.job["phasePlaced"] += 1
                self.job["phaseBlocksPlaced"] += cr.get("clippedCount") or 1

                await asyncio.sleep(0.001)

            await asyncio.sleep(1.0)

            self.job["phase"] = "删除常加载区块"
            self.job["phasePlaced"] = 0
            self.job["phaseTotal"] = 1
            self.job["phaseBlocksPlaced"] = 0
            self.job["phaseBlockTotal"] = 0
            try:
                await self.client.runCommand(f"/tickingarea remove {tick_name}")
            except Exception:
                pass

            await asyncio.sleep(1.0)

        if not self.job["cancelled"]:
            elapsed = (time.time() * 1000 - self.job["startTime"]) / 1000
            speed = round(data["nonTransparent"] / elapsed) if elapsed > 0 else 0
            self.client.tellAll(
                f"§eImage | §fConvert > §i{file_name} 转换完成 共 {data['nonTransparent']} 方块 耗时 {elapsed:.1f}s 速度 {speed}方块/s"
            )
        else:
            self.client.tellAll(f"§cImage | §fCancel > §i图片转换已中断 ({file_name})")
        self.job = None

    def onDestroy(self):
        if self.job:
            self.job["cancelled"] = True
        self.pending = None
        self.job = None
        self.client = None


def re_search_sep(file_name):
    """检测文件名是否含路径分隔符"""
    import re
    return re.search(r"[\\/]", file_name) is not None
