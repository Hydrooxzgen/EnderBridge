"""Litematic 建筑投影导入 Mod

解析 .litematic 文件(NBT 格式),导入为 MCBE 世界中的建筑;
支持预览、世界差异检查、修复、导出 .mcstructure 结构文件。
"""
import asyncio
import json
import math
import os
import re
import struct
import time
import zlib

from config import basePath, resolvePath
from lib.command import Command

# ---- NBT 标签类型常量 ----
TAG_END = 0
TAG_BYTE = 1
TAG_SHORT = 2
TAG_INT = 3
TAG_LONG = 4
TAG_FLOAT = 5
TAG_DOUBLE = 6
TAG_BYTE_ARRAY = 7
TAG_STRING = 8
TAG_LIST = 9
TAG_COMPOUND = 10
TAG_INT_ARRAY = 11
TAG_LONG_ARRAY = 12

# INT_MASKS 用于位操作
INT_MASKS = [(1 << i) - 1 for i in range(33)]
INT_MASKS[32] = 0xFFFFFFFF


# ---- NBT 解析 ----

def parse_nbt(buf):
    """解析 big-endian NBT 数据(Java 版),返回根 compound dict"""
    offset = 0

    def read_string():
        nonlocal offset
        length = struct.unpack(">H", buf[offset:offset + 2])[0]
        offset += 2
        s = buf[offset:offset + length].decode("utf-8", errors="replace")
        offset += length
        return s

    def read_tag(type_):
        nonlocal offset
        if type_ == TAG_BYTE:
            v = struct.unpack(">b", buf[offset:offset + 1])[0]
            offset += 1
            return v
        elif type_ == TAG_SHORT:
            v = struct.unpack(">h", buf[offset:offset + 2])[0]
            offset += 2
            return v
        elif type_ == TAG_INT:
            v = struct.unpack(">i", buf[offset:offset + 4])[0]
            offset += 4
            return v
        elif type_ == TAG_LONG:
            hi = struct.unpack(">i", buf[offset:offset + 4])[0]
            lo = struct.unpack(">I", buf[offset + 4:offset + 8])[0]
            offset += 8
            return hi * 4294967296 + lo
        elif type_ == TAG_FLOAT:
            v = struct.unpack(">f", buf[offset:offset + 4])[0]
            offset += 4
            return v
        elif type_ == TAG_DOUBLE:
            v = struct.unpack(">d", buf[offset:offset + 8])[0]
            offset += 8
            return v
        elif type_ == TAG_BYTE_ARRAY:
            length = struct.unpack(">i", buf[offset:offset + 4])[0]
            offset += 4 + length
            return []
        elif type_ == TAG_STRING:
            return read_string()
        elif type_ == TAG_LIST:
            list_type = buf[offset]
            offset += 1
            length = struct.unpack(">i", buf[offset:offset + 4])[0]
            offset += 4
            lst = []
            for _ in range(length):
                lst.append(read_tag(list_type))
            return lst
        elif type_ == TAG_COMPOUND:
            comp = {}
            while offset < len(buf):
                tag_type = buf[offset]
                offset += 1
                if tag_type == TAG_END:
                    break
                key = read_string()
                comp[key] = read_tag(tag_type)
            return comp
        elif type_ == TAG_INT_ARRAY:
            length = struct.unpack(">i", buf[offset:offset + 4])[0]
            offset += 4 + length * 4
            return []
        elif type_ == TAG_LONG_ARRAY:
            length = struct.unpack(">i", buf[offset:offset + 4])[0]
            data_start = offset + 4
            offset += 4 + length * 8
            return {"isZeroCopyLongArray": True, "buffer": buf, "offset": data_start, "length": length}
        else:
            raise ValueError(f"未知的 NBT 标签类型: {type_}")

    root_type = buf[offset]
    offset += 1
    if root_type == TAG_END:
        return {}
    read_string()
    return read_tag(root_type)


def decompress_and_parse(file_buffer):
    """解压 gzip 并解析 NBT"""
    unzipped = zlib.decompress(file_buffer, 16 + zlib.MAX_WBITS)
    return parse_nbt(unzipped)


# 从 BlockStates 提取方块索引
def extract_block_indices(block_states, total_blocks, bits_per_index):
    indices = [0] * total_blocks
    length = block_states["length"]
    buf = block_states["buffer"]
    offset = block_states["offset"]
    words = [0] * (length * 2)
    for i in range(length):
        ptr = offset + i * 8
        hi, lo = struct.unpack(">II", buf[ptr:ptr + 8])
        words[i * 2 + 1] = hi
        words[i * 2] = lo
    bit_pos = 0
    for i in range(total_blocks):
        word_idx = bit_pos >> 5
        bit_offset = bit_pos & 31
        bits_first = min(bits_per_index, 32 - bit_offset)
        value = (words[word_idx] >> bit_offset) & INT_MASKS[bits_first]
        remaining = bits_per_index - bits_first
        if remaining > 0:
            value |= ((words[word_idx + 1] if word_idx + 1 < len(words) else 0) & INT_MASKS[remaining]) << bits_first
        indices[i] = value
        bit_pos += bits_per_index
    return indices


# 加载 Java -> Bedrock 映射
def load_mappings():
    mapping_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generator_blocks.json")

    try:
        with open(mapping_file, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        raise ValueError(f"读取映射表失败: {e}")

    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("mappings"), list):
        raise ValueError("映射表格式不正确")

    mapping = {}
    fallback_map = {}

    for entry in data["mappings"]:
        java = entry.get("java_state")
        if not java or not java.get("Name"):
            continue
        props = java.get("Properties") or {}
        sorted_props = ",".join(f"{k}={props[k]}" for k in sorted(props.keys()))
        key = f"{java['Name']}::{sorted_props}"
        bedrock = entry.get("bedrock_state")
        if not bedrock:
            continue

        identifier = bedrock.get("bedrock_identifier") or java["Name"]
        state = dict(bedrock.get("state") or {})

        mapping[key] = {"identifier": identifier, "state": state}

        if java["Name"] not in fallback_map:
            fallback_map[java["Name"]] = {"identifier": identifier, "state": dict(state)}

    HARDCODED = {
        "minecraft:chain": {"identifier": "chain", "state": {}},
        "minecraft:grass": {"identifier": "grass_block", "state": {}},
    }
    for name, info in HARDCODED.items():
        if name not in fallback_map:
            fallback_map[name] = info

    mapping["fallbackMap"] = fallback_map
    return mapping


# 格式化 Bedrock 方块属性
def format_block_state(state):
    if not state:
        return ""
    pairs = []
    for k in sorted(state.keys()):
        v = state[k]
        if k.endswith("_bit"):
            val = "true" if v else "false"
        elif isinstance(v, str):
            val = f'"{v}"'
        else:
            val = v
        pairs.append(f'"{k}"={val}')
    return "[" + ",".join(pairs) + "]"


