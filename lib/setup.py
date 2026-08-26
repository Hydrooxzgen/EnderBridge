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
        "host": f.get("botHost", "127.0.0.1"),
        "port": int(f.get("botPort") or 19132),
        "username": f.get("botUsername", "FakeBot"),
        "offline": bool(f.get("botOffline", True)),
        "version": f.get("botVersion") or None,
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
        "botHost": _get(cfg, "botConfig", "host", default="127.0.0.1"),
        "botPort": _get(cfg, "botConfig", "port", default=19132),
        "botUsername": _get(cfg, "botConfig", "username", default="FakeBot"),
        "botOffline": _get(cfg, "botConfig", "offline", default=True),
        "botVersion": _get(cfg, "botConfig", "version", default=""),
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


PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EnderBridge 配置向导</title>
<style>
:root {
  --text: #e2e8f0;
  --text-dim: #94a3b8;
  --text-faint: #64748b;
  --accent: #818cf8;
  --card: rgba(30, 41, 59, 0.55);
  --card-border: rgba(148, 163, 184, 0.14);
  --input-bg: rgba(15, 23, 42, 0.65);
  --input-border: rgba(148, 163, 184, 0.22);
  --radius: 16px;
  --shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  min-height: 100vh;
  color: var(--text);
  line-height: 1.6;
  padding: 40px 20px 60px;
  background:
    radial-gradient(900px 600px at 15% -10%, rgba(99, 102, 241, 0.25), transparent 60%),
    radial-gradient(800px 500px at 105% 5%, rgba(168, 85, 247, 0.18), transparent 55%),
    radial-gradient(700px 600px at 50% 120%, rgba(56, 189, 248, 0.12), transparent 60%),
    linear-gradient(160deg, #0b1120 0%, #111827 100%);
  background-attachment: fixed;
}
.container { max-width: 760px; margin: 0 auto; }

/* 头部 */
.header { text-align: center; margin-bottom: 32px; }
.logo {
  width: 66px; height: 66px;
  margin: 0 auto 14px;
  border-radius: 18px;
  display: flex; align-items: center; justify-content: center;
  font-size: 32px;
  background: linear-gradient(135deg, #6366f1, #a855f7);
  box-shadow: 0 8px 24px rgba(99, 102, 241, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.25);
}
h1 {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: 0.5px;
  background: linear-gradient(90deg, #a5b4fc, #f0abfc, #7dd3fc);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.sub { color: var(--text-dim); font-size: 14px; margin-top: 6px; }
.badge {
  display: inline-block;
  margin-top: 14px;
  padding: 4px 14px;
  font-size: 12px;
  border-radius: 999px;
  color: #c7d2fe;
  background: rgba(99, 102, 241, 0.15);
  border: 1px solid rgba(99, 102, 241, 0.35);
  letter-spacing: 1px;
}

/* 卡片 */
.card {
  background: var(--card);
  border: 1px solid var(--card-border);
  border-radius: var(--radius);
  padding: 22px 24px;
  margin-bottom: 18px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  transition: transform 0.2s ease, border-color 0.2s ease;
}
.card:hover { transform: translateY(-2px); border-color: rgba(148, 163, 184, 0.28); }
.card h2 {
  display: flex; align-items: center; gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: #c7d2fe;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
  letter-spacing: 0.3px;
}
.card h2 .icon { font-size: 17px; }

label { display: block; font-size: 13px; color: var(--text-dim); margin: 12px 0 5px; font-weight: 500; }
input[type=text], input[type=number], input[type=password], select, textarea {
  width: 100%;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--input-border);
  background: var(--input-bg);
  color: var(--text);
  font-size: 14px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
input:focus, select:focus, textarea:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(129, 140, 248, 0.2);
}
input::placeholder, textarea::placeholder { color: var(--text-faint); }
textarea { min-height: 52px; resize: vertical; font-family: Consolas, monospace; font-size: 13px; }
select {
  cursor: pointer;
  appearance: none;
  -webkit-appearance: none;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%2394a3b8' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>");
  background-repeat: no-repeat;
  background-position: right 12px center;
  padding-right: 34px;
}
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }

/* 开关 */
.switch-row { margin: 12px 0; }
.switch { display: flex; align-items: center; gap: 12px; cursor: pointer; user-select: none; }
.switch input { position: absolute; opacity: 0; width: 0; height: 0; }
.track {
  flex-shrink: 0;
  width: 42px; height: 24px;
  border-radius: 999px;
  background: rgba(100, 116, 139, 0.45);
  border: 1px solid rgba(148, 163, 184, 0.2);
  position: relative;
  transition: background 0.25s ease, border-color 0.25s ease;
}
.track::after {
  content: "";
  position: absolute; top: 2px; left: 2px;
  width: 18px; height: 18px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.35);
  transition: transform 0.25s ease;
}
.switch input:checked + .track {
  background: linear-gradient(90deg, #6366f1, #8b5cf6);
  border-color: transparent;
}
.switch input:checked + .track::after { transform: translateX(18px); }
.switch-label { font-size: 14px; color: var(--text); }

/* 子设置块 */
.sub-box {
  margin-top: 14px;
  padding: 14px 16px;
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.45);
  border: 1px dashed rgba(148, 163, 184, 0.18);
}
.sub-box .hint { margin-top: 10px; }
.hint { font-size: 12px; color: var(--text-faint); margin-top: 4px; line-height: 1.5; }

/* 模组勾选列表 */
.mod-list {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 16px;
  margin-top: 6px;
}
.mod-check {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.45);
  border: 1px solid var(--input-border);
  cursor: pointer;
  user-select: none;
  transition: border-color 0.2s ease, background 0.2s ease;
}
.mod-check:hover { border-color: rgba(129, 140, 248, 0.5); }
.mod-check input { width: 16px; height: 16px; accent-color: #818cf8; cursor: pointer; flex-shrink: 0; }
.mod-check .name { font-size: 14px; color: var(--text); }
.mod-check .tag {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-faint);
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 6px;
  padding: 1px 8px;
  white-space: nowrap;
}
.mod-check:has(input:checked) {
  border-color: rgba(99, 102, 241, 0.55);
  background: rgba(99, 102, 241, 0.1);
}

