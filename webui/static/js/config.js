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
  loadConfig();
  initCategoryNav();
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

    $("cfg-webui").checked = webui.enabled !== false;
    $("cfg-webport").value = webui.port || 18888;
    $("cfg-webtoken").value = webui.token || "";
    $("cfg-weblockal").checked = webui.localOnly !== false;
    toggleSub("webuiFields", $("cfg-webui").checked);

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

    $("cfg-gmsg").value = sapi.gmsg || "gmsg";
    $("cfg-smsg").value = sapi.smsg || "smsg";

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
  }).catch(function () {});
}

// Toggle 展开/收起
["cfg-qq", "cfg-ratelimit", "cfg-webui"].forEach(function (id) {
  var el = $(id);
  if (el) el.addEventListener("change", function () {
    var subId = id === "cfg-qq" ? "qqFields" : id === "cfg-ratelimit" ? "rlFields" : "webuiFields";
    toggleSub(subId, this.checked);
  });
});

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
      activeEl.textContent = active || "未登录";
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
      if (!data.ok) { toast(data.message || "启动失败", "err"); return; }
      if (step1) step1.style.display = "none";
      if (step2) step2.style.display = "";
      // 开始轮询登录状态
      pollXboxLoginStatus();
    })
    .catch(function (e) { toast("启动失败: " + (e.message || e), "err"); });
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
        if (result) { result.style.display = ""; result.innerHTML = '<p style="color:var(--accent);">✅ 登录成功! 账号 ' + escapeHtml(data.username) + ' 已保存。</p>'; }
        loadXboxAccounts();
        setTimeout(closeXboxLoginModal, 2000);
      } else if (data.status === "error") {
        clearInterval(_xboxPollTimer); _xboxPollTimer = null;
        var result2 = $("cfgBotXboxLoginResult");
        var step2b = $("cfgBotXboxLoginStep2");
        if (step2b) step2b.style.display = "none";
        if (result2) { result2.style.display = ""; result2.innerHTML = '<p style="color:var(--danger,#ef4444);">❌ 登录失败: ' + escapeHtml(data.error || "未知错误") + '</p>'; }
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
    .catch(function (e) { toast("切换失败: " + (e.message || e), "err"); });
}

