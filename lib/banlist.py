"""IP 封禁管理模块

提供 banlist.json 的读写、IP 封禁/解封、连接拦截功能。
供 WebUI HTTP 服务器和 WebSocket 服务器共同使用。
支持自动封禁:短时间内大量登录失败可自动封禁 IP。
"""
import json
import os
import threading
import time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")
BANLIST_JSON = os.path.join(CONFIG_DIR, "banlist.json")

_lock = threading.RLock()  # RLock:可重入,避免 is_banned/list_bans 内调 save() 死锁
_banned_ips: dict = {}  # {"1.2.3.4": {"reason": "...", "time": "...", "expires": timestamp|None}}

# ===== 登录失败速率限制 / 自动封禁 =====
# 默认: 60 秒内失败 5 次 → 自动封禁 10 分钟
_FAIL_WINDOW = 60       # 检测窗口(秒)
_FAIL_THRESHOLD = 5     # 窗口内失败次数阈值
_BAN_DURATION = 600     # 自动封禁时长(秒),0 = 永久
_fail_log: dict = defaultdict(list)  # {ip: [timestamp, ...]}
_auto_ban_enabled = True


def set_auto_ban(enabled: bool) -> None:
    """设置自动封禁开关"""
    global _auto_ban_enabled
    _auto_ban_enabled = enabled


def is_auto_ban_enabled() -> bool:
    """查询自动封禁是否开启"""
    return _auto_ban_enabled


def _clean_old_fails(ip: str) -> None:
    """清除超出窗口期的失败记录"""
    cutoff = time.time() - _FAIL_WINDOW
    _fail_log[ip] = [t for t in _fail_log[ip] if t > cutoff]


def record_auth_failure(ip: str) -> dict:
    """记录一次登录失败,检查是否触发自动封禁

    Returns:
        {"banned": bool, "attempts": int, "remaining": int}
        banned: 是否在本次触发了自动封禁
        attempts: 当前窗口内累计失败次数
        remaining: 距离自动封禁还差多少次(0 表示已达阈值)
    """
    now = time.time()
    _clean_old_fails(ip)
    _fail_log[ip].append(now)
    attempts = len(_fail_log[ip])
    remaining = max(0, _FAIL_THRESHOLD - attempts)

    if attempts >= _FAIL_THRESHOLD and _auto_ban_enabled:
        ban(ip, reason=f"自动封禁: {_FAIL_WINDOW}秒内 {attempts} 次登录失败")
        _fail_log.pop(ip, None)
        return {"banned": True, "attempts": attempts, "remaining": 0}

    return {"banned": False, "attempts": attempts, "remaining": remaining}


def clear_auth_failures(ip: str) -> None:
    """登录成功后清除该 IP 的失败记录"""
    _fail_log.pop(ip, None)


def get_fail_count(ip: str) -> int:
    """获取 IP 当前窗口内的失败次数"""
    _clean_old_fails(ip)
    return len(_fail_log.get(ip, []))


def load():
    """加载 banlist.json"""
    global _banned_ips
    with _lock:
        if os.path.exists(BANLIST_JSON):
            try:
                with open(BANLIST_JSON, "r", encoding="utf-8") as f:
                    data = json.load(f)
                _banned_ips = data if isinstance(data, dict) else {}
            except Exception:
                _banned_ips = {}
        else:
            _banned_ips = {}


def save():
    """保存 banlist.json"""
    with _lock:
        tmp = BANLIST_JSON + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_banned_ips, f, ensure_ascii=False, indent=2)
        os.replace(tmp, BANLIST_JSON)


def is_banned(ip: str) -> bool:
    """检查 IP 是否被封禁(自动清理已过期的封禁)"""
    expired_ip = None
    with _lock:
        if ip not in _banned_ips:
            return False
        ban_info = _banned_ips[ip]
        expires = ban_info.get("expires")
        if expires and time.time() > expires:
            # 封禁已过期,标记待清理(锁内删除,锁外写盘)
            del _banned_ips[ip]
            expired_ip = ip
    if expired_ip is not None:
        save()
    return expired_ip is None


def ban(ip: str, reason: str = "", duration: int = 0) -> bool:
    """封禁 IP,返回是否为新封禁

    Args:
        ip: 要封禁的 IP 地址
        reason: 封禁原因
        duration: 封禁时长(分钟)。0 = 永久, >0 = 指定时长(分钟)
    """
    now = time.time()
    expires = None if duration <= 0 else now + duration * 60
    with _lock:
        if ip in _banned_ips:
            return False
        _banned_ips[ip] = {
            "reason": reason or "管理员封禁",
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "expires": expires,
        }
    save()
    return True


def unban(ip: str) -> bool:
    """解封 IP,返回是否成功"""
    with _lock:
        if ip not in _banned_ips:
            return False
        del _banned_ips[ip]
    save()
    return True


def list_bans() -> dict:
    """返回所有封禁记录(自动清理已过期的)"""
    had_expired = False
    with _lock:
        now = time.time()
        expired = [ip for ip, info in _banned_ips.items()
                   if info.get("expires") and now > info["expires"]]
        for ip in expired:
            del _banned_ips[ip]
        had_expired = bool(expired)
    if had_expired:
        save()
    with _lock:
        return dict(_banned_ips)


def count() -> int:
    """返回封禁数量"""
    with _lock:
        return len(_banned_ips)
