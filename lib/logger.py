"""日志模块

提供分级日志输出(控制台 + 文件),支持颜色高亮与日志文件自动创建。
"""
import os
import sys
from datetime import datetime, timezone, timedelta

# 日志输出目录
LOG_DIR = "./logs"

# 日志等级数值映射(数字越大越严重)
LOG_LEVELS = {
    "debug": 0,
    "info": 1,
    "warning": 2,
    "error": 3,
}

# 延迟导入 config(避免循环依赖;与 JS 端动态加载策略一致)
def _get_min_level():
    # 配置文件中为驼峰命名 logLevel,兼容下划线写法 log_level
    try:
        from config import logLevel as log_level
    except ImportError:
        try:
            from config import log_level
        except ImportError:
            return LOG_LEVELS["info"]
    return LOG_LEVELS.get(log_level, LOG_LEVELS["info"])

# 北京时间时区(UTC+8)
BEIJING_TZ = timezone(timedelta(hours=8))


def beijing_time() -> str:
    """获取北京时间字符串,形如 2026-08-07T12:34:56.789+08:00"""
    now = datetime.now(BEIJING_TZ)
    return now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+08:00"


os.makedirs(LOG_DIR, exist_ok=True)

# 日志文件句柄缓存(避免每次写入重新打开)
_log_streams: dict[str, object] = {}

# 控制台输出钩子:main.py 注入,日志写入 stdout 前后调用,用于协调终端提示符显示
_before_console_output = None
_after_console_output = None


def set_console_hooks(before=None, after=None):
    """注册控制台输出钩子(before/after),日志写入 stdout 前后自动调用"""
    global _before_console_output, _after_console_output
    _before_console_output = before
    _after_console_output = after


def get_log_stream(name: str):
    """获取或创建日志文件句柄"""
    if name not in _log_streams:
        log_path = os.path.join(LOG_DIR, f"{name}.log")
        _log_streams[name] = open(log_path, "a", encoding="utf-8")
    return _log_streams[name]


def close_log_streams() -> None:
    """关闭所有日志文件句柄(进程退出前调用,避免丢失缓冲中的日志)"""
    for name in list(_log_streams.keys()):
        try:
            _log_streams[name].flush()
            _log_streams[name].close()
        except Exception:
            pass
        del _log_streams[name]


class Logger:
    """日志工具类

    参数:
        name: 日志名称(用于文件名和前缀)
        ifprint: 是否输出到控制台
        ifile: 是否写入日志文件
    """

    def __init__(self, name: str = "app", ifprint: bool = True, ifile: bool = True):
        self.name = name
        self.print = ifprint
        self.file = ifile

    def log(self, message: str, type_: str = "def") -> None:
        """核心日志方法"""
        allow_types = ["info", "warning", "error", "debug"]

        if type_ in allow_types:
            # 等级过滤:低于配置等级的消息不输出
            if LOG_LEVELS.get(type_, 0) < _get_min_level():
                return
            # 标准格式: [北京时间戳] [类型] 名称 - 消息
            log_message = f"[{beijing_time()}] [{type_}] {self.name} - {message}"
        else:
            log_message = str(message)

        if self.print:
            colors = {
                "info": "\x1b[32m",
                "warning": "\x1b[33m",
                "error": "\x1b[31m",
                "debug": "\x1b[35m",
                "reset": "\x1b[0m",
            }
            color = colors.get(type_, "")
            if _before_console_output:
                _before_console_output()
            sys.stdout.write(f"{color}{log_message}{colors['reset']}\n")
            sys.stdout.flush()
            if _after_console_output:
                _after_console_output()

        # 写入日志文件
        if self.file:
            try:
                stream = get_log_stream(self.name)
                stream.write(log_message + "\n")
                stream.flush()
            except Exception as error:
                print("Log Error: ", error)

    def info(self, message: str) -> None:
        self.log(message, "info")

    def warning(self, message: str) -> None:
        self.log(message, "warning")

    def error(self, message: str) -> None:
        self.log(message, "error")

    def debug(self, message: str) -> None:
        self.log(message, "debug")
