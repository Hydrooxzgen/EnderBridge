"""共享实例模块

提供应用主日志实例与消息日志实例。
"""
from lib.logger import Logger

# 应用主日志实例
logger = Logger()

# 消息日志实例 - 用于记录玩家聊天消息
message_logger = Logger("message")
