// ===== 权限管理页面逻辑 =====
var permData = { owner: "YourXboxName", op: [], user: [], blocker: [] };
var _PERM_META = [
  { key: "dashboard", label: "📊 仪表盘" },
  { key: "config",    label: "⚙️ 功能设置" },
  { key: "mods",      label: "🧩 Mod 管理" },
  { key: "console",   label: "💻 控制台" },
  { key: "permissions", label: "👥 权限管理" },
  { key: "audit",     label: "📋 审计日志" },
  { key: "update",    label: "🔄 检查更新" },
  { key: "restart",   label: "🔁 重启服务器" }
];

requireAuth(function (role) {
  initSidebar("permissions", role);
  initTheme();
  loadPermissions();
});

function loadPermissions() {
  api("/permissions").then(function (data) {
    if (!data.ok) return;
    permData = data.permissions;
    $("perm-owner").value = permData.owner || "";
    ["op", "user", "blocker"].forEach(function (g) {
      var list = permData[g] || [];
      $("count-" + g).textContent = list.length + " 人";
      $("chips-" + g).innerHTML = list.map(function (name) {
        return '<span class="chip">' + escapeHtml(name) + '<span class="x" data-group="' + g + '" data-name="' + escapeHtml(name) + '">✕</span></span>';
      }).join("") || '<span class="hint">暂无成员</span>';
    });
  }).catch(function () {});
}

function savePerm(tip) {
  permData.owner = $("perm-owner").value.trim() || "YourXboxName";
  return api("/permissions", { method: "PUT", body: JSON.stringify({ permissions: permData }) })
    .then(function (data) {
      toast(data.message || tip, data.ok ? "ok" : "err");
      if (data.ok) loadPermissions();
    }).catch(function () {});
}

// 添加按钮
document.querySelectorAll('[data-group]').forEach(function (btn) {
  if (btn.tagName === "BUTTON") {
    btn.addEventListener("click", function () {
      var g = btn.getAttribute("data-group");
      var input = $("input-" + g);
      var name = input.value.trim();
      if (!name) return;
      permData[g] = permData[g] || [];
      if (permData[g].indexOf(name) < 0) {
        permData[g].push(name);
        savePerm("已添加 " + name + " → " + g);
      } else {
        toast(name + " 已在 " + g + " 列表中", "err");
      }
      input.value = "";
    });
  }
});

// 删除(x 按钮)
document.addEventListener("click", function (e) {
  if (e.target.classList.contains("x")) {
    var g = e.target.getAttribute("data-group");
    var name = e.target.getAttribute("data-name");
    permData[g] = (permData[g] || []).filter(function (n) { return n !== name; });
    savePerm("已移除 " + name + " ← " + g);
  }
});

var permSaveBtn = $("permSave");
if (permSaveBtn) permSaveBtn.addEventListener("click", function () { savePerm("权限已保存"); });

var permReloadBtn = $("permReload");
if (permReloadBtn) permReloadBtn.addEventListener("click", function () { loadPermissions(); toast("已重新加载", "ok"); });

// ===== 用户管理 =====
var _allRoles = {};

function loadUsers() {
  api("/users").then(function (data) {
    if (!data.ok) return;
    var tbody = $("userTableBody");
    if (!data.users.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="muted" style="text-align:center;padding:20px">暂无用户,请添加</td></tr>';
      return;
    }
    tbody.innerHTML = data.users.map(function (u) {
      var roleLabel = (_allRoles[u.role] || {}).label || u.role;
      var isDisabled = u.enabled === false;
      var me = getCurrentUser();
      var isMe = me.username === u.username;
      var isSystem = u.system;
      var statusHtml = isDisabled
        ? '<span style="color:var(--err)">禁用</span>'
        : '<span style="color:var(--accent)">启用</span>';
      // 启用/禁用按钮
      var toggleBtn = isMe ? '' // 不能禁用自己
        : '<button class="btn btn-sm" onclick="toggleUser(\'' + escapeHtml(u.username) + '\',' + (isDisabled ? 'true' : 'false') + ')" title="' + (isDisabled ? '启用' : '禁用') + '">'
        + (isDisabled ? '🔓' : '🔒') + '</button> ';
      // 删除按钮(系统用户不可删除)
      var delBtn = (isMe || isSystem) ? ''
        : '<button class="btn btn-sm" style="color:var(--err)" onclick="deleteUser(\'' + escapeHtml(u.username) + '\')">🗑️</button>';
      return '<tr>'
        + '<td>' + escapeHtml(u.username) + (isMe ? ' <span class="muted">(你)</span>' : '') + (isSystem ? ' <span class="muted">系统</span>' : '') + '</td>'
        + '<td><span class="chip">' + escapeHtml(roleLabel) + '</span></td>'
        + '<td>' + statusHtml + '</td>'
        + '<td>'
        + '<button class="btn btn-sm" onclick="editUser(\'' + escapeHtml(u.username) + '\')">✏️</button> '
        + toggleBtn + delBtn
        + '</td></tr>';
    }).join("");
  }).catch(function () {});
}

