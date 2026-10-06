# EnderBridge 模组开发与加载指南（Wiki）

> 本文档详细讲解如何在 EnderBridge 中编写、测试、加载与热重载你的自定义 Mod。
> 适用版本：EnderBridge v1.1.0+（Python 3.12+，WebSocket 8800 端口架构）

---

## 📑 目录

1. [Mod 体系与两层架构](#1-mod-体系与两层架构)
2. [Mod 的注册与配置方式](#2-mod-的注册与配置方式)
3. [编写你的第一个客户端 Mod](#3-编写你的第一个客户端-mod)
4. [命令系统设计 (Command 框架)](#4-命令系统设计-command-框架)
5. [常用 API 工具箱 (Utils & Client)](#5-常用-api-工具箱-utils--client)
6. [事件总线与通信 (EventBus)](#6-事件总线与通信-eventbus)
7. [持久化存储 (StorageManager)](#7-持久化存储-storagemanager)
8. [编写服务端 Mod](#8-编写服务端-mod)
9. [安全防护规范 (配置写入限制)](#9-安全防护规范-配置写入限制)
10. [加载、测试与热重载](#10-加载测试与热重载)
11. [常见问题与调试排查](#11-常见问题与调试排查)

---

## 1. Mod 体系与两层架构

EnderBridge 的 Mod 就是一个标准的 Python 模块，模块内**必须导出一个名为 `Mod` 的类**（框架通过 `getattr(module, "Mod")` 动态获取）。

EnderBridge 区分两种类型的 Mod：

| 类型 | 配置注册键 | 实例化时机与生命周期 | 典型应用场景 |
|:---:|:---:|---|---|
| **客户端 Mod**<br/>(Client Mod) | `mods.client` | 每一个 WebSocket 连接建立时单独实例化一份 (`Mod(client)`)，连接断开时销毁 | 游戏内命令交互、玩家对话、坐标标记、建筑生成、音乐播放、假人控制 |
| **服务端 Mod**<br/>(Server Mod) | `mods.server` | 服务启动时静态实例化一份 (`Mod()`)，随服务器主进程常驻 | 终端交互、全局守护、定时扫描、压力测试、后台监控 |

### 客户端 Mod 的生命周期钩子

全部钩子均为**可选实现**，框架调用时会自动进行存在性与异步检查：

- `__init__(self, client)`：构造函数，接收当前连接的 `ClientConnection` 实例对象。
- `onStart(self)` 或 `start(self)`：在基础设施（日志器、存储、事件、SAPI）注入完毕后立即触发。
- `onCommand(self)`：**声明并返回命令映射表**（命令分级字典，见第 4 节）。
- `onPocket(self, packet)`：接收原始 WebSocket 数据包回调（多数高级交互通过 `Utils` 事件监听，此钩子通常留空）。
- `onDestroy(self)` 或 `destroy(self)`：在玩家断开连接或 Mod 热重载时触发，用于清理异步任务或定时器。

框架在实例化后会自动为 Mod 对象注入以下属性：

| 注入属性 | 类型 | 说明 |
|---|---|---|
| `self.client` | `ClientConnection` | 当前游戏客户端连接，提供全部游戏通信方法 |
| `self.modName` | `str` | 该 Mod 在 `config.json` 中的注册名称（键名） |
| `self.logger` | `ModLogger` | 专属独立日志器（自动标注 `Client:<Mod名>`） |
| `self.storage` | `StorageManager` | 玩家专属的持久化键值存储空间 |
| `self.sapi` | `_ModSAPIHandle` | SAPI 轮询句柄（用于接收与发送 SAPI 数据包） |
| `self.on(event, cb)` | `callable` | 订阅客户端事件（链路隔离） |
| `self.emit(event, data)` | `callable` | 发送客户端事件 |
| `self.off(event)` | `callable` | 取消客户端事件订阅 |

---

## 2. Mod 的注册与配置方式

配置文件位于 `config/config.json`，在 `"mods"` 节点中进行注册：

```json
{
  "mods": {
    "client": {
      "AI": "mod.ai",
      "Tool": "mod.tool",
      "MyMod": "mod.mymod"
    },
    "server": {
      "chat": "mod.read",
      "spam": "mod.spam"
    }
  }
}
```

- **键名**（如 `"MyMod"`）：Mod 的显示名称与标识。
- **值**（如 `"mod.mymod"`）：Python 模块路径（对应 `mod/mymod.py`）。
- **子目录支持**：支持放置在子目录包中，如 `mod/mypackage/main.py` 对应 `"mod.mypackage.main"`（可参考内置的 `mod.ezmatic.main`）。

> 💡 你也可以在 Web 管理面板的「Mod 管理」页面直接上传 `.py` 文件并在线激活！

---

## 3. 编写你的第一个客户端 Mod

在 `mod/` 目录下创建文件 `mod/mymod.py`：

```python
"""我的第一个 EnderBridge Mod: 打招呼与坐标广播"""
import asyncio
from lib.command import Command
from lib.permission import PermissionManager


class Mod:
    """自定义客户端 Mod"""

    # 子方法元数据表: (方法名, 参数提示, 描述, 所需权限等级)
    MY_METHODS = [
        ("hello", "<名字>", "向指定玩家打招呼", 0),
        ("where", "", "查询自己当前的三维坐标", 0),
        ("alert", "<内容>", "全服广播消息 (需 OP 权限)", 2),
    ]

    def __init__(self, client):
        self.client = client

    def onStart(self):
        self.logger.info("MyMod 模组初始化完毕！")

    def onCommand(self):
        """返回命令映射表: 单入口命令统一注册在 normal 等级中，由内部进行方法分派"""
        return {
            "normal": [
                Command.create("mymod", "我的示例模组 (方法: hello/where/alert)")
                .add_string("方法", False)
                .add_optional_string("参数1")
                .add_optional_string("参数2")
                .add_optional_string("参数3")
                .set_func(self._cmd_dispatch),
            ],
        }

    async def _cmd_dispatch(self, sender, method, p1=None, p2=None, p3=None):
        # 1. 帮助说明
        if method == "help":
            lines = "\n".join(
                f"§a{Command.command_prefix}mymod {name} {args} §7- §f{desc}"
                for name, args, desc, _ in self.MY_METHODS
            )
            await self.client.tell(f"§eMyMod 帮助列表:\n{lines}", sender)
            return

        # 2. 打招呼
        if method == "hello":
            target = p1 or sender
            await self.client.tell(f"§a你好，§b{target}§a！欢迎来到基岩版服务器！", sender)

        # 3. 获取坐标
        elif method == "where":
            pos = await self.client.getPosition(sender)
            if not pos:
                await self.client.tell("§c未能获取到玩家位置，请确认玩家是否在线", sender)
                return
            await self.client.tell(
                f"§e当前坐标: §fX={pos['x']:.1f}, Y={pos['y']:.1f}, Z={pos['z']:.1f}", sender
            )

        # 4. 全服广播 (需要 OP 权限校验)
        elif method == "alert":
            perm = await PermissionManager.query(sender)
            if perm < 2:
                await self.client.tell("§c权限受限：该方法需要 OP 及以上权限！", sender)
                return
            if not p1:
                await self.client.tell("§c参数不足：用法 $mymod alert <内容>", sender)
                return
            await self.client.tellAll(f"§6[全服公告] §f{p1}")

        else:
            await self.client.tell(
                f"§c未知子方法: {method}，请输入 $mymod help 查看帮助", sender
            )
```

在 `config/config.json` 中添加 `"MyMod": "mod.mymod"`，保存后在游戏内输入：
- `$mymod hello Steve`
- `$mymod where`
- `$mymod alert 欢迎各位新玩家！`
- `$mymod help`

---

## 4. 命令系统设计 (Command 框架)

EnderBridge 的命令系统由 `lib/command.py` 提供，支持**链式调用声明**与**双引号参数解析**：

```python
Command.create("命令名", "命令描述")
    .add_string("必选参数", False)
    .add_optional_string("可选参数")
    .add_integer("整数参数", False)
    .add_optional_integer("可选整数")
    .add_enum(["模式A", "模式B"], "模式", False)
    .set_func(self._handler)
```

### 4.1 参数规则与约束
- **可选参数排后**：所有必选参数声明完毕后，方可声明可选参数 (`add_optional_*`)。
- **带空格字符串**：支持通过双引号包裹输入含空格的完整语句，例如 `$mymod hello "Steve Jobs"`。
- **动态前缀**：前缀从 `config.json` 中的 `commandPrefix`（默认 `$`）读取；支持在游戏内动态响应。

### 4.2 权限字典分类 (`onCommand`)
`onCommand` 返回的字典键名代表命令所需的最低权限级别：
- `"normal"`：所有玩家均可使用；
- `"user"`：User 及以上可用（权限值 $\ge 1$）；
- `"op"`：OP 及以上可用（权限值 $\ge 2$）；
- `"owner"`：仅服主可用（权限值 $\ge 3$）。

---

## 5. 常用 API 工具箱 (Utils & Client)

在 Mod 中通过 `self.client` 可以调用所有游戏控制与通信接口：

### 5.1 指令执行
```python
# 1. 异步发送命令并等待结果返回 (默认 10 秒超时)
result = await self.client.runCommand("time set day", timeout=5000)

# 2. 静默发送命令 (不等待回包)
await self.client.sendCommand("weather clear")

# 3. 安全带长度校验发送 (>461 字节自动拦截防踢出)
await self.client.sendCommandWithCheck("fill 0 0 0 10 10 10 stone")
```

### 5.2 消息通知与广播
```python
# 单发给指定玩家 (支持 Minecraft 样式代码 §)
await self.client.tell("§a个人消息", target="Steve")

# 全服广播
await self.client.tellAll("§e全服公告消息")
```

### 5.3 世界数据获取
```python
pos = await self.client.getPosition("@s")     # 返回 {"x": 100.0, "y": 64.0, "z": 200.0}
loc = await self.client.getLocation("@s")     # 返回坐标及 dimension 维度信息
dim = await self.client.getDimension("@s")    # 获取所在维度 (overworld/nether/the_end)
inv = await self.client.getInventory("@s")    # 物品栏信息
```

### 5.4 订阅 WebSocket 游戏事件流
```python
def on_player_chat(data):
    body = data.get("body", {})
    sender = body.get("sender")
    message = body.get("message")
    self.logger.info(f"收到玩家发言: {sender}: {message}")

# 建议传入 owner=self.modName，在 Mod 热重载时会自动卸载订阅，防止内存泄漏
self.client.subscribe("PlayerMessage", on_player_chat, owner=self.modName)
self.client.unsubscribe("PlayerMessage", owner=self.modName)
```

常用游戏事件名：`PlayerMessage`、`BlockPlaced`、`BlockBroken`、`ItemUsed`、`CameraUsed`。

---

## 6. 事件总线与通信 (EventBus)

### 6.1 实例级事件 (`self.on` / `self.emit`)
用于在同一客户端连接内部的客户端 Mod 与服务端 Mod 之间解耦通信：
```python
# 发送事件
self.emit("custom_event", {"status": "ok"})

# 监听事件
self.on("custom_event", lambda data: print(data))
```

### 6.2 全局事件总线 (`lib.mods.event_bus`)
跨越不同客户端连接或全局服务之间通信：
```python
from lib.mods import event_bus

event_bus.on("global_notice", "MyMod", callback)
event_bus.emit("global_notice", {"msg": "hello"})
event_bus.clear_mod("MyMod")
```

---

## 7. 持久化存储 (StorageManager)

框架为每个 Mod 自动分配了隔离的持久化键值存储空间（存放在 `StorageManager`）：
```python
# 写入数据 (自动持久化到本地独立 JSON)
self.storage.set("home_pos", {"x": 100, "y": 64, "z": 200})

# 读取数据 (支持缺省默认值)
home = self.storage.get("home_pos", default=None)
```

---

## 8. 编写服务端 Mod

服务端 Mod 不需要参数即可实例化，用于驻留后台、监听网络或维护定时器：

```python
"""mod/myserver.py —— 服务端后台 Mod"""
import asyncio
from lib.command import Command
from lib.current import Current


class Mod:
    def __init__(self):
        self._task = None

    def start(self):
        """服务加载后调用，拉起后台协程"""
        self._task = asyncio.get_running_loop().create_task(self._background_loop())

    async def _background_loop(self):
        while True:
            await asyncio.sleep(300)
            client = Current.client
            if client:
                await client.tellAll("§7[系统] 服务器稳定运行中...")

    def onClientConnect(self, client, is_main):
        if is_main:
            print("[MyServer] 主客户端已连接！")

    def onMainClientDisconnect(self):
        print("[MyServer] 主客户端断开连接！")

    def onDestroy(self):
        if self._task:
            self._task.cancel()

    # 注册终端指令 (控制台直接输入触发)
    commands = {
        "normal": [
            Command.create("myserver", "服务端模组指令")
            .set_func(lambda _: print("MyServer 正在运行")),
        ]
    }
```

注册到 `config.json` 的 `"mods.server"`：
```json
"MyServer": "mod.myserver"
```

---

## 9. 安全防护规范 (配置写入限制)

EnderBridge v1.1.0+ 引入了**操作系统级文件锁**与 **PEP 578 审计守卫**：
- 严禁任何 Mod 直接使用 `open("config/config.json", "w")` 或 `os.replace` 试图修改核心配置；
- 第三方未经授权的 Mod 尝试触碰核心配置文件时，会被底层安全守卫直接抛出 `PermissionError` 阻断；
- 若 Mod 拥有受信任的专属配置项（如 Bot Mod 的 `botConfig`），必须通过框架专有的安全通道写入：

```python
from lib.mods import save_mod_config

# 只有经过系统白名单授权的 Mod 名称与字段才能成功写入
ok = save_mod_config("bot", {"username": "NewBotName"})
```

---

## 10. 加载、测试与热重载

### 10.1 游戏内与控制台热重载
无需重启 EnderBridge 服务进程：
- **客户端 Mod 热重载**：执行 `$tool reload <Mod名>`（或 `$tool reload` 重载全部）。系统会自动执行旧实例的 `onDestroy`、卸载事件订阅、绕过 Python 缓存重新导入模块并重新实例化。
- **WebUI 面板重载**：在 WebUI 的「Mod 管理」页面点击对应模组的「重载」按钮。
- **脱机控制台重载**：在 WebUI 控制台或桌面客户端直接输入 `$tool reload MyMod`。

### 10.2 调试技巧
- 启动时推荐带 `-B` 参数防止 `.pyc` 干扰：`python -B main.py`。
- 查看详细日志：`logs/` 目录下按日期自动记录每个 Mod 的异常堆栈。

---

## 11. 常见问题与调试排查

**Q：Mod 加载报错 "Client Mod xxx 加载失败: module has no attribute 'Mod'"**
模块内缺少导出的 `Mod` 类，请确保类名大小写完全一致为 `class Mod:`。

**Q：命令输入后没有反应？**
1. 检查游戏内命令前缀是否与 `config.json` 中的 `commandPrefix` 一致（默认 `$`）；
2. 检查命令是否注册在 `onCommand` 返回的正确权限分组中；
3. 检查控制台是否有参数解析错误或异常报错日志。

**Q：Mod 能否在没有 MCBE 客户端连接时由控制台执行？**
可以！只要在 Mod 类中声明类属性 `terminal_compatible = True`（如内置的 `Bot` 模组），EnderBridge 控制台调度器就会自动支持在脱机无连接时直接执行其命令。

---

*EnderBridge · 模组开发者开发参考*