# 解析 Litematic 文件
async def parse_litematic(file_path):
    """解析 Litematic 文件

    返回 {sx, sy, sz, totalCoords, blocks, minY, maxY, unmappedBlocks, unmappedSummary}
      blocks: [{x, y, z, identifier, state, cmd}] 其中 cmd 为可直接执行的基岩版命令片段
      minY/maxY: 非空气方块的实际 Y 范围(用于裁剪底部空气层)
      unmappedBlocks/Summary: 无法映射到基岩版的方块
    """
    with open(file_path, "rb") as f:
        file_buffer = f.read()
    nbt = decompress_and_parse(file_buffer)

    regions = nbt.get("Regions")
    if not regions:
        raise ValueError("找不到 Regions 区域")

    r_name = next(iter(regions.keys()))
    region = regions[r_name]
    size = region["Size"]

    sx = abs(size["x"])
    sy = abs(size["y"])
    sz = abs(size["z"])
    total_blocks = sx * sy * sz

    palette_raw = region.get("BlockStatePalette")
    if isinstance(palette_raw, list):
        palette = palette_raw
    else:
        palette = palette_raw.get("value") or palette_raw
    block_states = region.get("BlockStates")

    if not palette or not block_states:
        raise ValueError("无效的 Litematic 文件")

    mapping = load_mappings()

    # 预处理 palette
    AIR_NAMES = ["minecraft:air", "minecraft:cave_air", "minecraft:void_air"]
    processed_palette = []
    for node in palette:
        state = node.get("value") if isinstance(node, dict) and "value" in node else node
        if not state or not state.get("Name"):
            processed_palette.append(None)
            continue

        b_name = state["Name"] if isinstance(state["Name"], str) else state["Name"]["value"]
        if b_name in AIR_NAMES:
            processed_palette.append(None)
            continue

        props = {}
        p = state.get("Properties")
        if p:
            if isinstance(p, dict) and "value" in p:
                p = p["value"]
            for k, v in (p or {}).items():
                if isinstance(v, dict) and "value" in v:
                    props[k] = v["value"]
                elif isinstance(v, str):
                    props[k] = v

        sorted_props = ",".join(f"{k}={props[k]}" for k in sorted(props.keys()))
        java_key = f"{b_name}::{sorted_props}"

        bedrock_info = mapping.get(java_key)
        if not bedrock_info and mapping.get("fallbackMap"):
            bedrock_info = mapping["fallbackMap"].get(b_name)

        if not bedrock_info:
            processed_palette.append({"unmapped": True, "name": b_name})
            continue

        processed_palette.append({
            "identifier": bedrock_info["identifier"],
            "state": bedrock_info["state"],
        })

    bits_per_index = max(2, math.ceil(math.log2(len(palette))))
    indices = extract_block_indices(block_states, total_blocks, bits_per_index)

    blocks = []
    unmapped_blocks = []
    unmapped_summary = {}
    slice_size = sx * sz
    idx = 0
    min_y = float("inf")
    max_y = float("-inf")

    for y in range(sy):
        for z in range(sz):
            for x in range(sx):
                p_idx = indices[idx]
                idx += 1
                cached = processed_palette[p_idx] if p_idx < len(processed_palette) else None

                if cached and cached.get("unmapped"):
                    unmapped_blocks.append({"x": x, "y": y, "z": z, "name": cached["name"]})
                    unmapped_summary[cached["name"]] = unmapped_summary.get(cached["name"], 0) + 1
                    continue

                if cached:
                    if y < min_y:
                        min_y = y
                    if y > max_y:
                        max_y = y
                    state = cached.get("state") or {}
                    state_str = format_block_state(state)
                    identifier = cached["identifier"]
                    block_id = re.sub(r"^minecraft:", "", identifier)
                    blocks.append({
                        "x": x, "y": y, "z": z,
                        "identifier": identifier,
                        "state": state,
                        "cmd": f"{block_id}{' ' + state_str if state_str else ''}",
                    })
                # p_idx === 0 或 cached === None 表示空气

    return {
        "sx": sx, "sy": sy, "sz": sz,
        "totalCoords": total_blocks,
        "blocks": blocks,
        "minY": 0 if min_y == float("inf") else min_y,
        "maxY": sy - 1 if max_y == float("-inf") else max_y,
        "unmappedBlocks": unmapped_blocks,
        "unmappedSummary": unmapped_summary,
    }


# 裁剪底部空气层:将建筑最低的非空气方块对齐到 Y=0(对应放置点地面)
def trim_air(data):
    off = data["minY"]
    data["trimmedAir"] = off
    if off > 0:
        for b in data["blocks"]:
            b["y"] -= off
        for b in data.get("unmappedBlocks") or []:
            b["y"] -= off
        data["sy"] = data["maxY"] - off + 1
        data["totalCoords"] = data["sx"] * data["sy"] * data["sz"]
    return data


# ---- .mcstructure 生成 (Little-endian NBT, 未压缩) ----
T_BYTE = 1
T_INT = 3
T_STRING = 8
T_LIST = 9
T_COMPOUND = 10


def nt(t, v):
    return (t, v)


def n_byte(v):
    return nt(T_BYTE, v)


def n_int(v):
    return nt(T_INT, v)


def n_str(v):
    return nt(T_STRING, v)


def n_list(elem_type, v):
    return nt(T_LIST, (elem_type, v))


def n_comp(v):
    return nt(T_COMPOUND, v)


def le_string(s):
    b = s.encode("utf-8")
    return struct.pack("<H", len(b)) + b


def nbt_payload(n):
    t, v = n
    if t == T_BYTE:
        return bytes([v & 0xFF])
    if t == T_INT:
        return struct.pack("<i", v)
    if t == T_STRING:
        return le_string(v)
    if t == T_LIST:
        elem_type, items = v
        parts = [nbt_payload(item) for item in items]
        return struct.pack("<Bi", elem_type, len(items)) + b"".join(parts)
    if t == T_COMPOUND:
        parts = []
        for k, child in v.items():
            parts.append(bytes([child[0]]))
            parts.append(le_string(k))
            parts.append(nbt_payload(child))
        parts.append(b"\x00")
        return b"".join(parts)
    raise ValueError(f"不支持的 NBT 类型: {t}")


def nbt_root(name, node):
    return bytes([node[0]]) + le_string(name) + nbt_payload(node)


def to_state(v):
    if isinstance(v, bool):
        return n_byte(1 if v else 0)
    if isinstance(v, (int, float)):
        return n_int(int(v))
    return n_str(str(v))


# 构建 .mcstructure 文件内容(block_indices 按 ZYX 顺序,z 变化最快;-1 表示留空)
def build_mc_structure(data):
    sx, sy, sz = data["sx"], data["sy"], data["sz"]
    palette = []
    index_map = {}
    for b in data["blocks"]:
        if b["cmd"] not in index_map:
            index_map[b["cmd"]] = len(palette)
            palette.append(b)
    total = sx * sy * sz
    base = [-1] * total
    overlay = [-1] * total
    for b in data["blocks"]:
        base[(b["x"] * sy + b["y"]) * sz + b["z"]] = index_map[b["cmd"]]

    block_palette = []
    for p in palette:
        states = {}
        for k, v in (p.get("state") or {}).items():
            states[k] = to_state(v)
        block_palette.append(n_comp({
            "name": n_str(p["identifier"]),
            "states": n_comp(states),
            "version": n_int(18168865),
        }))

    root = n_comp({
        "format_version": n_int(1),
        "size": n_list(T_INT, [n_int(sx), n_int(sy), n_int(sz)]),
        "structure": n_comp({
            "block_indices": n_list(T_LIST, [
                n_list(T_INT, [n_int(v) for v in base]),
                n_list(T_INT, [n_int(v) for v in overlay]),
            ]),
            "entities": n_list(T_COMPOUND, []),
            "palette": n_comp({
                "default": n_comp({
                    "block_palette": n_list(T_COMPOUND, block_palette),
                    "block_position_data": n_comp({}),
                })
            }),
        }),
        "structure_world_origin": n_list(T_INT, [n_int(0), n_int(0), n_int(0)]),
    })
    return nbt_root("", root)