function loadRoles() {
  api("/roles").then(function (data) {
    if (!data.ok) return;
    _allRoles = data.roles;
    var container = $("roleList");
    var builtins = ["admin", "operator", "viewer"];
    var html = "";
    for (var name in data.roles) {
      var role = data.roles[name];
      var perms = role.permissions || [];
      var isBuiltin = builtins.indexOf(name) !== -1;
      var delBtn = isBuiltin ? '' : ' <button class="btn btn-sm" style="color:var(--err);font-size:0.8em;margin-left:8px;" onclick="deleteRole(\'' + escapeHtml(name) + '\')">🗑️ 删除</button>';
      html += '<div class="perm-group" style="margin-bottom:16px;">'
        + '<div style="font-weight:600;margin-bottom:4px;">' + escapeHtml(role.label || name)
        + ' <span class="muted" style="font-weight:400;">(' + escapeHtml(name) + ')</span>'
        + delBtn + '</div>'
        + '<div class="row gap-10" style="flex-wrap:wrap;">';
      _PERM_META.forEach(function (p) {
        var checked = perms.indexOf(p.key) !== -1 ? "checked" : "";
        html += '<label style="display:flex;align-items:center;gap:4px;cursor:pointer;font-size:0.9em;">'
          + '<input type="checkbox" data-role="' + name + '" data-perm="' + p.key + '" ' + checked + '>'
          + p.label + '</label>';
      });
      html += '</div></div>';
    }
    container.innerHTML = html;
  }).catch(function () {});
}

// 角色保存
var roleSaveBtn = $("roleSaveBtn");
if (roleSaveBtn) roleSaveBtn.addEventListener("click", function () {
  var checkboxes = document.querySelectorAll('#roleList input[type="checkbox"]');
  var rolePerms = {};
  checkboxes.forEach(function (cb) {
    var role = cb.getAttribute("data-role");
    var perm = cb.getAttribute("data-perm");
    if (!rolePerms[role]) rolePerms[role] = [];
    if (cb.checked) rolePerms[role].push(perm);
  });
  // 逐个角色保存
  var promises = Object.keys(rolePerms).map(function (roleName) {
    return api("/roles", { method: "PUT", body: JSON.stringify({ role: roleName, permissions: rolePerms[roleName] }) });
  });
  Promise.all(promises).then(function (results) {
    var allOk = results.every(function (r) { return r.ok; });
    toast(allOk ? "角色配置已保存" : "部分保存失败", allOk ? "ok" : "err");
    if (allOk) {
      loadRoles();
      // 刷新当前用户权限缓存
      api("/auth/me").then(function (d) {
        if (d.ok) {
          sessionStorage.setItem("enderbridge_user", JSON.stringify({
            username: d.username, role: d.role, permissions: d.permissions || []
          }));
        }
      }).catch(function(){});
    }
  }).catch(function () { toast("保存失败", "err"); });
});

// ===== 新建角色 =====
var roleAddBtn = $("roleAddBtn");
if (roleAddBtn) roleAddBtn.addEventListener("click", function () {
  $("roleNameInput").value = "";
  $("roleLabelInput").value = "";
  $("roleModal").style.display = "flex";
});

var roleModalCancel = $("roleModalCancel");
if (roleModalCancel) roleModalCancel.addEventListener("click", function () {
  $("roleModal").style.display = "none";
});

