"""更新包处理 - 压缩包解压 / 目录覆盖 / 项目导出的统一逻辑

main.py 中的三处重复逻辑统一到这里:
- 命令行 `python main.py update <压缩包>`
- WebUI 触发的 `.update_pending` 更新
- 命令行 `python main.py export [输出路径]`

调用方只需捕获 PackageError 并按需退出, 无需重复实现解压细节。
"""

import json
import os
import re
import shutil
import tarfile
import tempfile
import time
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
EXPORT_IGNORE_FILE = ".exportignore"
NONEEDS_FILE = ".noneeds"

_ZIP_SUFFIX = (".zip",)
_TAR_SUFFIXES = (".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tar")

# 更新前自动备份:保留最近 N 个备份,存放在项目上级目录避免被打包/覆盖
BACKUP_KEEP_COUNT = 3
BACKUP_PREFIX = "EnderBridge_backup_"


class PackageError(Exception):
    """更新包处理失败(格式不支持 / 读取失败 / 校验不通过)"""


def safe_rel(name: str) -> str:
    """规范化压缩包成员路径,过滤路径穿越,返回相对路径或空字符串"""
    norm = os.path.normpath(name.replace("\\", "/"))
    if not norm or norm == ".":
        return ""
    # isabs 在 Windows 上不识别 /foo 形式的 Unix 绝对路径,额外检测
    if os.path.isabs(norm) or norm.startswith(("/", "\\")):
        return ""
    if norm.startswith(".."):
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


