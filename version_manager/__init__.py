"""版本管理器 - 集中管理配置格式的升级/降级逻辑"""

from .detector import detect_version, get_config_format, compare_versions
from .migrator import migrate, MIGRATIONS

__all__ = [
    "detect_version",
    "get_config_format",
    "compare_versions",
    "migrate",
    "MIGRATIONS",
]
