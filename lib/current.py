"""全局状态类

存储当前主客户端引用和全局运行时属性,用于管理全局状态和跨模块通信。
"""


class Current:
    """全局状态类(所有成员均为类级,即全局单例状态)"""

    # 当前主客户端连接实例
    client = None

    # 客户端 Mod 管理器映射 (ws -> ClientModManager)
    client_mods: dict = {}

    # 运行时属性键值存储(如循环定时器 ID 等)
    properties: dict = {}

    @classmethod
    def has(cls, key) -> bool:
        """检查指定属性是否存在且为真值"""
        return bool(cls.properties.get(key))

    @classmethod
    def get(cls, key):
        """获取指定属性值"""
        return cls.properties.get(key)

    @classmethod
    def set(cls, key, value):
        """设置指定属性值,返回设置的值"""
        cls.properties[key] = value
        return value

    @classmethod
    def reset(cls) -> None:
        """重置所有状态(主客户端断开时调用)"""
        cls.client = None
        cls.client_mods.clear()
        cls.properties = {}
