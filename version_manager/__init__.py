# Author: Hydrooxzgen
# Github: https://github.com/Hydrooxzgen
# This project uses the GPL-3.0 license, you can modify/distribute this project according to the GPL-3.0 license
"""版本管理器 - 集中管理配置格式的升级/降级逻辑"""

from . import package
from .detector import detect_version, get_config_format, compare_versions
from .migrator import migrate, MIGRATIONS

__all__ = [
    "detect_version",
    "get_config_format",
    "compare_versions",
    "migrate",
    "MIGRATIONS",
    "package",
]