/* 条件显示区块 */
section.conditional { display: block; }
section.hidden { display: none; }

/* 折叠高级配置 */
details.advanced {
  border-radius: 12px;
}
details.advanced summary {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: #c7d2fe;
  cursor: pointer;
  user-select: none;
  list-style: none;
  padding-bottom: 4px;
}
details.advanced summary::-webkit-details-marker { display: none; }
details.advanced summary::after {
  content: "▾";
  margin-left: auto;
  font-size: 14px;
  color: var(--text-faint);
  transition: transform 0.2s ease;
}
details.advanced[open] summary::after { transform: rotate(180deg); }

/* 资源路径行(默认隐藏,勾选对应模组后显示) */
.bp-row { display: none; }

/* 保存按钮 */
.btn-wrap { margin-top: 8px; }
button[type=submit] {
  width: 100%;
  padding: 14px;
  font-size: 16px;
  font-weight: 700;
  color: #fff;
  border: none;
  border-radius: 12px;
  cursor: pointer;
  letter-spacing: 2px;
  background: linear-gradient(90deg, #6366f1, #8b5cf6, #a855f7);
  background-size: 200% 100%;
  box-shadow: 0 8px 24px rgba(124, 58, 237, 0.35);
  transition: background-position 0.4s ease, transform 0.15s ease, box-shadow 0.2s ease;
}
button[type=submit]:hover { background-position: 100% 0; transform: translateY(-1px); box-shadow: 0 12px 28px rgba(124, 58, 237, 0.45); }
button[type=submit]:active { transform: translateY(0); }
button[type=submit]:disabled { opacity: 0.7; cursor: wait; transform: none; }

/* 结果提示 */
#result {
  margin-top: 16px;
  padding: 13px 16px;
  border-radius: 12px;
  font-size: 14px;
  display: none;
  white-space: pre-line;
  animation: fadeIn 0.3s ease;
}
#result.ok { background: rgba(5, 150, 105, 0.15); color: #6ee7b7; border: 1px solid rgba(16, 185, 129, 0.4); }
#result.err { background: rgba(225, 29, 72, 0.15); color: #fda4af; border: 1px solid rgba(244, 63, 94, 0.4); }
@keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }

