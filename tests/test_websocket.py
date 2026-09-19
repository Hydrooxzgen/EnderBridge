"""tests/test_websocket.py — WebUI 控制台 WebSocket 协议与连接测试"""

import json
import socket
import struct
import unittest
from unittest.mock import MagicMock

from webui.websocket import (
    compute_accept_key,
    make_frame,
    read_frame,
    WebSocketConnection,
    OP_TEXT,
    OP_BINARY,
    OP_CLOSE,
    OP_PING,
    OP_PONG,
)


class MockSocket:
    """用于测试帧读取和写入的模拟套接字"""

    def __init__(self, data_to_recv: bytes = b""):
        self.recv_data = bytearray(data_to_recv)
        self.sent_data = bytearray()
        self.closed = False

    def recv(self, count: int) -> bytes:
        if not self.recv_data:
            return b""
        chunk = self.recv_data[:count]
        del self.recv_data[:count]
        return bytes(chunk)

    def sendall(self, data: bytes) -> None:
        self.sent_data.extend(data)

    def shutdown(self, how) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class TestWebSocketProtocol(unittest.TestCase):
    def test_compute_accept_key_rfc_vector(self):
        """测试 RFC 6455 标准测试向量"""
        # RFC 6455 规范样例:
        # Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==
        # Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=
        key = "dGhlIHNhbXBsZSBub25jZQ=="
        expected = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
        self.assertEqual(compute_accept_key(key), expected)

    def test_make_frame_short_text(self):
        """测试普通短文本帧封装 (长度 < 126)"""
        payload = b"Hello, WebSocket"
        frame = make_frame(payload, OP_TEXT)
        self.assertEqual(frame[0], 0x81)  # FIN=1, opcode=0x1
        self.assertEqual(frame[1], len(payload))
        self.assertEqual(frame[2:], payload)

    def test_make_frame_medium_text(self):
        """测试中等长度文本帧 (126 <= 长度 <= 65535)"""
        payload = b"A" * 300
        frame = make_frame(payload, OP_TEXT)
        self.assertEqual(frame[0], 0x81)
        self.assertEqual(frame[1], 126)
        length = struct.unpack("!H", frame[2:4])[0]
        self.assertEqual(length, 300)
        self.assertEqual(frame[4:], payload)

    def test_make_frame_control_frames(self):
        """测试控制帧 (Ping / Pong / Close) 封装"""
        ping_frame = make_frame(b"ping_test", OP_PING)
        self.assertEqual(ping_frame[0], 0x89)
        self.assertEqual(ping_frame[2:], b"ping_test")

        pong_frame = make_frame(b"pong_test", OP_PONG)
        self.assertEqual(pong_frame[0], 0x8A)
        self.assertEqual(pong_frame[2:], b"pong_test")

        close_frame = make_frame(struct.pack("!H", 1000), OP_CLOSE)
        self.assertEqual(close_frame[0], 0x88)
        self.assertEqual(close_frame[1], 2)
        code = struct.unpack("!H", close_frame[2:])[0]
        self.assertEqual(code, 1000)

    def test_read_frame_masked_client_text(self):
        """测试从客户端读取带掩码的文本帧"""
        raw_msg = b"EnderBridge Console Test"
        mask_key = b"\x12\x34\x56\x78"
        masked_payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(raw_msg))

        # 构建客户端帧: b0 = 0x81 (FIN=1, OP_TEXT), b1 = 0x80 | len (MASK=1)
        wire_data = bytes([0x81, 0x80 | len(raw_msg)]) + mask_key + masked_payload

        mock_sock = MockSocket(wire_data)
        opcode, payload = read_frame(mock_sock)
        self.assertEqual(opcode, OP_TEXT)
        self.assertEqual(payload, raw_msg)

    def test_read_frame_masked_extended_length(self):
        """测试带掩码的 16-bit 扩展长度帧读取"""
        raw_msg = b"X" * 200
        mask_key = b"\xaa\xbb\xcc\xdd"
        masked_payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(raw_msg))

        header = bytes([0x81, 0x80 | 126]) + struct.pack("!H", 200) + mask_key
        wire_data = header + masked_payload

        mock_sock = MockSocket(wire_data)
        opcode, payload = read_frame(mock_sock)
        self.assertEqual(opcode, OP_TEXT)
        self.assertEqual(payload, raw_msg)

    def test_read_frame_close(self):
        """测试读取客户端关闭帧"""
        wire_data = bytes([0x88, 0x82]) + b"\x00\x00\x00\x00" + struct.pack("!H", 1000)
        mock_sock = MockSocket(wire_data)
        opcode, payload = read_frame(mock_sock)
        self.assertEqual(opcode, OP_CLOSE)
        self.assertEqual(struct.unpack("!H", payload)[0], 1000)

    def test_connection_send_methods(self):
        """测试 WebSocketConnection 的方法封装"""
        mock_sock = MockSocket()
        ws = WebSocketConnection(mock_sock)

        # 发送文本
        ws.send_text("hello")
        self.assertTrue(len(mock_sock.sent_data) > 0)

        # 发送 JSON
        mock_sock.sent_data.clear()
        ws.send_json({"type": "test", "num": 123})
        data_sent = bytes(mock_sock.sent_data)
        self.assertEqual(data_sent[0], 0x81)
        body = data_sent[2:].decode("utf-8")
        parsed = json.loads(body)
        self.assertEqual(parsed["type"], "test")
        self.assertEqual(parsed["num"], 123)

        # 发送 Ping
        mock_sock.sent_data.clear()
        ws.send_ping()
        self.assertEqual(mock_sock.sent_data[0], 0x89)

        # 发送 Close
        mock_sock.sent_data.clear()
        ws.send_close(1000)
        self.assertEqual(mock_sock.sent_data[0], 0x88)

        # 关闭连接
        ws.close()
        self.assertTrue(ws.is_closed)
        self.assertTrue(mock_sock.closed)


if __name__ == "__main__":
    unittest.main()

