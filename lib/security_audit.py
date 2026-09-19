"""lib/security_audit.py — EnderBridge 依赖库安全性审计与已知 CVE 漏洞检测模块"""

import os
import re
import sys
from typing import Dict, List, Optional, Any

try:
    from packaging.version import parse as _parse_version
except ImportError:
    def _parse_version(v: str):
        nums = [int(x) for x in re.findall(r"\d+", str(v))]
        return tuple(nums) if nums else (0,)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS_FILE = os.path.join(ROOT, "requirements.txt")

# 针对 EnderBridge 依赖维护的已知安全漏洞与 CVE 规则库
VULNERABILITY_RULES = [
    {
        "package": "Pillow",
        "vulnerable_below": "11.1.0",
        "severity": "high",
        "cves": ["CVE-2023-50447", "CVE-2024-28219", "CVE-2024-46982"],
        "title": "LibTIFF 缓冲区溢出 / 环境变量代码执行漏洞",
        "recommendation": "升级至 Pillow >= 11.1.0 (推荐 12.3.0)",
    },
    {
        "package": "Pillow",
        "vulnerable_below": "10.0.1",
        "severity": "medium",
        "cves": ["CVE-2023-44271"],
        "title": "特殊字体渲染导致 DoS 拒绝服务",
        "recommendation": "升级至 Pillow >= 10.0.1",
    },
    {
        "package": "websockets",
        "vulnerable_below": "11.0.3",
        "severity": "high",
        "cves": ["CVE-2023-46136"],
        "title": "握手标头超大内存消耗 DoS 漏洞",
        "recommendation": "升级至 websockets >= 11.0.3 (推荐 13.1 或更高)",
    },
    {
        "package": "websocket-client",
        "vulnerable_below": "1.7.0",
        "severity": "medium",
        "cves": ["CVE-2024-21668"],
        "title": "代理认证凭据重定向未过滤明文泄露",
        "recommendation": "升级至 websocket-client >= 1.7.0",
    },
    {
        "package": "bcrypt",
        "vulnerable_below": "4.0.0",
        "severity": "medium",
        "cves": ["GHSA-9rq5-rw6w-8355"],
        "title": "旧版密码哈希在特殊空字符下的截断隐患",
        "recommendation": "升级至 bcrypt >= 4.0.0",
    },
    {
        "package": "openai",
        "vulnerable_below": "1.0.0",
        "severity": "low",
        "cves": ["LEGACY-SDK-V0"],
        "title": "Legacy 0.x 旧版本 SDK 官方已停止安全维护",
        "recommendation": "升级至 openai >= 1.35.0",
    },
]


def get_installed_version(pkg_name: str) -> Optional[str]:
    """获取已安装包的版本号，未安装返回 None"""
    try:
        import importlib.metadata
        return importlib.metadata.version(pkg_name)
    except Exception:
        pass
    # 回退尝试直接 import 模块
    try:
        mod = __import__(pkg_name.replace("-", "_").lower())
        return getattr(mod, "__version__", None)
    except Exception:
        return None


def parse_requirements(filepath: Optional[str] = None) -> List[Dict[str, str]]:
    """解析 requirements.txt，提取包名和版本规范"""
    path = filepath or REQUIREMENTS_FILE
    results = []
    if not os.path.exists(path):
        return results

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # 匹配 package==version 或 package>=version 等
            match = re.match(r"^([A-Za-z0-9_\-\.]+)\s*([=><~^!].*)?$", line)
            if match:
                name = match.group(1).strip()
                spec = (match.group(2) or "").strip()
                results.append({"name": name, "spec": spec or "*"})
    return results


def is_spec_satisfied(installed_ver: Optional[str], spec: str) -> bool:
    """检查安装版本是否符合 requirements.txt 中的规范要求"""
    if not installed_ver:
        return False
    if not spec or spec == "*":
        return True
    try:
        from packaging.specifiers import SpecifierSet
        return SpecifierSet(spec).contains(installed_ver)
    except Exception:
        pass

    # 备用轻量比较器
    try:
        m = re.match(r"^([=><~^!]+)\s*([A-Za-z0-9_\-\.]+)$", spec.strip())
        if not m:
            return True
        op, req_v = m.group(1), m.group(2)
        v_inst = _parse_version(installed_ver)
        v_req = _parse_version(req_v)
        if op in ("==", "==="):
            return v_inst == v_req
        elif op == ">=":
            return v_inst >= v_req
        elif op == "<=":
            return v_inst <= v_req
        elif op == ">":
            return v_inst > v_req
        elif op == "<":
            return v_inst < v_req
        elif op == "!=":
            return v_inst != v_req
        elif op == "~=":
            return v_inst >= v_req
    except Exception:
        pass
    return True


def run_security_audit(req_file: Optional[str] = None) -> Dict[str, Any]:
    """执行依赖项健康检查、版本规范符合性与 CVE 漏洞比对，返回完整审计报告"""
    reqs = parse_requirements(req_file)
    packages_report = []
    total_vulns = 0
    missing_count = 0
    mismatch_count = 0

    for item in reqs:
        name = item["name"]
        spec = item["spec"]
        installed_ver = get_installed_version(name)

        matched_vulns = []
        status = "safe"
        spec_ok = True

        if installed_ver is None:
            status = "missing"
            spec_ok = False
            missing_count += 1
        else:
            spec_ok = is_spec_satisfied(installed_ver, spec)
            # 比对漏洞库
            for rule in VULNERABILITY_RULES:
                if rule["package"].lower() == name.lower():
                    threshold = rule["vulnerable_below"]
                    try:
                        if _parse_version(installed_ver) < _parse_version(threshold):
                            matched_vulns.append({
                                "severity": rule["severity"],
                                "cves": rule["cves"],
                                "title": rule["title"],
                                "recommendation": rule["recommendation"],
                            })
                    except Exception:
                        pass

            if matched_vulns:
                status = "vulnerable"
                total_vulns += len(matched_vulns)
            elif not spec_ok:
                status = "mismatch"
                mismatch_count += 1

        packages_report.append({
            "name": name,
            "installed": installed_ver is not None,
            "version": installed_ver or "",
            "spec": spec,
            "spec_satisfied": spec_ok,
            "status": status,
            "vulnerabilities": matched_vulns,
        })

    # 计算总体安全评估等级
    if total_vulns > 0:
        overall_status = "danger" if any(v["severity"] == "high" for p in packages_report for v in p["vulnerabilities"]) else "warning"
    elif missing_count > 0 or mismatch_count > 0:
        overall_status = "warning"
    else:
        overall_status = "safe"

    return {
        "ok": True,
        "status": overall_status,
        "summary": {
            "total_packages": len(packages_report),
            "safe_count": sum(1 for p in packages_report if p["status"] == "safe"),
            "vulnerable_count": sum(1 for p in packages_report if p["status"] == "vulnerable"),
            "mismatch_count": mismatch_count,
            "missing_count": missing_count,
            "total_vulnerabilities": total_vulns,
        },
        "packages": packages_report,
        "environment": {
            "python_version": sys.version.split()[0],
            "platform": sys.platform,
        },
    }

