// ===== Mod 管理页面逻辑 (含实时搜索与状态分类 Tab) =====
var _allMods = { client: {}, server: {} };
var _activeTab = "all"; // "all" | "active" | "failed"
var _searchKeyword = "";

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
  var refreshBtn = $("modRefresh");
  if (refreshBtn) refreshBtn.disabled = true;
  api("/mods").then(function (data) {
    if (!data.ok) return;
    _allMods = data.mods || { client: {}, server: {} };
    updateTabCounts();
    renderFilteredMods();
  }).catch(function () {
    toast(t("mods.reqFail"), "err");
  }).finally(function () {
    if (refreshBtn) refreshBtn.disabled = false;
  });
}

function updateTabCounts() {
  var total = 0;
  var active = 0;
  var failed = 0;

  ["client", "server"].forEach(function (side) {
    var list = _allMods[side] || {};
    Object.keys(list).forEach(function (name) {
      total++;
      if (list[name].importable) active++;
      else failed++;
    });
  });

  if ($("cntAll")) $("cntAll").textContent = "(" + total + ")";
  if ($("cntActive")) $("cntActive").textContent = "(" + active + ")";
  if ($("cntFailed")) $("cntFailed").textContent = "(" + failed + ")";
}

function filterMods(mods) {
  var res = {};
  var matched = 0;
  var kw = _searchKeyword.toLowerCase();

  Object.keys(mods).forEach(function (name) {
    var info = mods[name];
    var isOk = Boolean(info.importable);

    // Tab 分类过滤
    if (_activeTab === "active" && !isOk) return;
    if (_activeTab === "failed" && isOk) return;

    // 搜索关键词过滤 (匹配名称或文件路径)
    if (kw) {
      var matchName = name.toLowerCase().indexOf(kw) !== -1;
      var matchPath = (info.path || "").toLowerCase().indexOf(kw) !== -1;
      if (!matchName && !matchPath) return;
    }

    res[name] = info;
    matched++;
  });

  return { mods: res, matchedCount: matched };
}

function renderFilteredMods() {
  var clientResult = filterMods(_allMods.client || {});
  var serverResult = filterMods(_allMods.server || {});

  var clientTotal = Object.keys(_allMods.client || {}).length;
  var serverTotal = Object.keys(_allMods.server || {}).length;

  var clientCountEl = $("modClientCount");
  if (clientCountEl) {
    clientCountEl.textContent = "(" + clientResult.matchedCount + "/" + clientTotal + ")";
  }
  var serverCountEl = $("modServerCount");
  if (serverCountEl) {
    serverCountEl.textContent = "(" + serverResult.matchedCount + "/" + serverTotal + ")";
  }

  $("modBodyClient").innerHTML = renderModRows(clientResult.mods, "client");
  $("modBodyServer").innerHTML = renderModRows(serverResult.mods, "server");
}

function renderModRows(mods, side) {
  var keys = Object.keys(mods || {});
  if (!keys.length) {
    if (_searchKeyword || _activeTab !== "all") {
      return '<tr><td colspan="4" class="td-faint" style="text-align:center;padding:16px 8px;">' +
        escapeHtml(t("mods.noMatch")) +
        ' <button class="btn btn-sm mod-reset-btn" style="margin-left:8px;padding:2px 8px;font-size:12px;">' +
        escapeHtml(t("mods.resetFilter")) + '</button></td></tr>';
    }
    return '<tr><td colspan="4" class="td-faint">' + t("mods.empty") + '</td></tr>';
  }
  return keys.map(function (name) {
    var info = mods[name];
    var ok = info.importable;
    return '<tr><td><strong>' + escapeHtml(name) + '</strong></td><td class="td-dim"><code>' + escapeHtml(info.path) +
      '</code></td><td><span class="status-dot ' + (ok ? "ok" : "bad") + '"></span>' + (ok ? t("mods.importOk") : t("mods.importFail")) +
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

// 分类 Tab 切换
var modStatusTabs = $("modStatusTabs");
if (modStatusTabs) {
  modStatusTabs.addEventListener("click", function (e) {
    var tab = e.target.closest(".chip-tab");
    if (!tab) return;
    modStatusTabs.querySelectorAll(".chip-tab").forEach(function (el) { el.classList.remove("active"); });
    tab.classList.add("active");
    _activeTab = tab.dataset.tab || "all";
    renderFilteredMods();
  });
}

// 搜索框实时输入与清除
var searchInput = $("modSearchInput");
var searchClear = $("modSearchClear");

if (searchInput) {
  searchInput.addEventListener("input", function () {
    _searchKeyword = searchInput.value.trim();
    if (searchClear) searchClear.style.display = _searchKeyword ? "block" : "none";
    renderFilteredMods();
  });
  searchInput.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      searchInput.value = "";
      _searchKeyword = "";
      if (searchClear) searchClear.style.display = "none";
      renderFilteredMods();
    }
  });
}

if (searchClear) {
  searchClear.addEventListener("click", function () {
    if (searchInput) searchInput.value = "";
    _searchKeyword = "";
    searchClear.style.display = "none";
    renderFilteredMods();
    if (searchInput) searchInput.focus();
  });
}

// 点击重置筛选按钮
document.addEventListener("click", function (e) {
  var resetBtn = e.target.closest(".mod-reset-btn");
  if (!resetBtn) return;
  _activeTab = "all";
  _searchKeyword = "";
  if (searchInput) searchInput.value = "";
  if (searchClear) searchClear.style.display = "none";
  if (modStatusTabs) {
    modStatusTabs.querySelectorAll(".chip-tab").forEach(function (el) {
      el.classList.toggle("active", el.dataset.tab === "all");
    });
  }
  renderFilteredMods();
});

// 单个 Mod 重载(事件委托)
document.addEventListener("click", function (e) {
  var btn = e.target.closest(".mod-reload-btn");
  if (!btn) return;
  reloadMod(btn.dataset.name, btn.dataset.side, btn);
});
