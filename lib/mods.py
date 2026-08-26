"""Mod 管理器模块

包含事件总线、Mod 存储、客户端/服务端 Mod 管理器、SAPI 挂载等。
"""
import asyncio
import importlib
import json
import time

from lib import shared
from lib.current import Current
from lib.command import Command
from lib.permission import PermissionManager
from lib.sapi import SAPIMessageHandler


def _mods_config() -> dict:
    try:
        from config import mods
        return mods or {"client": {}, "server": {}}
    except Exception:
        return {"client": {}, "server": {}}


def _path_to_module(mod_path: str) -> str:
    """把 JS 风格的模块路径转成 Python 模块名

    如 "mod/ai.js" -> "mod.ai";兼容旧格式 "../mod/ai.js"(相对 lib/ 目录)
    """
    p = mod_path.replace("\\", "/")
    # 剥离 "../" 前缀(JS 中相对 lib/ 目录的写法)
    while p.startswith("../"):
        p = p[3:]
    return p.replace("/", ".").removesuffix(".js")


def _import_mod(mod_path: str):
    """动态导入 Mod 模块并返回其默认导出的 Mod 类"""
    module = importlib.import_module(_path_to_module(mod_path))
    return getattr(module, "Mod")


def _reimport_mod(mod_path: str):
    """重新导入 Mod 模块(绕过模块缓存,对应 JS 的时间戳参数)"""
    module = importlib.import_module(_path_to_module(mod_path))
    importlib.reload(module)
    return getattr(module, "Mod")


def _call_maybe_async(fn, *args):
    """调用函数;若返回协程则调度到事件循环(与 JS 不 await Promise 的行为一致)"""
    ret = fn(*args)
    if asyncio.iscoroutine(ret):
        try:
            asyncio.get_running_loop().create_task(ret)
        except RuntimeError:
            pass
    return ret


class EventBus:
    """Mod 事件总线:实现 Mod 间的发布/订阅通信"""

    def __init__(self):
        # 事件名 -> Mod名 -> 回调列表
        self.listeners = {}

    def on(self, event: str, mod_name: str, callback) -> None:
        """订阅事件"""
        if event not in self.listeners:
            self.listeners[event] = {}
        event_map = self.listeners[event]
        if mod_name not in event_map:
            event_map[mod_name] = []
        event_map[mod_name].append(callback)

    def off(self, event: str, mod_name: str) -> None:
        """取消订阅"""
        if event in self.listeners:
            self.listeners[event].pop(mod_name, None)

    def emit(self, event: str, data=None, exclude_mod: str = None) -> None:
        """发布事件"""
        event_map = self.listeners.get(event)
        if not event_map:
            return
        for mod_name, callbacks in list(event_map.items()):
            if mod_name == exclude_mod:
                continue
            for callback in list(callbacks):
                try:
                    _call_maybe_async(callback, data)
                except Exception as e:
                    shared.logger.error(f"EventBus: {mod_name}.{event} 执行错误")
                    shared.logger.debug(str(e))

    def clear_mod(self, mod_name: str) -> None:
        """清除指定 Mod 的所有订阅"""
        for event_map in self.listeners.values():
            event_map.pop(mod_name, None)

    def clear(self) -> None:
        """清除所有订阅"""
        self.listeners.clear()


class ModStorage:
    """Mod 存储管理器:为每个 Mod 提供独立的键值存储空间"""

    def __init__(self, mod_name: str):
        self.mod_name = mod_name
        self.data = {}

    def get(self, key, default_value=None):
        return self.data.get(key, default_value)

    def set(self, key, value):
        self.data[key] = value

    def delete(self, key) -> bool:
        return self.data.pop(key, None) is not None or key in self.data

    def has(self, key) -> bool:
        return key in self.data

    def clear(self):
        self.data.clear()

    def keys(self) -> list:
        return list(self.data.keys())

    def values(self) -> list:
        return list(self.data.values())

    def entries(self) -> list:
        return list(self.data.items())


class ModLogger:
    """Mod 日志实例:为每个 Mod 提供带前缀的日志方法"""

    def __init__(self, mod_name: str):
        self.prefix = f"[{mod_name}]"

    def _fmt(self, args) -> str:
        return " ".join(
            a if isinstance(a, str) else json.dumps(a, ensure_ascii=False) for a in args
        )

    def info(self, *args):
        shared.logger.info(f"{self.prefix} {self._fmt(args)}")

    def warning(self, *args):
        shared.logger.warning(f"{self.prefix} {self._fmt(args)}")

    def error(self, *args):
        shared.logger.error(f"{self.prefix} {self._fmt(args)}")

    def debug(self, *args):
        shared.logger.debug(f"{self.prefix} {self._fmt(args)}")


# 全局事件总线(单例),用于 Mod 间通信
event_bus = EventBus()


