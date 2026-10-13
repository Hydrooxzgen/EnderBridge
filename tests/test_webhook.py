"""tests/test_webhook.py — 多平台 Webhook 告警系统单元测试"""

import json
import time
import unittest
from unittest.mock import MagicMock, patch

from lib.webhook import (
    WebhookManager,
    _build_discord_payload,
    _build_dingtalk_request,
    _build_feishu_request,
    _build_wecom_request,
    _build_generic_request,
    _send_http,
)


class TestWebhookPayloads(unittest.TestCase):
    """测试各平台 Webhook 请求体与签名构造"""

    def test_discord_payload_structure(self):
        payload = _build_discord_payload(
            title="测试告警",
            message="这是一条告警信息",
            level="error",
            event_type="auto_ban",
            details={"ip": "1.2.3.4", "count": 5},
        )
        self.assertEqual(payload["username"], "EnderBridge")
        self.assertIn("embeds", payload)
        self.assertEqual(len(payload["embeds"]), 1)
        embed = payload["embeds"][0]
        self.assertIn("测试告警", embed["title"])
        self.assertEqual(embed["color"], 0xED4245)  # Red for error
        self.assertEqual(embed["description"], "这是一条告警信息")
        field_names = [f["name"] for f in embed["fields"]]
        self.assertIn("事件类型", field_names)
        self.assertIn("告警等级", field_names)
        self.assertIn("ip", field_names)

    def test_dingtalk_request_and_signature(self):
        base_url = "https://oapi.dingtalk.com/robot/send?access_token=test_token"
        secret = "SEC_test_secret_123456"
        final_url, payload = _build_dingtalk_request(
            url=base_url,
            secret=secret,
            title="暴力破解告警",
            message="IP 已封禁",
            level="error",
            event_type="auto_ban",
            details={"ip": "10.0.0.1"},
        )
        self.assertIn("timestamp=", final_url)
        self.assertIn("sign=", final_url)
        self.assertEqual(payload["msgtype"], "markdown")
        self.assertIn("暴力破解告警", payload["markdown"]["title"])
        self.assertIn("10.0.0.1", payload["markdown"]["text"])

    def test_feishu_request_and_signature(self):
        url = "https://open.feishu.cn/open-apis/bot/v2/hook/test_uuid"
        secret = "feishu_secret_abc"
        final_url, payload = _build_feishu_request(
            url=url,
            secret=secret,
            title="看门狗告警",
            message="事件循环挂起",
            level="warning",
            event_type="watchdog",
            details={"silence": "15s"},
        )
        self.assertEqual(final_url, url)
        self.assertIn("sign", payload)
        self.assertIn("timestamp", payload)
        self.assertEqual(payload["msg_type"], "interactive")
        self.assertEqual(payload["card"]["header"]["template"], "orange")

    def test_wecom_request(self):
        url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test_key"
        final_url, payload = _build_wecom_request(
            url=url,
            title="服务器启动",
            message="端口 8800 已就绪",
            level="info",
            event_type="server_lifecycle",
        )
        self.assertEqual(final_url, url)
        self.assertEqual(payload["msgtype"], "markdown")
        self.assertIn("服务器启动", payload["markdown"]["content"])

    def test_generic_request_and_hmac_header(self):
        url = "https://example.com/api/webhook"
        secret = "my_custom_secret"
        final_url, payload, headers = _build_generic_request(
            url=url,
            secret=secret,
            title="安全拦截",
            message="非法操作",
            level="error",
            event_type="security_guard",
            details={"caller": "bad_mod.py"},
        )
        self.assertEqual(final_url, url)
        self.assertEqual(payload["event"], "security_guard")
        self.assertIn("X-EnderBridge-Signature", headers)
        self.assertTrue(headers["X-EnderBridge-Signature"].startswith("sha256="))


class TestWebhookManager(unittest.TestCase):
    """测试 WebhookManager 调度、过滤与节流行为"""

    def setUp(self):
        self.mgr = WebhookManager()

    def test_disabled_by_default(self):
        self.mgr.load_config({"enabled": False, "services": []})
        res = self.mgr.dispatch("auto_ban", "error", "Test", "Message", sync_timeout=1.0)
        self.assertEqual(res, [])

    @patch("lib.webhook._send_http")
    def test_service_event_filtering(self, mock_send):
        mock_send.return_value = (True, 200, '{"ok": true}')
        config = {
            "enabled": True,
            "throttleSeconds": 0,
            "services": [
                {
                    "id": "s1",
                    "name": "Only Ban",
                    "type": "generic",
                    "url": "http://127.0.0.1/ban",
                    "enabled": True,
                    "events": ["auto_ban"],
                },
                {
                    "id": "s2",
                    "name": "Only Start",
                    "type": "generic",
                    "url": "http://127.0.0.1/start",
                    "enabled": True,
                    "events": ["server_lifecycle"],
                },
            ],
        }
        self.mgr.load_config(config)

        # 触发 auto_ban，仅 s1 匹配
        results = self.mgr.dispatch("auto_ban", "error", "IP 封禁", "1.1.1.1 被封", sync_timeout=1.0)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], "Only Ban")
        self.assertTrue(results[0][1])

        # 触发 server_lifecycle，仅 s2 匹配
        results2 = self.mgr.dispatch("server_lifecycle", "info", "服务器启动", "运行中", sync_timeout=1.0)
        self.assertEqual(len(results2), 1)
        self.assertEqual(results2[0][0], "Only Start")

    @patch("lib.webhook._send_http")
    def test_throttle_suppression(self, mock_send):
        mock_send.return_value = (True, 200, "ok")
        config = {
            "enabled": True,
            "throttleSeconds": 10,
            "services": [
                {
                    "id": "s1",
                    "type": "generic",
                    "url": "http://127.0.0.1/test",
                    "enabled": True,
                    "events": ["auto_ban"],
                }
            ],
        }
        self.mgr.load_config(config)

        # 第一次应分发
        res1 = self.mgr.dispatch("auto_ban", "error", "标题A", "内容A", sync_timeout=1.0)
        self.assertEqual(len(res1), 1)

        # 相同标题内容在 10s 内重复触发应被抑制
        res2 = self.mgr.dispatch("auto_ban", "error", "标题A", "内容A", sync_timeout=1.0)
        self.assertEqual(len(res2), 0)

    @patch("lib.webhook._send_http")
    def test_test_service_connectivity(self, mock_send):
        mock_send.return_value = (True, 200, "ok")
        service = {
            "name": "测试服务",
            "type": "discord",
            "url": "https://discord.com/api/webhooks/dummy",
        }
        ok, msg = self.mgr.test_service(service)
        self.assertTrue(ok)
        self.assertIn("200", msg)


if __name__ == "__main__":
    unittest.main()

