"""坐标操作 Mod

提供 A/B 点标记、距离/偏移计算、区域填充、结构复制/粘贴/剪切等功能
"""
import asyncio
import math
import time

from lib.command import Command

FILL_LIMIT = 32767
CHUNK = 16
CHUNK_SIZE = 64
MAX_TICKING_CHUNKS = 100
# 单个 tickingarea 上限为 100 个区块(16×16),最多同时 10 个。
# 64×64 区域横向最多占 5×5 区块,每 48 格高度最多占 4 区块:5×5×4=100,任意对齐均安全。
MAX_SEG_HEIGHT = 48
Y_MIN = -64
Y_MAX = 320


def _sleep(ms):
    return asyncio.sleep(ms / 1000)


def validate_y(y, sender):
    if y < Y_MIN or y > Y_MAX:
        raise ValueError(f"Y 坐标超出范围: §f{y} §c(允许 {Y_MIN} ~ {Y_MAX})")


def compute_xz_areas(min_x, min_z, max_x, max_z):
    """按 64×64 区块把区域切分为多个 tickingarea 单元"""
    start_chunk_x = min_x // CHUNK_SIZE
    start_chunk_z = min_z // CHUNK_SIZE
    end_chunk_x = max_x // CHUNK_SIZE
    end_chunk_z = max_z // CHUNK_SIZE

    total_chunks_x = end_chunk_x - start_chunk_x + 1
    total_chunks_z = end_chunk_z - start_chunk_z + 1
    total_chunks = total_chunks_x * total_chunks_z

    areas = []
    if total_chunks <= MAX_TICKING_CHUNKS:
        for cz in range(start_chunk_z, end_chunk_z + 1):
            for cx in range(start_chunk_x, end_chunk_x + 1):
                areas.append({"cx1": cx, "cz1": cz, "cx2": cx, "cz2": cz})
    elif total_chunks_z > MAX_TICKING_CHUNKS:
        max_cz = MAX_TICKING_CHUNKS
        cz = start_chunk_z
        while cz <= end_chunk_z:
            cz_end = min(cz + max_cz - 1, end_chunk_z)
            for czz in range(cz, cz_end + 1):
                for cx in range(start_chunk_x, end_chunk_x + 1):
                    areas.append({"cx1": cx, "cz1": czz, "cx2": cx, "cz2": czz})
            cz += max_cz
    else:
        max_cx = max(1, MAX_TICKING_CHUNKS // total_chunks_z)
        cx = start_chunk_x
        while cx <= end_chunk_x:
            cx_end = min(cx + max_cx - 1, end_chunk_x)
            for cxx in range(cx, cx_end + 1):
                for cz in range(start_chunk_z, end_chunk_z + 1):
                    areas.append({"cx1": cxx, "cz1": cz, "cx2": cxx, "cz2": cz})
            cx += max_cx
    return areas


class Mod:
    """坐标操作 Mod(客户端)"""

    def __init__(self, client):
        self.client = client
        self.job = None
        self.posA = None
        self.posB = None
        self.lastCopyEntry = None

    def onCommand(self):
        return {
            "op": [
                Command.create("p:a", "设置 A 点坐标（可选 X Y Z，缺省则取自身坐标）")
                .add_optional_integer("X")
                .add_optional_integer("Y")
                .add_optional_integer("Z")
                .set_func(self._cmd_a),

                Command.create("p:b", "设置 B 点坐标（可选 X Y Z，缺省则取自身坐标）")
                .add_optional_integer("X")
                .add_optional_integer("Y")
                .add_optional_integer("Z")
                .set_func(self._cmd_b),

                Command.create("p:distance", "计算 A B 两点间的距离（保留 3 位小数）")
                .set_func(self._cmd_distance),

                Command.create("p:offset", "计算 B 点相对于 A 点的偏移量")
                .set_func(self._cmd_offset),

                Command.create("p:fill", "填充 A B 两点间区域（必填方块 ID，选填 replace 目标方块 ID）")
                .add_string("填充方块 ID", False)
                .add_optional_string("替换目标方块 ID")
                .set_func(self._cmd_fill),

                Command.create("p:copy", "复制 A B 两点间区域")
                .set_func(self._cmd_copy),

                Command.create("p:paste", "粘贴复制的结构（可选 X Y Z，缺省取自身坐标）")
                .add_optional_integer("X")
                .add_optional_integer("Y")
                .add_optional_integer("Z")
                .set_func(self._cmd_paste),

                Command.create("p:cut", "剪切 A B 两点间区域（复制后填充空气）")
                .set_func(self._cmd_cut),

                Command.create("p:cancel", "中断当前操作")
                .set_func(self._cmd_cancel),

                Command.create("p:status", "查看当前任务进度")
                .set_func(self._cmd_status),

                Command.create("p:show", "显示当前 A B 点坐标")
                .set_func(self._cmd_show),
            ],
        }

    # ---- 命令实现 ----

    async def _cmd_a(self, sender, x, y, z):
        if self.job:
            self.client.tell("§cPosition | §fError > §i已有操作进行中，请等待完成或 $p:cancel 中断", sender)
            return
        if x is not None and y is not None and z is not None:
            pos = {"x": x, "y": y, "z": z}
        else:
            try:
                pos = await self.client.getPosition("@s")
            except Exception:
                self.client.tell("§cPosition | §fError > §i无法获取你的坐标", sender)
                return
        if not pos:
            self.client.tell("§cPosition | §fError > §i无法获取坐标", sender)
            return
        validate_y(math.floor(pos["y"]), sender)
        self.posA = {"x": math.floor(pos["x"]), "y": math.floor(pos["y"]), "z": math.floor(pos["z"])}
        self.client.tellAll(f"§ePosition | §fPosA > §i已记录坐标 {self.posA['x']} {self.posA['y']} {self.posA['z']}")

    async def _cmd_b(self, sender, x, y, z):
        if self.job:
            self.client.tell("§cPosition | §fError > §i已有操作进行中，请等待完成或 $p:cancel 中断", sender)
            return
        if x is not None and y is not None and z is not None:
            pos = {"x": x, "y": y, "z": z}
        else:
            try:
                pos = await self.client.getPosition("@s")
            except Exception:
                self.client.tell("§cPosition | §fError > §i无法获取你的坐标", sender)
                return
        if not pos:
            self.client.tell("§cPosition | §fError > §i无法获取坐标", sender)
            return
        validate_y(math.floor(pos["y"]), sender)
        self.posB = {"x": math.floor(pos["x"]), "y": math.floor(pos["y"]), "z": math.floor(pos["z"])}
        self.client.tellAll(f"§ePosition | §fPosB > §i已记录坐标 {self.posB['x']} {self.posB['y']} {self.posB['z']}")

    async def _cmd_distance(self, sender):
        if not self.posA or not self.posB:
            self.client.tell("§cPosition | §fError > §i请先设置 A 点和 B 点", sender)
            return
        dx = self.posB["x"] - self.posA["x"]
        dy = self.posB["y"] - self.posA["y"]
        dz = self.posB["z"] - self.posA["z"]
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        self.client.tellAll(f"§ePosition | §fDistance > §i{dist:.3f}")

    async def _cmd_offset(self, sender):
        if not self.posA or not self.posB:
            self.client.tell("§cPosition | §fError > §i请先设置 A 点和 B 点", sender)
            return
        ox = self.posB["x"] - self.posA["x"]
        oy = self.posB["y"] - self.posA["y"]
        oz = self.posB["z"] - self.posA["z"]
        self.client.tellAll(f"§ePosition | §fOffset > §iX {ox}  Y {oy}  Z {oz}")

    async def _cmd_fill(self, sender, fill_block, replace_block):
        if not self.posA or not self.posB:
            self.client.tell("§cPosition | §fError > §i请先设置 A 点和 B 点", sender)
            return
        await self._with_job(sender, "fill", lambda: self._exec_fill(sender, fill_block, replace_block))

    async def _cmd_copy(self, sender):
        if not self.posA or not self.posB:
            self.client.tell("§cPosition | §fError > §i请先设置 A 点和 B 点", sender)
            return
        await self._with_job(sender, "copy", lambda: self._exec_copy(sender))

    async def _cmd_paste(self, sender, x, y, z):
        if x is not None or y is not None or z is not None:
            if x is None or y is None or z is None:
                self.client.tell("§cPosition | §fError > §i请提供完整的 X Y Z 坐标或不提供坐标", sender)
                return
            origin = {"x": x, "y": y, "z": z}
        else:
            try:
                pos = await self.client.getPosition("@s")
                if not pos:
                    self.client.tell("§cPosition | §fError > §i无法获取你的坐标", sender)
                    return
                origin = {"x": math.floor(pos["x"]), "y": math.floor(pos["y"]), "z": math.floor(pos["z"])}
            except Exception:
                self.client.tell("§cPosition | §fError > §i无法获取你的坐标", sender)
                return
        await self._with_job(sender, "paste", lambda: self._exec_paste(sender, origin))

    async def _cmd_cut(self, sender):
        if not self.posA or not self.posB:
            self.client.tell("§cPosition | §fError > §i请先设置 A 点和 B 点", sender)
            return

        async def _cut():
            await self._exec_copy(sender)
            if self.job and not self.job["cancelled"]:
                await self._exec_fill(sender, "air", None)

        await self._with_job(sender, "cut", _cut)

    async def _cmd_cancel(self, sender):
        if self.job:
            self.job["cancelled"] = True
            self.client.tell("§cPosition | §fCancel > §i正在中断操作…", sender)
        else:
            self.client.tell("§cPosition | §fError > §i没有进行中的操作", sender)

    async def _cmd_status(self, sender):
        if not self.job:
            self.client.tell("§cPosition | §fError > §i没有进行中的操作", sender)
            return

        job = self.job
        elapsed = (time.time() * 1000 - job["startTime"]) / 1000
        placed = job.get("placed") or 0
        total = job.get("total") or 0
        pct = f"{(placed / total * 100):.1f}" if total > 0 else "0.0"
        cmd_placed = job.get("cmdPlaced") or 0
        cmd_speed = cmd_placed / elapsed if elapsed > 0 else 0
        eta = f"{(total - placed) / cmd_speed:.1f}" if cmd_speed > 0 else "∞"

        type_map = {"fill": "填充", "copy": "复制", "paste": "粘贴", "cut": "剪切"}
        type_ = type_map.get(job.get("type"), "未知")

        msg = f"§ePosition | §fStatus > §i{type_}\n" \
              f"§f阶段: {job.get('phase') or '未知'}\n" \
              f"§f进度: {pct}% ({placed}/{total} 步骤)"

        if job.get("blockTotal"):
            block_total = job["blockTotal"]
            block_pct = f"{(job.get('blockPlaced') or 0) / block_total * 100:.1f}" if block_total > 0 else "0.0"
            msg += f"\n§f方块: {block_pct}% ({job.get('blockPlaced') or 0}/{block_total})"

        msg += f"\n§f耗时: {elapsed:.1f}s | §f速度: {cmd_speed:.1f} 命令/s\n" \
               f"§f预计剩余: {eta}s"

        self.client.tellAll(msg)

    async def _cmd_show(self, sender):
        a = self.posA
        b = self.posB
        a_str = f"{a['x']} {a['y']} {a['z']}" if a else "无"
        b_str = f"{b['x']} {b['y']} {b['z']}" if b else "无"
        self.client.tellAll(f"§ePosition | §f[A] > §i{a_str}\n§ePosition | §f[B] > §i{b_str}")

    # ---- 作业管理 ----

    async def _with_job(self, sender, type_, fn):
        if self.job:
            self.client.tell("§cPosition | §fError > §i已有操作进行中，请等待完成或 $p:cancel 中断", sender)
            return
        self.job = {"cancelled": False, "startTime": time.time() * 1000, "type": type_}
        try:
            await fn()
        except Exception as e:
            self.client.tellAll(f"§cPosition | §fError > §i{e}")
        finally:
            self.job = None

    # ---- 填充 ----

    async def _exec_fill(self, sender, fill_block, replace_block):
        min_x = min(self.posA["x"], self.posB["x"])
        min_y = min(self.posA["y"], self.posB["y"])
        min_z = min(self.posA["z"], self.posB["z"])
        max_x = max(self.posA["x"], self.posB["x"])
        max_y = max(self.posA["y"], self.posB["y"])
        max_z = max(self.posA["z"], self.posB["z"])

        validate_y(min_y, sender)
        validate_y(max_y, sender)

        test_tick_name = "posfill_test"
        try:
            await self.client.runCommand(f"/tickingarea add {self.posA['x']} {self.posA['y']} {self.posA['z']} {self.posA['x']} {self.posA['y']} {self.posA['z']} {test_tick_name}")

            test_set = await self.client.runCommand(f"/setblock {self.posA['x']} {self.posA['y']} {self.posA['z']} {fill_block}")
            if not test_set or (test_set.get("body") or {}).get("statusCode") != 0:
                test_for = await self.client.runCommand(f"/testforblock {self.posA['x']} {self.posA['y']} {self.posA['z']} {fill_block}")
                if not test_for or (test_for.get("body") or {}).get("statusCode") != 0:
                    msg = (test_for.get("body") or {}).get("statusMessage") if test_for else None
                    self.client.tellAll(f"§cPosition | §fError > §i方块 ID 非法: {fill_block} -> {msg or '未知错误'}")
                    return

            if replace_block:
                test_replace = await self.client.runCommand(f"/setblock {self.posA['x']} {self.posA['y']} {self.posA['z']} {replace_block}")
                if not test_replace or (test_replace.get("body") or {}).get("statusCode") != 0:
                    test_for_r = await self.client.runCommand(f"/testforblock {self.posA['x']} {self.posA['y']} {self.posA['z']} {replace_block}")
                    if not test_for_r or (test_for_r.get("body") or {}).get("statusCode") != 0:
                        msg = (test_for_r.get("body") or {}).get("statusMessage") if test_for_r else None
                        self.client.tellAll(f"§cPosition | §fError > §i替换方块 ID 非法: {replace_block} -> {msg or '未知错误'}")
                        return
        except Exception as e:
            self.client.tellAll(f"§cPosition | §fError > §i方块 ID 测试异常: {e}")
            return
        finally:
            try:
                await self.client.runCommand(f"/tickingarea remove {test_tick_name}")
            except Exception:
                pass

        total_x = max_x - min_x + 1
        total_y = max_y - min_y + 1
        total_z = max_z - min_z + 1
        total_blocks = total_x * total_y * total_z

        xz_areas = compute_xz_areas(min_x, min_z, max_x, max_z)

        total_cmds = 0
        area_layers = []
        for area in xz_areas:
            x_size = (min(max_x, (area["cx2"] + 1) * CHUNK_SIZE - 1) - max(min_x, area["cx1"] * CHUNK_SIZE) + 1)
            z_size = (min(max_z, (area["cz2"] + 1) * CHUNK_SIZE - 1) - max(min_z, area["cz1"] * CHUNK_SIZE) + 1)
            area_per_y = x_size * z_size
            max_y_layers = max(1, (FILL_LIMIT - 1) // area_per_y)
            y_layers = (total_y + max_y_layers - 1) // max_y_layers
            total_cmds += y_layers
            area_layers.append({"area": area, "yLayers": y_layers, "maxYLayers": max_y_layers})

        self.job["type"] = self.job.get("type") or "fill"
        self.job["phase"] = "填充"
        self.job["placed"] = 0
        self.job["cmdPlaced"] = 0
        self.job["total"] = total_cmds
        self.job["blockTotal"] = total_blocks
        self.job["blockPlaced"] = 0

        replace_suffix = f" replace {replace_block}" if replace_block else ""

        for layer in area_layers:
            if self.job["cancelled"]:
                break

            area = layer["area"]
            abs_x1 = area["cx1"] * CHUNK_SIZE
            abs_z1 = area["cz1"] * CHUNK_SIZE
            abs_x2 = (area["cx2"] + 1) * CHUNK_SIZE - 1
            abs_z2 = (area["cz2"] + 1) * CHUNK_SIZE - 1

            fx1 = max(min_x, abs_x1)
            fz1 = max(min_z, abs_z1)
            fx2 = min(max_x, abs_x2)
            fz2 = min(max_z, abs_z2)

            for j in range(layer["yLayers"]):
                if self.job["cancelled"]:
                    break

                y_start = j * layer["maxYLayers"]
                y_end = min(y_start + layer["maxYLayers"] - 1, total_y - 1)
                abs_y1 = min_y + y_start
                abs_y2 = min_y + y_end

                tick_name = f"posfill_{int(time.time() * 1000)}_{area['cx1']}_{area['cz1']}_{j}"
                try:
                    await self.client.runCommand(f"/tickingarea add {fx1} {abs_y1} {fz1} {fx2} {abs_y2} {fz2} {tick_name}")
                except Exception as e:
                    self.client.tellAll(f"§cPosition | §fError > §i[tickingarea add] {e}")

                await self.client.sendCommand(f"/fill {fx1} {abs_y1} {fz1} {fx2} {abs_y2} {fz2} {fill_block}{replace_suffix}")
                await _sleep(10)

                try:
                    await self.client.runCommand(f"/tickingarea remove {tick_name}")
                except Exception:
                    pass

                self.job["placed"] += 1
                self.job["cmdPlaced"] += 1
                self.job["blockPlaced"] = round(total_blocks * self.job["placed"] / total_cmds) if total_cmds > 0 else 0

        if not self.job["cancelled"]:
            self.client.tellAll(f"§ePosition | §fFill > §i填充完成 {fill_block}{replace_suffix} 共 {total_blocks} 方块 {total_cmds} 条指令")
        else:
            self.client.tellAll("§cPosition | §fCancel > §i填充已中断")

    # ---- 复制 ----

    async def _exec_copy(self, sender):
        min_x = min(self.posA["x"], self.posB["x"])
        min_y = min(self.posA["y"], self.posB["y"])
        min_z = min(self.posA["z"], self.posB["z"])
        max_x = max(self.posA["x"], self.posB["x"])
        max_y = max(self.posA["y"], self.posB["y"])
        max_z = max(self.posA["z"], self.posB["z"])

        validate_y(min_y, sender)
        validate_y(max_y, sender)

        total_x = max_x - min_x + 1
        total_y = max_y - min_y + 1
        total_z = max_z - min_z + 1
        total_blocks = total_x * total_y * total_z

        # copy/cut 用于大型结构,区域大小本不应受限制
        # (单次 /structure save 的上限 64×384×64 由下方按区块 + 按 Y 分段保证)

        xz_areas = compute_xz_areas(min_x, min_z, max_x, max_z)
        structures = []

        self.job["type"] = self.job.get("type") or "copy"
        self.job["phase"] = "复制结构"
        self.job["placed"] = 0
        self.job["cmdPlaced"] = 0
        self.job["total"] = len(xz_areas)
        self.job["blockTotal"] = total_blocks

        for i, area in enumerate(xz_areas):
            if self.job["cancelled"]:
                break

            abs_x1 = area["cx1"] * CHUNK_SIZE
            abs_z1 = area["cz1"] * CHUNK_SIZE
            abs_x2 = (area["cx2"] + 1) * CHUNK_SIZE - 1
            abs_z2 = (area["cz2"] + 1) * CHUNK_SIZE - 1

            fx1 = max(min_x, abs_x1)
            fz1 = max(min_z, abs_z1)
            fx2 = min(max_x, abs_x2)
            fz2 = min(max_z, abs_z2)

            # 每个 Y 分段独立 add/remove tickingarea:
            # 单列 16×16 区块 × 48 格高度(3 区块),远小于 100 区块上限,任意高度均安全。
            height = max_y - min_y + 1
            y_segments = (height + MAX_SEG_HEIGHT - 1) // MAX_SEG_HEIGHT
            for seg in range(y_segments):
                if self.job["cancelled"]:
                    break

                ys = min_y + seg * MAX_SEG_HEIGHT
                ye = min(ys + MAX_SEG_HEIGHT - 1, max_y)
                tick_name = f"copy_{i}_{seg}"
                try:
                    await self.client.runCommand(f"/tickingarea add {fx1} {ys} {fz1} {fx2} {ye} {fz2} {tick_name}")
                except Exception as e:
                    self.client.tellAll(f"§cPosition | §fError > §i[tickingarea add] {e}")

                struct_name = f"Copy_{i}_{seg}"
                save_ok = False
                try:
                    result = await self.client.runCommand(f"/structure save {struct_name} {fx1} {ys} {fz1} {fx2} {ye} {fz2} true disk")
                    if result and (result.get("body") or {}) and (result.get("body") or {}).get("statusCode") != 0:
                        self.client.tellAll(f"§cPosition | §fError > §i[structure save] {struct_name}: {result['body']['statusMessage']}")
                    else:
                        save_ok = True
                except Exception as e:
                    self.client.tellAll(f"§cPosition | §fError > §i[structure save] {struct_name}: {e}")

                try:
                    await self.client.runCommand(f"/tickingarea remove {tick_name}")
                except Exception:
                    pass

                if not self.job["cancelled"] and save_ok:
                    structures.append({
                        "name": struct_name,
                        "saveX": fx1,
                        "saveY": ys,
                        "saveZ": fz1,
                        "sizeX": fx2 - fx1 + 1,
                        "sizeY": ye - ys + 1,
                        "sizeZ": fz2 - fz1 + 1,
                        "offsetX": fx1 - self.posA["x"],
                        "offsetY": ys - self.posA["y"],
                        "offsetZ": fz1 - self.posA["z"],
                    })
                    self.job["cmdPlaced"] += 1

            self.job["placed"] += 1

        if not self.job["cancelled"]:
            self.lastCopyEntry = {
                "regionMinX": min_x,
                "regionMinY": min_y,
                "regionMaxY": max_y,
                "regionMinZ": min_z,
                "regionMaxX": max_x,
                "regionMaxZ": max_z,
                "structures": structures,
            }
            self.client.tellAll(f"§ePosition | §fCopy > §i复制完成 共 {len(structures)} 个结构")
        else:
            for s in structures:
                try:
                    await self.client.runCommand(f"/structure delete {s['name']}")
                except Exception:
                    pass
            self.client.tellAll("§cPosition | §fCancel > §i复制已中断")

    # ---- 粘贴 ----

    async def _exec_paste(self, sender, origin):
        if not self.lastCopyEntry:
            self.client.tell("§cPosition | §fError > §i没有可粘贴的复制结构，请先使用 $p:copy", sender)
            return

        entry = self.lastCopyEntry

        total_y_paste = entry["regionMaxY"] - entry["regionMinY"] + 1
        paste_min_y = origin["y"] + (entry["structures"][0].get("offsetY") if entry["structures"] else 0)
        paste_max_y = paste_min_y + total_y_paste - 1
        if paste_min_y < Y_MIN or paste_max_y > Y_MAX:
            self.client.tell(f"§cPosition | §fError > §i粘贴位置 Y 超出范围: {paste_min_y} ~ {paste_max_y} (允许 {Y_MIN} ~ {Y_MAX})", sender)
            return

        error_count = 0
        total = len(entry["structures"])

        self.job["type"] = self.job.get("type") or "paste"
        self.job["phase"] = "粘贴结构"
        self.job["total"] = total
        self.job["placed"] = 0
        self.job["cmdPlaced"] = 0

        for i, s in enumerate(entry["structures"]):
            if self.job["cancelled"]:
                break

            load_x = origin["x"] + s["offsetX"]
            load_y = origin["y"] + s["offsetY"]
            load_z = origin["z"] + s["offsetZ"]

            tick_x1 = load_x
            tick_z1 = load_z
            tick_x2 = load_x + (s.get("sizeX") or (entry["regionMaxX"] - entry["regionMinX"] + 1)) - 1
            tick_z2 = load_z + (s.get("sizeZ") or (entry["regionMaxZ"] - entry["regionMinZ"] + 1)) - 1
            tick_y1 = max(load_y, Y_MIN)
            tick_y2 = min(load_y + (s.get("sizeY") or (entry["regionMaxY"] - entry["regionMinY"])) - 1, Y_MAX)

            tick_name = f"paste_{i}"
            if tick_y1 <= tick_y2:
                try:
                    await self.client.runCommand(f"/tickingarea add {tick_x1} {tick_y1} {tick_z1} {tick_x2} {tick_y2} {tick_z2} {tick_name}")
                except Exception as e:
                    self.client.tellAll(f"§cPosition | §fError > §i[tickingarea add] {e}")

            try:
                result = await self.client.runCommand(f"/structure load {s['name']} {load_x} {load_y} {load_z}")
                if result and (result.get("body") or {}) and (result.get("body") or {}).get("statusCode") != 0:
                    self.client.tellAll(f"§cPosition | §fError > §i[structure load] {s['name']}: {result['body']['statusMessage']}")
                    error_count += 1
            except Exception as e:
                self.client.tellAll(f"§cPosition | §fError > §i[structure load] {s['name']}: {e}")
                error_count += 1

            try:
                await self.client.runCommand(f"/tickingarea remove {tick_name}")
            except Exception:
                pass

            self.job["placed"] += 1
            self.job["cmdPlaced"] += 1
            await _sleep(10)

        if not self.job["cancelled"] and error_count == 0:
            for s in entry["structures"]:
                try:
                    await self.client.runCommand(f"/structure delete {s['name']}")
                except Exception:
                    pass
            self.lastCopyEntry = None
            self.client.tellAll(f"§ePosition | §fPaste > §i粘贴完成 共 {total} 个结构")
        elif not self.job["cancelled"]:
            self.client.tellAll(f"§cPosition | §fError > §i粘贴完成 失败 {error_count} 个结构，请重试")
        else:
            self.client.tellAll("§cPosition | §fCancel > §i粘贴已中断")

    def onDestroy(self):
        if self.job:
            self.job["cancelled"] = True
        self.job = None
        self.posA = None
        self.posB = None
        self.lastCopyEntry = None
        self.client = None
