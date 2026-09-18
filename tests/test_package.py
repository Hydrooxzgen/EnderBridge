"""test_package.py — version_manager.package 回归测试

覆盖:
- safe_rel / common_root
- extract_archive / apply_archive / validate_project
- backup_dir / list_backups / prune_backups / rollback
- create_export_zip / collect_export_files
"""

import os
import time
import zipfile
import tempfile
import pytest

from version_manager.package import (
    safe_rel,
    common_root,
    extract_archive,
    apply_archive,
    validate_project,
    backup_dir,
    list_backups,
    prune_backups,
    rollback,
    create_export_zip,
    collect_export_files,
    PackageError,
    BACKUP_PREFIX,
    BACKUP_KEEP_COUNT,
)


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────

def make_zip(path, members):
    """创建 zip，members 是 {内部路径: 字节内容} 的字典"""
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


def make_project(root, extra_files=None):
    """在 root 目录下创建最小合法 EnderBridge 项目结构"""
    os.makedirs(os.path.join(root, "lib"), exist_ok=True)
    with open(os.path.join(root, "main.py"), "w") as f:
        f.write("# main\n")
    if extra_files:
        for rel, content in extra_files.items():
            abs_path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w") as f:
                f.write(content)


# ──────────────────────────────────────────────
# safe_rel
# ──────────────────────────────────────────────

class TestSafeRel:
    def test_normal_path(self):
        assert safe_rel("foo/bar.py") == "foo/bar.py"

    def test_root_relative_dot(self):
        assert safe_rel(".") == ""

    def test_empty_string(self):
        assert safe_rel("") == ""

    def test_path_traversal_blocked(self):
        assert safe_rel("../../etc/passwd") == ""

    def test_absolute_path_blocked(self):
        assert safe_rel("/etc/passwd") == ""

    def test_windows_backslash(self):
        result = safe_rel("foo\\bar.py")
        assert result == "foo/bar.py"

    def test_single_filename(self):
        assert safe_rel("main.py") == "main.py"

    def test_nested(self):
        assert safe_rel("a/b/c/d.txt") == "a/b/c/d.txt"


# ──────────────────────────────────────────────
# common_root
# ──────────────────────────────────────────────

class TestCommonRoot:
    def test_github_style(self):
        names = ["EnderBridge-main/main.py", "EnderBridge-main/lib/foo.py"]
        assert common_root(names) == "EnderBridge-main"

    def test_no_common_root(self):
        names = ["main.py", "lib/foo.py"]
        assert common_root(names) == ""

    def test_empty(self):
        assert common_root([]) == ""

    def test_multiple_roots(self):
        names = ["a/x.py", "b/y.py"]
        assert common_root(names) == ""

    def test_single_file_no_slash(self):
        assert common_root(["main.py"]) == ""


# ──────────────────────────────────────────────
# extract_archive
# ──────────────────────────────────────────────

class TestExtractArchive:
    def test_basic_zip(self, tmp_path):
        z = make_zip(str(tmp_path / "pkg.zip"), {
            "main.py": "# main",
            "lib/util.py": "# util",
        })
        dest = tmp_path / "dest"
        dest.mkdir()
        count = extract_archive(z, str(dest))
        assert count == 2
        assert (dest / "main.py").exists()
        assert (dest / "lib" / "util.py").exists()

    def test_github_style_strips_root(self, tmp_path):
        z = make_zip(str(tmp_path / "pkg.zip"), {
            "EnderBridge-main/main.py": "# main",
            "EnderBridge-main/lib/util.py": "# util",
        })
        dest = tmp_path / "dest"
        dest.mkdir()
        count = extract_archive(z, str(dest))
        assert count == 2
        assert (dest / "main.py").exists()

    def test_keep_skips_config(self, tmp_path):
        z = make_zip(str(tmp_path / "pkg.zip"), {
            "main.py": "# main",
            "config/config.json": "{}",
            "config/config.example.json": "{}",
        })
        dest = tmp_path / "dest"
        dest.mkdir()
        count = extract_archive(z, str(dest))
        # config/ 跳过，模板文件放行
        assert (dest / "main.py").exists()
        assert not (dest / "config" / "config.json").exists()
        assert (dest / "config" / "config.example.json").exists()

    def test_unsupported_format(self, tmp_path):
        bad = tmp_path / "pkg.7z"
        bad.write_bytes(b"fake")
        with pytest.raises(PackageError, match="不支持的压缩包格式"):
            extract_archive(str(bad), str(tmp_path / "dest"))

    def test_corrupt_zip(self, tmp_path):
        bad = tmp_path / "pkg.zip"
        bad.write_bytes(b"not a zip")
        with pytest.raises(PackageError, match="读取压缩包失败"):
            extract_archive(str(bad), str(tmp_path / "dest"))


