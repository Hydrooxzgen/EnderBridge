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
    ExportIgnore,
    EXPORT_IGNORE_FILE,
    clean_noneeds,
    NONEEDS_FILE,
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

    def test_export_always_excludes_exportignore_file(self, tmp_path):
        # 验证 .exportignore 文件本身无论如何都不会被打入导出的 zip 包
        project = tmp_path / "project"
        make_project(str(project), {
            ".exportignore": "# empty\n",
            "app.py": "print('hello')\n",
        })
        out = str(tmp_path / "export.zip")
        create_export_zip(str(project), out)
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
        assert "app.py" in names
        assert ".exportignore" not in names
        assert "project/.exportignore" not in names

    def test_export_respects_custom_exportignore_rules(self, tmp_path):
        # 验证 glob 匹配、目录匹配 (/)、根目录锚定 (/) 与取反规则 (!)
        project = tmp_path / "project"
        make_project(str(project), {
            ".exportignore": (
                "*.log\n"
                "temp/\n"
                "/root_only.txt\n"
                "docs/**/draft.md\n"
                "!important.log\n"
            ),
            "app.py": "print(1)\n",
            "normal.log": "log text\n",
            "important.log": "vital log text\n",
            "temp/cache.dat": "temp data\n",
            "sub/temp/other.dat": "sub temp data\n",
            "root_only.txt": "secret\n",
            "nested/root_only.txt": "allowed nested\n",
            "docs/v1/sub/draft.md": "draft content\n",
            "docs/v1/sub/published.md": "published content\n",
        })
        out = str(tmp_path / "export.zip")
        create_export_zip(str(project), out)
        with zipfile.ZipFile(out) as z:
            names = z.namelist()

        # 包含的文件
        assert "app.py" in names
        assert "important.log" in names  # 取反被保留
        assert "nested/root_only.txt" in names  # /root_only.txt 仅锚定根目录
        assert "docs/v1/sub/published.md" in names

        # 排除的文件
        assert ".exportignore" not in names  # 自身永远排除
        assert "normal.log" not in names
        assert "temp/cache.dat" not in names
        assert "sub/temp/other.dat" not in names
        assert "root_only.txt" not in names
        assert "docs/v1/sub/draft.md" not in names


class TestExportIgnoreUnit:
    def test_parse_comments_and_empty_lines(self):
        ign = ExportIgnore.parse([
            "\n",
            "   \n",
            "# this is a comment\n",
            "*.tmp\n",
            "!keep.tmp\n",
        ])
        assert len(ign.rules) == 2
        assert ign.is_ignored(".exportignore") is True
        assert ign.is_ignored("junk.tmp") is True
        assert ign.is_ignored("keep.tmp") is False
        assert ign.is_ignored("clean.py") is False

    def test_dir_only_distinction(self):
        ign = ExportIgnore.parse(["cache/\n"])
        # cache 为纯文件时由于规则要求以 / 结尾，故普通文件 cache 不匹配
        assert ign.is_ignored("cache", is_dir=False) is False
        # cache 为目录时匹配
        assert ign.is_ignored("cache", is_dir=True) is True
        assert ign.is_ignored("cache/item.bin", is_dir=False) is True
        assert ign.is_ignored("sub/cache/item.bin", is_dir=False) is True


class TestNoneeds:
    def test_clean_noneeds_deletes_files_and_directories(self, tmp_path):
        # 模拟包含 .noneeds 规则的项目
        project = tmp_path / "project"
        project.mkdir()
        (project / "wiki").mkdir()
        (project / "wiki" / "readme.md").write_text("wiki content")
        (project / "tests").mkdir()
        (project / "tests" / "test_a.py").write_text("test")
        (project / ".github").mkdir()
        (project / ".github" / "ci.yml").write_text("ci")
        (project / "CODE_OF_CONDUCT.md").write_text("coc")
        (project / "CONTRIBUTING.md").write_text("contributing")
        (project / "LICENSE").write_text("mit")
        (project / "main.py").write_text("# main")
        (project / "keep.py").write_text("# keep")

        # 写入 .noneeds 文件 (与用户配置一致)
        (project / NONEEDS_FILE).write_text(
            "wiki/\n"
            "tests/\n"
            ".github/\n"
            "CODE_OF_CONDUCT.md\n"
            "CONTRIBUTING.md\n"
            "LICENSE\n"
            "nonexistent_file.txt\n"
        )

        deleted = clean_noneeds(str(project))
        assert "wiki/" in deleted
        assert "tests/" in deleted
        assert ".github/" in deleted
        assert "CODE_OF_CONDUCT.md" in deleted
        assert "CONTRIBUTING.md" in deleted
        assert "LICENSE" in deleted

        # 验证指定的文件和目录已被彻底删除
        assert not (project / "wiki").exists()
        assert not (project / "tests").exists()
        assert not (project / ".github").exists()
        assert not (project / "CODE_OF_CONDUCT.md").exists()
        assert not (project / "CONTRIBUTING.md").exists()
        assert not (project / "LICENSE").exists()

        # 验证保留的文件不受影响，.noneeds 自身保留
        assert (project / "main.py").exists()
        assert (project / "keep.py").exists()
        assert (project / NONEEDS_FILE).exists()

    def test_clean_noneeds_supports_wildcards_and_comments(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "temp").mkdir()
        (project / "temp" / "cache.bin").write_text("bin")
        (project / "test_old.log").write_text("log")
        (project / "test_new.log").write_text("log")
        (project / "important.txt").write_text("important")

        (project / NONEEDS_FILE).write_text(
            "# 这是注释\n"
            "\n"
            "*.log\n"
            "temp/\n"
        )

        deleted = clean_noneeds(str(project))
        assert not (project / "temp").exists()
        assert not (project / "test_old.log").exists()
        assert not (project / "test_new.log").exists()
        assert (project / "important.txt").exists()

    def test_apply_archive_automatically_cleans_noneeds(self, tmp_path):
        # 验证通过 apply_archive 执行更新包覆盖后，自动触发 .noneeds 清理
        project = tmp_path / "project"
        make_project(str(project), {
            "legacy_docs/faq.txt": "faq",
            "redundant.txt": "old",
            "essential.py": "keep",
        })

        # 准备更新压缩包，包内包含新版本代码和 .noneeds 清理清单
        update_zip = str(tmp_path / "update.zip")
        make_zip(update_zip, {
            "main.py": "# updated main\n",
            "lib/core.py": "# lib\n",
            NONEEDS_FILE: "legacy_docs/\nredundant.txt\n",
        })

        copied = apply_archive(update_zip, str(project))
        assert copied > 0
        # 确认冗余目录和文件已被自动清理
        assert not (project / "legacy_docs").exists()
        assert not (project / "redundant.txt").exists()
        assert (project / "essential.py").exists()
        assert (project / "main.py").exists()



