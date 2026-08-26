# Author: Hydrooxzgen
# Github: https://github.com/Hydrooxzgen
# This project uses the GPL-3.0 license, you can modify/distribute this project according to the GPL-3.0 license
import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
from uuid import uuid4

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PY = os.path.join(ROOT, "config.py")
CONFIG_EXAMPLE = os.path.join(ROOT, "config.example.py")
VERSION = "b0.3.0"
DESCRIPTION = None # 仅当不为None时从Github拉取更新日志，反之则直接显示该变量内容。
GITHUB_REPO = "Hydrooxzgen/EnderBridge"  # You can edit this to your own repository if you fork it :)
WANT_RESET = "--reset-all" in sys.argv
WANT_EXPORT = "export" in sys.argv
WANT_EXPORT_CLEAR = WANT_EXPORT and "-clear" in sys.argv
WANT_LOAD_WITHOUT_CONFIG = "--load-without-config" in sys.argv

# ===== 依赖检测(必须早于任何第三方模块使用) =====
# websockets 使用动态导入:缺失时自动运行 setup.py 安装,成功后继续启动。
def _dependencies_ok() -> bool:
    try:
        import websockets  # noqa: F401
        return True
    except ImportError:
        return False


def _run_setup() -> None:
    print("========================================")
    print("  检测到缺少依赖，正在安装依赖...")
    print("========================================")
    res = subprocess.run([sys.executable, "setup.py"], cwd=ROOT)
    if res.returncode != 0:
        print("依赖安装失败，请手动运行 python setup.py 排查")
        sys.exit(1)
    # 安装成功后重新尝试导入
    try:
        import websockets  # noqa: F401
    except ImportError as e:
        print(f"依赖安装后仍无法加载: {e}")
        sys.exit(1)


if not WANT_RESET and not WANT_EXPORT and not _dependencies_ok():
    _run_setup()

# ===== 引导阶段(必须早于任何依赖 config.py 的模块加载) =====
# 依赖 config.py 的模块(lib/logger.py、lib/utils.py、lib/mods.py 等)均为延迟加载,
# 因此 config.py 缺失时(如 --reset-all 之后)可先在此根据模板自动补全,保证程序可启动。
if not WANT_RESET and not os.path.exists(CONFIG_PY):
    with open(CONFIG_EXAMPLE, "r", encoding="utf-8") as f:
        tpl = f.read()
    if WANT_LOAD_WITHOUT_CONFIG:
        # --load-without-config:直接使用模板全部内容(含 is_first_run),后续跳过向导
        cfg = tpl
    else:
        # config.py 只存真实配置:剔除模板携带的 isFirstRun 标记块
        cfg = re.sub(
            r"# ===== 首次运行 =====[\s\S]*?is_first_run = (True|False)\r?\n(\r?\n)?",
            "",
            tpl,
        )
    with open(CONFIG_PY, "w", encoding="utf-8") as f:
        f.write(cfg)
    print("未找到 config.py，已根据模板自动生成默认配置（可在向导中修改）")

# permission.json 缺失时从模板复制(权限系统依赖该文件)
PERMISSION_JSON = os.path.join(ROOT, "permission.json")
PERMISSION_EXAMPLE = os.path.join(ROOT, "permission.example.json")
if not WANT_RESET and not os.path.exists(PERMISSION_JSON) and os.path.exists(PERMISSION_EXAMPLE):
    with open(PERMISSION_EXAMPLE, "r", encoding="utf-8") as f:
        content = f.read()
    with open(PERMISSION_JSON, "w", encoding="utf-8") as f:
        f.write(content)
    print("未找到 permission.json，已根据模板自动生成默认权限配置")

# ===== 一键重置:python main.py --reset-all =====
# 清除所有配置文件(不启动服务器),并将模板 config.example.py 的 is_first_run 复位为 True
if WANT_RESET:
    files = ["config.py", "config.py.bak", "permission.json", "permission.json.bak"]
    removed = []
    for name in files:
        p = os.path.join(ROOT, name)
        if os.path.exists(p):
            os.remove(p)
            removed.append(name)
    # 复位模板标记,下次启动自动进入向导重新配置
    try:
        with open(CONFIG_EXAMPLE, "r", encoding="utf-8") as f:
            src = f.read()
        next_ = re.sub(r"is_first_run = (True|False)", "is_first_run = True", src)
        if next_ != src:
            with open(CONFIG_EXAMPLE, "w", encoding="utf-8") as f:
                f.write(next_)
    except Exception:
        # 模板不可写时静默忽略
        pass
    print("========================================")
    print("  配置已重置")
    print("========================================")
    sys.exit(0)