/* 底部 */
.footer { text-align: center; color: var(--text-faint); font-size: 12px; margin-top: 28px; letter-spacing: 1px; }

@media (max-width: 560px) {
  .grid { grid-template-columns: 1fr; }
  body { padding: 24px 14px 40px; }
}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="logo">⛏️</div>
    <h1>EnderBridge 配置向导</h1>
    <p class="sub">填写下方配置，点击「保存配置」生成 config.py 与 permission.json</p>
    <span class="badge">◆ 在线配置向导</span>
  </div>

  <form id="cfg">
    <section class="card">
      <h2><span class="icon">⚙️</span>基础设置</h2>
      <div class="grid">
        <div><label for="name">服务器名称</label><input id="name" name="name" type="text" placeholder="EnderBridge"></div>
        <div><label for="port">WebSocket 端口</label><input id="port" name="port" type="number" min="1" max="65535"></div>
      </div>
      <div class="grid">
        <div><label for="commandPrefix">命令前缀</label><input id="commandPrefix" name="commandPrefix" type="text" maxlength="4" placeholder="$"></div>
        <div><label for="logLevel">日志等级</label>
          <select id="logLevel" name="logLevel">
            <option value="debug">debug</option>
            <option value="info">info</option>
            <option value="warning">warning</option>
            <option value="error">error</option>
          </select>
        </div>
      </div>
    </section>

    <section class="card">
      <h2><span class="icon">�</span>基础模组</h2>
      <p class="hint">勾选要启用的模组；部分模组启用后会出现对应配置区。</p>
      <label>客户端模组</label>
      <div id="clientMods" class="mod-list"></div>
      <label>服务端模组</label>
      <div id="serverMods" class="mod-list"></div>
    </section>

    <section class="card">
      <h2><span class="icon">🚀</span>高级模组</h2>
      <p class="hint">勾选后启用并显示对应配置区。</p>
      <div id="advancedMods" class="mod-list"></div>
    </section>

    <section class="card" id="aiFields">
      <h2><span class="icon">🤖</span>AI 设置</h2>
      <label for="apiKey">API Key</label>
      <input id="apiKey" name="apiKey" type="password" placeholder="sk-..." autocomplete="off">
      <label for="baseURL">Base URL</label>
      <input id="baseURL" name="baseURL" type="text">
      <div class="grid">
        <div><label for="chatModel">对话模型</label><input id="chatModel" name="chatModel" type="text"></div>
        <div><label for="commandModel">指令模型</label><input id="commandModel" name="commandModel" type="text"></div>
      </div>
      <label for="aiChatCooldown">对话冷却（毫秒）</label>
      <input id="aiChatCooldown" name="aiChatCooldown" type="number" min="0">
      <p class="hint">API Key 留空表示不启用 AI 功能。</p>
    </section>

    <section class="card" id="musicFields">
      <h2><span class="icon">🎵</span>音乐设置</h2>
      <div class="switch-row">
        <label class="switch">
          <input id="playPercussion" name="playPercussion" type="checkbox">
          <span class="track"></span>
          <span class="switch-label">播放打击乐</span>
        </label>
      </div>
    </section>

    <section class="card" id="qqFields">
      <h2><span class="icon">💬</span>QQ 群互通设置</h2>
      <div class="grid">
        <div><label for="qqGroupId">QQ 群号</label><input id="qqGroupId" name="qqGroupId" type="number"></div>
        <div><label for="qqPort">桥接端口</label><input id="qqPort" name="qqPort" type="number" min="1" max="65535"></div>
      </div>
      <div class="grid">
        <div><label for="qqHost">桥接主机</label><input id="qqHost" name="qqHost" type="text"></div>
        <div><label for="qqToken">访问令牌</label><input id="qqToken" name="qqToken" type="password" autocomplete="off"></div>
      </div>
    </section>

    <section class="card" id="botFields">
      <h2><span class="icon">🤖</span>假人 Bot 设置</h2>
      <p class="hint">假人以独立玩家身份连接 MCBE 服务器，出现在 Tab 列表和游戏世界中。需要 Node.js 运行时。</p>
      <div class="grid">
        <div><label for="botHost">服务器地址</label><input id="botHost" name="botHost" type="text" placeholder="127.0.0.1"></div>
        <div><label for="botPort">服务器端口</label><input id="botPort" name="botPort" type="number" min="1" max="65535" placeholder="19132"></div>
      </div>
      <div class="grid">
        <div><label for="botUsername">假人名称</label><input id="botUsername" name="botUsername" type="text" placeholder="FakeBot"></div>
        <div>
          <label>离线模式（无需 Xbox Live）</label>
          <div class="switch-row">
            <label class="switch">
              <input id="botOffline" name="botOffline" type="checkbox" checked>
              <span class="track"></span>
              <span class="switch-label">offline</span>
            </label>
          </div>
        </div>
      </div>
      <label for="botVersion">协议版本（留空自动检测）</label>
      <input id="botVersion" name="botVersion" type="text" placeholder="留空则自动检测">
    </section>

    <section class="card" id="spamFields">
      <h2><span class="icon">📢</span>刷屏设置</h2>
      <label for="spamAttack">攻击文本</label>
      <textarea id="spamAttack" name="spamAttack" placeholder="§c[示例] 刷屏文本"></textarea>
      <label for="spamAd">广告文本（每行一条）</label>
      <textarea id="spamAd" name="spamAd" placeholder="§u示例广告 1 §7| §bexample.com"></textarea>
      <div class="grid">
        <div><label for="spamAdInterval">广告推送间隔（毫秒）</label><input id="spamAdInterval" name="spamAdInterval" type="number" min="0"></div>
      </div>
      <p class="hint">用于 $spam 模组的 attack / ad 命令。</p>
    </section>

    <section class="card">
      <h2><span class="icon">👥</span>玩家权限</h2>
      <label for="owner">服主（拥有全部权限）</label>
      <input id="owner" name="owner" type="text" placeholder="YourXboxName">
      <label for="op">管理员（逗号分隔多个玩家名）</label>
      <textarea id="op" name="op" placeholder="PlayerA, PlayerB"></textarea>
      <label for="user">普通用户</label>
      <textarea id="user" name="user"></textarea>
      <label for="blocker">屏蔽名单</label>
      <textarea id="blocker" name="blocker"></textarea>
      <p class="hint">权限数据将保存到 permission.json。</p>
    </section>

    <section class="card" id="basePathFields">
      <h2><span class="icon">📁</span>资源路径</h2>
      <p class="hint">勾选对应模组后显示该模组的资源路径。</p>
      <div class="grid">
        <div data-basepath="music" class="bp-row"><label for="basePathMusic">音乐（midi）路径</label><input id="basePathMusic" name="basePathMusic" type="text"></div>
        <div data-basepath="mcfunc" class="bp-row"><label for="basePathMcfunc">MCFunc 路径</label><input id="basePathMcfunc" name="basePathMcfunc" type="text"></div>
      </div>
      <div class="grid">
        <div data-basepath="ezmatic" class="bp-row"><label for="basePathEzmatic">Ezmatic 路径</label><input id="basePathEzmatic" name="basePathEzmatic" type="text"></div>
        <div data-basepath="image" class="bp-row"><label for="basePathImage">图片路径</label><input id="basePathImage" name="basePathImage" type="text"></div>
      </div>
    </section>

    <section class="card">
      <details class="advanced">
        <summary><span class="icon">⚡</span>高级配置</summary>
        <div class="sub-box">
          <div class="switch-row">
            <label class="switch">
              <input id="rateLimitEnabled" name="rateLimitEnabled" type="checkbox">
              <span class="track"></span>
              <span class="switch-label">启用命令限流</span>
            </label>
          </div>
          <div id="rateLimitFields" class="sub-box">
            <div class="grid">
              <div><label for="rateLimitWindowMs">时间窗口 (毫秒)</label><input id="rateLimitWindowMs" name="rateLimitWindowMs" type="number" min="1"></div>
              <div><label for="rateLimitMax">窗口内最大命令数</label><input id="rateLimitMax" name="rateLimitMax" type="number" min="1"></div>
            </div>
            <p class="hint">例如：窗口 1000ms、最大 20 次，表示每个玩家每秒最多执行 20 条命令。</p>
          </div>
          <div class="switch-row">
            <label class="switch">
              <input id="webuiEnabled" name="webuiEnabled" type="checkbox">
              <span class="track"></span>
              <span class="switch-label">启用 Web 管理界面</span>
            </label>
          </div>
          <div id="webuiFields" class="sub-box">
            <div class="grid">
              <div><label for="webuiPort">Web 管理端口</label><input id="webuiPort" name="webuiPort" type="number" min="1" max="65535"></div>
              <div><label for="webuiToken">管理令牌（留空 = 仅本机访问）</label><input id="webuiToken" name="webuiToken" type="password" autocomplete="off"></div>
            </div>
            <div class="switch-row">
              <label class="switch">
                <input id="webuiLocalOnly" name="webuiLocalOnly" type="checkbox">
                <span class="track"></span>
                <span class="switch-label">仅允许本机访问 (localOnly)</span>
              </label>
            </div>
            <p class="hint">关闭后绑定 0.0.0.0，允许局域网/远程设备访问。建议配合管理令牌使用。</p>
            <p class="hint">每次启动时监听该端口，可在浏览器中管理权限、功能开关与仪表盘。</p>
          </div>
          <label for="githubToken">GitHub API Token（可选）</label>
          <input id="githubToken" name="githubToken" type="password" autocomplete="off" placeholder="ghp_... 或留空">
          <p class="hint">用于减少 GitHub API 速率限制。在 <a href="https://github.com/settings/tokens" target="_blank" style="color:#818cf8">github.com/settings/tokens</a> 创建，只需 public_repo 读取权限。⚠️ 请勿泄露此 Token。</p>
          <div class="grid">
            <div><label for="sapiGmsg">SAPI 群聊指令</label><input id="sapiGmsg" name="sapiGmsg" type="text"></div>
            <div><label for="sapiSmsg">SAPI 私聊指令</label><input id="sapiSmsg" name="sapiSmsg" type="text"></div>
          </div>
          <div class="switch-row">
            <label class="switch">
              <input id="utilsTellAllToTell" name="utilsTellAllToTell" type="checkbox">
              <span class="track"></span>
              <span class="switch-label">Utils：tellall 转发为 tell</span>
            </label>
          </div>
          <div class="switch-row">
            <label class="switch">
              <input id="utilsEnablePolling" name="utilsEnablePolling" type="checkbox">
              <span class="track"></span>
              <span class="switch-label">Utils：启用轮询</span>
            </label>
          </div>
        </div>
      </details>
    </section>

    <div class="btn-wrap">
      <button type="submit">保存配置</button>
    </div>
    <div id="result"></div>
  </form>

  <div class="footer">EnderBridge · Minecraft Bedrock 服务器管理框架</div>
