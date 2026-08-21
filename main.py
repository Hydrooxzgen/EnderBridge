"""程序入口

包含:依赖自愈引导、--reset-all 重置、-set 手动配置向导、config 自动生成、
首次运行向导、WebSocket 服务器、连接生命周期(1 秒延迟初始化)与正常关闭流程。
"""
import asyncio
import json
import os
import re
import subprocess
import sys
from uuid import uuid4

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PY = os.path.join(ROOT, "config.py")
CONFIG_EXAMPLE = os.path.join(ROOT, "config.example.py")
WANT_RESET = "--reset-all" in sys.argv
WANT_SETUP = "-set" in sys.argv or "--set" in sys.argv

# ===== 依赖检测(必须早于任何第三方模块使用) =====
# websockets 使用动态导入:缺失时自动运行 setup.py 安装,成功后继续启动。
def _dependencies_ok() -> bool:
    try:
        import websockets  # noqa: F401
        return True
    except ImportError:
        return False


def _run_setup() -> None:
    print("========================================")
    print("  检测到缺少依赖，正在运行 setup.py 安装依赖...")
    print("========================================")
    res = subprocess.run([sys.executable, "setup.py"], cwd=ROOT)
    if res.returncode != 0:
        print("依赖安装失败，请手动运行 python setup.py 排查")
        sys.exit(1)
    # 安装成功后重新尝试导入
    try:
        import websockets  # noqa: F401
    except ImportError as e:
        print(f"依赖安装后仍无法加载: {e}")
        sys.exit(1)


if not _dependencies_ok():
    _run_setup()

# ===== 引导阶段(必须早于任何依赖 config.py 的模块加载) =====
# 依赖 config.py 的模块(lib/logger.py、lib/utils.py、lib/mods.py 等)均为延迟加载,
# 因此 config.py 缺失时(如 --reset-all 之后)可先在此根据模板自动补全,保证程序可启动。
if not WANT_RESET and not os.path.exists(CONFIG_PY):
    with open(CONFIG_EXAMPLE, "r", encoding="utf-8") as f:
        tpl = f.read()
    # config.py 只存真实配置:剔除模板携带的 isFirstRun 标记块
    cfg = re.sub(
        r"# ===== 首次运行 =====[\s\S]*?is_first_run = (True|False)\r?\n(\r?\n)?",
        "",
        tpl,
    )
    with open(CONFIG_PY, "w", encoding="utf-8") as f:
        f.write(cfg)
    print("未找到 config.py，已根据模板自动生成默认配置（可在向导中修改）")

# permission.json 缺失时从模板复制(权限系统依赖该文件)
PERMISSION_JSON = os.path.join(ROOT, "permission.json")
PERMISSION_EXAMPLE = os.path.join(ROOT, "permission.example.json")
if not WANT_RESET and not os.path.exists(PERMISSION_JSON) and os.path.exists(PERMISSION_EXAMPLE):
    with open(PERMISSION_EXAMPLE, "r", encoding="utf-8") as f:
        content = f.read()
    with open(PERMISSION_JSON, "w", encoding="utf-8") as f:
        f.write(content)
    print("未找到 permission.json，已根据模板自动生成默认权限配置")

# ===== 一键重置:python main.py --reset-all =====
# 清除所有配置文件(不启动服务器),并将模板 config.example.py 的 is_first_run 复位为 True
if WANT_RESET:
    files = ["config.py", "config.py.bak", "permission.json", "permission.json.bak"]
    removed = []
    for name in files:
        p = os.path.join(ROOT, name)
        if os.path.exists(p):
            os.remove(p)
            removed.append(name)
    # 复位模板标记,下次启动自动进入向导重新配置
    try:
        with open(CONFIG_EXAMPLE, "r", encoding="utf-8") as f:
            src = f.read()
        next_ = re.sub(r"is_first_run = (True|False)", "is_first_run = True", src)
        if next_ != src:
            with open(CONFIG_EXAMPLE, "w", encoding="utf-8") as f:
                f.write(next_)
    except Exception:
        # 模板不可写时静默忽略
        pass
    print("========================================")
    print("  配置已重置")
    print("========================================")
    sys.exit(0)