class StorageManager:
    """全局存储管理器(单例),管理所有 Mod 的存储空间"""

    stores = {}

    @classmethod
    def get_store(cls, mod_name: str) -> ModStorage:
        if mod_name not in cls.stores:
            cls.stores[mod_name] = ModStorage(mod_name)
        return cls.stores[mod_name]

    @classmethod
    def clear_store(cls, mod_name: str) -> None:
        store = cls.stores.get(mod_name)
        if store:
            store.clear()
            cls.stores.pop(mod_name, None)

    @classmethod
    def clear_all(cls) -> None:
        for store in cls.stores.values():
            store.clear()
        cls.stores.clear()


class _ModSAPIHandle:
    """客户端 Mod 的 SAPI 处理句柄(共享同一轮询器,按 modName 路由)"""

    def __init__(self, hub, mod_name: str):
        self._hub = hub
        self._mod_name = mod_name

    def on(self, type_: str, callback) -> None:
        if self._hub:
            self._hub.register(self._mod_name, type_, callback)

    def off(self, type_: str) -> None:
        if self._hub:
            self._hub.unregister(self._mod_name, type_)

    async def send(self, type_: str, data: dict = None) -> bool:
        if not self._hub:
            return False
        return await self._hub.send(self._mod_name, type_, data or {})

    def exists(self):
        return self._hub.command_exists if self._hub else None


def _resolve_mod_method(instance, name):
    """解析 Mod 方法(兼容实例方法与类方法),返回 bound method 或 None"""
    if instance is None:
        return None
    if hasattr(instance, name) and callable(getattr(instance, name)):
        return getattr(instance, name)
    cls = instance.__class__
    if hasattr(cls, name) and callable(getattr(cls, name)):
        return getattr(cls, name)
    return None