</div>
</div>

<script>
var DEFAULTS = __DEFAULTS__;
function $(id) { return document.getElementById(id); }

// 模组注册表(与后端 MOD_REGISTRY / ADVANCED_MODS 对应)
var MOD_REGISTRY = {
  client: {
    PermissionCommands: { label: "权限命令" },
    Tool: { label: "工具" },
    Position: { label: "坐标" },
    Music: { label: "音乐", config: "music", basePath: "music" },
    MCFunc: { label: "MCFunc", basePath: "mcfunc" },
    MoreWS: { label: "MoreWS" },
    Ezmatic: { label: "Ezmatic 结构", basePath: "ezmatic" },
    ImageMod: { label: "图片", basePath: "image" }
  },
  server: {
    chat: { label: "聊天 / 终端" },
    spam: { label: "刷屏", config: "spam" }
  }
};
var ADVANCED_MODS = {
  AI: { label: "AI 对话（客户端 + 服务端）", config: "ai" },
  QQ: { label: "QQ 群互通", config: "qq" }
};

function buildModList(containerId, side) {
  var box = $(containerId);
  box.innerHTML = "";
  Object.keys(MOD_REGISTRY[side]).forEach(function (name) {
    var meta = MOD_REGISTRY[side][name];
    var label = document.createElement("label");
    label.className = "mod-check";
    var input = document.createElement("input");
    input.type = "checkbox";
    input.value = name;
    input.dataset.config = meta.config || "";
    input.dataset.basepath = meta.basePath || "";
    input.dataset.side = side;
    input.checked = (DEFAULTS[containerId] || []).indexOf(name) !== -1;
    label.appendChild(input);
    var span = document.createElement("span");
    span.className = "name";
    span.textContent = meta.label;
    label.appendChild(span);
    var tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = side === "client" ? "客户端" : "服务端";
    label.appendChild(tag);
    box.appendChild(label);
  });
}
function buildAdvancedList() {
  var box = $("advancedMods");
  box.innerHTML = "";
  Object.keys(ADVANCED_MODS).forEach(function (name) {
    var meta = ADVANCED_MODS[name];
    var label = document.createElement("label");
    label.className = "mod-check";
    var input = document.createElement("input");
    input.type = "checkbox";
    input.value = name;
    input.dataset.config = meta.config || "";
    input.checked = (DEFAULTS.advancedMods || []).indexOf(name) !== -1;
    label.appendChild(input);
    var span = document.createElement("span");
    span.className = "name";
    span.textContent = meta.label;
    label.appendChild(span);
    var tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = "高级";
    label.appendChild(tag);
    box.appendChild(label);
  });
}