var roleModalConfirm = $("roleModalConfirm");
if (roleModalConfirm) roleModalConfirm.addEventListener("click", function () {
  var name = $("roleNameInput").value.trim().toLowerCase();
  var label = $("roleLabelInput").value.trim();
  if (!name) { toast("请输入角色标识", "err"); return; }
  if (!/^[a-z][a-z0-9_]*$/.test(name)) { toast("角色标识只能包含小写字母、数字和下划线", "err"); return; }
  api("/roles", { method: "POST", body: JSON.stringify({ name: name, label: label || name, permissions: [] }) })
    .then(function (data) {
      toast(data.message || "已创建", data.ok ? "ok" : "err");
      if (data.ok) {
        $("roleModal").style.display = "none";
        loadRoles();
        loadUsers();  // 刷新用户列表的角色下拉
      }
    }).catch(function () {});
});

// 点击角色弹窗外部关闭
var roleModal = $("roleModal");
if (roleModal) roleModal.addEventListener("click", function (e) {
  if (e.target === roleModal) roleModal.style.display = "none";
});

// 添加用户
var userAddBtn = $("userAddBtn");
if (userAddBtn) userAddBtn.addEventListener("click", function () {
  $("userModalTitle").textContent = "添加用户";
  $("modalUsername").value = "";
  $("modalUsername").disabled = false;
  $("modalPassword").value = "";
  $("modalPassword").placeholder = "密码";
  fillRoleSelect();
  $("modalRole").value = "viewer";
  fillUserPermOverrides({}, false);  // 新用户默认继承
  $("userModal").style.display = "flex";
});

// 编辑用户
function editUser(username) {
  $("userModalTitle").textContent = "编辑用户 - " + username;
  $("modalUsername").value = username;
  $("modalUsername").disabled = true;
  $("modalPassword").value = "";
  $("modalPassword").placeholder = "留空则不修改";
  fillRoleSelect();
  // 查找用户并设置角色+权限覆盖
  api("/users").then(function (data) {
    if (data.ok) {
      var user = data.users.find(function (u) { return u.username === username; });
      if (user) {
        $("modalRole").value = user.role;
        fillUserPermOverrides(user.permissions || {}, user.no_role_inherit || false);
      }
    }
  });
  $("userModal").style.display = "flex";
}

function fillRoleSelect() {
  var sel = $("modalRole");
  sel.innerHTML = "";
  for (var name in _allRoles) {
    var opt = document.createElement("option");
    opt.value = name;
    opt.textContent = (_allRoles[name].label || name) + " (" + name + ")";
    sel.appendChild(opt);
  }
}

// 三态权限覆盖: inherit / allow / deny + 不继承开关
function fillUserPermOverrides(overrides, noRoleInherit) {
  var container = $("userPermOverrides");
  var html = '<div style="margin-bottom:8px;">'
    + '<label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:0.88em;font-weight:500;">'
    + '<input type="checkbox" id="noRoleInheritToggle"' + (noRoleInherit ? ' checked' : '') + '>'
    + '<span>🚫 不继承角色权限(完全自定义)</span>'
    + '</label>'
    + '<div class="muted" style="margin:2px 0 0 22px;font-size:0.8em;">开启后此用户不从角色继承任何权限,仅保留下方显式设置的权限</div>'
    + '</div>';
  html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:4px 16px;">';
  _PERM_META.forEach(function (p) {
    var val = overrides[p.key];  // undefined=inherit, true=allow, false=deny
    var stateInherit = (val === undefined) ? ' checked' : '';
    var stateAllow = (val === true) ? ' checked' : '';
    var stateDeny = (val === false) ? ' checked' : '';
    html += '<div style="display:flex;align-items:center;gap:2px;font-size:0.88em;">'
      + '<span style="min-width:100px;">' + p.label + '</span>'
      + '<label title="继承角色" style="cursor:pointer;color:var(--muted);">'
      + '<input type="radio" name="perm_' + p.key + '" value="inherit"' + stateInherit + '> 继承</label>'
      + '<label title="明确允许" style="cursor:pointer;color:var(--ok);">'
      + '<input type="radio" name="perm_' + p.key + '" value="allow"' + stateAllow + '> ✅</label>'
      + '<label title="明确拒绝" style="cursor:pointer;color:var(--err);">'
      + '<input type="radio" name="perm_' + p.key + '" value="deny"' + stateDeny + '> ❌</label>'
      + '</div>';
  });
  html += '</div>';
  container.innerHTML = html;
  // 不继承开关:切换时更新继承列视觉状态
  var toggle = $("noRoleInheritToggle");
  toggle.addEventListener("change", function () {
    _updateInheritVisuals(toggle.checked);
  });
  _updateInheritVisuals(noRoleInherit);
}

