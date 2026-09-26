// Author: Hydrooxzgen (Hydrooxygen)
// Github: https://github.com/Hydrooxzgen
// This project uses the GPL-3.0 license, you can modify/distribute this project according to the GPL-3.0 license
// 功能设置页面逻辑
var cfgData = null;
var MOD_CATALOG = {
  client: [
    ["AI", "mod.ai"], ["PermissionCommands", "mod.permission"], ["Tool", "mod.tool"],
    ["Position", "mod.position"], ["Music", "mod.music"], ["MCFunc", "mod.mcfunc"],
    ["MoreWS", "mod.morews"], ["Ezmatic", "mod.ezmatic.main"], ["ImageMod", "mod.image.main"],
    ["Message", "mod.message"], ["Bot", "mod.bot"],
  ],
  server: [
    ["chat", "mod.read"], ["spam", "mod.spam"],
  ],
};

requireAuth(function (role) {
  initSidebar("config", role);
  initTheme();
  initLang();
  loadConfig();
  initCategoryNav();
  initTexturePackManager();
  initBackupManager();
});

// ===== 分类导航 =====
function initCategoryNav() {
  var items = document.querySelectorAll(".cfg-sidebar-item[data-cfg-cat]");
  items.forEach(function (item) {
    item.addEventListener("click", function () {
      var cat = this.getAttribute("data-cfg-cat");
      // 跳过被隐藏的 tab
      if (this.style.display === "none") return;
      // 更新侧边栏高亮
      items.forEach(function (i) { i.classList.remove("active"); });
      this.classList.add("active");
      // 切换内容区
      document.querySelectorAll(".cfg-category[data-cfg-cat]").forEach(function (sec) {
        sec.classList.toggle("active", sec.getAttribute("data-cfg-cat") === cat);
      });
      // 切换到备份与恢复时自动刷新列表
      if (cat === "backup") {
        loadConfigBackups();
      }
      // 切换到资源管理时刷新材质包状态
      if (cat === "resources") {
        loadTexturePackStatus();
      }
      // 切换到 Raw JSON 时自动从表单同步最新数据
      if (cat === "raw") {
        var editor = $("cfgRawJsonEditor");
        if (editor && (!editor.value.trim() || editor.dataset.synced !== "true")) {
          var cfgToPreview = collectFormConfig();
          editor.value = JSON.stringify(cfgToPreview, null, 2);
          editor.dataset.synced = "true";
        }
        validateRawJson();
      }
    });
  });
}

function renderModSwitches() {
  var mods = cfgData.mods || {};
  ["client", "server"].forEach(function (side) {
    var enabled = mods[side] || {};
    var box = $("mod" + (side === "client" ? "Client" : "Server") + "Box");
    if (!box) return;
    box.innerHTML = MOD_CATALOG[side].map(function (m) {
      var key = m[0], path = m[1];
      var checked = enabled[key] === path;
      return '<div class="cfg-switch mod-check">' +
        '<label class="switch"><input type="checkbox" id="mod-' + side + '-' + key + '"' + (checked ? " checked" : "") + '><span class="track"></span></label>' +
        '<span class="switch-label">' + escapeHtml(key) + ' <span class="td-dim">(' + escapeHtml(path) + ')</span></span></div>';
    }).join("");
    box.querySelectorAll("input[type=checkbox]").forEach(function (cb) {
      cb.addEventListener("change", syncConfigCards);
    });
  });
}

function isModOn(side, key) {
  var cb = $("mod-" + side + "-" + key);
  if (cb) return cb.checked;
  var enabled = (cfgData.mods || {})[side] || {};
  return !!enabled[key];
}

function syncConfigCards() {
  var mc = $("cfgCardMusic"); if (mc) mc.classList.toggle("hidden", !isModOn("client", "Music"));
  var aiOn = isModOn("client", "AI");
  var ac = $("cfgCardAi"); if (ac) ac.classList.toggle("hidden", !aiOn);
  var sc = $("cfgCardSpam"); if (sc) sc.classList.toggle("hidden", !isModOn("server", "spam"));
  var tc = $("cfgCardTool"); if (tc) tc.classList.toggle("hidden", !isModOn("client", "Tool"));
  var botOn = isModOn("client", "Bot");
  var bc = $("cfgCardBot"); if (bc) bc.classList.toggle("hidden", !botOn);
  // 隐藏禁用功能对应的侧边栏 tab
  var aiTab = document.querySelector('.cfg-sidebar-item[data-cfg-cat="ai"]');
  if (aiTab) aiTab.style.display = aiOn ? "" : "none";
  // 如果当前选中的是被隐藏的 tab,自动跳到 features
  var activeTab = document.querySelector('.cfg-sidebar-item.active[data-cfg-cat]');
  if (activeTab && activeTab.style.display === "none") {
    var featTab = document.querySelector('.cfg-sidebar-item[data-cfg-cat="features"]');
    if (featTab) featTab.click();
  }
}

function toggleSub(id, show) { $(id).classList.toggle("show", !!show); }

