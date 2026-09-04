"""WebSocket 工具类

封装与 Minecraft Bedrock WebSocket API 的所有交互:命令发送、事件订阅、消息分发等。

注意:websockets 库的连接对象(ServerConnection)使用 __slots__,不能直接挂载自定义属性,
因此用 ClientConnection 包装类对齐 JS 中 "将方法绑定到 client" 的模式。
"""
import asyncio
import json
from uuid import uuid4

from lib import shared
from lib.shared import logger as _logger

# 延迟读取配置(与 JS 端动态加载策略一致)
def _utils_config():
    try:
        from config import utilsConfig
        return utilsConfig or {}
    except Exception:
        return {}


def _ws_open_state():
    """websockets 的 OPEN 状态常量"""
    from websockets.protocol import State
    return State.OPEN


class ClientConnection:
    """WebSocket 客户端连接包装类

    对齐 JS ws 对象的关键行为:readyState、send、close,并通过 __getattr__
    将 Utils 的方法透明委托出去(client.tell / client.runCommand 等)。
    """

    def __init__(self, ws):
        self.ws = ws
        # 由 Utils 构造时注入
        self.utils = None
        # 发送锁:websockets 库不允许并发 send,而 JS 的 ws 会自动排队
        self._send_lock = asyncio.Lock()

    @property
    def ready_state(self):
        """当前连接状态(websockets State 枚举,OPEN 表示已连接)"""
        return self.ws.state

    @property
    def is_open(self) -> bool:
        return self.ws.state == _ws_open_state()

    async def send(self, data):
        """发送数据(异常向上传播,由调用方处理)"""
        async with self._send_lock:
            await self.ws.send(data)

    async def close(self, code: int = 1000, reason: str = ""):
        try:
            await self.ws.close(code, reason)
        except Exception:
            pass

    def __getattr__(self, name):
        # 将 client 上的方法调用委托给 Utils(如 tell/runCommand/subscribe 等)
        if self.utils is not None and hasattr(self.utils, name):
            return getattr(self.utils, name)
        raise AttributeError(f"'ClientConnection' object has no attribute '{name}'")


