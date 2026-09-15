"""更新包处理 - 压缩包解压 / 目录覆盖 / 项目导出的统一逻辑

main.py 中的三处重复逻辑统一收敛到这里:
- 命令行 `python main.py update <压缩包>`
- WebUI 触发的 `.update_pending` 更新
- 命令行 `python main.py export [输出路径]`

调用方只需捕获 PackageError 并按需退出, 无需重复实现解压细节。
"""

import os
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
    "config",
}

# config/ 整体跳过,但模板文件必须带入,否则目标实例无法首次运行
CONFIG_TEMPLATE_ALLOW = {
    "config/config.example.json",
    "config/permission.example.json",
    "config/users.example.json",
}

# 导出时排除用户数据/设置(与 UPDATE_KEEP 对称,另排除 Bot 的 npm 依赖)
EXPORT_EXCLUDE = UPDATE_KEEP | {
    "node_modules",  # Bot 的 npm 依赖(约 500MB),用户需自行 npm install
}
EXPORT_FORCE_INCLUDE = set(CONFIG_TEMPLATE_ALLOW)
EXPORT_SKIP_DIRS = {"__pycache__"}
EXPORT_SKIP_EXTS = {".pyc", ".pyo"}

_ZIP_SUFFIX = (".zip",)
_TAR_SUFFIXES = (".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tar")


class PackageError(Exception):
    """更新包处理失败(格式不支持 / 读取失败 / 校验不通过)"""


def safe_rel(name: str) -> str:
    """规范化压缩包成员路径,过滤路径穿越,返回相对路径或空字符串"""
    norm = os.path.normpath(name.replace("\\", "/"))
    if not norm or norm == ".":
        return ""
    if norm.startswith("..") or os.path.isabs(norm):
        return ""
    return norm.replace(os.sep, "/")


def common_root(names) -> str:
    """GitHub 风格压缩包内含顶层目录(如 EnderBridge-main/),探测并剥离"""
    files = [n for n in names if n]
    if not files:
        return ""
    roots = {n.split("/", 1)[0] for n in files}
    if len(roots) == 1 and all("/" in n for n in files):
        return roots.pop()
    return ""


def iter_archive_members(archive):
    """迭代压缩包成员,产出 (相对路径, 文件对象)

    Raises:
        PackageError: 不支持的格式 / 读取失败
    """
    lower = archive.lower()
    try:
        if lower.endswith(_ZIP_SUFFIX):
            with zipfile.ZipFile(archive) as z:
                names = [i.filename for i in z.infolist() if not i.is_dir()]
                root = common_root(names)
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    rel = safe_rel(info.filename)
                    if not rel:
                        continue
                    if root:
                        if not rel.startswith(root + "/"):
                            continue
                        rel = rel[len(root) + 1:]
                    if not rel:
                        continue
                    yield rel, z.open(info)
        elif lower.endswith(_TAR_SUFFIXES):
            with tarfile.open(archive, "r:*") as t:
                members = [m for m in t.getmembers() if m.isfile()]
                root = common_root([m.name for m in members])
                for m in members:
                    rel = safe_rel(m.name)
                    if not rel:
                        continue
                    if root:
                        if not rel.startswith(root + "/"):
                            continue
                        rel = rel[len(root) + 1:]
                    if not rel:
                        continue
                    yield rel, t.extractfile(m)
        else:
            raise PackageError(f"不支持的压缩包格式: {archive}(仅支持 zip / tar.gz)")
    except PackageError:
        raise
    except Exception as e:
        raise PackageError(f"读取压缩包失败: {e}")


def _is_kept(rel: str, keep, allow) -> bool:
    """判断相对路径是否属于保留的数据区(模板白名单放行)"""
    top = rel.split("/", 1)[0]
    return top in keep and rel not in allow


def extract_archive(archive, dest_dir, keep=UPDATE_KEEP, allow=CONFIG_TEMPLATE_ALLOW) -> int:
    """解压压缩包到目标目录(跳过数据区,模板文件放行),返回解压文件数"""
    count = 0
    for rel, fobj in iter_archive_members(archive):
        if _is_kept(rel, keep, allow):
            continue
        target = os.path.join(dest_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as out:
            if fobj is not None:
                shutil.copyfileobj(fobj, out)
        count += 1
    return count


def validate_project(staged_dir) -> None:
    """校验解压结果为 EnderBridge 项目,失败抛 PackageError"""
    if not os.path.exists(os.path.join(staged_dir, "main.py")):
        raise PackageError("解压后未找到 main.py")
    if not os.path.exists(os.path.join(staged_dir, "lib")):
        raise PackageError("解压后未找到 lib 目录")


def overlay_dir(src_dir, root, keep=UPDATE_KEEP, allow=CONFIG_TEMPLATE_ALLOW) -> int:
    """将暂存目录覆盖到项目根目录(跳过数据区,不清除多余文件),返回覆盖文件数"""
    copied = 0
    for dirpath, _dirnames, filenames in os.walk(src_dir):
        rel_dir = os.path.relpath(dirpath, src_dir)
        for fname in filenames:
            src = os.path.join(dirpath, fname)
            dst = os.path.join(root, rel_dir, fname)
            rel = os.path.relpath(dst, root).replace(os.sep, "/")
            if _is_kept(rel, keep, allow):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
    return copied


def apply_archive(archive, root, keep=UPDATE_KEEP, allow=CONFIG_TEMPLATE_ALLOW,
                  validate=validate_project) -> int:
    """解压压缩包并覆盖到项目目录(经 validate 校验),返回覆盖文件数

    临时目录由本函数创建并清理,失败抛 PackageError。
    """
    tmp = tempfile.mkdtemp(prefix="enderbridge_update_")
    try:
        extract_archive(archive, tmp, keep, allow)
        if validate is not None:
            validate(tmp)
        return overlay_dir(tmp, root, keep, allow)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def iter_export_files(root):
    """遍历项目内需打包的文件,产出 (压缩包相对路径, 绝对路径)"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in EXPORT_EXCLUDE and d not in EXPORT_SKIP_DIRS
        ]
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else rel_dir
        for fname in filenames:
            if os.path.splitext(fname)[1].lower() in EXPORT_SKIP_EXTS:
                continue
            rel = os.path.join(rel_dir, fname) if rel_dir else fname
            rel = rel.replace(os.sep, "/")
            if rel.split("/", 1)[0] in EXPORT_EXCLUDE:
                continue
            yield rel, os.path.join(dirpath, fname)


def collect_export_files(root) -> list:
    """收集导出文件列表(含强制包含的模板文件)"""
    files = list(iter_export_files(root))
    seen = {rel for rel, _ in files}
    for force_rel in EXPORT_FORCE_INCLUDE:
        force_abs = os.path.join(root, force_rel)
        if os.path.isfile(force_abs) and force_rel not in seen:
            files.append((force_rel, force_abs))
            seen.add(force_rel)
    return files


def create_export_zip(root, out_path) -> str:
    """打包项目为 zip,返回输出路径,失败抛 PackageError"""
    files = collect_export_files(root)
    if not files:
        raise PackageError("未找到可导出的文件")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, abspath in files:
            z.write(abspath, rel)
    return out_path