function loadConfig() {
  api("/config").then(function (data) {
    if (!data.ok) return;
    cfgData = data.config;
    var editor = $("cfgRawJsonEditor");
    if (editor) {
      editor.value = JSON.stringify(data.config, null, 2);
      editor.dataset.synced = "true";
      validateRawJson();
    }
    var f = data.config.features || {};
    var qq = f.qq || {};
    var music = f.music || {};
    var rl = data.config.rateLimit || {};
    var rlCmd = rl.command || {};
    var webui = data.config.webui || {};

    $("cfg-name").value = data.config.name || "EnderBridge";
    $("cfg-port").value = data.config.port || 8800;
    $("cfg-prefix").value = data.config.commandPrefix || "$";
    $("cfg-loglevel").value = data.config.logLevel || "info";
    $("cfg-percussion").checked = !!music.playPercussion;

    $("cfg-qq").checked = !!qq.enabled;
    $("cfg-qqgroup").value = qq.groupId || "";
    $("cfg-qqport").value = qq.port || "";
    $("cfg-qqhost").value = qq.host || "";
    $("cfg-qqtoken").value = qq.accessToken || "";
    toggleSub("qqFields", $("cfg-qq").checked);

    $("cfg-ratelimit").checked = !!rlCmd.enabled;
    $("cfg-rlwindow").value = rlCmd.windowMs || "";
    $("cfg-rlmax").value = rlCmd.maxPerWindow || "";
    toggleSub("rlFields", $("cfg-ratelimit").checked);

    var plp = data.config.playerListPolling || {};
    $("cfg-playerlistpolling").checked = !!plp.enabled;
    $("cfg-plpinterval").value = plp.intervalSeconds || 30;
    toggleSub("plpFields", $("cfg-playerlistpolling").checked);

    $("cfg-webui").checked = webui.enabled !== false;
    $("cfg-webport").value = webui.port || 18888;
    $("cfg-weblockal").checked = webui.localOnly === true || webui.localOnly === "true";
    toggleSub("webuiFields", $("cfg-webui").checked);

    var upd = data.config.updateConfig || {};
    if ($("cfg-autobackup")) {
      $("cfg-autobackup").checked = upd.autoBackup !== false;
    }
    if ($("cfg-backup-autobackup")) {
      $("cfg-backup-autobackup").checked = upd.autoBackup !== false;
    }

    $("cfg-github-token").value = data.config.githubToken || "";

    var ai = data.config.ai || {};
    $("cfg-aibase").value = ai.baseURL || "";
    $("cfg-aikey").value = ai.apiKey || "";
    $("cfg-aicooldown").value = ai.chatCooldown || 5000;
    $("cfg-aichatmodel").value = ai.chatModel || "deepseek-chat";
    $("cfg-aichattokens").value = ai.chatMaxTokens || 512;
    $("cfg-aichatprompt").value = ai.chatPrompt || "";
    $("cfg-aicmdmodel").value = ai.cmdModel || "deepseek-chat";
    $("cfg-aicmdtokens").value = ai.cmdMaxTokens || 1024;
    $("cfg-aicmdprompt").value = ai.cmdPrompt || "";

    var utils = data.config.utils || {};
    $("cfg-tellall").checked = !!utils.tellAllToTell;
    $("cfg-polling").checked = utils.enablePolling !== false;

    var sapi = data.config.sapi || {};
    var bot = data.config.bot || {};
    var announce = (data.config.messageConfig || {}).announcements || {};

    $("cfg-gmsg").value = sapi.gmsg || "gmsg";
    $("cfg-smsg").value = sapi.smsg || "smsg";

    $("cfg-announce-enabled").checked = !!announce.enabled;
    $("cfg-announce-interval").value = announce.interval || 300;
    $("cfg-announce-messages").value = (announce.messages || []).join("\n");
    toggleSub("announceFields", $("cfg-announce-enabled").checked);

    $("cfg-bot-host").value = bot.host || "127.0.0.1";
    $("cfg-bot-port").value = bot.port || 19132;
    $("cfg-bot-username").value = bot.username || "FakeBot";
    $("cfg-bot-version").value = bot.version || "";
    // 反转: 勾选=正版(online), 不勾选=离线(offline)
    $("cfg-bot-offline").checked = bot.offline === false;
    $("cfg-bot-authtitle").value = bot.authTitle || "";
    $("cfg-bot-profilesfolder").value = bot.profilesFolder || "";
    $("cfg-bot-realmid").value = bot.realmId || "";
    $("cfg-bot-realminvite").value = bot.realmInvite || "";
    // Xbox Live 账号
    var xboxAccounts = bot.xboxAccounts || [];
    var activeXbox = bot.activeXboxAccount || null;
    if (activeXbox) {
      $("cfg-bot-username").value = activeXbox;
      var activeEl = $("cfg-bot-xbox-active");
      if (activeEl) activeEl.textContent = activeXbox;
    }
    var mode = bot.mode || "server";
    $("cfg-bot-mode-server").checked = mode === "server";
    $("cfg-bot-mode-realm").checked = mode === "realm";
    toggleBotMode();

    var spam = data.config.spam || {};
    $("cfg-spamattack").value = spam.attack || "";
    $("cfg-spamad").value = (spam.ad || []).join("\n");
    $("cfg-spaminterval").value = spam.adInterval || "";

    var bp = data.config.basePath || {};
    $("cfg-path-music").value = bp.music || "";
    $("cfg-path-mcfunc").value = bp.mcfunc || "";
    $("cfg-path-ezmatic").value = bp.ezmatic || "";
    $("cfg-path-image").value = bp.image || "";

    renderModSwitches();
    syncConfigCards();
    // 别名开关状态同步
    var aliasToggle = $("cfg-aliases-enabled");
    var hasAliases = data.config.commandAliases && Object.keys(data.config.commandAliases).length > 0;
    if (aliasToggle) aliasToggle.checked = hasAliases;
    // 始终显示别名 tab,不再因为空所以hide
    _syncAliasTabVisibility(true);
    renderAliasList();
  }).catch(function () {});
}

// Toggle 展开/收起
["cfg-qq", "cfg-ratelimit", "cfg-webui", "cfg-announce-enabled", "cfg-playerlistpolling"].forEach(function (id) {
  var el = $(id);
  if (el) el.addEventListener("change", function () {
    var subId = id === "cfg-qq" ? "qqFields" : id === "cfg-ratelimit" ? "rlFields" : id === "cfg-webui" ? "webuiFields" : id === "cfg-announce-enabled" ? "announceFields" : "plpFields";
    toggleSub(subId, this.checked);
  });
});

// ===== 命令别名管理 =====
function renderAliasList() {
  var container = $("aliasList");
  if (!container) return;
  var aliases = (cfgData.commandAliases || {});
  var html = "";
  for (var cmd in aliases) {
    var aliasList = aliases[cmd].join(", ");
    html += '<div class="alias-item" style="display:flex;align-items:center;gap:8px;padding:8px 12px;background:var(--bg-card);border:1px solid var(--border);border-radius:6px;margin-bottom:8px;">' +
      '<span style="font-weight:600;min-width:100px;">' + escapeHtml(cmd) + '</span>' +
      '<span style="flex:1;color:var(--text-dim);font-size:13px;">' + escapeHtml(aliasList) + '</span>' +
      '<button class="btn btn-sm btn-ghost edit-alias" data-cmd="' + escapeHtml(cmd) + '" data-aliases="' + escapeHtml(aliases[cmd].join(",")) + '">' + t("cfg.jsEdit") + '</button>' +
      '<button class="btn btn-sm btn-ghost remove-alias" data-cmd="' + escapeHtml(cmd) + '">🗑️</button>' +
      '</div>';
  }
  if (!html) html = '<p class="hint" style="text-align:center;padding:16px;">' + t("cfg.jsNoAlias") + '</p>';
  container.innerHTML = html;
  // 绑定编辑事件
  container.querySelectorAll(".edit-alias").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var cmd = this.getAttribute("data-cmd");
      var currentAliases = this.getAttribute("data-aliases");
      showEditAliasModal(cmd, currentAliases);
    });
  });
  // 绑定删除事件
  container.querySelectorAll(".remove-alias").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var cmd = this.getAttribute("data-cmd");
      if (confirm(t("cfg.jsConfirmDelAliasPrefix") + cmd + t("cfg.jsConfirmDelAliasSuffix"))) {
        delete cfgData.commandAliases[cmd];
        renderAliasList();
        toast(t("cfg.jsDeletedPrefix") + cmd + t("cfg.jsDeletedSuffix"), "ok");
      }
    });
  });
}

function showAddAliasModal() {
  var cmd = prompt(t("cfg.jsPromptCmd"));
  if (!cmd) return;
  var aliases = prompt(t("cfg.jsPromptAliases"));
  if (!aliases) return;
  var aliasArr = aliases.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
  if (!aliasArr.length) return;
  cfgData.commandAliases = cfgData.commandAliases || {};
  cfgData.commandAliases[cmd] = aliasArr;
  renderAliasList();
  toast(t("cfg.jsAddedPrefix") + cmd + " → " + aliasArr.join(", "), "ok");
}

function showEditAliasModal(cmd, currentAliases) {
  var newAliases = prompt(t("cfg.jsEditPromptPrefix") + cmd + t("cfg.jsEditPromptSuffix"), currentAliases);
  if (newAliases === null) return; // 用户取消
  var aliasArr = newAliases.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
  if (!aliasArr.length) {
    // 别名清空则删除该命令
    if (confirm(t("cfg.jsEmptyConfirmPrefix") + cmd + t("cfg.jsConfirmDelAliasSuffix"))) {
      delete cfgData.commandAliases[cmd];
    }
    renderAliasList();
    return;
  }
  cfgData.commandAliases = cfgData.commandAliases || {};
  cfgData.commandAliases[cmd] = aliasArr;
  renderAliasList();
  toast(t("cfg.jsUpdatedPrefix") + cmd + " → " + aliasArr.join(", "), "ok");
}