# 矩形合并优化
def merge_blocks_to_rects(blocks, sx, sz):
    layers = {}
    for b in blocks:
        layers.setdefault(b["y"], []).append(b)

    cmds = []

    for y in sorted(layers.keys()):
        grid = [[None] * sx for _ in range(sz)]
        for b in layers[y]:
            grid[b["z"]][b["x"]] = b["cmd"]

        used = [[False] * sx for _ in range(sz)]

        for z in range(sz):
            for x in range(sx):
                if used[z][x] or not grid[z][x]:
                    continue
                cmd = grid[z][x]

                max_x = x
                while max_x + 1 < sx and grid[z][max_x + 1] == cmd and not used[z][max_x + 1]:
                    max_x += 1

                max_z = z
                can_extend = True
                while can_extend and max_z + 1 < sz:
                    for tx in range(x, max_x + 1):
                        if grid[max_z + 1][tx] != cmd or used[max_z + 1][tx]:
                            can_extend = False
                            break
                    if can_extend:
                        max_z += 1

                for tz in range(z, max_z + 1):
                    for tx in range(x, max_x + 1):
                        used[tz][tx] = True

                area = (max_x - x + 1) * (max_z - z + 1)
                if area == 1:
                    cmds.append({"type": "setblock", "x": x, "y": y, "z": z, "cmd": cmd, "count": 1})
                else:
                    cmds.append({"type": "fill", "x1": x, "y": y, "z1": z, "x2": max_x, "z2": max_z, "cmd": cmd, "count": area})

    return cmds