class ClientModManager:
    """客户端 Mod 管理器:每个客户端连接创建一个实例"""

    # 存储已加载的 Mod 类定义(静态,全局共享)
    loaded_mod = {}

    @staticmethod
    async def load() -> None:
        """从配置中读取客户端 Mod 路径并加载"""
        for name, mod_path in _mods_config().get("client", {}).items():
            try:
                mod_class = _import_mod(mod_path)
                ClientModManager.loaded_mod[name] = mod_class
                shared.logger.info(f"Client Mod {name} 已加载")
            except Exception as e:
                shared.logger.error(f"Client Mod {name} 加载失败")
                shared.logger.debug(str(e))

    def __init__(self, client):
        self.client = client
        # 存储 Mod 实例
        self.mod_instances = {}
        # 按权限等级分类存储 Mod 注册的命令
        self.commands = {
            "normal": [],  # 所有用户可用(不含 Blocker)
            "user": [],    # User 以上权限可用
            "op": [],      # OP 以上权限可用
            "owner": [],   # 仅 Owner 权限可用
        }

        # 实例化所有 Mod
        self.instantiate()

        # 注册消息监听
        self.message()

        # 挂载到 client 对象(供 ServerModManager.attachMainClient 使用)
        client.clientMod = self

    def _resolve_mod_method(self, instance, name):
        return _resolve_mod_method(instance, name)

    def instantiate(self) -> None:
        """实例化所有已加载的 Mod 并收集命令"""
        # 为当前客户端创建统一的 SAPI 轮询器
        self.sapi = SAPIMessageHandler(self.client)

        for name, mod_class in ClientModManager.loaded_mod.items():
            try:
                self._instantiate_mod(name, mod_class)
            except Exception as e:
                shared.logger.error(f"Client Mod {name} 实例化失败")
                shared.logger.debug(str(e))

        # 重新收集全部命令(按权限等级分类)
        self._collect_commands()

    def _instantiate_mod(self, name: str, mod_class) -> object:
        """实例化单个 Mod(注入基础设施、SAPI、调用 onStart)"""
        instance = mod_class(self.client)

        # 注入 Mod 基础设施
        instance.modName = name
        client_id = getattr(self.client, "id", None) or "unknown"
        instance.storage = StorageManager.get_store(f"client_{client_id}_{name}")
        instance.logger = ModLogger(f"Client:{name}")

        # 事件通信
        # emit: 只发送给 CurrentClient 的 Server Mod
        def _emit(event, data=None):
            if self.client is not Current.client:
                return
            current_client_mods = Current.client_mods.get(Current.client)
            if not current_client_mods:
                return
            for mod_name, mod in current_client_mods.mod_instances.items():
                listeners = getattr(mod, "_listeners", None)
                if listeners and event in listeners:
                    for cb in listeners[event]:
                        try:
                            _call_maybe_async(cb, data)
                        except Exception as e:
                            shared.logger.error(f"EventBus: {mod_name}.{event} 执行错误")

        # on: 监听事件(存储到 _listeners 供 Server Mod 的 emit 调用)
        def _on(event, callback):
            if not hasattr(instance, "_listeners") or instance._listeners is None:
                instance._listeners = {}
            if event not in instance._listeners:
                instance._listeners[event] = []
            instance._listeners[event].append(callback)

        def _off(event):
            if hasattr(instance, "_listeners") and instance._listeners:
                instance._listeners.pop(event, None)

        instance.emit = _emit
        instance.on = _on
        instance.off = _off

        # 注入 SAPI 处理器(共享统一轮询器,按 modName 下放)
        instance.sapi = self._create_mod_sapi(name)

        self.mod_instances[name] = instance
        # 将实例挂载到 client 对象上,便于命令中访问
        setattr(self.client, name, instance)

        # 调用 onStart 方法(所有基础设施注入完成后,兼容静态方法)
        start_method = (
            self._resolve_mod_method(instance, "onStart")
            or self._resolve_mod_method(instance, "start")
        )
        if start_method:
            try:
                _call_maybe_async(start_method)
            except Exception as e:
                shared.logger.error(f"Client Mod {name}.start 执行错误")
                shared.logger.debug(str(e))

        return instance

    def _collect_commands(self) -> None:
        """重新收集所有 Mod 的命令(按权限等级分类)"""
        self.commands = {"normal": [], "user": [], "op": [], "owner": []}

        for name, instance in self.mod_instances.items():
            # 检查 Mod 是否导出 onCommand 方法(兼容旧的 commands 方法)
            command_method = getattr(instance, "onCommand", None) or getattr(instance, "commands", None)
            if not callable(command_method):
                continue

            try:
                # 获取命令映射表 { normal: [...], user: [...], op: [...] }
                cmd_map = command_method()

                # 按权限等级合并命令到管理器
                for key, cmd_list in cmd_map.items():
                    if not isinstance(cmd_list, list):
                        continue
                    if key in self.commands:
                        self.commands[key].extend(cmd_list)
            except Exception as e:
                shared.logger.error(f"Client Mod {name} 命令收集失败")
                shared.logger.debug(str(e))

    async def reload(self, name: str) -> dict:
        """重载单个客户端 Mod"""
        mod_class = ClientModManager.loaded_mod.get(name)
        mod_path = _mods_config().get("client", {}).get(name)
        if not mod_class or not mod_path:
            return {"success": False, "message": f'Client Mod "{name}" 未在配置中定义'}

        # 销毁旧实例
        old_instance = self.mod_instances.get(name)
        if old_instance:
            destroy_method = (
                self._resolve_mod_method(old_instance, "onDestroy")
                or self._resolve_mod_method(old_instance, "destroy")
            )
            if destroy_method:
                try:
                    _call_maybe_async(destroy_method)
                except Exception as e:
                    shared.logger.error(f"Client Mod {name}.onDestroy 执行错误")
                    shared.logger.debug(str(e))

            # 清除 SAPI 处理器与事件订阅
            if self.sapi and hasattr(self.sapi, "clearMod"):
                self.sapi.clearMod(name)
            if self.client and hasattr(self.client, "utils") and self.client.utils:
                self.client.utils.removeOwner(name)
            event_bus.clear_mod(f"client_{getattr(self.client, 'id', None) or 'unknown'}_{name}")

            # 清理 client 上的 Mod 引用
            setattr(self.client, name, None)
            self.mod_instances.pop(name, None)

        # 重新加载(绕过缓存)
        try:
            new_class = _reimport_mod(mod_path)
            if not new_class:
                return {"success": False, "message": f'Client Mod "{name}" 没有默认导出'}

            ClientModManager.loaded_mod[name] = new_class
            self._instantiate_mod(name, new_class)
            self._collect_commands()

            message = f"Client Mod {name} 已重载"
            shared.logger.info(message)
            return {"success": True, "message": message}
        except Exception as e:
            error_msg = f"Client Mod {name} 重载失败: {e}"
            shared.logger.error(error_msg)
            shared.logger.debug(getattr(e, "__traceback__", None))

            # 重载失败时尝试恢复旧版本
            try:
                old_class = _import_mod(mod_path)
                ClientModManager.loaded_mod[name] = old_class
                self._instantiate_mod(name, old_class)
                self._collect_commands()
                shared.logger.warning(f"Client Mod {name} 已恢复到旧版本")
            except Exception:
                shared.logger.error(f"Client Mod {name} 恢复失败")

            return {"success": False, "message": error_msg}

    async def reload_all(self) -> dict:
        """重载当前客户端的所有 Mod"""
        success = []
        failed = []

        for name in list(ClientModManager.loaded_mod.keys()):
            result = await self.reload(name)
            if result.get("success"):
                success.append(name)
            else:
                failed.append(name)

        return {"success": success, "failed": failed}

    @staticmethod
    async def reload_all_clients() -> dict:
        """重载所有客户端连接的所有 Mod 实例"""
        success = []
        failed = []

        for client, manager in list(Current.client_mods.items()):
            if not manager or not hasattr(manager, "reload_all"):
                continue
            result = await manager.reload_all()
            client_id = getattr(client, "id", None) or "?"
            success.extend(f"{client_id}:{name}" for name in result["success"])
            failed.extend(f"{client_id}:{name}" for name in result["failed"])

        return {"success": success, "failed": failed}

    def _create_mod_sapi(self, mod_name: str) -> _ModSAPIHandle:
        """创建 Mod 的 SAPI 处理句柄(所有 Mod 共享同一个轮询器)"""
        hub = self.sapi
        if not hub:
            return None
        return _ModSAPIHandle(hub, mod_name)

    def message(self) -> None:
        """消息订阅与处理:监听 PlayerMessage 事件,根据权限等级执行对应命令"""
        async def _handler(data):
            # 提取消息字段
            body = data.get("body", {})
            sender = body.get("sender")
            msg = body.get("message")
            type_ = body.get("type")

            # 过滤非法消息
            if not msg or not type_ or not sender:
                return

            # 记录消息日志
            self.log(sender, msg, type_)

            # 仅处理 chat 类型且长度小于 256 的消息
            if type_ != "chat" or len(msg) >= 256:
                return

            # 检查消息是否以命令前缀开头(动态读取 config.py,与 WebUI 保存保持同步)
            Command.reload_prefix()
            if not msg.startswith(Command.command_prefix):
                return

            # 服务端 Mod 专属命令(如 $chat)由服务端处理,客户端不拦截、不报"未知的命令"
            if ServerModManager.has_command(msg.split(" ")[0]):
                return

            # 内置命令:终端侧的本地命令,任何人可用,无需权限分级
            token = msg.split(" ")[0]  # e.g. "$help"
            token_suffix = token[len(Command.command_prefix):].strip()  # e.g. "help"
            if token_suffix in ("status", "info"):
                st = shared.start_time
                conns = shared.connections_ref
                uptime = int(time.time() - st) if st else 0
                h, m, s = uptime // 3600, (uptime % 3600) // 60, uptime % 60
                self.client.tell(sender, f"§e客户端连接数: §f{len(conns) if conns else 0}")
                self.client.tell(sender, f"§e运行时间: §f{h}h {m}m {s}s")
                return
            if token_suffix == "list":
                conns = shared.connections_ref
                if not conns:
                    self.client.tell(sender, "§e当前无客户端连接")
                else:
                    self.client.tell(sender, "§e在线客户端:")
                    for i, conn in enumerate(conns, 1):
                        ip = conn.ws.remote_address[0] if conn.ws.remote_address else "unknown"
                        role = "主客户端" if conn is Current.client else "副客户端"
                        self.client.tell(sender, f"§7  {i}. {ip} ({role})")
                return

            # 查询发送者权限
            permission = await PermissionManager.query(sender)

            # 权限查询出错
            if isinstance(permission, Exception):
                self.client.tellAll(f"§cCommand | §fError > §i{permission}")
                return

            # Blocker 黑名单用户直接拒绝
            if permission < 0:
                self.client.tell(f"§cCommand | §fError > §i命令权限错误", sender)
                return

            if not self.execute(sender, msg, self.commands["normal"]):
                return

            if permission < 1:
                self.client.tell(f"§cCommand | §fError > §i未知的命令 {msg.split(' ')[0]}，权限受限", sender)
                return

            if not self.execute(sender, msg, self.commands["user"]):
                return

            if permission < 2:
                self.client.tell(f"§cCommand | §fError > §i未知的命令 {msg.split(' ')[0]}，权限受限", sender)
                return

            if not self.execute(sender, msg, self.commands["op"]):
                return

            if permission < 3:
                self.client.tell(f"§cCommand | §fError > §i未知的命令 {msg.split(' ')[0]}，权限受限", sender)
                return

            if not self.execute(sender, msg, self.commands["owner"]):
                return

            self.client.tell(f"§cCommand | §fError > §i未知的命令 {msg.split(' ')[0]}", sender)

        def _sync_wrapper(data):
            try:
                asyncio.get_running_loop().create_task(_handler(data))
            except RuntimeError:
                pass

        self.client.subscribe("PlayerMessage", _sync_wrapper)

    def log(self, sender: str, msg: str, type_: str) -> None:
        """消息日志记录(仅记录主客户端的 chat 消息)"""
        if type_ == "chat":
            if self.client is Current.client:
                shared.message_logger.log(f"<{sender}> {msg}")

    def execute(self, sender: str, msg: str, cmds: list) -> bool:
        """遍历命令列表并执行匹配的命令;False=已匹配并执行,True=无匹配"""
        try:
            for cmd in cmds:
                # 异步命令出错时反馈给发送者
                def _on_error(e, _sender=sender):
                    self.client.tell(f"§cCommand | §fError > §i{e}", _sender)
                    shared.logger.debug(str(e))

                cmd.on_error = _on_error

                result = cmd.execute(sender, msg)

                if result:
                    # 命令执行出错时通知发送者
                    if not result.get("status") and result.get("message"):
                        self.client.tell(f"§cCommand | §fError > §i{result['message']}", sender)
                    return False
        except Exception as e:
            self.client.tellAll(f"§cModCMD | §fError > §i{e}")
            return False

        return True

    def call_mod_method(self, method_name: str, *args) -> None:
        """调用所有 Mod 的指定方法(如果存在)"""
        for name, instance in self.mod_instances.items():
            method = self._resolve_mod_method(instance, method_name)
            if method:
                try:
                    _call_maybe_async(method, *args)
                except Exception as e:
                    shared.logger.error(f"Client Mod {name}.{method_name} 执行错误")
                    shared.logger.debug(str(e))

    def get_mod(self, mod_name: str):
        """获取指定 Mod 实例"""
        return self.mod_instances.get(mod_name) or None

    def get_all_mods(self) -> dict:
        """获取所有 Mod 实例"""
        return dict(self.mod_instances)

    def destroy(self) -> None:
        """销毁方法:清理所有 Mod 实例并释放资源"""
        # 调用所有 Mod 的 onDestroy 方法
        self.call_mod_method("onDestroy")

        # 销毁统一的 SAPI 轮询器
        if self.sapi and hasattr(self.sapi, "destroy"):
            self.sapi.destroy()
        self.sapi = None

        # 清理 Mod 实例
        client_id = getattr(self.client, "id", None) or "unknown"
        for name, instance in list(self.mod_instances.items()):
            # 清除 SAPI 句柄引用
            instance.sapi = None
            # 清除事件订阅与存储,避免客户端反复连接造成内存泄漏
            event_bus.clear_mod(f"client_{client_id}_{name}")
            StorageManager.clear_store(f"client_{client_id}_{name}")
            # 清除 client 上的 Mod 引用
            setattr(self.client, name, None)

        self.client = None
        self.mod_instances = {}
        self.commands = {}


