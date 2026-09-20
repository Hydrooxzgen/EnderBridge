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
      '</td><td style="white-space:nowrap;"><button class="btn btn-sm mod-config-btn" data-name="' + escapeHtml(name) + '" data-side="' + side + '" style="margin-right:6px;">⚙️ ' + t("mods.config") + '</button><button class="btn btn-sm mod-reload-btn" data-name="' + escapeHtml(name) + '" data-side="' + side + '">' + t("mods.reload") + '</button></td></tr>';
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
        editor.value = res.content || "";
        validateModJson();
        updateModLineColInfo();
        editor.focus();
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