// 根据勾选状态切换各配置区的显示
function syncConfig() {
  var aiOn = $("advancedMods").querySelector('input[value="AI"]').checked;
  var qqOn = $("advancedMods").querySelector('input[value="QQ"]').checked;
  var botOn = $("advancedMods").querySelector('input[value="Bot"]').checked;
  var musicOn = $("clientMods").querySelector('input[value="Music"]').checked;
  var spamOn = $("serverMods").querySelector('input[value="spam"]').checked;
  $("aiFields").classList.toggle("hidden", !aiOn);
  $("qqFields").classList.toggle("hidden", !qqOn);
  $("botFields").classList.toggle("hidden", !botOn);
  $("musicFields").classList.toggle("hidden", !musicOn);
  $("spamFields").classList.toggle("hidden", !spamOn);
  // 资源路径:仅显示勾选模组对应的行
  document.querySelectorAll(".bp-row").forEach(function (row) {
    var key = row.getAttribute("data-basepath");
    var on = false;
    document.querySelectorAll("#clientMods input[data-basepath]").forEach(function (el) {
      if (el.dataset.basepath === key && el.checked) on = true;
    });
    row.style.display = on ? "block" : "none";
  });
  var basePathAny = document.querySelectorAll("#clientMods input[data-basepath]:checked").length > 0;
  $("basePathFields").classList.toggle("hidden", !basePathAny);
  toggleRateLimit();
  toggleWebui();
}
function toggleRateLimit() {
  $("rateLimitFields").style.display = $("rateLimitEnabled").checked ? "block" : "none";
}
function toggleWebui() {
  $("webuiFields").style.display = $("webuiEnabled").checked ? "block" : "none";
}