function removeXboxAccount() {
  var active = ($("cfg-bot-xbox-active").textContent || "").trim();
  if (!active || active === "未登录") { toast("没有可移除的账号", "err"); return; }
  var select = $("cfg-bot-xbox-switch");
  var username = (select && select.style.display !== "none") ? select.value : active;
  if (!username) return;
  if (!confirm("确定要移除账号 " + username + " 吗?")) return;
  api("/bot/xbox-account/remove", { method: "POST", body: JSON.stringify({ username: username }) })
    .then(function (data) {
      toast(data.message, data.ok ? "ok" : "err");
      if (data.ok) loadXboxAccounts();
    })
    .catch(function (e) { toast("移除失败: " + (e.message || e), "err"); });
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

function saveConfig() {
  if (!cfgData) return;
  var f = cfgData.features || {};
  f.music = f.music || {}; f.qq = f.qq || {};
  f.music.playPercussion = $("cfg-percussion").checked;
  f.qq.enabled = $("cfg-qq").checked;
  f.qq.groupId = parseInt($("cfg-qqgroup").value, 10) || 0;
  f.qq.port = parseInt($("cfg-qqport").value, 10) || 0;
  f.qq.host = $("cfg-qqhost").value.trim() || "127.0.0.1";
  f.qq.accessToken = $("cfg-qqtoken").value.trim();

  var rl = cfgData.rateLimit || {}; rl.command = rl.command || {};
  rl.command.enabled = $("cfg-ratelimit").checked;
  rl.command.windowMs = parseInt($("cfg-rlwindow").value, 10) || 1000;
  rl.command.maxPerWindow = parseInt($("cfg-rlmax").value, 10) || 20;

  var webui = cfgData.webui || {};
  webui.enabled = $("cfg-webui").checked;
    webui.port = parseInt($("cfg-webport").value, 10) || 18888;
    webui.token = $("cfg-webtoken").value.trim();
    webui.localOnly = $("cfg-weblockal").checked;
  var ai = {
    baseURL: $("cfg-aibase").value.trim(), apiKey: $("cfg-aikey").value.trim(),
    chatModel: $("cfg-aichatmodel").value.trim() || "deepseek-chat",
    chatMaxTokens: parseInt($("cfg-aichattokens").value, 10) || 512,
    chatPrompt: $("cfg-aichatprompt").value,
    cmdModel: $("cfg-aicmdmodel").value.trim() || "deepseek-chat",
    cmdMaxTokens: parseInt($("cfg-aicmdtokens").value, 10) || 1024,
    cmdPrompt: $("cfg-aicmdprompt").value,
    chatCooldown: parseInt($("cfg-aicooldown").value, 10) || 5000,
  };
  var utils = { tellAllToTell: $("cfg-tellall").checked, enablePolling: $("cfg-polling").checked };
  var sapi = { gmsg: $("cfg-gmsg").value.trim() || "gmsg", smsg: $("cfg-smsg").value.trim() || "smsg" };

  var mods = cfgData.mods || {}; mods.client = mods.client || {}; mods.server = mods.server || {};
  ["client", "server"].forEach(function (side) {
    MOD_CATALOG[side].forEach(function (m) {
      var cb = $("mod-" + side + "-" + m[0]);
      if (cb && cb.checked) mods[side][m[0]] = m[1];
      else if (mods[side][m[0]] === m[1]) delete mods[side][m[0]];
    });
  });

  var spam = cfgData.spam || {};
  spam.attack = $("cfg-spamattack").value;
  spam.ad = $("cfg-spamad").value.split(/\n+/).map(function (s) { return s.trim(); }).filter(Boolean);
  spam.adInterval = parseInt($("cfg-spaminterval").value, 10) || 0;

  var basePath = cfgData.basePath || {};
  basePath.music = $("cfg-path-music").value.trim();
  basePath.mcfunc = $("cfg-path-mcfunc").value.trim();
  basePath.ezmatic = $("cfg-path-ezmatic").value.trim();
  basePath.image = $("cfg-path-image").value.trim();

  var bot = {
    enabled: true,
    mode: $("cfg-bot-mode-server").checked ? "server" : "realm",
    host: $("cfg-bot-host").value.trim() || "127.0.0.1",
    port: parseInt($("cfg-bot-port").value, 10) || 19132,
    username: $("cfg-bot-username").value.trim() || "FakeBot",
    version: $("cfg-bot-version").value.trim() || null,
    // 反转: 勾选=正版(online,offline=false), 不勾选=离线(offline=true)
    offline: !$("cfg-bot-offline").checked,
    authTitle: $("cfg-bot-authtitle").value.trim() || null,
    profilesFolder: $("cfg-bot-profilesfolder").value.trim() || null,
    realmId: $("cfg-bot-realmid").value.trim() || null,
    realmInvite: $("cfg-bot-realminvite").value.trim() || null,
  };

  var payload = {
    config: {
      name: $("cfg-name").value.trim() || "EnderBridge",
      port: parseInt($("cfg-port").value, 10) || 8800,
      commandPrefix: $("cfg-prefix").value.trim() || "$",
      logLevel: $("cfg-loglevel").value,
      githubToken: $("cfg-github-token").value.trim(),
      features: f, rateLimit: rl, webui: webui, ai: ai,
      utils: utils, sapi: sapi, bot: bot, mods: mods, spam: spam, basePath: basePath,
    }
  };
  api("/config", { method: "PUT", body: JSON.stringify(payload) })
    .then(function (data) { toast(data.message, data.ok ? "ok" : "err"); if (data.ok) loadConfig(); })
    .catch(function (e) { toast("保存失败: " + (e.message || e), "err"); });
}

var cs1 = $("configSave"); if (cs1) cs1.addEventListener("click", saveConfig);
var cs2 = $("configSave2"); if (cs2) cs2.addEventListener("click", saveConfig);