var addAliasBtn = $("addAliasBtn");
if (addAliasBtn) addAliasBtn.addEventListener("click", showAddAliasModal);

// 命令别名开关 — 控制侧边栏「命令别名」tab 的显示/隐藏
function _syncAliasTabVisibility(enabled) {
  var sidebarItem = document.querySelector('.cfg-sidebar-item[data-cfg-cat="aliases"]');
  if (sidebarItem) sidebarItem.style.display = enabled ? "" : "none";
  // 若当前在别名tab但被隐藏了，跳回功能开关tab
  if (!enabled) {
    var activeCat = document.querySelector('.cfg-sidebar-item.active[data-cfg-cat="aliases"]');
    if (activeCat) {
      var featuresItem = document.querySelector('.cfg-sidebar-item[data-cfg-cat="features"]');
      if (featuresItem) featuresItem.click();
    }
  }
}
var DEFAULT_COMMAND_ALIASES = {
  "message": ["msg", "m"],
  "bot": ["b"],
  "function": ["func", "fn"],
  "music": ["m"],
  "tool": ["t"],
  "spam": ["s"],
  "ws": ["w"],
  "ai": ["a"],
  "chat": ["c"],
  "ezmatic": ["ez"],
  "image": ["img"],
  "help": ["h", "?"],
  "perm": ["p"],
};

var aliasToggle = $("cfg-aliases-enabled");
if (aliasToggle) {
  aliasToggle.addEventListener("change", function () {
    _syncAliasTabVisibility(this.checked);
    if (this.checked) {
      // 开启别名:若当前为空则填充默认值
      if (!cfgData.commandAliases || Object.keys(cfgData.commandAliases).length === 0) {
        cfgData.commandAliases = JSON.parse(JSON.stringify(DEFAULT_COMMAND_ALIASES));
        toast(t("cfg.jsDefaultLoaded"), "ok");
      }
    } else {
      cfgData.commandAliases = {};
    }
    renderAliasList();
  });
}

function toggleBotMode() {
  var mode = $("cfg-bot-mode-server").checked ? "server" : "realm";
  var isServer = mode === "server";
  $("cfgBotServerFields").style.display = isServer ? "" : "none";
  $("cfgBotRealmFields").style.display = isServer ? "none" : "";
  // Xbox Live: server 模式下离线时隐藏, Realm 模式始终显示
  // 反转: 勾选=正版(online), 不勾选=离线(offline)
  var isOnline = false;
  if (isServer) {
    var hasLicense = $("cfg-bot-offline").checked;
    $("cfgBotXboxLiveFields").style.display = hasLicense ? "" : "none";
    isOnline = hasLicense;
  } else {
    $("cfgBotXboxLiveFields").style.display = "";
    isOnline = true;
  }
  // online 模式: 禁用 username 输入框,显示 Xbox 账号管理
  $("cfgBotUsernameOffline").style.display = isOnline ? "none" : "";
  $("cfgBotUsernameOnline").style.display = isOnline ? "" : "none";
  if (isOnline) {
    loadXboxAccounts();
  }
}
var botModeSvr = $("cfg-bot-mode-server");
var botModeRealm = $("cfg-bot-mode-realm");
if (botModeSvr) botModeSvr.addEventListener("change", toggleBotMode);
if (botModeRealm) botModeRealm.addEventListener("change", toggleBotMode);
var botOfflineEl = $("cfg-bot-offline");
if (botOfflineEl) botOfflineEl.addEventListener("change", toggleBotMode);

// ===== Xbox Live 多账号管理 =====
var _xboxPollTimer = null;

function loadXboxAccounts() {
  api("/bot/xbox-accounts").then(function (data) {
    if (!data.ok) return;
    var accounts = data.accounts || [];
    var active = data.active || null;
    // 更新当前账号显示
    var activeEl = $("cfg-bot-xbox-active");
    var badgeEl = $("cfg-bot-xbox-badge");
    if (activeEl) {
      activeEl.textContent = active || t("cfg.botXboxNotLogged");
    }
    if (badgeEl) {
      badgeEl.style.display = active ? "inline" : "none";
    }
    // 更新 username 隐藏字段(保存时使用)
    var usernameEl = $("cfg-bot-username");
    if (usernameEl && active) usernameEl.value = active;
    // 更新切换下拉框
    var switchEl = $("cfg-bot-xbox-switch");
    var switchBtn = $("cfg-bot-xbox-switch-btn");
    var removeBtn = $("cfg-bot-xbox-remove-btn");
    if (accounts.length > 1) {
      if (switchEl) {
        switchEl.innerHTML = accounts.map(function (a) {
          return '<option value="' + escapeHtml(a.username) + '"' +
            (a.username === active ? ' selected' : '') + '>' +
            escapeHtml(a.username) + '</option>';
        }).join("");
        switchEl.style.display = "";
      }
      if (switchBtn) switchBtn.style.display = "";
    } else {
      if (switchEl) switchEl.style.display = "none";
      if (switchBtn) switchBtn.style.display = "none";
    }
    if (removeBtn) {
      removeBtn.style.display = accounts.length > 0 ? "" : "none";
    }
  }).catch(function () {});
}

function startXboxLogin() {
  var modal = $("cfgBotXboxLoginModal");
  var step1 = $("cfgBotXboxLoginStep1");
  var step2 = $("cfgBotXboxLoginStep2");
  var result = $("cfgBotXboxLoginResult");
  if (modal) modal.style.display = "";
  if (step1) step1.style.display = "";
  if (step2) step2.style.display = "none";
  if (result) { result.style.display = "none"; result.innerHTML = ""; }
}

function startLoginProcess() {
  var step1 = $("cfgBotXboxLoginStep1");
  var step2 = $("cfgBotXboxLoginStep2");
  api("/bot/xbox-login", { method: "POST", body: JSON.stringify({}) })
    .then(function (data) {
      if (!data.ok) { toast(data.message || t("cfg.jsStartFail"), "err"); return; }
      if (step1) step1.style.display = "none";
      if (step2) step2.style.display = "";
      // 开始轮询登录状态
      pollXboxLoginStatus();
    })
    .catch(function (e) { toast(t("cfg.jsStartFailPrefix") + (e.message || e), "err"); });
}