class Utils:
    """WebSocket 工具类(方法名与 JS 版保持一致,便于逐行对照)"""

    # ---- 静态工具方法 ----

    @staticmethod
    def setMulti(multimap: dict, key, value) -> None:
        """设置 Multi Map(用于 subscribeBack / packageBack 等多对多映射)"""
        if key not in multimap:
            multimap[key] = []
        multimap[key].append(value)

    @staticmethod
    def splitByBytes(str_: str, maxBytes: int) -> list:
        """按 UTF-8 字节数分割字符串,防止发送超长包"""
        result = []
        start = 0
        text = str_
        while start < len(text):
            end = start + 1
            while end <= len(text) and len(text[start:end].encode("utf-8")) <= maxBytes:
                end += 1
            # 单个字符就超限时强制推进,避免死循环或产生空片段
            if end - 1 <= start:
                end = start + 2
            cut = end - 1
            # 避免把代理对(emoji)截断:若切点前一字符是高代理,则前移一位
            if cut > start and 0xD800 <= ord(text[cut - 1]) <= 0xDBFF:
                cut -= 1
            if cut <= start:
                cut = start + 1  # 极端情况兜底,保证推进
            result.append(text[start:cut])
            start = cut
        return result

    # snake_case 别名
    set_multi = setMulti
    split_by_bytes = splitByBytes

    # ---- 实例 ----

    def __init__(self, client: ClientConnection):
        # 存储 client
        self.client = client
        # 让包装类可以委托 Utils 方法
        client.utils = self

        # 状态标记
        # permission: 0=未进入世界/未知 1=普通 2=OP 3=最高
        self.permission = 0
        # tellAll 转发模式(默认取配置值,可按客户端用 Tool 命令单独开关)
        cfg = _utils_config()
        self.tell_all_to_tell = cfg.get("tellAllToTell", True)

        # 启动轮询
        if cfg.get("enablePolling", True):
            self.start_polling()

        # 各种操作的返回 Map
        self.command_back = {}
        self.subscribe_back = {}
        self.package_back = {}
        # 订阅归属表: owner(Mod 名) -> list[(event, callback)]
        self.owner_back = {}
        # 已向游戏端订阅的事件集合(同一事件只订阅一次)
        self.subscribed_events = set()

        # 轮询任务引用
        self._in_world_task = None
        self._permission_task = None

    # ---- 基础发包 ----

    def _saveLog(self, message: str, error: Exception = None) -> None:
        """调试发包记录"""
        shared.logger.debug(f"Server -> Client {message}")
        if error:
            shared.logger.error("服务端发包错误")
            shared.logger.debug(str(error))

    async def sendCommandUnsafe(self, command: str, uuid: str = None) -> str:
        """无检测的命令发送方法,可能抛出错误,返回命令的 UUID"""
        if uuid is None:
            uuid = str(uuid4())
        # 构造命令包
        cmd = {
            "body": {
                "origin": {"type": "player"},
                "commandLine": command,
                "version": 17104896,
            },
            "header": {
                "requestId": uuid,
                "messagePurpose": "commandRequest",
                "version": 1,
                "messageType": "commandRequest",
            },
        }
        # 发送命令
        await self.client.send(json.dumps(cmd, ensure_ascii=False, separators=(",", ":")))
        self._saveLog(json.dumps(cmd, ensure_ascii=False, separators=(",", ":")))
        return uuid

    async def sendCommandWithCheck(self, command: str, uuid: str = None) -> str:
        """有检测的执行命令方法,可能抛出错误"""
        if not isinstance(command, str):
            raise ValueError("命令格式错误")
        # 如果没有 client 客户端或未开启则直接返回
        if not self.client or not self.client.is_open:
            raise ConnectionError("该 Client 无效或非活跃")
        # 检测 command 内容是否大于 461 字节
        # 原因:大于 461 字节的包会触发游戏 Block / NetherNet 错误并退出房间
        if len(command.encode("utf-8")) > 461:
            raise ValueError("命令长度过长")
        return await self.sendCommandUnsafe(command, uuid)

    async def sendCommand(self, command: str):
        """无报错的执行命令方法,返回命令 UUID 或 None"""
        try:
            return await self.sendCommandWithCheck(command)
        except Exception:
            return None

    async def runCommand(self, command: str, timeout: int = 10000):
        """带返回的命令执行方法,可能抛出错误

        先以预生成 UUID 注册回调再发送命令,避免响应先于注册到达导致悬挂到超时。
        """
        # 预生成 UUID
        uuid = str(uuid4())
        fut = asyncio.get_running_loop().create_future()
        self.command_back[uuid] = fut

        try:
            await self.sendCommandWithCheck(command, uuid)
        except Exception as e:
            self.command_back.pop(uuid, None)
            raise e

        try:
            return await asyncio.wait_for(fut, timeout / 1000)
        except asyncio.TimeoutError:
            self.command_back.pop(uuid, None)
            raise TimeoutError("命令响应超时")

    # ---- 订阅 ----

    def subscribe(self, event: str, callback=None, owner: str = None):
        """订阅事件方法(发送为异步 fire-and-forget,与 JS 行为一致)"""
        if not isinstance(event, str) or (callback is not None and not callable(callback)):
            raise ValueError("非法 Event 或 非 null 下的非法 callback")
        if not self.client or not self.client.is_open:
            return False

        # 仅在 callback 有效时存储,避免 null 调用
        if callback is not None:
            Utils.setMulti(self.subscribe_back, event, callback)
            # 记录归属,便于 reload 时移除
            if owner:
                if owner not in self.owner_back:
                    self.owner_back[owner] = []
                self.owner_back[owner].append([event, callback])

        # 同一事件已订阅过则不再重复发包
        if event in self.subscribed_events:
            return True
        self.subscribed_events.add(event)

        # 构造 subscribe 包
        sub = {
            "body": {"eventName": event},
            "header": {
                "requestId": str(uuid4()),
                "messagePurpose": "subscribe",
                "version": 1,
                "messageType": "commandRequest",
            },
        }
        payload = json.dumps(sub, ensure_ascii=False, separators=(",", ":"))

        # 发送 subscribe 包(fire-and-forget)
        async def _send():
            try:
                await self.client.send(payload)
                self._saveLog(payload)
            except Exception as e:
                self._saveLog(payload, e)

        try:
            asyncio.get_running_loop().create_task(_send())
        except RuntimeError:
            pass
        return True

    def unsubscribe(self, event: str):
        """取消订阅事件方法"""
        if not isinstance(event, str):
            raise ValueError("非法 Event")
        if not self.client or not self.client.is_open:
            return False

        # 标记事件已取消订阅,允许后续重新订阅
        self.subscribed_events.discard(event)

        # 同步清理 owner_back 中该事件的记录
        for owner in list(self.owner_back.keys()):
            remain = [s for s in self.owner_back[owner] if s[0] != event]
            if not remain:
                del self.owner_back[owner]
            else:
                self.owner_back[owner] = remain

        # 构造 unsubscribe 包
        unsub = {
            "body": {"eventName": event},
            "header": {
                "requestId": str(uuid4()),
                "messagePurpose": "unsubscribe",
                "version": 1,
                "messageType": "commandRequest",
            },
        }
        payload = json.dumps(unsub, ensure_ascii=False, separators=(",", ":"))

        async def _send():
            try:
                await self.client.send(payload)
                # 无错误则删除该事件的所有回调
                self.subscribe_back.pop(event, None)
                self._saveLog(payload)
            except Exception as e:
                self._saveLog(payload, e)

        try:
            asyncio.get_running_loop().create_task(_send())
        except RuntimeError:
            pass

    def subscribePackage(self, uuid: str, callback) -> bool:
        """订阅所有游戏返回的包(主要用于底层管理)"""
        if not isinstance(uuid, str) or callback is None or not callable(callback):
            return False
        self.package_back[uuid] = callback
        return True

    def unsubscribePackage(self, uuid: str) -> None:
        """取消订阅所有游戏返回的包"""
        self.package_back.pop(uuid, None)

    # ---- 消息发送 ----

    def tellAll(self, msg: str) -> None:
        """全局发送消息(使用命令 me)"""
        # 开启转发模式时:直接转发为 tell
        if self.tell_all_to_tell:
            return self.tell(msg)
        # 分割消息并遍历发送
        for m in Utils.splitByBytes(msg, 420):
            self._fire_send_command(f"me {m}")

    def tell(self, msg: str, current: str = "@a", isPrefix: bool = True) -> None:
        """对可选目标发送消息（统一用 /me 广播，不需要 OP）"""
        # 分割消息并遍历发送
        for m in Utils.splitByBytes(msg, 420):
            self._fire_send_command(f"me {m}")

    def _fire_send_command(self, command: str) -> None:
        """fire-and-forget 发送命令(内部吞错)"""
        async def _send():
            try:
                await self.sendCommandWithCheck(command)
            except Exception:
                pass

        try:
            asyncio.get_running_loop().create_task(_send())
        except RuntimeError:
            pass

    # ---- 游戏数据查询 ----

    async def getLocation(self, target: str):
        """获取位置方法,返回 {x, y, z, dimension} 或 None"""
        try:
            data = await self.runCommand(f"querytarget {target}")
        except Exception:
            return None

        body = data.get("body") if isinstance(data, dict) else None
        if not body or body.get("statusCode"):
            return None

        details = body.get("details")
        if not details:
            return None

        # querytarget 返回的 details 是 JSON 字符串,需要解析
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except Exception:
                return None

        # details 是数组,取第一个元素
        entry = details[0] if isinstance(details, list) else details
        if not entry or not entry.get("position"):
            return None

        return {**entry["position"], "dimension": entry.get("dimension")}

    async def getPosition(self, target: str):
        """获取坐标方法,返回 {x, y, z} 或 None"""
        location = await self.getLocation(target)
        return (
            {"x": location["x"], "y": location["y"], "z": location["z"]}
            if location
            else None
        )

    async def getDimension(self, target: str):
        """获取维度方法,返回维度名称或 None"""
        location = await self.getLocation(target)
        return location.get("dimension") if location else None

    async def getInventory(self, target: str):
        """获取物品栏方法,返回物品栏数据或 None"""
        try:
            data = await self.runCommand(f"codebuilder_actorinfo inventory {target}")
            if isinstance(data, dict):
                return data.get("body", {}).get("inventory")
        except Exception:
            pass
        return None

    async def getLocalPlayer(self):
        """获取本地玩家方法,返回玩家名称或 None"""
        try:
            data = await self.runCommand("getlocalplayername")
            if isinstance(data, dict):
                return data.get("body", {}).get("localplayername")
        except Exception:
            pass
        return None

    async def closechat(self) -> bool:
        """关闭聊天框方法,返回操作状态"""
        try:
            data = await self.runCommand("closechat")
            if isinstance(data, dict):
                return data.get("body", {}).get("statusCode") == 0
        except Exception:
            pass
        return False

    def getPermission(self) -> int:
        """获取权限等级:0=未进入世界/未知 1=普通 2=OP 3=最高"""
        return self.permission

    def getTellAllMode(self) -> bool:
        """获取当前 tellAll 转发模式"""
        return self.tell_all_to_tell

    def setTellAllMode(self, enabled: bool) -> bool:
        """设置当前客户端的 tellAll 转发模式"""
        self.tell_all_to_tell = bool(enabled)
        return self.tell_all_to_tell

    # ---- 轮询 ----

    def start_polling(self) -> None:
        """启动轮询:每秒检查是否进入世界,每 45 秒检测权限等级,并立即执行一次"""
        loop = asyncio.get_running_loop()
        self._in_world_task = loop.create_task(self._in_world_loop())
        self._permission_task = loop.create_task(self._permission_loop())

    async def _in_world_loop(self) -> None:
        # 立即执行一次,尽快拿到初始状态
        await self._check_in_world()
        while True:
            await asyncio.sleep(1.0)
            await self._check_in_world()

    async def _permission_loop(self) -> None:
        # 立即执行一次
        await self._check_permission()
        while True:
            await asyncio.sleep(45.0)
            await self._check_permission()

    async def _check_in_world(self) -> None:
        """检测客户端是否进入世界(/list 短超时判定)"""
        if not self.client or not self.client.is_open:
            return
        try:
            await self.runCommand("list", 500)
            # 已进入世界:若当前仍为 0,先临时标记为 1
            if self.permission == 0:
                self.permission = 1
        except Exception:
            # 超时说明未进入世界
            self.permission = 0

    async def _check_permission(self) -> None:
        """检测权限等级(/testfor 失败→1;成功再经 /listd:失败→2,成功→3)"""
        if self.permission == 0:
            return
        if not self.client or not self.client.is_open:
            return
        try:
            # /testfor 为操作员命令,权限不足时命令会失败
            testfor = await self.runCommand("testfor @a", 5000)
            if isinstance(testfor, dict) and testfor.get("body", {}).get("statusCode"):
                self.permission = 1
                return
            # /testfor 成功,进一步判断自身等级是否为 3
            listd = await self.runCommand("listd", 5000)
            if isinstance(listd, dict) and listd.get("body", {}).get("statusCode"):
                self.permission = 2
            else:
                self.permission = 3
        except Exception:
            # 命令超时等异常:保留当前权限值,避免误标记
            pass

    # ---- 消息分发 ----

    def onMessage(self, data: dict) -> None:
        """接收消息方法,分发到 packageBack / subscribeBack / commandBack"""
        if not isinstance(data, dict):
            return
        # 获取包类型 purpose
        purpose = data.get("header", {}).get("messagePurpose")

        # 过滤非法包
        if not purpose:
            return

        # 调试记录信息
        shared.logger.debug(f"Client -> Server {json.dumps(data, ensure_ascii=False)}")

        # 将包直接发送给 packageBack 中存储的 callback 函数
        for callback in list(self.package_back.values()):
            try:
                ret = callback(data)
                # 回调为协程函数时调度执行(对齐 JS 不 await async 回调的行为)
                if asyncio.iscoroutine(ret):
                    try:
                        asyncio.get_running_loop().create_task(ret)
                    except RuntimeError:
                        pass
            except Exception as e:
                shared.logger.error("总返回包 Callback 函数错误")
                shared.logger.debug(str(e))

        # event 事件包
        if purpose == "event":
            event_name = data.get("header", {}).get("eventName")
            if event_name not in self.subscribe_back:
                return
            for callback in list(self.subscribe_back.get(event_name, [])):
                try:
                    ret = callback(data)
                    # 回调为协程函数时调度执行
                    if asyncio.iscoroutine(ret):
                        try:
                            asyncio.get_running_loop().create_task(ret)
                        except RuntimeError:
                            pass
                except Exception as e:
                    shared.logger.error("订阅返回包 Callback 函数错误")
                    shared.logger.debug(str(e))

        # commandResponse 命令返回包
        elif purpose == "commandResponse":
            uuid = data.get("header", {}).get("requestId")
            fut = self.command_back.get(uuid)
            if fut is None:
                return
            try:
                if not fut.done():
                    fut.set_result(data)
            except Exception as e:
                shared.logger.error("命令返回包 Callback 函数错误")
                shared.logger.debug(str(e))
            # 直接删除该元素
            self.command_back.pop(uuid, None)

    # ---- 订阅清理 ----

    def removeOwner(self, owner: str) -> None:
        """按归属(Mod 名)批量移除订阅"""
        subs = self.owner_back.get(owner)
        if not subs:
            return
        for event, callback in subs:
            lst = self.subscribe_back.get(event)
            if lst:
                try:
                    lst.remove(callback)
                except ValueError:
                    pass
                if not lst:
                    self.subscribe_back.pop(event, None)
        self.owner_back.pop(owner, None)

    # ---- 销毁 ----

    def destroy(self) -> None:
        """销毁方法:清除轮询任务、client 引用与所有缓存"""
        if self._in_world_task:
            self._in_world_task.cancel()
        if self._permission_task:
            self._permission_task.cancel()
        self._in_world_task = None
        self._permission_task = None
        # 清除 client 引用
        self.client = None
        # 清空所有 Map
        self.command_back.clear()
        self.subscribe_back.clear()
        self.package_back.clear()
        self.owner_back.clear()
        self.subscribed_events.clear()
