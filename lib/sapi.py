"""SAPI 桥接模块

用于与 Minecraft Bedrock 的 SAPI (Server API) 进行通信。

命令说明(命令名见 config 的 sapiConfig,SAPI 端需要注册):
- sapiConfig.gmsg: 获取等待处理的消息列表(JSON 数组)
- sapiConfig.smsg <json>: 设置要传递给 WebSocket 的消息(JSON 对象)

消息格式:
{
    "mod": "ModName",   // 目标 Mod 标识
    "type": "msgType",  // 消息类型
    "data": {}          // 消息数据
}
"""
import asyncio
import json

from lib import shared


def _sapi_config() -> dict:
    try:
        from config import sapiConfig
        return sapiConfig or {}
    except Exception:
        return {}


# 命令不存在的状态码
COMMAND_NOT_FOUND = -2147483648


class SAPIBridge:
    """SAPI 桥接静态工具类"""

    @staticmethod
    async def detect(client) -> bool:
        """检测 /gmsg 和 /smsg 命令是否存在"""
        if not client:
            return False
        try:
            data = await client.runCommand(_sapi_config().get("gmsg", ""))
            status_code = data.get("body", {}).get("statusCode") if isinstance(data, dict) else None
            # -2147483648 表示命令不存在
            if status_code == COMMAND_NOT_FOUND:
                return False
            return True
        except Exception as e:
            shared.logger.debug(f"SAPI 检测失败: {e}")
            return False

    @staticmethod
    async def getMessages(client):
        """获取消息列表;命令不存在时返回 None"""
        if not client:
            return []
        try:
            data = await client.runCommand(_sapi_config().get("gmsg", ""))
            status_code = data.get("body", {}).get("statusCode") if isinstance(data, dict) else None

            # 检查命令是否存在
            if status_code == COMMAND_NOT_FOUND:
                return None

            # 从 statusMessage 获取消息(JSON 字符串)
            status_message = data.get("body", {}).get("statusMessage") if isinstance(data, dict) else None
            if not status_message:
                return []

            # 尝试 JSON 解析
            try:
                messages = json.loads(status_message)
                return messages if isinstance(messages, list) else []
            except Exception:
                return []
        except Exception as e:
            shared.logger.debug(f"SAPI getMessages 失败: {e}")
            return []

    @staticmethod
    async def sendMessage(client, mod: str, type_: str, data: dict = None):
        """发送消息

        Returns:
            True: 成功
            False: 失败但命令存在
            None: 命令不存在
        """
        if not client:
            return False

        if data is None:
            data = {}
        message = json.dumps({"mod": mod, "type": type_, "data": data}, ensure_ascii=False, separators=(",", ":"))

        # 检查消息长度
        if len(message.encode("utf-8")) > 400:
            shared.logger.warning(f"SAPI 消息过长: {len(message.encode('utf-8'))} bytes")
            return False

        escaped = message.replace("\\", "\\\\").replace('"', '\\"')
        command = f'{_sapi_config().get("smsg", "")} "{escaped}"'

        # 检查完整命令长度(不能超过 runCommand 的 461 字节限制)
        if len(command.encode("utf-8")) > 461:
            shared.logger.warning(f"SAPI 命令过长: {len(command.encode('utf-8'))} bytes")
            return False

        try:
            result = await client.runCommand(command)
            status_code = result.get("body", {}).get("statusCode") if isinstance(result, dict) else None

            # 检查命令是否存在
            if status_code == COMMAND_NOT_FOUND:
                return None

            # statusCode 为 0 表示成功
            if status_code == 0:
                shared.logger.debug(f"SAPI 发送成功: {mod}/{type_}")
                return True

            shared.logger.debug(f"SAPI 发送失败: statusCode={status_code}")
            return False
        except Exception as e:
            shared.logger.debug(f"SAPI sendMessage 失败: {e}")
            return False

    # snake_case 别名
    get_messages = getMessages
    send_message = sendMessage


