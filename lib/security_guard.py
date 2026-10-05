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


OFFICIAL_BUILTIN_MOD_FILES = {
    "ai.py",
    "bot.py",
    "mcfunc.py",
    "message.py",
    "morews.py",
    "music.py",
    "permission.py",
    "position.py",
    "read.py",
    "spam.py",
    "tool.py",
}

OFFICIAL_BUILTIN_MOD_DIRS = {
    "bot",
    "ezmatic",
    "image",
    "qq",
}


def _is_official_mod(co_filename: str) -> bool:
    """判断代码文件是否属于官方内置 Mod 模块"""
    if not co_filename:
        return False
    norm_file = _norm(co_filename)
    norm_mod_dir = _norm(MOD_DIR)
    rel = ""
    if norm_mod_dir and norm_file.startswith(norm_mod_dir + "/"):
        rel = norm_file[len(norm_mod_dir) + 1:]
    elif "/mod/" in norm_file:
        rel = norm_file.split("/mod/", 1)[1]
    else:
        return False

    parts = rel.split("/")
    if len(parts) == 1 and parts[0] in OFFICIAL_BUILTIN_MOD_FILES:
        return True
    if len(parts) > 1 and parts[0] in OFFICIAL_BUILTIN_MOD_DIRS:
        return True
    return False


def _is_caller_mod() -> Tuple[bool, str]:
    """回溯当前调用栈，判断当前文件操作是否由 mod/ 目录下的非官方第三方模块直接或间接发起

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

    # 1. 检查是否处于通过授权通道 save_mod_config 进行的安全 Mod 配置保存上下文
    try:
        from lib.mods import is_in_mod_save_context
        if is_in_mod_save_context():
            return False, ""
    except Exception:
        pass

    # 2. 检查调用栈中是否存在官方授权的配置保存核心方法 (webui.server.save_config)
    has_authorized_save_api = False
    f_check = frame
    while f_check is not None:
        if f_check.f_code.co_name == "save_config" and "webui" in _norm(f_check.f_code.co_filename):
            has_authorized_save_api = True
            break
        f_check = f_check.f_back

    while frame is not None:
        co_filename = frame.f_code.co_filename
        if co_filename:
            norm_file = _norm(co_filename)
            # 必须排除框架本身的 Mod 加载器 (lib/mods.py)
            if norm_file and norm_file != norm_lib_mods:
                # 判断当前调用栈帧是否来自 mod/ 目录
                if (norm_mod_dir and norm_file.startswith(norm_mod_dir + "/")) or ("/mod/" in norm_file):
                    # 如果是官方内置 Mod 且通过授权的 save_config 核心方法写入，则安全放行
                    if _is_official_mod(co_filename) and has_authorized_save_api:
                        pass
                    else:
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

    # 0. 绝不拦截 Python 内部编译字节码缓存 (__pycache__, *.pyc, *.pyo 等)
    if "/__pycache__/" in nt or nt.endswith("/__pycache__") or nt.endswith(".pyc") or nt.endswith(".pyo"):
        return False

    norm_root = _norm(ROOT)
    norm_cfg_dir = _norm(CONFIG_DIR)

    # 1. 严格保护 config/ 目录本身及其下所有文件 (无论文件名与层级)
    if norm_cfg_dir and (nt == norm_cfg_dir or nt.startswith(norm_cfg_dir + "/")):
        return True

    # 2. 泛匹配任意名为 config/users.json, config/config.json 的敏感相对路径
    if nt.endswith("/config/config.json") or nt.endswith("/config/users.json") or nt.endswith("/config/permission.json") or nt.endswith("/config/banlist.json"):
        return True

    # 3. 严格保护项目入口与核心代码目录及官方内置 Mod 源码
    if norm_root:
        if nt == f"{norm_root}/main.py" or nt == f"{norm_root}/.noneeds":
            return True
        if nt.startswith(f"{norm_root}/lib/") or nt.startswith(f"{norm_root}/webui/") or nt.startswith(f"{norm_root}/version_manager/"):
            return True
        for of in OFFICIAL_BUILTIN_MOD_FILES:
            if nt == f"{norm_root}/mod/{of}":
                return True
        for od in OFFICIAL_BUILTIN_MOD_DIRS:
            if nt.startswith(f"{norm_root}/mod/{od}/"):
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
    caller_is_official = _is_official_mod(caller) if caller else False
    mod_kind = "官方内置 Mod" if caller_is_official else "第三方 Mod"
    msg = f"[EnderBridge 安全防护] 成功拦截{mod_kind} ({caller_name}) 企图非法{action}核心系统配置: {target}的操作！"
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
