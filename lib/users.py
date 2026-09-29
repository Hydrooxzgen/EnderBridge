"""用户管理模块

提供 WebUI 用户认证与权限管理:
- 用户存储在 users.json(username + bcrypt 哈希 + 角色)
- 角色存储在 users.json(预设 admin/operator/viewer + 自定义)
- 每个角色拥有一组权限(页面级 + 操作级)
- 首次运行自动创建 admin(随机密码) + guest(空密码,不可删除)
- 从旧版本升级时自动迁移 admin(密码=旧令牌)
"""
import hashlib
import json
import os
import secrets
import threading
import time
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")
USERS_JSON = os.path.join(CONFIG_DIR, "users.json")

# ===== bcrypt 依赖导入与虚拟环境自动发现 =====
try:
    import bcrypt as _bcrypt
    _HAS_BCRYPT = True
except ImportError:
    _HAS_BCRYPT = False
    # 尝试在项目根目录 .venv / venv / env 中查找 site-packages
    import sys
    for _venv in (".venv", "venv", "env"):
        _sp = os.path.join(ROOT, _venv, "Lib", "site-packages")
        if not os.path.isdir(_sp):
            _lib = os.path.join(ROOT, _venv, "lib")
            if os.path.isdir(_lib):
                for _pv in os.listdir(_lib):
                    _p = os.path.join(_lib, _pv, "site-packages")
                    if os.path.isdir(_p):
                        _sp = _p
                        break
        if os.path.isdir(_sp) and _sp not in sys.path:
            sys.path.insert(0, _sp)
            try:
                import bcrypt as _bcrypt
                _HAS_BCRYPT = True
                break
            except ImportError:
                pass

# ===== 密码哈希 =====

def hash_password(password: str) -> str:
    """对密码进行哈希(bcrypt 优先,回退 PBKDF2-SHA256)"""
    if _HAS_BCRYPT:
        return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")
    # PBKDF2-SHA256 回退(stdlib,无额外依赖)
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 260000)
    return f"pbkdf2:sha256:{salt}:{dk.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码是否匹配哈希"""
    if not password and not password_hash:
        return True  # 空密码 = 空哈希(仅 guest 用)
    if not password_hash:
        return False
    # 容错 1: 密码直接等于哈希密文(允许在客户端/WebUI中直接粘贴 users.json 中的哈希密文作为安全凭据登录)
    if password == password_hash or password.strip() == password_hash.strip():
        return True
    if password_hash.startswith("$2"):
        if not _HAS_BCRYPT:
            try:
                from lib import shared
                shared.logger.error("[users] 无法验证用户密码: 密码为 bcrypt 哈希, 但当前 Python 环境未安装 bcrypt 模块！请安装 bcrypt 或使用包含依赖的环境启动。")
            except Exception:
                pass
            return False
        try:
            p_bytes = password.encode("utf-8")
            h_bytes = password_hash.strip().encode("utf-8")
            if _bcrypt.checkpw(p_bytes, h_bytes):
                return True
            # 容错 2: 去除全角/半角空格、回车换行等所有不可见控制字符
            p_trimmed = password.strip()
            if p_trimmed and p_trimmed != password:
                if _bcrypt.checkpw(p_trimmed.encode("utf-8"), h_bytes):
                    return True
        except Exception as e:
            try:
                from lib import shared
                shared.logger.warning(f"[users] bcrypt 校验异常: {e}")
            except Exception:
                pass
            return False
        return False
    if password_hash.startswith("pbkdf2:"):
        parts = password_hash.split(":")
        if len(parts) == 4:
            _, algo, salt, stored_hex = parts
            # 兼容旧格式: 存储时误用 "256" 而非 "sha256"
            digest = "sha256" if algo == "256" else algo
            p_bytes = password.encode("utf-8")
            dk = hashlib.pbkdf2_hmac(digest, p_bytes, salt.encode("utf-8"), 260000)
            if dk.hex() == stored_hex:
                return True
            p_trimmed = password.strip("\r\n \t")
            if p_trimmed and p_trimmed != password:
                dk_t = hashlib.pbkdf2_hmac(digest, p_trimmed.encode("utf-8"), salt.encode("utf-8"), 260000)
                if dk_t.hex() == stored_hex:
                    return True
    return False


