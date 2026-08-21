"""QQ 互通 Mod 模块

通过 NapCat (OneBot v11 协议) WebSocket 连接 QQ,实现 QQ 群消息与游戏内消息互通。

注:这里用 websocket-client 实现 NapCat (OneBot v11) 连接:
连接与消息收发运行在后台线程,事件回调通过 call_soon_threadsafe 调度回主事件循环;
API 请求 (get_login_info / send_group_msg) 通过 echo 字段关联请求与响应。
"""
import asyncio
import json
import threading
import time

import websocket

from config import features
from lib import shared


def extract_text(segments):
    """从 OneBot 消息段数组中提取纯文本"""
    if isinstance(segments, str):
        return segments.strip()
    if not isinstance(segments, list):
        return ""
    parts = []
    for s in segments:
        if isinstance(s, dict) and s.get("type") == "text":
            d = s.get("data") or {}
            parts.append(d.get("text") or "")
    return "".join(parts).strip()


def _call_async(coro_factory):
    """把协程工厂调度到主事件循环执行(fire-and-forget)"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    try:
        loop.create_task(coro_factory())
    except Exception:
        pass


class _NapCatClient:
    """基于 websocket-client 的 NapCat (OneBot v11) 客户端"""

    def __init__(self, host, port, access_token):
        self.host = host
        self.port = port
        self.access_token = access_token or ""
        self.ws = None
        self.thread = None
        self.loop = None
        self._ready = None
        self._connected = False
        self._stop = False
        self._echo_seq = 0
        self._pending = {}  # echo -> asyncio.Future
        self._handlers = {}  # 事件名 -> [回调]

    # ---- 事件注册/分发 ----

    def on(self, event, callback):
        self._handlers.setdefault(event, []).append(callback)

    def _post(self, fn):
        """把同步函数调度回主事件循环执行"""
        if self.loop:
            try:
                self.loop.call_soon_threadsafe(fn)
            except Exception:
                pass
        else:
            try:
                fn()
            except Exception:
                pass

    def _emit(self, event, data=None):
        for cb in list(self._handlers.get(event, [])):
            try:
                result = cb(data)
                if asyncio.iscoroutine(result):
                    asyncio.get_running_loop().create_task(result)
            except Exception:
                pass

    # ---- 线程回调(运行在 websocket 线程) ----

    def _on_open(self, ws):
        self._connected = True
        if self.loop and self._ready:
            self.loop.call_soon_threadsafe(self._ready.set)
        self._post(lambda: self._emit("socket.open"))

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
        except Exception:
            return
        if not isinstance(data, dict):
            return

        # 请求响应(带 echo 关联)
        echo = data.get("echo")
        if echo is not None:
            fut = self._pending.pop(str(echo), None)
            if fut:
                self._post(lambda f=fut, d=data: f.set_result(d))
            return

        # 事件推送
        post_type = data.get("post_type")
        if post_type == "message" and data.get("message_type") == "group" and data.get("sub_type") == "normal":
            self._post(lambda: self._emit("message.group.normal", data))

    def _on_error(self, ws, error):
        self._connected = False

    def _on_close(self, ws, code, reason):
        self._connected = False
        if self.loop and self._ready:
            self.loop.call_soon_threadsafe(self._ready.clear)
        self._post(lambda: self._emit("socket.close"))

    # ---- 线程主循环(自动重连) ----

    def _run(self):
        url = f"ws://{self.host}:{self.port}/"
        headers = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
            url += f"?access_token={self.access_token}"
        while not self._stop:
            try:
                ws = websocket.WebSocketApp(url, header=headers)
                ws.on_open = self._on_open
                ws.on_message = self._on_message
                ws.on_error = self._on_error
                ws.on_close = self._on_close
                self.ws = ws
                ws.run_forever()
            except Exception:
                pass
            finally:
                self.ws = None
            if self._stop:
                break
            # 重连延时(与 JS reconnection.delay = 10000 一致)
            time.sleep(10)
        self.thread = None

    # ---- 公开 API ----

    async def connect(self):
        """建立连接(幂等);若线程未运行则启动,最多等待 5 秒连接建立"""
        self.loop = asyncio.get_running_loop()
        if self.thread and self.thread.is_alive() and self._connected:
            return
        # 旧线程仍在重连循环中,先停止并等待退出
        if self.thread and self.thread.is_alive():
            self._stop = True
            old_ws = self.ws
            if old_ws:
                try:
                    old_ws.close()
                except Exception:
                    pass
            await asyncio.to_thread(self.thread.join, 3)
        self._stop = False
        self._ready = asyncio.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass

    async def disconnect(self):
        """断开连接并停止重连线程"""
        self._stop = True
        ws = self.ws
        if ws:
            try:
                ws.close()
            except Exception:
                pass
        t = self.thread
        if t and t.is_alive():
            await asyncio.to_thread(t.join, 3)
        self.thread = None
        self.ws = None
        self._connected = False
        if self.loop and self._ready:
            try:
                self.loop.call_soon_threadsafe(self._ready.clear)
            except Exception:
                pass

    async def request(self, action, params=None):
        """发送 OneBot API 请求,等待响应(超时 10 秒)"""
        ws = self.ws
        if not ws or not self._connected:
            raise ConnectionError("QQ WebSocket 未连接")
        self._echo_seq += 1
        echo = str(self._echo_seq)
        fut = asyncio.get_running_loop().create_future()
        self._pending[echo] = fut
        payload = json.dumps({"action": action, "params": params or {}, "echo": echo})
        try:
            ws.send(payload)
        except Exception:
            self._pending.pop(echo, None)
            raise
        try:
            return await asyncio.wait_for(fut, timeout=10)
        except asyncio.TimeoutError:
            self._pending.pop(echo, None)
            raise TimeoutError(f"QQ API 请求超时: {action}")

    async def get_login_info(self):
        return await self.request("get_login_info")

    async def send_group_msg(self, group_id, text):
        return await self.request("send_group_msg", {
            "group_id": group_id,
            "message": [{"type": "text", "data": {"text": text}}],
        })


class Mod:
    """QQ 互通 Mod(服务端,静态单例;由 tool Mod 的 tool move / commands 直接调用)"""

    napcat = None
    main_client = None

    @staticmethod
    def onStart():
        pass

    @staticmethod
    def connect():
        if Mod.napcat:
            return
        if not features.qq.get("enabled"):
            return

        if not features.qq.get("accessToken"):
            shared.logger.warning("未配置 QQ accessToken，QQ 连接可能被服务端拒绝")

        napcat = _NapCatClient(
            host=features.qq.get("host", "127.0.0.1"),
            port=features.qq.get("port", 3001),
            access_token=features.qq.get("accessToken") or "",
        )
        Mod.napcat = napcat

        napcat.on("message.group.normal", Mod._on_group_message)
        napcat.on("socket.close", lambda _d: shared.logger.warning("QQ 连接已断开"))

        # 与 JS 的 napcat.connect().then(日志).catch(日志) 一致:fire-and-forget
        async def _do_connect():
            try:
                await napcat.connect()
                shared.logger.info("QQ 已连接")
            except Exception as e:
                shared.logger.error("QQ 连接失败")
                shared.logger.debug(str(e))

        _call_async(_do_connect)

    @staticmethod
    def set_main_client(client):
        Mod.main_client = client
        if client:
            Mod.connect()

    @staticmethod
    def get_main_client():
        return Mod.main_client

    # 主客户端接入/断开钩子(由 lib/mods.py 的 ServerModManager 分发)
    @staticmethod
    def on_main_client_connect(client):
        Mod.set_main_client(client)

    @staticmethod
    def on_main_client_disconnect():
        Mod.set_main_client(None)

    # 处理 QQ 群普通消息 -> 转发到游戏
    @staticmethod
    def _on_group_message(data):
        if not features.qq.get("enabled"):
            return
        if data.get("group_id") != features.qq.get("groupId"):
            return
        if not Mod.main_client:
            return

        sender = data.get("sender") or {}
        nickname = sender.get("card") or sender.get("nickname") or "QQ用户"
        text = extract_text(data.get("message"))
        if not text:
            return

        try:
            # tell 为同步方法,isPrefix=False
            Mod.main_client.tell(f"§dQQ | §f<{nickname}> > §i{text}", "@a", False)
        except Exception:
            pass

    # 手动自愈检测:强制断开并重建连接,再用真实 API 请求验证链路是否畅通
    @staticmethod
    async def check():
        if not features.qq.get("enabled"):
            return {"ok": False, "reason": "QQ 互通未启用"}
        if not Mod.napcat:
            Mod.connect()
        if not Mod.napcat:
            return {"ok": False, "reason": "napcat 未初始化"}

        try:
            # disconnect() 会清空旧 socket,connect() 再建立全新连接,避免旧连接残留
            await Mod.napcat.disconnect()
            await Mod.napcat.connect()
            # get_login_info 需要真正的 socket 往返,失败即说明链路不通
            info = await Mod.napcat.get_login_info()
            data = info.get("data") or {}
            nickname = data.get("nickname") or info.get("nickname") or "QQ"
            return {"ok": True, "nickname": nickname}
        except Exception as e:
            return {"ok": False, "reason": str(e) or "未知错误"}

    @staticmethod
    async def send_to_group(text):
        if not features.qq.get("enabled"):
            return False
        if not Mod.napcat:
            return False

        # 若底层 socket 尚未建立/已断开,先尝试(重)连接,避免"总是发送失败"
        try:
            await Mod.napcat.connect()
        except Exception:
            pass

        try:
            await Mod.napcat.send_group_msg(features.qq.get("groupId"), text)
            return True
        except Exception as e:
            shared.logger.error("QQ 消息发送失败")
            shared.logger.debug(str(e))
            return False

    # 销毁(服务端关闭时调用)
    @staticmethod
    def destroy():
        Mod.main_client = None
        if Mod.napcat:
            napcat = Mod.napcat
            Mod.napcat = None
            _call_async(napcat.disconnect)

    @staticmethod
    def onDestroy():
        Mod.destroy()
