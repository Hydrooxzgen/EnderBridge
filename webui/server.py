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
- POST /api/auth                 登录校验(令牌正确→admin,错误→密码错误提示)
- GET  /api/status               仪表盘状态(名称/端口/在线客户端/mod 等,无需鉴权)
- GET  /api/release-notes        当前版本 Release Notes(GitHub API,无需鉴权)
- GET  /api/config               读取可管理配置(仅 admin)
- PUT  /api/config               保存可管理配置(写回 config.py,仅 admin)
- GET  /api/permissions          读取权限配置(仅 admin)
- PUT  /api/permissions          保存权限配置(仅 admin)
- GET  /api/mods                 列出 Mod 及加载状态(admin / guest 均可,只读)
- POST /api/mods/reload-all      重载所有服务端 Mod(仅 admin)
- POST /api/restart              一键重启服务器进程(优雅关闭后自动以相同参数重启,仅 admin)

鉴权:config.webuiConfig.token 非空时,登录页询问令牌——
- 令牌正确 → admin(全部权限)
- 令牌错误 → 提示"密码错误",停留在登录页(不会自动进入访客模式)
- 点击「以访客身份浏览」按钮 → guest(仅基础只读功能:仪表盘 / Mod 列表)
- 请求头 X-Auth-Token 携带正确令牌 → admin
- 请求头 X-Auth-Guest: 1 → guest
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBUI_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(WEBUI_DIR, "static")
CONFIG_JSON = os.path.join(ROOT, "config.json")
CONFIG_PY = os.path.join(ROOT, "config.py")
CONFIG_PY_BAK = os.path.join(ROOT, "config.py.bak")
PERMISSION_JSON = os.path.join(ROOT, "permission.json")
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
_description = None  # 非 None 时直接用作 Release Notes,跳过 GitHub API


def set_app_info(github_repo: str, version: str, description=None) -> None:
    """注入应用信息:main.py 启动后调用,提供 GitHub 仓库名与当前版本

    description: 若提供(非 None),则 /api/release-notes 直接返回该内容,
    不再从 GitHub 拉取 Release 数据。"""
    global _github_repo, _app_version, _description
    _github_repo = github_repo
    _app_version = version
    _description = description


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

    # 兼容：如果存在旧的 config.py，提示可删除
    if os.path.exists(CONFIG_PY):
        print("[Config] 配置已保存到 config.json，旧的 config.py 可手动删除")


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

def _webui_token() -> str:
    ns = _load_config_module()
    return str(ns.get("webuiConfig", {}).get("token", "") or "").strip()


def _auth_role(handler) -> str:
    """返回请求身份: "admin"(令牌正确) / "guest"(访客) / ""(未授权)

    token 未设置时直接开放全部权限(本机使用)。
    """
    token = _webui_token()
    if not token:
        return "admin"
    if handler.headers.get("X-Auth-Guest", "") == "1":
        return "guest"
    provided = handler.headers.get("X-Auth-Token", "")
    return "admin" if provided == token else ""


def _require_admin(handler) -> bool:
    """管理操作:仅 admin 可访问;访客返回 403,未授权返回 401"""
    role = _auth_role(handler)
    if role == "admin":
        return True
    if role == "guest":
        handler._respond({"ok": False, "message": "访客模式:无管理权限"}, status=403)
        return False
    handler._respond_denied()
    return False


def _require_any(handler) -> bool:
    """登录即可访问(admin 或 guest);未授权返回 401"""
    if _auth_role(handler) in ("admin", "guest"):
        return True
    handler._respond_denied()
    return False


# ===== HTTP 处理器 =====

class WebUIHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # 静默日志,避免刷屏
        pass

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

    # ---- 静态页面 ----
    def do_GET(self):
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
        if path == "/api/release-notes":
            self._api_release_notes()
            return
        if path == "/api/update/check":
            self._api_update_check()
            return
        if path == "/api/update/releases":
            self._api_update_releases()
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
        if path == "/api/bot/xbox-accounts":
            self._api_bot_xbox_accounts()
            return
        if path == "/api/bot/xbox-login-status":
            self._api_bot_xbox_login_status()
            return
        if path == "/audit":
            self._serve_page("audit.html")
            return
        if path == "/api/audit-logs":
            self._api_audit_logs()
            return
        self.send_response(404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Not Found")

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/config":
            self._api_save_config()
            return
        if parsed.path == "/api/permissions":
            self._api_save_permissions()
            return
        self.send_response(404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/auth":
            self._api_auth()
            return
        if parsed.path == "/api/mods/reload-all":
            self._api_reload_all()
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
        if parsed.path == "/api/console":
            self._api_console()
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
        self.send_response(404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Not Found")

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
        """向 MCBE 客户端发送命令并返回结果(仅 admin)"""
        if not _require_admin(self):
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
        except Exception as e:
            self._respond({"ok": False, "message": f"命令执行失败: {e}"})

    # ---- Xbox Live 多账号登录 ----

    def _api_bot_xbox_accounts(self) -> None:
        """获取已保存的 Xbox Live 账号列表"""
        if not _require_admin(self):
            return
        ns = _load_config_module()
        bot_cfg = ns.get("botConfig") or {}
        accounts = bot_cfg.get("xboxAccounts") or []
        active = bot_cfg.get("activeXboxAccount") or None
        self._respond({"ok": True, "accounts": accounts, "active": active})

    def _api_bot_xbox_login(self) -> None:
        """启动 Xbox Live 登录流程 — Gamertag 从认证响应中自动获取,无需传入用户名"""
        if not _require_admin(self):
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
        if not _require_admin(self):
            return
        try:
            from mod.bot import XboxLoginManager
            login_mgr = XboxLoginManager.get()
            self._respond({"ok": True, **login_mgr.get_status()})
        except Exception as e:
            self._respond({"ok": False, "message": f"查询状态失败: {e}"})

    def _api_bot_xbox_login_stop(self) -> None:
        """取消 Xbox Live 登录流程"""
        if not _require_admin(self):
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
        if not _require_admin(self):
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
        if not _require_admin(self):
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
        """登录校验:令牌正确返回 admin;错误返回失败(不自动进入访客模式)"""
        body = self._read_body()
        token = _webui_token()
        if not token:
            self._respond({"ok": True, "role": "admin"})
            return
        provided = str(body.get("token", "") or "")
        if provided == token:
            self._respond({"ok": True, "role": "admin"})
        else:
            self._respond({"ok": False, "message": "密码错误,请重新输入"})

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
        self._respond({
            "ok": True,
            "name": cfg.get("name", "EnderBridge"),
            "port": cfg.get("port", 8800),
            "webPort": webui.get("port", 18888),
            "webTokenSet": bool(str(webui.get("token", "") or "").strip()),
            "clients": extra.get("clients", 0),
            "uptime": extra.get("uptime", 0),
            "version": _app_version or "EnderBridge",
        })

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
                })
            self._respond({"ok": True, "releases": items, "page": page})
        except urllib.error.HTTPError as e:
            msg = f"GitHub API 错误: {e.code}"
            if e.code == 403:
                msg = "GitHub API 请求过于频繁(403),请稍后再试"
            self._respond({"ok": False, "message": msg})
        except Exception as e:
            self._respond({"ok": False, "message": f"获取 Release 列表失败: {e}"})

    def _api_update_install(self) -> None:
        """从本地 zip 或 GitHub Release 执行更新(仅 admin)"""
        import tempfile
        if not _require_admin(self):
            return
        body = self._read_body()
        github_tag = body.get("github_tag", "").strip()
        file_path = body.get("path", "").strip()

        # GitHub tag 模式:下载 Release asset
        if github_tag:
            if not _github_repo:
                self._respond({"ok": False, "message": "未配置 GitHub 仓库信息"})
                return
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
        self._respond({"ok": True, "message": "服务器正在更新，更新完成后请点击仪表盘"})
        # 等待响应数据发送到浏览器后再触发重启
        import time
        time.sleep(0.5)
        try:
            _restart_handler()
        except Exception:
            pass  # 响应已发送,重启失败时用户可手动重启

    def _api_update_upload(self) -> None:
        """接收前端上传的压缩包文件,保存到临时目录(仅 admin)"""
        import tempfile
        if not _require_admin(self):
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

    def _api_get_config(self) -> None:
        if not _require_admin(self):
            return
        self._respond({"ok": True, "config": load_config()})

    def _api_save_config(self) -> None:
        if not _require_admin(self):
            return
        body = self._read_body()
        if not body or "config" not in body:
            self._respond({"ok": False, "message": "请求数据格式错误"})
            return
        try:
            save_config(body["config"])
        except Exception as e:
            self._respond({"ok": False, "message": f"保存失败: {e}"})
            return
        self._respond({"ok": True, "message": "配置已保存(部分设置需重启服务器生效)"})

    def _api_get_permissions(self) -> None:
        if not _require_admin(self):
            return
        self._respond({"ok": True, "permissions": load_permissions()})

    def _api_save_permissions(self) -> None:
        if not _require_admin(self):
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
        if not _require_any(self):
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
        if not _require_admin(self):
            return
        try:
            import asyncio
            from lib.mods import ServerModManager
            result = asyncio.run(ServerModManager.reload_all())
            self._respond({"ok": True, "result": result})
        except Exception as e:
            self._respond({"ok": False, "message": f"重载失败: {e}"})

    def _api_restart(self) -> None:
        """一键重启:触发主程序后台执行优雅关闭并重启进程(仅 admin)"""
        if not _require_admin(self):
            return
        if _restart_handler is None:
            self._respond({"ok": False, "message": "重启处理器未注册(请通过 main.py 启动服务器)"})
            return
        try:
            _restart_handler()
        except Exception as e:
            self._respond({"ok": False, "message": f"重启触发失败: {e}"})
            return
        # 处理器在后台线程执行,这里先响应,保证浏览器能收到结果
        self._respond({"ok": True, "message": "服务器正在重启,请稍候..."})

    # ---- 审计日志 API ----

    def _api_audit_logs(self) -> None:
        """读取审计日志(admin/guest 均可)"""
        if not _require_any(self):
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
    return _instance


def stop_webui() -> None:
    """停止 Web 管理服务器(置空实例,支持热重启后再次启动) """
    global _instance
    if _instance:
        _instance.stop()
        _instance = None
        _instance = None
