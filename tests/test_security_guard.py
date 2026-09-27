"""test_security_guard.py — 核心配置防篡改安全卫士单元与集成测试"""

import os
import shutil
import sys
import pytest

from lib.security_guard import install_security_guard, ROOT, CONFIG_DIR, MOD_DIR


class TestSecurityGuard:
    @classmethod
    def setup_class(cls):
        install_security_guard()

    def test_core_can_write_config(self, tmp_path):
        # 核心代码或非 Mod 代码写入非受限文件或测试文件正常放行
        test_file = tmp_path / "test.txt"
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("allowed")
        assert test_file.read_text(encoding="utf-8") == "allowed"

    def test_mod_blocked_from_writing_config_json(self):
        # 模拟位于 mod/evil_mod.py 中的代码调用
        code = compile("""
import os, sys

def attack():
    target = os.path.join(CONFIG_DIR, "config.json")
    with open(target, "w", encoding="utf-8") as f:
        f.write("hacked")

attack()
""", os.path.join(MOD_DIR, "evil_mod.py"), "exec")

        with pytest.raises(PermissionError, match=r"\[EnderBridge.*Mod"):
            exec(code, {"CONFIG_DIR": CONFIG_DIR})

    def test_mod_blocked_from_shutil_copy_to_config(self, tmp_path):
        # 模拟 Mod 使用 shutil.copy 覆盖 config.json
        src_file = tmp_path / "fake_config.json"
        src_file.write_text("{}", encoding="utf-8")

        code = compile("""
import shutil, os

def attack():
    target = os.path.join(CONFIG_DIR, "config.json")
    shutil.copy(src_file, target)

attack()
""", os.path.join(MOD_DIR, "evil_copy_mod.py"), "exec")

        with pytest.raises(PermissionError, match=r"\[EnderBridge.*Mod"):
            exec(code, {"CONFIG_DIR": CONFIG_DIR, "src_file": str(src_file)})

    def test_mod_blocked_from_deleting_users_json(self):
        # 模拟 Mod 使用 os.remove 删除 users.json
        code = compile("""
import os

def attack():
    target = os.path.join(CONFIG_DIR, "users.json")
    os.remove(target)

attack()
""", os.path.join(MOD_DIR, "evil_delete_mod.py"), "exec")

        with pytest.raises(PermissionError, match=r"\[EnderBridge.*Mod"):
            exec(code, {"CONFIG_DIR": CONFIG_DIR})

    def test_mod_blocked_from_renaming_config(self):
        # 模拟 Mod 重命名核心配置
        code = compile("""
import os

def attack():
    target = os.path.join(CONFIG_DIR, "config.json")
    os.rename(target, target + ".bak")

attack()
""", os.path.join(MOD_DIR, "evil_rename_mod.py"), "exec")

        with pytest.raises(PermissionError, match=r"\[EnderBridge.*Mod"):
            exec(code, {"CONFIG_DIR": CONFIG_DIR})

    def test_mod_allowed_to_write_own_dir(self, tmp_path):
        # 验证 Mod 写入自己目录或临时目录不受影响
        mod_local_file = os.path.join(MOD_DIR, "my_mod_cache.tmp")
        code = compile("""
import os

def normal_work():
    with open(target, "w", encoding="utf-8") as f:
        f.write("mod cache")

normal_work()
""", os.path.join(MOD_DIR, "my_normal_mod.py"), "exec")

        try:
            exec(code, {"target": mod_local_file})
            assert os.path.isfile(mod_local_file)
        finally:
            if os.path.isfile(mod_local_file):
                os.remove(mod_local_file)
