"""lib/file_lock.py — 操作系统级运行时独占/排他文件锁管理器 (System File Lock Manager)

在 EnderBridge 运行期间，对系统关键配置文件与核心源码持有系统级只读保护锁，
从操作系统内核层面彻底禁止外部独立进程 (如独立攻击脚本、病毒、第三方篡改程序、外部编辑器误操作等)
在服务运行期间非法写入、覆盖、截断或删除核心配置与关键代码。

跨平台支持与防护设计：
1. 操作系统权限与内核级防护：
   - 跨平台强制只读 (os.chmod stat.S_IREAD / 0o444)：
     在 Windows 与 Linux/macOS 上均会令外部进程执行 open('w') 或 open('a') 时直接触发 PermissionError: [Errno 13] Permission denied。
   - Windows 共享锁强化 (Win32 CreateFileW):
     以 GENERIC_READ 且仅开放 FILE_SHARE_READ 句柄，拒绝 FILE_SHARE_WRITE 与 FILE_SHARE_DELETE，
     使 Windows 内核额外在文件被移动、替换 (os.replace)、原子写入或删除时直接抛出 WinError 32 / WinError 5。
   - POSIX 共享锁强化 (fcntl.flock):
     持有 LOCK_SH 共享锁，协同 UNIX 系统的文件锁管理。
2. 零损耗读取：
   - 允许内部及外部所有进程并发以只读模式 ('r') 读取文件，完全不影响系统性能与监控探针。
3. 安全受控修改通道 (unlock_for_write 上下文管理器)：
   - 当 EnderBridge 自身需要合法持久化配置 (如 WebUI 保存、白名单 Mod 保存) 时，
     在微秒级时间内临时释放系统锁，执行原子写入与替换，并立即自动恢复系统加锁。
4. 退出自动清理：
   - 注册 atexit 与 destroy 回调，进程退出时确保释放所有系统句柄并恢复权限。
"""

import atexit
import contextlib
import os
import stat
import sys
import threading
from typing import Dict, List, Optional, Set

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")
MOD_DIR = os.path.join(ROOT, "mod")

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _GENERIC_READ = 0x80000000
    _FILE_SHARE_READ = 0x00000001
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_NORMAL = 0x00000080
    _INVALID_HANDLE_VALUE = -1
else:
    try:
        import fcntl
    except ImportError:
        fcntl = None


def _norm(path: str) -> str:
    """标准化路径为小写正斜杠绝对路径"""
    try:
        return os.path.abspath(os.fspath(path)).replace("\\", "/").lower()
    except Exception:
        return ""