# 确保项目根目录可导入
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ===== 资源目录自愈:确保默认资源目录存在 =====
# basePath(music/mcfunc/ezmatic/image)与 ezmatic 导出目录 structures
# 缺失时自动创建,避免首次运行找不到目录(如投影目录 resources/ezmatic)。
try:
    from config import basePath, resolvePath
    _resource_dirs = [resolvePath(d) for d in list(basePath.values())]
except Exception:
    _resource_dirs = [
        "./resources/midi",
        "./resources/mcfunc",
        "./resources/ezmatic",
        "./resources/pictures",
    ]
_resource_dirs.append(resolvePath("./structures"))  # ezmatic 导出目录
for _d in _resource_dirs:
    try:
        os.makedirs(_d, exist_ok=True)
    except OSError:
        pass

# ===== 动态加载依赖 config.py 的本地模块(此时 config.py 必然已存在) =====
from lib import shared
from lib.logger import close_log_streams
from lib.utils import ClientConnection, Utils
from lib.current import Current
from lib.mods import ClientModManager, ServerModManager
from config import wsConfig

# 根目录同时存在 config.py 时,config 会被当作普通模块而非包,无法用
# "from config.example import ..." 导入,这里改为读取模板文件提取标记。
with open(CONFIG_EXAMPLE, "r", encoding="utf-8") as f:
    _example_src = f.read()
_m = re.search(r"is_first_run = (True|False)", _example_src)
is_first_run = _m is not None and _m.group(1) == "True"

# 首次运行检查:is_first_run 为 True(或指定 -set/--set 手动配置)时启动图形化配置向导
if is_first_run or WANT_SETUP:
    if WANT_SETUP:
        shared.logger.info("检测到 -set 参数，启动图形化配置向导...")
    else:
        shared.logger.info("检测到首次运行，启动图形化配置向导...")
    from lib.setup import start_setup_server
    try:
        asyncio.run(start_setup_server())
        shared.logger.info("配置已保存，请重新启动服务器以应用配置")
    except Exception as error:
        shared.logger.error(f"配置向导异常: {error}")
    close_log_streams()
    sys.exit(0)

# ===== WebSocket 服务器 =====
import websockets
from websockets.protocol import State

# 当前所有连接(含未初始化完成的),用于关闭时统一通知
connections = set()
server = None