function pollXboxLoginStatus() {
  if (_xboxPollTimer) clearInterval(_xboxPollTimer);
  _xboxPollTimer = setInterval(function () {
    api("/bot/xbox-login-status").then(function (data) {
      if (!data.ok) return;
      if (data.status === "waiting" && data.user_code) {
        var urlEl = $("cfg-bot-xbox-login-url");
        var codeEl = $("cfg-bot-xbox-login-code");
        if (urlEl) { urlEl.href = data.verification_uri; urlEl.textContent = data.verification_uri; }
        if (codeEl) codeEl.textContent = data.user_code;
      } else if (data.status === "done") {
        clearInterval(_xboxPollTimer); _xboxPollTimer = null;
        var result = $("cfgBotXboxLoginResult");
        var step2 = $("cfgBotXboxLoginStep2");
        if (step2) step2.style.display = "none";
        if (result) { result.style.display = ""; result.innerHTML = '<p style="color:var(--accent);">' + t("cfg.jsLoginOkPrefix") + escapeHtml(data.username) + t("cfg.jsLoginOkSuffix") + '</p>'; }
        loadXboxAccounts();
        setTimeout(closeXboxLoginModal, 2000);
      } else if (data.status === "error") {
        clearInterval(_xboxPollTimer); _xboxPollTimer = null;
        var result2 = $("cfgBotXboxLoginResult");
        var step2b = $("cfgBotXboxLoginStep2");
        if (step2b) step2b.style.display = "none";
        if (result2) { result2.style.display = ""; result2.innerHTML = '<p style="color:var(--danger,#ef4444);">' + t("cfg.jsLoginFailPrefix") + escapeHtml(data.error || t("cfg.jsUnknownError")) + '</p>'; }
      }
    }).catch(function () {});
  }, 2000);
}

function cancelXboxLogin() {
  if (_xboxPollTimer) { clearInterval(_xboxPollTimer); _xboxPollTimer = null; }
  api("/bot/xbox-login-stop", { method: "POST" }).catch(function () {});
  closeXboxLoginModal();
}

function closeXboxLoginModal() {
  var modal = $("cfgBotXboxLoginModal");
  if (modal) modal.style.display = "none";
}

function switchXboxAccount() {
  var select = $("cfg-bot-xbox-switch");
  if (!select) return;
  var username = select.value;
  if (!username) return;
  api("/bot/xbox-account/switch", { method: "POST", body: JSON.stringify({ username: username }) })
    .then(function (data) {
      toast(data.message, data.ok ? "ok" : "err");
      if (data.ok) loadXboxAccounts();
    })
    .catch(function (e) { toast(t("cfg.jsSwitchFailPrefix") + (e.message || e), "err"); });
}

function removeXboxAccount() {
  var active = ($("cfg-bot-xbox-active").textContent || "").trim();
  if (!active || active === t("cfg.botXboxNotLogged")) { toast(t("cfg.jsNoAccount"), "err"); return; }
  var select = $("cfg-bot-xbox-switch");
  var username = (select && select.style.display !== "none") ? select.value : active;
  if (!username) return;
  if (!confirm(t("cfg.jsRemoveConfirmPrefix") + username + t("cfg.jsRemoveConfirmSuffix"))) return;
  api("/bot/xbox-account/remove", { method: "POST", body: JSON.stringify({ username: username }) })
    .then(function (data) {
      toast(data.message, data.ok ? "ok" : "err");
      if (data.ok) loadXboxAccounts();
    })
    .catch(function (e) { toast(t("cfg.jsRemoveFailPrefix") + (e.message || e), "err"); });
}

// 绑定 Xbox 账号按钮事件
var xboxLoginBtn = $("cfg-bot-xbox-login");
if (xboxLoginBtn) xboxLoginBtn.addEventListener("click", startXboxLogin);
var xboxLoginStart = $("cfg-bot-xbox-login-start");
if (xboxLoginStart) xboxLoginStart.addEventListener("click", startLoginProcess);
var xboxLoginCancel = $("cfg-bot-xbox-login-cancel");
if (xboxLoginCancel) xboxLoginCancel.addEventListener("click", cancelXboxLogin);
var xboxLoginCancel2 = $("cfg-bot-xbox-login-cancel2");
if (xboxLoginCancel2) xboxLoginCancel2.addEventListener("click", cancelXboxLogin);
var xboxSwitchBtn = $("cfg-bot-xbox-switch-btn");
if (xboxSwitchBtn) xboxSwitchBtn.addEventListener("click", switchXboxAccount);
var xboxRemoveBtn = $("cfg-bot-xbox-remove-btn");
if (xboxRemoveBtn) xboxRemoveBtn.addEventListener("click", removeXboxAccount);