class Mod:
    """Litematic 建筑投影导入 Mod(客户端)"""

    # 任务存档为静态共享:连接/实例共用同一份,$create 返回的任务 ID 全局有效
    task_seq = 0
    tasks = {}

    def __init__(self, client):
        self.client = client
        self.pending = None
        self.job = None
        self.page = 1
        self.preview_timer = None
        self.preview_data = None
        self.verify_job = None
        self.fix_job = None

    def onCommand(self):
        c = self.client
        return {
            "op": [
                # l:help [命令名] — 列出所有命令,或查看指定命令的用法
                Command.create("l:help", "查看命令用法")
                .add_optional_string("命令名")
                .set_func(self._cmd_help),

                # l:create <文件> [X] [Y] [Z] [trim|raw] — 导入建筑投影
                Command.create("l:create", "导入 Litematic 建筑投影")
                .add_string("文件名", False)
                .add_optional_string("X")
                .add_optional_string("Y")
                .add_optional_string("Z")
                .add_optional_string("模式")
                .set_func(self._cmd_create),

                # l:preview <文件> [X] [Y] [Z] [trim|raw] — 粒子+实体边框预览
                Command.create("l:preview", "粒子边框 + 实体标记预览建筑位置")
                .add_string("文件名", False)
                .add_optional_string("X")
                .add_optional_string("Y")
                .add_optional_string("Z")
                .add_optional_string("模式")
                .set_func(self._cmd_preview),

                # l:unpreview — 清除预览
                Command.create("l:unpreview", "清除建筑预览")
                .set_func(self._cmd_unpreview),

                # l:export <文件> [导出名] [trim|raw] — 导出 .mcstructure 结构文件
                Command.create("l:export", "导出为 MCBE 结构方块文件 (.mcstructure)")
                .add_string("文件名", False)
                .add_optional_string("导出名")
                .add_optional_string("模式")
                .set_func(self._cmd_export),

                # l:list [页码] — 浏览建筑文件
                Command.create("l:list", "查看建筑文件列表")
                .add_optional_string("页码")
                .set_func(self._cmd_list),

                # l:id — 查看所有任务 ID
                Command.create("l:id", "查看所有任务 ID")
                .set_func(self._cmd_id),

                # l:search <关键词> [页码] — 搜索建筑文件
                Command.create("l:search", "搜索建筑文件")
                .add_string("关键词", False)
                .add_optional_string("页码")
                .set_func(self._cmd_search),

                # l:y — 确认待执行的导入
                Command.create("l:y", "确认导入操作")
                .set_func(self._cmd_confirm),

                # l:n — 取消待确认任务或中断正在进行的导入/检查/修复
                Command.create("l:n", "取消/中断操作")
                .set_func(self._cmd_cancel),

                # l:author — 作者信息
                Command.create("l:author", "查看作者信息")
                .set_func(self._cmd_author),

                # l:status — 查看所有进行中任务进度
                Command.create("l:status", "查看导入/检查/修复进度")
                .set_func(self._cmd_status),

                # l:verify <ID> [map|world] — 默认检查游戏世界一致性;map 检查方块映射错误
                Command.create("l:verify", "检查投影与世界的差异 / 方块映射错误")
                .add_string("ID", False)
                .add_optional_string("模式")
                .set_func(self._cmd_verify),

                # l:fix <ID> [替代方块] — 修复错误方块
                Command.create("l:fix", "修复被挖掉的方块 / 替换无法映射的方块")
                .add_string("ID", False)
                .add_optional_string("替代方块")
                .set_func(self._cmd_fix),
            ],
        }

    # ---- 命令实现 ----

    async def _cmd_help(self, sender, name):
        all_cmds = self.onCommand()["op"]
        if name:
            cm = next((x for x in all_cmds if x.name == name), None)
            if not cm:
                self.client.tell(f"§cLitematic | §fError > §i没有找到命令: {name}（输入 !l:help 查看全部命令）", sender)
                return
            if cm.parameters:
                params = []
                for i, p in enumerate(cm.parameters):
                    ptype, desc, opt = p
                    params.append(f" §f参数{i + 1}: §7<{ptype}> §f({'可选' if opt else '必选'}){f' - {desc}' if desc else ''}")
                param_text = "\n".join(params)
            else:
                param_text = " §7无参数"
            self.client.tell(
                f"§eLitematic | §fHelp > §b{cm.name} §7用法:\n"
                f"§f说明: §7{cm.description}\n"
                f"§f参数:\n{param_text}", sender
            )
        else:
            lines = "\n".join(f"§a$l:{cm.name.replace('l:', '', 1)} §7- §f{cm.description}" for cm in all_cmds)
            self.client.tell(
                f"§eLitematic | §fHelp > §7可用命令\n{lines}\n"
                f"§7输入 §a!l:help <命令名> §7查看详细用法", sender
            )

    async def _cmd_create(self, sender, file_name, x, y, z, mode):
        if self.job:
            self.client.tell("§cLitematic | §fError > §i已有导入进程运行中，请等待完成或 !l:n 中断", sender)
            return
        await self.create(file_name, sender, x, y, z, mode)

    async def _cmd_preview(self, sender, file_name, x, y, z, mode):
        await self.preview(file_name, sender, x, y, z, mode)

    async def _cmd_unpreview(self, sender):
        await self.clear_preview(sender)

    async def _cmd_export(self, sender, file_name, export_name, mode):
        await self.export_structure(file_name, sender, export_name, mode)

    async def _cmd_list(self, sender, page):
        self.list_files(page, sender)

    async def _cmd_id(self, sender):
        self.list_tasks(sender)

    async def _cmd_search(self, sender, keyword, page):
        self.search_files(keyword, page, sender)

    async def _cmd_confirm(self, sender):
        if not self.pending:
            self.client.tell("§cLitematic | §fError > §i没有待确认的导入任务", sender)
            return
        self.client.tell("§eLitematic | §fImport > §i已确认，开始导入…", sender)
        try:
            await self.run()
        except Exception as e:
            self.client.tell(f"§cLitematic | §fError > §i导入出错: {e}", sender)
            self.job = None

    async def _cmd_cancel(self, sender):
        if self.job:
            self.job["cancelled"] = True
            self.client.tell("§cLitematic | §fCancel > §i正在中断导入…", sender)
        elif self.verify_job:
            self.verify_job["cancelled"] = True
            self.client.tell("§cLitematic | §fCancel > §i正在中断世界检查…", sender)
        elif self.fix_job:
            self.fix_job["cancelled"] = True
            self.client.tell("§cLitematic | §fCancel > §i正在中断修复…", sender)
        elif self.pending:
            self.pending = None
            self.client.tell("§cLitematic | §fCancel > §i已取消导入", sender)
        else:
            self.client.tell("§cLitematic | §fError > §i没有进行中的操作", sender)

    async def _cmd_author(self, sender):
        self.client.tell("§eLitematic | §fAuthor > §iStarAwA117 & Hydrooxygen", sender)

    async def _cmd_status(self, sender):
        lines = []
        if self.job:
            j = self.job
            elapsed = (time.time() * 1000 - j["startTime"]) / 1000
            cmd_speed = round(j["phasePlaced"] / elapsed) if j["phasePlaced"] > 0 and elapsed > 0 else 0
            total_pct = f"{(j['phasePlaced'] / j['total'] * 100):.1f}" if j["total"] > 0 else "0.0"
            phase_pct = f"{(j['phasePlaced'] / j['phaseTotal'] * 100):.1f}" if j["phaseTotal"] > 0 else "0.0"
            eta = f"{((j['total'] - j['phasePlaced']) / cmd_speed):.1f}" if cmd_speed > 0 else "?"
            lines.append(
                f"§eLitematic | §fStatus > §i导入 §f{j['fileName']}\n"
                f"§f总进度 {total_pct}% | 预计 {eta}s\n"
                f"§f阶段: {j['phase']} ({j['areaIndex']}/{j['areaTotal']} 区域)\n"
                f"§f进度: {phase_pct}% | {j['phasePlaced']} / {j['phaseTotal']} 命令 | 方块 {j['phaseBlocksPlaced']} / {j['phaseBlockTotal']}\n"
                f"§f速度: {cmd_speed} 命令/s | {elapsed:.1f}s"
            )
        if self.verify_job:
            v = self.verify_job
            elapsed = (time.time() * 1000 - v["startTime"]) / 1000
            lines.append(
                f"§eLitematic | §fStatus > §i世界检查 §f(任务 #{v['taskId']}: {v['fileName']})\n"
                f"§f进度: {f'{(v['checked'] / v['total'] * 100):.1f}' if v['total'] > 0 else '0.0'}% | {v['checked']} / {v['total']} 方块 | 不匹配: {v['mismatches']} | {elapsed:.1f}s"
            )
        if self.fix_job:
            f = self.fix_job
            elapsed = (time.time() * 1000 - f["startTime"]) / 1000
            lines.append(
                f"§eLitematic | §fStatus > §i修复 §f(任务 #{f['taskId']}: {f['fileName']})\n"
                f"§f进度: {f['done']} / {f['total']} 方块 | {elapsed:.1f}s"
            )
        if not lines:
            self.client.tell("§cLitematic | §fError > §i当前没有进行中的任务", sender)
            return
        self.client.tellAll("\n\n".join(lines))

    async def _cmd_verify(self, sender, id_, mode):
        try:
            tid = int(id_)
        except (ValueError, TypeError):
            tid = None
        if tid is None or tid not in Mod.tasks:
            self.client.tell("§cLitematic | §fError > §i没有找到任务 ID，请先 !l:create 获取任务 ID", sender)
            return
        if mode == "map":
            self.verify(tid, sender)
            return
        if mode is not None and mode != "world":
            self.client.tell("§cLitematic | §fError > §i模式参数无效：应为 map（检查方块映射）或留空（检查世界一致性）", sender)
            return
        await self.verify_world(tid, sender)

    async def _cmd_fix(self, sender, id_, fb):
        try:
            tid = int(id_)
        except (ValueError, TypeError):
            tid = None
        if tid is None or tid not in Mod.tasks:
            self.client.tell("§cLitematic | §fError > §i没有找到任务 ID，请先 !l:create 获取任务 ID", sender)
            return
        if self.fix_job:
            self.client.tell("§cLitematic | §fError > §i已有修复任务进行中，请等待完成或 !l:n 中断", sender)
            return
        await self.fix(tid, sender, fb)

    # ---- 文件列表 ----

    def page_list(self, sender, files, header):
        dir_ = basePath["litematic"]
        if not os.path.exists(dir_):
            self.client.tell("§cLitematic | §fError > §i建筑目录不存在", sender)
            return
        if not files:
            self.client.tell("§cLitematic | §fError > §i没有找到 .litematic 文件", sender)
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
            name = re.sub(r"\.litematic$", "", f, flags=re.IGNORECASE)
            num = str(start_index + i + 1).rjust(2, " ")
            file_path = os.path.join(dir_, f)
            stats = os.stat(file_path)
            size = self.format_size(stats.st_size)
            items.append(f"{num}. {name} §f{size}")
        items_text = "\n".join(items)

        self.client.tell(f"{header} §f({pn}/{total_pages}页) §i共 {len(files)} 个\n{items_text}", sender)

    def list_files(self, page, sender):
        if page is not None:
            try:
                self.page = int(page) or 1
            except (ValueError, TypeError):
                self.page = 1
        else:
            self.page = 1
        dir_ = basePath["litematic"]
        files = sorted([f for f in os.listdir(dir_) if f.endswith(".litematic")]) if os.path.exists(dir_) else []
        self.page_list(sender, files, "§eLitematic | §fList")

    def search_files(self, keyword, page, sender):
        if page is not None:
            try:
                self.page = int(page) or 1
            except (ValueError, TypeError):
                self.page = 1
        else:
            self.page = 1
        dir_ = basePath["litematic"]
        files = sorted([
            f for f in os.listdir(dir_)
            if f.endswith(".litematic") and keyword.lower() in f.lower()
        ]) if os.path.exists(dir_) else []
        self.page_list(sender, files, f"§eLitematic | §fSearch > §i\"{keyword}\"")

    def list_tasks(self, sender):
        tasks = sorted(Mod.tasks.items(), key=lambda kv: kv[0], reverse=True)
        if not tasks:
            self.client.tell("§cLitematic | §fError > §i当前没有任务，先 !l:create 创建", sender)
            return
        now = time.time() * 1000
        lines = []
        for tid, t in tasks:
            blocks = len(t["data"].get("blocks") or []) if t.get("data") else 0
            age = now - t["time"]
            if age < 60000:
                ago = "刚刚"
            elif age < 3600000:
                ago = f"{math.floor(age / 60000)}分钟前"
            elif age < 86400000:
                ago = f"{math.floor(age / 3600000)}小时前"
            else:
                ago = f"{math.floor(age / 86400000)}天前"
            tags = []
            if len(t.get("mismatches") or []):
                tags.append(f"§c差异 §e{len(t['mismatches'])}§c 个")
            if len(t.get("data", {}).get("unmappedBlocks") or []):
                tags.append(f"§e未映射 {len(t['data']['unmappedBlocks'])} 个")
            lines.append(f"§b{str(tid).rjust(3, ' ')}. §f{t['file']} §7| §f{blocks}§7 方块 §7| §7{ago}{' §7| ' + ' '.join(tags) if tags else ''}")
        lines_text = "\n".join(lines)
        self.client.tell(
            f"§eLitematic | §fID > §i任务列表 ({len(tasks)} 个)\n{lines_text}\n"
            f"§7使用 §a!l:verify <ID>§7 检查世界差异 / §a!l:fix <ID>§7 修复", sender
        )

    def format_size(self, bytes_):
        if bytes_ < 1024:
            return f"{bytes_}B"
        if bytes_ < 1024 * 1024:
            return f"{(bytes_ / 1024):.1f}KB"
        return f"{(bytes_ / (1024 * 1024)):.1f}MB"

    # 解析放置参数:支持 $cmd file raw / $cmd file x y z / $cmd file x y z raw
    def parse_placement(self, x, y, z, mode):
        raw = False
        if mode == "raw":
            raw = True
        elif mode == "trim":
            raw = False
        elif mode is not None:
            return {"raw": None, "coords": []}
        if mode is None and x == "raw":
            raw = True
            x = None
        coords = [v for v in (x, y, z) if v is not None]
        return {"raw": raw, "coords": coords}

    # ---- 创建(导入)流程 ----

    async def create(self, file_name, sender, x, y, z, mode):
        placement = self.parse_placement(x, y, z, mode)
        raw = placement["raw"]
        coords = placement["coords"]
        if raw is None:
            self.client.tell("§cLitematic | §fError > §i模式参数无效：应为 raw（保留原始高度）或 trim（裁剪底部空气，默认）", sender)
            return
        if 0 < len(coords) < 3:
            self.client.tell("§cLitematic | §fError > §i坐标参数不完整，需要同时提供 X Y Z 或都不提供（使用自身坐标）", sender)
            return

        # 路径穿越防护:只允许单层合法文件名
        if (not isinstance(file_name, str) or not file_name
                or file_name != os.path.basename(file_name)
                or re.search(r"[\\/]", file_name) is not None or file_name.startswith(".")):
            self.client.tell(f"§cLitematic | §fError > §i非法的文件名: {file_name}", sender)
            return

        base_name = file_name if file_name.endswith(".litematic") else file_name + ".litematic"
        file_path = os.path.join(basePath["litematic"], base_name)
        if not os.path.exists(file_path):
            self.client.tell(f"§cLitematic | §fError > §i文件不存在: {file_name}", sender)
            return

        self.client.tell("§i正在解析 Litematic 文件…", sender)

        try:
            data = await parse_litematic(file_path)
        except Exception as e:
            self.client.tell(f"§cLitematic | §fError > §i解析失败: {e}", sender)
            return
        if not raw:
            trim_air(data)

        if len(coords) == 3:
            origin = {
                "x": math.floor(float(coords[0])),
                "y": math.floor(float(coords[1])),
                "z": math.floor(float(coords[2])),
            }
        else:
            try:
                pos = await self.client.getPosition("@s")
                if not pos:
                    self.client.tell("§cLitematic | §fError > §i无法获取你的坐标", sender)
                    return
                # 玩家脚底的 Y 是其脚下方块的上表面,减 1 使建筑底部对齐到脚下那层方块
                origin = {"x": math.floor(pos["x"]), "y": math.floor(pos["y"]) - 1, "z": math.floor(pos["z"])}
            except Exception:
                self.client.tell("§cLitematic | §fError > §i无法获取你的坐标", sender)
                return

        if origin["y"] < -64 or origin["y"] + data["sy"] - 1 > 320:
            self.client.tell(f"§cLitematic | §fError > §iY 轴超出限制: {origin['y']} ~ {origin['y'] + data['sy'] - 1} (允许 -64 ~ 320)", sender)
            return

        self.pending = {"data": data, "origin": origin, "file": file_name, "raw": raw}

        # 分配唯一任务 ID 并存档,供 $verify / $fix 使用
        Mod.task_seq += 1
        task_id = Mod.task_seq
        Mod.tasks[task_id] = {"data": data, "file": file_name, "origin": origin, "raw": raw, "time": time.time() * 1000}
        self.pending["taskId"] = task_id
        if self.job and "taskId" not in self.job:
            self.job["taskId"] = task_id

        min_x = origin["x"]
        min_y = origin["y"]
        min_z = origin["z"]
        max_x = min_x + data["sx"] - 1
        max_y = min_y + data["sy"] - 1
        max_z = min_z + data["sz"] - 1
        block_count = len(data["blocks"])
        cmd_count = len(merge_blocks_to_rects(data["blocks"], data["sx"], data["sz"]))

        start_chunk_x = math.floor(min_x / 16)
        start_chunk_z = math.floor(min_z / 16)
        end_chunk_x = math.floor(max_x / 16)
        end_chunk_z = math.floor(max_z / 16)
        total_chunks_x = end_chunk_x - start_chunk_x + 1
        total_chunks_z = end_chunk_z - start_chunk_z + 1
        total_chunks = total_chunks_x * total_chunks_z

        MAX_CHUNKS = 100
        if total_chunks <= MAX_CHUNKS:
            area_count = 1
        elif total_chunks_z > MAX_CHUNKS:
            area_count = math.ceil(total_chunks_z / MAX_CHUNKS) * total_chunks_x
        else:
            area_count = math.ceil(total_chunks_x / max(1, math.floor(MAX_CHUNKS / total_chunks_z)))

        unmapped_count = len(data.get("unmappedBlocks") or [])
        est_time = f"{((area_count + cmd_count) * 0.001 + 1):.1f}"

        self.client.tellAll(
            f"§eLitematic | §fImport > §i{file_name}\n"
            f"§f任务ID: §b{task_id} §7(用于 !l:verify / !l:fix)\n"
            f"§f尺寸: {data['sx']} × {data['sy']} × {data['sz']} = {data['totalCoords']} 坐标\n"
            f"§f方块: {block_count} → {cmd_count} 条指令\n"
            f"§f底部空气: {data.get('trimmedAir', 0)} 层 §7({'raw: 保留高度偏移' if raw else 'trim: 已裁剪对齐地面'})\n"
            f"§f区块: {total_chunks} 个 ({total_chunks_x}×{total_chunks_z}) → {area_count} 个区域\n"
            f"§f范围: ({min_x}, {min_y}, {min_z}) → ({max_x}, {max_y}, {max_z})\n"
            f"§f预计耗时: {est_time}s"
        )
        if unmapped_count:
            self.client.tellAll(f"§cLitematic | §fWarn > §i无法映射方块: {unmapped_count} 个 （可用 !l:verify {task_id} map 检查，!l:fix {task_id} 修复）")
        self.client.tellAll(f"§f确认请发送 §e!l:y，取消请发送 §c!l:n")

    async def run(self):
        task = self.pending
        self.pending = None

        data = task["data"]
        origin = task["origin"]
        file_name = task["file"]
        task_id = task.get("taskId")
        blocks = data["blocks"]
        total = len(blocks)
        sx, sy, sz = data["sx"], data["sy"], data["sz"]

        rects = merge_blocks_to_rects(blocks, sx, sz)
        total_cmds = len(rects)

        self.job = {
            "fileName": file_name,
            "taskId": task_id,
            "total": total_cmds,
            "cancelled": False,
            "startTime": time.time() * 1000,
            "blockTotal": total,
            "phase": "准备",
            "areaIndex": 0,
            "areaTotal": 0,
            "phasePlaced": 0,
            "phaseTotal": 0,
            "phaseBlocksPlaced": 0,
            "phaseBlockTotal": 0,
        }

        MAX_CHUNKS = 100
        FILL_LIMIT = 32767

        start_chunk_x = math.floor(origin["x"] / 16)
        start_chunk_z = math.floor(origin["z"] / 16)
        end_chunk_x = math.floor((origin["x"] + sx - 1) / 16)
        end_chunk_z = math.floor((origin["z"] + sz - 1) / 16)

        total_chunks_x = end_chunk_x - start_chunk_x + 1
        total_chunks_z = end_chunk_z - start_chunk_z + 1

        areas = []
        if total_chunks_x * total_chunks_z <= MAX_CHUNKS:
            areas.append({"cx1": start_chunk_x, "cz1": start_chunk_z, "cx2": end_chunk_x, "cz2": end_chunk_z})
        elif total_chunks_z > MAX_CHUNKS:
            max_chunks_z = MAX_CHUNKS
            cz = start_chunk_z
            while cz <= end_chunk_z:
                cz2 = min(cz + max_chunks_z - 1, end_chunk_z)
                areas.append({"cx1": start_chunk_x, "cz1": cz, "cx2": end_chunk_x, "cz2": cz2})
                cz += max_chunks_z
        else:
            max_chunks_x = max(1, math.floor(MAX_CHUNKS / total_chunks_z))
            cx = start_chunk_x
            while cx <= end_chunk_x:
                cx2 = min(cx + max_chunks_x - 1, end_chunk_x)
                areas.append({"cx1": cx, "cz1": start_chunk_z, "cx2": cx2, "cz2": end_chunk_z})
                cx += max_chunks_x

        for i, area in enumerate(areas):
            if self.job["cancelled"]:
                break

            cx1, cz1, cx2, cz2 = area["cx1"], area["cz1"], area["cx2"], area["cz2"]
            abs_x1 = cx1 * 16
            abs_z1 = cz1 * 16
            abs_x2 = (cx2 + 1) * 16 - 1
            abs_z2 = (cz2 + 1) * 16 - 1

            self.job["areaIndex"] = i + 1
            self.job["areaTotal"] = len(areas)

            self.job["phase"] = "创建常加载区块"
            self.job["phasePlaced"] = 0
            self.job["phaseTotal"] = 1
            self.job["phaseBlocksPlaced"] = 0
            self.job["phaseBlockTotal"] = 0
            try:
                await self.client.runCommand(f"/tickingarea add {abs_x1} {origin['y']} {abs_z1} {abs_x2} {origin['y'] + sy - 1} {abs_z2} litematic_{i}")
            except Exception as e:
                self.client.tellAll(f"§cLitematic | §fError > §i[tickingarea add] {e}")
            fill_x1 = max(abs_x1, origin["x"])
            fill_z1 = max(abs_z1, origin["z"])
            fill_x2 = min(abs_x2, origin["x"] + sx - 1)
            fill_z2 = min(abs_z2, origin["z"] + sz - 1)

            area_per_y = (fill_x2 - fill_x1 + 1) * (fill_z2 - fill_z1 + 1)
            max_y_layers_per_chunk = math.floor(FILL_LIMIT / area_per_y)

            self.job["phase"] = "清除空气"
            y_layers = 1 if max_y_layers_per_chunk >= sy else math.ceil(sy / max_y_layers_per_chunk)
            self.job["phaseTotal"] = y_layers
            self.job["phasePlaced"] = 0
            self.job["phaseBlocksPlaced"] = 0
            self.job["phaseBlockTotal"] = 0

            if max_y_layers_per_chunk >= sy:
                await self.client.sendCommand(f"/fill {fill_x1} {origin['y']} {fill_z1} {fill_x2} {origin['y'] + sy - 1} {fill_z2} air")
                self.job["phasePlaced"] = 1
            else:
                y_start = 0
                while y_start < sy:
                    if self.job["cancelled"]:
                        break
                    y_end = min(y_start + max_y_layers_per_chunk - 1, sy - 1)
                    abs_y1 = origin["y"] + y_start
                    abs_y2 = origin["y"] + y_end
                    await self.client.sendCommand(f"/fill {fill_x1} {abs_y1} {fill_z1} {fill_x2} {abs_y2} {fill_z2} air")
                    self.job["phasePlaced"] += 1
                    y_start += max_y_layers_per_chunk
                    await asyncio.sleep(0.001)
            await asyncio.sleep(1.0)

            chunk_rects = []
            for r in rects:
                if r["type"] == "setblock":
                    rx1 = r["x"]
                    rz1 = r["z"]
                else:
                    rx1 = r["x1"]
                    rz1 = r["z1"]
                abs_rx1 = origin["x"] + rx1
                abs_rz1 = origin["z"] + rz1
                abs_ry = origin["y"] + r["y"]

                if r["type"] == "setblock":
                    if fill_x1 <= abs_rx1 <= fill_x2 and fill_z1 <= abs_rz1 <= fill_z2:
                        chunk_rects.append({"r": r, "cx1": abs_rx1, "cy1": abs_ry, "cz1": abs_rz1,
                                            "cx2": abs_rx1, "cy2": abs_ry, "cz2": abs_rz1})
                else:
                    rx2 = r["x2"]
                    rz2 = r["z2"]
                    abs_rx2 = origin["x"] + rx2
                    abs_rz2 = origin["z"] + rz2
                    if abs_rx2 >= fill_x1 and abs_rx1 <= fill_x2 and abs_rz2 >= fill_z1 and abs_rz1 <= fill_z2:
                        c_x1 = max(abs_rx1, fill_x1)
                        c_z1 = max(abs_rz1, fill_z1)
                        c_x2 = min(abs_rx2, fill_x2)
                        c_z2 = min(abs_rz2, fill_z2)
                        clipped_count = (c_x2 - c_x1 + 1) * (c_z2 - c_z1 + 1)
                        chunk_rects.append({"r": r, "cx1": c_x1, "cy1": abs_ry, "cz1": c_z1,
                                            "cx2": c_x2, "cy2": abs_ry, "cz2": c_z2, "clippedCount": clipped_count})

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
                await self.client.runCommand(f"/tickingarea remove litematic_{i}")
            except Exception:
                pass

        if not self.job["cancelled"]:
            elapsed = (time.time() * 1000 - self.job["startTime"]) / 1000
            speed = round(total / elapsed) if elapsed > 0 else 0
            self.client.tellAll(f"§eLitematic | §fImport > §i{file_name} 导入完成 共 {total} 方块 {total_cmds} 指令 耗时 {elapsed:.1f}s 速度 {speed}方块/s")
        else:
            self.client.tellAll(f"§cLitematic | §fCancel > §i导入已中断 ({file_name})")
        self.job = None

    # l:verify <ID> map: 检查任务投影中方块映射错误
    def verify(self, id_, sender):
        task = Mod.tasks.get(id_)
        data = task["data"]
        unmapped = data.get("unmappedBlocks") or []
        if not unmapped:
            self.client.tell(
                f"§aLitematic | §fVerify > §i任务 #{id_} ({task['file']}) 方块映射检查通过，无 mod 方块错误\n"
                f"§f提示: 要检查游戏世界里方块是否被挖掉/替换，请用 !l:verify {id_}", sender
            )
            return
        lines = "\n".join(f"§f{name} §7× §e{cnt}" for name, cnt in (data.get("unmappedSummary") or {}).items())
        self.client.tell(
            f"§eLitematic | §fVerify > §i方块检查报告 (任务 #{id_})\n"
            f"§f文件: {task['file']}\n"
            f"§c无法映射方块: {len(unmapped)} 个 （导入时会被跳过）\n"
            f"{lines}\n"
            f"§7发送 !l:fix {id_} §7将用 stone 替换（可指定替代方块）", sender
        )

    # l:verify <ID> world: 检查游戏世界里投影区域与投影数据的差异
    async def verify_world(self, id_, sender):
        c = self.client
        task = Mod.tasks.get(id_)
        data = task["data"]
        origin = task["origin"]
        blocks = data["blocks"]
        if not blocks:
            self.client.tell(f"§aLitematic | §fVerify > §i任务 #{id_} 没有可检查的方块", sender)
            return
        t0 = time.time() * 1000
        est = math.ceil(len(blocks) / 8)
        self.client.tell(f"§i开始世界检查… {len(blocks)} 个方块 （预计 {est}s 左右，!l:n 可中断）", sender)
        CONC = 4
        mismatches = []
        checked = 0
        self.verify_job = {
            "cancelled": False, "taskId": id_, "fileName": task["file"],
            "total": len(blocks), "checked": 0, "mismatches": 0, "startTime": time.time() * 1000,
        }
        try:
            async def check_one(b):
                nonlocal checked
                ax = origin["x"] + b["x"]
                ay = origin["y"] + b["y"]
                az = origin["z"] + b["z"]
                cmd = f"testforblock {ax} {ay} {az} {b['cmd'] or b['identifier']}"
                matched = False
                # testforblock 命令可能被服务器限流丢弃(无响应),超时重试最多 3 次
                for attempt in range(3):
                    try:
                        d = await c.runCommand(cmd, 3000)
                        if isinstance(d, dict) and d.get("body", {}).get("statusCode") == 0:
                            matched = True
                        break
                    except Exception:
                        if attempt < 2:
                            await asyncio.sleep(0.3)
                if not matched:
                    mismatches.append({"x": ax, "y": ay, "z": az, "expect": b["identifier"], "cmd": b["cmd"] or b["identifier"]})
                    self.verify_job["mismatches"] = len(mismatches)
                checked += 1
                self.verify_job["checked"] = checked

            i = 0
            while i < len(blocks) and not self.verify_job["cancelled"]:
                batch = blocks[i:i + CONC]
                await asyncio.gather(*(check_one(b) for b in batch))
                if checked >= 500 and checked % 500 == 0:
                    self.client.tellAll(f"§7Litematic | §fVerify >  §i世界检查进度: {checked}/{len(blocks)} | 不匹配: {len(mismatches)} 个")
                i += CONC
                await asyncio.sleep(0.001)
        finally:
            self.verify_job = None

        if checked == 0:
            self.client.tell("§cLitematic | §fVerify > §i世界检查已中断", sender)
            return
        elapsed = (time.time() * 1000 - t0) / 1000
        # 差异列表存档到任务,供 $fix 修复
        task["mismatches"] = mismatches
        if not mismatches:
            self.client.tell(f"§aLitematic | §fVerify > §i世界检查完成 (任务 #{id_}) 已逐块 testforblock 比对 {checked} 个方块，全部与投影一致 耗时 {elapsed:.1f}s", sender)
            return
        lines = []
        for m in mismatches[:20]:
            sp = m["cmd"][m["cmd"].index("["):] if m["cmd"] and "[" in m["cmd"] else ""
            lines.append(f"§7({m['x']},{m['y']},{m['z']}) §f期望 §e{re.sub(r'^minecraft:', '', m['expect'])}§f{sp}")
        list_text = "\n".join(lines)
        more = f"\n§7…共 {len(mismatches)} 处差异" if len(mismatches) > 20 else ""
        self.client.tell(
            f"§eLitematic | §fVerify > §i世界检查报告 (任务 #{id_})\n"
            f"§f文件: {task['file']}\n"
            f"§f检查: {checked} 个方块 | 不匹配: {len(mismatches)} 个 耗时 {elapsed:.1f}s\n"
            f"{list_text}{more}\n"
            f"§7差异可能是方块被挖掉或替换（本检查不检测额外新增的方块）\n"
            f"§7发送 !l:fix {id_} §7可重新放置这些方块，恢复与投影一致", sender
        )

    # l:fix <ID> [替代方块]: ① 重新放置 verify 发现的被挖掉/替换的方块 ② 替换无法映射的方块
    async def fix(self, id_, sender, fb):
        c = self.client
        task = Mod.tasks.get(id_)
        data = task["data"]
        n1 = 0
        n2 = 0
        fixed = []
        failed = []
        # ① 修复世界检查发现的差异
        mismatches = task.get("mismatches") or []
        if mismatches:
            n1 = len(mismatches)
            CONC = 4
            self.fix_job = {
                "cancelled": False, "taskId": id_, "fileName": task["file"],
                "total": len(mismatches), "done": 0, "startTime": time.time() * 1000,
            }
            try:
                async def place_one(m):
                    idn = re.sub(r"^minecraft:", "", m["expect"])
                    cmd = f"/setblock {m['x']} {m['y']} {m['z']} {m['cmd'] or idn}"
                    for attempt in range(3):
                        try:
                            d = await c.runCommand(cmd, 3000)
                            if isinstance(d, dict) and d.get("body", {}).get("statusCode") == 0:
                                fixed.append(f"§7({m['x']},{m['y']},{m['z']}) §f→ §e{idn}")
                                self.fix_job["done"] += 1
                                return
                        except Exception:
                            pass
                        await asyncio.sleep(0.3)
                    failed.append(m)
                    self.fix_job["done"] += 1

                i = 0
                while i < len(mismatches) and not self.fix_job["cancelled"]:
                    batch = mismatches[i:i + CONC]
                    await asyncio.gather(*(place_one(m) for m in batch))
                    i += CONC
                # 中断时未处理的差异保留,供再次 $fix 继续
                for idx in range(self.fix_job["done"], len(mismatches)):
                    failed.append(mismatches[idx])
            finally:
                self.fix_job = None
            task["mismatches"] = failed
        # ② 修复无法映射的方块(更新任务数据,供 $y 导入)
        unmapped = data.get("unmappedBlocks") or []
        if unmapped:
            n2 = len(unmapped)
            bid = fb or "minecraft:stone"
            idn = re.sub(r"^minecraft:", "", bid)
            for u in unmapped:
                data["blocks"].append({"x": u["x"], "y": u["y"], "z": u["z"], "identifier": bid, "state": {}, "cmd": idn})
            data["unmappedBlocks"] = []
            data["unmappedSummary"] = {}
        if not n1 and not n2:
            self.client.tell(f"§aLitematic | §fFix > §i任务 #{id_} 没有需要修复的方块", sender)
            return
        lines = []
        if n1:
            lines.append(f"§a已重新放置 {len(fixed)} / {n1} 个方块 （恢复与投影一致）")
            if failed:
                lines.append(f"§c未成功 {len(failed)} 个 （命令被服务器限流，可再次 !l:verify {id_} 检查并 !l:fix {id_} 重试）")
        if n2:
            lines.append(f"§a已将 {n2} 个无法映射方块替换为 {fb or 'minecraft:stone'}，任务存档已更新，直接发送 !l:y 即可用修复后的数据导入")
        if fixed:
            lines.append("\n".join(fixed[:20]))
        self.client.tell(f"§aLitematic | §fFix > §i已修复 (任务 #{id_})\n" + "\n".join(lines), sender)

    # ---- 预览 ----

    async def preview(self, file_name, sender, x, y, z, mode):
        placement = self.parse_placement(x, y, z, mode)
        raw = placement["raw"]
        coords = placement["coords"]
        if raw is None:
            self.client.tell("§cLitematic | §fError > §i模式参数无效：应为 raw（保留原始高度）或 trim（裁剪底部空气，默认）", sender)
            return
        if 0 < len(coords) < 3:
            self.client.tell("§cLitematic | §fError > §i坐标参数不完整，需要同时提供 X Y Z 或都不提供（使用自身坐标）", sender)
            return
        base_name = file_name if file_name.endswith(".litematic") else file_name + ".litematic"
        file_path = os.path.join(basePath["litematic"], base_name)
        if not os.path.exists(file_path):
            self.client.tell(f"§cLitematic | §fError > §i文件不存在: {file_name}", sender)
            return
        self.client.tell("§i正在解析 Litematic 文件…", sender)
        try:
            data = await parse_litematic(file_path)
        except Exception as e:
            self.client.tell(f"§cLitematic | §fError > §i解析失败: {e}", sender)
            return
        if not raw:
            trim_air(data)
        if len(coords) == 3:
            origin = {
                "x": math.floor(float(coords[0])),
                "y": math.floor(float(coords[1])),
                "z": math.floor(float(coords[2])),
            }
        else:
            try:
                pos = await self.client.getPosition("@s")
                if not pos:
                    self.client.tell("§cLitematic | §fError > §i无法获取你的坐标", sender)
                    return
                origin = {"x": math.floor(pos["x"]), "y": math.floor(pos["y"]) - 1, "z": math.floor(pos["z"])}
            except Exception:
                self.client.tell("§cLitematic | §fError > §i无法获取你的坐标", sender)
                return
        if origin["y"] < -64 or origin["y"] + data["sy"] - 1 > 320:
            self.client.tell(f"§cLitematic | §fError > §iY 轴超出限制: {origin['y']} ~ {origin['y'] + data['sy'] - 1} (允许 -64 ~ 320)", sender)
            return
        await self.clear_preview()
        self.preview_data = {"origin": origin, "data": data, "file": file_name}
        await self.spawn_preview_entities()
        await self.spawn_preview_particles()
        loop = asyncio.get_running_loop()
        self.preview_timer = loop.create_task(self._preview_loop())
        self.client.tell(
            f"§eLitematic | §fPreview > §i已生成预览: {file_name} 尺寸 {data['sx']}×{data['sy']}×{data['sz']}\n"
            f"§f范围: ({origin['x']}, {origin['y']}, {origin['z']}) → ({origin['x'] + data['sx'] - 1}, {origin['y'] + data['sy'] - 1}, {origin['z'] + data['sz'] - 1})\n"
            f"§f底部空气: {data.get('trimmedAir', 0)} 层 §7({'保留原始高度' if raw else '已裁剪，建筑底部对齐放置点'})\n"
            f"§f§o实体标记持续显示，输入 !l:unpreview 清除", sender
        )

    async def _preview_loop(self):
        try:
            while True:
                await asyncio.sleep(1.5)
                await self.spawn_preview_particles()
        except asyncio.CancelledError:
            pass

    async def clear_preview(self, sender=None):
        if self.preview_timer:
            self.preview_timer.cancel()
            self.preview_timer = None
        self.preview_data = None
        await self.client.sendCommand('/kill @e[name="§a[LIT]▪"]')
        await self.client.sendCommand('/kill @e[name="§e[LIT]✦"]')
        await self.client.sendCommand('/kill @e[name="§b[LIT]INFO"]')
        if sender:
            self.client.tell("§7Litematic | §fPreview > §i已清除建筑预览", sender)

    # 12 条边框边(角点对)
    @staticmethod
    def preview_edges(x1, y1, z1, x2, y2, z2):
        return [
            [[x1, y1, z1], [x2, y1, z1]], [[x1, y1, z2], [x2, y1, z2]],
            [[x1, y2, z1], [x2, y2, z1]], [[x1, y2, z2], [x2, y2, z2]],
            [[x1, y1, z1], [x1, y2, z1]], [[x2, y1, z1], [x2, y2, z1]],
            [[x1, y1, z2], [x1, y2, z2]], [[x2, y1, z2], [x2, y2, z2]],
            [[x1, y1, z1], [x1, y1, z2]], [[x2, y1, z1], [x2, y1, z2]],
            [[x1, y2, z1], [x1, y2, z2]], [[x2, y2, z1], [x2, y2, z2]],
        ]

    async def spawn_preview_entities(self):
        origin = self.preview_data["origin"]
        data = self.preview_data["data"]
        x1, y1, z1 = origin["x"], origin["y"], origin["z"]
        x2, y2, z2 = x1 + data["sx"] - 1, y1 + data["sy"] - 1, z1 + data["sz"] - 1
        step = max(3, math.ceil(max(data["sx"], data["sy"], data["sz"]) / 50))
        for px, py, pz in [[x1, y1, z1], [x2, y1, z1], [x1, y1, z2], [x2, y1, z2],
                           [x1, y2, z1], [x2, y2, z1], [x1, y2, z2], [x2, y2, z2]]:
            await self.client.sendCommand(f'/summon text_display {px} {py} {pz} "§e[LIT]✦"')
        for a, b in Mod.preview_edges(x1, y1, z1, x2, y2, z2):
            dx = b[0] - a[0]
            dy = b[1] - a[1]
            dz = b[2] - a[2]
            length = max(abs(dx), abs(dy), abs(dz))
            n = math.floor(length / step)
            for i in range(1, n + 1):
                await self.client.sendCommand(
                    f'/summon text_display {round(a[0] + dx * i / n)} {round(a[1] + dy * i / n)} {round(a[2] + dz * i / n)} "§a[LIT]▪"'
                )
        await self.client.sendCommand(f'/summon text_display {math.floor((x1 + x2) / 2)} {y2 + 2} {math.floor((z1 + z2) / 2)} "§b[LIT]INFO"')

    async def spawn_preview_particles(self):
        if not self.preview_data:
            return
        origin = self.preview_data["origin"]
        data = self.preview_data["data"]
        x1, y1, z1 = origin["x"], origin["y"], origin["z"]
        x2, y2, z2 = x1 + data["sx"] - 1, y1 + data["sy"] - 1, z1 + data["sz"] - 1
        step = max(3, math.ceil(max(data["sx"], data["sy"], data["sz"]) / 60))
        # 底边 4 条 + 立柱 4 条(顶部省略,避免粒子过多)
        edges = Mod.preview_edges(x1, y1, z1, x2, y2, z2)[:8]
        for a, b in edges:
            dx = b[0] - a[0]
            dy = b[1] - a[1]
            dz = b[2] - a[2]
            length = max(abs(dx), abs(dy), abs(dz))
            n = math.floor(length / step)
            for i in range(n + 1):
                await self.client.sendCommand(
                    f"/particle minecraft:endrod {a[0] + dx * i / n + 0.5} {a[1] + dy * i / n + 0.5} {a[2] + dz * i / n + 0.5}"
                )

    # ---- 导出 .mcstructure ----

    async def export_structure(self, file_name, sender, export_name, mode):
        raw = False
        if mode == "raw":
            raw = True
        elif mode == "trim":
            raw = False
        elif mode is not None:
            self.client.tell("§cLitematic | §fError > §i模式参数无效：应为 raw 或 trim", sender)
            return
        if mode is None and export_name == "raw":
            raw = True
            export_name = None
        base_name = file_name if file_name.endswith(".litematic") else file_name + ".litematic"
        file_path = os.path.join(basePath["litematic"], base_name)
        if not os.path.exists(file_path):
            self.client.tell(f"§cLitematic | §fError > §i文件不存在: {file_name}", sender)
            return
        self.client.tell("§i正在解析 Litematic 文件…", sender)
        try:
            data = await parse_litematic(file_path)
        except Exception as e:
            self.client.tell(f"§cLitematic | §fError > §i解析失败: {e}", sender)
            return
        if not raw:
            trim_air(data)
        default_name = re.sub(r"\.litematic$", "", file_name, flags=re.IGNORECASE)
        name = re.sub(r'[\\/:*?"<>|]', "_", export_name or default_name)
        dir_ = resolvePath("./structures")
        os.makedirs(dir_, exist_ok=True)
        out_path = os.path.join(dir_, name + ".mcstructure")
        try:
            content = build_mc_structure(data)
            with open(out_path, "wb") as f:
                f.write(content)
        except Exception as e:
            self.client.tell(f"§cLitematic | §fError > §i导出失败: {e}", sender)
            return
        self.client.tell(
            f"§aLitematic | §fExport > §i已导出结构文件: {out_path}\n"
            f"§f尺寸: {data['sx']} × {data['sy']} × {data['sz']} | 方块: {len(data['blocks'])} | 底部空气: {data.get('trimmedAir', 0)} 层\n"
            f"§7用法: 将文件放入行为包 structures 文件夹（如 BP/structures/mystructure/）或单机存档的 structures 文件夹，游戏内用结构方块预览放置，或执行 /structure load <名称>", sender
        )

    def onDestroy(self):
        if self.job:
            self.job["cancelled"] = True
        if self.verify_job:
            self.verify_job["cancelled"] = True
        if self.fix_job:
            self.fix_job["cancelled"] = True
        if self.preview_timer:
            self.preview_timer.cancel()
            self.preview_timer = None
        self.pending = None
        self.job = None
        self.verify_job = None
        self.fix_job = None
        self.preview_data = None
        self.client = None