async def connection_handler(ws):
    """处理客户端连接"""
    global connections
    # 获取客户端 IP
    client_ip = ws.remote_address[0] if ws.remote_address else "unknown"
    shared.logger.info(f"客户端 {client_ip} 已连接")

    # 分配唯一 ID,用于客户端 Mod 存储和事件总线隔离
    conn = ClientConnection(ws)
    conn.id = str(uuid4())
    connections.add(conn)

    client_mod = None
    initialized = False

    # 消息接收循环(初始化完成前忽略客户端消息,与 JS 一致)
    async def message_loop():
        nonlocal client_mod, initialized
        async for message in ws:
            if not initialized or conn.utils is None:
                continue
            # 仅 JSON 解析需捕获,非 JSON 消息直接忽略
            try:
                text = message.decode("utf-8") if isinstance(message, bytes) else str(message)
                data = json.loads(text)
            except Exception:
                continue
            # 将消息解析为 JSON 后分发给工具类处理
            conn.utils.onMessage(data)
            # 通知客户端 Mod 收到消息
            if client_mod:
                client_mod.call_mod_method("onPocket", data)
            # 通知服务端 Mod 收到消息
            ServerModManager.on_message(conn, data)

    msg_task = asyncio.get_running_loop().create_task(message_loop())

    # 延迟初始化:MCBE 客户端建立 WebSocket 连接后需约 1 秒完成内部握手,
    # 若立即发送命令(权限检测 /list、SAPI 检测 /gmsg、订阅、欢迎消息等),
    # 客户端会主动断开并重连(表现为"每次启动都要断开一次才能连上")。
    try:
        await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        msg_task.cancel()
        connections.discard(conn)
        return

    # 延迟期间客户端可能已断开,检查连接状态
    if ws.state != State.OPEN:
        msg_task.cancel()
        connections.discard(conn)
        return

    # 为当前客户端绑定工具方法(runCommand, subscribe, tell 等)
    conn.utils = Utils(conn)

    # 记录第一个连接的客户端为主客户端
    is_main_client = Current.client is None
    if is_main_client:
        Current.client = conn
        shared.logger.info("主客户端已连接")

    # 实例化客户端 Mod,注入当前连接
    client_mod = ClientModManager(conn)
    conn.clientMod = client_mod
    Current.client_mods[conn] = client_mod

    # 通知服务端 Mod 客户端已连接
    ServerModManager.on_client_connect(conn, is_main_client)

    # 广播连接通知
    conn.tell(f"§e{wsConfig.get('name', 'starws')} | §fSystem > §i已连接")
    initialized = True

    # 等待消息循环结束(连接关闭)
    try:
        await msg_task
    except asyncio.CancelledError:
        pass
    except websockets.exceptions.WebSocketException:
        # 客户端断开(含 MCBE 非标准关闭导致的无 close frame 协议错误 1002),
        # 属正常连接结束,无需记录为错误
        pass
    except Exception as e:
        shared.logger.error(f"消息循环异常: {e}")

    # ===== 客户端断开连接 =====
    connections.discard(conn)
    shared.logger.info(f"客户端 {client_ip} 连接已关闭")

    # 通知服务端 Mod 客户端已断开连接
    ServerModManager.on_client_disconnect(conn, conn is Current.client)

    # 若为主客户端断开,重置主客户端状态
    if conn is Current.client:
        Current.reset()
        shared.logger.info("主客户端连接已关闭")

    # 销毁该客户端的所有 Mod 实例
    Current.client_mods.pop(conn, None)
    if client_mod:
        client_mod.destroy()

    # 清理工具类回调映射,防止内存泄漏
    if conn.utils is not None:
        conn.utils.destroy()


# ===== 主入口 =====
async def main():
    global server
    host = wsConfig.get("host") or None  # None = 监听所有接口
    port = wsConfig.get("port", 8800)

    # 创建 WebSocket 服务端
    server = await websockets.serve(connection_handler, host, port)

    # 加载服务端 Mod 和客户端 Mod 的静态定义
    await ServerModManager.load()
    await ClientModManager.load()
    shared.logger.info("服务器已启动")

    try:
        # 运行直到收到信号
        await asyncio.Future()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await destroy()


# ===== 关闭函数 =====
# 依次销毁 Mod、关闭 WebSocket 服务端
# 防重入:重复调用直接忽略
destroying = False


async def destroy():
    global destroying
    if destroying:
        return
    destroying = True

    shared.logger.info("正在关闭服务端 Mod...")
    ServerModManager.destroy()
    shared.logger.info("服务端 Mod 已关闭")

    shared.logger.info("正在通知客户端断开连接...")
    for client in list(connections):
        client.tell(f"§c{wsConfig.get('name', 'starws')} | §fSystem > §i已关闭连接")
        try:
            await client.runCommand("/closewebsocket")
        except Exception:
            pass
        await client.close()
    shared.logger.info("客户端通知已完成")

    shared.logger.info("正在关闭服务器...")
    try:
        server.close()
        await asyncio.wait_for(server.wait_closed(), timeout=10)
        shared.logger.info("服务器已关闭")
    except Exception:
        shared.logger.warning("服务器关闭异常，正在强制退出")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        close_log_streams()
        shared.logger.info("程序进程结束")
