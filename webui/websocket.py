"""webui/websocket.py — 轻量原生 RFC 6455 WebSocket 协议编解码与连接管理

专为 EnderBridge WebUI 控制台实时推流设计，零外部重量级 C 依赖，
支持：
- RFC 6455 握手 Key 计算 (Sec-WebSocket-Accept)
- 客户端掩码解码 (Client-to-Server Masking) 与服务端无掩码帧封装
- 文本帧 (OP_TEXT)、控制帧 (Ping/Pong/Close) 协议支持
- 多线程安全写操作与长连接优雅关闭
"""

import base64
import hashlib
import json
import socket
import struct
import threading
from typing import Optional, Tuple

WS_MAGIC = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONTINUATION = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


def compute_accept_key(sec_key: str) -> str:
    """计算 RFC 6455 握手 Sec-WebSocket-Accept 值"""
    raw = (sec_key.strip().encode("utf-8")) + WS_MAGIC
    return base64.b64encode(hashlib.sha1(raw).digest()).decode("ascii")


def make_frame(payload: bytes, opcode: int = OP_TEXT) -> bytes:
    """封装服务端向客户端发送的未掩码数据帧"""
    length = len(payload)
    b0 = 0x80 | (opcode & 0x0F)  # FIN=1 + opcode

    if length < 126:
        header = bytes([b0, length])
    elif length <= 65535:
        header = bytes([b0, 126]) + struct.pack("!H", length)
    else:
        header = bytes([b0, 127]) + struct.pack("!Q", length)

    return header + payload


def _recv_exact(sock: socket.socket, count: int) -> bytes:
    """精确读取指定字节数，若套接字关闭则抛出 EOFError"""
    buf = bytearray()
    while len(buf) < count:
        chunk = sock.recv(count - len(buf))
        if not chunk:
            raise EOFError("WebSocket 客户端连接已关闭")
        buf.extend(chunk)
    return bytes(buf)


def read_frame(sock: socket.socket) -> Tuple[int, bytes]:
    """读取并解包单个 RFC 6455 帧 (支持客户端掩码解密)"""
    head = _recv_exact(sock, 2)
    b0, b1 = head[0], head[1]
    opcode = b0 & 0x0F
    is_masked = bool(b1 & 0x80)
    length = b1 & 0x7F

    if length == 126:
        length = struct.unpack("!H", _recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _recv_exact(sock, 8))[0]

    mask_key = _recv_exact(sock, 4) if is_masked else None
    raw_payload = _recv_exact(sock, length) if length > 0 else b""

    if is_masked and mask_key:
        payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(raw_payload))
    else:
        payload = raw_payload

    return opcode, payload


class WebSocketConnection:
    """包装原始 TCP 套接字的 WebSocket 会话对象，提供线程安全的数据帧发送"""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self._write_lock = threading.Lock()
        self._closed = False

    @property
    def is_closed(self) -> bool:
        return self._closed

    def send_text(self, text: str) -> None:
        """发送 UTF-8 文本帧"""
        self._send(make_frame(text.encode("utf-8"), OP_TEXT))

    def send_json(self, obj: dict) -> None:
        """发送 JSON 文本帧"""
        self.send_text(json.dumps(obj, ensure_ascii=False))

    def send_ping(self, payload: bytes = b"") -> None:
        """发送 Ping 保活控制帧"""
        self._send(make_frame(payload, OP_PING))

    def send_pong(self, payload: bytes = b"") -> None:
        """发送 Pong 响应控制帧"""
        self._send(make_frame(payload, OP_PONG))

    def send_close(self, code: int = 1000) -> None:
        """发送 Close 关闭握手帧"""
        try:
            payload = struct.pack("!H", code)
            self._send(make_frame(payload, OP_CLOSE))
        except Exception:
            pass

    def _send(self, frame: bytes) -> None:
        with self._write_lock:
            if not self._closed:
                try:
                    self.sock.sendall(frame)
                except (ConnectionResetError, BrokenPipeError, OSError):
                    self._closed = True

    def close(self) -> None:
        """安全关闭连接"""
        with self._write_lock:
            if not self._closed:
                self._closed = True
                try:
                    self.sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    self.sock.close()
                except Exception:
                    pass