class ServerSAPIHandle:
    """服务端 Mod 的 SAPI 处理句柄:绑定到当前主客户端的统一轮询器"""

    def __init__(self, mod_name: str):
        self.mod_name = mod_name
        # 绑定的统一轮询器
        self.hub = None
        # 注册记录:未连接时暂存,挂载时恢复
        self.registered = []

    def _attach(self, hub) -> None:
        """挂载到指定轮询器"""
        if not hub or self.hub is hub:
            return
        self._detach()
        self.hub = hub
        for type_, callback in self.registered:
            hub.register(self.mod_name, type_, callback)

    def _detach(self) -> None:
        """从当前轮询器卸载"""
        if not self.hub:
            return
        for type_ in [t for t, _ in self.registered]:
            self.hub.unregister(self.mod_name, type_)
        self.hub = None

    def on(self, type_: str, callback) -> None:
        """注册消息处理器("*" 表示所有类型)"""
        if not isinstance(type_, str) or not callable(callback):
            return
        self.registered.append([type_, callback])
        if self.hub:
            self.hub.register(self.mod_name, type_, callback)

    def off(self, type_: str) -> None:
        """移除消息处理器"""
        self.registered = [r for r in self.registered if r[0] != type_]
        if self.hub:
            self.hub.unregister(self.mod_name, type_)

    async def send(self, type_: str, data: dict = None) -> bool:
        """发送消息"""
        if not self.hub:
            return False
        return await self.hub.send(self.mod_name, type_, data or {})

    def exists(self):
        """获取命令是否存在"""
        return self.hub.command_exists if self.hub else None

    def destroy(self) -> None:
        """销毁句柄"""
        self._detach()
        self.registered = []


