// ===== Mod 管理页面逻辑 =====
requireAuth(function (role) {
  initSidebar("mods", role);
  initTheme();
  initLang();
  loadMods();
  // 访客隐藏重载按钮
  if (role === "guest") {
    var reloadAll = $("modReloadAll");
    if (reloadAll) reloadAll.style.display = "none";
  }
});

function loadMods() {
  api("/mods").then(function (data) {
    if (!data.ok) return;
    $("modBodyClient").innerHTML = renderModRows(data.mods.client, "client");
    $("modBodyServer").innerHTML = renderModRows(data.mods.server, "server");
  }).catch(function () {});
}

function renderModRows(mods, side) {
  var keys = Object.keys(mods || {});
  if (!keys.length) return '<tr><td colspan="4" class="td-faint">' + t("mods.empty") + '</td></tr>';
  return keys.map(function (name) {
    var info = mods[name];
    var ok = info.importable;
    return '<tr><td>' + escapeHtml(name) + '</td><td class="td-dim">' + escapeHtml(info.path) +
      '</td><td><span class="status-dot ' + (ok ? "ok" : "bad") + '"></span>' + (ok ? t("mods.importOk") : t("mods.importFail")) +
      '</td><td><button class="btn btn-sm mod-reload-btn" data-name="' + escapeHtml(name) + '" data-side="' + side + '">' + t("mods.reload") + '</button></td></tr>';
  }).join("");
}

function reloadMod(name, side, btn) {
  btn.disabled = true;
  btn.textContent = "⏳";
  api("/mods/reload", { method: "POST", body: JSON.stringify({ name: name, side: side }) })
    .then(function (data) { toast(data.message || t("mods.reloadDone"), data.ok ? "ok" : "err"); })
    .catch(function () { toast(t("mods.reqFail"), "err"); })
    .finally(function () { btn.disabled = false; btn.textContent = t("mods.reload"); });
}

// 刷新按钮
var modRefreshBtn = $("modRefresh");
if (modRefreshBtn) modRefreshBtn.addEventListener("click", loadMods);

// 重载所有
var modReloadAllBtn = $("modReloadAll");
if (modReloadAllBtn) {
  modReloadAllBtn.addEventListener("click", function () {
    var btn = this;
    btn.disabled = true;
    api("/mods/reload-all", { method: "POST" })
      .then(function (data) { toast(data.message || t("mods.reloadDone"), data.ok ? "ok" : "err"); })
      .catch(function () {})
      .finally(function () { btn.disabled = false; });
  });
}

// 单个 Mod 重载(事件委托)
document.addEventListener("click", function (e) {
  var btn = e.target.closest(".mod-reload-btn");
  if (!btn) return;
  reloadMod(btn.dataset.name, btn.dataset.side, btn);
});
