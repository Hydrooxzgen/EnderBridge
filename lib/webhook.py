# Author: Hydrooxzgen
# Github: https://github.com/Hydrooxzgen
# This project uses the GPL-3.0 license, you can modify/distribute this project according to the GPL-3.0 license
"""lib/webhook.py — 多平台 Webhook 告警与外部通知服务模块 (Webhook Alert Manager)

支持 Discord、钉钉 (DingTalk)、飞书 (Feishu/Lark)、企业微信 (WeCom) 以及通用 JSON Webhook。
提供异步线程池非阻塞发送、签名防伪计算、防刷屏节流限流 (Throttle)、多服务多事件路由与在线测试能力。
"""

import base64
import hashlib
import hmac
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")
CONFIG_JSON = os.path.join(CONFIG_DIR, "config.json")

# 北京时间 UTC+8
BEIJING_TZ = timezone(timedelta(hours=8))


def _now_beijing_str() -> str:
    """获取当前北京时间可读字符串"""
    now = datetime.now(BEIJING_TZ)
    return now.strftime("%Y-%m-%d %H:%M:%S")


def _now_iso_utc() -> str:
    """获取当前 ISO 8601 UTC 时间字符串"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


ALL_SUPPORTED_EVENTS = [
    "server_lifecycle",
    "client_connection",
    "auto_ban",
    "security_guard",
    "watchdog",
    "error_log",
]

DEFAULT_WEBHOOK_CONFIG = {
    "enabled": False,
    "throttleSeconds": 3,
    "services": [],
}


# ===== 平台 Payload 构造器 =====

def _build_discord_payload(
    title: str,
    message: str,
    level: str,
    event_type: str,
    details: Optional[dict] = None,
) -> dict:
    colors = {
        "error": 0xED4245,    # Red
        "warning": 0xFEE75C,  # Yellow / Gold
        "info": 0x57F287,     # Green
    }
    color = colors.get(level.lower(), 0x5865F2)

    fields = [
        {"name": "事件类型", "value": f"`{event_type}`", "inline": True},
        {"name": "告警等级", "value": f"`{level.upper()}`", "inline": True},
    ]
    if details:
        for k, v in list(details.items())[:8]:
            fields.append({"name": str(k), "value": str(v)[:1000], "inline": True})

    embed = {
        "title": f"🚨 {title}" if level == "error" else f"🔔 {title}",
        "description": str(message)[:4000],
        "color": color,
        "fields": fields,
        "footer": {"text": "EnderBridge 告警系统"},
        "timestamp": _now_iso_utc(),
    }
    return {
        "username": "EnderBridge",
        "embeds": [embed],
    }


def _build_dingtalk_request(
    url: str,
    secret: str,
    title: str,
    message: str,
    level: str,
    event_type: str,
    details: Optional[dict] = None,
) -> Tuple[str, dict]:
    final_url = url
    if secret and secret.strip():
        ts = str(round(time.time() * 1000))
        secret_enc = secret.strip().encode("utf-8")
        string_to_sign = f"{ts}\n{secret.strip()}".encode("utf-8")
        hmac_code = hmac.new(secret_enc, string_to_sign, digestmod=hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        sep = "&" if "?" in final_url else "?"
        final_url = f"{final_url}{sep}timestamp={ts}&sign={sign}"

    text_lines = [
        f"### 🔔 {title}",
        f"- **事件类型**: `{event_type}`",
        f"- **告警等级**: `{level.upper()}`",
        f"- **详情**: {message}",
    ]
    if details:
        for k, v in details.items():
            text_lines.append(f"- **{k}**: {v}")
    text_lines.append(f"\n> 时间: {_now_beijing_str()}")

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": f"EnderBridge: {title}",
            "text": "\n\n".join(text_lines),
        },
    }
    return final_url, payload


def _build_feishu_request(
    url: str,
    secret: str,
    title: str,
    message: str,
    level: str,
    event_type: str,
    details: Optional[dict] = None,
) -> Tuple[str, dict]:
    color_template = "red" if level == "error" else ("orange" if level == "warning" else "blue")
    elements: List[dict] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**事件类型**: `{event_type}`\n**告警等级**: `{level.upper()}`\n**详情**: {message}",
            },
        }
    ]
    if details:
        detail_lines = [f"**{k}**: {v}" for k, v in details.items()]
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "\n".join(detail_lines),
            },
        })
    elements.append({"tag": "hr"})
    elements.append({
        "tag": "note",
        "elements": [{"tag": "plain_text", "content": f"来源: EnderBridge | 时间: {_now_beijing_str()}"}],
    })

    card_payload: dict = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"EnderBridge: {title}"},
                "template": color_template,
            },
            "elements": elements,
        },
    }

    if secret and secret.strip():
        ts = int(time.time())
        string_to_sign = f"{ts}\n{secret.strip()}".encode("utf-8")
        hmac_code = hmac.new(string_to_sign, digestmod=hashlib.sha256).digest()
        sign = base64.b64encode(hmac_code).decode("utf-8")
        card_payload["timestamp"] = str(ts)
        card_payload["sign"] = sign

    return url, card_payload


def _build_wecom_request(
    url: str,
    title: str,
    message: str,
    level: str,
    event_type: str,
    details: Optional[dict] = None,
) -> Tuple[str, dict]:
    color_tag = "warning" if level == "error" else "info"
    lines = [
        f"### <font color=\"{color_tag}\">EnderBridge 告警: {title}</font>",
        f"> 事件类型: <font color=\"comment\">{event_type}</font>",
        f"> 告警等级: <font color=\"comment\">{level.upper()}</font>",
        f"\n{message}",
    ]
    if details:
        for k, v in details.items():
            lines.append(f"> **{k}**: {v}")
    lines.append(f"\n> 时间: {_now_beijing_str()}")
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": "\n".join(lines),
        },
    }
    return url, payload


def _build_generic_request(
    url: str,
    secret: str,
    title: str,
    message: str,
    level: str,
    event_type: str,
    details: Optional[dict] = None,
) -> Tuple[str, dict, dict]:
    payload = {
        "source": "EnderBridge",
        "event": event_type,
        "level": level,
        "title": title,
        "message": message,
        "details": details or {},
        "timestamp": _now_beijing_str(),
        "iso_utc": _now_iso_utc(),
    }
    headers = {"Content-Type": "application/json; charset=utf-8", "User-Agent": "EnderBridge-Webhook/1.0"}
    if secret and secret.strip():
        raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        sig = hmac.new(secret.strip().encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        headers["X-EnderBridge-Signature"] = f"sha256={sig}"
    return url, payload, headers


def _send_http(
    url: str,
    payload: dict,
    headers: Optional[dict] = None,
    timeout: float = 6.0,
) -> Tuple[bool, int, str]:
    """底层 HTTP POST 发送函数，兼容各类 Webhook 协议与错误响应解析"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req_headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "EnderBridge-Alert-Bot/1.0",
    }
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            body = resp.read().decode("utf-8", errors="replace")
            # 针对国内平台(钉钉/企业微信/飞书)在 HTTP 200 下返回业务级错误的拦截检查
            try:
                res_json = json.loads(body)
                if isinstance(res_json, dict):
                    if res_json.get("errcode") not in (None, 0):
                        return False, status, f"平台返回业务错误 ({res_json.get('errcode')}): {res_json.get('errmsg', body)}"
                    if res_json.get("code") not in (None, 0):
                        return False, status, f"平台返回业务错误 ({res_json.get('code')}): {res_json.get('msg', body)}"
            except Exception:
                pass
            return True, status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        return False, e.code, f"HTTP {e.code}: {body or e.reason}"
    except Exception as e:
        return False, 0, f"网络请求失败: {e}"