// ===== 表单数据收集 =====
function collectFormConfig() {
  if (!cfgData) return {};
  var f = cfgData.features || {};
  f.music = f.music || {}; f.qq = f.qq || {};
  f.music.playPercussion = $("cfg-percussion") ? $("cfg-percussion").checked : false;
  f.qq.enabled = $("cfg-qq") ? $("cfg-qq").checked : false;
  f.qq.groupId = parseInt($("cfg-qqgroup") ? $("cfg-qqgroup").value : 0, 10) || 0;
  f.qq.port = parseInt($("cfg-qqport") ? $("cfg-qqport").value : 0, 10) || 0;
  f.qq.host = ($("cfg-qqhost") ? $("cfg-qqhost").value.trim() : "") || "127.0.0.1";
  f.qq.accessToken = $("cfg-qqtoken") ? $("cfg-qqtoken").value.trim() : "";

  var rl = cfgData.rateLimit || {}; rl.command = rl.command || {};
  rl.command.enabled = $("cfg-ratelimit") ? $("cfg-ratelimit").checked : false;
  rl.command.windowMs = parseInt($("cfg-rlwindow") ? $("cfg-rlwindow").value : 1000, 10) || 1000;
  rl.command.maxPerWindow = parseInt($("cfg-rlmax") ? $("cfg-rlmax").value : 20, 10) || 20;

  var plp = cfgData.playerListPolling || {};
  plp.enabled = $("cfg-playerlistpolling") ? $("cfg-playerlistpolling").checked : false;
  plp.intervalSeconds = parseInt($("cfg-plpinterval") ? $("cfg-plpinterval").value : 30, 10) || 30;

  var webui = cfgData.webui || {};
  webui.enabled = $("cfg-webui") ? $("cfg-webui").checked : true;
  webui.port = parseInt($("cfg-webport") ? $("cfg-webport").value : 18888, 10) || 18888;
  webui.localOnly = $("cfg-weblockal") ? $("cfg-weblockal").checked : false;

  var ai = {
    baseURL: $("cfg-aibase") ? $("cfg-aibase").value.trim() : "",
    apiKey: $("cfg-aikey") ? $("cfg-aikey").value.trim() : "",
    chatModel: ($("cfg-aichatmodel") ? $("cfg-aichatmodel").value.trim() : "") || "deepseek-chat",
    chatMaxTokens: parseInt($("cfg-aichattokens") ? $("cfg-aichattokens").value : 512, 10) || 512,
    chatPrompt: $("cfg-aichatprompt") ? $("cfg-aichatprompt").value : "",
    cmdModel: ($("cfg-aicmdmodel") ? $("cfg-aicmdmodel").value.trim() : "") || "deepseek-chat",
    cmdMaxTokens: parseInt($("cfg-aicmdtokens") ? $("cfg-aicmdtokens").value : 1024, 10) || 1024,
    cmdPrompt: $("cfg-aicmdprompt") ? $("cfg-aicmdprompt").value : "",
    chatCooldown: parseInt($("cfg-aicooldown") ? $("cfg-aicooldown").value : 5000, 10) || 5000,
  };

  var utils = {
    tellAllToTell: $("cfg-tellall") ? $("cfg-tellall").checked : false,
    enablePolling: $("cfg-polling") ? $("cfg-polling").checked : true
  };

  var sapi = {
    gmsg: ($("cfg-gmsg") ? $("cfg-gmsg").value.trim() : "") || "gmsg",
    smsg: ($("cfg-smsg") ? $("cfg-smsg").value.trim() : "") || "smsg"
  };

  var announce = {
    enabled: $("cfg-announce-enabled") ? $("cfg-announce-enabled").checked : false,
    interval: parseInt($("cfg-announce-interval") ? $("cfg-announce-interval").value : 300, 10) || 300,
    messages: $("cfg-announce-messages") ? $("cfg-announce-messages").value.split(/\n+/).map(function (s) { return s.trim(); }).filter(Boolean) : [],
  };

  var mods = cfgData.mods || {}; mods.client = mods.client || {}; mods.server = mods.server || {};
  ["client", "server"].forEach(function (side) {
    MOD_CATALOG[side].forEach(function (m) {
      var cb = $("mod-" + side + "-" + m[0]);
      if (cb && cb.checked) mods[side][m[0]] = m[1];
      else if (mods[side][m[0]] === m[1]) delete mods[side][m[0]];
    });
  });

  var spam = cfgData.spam || {};
  spam.attack = $("cfg-spamattack") ? $("cfg-spamattack").value : "";
  spam.ad = $("cfg-spamad") ? $("cfg-spamad").value.split(/\n+/).map(function (s) { return s.trim(); }).filter(Boolean) : [];
  spam.adInterval = parseInt($("cfg-spaminterval") ? $("cfg-spaminterval").value : 0, 10) || 0;

  var basePath = cfgData.basePath || {};
  basePath.music = $("cfg-path-music") ? $("cfg-path-music").value.trim() : "";
  basePath.mcfunc = $("cfg-path-mcfunc") ? $("cfg-path-mcfunc").value.trim() : "";
  basePath.ezmatic = $("cfg-path-ezmatic") ? $("cfg-path-ezmatic").value.trim() : "";
  basePath.image = $("cfg-path-image") ? $("cfg-path-image").value.trim() : "";

  var bot = {
    enabled: true,
    mode: ($("cfg-bot-mode-server") && $("cfg-bot-mode-server").checked) ? "server" : "realm",
    host: ($("cfg-bot-host") ? $("cfg-bot-host").value.trim() : "") || "127.0.0.1",
    port: parseInt($("cfg-bot-port") ? $("cfg-bot-port").value : 19132, 10) || 19132,
    username: ($("cfg-bot-username") ? $("cfg-bot-username").value.trim() : "") || "FakeBot",
    version: ($("cfg-bot-version") ? $("cfg-bot-version").value.trim() : "") || null,
    offline: $("cfg-bot-offline") ? !$("cfg-bot-offline").checked : false,
    authTitle: ($("cfg-bot-authtitle") ? $("cfg-bot-authtitle").value.trim() : "") || null,
    profilesFolder: ($("cfg-bot-profilesfolder") ? $("cfg-bot-profilesfolder").value.trim() : "") || null,
    realmId: ($("cfg-bot-realmid") ? $("cfg-bot-realmid").value.trim() : "") || null,
    realmInvite: ($("cfg-bot-realminvite") ? $("cfg-bot-realminvite").value.trim() : "") || null,
  };

  return {
    name: ($("cfg-name") ? $("cfg-name").value.trim() : "") || "EnderBridge",
    port: parseInt($("cfg-port") ? $("cfg-port").value : 8800, 10) || 8800,
    commandPrefix: ($("cfg-prefix") ? $("cfg-prefix").value.trim() : "") || "$",
    logLevel: $("cfg-loglevel") ? $("cfg-loglevel").value : "info",
    githubToken: $("cfg-github-token") ? $("cfg-github-token").value.trim() : "",
    features: f, rateLimit: rl, webui: webui, ai: ai,
    utils: utils, sapi: sapi, bot: bot, mods: mods, spam: spam, basePath: basePath,
    messageConfig: { announcements: announce },
    commandAliases: cfgData.commandAliases || {},
    playerListPolling: plp,
    updateConfig: {
      autoBackup: $("cfg-backup-autobackup") ? $("cfg-backup-autobackup").checked : ($("cfg-autobackup") ? $("cfg-autobackup").checked : true),
    },
  };
}

// ===== 高级 Raw JSON 语法校验与行号定位 =====
var _lastJsonError = null;
var _jsonValidateTimer = null;

