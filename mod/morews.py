"""扩展 WebSocket Mod

允许客户端同时连接到多个外部 WebSocket 服务端,实现消息的双向转发

注:websocket-client 是同步库,连接与消息收发在线程中运行,
回调通过 call_soon_threadsafe 调度回主事件循环执行。
"""
import asyncio
import json
import threading

import websocket

from lib.command import Command


class Mod:
    """扩展 WebSocket 连接 Mod(客户端)"""

    def __init__(self, client):
        # 用于存储客户端
        self.client = client
        # 用于存储连接的外部 WebSocket 实例
        self.wss = set()

    # 返回命令定义
    def onCommand(self):
        return {
            "op": [
                Command.create("c:connect", "连接到 WebSocket 服务端")
                .add_string("WebSocket 地址", True)
                .set_func(self._cmd_connect),
            ],
        }

    async def _cmd_connect(self, _, ip):
        self.connect(ip)

    def _post(self, fn, *args):
        """把回调调度回主事件循环执行(兼容同步方法与协程)"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        def _run():
            try:
                result = fn(*args)
                if asyncio.iscoroutine(result):
                    asyncio.get_running_loop().create_task(result)
            except Exception:
                pass

        loop.call_soon_threadsafe(_run)

    # 连接函数
    def connect(self, url):
        # 若没有协议头,自动添加 ws:// 头
        if not (url.startswith("ws://") or url.startswith("wss://")):
            url = "ws://" + url

        # 连接与操作 ws
        # 放入 try - except 防报错
        try:
            # 连接 ws 服务端
            ws = websocket.WebSocketApp(url)

            def on_open(_ws):
                # 发送消息
                self._post(self.client.tellAll, "§eMoreWS | §fConnect > §i已连接")
                # 添加 ws
                self.wss.add(_ws)

            def on_message(_ws, message):
                # 处理
                msg = message
                try:
                    msg = str(msg)
                except Exception:
                    pass
                # 直接发送给客户端
                self._post(self.client.send, msg)

            def on_close(_ws, code, reason):
                # 提示
                self._post(self.client.tellAll, f"§cMoreWS | §fDisconnect > §i已关闭 -> {url}")
                # 删除 ws
                if _ws in self.wss:
                    self.wss.discard(_ws)

            def on_error(_ws, error):
                # 提示
                self._post(self.client.tellAll, f"§cMoreWS | §fError > §i{error}")
                # 删除连接
                if _ws in self.wss:
                    self.wss.discard(_ws)

            ws.on_open = on_open
            ws.on_message = on_message
            ws.on_close = on_close
            ws.on_error = on_error

            # 后台线程运行连接(websocket-client 为同步库)
            threading.Thread(target=ws.run_forever, daemon=True).start()
        except Exception as e:
            # 提示连接失败
            self._post(self.client.tellAll, f"§cMoreWS | §fError > §i连接失败 {e}")

    # 处理来自客户端的消息
    def onPocket(self, data):
        # 将消息转发到所有外部 WebSocket 服务端
        try:
            str_ = json.dumps(data)
        except Exception:
            str_ = str(data)

        # 遍历所有外部服务端
        for ws in list(self.wss):
            try:
                ws.send(str_)
            except Exception:
                pass

    # 销毁方法
    def onDestroy(self):
        # 遍历所有外部服务端连接
        for ws in list(self.wss):
            try:
                ws.close()
            except Exception:
                pass

        # 清空连接集合
        self.wss.clear()
        self.client = None