# ===== Webhook 服务管理器 =====

class WebhookManager:
    """EnderBridge Webhook 告警与通知中枢"""

    def __init__(self):
        self._lock = threading.RLock()
        self._config: dict = dict(DEFAULT_WEBHOOK_CONFIG)
        self._throttle_cache: Dict[str, float] = {}
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="EB-Webhook")
        self._local = threading.local()
        self._subscribed = False

    def load_config(self, cfg: Optional[dict] = None) -> None:
        """加载或重载 Webhook 配置"""
        with self._lock:
            if cfg is not None:
                wh_cfg = cfg.get("webhookConfig", {}) if "webhookConfig" in cfg else cfg
            else:
                wh_cfg = {}
                if os.path.exists(CONFIG_JSON):
                    try:
                        with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                            raw = json.load(f)
                            wh_cfg = raw.get("webhookConfig", {})
                    except Exception:
                        wh_cfg = {}

            self._config = {
                "enabled": bool(wh_cfg.get("enabled", False)),
                "throttleSeconds": max(0, int(wh_cfg.get("throttleSeconds", 3))),
                "services": wh_cfg.get("services", []) if isinstance(wh_cfg.get("services"), list) else [],
            }

        self._ensure_logger_subscription()

    def reload(self) -> None:
        """从本地磁盘重新加载配置"""
        self.load_config(None)

    def get_config(self) -> dict:
        """获取当前配置拷贝"""
        with self._lock:
            return {
                "enabled": self._config["enabled"],
                "throttleSeconds": self._config["throttleSeconds"],
                "services": list(self._config["services"]),
            }

    def _ensure_logger_subscription(self) -> None:
        """挂载实时日志错误监听回调，实现零侵入捕获 error_log"""
        if self._subscribed:
            return
        try:
            from lib.logger import _live_log
            _live_log.subscribe(self._on_live_log_entry)
            self._subscribed = True
        except Exception:
            pass

    def _on_live_log_entry(self, record: dict) -> None:
        """实时日志监听回调"""
        if getattr(self._local, "is_dispatching", False):
            return
        if not isinstance(record, dict):
            return
        if record.get("level") != "error":
            return
        source = str(record.get("source") or "")
        if "webhook" in source.lower():
            return
        # 触发 error_log 事件推送
        self.dispatch(
            event_type="error_log",
            level="error",
            title=f"系统错误 [{source}]",
            message=str(record.get("message") or ""),
            details={"source": source, "log_time": record.get("ts", "")},
        )

    def _is_throttled(self, event_type: str, title: str, message: str) -> bool:
        """检查并更新防刷屏节流窗口"""
        throttle_sec = self._config.get("throttleSeconds", 3)
        if throttle_sec <= 0:
            return False

        key = f"{event_type}:{title}:{message[:120]}"
        now = time.time()
        with self._lock:
            # 清理过期键
            cutoff = now - 60.0
            expired = [k for k, t in self._throttle_cache.items() if t < cutoff]
            for exp in expired:
                self._throttle_cache.pop(exp, None)

            last_time = self._throttle_cache.get(key, 0.0)
            if now - last_time < throttle_sec:
                return True
            self._throttle_cache[key] = now
            return False

    def dispatch(
        self,
        event_type: str,
        level: str,
        title: str,
        message: str,
        details: Optional[dict] = None,
        sync_timeout: Optional[float] = None,
    ) -> List[Tuple[str, bool, str]]:
        """向所有订阅该事件类型的启用服务分发告警

        Args:
            event_type: 事件类型，如 server_lifecycle, auto_ban, security_guard, watchdog, client_connection, error_log
            level: 告警等级 (info, warning, error)
            title: 标题
            message: 正文描述
            details: 附属键值字典
            sync_timeout: 若指定则同步执行并等待超时，主要用于测试或关键关闭前推送

        Returns:
            若为同步执行返回各服务的 [(service_name, success, info)] 列表；若为异步执行返回空列表
        """
        with self._lock:
            if not self._config.get("enabled", False):
                return []
            services = list(self._config.get("services", []))

        # 节流防刷
        if self._is_throttled(event_type, title, message):
            return []

        # 匹配服务
        matched_services = []
        for s in services:
            if not isinstance(s, dict) or not s.get("enabled", True):
                continue
            evs = s.get("events", [])
            if not isinstance(evs, list):
                continue
            if event_type in evs or "all" in evs:
                matched_services.append(s)

        if not matched_services:
            return []

        if sync_timeout is not None:
            results = []
            for s in matched_services:
                ok, msg = self._send_to_service(s, event_type, level, title, message, details, timeout=sync_timeout)
                results.append((s.get("name") or s.get("id") or "Service", ok, msg))
            return results

        # 异步分发
        def _async_worker():
            self._local.is_dispatching = True
            try:
                for s in matched_services:
                    try:
                        self._send_to_service(s, event_type, level, title, message, details, timeout=6.0)
                    except Exception:
                        pass
            finally:
                self._local.is_dispatching = False

        self._executor.submit(_async_worker)
        return []

    def _send_to_service(
        self,
        service: dict,
        event_type: str,
        level: str,
        title: str,
        message: str,
        details: Optional[dict] = None,
        timeout: float = 6.0,
    ) -> Tuple[bool, str]:
        """将事件打包并发送到指定服务实例"""
        stype = str(service.get("type") or "generic").lower().strip()
        url = str(service.get("url") or "").strip()
        secret = str(service.get("secret") or "").strip()

        if not url:
            return False, "Webhook URL 为空"

        try:
            if stype == "discord":
                payload = _build_discord_payload(title, message, level, event_type, details)
                ok, status, resp = _send_http(url, payload, timeout=timeout)
            elif stype == "dingtalk":
                final_url, payload = _build_dingtalk_request(url, secret, title, message, level, event_type, details)
                ok, status, resp = _send_http(final_url, payload, timeout=timeout)
            elif stype == "feishu":
                final_url, payload = _build_feishu_request(url, secret, title, message, level, event_type, details)
                ok, status, resp = _send_http(final_url, payload, timeout=timeout)
            elif stype == "wecom":
                final_url, payload = _build_wecom_request(url, title, message, level, event_type, details)
                ok, status, resp = _send_http(final_url, payload, timeout=timeout)
            else:  # generic
                final_url, payload, headers = _build_generic_request(url, secret, title, message, level, event_type, details)
                ok, status, resp = _send_http(final_url, payload, headers=headers, timeout=timeout)

            if ok:
                return True, f"发送成功 (HTTP {status})"
            else:
                return False, f"发送失败: {resp}"
        except Exception as e:
            return False, f"异常: {e}"

    def test_service(self, service: dict) -> Tuple[bool, str]:
        """测试指定服务的网络联通与认证合法性"""
        name = service.get("name") or "未命名服务"
        stype = service.get("type") or "generic"
        test_title = f"Webhook 连通性测试 — {name}"
        test_msg = f"这是一条来自 EnderBridge 的 Webhook 测试消息。当前配置运行正常，支持平台 [{stype.upper()}]。"
        test_details = {
            "测试类型": "在线手动测试",
            "目标服务": name,
            "平台类型": stype,
            "触发时间": _now_beijing_str(),
        }
        return self._send_to_service(
            service=service,
            event_type="test",
            level="info",
            title=test_title,
            message=test_msg,
            details=test_details,
            timeout=8.0,
        )


# 单例全局管理器
webhook = WebhookManager()
# 初始化加载
webhook.load_config()

