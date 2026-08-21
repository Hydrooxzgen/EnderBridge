"""音乐播放 Mod

解析 MIDI/JSON 音乐文件并在游戏内播放(基于 playsound 命令)
"""
import asyncio
import json
import os
import random
import re
import time

import mido

from config import basePath, features
from lib.command import Command

# MIDI 解析工具函数

MAIN_VOL_FACTOR = 0.9
SUB_VOL_FACTOR = 0.7


def sanitize_music_name(file_name):
    """文件名合法性校验(路径穿越防护)

    拒绝含路径分隔符、以 . 开头(含 ..)或过长的文件名
    """
    if not isinstance(file_name, str) or not file_name:
        return None
    if len(file_name) > 100:
        return None
    if file_name != os.path.basename(file_name):
        return None  # 含目录成分
    if re.search(r"[\\/]", file_name):
        return None  # 路径分隔符
    if file_name.startswith("."):
        return None  # . .. .hidden
    return file_name


def get_sound_string(program, percussion=False):
    if not percussion:
        if program == 105:
            return "note.banjo"
        if program in (32, 33, 34, 35, 36, 37, 38, 39):
            return "note.bass"
        if program in (115, 116, 117, 118):
            return "note.basedrum"
        if program == 9:
            return "note.bell"
        if program in (80, 81):
            return "note.bit"
        if program == 112:
            return "note.cow_bell"
        if program in (72, 73, 74, 75, 76, 77, 78, 79, 41, 42, 43, 44):
            return "note.flute"
        if program in (24, 25, 26, 27, 28, 29, 30, 31):
            return "note.guitar"
        if program == 14:
            return "note.chime"
        if program in (8, 9, 10, 11, 12, 13, 15):
            return "note.iron_xylophone"
        if program == 2:
            return "note.pling"
        return "note.harp"
    else:
        if program == 55:
            return "note.cow_bell"
        if program in (41, 43, 45):
            return "note.hat"
        if program in (36, 37, 39):
            return "note.snare"
        return "note.bd"


def map_instrument(channel, program, note):
    if channel == 9 or channel == 10:
        return get_sound_string(note, True)
    return get_sound_string(program, False)


def midi_to_minecraft_pitch(midi_note):
    if midi_note < 0 or midi_note > 127:
        return 1.0
    semitone_offset = midi_note - 66
    return 2 ** (semitone_offset / 12)


def parse_midi_file(file_path, file_name, play_percussion):
    """解析 MIDI 文件为音轨数据"""
    mid = mido.MidiFile(file_path)
    if not mid.tracks:
        raise ValueError("无法解析 MIDI 文件")

    ppq = mid.ticks_per_beat or 480
    if not isinstance(ppq, int) or ppq <= 0:
        raise ValueError(f"无效的 PPQ 值: {ppq}")

    current_tempo = 500000
    notes = []
    channel_programs = {}

    for track_idx, track in enumerate(mid.tracks):
        time_sec = 0.0
        for event in track:
            delta_ticks = getattr(event, "time", 0) or 0
            delta_sec = (delta_ticks / ppq) * (current_tempo / 1000000)
            time_sec += delta_sec

            etype = event.type
            if etype == "note_on" and event.velocity > 0:
                channel = event.channel
                note = event.note
                velocity = event.velocity

                volume_factor = MAIN_VOL_FACTOR if channel == 0 else SUB_VOL_FACTOR
                volume = round(velocity / 100 * volume_factor, 5)

                if (channel == 9 or channel == 10) and not play_percussion:
                    continue

                pitch = midi_to_minecraft_pitch(note)
                program_key = f"{track_idx}-{channel}"
                program = channel_programs.get(program_key, 0)
                instrument = map_instrument(channel, program, note)

                notes.append({
                    "time": round(time_sec, 3),
                    "instrument": instrument,
                    "volume": volume,
                    "pitch": round(pitch, 5),
                })
            elif etype == "program_change":
                program_key = f"{track_idx}-{event.channel}"
                channel_programs[program_key] = event.program
            elif etype == "set_tempo":
                current_tempo = event.tempo

    notes.sort(key=lambda n: n["time"])
    first_time = notes[0]["time"] if notes else 0
    track_array = [
        [round(n["time"] - first_time, 3), n["instrument"], n["volume"], n["pitch"]]
        for n in notes
    ]

    title_without_ext = re.sub(r"\.[^/.]+$", "", file_name)
    return {"title": title_without_ext, "tracks": track_array}


