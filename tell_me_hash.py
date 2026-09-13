#!/usr/bin/env python3
"""密码哈希计算工具 —— 明文 → 密文

用法:
  python tell_me_hash.py                  # 交互式输入密码
  python tell_me_hash.py "my_password"    # 命令行直接传入
  python tell_me_hash.py -m pbkdf2        # 强制使用 PBKDF2-SHA256
  python tell_me_hash.py -m bcrypt        # 强制使用 bcrypt
  python tell_me_hash.py -v "明文" "哈希"  # 验证密码是否匹配
"""
import argparse
import hashlib
import os
import sys

# ===== bcrypt 可选依赖 =====
try:
    import bcrypt as _bcrypt
    _HAS_BCRYPT = True
except ImportError:
    _HAS_BCRYPT = False


def hash_bcrypt(password: str) -> str:
    """使用 bcrypt 哈希密码"""
    if not _HAS_BCRYPT:
        print("[错误] 未安装 bcrypt,请运行: pip install bcrypt", file=sys.stderr)
        sys.exit(1)
    return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


def hash_pbkdf2(password: str) -> str:
    """使用 PBKDF2-SHA256 哈希密码(stdlib,无额外依赖)"""
    salt = os.urandom(16).hex()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 260000)
    return f"pbkdf2:sha256:{salt}:{dk.hex()}"


def hash_auto(password: str) -> str:
    """自动选择:bcrypt 优先,不可用时回退 PBKDF2-SHA256"""
    if _HAS_BCRYPT:
        return hash_bcrypt(password)
    return hash_pbkdf2(password)


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码是否匹配哈希"""
    if not password_hash:
        return False
    if password_hash.startswith("$2") and _HAS_BCRYPT:
        return _bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    if password_hash.startswith("pbkdf2:"):
        parts = password_hash.split(":")
        if len(parts) == 4:
            _, algo, salt, dk_hex = parts
            digest = "sha256" if algo == "256" else algo
            dk = hashlib.pbkdf2_hmac(digest, password.encode("utf-8"), salt.encode("utf-8"), 260000)
            return dk.hex() == dk_hex
    return False


def main():
    parser = argparse.ArgumentParser(
        description="密码哈希计算工具 —— 明文 → 密文",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python tell_me_hash.py                 # 交互式\n"
               "  python tell_me_hash.py \"mypassword\"    # 命令行\n"
               "  python tell_me_hash.py -v \"pw\" \"hash\"  # 验证\n",
    )
    parser.add_argument("password", nargs="?", help="要哈希的明文密码(不传则交互式输入)")
    parser.add_argument("-m", "--method", choices=["auto", "bcrypt", "pbkdf2"], default="auto",
                        help="哈希算法:auto=自动选择(默认),bcrypt=强制bcrypt,pbkdf2=强制PBKDF2-SHA256")
    parser.add_argument("-v", "--verify", metavar="HASH",
                        help="验证模式:比较明文密码与指定哈希是否匹配")
    args = parser.parse_args()

    # ===== 验证模式 =====
    if args.verify:
        password = args.password
        if not password:
            password = input("请输入明文密码: ")
        if verify_password(password, args.verify):
            print("✅ 密码匹配!")
        else:
            print("❌ 密码不匹配!")
            sys.exit(1)
        return

    # ===== 哈希模式 =====
    password = args.password
    if not password:
        password = input("请输入明文密码: ")

    if not password:
        print("[错误] 密码不能为空", file=sys.stderr)
        sys.exit(1)

    # 选择算法
    if args.method == "bcrypt":
        result = hash_bcrypt(password)
        algo = "bcrypt"
    elif args.method == "pbkdf2":
        result = hash_pbkdf2(password)
        algo = "PBKDF2-SHA256"
    else:
        result = hash_auto(password)
        algo = "bcrypt" if result.startswith("$2") else "PBKDF2-SHA256"

    print(f"算法:   {algo}")
    print(f"密文:   {result}")
    print()

    # 显示兼容性提示
    if result.startswith("$2"):
        print("💡 以 $2 开头 → bcrypt 格式,可直接用于 EnderBridge")
    elif result.startswith("pbkdf2:"):
        print("💡 以 pbkdf2: 开头 → PBKDF2 格式,可直接用于 EnderBridge")


if __name__ == "__main__":
    main()
