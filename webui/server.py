# Author: Hydrooxzgen
# Github: https://github.com/Hydrooxzgen
# This project uses the GPL-3.0 license, you can modify/distribute this project according to the GPL-3.0 license
"""Web 管理后端服务

每次启动时随主程序启动,监听配置的 Web 端口,提供:
- 前端页面(index.html + static/ 静态资源)
- REST API:仪表盘状态 / 配置管理 / 权限管理 / Mod 管理 / Release Notes

前端资源全部以独立文件存放于 static/ 目录(css/js/图片/字体等),
不依赖 Python 内嵌模板,可自由使用任意前端技术(原生 JS / Vue 等)。

API 一览:
- GET  /                         返回前端页面
- GET  /static/*                 静态资源(css/js/图片/字体,自动识别 MIME)
- POST /api/auth                 登录校验(用户名+密码,正确→返回会话token)
- GET  /api/status               仪表盘状态(名称/端口/在线客户端/mod 等,无需鉴权)
- GET  /api/release-notes        当前版本 Release Notes(GitHub API,无需鉴权)
- GET  /api/config               读取可管理配置(仅 admin)
- PUT  /api/config               保存可管理配置(写回 config.py,仅 admin)
- GET  /api/permissions          读取权限配置(仅 admin)
- PUT  /api/permissions          保存权限配置(仅 admin)
- GET  /api/mods                 列出 Mod 及加载状态(admin / guest 均可,只读)
- POST /api/mods/reload-all      重载所有服务端 Mod(仅 admin)
- POST /api/restart              一键重启服务器进程(优雅关闭后自动以相同参数重启,仅 admin)

鉴权:用户名+bcrypt密码登录
- 登录页(/login)输入用户名+密码,正确→返回会话token
- 请求头 X-Auth-Token 携带有效会话token → 对应用户角色
- 请求头 X-Auth-Guest: 1 → guest(仅基础只读功能:仪表盘 / Mod 列表)
- 无有效身份 → 401;访客访问管理操作 → 403
"""
import json
import os
import re
import socket
import socketserver
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lib.users import user_manager

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBUI_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(WEBUI_DIR, "static")
CONFIG_DIR = os.path.join(ROOT, "config")
CONFIG_JSON = os.path.join(CONFIG_DIR, "config.json")
CONFIG_PY = os.path.join(CONFIG_DIR, "config.py")
CONFIG_PY_BAK = os.path.join(CONFIG_DIR, "config.py.bak")
PERMISSION_JSON = os.path.join(CONFIG_DIR, "permission.json")
# 仅作代码内兜底提示:真实版本由 main.py 启动时通过 set_app_info(main.VERSION) 注入,
# 实际显示/更新检测均以 main.py 的 VERSION 为准,此处无需随发布同步更新。
APP_VERSION = "b0.2.1"

# 静态资源 MIME 类型(前端可自由使用 css/js/图片/字体等,甚至接入 Vue 等框架)
_MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".map": "application/json",
}

# 在线客户端数量提供者(main.py 注入),避免跨线程直接访问 main 的 connections
_status_provider = None


def set_status_provider(fn):
    """注入状态提供者:main.py 启动后调用,返回 dict(如 {"clients": N})"""
    global _status_provider
    _status_provider = fn


# 一键重启处理器(main.py 注入):Web 管理界面触发后由主程序后台执行优雅关闭与进程重启
_restart_handler = None


def set_restart_handler(fn):
    """注入重启处理器:main.py 启动后调用,fn() 应发起服务器进程重启(不得阻塞请求线程)"""
    global _restart_handler
    _restart_handler = fn


# asyncio 事件循环引用(main.py 注入):用于从 WebUI 线程调度异步任务(如发送 MCBE 命令)
_event_loop = None


def set_event_loop(loop):
    """注入主 asyncio 事件循环,WebUI 线程可通过它调度协程"""
    global _event_loop
    _event_loop = loop


# 应用信息(main.py 注入):用于 Release Notes 获取
_github_repo = ""    # e.g. "UserXYY123/EnderBridge"
_app_version = APP_VERSION    # 初始为兜底值,set_app_info 后为 main.py 的真实 VERSION
_minimum_version = ""  # 最低允许版本,低于此版本禁止升级
_description = None  # 非 None 时直接用作 Release Notes,跳过 GitHub API
_system_mode = False  # --system 启动时启用系统保留账户功能


def set_app_info(github_repo: str, version: str, description=None, minimum_version: str = "") -> None:
    """注入应用信息:main.py 启动后调用,提供 GitHub 仓库名与当前版本

    description: 若提供(非 None),则 /api/release-notes 直接返回该内容,
    不再从 GitHub 拉取 Release 数据。"""
    global _github_repo, _app_version, _minimum_version, _description
    _github_repo = github_repo
    _app_version = version
    _minimum_version = minimum_version
    _description = description


def set_system_mode(enabled: bool) -> None:
    """启用/禁用系统保留账户模式(--system 启动参数)"""
    global _system_mode
    _system_mode = enabled


def _github_headers() -> dict:
    """返回 GitHub API request head,若配置了 token 则附带认证以提升速率限制"""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": f"EnderBridge/{_app_version}",
    }
    ns = _load_config_module()
    token = ns.get("githubToken", "")
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def _parse_version(ver: str) -> list:
    """解析版本号字符串为可比较的整数列表。支持 b0.1.0 / v0.1.0 / 0.1.0 等格式。"""
    import re
    nums = re.findall(r'\d+', ver)
    return [int(n) for n in nums] if nums else [0]


def _version_gt(a: str, b: str) -> bool:
    """判断版本 a 是否严格大于版本 b"""
    return _parse_version(a) > _parse_version(b)


def _version_below_min(ver: str) -> bool:
    """判断版本是否低于最低允许版本(低于则返回 True,禁止安装)"""
    if not _minimum_version or not ver:
        return False
    try:
        return _parse_version(ver) < _parse_version(_minimum_version)
    except Exception:
        return False





def _read_config_src() -> str:
    """读取 config.py 源码文本"""
    with open(CONFIG_PY, "r", encoding="utf-8") as f:
        return f.read()


def _load_config_module() -> dict:
    """加载配置，优先读取 config.json (b0.3.6)，回退到 config.py (b0.1.0)"""
    # 优先读取 JSON 配置
    if os.path.exists(CONFIG_JSON):
        try:
            with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # 回退：读取 Python 配置
    ns = {}
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("webui_config_src", CONFIG_PY)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ns = module.__dict__
    except Exception:
        pass
    return ns


def _py_dump(value, level: int = 0) -> str:
    """将 dict/list 序列化为 Python 字面量文本(True/False/None 而非 true/false/null)

    递归生成,缩进 4 空格,与 config.py 手写风格一致。
    """
    pad = "    " * level
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = [pad + "{"]
        for k, v in value.items():
            lines.append(f'{pad}    {json.dumps(str(k), ensure_ascii=False)}: {_py_dump(v, level + 1)},')
        lines.append(pad + "}")
        return "\n".join(lines)
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        lines = [pad + "["]
        for v in value:
            lines.append(f"{pad}    {_py_dump(v, level + 1)},")
        lines.append(pad + "]")
        return "\n".join(lines)
    if value is True:
        return "True"
    if value is False:
        return "False"
    if value is None:
        return "None"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return repr(value)


