// ===== Mod 管理页面逻辑 =====
requireAuth(function (role) {
  initSidebar("mods", role);
  loadMods();
});

function loadMods() {
  api("/mods").then(function (data) {
    if (!data.ok) return;
    $("modBodyClient").innerHTML = renderModRows(data.mods.client);
    $("modBodyServer").innerHTML = renderModRows(data.mods.server);
  }).catch(function () {});
}

function renderModRows(mods) {
  var keys = Object.keys(mods || {});
  if (!keys.length) return '<tr><td colspan="3" class="td-faint">无</td></tr>';
  return keys.map(function (name) {
    var info = mods[name];
    var ok = info.importable;
    return '<tr><td>' + escapeHtml(name) + '</td><td class="td-dim">' + escapeHtml(info.path) +
      '</td><td><span class="status-dot ' + (ok ? "ok" : "bad") + '"></span>' + (ok ? "可导入" : "导入失败") + '</td></tr>';
  }).join("");
}

var modRefreshBtn = $("modRefresh");
if (modRefreshBtn) modRefreshBtn.addEventListener("click", loadMods);

var modReloadAllBtn = $("modReloadAll");
if (modReloadAllBtn) {
  modReloadAllBtn.addEventListener("click", function () {
    var btn = this;
    btn.disabled = true;
    api("/mods/reload-all", { method: "POST" })
      .then(function (data) { toast(data.message || "重载完成", data.ok ? "ok" : "err"); })
      .catch(function () {})
      .finally(function () { btn.disabled = false; });
  });
}
