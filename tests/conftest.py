# Author: Hydrooxzgen
# Github: https://github.com/Hydrooxzgen
# This project uses the GPL-3.0 license, you can modify/distribute this project according to the GPL-3.0 license
"""conftest.py — 在导入 mod 前 mock config 模块,避免缺少 config.py 导致导入失败"""
import sys
import types

# 在任何 mod 导入之前注入 mock config
if "config" not in sys.modules:
    _mock_config = types.ModuleType("config")
    _mock_config.basePath = {"ezmatic": "./resources/ezmatic"}
    _mock_config.resolvePath = lambda p: p
    sys.modules["config"] = _mock_config
