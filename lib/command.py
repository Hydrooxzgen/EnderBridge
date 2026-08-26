"""命令框架类

提供声明式的命令定义和执行框架,支持多种参数类型和链式调用。
"""
import asyncio
import re
import time


def _load_config():
    """从 config.py 读取命令前缀与限流配置(强制重新加载,确保 WebUI 保存后生效)

    使用 importlib.reload 强制重新执行 config.py,绕过 Python 模块缓存。
    """
    import importlib
    try:
        import config
        importlib.reload(config)
        command_prefix = getattr(config, "commandPrefix", None) or getattr(config, "command_prefix", "$")
        rate_limit = getattr(config, "rateLimit", None) or getattr(config, "rate_limit", None)
        return command_prefix, rate_limit
    except Exception:
        return "$", None


_PREFIX, _RATE_LIMIT = _load_config()


class Command:
    """命令框架类"""

    # 当前命令前缀(从配置读取)
    command_prefix = _PREFIX

    # 命令限流桶:commander -> {"start": ms, "count": n}
    _rate_buckets: dict = {}

    @classmethod
    def reload_prefix(cls) -> None:
        """从 config.py 重新读取命令前缀(热重启/配置保存后调用)"""
        prefix, _ = _load_config()
        cls.command_prefix = prefix

    @classmethod
    def _check_rate_limit(cls, commander: str) -> bool:
        """按玩家名进行命令限流检查(基于 config.rate_limit.command)"""
        cfg = None
        try:
            # 配置文件中为驼峰命名 rateLimit,兼容下划线写法
            try:
                from config import rateLimit as rate_limit
            except ImportError:
                from config import rate_limit
            cfg = (rate_limit or {}).get("command")
        except Exception:
            cfg = None
        if not cfg or not cfg.get("enabled"):
            return True

        now = time.time() * 1000
        bucket = cls._rate_buckets.get(commander)
        if not bucket or now - bucket["start"] >= cfg.get("windowMs", 0):
            bucket = {"start": now, "count": 0}
            cls._rate_buckets[commander] = bucket
        if bucket["count"] >= cfg.get("maxPerWindow", 0):
            return False
        bucket["count"] += 1
        return True

    @classmethod
    def set_command_prefix(cls, text: str) -> bool:
        """动态设置命令前缀(不能包含空格)"""
        if " " in text:
            return False
        cls.command_prefix = text
        return True

    @staticmethod
    def parse_args(input_: str) -> list:
        """解析命令参数字符串,支持双引号包裹的含空格参数

        Raises:
            ValueError: 双引号未闭合时抛出
        """
        tokens = []
        cur = ""
        in_quote = False
        for ch in input_:
            if ch == '"':
                if in_quote:
                    tokens.append(cur)
                    cur = ""
                in_quote = not in_quote
            elif not in_quote and ch == " ":
                if cur:
                    tokens.append(cur)
                    cur = ""
            else:
                cur += ch
        if cur:
            tokens.append(cur)
        if in_quote:
            raise ValueError("未闭合的双引号")
        return tokens

    @classmethod
    def create(cls, name: str, description: str = None) -> "Command":
        """创建命令实例的静态工厂方法"""
        return cls(name, description)

    def __init__(self, name: str, description: str = None):
        self.name = name
        self.description = description
        self.parameters = []  # [type, description, optional]
        self.func = None
        # 异步执行出错时的回调(由调用方注入,用于向用户反馈错误)
        self.on_error = None

    # ---- 参数添加(链式) ----

    def _add_parameter(self, param: list) -> None:
        """内部方法:添加参数到参数列表,确保可选参数在必选参数之后"""
        optional = param[2]
        if not optional:
            if any(p[2] for p in self.parameters):
                raise ValueError("必选参数不能放在可选参数之后")
        self.parameters.append(param)

    def add_boolean(self, description: str = None, optional: bool = False) -> "Command":
        self._add_parameter(["Boolean", description, optional])
        return self

    def add_string(self, description: str = None, optional: bool = False) -> "Command":
        self._add_parameter(["String", description, optional])
        return self

    def add_integer(self, description: str = None, optional: bool = False) -> "Command":
        self._add_parameter(["Integer", description, optional])
        return self

    def add_float(self, description: str = None, optional: bool = False) -> "Command":
        self._add_parameter(["Float", description, optional])
        return self

    def add_enum(self, e: list, description: str = None, optional: bool = False) -> "Command":
        if not isinstance(e, (list, tuple)):
            return self
        self._add_parameter([list(e), description, optional])
        return self

    def add(self, type_: str, description: str = None, optional: bool = False) -> "Command":
        self._add_parameter([type_, description, optional])
        return self

    def add_optional_boolean(self, description: str = None) -> "Command":
        return self.add_boolean(description, True)

    def add_optional_string(self, description: str = None) -> "Command":
        return self.add_string(description, True)

    def add_optional_integer(self, description: str = None) -> "Command":
        return self.add_integer(description, True)

    def add_optional_float(self, description: str = None) -> "Command":
        return self.add_float(description, True)

    def add_optional_enum(self, e: list, description: str = None) -> "Command":
        return self.add_enum(e, description, True)

    def add_optional(self, type_: str, description: str = None) -> "Command":
        return self.add(type_, description, True)

    def set_func(self, func) -> "Command":
        """设置命令执行函数"""
        self.func = func
        return self

    # ---- 执行 ----

    def execute(self, commander: str, text: str):
        """执行命令

        Returns:
            成功: {"status": True, "message": result_list}
            参数错误: {"status": False, "message": 错误信息}
            命令名称不匹配: False
        """
        # 命令限流检查
        if not Command._check_rate_limit(commander):
            return {"status": False, "message": "命令过于频繁，请稍后再试"}

        try:
            text_list = Command.parse_args(text)
        except ValueError as e:
            return {"status": False, "message": str(e)}

        # 校验命令名称是否匹配
        if text_list[0] != f"{Command.command_prefix}{self.name}":
            return False

        # 计算必选参数和可选参数数量
        required_count = sum(1 for p in self.parameters if not p[2])
        total_count = len(self.parameters)
        provided_args = len(text_list) - 1  # 减去命令名称

        if provided_args < required_count or provided_args > total_count:
            return {
                "status": False,
                "message": f"参数数量错误：需要 {required_count}-{total_count} 个参数，但提供了 {provided_args} 个",
            }

        result_list = []

        # 逐个解析并校验参数类型
        for i, (now_type, _desc, optional) in enumerate(self.parameters):
            now_text = text_list[i + 1] if i + 1 < len(text_list) else None

            # 可选参数且未提供值 → None(对应 JS undefined)
            if optional and now_text is None:
                result_list.append(None)
                continue

            # 枚举类型校验
            if isinstance(now_type, list):
                if now_text not in now_type:
                    return {
                        "status": False,
                        "message": f'"{now_text}" 处应为枚举 {", ".join(str(x) for x in now_type)}',
                    }
                result_list.append(now_text)
                continue

            if not isinstance(now_type, str):
                return {"status": False, "message": "未知错误"}

            # 基础类型校验
            if now_type == "Boolean":
                if now_text not in ("true", "false"):
                    return {"status": False, "message": f'"{now_text}" 处应为布尔型'}
                result_list.append(now_text == "true")

            elif now_type == "String":
                result_list.append(now_text)

            elif now_type == "Integer":
                # 严格整数:拒绝科学计数法/Infinity 等格式
                if not re.fullmatch(r"-?\d+", now_text):
                    return {"status": False, "message": f'"{now_text}" 处应为整型'}
                result_list.append(int(now_text))

            elif now_type == "Float":
                # 严格浮点:拒绝 Infinity / NaN 等非法格式
                if not re.fullmatch(r"-?\d*\.?\d+(?:e[+-]?\d+)?", now_text, re.IGNORECASE):
                    return {"status": False, "message": f'"{now_text}" 处应为浮点型'}
                num = float(now_text)
                if num != num or num in (float("inf"), float("-inf")):
                    return {"status": False, "message": f'"{now_text}" 处应为浮点型'}
                result_list.append(num)

            else:
                # 未知/自定义类型:原样透传文本
                result_list.append(now_text)

        # 调用命令执行函数
        if self.func is not None:
            try:
                ret = self.func(commander, *result_list)
                # 异步命令函数(协程)出错时捕获,避免静默失败
                if asyncio.iscoroutine(ret):
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None
                    if loop is not None:
                        task = loop.create_task(ret)
                        task.add_done_callback(self._on_task_done)
                    else:
                        # 无运行中的事件循环:仅记录
                        asyncio.get_event_loop().run_until_complete(ret)
            except Exception as e:
                return {"status": False, "message": str(e)}

        return {"status": True, "message": result_list}

    def _on_task_done(self, task) -> None:
        """协程任务完成回调:捕获异常并通知 on_error"""
        try:
            task.result()
        except Exception as e:
            if self.on_error:
                self.on_error(e)