def _replace_block(src: str, varname: str, value) -> tuple:
    """将源码中 `varname = { ... }` 块整体替换为 value 的序列化文本

    Args:
        src: config.py 源码
        varname: 顶层变量名(如 features / rateLimit / webuiConfig)
        value: 新的 dict 值

    Returns:
        (新源码, 是否替换成功)
    """
    m = re.search(rf"(?m)^{re.escape(varname)}\s*=\s*\{{", src)
    if not m:
        return src, False
    start = m.start()
    # 从第一个 { 开始做括号配对
    i = src.index("{", m.start())
    depth = 0
    end = -1
    for j in range(i, len(src)):
        c = src[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = j + 1
                break
    if end < 0:
        return src, False
    text = _py_dump(value)
    # 顶层变量缩进为 0,直接生成 varname = { ... }
    return src[:start] + f"{varname} = {text}\n" + src[end:], True


def _replace_line(src: str, varname: str, value) -> tuple:
    """将源码中 `varname = xxx` 单行赋值替换为新值"""
    pattern = re.compile(rf"(?m)^({re.escape(varname)}\s*=\s*).*?$")
    m = pattern.search(src)
    if not m:
        return src, False
    text = json.dumps(value, ensure_ascii=False)
    return src[:m.start()] + f"{m.group(1)}{text}" + src[m.end():], True


# ===== 配置读写 =====

def _first_system_prompt(model_cfg: dict) -> str:
    """提取模型配置中的第一条 system 提示词"""
    for m in (model_cfg.get("messages") or []):
        if isinstance(m, dict) and m.get("role") == "system":
            return m.get("content", "")
    return ""


def _set_system_prompt(messages, content: str) -> list:
    """将模型配置中的 system 提示词替换/插入为首条"""
    msgs = [dict(m) for m in (messages or []) if isinstance(m, dict)]
    content = str(content or "")
    if msgs and msgs[0].get("role") == "system":
        msgs[0]["content"] = content
    else:
        msgs.insert(0, {"role": "system", "content": content})
    return msgs


def load_config() -> dict:
    """读取可管理配置(供前端表单使用)，优先读取 JSON，兼容旧版 Python"""
    # 优先尝试读取 JSON 配置
    json_config = {}
    if os.path.exists(CONFIG_JSON):
        try:
            with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                json_config = json.load(f)
        except Exception:
            pass

    # 兼容旧版 Python 配置
    py_config = {}
    if not json_config and os.path.exists(CONFIG_PY):
        ns = _load_config_module()
        # 只提取配置变量，不包含模块对象
        for name in dir(ns):
            if not name.startswith("_"):
                try:
                    val = getattr(ns, name)
                    # 跳过模块、函数等不可序列化对象
                    if not callable(val) and not hasattr(val, '__loader__'):
                        py_config[name] = val
                except Exception:
                    pass

    # 合并配置，JSON 优先
    config = {**py_config, **json_config}

    cfg = config.get("wsConfig", {})
    features = config.get("features", {})
    rate_limit = config.get("rateLimit", {})
    webui = config.get("webuiConfig", {})
    ai = config.get("AIConfig", {})
    ai_models = ai.get("models", {})
    utils = config.get("utilsConfig", {})
    sapi = config.get("sapiConfig", {})
    bot = config.get("botConfig", {})
    message_cfg = config.get("messageConfig", {})
    spam = config.get("spam", {})
    base_path = config.get("basePath", {})
    mods = config.get("mods", {"client": {}, "server": {}})
    command_aliases = config.get("commandAliases", {})

    return {
        "name": cfg.get("name", "EnderBridge"),
        "port": cfg.get("port", 8800),
        "commandPrefix": config.get("commandPrefix", "!"),
        "logLevel": config.get("logLevel", "info"),
        "features": features,
        "rateLimit": rate_limit,
        "mods": mods,
        "spam": spam,
        "basePath": base_path,
        "webui": {
            "enabled": webui.get("enabled", True),
            "port": webui.get("port", 18888),
            "token": webui.get("token", ""),
            "localOnly": webui.get("localOnly", False),
            "autoBan": webui.get("autoBan", True),
        },
        "ai": {
            "baseURL": (ai.get("options") or {}).get("baseURL", ""),
            "apiKey": (ai.get("options") or {}).get("apiKey", ""),
            "chatModel": (ai_models.get("chat") or {}).get("model", "deepseek-chat"),
            "chatMaxTokens": (ai_models.get("chat") or {}).get("max_tokens", 512),
            "chatPrompt": _first_system_prompt(ai_models.get("chat") or {}),
            "cmdModel": (ai_models.get("command") or {}).get("model", "deepseek-chat"),
            "cmdMaxTokens": (ai_models.get("command") or {}).get("max_tokens", 1024),
            "cmdPrompt": _first_system_prompt(ai_models.get("command") or {}),
            "chatCooldown": ai.get("chatCooldown", 5000),
        },
        "utils": {
            "tellAllToTell": utils.get("tellAllToTell", False),
            "enablePolling": utils.get("enablePolling", True),
        },
        "sapi": {
            "gmsg": sapi.get("gmsg", "gmsg"),
            "smsg": sapi.get("smsg", "smsg"),
        },
        "messageConfig": {
            "announcements": (message_cfg or {}).get("announcements", {
                "enabled": False,
                "interval": 300,
                "messages": [
                    "欢迎来到本服务器！请遵守游戏规则。",
                    "加入我们的 QQ 群：123456789",
                    "服务器官网：https://example.com",
                ],
            }),
        },
        "bot": {
            "enabled": bot.get("enabled", True),
            "mode": bot.get("mode", "server"),
            "host": bot.get("host", "127.0.0.1"),
            "port": bot.get("port", 19132),
            "username": bot.get("username", "FakeBot"),
            "offline": bot.get("offline", True),
            "version": bot.get("version", None),
            "authTitle": bot.get("authTitle", None),
            "profilesFolder": bot.get("profilesFolder", None),
            "realmId": bot.get("realmId", None),
            "realmInvite": bot.get("realmInvite", None),
            "xboxAccounts": bot.get("xboxAccounts", []),
            "activeXboxAccount": bot.get("activeXboxAccount", None),
        },
        "githubToken": config.get("githubToken", ""),
        "commandAliases": command_aliases,
        "playerListPolling": config.get("playerListPolling", {"enabled": False, "intervalSeconds": 30}),
        "updateConfig": config.get("updateConfig", {"autoBackup": True}),
    }


def save_config(new: dict) -> None:
    """将表单配置写回 config.json(优先 JSON，兼容旧版 Python)"""
    # 读取现有配置（优先 JSON，兼容旧版 Python）
    json_config = {}
    if os.path.exists(CONFIG_JSON):
        try:
            with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                json_config = json.load(f)
        except Exception:
            pass

    py_config = {}
    if not json_config and os.path.exists(CONFIG_PY):
        ns = _load_config_module()
        # 只提取配置变量，不包含模块对象
        for name in dir(ns):
            if not name.startswith("_"):
                try:
                    val = getattr(ns, name)
                    # 跳过模块、函数等不可序列化对象
                    if not callable(val) and not hasattr(val, '__loader__'):
                        py_config[name] = val
                except Exception:
                    pass

    # 合并现有配置，JSON 优先
    config = {**py_config, **json_config}

    # 更新配置
    config["wsConfig"] = {
        "name": str(new.get("name") or "").strip() or "EnderBridge",
        "port": int(new.get("port") or 8800),
    }
    config["commandPrefix"] = str(new.get("commandPrefix") or "!").strip() or "!"
    config["logLevel"] = str(new.get("logLevel") or "info").strip()
    config["features"] = new.get("features") or {}
    config["rateLimit"] = new.get("rateLimit") or {}

    # Mods
    mods_form = new.get("mods") or {"client": {}, "server": {}}
    mods_form.setdefault("client", {})
    mods_form.setdefault("server", {})
    mods_form["client"].setdefault("Message", "mod.message")
    config["mods"] = mods_form

    config["spam"] = new.get("spam") or {}
    config["basePath"] = new.get("basePath") or {}

    # AI
    ai = config.get("AIConfig", {})
    ai.setdefault("options", {})
    ai.setdefault("models", {})
    ai_form = new.get("ai") or {}
    ai["options"]["baseURL"] = str(ai_form.get("baseURL") or "").strip()
    ai["options"]["apiKey"] = str(ai_form.get("apiKey") or "").strip()
    chat = dict(ai.get("models", {}).get("chat", {}))
    cmd = dict(ai.get("models", {}).get("command", {}))
    chat["model"] = str(ai_form.get("chatModel") or "deepseek-chat").strip()
    chat["max_tokens"] = int(ai_form.get("chatMaxTokens") or 512)
    chat["messages"] = _set_system_prompt(chat.get("messages"), ai_form.get("chatPrompt"))
    cmd["model"] = str(ai_form.get("cmdModel") or "deepseek-chat").strip()
    cmd["max_tokens"] = int(ai_form.get("cmdMaxTokens") or 1024)
    cmd["messages"] = _set_system_prompt(cmd.get("messages"), ai_form.get("cmdPrompt"))
    ai["models"]["chat"] = chat
    ai["models"]["command"] = cmd
    ai["chatCooldown"] = int(ai_form.get("chatCooldown") or 5000)
    config["AIConfig"] = ai

    # 工具配置
    utils_form = new.get("utils") or {}
    config["utilsConfig"] = {
        "tellAllToTell": bool(utils_form.get("tellAllToTell", False)),
        "enablePolling": bool(utils_form.get("enablePolling", True)),
    }

    # SAPI
    sapi_form = new.get("sapi") or {}
    config["sapiConfig"] = {
        "gmsg": str(sapi_form.get("gmsg") or "gmsg").strip(),
        "smsg": str(sapi_form.get("smsg") or "smsg").strip(),
    }

    # 消息通知与公告
    message_form = new.get("messageConfig") or {}
    announce_form = message_form.get("announcements") or {}
    config["messageConfig"] = {
        "agreement": {
            "enabled": True,
            "title": "📋 服务器协议",
            "text": "欢迎来到本服务器！\n\n请遵守以下规则：\n1. 尊重其他玩家\n2. 禁止作弊和破坏\n3. 禁止刷屏和骚扰\n\n输入 agree 同意协议后即可游戏。",
        },
        "announcements": {
            "enabled": bool(announce_form.get("enabled", False)),
            "interval": int(announce_form.get("interval", 300)),
            "messages": announce_form.get("messages", [
                "欢迎来到本服务器！请遵守游戏规则。",
                "加入我们的 QQ 群：123456789",
                "服务器官网：https://example.com",
            ]),
        },
    }

    # Bot
    bot_form = new.get("bot") or {}
    config["botConfig"] = {
        "enabled": bool(bot_form.get("enabled", True)),
        "mode": str(bot_form.get("mode") or "server").strip(),
        "host": str(bot_form.get("host") or "127.0.0.1").strip(),
        "port": int(bot_form.get("port") or 19132),
        "username": str(bot_form.get("username") or "FakeBot").strip(),
        "offline": bool(bot_form.get("offline", True)),
        "version": bot_form.get("version") or None,
        "authTitle": bot_form.get("authTitle") or None,
        "profilesFolder": bot_form.get("profilesFolder") or None,
        "realmId": bot_form.get("realmId") or None,
        "realmInvite": bot_form.get("realmInvite") or None,
        "xboxAccounts": [],  # 由登录 API 管理
        "activeXboxAccount": None,
    }

    # WebUI
    webui = new.get("webui") or {}
    config["webuiConfig"] = {
        "enabled": bool(webui.get("enabled", True)),
        "port": int(webui.get("port") or 18888),
        "token": str(webui.get("token") or "").strip(),
        "localOnly": bool(webui.get("localOnly", False)),
    }

    # GitHub Token
    config["githubToken"] = str(new.get("githubToken") or "").strip()

    # Mods
    config["mods"] = new.get("mods") or {"client": {}, "server": {}}
    config["mods"].setdefault("client", {})
    config["mods"].setdefault("server", {})
    config["mods"]["client"].setdefault("Message", "mod.message")

    config["spam"] = new.get("spam") or {}
    config["basePath"] = new.get("basePath") or {}

    # 命令别名
    config["commandAliases"] = new.get("commandAliases") or {}

    # 玩家列表轮询
    plp = new.get("playerListPolling") or {}
    config["playerListPolling"] = {
        "enabled": bool(plp.get("enabled", False)),
        "intervalSeconds": int(plp.get("intervalSeconds", 30)),
    }

    # 更新与备份设置
    upd = new.get("updateConfig") or {}
    config["updateConfig"] = {
        "autoBackup": bool(upd.get("autoBackup", True)),
    }

    # 版本信息
    config["_version"] = "b0.3.6"

    # 保存到 JSON
    if os.path.exists(CONFIG_JSON):
        os.replace(CONFIG_JSON, CONFIG_JSON + ".bak")
    with open(CONFIG_JSON, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    # 别名热重载:保存后立即生效,无需重启 (必须在写入 JSON 之后,否则读到旧缓存)
    try:
        from lib.config_loader import reload_config
        from lib.command import reload_all_aliases
        reload_config()  # 清除配置缓存
        reload_all_aliases()
    except Exception:
        pass




# ===== 权限读写 =====

def load_permissions() -> dict:
    """读取 permission.json(不存在时创建默认结构并落盘,避免查询永远显示默认值)"""
    try:
        with open(PERMISSION_JSON, "r", encoding="utf-8") as f:
            perm = json.load(f)
        if not isinstance(perm, dict):
            raise ValueError
        return perm
    except Exception:
        default = {"owner": "YourXboxName", "op": [], "user": [], "blocker": []}
        try:
            save_permissions(default)
        except Exception:
            pass
        return default


def save_permissions(perm: dict) -> None:
    """原子写入 permission.json,并清除 PermissionManager 缓存使游戏内权限立即生效"""
    tmp = PERMISSION_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(perm, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, PERMISSION_JSON)
    # 同步清除 lib.permission 的缓存,否则游戏内查询权限仍用旧数据
    try:
        from lib.permission import PermissionManager
        PermissionManager._cache = None
    except Exception:
        pass


def _perm_groups() -> list:
    return ["owner", "op", "user", "blocker"]


# ===== 鉴权 =====

def _extract_session_token(handler) -> str:
    """从请求头或查询参数中提取会话 token"""
    # 优先从请求头获取
    token = handler.headers.get("X-Auth-Token", "")
    if token:
        return token
    # 查询参数兼容(EventSource 等无法设置自定义头的场景)
    parsed = urllib.parse.urlparse(handler.path)
    qs = urllib.parse.parse_qs(parsed.query)
    return qs.get("token", [None])[0] or ""


def _auth_user(handler) -> dict:
    """返回请求身份信息: {username, role, permissions, is_guest}

    通过会话 token 查找用户。无 token 时回退到 guest 访客。
    """
    token = _extract_session_token(handler)

    # 1) 通过 session token 查找
    if token:
        session = user_manager.validate_session(token)
        if session:
            return {
                "username": session["username"],
                "role": session["role"],
                "permissions": session["permissions"],
                "system": session.get("system", False),
                "is_guest": False,
            }

    # 2) Guest header / 查询参数兼容(EventSource 等无法设置自定义头的场景)
    is_guest = False
    if handler.headers.get("X-Auth-Guest", "") == "1":
        is_guest = True
    else:
        parsed_qs = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
        if parsed_qs.get("guest", [None])[0] is not None:
            is_guest = True

    if is_guest:
        guest_user = user_manager.get_user("guest")
        if guest_user:
            role = guest_user.get("role", "viewer")
            permissions = user_manager.get_effective_permissions("guest")
            return {"username": "guest", "role": role, "permissions": permissions, "system": False, "is_guest": True}
        return {"username": "guest", "role": "viewer", "permissions": ["dashboard", "mods"], "system": False, "is_guest": True}

    # 3) 未授权
    return {"username": "", "role": "", "permissions": [], "system": False, "is_guest": False}


def _auth_role(handler) -> str:
    """返回请求角色字符串(兼容旧代码);新代码请用 _auth_user"""
    user = _auth_user(handler)
    return user["role"]


def _require_permission(permission: str):
    """返回一个检查权限的装饰器函数:调用时传入 handler,有权限返回 True,否则自动 401/403 并返回 False"""
    def checker(handler) -> bool:
        user = _auth_user(handler)
        if permission in user.get("permissions", []):
            return True
        if not user.get("role"):
            handler._respond_denied()
        else:
            handler._respond({"ok": False, "message": f"无权限:需要 {permission} 权限"}, status=403)
        return False
    return checker


def _audit(handler, type_: str, message: str) -> None:
    """写入审计日志(类型: ban/user/role/config/system/update/command)"""
    try:
        from lib.logger import audit_log
        user = _auth_user(handler)
        sender = user.get("username") or "Anonymous"
        audit_log.append(type_, sender, message)
    except Exception:
        pass


def _require_admin(handler) -> bool:
    """管理操作:仅 admin 角色可访问;访客返回 403,未授权返回 401(兼容旧代码)"""
    user = _auth_user(handler)
    if user["role"] == "admin":
        return True
    if user["is_guest"]:
        handler._respond({"ok": False, "message": "访客模式:无管理权限"}, status=403)
        return False
    handler._respond_denied()
    return False


def _require_any(handler) -> bool:
    """登录即可访问(任何角色);未授权返回 401(兼容旧代码)"""
    user = _auth_user(handler)
    if user.get("role"):
        return True
    handler._respond_denied()
    return False


# ===== HTTP 处理器 =====

class WebUIHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # 静默日志,避免刷屏
        pass

    def log_error(self, fmt, *args):
        """静默连接断开类错误,避免 Ctrl+C / SSE 断开时刷 traceback"""
        msg = str(fmt) % args if args else str(fmt)
        if any(s in msg for s in ("ConnectionAbortedError", "BrokenPipeError",
                                   "ConnectionResetError", "10053", "10054")):
            return
        super().log_error(fmt, *args)

    def _respond(self, obj, status=200) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (ConnectionAbortedError, BrokenPipeError, OSError):
            pass  # 客户端已断开,忽略写入失败

    def _respond_denied(self) -> None:
        self._respond({"ok": False, "message": "未授权:请先在登录页输入管理令牌"}, status=401)

    def _read_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _check_ban(self) -> bool:
        """检查当前请求 IP 是否被封禁,被封禁则返回 True(已发送 403 HTML 页面)"""
        from lib import banlist
        ip = self.client_address[0] if self.client_address else ""
        if banlist.is_banned(ip):
            ban_info = banlist.list_bans().get(ip, {})
            reason = ban_info.get("reason", "管理员封禁")
            ban_time = ban_info.get("time", "未知")
            expires_ts = ban_info.get("expires")
            if expires_ts:
                from datetime import datetime
                expires_str = datetime.fromtimestamp(expires_ts).strftime("%Y-%m-%d %H:%M:%S")
            else:
                expires_str = "永久"
            # 从 ban.html 模板读取并填充动态数据
            from string import Template
            _ban_tpl = os.path.join(os.path.dirname(__file__), "ban.html")
            with open(_ban_tpl, "r", encoding="utf-8") as _bf:
                html = Template(_bf.read()).safe_substitute(ip=ip, reason=reason, ban_time=ban_time, expires_str=expires_str)
            try:
                data = html.encode("utf-8")
                self.send_response(403)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (ConnectionAbortedError, BrokenPipeError, OSError):
                pass
            return True
        return False

    # ---- 静态页面 ----
    def do_GET(self):
        if self._check_ban(): return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # 页面路由
        if path == "/login":
            self._serve_page("login.html")
            return
        if path in ("/", "/index.html", "/dashboard"):
            self._serve_page("dashboard.html")
            return
        if path == "/permissions":
            self._serve_page("permissions.html")
            return
        if path == "/config":
            self._serve_page("config.html")
            return
        if path == "/mods":
            self._serve_page("mods.html")
            return
        if path == "/studio":
            self._serve_page("studio.html")
            return
        if path == "/update":
            self._serve_page("update.html")
            return
        if path == "/console":
            self._serve_page("console.html")
            return
        if path.startswith("/static/"):
            self._serve_static(path)
            return
        if path == "/api/status":
            self._api_status()
            return
        if path == "/api/performance":
            self._api_performance()
            return
        if path == "/api/release-notes":
            self._api_release_notes()
            return
        if path == "/api/update/check":
            self._api_update_check()
            return
        if path == "/api/update/releases":
            self._api_update_releases()
            return
        if path == "/api/update/backups":
            self._api_update_backups()
            return
        if path == "/api/security/audit":
            self._api_security_audit()
            return
        if path == "/api/config":
            self._api_get_config()
            return
        if path == "/api/permissions":
            self._api_get_permissions()
            return
        if path == "/api/mods":
            self._api_get_mods()
            return
        if path == "/api/mods/config":
            self._api_get_mod_config()
            return
        if path == "/api/studio/assets":
            self._api_studio_get_assets()
            return
        if path == "/api/studio/asset-file":
            self._api_studio_get_asset_file()
            return
        if path == "/api/studio/palette":
            self._api_studio_get_palette()
            return
        if path == "/api/studio/blueprint-voxels":
            self._api_studio_get_blueprint_voxels()
            return
        if path == "/api/studio/blueprint-html":
            self._api_studio_get_blueprint_html()
            return
        if path == "/api/studio/textures/status":
            self._api_studio_textures_status()
            return

        if path == "/api/bot/xbox-accounts":
            self._api_bot_xbox_accounts()
            return
        if path == "/api/bot/xbox-login-status":
            self._api_bot_xbox_login_status()
            return
        if path == "/audit":
            self._serve_page("audit.html")
            return
        if path == "/banlist":
            self._serve_page("banlist.html")
            return
        if path == "/api/audit-logs":
            self._api_audit_logs()
            return
        if path == "/api/audit-logs/export":
            self._api_audit_logs_export()
            return
        if path == "/api/logs/recent":
            self._api_logs_recent()
            return
        if path == "/api/logs/stream":
            self._api_logs_stream()
            return
        if path == "/api/ws/console":
            self._handle_ws_console()
            return
        if path == "/api/auth/me":
            self._api_auth_me()
            return
        if path == "/api/users":
            self._api_users_list()
            return
        if path == "/api/roles":
            self._api_roles_list()
            return
        if path == "/api/banlist":
            self._api_banlist_list()
            return
        if path == "/api/banlist/auto-ban":
            self._api_banlist_auto_ban_status()
            return
        if path == "/api/banlist/auto-ban-config":
            self._api_banlist_auto_ban_config_get()
            return
        if path.startswith("/api/"):
            self._respond({"ok": False, "message": "Not Found"}, status=404)
            return
        if path == "/author":
            self._respond({"ok": True, "author": "Hydrooxygen"})
            return
        self._serve_page("404.html")

    def do_PUT(self):
        if self._check_ban(): return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/config":
            self._api_save_config()
            return
        if parsed.path == "/api/permissions":
            self._api_save_permissions()
            return
        if parsed.path == "/api/users":
            self._api_users_update()
            return
        if parsed.path == "/api/roles":
            self._api_roles_update()
            return
        self._respond({"ok": False, "message": "Not Found"}, status=404)

    def do_DELETE(self):
        if self._check_ban(): return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/users":
            self._api_users_delete()
            return
        if parsed.path == "/api/roles":
            self._api_roles_delete()
            return
        if parsed.path == "/api/banlist":
            self._api_banlist_remove()
            return
        if parsed.path == "/api/studio/asset":
            self._api_studio_delete_asset()
            return
        self._respond({"ok": False, "message": "Not Found"}, status=404)

    def do_POST(self):
        if self._check_ban(): return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/auth":
            self._api_auth()
            return
        if parsed.path == "/api/auth/logout":
            self._api_auth_logout()
            return
        if parsed.path == "/api/users":
            self._api_users_create()
            return
        if parsed.path == "/api/roles":
            self._api_roles_create()
            return
        if parsed.path == "/api/mods/reload-all":
            self._api_reload_all()
            return
        if parsed.path == "/api/mods/reload":
            self._api_reload_mod()
            return
        if parsed.path == "/api/mods/config":
            self._api_save_mod_config()
            return
        if parsed.path == "/api/studio/upload":
            self._api_studio_upload()
            return
        if parsed.path == "/api/studio/save-text":
            self._api_studio_save_text()
            return
        if parsed.path == "/api/studio/action":
            self._api_studio_action()
            return
        if parsed.path == "/api/studio/blueprint-voxels":
            self._api_studio_post_blueprint_voxels()
            return
        if parsed.path == "/api/studio/textures/download":
            self._api_studio_textures_download()
            return
        if parsed.path == "/api/studio/textures/uninstall":
            self._api_studio_textures_uninstall()
            return
        if parsed.path == "/api/restart":
            self._api_restart()
            return
        if parsed.path == "/api/update/install":
            self._api_update_install()
            return
        if parsed.path == "/api/update/upload":
            self._api_update_upload()
            return
        if parsed.path == "/api/update/rollback":
            self._api_update_rollback()
            return
        if parsed.path == "/api/console":
            self._api_console()
            return
        if parsed.path == "/api/banlist":
            self._api_banlist_add()
            return
        if parsed.path == "/api/banlist/batch":
            self._api_banlist_batch_add()
            return
        if parsed.path == "/api/banlist/auto-ban":
            self._api_banlist_auto_ban_toggle()
            return
        if parsed.path == "/api/banlist/auto-ban-config":
            self._api_banlist_auto_ban_config_set()
            return
        if parsed.path == "/api/banlist/edit":
            self._api_banlist_edit()
            return
        if parsed.path == "/api/firewall":
            self._api_firewall_add_rule()
            return
        if parsed.path == "/api/bot/xbox-login":
            self._api_bot_xbox_login()
            return
        if parsed.path == "/api/bot/xbox-login-stop":
            self._api_bot_xbox_login_stop()
            return
        if parsed.path == "/api/bot/xbox-account/switch":
            self._api_bot_xbox_account_switch()
            return
        if parsed.path == "/api/bot/xbox-account/remove":
            self._api_bot_xbox_account_remove()
            return
        self._respond({"ok": False, "message": "Not Found"}, status=404)

    # ---- 前端页面 ----
    def _serve_index(self) -> None:
        index_path = os.path.join(WEBUI_DIR, "index.html")
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                body = f.read().encode("utf-8")
        except Exception:
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("index.html 缺失".encode("utf-8"))
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_page(self, page_name: str) -> None:
        """提供 pages 目录下的单个 HTML 页面"""
        page_path = os.path.join(WEBUI_DIR, "pages", page_name)
        try:
            with open(page_path, "r", encoding="utf-8") as f:
                body = f.read().encode("utf-8")
        except Exception:
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"{page_name} 缺失".encode("utf-8"))
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, path: str) -> None:
        """提供 static 目录下的静态资源(css/js/图片/字体等,支持任意前端框架产物)"""
        # 防目录穿越:解析后必须仍位于 static 目录内
        rel = path[len("/static/"):]
        base = os.path.realpath(STATIC_DIR)
        full = os.path.realpath(os.path.join(base, rel))
        if full != base and not full.startswith(base + os.sep):
            self.send_response(403)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Forbidden")
            return
        if not os.path.isfile(full):
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Not Found")
            return
        try:
            with open(full, "rb") as f:
                body = f.read()
        except Exception:
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Internal Server Error")
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = _MIME_TYPES.get(ext, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- API ----
    def _api_console(self) -> None:
        """向 MCBE 客户端发送命令并返回结果(需要 console 权限)"""
        if not _require_permission("console")(self):
            return
        body = self._read_body()
        command = body.get("command", "").strip()
        if not command:
            self._respond({"ok": False, "message": "缺少 command 参数"})
            return
        if _event_loop is None or _event_loop.is_closed():
            self._respond({"ok": False, "message": "事件循环未就绪,请稍后重试"})
            return
        try:
            from lib.current import Current
            client = Current.client
            if client is None:
                self._respond({"ok": False, "message": "无客户端连接"})
                return
            import asyncio
            fut = asyncio.run_coroutine_threadsafe(
                client.runCommand(command), _event_loop
            )
            result = fut.result(timeout=15)
            body_data = result.get("body", {}) if isinstance(result, dict) else {}
            self._respond({
                "ok": True,
                "statusCode": body_data.get("statusCode"),
                "statusMessage": body_data.get("statusMessage"),
            })
            _audit(self, "command", f"执行了命令: {command}")
        except Exception as e:
            self._respond({"ok": False, "message": f"命令执行失败: {e}"})

    # ---- Xbox Live 多账号登录 ----

    def _api_bot_xbox_accounts(self) -> None:
        """获取已保存的 Xbox Live 账号列表"""
        if not _require_permission("config")(self):
            return
        ns = _load_config_module()
        bot_cfg = ns.get("botConfig") or {}
        accounts = bot_cfg.get("xboxAccounts") or []
        active = bot_cfg.get("activeXboxAccount") or None
        self._respond({"ok": True, "accounts": accounts, "active": active})

    def _api_bot_xbox_login(self) -> None:
        """启动 Xbox Live 登录流程 — Gamertag 从认证响应中自动获取,无需传入用户名"""
        if not _require_permission("config")(self):
            return
        if _event_loop is None or _event_loop.is_closed():
            self._respond({"ok": False, "message": "事件循环未就绪,请稍后重试"})
            return
        body = self._read_body()
        auth_title = (body.get("authTitle") or "").strip() or None
        try:
            from mod.bot import XboxLoginManager
            import asyncio
            login_mgr = XboxLoginManager.get()
            fut = asyncio.run_coroutine_threadsafe(
                login_mgr.start_login(auth_title), _event_loop
            )
            result = fut.result(timeout=10)
            self._respond(result)
        except Exception as e:
            self._respond({"ok": False, "message": f"启动登录失败: {e}"})

    def _api_bot_xbox_login_status(self) -> None:
        """查询 Xbox Live 登录状态"""
        if not _require_permission("config")(self):
            return
        try:
            from mod.bot import XboxLoginManager
            login_mgr = XboxLoginManager.get()
            self._respond({"ok": True, **login_mgr.get_status()})
        except Exception as e:
            self._respond({"ok": False, "message": f"查询状态失败: {e}"})

    def _api_bot_xbox_login_stop(self) -> None:
        """取消 Xbox Live 登录流程"""
        if not _require_permission("config")(self):
            return
        if _event_loop is None or _event_loop.is_closed():
            self._respond({"ok": True})
            return
        try:
            from mod.bot import XboxLoginManager
            import asyncio
            login_mgr = XboxLoginManager.get()
            fut = asyncio.run_coroutine_threadsafe(
                login_mgr.stop_login(), _event_loop
            )
            fut.result(timeout=5)
            self._respond({"ok": True, "message": "登录已取消"})
        except Exception as e:
            self._respond({"ok": False, "message": f"取消登录失败: {e}"})

    def _api_bot_xbox_account_switch(self) -> None:
        """切换活跃的 Xbox Live 账号"""
        if not _require_permission("config")(self):
            return
        body = self._read_body()
        username = (body.get("username") or "").strip()
        if not username:
            self._respond({"ok": False, "message": "缺少用户名"})
            return
        ns = _load_config_module()
        bot_cfg = dict(ns.get("botConfig") or {})
        accounts = list(bot_cfg.get("xboxAccounts") or [])
        found = False
        for acc in accounts:
            if acc.get("username") == username:
                found = True
                break
        if not found:
            self._respond({"ok": False, "message": f"账号 {username} 未找到"})
            return
        # 更新 activeXboxAccount 和 username（通过整体替换 botConfig 块）
        try:
            src = _read_config_src()
            src_new, _ = _replace_block(src, "botConfig", {
                **bot_cfg,
                "activeXboxAccount": username,
                "username": username,
                # offline 完全由用户开关控制,切换账号不再强制覆盖
            })
            import shutil
            shutil.copy2(CONFIG_PY, CONFIG_PY_BAK)
            with open(CONFIG_PY, "w", encoding="utf-8") as f:
                f.write(src_new)
            self._respond({"ok": True, "message": f"已切换到账号 {username}"})
        except Exception as e:
            self._respond({"ok": False, "message": f"切换失败: {e}"})

    def _api_bot_xbox_account_remove(self) -> None:
        """移除 Xbox Live 账号"""
        if not _require_permission("config")(self):
            return
        body = self._read_body()
        username = (body.get("username") or "").strip()
        if not username:
            self._respond({"ok": False, "message": "缺少用户名"})
            return
        ns = _load_config_module()
        bot_cfg = dict(ns.get("botConfig") or {})
        accounts = list(bot_cfg.get("xboxAccounts") or [])
        new_accounts = [a for a in accounts if a.get("username") != username]
        if len(new_accounts) == len(accounts):
            self._respond({"ok": False, "message": f"账号 {username} 未找到"})
            return
        # 如果移除的是活跃账号,切到第一个或清空
        active = bot_cfg.get("activeXboxAccount")
        if active == username:
            active = new_accounts[0]["username"] if new_accounts else None
        try:
            new_cfg = {**bot_cfg, "xboxAccounts": new_accounts, "activeXboxAccount": active}
            if active:
                new_cfg["username"] = active
            src = _read_config_src()
            src, _ = _replace_block(src, "botConfig", new_cfg)
            import shutil
            shutil.copy2(CONFIG_PY, CONFIG_PY_BAK)
            with open(CONFIG_PY, "w", encoding="utf-8") as f:
                f.write(src)
            # 删除该账号的 token 缓存文件(与 prismarine-auth 相同的 SHA1 前缀),防止重新登录时秒复用
            self._delete_account_cache(username, bot_cfg)
            self._respond({"ok": True, "message": f"已移除账号 {username}"})
        except Exception as e:
            self._respond({"ok": False, "message": f"移除失败: {e}"})

    def _delete_account_cache(self, username: str, bot_cfg: dict) -> None:
        """删除指定账号在 nmp-cache 中的 token 缓存文件"""
        try:
            import hashlib
            folder = bot_cfg.get("profilesFolder") or ".minecraft/nmp-cache"
            if not os.path.isabs(folder):
                folder = os.path.join(ROOT, "mod", "bot", folder)
            if not os.path.isdir(folder):
                return
            prefix = hashlib.sha1(username.encode("utf-8")).digest().hex()[:6]
            removed = []
            for f in os.listdir(folder):
                if f.startswith(prefix + "_"):
                    os.remove(os.path.join(folder, f))
                    removed.append(f)
            if removed:
                from lib import shared
                shared.logger.info(f"[Xbox] 已删除账号 {username} 的缓存: {', '.join(removed)}")
        except Exception:
            pass

    def _api_auth(self) -> None:
        """登录校验:用户名+密码"""
        body = self._read_body()
        username = str(body.get("username", "") or "").strip()
        password = str(body.get("password", "") or "")

        if not username:
            self._respond({"ok": False, "message": "请输入用户名"})
            return

        ip = self.client_address[0] if self.client_address else ""
        result = user_manager.authenticate(username, password)
        if result["ok"]:
            # 登录成功:清除失败记录
            from lib import banlist
            banlist.clear_auth_failures(ip)
            self._respond({
                "ok": True,
                "token": result["token"],
                "role": result["role"],
                "username": result["username"],
                "permissions": result["permissions"],
                "system": result.get("system", False),
            })
        else:
            # 登录失败:记录并检查是否触发自动封禁
            # 但"账户已禁用"不计入失败次数(防止被误封)
            from lib import banlist
            msg = result["message"]
            if "禁用" not in msg:
                fail_info = banlist.record_auth_failure(ip)
                if fail_info["banned"]:
                    abc = banlist.get_auto_ban_config()
                    msg = f"登录失败次数过多,你的 IP 已被自动封禁(检测窗口: {abc['window']}秒, 封禁时长: {abc['banDuration']}分钟)"
                elif fail_info["remaining"] > 0:
                    msg = f"{msg}(登录失败记录: {fail_info['attempts']}/{banlist._FAIL_THRESHOLD})"
            self._respond({"ok": False, "message": msg})

    # ---- 用户管理 API ----

    def _api_users_list(self) -> None:
        """获取用户列表(需 permissions 权限;未授权时仅返回当前用户自身信息)"""
        if not _require_permission("permissions")(self):
            # 无 permissions 权限时,仅返回当前用户自身信息(用于改密码)
            current = _auth_user(self)
            username = current.get("username", "")
            user = user_manager.get_user(username) if username else None
            if user:
                safe = {k: v for k, v in user.items() if k != "password_hash"}
                self._respond({"ok": True, "users": [safe]})
            else:
                self._respond({"ok": True, "users": []})
            return
        self._respond({"ok": True, "users": user_manager.list_users()})

    def _api_users_create(self) -> None:
        """创建用户(需 permissions 权限;非系统管理员需验证 admin 密码)"""
        if not _require_permission("permissions")(self):
            return
        current = _auth_user(self)
        # 非系统管理员创建用户需验证 admin 密码
        if not (current.get("role") == "admin" and current.get("system")):
            body_tmp = self._read_body()
            admin_pw = body_tmp.get("admin_password", "")
            if not admin_pw or not user_manager.verify_admin_password(admin_pw):
                self._respond({"ok": False, "message": "admin 密码验证失败"})
                return
            body = body_tmp
        else:
            body = self._read_body()
        result = user_manager.add_user(
            body.get("username", "").strip(),
            body.get("password", ""),
            body.get("role", "viewer"),
            permissions=body.get("permissions") or {},
            no_role_inherit=body.get("no_role_inherit", False),
        )
        if result.get("ok"):
            _audit(self, "user", f"创建了用户 {body.get('username', '').strip()} (角色: {body.get('role', 'viewer')})")
        self._respond(result)

    def _api_users_update(self) -> None:
        """更新用户(仅 admin;非 admin 编辑他人需验证 admin 密码)"""
        body = self._read_body()
        username = body.get("username", "").strip()
        if not username:
            self._respond({"ok": False, "message": "缺少用户名"})
            return
        current = _auth_user(self)
        is_system_admin = current.get("role") == "admin" and current.get("system")
        is_self = current.get("username") == username
        target_user = user_manager.get_user(username)
        # 修改他人需要 permissions 权限;修改自己只需登录即可
        if not is_self and not _require_permission("permissions")(self):
            return
        # 非系统管理员编辑他人:需验证 admin 密码
        if not is_system_admin and not is_self:
            admin_pw = body.get("admin_password", "")
            if not admin_pw or not user_manager.verify_admin_password(admin_pw):
                self._respond({"ok": False, "message": "admin 密码验证失败"})
                return
        # 系统保留账户:仅内置系统管理员可编辑(自己除外)
        if not is_system_admin and not is_self and target_user and target_user.get("system_reserved"):
            self._respond({"ok": False, "message": "该账户为系统保留账户,仅系统管理员可编辑"})
            return
        # 不允许通过 API 修改自己的角色(防止误操作锁死)
        if is_self and body.get("role") and body["role"] != current.get("role"):
            self._respond({"ok": False, "message": "不能修改自己的角色"})
            return
        # 非系统管理员不允许修改自己的权限覆盖(防止提权)
        if is_self and not is_system_admin:
            body.pop("permissions", None)
            body.pop("no_role_inherit", None)
        # guest 用户不允许设置密码
        if target_user and target_user.get("username") == "guest" and body.get("password"):
            self._respond({"ok": False, "message": "guest 用户不允许设置密码"})
            return
        result = user_manager.update_user(username, **{
            k: v for k, v in body.items()
            if k in ("password", "role", "enabled", "permissions", "no_role_inherit", "system_reserved") and (k != "password" or v)
        })
        if result.get("ok"):
            changes = [k for k in body if k in ("password", "role", "enabled", "permissions", "no_role_inherit", "system_reserved") and (k != "password" or body.get(k))]
            action = "修改了自己" if is_self else f"更新了用户 {username}"
            _audit(self, "user", f"{action} (字段: {', '.join(changes)})")
        self._respond(result)

    def _api_users_delete(self) -> None:
        """删除用户(需 permissions 权限,非系统管理员需验证 admin 密码)"""
        if not _require_permission("permissions")(self):
            return
        body = self._read_body()
        username = body.get("username", "").strip()
        if not username:
            self._respond({"ok": False, "message": "缺少用户名"})
            return
        # 不允许删除自己
        current = _auth_user(self)
        if current.get("username") == username:
            self._respond({"ok": False, "message": "不能删除自己"})
            return
        # 非系统管理员操作需验证 admin 密码
        if not (current.get("role") == "admin" and current.get("system")):
            admin_pw = body.get("admin_password", "")
            if not admin_pw or not user_manager.verify_admin_password(admin_pw):
                self._respond({"ok": False, "message": "admin 密码验证失败"})
                return
        result = user_manager.delete_user(username)
        if result.get("ok"):
            _audit(self, "user", f"删除了用户 {username}")
        self._respond(result)

    def _api_roles_list(self) -> None:
        """获取角色列表(所有登录用户可读;仅 admin 可写)"""
        self._respond({"ok": True, "roles": user_manager.get_roles()})

    def _api_roles_update(self) -> None:
        """更新角色权限(仅 admin)"""
        if not _require_permission("permissions")(self):
            return
        body = self._read_body()
        role_name = body.get("role", "").strip()
        if not role_name:
            self._respond({"ok": False, "message": "缺少角色名"})
            return
        result = user_manager.update_role(
            role_name,
            label=body.get("label"),
            permissions=body.get("permissions"),
        )
        if result.get("ok"):
            _audit(self, "role", f"更新了角色 {role_name}")
        self._respond(result)

    def _api_roles_create(self) -> None:
        """新增自定义角色(仅 admin)"""
        if not _require_permission("permissions")(self):
            return
        body = self._read_body()
        name = body.get("name", "").strip()
        label = body.get("label", "").strip()
        permissions = body.get("permissions", [])
        if not name:
            self._respond({"ok": False, "message": "缺少角色名"})
            return
        result = user_manager.add_role(name, label=label or None, permissions=permissions)
        if result.get("ok"):
            _audit(self, "role", f"创建了角色 {name}")
        self._respond(result)

    def _api_roles_delete(self) -> None:
        """删除自定义角色(仅 admin)"""
        if not _require_permission("permissions")(self):
            return
        body = self._read_body()
        name = body.get("name", "").strip()
        if not name:
            self._respond({"ok": False, "message": "缺少角色名"})
            return
        result = user_manager.delete_role(name)
        if result.get("ok"):
            _audit(self, "role", f"删除了角色 {name}")
        self._respond(result)

    # ---- 当前用户信息 ----

    def _api_auth_me(self) -> None:
        """返回当前用户信息(含角色和权限)"""
        user = _auth_user(self)
        if not user.get("role"):
            self._respond({"ok": False, "message": "未登录"}, status=401)
            return
        self._respond({
            "ok": True,
            "username": user["username"],
            "role": user["role"],
            "permissions": user["permissions"],
            "system": user.get("system", False),
            "systemMode": _system_mode,
        })

    def _api_auth_logout(self) -> None:
        """注销当前会话"""
        token = _extract_session_token(self)
        if token:
            user_manager.logout(token)
        self._respond({"ok": True, "message": "已注销"})

    def _api_status(self) -> None:
        ns = _load_config_module()
        cfg = ns.get("wsConfig", {})
        webui = ns.get("webuiConfig", {})
        extra = {}
        if _status_provider:
            try:
                extra = _status_provider() or {}
            except Exception:
                extra = {}
        metrics = {}
        try:
            from lib.sys_metrics import metrics_collector
            metrics = metrics_collector.get_snapshot().get("current", {})
        except Exception:
            metrics = {}
        self._respond({
            "ok": True,
            "name": cfg.get("name", "EnderBridge"),
            "port": cfg.get("port", 8800),
            "webPort": webui.get("port", 18888),
            "clients": extra.get("clients", 0),
            "uptime": extra.get("uptime", 0),
            "players": extra.get("players", []),
            "version": _app_version or "EnderBridge",
            "systemMode": _system_mode,
            "metrics": metrics,
        })

    def _api_performance(self) -> None:
        """获取系统资源与 WebSocket 性能指标(实时当前值与 60s 时序历史)"""
        try:
            from lib.sys_metrics import metrics_collector
            self._respond(metrics_collector.get_snapshot())
        except Exception as e:
            self._respond({"ok": False, "message": str(e)})

    def _api_release_notes(self) -> None:
        """获取 Release Notes:优先使用 main.py 注入的 DESCRIPTION,否则从 GitHub API 拉取"""
        # DESCRIPTION 已设置时直接返回,无需请求 GitHub
        if _description is not None:
            self._respond({
                "ok": True,
                "release": {
                    "tag": _app_version or "",
                    "name": "",
                    "body": str(_description),
                    "html_url": "",
                }
            })
            return

        if not _github_repo or not _app_version:
            self._respond({"ok": False, "message": "未配置 GitHub 仓库信息"})
            return

        try:
            # 尝试按 tag 查找当前版本的 Release(版本号可能含空格如 b0.2.2 RC2,需 URL 编码)
            tag = urllib.parse.quote(_app_version)
            api_url = f"https://api.github.com/repos/{_github_repo}/releases/tags/{tag}"
            req = urllib.request.Request(api_url, headers=_github_headers())
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError:
                # tag 未找到,回退到最新 release。releases/latest 对仅含预览版的仓库
                # 返回 404,改用列表接口取最新一条(含预览版)。
                api_url = f"https://api.github.com/repos/{_github_repo}/releases?per_page=1"
                req = urllib.request.Request(api_url, headers=_github_headers())
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if isinstance(data, list):
                        if not data:
                            self._respond({"ok": True, "release": None, "message": "当前版本不是 Release 版"})
                            return
                        data = data[0]

            self._respond({
                "ok": True,
                "release": {
                    "tag": data.get("tag_name", ""),
                    "name": data.get("name", ""),
                    "body": data.get("body", ""),
                    "html_url": data.get("html_url", ""),
                    "published_at": data.get("published_at", ""),
                }
            })
        except urllib.error.HTTPError as e:
            if e.code == 404:
                self._respond({"ok": True, "release": None, "message": "当前版本不是 Release 版"})
            else:
                msg = f"GitHub API 错误: {e.code}"
                if e.code == 403:
                    msg = "GitHub API 请求过于频繁(403),请稍后再试"
                self._respond({"ok": False, "release": None, "current": _app_version, "message": msg})
        except Exception as e:
            self._respond({"ok": False, "release": None, "current": _app_version, "message": f"获取 Release Notes 失败: {e}"})

    def _api_update_check(self) -> None:
        """检查是否有新版本:对比当前版本与 GitHub 最新 Release"""
        if not _github_repo or not _app_version:
            self._respond({"ok": False, "message": "未配置 GitHub 仓库信息"})
            return
        try:
            # 获取最新 Release(含 prerelease)
            api_url = f"https://api.github.com/repos/{_github_repo}/releases?per_page=1"
            req = urllib.request.Request(api_url, headers=_github_headers())
            with urllib.request.urlopen(req, timeout=8) as resp:
                releases = json.loads(resp.read().decode("utf-8"))

            if not releases:
                self._respond({"ok": True, "current": _app_version, "latest": None, "update_available": False})
                return

            latest = releases[0]
            latest_tag = latest.get("tag_name", "")
            is_prerelease = latest.get("prerelease", False)
            has_asset = any(
                a.get("name", "").endswith((".zip", ".tar.gz", ".tgz"))
                for a in latest.get("assets", [])
            )

            self._respond({
                "ok": True,
                "current": _app_version,
                "latest": latest_tag,
                "latest_name": latest.get("name", ""),
                "is_prerelease": is_prerelease,
                "has_asset": has_asset,
                "body": latest.get("body", ""),
                "html_url": latest.get("html_url", ""),
                "published_at": latest.get("published_at", ""),
                "update_available": _version_gt(latest_tag, _app_version),
                "minimum_version": _minimum_version,
            })
        except urllib.error.HTTPError as e:
            msg = f"GitHub API 错误: {e.code}"
            if e.code == 403:
                msg = "GitHub API 请求过于频繁(403),你可以前往配置区配置GitHub Token以增加请求额度(免费)"
            self._respond({"ok": False, "current": _app_version, "message": msg})
        except Exception as e:
            self._respond({"ok": False, "current": _app_version, "message": f"检查更新失败: {e}"})

    def _api_update_releases(self) -> None:
        """获取所有 Release 列表(分页,含 prerelease)"""
        if not _github_repo:
            self._respond({"ok": False, "message": "未配置 GitHub 仓库信息"})
            return
        # 解析查询参数 page
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        page = int(qs.get("page", ["1"])[0])
        try:
            api_url = f"https://api.github.com/repos/{_github_repo}/releases?per_page=3&page={page}"
            req = urllib.request.Request(api_url, headers=_github_headers())
            with urllib.request.urlopen(req, timeout=8) as resp:
                releases = json.loads(resp.read().decode("utf-8"))

            items = []
            for r in releases:
                items.append({
                    "tag": r.get("tag_name", ""),
                    "name": r.get("name", ""),
                    "prerelease": r.get("prerelease", False),
                    "body": r.get("body", ""),
                    "html_url": r.get("html_url", ""),
                    "published_at": r.get("published_at", ""),
                    "current": r.get("tag_name", "") == _app_version,
                    "has_asset": any(
                        a.get("name", "").endswith((".zip", ".tar.gz", ".tgz"))
                        for a in r.get("assets", [])
                    ),
                    "below_min": _version_below_min(r.get("tag_name", "")),
                })
            self._respond({"ok": True, "releases": items, "page": page, "minimum_version": _minimum_version})
        except urllib.error.HTTPError as e:
            msg = f"GitHub API 错误: {e.code}"
            if e.code == 403:
                msg = "GitHub API 请求过于频繁(403),请稍后再试"
            self._respond({"ok": False, "message": msg})
        except Exception as e:
            self._respond({"ok": False, "message": f"获取 Release 列表失败: {e}"})

    def _api_update_install(self) -> None:
        """从本地 zip 或 GitHub Release 执行更新(需要 update 权限)"""
        import tempfile
        if not _require_permission("update")(self):
            return
        body = self._read_body()
        github_tag = body.get("github_tag", "").strip()
        file_path = body.get("path", "").strip()

        # GitHub tag 模式:下载 Release asset
        if github_tag:
            if not _github_repo:
                self._respond({"ok": False, "message": "未配置 GitHub 仓库信息"})
                return
            # 版本降级检查
            try:
                from main import _parse_version, MINIMIUM_ALLOWED_VERSION
                if MINIMIUM_ALLOWED_VERSION and _parse_version(github_tag) < _parse_version(MINIMIUM_ALLOWED_VERSION):
                    self._respond({"ok": False, "message": f"目标版本 {github_tag} 低于最低允许版本 {MINIMIUM_ALLOWED_VERSION},不允许降级"})
                    return
            except Exception:
                pass
            try:
                api_url = f"https://api.github.com/repos/{_github_repo}/releases/tags/{urllib.parse.quote(github_tag)}"
                req = urllib.request.Request(api_url, headers=_github_headers())
                with urllib.request.urlopen(req, timeout=10) as resp:
                    release = json.loads(resp.read().decode("utf-8"))
                # 查找 zip/tar.gz asset
                asset = None
                for a in release.get("assets", []):
                    name = a.get("name", "")
                    if name.endswith(".zip") or name.endswith((".tar.gz", ".tgz")):
                        asset = a
                        break
                if not asset:
                    self._respond({"ok": False, "message": f"版本 {github_tag} 中未找到压缩包附件"})
                    return
                # 下载到临时文件
                dl_url = asset["browser_download_url"]
                suffix = ".zip" if asset["name"].endswith(".zip") else ".tar.gz"
                tmp_fd, file_path = tempfile.mkstemp(suffix=suffix, prefix="enderbridge_update_")
                os.close(tmp_fd)
                dl_req = urllib.request.Request(dl_url, headers=_github_headers())
                with urllib.request.urlopen(dl_req, timeout=60) as resp:
                    with open(file_path, "wb") as f:
                        while True:
                            chunk = resp.read(8192)
                            if not chunk:
                                break
                            f.write(chunk)
            except Exception as e:
                self._respond({"ok": False, "message": f"下载失败: {e}"})
                return
        elif not file_path:
            self._respond({"ok": False, "message": "请提供压缩包路径或 GitHub 版本号"})
            return

        if not os.path.isfile(file_path):
            self._respond({"ok": False, "message": f"文件不存在: {file_path}"})
            return
        lower = file_path.lower()
        if not (lower.endswith(".zip") or lower.endswith((".tar.gz", ".tgz"))):
            self._respond({"ok": False, "message": "仅支持 .zip / .tar.gz 压缩包"})
            return
        # 触发重启并执行更新
        if _restart_handler is None:
            self._respond({"ok": False, "message": "重启处理器未注册"})
            return
        try:
            # 将更新路径写入临时文件供 main.py 读取
            update_marker = os.path.join(ROOT, ".update_pending")
            with open(update_marker, "w", encoding="utf-8") as f:
                f.write(file_path)
        except Exception as e:
            self._respond({"ok": False, "message": f"更新触发失败: {e}"})
            return
        # 先发送成功响应,再触发重启(避免 destroy() 在响应发送前关闭连接)
        _audit(self, "update", f"触发了更新 ({github_tag or os.path.basename(file_path)})")
        self._respond({"ok": True, "message": "服务器正在更新，更新完成后请点击仪表盘"})
        # 等待响应数据发送到浏览器后再触发重启
        import time
        time.sleep(0.5)
        try:
            _restart_handler()
        except Exception:
            pass  # 响应已发送,重启失败时用户可手动重启

    def _api_update_upload(self) -> None:
        """接收前端上传的压缩包文件,保存到临时目录(需要 update 权限)"""
        import tempfile
        if not _require_permission("update")(self):
            return
        try:
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in content_type:
                self._respond({"ok": False, "message": "请使用 multipart/form-data 上传"})
                return
            # 解析 boundary
            boundary = content_type.split("boundary=")[-1].strip()
            if not boundary:
                self._respond({"ok": False, "message": "无效的上传格式"})
                return
            content_length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(content_length)
            # 简易 multipart 解析:查找文件内容
            boundary_bytes = ("--" + boundary).encode()
            parts = raw.split(boundary_bytes)
            for part in parts:
                if b'filename="' not in part:
                    continue
                # 提取文件名
                header_end = part.find(b"\r\n\r\n")
                if header_end < 0:
                    continue
                header = part[:header_end].decode("utf-8", errors="replace")
                body = part[header_end + 4:]
                # 去除尾部 \r\n
                if body.endswith(b"\r\n"):
                    body = body[:-2]
                if body.endswith(b"--"):
                    body = body[:-2]
                # 提取原始文件名
                m = re.search(r'filename="([^"]+)"', header)
                orig_name = m.group(1) if m else "upload.zip"
                # 只接受 zip/tar.gz
                ln = orig_name.lower()
                if not (ln.endswith(".zip") or ln.endswith((".tar.gz", ".tgz"))):
                    self._respond({"ok": False, "message": "仅支持 .zip / .tar.gz 文件"})
                    return
                suffix = os.path.splitext(orig_name)[1]
                tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="enderbridge_upload_")
                os.close(tmp_fd)
                with open(tmp_path, "wb") as f:
                    f.write(body)
                self._respond({"ok": True, "path": tmp_path, "filename": orig_name})
                return
            self._respond({"ok": False, "message": "未找到文件内容"})
        except Exception as e:
            self._respond({"ok": False, "message": f"上传处理失败: {e}"})

    def _api_update_backups(self) -> None:
        """列出可用备份包（无需鉴权，仅展示元数据）"""
        try:
            from version_manager.package import list_backups, BACKUP_PREFIX
            backup_dir = os.path.dirname(ROOT)
            found = list_backups(backup_dir)
            items = []
            for path in reversed(found):  # 最新的排最前
                fname = os.path.basename(path)
                try:
                    size = os.path.getsize(path)
                    mtime = os.path.getmtime(path)
                except OSError:
                    size = 0
                    mtime = 0
                # 从文件名解析时间戳：EnderBridge_backup_YYYYMMDD_HHMMSS.zip
                stamp = fname[len(BACKUP_PREFIX):].replace(".zip", "")
                items.append({
                    "filename": fname,
                    "path": path,
                    "size": size,
                    "mtime": mtime,
                    "stamp": stamp,
                })
            self._respond({"ok": True, "backups": items})
        except Exception as e:
            self._respond({"ok": False, "message": f"获取备份列表失败: {e}"})

    def _api_update_rollback(self) -> None:
        """回滚到指定备份（需要 update 权限），完成后触发重启"""
        if not _require_permission("update")(self):
            return
        body = self._read_body()
        backup_path = body.get("path", "").strip()
        if not backup_path:
            self._respond({"ok": False, "message": "请指定备份文件路径"})
            return
        if not os.path.isfile(backup_path):
            self._respond({"ok": False, "message": f"备份文件不存在: {backup_path}"})
            return
        if _restart_handler is None:
            self._respond({"ok": False, "message": "重启处理器未注册"})
            return
        # 将回滚路径写入标记文件，main.py 重启后读取并执行回滚
        try:
            rollback_marker = os.path.join(ROOT, ".rollback_pending")
            with open(rollback_marker, "w", encoding="utf-8") as f:
                f.write(backup_path)
        except Exception as e:
            self._respond({"ok": False, "message": f"回滚触发失败: {e}"})
            return
        _audit(self, "update", f"触发了回滚 ({os.path.basename(backup_path)})")
        self._respond({"ok": True, "message": "服务器正在回滚，完成后自动重启"})
        import time
        time.sleep(0.5)
        try:
            _restart_handler()
        except Exception:
            pass

    def _api_security_audit(self) -> None:
        """执行依赖包安全健康检查与已知 CVE 比对"""
        try:
            from lib.security_audit import run_security_audit
            report = run_security_audit()
            self._respond(report)
        except Exception as e:
            self._respond({"ok": False, "message": f"依赖安全审计失败: {e}"})

    def _api_get_config(self) -> None:
        if not _require_permission("config")(self):
            return
        self._respond({"ok": True, "config": load_config()})

    def _api_save_config(self) -> None:
        if not _require_permission("config")(self):
            return
        body = self._read_body()
        if not body or "config" not in body or not isinstance(body.get("config"), dict):
            self._respond({"ok": False, "message": "请求数据格式错误: config 必须为 JSON 对象"})
            return
        # 保存前记录 localOnly 和 port 状态
        _old_cfg = _load_config_module().get("webuiConfig", {})
        old_local_only = _old_cfg.get("localOnly", False)
        old_port = int(_old_cfg.get("port") or 18888)
        try:
            save_config(body["config"])
        except Exception as e:
            self._respond({"ok": False, "message": f"保存失败: {e}"})
            return
        new_local_only = (body["config"].get("webui") or {}).get("localOnly", False)
        # localOnly/port 变更时原地重启 WebUI 以重新绑定地址
        new_port = int((body["config"].get("webui") or {}).get("port") or 18888)
        need_restart = (bool(old_local_only) != bool(new_local_only)) or (int(old_port) != new_port)
        _audit(self, "config", "保存了配置")
        if need_restart:
            # 先响应客户端,确保浏览器收到结果;再延迟重绑定(停止旧服务器会断开连接)
            self._respond({"ok": True, "message": "配置已保存,WebUI 正在重新绑定..."})
            def _deferred_restart():
                time.sleep(0.3)
                try:
                    restart_webui()
                except Exception:
                    pass
            threading.Thread(target=_deferred_restart, daemon=True).start()
        else:
            self._respond({"ok": True, "message": "配置已保存(部分设置需重启服务器生效)"})

    def _api_get_permissions(self) -> None:
        if not _require_permission("permissions")(self):
            return
        self._respond({"ok": True, "permissions": load_permissions()})

    def _api_save_permissions(self) -> None:
        if not _require_permission("permissions")(self):
            return
        body = self._read_body()
        perm = body.get("permissions")
        if not isinstance(perm, dict):
            self._respond({"ok": False, "message": "权限数据格式错误"})
            return
        # 规整结构,防止缺失键
        clean = {}
        for group in _perm_groups():
            value = perm.get(group)
            if group == "owner":
                clean[group] = str(value or "").strip() or "YourXboxName"
            elif isinstance(value, list):
                clean[group] = [str(v).strip() for v in value if str(v).strip()]
            else:
                clean[group] = []
        save_permissions(clean)
        self._respond({"ok": True, "message": "权限已保存"})

    def _api_get_mods(self) -> None:
        if not _require_permission("mods")(self):
            return
        ns = _load_config_module()
        mods = ns.get("mods", {}) or {"client": {}, "server": {}}
        # 附加模块可导入性检测
        result = {"client": {}, "server": {}}
        for side in ("client", "server"):
            for name, mod_path in (mods.get(side) or {}).items():
                result[side][name] = {
                    "path": mod_path,
                    "importable": _check_importable(mod_path),
                }
        self._respond({"ok": True, "mods": result})

    def _api_reload_all(self) -> None:
        if not _require_permission("mods")(self):
            return
        try:
            import asyncio
            from lib.mods import ServerModManager
            result = asyncio.run(ServerModManager.reload_all())
            self._respond({"ok": True, "result": result})
        except Exception as e:
            self._respond({"ok": False, "message": f"重载失败: {e}"})

    def _api_reload_mod(self) -> None:
        """重载单个 Mod(需要 mods 权限)"""
        if not _require_permission("mods")(self):
            return
        body = self._read_body()
        name = (body.get("name") or "").strip()
        side = (body.get("side") or "").strip()
        if not name:
            self._respond({"ok": False, "message": "缺少 name 参数"})
            return
        if side not in ("client", "server"):
            self._respond({"ok": False, "message": "side 必须为 client 或 server"})
            return
        try:
            import asyncio
            if side == "server":
                from lib.mods import ServerModManager
                result = asyncio.run(ServerModManager.reload(name))
            else:
                from lib.current import Current
                from lib.mods import ClientModManager
                success_all = []
                failed_all = []
                for client, manager in list(Current.client_mods.items()):
                    if not manager or not hasattr(manager, "reload"):
                        continue
                    r = asyncio.run(manager.reload(name))
                    cid = getattr(client, "id", None) or "?"
                    if r.get("success"):
                        success_all.append(f"{cid}:{name}")
                    else:
                        failed_all.append(f"{cid}:{name}")
                if not Current.client_mods:
                    result = {"success": False, "message": f"无客户端连接,无法重载客户端 Mod"}
                elif success_all:
                    result = {"success": True, "message": f"Client Mod {name} 已重载 ({len(success_all)} 个连接)"}
                else:
                    result = {"success": False, "message": failed_all[0] if failed_all else f"Client Mod {name} 重载失败"}
            ok = result.get("success", False)
            self._respond({"ok": ok, "message": result.get("message", "重载完成")})
        except Exception as e:
            self._respond({"ok": False, "message": f"重载失败: {e}"})

    def _resolve_mod_config(self, name: str, side: str) -> dict:
        """解析 Mod 配置的目标文件或 config.json 节"""
        mod_section_map = {
            "ai": "AIConfig",
            "bot": "botConfig",
            "message": "messageConfig",
            "spam": "spam",
            "chat": "spam",
            "tool": "utilsConfig",
        }
        # 1. 检查专属独立配置文件 (config/mods/<name>.json)
        candidate_files = [
            os.path.join(ROOT, "config", "mods", f"{name}.json"),
            os.path.join(ROOT, "config", "mods", f"{name.lower()}.json"),
        ]
        for cf in candidate_files:
            if os.path.exists(cf):
                rel = os.path.relpath(cf, ROOT).replace("\\", "/")
                return {"configType": "file", "target": rel, "filePath": cf, "section": None}

        # 2. 检查 config.json 对应配置节
        key_lower = name.strip().lower()
        if key_lower in mod_section_map:
            sec = mod_section_map[key_lower]
            return {"configType": "section", "target": f"config/config.json -> {sec}", "filePath": CONFIG_JSON, "section": sec}

        # 3. 默认独立配置文件 (位于 config/mods/<name>.json)
        default_file = os.path.join(ROOT, "config", "mods", f"{name}.json")
        rel = os.path.relpath(default_file, ROOT).replace("\\", "/")
        return {"configType": "file", "target": rel, "filePath": default_file, "section": None}

    def _api_get_mod_config(self) -> None:
        """获取指定 Mod 的配置文件或配置节 (需要 mods 权限)"""
        if not _require_permission("mods")(self):
            return
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        name = (qs.get("name", [""])[0] or "").strip()
        side = (qs.get("side", ["client"])[0] or "").strip()
        if not name:
            self._respond({"ok": False, "message": "缺少 name 参数"})
            return
        if side not in ("client", "server"):
            side = "client"

        resolved = self._resolve_mod_config(name, side)
        try:
            if resolved["configType"] == "file":
                filepath = resolved["filePath"]
                if os.path.exists(filepath):
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                else:
                    default_obj = {
                        "enabled": True,
                        "name": name,
                    }
                    content = json.dumps(default_obj, ensure_ascii=False, indent=2) + "\n"
            else:
                full_cfg = {}
                if os.path.exists(CONFIG_JSON):
                    with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                        full_cfg = json.load(f)
                elif os.path.exists(CONFIG_PY):
                    ns = _load_config_module()
                    full_cfg = {k: getattr(ns, k) for k in dir(ns) if not k.startswith("_") and not callable(getattr(ns, k))}
                elif os.path.exists(os.path.join(CONFIG_DIR, "config.example.json")):
                    with open(os.path.join(CONFIG_DIR, "config.example.json"), "r", encoding="utf-8") as f:
                        full_cfg = json.load(f)
                sec_val = full_cfg.get(resolved["section"], {})
                content = json.dumps(sec_val, ensure_ascii=False, indent=2) + "\n"

            self._respond({
                "ok": True,
                "name": name,
                "side": side,
                "configType": resolved["configType"],
                "target": resolved["target"],
                "content": content,
            })
        except Exception as e:
            self._respond({"ok": False, "message": f"读取 Mod 配置失败: {e}"})

    def _api_save_mod_config(self) -> None:
        """保存指定 Mod 的配置并执行热重载 (需要 mods 权限)"""
        if not _require_permission("mods")(self):
            return
        body = self._read_body()
        name = (body.get("name") or "").strip()
        side = (body.get("side") or "client").strip()
        content = body.get("content")
        do_reload = bool(body.get("reload", True))

        if not name:
            self._respond({"ok": False, "message": "缺少 name 参数"})
            return
        if content is None or not isinstance(content, str):
            self._respond({"ok": False, "message": "缺少 content 参数"})
            return

        # 实时语法校验
        try:
            parsed_data = json.loads(content)
        except json.JSONDecodeError as e:
            self._respond({
                "ok": False,
                "message": f"JSON 语法错误 (第 {e.lineno} 行, 第 {e.colno} 列): {e.msg}",
                "error": {
                    "line": e.lineno,
                    "column": e.colno,
                    "msg": e.msg,
                }
            })
            return

        resolved = self._resolve_mod_config(name, side)
        try:
            if resolved["configType"] == "file":
                filepath = resolved["filePath"]
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                if os.path.exists(filepath):
                    try:
                        import shutil
                        shutil.copy2(filepath, filepath + ".bak")
                    except Exception:
                        pass
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(parsed_data, f, ensure_ascii=False, indent=2)
                    f.write("\n")
            else:
                full_cfg = {}
                if os.path.exists(CONFIG_JSON):
                    with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                        full_cfg = json.load(f)
                    try:
                        import shutil
                        shutil.copy2(CONFIG_JSON, CONFIG_JSON + ".bak")
                    except Exception:
                        pass
                elif os.path.exists(CONFIG_PY):
                    ns = _load_config_module()
                    full_cfg = {k: getattr(ns, k) for k in dir(ns) if not k.startswith("_") and not callable(getattr(ns, k))}
                elif os.path.exists(os.path.join(CONFIG_DIR, "config.example.json")):
                    with open(os.path.join(CONFIG_DIR, "config.example.json"), "r", encoding="utf-8") as f:
                        full_cfg = json.load(f)

                full_cfg[resolved["section"]] = parsed_data
                with open(CONFIG_JSON, "w", encoding="utf-8") as f:
                    json.dump(full_cfg, f, ensure_ascii=False, indent=2)
                    f.write("\n")

                # 刷新配置缓存与命令别名
                try:
                    from lib.config_loader import reload_config
                    from lib.command import reload_all_aliases
                    reload_config()
                    reload_all_aliases()
                except Exception:
                    pass

            # 执行热重载
            reload_res = {"success": True, "message": "配置已保存"}
            if do_reload:
                import asyncio
                if side == "server":
                    from lib.mods import ServerModManager
                    r = asyncio.run(ServerModManager.reload(name))
                    reload_res = {"success": r.get("success", False), "message": r.get("message", "重载完成")}
                else:
                    from lib.current import Current
                    from lib.mods import ClientModManager
                    success_all = []
                    failed_all = []
                    for client, manager in list(Current.client_mods.items()):
                        if not manager or not hasattr(manager, "reload"):
                            continue
                        r = asyncio.run(manager.reload(name))
                        cid = getattr(client, "id", None) or "?"
                        if r.get("success"):
                            success_all.append(f"{cid}:{name}")
                        else:
                            failed_all.append(f"{cid}:{name}")
                    if not Current.client_mods:
                        reload_res = {"success": True, "message": "配置已保存并同步（当前无活跃客户端连接，重载将在客户端连接时生效）"}
                    elif success_all:
                        reload_res = {"success": True, "message": f"Client Mod {name} 已热重载 ({len(success_all)} 个客户端)"}
                    else:
                        reload_res = {"success": False, "message": failed_all[0] if failed_all else f"Client Mod {name} 重载失败"}

            self._respond({
                "ok": True,
                "reloadOk": reload_res.get("success", False),
                "message": f"配置已保存。{reload_res.get('message', '')}".rstrip("。") if reload_res.get("message") != "配置已保存" else "配置已保存",
                "target": resolved["target"],
                "configType": resolved["configType"],
            })
        except Exception as e:
            self._respond({"ok": False, "message": f"保存 Mod 配置失败: {e}"})

    # ===== Studio 创意资产工坊 API =====

    def _api_studio_get_assets(self) -> None:
        """获取指定分类或全部资产列表 (需要 mods 权限)"""
        if not _require_permission("mods")(self):
            return
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        cat = (qs.get("category", [""])[0] or "").strip()
        from lib.studio import list_assets, CATEGORIES
        try:
            if cat:
                assets = list_assets(cat)
                self._respond({"ok": True, "category": cat, "assets": assets})
            else:
                all_assets = {}
                for c in CATEGORIES:
                    all_assets[c] = list_assets(c)
                self._respond({"ok": True, "assets": all_assets})
        except Exception as e:
            self._respond({"ok": False, "message": f"获取资产失败: {e}"})

    def _api_studio_get_asset_file(self) -> None:
        """读取/下载指定资产文件 (需要 mods 权限)"""
        if not _require_permission("mods")(self):
            return
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        cat = (qs.get("category", [""])[0] or "").strip()
        fn = (qs.get("file", [""])[0] or "").strip()
        as_text = qs.get("text", ["0"])[0] in ("1", "true")
        if not cat or not fn:
            self._respond({"ok": False, "message": "缺少 category 或 file 参数"})
            return
        try:
            import mimetypes
            from lib.studio import get_asset_file_path, CATEGORIES
            filepath = get_asset_file_path(cat, fn)
            if as_text:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                self._respond({"ok": True, "filename": fn, "category": cat, "content": content})
                return

            mime = CATEGORIES.get(cat, {}).get("mime") or mimetypes.guess_type(fn)[0] or "application/octet-stream"
            with open(filepath, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self._respond({"ok": False, "message": "文件不存在"}, status=404)
        except Exception as e:
            self._respond({"ok": False, "message": f"读取失败: {e}"})

    def _api_studio_get_palette(self) -> None:
        """获取方块调色板 (需要 mods 权限)"""
        if not _require_permission("mods")(self):
            return
        from lib.studio import get_block_palette
        try:
            blocks = get_block_palette()
            self._respond({"ok": True, "blocks": blocks})
        except Exception as e:
            self._respond({"ok": False, "message": f"读取调色板失败: {e}"})

    def _api_studio_get_blueprint_voxels(self) -> None:
        """获取蓝图离线 3D 体素渲染数据 (需要 mods 权限)"""
        if not _require_permission("mods")(self):
            return
        from lib.studio import parse_blueprint_voxels
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        filename = (query.get("file") or [""])[0]
        category = (query.get("category") or ["ezmatic"])[0]
        max_blocks_str = (query.get("max_blocks") or ["50000"])[0]
        try:
            max_blocks = max(100, min(200000, int(max_blocks_str)))
        except ValueError:
            max_blocks = 50000

        if not filename:
            self._respond({"ok": False, "message": "未指定蓝图文件名 (file 参数)"}, status=400)
            return

        try:
            data = parse_blueprint_voxels(category=category, filename=filename, max_blocks=max_blocks)
            self._respond({"ok": True, **data})
        except FileNotFoundError:
            self._respond({"ok": False, "message": f"蓝图文件未找到: {filename}"}, status=404)
        except Exception as e:
            self._respond({"ok": False, "message": f"蓝图解析失败: {e}"}, status=400)

    def _api_studio_post_blueprint_voxels(self) -> None:
        """从客户端直接接收本地蓝图文件并实时返回 3D 体素 (无需连接 MC 客户端)"""
        if not _require_permission("mods")(self):
            return
        import base64
        import tempfile
        from lib.studio import parse_blueprint_voxels
        body = self._read_body()
        filename = (body.get("filename") or "local.litematic").strip()
        data_b64 = body.get("dataBase64") or ""
        max_blocks = int(body.get("max_blocks") or 50000)

        if not data_b64:
            self._respond({"ok": False, "message": "未提供蓝图数据 (dataBase64)"}, status=400)
            return

        try:
            raw_bytes = base64.b64decode(data_b64)
            with tempfile.NamedTemporaryFile(suffix=".litematic", delete=False) as tf:
                tf.write(raw_bytes)
                tf_path = tf.name
            try:
                data = parse_blueprint_voxels(file_path=tf_path, max_blocks=max_blocks)
                data["name"] = filename
                self._respond({"ok": True, **data})
            finally:
                try:
                    os.unlink(tf_path)
                except Exception:
                    pass
        except Exception as e:
            self._respond({"ok": False, "message": f"本地蓝图解析失败: {e}"}, status=400)

    def _api_studio_get_blueprint_html(self) -> None:
        """导出独立离线单文件 3D 蓝图预览 HTML"""
        if not _require_permission("mods")(self):
            return
        from lib.studio import parse_blueprint_voxels, generate_standalone_blueprint_html
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        filename = (query.get("file") or [""])[0]
        category = (query.get("category") or ["ezmatic"])[0]
        if not filename:
            self._respond({"ok": False, "message": "未指定蓝图文件名"}, status=400)
            return
        try:
            data = parse_blueprint_voxels(category=category, filename=filename)
            html_str = generate_standalone_blueprint_html(data)
            content = html_str.encode("utf-8")
            stem = os.path.splitext(filename)[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Content-Disposition", f'attachment; filename="{urllib.parse.quote(stem)}_3d_preview.html"')
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self._respond({"ok": False, "message": "文件不存在"}, status=404)
        except Exception as e:
            self._respond({"ok": False, "message": f"生成 HTML 失败: {e}"}, status=400)

    def _api_studio_textures_status(self) -> None:
        """获取方块纹理包当前状态与统计 (需要 config 或 mods 权限)"""
        user = _auth_user(self)
        perms = user.get("permissions", [])
        if "config" not in perms and "mods" not in perms and "*" not in perms and "admin" not in perms:
            if not user.get("role"):
                self._respond_denied()
            else:
                self._respond({"ok": False, "message": "无权限:需要 config 或 mods 权限"}, status=403)
            return
        from lib.studio import get_textures_status
        try:
            stat = get_textures_status()
            self._respond({"ok": True, "data": stat})
        except Exception as e:
            self._respond({"ok": False, "message": f"获取材质包状态失败: {e}"}, status=500)

    def _api_studio_textures_download(self) -> None:
        """下载/更新方块材质包，或从本机客户端提取 (需要 config 或 mods 权限)"""
        user = _auth_user(self)
        perms = user.get("permissions", [])
        if "config" not in perms and "mods" not in perms and "*" not in perms and "admin" not in perms:
            if not user.get("role"):
                self._respond_denied()
            else:
                self._respond({"ok": False, "message": "无权限:需要 config 或 mods 权限"}, status=403)
            return
        body = self._read_body()
        source = str(body.get("source") or "online").strip().lower()
        url = str(body.get("url") or "").strip()
        from lib.studio import download_online_textures, extract_local_minecraft_textures
        try:
            if source == "local":
                res = extract_local_minecraft_textures(force=True)
            else:
                res = download_online_textures(source_url=url, fallback_local=True)
            self._respond(res)
        except Exception as e:
            self._respond({"ok": False, "message": f"材质包操作失败: {e}"}, status=500)

    def _api_studio_textures_uninstall(self) -> None:
        """卸载方块材质包并释放空间 (需要 config 或 mods 权限)"""
        user = _auth_user(self)
        perms = user.get("permissions", [])
        if "config" not in perms and "mods" not in perms and "*" not in perms and "admin" not in perms:
            if not user.get("role"):
                self._respond_denied()
            else:
                self._respond({"ok": False, "message": "无权限:需要 config 或 mods 权限"}, status=403)
            return
        from lib.studio import uninstall_textures
        try:
            res = uninstall_textures()
            self._respond(res)
        except Exception as e:
            self._respond({"ok": False, "message": f"卸载失败: {e}"}, status=500)

    def _api_studio_upload(self) -> None:
        """上传资产文件 (支持 Base64 JSON 与 multipart/form-data)"""
        if not _require_permission("mods")(self):
            return
        import base64
        from lib.studio import save_asset_file
        content_type = self.headers.get("Content-Type", "")

        # 1. 支持 JSON Base64 上传
        if "application/json" in content_type:
            body = self._read_body()
            cat = (body.get("category") or "").strip()
            fn = (body.get("filename") or "").strip()
            b64_data = body.get("dataBase64") or ""
            raw_text = body.get("text")
            if not cat or not fn:
                self._respond({"ok": False, "message": "缺少 category 或 filename 参数"})
                return
            try:
                if b64_data:
                    data = base64.b64decode(b64_data)
                elif raw_text is not None:
                    data = raw_text.encode("utf-8")
                else:
                    self._respond({"ok": False, "message": "缺少文件数据"})
                    return
                res = save_asset_file(cat, fn, data)
                self._respond(res)
            except Exception as e:
                self._respond({"ok": False, "message": f"保存文件失败: {e}"})
            return

        # 2. 支持 multipart/form-data 上传
        if "multipart/form-data" in content_type:
            boundary = content_type.split("boundary=")[-1].strip()
            if not boundary:
                self._respond({"ok": False, "message": "无效上传格式"})
                return
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            boundary_bytes = ("--" + boundary).encode()
            parts = raw.split(boundary_bytes)

            category = ""
            filename = ""
            file_data = b""

            for part in parts:
                if b'name="category"' in part:
                    header_end = part.find(b"\r\n\r\n")
                    if header_end >= 0:
                        category = part[header_end + 4:].rstrip(b"\r\n").decode("utf-8", errors="ignore").strip()
                if b'filename="' in part:
                    fn_match = re.search(rb'filename="([^"]+)"', part)
                    if fn_match:
                        filename = fn_match.group(1).decode("utf-8", errors="replace")
                    header_end = part.find(b"\r\n\r\n")
                    if header_end >= 0:
                        file_data = part[header_end + 4:].rstrip(b"\r\n")

            if not category or not filename or not file_data:
                self._respond({"ok": False, "message": "解析上传数据失败 (缺少 category、filename 或 file)"})
                return
            try:
                res = save_asset_file(category, filename, file_data)
                self._respond(res)
            except Exception as e:
                self._respond({"ok": False, "message": f"保存文件失败: {e}"})
            return

        self._respond({"ok": False, "message": "不支持的上传 Content-Type"})

    def _api_studio_save_text(self) -> None:
        """保存文本资产 (如 .mcfunc 脚本文件)"""
        if not _require_permission("mods")(self):
            return
        body = self._read_body()
        cat = (body.get("category") or "").strip()
        fn = (body.get("filename") or "").strip()
        content = body.get("content")
        if not cat or not fn or content is None:
            self._respond({"ok": False, "message": "缺少 category、filename 或 content 参数"})
            return
        from lib.studio import save_asset_file
        try:
            res = save_asset_file(cat, fn, content.encode("utf-8"))
            self._respond(res)
        except Exception as e:
            self._respond({"ok": False, "message": f"保存失败: {e}"})

    def _api_studio_delete_asset(self) -> None:
        """删除指定资产文件 (需要 mods 权限)"""
        if not _require_permission("mods")(self):
            return
        body = self._read_body()
        cat = (body.get("category") or "").strip()
        fn = (body.get("filename") or "").strip()
        if not cat or not fn:
            self._respond({"ok": False, "message": "缺少 category 或 filename 参数"})
            return
        from lib.studio import delete_asset_file
        try:
            res = delete_asset_file(cat, fn)
            self._respond(res)
        except Exception as e:
            self._respond({"ok": False, "message": f"删除失败: {e}"})

    def _api_studio_action(self) -> None:
        """在游戏内执行 Studio 动作 (需要 mods 权限)"""
        if not _require_permission("mods")(self):
            return
        body = self._read_body()
        action = (body.get("action") or "").strip()
        cat = (body.get("category") or "").strip()
        fn = (body.get("filename") or "").strip()
        params = body.get("params") or {}
        if not action:
            self._respond({"ok": False, "message": "缺少 action 参数"})
            return
        from lib.studio import execute_studio_action
        try:
            res = execute_studio_action(action, cat, fn, params)
            self._respond(res)
        except Exception as e:
            self._respond({"ok": False, "message": f"执行失败: {e}"})

    def _api_firewall_add_rule(self) -> None:
        """添加 Windows 防火墙入站规则,允许 WebUI 端口(需要 config 权限)"""
        if not _require_permission("config")(self):
            return
        if sys.platform != "win32":
            self._respond({"ok": False, "message": "此功能仅支持 Windows"})
            return
        webui = _load_config_module().get("webuiConfig", {})
        port = int(webui.get("port") or 18888)
        rule_name = f"EnderBridge WebUI ({port})"
        # 尝试通过 netsh 添加防火墙规则
        try:
            import subprocess
            result = subprocess.run(
                [
                    "netsh", "advfirewall", "firewall", "add", "rule",
                    f"name={rule_name}",
                    "dir=in", "action=allow", "protocol=TCP",
                    f"localport={port}",
                    "enable=yes",
                ],
                capture_output=True, timeout=10,
            )
            def _decode_output(data: bytes) -> str:
                if not data:
                    return ""
                for enc in ("gbk", "utf-8", "cp936", "latin1"):
                    try:
                        return data.decode(enc)
                    except (UnicodeDecodeError, LookupError):
                        pass
                return data.decode("utf-8", errors="replace")

            stdout_str = _decode_output(result.stdout)
            stderr_str = _decode_output(result.stderr)
            if result.returncode == 0 and ("确定" in stdout_str or "ok" in stdout_str.lower()):
                self._respond({"ok": True, "message": f"已添加防火墙规则: {rule_name} (端口 {port})"})
            else:
                err = stdout_str.strip() + stderr_str.strip()
                if "需要提升" in err or "Run as administrator" in err or "拒绝访问" in err or result.returncode == 5:
                    self._respond({"ok": False, "message": "需要管理员权限,请在管理员终端中手动执行", "command": f'netsh advfirewall firewall add rule name="{rule_name}" dir=in action=allow protocol=TCP localport={port}'})
                else:
                    self._respond({"ok": False, "message": f"添加失败: {err}", "command": f'netsh advfirewall firewall add rule name="{rule_name}" dir=in action=allow protocol=TCP localport={port}'})
        except Exception as e:
            self._respond({"ok": False, "message": f"执行失败: {e}", "command": f'netsh advfirewall firewall add rule name="{rule_name}" dir=in action=allow protocol=TCP localport={port}'})

    # ---- 封禁管理 API ----

    def _api_banlist_list(self) -> None:
        """获取封禁列表(需要 banlist 权限)"""
        if not _require_permission("banlist")(self):
            return
        from lib import banlist
        bans = banlist.list_bans()
        # 统计自动封禁数量(用于仪表盘攻击警报)
        auto_ban_count = sum(
            1 for info in bans.values()
            if (info.get("reason") or "").startswith("自动封禁")
        )
        self._respond({"ok": True, "bans": bans, "count": len(bans), "autoBanCount": auto_ban_count})

    def _api_banlist_add(self) -> None:
        """封禁 IP(需要 banlist 权限)"""
        if not _require_permission("banlist")(self):
            return
        body = self._read_body()
        ip = (body.get("ip") or "").strip()
        reason = (body.get("reason") or "").strip()
        duration = int(body.get("duration", 0))  # 分钟,0=永久
        if not ip:
            self._respond({"ok": False, "message": "请输入 IP 地址"})
            return
        # 基本格式校验
        import re
        if not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip) and ":" not in ip:
            self._respond({"ok": False, "message": f"无效的 IP 地址: {ip}"})
            return
        from lib import banlist
        if ip in banlist._PROTECTED_IPS:
            self._respond({"ok": False, "message": f"{ip} 是受保护的本地地址,无法封禁"})
            return
        if banlist.ban(ip, reason, duration=duration):
            # 尝试断开该 IP 的现有连接
            self._disconnect_banned_ip(ip)
            dur_text = "永久" if duration <= 0 else f"{duration} 分钟"
            _audit(self, "ban", f"封禁了 {ip} (原因: {reason or '无'}, 时长: {dur_text})")
            self._respond({"ok": True, "message": f"已封禁 {ip}"})
        else:
            self._respond({"ok": False, "message": f"{ip} 已在封禁列表中"})

    def _api_banlist_batch_add(self) -> None:
        """批量封禁 IP(需要 banlist 权限)"""
        if not _require_permission("banlist")(self):
            return
        body = self._read_body()
        raw_ips = body.get("ips") or []
        reason = (body.get("reason") or "管理员批量封禁").strip()
        duration = int(body.get("duration", 0))  # 分钟, 0=永久
        if isinstance(raw_ips, str):
            import re
            raw_ips = re.split(r"[\r\n,;\s]+", raw_ips)
        from lib import banlist
        import ipaddress
        banned = []
        skipped = []
        invalid = []
        for raw in raw_ips:
            text = str(raw).strip()
            if not text:
                continue
            if ":" in text and not text.startswith("[") and text.count(":") == 1:
                text = text.split(":", 1)[0]
            try:
                if "/" in text:
                    net = ipaddress.ip_network(text, strict=False)
                    if net.num_addresses > 1024:
                        invalid.append(f"{text}(子网超1024)")
                        continue
                    candidates = [str(h) for h in net.hosts()] if net.num_addresses > 1 else [str(net.network_address)]
                else:
                    ipaddress.ip_address(text)
                    candidates = [text]
            except ValueError:
                invalid.append(text)
                continue

            for cand in candidates:
                if cand in banlist._PROTECTED_IPS or cand in skipped or cand in banned:
                    skipped.append(cand)
                    continue
                if banlist.ban(cand, reason, duration=duration):
                    self._disconnect_banned_ip(cand)
                    banned.append(cand)
                else:
                    skipped.append(cand)

        dur_text = "永久" if duration <= 0 else f"{duration} 分钟"
        _audit(self, "ban", f"批量封禁了 {len(banned)} 个 IP (原因: {reason}, 时长: {dur_text})")
        msg = f"成功封禁 {len(banned)} 个 IP"
        if skipped:
            msg += f"，跳过 {len(skipped)} 个已存在或受保护的 IP"
        if invalid:
            msg += f"，忽略 {len(invalid)} 个无效输入"
        self._respond({
            "ok": True,
            "banned_count": len(banned),
            "skipped_count": len(skipped),
            "invalid_count": len(invalid),
            "message": msg,
        })

    def _api_banlist_remove(self) -> None:
        """解封 IP(单条或批量，需要 banlist 权限)"""
        if not _require_permission("banlist")(self):
            return
        body = self._read_body()
        from lib import banlist
        # 支持批量解封
        ips = body.get("ips")
        if isinstance(ips, list):
            removed = []
            for ip_item in ips:
                ip_clean = str(ip_item).strip()
                if ip_clean and banlist.unban(ip_clean):
                    removed.append(ip_clean)
            _audit(self, "ban", f"批量解封了 {len(removed)} 个 IP")
            self._respond({"ok": True, "count": len(removed), "message": f"已批量解封 {len(removed)} 个 IP"})
            return
        ip = (body.get("ip") or "").strip()
        if not ip:
            self._respond({"ok": False, "message": "请输入 IP 地址"})
            return
        if banlist.unban(ip):
            _audit(self, "ban", f"解封了 {ip}")
            self._respond({"ok": True, "message": f"已解封 {ip}"})
        else:
            self._respond({"ok": False, "message": f"{ip} 不在封禁列表中"})

    def _api_banlist_edit(self) -> None:
        """修改封禁时长(需要 banlist 权限)"""
        if not _require_permission("banlist")(self):
            return
        body = self._read_body()
        ip = (body.get("ip") or "").strip()
        duration = int(body.get("duration", 0))  # 分钟,0=永久
        if not ip:
            self._respond({"ok": False, "message": "请输入 IP 地址"})
            return
        from lib import banlist
        if banlist.set_ban_duration(ip, duration):
            dur_text = "永久" if duration <= 0 else f"{duration} 分钟"
            _audit(self, "ban", f"修改了 {ip} 的封禁时长为 {dur_text}")
            self._respond({"ok": True, "message": f"已将 {ip} 的封禁时长改为 {dur_text}"})
        else:
            self._respond({"ok": False, "message": f"{ip} 不在封禁列表中"})

    def _disconnect_banned_ip(self, ip: str) -> None:
        """断开指定 IP 的所有 WebSocket 连接"""
        try:
            from main import connections
            import asyncio
            for conn in list(connections):
                remote = getattr(conn.ws, "remote_address", None)
                if remote and remote[0] == ip:
                    asyncio.ensure_future(conn.ws.close(1008, "你的 IP 已被封禁"))
        except Exception:
            pass

    def _api_banlist_auto_ban_status(self) -> None:
        """获取自动封禁开关状态"""
        if not _require_permission("banlist")(self):
            return
        from lib import banlist
        self._respond({"ok": True, "enabled": banlist.is_auto_ban_enabled()})

    def _api_banlist_auto_ban_toggle(self) -> None:
        """切换自动封禁开关"""
        if not _require_permission("banlist")(self):
            return
        body = self._read_body()
        enabled = body.get("enabled", True)
        from lib import banlist
        banlist.set_auto_ban(bool(enabled))
        _audit(self, "config", f"{'启用了' if enabled else '关闭了'}自动封禁")
        # 持久化到 config.json
        try:
            from lib.config_loader import get_config, save_config
            cfg = get_config()
            wb = cfg.setdefault("webuiConfig", {})
            wb["autoBan"] = banlist.is_auto_ban_enabled()
            save_config(cfg)
        except Exception:
            pass
        self._respond({"ok": True, "enabled": banlist.is_auto_ban_enabled()})

    def _api_banlist_auto_ban_config_get(self) -> None:
        """获取自动封禁详细配置(window/threshold/duration)"""
        if not _require_permission("banlist")(self):
            return
        from lib import banlist
        self._respond({"ok": True, **banlist.get_auto_ban_config()})

    def _api_banlist_auto_ban_config_set(self) -> None:
        """更新自动封禁详细配置(window/threshold/duration)"""
        if not _require_permission("banlist")(self):
            return
        body = self._read_body()
        from lib import banlist
        banlist.set_auto_ban_config(body)
        _audit(self, "config", f"修改了自动封禁参数: 窗口={body.get('window','?')}秒, 阈值={body.get('threshold','?')}次, 时长={body.get('banDuration','?')}分钟")
        # 同步到 config.json
        try:
            from lib.config_loader import get_config, save_config
            cfg = get_config()
            wb = cfg.setdefault("webuiConfig", {})
            wb["autoBanConfig"] = banlist.get_auto_ban_config()
            wb["autoBan"] = banlist.is_auto_ban_enabled()
            save_config(cfg)
        except Exception:
            pass
        self._respond({"ok": True, **banlist.get_auto_ban_config()})

    def _api_restart(self) -> None:
        """一键重启:触发主程序后台执行优雅关闭并重启进程(需要 restart 权限)"""
        if not _require_permission("restart")(self):
            return
        if _restart_handler is None:
            self._respond({"ok": False, "message": "重启处理器未注册(请通过 main.py 启动服务器)"})
            return
        _audit(self, "system", "触发了服务器重启")
        try:
            _restart_handler()
        except Exception as e:
            self._respond({"ok": False, "message": f"重启触发失败: {e}"})
            return
        # 处理器在后台线程执行,这里先响应,保证浏览器能收到结果
        self._respond({"ok": True, "message": "服务器正在重启,请稍候..."})

    # ---- 审计日志 API ----

    def _api_audit_logs(self) -> None:
        """读取审计日志(需要 audit 权限)"""
        if not _require_permission("audit")(self):
            return
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        sender = qs.get("sender", [None])[0]
        type_ = qs.get("type", [None])[0]
        try:
            limit = min(int(qs.get("limit", ["50"])[0]), 200)
        except (ValueError, IndexError):
            limit = 50
        try:
            offset = max(int(qs.get("offset", ["0"])[0]), 0)
        except (ValueError, IndexError):
            offset = 0
        from lib.logger import audit_log
        result = audit_log.query(sender=sender, type_=type_, limit=limit, offset=offset)
        self._respond({"ok": True, **result})

    def _api_audit_logs_export(self) -> None:
        """导出审计日志(需要 audit 权限, 支持 format=csv|json)"""
        if not _require_permission("audit")(self):
            return
        import csv
        import io
        import json
        from datetime import datetime

        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        format_ = (qs.get("format", ["csv"])[0] or "csv").lower()
        sender = qs.get("sender", [None])[0]
        type_ = qs.get("type", [None])[0]

        from lib.logger import audit_log
        # 查询所有匹配记录, 导出上限 10000 条
        result = audit_log.query(sender=sender, type_=type_, limit=10000, offset=0)
        records = result.get("records", [])

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if format_ == "json":
            filename = f"audit_log_{stamp}.json"
            content = json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            filename = f"audit_log_{stamp}.csv"
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerow(["时间", "类型", "发送者", "内容"])
            for r in records:
                writer.writerow([
                    r.get("ts", ""),
                    r.get("type", ""),
                    r.get("sender", ""),
                    r.get("message", ""),
                ])
            # 添加 UTF-8 BOM，确保 Excel 打开中文不乱码
            content = ("\ufeff" + out.getvalue()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    # ---- 实时日志流(SSE) ----

    def _api_logs_recent(self) -> None:
        """获取最近 N 条日志(需要 console 权限,用于 SSE 初始加载)"""
        if not _require_permission("console")(self):
            return
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        try:
            limit = min(int(qs.get("limit", ["200"])[0]), 500)
        except (ValueError, IndexError):
            limit = 200
        from lib.logger import _live_log
        logs = _live_log.get_recent(limit)
        self._respond({"ok": True, "logs": logs})

    def _api_logs_stream(self) -> None:
        """SSE 实时日志流(需要 console 权限)

        首次连接时发送最近 50 条日志作为历史,
        之后持续推送新日志直到客户端断开。
        """
        if not _require_permission("console")(self):
            return
        from lib.logger import _live_log
        try:
            # 发送 SSE 响应头
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            # 发送最近 50 条历史日志
            recent = _live_log.get_recent(50)
            for record in recent:
                data = json.dumps(record, ensure_ascii=False)
                self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
            self.wfile.flush()

            # 订阅新日志
            _queue = []
            _queue_lock = threading.Lock()
            _event = threading.Event()

            def _on_log(record):
                with _queue_lock:
                    _queue.append(record)
                _event.set()

            _live_log.subscribe(_on_log)

            try:
                while True:
                    # 心跳:每 15 秒发送一次,检测客户端是否断开
                    _event.wait(timeout=15)
                    _event.clear()

                    # 取出并发送所有排队的日志
                    with _queue_lock:
                        batch = list(_queue)
                        _queue.clear()
                    for record in batch:
                        data = json.dumps(record, ensure_ascii=False)
                        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                    # 空闲时发心跳注释保持连接
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
            except (ConnectionAbortedError, BrokenPipeError, OSError):
                pass  # 客户端已断开
            finally:
                _live_log.unsubscribe(_on_log)
        except (ConnectionAbortedError, BrokenPipeError, OSError):
            pass

    def _handle_ws_console(self) -> None:
        """WebSocket 实时双向控制台 (需要 console 权限)

        握手后完成：
        1. 初始下发最近 50 条历史日志 {"type": "history", "logs": [...]}
        2. 实时推送新日志 {"type": "log", "record": {...}}
        3. 双向接收客户端执行命令请求 {"type": "command", "command": "...", "id": "..."} 并返回结果
        4. 自动心跳保持与异常断开安全回收
        """
        if not _require_permission("console")(self):
            return
        sec_key = self.headers.get("Sec-WebSocket-Key", "").strip()
        if not sec_key:
            self._respond({"ok": False, "message": "缺少 Sec-WebSocket-Key 请求头"}, status=400)
            return

        try:
            from webui.websocket import (
                compute_accept_key,
                WebSocketConnection,
                read_frame,
                OP_TEXT,
                OP_PING,
                OP_PONG,
                OP_CLOSE,
            )
            accept_val = compute_accept_key(sec_key)
            self.send_response(101, "Switching Protocols")
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept_val)
            self.end_headers()
            self.wfile.flush()
            self.close_connection = True

            ws = WebSocketConnection(self.request)
            from lib.logger import _live_log

            # 1) 下发历史日志
            recent = _live_log.get_recent(50)
            ws.send_json({"type": "history", "logs": recent})

            # 2) 订阅实时日志
            def _on_log(record):
                if not ws.is_closed:
                    try:
                        ws.send_json({"type": "log", "record": record})
                    except Exception:
                        pass

            _live_log.subscribe(_on_log)

            # 3) 消息循环
            self.request.settimeout(1.0)
            last_ping_time = time.time()

            try:
                while not ws.is_closed:
                    now = time.time()
                    if now - last_ping_time >= 15.0:
                        ws.send_ping()
                        last_ping_time = now

                    try:
                        opcode, payload = read_frame(self.request)
                    except socket.timeout:
                        continue
                    except (EOFError, ConnectionResetError, BrokenPipeError, OSError):
                        break

                    if opcode == OP_CLOSE:
                        ws.send_close()
                        break
                    elif opcode == OP_PING:
                        ws.send_pong(payload)
                    elif opcode == OP_PONG:
                        pass
                    elif opcode == OP_TEXT:
                        try:
                            msg_text = payload.decode("utf-8")
                            data = json.loads(msg_text)
                        except Exception:
                            continue

                        msg_type = data.get("type")
                        if msg_type == "ping":
                            ws.send_json({"type": "pong"})
                        elif msg_type == "command":
                            command = data.get("command", "").strip()
                            req_id = data.get("id")

                            user = _auth_user(self)
                            if user.get("is_guest") or "console" not in user.get("permissions", []):
                                ws.send_json({
                                    "type": "cmd-result",
                                    "id": req_id,
                                    "ok": False,
                                    "message": "无命令执行权限",
                                })
                                continue

                            if not command:
                                ws.send_json({
                                    "type": "cmd-result",
                                    "id": req_id,
                                    "ok": False,
                                    "message": "缺少 command 参数",
                                })
                                continue

                            if _event_loop is None or _event_loop.is_closed():
                                ws.send_json({
                                    "type": "cmd-result",
                                    "id": req_id,
                                    "ok": False,
                                    "message": "事件循环未就绪,请稍后重试",
                                })
                                continue

                            try:
                                from lib.current import Current
                                client = Current.client
                                if client is None:
                                    ws.send_json({
                                        "type": "cmd-result",
                                        "id": req_id,
                                        "ok": False,
                                        "message": "无客户端连接",
                                    })
                                    continue

                                import asyncio
                                fut = asyncio.run_coroutine_threadsafe(
                                    client.runCommand(command), _event_loop
                                )
                                result = fut.result(timeout=15)
                                body_data = result.get("body", {}) if isinstance(result, dict) else {}
                                ws.send_json({
                                    "type": "cmd-result",
                                    "id": req_id,
                                    "ok": True,
                                    "statusCode": body_data.get("statusCode"),
                                    "statusMessage": body_data.get("statusMessage"),
                                })
                                _audit(self, "command", f"执行了命令: {command}")
                            except Exception as e:
                                ws.send_json({
                                    "type": "cmd-result",
                                    "id": req_id,
                                    "ok": False,
                                    "message": f"命令执行失败: {e}",
                                })
            finally:
                _live_log.unsubscribe(_on_log)
                ws.close()
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError, OSError):
            pass


