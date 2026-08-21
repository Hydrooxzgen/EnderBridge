"""权限管理类

基于 JSON 文件的权限系统,支持 blocker/user/op/owner 四级权限的增删查改。
使用缓存机制避免频繁读取磁盘。
"""
import json
import os
from copy import deepcopy

# 项目根目录(本文件位于 lib/ 下)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERMISSION_PATH = os.path.join(_PROJECT_ROOT, "permission.json")
TEMP_PATH = os.path.join(_PROJECT_ROOT, "permission.json.tmp")


class PermissionManager:
    """权限管理类(全部为类级静态方法)"""

    # 权限缓存(避免每次查询都读取磁盘)
    _cache = None

    @classmethod
    async def get(cls, object_: str = "all"):
        """读取权限配置

        object_: "all" 返回完整配置,"blocker"/"user"/"op"/"owner" 返回对应列表
        Raises:
            ValueError: 对象参数非法
        """
        # 缓存命中时直接使用,避免重复读取磁盘
        if cls._cache is None:
            with open(PERMISSION_PATH, "r", encoding="utf-8") as f:
                cls._cache = json.load(f)

        permission = cls._cache

        if object_ == "all":
            return permission

        if object_ not in ("owner", "op", "user", "blocker"):
            raise ValueError("非法对象")

        return permission.get(object_)

    @classmethod
    async def set(cls, new_permission: dict):
        """写入完整权限配置,成功返回 True,失败返回 Error"""
        try:
            # 先写入临时文件再原子替换,避免进程中断导致原文件损坏
            with open(TEMP_PATH, "w", encoding="utf-8") as f:
                json.dump(new_permission, f, ensure_ascii=False, indent=2)
            os.replace(TEMP_PATH, PERMISSION_PATH)
            # 写入后清除缓存,下次读取重新加载
            cls._cache = None
            return True
        except Exception as error:
            return error

    @classmethod
    async def add(cls, object_: str, value: str):
        """向指定权限组添加成员,成功返回 True,失败返回 Error"""
        try:
            if object_ not in ("op", "user", "blocker"):
                raise ValueError("非法对象")

            permission = deepcopy(await cls.get())

            # 确保目标组为数组
            if not isinstance(permission.get(object_), list):
                permission[object_] = []

            # 已存在则直接返回
            if value in permission[object_]:
                return True

            permission[object_].append(value)
            result = await cls.set(permission)
            if isinstance(result, Exception):
                raise result
            return True
        except Exception as error:
            return error

    @classmethod
    async def remove(cls, object_: str, value: str):
        """从指定权限组移除成员,成功返回 True,失败返回 Error"""
        try:
            if object_ not in ("op", "user", "blocker"):
                raise ValueError("非法对象")

            permission = deepcopy(await cls.get())

            if not isinstance(permission.get(object_), list):
                permission[object_] = []

            # 过滤掉目标成员
            permission[object_] = [item for item in permission[object_] if item != value]

            result = await cls.set(permission)
            if isinstance(result, Exception):
                raise result
            return True
        except Exception as error:
            return error

    @classmethod
    async def query(cls, queried: str):
        """查询成员权限等级

        按 owner > blocker > op > user > normal 优先级返回最高权限:
        -1 - blocker / 0 - normal / 1 - user / 2 - op / 3 - owner
        """
        try:
            permission = await cls.get()

            if permission.get("owner") == queried:
                return 3

            if queried in (permission.get("blocker") or []):
                return -1

            if queried in (permission.get("op") or []):
                return 2

            if queried in (permission.get("user") or []):
                return 1

            return 0
        except Exception as e:
            return Exception(str(e))
