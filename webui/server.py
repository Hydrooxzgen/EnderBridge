"""Web 管理后端服务

每次启动时随主程序启动,监听配置的 Web 端口,提供:
- 前端页面(index.html + static/ 静态资源)
- REST API:仪表盘状态 / 配置管理 / 权限管理 / Mod 管理

前端资源全部以独立文件存放于 static/ 目录(css/js/图片/字体等),
不依赖 Python 内嵌模板,可自由使用任意前端技术(原生 JS / Vue 等)。

API 一览:
- GET  /                         返回前端页面
- GET  /static/*                 静态资源(css/js/图片/字体,自动识别 MIME)
- POST /api/auth                 登录校验(令牌正确→admin,错误→密码错误提示)
- GET  /api/status               仪表盘状态(名称/端口/在线客户端/mod 等,无需鉴权)
- GET  /api/config               读取可管理配置(仅 admin)
- PUT  /api/config               保存可管理配置(写回 config.py,仅 admin)
- GET  /api/permissions          读取权限配置(仅 admin)
- PUT  /api/permissions          保存权限配置(仅 admin)
- GET  /api/mods                 列出 Mod 及加载状态(admin / guest 均可,只读)
- POST /api/mods/reload-all      重载所有服务端 Mod(仅 admin)

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
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBUI_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(WEBUI_DIR, "static")
CONFIG_PY = os.path.join(ROOT, "config.py")
CONFIG_PY_BAK = os.path.join(ROOT, "config.py.bak")
PERMISSION_JSON = os.path.join(ROOT, "permission.json")

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


def _read_config_src() -> str:
    """读取 config.py 源码文本"""
    with open(CONFIG_PY, "r", encoding="utf-8") as f:
        return f.read()


def _load_config_module() -> dict:
    """以模块方式加载 config.py,返回其命名空间(失败时返回空 dict)"""
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
    """读取可管理配置(供前端表单使用)"""
    ns = _load_config_module()
    cfg = ns.get("wsConfig", {})
    features = ns.get("features", {})
    rate_limit = ns.get("rateLimit", {})
    webui = ns.get("webuiConfig", {})
    ai = ns.get("AIConfig", {})
    ai_models = ai.get("models", {})
    utils = ns.get("utilsConfig", {})
    sapi = ns.get("sapiConfig", {})
    return {
        "name": cfg.get("name", "EnderBridge"),
        "port": cfg.get("port", 8800),
        "commandPrefix": ns.get("commandPrefix", "!"),
        "logLevel": ns.get("logLevel", "info"),
        "features": features,
        "rateLimit": rate_limit,
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
    }


def save_config(new: dict) -> None:
    """将表单配置写回 config.py(块替换,不触碰其他配置;写前备份 .bak)"""
    src = _read_config_src()
    orig = src

    def apply_block(name, value):
        nonlocal src
        src, ok = _replace_block(src, name, value)
        if not ok:
            raise RuntimeError(f"config.py 中未找到 {name} 配置块")

    def apply_block_or_append(name, value, comment=""):
        """块替换;旧版 config.py 缺少该块时自动追加到文件末尾"""
        nonlocal src
        src, ok = _replace_block(src, name, value)
        if ok:
            return
        text = _py_dump(value)
        if not src.endswith("\n"):
            src += "\n"
        src += f"\n{comment}# {name}\n{name} = {text}\n"

    def apply_line(name, value):
        nonlocal src
        src, ok = _replace_line(src, name, value)
        if not ok:
            raise RuntimeError(f"config.py 中未找到 {name} 配置")

    # wsConfig:整体块替换(包含 name / port)
    ws = {
        "name": str(new.get("name") or "").strip() or "EnderBridge",
        "port": int(new.get("port") or 8800),
    }
    apply_block("wsConfig", ws)
    apply_line("commandPrefix", str(new.get("commandPrefix") or "!").strip() or "!")
    apply_line("logLevel", str(new.get("logLevel") or "info").strip())
    apply_block("features", new.get("features") or {})
    apply_block("rateLimit", new.get("rateLimit") or {})

    # AI 对话配置:基于现有结构合并,保留 thinking / stream 等未暴露字段
    ns = _load_config_module()
    ai = dict(ns.get("AIConfig") or {})
    ai.setdefault("options", {})
    ai.setdefault("models", {})
    ai_form = new.get("ai") or {}
    ai["options"]["baseURL"] = str(ai_form.get("baseURL") or "").strip()
    ai["options"]["apiKey"] = str(ai_form.get("apiKey") or "").strip()
    chat = dict(ai["models"].get("chat") or {})
    cmd = dict(ai["models"].get("command") or {})
    chat["model"] = str(ai_form.get("chatModel") or "deepseek-chat").strip()
    chat["max_tokens"] = int(ai_form.get("chatMaxTokens") or 512)
    chat["messages"] = _set_system_prompt(chat.get("messages"), ai_form.get("chatPrompt"))
    cmd["model"] = str(ai_form.get("cmdModel") or "deepseek-chat").strip()
    cmd["max_tokens"] = int(ai_form.get("cmdMaxTokens") or 1024)
    cmd["messages"] = _set_system_prompt(cmd.get("messages"), ai_form.get("cmdPrompt"))
    ai["models"]["chat"] = chat
    ai["models"]["command"] = cmd
    ai["chatCooldown"] = int(ai_form.get("chatCooldown") or 5000)
    apply_block_or_append("AIConfig", ai, "# AI 对话配置")

    # 工具配置
    utils_form = new.get("utils") or {}
    apply_block_or_append("utilsConfig", {
        "tellAllToTell": bool(utils_form.get("tellAllToTell", False)),
        "enablePolling": bool(utils_form.get("enablePolling", True)),
    }, "# 工具配置")

    # 消息通道配置
    sapi_form = new.get("sapi") or {}
    apply_block_or_append("sapiConfig", {
        "gmsg": str(sapi_form.get("gmsg") or "gmsg").strip(),
        "smsg": str(sapi_form.get("smsg") or "smsg").strip(),
    }, "# 消息通道配置")

    # webuiConfig:整体块替换;旧版 config.py 无该块时自动追加到文件末尾
    webui = new.get("webui") or {}
    webui_value = {
        "enabled": bool(webui.get("enabled", True)),
        "port": int(webui.get("port") or 18888),
        "token": str(webui.get("token") or "").strip(),
    }
    apply_block_or_append("webuiConfig", webui_value, "# Web 管理界面配置（每次启动时监听该端口）")

    if src == orig:
        return
    if os.path.exists(CONFIG_PY):
        os.replace(CONFIG_PY, CONFIG_PY_BAK)
    with open(CONFIG_PY, "w", encoding="utf-8") as f:
        f.write(src)


# ===== 权限读写 =====

def load_permissions() -> dict:
    """读取 permission.json(不存在时返回默认结构)"""
    try:
        with open(PERMISSION_JSON, "r", encoding="utf-8") as f:
            perm = json.load(f)
        if not isinstance(perm, dict):
            raise ValueError
        return perm
    except Exception:
        return {"owner": "YourXboxName", "op": [], "user": [], "blocker": []}


def save_permissions(perm: dict) -> None:
    """原子写入 permission.json"""
    tmp = PERMISSION_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(perm, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, PERMISSION_JSON)


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
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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

        if path in ("/", "/index.html"):
            self._serve_index()
            return
        if path.startswith("/static/"):
            self._serve_static(path)
            return
        if path == "/api/status":
            self._api_status()
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
            "version": "EnderBridge",
        })

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

class WebUIServer:
    """Web 管理服务器(后台线程运行,不阻塞主程序)"""

    def __init__(self, port: int = 18888):
        self.port = port
        self._server = None
        self._thread = None

    def start(self) -> bool:
        """启动 HTTP 服务器(独立线程);端口占用时自动尝试下一个可用端口"""
        max_tries = 10
        for offset in range(max_tries):
            try:
                self._server = ThreadingHTTPServer(("127.0.0.1", self.port + offset), WebUIHandler)
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
        return f"http://127.0.0.1:{self.port}"


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
    _instance = WebUIServer(port)
    if not _instance.start():
        from lib import shared
        shared.logger.warning(f"Web 管理端口 {port} 不可用,已跳过启动")
        _instance = None
        return None
    from lib import shared
    shared.logger.info(f"Web 管理界面已启动: http://127.0.0.1:{_instance.port}")
    return _instance


def stop_webui() -> None:
    """停止 Web 管理服务器"""
    global _instance
    if _instance:
        _instance.stop()
        _instance = None