function collectMods(side) {
  var result = [];
  document.querySelectorAll("#" + side + "Mods input:checked").forEach(function (el) {
    result.push(el.value);
  });
  return result;
}
function collectAdvanced() {
  var result = [];
  document.querySelectorAll("#advancedMods input:checked").forEach(function (el) {
    result.push(el.value);
  });
  return result;
}

function fill() {
  $("name").value = DEFAULTS.name;
  $("port").value = DEFAULTS.port;
  $("commandPrefix").value = DEFAULTS.commandPrefix;
  $("logLevel").value = DEFAULTS.logLevel;
  $("apiKey").value = DEFAULTS.apiKey;
  $("baseURL").value = DEFAULTS.baseURL;
  $("chatModel").value = DEFAULTS.chatModel;
  $("commandModel").value = DEFAULTS.commandModel;
  $("aiChatCooldown").value = DEFAULTS.aiChatCooldown;
  $("playPercussion").checked = !!DEFAULTS.playPercussion;
  $("qqGroupId").value = DEFAULTS.qqGroupId;
  $("qqHost").value = DEFAULTS.qqHost;
  $("qqPort").value = DEFAULTS.qqPort;
  $("qqToken").value = DEFAULTS.qqToken;
  $("sapiGmsg").value = DEFAULTS.sapiGmsg;
  $("sapiSmsg").value = DEFAULTS.sapiSmsg;
  $("utilsTellAllToTell").checked = !!DEFAULTS.utilsTellAllToTell;
  $("utilsEnablePolling").checked = DEFAULTS.utilsEnablePolling !== false;
  $("basePathMusic").value = DEFAULTS.basePathMusic;
  $("basePathMcfunc").value = DEFAULTS.basePathMcfunc;
  $("basePathEzmatic").value = DEFAULTS.basePathEzmatic;
  $("basePathImage").value = DEFAULTS.basePathImage;
  $("spamAttack").value = DEFAULTS.spamAttack;
  $("spamAd").value = DEFAULTS.spamAd;
  $("spamAdInterval").value = DEFAULTS.spamAdInterval;
  $("rateLimitEnabled").checked = !!DEFAULTS.rateLimitEnabled;
  $("rateLimitWindowMs").value = DEFAULTS.rateLimitWindowMs;
  $("rateLimitMax").value = DEFAULTS.rateLimitMax;
  $("webuiEnabled").checked = DEFAULTS.webuiEnabled !== false;
  $("webuiPort").value = DEFAULTS.webuiPort;
  $("webuiToken").value = DEFAULTS.webuiToken;
  $("webuiLocalOnly").checked = DEFAULTS.webuiLocalOnly !== false;
  $("githubToken").value = DEFAULTS.githubToken || "";
  $("botHost").value = DEFAULTS.botHost || "127.0.0.1";
  $("botPort").value = DEFAULTS.botPort || 19132;
  $("botUsername").value = DEFAULTS.botUsername || "FakeBot";
  $("botOffline").checked = DEFAULTS.botOffline !== false;
  $("botVersion").value = DEFAULTS.botVersion || "";
  $("owner").value = DEFAULTS.owner;
  $("op").value = (DEFAULTS.op || []).join(", ");
  $("user").value = (DEFAULTS.user || []).join(", ");
  $("blocker").value = (DEFAULTS.blocker || []).join(", ");
  buildModList("clientMods", "client");
  buildModList("serverMods", "server");
  buildAdvancedList();
  syncConfig();
}
function showResult(ok, msg) {
  var r = $("result");
  r.className = ok ? "ok" : "err";
  r.textContent = msg;
  r.style.display = "block";
}
document.getElementById("cfg").addEventListener("submit", function (e) {
  e.preventDefault();
  var btn = document.querySelector("button[type=submit]");
  btn.disabled = true;
  btn.textContent = "保存中...";
  var data = {
    name: $("name").value.trim(),
    port: parseInt($("port").value, 10),
    commandPrefix: $("commandPrefix").value.trim(),
    logLevel: $("logLevel").value,
    apiKey: $("apiKey").value.trim(),
    baseURL: $("baseURL").value.trim(),
    chatModel: $("chatModel").value.trim(),
    commandModel: $("commandModel").value.trim(),
    aiChatCooldown: parseInt($("aiChatCooldown").value, 10),
    playPercussion: $("playPercussion").checked,
    qqGroupId: parseInt($("qqGroupId").value, 10),
    qqHost: $("qqHost").value.trim(),
    qqPort: parseInt($("qqPort").value, 10),
    qqToken: $("qqToken").value.trim(),
    sapiGmsg: $("sapiGmsg").value.trim(),
    sapiSmsg: $("sapiSmsg").value.trim(),
    utilsTellAllToTell: $("utilsTellAllToTell").checked,
    utilsEnablePolling: $("utilsEnablePolling").checked,
    basePathMusic: $("basePathMusic").value.trim(),
    basePathMcfunc: $("basePathMcfunc").value.trim(),
    basePathEzmatic: $("basePathEzmatic").value.trim(),
    basePathImage: $("basePathImage").value.trim(),
    spamAttack: $("spamAttack").value.trim(),
    spamAd: $("spamAd").value,
    spamAdInterval: parseInt($("spamAdInterval").value, 10),
    rateLimitEnabled: $("rateLimitEnabled").checked,
    rateLimitWindowMs: parseInt($("rateLimitWindowMs").value, 10),
    rateLimitMax: parseInt($("rateLimitMax").value, 10),
    webuiEnabled: $("webuiEnabled").checked,
    webuiPort: parseInt($("webuiPort").value, 10),
    webuiToken: $("webuiToken").value.trim(),
    webuiLocalOnly: $("webuiLocalOnly").checked,
    githubToken: $("githubToken").value.trim(),
    botHost: $("botHost").value.trim(),
    botPort: parseInt($("botPort").value, 10),
    botUsername: $("botUsername").value.trim(),
    botOffline: $("botOffline").checked,
    botVersion: $("botVersion").value.trim(),
    owner: $("owner").value.trim(),
    op: $("op").value,
    user: $("user").value,
    blocker: $("blocker").value,
    clientMods: collectMods("client"),
    serverMods: collectMods("server"),
    advancedMods: collectAdvanced()
  };
  fetch("/api/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data)
  }).then(function (res) { return res.json(); }).then(function (result) {
    showResult(result.ok, result.message || (result.ok ? "保存成功" : "保存失败"));
    btn.disabled = false;
    btn.textContent = "保存配置";
  }).catch(function (err) {
    showResult(false, "请求失败: " + err.message);
    btn.disabled = false;
    btn.textContent = "保存配置";
  });
});
document.addEventListener("change", function (e) {
  if (e.target && e.target.closest && e.target.closest(".mod-list")) syncConfig();
  if (e.target && e.target.id === "rateLimitEnabled") toggleRateLimit();
  if (e.target && e.target.id === "webuiEnabled") toggleWebui();
});
fill();
</script>
</body>
</html>
"""


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
    html = PAGE_HTML.replace("__DEFAULTS__", json.dumps(defaults, ensure_ascii=False).replace("<", "\\u003c"))

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
