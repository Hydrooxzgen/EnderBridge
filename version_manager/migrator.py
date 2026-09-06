"""迁移调度器 - 注册和执行配置格式迁移

迁移器注册表 MIGRATIONS 维护了所有可用的迁移路径。
新增格式只需添加一个迁移函数并注册到 MIGRATIONS 即可。
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent

# 迁移器注册表: (from_format, to_format) -> migrate_function
# migrate_function 签名: (src_path: Path, dst_path: Path, **kwargs) -> bool
MIGRATIONS: dict = {}


def register_migration(from_fmt: str, to_fmt: str):
    """装饰器: 注册一个迁移函数"""
    def decorator(func):
        MIGRATIONS[(from_fmt, to_fmt)] = func
        return func
    return decorator


def migrate(from_fmt: str, to_fmt: str, **kwargs) -> bool:
    """执行指定格式之间的迁移

    Args:
        from_fmt: 源格式 ("py" / "json")
        to_fmt: 目标格式 ("py" / "json")
        **kwargs: 传递给迁移函数的额外参数

    Returns:
        是否成功
    """
    key = (from_fmt, to_fmt)
    if key not in MIGRATIONS:
        print(f"[VersionManager] 不支持的迁移路径: {from_fmt} -> {to_fmt}")
        print(f"[VersionManager] 可用路径: {', '.join(f'{k[0]}->{k[1]}' for k in MIGRATIONS)}")
        return False

    return MIGRATIONS[key](**kwargs)


# ===== b0.1.0 (Python) -> b0.3.6 (JSON) =====

@register_migration("py", "json")
def migrate_py_to_json(src: Path = None, dst: Path = None, **kwargs) -> bool:
    """将 Python 格式配置迁移到 JSON 格式

    从 config.py 读取所有可序列化的配置变量，写入 config.json。
    迁移后原 config.py 重命名为 config.py.bak 保留。
    """
    import json

    src = src or ROOT / "config.py"
    dst = dst or ROOT / "config.json"

    if not src.exists():
        print("[VersionManager] 未找到 config.py, 无法迁移")
        return False

    # 动态加载 Python 配置
    import importlib.util
    import sys
    try:
        spec = importlib.util.spec_from_file_location("_migrate_cfg", str(src))
        module = importlib.util.module_from_spec(spec)
        sys.modules["_migrate_cfg"] = module
        spec.loader.exec_module(module)
    except Exception as e:
        print(f"[VersionManager] 加载 config.py 失败: {e}")
        return False

    # 提取可序列化变量
    config = {}
    _known_keys = (
        "is_first_run", "platform", "commandAliases", "commandPrefix",
        "wsConfig", "webuiConfig", "logLevel", "githubToken",
        "sapiConfig", "botConfig", "features", "mods",
    )
    for name in dir(module):
        if name.startswith("_"):
            continue
        if name.isupper() or name in _known_keys or callable(getattr(module, name, None)):
            if name in ("resolvePath",):  # 跳过函数
                continue
            val = getattr(module, name)
            try:
                json.dumps(val)  # 测试可序列化
                config[name] = val
            except (TypeError, ValueError):
                pass  # 跳过不可序列化的值

    # 写入 JSON
    try:
        from version_manager.detector import detect_version
        config["_version"] = detect_version() or "b0.3.6"

        with open(dst, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[VersionManager] 写入 config.json 失败: {e}")
        return False

    # 删除原 config.py
    try:
        if src.exists():
            src.unlink()
            print(f"[VersionManager] 已删除旧配置文件 config.py")
    except Exception as e:
        print(f"[VersionManager] 删除 config.py 失败: {e}")

    print(f"[VersionManager] 迁移完成: config.py -> config.json")
    print(f"[VersionManager] 共迁移 {len(config)} 个配置项")
    return True


# ===== b0.3.6 (JSON) -> b0.1.0 (Python) 降级 =====

@register_migration("json", "py")
def migrate_json_to_py(src: Path = None, dst: Path = None, **kwargs) -> bool:
    """将 JSON 格式配置降级为 Python 格式

    从 config.json 读取配置，生成等效的 config.py。
    降级后原 config.json 重命名为 config.json.bak 保留。
    """
    import json

    src = src or ROOT / "config.json"
    dst = dst or ROOT / "config.py"

    if not src.exists():
        print("[VersionManager] 未找到 config.json，无法降级")
        return False

    try:
        with open(src, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        print(f"[VersionManager] 加载 config.json 失败: {e}")
        return False

    # 生成 Python 配置文件
    lines = [
        '# EnderBridge 配置文件 (由 version_manager 自动降级生成)',
        '# 从 config.json 格式降级为 b0.1.0 Python 格式',
        'import sys',
        '',
        '',
    ]

    # is_first_run
    is_first = config.get("is_first_run", False)
    lines.append(f'is_first_run = {is_first}')
    lines.append('')

    # platform
    platform = config.get("platform", {})
    if platform:
        lines.append('platform = {')
        for k, v in platform.items():
            lines.append(f'    "{k}": {v},')
        lines.append('}')
        lines.append('')

    # resolvePath 函数 (b0.1.0 标准需要)
    lines.extend([
        'import re',
        '',
        '',
        'def resolvePath(relPath):',
        '    """路径适配函数"""',
        '    p = str(relPath)',
        '    if p.startswith("/") or re.match(r"^[a-zA-Z]:[\\\\/]", p):',
        '        return p',
        '    return p',
        '',
        '',
    ])

    # 简单字典配置
    _dict_keys = ("wsConfig", "webuiConfig", "sapiConfig", "botConfig",
                   "messageConfig", "AIConfig", "utilsConfig", "rateLimit")
    for key in _dict_keys:
        if key in config:
            val = config[key]
            lines.append(f'{key} = {repr(val)}')
            lines.append('')

    # features
    if "features" in config:
        lines.append(f'features = {repr(config["features"])}')
        lines.append('')

    # mods
    if "mods" in config:
        lines.append(f'mods = {repr(config["mods"])}')
        lines.append('')

    # 其他简单字段
    _simple_keys = ("commandPrefix", "logLevel", "githubToken")
    for key in _simple_keys:
        if key in config:
            lines.append(f'{key} = {repr(config[key])}')
            lines.append('')

    # commandAliases
    if "commandAliases" in config:
        lines.append(f'commandAliases = {repr(config["commandAliases"])}')
        lines.append('')

    try:
        with open(dst, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        print(f"[VersionManager] 写入 config.py 失败: {e}")
        return False

    # 删除原 config.json
    try:
        if src.exists():
            src.unlink()
            print(f"[VersionManager] 已删除旧配置文件 config.json")
    except Exception as e:
        print(f"[VersionManager] 删除 config.json 失败: {e}")

    print(f"[VersionManager] 降级完成: config.json -> config.py")
    print(f"[VersionManager] 共迁移 {len(config)} 个配置项")
    return True