function getJsonErrorInfo(jsonStr) {
  if (!jsonStr || !jsonStr.trim()) {
    return {
      message: "JSON 内容为空",
      line: 1,
      column: 1,
      position: 0,
      snippet: { lineNum: 1, prev: null, curr: "", next: null }
    };
  }

  try {
    JSON.parse(jsonStr);
    return null;
  } catch (err) {
    var msg = err.message || "JSON 语法解析失败";
    var line = 1;
    var column = 1;
    var position = -1;

    // 1) 尝试提取 "at position X"
    var posMatch = msg.match(/at position (\d+)/i);
    if (posMatch) {
      position = parseInt(posMatch[1], 10);
    }

    // 2) 尝试提取 "line X column Y"
    var lineMatch = msg.match(/line (\d+)/i);
    var colMatch = msg.match(/column (\d+)/i);
    if (lineMatch) line = parseInt(lineMatch[1], 10);
    if (colMatch) column = parseInt(colMatch[1], 10);

    // 3) 若有精准字符偏移量 position，推导精确实时行号和列号
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

function validateRawJson() {
  var editor = $("cfgRawJsonEditor");
  if (!editor) return true;
  var val = editor.value;
  var err = getJsonErrorInfo(val);
  _lastJsonError = err;

  var banner = $("cfgJsonErrorBanner");
  var titleEl = $("cfgJsonErrorTitle");
  var msgEl = $("cfgJsonErrorMsg");
  var snippetEl = $("cfgJsonErrorSnippet");
  var badge = $("cfgJsonValidationBadge");

  var totalLines = val ? val.split("\n").length : 0;
  if ($("cfgJsonTotalLines")) $("cfgJsonTotalLines").textContent = "共 " + totalLines + " 行";

  if (!err) {
    if (banner) banner.style.display = "none";
    if (badge) {
      badge.className = "badge-sec-safe";
      badge.textContent = t("cfg.jsonValid");
    }
    return true;
  } else {
    if (banner) banner.style.display = "block";
    if (titleEl) {
      titleEl.textContent = "❌ " + t("cfg.jsonInvalid") + " (第 " + err.line + " 行, 第 " + err.column + " 列)";
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
      badge.textContent = t("cfg.jsonInvalid") + " (L" + err.line + ":C" + err.column + ")";
    }
    return false;
  }
}

function gotoErrorLine() {
  var editor = $("cfgRawJsonEditor");
  if (!editor || !_lastJsonError) return;
  var lines = editor.value.split("\n");
  var targetLine = _lastJsonError.line;
  var targetCol = _lastJsonError.column || 1;

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

function updateCursorInfo() {
  var editor = $("cfgRawJsonEditor");
  var infoEl = $("cfgJsonLineColInfo");
  if (!editor || !infoEl) return;
  var pos = editor.selectionStart || 0;
  var linesBefore = editor.value.substring(0, pos).split("\n");
  var line = linesBefore.length;
  var col = linesBefore[linesBefore.length - 1].length + 1;
  infoEl.textContent = "第 " + line + " 行, 第 " + col + " 列";
}

function saveConfig() {
  if (!cfgData) return;

  var activeCat = document.querySelector(".cfg-sidebar-item.active[data-cfg-cat]");
  var isRawMode = activeCat && activeCat.getAttribute("data-cfg-cat") === "raw";

  if (isRawMode) {
    var isValid = validateRawJson();
    if (!isValid) {
      var err = _lastJsonError;
      var banner = $("cfgJsonErrorBanner");
      if (banner) banner.scrollIntoView({ behavior: "smooth", block: "nearest" });
      toast(t("cfg.jsonSaveBlocked") + " (" + (err ? "第 " + err.line + " 行" : "") + ")", "err");
      return;
    }
    var editor = $("cfgRawJsonEditor");
    var parsedConfig;
    try {
      parsedConfig = JSON.parse(editor.value);
    } catch (e) {
      toast(t("cfg.jsonSaveBlocked"), "err");
      return;
    }

    api("/config", { method: "PUT", body: JSON.stringify({ config: parsedConfig }) })
      .then(function (data) {
        toast(data.message, data.ok ? "ok" : "err");
        if (data.ok) {
          cfgData = parsedConfig;
          loadConfig();
        }
      })
      .catch(function (e) {
        toast(t("cfg.jsSaveFailPrefix") + (e.message || e), "err");
      });
    return;
  }

  var currentPayload = collectFormConfig();
  api("/config", { method: "PUT", body: JSON.stringify({ config: currentPayload }) })
    .then(function (data) {
      toast(data.message, data.ok ? "ok" : "err");
      if (data.ok) loadConfig();
    })
    .catch(function (e) { toast(t("cfg.jsSaveFailPrefix") + (e.message || e), "err"); });
}

var cs1 = $("configSave"); if (cs1) cs1.addEventListener("click", saveConfig);
var cs2 = $("configSave2"); if (cs2) cs2.addEventListener("click", saveConfig);

// ===== Raw JSON 编辑器辅助按钮与交互 =====
var formatBtn = $("cfgJsonFormatBtn");
if (formatBtn) {
  formatBtn.addEventListener("click", function () {
    var editor = $("cfgRawJsonEditor");
    if (!editor) return;
    if (!validateRawJson()) {
      toast(t("cfg.jsonSaveBlocked"), "err");
      return;
    }
    try {
      var obj = JSON.parse(editor.value);
      editor.value = JSON.stringify(obj, null, 2);
      validateRawJson();
      toast(t("cfg.jsonFormat") + " ✔", "ok");
    } catch (e) {}
  });
}

var syncFromFormBtn = $("cfgJsonSyncFromFormBtn");
if (syncFromFormBtn) {
  syncFromFormBtn.addEventListener("click", function () {
    var editor = $("cfgRawJsonEditor");
    if (!editor) return;
    var currentCfg = collectFormConfig();
    editor.value = JSON.stringify(currentCfg, null, 2);
    validateRawJson();
    toast(t("cfg.jsonSynced"), "ok");
  });
}

var copyBtn = $("cfgJsonCopyBtn");
if (copyBtn) {
  copyBtn.addEventListener("click", function () {
    var editor = $("cfgRawJsonEditor");
    if (!editor) return;
    navigator.clipboard.writeText(editor.value)
      .then(function () { toast(t("cfg.jsonCopied"), "ok"); })
      .catch(function () { toast("复制失败", "err"); });
  });
}

var gotoErrorBtn = $("cfgJsonGotoErrorBtn");
if (gotoErrorBtn) {
  gotoErrorBtn.addEventListener("click", gotoErrorLine);
}

var rawEditor = $("cfgRawJsonEditor");
if (rawEditor) {
  // Tab 键插入两空格缩进
  rawEditor.addEventListener("keydown", function (e) {
    if (e.key === "Tab") {
      e.preventDefault();
      var start = this.selectionStart;
      var end = this.selectionEnd;
      this.value = this.value.substring(0, start) + "  " + this.value.substring(end);
      this.selectionStart = this.selectionEnd = start + 2;
      updateCursorInfo();
      clearTimeout(_jsonValidateTimer);
      _jsonValidateTimer = setTimeout(validateRawJson, 250);
    }
  });

  // 输入防抖校验
  rawEditor.addEventListener("input", function () {
    updateCursorInfo();
    clearTimeout(_jsonValidateTimer);
    _jsonValidateTimer = setTimeout(validateRawJson, 300);
  });

  // 光标位置指示更新
  rawEditor.addEventListener("click", updateCursorInfo);
  rawEditor.addEventListener("keyup", updateCursorInfo);
}

// ===== 防火墙放行 =====
var fwBtn = $("cfg-addFirewall");
if (fwBtn) fwBtn.addEventListener("click", function () {
  fwBtn.disabled = true;
  fwBtn.textContent = t("cfg.jsFwAdding");
  api("/firewall", { method: "POST" })
    .then(function (data) {
      if (data.ok) {
        toast(data.message, "ok");
      } else {
        toast(data.message, "err");
        if (data.command) {
          navigator.clipboard.writeText(data.command).then(function () {
            toast(t("cfg.jsFwCopied"), "ok");
          }).catch(function () {
            toast(t("cfg.jsFwCopyManualPrefix") + data.command, "err");
          });
        }
      }
    })
    .catch(function (e) { toast(t("cfg.jsReqFailPrefix") + (e.message || e), "err"); })
    .finally(function () {
      fwBtn.disabled = false;
      fwBtn.textContent = t("cfg.webFirewall");
    });
});

// ===== 在线资源与方块材质包管理 =====
function initTexturePackManager() {
  var btnDl = $("btnTexDownload");
  var btnLocal = $("btnTexLocalExtract");
  var btnUn = $("btnTexUninstall");

  if (btnDl) {
    btnDl.addEventListener("click", function () {
      var url = ($("cfg-tex-url") ? $("cfg-tex-url").value.trim() : "");
      doTexturePackAction("online", url);
    });
  }

  if (btnLocal) {
    btnLocal.addEventListener("click", function () {
      doTexturePackAction("local", "");
    });
  }

  if (btnUn) {
    btnUn.addEventListener("click", function () {
      var confirmed = confirm(t("cfg.texUninstallConfirm") || "确定要卸载本地所有方块材质包吗？卸载后 3D 蓝图预览将自动切换为基于调色板的平滑色彩模式，可随时重新下载。");
      if (!confirmed) return;
      doTexturePackUninstall();
    });
  }
}

function updateTexturePackUI(stat) {
  if (!stat) return;
  var badge = $("texPackBadge");
  var countEl = $("texPackCount");
  var sizeEl = $("texPackSize");
  var dirEl = $("texPackDir");

  if (badge) {
    if (stat.installed) {
      badge.textContent = t("cfg.texInstalled") || "已安装";
      badge.style.background = "rgba(34, 197, 94, 0.2)";
      badge.style.color = "#4ade80";
    } else {
      badge.textContent = t("cfg.texNotInstalled") || "未安装 (调色板降级)";
      badge.style.background = "rgba(255, 255, 255, 0.08)";
      badge.style.color = "var(--text-muted)";
    }
  }

  if (countEl) countEl.textContent = (stat.count || 0).toLocaleString() + " " + (t("cfg.texUnit") || "个方块纹理");
  if (sizeEl) sizeEl.textContent = stat.size_formatted || "0 B";
  if (dirEl && stat.directory) dirEl.textContent = stat.directory;
}

function loadTexturePackStatus() {
  api("/studio/textures/status")
    .then(function (res) {
      if (res && res.ok && res.data) {
        updateTexturePackUI(res.data);
      }
    })
    .catch(function (err) {
      console.warn("Failed to load texture pack status:", err);
    });
}

function doTexturePackAction(source, url) {
  var btnDl = $("btnTexDownload");
  var btnLocal = $("btnTexLocalExtract");
  var spinner = $("texDlSpinner");
  var txt = $("btnTexDownloadText");

  if (btnDl) btnDl.disabled = true;
  if (btnLocal) btnLocal.disabled = true;
  if (spinner) spinner.style.display = "inline-block";
  if (txt) txt.textContent = source === "local" ? (t("cfg.texExtracting") || "⏳ 正在提取...") : (t("cfg.texDownloading") || "⏳ 正在下载...");

  api("/studio/textures/download", {
    method: "POST",
    body: JSON.stringify({ source: source, url: url || "" })
  })
    .then(function (res) {
      if (res && res.ok) {
        toast(res.message || (t("cfg.texDownloadSuccess") || "材质包操作成功"), "ok");
        if (res.status) {
          updateTexturePackUI(res.status);
        } else {
          loadTexturePackStatus();
        }
      } else {
        toast((res && res.message) ? res.message : (t("cfg.texDownloadFailed") || "材质包操作失败"), "err");
      }
    })
    .catch(function (err) {
      toast((err && err.message) ? err.message : (t("cfg.texDownloadFailed") || "材质包操作异常"), "err");
    })
    .finally(function () {
      if (btnDl) btnDl.disabled = false;
      if (btnLocal) btnLocal.disabled = false;
      if (spinner) spinner.style.display = "none";
      if (txt) txt.textContent = t("cfg.btnTexDownload") || "⬇️ 在线下载 / 更新材质包";
    });
}

function doTexturePackUninstall() {
  var btnUn = $("btnTexUninstall");
  if (btnUn) btnUn.disabled = true;

  api("/studio/textures/uninstall", { method: "POST" })
    .then(function (res) {
      if (res && res.ok) {
        toast(res.message || (t("cfg.texUninstallSuccess") || "已成功卸载材质包"), "ok");
        if (res.status) {
          updateTexturePackUI(res.status);
        } else {
          loadTexturePackStatus();
        }
      } else {
        toast((res && res.message) ? res.message : (t("cfg.texUninstallFailed") || "卸载失败"), "err");
      }
    })
    .catch(function (err) {
      toast((err && err.message) ? err.message : (t("cfg.texUninstallFailed") || "卸载异常"), "err");
    })
    .finally(function () {
      if (btnUn) btnUn.disabled = false;
    });
}

// ===== 备份与恢复管理 =====
function initBackupManager() {
  var createBtn = $("cfgCreateBackupBtn");
  if (createBtn) {
    createBtn.addEventListener("click", doCreateBackup);
  }
  var descInput = $("cfgBackupDescInput");
  if (descInput) {
    descInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        doCreateBackup();
      }
    });
  }
  var refreshBtn = $("cfgRefreshBackupsBtn");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", loadConfigBackups);
  }
  var ab1 = $("cfg-autobackup");
  var ab2 = $("cfg-backup-autobackup");
  if (ab1 && ab2) {
    ab1.addEventListener("change", function () { ab2.checked = this.checked; });
    ab2.addEventListener("change", function () { ab1.checked = this.checked; });
  }
}

