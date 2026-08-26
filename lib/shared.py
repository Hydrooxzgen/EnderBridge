"""共享实例模块

提供应用主日志实例与消息日志实例。
"""
from lib.logger import Logger

# 应用主日志实例
logger = Logger()

# 消息日志实例 - 用于记录玩家聊天消息
message_logger = Logger("message")

# 主程序状态引用(main.py 启动后注入,供 lib/mods.py 等模块访问,避免循环导入)
start_time: float = 0        # 服务器启动时刻
connections_ref: set = None  # 活跃连接集合的引用

# Bot Shell 模式状态
bot_shell_mode: bool = False        # 是否处于 Bot Shell 交互模式
bot_shell_queue = None              # asyncio.Queue — Shell 输入队列