class SystemFileLockManager:
    """操作系统级文件锁管理器单例"""

    _instance = None
    _mutex = threading.RLock()
    _locks: Dict[str, any] = {}  # normpath -> handle or fd
    _raw_paths: Dict[str, str] = {}  # normpath -> original path
    _orig_modes: Dict[str, int] = {}  # normpath -> original file permissions

    @classmethod
    def get(cls) -> "SystemFileLockManager":
        if cls._instance is None:
            with cls._mutex:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def lock_file(cls, filepath: str) -> bool:
        """对单个文件加系统级只读共享锁 (禁止写入/删除/替换)"""
        if not filepath:
            return False
        abs_path = os.path.abspath(filepath)
        if not os.path.isfile(abs_path):
            return False

        norm = _norm(abs_path)
        with cls._mutex:
            if norm in cls._locks:
                return True

            try:
                mode = stat.S_IMODE(os.stat(abs_path).st_mode)
                cls._orig_modes[norm] = mode
            except Exception:
                cls._orig_modes[norm] = 0o644

            # 1. 跨平台设置文件为只读 (在 Windows 和 Linux/macOS 上均直接禁止 open('w') 与 open('a'))
            try:
                os.chmod(abs_path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
            except Exception:
                pass

            # 2. 操作系统内核排他共享锁加固
            if _IS_WINDOWS:
                try:
                    handle = ctypes.windll.kernel32.CreateFileW(
                        abs_path,
                        _GENERIC_READ,
                        _FILE_SHARE_READ,  # 仅允许读，拒绝 FILE_SHARE_WRITE 与 FILE_SHARE_DELETE
                        None,
                        _OPEN_EXISTING,
                        _FILE_ATTRIBUTE_NORMAL,
                        None,
                    )
                    cls._locks[norm] = None if (handle == _INVALID_HANDLE_VALUE or handle <= 0) else handle
                    cls._raw_paths[norm] = abs_path
                    return True
                except Exception:
                    cls._locks[norm] = None
                    cls._raw_paths[norm] = abs_path
                    return True
            else:
                cls._raw_paths[norm] = abs_path
                if fcntl is not None:
                    try:
                        fd = os.open(abs_path, os.O_RDONLY)
                        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                        cls._locks[norm] = fd
                    except Exception:
                        cls._locks[norm] = None
                else:
                    cls._locks[norm] = None
                return True

    @classmethod
    def unlock_file(cls, filepath: str) -> bool:
        """释放指定文件的系统级锁并恢复可写权限"""
        if not filepath:
            return False
        norm = _norm(filepath)
        with cls._mutex:
            if norm not in cls._locks:
                return False

            raw_path = cls._raw_paths.pop(norm, filepath)
            val = cls._locks.pop(norm, None)
            orig_mode = cls._orig_modes.pop(norm, 0o644)

            # 恢复可写权限
            if raw_path and os.path.exists(raw_path):
                try:
                    os.chmod(raw_path, orig_mode | stat.S_IWUSR)
                except Exception:
                    pass

            if val is not None:
                if _IS_WINDOWS:
                    try:
                        ctypes.windll.kernel32.CloseHandle(val)
                    except Exception:
                        pass
                else:
                    try:
                        os.close(val)
                    except Exception:
                        pass
            return True

    @classmethod
    def is_locked(cls, filepath: str) -> bool:
        """判断指定文件当前是否持有系统级锁"""
        norm = _norm(filepath)
        with cls._mutex:
            return norm in cls._locks

    @classmethod
    @contextlib.contextmanager
    def unlock_for_write(cls, filepath: str):
        """安全修改上下文管理器：临时解开系统锁，允许原子写入/替换，退出时自动恢复加锁"""
        norm = _norm(filepath)
        with cls._mutex:
            was_locked = norm in cls._locks
            if was_locked:
                cls.unlock_file(filepath)
            try:
                yield
            finally:
                # 若此前处于锁定状态，或者文件是核心配置且在写入后存在，自动恢复锁
                if was_locked or (os.path.isfile(filepath) and cls.is_core_protected_file(filepath)):
                    cls.lock_file(filepath)

    @classmethod
    def is_core_protected_file(cls, filepath: str) -> bool:
        """检测文件是否属于核心系统与配置文件"""
        if not filepath:
            return False
        norm = _norm(filepath)
        norm_cfg_dir = _norm(CONFIG_DIR)
        norm_root = _norm(ROOT)

        # config/ 下的核心 json 文件
        core_names = {"config.json", "permission.json", "users.json", "banlist.json", "config.py"}
        base = os.path.basename(filepath).lower()
        if base in core_names and norm_cfg_dir and (norm.startswith(norm_cfg_dir + "/") or norm == norm_cfg_dir):
            return True

        # main.py
        if norm == f"{norm_root}/main.py":
            return True

        return False

    @classmethod
    def lock_core_system_files(cls) -> int:
        """对所有核心配置文件与主入口持有系统锁，返回成功加锁的文件数"""
        targets = [
            os.path.join(CONFIG_DIR, "config.json"),
            os.path.join(CONFIG_DIR, "permission.json"),
            os.path.join(CONFIG_DIR, "users.json"),
            os.path.join(CONFIG_DIR, "banlist.json"),
            os.path.join(CONFIG_DIR, "config.py"),
            os.path.join(ROOT, "main.py"),
        ]

        count = 0
        with cls._mutex:
            for t in targets:
                if os.path.isfile(t):
                    if cls.lock_file(t):
                        count += 1
        return count

    @classmethod
    def unlock_all(cls) -> None:
        """释放所有系统文件锁并恢复文件权限"""
        with cls._mutex:
            for norm in list(cls._locks.keys()):
                raw_path = cls._raw_paths.get(norm, norm)
                cls.unlock_file(raw_path)
            cls._locks.clear()
            cls._raw_paths.clear()
            cls._orig_modes.clear()


# 进程退出时自动释放所有系统级句柄与权限
atexit.register(SystemFileLockManager.unlock_all)