function _updateInheritVisuals(noInherit) {
  var inherits = document.querySelectorAll('input[name^="perm_"][value="inherit"]');
  inherits.forEach(function (r) {
    var label = r.parentElement;
    if (noInherit) {
      label.style.opacity = "0.35";
      label.style.textDecoration = "line-through";
      label.title = "已禁用:不继承角色";
    } else {
      label.style.opacity = "1";
      label.style.textDecoration = "none";
      label.title = "继承角色";
    }
  });
}

function collectUserPermOverrides() {
  var result = { permissions: {}, no_role_inherit: false };
  var toggle = $("noRoleInheritToggle");
  result.no_role_inherit = toggle ? toggle.checked : false;
  _PERM_META.forEach(function (p) {
    var radios = document.querySelectorAll('input[name="perm_' + p.key + '"]');
    radios.forEach(function (r) {
      if (r.checked) {
        if (r.value === "allow") result.permissions[p.key] = true;
        else if (r.value === "deny") result.permissions[p.key] = false;
        // inherit = don't set key
      }
    });
  });
  return result;
}

// 删除用户
function deleteUser(username) {
  if (!confirm("确定要删除用户 " + username + " 吗?")) return;
  api("/users", { method: "DELETE", body: JSON.stringify({ username: username }) })
    .then(function (data) {
      toast(data.message || "已删除", data.ok ? "ok" : "err");
      if (data.ok) loadUsers();
    }).catch(function () {});
}

// 启用/禁用用户
function toggleUser(username, enable) {
  var action = enable ? "启用" : "禁用";
  if (!confirm("确定要" + action + "用户 " + username + " 吗?")) return;
  api("/users", { method: "PUT", body: JSON.stringify({ username: username, enabled: enable }) })
    .then(function (data) {
      toast(data.message || ("已" + action), data.ok ? "ok" : "err");
      if (data.ok) loadUsers();
    }).catch(function () {});
}

// 弹窗操作
var modalCancel = $("modalCancel");
if (modalCancel) modalCancel.addEventListener("click", function () { $("userModal").style.display = "none"; });

var modalConfirm = $("modalConfirm");
if (modalConfirm) modalConfirm.addEventListener("click", function () {
  var username = $("modalUsername").value.trim();
  var password = $("modalPassword").value;
  var role = $("modalRole").value;
  if (!username) { toast("请输入用户名", "err"); return; }
  var isEdit = $("modalUsername").disabled;
  var permData = collectUserPermOverrides();
  var permOverrides = permData.permissions;
  var noRoleInherit = permData.no_role_inherit;
  if (isEdit) {
    // 编辑模式
    var body = { username: username, role: role, permissions: permOverrides, no_role_inherit: noRoleInherit };
    if (password) body.password = password;
    api("/users", { method: "PUT", body: JSON.stringify(body) })
      .then(function (data) {
        toast(data.message || "已更新", data.ok ? "ok" : "err");
        if (data.ok) { $("userModal").style.display = "none"; loadUsers(); }
      }).catch(function () {});
  } else {
    // 新增模式
    if (!password) { toast("请输入密码", "err"); return; }
    api("/users", { method: "POST", body: JSON.stringify({ username: username, password: password, role: role, permissions: permOverrides, no_role_inherit: noRoleInherit }) })
      .then(function (data) {
        toast(data.message || "已创建", data.ok ? "ok" : "err");
        if (data.ok) { $("userModal").style.display = "none"; loadUsers(); }
      }).catch(function () {});
  }
});

// 点击弹窗外部关闭
var userModal = $("userModal");
if (userModal) userModal.addEventListener("click", function (e) {
  if (e.target === userModal) userModal.style.display = "none";
});

// 页面加载时加载用户和角色
loadUsers();
loadRoles();

// 删除自定义角色
function deleteRole(name) {
  if (!confirm("确定要删除角色 " + name + " 吗?")) return;
  api("/roles", { method: "DELETE", body: JSON.stringify({ name: name }) })
    .then(function (data) {
      toast(data.message || "已删除", data.ok ? "ok" : "err");
      if (data.ok) { loadRoles(); loadUsers(); }
    }).catch(function () {});
}
