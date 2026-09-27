"""test_permissions_meta.py — 动态权限自适应扫描与 Studio 专属权限测试"""

import os
import json
import pytest
import tempfile
from lib.users import (
    discover_all_permissions,
    get_all_permissions_meta,
    UserManager,
    ALL_PERMISSIONS,
    DEFAULT_ROLES,
)
from webui.server import WebUIHandler


def test_discover_all_permissions_contains_all_core_and_pages():
    perms = discover_all_permissions()
    assert isinstance(perms, list)
    # 核心页面权限必须被发现
    expected_pages = [
        "dashboard", "config", "mods", "studio", "console",
        "scheduler", "permissions", "banlist", "audit", "update",
    ]
    for p in expected_pages:
        assert p in perms, f"权限项 {p} 未在自动发现列表中"
    # 操作级权限必须存在
    assert "restart" in perms


def test_get_all_permissions_meta():
    meta = get_all_permissions_meta()
    assert isinstance(meta, list)
    keys = [item["key"] for item in meta]
    assert "studio" in keys
    assert "scheduler" in keys
    assert "restart" in keys

    studio_item = next(item for item in meta if item["key"] == "studio")
    assert studio_item["icon"] == "🎨"
    assert studio_item["label"] == "nav.studio"


def test_admin_role_auto_merges_all_discovered_permissions(tmp_path, monkeypatch):
    """测试旧 users.json 缺少 studio/scheduler 时，系统加载会自动补齐 admin 权限"""
    users_file = tmp_path / "users.json"
    old_data = {
        "users": [
            {"username": "admin", "password_hash": "hash", "role": "admin", "enabled": True}
        ],
        "roles": {
            "admin": {
                "label": "管理员",
                "permissions": ["dashboard", "config", "mods"]  # 旧版本，缺少 studio 等
            },
            "viewer": {
                "label": "访客",
                "permissions": ["dashboard"]
            }
        }
    }
    with open(users_file, "w", encoding="utf-8") as f:
        json.dump(old_data, f)

    monkeypatch.setattr("lib.users.USERS_JSON", str(users_file))
    mgr = UserManager()
    mgr.load()

    roles = mgr.get_roles()
    admin_perms = roles["admin"]["permissions"]
    assert "studio" in admin_perms
    assert "scheduler" in admin_perms
    assert "restart" in admin_perms
    # 访客不受影响
    assert "studio" not in roles["viewer"]["permissions"]


def test_api_permissions_meta_endpoint():
    class DummyHandler:
        def __init__(self, user_perms=None):
            self.user_perms = user_perms or ["permissions"]
            self.responses = []
            self.headers = {"Content-Type": "application/json"}

        def _respond(self, data, status=200):
            self.responses.append((status, data))

    DummyHandler._api_get_permissions_meta = WebUIHandler._api_get_permissions_meta

    handler = DummyHandler(["permissions"])
    # 模拟权限装饰器
    import webui.server
    orig_req = webui.server._require_permission
    try:
        webui.server._require_permission = lambda perm: (lambda h: True if perm in h.user_perms else False)
        handler._api_get_permissions_meta()
        assert len(handler.responses) == 1
        status, data = handler.responses[0]
        assert status == 200
        assert data["ok"] is True
        perm_keys = [p["key"] for p in data["permissions"]]
        assert "studio" in perm_keys
        assert "scheduler" in perm_keys
    finally:
        webui.server._require_permission = orig_req


def test_studio_requires_studio_permission():
    class DummyStudioHandler:
        def __init__(self, user_perms):
            self.path = "/api/studio/assets"
            self.user_perms = user_perms
            self.responses = []
            self.headers = {"Content-Type": "application/json"}

        def _respond(self, data, status=200):
            self.responses.append((status, data))

    DummyStudioHandler._api_studio_get_assets = WebUIHandler._api_studio_get_assets

    import webui.server
    orig_req = webui.server._require_permission
    try:
        webui.server._require_permission = lambda perm: (
            lambda h: True if perm in h.user_perms else (h._respond({"ok": False, "message": f"需要 {perm} 权限"}, status=403) or False)
        )
        # 仅有 mods 权限但没有 studio 权限的用户访问 Studio 应该被拒绝
        h_deny = DummyStudioHandler(["mods"])
        h_deny._api_studio_get_assets()
        assert len(h_deny.responses) == 1
        assert h_deny.responses[0][0] == 403
        assert "studio" in h_deny.responses[0][1]["message"]

        # 拥有 studio 权限的用户正常访问
        h_allow = DummyStudioHandler(["studio"])
        h_allow._api_studio_get_assets()
        assert len(h_allow.responses) == 1
        assert h_allow.responses[0][0] == 200
        assert h_allow.responses[0][1]["ok"] is True
    finally:
        webui.server._require_permission = orig_req