class ServerModManager:
    """服务端 Mod 管理器(静态单例,不随客户端连接创建)"""

    # 存储已加载的 Mod 类定义
    loaded_mod = {}

    # 存储 Mod 实例(用于调用实例方法)
    mod_instances = {}

    # 服务端 Mod 注册的命令名集合(不含前缀),用于客户端识别"由服务端处理"的命令
    command_names = set()

    @classmethod
    def _resolve_method(cls, instance, name):
        return _resolve_mod_method(instance, name)

    @classmethod
    def _inject_infra(cls, target, name: str) -> None:
        """向目标注入 Mod 基础设施(实例或类均可)"""
        target.modName = name
        target.storage = StorageManager.get_store(f"server_{name}")
        target.logger = ModLogger(f"Server:{name}")

        # 事件通信
        # emit: 只发送给 CurrentClient 的 Client Mod
        def _emit(event, data=None):
            if not Current.client:
                return
            current_client_mods = Current.client_mods.get(Current.client)
            if not current_client_mods:
                return
            for mod_name, mod in current_client_mods.mod_instances.items():
                listeners = getattr(mod, "_listeners", None)
                if listeners and event in listeners:
                    for cb in listeners[event]:
                        try:
                            _call_maybe_async(cb, data)
                        except Exception as e:
                            shared.logger.error(f"EventBus: {mod_name}.{event} 执行错误")

        # on: 监听 CurrentClient 的事件
        def _on(event, callback):
            if not hasattr(target, "_listeners") or target._listeners is None:
                target._listeners = {}
            if event not in target._listeners:
                target._listeners[event] = []
            target._listeners[event].append(callback)

        # onAll: 监听所有客户端的事件
        def _on_all(event, callback):
            event_bus.on(event, f"server_{name}", callback)

        # off: 同时移除 on() 注册的 _listeners 与 onAll() 注册的 eventBus 监听
        def _off(event, callback=None):
            if hasattr(target, "_listeners") and target._listeners and event in target._listeners:
                if callable(callback):
                    target._listeners[event] = [cb for cb in target._listeners[event] if cb is not callback]
                    if not target._listeners[event]:
                        del target._listeners[event]
                else:
                    del target._listeners[event]
            event_bus.off(event, f"server_{name}")

        target.emit = _emit
        target.on = _on
        target.onAll = _on_all
        target.off = _off

    @classmethod
    def _inject_sapi(cls, instance, mod_class, name: str) -> None:
        """注入 SAPI 处理句柄(实例与类共享同一个句柄)"""
        handle = ServerSAPIHandle(f"server_{name}")
        instance.sapi = handle
        mod_class.sapi = handle

        # 若当前已有主客户端,立即挂载
        cls.attach_main_client(Current.client)

    @classmethod
    def attach_main_client(cls, client) -> None:
        """将服务端 Mod 的 SAPI 句柄挂载到指定(主)客户端"""
        hub = getattr(client, "clientMod", None)
        hub = getattr(hub, "sapi", None) if hub else None
        if not hub:
            return
        for instance in cls.mod_instances.values():
            sapi = getattr(instance, "sapi", None)
            if sapi and hasattr(sapi, "_attach"):
                try:
                    sapi._attach(hub)
                except Exception as e:
                    shared.logger.error(f"Server Mod {getattr(instance, 'modName', '?')}.sapi 挂载错误")
                    shared.logger.debug(str(e))

    @classmethod
    def detach_main_client(cls) -> None:
        """将服务端 Mod 的 SAPI 句柄从当前主客户端卸载"""
        for instance in cls.mod_instances.values():
            sapi = getattr(instance, "sapi", None)
            if sapi and hasattr(sapi, "_detach"):
                try:
                    sapi._detach()
                except Exception as e:
                    shared.logger.error(f"Server Mod {getattr(instance, 'modName', '?')}.sapi 卸载错误")
                    shared.logger.debug(str(e))

    @classmethod
    async def load(cls) -> None:
        """从配置中读取服务端 Mod 路径并加载"""
        for name, mod_path in _mods_config().get("server", {}).items():
            try:
                mod_class = _import_mod(mod_path)
                cls.loaded_mod[name] = mod_class

                # 创建 Mod 实例
                instance = mod_class()
                cls.mod_instances[name] = instance

                # 注入 Mod 基础设施(实例与类都注入,兼容静态方法与实例方法)
                cls._inject_infra(instance, name)
                cls._inject_infra(mod_class, name)
                cls._inject_sapi(instance, mod_class, name)

                # 调用 onStart / start(优先实例方法,兼容静态方法)
                start_method = cls._resolve_method(instance, "onStart") or cls._resolve_method(instance, "start")
                if start_method:
                    try:
                        _call_maybe_async(start_method)
                    except Exception as e:
                        shared.logger.error(f"Server Mod {name}.start 执行错误")
                        shared.logger.debug(str(e))

                shared.logger.info(f"Server Mod {name} 已加载")
            except Exception as e:
                shared.logger.error(f"Server Mod {name} 加载失败")
                shared.logger.debug(str(e))

        # 收集服务端 Mod 注册的命令名(供客户端识别服务端专属命令)
        cls._collect_command_names()

    @classmethod
    def on_client_connect(cls, client, is_main_client: bool) -> None:
        """通知所有服务端 Mod 客户端已连接"""
        # 服务端 Mod 的 SAPI 只绑定主客户端的统一轮询器
        if is_main_client:
            cls.attach_main_client(client)

        for name, instance in cls.mod_instances.items():
            # 调用 onClientConnect(兼容静态方法)
            connect_method = cls._resolve_method(instance, "onClientConnect")
            if connect_method:
                try:
                    _call_maybe_async(connect_method, client)
                except Exception as e:
                    shared.logger.error(f"Server Mod {name}.onClientConnect 执行错误")
                    shared.logger.debug(str(e))

            # 如果是主客户端,调用 onMainClientConnect
            if is_main_client:
                main_method = cls._resolve_method(instance, "onMainClientConnect")
                if main_method:
                    try:
                        _call_maybe_async(main_method, client)
                    except Exception as e:
                        shared.logger.error(f"Server Mod {name}.onMainClientConnect 执行错误")
                        shared.logger.debug(str(e))

    @classmethod
    def on_client_disconnect(cls, client, was_main_client: bool) -> None:
        """通知所有服务端 Mod 客户端已断开连接"""
        # 主客户端断开时卸载服务端 Mod 的 SAPI,并通知 onMainClientDisconnect 钩子
        if was_main_client:
            cls.detach_main_client()

            for name, instance in cls.mod_instances.items():
                main_method = cls._resolve_method(instance, "onMainClientDisconnect")
                if main_method:
                    try:
                        _call_maybe_async(main_method)
                    except Exception as e:
                        shared.logger.error(f"Server Mod {name}.onMainClientDisconnect 执行错误")
                        shared.logger.debug(str(e))

        for name, instance in cls.mod_instances.items():
            # 调用 onClientDestroy(兼容静态方法)
            destroy_method = cls._resolve_method(instance, "onClientDestroy")
            if destroy_method:
                try:
                    _call_maybe_async(destroy_method, client, was_main_client)
                except Exception as e:
                    shared.logger.error(f"Server Mod {name}.onClientDestroy 执行错误")
                    shared.logger.debug(str(e))

    @classmethod
    def on_message(cls, client, data) -> None:
        """通知所有服务端 Mod 收到 WebSocket 消息"""
        for name, instance in cls.mod_instances.items():
            method = cls._resolve_method(instance, "onMessage")
            if method:
                try:
                    _call_maybe_async(method, client, data)
                except Exception as e:
                    shared.logger.error(f"Server Mod {name}.onMessage 执行错误")
                    shared.logger.debug(str(e))

    @classmethod
    def get_mod(cls, mod_name: str):
        """获取指定 Mod 实例"""
        return cls.mod_instances.get(mod_name) or None

    @classmethod
    def get_all_mods(cls) -> dict:
        """获取所有 Mod 实例"""
        return dict(cls.mod_instances)

    @classmethod
    def get_loaded_mod_names(cls) -> list:
        """获取所有已加载的 Mod 名称"""
        return list(cls.loaded_mod.keys())

    @classmethod
    def _collect_command_names(cls) -> None:
        """重新收集服务端 Mod 注册的命令名(兼容 onCommand 方法与 commands 属性)"""
        names = set()
        for instance in cls.mod_instances.values():
            command_method = getattr(instance, "onCommand", None) or getattr(instance, "commands", None)
            try:
                cmd_map = command_method() if callable(command_method) else command_method
            except Exception:
                continue
            if not isinstance(cmd_map, dict):
                continue
            for cmd_list in cmd_map.values():
                if not isinstance(cmd_list, list):
                    continue
                for cmd in cmd_list:
                    name = getattr(cmd, "name", None)
                    if name:
                        names.add(name)
        cls.command_names = names

    @classmethod
    def has_command(cls, token: str) -> bool:
        """判断命令 token(如 $chat)是否为服务端 Mod 注册的命令"""
        if not cls.command_names or not isinstance(token, str):
            return False
        name = token[len(Command.command_prefix):] if token.startswith(Command.command_prefix) else token
        return name in cls.command_names

    @classmethod
    async def execute_terminal(cls, msg: str, skip_mod: str = None) -> bool:
        """终端命令跨 Mod 转发:让其他服务端 Mod 尝试执行命令

        由 chat(mod.read)的终端读取循环调用;当 chat 自身未匹配命令时,
        转发给其余服务端 Mod(如 spam)执行。返回 True 表示已处理。

        Args:
            msg: 终端输入的命令文本(如 $spam attack)
            skip_mod: 跳过的 Mod 名称(通常是调用方自身,避免重复执行)

        Returns:
            True = 有 Mod 处理了该命令;False = 无 Mod 匹配
        """
        for name, instance in cls.mod_instances.items():
            if skip_mod and name == skip_mod:
                continue
            exec_method = getattr(instance, "execute", None)
            cmd_map = getattr(instance, "commands", None)
            if not callable(exec_method) or not isinstance(cmd_map, dict):
                continue
            cmd_list = cmd_map.get("normal")
            if not isinstance(cmd_list, list):
                continue
            try:
                if not exec_method(msg, cmd_list):
                    return True
            except Exception as e:
                shared.logger.error(f"Server Mod {name}.execute_terminal 错误: {e}")
                shared.logger.debug(f"Server Mod {name}.execute_terminal 详情", exc_info=True)
        return False

    @classmethod
    def get_mod_path(cls, mod_name: str):
        """获取 Mod 的文件路径"""
        return _mods_config().get("server", {}).get(mod_name) or None

    @classmethod
    async def reload(cls, mod_name: str) -> dict:
        """重载指定的服务端 Mod"""
        # 检查 Mod 是否存在
        if not _mods_config().get("server", {}).get(mod_name):
            return {"success": False, "message": f'Mod "{mod_name}" 未在配置中定义'}

        mod_path = _mods_config()["server"][mod_name]

        # 销毁旧的 Mod 实例
        if mod_name in cls.mod_instances:
            old_instance = cls.mod_instances[mod_name]
            old_class = old_instance.__class__

            # 调用 onDestroy / destroy(兼容静态方法)
            destroy_method = cls._resolve_method(old_instance, "onDestroy") or cls._resolve_method(old_instance, "destroy")
            if destroy_method:
                try:
                    _call_maybe_async(destroy_method)
                except Exception as e:
                    shared.logger.error(f"Server Mod {mod_name}.onDestroy 执行错误")
                    shared.logger.debug(str(e))

            # 销毁旧 SAPI 处理器(实例与类共享同一实例)
            for sapi in [getattr(old_instance, "sapi", None), getattr(old_class, "sapi", None)]:
                if sapi and hasattr(sapi, "destroy"):
                    try:
                        sapi.destroy()
                    except Exception:
                        pass

            # 清除旧的事件订阅
            event_bus.clear_mod(f"server_{mod_name}")
            StorageManager.clear_store(f"server_{mod_name}")

            shared.logger.info(f"Server Mod {mod_name} 已销毁(重载中)")

        # 重新加载 Mod
        try:
            mod_class = _reimport_mod(mod_path)
            if not mod_class:
                return {"success": False, "message": f'Mod "{mod_name}" 没有默认导出'}

            # 更新已加载的 Mod
            cls.loaded_mod[mod_name] = mod_class

            # 创建新实例
            instance = mod_class()

            # 注入 Mod 基础设施(实例与类都注入)
            cls._inject_infra(instance, mod_name)
            cls._inject_infra(mod_class, mod_name)
            cls._inject_sapi(instance, mod_class, mod_name)

            cls.mod_instances[mod_name] = instance

            # 调用 onStart / start
            start_method = cls._resolve_method(instance, "onStart") or cls._resolve_method(instance, "start")
            if start_method:
                try:
                    _call_maybe_async(start_method)
                except Exception as e:
                    shared.logger.error(f"Server Mod {mod_name}.start 执行错误")
                    shared.logger.debug(str(e))

            message = f"Server Mod {mod_name} 已重载"
            shared.logger.info(message)
            cls._collect_command_names()
            return {"success": True, "message": message}
        except Exception as e:
            error_msg = f"Server Mod {mod_name} 重载失败: {e}"
            shared.logger.error(error_msg)
            shared.logger.debug(getattr(e, "__traceback__", None))

            # 尝试从配置重新加载旧版本
            if _mods_config().get("server", {}).get(mod_name):
                try:
                    old_class = _import_mod(mod_path)
                    cls.loaded_mod[mod_name] = old_class

                    instance = old_class()

                    cls._inject_infra(instance, mod_name)
                    cls._inject_infra(old_class, mod_name)
                    cls._inject_sapi(instance, old_class, mod_name)

                    cls.mod_instances[mod_name] = instance

                    start_method = cls._resolve_method(instance, "onStart") or cls._resolve_method(instance, "start")
                    if start_method:
                        try:
                            _call_maybe_async(start_method)
                        except Exception as e2:
                            shared.logger.error(f"Server Mod {mod_name}.start 执行错误")
                            shared.logger.debug(str(e2))

                    shared.logger.warning(f"Server Mod {mod_name} 已恢复到旧版本")
                except Exception:
                    shared.logger.error(f"Server Mod {mod_name} 恢复失败")

            cls._collect_command_names()
            return {"success": False, "message": error_msg}

    @classmethod
    async def reload_all(cls) -> dict:
        """重载所有服务端 Mod"""
        success = []
        failed = []

        for mod_name in _mods_config().get("server", {}).keys():
            result = await cls.reload(mod_name)
            if result.get("success"):
                success.append(mod_name)
            else:
                failed.append(mod_name)

        return {"success": success, "failed": failed}

    @classmethod
    def destroy(cls) -> None:
        """静态销毁方法:遍历并销毁所有已加载的服务端 Mod"""
        for name, instance in cls.mod_instances.items():
            mod_class = instance.__class__ if instance else None

            # 调用 onDestroy / destroy(兼容静态方法)
            destroy_method = cls._resolve_method(instance, "onDestroy") or cls._resolve_method(instance, "destroy")
            if destroy_method:
                try:
                    _call_maybe_async(destroy_method)
                except Exception as e:
                    shared.logger.error(f"Server Mod {name}.onDestroy 执行错误")
                    shared.logger.debug(str(e))

            # 销毁 SAPI 处理器(实例与类共享同一实例,重复销毁安全)
            for sapi in [getattr(instance, "sapi", None), getattr(mod_class, "sapi", None) if mod_class else None]:
                if sapi and hasattr(sapi, "destroy"):
                    try:
                        sapi.destroy()
                    except Exception:
                        pass

            # 清除事件订阅和存储
            event_bus.clear_mod(f"server_{name}")
            StorageManager.clear_store(f"server_{name}")

            shared.logger.info(f"Server Mod {name} 已销毁")

        cls.loaded_mod = {}
        cls.mod_instances = {}