# ──────────────────────────────────────────────
# validate_project
# ──────────────────────────────────────────────

class TestValidateProject:
    def test_valid_project(self, tmp_path):
        make_project(str(tmp_path))
        validate_project(str(tmp_path))  # 不应抛异常

    def test_missing_main_py(self, tmp_path):
        os.makedirs(str(tmp_path / "lib"))
        with pytest.raises(PackageError, match="main.py"):
            validate_project(str(tmp_path))

    def test_missing_lib_dir(self, tmp_path):
        (tmp_path / "main.py").write_text("# main")
        with pytest.raises(PackageError, match="lib"):
            validate_project(str(tmp_path))


# ──────────────────────────────────────────────
# apply_archive
# ──────────────────────────────────────────────

class TestApplyArchive:
    def test_apply_overlays_files(self, tmp_path):
        root = tmp_path / "project"
        make_project(str(root), {"old.py": "old"})

        z = make_zip(str(tmp_path / "update.zip"), {
            "main.py": "# new main",
            "lib/new.py": "# new lib",
        })
        count = apply_archive(z, str(root))
        assert count >= 2
        assert (root / "main.py").read_text() == "# new main"
        assert (root / "old.py").exists()  # 旧文件不被删除

    def test_apply_invalid_archive_raises(self, tmp_path):
        root = tmp_path / "project"
        make_project(str(root))
        bad = tmp_path / "bad.zip"
        bad.write_bytes(b"not a zip")
        with pytest.raises(PackageError):
            apply_archive(str(bad), str(root))

    def test_apply_fails_validation(self, tmp_path):
        root = tmp_path / "project"
        make_project(str(root))
        # 压缩包中没有 main.py 和 lib/
        z = make_zip(str(tmp_path / "bad.zip"), {"readme.txt": "hi"})
        with pytest.raises(PackageError):
            apply_archive(z, str(root))


# ──────────────────────────────────────────────
# backup_dir / list_backups / prune_backups
# ──────────────────────────────────────────────

class TestBackup:
    def test_backup_creates_zip(self, tmp_path):
        project = tmp_path / "project"
        make_project(str(project))
        backup_dest = tmp_path / "backups"
        path = backup_dir(str(project), dest_dir=str(backup_dest))
        assert os.path.isfile(path)
        assert os.path.basename(path).startswith(BACKUP_PREFIX)
        assert path.endswith(".zip")

    def test_backup_zip_contains_main_py(self, tmp_path):
        project = tmp_path / "project"
        make_project(str(project))
        backup_dest = tmp_path / "backups"
        path = backup_dir(str(project), dest_dir=str(backup_dest))
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
        assert "main.py" in names

    def test_list_backups_empty(self, tmp_path):
        assert list_backups(str(tmp_path)) == []

    def test_list_backups_sorted(self, tmp_path):
        project = tmp_path / "project"
        make_project(str(project))
        backup_dest = tmp_path / "backups"
        p1 = backup_dir(str(project), dest_dir=str(backup_dest), keep=99)
        time.sleep(1.1)  # 确保时间戳不同
        p2 = backup_dir(str(project), dest_dir=str(backup_dest), keep=99)
        found = list_backups(str(backup_dest))
        assert len(found) == 2
        assert found[0] < found[1]  # 按字典序（时间戳）升序

    def test_prune_keeps_recent(self, tmp_path):
        project = tmp_path / "project"
        make_project(str(project))
        backup_dest = tmp_path / "backups"
        for _ in range(4):
            backup_dir(str(project), dest_dir=str(backup_dest), keep=99)
            time.sleep(1.1)
        prune_backups(str(backup_dest), keep=2)
        found = list_backups(str(backup_dest))
        assert len(found) == 2

    def test_backup_prunes_automatically(self, tmp_path):
        project = tmp_path / "project"
        make_project(str(project))
        backup_dest = tmp_path / "backups"
        for _ in range(BACKUP_KEEP_COUNT + 1):
            backup_dir(str(project), dest_dir=str(backup_dest))
            time.sleep(1.1)
        found = list_backups(str(backup_dest))
        assert len(found) == BACKUP_KEEP_COUNT