function loadConfigBackups() {
  var container = $("cfgBackupsContainer");
  if (!container) return;
  container.innerHTML = '<div class="td-dim" style="padding:16px 0;">' + (t("common.loading") || "加载中...") + '</div>';

  api("/update/backups")
    .then(function (res) {
      if (!res || !res.ok) {
        container.innerHTML = '<div style="color:var(--err,#ef4444);padding:16px 0;">' + escapeHtml((res && res.message) ? res.message : (t("cfg.backupLoadFail") || "获取备份列表失败")) + '</div>';
        return;
      }
      var backups = res.backups || [];
      if (backups.length === 0) {
        container.innerHTML = '<div class="hint" style="padding:20px 0;text-align:center;">' + (t("cfg.backupEmpty") || "暂无可用备份文件") + '</div>';
        return;
      }

      var html = '<div style="overflow-x:auto;"><table class="cfg-table" style="width:100%;border-collapse:collapse;margin-top:6px;">' +
        '<thead><tr style="border-bottom:1px solid var(--card-border);text-align:left;font-size:12px;color:var(--text-dim);">' +
        '<th style="padding:8px 10px;">' + (t("cfg.thTime") || t("upd.thTime") || "备份时间") + '</th>' +
        '<th style="padding:8px 10px;">' + (t("cfg.thFile") || t("upd.thFile") || "文件名") + '</th>' +
        '<th style="padding:8px 10px;">' + (t("cfg.thDesc") || t("upd.thDesc") || "备份描述") + '</th>' +
        '<th style="padding:8px 10px;">' + (t("cfg.thSize") || t("upd.thSize") || "大小") + '</th>' +
        '<th style="padding:8px 10px;text-align:right;">' + (t("cfg.thActions") || t("common.actions") || "操作") + '</th>' +
        '</tr></thead><tbody>';

      backups.forEach(function (b) {
        var sizeMB = b.size ? (b.size / 1048576).toFixed(1) + " MB" : (b.size > 1024 ? (b.size / 1024).toFixed(0) + " KB" : (b.size || 0) + " B");
        var timeStr = b.mtime ? new Date(b.mtime * 1000).toLocaleString() : (b.stamp || "—");
        var descText = b.description ? escapeHtml(b.description) : '<span style="color:var(--text-dim);font-style:italic;">—</span>';
        html += '<tr style="border-bottom:1px solid var(--card-border);font-size:13px;">' +
          '<td style="padding:10px 10px;white-space:nowrap;color:var(--text-dim);">' + escapeHtml(timeStr) + '</td>' +
          '<td style="padding:10px 10px;font-family:monospace;word-break:break-all;">' + escapeHtml(b.filename) + '</td>' +
          '<td style="padding:10px 10px;max-width:240px;word-break:break-word;">' +
          descText +
          ' <button type="button" class="btn-ghost btn-cfg-edit-desc" data-path="' + escapeHtml(b.path) + '" data-desc="' + escapeHtml(b.description || "") + '" title="' + (t("cfg.backupEditDesc") || "编辑描述") + '" style="cursor:pointer;background:none;border:none;padding:1px 4px;font-size:12px;opacity:0.75;">✏️</button>' +
          '</td>' +
          '<td style="padding:10px 10px;white-space:nowrap;color:var(--text-dim);">' + sizeMB + '</td>' +
          '<td style="padding:10px 10px;text-align:right;white-space:nowrap;">' +
          '<button type="button" class="btn btn-sm btn-ghost btn-cfg-restore" data-path="' + escapeHtml(b.path) + '" data-file="' + escapeHtml(b.filename) + '" style="margin-right:6px;color:var(--accent,#818cf8);">' + (t("cfg.btnRestore") || "⏪ 恢复此备份") + '</button>' +
          '<a class="btn btn-sm btn-ghost" href="/api/backups/download?path=' + encodeURIComponent(b.path) + '" download="' + escapeHtml(b.filename) + '" style="margin-right:6px;color:var(--text);text-decoration:none;">' + (t("cfg.btnDownload") || "📥 下载") + '</a>' +
          '<button type="button" class="btn btn-sm btn-ghost btn-cfg-delete" data-path="' + escapeHtml(b.path) + '" data-file="' + escapeHtml(b.filename) + '" style="color:var(--danger,#ef4444);">' + (t("cfg.btnDelete") || "🗑️ 删除") + '</button>' +
          '</td>' +
          '</tr>';
      });

      html += '</tbody></table></div>';
      container.innerHTML = html;

      // 绑定编辑描述事件
      container.querySelectorAll(".btn-cfg-edit-desc").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var p = this.getAttribute("data-path");
          var oldDesc = this.getAttribute("data-desc") || "";
          var newDesc = prompt(t("cfg.backupDescPrompt") || "请输入该备份的备注说明：", oldDesc);
          if (newDesc === null) return;
          api("/backups/description", {
            method: "POST",
            body: JSON.stringify({ path: p, description: newDesc })
          }).then(function (res) {
            if (res && res.ok) {
              toast(t("cfg.backupDescUpdated") || "备份描述已更新", "ok");
              loadConfigBackups();
            } else {
              toast((res && res.message) ? res.message : "更新描述失败", "err");
            }
          }).catch(function (err) {
            toast((err && err.message) ? err.message : "更新描述异常", "err");
          });
        });
      });

      // 绑定恢复与删除按钮事件
      container.querySelectorAll(".btn-cfg-restore").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var p = this.getAttribute("data-path");
          var fn = this.getAttribute("data-file");
          doRollbackBackup(p, fn);
        });
      });

      container.querySelectorAll(".btn-cfg-delete").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var p = this.getAttribute("data-path");
          var fn = this.getAttribute("data-file");
          doDeleteBackup(p, fn);
        });
      });
    })
    .catch(function (err) {
      container.innerHTML = '<div style="color:var(--err,#ef4444);padding:16px 0;">' + escapeHtml((err && err.message) ? err.message : (t("cfg.backupLoadFail") || "获取备份列表失败")) + '</div>';
    });
}