def _check_importable(mod_path: str) -> bool:
    """检测 mod 模块能否导入(轻量检查,不真正实例化)"""
    try:
        import importlib
        p = str(mod_path).replace("\\", "/")
        while p.startswith("../"):
            p = p[3:]
        p = p.replace("/", ".").removesuffix(".js")
        importlib.import_module(p)
        return True
    except Exception:
        return False


# ===== 服务器生命周期 =====

class _FastHTTPServer(ThreadingHTTPServer):
    """跳过 HTTPServer.server_bind 中的 socket.getfqdn() 反向 DNS 查询

    原版 HTTPServer 绑定时会对 host 执行 gethostbyaddr 反向解析,
    当绑定 0.0.0.0 时 Windows 的 DNS 解析器可能阻塞数秒(启动慢的根因)。
    server_name 仅用于日志/SNI(仅 HTTPS 场景需要),HTTP 场景下无影响。
    """

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = socket.gethostname()
        self.server_port = port

    def process_request(self, request, client_address):
        """静默连接中断类错误,避免 Windows 上浏览器快速刷新/断开时打印 traceback"""
        try:
            super().process_request(request, client_address)
        except Exception:
            # ConnectionAbortedError / BrokenPipeError / ConnectionResetError
            # 均为客户端提前断开导致,静默忽略
            pass

    def handle_error(self, request, client_address):
        """静默连接断开类错误,避免 Ctrl+C / SSE 断开时打印 traceback"""
        _, exc, _ = sys.exc_info()
        # 注意:exc 是异常实例,必须用 isinstance 判断(旧代码用 in 比较类,永远为 False)
        if isinstance(exc, (ConnectionAbortedError, BrokenPipeError, ConnectionResetError, OSError)):
            return
        super().handle_error(request, client_address)