# ──────────────────────────────────────────────
# rollback
# ──────────────────────────────────────────────

class TestRollback:
    def test_rollback_restores_file(self, tmp_path):
        project = tmp_path / "project"
        make_project(str(project), {"marker.txt": "original"})
        backup_dest = tmp_path / "backups"

        # 先备份
        bp = backup_dir(str(project), dest_dir=str(backup_dest), keep=99)
        # 破坏项目
        (project / "marker.txt").write_text("corrupted")

        used = rollback(str(project), backup_path=bp, dest_dir=str(backup_dest))
        assert used == bp
        assert (project / "marker.txt").read_text() == "original"

    def test_rollback_no_backup_raises(self, tmp_path):
        project = tmp_path / "project"
        make_project(str(project))
        empty_dest = tmp_path / "backups"
        empty_dest.mkdir()
        with pytest.raises(PackageError, match="未找到可用备份"):
            rollback(str(project), dest_dir=str(empty_dest))

    def test_rollback_missing_file_raises(self, tmp_path):
        project = tmp_path / "project"
        make_project(str(project))
        with pytest.raises(PackageError, match="找不到备份文件"):
            rollback(str(project), backup_path="/nonexistent/backup.zip",
                     dest_dir=str(tmp_path))

    def test_rollback_creates_pre_rollback_backup(self, tmp_path):
        """rollback 前会先备份当前状态"""
        project = tmp_path / "project"
        make_project(str(project))
        backup_dest = tmp_path / "backups"
        bp = backup_dir(str(project), dest_dir=str(backup_dest), keep=99)
        time.sleep(1.1)
        rollback(str(project), backup_path=bp, dest_dir=str(backup_dest))
        # 回滚完成后备份数应该是 2（原备份 + 回滚前备份）
        found = list_backups(str(backup_dest))
        assert len(found) >= 2


# ──────────────────────────────────────────────
# create_export_zip / collect_export_files
# ──────────────────────────────────────────────

class TestExport:
    def test_export_includes_main_py(self, tmp_path):
        project = tmp_path / "project"
        make_project(str(project), {
            "webui/index.html": "<html/>",
            "config/config.json": "{}",
            "config/config.example.json": "{}",
        })
        out = str(tmp_path / "export.zip")
        create_export_zip(str(project), out)
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
        assert "main.py" in names

    def test_export_excludes_config_data(self, tmp_path):
        project = tmp_path / "project"
        make_project(str(project), {
            "config/config.json": "{}",
        })
        out = str(tmp_path / "export.zip")
        create_export_zip(str(project), out)
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
        assert "config/config.json" not in names

    def test_export_includes_template_files(self, tmp_path):
        project = tmp_path / "project"
        make_project(str(project), {
            "config/config.example.json": "{}",
            "config/users.example.json": "{}",
            "config/permission.example.json": "{}",
        })
        out = str(tmp_path / "export.zip")
        create_export_zip(str(project), out)
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
        assert "config/config.example.json" in names
        assert "config/users.example.json" in names

    def test_export_excludes_pyc(self, tmp_path):
        project = tmp_path / "project"
        make_project(str(project), {"foo.pyc": "bytecode"})
        out = str(tmp_path / "export.zip")
        create_export_zip(str(project), out)
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
        assert "foo.pyc" not in names

    def test_export_empty_project_raises(self, tmp_path):
        # 只有被排除的目录，collect_export_files 返回空
        project = tmp_path / "empty"
        project.mkdir()
        os.makedirs(str(project / "config"))
        out = str(tmp_path / "export.zip")
        with pytest.raises(PackageError, match="未找到可导出的文件"):
            create_export_zip(str(project), out)