def clean_noneeds(root: str) -> list:
    """更新后检测并删除 .noneeds 中指定的冗余文件与文件夹

    返回被成功删除的相对路径列表。
    """
    noneeds_path = os.path.join(root, NONEEDS_FILE)
    if not os.path.isfile(noneeds_path):
        return []

    try:
        with open(noneeds_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return []

    deleted = []
    # 核心保护名单: 严禁删除的项目关键文件与配置
    PROTECTED = {"", ".", "main.py", NONEEDS_FILE, "config", "config/config.json"}

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        clean_line = line.replace("\\", "/").strip("/")
        if not clean_line or clean_line in PROTECTED:
            continue

        # 防止路径穿越与绝对路径逃逸
        if ".." in clean_line.split("/"):
            continue
        if os.path.isabs(clean_line) or clean_line.startswith(("/", "\\")):
            continue

        # 支持通配符匹配 (如 *.tmp, docs/*.draft 等)
        if any(char in line for char in ("*", "?", "[")):
            import glob
            full_pattern = os.path.join(root, line.replace("/", os.sep))
            matches = glob.glob(full_pattern, recursive=True)
            for m in matches:
                rel = os.path.relpath(m, root).replace(os.sep, "/")
                if rel in PROTECTED or rel.startswith("../"):
                    continue
                try:
                    if os.path.isdir(m):
                        shutil.rmtree(m, ignore_errors=True)
                        deleted.append(rel + "/")
                    elif os.path.isfile(m) or os.path.islink(m):
                        os.remove(m)
                        deleted.append(rel)
                except Exception:
                    pass
        else:
            # 精确匹配文件或目录
            target_path = os.path.join(root, *clean_line.split("/"))
            if not os.path.exists(target_path):
                continue
            try:
                if os.path.isdir(target_path):
                    shutil.rmtree(target_path, ignore_errors=True)
                    deleted.append(clean_line + "/")
                elif os.path.isfile(target_path) or os.path.islink(target_path):
                    os.remove(target_path)
                    deleted.append(clean_line)
            except Exception:
                pass

    return deleted


def apply_archive(archive, root, keep=UPDATE_KEEP, allow=CONFIG_TEMPLATE_ALLOW,
                  validate=validate_project) -> int:
    """解压压缩包并覆盖到项目目录(经 validate 校验),返回覆盖文件数

    临时目录由本函数创建并清理,失败抛 PackageError。
    更新完成后自动检测并执行 .noneeds 清理。
    """
    tmp = tempfile.mkdtemp(prefix="enderbridge_update_")
    try:
        extract_archive(archive, tmp, keep, allow)
        if validate is not None:
            validate(tmp)
        copied = overlay_dir(tmp, root, keep, allow)
        clean_noneeds(root)
        return copied
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _gitignore_pattern_to_regex(pattern: str) -> re.Pattern:
    """将类似 .gitignore 的 glob 模式转为正则表达式"""
    anchored = False
    if pattern.startswith("/"):
        anchored = True
        pattern = pattern[1:]
    elif "/" in pattern.rstrip("/"):
        anchored = True

    dir_only = pattern.endswith("/")
    if dir_only:
        pattern = pattern.rstrip("/")

    i = 0
    n = len(pattern)
    res = []
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                i += 2
                if i < n and pattern[i] == "/":
                    i += 1
                    res.append("(?:.+/)?")
                else:
                    res.append(".*")
            else:
                i += 1
                res.append("[^/]*")
        elif c == "?":
            i += 1
            res.append("[^/]")
        elif c in r"\.+^$()[]{}|":
            res.append(re.escape(c))
            i += 1
        elif c == "/":
            res.append("/")
            i += 1
        else:
            res.append(c)
            i += 1

    pattern_re = "".join(res)
    if dir_only:
        if anchored:
            regex_str = f"^(?:{pattern_re})/(?:.*)?$"
        else:
            regex_str = f"(?:^|/)(?:{pattern_re})/(?:.*)?$"
    else:
        if anchored:
            regex_str = f"^(?:{pattern_re})(?:/.*)?$"
        else:
            regex_str = f"(?:^|/)(?:{pattern_re})(?:/.*)?$"

    return re.compile(regex_str, re.IGNORECASE)


class ExportIgnore:
    """解析并匹配 .exportignore 规则 (语法与功能类似 .gitignore)"""

    def __init__(self, rules: list = None, raw_rules: list = None):
        self.rules = rules or []  # list of (is_negated: bool, regex: re.Pattern)
        self.raw_rules = raw_rules or []  # list of (is_negated: bool, clean_pattern: str)

    @classmethod
    def from_file(cls, filepath: str) -> "ExportIgnore":
        """从 .exportignore 文件解析规则"""
        if not filepath or not os.path.isfile(filepath):
            return cls([])
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                return cls.parse(f.readlines())
        except Exception:
            return cls([])

    @classmethod
    def parse(cls, lines) -> "ExportIgnore":
        """解析多行 ignore 规则"""
        rules = []
        raw_rules = []
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            is_negated = False
            if line.startswith("!"):
                is_negated = True
                line = line[1:].strip()
                if not line:
                    continue
            rx = _gitignore_pattern_to_regex(line)
            rules.append((is_negated, rx))
            raw_rules.append((is_negated, line))
        return cls(rules=rules, raw_rules=raw_rules)

    def has_negations_under(self, dir_rel: str) -> bool:
        """检查是否有取反规则指向该子目录下，若有则不能直接裁剪整个目录"""
        prefix = dir_rel.replace("\\", "/").strip("/") + "/"
        for is_negated, pat in self.raw_rules:
            clean = pat.lstrip("/")
            if is_negated:
                if clean.startswith(prefix) or ("/" not in clean.rstrip("/")):
                    return True
        return False

    def is_ignored(self, rel_path: str, is_dir: bool = False) -> bool:
        """检查相对路径是否匹配忽略规则 (注: .exportignore 自身永远忽略)"""
        norm = rel_path.replace("\\", "/").strip("/")
        if not norm or norm == EXPORT_IGNORE_FILE or norm.endswith(f"/{EXPORT_IGNORE_FILE}") or os.path.basename(norm) == EXPORT_IGNORE_FILE:
            return True

        target = norm + "/" if is_dir and not norm.endswith("/") else norm
        ignored = False
        for is_negated, rx in self.rules:
            if rx.search(target):
                ignored = not is_negated
        return ignored


def iter_export_files(root, export_ignore=None):
    """遍历项目内需打包的文件,产出 (压缩包相对路径, 绝对路径)"""
    if export_ignore is None:
        export_ignore = ExportIgnore.from_file(os.path.join(root, EXPORT_IGNORE_FILE))

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")

        # 1. 目录修剪: 排除默认排除目录与 .exportignore 指定忽略的目录
        pruned_dirs = []
        for d in dirnames:
            child_rel = f"{rel_dir}/{d}" if rel_dir else d
            # 基础规则过滤
            if d in EXPORT_EXCLUDE or d in EXPORT_SKIP_DIRS:
                continue
            if child_rel.split("/", 1)[0] in EXPORT_EXCLUDE:
                continue
            # .exportignore 目录过滤
            if export_ignore.is_ignored(child_rel, is_dir=True):
                # 若该目录下有取反规则，不直接剪枝，留待子文件逐个判定
                if not export_ignore.has_negations_under(child_rel):
                    continue
            pruned_dirs.append(d)
        dirnames[:] = pruned_dirs

        # 2. 文件收集
        for fname in filenames:
            if fname == EXPORT_IGNORE_FILE:
                continue
            if os.path.splitext(fname)[1].lower() in EXPORT_SKIP_EXTS:
                continue
            rel = f"{rel_dir}/{fname}" if rel_dir else fname
            if rel.split("/", 1)[0] in EXPORT_EXCLUDE:
                continue
            # .exportignore 规则过滤
            if export_ignore.is_ignored(rel, is_dir=False):
                continue
            yield rel, os.path.join(dirpath, fname)


def collect_export_files(root, export_ignore=None) -> list:
    """收集导出文件列表(含强制包含的模板文件, 支持 .exportignore)"""
    if export_ignore is None:
        export_ignore = ExportIgnore.from_file(os.path.join(root, EXPORT_IGNORE_FILE))
    files = list(iter_export_files(root, export_ignore=export_ignore))
    seen = {rel for rel, _ in files}
    for force_rel in EXPORT_FORCE_INCLUDE:
        if export_ignore.is_ignored(force_rel, is_dir=False):
            continue
        force_abs = os.path.join(root, force_rel)
        if os.path.isfile(force_abs) and force_rel not in seen:
            files.append((force_rel, force_abs))
            seen.add(force_rel)
    return files


def create_export_zip(root, out_path, export_ignore=None) -> str:
    """打包项目为 zip,返回输出路径,失败抛 PackageError"""
    files = collect_export_files(root, export_ignore=export_ignore)
    if not files:
        raise PackageError("未找到可导出的文件")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, abspath in files:
            z.write(abspath, rel)
    return out_path


BACKUP_META_FILE = ".backups_meta.json"


def _get_backup_meta_path(dest_dir: str) -> str:
    return os.path.join(dest_dir, BACKUP_META_FILE)


def load_backups_meta(dest_dir: str) -> dict:
    meta_path = _get_backup_meta_path(dest_dir)
    if not os.path.isfile(meta_path):
        return {}
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_backup_meta(dest_dir: str, filename: str, description: str) -> None:
    meta_path = _get_backup_meta_path(dest_dir)
    data = load_backups_meta(dest_dir)
    data[filename] = {
        "description": description.strip(),
        "updated_at": time.time(),
    }
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_backup_description(path: str) -> str:
    """获取指定备份的描述信息"""
    dest_dir = os.path.dirname(os.path.abspath(path))
    fname = os.path.basename(path)
    meta = load_backups_meta(dest_dir)
    if fname in meta and "description" in meta[fname]:
        return meta[fname]["description"]
    if os.path.isfile(path):
        try:
            with zipfile.ZipFile(path, "r") as z:
                if ".backup_meta.json" in z.namelist():
                    info = json.loads(z.read(".backup_meta.json").decode("utf-8", errors="replace"))
                    desc = info.get("description", "")
                    if desc:
                        save_backup_meta(dest_dir, fname, desc)
                        return desc
        except Exception:
            pass
    return ""


def backup_dir(root, dest_dir=None, keep=BACKUP_KEEP_COUNT, description: str = None) -> str:
    """更新前备份:将项目目录整体打包为 zip,返回备份路径,失败抛 PackageError

    备份默认存放在项目上级目录(避免被打包/覆盖/删除),只保留最近 keep 个。
    """
    from datetime import datetime
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:20]  # 精确到毫秒，格式 YYYYMMDD_HHMMSS_mmm
    parent = os.path.dirname(os.path.abspath(root))
    dest_dir = dest_dir or parent
    os.makedirs(dest_dir, exist_ok=True)
    out_path = os.path.join(dest_dir, f"{BACKUP_PREFIX}{stamp}.zip")
    fname = os.path.basename(out_path)
    clean_desc = (description or "").strip()
    try:
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            if clean_desc:
                meta_content = {
                    "timestamp": stamp,
                    "description": clean_desc,
                    "created_at": datetime.now().isoformat(),
                }
                z.writestr(".backup_meta.json", json.dumps(meta_content, ensure_ascii=False, indent=2))
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d != "__pycache__"]
                for fname_item in filenames:
                    if os.path.splitext(fname_item)[1].lower() in EXPORT_SKIP_EXTS:
                        continue
                    abspath = os.path.join(dirpath, fname_item)
                    rel = os.path.relpath(abspath, root).replace(os.sep, "/")
                    z.write(abspath, rel)
    except Exception as e:
        try:
            os.unlink(out_path)
        except OSError:
            pass
        raise PackageError(f"备份失败: {e}")
    if clean_desc:
        save_backup_meta(dest_dir, fname, clean_desc)
    prune_backups(dest_dir, keep)
    return out_path


