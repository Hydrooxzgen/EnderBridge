"""lib/security_guard.py — 核心系统与配置文件安全防护卫士 (Security Guard)

使用 Python C 运行时底层审计挂钩 (PEP 578 sys.addaudithook)，
在解释器级别全面拦截第三方 Mod 对系统核心文件与配置目录 (config/) 的非法篡改、写入与删除。

防护范围：
1. config/ 目录下的所有文件 (config.json, users.json, permission.json, banlist.json 等)
2. 项目核心关键文件 (main.py, .noneeds, lib/, webui/, version_manager/)
拦截方式：
在 open (写/追加/创建/截断)、os.remove、os.unlink、os.rmdir、os.rename、os.replace、os.truncate 等 C 级事件触发时，
向上遍历调用帧栈。若检测到调用链源自 mod/ 目录下的非授权第三方模块，则直接抛出 PermissionError 实施阻断。
"""

import os
import sys
import threading
from typing import Optional, Set, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")
MOD_DIR = os.path.join(ROOT, "mod")

_installed = False
_install_lock = threading.Lock()


def _norm(path: str) -> str:
    """标准化路径为绝对小写正斜杠路径，方便跨平台精准匹配"""
    try:
        return os.path.abspath(os.fspath(path)).replace("\\", "/").lower()
    except Exception:
        return ""


def _is_caller_mod() -> Tuple[bool, str]:
    """回溯当前调用栈，判断当前文件操作是否由 mod/ 目录下的模块直接或间接发起

    返回: (is_mod: bool, caller_filename: str)
    """
    try:
        # 跳过 audit_hook 自身和 _is_caller_mod
        frame = sys._getframe(2)
    except (AttributeError, ValueError):
        return False, ""

    norm_root = _norm(ROOT)
    norm_mod_dir = _norm(MOD_DIR)
    norm_lib_mods = _norm(os.path.join(ROOT, "lib", "mods.py"))

    while frame is not None:
        co_filename = frame.f_code.co_filename
        if co_filename:
            norm_file = _norm(co_filename)
            # 必须排除框架本身的 Mod 加载器 (lib/mods.py)
            if norm_file and norm_file != norm_lib_mods:
                # 判断当前调用栈帧是否来自 mod/ 目录
                if (norm_mod_dir and norm_file.startswith(norm_mod_dir + "/")) or ("/mod/" in norm_file):
                    return True, co_filename
        frame = frame.f_back

    return False, ""


def _is_protected_target(target) -> bool:
    """检测目标路径是否属于受保护的核心配置或系统文件"""
    if not target or not isinstance(target, (str, bytes, os.PathLike)):
        return False

    nt = _norm(target)
    if not nt:
        return False

    norm_root = _norm(ROOT)
    norm_cfg_dir = _norm(CONFIG_DIR)

    # 1. 严格保护 config/ 目录本身及其下所有文件 (无论文件名与层级)
    if norm_cfg_dir and (nt == norm_cfg_dir or nt.startswith(norm_cfg_dir + "/")):
        return True

    # 2. 泛匹配任意名为 config/users.json, config/config.json 的敏感相对路径
    if nt.endswith("/config/config.json") or nt.endswith("/config/users.json") or nt.endswith("/config/permission.json") or nt.endswith("/config/banlist.json"):
        return True

    # 3. 严格保护项目入口与核心代码目录
    if norm_root:
        if nt == f"{norm_root}/main.py" or nt == f"{norm_root}/.noneeds":
            return True
        if nt.startswith(f"{norm_root}/lib/") or nt.startswith(f"{norm_root}/webui/") or nt.startswith(f"{norm_root}/version_manager/"):
            return True

    return False


def _audit_hook(event: str, args: tuple) -> None:
    """PEP 578 审计回调函数"""
    try:
        if event == "open":
            # args: (file, mode, flags)
            if len(args) < 2:
                return
            target = args[0]
            mode = str(args[1] or "")
            flags = args[2] if len(args) > 2 else 0

            # 仅检测写、追加、独占创建、截断与读写操作
            is_write = (
                ("w" in mode)
                or ("a" in mode)
                or ("+" in mode)
                or ("x" in mode)
                or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            )
            if not is_write:
                return

            if _is_protected_target(target):
                is_mod, caller = _is_caller_mod()
                if is_mod:
                    _log_and_block(caller, target, "写入/覆盖")

        elif event in ("os.remove", "os.unlink", "os.rmdir"):
            # args: (path, dir_fd)
            if not args:
                return
            target = args[0]
            if _is_protected_target(target):
                is_mod, caller = _is_caller_mod()
                if is_mod:
                    _log_and_block(caller, target, "删除")

        elif event in ("os.rename", "os.replace"):
            # args: (src, dst, src_dir_fd, dst_dir_fd)
            if len(args) < 2:
                return
            src, dst = args[0], args[1]
            if _is_protected_target(src) or _is_protected_target(dst):
                is_mod, caller = _is_caller_mod()
                if is_mod:
                    _log_and_block(caller, f"{src} -> {dst}", "移动/重命名")

        elif event in ("os.truncate",):
            if not args:
                return
            target = args[0]
            if _is_protected_target(target):
                is_mod, caller = _is_caller_mod()
                if is_mod:
                    _log_and_block(caller, target, "截断")

    except PermissionError:
        raise
    except Exception:
        # 审计钩子自身防崩，内部异常不阻断正常业务
        pass


def _log_and_block(caller: str, target: str, action: str) -> None:
    """记录安全告警并抛出 PermissionError 中断非法操作"""
    caller_name = os.path.basename(caller) if caller else "未知 Mod"
    msg = f"[EnderBridge 安全防护] 成功拦截第三方 Mod ({caller_name}) 企图非法{action}核心系统配置: {target}的操作！ "
    try:
        from lib import shared
        if hasattr(shared, "logger"):
            shared.logger.error(msg)
    except Exception:
        pass
    raise PermissionError(msg)


def install_security_guard() -> bool:
    """在当前 Python 进程中挂载不可卸载的底层 C 级安全拦截守卫 (PEP 578)

    防重入: 仅在首次调用时生效。
    """
    global _installed
    with _install_lock:
        if _installed:
            return True
        try:
            sys.addaudithook(_audit_hook)
            _installed = True
            return True
        except Exception:
            return False
