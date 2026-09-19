"""tests/test_security_audit.py — 依赖安全审计与已知 CVE 检测单元测试"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from lib.security_audit import (
    parse_requirements,
    get_installed_version,
    run_security_audit,
    _parse_version,
    VULNERABILITY_RULES,
)


class TestSecurityAudit(unittest.TestCase):
    def test_version_parsing(self):
        """测试版本比对逻辑"""
        self.assertTrue(_parse_version("11.1.0") >= _parse_version("11.1.0"))
        self.assertTrue(_parse_version("10.0.0") < _parse_version("11.1.0"))
        self.assertTrue(_parse_version("1.7.1") > _parse_version("1.7.0"))
        self.assertTrue(_parse_version("0.28.0") < _parse_version("1.0.0"))

    def test_parse_requirements_file(self):
        """测试 requirements.txt 文件解析"""
        content = """# Core requirements
Pillow>=10.0.0
websockets==12.0
websocket-client>=1.6.0
# Comment line

openai~=1.35.0
custom-pkg
"""
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".txt") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            reqs = parse_requirements(tmp_path)
            self.assertEqual(len(reqs), 5)
            names = [r["name"] for r in reqs]
            self.assertIn("Pillow", names)
            self.assertIn("websockets", names)
            self.assertIn("websocket-client", names)
            self.assertIn("openai", names)
            self.assertIn("custom-pkg", names)

            # 校验 spec 提取
            pillow_spec = next(r["spec"] for r in reqs if r["name"] == "Pillow")
            self.assertEqual(pillow_spec, ">=10.0.0")
            custom_spec = next(r["spec"] for r in reqs if r["name"] == "custom-pkg")
            self.assertEqual(custom_spec, "*")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_parse_requirements_nonexistent(self):
        """测试读取不存在的 requirements 文件"""
        reqs = parse_requirements("non_existent_file_xyz_123.txt")
        self.assertEqual(reqs, [])

    def test_get_installed_version_nonexistent(self):
        """测试未安装模块的版本获取返回 None"""
        ver = get_installed_version("package_that_definitely_does_not_exist_xyz123")
        self.assertIsNone(ver)

    def test_run_security_audit_with_vulnerable_package(self):
        """模拟存在低版本存在 CVE 漏洞的依赖包"""
        content = "Pillow==9.5.0\nwebsockets==10.0\n"
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".txt") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            with patch("lib.security_audit.get_installed_version") as mock_ver:
                def fake_ver(pkg):
                    if pkg.lower() == "pillow":
                        return "9.5.0"
                    if pkg.lower() == "websockets":
                        return "10.0.0"
                    return None
                mock_ver.side_effect = fake_ver

                report = run_security_audit(tmp_path)
                self.assertTrue(report["ok"])
                self.assertEqual(report["status"], "danger")
                self.assertEqual(report["summary"]["vulnerable_count"], 2)
                self.assertEqual(report["summary"]["missing_count"], 0)

                # 检查 Pillow 命中的漏洞详情
                pillow_info = next(p for p in report["packages"] if p["name"] == "Pillow")
                self.assertEqual(pillow_info["status"], "vulnerable")
                self.assertTrue(len(pillow_info["vulnerabilities"]) >= 1)
                cves = [c for v in pillow_info["vulnerabilities"] for c in v["cves"]]
                self.assertIn("CVE-2023-50447", cves)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_run_security_audit_with_safe_packages(self):
        """测试所有已安装包均高于安全阈值时的安全态势"""
        content = "Pillow>=11.1.0\nwebsockets>=12.0.0\n"
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".txt") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            with patch("lib.security_audit.get_installed_version") as mock_ver:
                mock_ver.side_effect = lambda pkg: "12.3.0" if pkg.lower() == "pillow" else "13.0.0"
                report = run_security_audit(tmp_path)
                self.assertTrue(report["ok"])
                self.assertEqual(report["status"], "safe")
                self.assertEqual(report["summary"]["vulnerable_count"], 0)
                self.assertEqual(report["summary"]["safe_count"], 2)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_run_security_audit_with_missing_package(self):
        """测试依赖未安装时报告 warning 状态"""
        content = "not-installed-pkg>=1.0.0\n"
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".txt") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            with patch("lib.security_audit.get_installed_version", return_value=None):
                report = run_security_audit(tmp_path)
                self.assertTrue(report["ok"])
                self.assertEqual(report["status"], "warning")
                self.assertEqual(report["summary"]["missing_count"], 1)
                self.assertEqual(report["summary"]["vulnerable_count"], 0)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_spec_satisfaction(self):
        """测试版本规范匹配函数 is_spec_satisfied"""
        from lib.security_audit import is_spec_satisfied
        self.assertTrue(is_spec_satisfied("12.3.0", "==12.3.0"))
        self.assertFalse(is_spec_satisfied("12.2.0", "==12.3.0"))
        self.assertTrue(is_spec_satisfied("12.2.0", ">=12.0.0"))
        self.assertFalse(is_spec_satisfied("11.9.0", ">=12.0.0"))
        self.assertTrue(is_spec_satisfied("1.35.0", "*"))
        self.assertFalse(is_spec_satisfied(None, "==1.0.0"))

    def test_run_security_audit_with_version_mismatch(self):
        """测试版本不符合要求但无 CVE 漏洞时报告 mismatch 状态"""
        from lib.security_audit import run_security_audit
        content = "Pillow==12.3.0\n"
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".txt") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            with patch("lib.security_audit.get_installed_version", return_value="12.2.0"):
                report = run_security_audit(tmp_path)
                self.assertTrue(report["ok"])
                self.assertEqual(report["status"], "warning")
                self.assertEqual(report["summary"]["mismatch_count"], 1)
                self.assertEqual(report["summary"]["safe_count"], 0)
                pillow_info = report["packages"][0]
                self.assertEqual(pillow_info["status"], "mismatch")
                self.assertFalse(pillow_info["spec_satisfied"])
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_real_project_requirements_audit(self):
        """对实际项目 requirements.txt 运行审计，确保不崩溃且环境信息健全"""
        report = run_security_audit()
        self.assertTrue(report["ok"])
        self.assertIn("status", report)
        self.assertIn("summary", report)
        self.assertIn("packages", report)
        self.assertIn("environment", report)
        self.assertIn("python_version", report["environment"])
        self.assertIn("platform", report["environment"])
        self.assertGreater(report["summary"]["total_packages"], 0)


if __name__ == "__main__":
    unittest.main()