def list_backups(dest_dir) -> list:
    """列出备份目录下的备份包(按时间从旧到新排序)"""
    try:
        names = os.listdir(dest_dir)
    except OSError:
        return []
    found = [os.path.join(dest_dir, n) for n in names
             if n.startswith(BACKUP_PREFIX) and n.endswith(".zip")]
    found.sort()
    return found


def prune_backups(dest_dir, keep=BACKUP_KEEP_COUNT) -> None:
    """只保留最近 keep 个备份,删除多余的旧备份并清理元数据记录"""
    found = list_backups(dest_dir)
    deleted_names = set()
    for old in found[:-keep] if keep > 0 else found:
        try:
            os.remove(old)
            deleted_names.add(os.path.basename(old))
        except OSError:
            pass
    if deleted_names:
        meta = load_backups_meta(dest_dir)
        changed = False
        for d in deleted_names:
            if d in meta:
                meta.pop(d, None)
                changed = True
        if changed:
            try:
                with open(_get_backup_meta_path(dest_dir), "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
            except Exception:
                pass


def rollback(root, backup_path=None, dest_dir=None) -> str:
    """回滚:用指定备份(默认最新)覆盖项目目录,返回使用的备份路径

    失败抛 PackageError。回滚同样先备份当前状态,避免回滚本身造成数据丢失。
    """
    dest_dir = dest_dir or os.path.dirname(os.path.abspath(root))
    if backup_path is None:
        found = list_backups(dest_dir)
        if not found:
            raise PackageError(f"未找到可用备份(目录: {dest_dir})")
        backup_path = found[-1]
    if not os.path.isfile(backup_path):
        raise PackageError(f"找不到备份文件: {backup_path}")
    # 回滚前先备份当前状态:
    # 传 keep=BACKUP_KEEP_COUNT+1 避免 prune 误删我们即将使用的 backup_path
    backup_dir(root, dest_dir, keep=BACKUP_KEEP_COUNT + 1)
    # 备份包是全量打包(含 config/ 等数据区),回滚时全量覆盖
    tmp = tempfile.mkdtemp(prefix="enderbridge_rollback_")
    try:
        extract_archive(backup_path, tmp, keep=set(), allow=set())
        copied = overlay_dir(tmp, root, keep=set(), allow=set())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if copied == 0:
        raise PackageError("回滚失败: 备份包为空或无法解压")
    # 覆盖完成后统一修剪回正常数量
    prune_backups(dest_dir)
    return backup_path

