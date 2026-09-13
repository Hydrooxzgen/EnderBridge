"""版本检测 - 识别当前配置格式和版本"""

import json
import re
import os
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).parent.parent
CONFIG_DIR = ROOT / "config"


def parse_version(ver: str) -> tuple:
    """解析版本字符串为元组用于比较

    支持格式: "b0.3.5", "b0.3.5 dev1", "0.3.6", "V0.3.6" 等
    """
    ver = ver.strip().lstrip("bvV")
    parts = ver.split()
    main = parts[0]
    nums = []
    for part in main.split("."):
        try:
            nums.append(int(part))
        except ValueError:
            nums.append(0)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])


def compare_versions(a: str, b: str) -> int:
    """比较两个版本字符串

    返回: -1 (a < b), 0 (a == b), 1 (a > b)
    """
    try:
        ta, tb = parse_version(a), parse_version(b)
        if ta < tb:
            return -1
        elif ta > tb:
            return 1
        return 0
    except Exception:
        return 0


def _read_main_py_version() -> str:
    """从 main.py 读取 VERSION 变量"""
    main_py = ROOT / "main.py"
    if not main_py.exists():
        return ""
    try:
        content = main_py.read_text(encoding="utf-8")
        match = re.search(r'VERSION\s*=\s*["\']([^"\']+)["\']', content)
        if match:
            return match.group(1)
    except Exception:
        pass
    return ""


def detect_version() -> str:
    """检测当前项目版本

    优先级: VERSION 文件 > main.py VERSION 变量 > config.json._version
    """
    # 1. VERSION 文件
    vf = ROOT / "VERSION"
    if vf.exists():
        try:
            v = vf.read_text(encoding="utf-8").strip()
            if v:
                return v
        except Exception:
            pass

    # 2. main.py 中的 VERSION
    v = _read_main_py_version()
    if v:
        return v

    # 3. config.json 中的 _version
    cj = CONFIG_DIR / "config.json"
    if cj.exists():
        try:
            with open(cj, "r", encoding="utf-8") as f:
                data = json.load(f)
            v = data.get("_version", "")
            if v:
                return v
        except Exception:
            pass

    return ""


def get_config_format() -> str:
    """检测当前使用的配置格式

    返回: "json" | "py" | "none"
    """
    if (CONFIG_DIR / "config.json").exists():
        return "json"
    if (CONFIG_DIR / "config.py").exists():
        return "py"
    return "none"


def is_at_or_below(version: str, threshold: str) -> bool:
    """检查版本是否 <= 阈值"""
    return compare_versions(version, threshold) <= 0


# ===== 0.4.1 版本边界: config 文件位置迁移 =====
# <= 0.4.0: 配置文件在项目根目录
# >= 0.4.1: 配置文件在 config/ 子目录
_CONFIG_MIGRATION_VERSION = "0.4.1"

_CONFIG_FILENAMES = [
    "config.json", "config.py", "config.py.bak", "config.json.bak",
    "config.example.json",
    "permission.json", "permission.json.bak", "permission.example.json",
    "users.json", "users.example.json",
    "banlist.json",
]


def migrate_config_location(old_version: str, new_version: str) -> None:
    """根据版本变迁自动移动配置文件位置

    升级到 >= 0.4.1: 根目录 → config/
    降级到 <= 0.4.0: config/ → 根目录

    文件已存在于目标位置时不会覆盖。
    """
    import shutil

    old_at_or_below = is_at_or_below(old_version, _CONFIG_MIGRATION_VERSION)
    new_at_or_below = is_at_or_below(new_version, _CONFIG_MIGRATION_VERSION)

    if old_at_or_below and not new_at_or_below:
        # 升级: 根目录 → config/
        _migrate_files(ROOT, CONFIG_DIR, "根目录", "config/")
    elif not old_at_or_below and new_at_or_below:
        # 降级: config/ → 根目录
        _migrate_files(CONFIG_DIR, ROOT, "config/", "根目录")


def _migrate_files(src_dir, dst_dir, src_label: str, dst_label: str) -> None:
    """将配置文件从 src_dir 移动到 dst_dir(已存在则跳过)"""
    import shutil

    src_dir = Path(src_dir)
    dst_dir = Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)

    moved = []
    for fname in _CONFIG_FILENAMES:
        src = src_dir / fname
        dst = dst_dir / fname
        if src.exists() and not dst.exists():
            try:
                shutil.move(str(src), str(dst))
                moved.append(fname)
            except Exception as e:
                print(f"[VersionManager] 移动 {fname} 失败: {e}")

    if moved:
        print(f"[VersionManager] 已将 {len(moved)} 个配置文件从{src_label}移动到{dst_label}")
        for f in moved:
            print(f"  - {f}")