class SAPIMessageHandler:
    """SAPI 消息处理器(统一轮询器)

    为每个客户端实例化一个,负责:
    - 统一轮询 /gmsg 消息队列
    - 按消息中的 mod 字段将消息下放给对应 Mod 注册的处理器
    - 检测状态为实例级(每个客户端独立),互不影响
    - 命令不存在时停止轮询,并每 45 秒重试一次
    """

    def __init__(self, client):
        self.client = client
        # 命令是否存在(实例级状态,None=未检测,False=不存在,True=存在)
        self.command_exists = None
        self.polling = False
        self._poll_task = None
        self._retry_task = None
        # 处理器注册表: modName -> {type: callback}
        self.handlers = {}
        self.poll_interval = 1.0
        self.retry_interval = 45.0
        self.destroyed = False

        # 自动开始轮询
        self.start()

    def register(self, mod_name: str, type_: str, callback) -> None:
        """注册消息处理器(按 modName 下放)"""
        if not mod_name or not isinstance(type_, str) or not callable(callback):
            return
        if mod_name not in self.handlers:
            self.handlers[mod_name] = {}
        self.handlers[mod_name][type_] = callback

    def unregister(self, mod_name: str, type_: str) -> None:
        """移除消息处理器"""
        mod_handlers = self.handlers.get(mod_name)
        if not mod_handlers:
            return
        mod_handlers.pop(type_, None)
        if not mod_handlers:
            self.handlers.pop(mod_name, None)

    def clearMod(self, mod_name: str) -> None:
        """清除指定 Mod 的全部处理器"""
        self.handlers.pop(mod_name, None)

    async def send(self, mod_name: str, type_: str, data: dict = None) -> bool:
        """发送消息(以指定 Mod 名义)"""
        if not self.client or self.destroyed:
            return False

        result = await SAPIBridge.sendMessage(self.client, mod_name, type_, data or {})

        # 命令不存在时禁用并周期重试
        if result is None:
            self._disable()
            return False

        # 发送成功说明命令已恢复,立即重新启用轮询
        if result is True and self.command_exists is False:
            self._enable()

        return result is True

    def start(self) -> None:
        """开始轮询消息(如果已经在轮询中,则忽略)"""
        if self.polling or not self.client or self.destroyed:
            return
        self.polling = True
        # 清除待定的重试任务,以当前轮询为准
        if self._retry_task:
            self._retry_task.cancel()
            self._retry_task = None
        shared.logger.debug("SAPI 开始轮询")
        self._poll_task = asyncio.get_running_loop().create_task(self._poll_loop())

    def stop(self) -> None:
        """停止轮询消息"""
        if not self.polling:
            return
        self.polling = False
        if self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None
        shared.logger.debug("SAPI 停止轮询")

    async def _poll_loop(self) -> None:
        """内部轮询循环"""
        while self.polling and not self.destroyed:
            try:
                # 首次轮询前先检测命令是否存在
                if self.command_exists is None:
                    exists = await SAPIBridge.detect(self.client)
                    if not exists:
                        self._disable()
                        return
                    self.command_exists = True
                    shared.logger.info("SAPI 命令已检测到，桥接功能已启用")

                messages = await SAPIBridge.getMessages(self.client)

                # 命令不存在,停止轮询并周期重试
                if messages is None:
                    self._disable()
                    return

                # 按 mod 下放处理接收到的消息
                for msg in messages:
                    self._handle_message(msg)
            except Exception as e:
                shared.logger.debug(f"SAPI 轮询错误: {e}")

            # 安排下次轮询
            if self.polling:
                try:
                    await asyncio.sleep(self.poll_interval)
                except asyncio.CancelledError:
                    return

    def _handle_message(self, msg) -> None:
        """处理单条消息"""
        if not msg or not isinstance(msg, dict):
            return

        mod = msg.get("mod")
        type_ = msg.get("type")
        data = msg.get("data")
        msg_data = {"mod": mod, "type": type_, "data": data}

        mod_handlers = self.handlers.get(mod) if isinstance(mod, str) else None

        if mod_handlers:
            self._call_handler(mod_handlers.get(type_), msg_data)
            self._call_handler(mod_handlers.get("*"), msg_data)
        else:
            # 无对应 Mod(或 mod 为空)时,广播到所有通配符处理器
            for handlers in self.handlers.values():
                self._call_handler(handlers.get("*"), msg_data)

    def _call_handler(self, handler, msg) -> None:
        """安全调用单个处理器"""
        if not callable(handler):
            return
        try:
            handler(msg)
        except Exception as e:
            shared.logger.error(f"SAPI 消息处理错误: {msg.get('type') if isinstance(msg, dict) else ''}")
            shared.logger.debug(str(e))

    def _disable(self) -> None:
        """禁用桥接(命令不存在):停止轮询并安排周期性重试"""
        if self.command_exists is False:
            return
        self.command_exists = False
        self.stop()
        shared.logger.info("SAPI 命令不存在，已禁用桥接功能")
        self._schedule_retry()

    def _enable(self) -> None:
        """启用桥接(命令恢复)"""
        if self.command_exists is True:
            return
        self.command_exists = True
        shared.logger.info("SAPI 命令已恢复，桥接功能已启用")
        self.start()

    def _schedule_retry(self) -> None:
        """安排周期重试检测"""
        if self._retry_task or self.destroyed:
            return
        self._retry_task = asyncio.get_running_loop().create_task(self._retry_loop())

    async def _retry_loop(self) -> None:
        """周期重试检测循环"""
        try:
            await asyncio.sleep(self.retry_interval)
        except asyncio.CancelledError:
            return
        self._retry_task = None
        if self.destroyed or not self.client:
            return
        try:
            exists = await SAPIBridge.detect(self.client)
            if exists:
                self._enable()
            else:
                self._schedule_retry()
        except Exception:
            self._schedule_retry()

    def destroy(self) -> None:
        """销毁处理器"""
        self.destroyed = True
        self.stop()
        if self._retry_task:
            self._retry_task.cancel()
            self._retry_task = None
        self.handlers.clear()
        self.client = None
