"""配置加载器 - 支持 JSON 和 Python 双格式，自动版本迁移

版本检测和迁移逻辑委托给 version_manager 包。
"""

import json
import os
import sys
import importlib.util
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONFIG_JSON = ROOT / "config.json"
CONFIG_PY = ROOT / "config.py"
CONFIG_EXAMPLE_JSON = ROOT / "config.example.json"
CONFIG_EXAMPLE_PY = ROOT / "config.example.py"

# 版本常量（供外部引用）
CURRENT_VERSION = "b0.3.6"
LEGACY_VERSION_THRESHOLD = "b0.3.5"  # 此版本及以下使用 .py 格式


def _get_current_version() -> str:
    """获取当前版本（委托 version_manager）"""
    try:
        from version_manager.detector import detect_version
        v = detect_version()
        if v:
            return v
    except ImportError:
        pass
    return CURRENT_VERSION


def _is_legacy_version(version: str) -> bool:
    """检查是否为旧版本（<= b0.3.5）"""
    try:
        from version_manager.detector import is_at_or_below
        return is_at_or_below(version, LEGACY_VERSION_THRESHOLD)
    except ImportError:
        return "b0.3.5" >= version


def _load_json_config(path: Path) -> dict:
    """加载 JSON 配置文件"""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Config] 加载 JSON 配置失败 {path}: {e}")
        return {}