class WebUIServer:
    """Web 管理服务器(后台线程运行,不阻塞主程序)"""

    def __init__(self, port: int = 18888):
        self.port = port
        self._server = None
        self._thread = None

    def start(self, local_only: bool = True) -> bool:
        """启动 HTTP 服务器(独立线程);端口占用时自动尝试下一个可用端口"""
        bind_host = "127.0.0.1" if local_only else "0.0.0.0"
        max_tries = 10
        for offset in range(max_tries):
            try:
                self._server = _FastHTTPServer((bind_host, self.port + offset), WebUIHandler)
                self.port = self.port + offset
                break
            except OSError:
                continue
        if self._server is None:
            return False
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    @property
    def address(self) -> str:
        host = "127.0.0.1" if getattr(self._server, "_local_only", True) else "0.0.0.0"
        return f"http://{host}:{self.port}"


# 全局实例(由 main.py 启动/停止)
_instance = None


def start_webui() -> WebUIServer:
    """启动 Web 管理服务器(每次启动时调用)"""
    global _instance
    if _instance is not None:
        return _instance
    ns = _load_config_module()
    webui = ns.get("webuiConfig", {})
    if not webui.get("enabled", True):
        return None
    port = int(webui.get("port") or 18888)
    local_only = webui.get("localOnly", False)
    _instance = WebUIServer(port)
    if not _instance.start(local_only=local_only):
        from lib import shared
        shared.logger.warning(f"Web 管理端口 {port} 不可用,已跳过启动")
        _instance = None
        return None
    from lib import shared
    bind_desc = "仅本机" if local_only else "所有接口"
    shared.logger.info(f"Web 管理界面已启动: http://127.0.0.1:{_instance.port} ({bind_desc})")
    try:
        from lib.sys_metrics import metrics_collector
        metrics_collector.start()
    except Exception:
        pass
    return _instance


def stop_webui() -> None:
    """停止 Web 管理服务器(置空实例,支持热重启后再次启动) """
    global _instance
    try:
        from lib.sys_metrics import metrics_collector
        metrics_collector.stop()
    except Exception:
        pass
    if _instance:
        _instance.stop()
        _instance = None


def restart_webui() -> bool:
    """原地重启 Web 管理服务器(用于 localOnly/port 等需重绑定的设置变更,不重启整个进程)"""
    global _instance
    old_port = _instance.port if _instance else None
    stop_webui()
    ns = _load_config_module()
    webui = ns.get("webuiConfig", {})
    if not webui.get("enabled", True):
        return False
    port = int(webui.get("port") or 18888)
    local_only = webui.get("localOnly", False)
    _instance = WebUIServer(port)
    if not _instance.start(local_only=local_only):
        from lib import shared
        shared.logger.warning(f"Web 管理端口 {port} 不可用,已跳过重启")
        _instance = None
        return False
    from lib import shared
    bind_desc = "仅本机" if local_only else "所有接口"
    shared.logger.info(f"Web 管理界面已重启: http://127.0.0.1:{_instance.port} ({bind_desc})")
    return True