# ===== 权限元数据与自适应自动发现机制 =====

BUILTIN_PERM_META = [
    {"key": "dashboard", "label": "nav.dashboard", "icon": "📊", "name": "仪表盘"},
    {"key": "permissions", "label": "nav.permissions", "icon": "👥", "name": "权限管理"},
    {"key": "config", "label": "nav.config", "icon": "⚙️", "name": "功能设置"},
    {"key": "mods", "label": "nav.mods", "icon": "🧩", "name": "Mod 管理"},
    {"key": "studio", "label": "nav.studio", "icon": "🎨", "name": "创意工坊"},
    {"key": "console", "label": "nav.console", "icon": "💻", "name": "控制台"},
    {"key": "scheduler", "label": "nav.scheduler", "icon": "⏰", "name": "任务计划"},
    {"key": "audit", "label": "nav.audit", "icon": "📋", "name": "审计日志"},
    {"key": "update", "label": "nav.update", "icon": "🔄", "name": "检查更新"},
    {"key": "banlist", "label": "nav.banlist", "icon": "🚫", "name": "封禁管理"},
    {"key": "restart", "label": "nav.restart", "icon": "🔁", "name": "重启服务器"},
]


def discover_all_permissions() -> list[str]:
    """动态扫描 webui/pages/*.html 及内置操作, 自动发现所有权限项"""
    perms = set()
    for item in BUILTIN_PERM_META:
        perms.add(item["key"])

    pages_dir = os.path.join(ROOT, "webui", "pages")
    if os.path.isdir(pages_dir):
        for fname in os.listdir(pages_dir):
            if fname.endswith(".html"):
                base = fname[:-5].lower()
                if base not in ("login", "404"):
                    perms.add(base)

    order = {item["key"]: idx for idx, item in enumerate(BUILTIN_PERM_META)}
    return sorted(perms, key=lambda k: (order.get(k, 1000), k))


def get_all_permissions_meta() -> list[dict]:
    """返回动态发现的完整权限元数据列表 (供 WebUI 前端矩阵渲染)"""
    discovered = discover_all_permissions()
    meta_map = {item["key"]: dict(item) for item in BUILTIN_PERM_META}
    result = []
    for key in discovered:
        if key in meta_map:
            result.append(meta_map[key])
        else:
            result.append({
                "key": key,
                "label": f"nav.{key}",
                "icon": "📄",
                "name": key.capitalize(),
            })
    return result


# 所有可能的权限 (动态发现)
ALL_PERMISSIONS = discover_all_permissions()

# ===== 默认角色 =====

DEFAULT_ROLES = {
    "admin": {
        "label": "管理员",
        "permissions": discover_all_permissions(),
    },
    "operator": {
        "label": "操作员",
        "permissions": [
            "dashboard", "mods", "studio", "console", "banlist", "audit",
            "scheduler",
        ],
    },
    "viewer": {
        "label": "访客",
        "permissions": [
            "dashboard", "mods",
        ],
    },
}


# ===== 用户管理器 =====

