// ===== 权限管理页面逻辑 =====
var permData = { owner: "YourXboxName", op: [], user: [], blocker: [] };

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
