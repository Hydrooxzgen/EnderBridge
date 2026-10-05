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

    def test_official_mod_can_call_save_config(self):
        # 验证官方核心 Mod (如 bot.py) 通过官方 save_config 正常保存账号等配置
        from webui.server import save_config
        cfg_path = os.path.join(CONFIG_DIR, "config.json")
        backup = None
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                backup = f.read()

        code = compile("""
from webui.server import save_config
save_config({"botConfig": {"username": "OfficialBot"}})
""", os.path.join(MOD_DIR, "bot.py"), "exec")

        try:
            exec(code)
        finally:
            if backup is not None:
                with open(cfg_path, "w", encoding="utf-8") as f:
                    f.write(backup)

    def test_third_party_mod_blocked_from_calling_save_config(self):
        # 验证第三方 Mod 企图调用 save_config 写入配置被拦截
        code = compile("""
from webui.server import save_config
save_config({"botConfig": {"username": "HackedBot"}})
""", os.path.join(MOD_DIR, "evil_bot_mod.py"), "exec")

        with pytest.raises(PermissionError, match=r"\[EnderBridge.*Mod"):
            exec(code)

    def test_save_mod_config_bot_allowed(self):
        # 验证专有 save_mod_config 函数允许 bot 修改其合法字段
        from lib.mods import save_mod_config
        from lib.config_loader import get_config
        cfg_path = os.path.join(CONFIG_DIR, "config.json")
        backup = None
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                backup = f.read()

        try:
            ok = save_mod_config("bot", {"username": "SaveModConfigBot", "offline": False})
            assert ok is True
            cfg = get_config(force_reload=True)
            assert cfg.get("botConfig", {}).get("username") == "SaveModConfigBot"
        finally:
            if backup is not None:
                with open(cfg_path, "w", encoding="utf-8") as f:
                    f.write(backup)

    def test_save_mod_config_disallows_tampering_system_keys(self):
        # 验证即使 hacker 尝试利用 save_mod_config 写入未授权的系统字段(如 webuiConfig)，也会被拦截/剔除
        from lib.mods import save_mod_config
        # 传入未在 MOD_ALLOWED_KEYS["bot"] 中的恶意字段
        ok = save_mod_config("bot", {"webuiConfig": {"token": "malicious"}})
        assert ok is False

    def test_save_mod_config_unregistered_mod_rejected(self):
        # 验证未注册的第三方 Mod 调用 save_mod_config 直接被拒绝
        from lib.mods import save_mod_config
        ok = save_mod_config("evil_third_party_mod", {"attack": "data"})
        assert ok is False

    def test_mod_blocked_from_modifying_official_mod_source(self):
        # 验证第三方 Mod 企图在磁盘上篡改/覆盖官方内置 Mod (如 bot.py) 源码被底层拦截
        code = compile("""
import os
target = os.path.join(MOD_DIR, "bot.py")
with open(target, "a", encoding="utf-8") as f:
    f.write("# hacked")
""", os.path.join(MOD_DIR, "evil_hacker_mod.py"), "exec")

        with pytest.raises(PermissionError, match=r"\[EnderBridge.*Mod"):
            exec(code, {"MOD_DIR": MOD_DIR})
