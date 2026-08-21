#!/usr/bin/env python3
# ============================================================
#  setup.py - 依赖安装器(用于空包主机)
# ------------------------------------------------------------
#  空包主机 = 只有项目文件、没有第三方库的环境
#  (例如直接从 GitHub 下载 zip 解压后运行)
#
#  用法:
#    python setup.py           检测依赖,缺失时自动 pip install
#    python setup.py --check   仅检测不安装(齐全退出 0,缺失退出 1)
#
#  main.py 在直接运行时也会在缺失依赖时调用本脚本。
# ============================================================
import importlib.util
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ONLY_CHECK = "--check" in sys.argv

REQUIREMENTS = os.path.join(ROOT, "requirements.txt")

# 依赖名 -> 检测用的导入名(处理包名与导入名不一致的情况)
IMPORT_NAMES = {
    "websockets": "websockets",
    "Pillow": "PIL",
    "mido": "mido",
    "openai": "openai",
    "websocket-client": "websocket",
}


def load_requirements():
    """读取 requirements.txt,失败则退出"""
    try:
        deps = []
        with open(REQUIREMENTS, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # 去掉版本约束
                name = line.split("==")[0].split(">=")[0].split("<")[0].split("~=")[0].strip()
                if name:
                    deps.append(name)
        return deps
    except Exception as e:
        print(f"无法读取 requirements.txt: {e}")
        sys.exit(1)


def is_installed(dep):
    """检测单个依赖是否真正可导入(最接近真实运行环境)"""
    import_name = IMPORT_NAMES.get(dep, dep)
    try:
        return importlib.util.find_spec(import_name) is not None
    except (ImportError, ValueError):
        return False


def has_pip():
    """检测 pip 是否可用"""
    res = subprocess.run(
        [sys.executable, "-m", "pip", "--version"],
        capture_output=True,
        text=True,
    )
    return res.returncode == 0


def main():
    deps = load_requirements()
    print(f"检测到 {len(deps)} 个依赖: {', '.join(deps)}")

    missing = [d for d in deps if not is_installed(d)]

    if not missing:
        print("依赖已齐全，无需安装")
        sys.exit(0)

    print(f"缺少 {len(missing)} 个依赖: {', '.join(missing)}")

    if ONLY_CHECK:
        print("依赖不完整（--check 模式，不执行安装）")
        sys.exit(1)

    if not has_pip():
        print("未检测到 pip，请先安装 Python（https://www.python.org）后再试")
        sys.exit(1)

    print("正在执行 pip install -r requirements.txt（首次安装可能需要几分钟）...")
    res = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", REQUIREMENTS],
        cwd=ROOT,
    )

    if res.returncode != 0:
        print(f"pip install 失败（退出码 {res.returncode}），请手动运行 pip install -r requirements.txt 查看详细报错")
        sys.exit(1)

    # 安装后二次验证
    still_missing = [d for d in deps if not is_installed(d)]
    if still_missing:
        print(f"安装完成后仍缺少: {', '.join(still_missing)}")
        sys.exit(1)

    print("========================================")
    print("  依赖安装完成，可以启动服务器了")
    print("  运行: python main.py")
    print("========================================")
    sys.exit(0)


if __name__ == "__main__":
    main()