# ===== 一键升级:python main.py update <新版本压缩包> =====
# 从压缩包(zip / tar.gz)升级当前版本,保留 config.py / permission.json
# 等设置与 resources / structures / logs 等用户数据,完成后退出不启动服务器。
WANT_UPDATE = "update" in sys.argv
if WANT_UPDATE:
    import shutil
    import tarfile
    import tempfile
    import zipfile

    # 数据区/设置文件:升级时跳过,不覆盖不删除
    UPDATE_KEEP = {
        ".git",
        "logs",
        "resources",
        "structures",
        "config.py",
        "config.py.bak",
        "permission.json",
        "permission.json.bak",
    }

    def _load_github_token() -> str:
        """从 config.py 读取 GitHub API Token（用于减少速率限制）"""
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("_cfg_token", CONFIG_PY)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return getattr(mod, "githubToken", "") or ""
        except Exception:
            return ""

    def _github_headers() -> dict:
        """返回 GitHub API 请求头,附带 Token 认证（若有）"""
        headers = {"Accept": "application/vnd.github.v3+json"}
        token = _load_github_token()
        if token:
            headers["Authorization"] = f"token {token}"
        return headers

    def _update_err(msg):
        print("========================================")
        print(f"  升级失败: {msg}")
        print("  当前版本未做任何改动,可继续正常启动")
        print("========================================")
        sys.exit(1)

    def _update_member_name(name):
        """规范化压缩包成员路径,过滤路径穿越,返回相对路径或 None"""
        norm = os.path.normpath(name.replace("\\", "/"))
        if not norm or norm == ".":
            return None
        if norm.startswith("..") or os.path.isabs(norm):
            return None
        return norm.replace(os.sep, "/")

    def _update_common_root(names):
        """GitHub 风格压缩包内含顶层目录(如 EnderBridge-main/),探测并剥离"""
        files = [n for n in names if n]
        if not files:
            return ""
        roots = {n.split("/", 1)[0] for n in files}
        if len(roots) == 1 and all("/" in n for n in files):
            return roots.pop()
        return ""

    def _update_archive_members(archive):
        """迭代压缩包成员,产出 (相对路径, 文件对象)"""
        lower = archive.lower()
        if lower.endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                names = [i.filename for i in z.infolist() if not i.is_dir()]
                root = _update_common_root(names)
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    rel = _update_member_name(info.filename)
                    if rel is None:
                        continue
                    if root:
                        if not rel.startswith(root + "/"):
                            continue
                        rel = rel[len(root) + 1:]
                    if not rel:
                        continue
                    yield rel, z.open(info)
        elif lower.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tar")):
            with tarfile.open(archive, "r:*") as t:
                names = [m.name for m in t.getmembers() if m.isfile()]
                root = _update_common_root(names)
                for m in t.getmembers():
                    if not m.isfile():
                        continue
                    rel = _update_member_name(m.name)
                    if rel is None:
                        continue
                    if root:
                        if not rel.startswith(root + "/"):
                            continue
                        rel = rel[len(root) + 1:]
                    if not rel:
                        continue
                    yield rel, t.extractfile(m)
        else:
            _update_err(f"不支持的压缩包格式: {archive}（仅支持 zip / tar.gz）")

    def _do_update(archive, new_version=None):
        if not os.path.isfile(archive):
            _update_err(f"找不到压缩包: {archive}")

        print("========================================")
        print(f"  正在升级 EnderBridge ...")
        print(f"  当前版本: {VERSION}")
        if new_version:
            print(f"  目标版本: {new_version}")
        print(f"  压缩包: {archive}")
        print("========================================")

        # 1. 先探测压缩包内容,校验为 EnderBridge 项目
        members = []
        try:
            for rel, _f in _update_archive_members(archive):
                members.append(rel)
        except Exception as e:
            _update_err(f"读取压缩包失败: {e}")
        if "main.py" not in members:
            _update_err("压缩包内未找到 main.py,不是 EnderBridge 压缩包")

        # 2. 解压到临时目录(跳过数据区)
        tmp = tempfile.mkdtemp(prefix="enderbridge_update_")
        try:
            for rel, fobj in _update_archive_members(archive):
                top = rel.split("/", 1)[0]
                if top in UPDATE_KEEP:
                    continue
                target = os.path.join(tmp, *rel.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as out:
                    shutil.copyfileobj(fobj, out)

            # 3. 校验解压结果
            if not os.path.exists(os.path.join(tmp, "main.py")):
                _update_err("解压后未找到 main.py")
            if not os.path.exists(os.path.join(tmp, "lib")):
                _update_err("解压后未找到 lib 目录")

            # 4. 覆盖到项目根目录(跳过数据区,不清除多余文件以保留自定义内容)
            copied = 0
            for dirpath, dirnames, filenames in os.walk(tmp):
                rel_dir = os.path.relpath(dirpath, tmp)
                for fname in filenames:
                    src = os.path.join(dirpath, fname)
                    dst = os.path.join(ROOT, rel_dir, fname)
                    if rel_dir.split(os.sep)[0] in UPDATE_KEEP:
                        continue
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    copied += 1
            print(f"  已覆盖 {copied} 个文件")

            # 5. 更新版本号
            if new_version:
                main_path = os.path.join(ROOT, "main.py")
                try:
                    with open(main_path, "r", encoding="utf-8") as f:
                        src = f.read()
                    new_src = re.sub(
                        r'^VERSION\s*=\s*"[^"]*"',
                        f'VERSION = "{new_version}"',
                        src,
                        count=1,
                        flags=re.MULTILINE,
                    )
                    if new_src != src:
                        with open(main_path, "w", encoding="utf-8") as f:
                            f.write(new_src)
                        print(f"  版本号已更新: {VERSION} → {new_version}")
                except Exception as e:
                    print(f"  警告: 版本号更新失败 ({e}),请手动修改 VERSION")

            # 6. 重新生成 requirements.txt 缺失依赖的自动安装由下次启动完成
            print("========================================")
            print("  升级完成!")
            print("  已保留: config.py / permission.json 等设置与用户数据")
            print("  请重新启动: py -B main.py")
            print("========================================")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        sys.exit(0)

    def _download_release(tag=None):
        """从 GitHub Releases 下载压缩包,返回本地临时文件路径

        Args:
            tag: 版本标签(如 "b0.1.0"),None 表示最新版本
        """
        import urllib.parse
        import urllib.request
        import urllib.error

        if tag:
            api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/{urllib.parse.quote(tag)}"
        else:
            # releases/latest 只返回正式版;仓库最新版本为预览版(prerelease)时会返回 404,
            # 改用列表接口取最新一条(含预览版),与 WebUI 检查更新保持一致。
            api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=1"

        print(f"  正在查询 GitHub Releases ...")
        print(f"  API: {api_url}")

        # 1. 查询 release 信息
        try:
            req = urllib.request.Request(api_url, headers=_github_headers())
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                # 列表接口返回数组,取最新一条
                if not data:
                    _update_err(f"GitHub 上未找到版本 latest\n  仓库: {GITHUB_REPO}")
                data = data[0]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                ver = tag or "latest"
                _update_err(f"GitHub 上未找到版本 {ver}\n  仓库: {GITHUB_REPO}")
            _update_err(f"查询 GitHub Releases 失败: {e}")
        except Exception as e:
            _update_err(f"网络请求失败: {e}")

        release_tag = data.get("tag_name", "unknown")
        release_name = data.get("name") or release_tag
        print(f"  版本: {release_name} ({release_tag})")

        # 2. 查找 zip 或 tar.gz 资源
        assets = data.get("assets", [])
        asset = None
        for a in assets:
            name = a.get("name", "").lower()
            if name.endswith(".zip") or name.endswith((".tar.gz", ".tgz")):
                asset = a
                break

        if not asset:
            _update_err(f"版本 {release_tag} 中未找到 zip/tar.gz 压缩包资源")

        download_url = asset["browser_download_url"]
        asset_name = asset["name"]
        print(f"  资源: {asset_name}")
        print(f"  下载: {download_url}")

        # 3. 下载到临时文件
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=os.path.splitext(asset_name)[1], prefix="enderbridge_dl_")
        try:
            print(f"  正在下载 ...")
            req = urllib.request.Request(download_url, headers=_github_headers())
            with urllib.request.urlopen(req, timeout=120) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                with os.fdopen(tmp_fd, "wb") as f:
                    tmp_fd = -1  # fdopen 会接管关闭
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = downloaded * 100 // total
                            sys.stdout.write(f"\r  下载进度: {pct}% ({downloaded}/{total})")
                            sys.stdout.flush()
                if total:
                    print()  # 换行
            print(f"  下载完成: {tmp_path}")
            return tmp_path
        except Exception as e:
            if tmp_fd >= 0:
                os.close(tmp_fd)
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            _update_err(f"下载失败: {e}")

    def _download_commit(ref=None):
        """从 GitHub 下载指定 commit 的源码压缩包

        Args:
            ref: commit SHA 或分支名(如 "abc1234","HEAD","main"),None 表示默认分支最新
        Returns:
            (本地临时文件路径, 版本号字符串)
        """
        import urllib.parse
        import urllib.request
        import urllib.error

        ref = ref or "HEAD"

        # 1. 解析 ref → 获取 commit 信息
        if ref.upper() == "HEAD" or ref == "":
            # 获取默认分支最新 commit
            api_url = f"https://api.github.com/repos/{GITHUB_REPO}/commits/HEAD"
        else:
            api_url = f"https://api.github.com/repos/{GITHUB_REPO}/commits/{urllib.parse.quote(ref)}"

        print(f"  正在查询 GitHub Commits ...")
        print(f"  API: {api_url}")

        try:
            req = urllib.request.Request(api_url, headers=_github_headers())
            with urllib.request.urlopen(req, timeout=30) as resp:
                commit_data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                _update_err(f"GitHub 上未找到 commit: {ref}\n  仓库: {GITHUB_REPO}")
            _update_err(f"查询 GitHub Commits 失败: {e}")
        except Exception as e:
            _update_err(f"网络请求失败: {e}")

        sha = commit_data["sha"]
        short_sha = sha[:7]
        commit_msg = commit_data.get("commit", {}).get("message", "").split("\n")[0]
        print(f"  Commit: {short_sha} - {commit_msg}")

        # 2. 检查此 commit 是否有 tag
        version = None
        try:
            tags_url = f"https://api.github.com/repos/{GITHUB_REPO}/tags"
            req = urllib.request.Request(tags_url, headers=_github_headers())
            with urllib.request.urlopen(req, timeout=30) as resp:
                tags = json.loads(resp.read().decode("utf-8"))
            for tag in tags:
                tag_sha = tag.get("commit", {}).get("sha", "")
                if tag_sha == sha:
                    version = tag["name"]
                    print(f"  已关联 Tag: {version}")
                    break
        except Exception:
            pass

        if not version:
            version = short_sha
            print(f"  无关联 Tag,使用 Commit ID: {version}")

        # 3. 下载源码压缩包(zipball)
        download_url = f"https://api.github.com/repos/{GITHUB_REPO}/zipball/{sha}"
        print(f"  下载: {download_url}")

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip", prefix="enderbridge_commit_")
        try:
            print(f"  正在下载 ...")
            req = urllib.request.Request(download_url, headers=_github_headers())
            with urllib.request.urlopen(req, timeout=120) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                with os.fdopen(tmp_fd, "wb") as f:
                    tmp_fd = -1
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = downloaded * 100 // total
                            sys.stdout.write(f"\r  下载进度: {pct}% ({downloaded}/{total})")
                            sys.stdout.flush()
                if total:
                    print()
            print(f"  下载完成: {tmp_path}")
            return tmp_path, version
        except Exception as e:
            if tmp_fd >= 0:
                os.close(tmp_fd)
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            _update_err(f"下载失败: {e}")

    # update 命令解析
    if "--local" in sys.argv:
        # 本地更新:py main.py update --local <压缩包>
        idx = sys.argv.index("--local")
        if len(sys.argv) > idx + 1:
            _do_update(sys.argv[idx + 1])
        else:
            _update_err("用法: python main.py update --local <新版本压缩包路径>")
    elif "--online" in sys.argv:
        idx = sys.argv.index("--online")
        rest = sys.argv[idx + 1:]

        if rest and rest[0].lower() == "commit":
            # commit 模式:py main.py update --online commit [HEAD|commitID]
            ref = rest[1] if len(rest) > 1 else None
            dl_path, new_ver = _download_commit(ref)
            try:
                _do_update(dl_path, new_version=new_ver)
            finally:
                try:
                    os.unlink(dl_path)
                except Exception:
                    pass
        else:
            # release 模式:py main.py update --online [release] [版本号]
            tag = None
            if rest:
                if rest[0].lower() == "release":
                    if len(rest) > 1:
                        tag = rest[1]
                else:
                    tag = rest[0]
            dl_path = _download_release(tag)
            try:
                _do_update(dl_path, new_version=tag)
            finally:
                try:
                    os.unlink(dl_path)
                except Exception:
                    pass
    elif len(sys.argv) > sys.argv.index("update") + 1:
        # 无标志但有参数:py main.py update <压缩包> → 当作 --local
        _do_update(sys.argv[sys.argv.index("update") + 1])
    else:
        # 无参数:默认从 GitHub 下载最新 release
        dl_path = _download_release()
        try:
            _do_update(dl_path)
        finally:
            try:
                os.unlink(dl_path)
            except Exception:
                pass

