# lib/setup.py - 首次运行图形化配置向导
#
# 当模板 config.example.json 中 is_first_run 为 True 时,main.py 会调用 start_setup_server():
# 1. 启动一个临时 HTTP 服务器(仅监听 127.0.0.1,不对外网开放)
# 2. 用户在浏览器中填写配置表单
# 3. 保存时基于 config.example.json 模板直接生成 config.json,
#    并将玩家权限写入 permission.json(旧文件自动备份为 .bak)
# 4. 保存成功后关闭临时服务器,由 main.py 自动启动服务器
"""首次运行图形化配置向导"""
import asyncio
import json
import os
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_DIR = os.path.join(ROOT, "config")
CONFIG_PY = os.path.join(CONFIG_DIR, "config.py")
CONFIG_JSON = os.path.join(CONFIG_DIR, "config.json")
CONFIG_EXAMPLE_JSON = os.path.join(CONFIG_DIR, "config.example.json")
PERMISSION_EXAMPLE = os.path.join(CONFIG_DIR, "permission.example.json")
PERMISSION_JSON = os.path.join(CONFIG_DIR, "permission.json")

SETUP_PORT_START = 18888
SETUP_PORT_MAX = 18899
LOG_LEVELS = ["debug", "info", "warning", "error"]


def _json(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def _bool(v) -> str:
    return "True" if v else "False"


def _num(v):
    return int(v)


# 模组注册表:供向导勾选启用(与 config.example.json 的 mods 块对应)
# config: 该模组启用时显示的同名配置区(spam)
# basePath: 该模组启用时显示的资源路径配置项
MOD_REGISTRY = {
    "client": {
        "PermissionCommands": {"path": "mod.permission", "label": "权限命令"},
        "Tool": {"path": "mod.tool", "label": "工具"},
        "Position": {"path": "mod.position", "label": "坐标"},
        "Music": {"path": "mod.music", "label": "音乐", "config": "music", "basePath": "music"},
        "MCFunc": {"path": "mod.mcfunc", "label": "MCFunc", "basePath": "mcfunc"},
        "MoreWS": {"path": "mod.morews", "label": "MoreWS"},
        "Ezmatic": {"path": "mod.ezmatic.main", "label": "Ezmatic 结构", "basePath": "ezmatic"},
        "ImageMod": {"path": "mod.image.main", "label": "图片", "basePath": "image"},
        "Message": {"path": "mod.message", "label": "消息通知 / 协议"},
    },
    "server": {
        "chat": {"path": "mod.read", "label": "聊天 / 终端"},
        "spam": {"path": "mod.spam", "label": "刷屏", "config": "spam"},
    },
}

# 高级模组(同时勾选多个,启用后显示对应配置区)
ADVANCED_MODS = {
    "AI": {"label": "AI 对话（客户端 + 服务端）", "clientPath": "mod.ai", "serverPath": "mod.ai", "config": "ai"},
    "QQ": {"label": "QQ 群互通", "config": "qq"},
    "Bot": {"label": "假人 Bot（Tab 列表玩家）", "clientPath": "mod.bot", "config": "bot"},
}


def _build_mods(f) -> dict:
    """根据勾选的模组生成 mods 字典"""
    mods = {"client": {}, "server": {}}
    for name in f.get("clientMods") or []:
        meta = MOD_REGISTRY["client"].get(name)
        if meta:
            mods["client"][name] = meta["path"]
    # Message 是核心 mod(协议/通知),始终自动注入
    if "Message" not in mods["client"]:
        mods["client"]["Message"] = MOD_REGISTRY["client"]["Message"]["path"]
    for name in f.get("serverMods") or []:
        meta = MOD_REGISTRY["server"].get(name)
        if meta:
            mods["server"][name] = meta["path"]
    for name in f.get("advancedMods") or []:
        meta = ADVANCED_MODS.get(name)
        if meta:
            if meta.get("clientPath"):
                mods["client"][name] = meta["clientPath"]
            if meta.get("serverPath"):
                mods["server"][name] = meta["serverPath"]
    return mods


def _normalize(f: dict) -> dict:
    """将向导表单数据规范化:高级模组勾选 → 对应的启用开关"""
    f = dict(f)
    advanced = f.get("advancedMods") or []
    f["qqEnabled"] = "QQ" in advanced
    return f


def split_list(str_) -> list:
    """将逗号/换行分隔的玩家名文本解析为去重数组"""
    if not isinstance(str_, str):
        return []
    seen = set()
    result = []
    for s in re.split(r"[,，\s]+", str_):
        s = s.strip()
        if s and s not in seen:
            seen.add(s)
            result.append(s)
    return result


def split_lines(str_) -> list:
    """将换行分隔的文本解析为去重数组(广告文本每行一条,保留行内空格)"""
    if not isinstance(str_, str):
        return []
    seen = set()
    result = []
    for s in str_.splitlines():
        s = s.strip()
        if s and s not in seen:
            seen.add(s)
            result.append(s)
    return result


def load_defaults() -> dict:
    """读取表单默认值:优先读取现有 config.json / permission.json,不存在时回退到 JSON 模板"""
    cfg = {}
    for path in (CONFIG_JSON, CONFIG_EXAMPLE_JSON):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                break
            except Exception:
                continue

    perm = {}
    for path in (PERMISSION_JSON, PERMISSION_EXAMPLE):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    perm = json.load(f)
                break
            except Exception:
                continue

    def _get(d, *keys, default=None):
        cur = d
        for k in keys:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(k)
            if cur is None:
                return default
        return cur if cur is not None else default

    mods = cfg.get("mods") or {}
    client_mods = [k for k in (mods.get("client") or {}).keys() if k in MOD_REGISTRY["client"]]
    server_mods = [k for k in (mods.get("server") or {}).keys() if k in MOD_REGISTRY["server"]]
    advanced_mods = []
    if "AI" in (mods.get("client") or {}):
        advanced_mods.append("AI")
    if _get(cfg, "features", "qq", "enabled", default=False):
        advanced_mods.append("QQ")
    if "Bot" in (mods.get("client") or {}):
        advanced_mods.append("Bot")

    return {
        "name": _get(cfg, "wsConfig", "name", default="EnderBridge"),
        "port": _get(cfg, "wsConfig", "port", default=8800),
        "commandPrefix": cfg.get("commandPrefix", "$"),
        "logLevel": cfg.get("logLevel", "info"),
        "apiKey": _get(cfg, "AIConfig", "options", "apiKey", default=""),
        "baseURL": _get(cfg, "AIConfig", "options", "baseURL", default="https://api.deepseek.com"),
        "chatModel": _get(cfg, "AIConfig", "models", "chat", "model", default="deepseek-chat"),
        "commandModel": _get(cfg, "AIConfig", "models", "command", "model", default="deepseek-chat"),
        "aiChatCooldown": _get(cfg, "AIConfig", "chatCooldown", default=5000),
        "playPercussion": _get(cfg, "features", "music", "playPercussion", default=True),
        "qqEnabled": _get(cfg, "features", "qq", "enabled", default=False),
        "qqGroupId": _get(cfg, "features", "qq", "groupId", default=123456789),
        "qqHost": _get(cfg, "features", "qq", "host", default="127.0.0.1"),
        "qqPort": _get(cfg, "features", "qq", "port", default=3001),
        "qqToken": _get(cfg, "features", "qq", "accessToken", default=""),
        "sapiGmsg": _get(cfg, "sapiConfig", "gmsg", default="gmsg"),
        "sapiSmsg": _get(cfg, "sapiConfig", "smsg", default="smsg"),
        "utilsTellAllToTell": _get(cfg, "utilsConfig", "tellAllToTell", default=False),
        "utilsEnablePolling": _get(cfg, "utilsConfig", "enablePolling", default=True),
        "basePathMusic": _get(cfg, "basePath", "music", default="./resources/midi"),
        "basePathMcfunc": _get(cfg, "basePath", "mcfunc", default="./resources/mcfunc"),
        "basePathEzmatic": _get(cfg, "basePath", "ezmatic", default="./resources/ezmatic"),
        "basePathImage": _get(cfg, "basePath", "image", default="./resources/pictures"),
        "spamAttack": _get(cfg, "spam", "attack", default=""),
        "spamAd": "\n".join(_get(cfg, "spam", "ad", default=[]) or []),
        "spamAdInterval": _get(cfg, "spam", "adInterval", default=60000),
        "rateLimitEnabled": _get(cfg, "rateLimit", "command", "enabled", default=False),
        "rateLimitWindowMs": _get(cfg, "rateLimit", "command", "windowMs", default=1000),
        "rateLimitMax": _get(cfg, "rateLimit", "command", "maxPerWindow", default=20),
        "webuiEnabled": _get(cfg, "webuiConfig", "enabled", default=True),
        "webuiPort": _get(cfg, "webuiConfig", "port", default=18888),
        "webuiToken": _get(cfg, "webuiConfig", "token", default=""),
        "webuiLocalOnly": _get(cfg, "webuiConfig", "localOnly", default=False),
        "botEnabled": _get(cfg, "botConfig", "enabled", default=True),
        "botMode": _get(cfg, "botConfig", "mode", default="server"),
        "botHost": _get(cfg, "botConfig", "host", default="127.0.0.1"),
        "botPort": _get(cfg, "botConfig", "port", default=19132),
        "botUsername": _get(cfg, "botConfig", "username", default="FakeBot"),
        "botOffline": _get(cfg, "botConfig", "offline", default=True),
        "botVersion": _get(cfg, "botConfig", "version", default=""),
        "botAuthTitle": _get(cfg, "botConfig", "authTitle", default=""),
        "botProfilesFolder": _get(cfg, "botConfig", "profilesFolder", default=""),
        "botRealmId": _get(cfg, "botConfig", "realmId", default=""),
        "botRealmInvite": _get(cfg, "botConfig", "realmInvite", default=""),
        "clientMods": client_mods,
        "serverMods": server_mods,
        "advancedMods": advanced_mods,
        "owner": perm.get("owner", "YourXboxName"),
        "op": perm.get("op") if isinstance(perm.get("op"), list) else [],
        "user": perm.get("user") if isinstance(perm.get("user"), list) else [],
        "blocker": perm.get("blocker") if isinstance(perm.get("blocker"), list) else [],
    }


def validate(f):
    """校验表单数据,返回错误信息或 None"""
    if not f or not str(f.get("name") or "").strip():
        return "服务器名称不能为空"
    try:
        port = int(f.get("port"))
    except (TypeError, ValueError):
        return "WebSocket 端口必须是 1-65535 的整数"
    if port < 1 or port > 65535:
        return "WebSocket 端口必须是 1-65535 的整数"
    if f.get("logLevel") not in LOG_LEVELS:
        return "日志等级无效"
    if f.get("rateLimitEnabled"):
        try:
            window_ms = int(f.get("rateLimitWindowMs"))
            max_per = int(f.get("rateLimitMax"))
        except (TypeError, ValueError):
            return "限流时间窗口与次数必须是整数"
        if window_ms <= 0 or max_per <= 0:
            return "限流时间窗口与次数必须大于 0"
    try:
        web_port = int(f.get("webuiPort"))
    except (TypeError, ValueError):
        return "Web 管理端口必须是 1-65535 的整数"
    if web_port < 1 or web_port > 65535:
        return "Web 管理端口必须是 1-65535 的整数"
    try:
        ad_interval = int(f.get("spamAdInterval") or 0)
    except (TypeError, ValueError):
        return "广告推送间隔必须是整数(毫秒)"
    if ad_interval < 0:
        return "广告推送间隔不能为负数"
    return None


def clear_first_run_flag() -> None:
    """将所有配置模板的 is_first_run 标记写为 False(保存成功后调用)"""
    # 1. 清除 config.example.json 中的标记
    try:
        if os.path.exists(CONFIG_EXAMPLE_JSON):
            with open(CONFIG_EXAMPLE_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("is_first_run", False):
                data["is_first_run"] = False
                with open(CONFIG_EXAMPLE_JSON, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    # 2. 清除 config.json 中的标记(运行时配置)
    try:
        if os.path.exists(CONFIG_JSON):
            with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("is_first_run", False):
                data["is_first_run"] = False
                with open(CONFIG_JSON, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def save_config(f) -> None:
    """基于 JSON 模板直接生成 config.json 并写入 permission.json(均先备份旧文件)"""
    f = _normalize(f)

    # 从 JSON 模板开始,逐层覆盖表单值
    tpl_path = os.path.join(CONFIG_DIR, "config.example.json")
    try:
        with open(tpl_path, "r", encoding="utf-8") as fp:
            cfg = json.load(fp)
    except Exception:
        raise RuntimeError("找不到模板文件 config.example.json")

    # 移除模板内部字段
    for k in ("_comment", "_version", "_migration_note"):
        cfg.pop(k, None)

    # --- 基础配置 ---
    cfg["is_first_run"] = False
    cfg.setdefault("wsConfig", {})
    cfg["wsConfig"]["name"] = str(f.get("name") or "EnderBridge")
    cfg["wsConfig"]["port"] = int(f.get("port") or 8800)
    cfg["commandPrefix"] = str(f.get("commandPrefix") or "$")
    cfg["logLevel"] = str(f.get("logLevel") or "info")

    # --- AI 配置 ---
    cfg.setdefault("AIConfig", {})
    cfg["AIConfig"].setdefault("options", {})
    cfg["AIConfig"]["options"]["apiKey"] = str(f.get("apiKey") or "")
    cfg["AIConfig"]["options"]["baseURL"] = str(f.get("baseURL") or "https://api.deepseek.com")
    cfg["AIConfig"].setdefault("models", {})
    cfg["AIConfig"]["models"].setdefault("chat", {})
    cfg["AIConfig"]["models"]["chat"]["model"] = str(f.get("chatModel") or "deepseek-chat")
    cfg["AIConfig"]["models"].setdefault("command", {})
    cfg["AIConfig"]["models"]["command"]["model"] = str(f.get("commandModel") or "deepseek-chat")

    # --- 功能配置 ---
    cfg.setdefault("features", {})
    cfg["features"].setdefault("music", {})
    cfg["features"]["music"]["playPercussion"] = bool(f.get("playPercussion", True))

    # QQ
    cfg["features"].setdefault("qq", {})
    cfg["features"]["qq"]["enabled"] = bool(f.get("qqEnabled"))
    cfg["features"]["qq"]["groupId"] = int(f.get("qqGroupId") or 123456789)
    cfg["features"]["qq"]["host"] = str(f.get("qqHost") or "127.0.0.1")
    cfg["features"]["qq"]["port"] = int(f.get("qqPort") or 3001)
    cfg["features"]["qq"]["accessToken"] = str(f.get("qqToken") or "")

    # --- SAPI ---
    cfg.setdefault("sapiConfig", {})
    cfg["sapiConfig"]["gmsg"] = str(f.get("sapiGmsg") or "gmsg")
    cfg["sapiConfig"]["smsg"] = str(f.get("sapiSmsg") or "smsg")

    # --- Utils ---
    cfg.setdefault("utilsConfig", {})
    cfg["utilsConfig"]["tellAllToTell"] = bool(f.get("utilsTellAllToTell"))
    cfg["utilsConfig"]["enablePolling"] = bool(f.get("utilsEnablePolling"))

    # --- 资源路径 ---
    cfg.setdefault("basePath", {})
    cfg["basePath"]["music"] = str(f.get("basePathMusic") or "./resources/midi")
    cfg["basePath"]["mcfunc"] = str(f.get("basePathMcfunc") or "./resources/mcfunc")
    cfg["basePath"]["ezmatic"] = str(f.get("basePathEzmatic") or "./resources/ezmatic")
    cfg["basePath"]["image"] = str(f.get("basePathImage") or "./resources/pictures")

    # --- Mods ---
    cfg["mods"] = _build_mods(f)

    # --- 刷屏 ---
    cfg["spam"] = {
        "attack": str(f.get("spamAttack") or ""),
        "ad": split_lines(f.get("spamAd") or ""),
        "adInterval": int(f.get("spamAdInterval") or 60000),
    }

    # --- 限流 ---
    cfg["rateLimit"] = {
        "command": {
            "enabled": bool(f.get("rateLimitEnabled")),
            "windowMs": int(f.get("rateLimitWindowMs") or 1000),
            "maxPerWindow": int(f.get("rateLimitMax") or 20),
        }
    }

    # --- Web 管理 ---
    cfg.setdefault("webuiConfig", {})
    cfg["webuiConfig"]["enabled"] = bool(f.get("webuiEnabled", True))
    cfg["webuiConfig"]["port"] = int(f.get("webuiPort") or 18888)
    cfg["webuiConfig"]["token"] = str(f.get("webuiToken") or "")
    cfg["webuiConfig"]["localOnly"] = bool(f.get("webuiLocalOnly"))

    # --- Bot ---
    cfg.setdefault("botConfig", {})
    cfg["botConfig"]["enabled"] = bool(f.get("botEnabled", True))
    cfg["botConfig"]["mode"] = str(f.get("botMode") or "server")
    cfg["botConfig"]["host"] = str(f.get("botHost") or "127.0.0.1")
    cfg["botConfig"]["port"] = int(f.get("botPort") or 19132)
    cfg["botConfig"]["offline"] = bool(f.get("botOffline", True))
    cfg["botConfig"]["version"] = f.get("botVersion") or None
    cfg["botConfig"]["realmId"] = f.get("botRealmId") or None
    cfg["botConfig"]["realmInvite"] = f.get("botRealmInvite") or None
    cfg["botConfig"]["username"] = str(f.get("botUsername") or "FakeBot")
    cfg["botConfig"]["authTitle"] = f.get("botAuthTitle") or None
    cfg["botConfig"]["profilesFolder"] = f.get("botProfilesFolder") or None

    # 添加版本标记
    try:
        from lib.config_loader import CURRENT_VERSION
        cfg["_version"] = CURRENT_VERSION
    except ImportError:
        cfg["_version"] = "b0.3.6"

    # 写入 config.json
    if os.path.exists(CONFIG_JSON):
        os.replace(CONFIG_JSON, CONFIG_JSON + ".bak")
    with open(CONFIG_JSON, "w", encoding="utf-8") as fp:
        json.dump(cfg, fp, ensure_ascii=False, indent=2)
        fp.write("\n")

    # 保存成功后把模板中的 is_first_run 写为 False,下次启动正常进入服务
    clear_first_run_flag()

    # 写入 permission.json
    if os.path.exists(PERMISSION_JSON):
        os.replace(PERMISSION_JSON, PERMISSION_JSON + ".bak")
    perm = {
        "owner": str(f.get("owner") or "").strip() or "YourXboxName",
        "op": split_list(f.get("op", "")),
        "user": split_list(f.get("user", "")),
        "blocker": split_list(f.get("blocker", "")),
    }
    with open(PERMISSION_JSON, "w", encoding="utf-8") as fp:
        json.dump(perm, fp, ensure_ascii=False, indent=2)
        fp.write("\n")


SETUP_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "setup.html")


def _load_html() -> str:
    """从 setup.html 文件加载页面模板"""
    with open(SETUP_HTML, "r", encoding="utf-8") as f:
        return f.read()


# 兼容占位:部分旧代码可能直接引用 PAGE_HTML
PAGE_HTML = ""  # 占位,实际内容从 setup.html 加载


def _make_handler(html: str, save_fn, shutdown_fn):
    """创建 HTTP 请求处理器类"""

    class SetupHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # 静默日志
            pass

        def _respond(self, obj) -> None:
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Not Found")

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/api/save":
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Not Found")
                return

            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                form = json.loads(body)
            except Exception:
                self._respond({"ok": False, "message": "请求数据格式错误"})
                return

            err = validate(form)
            if err:
                self._respond({"ok": False, "message": err})
                return

            try:
                save_fn(form)
            except Exception as e:
                self._respond({"ok": False, "message": str(e)})
                return

            self._respond({"ok": True, "message": "✅ 配置已保存！\n服务器即将自动启动，请稍候..."})
            # 延迟关闭,确保响应已发送
            threading.Timer(0.3, shutdown_fn).start()

    return SetupHandler


async def start_setup_server(preferred_port: int = SETUP_PORT_START) -> None:
    """启动图形化配置向导(阻塞直到配置保存完成)

    Args:
        preferred_port: 首选端口,被占用时自动递增
    """
    defaults = load_defaults()
    # 转义 < 防止用户输入(如 API Key)破坏 HTML 结构
    html = _load_html().replace("__DEFAULTS__", json.dumps(defaults, ensure_ascii=False).replace("<", "\\u003c"))

    # 依次尝试监听端口,直到成功或超出范围
    server = None
    for port in range(preferred_port, SETUP_PORT_MAX + 1):
        try:
            # 闭包捕获 server 变量:请求处理时(保存成功后)取其最新值关闭服务器
            handler = _make_handler(html, save_config, lambda: server and server.shutdown())
            server = ThreadingHTTPServer(("127.0.0.1", port), handler)
            break
        except OSError as e:
            # 端口占用(Windows: 10048, Unix: 98)
            if e.errno in (98, 10048, 10013):
                continue
            raise
        except Exception:
            raise

    if server is None:
        raise RuntimeError(f"端口 {preferred_port}-{SETUP_PORT_MAX} 均被占用，无法启动配置向导")

    print("")
    print("========================================")
    print("  EnderBridge 配置向导已启动")
    print(f"  请在浏览器打开: http://127.0.0.1:{server.server_address[1]}")
    print("  配置保存后服务器将自动启动")
    print("========================================")
    print("")

    # 阻塞,直到保存成功触发 shutdown()
    await asyncio.to_thread(server.serve_forever)
    server.server_close()
