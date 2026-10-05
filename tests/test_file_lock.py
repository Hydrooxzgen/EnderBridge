"""tests/test_file_lock.py — 操作系统级运行时独占/排他文件锁单元测试"""

import json
import os
import sys
import pytest
from lib.file_lock import SystemFileLockManager


class TestSystemFileLock:
    def test_locked_file_blocks_write_and_allows_read(self, tmp_path):
        """测试锁定文件后：允许正常读取，但严格阻止外部写入/追加/覆写"""
        test_file = tmp_path / "test_config.json"
        with open(str(test_file), "w", encoding="utf-8") as f:
            f.write(json.dumps({"key": "original_value"}))

        # 初始未锁定状态：写入应当成功
        with open(str(test_file), "a", encoding="utf-8") as f:
            f.write(" ")

        # 加系统级锁
        ok = SystemFileLockManager.lock_file(str(test_file))
        assert ok is True
        assert SystemFileLockManager.is_locked(str(test_file)) is True

        try:
            # 1. 验证允许只读访问
            with open(str(test_file), "r", encoding="utf-8") as f:
                content = f.read()
            assert "original_value" in content

            # 2. 验证写模式 ('w') 被系统内核拦截抛出 PermissionError
            with pytest.raises(PermissionError):
                with open(str(test_file), "w", encoding="utf-8") as f:
                    f.write("hacked")

            # 3. 验证追加模式 ('a') 被系统内核拦截抛出 PermissionError
            with pytest.raises(PermissionError):
                with open(str(test_file), "a", encoding="utf-8") as f:
                    f.write("more")

            # 4. 验证替换/原子覆盖在 Windows 下被排他句柄拦截 (WinError 32 / WinError 5)
            if sys.platform == "win32":
                tmp_source = tmp_path / "attacker_tmp.json"
                with open(str(tmp_source), "w", encoding="utf-8") as f:
                    f.write("malicious")

                with pytest.raises(PermissionError):
                    os.replace(str(tmp_source), str(test_file))

        finally:
            # 清理锁并恢复权限
            SystemFileLockManager.unlock_file(str(test_file))

        # 解锁后：写入应当恢复正常
        with open(str(test_file), "w", encoding="utf-8") as f:
            f.write("normal_after_unlock")
        assert test_file.read_text(encoding="utf-8") == "normal_after_unlock"

    def test_unlock_for_write_context_manager(self, tmp_path):
        """测试 unlock_for_write 上下文管理器：允许内部安全修改并在退出后自动恢复加锁"""
        test_file = tmp_path / "safe_config.json"
        test_file.write_text(json.dumps({"state": "init"}), encoding="utf-8")

        # 加锁
        SystemFileLockManager.lock_file(str(test_file))
        assert SystemFileLockManager.is_locked(str(test_file)) is True

        try:
            # 使用安全通道更新
            with SystemFileLockManager.unlock_for_write(str(test_file)):
                tmp_file = tmp_path / "safe_tmp.json"
                tmp_file.write_text(json.dumps({"state": "updated_by_eb"}), encoding="utf-8")
                os.replace(str(tmp_file), str(test_file))

            # 退出上下文后：自动重新处于锁定状态
            assert SystemFileLockManager.is_locked(str(test_file)) is True

            # 验证内容已更新
            with open(str(test_file), "r", encoding="utf-8") as f:
                data = json.load(f)
            assert data["state"] == "updated_by_eb"

            # 验证外部写入依然被阻止
            with pytest.raises(PermissionError):
                with open(str(test_file), "w", encoding="utf-8") as f:
                    f.write("hacked")
        finally:
            SystemFileLockManager.unlock_file(str(test_file))

    def test_unlock_all(self, tmp_path):
        """测试 unlock_all 一次性释放全部系统级句柄与权限"""
        f1 = tmp_path / "f1.json"
        f2 = tmp_path / "f2.json"
        f1.write_text("1", encoding="utf-8")
        f2.write_text("2", encoding="utf-8")

        SystemFileLockManager.lock_file(str(f1))
        SystemFileLockManager.lock_file(str(f2))
        assert SystemFileLockManager.is_locked(str(f1)) is True
        assert SystemFileLockManager.is_locked(str(f2)) is True

        SystemFileLockManager.unlock_all()
        assert SystemFileLockManager.is_locked(str(f1)) is False
        assert SystemFileLockManager.is_locked(str(f2)) is False

        # 确认均可正常写入
        f1.write_text("11", encoding="utf-8")
        f2.write_text("22", encoding="utf-8")