# ===== WebUI 触发的更新:检测 .update_pending 标记文件 =====
UPDATE_MARKER = os.path.join(ROOT, ".update_pending")
if os.path.isfile(UPDATE_MARKER) and not WANT_UPDATE:
    # WebUI 写入了待更新的压缩包路径,立即执行更新
    try:
        with open(UPDATE_MARKER, "r", encoding="utf-8") as f:
            pending_path = f.read().strip()
    except Exception:
        pending_path = ""
    finally:
        try:
            os.remove(UPDATE_MARKER)
        except Exception:
            pass
    if pending_path and os.path.isfile(pending_path):
        import shutil
        import tarfile
        import tempfile
        import zipfile

        # 复用 UPDATE_KEEP(如果 WANT_UPDATE 已定义)或使用默认值
        _keep = locals().get("UPDATE_KEEP", {
            ".git", "logs", "resources", "structures",
            "config.py", "config.py.bak", "permission.json", "permission.json.bak",
        })

        print("========================================")
        print(f"  WebUI 触发更新: {pending_path}")
        print(f"  当前版本: {VERSION}")
        print("========================================")

        try:
            tmp = tempfile.mkdtemp(prefix="enderbridge_webui_update_")
            lower = pending_path.lower()

            def _safe_rel(name: str) -> str:
                """规范化成员路径,过滤路径穿越,返回相对路径或空字符串"""
                norm = os.path.normpath(name.replace("\\", "/"))
                if not norm or norm == ".":
                    return ""
                if norm.startswith("..") or os.path.isabs(norm):
                    return ""
                return norm.replace(os.sep, "/")

            if lower.endswith(".zip"):
                with zipfile.ZipFile(pending_path) as z:
                    names = [i.filename for i in z.infolist() if not i.is_dir()]
                    # 检测公共根目录
                    roots = {n.split("/", 1)[0] for n in names if "/" in n}
                    root = roots.pop() if len(roots) == 1 and all("/" in n for n in names) else ""
                    for info in z.infolist():
                        if info.is_dir():
                            continue
                        rel = _safe_rel(info.filename)
                        if not rel:
                            continue
                        if root and rel.startswith(root + "/"):
                            rel = rel[len(root) + 1:]
                        if not rel:
                            continue
                        top = rel.split("/", 1)[0]
                        if top in _keep:
                            continue
                        target = os.path.join(tmp, *rel.split("/"))
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        with open(target, "wb") as out:
                            with z.open(info) as src:
                                shutil.copyfileobj(src, out)
            elif lower.endswith((".tar.gz", ".tgz", ".tar")):
                with tarfile.open(pending_path, "r:*") as t:
                    names = [m.name for m in t.getmembers() if m.isfile()]
                    roots = {n.split("/", 1)[0] for n in names if "/" in n}
                    root = roots.pop() if len(roots) == 1 and all("/" in n for n in names) else ""
                    for m in t.getmembers():
                        if not m.isfile():
                            continue
                        rel = _safe_rel(m.name)
                        if not rel:
                            continue
                        if root and rel.startswith(root + "/"):
                            rel = rel[len(root) + 1:]
                        if not rel:
                            continue
                        top = rel.split("/", 1)[0]
                        if top in _keep:
                            continue
                        target = os.path.join(tmp, *rel.split("/"))
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        with open(target, "wb") as out:
                            src = t.extractfile(m)
                            if src is not None:
                                shutil.copyfileobj(src, out)
            else:
                print("  不支持的格式,仅支持 .zip / .tar.gz")
                sys.exit(1)

            if not os.path.exists(os.path.join(tmp, "main.py")):
                print("  压缩包内未找到 main.py,不是 EnderBridge 压缩包")
                sys.exit(1)

            # 覆盖到项目目录
            copied = 0
            for dirpath, dirnames, filenames in os.walk(tmp):
                rel_dir = os.path.relpath(dirpath, tmp)
                for fname in filenames:
                    src = os.path.join(dirpath, fname)
                    dst = os.path.join(ROOT, rel_dir, fname)
                    top = rel_dir.split(os.sep)[0]
                    if top in _keep:
                        continue
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    copied += 1
            print(f"  已覆盖 {copied} 个文件")
            print("  文件已覆盖,正在重启以加载新版本...")
            # 覆盖完成后磁盘上已是新版本代码,但内存中仍是旧代码
            # 需要再启动一次新进程,让新代码正确加载并显示版本号
            # (.update_pending 已在上方删除,新进程不会重复执行更新)
            # 等待端口释放:旧进程的 destroy() 已关闭服务器,但 Windows 上
            # TCP 端口可能仍在 TIME_WAIT 状态,需等待 OS 回收后新进程才能绑端口
            print("  等待端口释放...")
            time.sleep(3)
            try:
                import subprocess
                subprocess.Popen([sys.executable] + sys.argv, cwd=ROOT)
            except Exception as e:
                print(f"  重启失败: {e},请手动重启服务器")
            # os._exit 跳过 atexit/finalizer,避免终端残留状态导致新进程无法输入
            os._exit(0)
        except Exception as e:
            print(f"  更新失败: {e}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

# ===== 一键导出:python main.py export [输出路径] =====
# 将项目代码打包为 zip(排除用户数据/设置,与 update 命令的保留规则对称),
# 生成的压缩包可直接用于:python main.py update <压缩包> 升级其他实例。
if WANT_EXPORT:
    import zipfile
    from datetime import datetime

    # 与 update 命令的 UPDATE_KEEP 保持一致:用户数据/设置不打包
    EXPORT_EXCLUDE = {
        ".git",
        "logs",
        "resources",
        "structures",
        "config.py",
        "config.py.bak",
        "permission.json",
        "permission.json.bak",
    }
    EXPORT_SKIP_DIRS = {"__pycache__"}
    EXPORT_SKIP_EXTS = {".pyc", ".pyo"}

    def _export_err(msg):
        print("======================================")
        print(f"  导出失败: {msg}")
        print("======================================")
        sys.exit(1)

    def _iter_export_files():
        """遍历项目内需打包的文件,产出 (压缩包相对路径, 绝对路径)"""
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [
                d for d in dirnames
                if d not in EXPORT_EXCLUDE and d not in EXPORT_SKIP_DIRS
            ]
            rel_dir = os.path.relpath(dirpath, ROOT)
            rel_dir = "" if rel_dir == "." else rel_dir
            for fname in filenames:
                if os.path.splitext(fname)[1].lower() in EXPORT_SKIP_EXTS:
                    continue
                rel = os.path.join(rel_dir, fname) if rel_dir else fname
                rel = rel.replace(os.sep, "/")
                if rel.split("/", 1)[0] in EXPORT_EXCLUDE:
                    continue
                yield rel, os.path.join(dirpath, fname)

    # 输出路径:默认当前工作目录 EnderBridge_export_<时间戳>.zip
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_name = f"EnderBridge_export_{stamp}.zip"
    if len(sys.argv) > sys.argv.index("export") + 1:
        out = os.path.abspath(sys.argv[sys.argv.index("export") + 1])
        # 若路径是目录或不以 .zip 结尾,自动在其下生成默认文件名
        if os.path.isdir(out) or not out.lower().endswith(".zip"):
            out = os.path.join(out, default_name)
    else:
        out = os.path.abspath(os.path.join(os.getcwd(), default_name))

    # 输出文件不能位于项目目录内,否则会把自己打进压缩包
    if out == ROOT or out.startswith(ROOT + os.sep):
        _export_err("输出路径不能位于项目目录内,请放到上级目录或指定其他位置")

    files = list(_iter_export_files())
    if not files:
        _export_err("未找到可导出的文件")

    print("======================================")
    print(f"  正在导出 EnderBridge ...")
    print(f"  文件数量: {len(files)}")
    print(f"  输出路径: {out}")
    print("======================================")

    os.makedirs(os.path.dirname(out), exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, abspath in files:
            z.write(abspath, rel)

    size_kb = os.path.getsize(out) / 1024.0
    print("======================================")
    print(f"  导出完成: {out} ({size_kb:.1f} KB)")
    print(f"  使用方法: python main.py update {out}")
    print("======================================")
    # export -clear:导出后自动执行 reset-all
    if WANT_EXPORT_CLEAR:
        print("  正在执行 --reset-all ...")
        for name in ["config.py", "config.py.bak", "permission.json", "permission.json.bak"]:
            p = os.path.join(ROOT, name)
            if os.path.exists(p):
                os.remove(p)
        try:
            with open(CONFIG_EXAMPLE, "r", encoding="utf-8") as f:
                src = f.read()
            next_ = re.sub(r"is_first_run = (True|False)", "is_first_run = True", src)
            if next_ != src:
                with open(CONFIG_EXAMPLE, "w", encoding="utf-8") as f:
                    f.write(next_)
        except Exception:
            pass
        print("  配置已重置")
    sys.exit(0)

# 确保项目根目录可导入
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ===== 资源目录自愈:确保默认资源目录存在 =====
# basePath(music/mcfunc/ezmatic/image)与 ezmatic 导出目录 structures
# 缺失时自动创建,避免首次运行找不到目录(如投影目录 resources/ezmatic)。
try:
    from config import basePath, resolvePath
    _resource_dirs = [resolvePath(d) for d in list(basePath.values())]
except Exception:
    _resource_dirs = [
        "./resources/midi",
        "./resources/mcfunc",
        "./resources/ezmatic",
        "./resources/pictures",
    ]
_resource_dirs.append(resolvePath("./structures"))  # ezmatic 导出目录
for _d in _resource_dirs:
    try:
        os.makedirs(_d, exist_ok=True)
    except OSError:
        pass

# ===== 动态加载依赖 config.py 的本地模块(此时 config.py 必然已存在) =====
from lib import shared
from lib.logger import close_log_streams
from lib.utils import ClientConnection, Utils
from lib.current import Current
from lib.mods import ClientModManager, ServerModManager
from config import wsConfig

# 根目录同时存在 config.py 时,config 会被当作普通模块而非包,无法用
# "from config.example import ..." 导入,这里改为读取模板文件提取标记。
with open(CONFIG_EXAMPLE, "r", encoding="utf-8") as f:
    _example_src = f.read()
_m = re.search(r"is_first_run = (True|False)", _example_src)
is_first_run = _m is not None and _m.group(1) == "True"

# 首次运行检查:is_first_run 为 True 时启动图形化配置向导(向导中可设置 Web 管理端口)
# --load-without-config 模式跳过向导,直接使用默认配置运行
if is_first_run and not WANT_LOAD_WITHOUT_CONFIG:
    shared.logger.info("检测到首次运行或是被更新/改动，启动图形化配置向导...")
    from lib.setup import start_setup_server
    try:
        asyncio.run(start_setup_server())
        shared.logger.info("配置已保存，正在自动启动服务器...")
    except Exception as error:
        shared.logger.error(f"配置向导异常: {error}")
        close_log_streams()
        sys.exit(1)
    # 向导已基于模板生成新的 config.py:重新加载配置模块,
    # 使下方服务器启动代码使用用户在向导中保存的值(不退出,自动启动服务器)
    import importlib
    import config as _config_module
    importlib.reload(_config_module)
    wsConfig = _config_module.wsConfig

# ===== WebSocket 服务器 =====
import websockets
from websockets.protocol import State

# 当前所有连接(含未初始化完成的),用于关闭时统一通知
connections = set()
server = None
# 主事件循环引用(供 Web 管理界面线程提交关闭协程,实现一键重启)
_main_loop = None
# 阻塞 Future 引用(供 Ctrl+C / exit 触发优雅关闭)
_main_future = None


async def connection_handler(ws):
    """处理客户端连接"""
    global connections
    # 获取客户端 IP
    client_ip = ws.remote_address[0] if ws.remote_address else "unknown"
    shared.logger.info(f"客户端 {client_ip} 已连接")

    # 分配唯一 ID,用于客户端 Mod 存储和事件总线隔离
    conn = ClientConnection(ws)
    conn.id = str(uuid4())
    connections.add(conn)

    client_mod = None
    initialized = False

    # 消息接收循环(初始化完成前忽略客户端消息,与 JS 一致)
    async def message_loop():
        nonlocal client_mod, initialized
        async for message in ws:
            if not initialized or conn.utils is None:
                continue
            # 仅 JSON 解析需捕获,非 JSON 消息直接忽略
            try:
                text = message.decode("utf-8") if isinstance(message, bytes) else str(message)
                data = json.loads(text)
            except Exception:
                continue
            # 将消息解析为 JSON 后分发给工具类处理
            conn.utils.onMessage(data)
            # 通知客户端 Mod 收到消息
            if client_mod:
                client_mod.call_mod_method("onPocket", data)
            # 通知服务端 Mod 收到消息
            ServerModManager.on_message(conn, data)

    msg_task = asyncio.get_running_loop().create_task(message_loop())

    # 延迟初始化:MCBE 客户端建立 WebSocket 连接后需约 1 秒完成内部握手,
    # 若立即发送命令(权限检测 /list、SAPI 检测 /gmsg、订阅、欢迎消息等),
    # 客户端会主动断开并重连(表现为"每次启动都要断开一次才能连上")。
    try:
        await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        msg_task.cancel()
        connections.discard(conn)
        return

    # 延迟期间客户端可能已断开,检查连接状态
    if ws.state != State.OPEN:
        msg_task.cancel()
        connections.discard(conn)
        return

    # 为当前客户端绑定工具方法(runCommand, subscribe, tell 等)
    conn.utils = Utils(conn)

    # 记录第一个连接的客户端为主客户端
    is_main_client = Current.client is None
    if is_main_client:
        Current.client = conn
        shared.logger.info("主客户端已连接")

    # 实例化客户端 Mod,注入当前连接
    client_mod = ClientModManager(conn)
    conn.clientMod = client_mod
    Current.client_mods[conn] = client_mod

    # 通知服务端 Mod 客户端已连接
    ServerModManager.on_client_connect(conn, is_main_client)

    # 广播连接通知
    conn.tell(f"§e{wsConfig.get('name', 'starws')} | §fSystem > §i已连接")
    initialized = True

    # 等待消息循环结束(连接关闭)
    try:
        await msg_task
    except asyncio.CancelledError:
        pass
    except websockets.exceptions.WebSocketException:
        # 客户端断开(含 MCBE 非标准关闭导致的无 close frame 协议错误 1002),
        # 属正常连接结束,无需记录为错误
        pass
    except Exception as e:
        shared.logger.error(f"消息循环异常: {e}")

    # ===== 客户端断开连接 =====
    connections.discard(conn)
    shared.logger.info(f"客户端 {client_ip} 连接已关闭")

    # 通知服务端 Mod 客户端已断开连接
    ServerModManager.on_client_disconnect(conn, conn is Current.client)

    # 若为主客户端断开,重置主客户端状态
    if conn is Current.client:
        Current.reset()
        shared.logger.info("主客户端连接已关闭")

    # 销毁该客户端的所有 Mod 实例
    Current.client_mods.pop(conn, None)
    if client_mod:
        client_mod.destroy()

    # 清理工具类回调映射,防止内存泄漏
    if conn.utils is not None:
        conn.utils.destroy()


# ===== 主入口 =====
# 启动时刻(供 Web 仪表盘展示运行时间)
_start_time = time.time()


def _webui_status() -> dict:
    """为 Web 仪表盘提供实时状态"""
    return {
        "clients": len(connections),
        "uptime": int(time.time() - _start_time),
    }


def _start_webui() -> None:
    """启动 Web 管理界面(每次启动都监听配置的 Web 端口)"""
    try:
        from webui.server import set_app_info, set_event_loop, set_restart_handler, set_status_provider, start_webui
        set_status_provider(_webui_status)
        set_restart_handler(_request_restart)
        set_event_loop(asyncio.get_running_loop())
        set_app_info(GITHUB_REPO, VERSION, DESCRIPTION)
        start_webui()
    except Exception as error:
        shared.logger.warning(f"Web 管理界面启动失败: {error}")


def _request_restart() -> None:
    """由 Web 管理界面触发:后台线程执行进程内热重启

    顺序:经事件循环执行 destroy()(停 Web 界面 / 关 Mod / 断开客户端 /
    关闭 WS 服务端,确保端口释放),再重新启动全部组件。
    不退出进程、不启动新进程——Windows 控制台下旧进程退出后,
    py.exe/PowerShell 只等待直接子进程,新进程会变成孤儿继续抢占 stdin,
    导致终端无法输入、Ctrl+C 无法结束进程,因此这里采用热重启。

    特殊分支:存在 .update_pending 标记(WebUI 一键更新)时,热重启无法
    重新加载 main.py 自身的新代码,必须关闭全部组件释放端口后启动新进程,
    由新进程读取 .update_pending 执行文件覆盖,再二次启动加载新代码。
    """
    loop = _main_loop

    def _do_restart():
        global _restarting
        update_marker = os.path.join(ROOT, ".update_pending")
        if os.path.isfile(update_marker):
            # ===== WebUI 更新模式 =====
            if loop is not None and not loop.is_closed():
                try:
                    fut = asyncio.run_coroutine_threadsafe(_shutdown_for_update(), loop)
                    fut.result(timeout=30)
                except Exception as error:
                    shared.logger.warning(f"更新前关闭组件异常: {error}")
            try:
                subprocess.Popen([sys.executable] + sys.argv, cwd=ROOT)
            except Exception as error:
                shared.logger.warning(f"更新进程启动失败: {error},请手动重启服务器")
            os._exit(0)
        _restarting = True  # 抑制提示符输出、阻止输入分发
        # 清除当前行提示符,避免残留
        sys.stdout.write("\r\x1b[K")
        sys.stdout.flush()
        if loop is not None and not loop.is_closed():
            try:
                fut = asyncio.run_coroutine_threadsafe(_hot_restart(), loop)
                fut.result(timeout=30)
            except Exception as error:
                shared.logger.warning(f"重启流程异常: {error}")

    threading.Thread(target=_do_restart, daemon=True).start()


async def _shutdown_for_update() -> None:
    """WebUI 更新模式专用:只关闭全部组件并释放端口,不重启

    之后由 _request_restart 启动新进程,新进程读取 .update_pending 执行更新。
    """
    global destroying
    destroying = False  # 复位防重入标志,允许执行关闭流程
    await destroy()


async def _hot_restart() -> None:
    """进程内热重启:在同一进程内关闭并重新启动所有服务器组件

    不退出进程、不启动新进程,终端输入循环不受影响。
    """
    global destroying, server, _restarting
    _restarting = True  # 短暂抑制输入分发(重启过程仅几百毫秒)
    try:
        # 复位防重入标志,允许执行关闭流程
        destroying = False
        await destroy()

        # 重新绑定 WebSocket 服务端(端口已释放)
        host = wsConfig.get("host") or None  # None = 监听所有接口
        port = wsConfig.get("port", 8800)
        server = await websockets.serve(
            connection_handler, host, port,
            compression=None,
            ping_interval=None,
            ping_timeout=None,
        )

        # 重新加载配置(含命令前缀等模块级变量)
        from lib.command import Command
        Command.reload_prefix()

        # 重新启动 Web 管理界面
        _start_webui()

        # 重新加载 Mod 定义
        await ServerModManager.load()
        await ClientModManager.load()

        shared.logger.info("服务器已重启")
    except Exception as error:
        shared.logger.error(f"热重启失败: {error}")
    finally:
        # 复位标志:允许最终退出时再次执行 destroy()
        destroying = False
        _restarting = False
        # 复位提示符状态:热重启期间日志钩子把 _prompt_visible 置 False 后
        # 因 _restarting 抑制了 _show_prompt,这里补一次确保提示符可见
        global _prompt_visible
        _prompt_visible = False
        _show_prompt()


# ===== 交互式终端提示符 =====
CONSOLE_PROMPT = "EnderBridge> "
_restarting = False  # 重启/更新中,抑制提示符输出
_prompt_visible = False  # 提示符是否已在终端显示(防重复)


def console_out(msg):
    """终端输出消息"""
    global _prompt_visible
    _prompt_visible = False  # console_out 清除了当前行,提示符不再可见
    sys.stdout.write("\r\x1b[K")
    print(msg)


def _console_help():
    """显示帮助信息"""
    from lib.command import Command
    cp = Command.command_prefix
    console_out("可用命令:")
    console_out(f"  {cp}help       - 显示此帮助")
    console_out(f"  {cp}status     - 显示服务器状态")
    console_out(f"  {cp}list       - 列出所有客户端连接")
    console_out(f"  {cp}say <msg>  - 向主客户端发送消息")
    console_out(f"  {cp}cmd <cmd>  - 向主客户端发送命令")
    console_out(f"  /<cmd>     - 直接发送游戏命令(如 /list)")
    console_out(f"  <text>     - 作为聊天消息发送")
    console_out(f"  exit/quit  - 退出程序")
    console_out(f"  {cp}chat ...   - Mod 命令(如 {cp}chat help)")
    console_out(f"  {cp}bot ...    - 假人管理(如 {cp}bot start)")


def _console_status():
    """显示服务器状态"""
    uptime = int(time.time() - _start_time)
    h, m, s = uptime // 3600, (uptime % 3600) // 60, uptime % 60
    console_out(f"客户端连接数: {len(connections)}")
    console_out(f"运行时间: {h}h {m}m {s}s")
    console_out(f"WebSocket 端口: {wsConfig.get('port', 8800)}")
    console_out(f"Web 管理端口: {wsConfig.get('web_port', 18888)}")


def _console_list():
    """列出所有连接"""
    if not connections:
        console_out("当前无客户端连接")
        return
    for i, conn in enumerate(connections, 1):
        ip = conn.ws.remote_address[0] if conn.ws.remote_address else "unknown"
        role = "主客户端" if conn is Current.client else "副客户端"
        console_out(f"  {i}. {ip} ({role})")


def _show_prompt():
    """显示终端提示符(防重复:提示符已在行首时不重复输出)"""
    global _prompt_visible
    if _restarting or _prompt_visible:
        return
    _prompt_visible = True
    sys.stdout.write(CONSOLE_PROMPT)
    sys.stdout.flush()


def _clear_prompt():
    """日志输出前清除当前行的提示符"""
    global _prompt_visible
    _prompt_visible = False
    sys.stdout.write("\r\x1b[K")
    sys.stdout.flush()


# 注册控制台钩子:日志写 stdout 前清除提示符,写完后补回来
from lib.logger import set_console_hooks
set_console_hooks(before=_clear_prompt, after=_show_prompt)


async def _dispatch_console_command(text):
    """分发终端命令"""
    text = text.strip()
    if not text:
        return

    # Bot Shell 模式:所有输入转发给 bot
    if getattr(shared, "bot_shell_mode", False) and getattr(shared, "bot_shell_queue", None):
        shared.bot_shell_queue.put_nowait(text)
        return

    if text in ("exit", "quit"):
        # 触发优雅关闭:取消阻塞的 Future,让 finally 块执行 destroy()
        loop = _main_loop
        fut = _main_future
        if loop is not None and not loop.is_closed() and fut is not None and not fut.done():
            loop.call_soon_threadsafe(fut.cancel)
        return

    # 以 / 开头:转发为游戏命令
    if text.startswith("/"):
        if Current.client:
            try:
                data = await Current.client.runCommand(text)
                body = data.get("body", {})
                console_out(f"CMD {body.get('statusCode')} -> {body.get('statusMessage') or 'Null'}")
            except Exception as e:
                console_out(f"§cCMD 执行失败: {e}")
        else:
            console_out("§c无客户端连接")
        return

    # 以命令前缀开头:本地控制台命令
    from lib.command import Command
    Command.reload_prefix()
    cp = Command.command_prefix
    if text.startswith(cp):
        cmd = text[len(cp):].strip()

        if cmd in ("help", "h", "?"):
            _console_help()
        elif cmd in ("status", "info"):
            _console_status()
        elif cmd == "list":
            _console_list()
        elif cmd.startswith("say "):
            msg = cmd[4:]
            if Current.client:
                Current.client.tell(msg)
                console_out(f"§a已发送: §f{msg}")
            else:
                console_out("§c无客户端连接")
        elif cmd.startswith("cmd "):
            c = cmd[4:]
            if Current.client:
                await Current.client.runCommand(c)
                console_out(f"§a已执行: §f{c}")
            else:
                console_out("§c无客户端连接")
        else:
            # 转发给服务端 Mod 执行(如 $chat、$spam 等)
            mod_cmd = f"{cp}{cmd}"
            handled = await ServerModManager.execute_terminal(mod_cmd)
            if not handled:
                # 再尝试客户端 Mod(如 $bot)
                handled = await ClientModManager.execute_terminal(mod_cmd)
            if not handled:
                console_out(f"§c未知命令: §f{cmd}，输入 {cp}help 查看帮助")
        return

    # 非命令文本:作为聊天消息发送给主客户端
    if Current.client:
        Current.client.tellAll(text)
    else:
        console_out("§c无客户端连接")


async def main():
    global server, _main_loop, _main_future
    _main_loop = asyncio.get_running_loop()
    host = wsConfig.get("host") or None  # None = 监听所有接口
    port = wsConfig.get("port", 8800)

    # 创建 WebSocket 服务端
    # 禁用压缩(MCBE 不支持 permessage-deflate)和 ping 保活(MCBE 不响应 ping)
    server = await websockets.serve(
        connection_handler, host, port,
        compression=None,
        ping_interval=None,
        ping_timeout=None,
    )

    # 启动 Web 管理界面(独立线程,不阻塞主流程)
    _start_webui()

    # 加载服务端 Mod 和客户端 Mod 的静态定义
    await ServerModManager.load()
    await ClientModManager.load()
    shared.logger.info("服务器已启动")

    # 注入状态引用供游戏内命令(如 $help/$status/$list)使用
    shared.start_time = _start_time
    shared.connections_ref = connections

    # 启动终端交互式输入循环(独立线程,Windows 不支持 asyncio add_reader)
    def on_line(text):
        if _restarting:          # 重启中不处理任何输入
            return
        text = text.strip()
        task = asyncio.ensure_future(_dispatch_console_command(text))
        def _done(fut):
            try:
                fut.result()
            except Exception as e:
                console_out(f"§c错误: §f{e}")
            finally:
                _show_prompt()
        task.add_done_callback(_done)

    def stdin_loop():
        # 注意:不使用 _restarting 退出循环——热重启期间只短暂抑制输入分发,
        # 若在此退出则重启后终端将失去输入能力
        while True:
            try:
                line = sys.stdin.readline()
            except (EOFError, KeyboardInterrupt, ValueError, OSError):
                break
            if not line:
                break
            _main_loop.call_soon_threadsafe(on_line, line.rstrip("\n"))

    threading.Thread(target=stdin_loop, daemon=True).start()

    # Ctrl+C 处理:Windows 下 await Future() 可能无法可靠捕获 KeyboardInterrupt
    # 用信号处理器取消阻塞的 Future,让 finally 块执行 destroy()
    import signal
    def _sigint(sig, frame):
        loop = _main_loop
        fut = _main_future
        if loop is not None and not loop.is_closed() and fut is not None and not fut.done():
            loop.call_soon_threadsafe(fut.cancel)
    signal.signal(signal.SIGINT, _sigint)

    _main_future = asyncio.Future()
    try:
        await _main_future
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await destroy()


# ===== 关闭函数 =====
# 依次销毁 Mod、关闭 WebSocket 服务端、停止 Web 管理界面
# 防重入:重复调用直接忽略
destroying = False


async def destroy():
    global destroying
    if destroying:
        return
    destroying = True

    shared.logger.info("正在停止 Web 管理界面...")
    try:
        from webui.server import stop_webui
        stop_webui()
    except Exception:
        pass

    shared.logger.info("正在关闭服务端 Mod...")
    ServerModManager.destroy()
    shared.logger.info("服务端 Mod 已关闭")

    shared.logger.info("正在通知客户端断开连接...")
    for client in list(connections):
        try:
            client.tell(f"§c{wsConfig.get('name', 'starws')} | §fSystem > §i已关闭连接")
        except Exception:
            pass
        try:
            await asyncio.wait_for(client.runCommand("/closewebsocket"), timeout=2)
        except Exception:
            pass
        try:
            await asyncio.wait_for(client.close(), timeout=2)
        except Exception:
            pass
    shared.logger.info("客户端通知已完成")

    shared.logger.info("正在关闭服务器...")
    try:
        server.close()
        await asyncio.wait_for(server.wait_closed(), timeout=5)
        shared.logger.info("服务器已关闭")
    except Exception:
        shared.logger.warning("服务器关闭异常，正在强制退出")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        close_log_streams()
        shared.logger.info("程序进程结束")