def _load_py_config(path: Path) -> dict:
    """加载 Python 配置文件（兼容旧版本）"""
    if not path.exists():
        return {}
    try:
        spec = importlib.util.spec_from_file_location("config_py", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["config_py"] = module
        spec.loader.exec_module(module)
        # 提取配置变量（大写、驼峰命名、下划线命名）
        config = {}
        for name in dir(module):
            if (name.isupper() or 
                name in ("is_first_run", "platform", "commandAliases", "commandPrefix", "command_prefix", "wsConfig", "ws_config", "logLevel", "log_level", "githubToken", "github_token", "rateLimit", "rate_limit", "webuiConfig", "webui_config", "AIConfig", "ai_config", "utilsConfig", "utils_config", "sapiConfig", "sapi_config", "botConfig", "bot_config", "messageConfig", "message_config", "basePath", "base_path", "mods", "spam", "features")):
                config[name] = getattr(module, name)
        return config
    except Exception as e:
        print(f"[Config] 加载 Python 配置失败 {path}: {e}")
        return {}


def _merge_configs(json_config: dict, py_config: dict) -> dict:
    """合并配置，JSON 优先，Python 作为回退"""
    merged = py_config.copy()
    merged.update(json_config)
    return merged


def load_config() -> dict:
    """加载配置，支持双格式自动检测和迁移"""
    # 启动时自动迁移（删除旧格式配置文件）
    auto_migrate_if_needed()

    version = _get_current_version()
    is_legacy = _is_legacy_version(version)

    # 1. 尝试加载 JSON 配置
    json_config = _load_json_config(CONFIG_JSON)

    # 2. 尝试加载 Python 配置（兼容旧版本）
    py_config = _load_py_config(CONFIG_PY)

    # 3. 合并配置
    if json_config:
        config = _merge_configs(json_config, py_config)
        config["_config_format"] = "json"
    elif py_config:
        config = py_config
        config["_config_format"] = "py"
        # 旧版本提醒
        if is_legacy:
            print(f"[Config] ⚠️ 检测到旧版本配置 (v{version} <= {LEGACY_VERSION_THRESHOLD})")
            print("[Config] 建议迁移到 config.json 格式，详见 config.example.json")
    else:
        # 都没有，使用示例配置
        json_example = _load_json_config(CONFIG_EXAMPLE_JSON)
        py_example = _load_py_config(CONFIG_EXAMPLE_PY)
        config = _merge_configs(json_example, py_example)
        config["_config_format"] = "example"

    # 确保版本信息
    config["_version"] = version
    config["_is_legacy"] = is_legacy

    return config


def save_config(config: dict) -> bool:
    """保存配置到 JSON 文件"""
    try:
        # 移除内部字段
        internal_keys = ["_config_format", "_version", "_is_legacy"]
        save_data = {k: v for k, v in config.items() if k not in internal_keys}
        save_data["_version"] = CURRENT_VERSION

        with open(CONFIG_JSON, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)

        # 如果存在旧的 config.py，提示用户可删除
        if CONFIG_PY.exists():
            print(f"[Config] 配置已保存到 config.json，旧的 config.py 可手动删除")
        return True
    except Exception as e:
        print(f"[Config] 保存配置失败: {e}")
        return False


def auto_migrate_if_needed() -> bool:
    """启动时自动检测并迁移配置格式

    升级: config.py 存在且 config.json 不存在 -> 迁移到 JSON 并删除 config.py
    降级: config.json 存在且 config.py 不存在且 config.json._version <= b0.3.5 -> 降级到 Python 并删除 config.json

    Returns:
        是否发生了迁移
    """
    has_json = CONFIG_JSON.exists()
    has_py = CONFIG_PY.exists()

    # 都存在或都不存在，无需迁移
    if has_json == has_py:
        return False

    # 升级: 只有 config.py，迁移到 JSON
    if has_py and not has_json:
        print(f"[Config] 检测到旧版本配置，自动迁移到 config.json...")
        from version_manager import migrate
        if migrate("py", "json"):
            print("[Config] 自动迁移完成，旧 config.py 已删除")
            return True
        else:
            print("[Config] 自动迁移失败")
            return False

    # 降级: 只有 config.json，检查其 _version 字段是否为旧版本
    if has_json and not has_py:
        try:
            with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                json_config = json.load(f)
            json_version = json_config.get("_version", "")
            from version_manager.detector import is_at_or_below
            if is_at_or_below(json_version, LEGACY_VERSION_THRESHOLD):
                print(f"[Config] 检测到旧版本 JSON 配置 (v{json_version})，自动降级到 config.py...")
                from version_manager import migrate
                if migrate("json", "py"):
                    print("[Config] 自动降级完成，旧 config.json 已删除")
                    return True
                else:
                    print("[Config] 自动降级失败")
                    return False
        except Exception as e:
            print(f"[Config] 读取 config.json 版本失败: {e}")

    return False


def migrate_py_to_json() -> bool:
    """将 Python 配置迁移到 JSON（委托 version_manager）"""
    try:
        from version_manager import migrate
        return migrate("py", "json", src=CONFIG_PY, dst=CONFIG_JSON)
    except ImportError:
        # 回退: 内置简单迁移
        py_config = _load_py_config(CONFIG_PY)
        if not py_config:
            return False
        serializable = {}
        for k, v in py_config.items():
            if not k.startswith("_"):
                try:
                    json.dumps(v)
                    serializable[k] = v
                except (TypeError, ValueError):
                    pass
        serializable["_version"] = _get_current_version()
        try:
            with open(CONFIG_JSON, "w", encoding="utf-8") as f:
                json.dump(serializable, f, ensure_ascii=False, indent=2)
            print(f"[Config] 已迁移 config.py -> config.json")
            return True
        except Exception as e:
            print(f"[Config] 迁移失败: {e}")
            return False


def migrate_json_to_py() -> bool:
    """将 JSON(b0.3.6) 配置降级为 Python(b0.1.0)（委托 version_manager）"""
    try:
        from version_manager import migrate
        return migrate("json", "py", src=CONFIG_JSON, dst=CONFIG_PY)
    except ImportError:
        print("[Config] version_manager 不可用，无法执行降级")
        return False


# 全局配置缓存
_config_cache = None


def get_config() -> dict:
    """获取配置（带缓存）"""
    global _config_cache
    if _config_cache is None:
        _config_cache = load_config()
    return _config_cache


def reload_config() -> dict:
    """重新加载配置（清除缓存）"""
    global _config_cache
    _config_cache = None
    return get_config()


# 兼容旧代码：提供 config 模块接口
class ConfigProxy:
    """配置代理，兼容旧的 `from config import xxx` 用法"""

    # 缺失键的默认值,防止 `from config import xxx` 在 config.json 不完整时崩溃
    _DEFAULTS = {
        "basePath": {},
        "spam": {},
        "rateLimit": {},
        "commandAliases": {},
    }

    def __getattr__(self, name):
        config = get_config()
        if name in config:
            return config[name]
        if name in self._DEFAULTS:
            return self._DEFAULTS[name]
        raise AttributeError(f"配置项不存在: {name}")

    def __setattr__(self, name, value):
        if name.startswith("_"):
            super().__setattr__(name, value)
        else:
            config = get_config()
            config[name] = value
            save_config(config)

    def __dir__(self):
        return list(get_config().keys())


# 创建全局代理实例，兼容 `import config`
config = ConfigProxy()


# resolvePath: 兼容 config.py 中的 resolvePath 函数
# 所有平台统一返回相对路径写法
def resolvePath(relPath):
    """路径适配函数(兼容 config.py 旧代码(技术债:((()))))"""
    p = str(relPath)
    if p.startswith("/") or (len(p) >= 2 and p[1] == ":"):
        return p
    return p


# 为了兼容 `from config import xxx`，动态设置模块属性
import sys
this_module = sys.modules[__name__]
for key, value in get_config().items():
    if not key.startswith("_"):
        setattr(this_module, key, value)

# 将本模块注册为 `config`，使 `from config import xxx` 在无 config.py 时也能工作
# Mod 文件大量使用 `from config import basePath, features` 等
if "config" not in sys.modules:
    sys.modules["config"] = this_module