function doCreateBackup() {
  var btn = $("cfgCreateBackupBtn");
  var descInput = $("cfgBackupDescInput");
  var desc = descInput ? descInput.value.trim() : "";
  if (btn) btn.disabled = true;
  toast(t("cfg.backupCreating") || "正在创建备份中，请稍候...", "info", 3000);

  api("/backups/create", { method: "POST", body: JSON.stringify({ description: desc }) })
    .then(function (res) {
      if (res && res.ok) {
        toast((t("cfg.backupCreated") || "备份创建成功！") + (res.filename ? " (" + res.filename + ")" : ""), "ok");
        if (descInput) descInput.value = "";
        loadConfigBackups();
      } else {
        toast((res && res.message) ? res.message : "备份创建失败", "err");
      }
    })
    .catch(function (err) {
      toast((err && err.message) ? err.message : "创建备份异常", "err");
    })
    .finally(function () {
      if (btn) btn.disabled = false;
    });
}

function doDeleteBackup(path, filename) {
  var promptMsg = (t("cfg.backupDeleteConfirm") || "确定要彻底删除备份文件 {file} 吗？此操作无法撤销！").replace("{file}", filename);
  if (!confirm(promptMsg)) return;

  toast(t("cfg.backupDeleting") || "正在删除备份...", "info", 2000);
  api("/backups/delete", { method: "DELETE", body: JSON.stringify({ path: path }) })
    .then(function (res) {
      if (res && res.ok) {
        toast(t("cfg.backupDeleted") || "备份已成功删除", "ok");
        loadConfigBackups();
      } else {
        toast((res && res.message) ? res.message : "删除失败", "err");
      }
    })
    .catch(function (err) {
      toast((err && err.message) ? err.message : "删除备份异常", "err");
    });
}

function doRollbackBackup(path, filename) {
  var promptMsg = (t("cfg.backupRestoreConfirm") || "确定要将系统恢复到此备份快照吗？\n文件: {file}\n恢复后将自动重启服务器以加载旧版本。").replace("{file}", filename);
  if (!confirm(promptMsg)) return;

  var modal = $("cfgRollbackModal");
  if (modal) modal.style.display = "flex";
  var statusText = $("cfgRollbackStatusText");
  if (statusText) statusText.textContent = t("cfg.rollbackProcessing") || "正在执行系统回滚并准备重启...";
  var progressBar = $("cfgRollbackProgressBar");
  if (progressBar) progressBar.style.width = "40%";

  api("/update/rollback", { method: "POST", body: JSON.stringify({ path: path }) })
    .then(function (res) {
      if (res && res.ok) {
        if (progressBar) progressBar.style.width = "75%";
        var waitNotice = $("cfgRollbackNotice");
        if (waitNotice) waitNotice.textContent = t("cfg.rollbackWait") || "请稍候，服务器正在重启上线...";
        _pollAndRedirectConfig();
      } else {
        if (modal) modal.style.display = "none";
        toast((res && res.message) ? res.message : "回滚失败", "err");
      }
    })
    .catch(function (err) {
      if (modal) modal.style.display = "none";
      toast((err && err.message) ? err.message : "回滚触发异常", "err");
    });
}

function _pollAndRedirectConfig() {
  var basePort = parseInt(location.port || (location.protocol === "https:" ? 443 : 80), 10);
  var ports = [basePort];
  for (var i = 1; i <= 9; i++) { ports.push(basePort + i); }

  function fetchWithTimeout(url, ms) {
    var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var opts = ctrl ? { signal: ctrl.signal } : {};
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, ms) : null;
    return fetch(url, opts).finally(function () { if (timer) clearTimeout(timer); });
  }

  function probe() {
    var tryIdx = 0;
    return new Promise(function (resolve) {
      function tryPort() {
        if (tryIdx >= ports.length) { resolve(null); return; }
        var p = ports[tryIdx];
        fetchWithTimeout(location.protocol + "//" + location.hostname + ":" + p + "/api/status", 2500)
          .then(function (r) { return r.json(); })
          .then(function (d) { resolve(d.ok ? p : (tryIdx++, tryPort())); })
          .catch(function () { tryIdx++; tryPort(); });
      }
      tryPort();
    });
  }

  var waitCount = 0;
  var timer = setInterval(function () {
    waitCount++;
    var progressBar = $("cfgRollbackProgressBar");
    if (progressBar) {
      var pct = Math.min(95, 75 + waitCount * 2);
      progressBar.style.width = pct + "%";
    }

    if (waitCount >= 3) {
      probe().then(function (alivePort) {
        if (alivePort !== null) {
          clearInterval(timer);
          if (progressBar) progressBar.style.width = "100%";
          var statusText = $("cfgRollbackStatusText");
          if (statusText) statusText.textContent = t("cfg.rollbackSuccess") || "回滚成功，服务器已重启就绪！";
          setTimeout(function () {
            location.href = location.protocol + "//" + location.hostname + ":" + alivePort + "/config";
          }, 1500);
        }
      });
    }
  }, 1000);
}

