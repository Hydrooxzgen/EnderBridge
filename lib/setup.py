# lib/setup.py - 首次运行图形化配置向导
#
# 当模板 config.example.py 中 is_first_run 为 True 时,main.py 会调用 start_setup_server():
# 1. 启动一个临时 HTTP 服务器(仅监听 127.0.0.1,不对外网开放)
# 2. 用户在浏览器中填写配置表单
# 3. 保存时基于 config.example.py 模板生成 config.py(剔除 isFirstRun 标记,
#    config.py 只存储用户真实配置),并将玩家权限写入 permission.json
#    (旧文件自动备份为 .bak)
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

CONFIG_EXAMPLE = os.path.join(ROOT, "config.example.py")
CONFIG_PY = os.path.join(ROOT, "config.py")
PERMISSION_EXAMPLE = os.path.join(ROOT, "permission.example.json")
PERMISSION_JSON = os.path.join(ROOT, "permission.json")

SETUP_PORT_START = 18888
SETUP_PORT_MAX = 18899
LOG_LEVELS = ["debug", "info", "warning", "error"]


def _json(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def _bool(v) -> str:
    return "True" if v else "False"


def _num(v):
    return int(v)


def make_rule(pattern, build):
    """生成单次替换规则:模式未命中时返回 None,命中则返回替换后的文本"""
    def apply(src, f):
        if isinstance(pattern, str):
            if pattern not in src:
                return None
            return src.replace(pattern, build(f))
        if not pattern.search(src):
            return None
        return pattern.sub(build(f), src, count=1)
    return apply


def _py_dump(value, level: int = 0) -> str:
    """将 dict/list 序列化为 Python 字面量文本(True/False/None 而非 true/false/null)"""
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


def _replace_block_text(src: str, varname: str, text: str):
    """将源码中 `varname = { ... }` 块整体替换为指定文本(括号配对定位)"""
    m = re.search(rf"(?m)^{re.escape(varname)}\s*=\s*\{{", src)
    if not m:
        return src, False
    start = m.start()
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
    return src[:start] + f"{varname} = {text}\n" + src[end:], True


def make_block_rule(varname, build):
    """生成整块替换规则:`varname = { ... }` 整体替换为 build(f) 生成的文本"""
    def apply(src, f):
        new_src, ok = _replace_block_text(src, varname, build(f))
        return new_src if ok else None
    return apply


# 模组注册表:供向导勾选启用(与 config.example.py 的 mods 块对应)
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


def _build_base_path(f) -> str:
    """生成 basePath 块(resolvePath 包裹,与模板风格一致)"""
    lines = ["{"]
    for key, label in (("music", "音乐"), ("mcfunc", "MCFunc"), ("ezmatic", "Ezmatic"), ("image", "图片")):
        val = str(f.get(f"basePath{key.capitalize()}") or "").strip() or f"./resources/{key}"
        lines.append(f'    {json.dumps(key, ensure_ascii=False)}: resolvePath({json.dumps(val, ensure_ascii=False)}),')
    lines.append("}")
    return "\n".join(lines)


def _normalize(f: dict) -> dict:
    """将向导表单数据规范化:高级模组勾选 → 对应的启用开关"""
    f = dict(f)
    advanced = f.get("advancedMods") or []
    f["qqEnabled"] = "QQ" in advanced
    return f


# chat 与 command 的 model 字段按各自后面的 max_tokens 值精确定位(互不影响)
CHAT_MODEL = re.compile(
    r'"model": "deepseek-chat"(?=,\s*\n\s*"thinking": \{\s*"type": "disabled"\s*\},\s*\n\s*"max_tokens": 512)'
)
COMMAND_MODEL = re.compile(
    r'"model": "deepseek-chat"(?=,\s*\n\s*"thinking": \{\s*"type": "disabled"\s*\},\s*\n\s*"max_tokens": 1024)'
)

# 替换规则表:将 config.example.py 源文本中的默认值替换为用户填写值
# 注意:若模板结构发生变更,需同步更新这里的匹配模式
RULES = [
    {"key": "服务器名称", "apply": make_rule('"name": "EnderBridge"', lambda f: f'"name": {_json(f["name"])}')},
    {"key": "WebSocket 端口", "apply": make_rule('"port": 8800', lambda f: f'"port": {_num(f["port"])}')},
    {"key": "命令前缀", "apply": make_rule('commandPrefix = "$"', lambda f: f"commandPrefix = {_json(f['commandPrefix'])}")},
    {"key": "日志等级", "apply": make_rule('logLevel = "info"', lambda f: f"logLevel = {_json(f['logLevel'])}")},
    {"key": "AI API Key", "apply": make_rule('"apiKey": ""', lambda f: f'"apiKey": {_json(f["apiKey"])}')},
    {"key": "AI Base URL", "apply": make_rule('"baseURL": "https://api.deepseek.com"', lambda f: f'"baseURL": {_json(f["baseURL"])}')},
    {"key": "对话模型", "apply": make_rule(CHAT_MODEL, lambda f: f'"model": {_json(f["chatModel"])}')},
    {"key": "指令模型", "apply": make_rule(COMMAND_MODEL, lambda f: f'"model": {_json(f["commandModel"])}')},
    {"key": "AI 对话冷却", "apply": make_rule('"chatCooldown": 5000', lambda f: f'"chatCooldown": {_num(f["aiChatCooldown"])}')},
    {"key": "音乐打击乐", "apply": make_rule('"playPercussion": True', lambda f: f'"playPercussion": {_bool(f["playPercussion"])}')},
    # qq 块的 enabled 后面紧跟 groupId,用它做上下文锚点,避免误匹配其他 enabled
    {"key": "QQ 启用", "apply": make_rule(re.compile(r'"enabled": (True|False)(?=,\s*\n\s*"groupId")'), lambda f: f'"enabled": {_bool(f["qqEnabled"])}')},
    {"key": "QQ 群号", "apply": make_rule('"groupId": 123456789', lambda f: f'"groupId": {_num(f["qqGroupId"])}')},
    {"key": "QQ 主机", "apply": make_rule('"host": "127.0.0.1"', lambda f: f'"host": {_json(f["qqHost"])}')},
    {"key": "QQ 端口", "apply": make_rule('"port": 3001', lambda f: f'"port": {_num(f["qqPort"])}')},
    {"key": "QQ 访问令牌", "apply": make_rule('"accessToken": ""', lambda f: f'"accessToken": {_json(f["qqToken"])}')},
    # SAPI 配置块
    {"key": "SAPI 配置", "apply": make_block_rule("sapiConfig", lambda f: _py_dump({
        "gmsg": f.get("sapiGmsg", "gmsg"),
        "smsg": f.get("sapiSmsg", "smsg"),
    }))},
    # Utils 配置块
    {"key": "Utils 配置", "apply": make_block_rule("utilsConfig", lambda f: _py_dump({
        "tellAllToTell": bool(f.get("utilsTellAllToTell")),
        "enablePolling": bool(f.get("utilsEnablePolling")),
    }))},
    # basePath 资源路径块
    {"key": "资源路径", "apply": make_block_rule("basePath", _build_base_path)},
    # Mods 勾选块
    {"key": "Mods 配置", "apply": make_block_rule("mods", lambda f: _py_dump(_build_mods(f)))},
    # 刷屏数据配置块
    {"key": "刷屏配置", "apply": make_block_rule("spam", lambda f: _py_dump({
        "attack": f.get("spamAttack", ""),
        "ad": split_lines(f.get("spamAd", "")),
        "adInterval": int(f.get("spamAdInterval") or 60000),
    }))},
    # rateLimit 块的 enabled 后面紧跟 windowMs,用它做上下文锚点,避免误匹配其他 enabled
    {"key": "限流启用", "apply": make_rule(re.compile(r'"enabled": (True|False)(?=,\s*\n\s*"windowMs")'), lambda f: f'"enabled": {_bool(f["rateLimitEnabled"])}')},
    {"key": "限流窗口", "apply": make_rule('"windowMs": 1000', lambda f: f'"windowMs": {_num(f["rateLimitWindowMs"])}')},
    {"key": "限流次数", "apply": make_rule('"maxPerWindow": 20', lambda f: f'"maxPerWindow": {_num(f["rateLimitMax"])}')},
    # webuiConfig 块:enabled 后面紧跟 port 18888,用它做上下文锚点,避免误匹配其他 enabled
    {"key": "Web 管理启用", "apply": make_rule(re.compile(r'"enabled": (True|False)(?=,\s*\n\s*"port": 18888)'), lambda f: f'"enabled": {_bool(f["webuiEnabled"])}')},
    {"key": "Web 管理端口", "apply": make_rule('"port": 18888', lambda f: f'"port": {_num(f["webuiPort"])}')},
    {"key": "Web 管理令牌", "apply": make_rule('"token": ""', lambda f: f'"token": {_json(f["webuiToken"])}')},
    {"key": "Web 仅本机", "apply": make_rule(re.compile(r'"localOnly": (True|False)'), lambda f: f'"localOnly": {_bool(f["webuiLocalOnly"])}')},
    # GitHub API Token:匹配模板中的 githubToken 行
    {"key": "GitHub Token", "apply": make_rule('githubToken = ""', lambda f: f'githubToken = {_json(f["githubToken"])}')},
    # botConfig 块
    {"key": "Bot 配置", "apply": make_block_rule("botConfig", lambda f: _py_dump({
        "enabled": bool(f.get("botEnabled", True)),
        "mode": f.get("botMode", "server"),
        "host": f.get("botHost", "127.0.0.1"),
        "port": int(f.get("botPort") or 19132),
        "offline": bool(f.get("botOffline", True)),
        "version": f.get("botVersion") or None,
        "realmId": f.get("botRealmId") or None,
        "realmInvite": f.get("botRealmInvite") or None,
        "username": f.get("botUsername", "FakeBot"),
        "authTitle": f.get("botAuthTitle") or None,
        "profilesFolder": f.get("botProfilesFolder") or None,
    }))},
    # messageConfig 块(协议/通知配置)
    {"key": "消息协议配置", "apply": make_block_rule("messageConfig", lambda f: _py_dump({
        "agreement": {
            "enabled": True,
            "title": "📋 服务器协议",
            "text": "欢迎来到本服务器！\n\n请遵守以下规则：\n1. 尊重其他玩家\n2. 禁止作弊和破坏\n3. 禁止刷屏和骚扰\n\n输入 agree 同意协议后即可游戏。",
        },
    }))},
    # 注意:config.py 不包含 isFirstRun 标记(判定仅存在于模板 config.example.py)
]


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
    """读取表单默认值:优先读取现有 config.py / permission.json,不存在时回退到模板"""
    cfg = {}
    for path in (CONFIG_PY, CONFIG_EXAMPLE):
        if os.path.exists(path):
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location("setup_config_src", path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                cfg = module.__dict__
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
        "githubToken": cfg.get("githubToken", ""),
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
    """将模板 config.example.py 的 is_first_run 标记写为 False(保存成功后调用)"""
    try:
        with open(CONFIG_EXAMPLE, "r", encoding="utf-8") as f:
            tpl = f.read()
        next_ = re.sub(r"is_first_run = (True|False)", "is_first_run = False", tpl, count=1)
        if next_ != tpl:
            with open(CONFIG_EXAMPLE, "w", encoding="utf-8") as f:
                f.write(next_)
    except Exception:
        # 忽略:下次启动仍会进入向导,由用户手动处理
        pass


def save_config(f) -> None:
    """基于模板生成 config.py 并写入 permission.json(均先备份旧文件)"""
    f = _normalize(f)
    try:
        with open(CONFIG_EXAMPLE, "r", encoding="utf-8") as fp:
            src = fp.read()
    except Exception:
        raise RuntimeError("找不到模板文件 config.example.py")

    for rule in RULES:
        next_ = rule["apply"](src, f)
        if next_ is None:
            raise RuntimeError(f"模板匹配失败:{rule['key']}(config.example.py 结构可能已变更)")
        src = next_

    # config.py 只存储用户真实配置:剔除模板中携带的 isFirstRun 标记块
    src = re.sub(
        r"# ===== 首次运行 =====[\s\S]*?is_first_run = (True|False)\r?\n(\r?\n)?",
        "",
        src,
        count=1,
    )

    if os.path.exists(CONFIG_PY):
        os.replace(CONFIG_PY, CONFIG_PY + ".bak")
    with open(CONFIG_PY, "w", encoding="utf-8") as fp:
        fp.write(src)

    # 保存成功后把模板中的 is_first_run 写为 False,下次启动正常进入服务
    clear_first_run_flag()

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