class UserManager:
    """用户管理:加载/保存/认证/会话管理"""

    def __init__(self):
        self._users: list[dict] = []
        self._roles: dict = dict(DEFAULT_ROLES)
        self._sessions: dict[str, dict] = {}  # token → {username, role, permissions, expires}
        self._lock = threading.Lock()
        self._loaded = False
        self._first_run_password: Optional[str] = None  # 首次运行/迁移时记录的 admin 明文密码

    # ---- 数据加载/保存 ----

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()

    def load(self):
        """从 users.json 加载用户和角色"""
        if os.path.exists(USERS_JSON):
            try:
                with open(USERS_JSON, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._users = data.get("users", [])
                if data.get("roles"):
                    current_all = discover_all_permissions()
                    # 合并:确保新版本新增的权限不会因旧 users.json 而丢失
                    for role_name, default_info in DEFAULT_ROLES.items():
                        existing = data["roles"].get(role_name, {})
                        existing_perms = set(existing.get("permissions", []))
                        default_perms = set(default_info.get("permissions", []))
                        merged = existing_perms | default_perms  # 并集,只增不减
                        if role_name == "admin":
                            merged = merged | set(current_all)
                        if merged != existing_perms:
                            existing["permissions"] = sorted(merged)
                        data["roles"][role_name] = existing
                    self._roles = data["roles"]
                self._loaded = True
                return
            except Exception:
                pass
        # 无 users.json → 初始化
        self._first_run_init()
        self._loaded = True

    def _first_run_init(self):
        """首次运行:从旧 token 迁移或创建默认 admin + guest"""
        # 尝试读取旧令牌
        old_token = self._read_old_token()
        if old_token:
            admin_password = old_token  # 旧令牌直接作为密码
            self._first_run_password = admin_password
        else:
            admin_password = secrets.token_urlsafe(16)
            self._first_run_password = admin_password

        self._users = [
            {
                "username": "admin",
                "password_hash": hash_password(admin_password),
                "role": "admin",
                "enabled": True,
                "system": True,  # 标记为系统用户,不可删除
            },
            {
                "username": "guest",
                "password_hash": "",
                "role": "viewer",
                "enabled": True,
                "system": True,
            },
        ]
        self.save()

    def _read_old_token(self) -> str:
        """尝试从旧配置读取 webuiConfig.token"""
        try:
            ns = {}
            config_json = os.path.join(CONFIG_DIR, "config.json")
            config_py = os.path.join(CONFIG_DIR, "config.py")
            if os.path.exists(config_json):
                with open(config_json, "r", encoding="utf-8") as f:
                    ns = json.load(f)
            elif os.path.exists(config_py):
                import importlib.util
                spec = importlib.util.spec_from_file_location("_cfg", config_py)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    ns = {k: v for k, v in vars(mod).items() if not k.startswith("_")}
            token = str(ns.get("webuiConfig", {}).get("token", "") or "").strip()
            return token
        except Exception:
            return ""

    def save(self):
        """保存用户和角色到 users.json"""
        with self._lock:
            data = {
                "users": self._users,
                "roles": self._roles,
            }
            tmp = USERS_JSON + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, USERS_JSON)

    # ---- 用户 CRUD ----

    def get_effective_permissions(self, username: str) -> list[str]:
        """计算用户的有效权限(角色基础 + 用户覆盖,拒绝优先于允许)"""
        self._ensure_loaded()
        user = self.get_user(username)
        if not user:
            return []
        role_name = user.get("role", "viewer")
        role_perms = set(self._roles.get(role_name, {}).get("permissions", []))
        overrides = user.get("permissions", {})
        no_inherit = user.get("no_role_inherit", False)
        result = []
        for perm in discover_all_permissions():
            override = overrides.get(perm)
            if override is False:
                continue  # 明确拒绝
            elif override is True:
                result.append(perm)  # 明确允许
            elif not no_inherit and perm in role_perms:
                result.append(perm)  # 继承角色(仅当未开启不继承)
        return result

    def list_users(self) -> list[dict]:
        """返回用户列表(隐藏密码哈希)"""
        self._ensure_loaded()
        return [
            {
                "username": u["username"],
                "role": u.get("role", "viewer"),
                "permissions": u.get("permissions", {}),
                "no_role_inherit": u.get("no_role_inherit", False),
                "enabled": u.get("enabled", True),
                "system": u.get("system", False),
                "system_reserved": u.get("system_reserved", False),
            }
            for u in self._users
        ]

    def get_user(self, username: str) -> Optional[dict]:
        self._ensure_loaded()
        for u in self._users:
            if u["username"] == username:
                return u
        return None

    def add_user(self, username: str, password: str, role: str = "viewer", permissions: dict = None, no_role_inherit: bool = False) -> dict:
        """添加用户"""
        self._ensure_loaded()
        if not username:
            return {"ok": False, "message": "用户名不能为空"}
        if self.get_user(username):
            return {"ok": False, "message": f"用户 {username} 已存在"}
        if role not in self._roles:
            return {"ok": False, "message": f"角色 {role} 不存在"}
        user = {
            "username": username,
            "password_hash": hash_password(password) if password else "",
            "role": role,
            "permissions": permissions or {},
            "no_role_inherit": bool(no_role_inherit),
            "enabled": True,
        }
        with self._lock:
            self._users.append(user)
        self.save()
        return {"ok": True, "message": f"用户 {username} 已创建"}

    def update_user(self, username: str, **kwargs) -> dict:
        """更新用户(密码/角色/权限覆盖/启用状态/不继承)"""
        self._ensure_loaded()
        user = self.get_user(username)
        if not user:
            return {"ok": False, "message": f"用户 {username} 不存在"}
        with self._lock:
            if "password" in kwargs and kwargs["password"]:
                user["password_hash"] = hash_password(kwargs["password"])
            if "role" in kwargs:
                if kwargs["role"] not in self._roles:
                    return {"ok": False, "message": f"角色 {kwargs['role']} 不存在"}
                user["role"] = kwargs["role"]
            if "permissions" in kwargs:
                # 合并权限覆盖:只接受 discover_all_permissions() 中的有效值
                raw = kwargs["permissions"]
                if isinstance(raw, dict):
                    valid_perms = set(discover_all_permissions())
                    cleaned = {}
                    for k, v in raw.items():
                        if k in valid_perms and isinstance(v, bool):
                            cleaned[k] = v
                    user["permissions"] = cleaned
            if "no_role_inherit" in kwargs:
                user["no_role_inherit"] = bool(kwargs["no_role_inherit"])
            if "system_reserved" in kwargs:
                user["system_reserved"] = bool(kwargs["system_reserved"])
            if "enabled" in kwargs:
                user["enabled"] = bool(kwargs["enabled"])
        self.save()
        # 刷新该用户的所有在线会话权限
        effective = self.get_effective_permissions(username)
        with self._lock:
            for session in self._sessions.values():
                if session["username"] == username:
                    session["permissions"] = effective
        return {"ok": True, "message": f"用户 {username} 已更新"}

    def delete_user(self, username: str) -> dict:
        """删除用户(系统用户/系统保留账户不可删除)"""
        self._ensure_loaded()
        user = self.get_user(username)
        if not user:
            return {"ok": False, "message": f"用户 {username} 不存在"}
        if user.get("system") or user.get("system_reserved"):
            return {"ok": False, "message": f"系统用户 {username} 不可删除"}
        with self._lock:
            self._users = [u for u in self._users if u["username"] != username]
        self.save()
        return {"ok": True, "message": f"用户 {username} 已删除"}

    def verify_admin_password(self, password: str) -> bool:
        """验证 admin 账户密码(非 admin 用户编辑他人时需调用)"""
        self._ensure_loaded()
        admin = self.get_user("admin")
        if not admin:
            return False
        return verify_password(password, admin.get("password_hash", ""))

    # ---- 认证 ----

    def authenticate(self, username: str, password: str) -> dict:
        """验证用户名密码,成功返回 {ok, token, role, permissions}"""
        self._ensure_loaded()
        user = self.get_user(username)
        if not user:
            try:
                from lib import shared
                shared.logger.warning(f"[users] 认证失败: 用户名 [{username}] 不存在")
            except Exception:
                pass
            return {"ok": False, "message": "用户名或密码错误"}
        if not user.get("enabled", True):
            try:
                from lib import shared
                shared.logger.warning(f"[users] 认证失败: 用户 [{username}] 已被禁用")
            except Exception:
                pass
            return {"ok": False, "message": "该账户已被禁用"}
        if not verify_password(password, user.get("password_hash", "")):
            try:
                from lib import shared
                shared.logger.warning(f"[users] 认证失败: 用户 [{username}] 密码验证未通过 (哈希前缀: {user.get('password_hash', '')[:7]}, 输入密码长度: {len(password)})")
            except Exception:
                pass
            return {"ok": False, "message": "用户名或密码错误"}
        # 生成会话 token
        token = secrets.token_hex(32)
        role = user.get("role", "viewer")
        permissions = self.get_effective_permissions(username)
        with self._lock:
            self._sessions[token] = {
                "username": username,
                "role": role,
                "permissions": permissions,
                "system": user.get("system", False),
                "expires": time.time() + 86400 * 7,  # 7 天
            }
        return {"ok": True, "token": token, "role": role, "permissions": permissions, "username": username, "system": user.get("system", False)}

    def validate_session(self, token: str) -> Optional[dict]:
        """验证会话 token,返回 {username, role, permissions} 或 None"""
        if not token:
            return None
        with self._lock:
            session = self._sessions.get(token)
        if not session:
            return None
        if time.time() > session["expires"]:
            with self._lock:
                self._sessions.pop(token, None)
            return None
        return session

    def logout(self, token: str):
        """注销会话"""
        with self._lock:
            self._sessions.pop(token, None)

    # ---- 角色管理 ----

    def get_roles(self) -> dict:
        """返回角色列表"""
        self._ensure_loaded()
        return dict(self._roles)

    def add_role(self, name: str, label: str = None, permissions: list = None) -> dict:
        """新增自定义角色"""
        self._ensure_loaded()
        if not name:
            return {"ok": False, "message": "角色名不能为空"}
        if name in self._roles:
            return {"ok": False, "message": f"角色 {name} 已存在"}
        valid_perms = set(discover_all_permissions())
        self._roles[name] = {
            "label": label or name,
            "permissions": [p for p in (permissions or []) if p in valid_perms],
        }
        self.save()
        return {"ok": True, "message": f"角色 {name} 已创建"}

    def delete_role(self, name: str) -> dict:
        """删除自定义角色(内置角色不可删除)"""
        self._ensure_loaded()
        builtins = {"admin", "operator", "viewer"}
        if name in builtins:
            return {"ok": False, "message": f"内置角色 {name} 不可删除"}
        if name not in self._roles:
            return {"ok": False, "message": f"角色 {name} 不存在"}
        # 检查是否有用户正在使用该角色
        for u in self._users:
            if u.get("role") == name:
                return {"ok": False, "message": f"角色 {name} 正在被用户 {u['username']} 使用,请先修改该用户的角色"}
        with self._lock:
            del self._roles[name]
        self.save()
        return {"ok": True, "message": f"角色 {name} 已删除"}

    def update_role(self, role_name: str, label: str = None, permissions: list = None) -> dict:
        """更新角色(权限)"""
        self._ensure_loaded()
        if role_name not in self._roles:
            self._roles[role_name] = {"label": role_name, "permissions": []}
        if label is not None:
            self._roles[role_name]["label"] = label
        if permissions is not None:
            # 验证权限值
            valid_perms = set(discover_all_permissions())
            valid = [p for p in permissions if p in valid_perms]
            self._roles[role_name]["permissions"] = valid
        self.save()
        # 刷新所有使用该角色的在线会话权限(用户可能有自定义覆盖,需重新计算)
        with self._lock:
            for session in self._sessions.values():
                if session["role"] == role_name:
                    session["permissions"] = self.get_effective_permissions(session["username"])
        return {"ok": True, "message": f"角色 {role_name} 已更新"}


# 全局实例
user_manager = UserManager()