class Mod:
    """音乐播放 Mod(客户端)"""

    def __init__(self, client):
        self.client = client
        self.title = None
        self.tracks = None
        self.files = []
        self.index = 0
        self.progress = 0
        self.running = False
        self.looping = False
        self.loop_mode = None
        self._files_cache_time = 0
        # 当前活跃任务(播放/循环),用于 stop 取消
        self._active_task = None
        self._loop_task = None
        self.playPercussion = bool((features.get("music") or {}).get("playPercussion", True))

    def onCommand(self):
        return {
            "normal": [
                Command.create("music", "音乐播放命令（方法: join/exit/status/list/search/percussion/run/next/random/loop/stop）")
                .add_string("方法", False)
                .add_optional_string("参数1")
                .add_optional_string("参数2")
                .add_optional_string("参数3")
                .add_optional_string("参数4")
                .add_optional_string("参数5")
                .set_func(self._cmd_music),
            ],
        }

    # ---- 命令分发器 ----

    # (方法, 参数格式, 说明, 所需权限等级)
    MUSIC_METHODS = [
        ("join", "", "加入音乐收听", 0),
        ("exit", "", "退出音乐收听", 0),
        ("status", "", "查看当前播放进度", 0),
        ("list", "[页码]", "查看音乐列表", 0),
        ("search", "[关键词] [页码]", "搜索音乐文件", 0),
        ("percussion", "<on|off>", "开启/关闭打击乐器", 0),
        ("run", "<音乐文件名>", "快速播放指定音乐", 1),
        ("next", "", "切换到下一首音乐", 1),
        ("random", "", "随机播放音乐", 1),
        ("loop", "<next|random|single> [歌名]", "设置循环播放模式", 1),
        ("stop", "[music|loop|all]", "停止播放（不带参数停止全部）", 1),
    ]

    async def _cmd_music(self, sender, method, p1=None, p2=None, p3=None, p4=None, p5=None):
        """$music 方法分发器(方法内做权限检查)"""
        if method is None:
            self.client.tell(f"§cMusic | §fError > §i未知方法: 未指定（输入 {Command.command_prefix}music help 查看全部方法）", sender)
            return

        # help 显示本模组方法列表
        if method == "help":
            lines = "\n".join(
                f"§a{Command.command_prefix}music {mname}{' ' + margs if margs else ''} §7- §f{mdesc}"
                for mname, margs, mdesc, _l in self.MUSIC_METHODS
            )
            self.client.tell(f"§eMusic | §fHelp > §7可用方法\n{lines}", sender)
            return

        # 查询方法所需权限
        required = None
        for mname, _args, _desc, plevel in self.MUSIC_METHODS:
            if mname == method:
                required = plevel
                break
        if required is None:
            self.client.tell(f"§cMusic | §fError > §i未知方法: {method}（输入 {Command.command_prefix}music help 查看全部方法）", sender)
            return

        # 权限检查
        from lib.permission import PermissionManager
        perm = await PermissionManager.query(sender)
        if isinstance(perm, Exception):
            self.client.tell("§cMusic | §fError > §i权限查询失败", sender)
            return
        if perm < required:
            self.client.tell("§cMusic | §fError > §i权限不足", sender)
            return

        # 分发到具体实现
        if method == "join":
            await self._cmd_join(sender)

        elif method == "exit":
            await self._cmd_exit(sender)

        elif method == "status":
            await self._cmd_status(sender)

        elif method == "list":
            page = None
            if p1 is not None:
                try:
                    page = int(p1)
                except ValueError:
                    self.client.tell(f'§cMusic | §fError > §i"{p1}" 处应为整型', sender)
                    return
            await self._cmd_list(sender, page)

        elif method == "search":
            page = None
            if p2 is not None:
                try:
                    page = int(p2)
                except ValueError:
                    self.client.tell(f'§cMusic | §fError > §i"{p2}" 处应为整型', sender)
                    return
            await self._cmd_search(sender, p1, page)

        elif method == "percussion":
            if p1 is None:
                self.client.tell(f"§cMusic | §fError > §i参数不足：{Command.command_prefix}music percussion <on|off>", sender)
                return
            if p1 not in ("on", "off"):
                self.client.tell(f'§cMusic | §fError > §i"{p1}" 处应为枚举 on, off', sender)
                return
            await self._cmd_percussion(sender, p1)

        elif method == "run":
            if p1 is None:
                self.client.tell(f"§cMusic | §fError > §i参数不足：{Command.command_prefix}music run <音乐文件名>", sender)
                return
            await self._cmd_run(sender, p1)

        elif method == "next":
            await self._cmd_next(sender)

        elif method == "random":
            await self._cmd_random(sender)

        elif method == "loop":
            if p1 is None:
                self.client.tell(f"§cMusic | §fError > §i参数不足：{Command.command_prefix}music loop <next|random|single> [歌名]", sender)
                return
            if p1 not in ("next", "random", "single"):
                self.client.tell(f'§cMusic | §fError > §i"{p1}" 处应为枚举 next, random, single', sender)
                return
            await self._cmd_loop(sender, p1, p2)

        elif method == "stop":
            mode = p1
            if mode is not None and mode not in ("music", "loop", "all"):
                self.client.tell(f'§cMusic | §fError > §i"{mode}" 处应为枚举 music, loop, all', sender)
                return
            await self._cmd_stop(sender, mode)

    # ---- 命令实现 ----

    async def _cmd_join(self, commander):
        await self.client.sendCommand(f'tag @a[name="{commander}"] remove non-listener')
        self.client.tell("§eMusic | §fJoin > §i已加入收听音乐~", commander)

    async def _cmd_exit(self, commander):
        await self.client.sendCommand(f'tag @a[name="{commander}"] add non-listener')
        self.client.tell("§eMusic | §fExit > §i已退出收听音乐~", commander)

    async def _cmd_status(self, commander):
        self.status(commander)

    async def _cmd_list(self, commander, page):
        await self.show(10, page, commander)

    async def _cmd_search(self, commander, keyword, page):
        await self.search(keyword, 10, page, commander)

    async def _cmd_percussion(self, commander, mode):
        self.playPercussion = mode == "on"
        self.client.tell(f"§eMusic | §fPercussion > §i已{'开启' if self.playPercussion else '关闭'}", commander)

    async def _cmd_run(self, _, file_name):
        # 播放是长任务,fire-and-forget
        asyncio.get_running_loop().create_task(self.fastrun(file_name))

    async def _cmd_next(self, _):
        asyncio.get_running_loop().create_task(self.next())

    async def _cmd_random(self, _):
        asyncio.get_running_loop().create_task(self.random())

    async def _cmd_loop(self, commander, mode, file_name):
        if mode == "single":
            if file_name:
                asyncio.get_running_loop().create_task(self.fastrun(file_name))
            else:
                asyncio.get_running_loop().create_task(self.single_loop())
        else:
            if file_name:
                self.client.tell("§cMusic | §fError > §i非 single 模式不支持指定歌名", commander)
                return
            if mode == "next":
                asyncio.get_running_loop().create_task(self.next_loop())
            elif mode == "random":
                asyncio.get_running_loop().create_task(self.random_loop())

    async def _cmd_stop(self, _, mode):
        if mode is None or mode == "all":
            await self.stop_all()
        if mode == "music":
            self.stop()
        if mode == "loop":
            await self.stop_loop()

    # ---- 列表管理 ----

    def set(self, number):
        if isinstance(number, int):
            self.index = number
            return True
        if isinstance(number, str) and re.match(r"^[-+]?\d+$", number):
            self.index = int(number)
            return True
        return False

    async def get(self):
        try:
            files = os.listdir(basePath["music"])
        except Exception as error:
            self.client.tell(f"§cMusic | §fError > §i获取目录失败: {error}")
            raise ValueError("目录获取失败")

        # 过滤 .json 和 .mid 文件,按文件名去重(优先保留 .json)
        music_files = [f for f in files if re.search(r"\.(json|mid)$", f, re.I)]
        name_map = {}
        for file_ in music_files:
            base_name = re.sub(r"\.(json|mid)$", "", file_, flags=re.I)
            if base_name not in name_map:
                name_map[base_name] = file_
            else:
                existing = name_map[base_name]
                if existing.lower().endswith(".mid") and file_.lower().endswith(".json"):
                    name_map[base_name] = file_

        # 排序:readdir 返回顺序由文件系统决定,若不排序会导致 music list 顺序每次不同(显示错乱)
        self.files = sorted(
            name_map.values(),
            key=lambda f: re.sub(r"\.(json|mid)$", "", f, flags=re.I).lower(),
        )
        self._files_cache_time = time.time() * 1000
        self.reset()

    async def safeget(self):
        now = time.time() * 1000
        if len(self.files) > 0 and (now - self._files_cache_time) < 30000:
            return True
        try:
            await self.get()
            return True
        except Exception:
            return False

    async def test(self):
        if not self.files or len(self.files) == 0:
            await self.safeget()
        if 0 <= self.index < len(self.files):
            return True
        return False

    def reset(self):
        self.set(0)

    def load(self, file_name):
        """加载音乐文件(返回成功消息字符串)"""
        # 路径穿越防护:只允许单层合法文件名
        safe_name = sanitize_music_name(file_name)
        if not safe_name:
            self.client.tell(f"§cMusic | §fError > §i非法的文件名: {file_name}")
            raise ValueError("非法的文件名")
        file_name = safe_name

        music_dir = basePath["music"]
        if file_name.lower().endswith(".json") or file_name.lower().endswith(".mid"):
            file_path = os.path.join(music_dir, file_name)
        else:
            json_path = os.path.join(music_dir, file_name + ".json")
            mid_path = os.path.join(music_dir, file_name + ".mid")
            if os.path.exists(json_path):
                file_path = json_path
            elif os.path.exists(mid_path):
                file_path = mid_path
            else:
                file_path = json_path

        ext = os.path.splitext(file_path)[1].lower()

        if ext == ".mid":
            try:
                data = parse_midi_file(file_path, os.path.basename(file_path), self.playPercussion)
                self.title = data["title"]
                self.tracks = data["tracks"]
                return "音乐加载成功"
            except Exception as error:
                self.client.tell(f"§cMusic | §fError > §iMIDI 加载失败: {error}")
                raise ValueError("MIDI 加载失败")
        else:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    file = f.read()
            except Exception as error:
                self.client.tell(f"§cMusic | §fError > §i音乐加载失败: {error}")
                raise ValueError("音乐加载失败")
            try:
                data = json.loads(file)
                self.title = data.get("title") if isinstance(data, dict) else None
                self.tracks = data.get("tracks") if isinstance(data, dict) else None
                return "音乐加载成功"
            except Exception as parse_error:
                self.client.tell(f"§cMusic | §fError > §iJSON 解析失败: {parse_error}")
                raise ValueError("JSON 解析失败")

    # ---- 播放 ----

    def stop(self):
        if not self.running:
            self.client.tell("§cMusic | §fError > §i音乐进程不存在")
            return
        task = self._active_task
        self.running = False
        if task:
            task.cancel()
        self.client.tell("§eMusic | §fStop > §i音乐进程已取消")

    async def run(self):
        if not self.title or not self.tracks:
            self.client.tell("§cMusic | §fError > §i音乐文件不存在")
            return
        if self.running:
            self.client.tell("§cMusic | §fError > §i音乐进程已存在")
            return

        self.running = True
        self._active_task = asyncio.current_task()
        self.client.tell(f"§eMusic | §fPlay > §i正在播放 {self.title}")

        start_time = time.time()

        try:
            for track in self.tracks:
                if not self.running:
                    return

                t, timbre, volume, pitch = track

                now_time = time.time()
                sleep_time = t - (now_time - start_time)

                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

                if sleep_time < -1:
                    self.client.tell(f"§cMusic | §fError > §i播放超时: {sleep_time}")
                if not self.running:
                    return

                await self.client.sendCommand(f"/execute as @a[tag=!non-listener] at @s run playsound {timbre} @s ~ ~ ~ {volume} {pitch}")
                self.progress += 1

            self.client.tell(f"§eMusic | §fPlay > §i{self.title} 播放完成")
            self.progress = 0
        except asyncio.CancelledError:
            return
        except Exception as error:
            self.client.tell(f"§cMusic | §fError > §i播放错误: {error}")
        finally:
            self.running = False
            self._active_task = None

    async def fastrun(self, file_name):
        try:
            await self.load(file_name)
            await self.run()
        except Exception:
            return

    async def indexrun(self, number=None):
        if number is None:
            number = self.index
        if not self.set(number):
            self.client.tell("§cMusic | §fError > §iIndex 加载失败")
            return False
        if not await self.test():
            self.client.tell("§cMusic | §fError > §iIndex 非法")
            return False
        await self.fastrun(self.files[self.index])
        return True

    async def next(self):
        if not await self.test():
            self.client.tell("§cMusic | §fError > §iIndex 非法")
            return False
        # 先推进到下一首再播放(与命令描述"切换到下一首"一致)
        self.index = (self.index + 1) % len(self.files)
        # 播放中切换需先停止当前歌曲,否则 run() 会因 running 直接返回
        if self.running:
            self.stop()
        await self.indexrun()
        return True

    async def random(self):
        await self.safeget()
        if len(self.files) == 0:
            self.client.tell("§cMusic | §fError > §i音乐文件列表为空")
            return
        self.index = random.randrange(len(self.files))
        # 播放中切换需先停止当前歌曲
        if self.running:
            self.stop()
        await self.indexrun()

    def _validate_loop_time(self, time_):
        if not (isinstance(time_, str) and re.match(r"^[-+]?\d+$", time_)) and not isinstance(time_, (int, float)):
            self.client.tell("§cMusic | §fError > §i循环时间错误")
            return False
        return True

    async def start_loop(self, mode, time_=5):
        if self.looping:
            self.client.tell("§eMusic | §fLoop > §i循环已存在")
            return
        if not self._validate_loop_time(time_):
            return

        if mode == "single" and (not self.title or not self.tracks):
            self.client.tell("§cMusic | §fError > §i请先播放一首音乐再启用单曲循环")
            return

        int_time = int(time_) * 1000
        mode_labels = {"next": "顺序循环", "random": "随机循环", "single": "单曲循环"}
        mode_label = mode_labels.get(mode, mode)
        display_title = f" {self.title}" if mode == "single" else ""
        self.client.tell(f"§eMusic | §fLoop > §i{mode_label}{display_title}已启用")

        self.looping = True
        self.loop_mode = mode
        self._loop_task = asyncio.get_running_loop().create_task(self._loop_worker(mode, int_time))

    async def _loop_worker(self, mode, int_time):
        try:
            while self.looping:
                if mode == "next":
                    await self.next()
                elif mode == "random":
                    await self.random()
                elif mode == "single":
                    await self.run()
                if not self.looping:
                    break
                await asyncio.sleep(int_time / 1000)
        except asyncio.CancelledError:
            pass
        finally:
            self.looping = False
            self.loop_mode = None
            self._loop_task = None

    async def next_loop(self, time_=5):
        await self.start_loop("next", time_)

    async def random_loop(self, time_=5):
        await self.start_loop("random", time_)

    async def single_loop(self, time_=5):
        await self.start_loop("single", time_)

    async def stop_loop(self):
        if self.looping:
            self.looping = False
            self.loop_mode = None
            if self._loop_task:
                self._loop_task.cancel()
                self._loop_task = None
            self.client.tell("§eMusic | §fLoop > §i循环已禁用")
        else:
            self.client.tell("§cMusic | §fError > §i循环不存在")

    async def stop_all(self):
        if self.looping:
            await self.stop_loop()
        if self.running:
            self.stop()

    # ---- 查询展示 ----

    def status(self, cmder="@a"):
        if not self.running:
            self.client.tell("§cMusic | §fError > §i无音乐播放")
            return
        self.client.tell(f"§eMusic | §fStatus > §i正在播放 {self.title} -> {self.progress} / {len(self.tracks)}", cmder)

    async def show(self, page_size, page_number, cmder=None):
        await self.safeget()
        if len(self.files) == 0:
            self.client.tell("§cMusic | §fError > §i音乐文件列表为空", cmder)
            return []

        total_pages = (len(self.files) + page_size - 1) // page_size
        if not page_number or page_number < 1:
            page_number = 1
        if page_number > total_pages:
            page_number = total_pages

        start_index = (page_number - 1) * page_size
        end_index = start_index + page_size
        page_files = self.files[start_index:end_index]

        header = f"§eMusic | §fList > §i第{page_number}/{total_pages}页 共 {len(self.files)} 首"
        items = []
        for i, f in enumerate(page_files):
            name = re.sub(r"\.(json|mid)$", "", f, flags=re.I)
            num = str(start_index + i + 1).rjust(2)
            size = "?"
            try:
                size = self.format_size(os.path.getsize(os.path.join(basePath["music"], f)))
            except Exception:
                pass
            items.append(f"{num}. §b{name} §f{size}")

        self.client.tell(f"{header}\n{chr(10).join(items)}", cmder)
        return page_files

    async def search(self, keyword, page_size=10, page_number=1, cmder=None):
        await self.safeget()
        if len(self.files) == 0:
            self.client.tell("§cMusic | §fError > §i音乐文件列表为空", cmder)
            return

        lower_keyword = keyword.lower()
        matched = [f for f in self.files if lower_keyword in f.lower()]

        if len(matched) == 0:
            self.client.tell(f'§cMusic | §fError > §i未找到包含 "{keyword}" 的音乐', cmder)
            return

        total_pages = (len(matched) + page_size - 1) // page_size
        if not page_number or page_number < 1:
            page_number = 1
        if page_number > total_pages:
            page_number = total_pages

        start_index = (page_number - 1) * page_size
        end_index = start_index + page_size
        page_files = matched[start_index:end_index]

        header = f'§eMusic | §fSearch > §i"{keyword}" 第{page_number}/{total_pages}页 共 {len(matched)} 首'
        items = []
        for i, f in enumerate(page_files):
            name = re.sub(r"\.(json|mid)$", "", f, flags=re.I)
            num = str(start_index + i + 1).rjust(2)
            size = "?"
            try:
                size = self.format_size(os.path.getsize(os.path.join(basePath["music"], f)))
            except Exception:
                pass
            items.append(f"{num}. {name} §f{size}")

        self.client.tell(f"{header}\n{chr(10).join(items)}", cmder)

    def format_size(self, bytes_):
        if bytes_ < 1024:
            return f"{bytes_}B"
        if bytes_ < 1024 * 1024:
            return f"{bytes_ / 1024:.1f}KB"
        return f"{bytes_ / (1024 * 1024):.1f}MB"

    def onDestroy(self):
        # 同步清理:取消任务
        if self._loop_task:
            self._loop_task.cancel()
            self._loop_task = None
        if self.running:
            task = self._active_task
            self.running = False
            if task:
                task.cancel()
        self.client = None
        self.title = None
        self.tracks = None
        self.files = []
        self.index = 0
        self.loop_mode = None
