// ===== Mod 管理页面逻辑 (含实时搜索与状态分类 Tab) =====
var _allMods = { client: {}, server: {}, disabledClient: {}, disabledServer: {} };
var _activeTab = "all"; // "all" | "active" | "failed" | "disabled"
var _searchKeyword = "";
var _currentUser = null;
var _isReadOnly = false;

requireAuth(function (role) {
  initSidebar("mods", role);
  initTheme();
  initLang();
  _currentUser = getCurrentUser();
  _isReadOnly = (role === "guest" || _currentUser.role === "viewer");

  // 访客与只读角色隐藏重载所有和导入按钮及重载提示，并显示只读横幅
  if (_isReadOnly) {
    var banner = $("modReadOnlyBanner");
    if (banner) banner.style.display = "block";
    var reloadAll = $("modReloadAll");
    if (reloadAll) reloadAll.style.display = "none";
    var importBtn = $("modImportBtn");
    if (importBtn) importBtn.style.display = "none";
    var reloadHint = document.querySelector(".hint[data-i18n='mods.reloadHint']");
    if (reloadHint) reloadHint.style.display = "none";
  }
  loadMods();
});

function loadMods() {
  var refreshBtn = $("modRefresh");
  if (refreshBtn) refreshBtn.disabled = true;
  api("/mods").then(function (data) {
    if (!data.ok) return;
    var raw = data.mods || {};
    _allMods.client = raw.client || {};
    _allMods.server = raw.server || {};
    var dis = raw.disabled || {};
    _allMods.disabledClient = dis.client || {};
    _allMods.disabledServer = dis.server || {};
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
  var disabled = 0;

  ["client", "server"].forEach(function (side) {
    var list = _allMods[side] || {};
    Object.keys(list).forEach(function (name) {
      total++;
      var item = list[name];
      if (item.status === "active") active++;
      else if (item.status === "timeout" || item.status === "failed" || item.status === "syntax_error") failed++;
    });
  });

  ["disabledClient", "disabledServer"].forEach(function (sideKey) {
    var list = _allMods[sideKey] || {};
    Object.keys(list).forEach(function (name) {
      total++;
      disabled++;
    });
  });

  if ($("cntAll")) $("cntAll").textContent = "(" + total + ")";
  if ($("cntActive")) $("cntActive").textContent = "(" + active + ")";
  if ($("cntFailed")) $("cntFailed").textContent = "(" + failed + ")";
  if ($("cntDisabled")) $("cntDisabled").textContent = "(" + disabled + ")";
}

function filterMods(activeMods, disabledMods) {
  var res = {};
  var matched = 0;
  var kw = _searchKeyword.toLowerCase();

  var allForSide = {};
  Object.keys(activeMods || {}).forEach(function (k) { allForSide[k] = activeMods[k]; });
  Object.keys(disabledMods || {}).forEach(function (k) { allForSide[k] = disabledMods[k]; });

  Object.keys(allForSide).forEach(function (name) {
    var info = allForSide[name];
    var isEnabled = info.enabled !== false;
    var isOk = info.status === "active";
    var isFailed = info.status === "timeout" || info.status === "failed" || info.status === "syntax_error";

    // Tab 分类过滤
    if (_activeTab === "active" && !isOk) return;
    if (_activeTab === "failed" && !isFailed) return;
    if (_activeTab === "disabled" && isEnabled) return;

    // 搜索关键词过滤 (匹配名称或文件路径)
    if (kw) {
      var matchName = name.toLowerCase().indexOf(kw) !== -1;
      var matchPath = (info.path || "").toLowerCase().indexOf(kw) !== -1;
      if (!matchName && !matchPath) return;
    }

    res[name] = info;
    matched++;
  });

  var totalForSide = Object.keys(activeMods || {}).length + Object.keys(disabledMods || {}).length;
  return { mods: res, matchedCount: matched, totalCount: totalForSide };
}

function renderFilteredMods() {
  var clientResult = filterMods(_allMods.client || {}, _allMods.disabledClient || {});
  var serverResult = filterMods(_allMods.server || {}, _allMods.disabledServer || {});

  var clientCountEl = $("modClientCount");
  if (clientCountEl) {
    clientCountEl.textContent = "(" + clientResult.matchedCount + "/" + clientResult.totalCount + ")";
  }
  var serverCountEl = $("modServerCount");
  if (serverCountEl) {
    serverCountEl.textContent = "(" + serverResult.matchedCount + "/" + serverResult.totalCount + ")";
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
    var isEnabled = info.enabled !== false;
    var statusHtml = "";

    if (!isEnabled || info.status === "disabled") {
      statusHtml = '<span class="badge-sec-warn" style="display:inline-flex;align-items:center;gap:4px;"><span class="status-dot" style="background:var(--text-dim);"></span> ' + escapeHtml(t("mods.statusDisabled") || "已禁用") + '</span>';
    } else if (info.status === "active") {
      statusHtml = '<span class="badge-sec-safe" style="display:inline-flex;align-items:center;gap:4px;"><span class="status-dot ok"></span> ' + escapeHtml(t("mods.statusActive") || "正常运行") + '</span>';
    } else if (info.status === "timeout") {
      var title = escapeHtml(info.error || "加载超时（死循环或长时间阻塞），已自动熔断");
      statusHtml = '<span class="badge-sec-danger" style="display:inline-flex;align-items:center;gap:4px;cursor:help;" title="' + title + '"><span class="status-dot bad"></span> ⚠️ ' + escapeHtml(t("mods.statusTimeout") || "超时熔断") + '</span>';
    } else if (info.status === "failed") {
      var title = escapeHtml(info.error || "加载失败");
      statusHtml = '<span class="badge-sec-danger" style="display:inline-flex;align-items:center;gap:4px;cursor:help;" title="' + title + '"><span class="status-dot bad"></span> ❌ ' + escapeHtml(t("mods.statusFailed") || "加载失败") + '</span>';
    } else if (info.status === "safe_mode") {
      var title = escapeHtml(info.error || "出厂安全排障模式下已跳过第三方 Mod 加载");
      statusHtml = '<span class="badge-sec-warn" style="display:inline-flex;align-items:center;gap:4px;cursor:help;" title="' + title + '"><span class="status-dot" style="background:#eab308;"></span> 🛡️ ' + escapeHtml(t("mods.statusSafeMode") || "安全模式跳过") + '</span>';
    } else {
      statusHtml = '<span class="badge-sec-safe" style="display:inline-flex;align-items:center;gap:4px;opacity:0.8;"><span class="status-dot ok"></span> ' + escapeHtml(info.statusLabel || "就绪") + '</span>';
    }

    var opHtml = "";
    if (_isReadOnly) {
      // 访客/只读角色模式：无禁用、启用、重载、移除等破坏性按钮，仅提供只读查看配置
      opHtml = '<button class="btn btn-sm mod-config-btn" data-name="' + escapeHtml(name) + '" data-side="' + side + '" data-readonly="true">🔍 ' + escapeHtml(t("mods.viewConfig") || "查看配置") + '</button>';
    } else {
      var toggleBtn = '<button class="btn btn-sm ' + (isEnabled ? "btn-warn" : "btn-primary") + ' mod-toggle-btn" data-name="' + escapeHtml(name) + '" data-side="' + side + '" data-enabled="' + (isEnabled ? "false" : "true") + '" style="margin-right:6px;">' + (isEnabled ? ("⏸️ " + (t("mods.toggleDisable") || "禁用")) : ("▶️ " + (t("mods.toggleEnable") || "启用"))) + '</button>';
      var configBtn = '<button class="btn btn-sm mod-config-btn" data-name="' + escapeHtml(name) + '" data-side="' + side + '" style="margin-right:6px;">⚙️ ' + escapeHtml(t("mods.config") || "配置") + '</button>';
      var reloadBtn = (side === "server" && isEnabled) ? '<button class="btn btn-sm mod-reload-btn" data-name="' + escapeHtml(name) + '" data-side="' + side + '" style="margin-right:6px;">' + escapeHtml(t("mods.reload") || "重载") + '</button>' : '';
      var removeBtn = '<button class="btn btn-sm btn-danger mod-remove-btn" data-name="' + escapeHtml(name) + '" data-side="' + side + '" title="' + escapeHtml(t("mods.remove") || "移除") + '">🗑️</button>';
      opHtml = toggleBtn + configBtn + reloadBtn + removeBtn;
    }

    return '<tr><td><strong>' + escapeHtml(name) + '</strong></td><td class="td-dim"><code>' + escapeHtml(info.path) +
      '</code></td><td>' + statusHtml +
      '</td><td style="white-space:nowrap;">' + opHtml + '</td></tr>';
  }).join("");
}

function toggleMod(name, side, targetEnabled, btn) {
  if (_isReadOnly) {
    toast(t("mods.readOnlyHint") || "访客模式无法禁用或启用 Mod", "err");
    return;
  }
  btn.disabled = true;
  var oldText = btn.textContent;
  btn.textContent = "⏳";
  api("/mods/toggle", { method: "POST", body: JSON.stringify({ name: name, side: side, enabled: targetEnabled }) })
    .then(function (res) {
      toast(res.message || (targetEnabled ? "Mod 已启用" : "Mod 已禁用"), res.ok ? "ok" : "err");
      if (res.ok) loadMods();
    })
    .catch(function () { toast(t("mods.reqFail"), "err"); })
    .finally(function () { btn.disabled = false; btn.textContent = oldText; });
}

function removeMod(name, side, btn) {
  if (_isReadOnly) {
    toast(t("mods.readOnlyHint") || "访客模式无法移除 Mod", "err");
    return;
  }
  var tpl = t("mods.removeConfirm") || "确定要从配置中移除 Mod '{name}' 吗？";
  var msg = tpl.replace("{name}", name);
  if (!confirm(msg)) return;
  btn.disabled = true;
  api("/mods/remove", { method: "POST", body: JSON.stringify({ name: name, side: side }) })
    .then(function (res) {
      toast(res.message || "Mod 已移除", res.ok ? "ok" : "err");
      if (res.ok) loadMods();
    })
    .catch(function () { toast(t("mods.reqFail"), "err"); })
    .finally(function () { btn.disabled = false; });
}

function reloadMod(name, side, btn) {
  if (_isReadOnly) {
    toast(t("mods.readOnlyHint") || "访客模式无法重载 Mod", "err");
    return;
  }
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

// 单个 Mod 启用/禁用(事件委托)
document.addEventListener("click", function (e) {
  var btn = e.target.closest(".mod-toggle-btn");
  if (!btn) return;
  var targetEnabled = btn.dataset.enabled === "true";
  toggleMod(btn.dataset.name, btn.dataset.side, targetEnabled, btn);
});

// 单个 Mod 移除(事件委托)
document.addEventListener("click", function (e) {
  var btn = e.target.closest(".mod-remove-btn");
  if (!btn) return;
  removeMod(btn.dataset.name, btn.dataset.side, btn);
});

// ===== Mod 在线专属配置文件编辑与热重载逻辑 =====
var _currentEditingMod = { name: "", side: "", originalContent: "", target: "" };
var _lastModJsonError = null;
var _modValidateDebounceTimer = null;

function getModJsonErrorInfo(jsonStr) {
  if (!jsonStr || !jsonStr.trim()) return null;
  try {
    JSON.parse(jsonStr);
    return null;
  } catch (e) {
    var msg = e.message || String(e);
    var line = 1;
    var column = 1;
    var position = -1;

    var posMatch = msg.match(/at position (\d+)/i);
    if (posMatch) {
      position = parseInt(posMatch[1], 10);
    }
    var lineMatch = msg.match(/line (\d+)/i);
    var colMatch = msg.match(/column (\d+)/i);
    if (lineMatch) line = parseInt(lineMatch[1], 10);
    if (colMatch) column = parseInt(colMatch[1], 10);

    if (position >= 0 && position <= jsonStr.length) {
      var linesBefore = jsonStr.substring(0, position).split("\n");
      line = linesBefore.length;
      column = linesBefore[linesBefore.length - 1].length + 1;
    }

    var allLines = jsonStr.split("\n");
    var errorLine = Math.max(1, Math.min(line, allLines.length));
    var currLineText = allLines[errorLine - 1] || "";
    var prevLineText = errorLine > 1 ? allLines[errorLine - 2] : null;
    var nextLineText = errorLine < allLines.length ? allLines[errorLine] : null;

    return {
      message: msg,
      line: errorLine,
      column: column,
      position: position,
      snippet: {
        lineNum: errorLine,
        prev: prevLineText,
        curr: currLineText,
        next: nextLineText,
      }
    };
  }
}

function validateModJson() {
  var editor = $("modCfgEditor");
  if (!editor) return true;
  var val = editor.value;
  var err = getModJsonErrorInfo(val);
  _lastModJsonError = err;

  var banner = $("modCfgErrorBanner");
  var titleEl = $("modCfgErrorTitle");
  var msgEl = $("modCfgErrorMsg");
  var snippetEl = $("modCfgErrorSnippet");
  var badge = $("modCfgValidationBadge");

  var totalLines = val ? val.split("\n").length : 0;
  if ($("modCfgTotalLines")) $("modCfgTotalLines").textContent = "共 " + totalLines + " 行";

  if (!err) {
    if (banner) banner.style.display = "none";
    if (badge) {
      badge.className = "badge-sec-safe";
      badge.textContent = t("mods.cfgValid") || "✔ 语法有效";
    }
    return true;
  } else {
    if (banner) banner.style.display = "block";
    if (titleEl) {
      titleEl.textContent = "❌ " + (t("mods.cfgInvalid") || "语法错误") + " (第 " + err.line + " 行, 第 " + err.column + " 列)";
    }
    if (msgEl) msgEl.textContent = err.message;
    if (snippetEl && err.snippet) {
      var snipText = "";
      if (err.snippet.prev !== null) {
        snipText += " " + (err.snippet.lineNum - 1) + " | " + err.snippet.prev + "\n";
      }
      snipText += ">" + err.snippet.lineNum + " | " + err.snippet.curr + "   <-- [语法错误位置]\n";
      if (err.snippet.next !== null) {
        snipText += " " + (err.snippet.lineNum + 1) + " | " + err.snippet.next;
      }
      snippetEl.textContent = snipText;
    }
    if (badge) {
      badge.className = "badge-sec-danger";
      badge.textContent = (t("mods.cfgInvalid") || "语法错误") + " (L" + err.line + ":C" + err.column + ")";
    }
    return false;
  }
}

function updateModLineColInfo() {
  var editor = $("modCfgEditor");
  var infoEl = $("modCfgLineColInfo");
  if (!editor || !infoEl) return;
  var pos = editor.selectionStart || 0;
  var linesBefore = editor.value.substring(0, pos).split("\n");
  var line = linesBefore.length;
  var col = linesBefore[linesBefore.length - 1].length + 1;
  infoEl.textContent = "第 " + line + " 行, 第 " + col + " 列";
}

function gotoModErrorLine() {
  var editor = $("modCfgEditor");
  if (!editor || !_lastModJsonError) return;
  var lines = editor.value.split("\n");
  var targetLine = _lastModJsonError.line;
  var targetCol = _lastModJsonError.column || 1;

  var charIndex = 0;
  for (var i = 0; i < targetLine - 1 && i < lines.length; i++) {
    charIndex += lines[i].length + 1;
  }
  charIndex += Math.max(0, targetCol - 1);

  editor.focus();
  editor.setSelectionRange(charIndex, charIndex);
  var lineHeight = 20;
  editor.scrollTop = Math.max(0, (targetLine - 5) * lineHeight);
}

function openModConfig(name, side) {
  _currentEditingMod.name = name;
  _currentEditingMod.side = side;

  var modal = $("modConfigModal");
  var nameEl = $("modCfgModalName");
  var targetEl = $("modCfgModalTarget");
  var editor = $("modCfgEditor");
  var saveBtn = $("modCfgSaveBtn");
  var formatBtn = $("modCfgFormatBtn");
  var resetBtn = $("modCfgResetBtn");
  var titleText = $("modCfgModalTitleText");
  var iconEl = $("modCfgModalIcon");

  if (_isReadOnly) {
    if (titleText) titleText.textContent = t("mods.cfgViewTitle") || "查看 Mod 配置";
    if (iconEl) iconEl.textContent = "🔍";
    if (saveBtn) saveBtn.style.display = "none";
    if (formatBtn) formatBtn.style.display = "none";
    if (resetBtn) resetBtn.style.display = "none";
  } else {
    if (titleText) titleText.textContent = t("mods.cfgTitle") || "编辑 Mod 配置";
    if (iconEl) iconEl.textContent = "⚙️";
    if (saveBtn) saveBtn.style.display = "";
    if (formatBtn) formatBtn.style.display = "";
    if (resetBtn) resetBtn.style.display = "";
  }

  if (nameEl) nameEl.textContent = name + " (" + side + ")";
  if (targetEl) targetEl.textContent = "加载中...";
  if (editor) {
    editor.value = "// " + (t("mods.cfgLoading") || "正在加载 Mod 配置...");
    editor.disabled = true;
  }
  if (modal) modal.style.display = "flex";

  api("/mods/config?name=" + encodeURIComponent(name) + "&side=" + encodeURIComponent(side))
    .then(function (res) {
      if (!res.ok) {
        toast(res.message || t("mods.reqFail"), "err");
        return;
      }
      _currentEditingMod.target = res.target;
      _currentEditingMod.originalContent = res.content || "";
      if (targetEl) targetEl.textContent = res.target;
      if (editor) {
        editor.disabled = false;
        editor.readOnly = _isReadOnly;
        editor.value = res.content || "";
        validateModJson();
        updateModLineColInfo();
        if (!_isReadOnly) editor.focus();
      }
    })
    .catch(function () {
      toast(t("mods.reqFail"), "err");
      if (editor) editor.disabled = false;
    });
}

function closeModConfig() {
  var modal = $("modConfigModal");
  if (modal) modal.style.display = "none";
}

function saveAndReloadModConfig() {
  if (_isReadOnly) {
    toast(t("mods.readOnlyHint") || "访客模式无法保存 Mod 配置", "err");
    return;
  }
  var editor = $("modCfgEditor");
  var saveBtn = $("modCfgSaveBtn");
  if (!editor || !saveBtn) return;

  var ok = validateModJson();
  if (!ok) {
    var banner = $("modCfgErrorBanner");
    if (banner) banner.scrollIntoView({ behavior: "smooth", block: "nearest" });
    toast(t("mods.cfgSaveBlocked") || "JSON 存在语法错误，无法保存", "err");
    return;
  }

  var content = editor.value;
  saveBtn.disabled = true;
  saveBtn.textContent = "⏳ " + (t("mods.cfgSaving") || "正在保存并重载...");

  api("/mods/config", {
    method: "POST",
    body: JSON.stringify({
      name: _currentEditingMod.name,
      side: _currentEditingMod.side,
      content: content,
      reload: true,
    }),
  })
    .then(function (res) {
      if (res.ok) {
        _currentEditingMod.originalContent = content;
        toast(res.message || t("mods.cfgSaved") || "配置已保存并重载完成", res.reloadOk ? "ok" : "warn");
        closeModConfig();
        // 刷新列表状态
        loadMods();
      } else {
        toast(res.message || "保存失败", "err");
        if (res.error) {
          _lastModJsonError = {
            line: res.error.line,
            column: res.error.column,
            message: res.error.msg,
          };
          gotoModErrorLine();
        }
      }
    })
    .catch(function () {
      toast(t("mods.reqFail"), "err");
    })
    .finally(function () {
      saveBtn.disabled = false;
      saveBtn.textContent = t("mods.cfgSaveReload") || "💾 保存并热重载";
    });
}

// 绑定 Mod 配置编辑器事件
var modEditor = $("modCfgEditor");
if (modEditor) {
  modEditor.addEventListener("input", function () {
    clearTimeout(_modValidateDebounceTimer);
    _modValidateDebounceTimer = setTimeout(validateModJson, 250);
    updateModLineColInfo();
  });
  ["click", "keyup", "select"].forEach(function (evt) {
    modEditor.addEventListener(evt, updateModLineColInfo);
  });
  // Tab 键输入 2 个空格缩进
  modEditor.addEventListener("keydown", function (e) {
    if (e.key === "Tab") {
      e.preventDefault();
      var start = this.selectionStart;
      var end = this.selectionEnd;
      this.value = this.value.substring(0, start) + "  " + this.value.substring(end);
      this.selectionStart = this.selectionEnd = start + 2;
      clearTimeout(_modValidateDebounceTimer);
      _modValidateDebounceTimer = setTimeout(validateModJson, 250);
      updateModLineColInfo();
    }
  });
}

// 格式化按钮
var modFormatBtn = $("modCfgFormatBtn");
if (modFormatBtn) {
  modFormatBtn.addEventListener("click", function () {
    var editor = $("modCfgEditor");
    if (!editor) return;
    try {
      var obj = JSON.parse(editor.value);
      editor.value = JSON.stringify(obj, null, 2);
      validateModJson();
      updateModLineColInfo();
      toast(t("cfg.jsonFormatted") || "已格式化 JSON", "ok");
    } catch (e) {
      validateModJson();
      toast(t("mods.cfgInvalid") || "JSON 存在错误，无法格式化", "err");
    }
  });
}

// 还原按钮
var modResetBtn = $("modCfgResetBtn");
if (modResetBtn) {
  modResetBtn.addEventListener("click", function () {
    var editor = $("modCfgEditor");
    if (!editor) return;
    editor.value = _currentEditingMod.originalContent || "";
    validateModJson();
    updateModLineColInfo();
    toast(t("cfg.jsonRestored") || "已还原为原始配置", "ok");
  });
}

// 定位错误行按钮
var modGotoErrBtn = $("modCfgGotoErrorBtn");
if (modGotoErrBtn) {
  modGotoErrBtn.addEventListener("click", gotoModErrorLine);
}

// 保存并热重载按钮
var modSaveBtn = $("modCfgSaveBtn");
if (modSaveBtn) {
  modSaveBtn.addEventListener("click", saveAndReloadModConfig);
}

// 关闭按钮 (右上角与底部)
var modCloseTopBtn = $("modCfgCloseTopBtn");
if (modCloseTopBtn) modCloseTopBtn.addEventListener("click", closeModConfig);
var modCancelBtn = $("modCfgCancelBtn");
if (modCancelBtn) modCancelBtn.addEventListener("click", closeModConfig);

// 点击遮罩外部关闭
var modModal = $("modConfigModal");
if (modModal) {
  modModal.addEventListener("click", function (e) {
    if (e.target === modModal) closeModConfig();
  });
}

// 点击配置按钮(事件委托)
document.addEventListener("click", function (e) {
  var btn = e.target.closest(".mod-config-btn");
  if (!btn) return;
  openModConfig(btn.dataset.name, btn.dataset.side);
});

// ===== 导入 Mod 弹窗逻辑 =====
var _importTab = "scan";
var _selectedUploadFile = null;

function openImportModal() {
  var modal = $("modImportModal");
  if (modal) modal.style.display = "flex";
  switchImportTab("scan");
  loadDiscoveredMods();
}

function closeImportModal() {
  var modal = $("modImportModal");
  if (modal) modal.style.display = "none";
  _selectedUploadFile = null;
  if ($("modSelectedFileName")) $("modSelectedFileName").textContent = "";
  if ($("uploadSubmitBtn")) $("uploadSubmitBtn").disabled = true;
  if ($("modUploadFile")) $("modUploadFile").value = "";
}

function switchImportTab(tabKey) {
  _importTab = tabKey;
  var tabs = $("modImportTabs");
  if (tabs) {
    tabs.querySelectorAll(".chip-tab").forEach(function (el) {
      el.classList.toggle("active", el.dataset.tab === tabKey);
    });
  }
  if ($("importScanPane")) $("importScanPane").style.display = tabKey === "scan" ? "block" : "none";
  if ($("importManualPane")) $("importManualPane").style.display = tabKey === "manual" ? "block" : "none";
  if ($("importUploadPane")) $("importUploadPane").style.display = tabKey === "upload" ? "block" : "none";
}

function loadDiscoveredMods() {
  var listEl = $("modScanList");
  if (!listEl) return;
  listEl.innerHTML = '<div class="td-faint" style="text-align:center;padding:20px;">' + (t("mods.loading") || "正在扫描 mod 目录...") + '</div>';

  api("/mods/scan").then(function (res) {
    if (!res.ok) {
      listEl.innerHTML = '<div class="td-faint" style="color:var(--danger);padding:16px;">' + escapeHtml(res.message || "扫描失败") + '</div>';
      return;
    }
    var unconf = res.unconfigured || [];
    if (!unconf.length) {
      listEl.innerHTML = '<div class="td-faint" style="text-align:center;padding:24px;">🎉 mod/ 目录下未发现未配置的 Mod 文件（全部已配置）</div>';
      return;
    }

    var html = '<table class="perm-table" style="margin:0;font-size:12px;">' +
      '<thead><tr><th>建议名称</th><th>类型</th><th>文件与模块</th><th>操作</th></tr></thead><tbody>';

    unconf.forEach(function (item) {
      var side = item.suggestedSide || "client";
      html += '<tr>' +
        '<td><strong>' + escapeHtml(item.name) + '</strong></td>' +
        '<td><span class="badge-sec-safe">' + (side === "server" ? "服务端" : "客户端") + '</span></td>' +
        '<td><code>' + escapeHtml(item.module) + '</code><div style="font-size:11px;color:var(--text-dim);">' + escapeHtml(item.file) + '</div></td>' +
        '<td><button class="btn btn-sm btn-primary scan-import-btn" data-name="' + escapeHtml(item.name) + '" data-side="' + side + '" data-path="' + escapeHtml(item.module) + '">➕ 导入</button></td>' +
        '</tr>';
    });

    html += '</tbody></table>';
    listEl.innerHTML = html;
  }).catch(function () {
    listEl.innerHTML = '<div class="td-faint" style="color:var(--danger);padding:16px;">网络异常，扫描失败</div>';
  });
}

function submitManualImport() {
  var name = ($("manualModName") ? $("manualModName").value : "").trim();
  var side = $("manualModSide") ? $("manualModSide").value : "client";
  var path = ($("manualModPath") ? $("manualModPath").value : "").trim();
  var autoEnable = $("manualModAutoEnable") ? $("manualModAutoEnable").checked : true;

  if (!name) {
    toast("Mod 名称不能为空", "err");
    if ($("manualModName")) $("manualModName").focus();
    return;
  }
  if (!path) {
    toast("模块导入路径不能为空", "err");
    if ($("manualModPath")) $("manualModPath").focus();
    return;
  }

  var btn = $("manualSubmitBtn");
  if (btn) btn.disabled = true;

  api("/mods/import", {
    method: "POST",
    body: JSON.stringify({ name: name, side: side, path: path, auto_enable: autoEnable }),
  }).then(function (res) {
    if (res.ok) {
      toast(res.message || "Mod 导入成功", "ok");
      closeImportModal();
      loadMods();
    } else {
      toast(res.message || "导入失败", "err");
    }
  }).catch(function () {
    toast(t("mods.reqFail"), "err");
  }).finally(function () {
    if (btn) btn.disabled = false;
  });
}

var modImportBtn = $("modImportBtn");
if (modImportBtn) modImportBtn.addEventListener("click", openImportModal);

var modImportCloseBtn = $("modImportCloseBtn");
if (modImportCloseBtn) modImportCloseBtn.addEventListener("click", closeImportModal);
var manualCancelBtn = $("manualCancelBtn");
if (manualCancelBtn) manualCancelBtn.addEventListener("click", closeImportModal);
var uploadCancelBtn = $("uploadCancelBtn");
if (uploadCancelBtn) uploadCancelBtn.addEventListener("click", closeImportModal);

var modImportTabs = $("modImportTabs");
if (modImportTabs) {
  modImportTabs.addEventListener("click", function (e) {
    var tab = e.target.closest(".chip-tab");
    if (!tab) return;
    switchImportTab(tab.dataset.tab || "scan");
  });
}

var manualSubmitBtn = $("manualSubmitBtn");
if (manualSubmitBtn) manualSubmitBtn.addEventListener("click", submitManualImport);

document.addEventListener("click", function (e) {
  var btn = e.target.closest(".scan-import-btn");
  if (!btn) return;
  btn.disabled = true;
  api("/mods/import", {
    method: "POST",
    body: JSON.stringify({
      name: btn.dataset.name,
      side: btn.dataset.side,
      path: btn.dataset.path,
      auto_enable: true,
    }),
  }).then(function (res) {
    if (res.ok) {
      toast(res.message || "Mod 导入成功", "ok");
      closeImportModal();
      loadMods();
    } else {
      toast(res.message || "导入失败", "err");
      btn.disabled = false;
    }
  }).catch(function () {
    toast(t("mods.reqFail"), "err");
    btn.disabled = false;
  });
});

var modSelectFileBtn = $("modSelectFileBtn");
var modUploadFile = $("modUploadFile");
var uploadSubmitBtn = $("uploadSubmitBtn");

if (modSelectFileBtn && modUploadFile) {
  modSelectFileBtn.addEventListener("click", function () { modUploadFile.click(); });
  modUploadFile.addEventListener("change", function () {
    if (modUploadFile.files && modUploadFile.files[0]) {
      _selectedUploadFile = modUploadFile.files[0];
      if ($("modSelectedFileName")) {
        $("modSelectedFileName").textContent = "已选中: " + _selectedUploadFile.name + " (" + Math.round(_selectedUploadFile.size / 1024) + " KB)";
      }
      if (uploadSubmitBtn) uploadSubmitBtn.disabled = false;
    }
  });
}

if (uploadSubmitBtn) {
  uploadSubmitBtn.addEventListener("click", function () {
    if (!_selectedUploadFile) return;
    uploadSubmitBtn.disabled = true;
    var reader = new FileReader();
    reader.onload = function (e) {
      var content = e.target.result;
      api("/mods/upload", {
        method: "POST",
        body: JSON.stringify({ filename: _selectedUploadFile.name, content: content }),
      }).then(function (res) {
        if (!res.ok) {
          toast(res.message || "上传失败", "err");
          uploadSubmitBtn.disabled = false;
          return;
        }
        toast("文件已上传，正在导入 Mod 配置...", "ok");
        api("/mods/import", {
          method: "POST",
          body: JSON.stringify({
            name: res.name,
            side: "client",
            path: res.module,
            auto_enable: true,
          }),
        }).then(function (importRes) {
          if (importRes.ok) {
            toast(importRes.message || "Mod 导入成功", "ok");
            closeImportModal();
            loadMods();
          } else {
            toast(importRes.message || "配置导入失败，已保存至 mod/ 目录", "warn");
            switchImportTab("manual");
            if ($("manualModName")) $("manualModName").value = res.name;
            if ($("manualModPath")) $("manualModPath").value = res.module;
          }
        }).catch(function () {
          toast(t("mods.reqFail"), "err");
        });
      }).catch(function () {
        toast("上传失败", "err");
        uploadSubmitBtn.disabled = false;
      });
    };
    reader.readAsText(_selectedUploadFile, "UTF-8");
  });
}

var modImportModal = $("modImportModal");
if (modImportModal) {
  modImportModal.addEventListener("click", function (e) {
    if (e.target === modImportModal) closeImportModal();
  });
}

