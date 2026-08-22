// ===== 工具 =====
function $(id) { return document.getElementById(id); }
var TOKEN_KEY = "enderbridge_web_token";
var ROLE_KEY = "enderbridge_web_role";

function clearAuth() {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(ROLE_KEY);
}

function toast(msg, type) {
  var t = $("toast");
  t.className = type || "ok";
  t.textContent = msg;
  t.style.display = "block";
  clearTimeout(t._timer);
  t._timer = setTimeout(function () { t.style.display = "none"; }, 3000);
}

function api(path, options) {
  options = options || {};
  options.headers = options.headers || {};
  options.headers["Content-Type"] = "application/json";
  var role = sessionStorage.getItem(ROLE_KEY) || "";
  if (role === "guest") {
    options.headers["X-Auth-Guest"] = "1";
  } else {
    var token = sessionStorage.getItem(TOKEN_KEY) || "";
    if (token) options.headers["X-Auth-Token"] = token;
  }
  return fetch("/api" + path, options).then(function (res) {
    return res.json().then(function (data) {
      if (res.status === 401) {
        clearAuth();
        showLogin();
        return Promise.reject(data);
      }
      if (res.status === 403) {
        toast(data.message || "无权限", "err");
        return Promise.reject(data);
      }
      return data;
    });
  });
}

// ===== 页面切换 =====
var pages = ["dashboard", "permissions", "config", "mods"];
function showPage(name) {
  pages.forEach(function (p) {
    $("page-" + p).classList.toggle("active", p === name);
  });
  document.querySelectorAll(".nav-item").forEach(function (el) {
    el.classList.toggle("active", el.getAttribute("data-page") === name);
  });
  if (name === "dashboard") refreshStatus();
  if (name === "permissions") loadPermissions();
  if (name === "config") loadConfig();
  if (name === "mods") loadMods();
}
document.querySelectorAll(".nav-item").forEach(function (el) {
  el.addEventListener("click", function () { showPage(el.getAttribute("data-page")); });
});

// ===== 登录 =====
function showLogin() {
  $("appView").classList.remove("show");
  $("loginView").classList.add("show");
}
function showApp() {
  $("loginView").classList.remove("show");
  $("appView").classList.add("show");
}
function enterApp(role) {
  sessionStorage.setItem(ROLE_KEY, role);
  applyRoleUI(role);
  showApp();
  refreshStatus();
}
function applyRoleUI(role) {
  var isGuest = role === "guest";
  // 访客仅保留仪表盘与 Mod 列表(只读)
  document.querySelectorAll('.nav-item[data-page="permissions"], .nav-item[data-page="config"]')
    .forEach(function (el) { el.style.display = isGuest ? "none" : ""; });
  $("guestBadge").style.display = isGuest ? "block" : "none";
  $("adminLoginBtn").style.display = isGuest ? "flex" : "none";
  $("permSave").style.display = isGuest ? "none" : "";
  $("permReload").style.display = isGuest ? "none" : "";
  $("configSave").style.display = isGuest ? "none" : "";
  $("modReloadAll").style.display = isGuest ? "none" : "";
  if (isGuest) showPage("dashboard");
}
$("loginBtn").addEventListener("click", function () {
  var token = $("tokenInput").value.trim();
  sessionStorage.setItem(TOKEN_KEY, token);
  api("/auth", { method: "POST", body: JSON.stringify({ token: token }) })
    .then(function (data) {
      if (data.ok && data.role === "admin") {
        $("loginMsg").textContent = "";
        enterApp("admin");
      } else {
        // 密码错误:停留登录页并提示,不自动进入访客模式
        sessionStorage.removeItem(TOKEN_KEY);
        $("loginMsg").textContent = data.message || "密码错误";
      }
    }).catch(function () {
      $("loginMsg").textContent = "无法连接服务器";
    });
});
$("guestBtn").addEventListener("click", function () {
  sessionStorage.removeItem(TOKEN_KEY);
  $("loginMsg").textContent = "";
  enterApp("guest");
});
$("tokenInput").addEventListener("keydown", function (e) {
  if (e.key === "Enter") $("loginBtn").click();
});
$("adminLoginBtn").addEventListener("click", function () {
  clearAuth();
  showLogin();
});
$("logoutBtn").addEventListener("click", function () {
  clearAuth();
  showLogin();
});

// ===== 仪表盘 =====
function refreshStatus() {
  api("/status").then(function (data) {
    if (!data.ok) return;
    $("srvName").textContent = data.name;
    var uptime = data.uptime || 0;
    var s = Math.floor(uptime % 60), m = Math.floor(uptime / 60) % 60, h = Math.floor(uptime / 3600);
    var uptimeText = (h > 0 ? h + "时 " : "") + (m > 0 ? m + "分 " : "") + s + "秒";
    $("statGrid").innerHTML =
      statCard("📛", data.name, "服务器名称") +
      statCard("🔌", data.port, "WebSocket 端口") +
      statCard("🌐", data.webPort, "Web 管理端口") +
      statCard("👥", data.clients, "在线客户端") +
      statCard("⏱️", uptimeText, "运行时间") +
      statCard("🔑", data.webTokenSet ? "已设置" : "未设置", "管理令牌");
  }).catch(function () {});
}
function statCard(icon, val, label) {
  return '<div class="stat"><div class="val">' + icon + " " + escapeHtml(String(val)) + '</div><div class="label">' + label + "</div></div>";
}
function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ===== 权限管理 =====
var permData = { owner: "YourXboxName", op: [], user: [], blocker: [] };
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
// 保存到服务器(添加/删除/保存按钮共用),成功后重载确认
function savePerm(tip) {
  permData.owner = $("perm-owner").value.trim() || "YourXboxName";
  return api("/permissions", { method: "PUT", body: JSON.stringify({ permissions: permData }) })
    .then(function (data) {
      toast(data.message || tip, data.ok ? "ok" : "err");
      if (data.ok) loadPermissions();
    }).catch(function () {});
}
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
document.addEventListener("click", function (e) {
  if (e.target.classList.contains("x")) {
    var g = e.target.getAttribute("data-group");
    var name = e.target.getAttribute("data-name");
    permData[g] = (permData[g] || []).filter(function (n) { return n !== name; });
    savePerm("已移除 " + name + " ← " + g);
  }
});
$("permSave").addEventListener("click", function () {
  savePerm("权限已保存");
});
$("permReload").addEventListener("click", function () {
  loadPermissions();
  toast("已重新加载", "ok");
});

// ===== 功能设置 =====
var cfgData = null;
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
    $("cfg-prefix").value = data.config.commandPrefix || "!";
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
    toggleSub("webuiFields", $("cfg-webui").checked);

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
    $("cfg-gmsg").value = sapi.gmsg || "gmsg";
    $("cfg-smsg").value = sapi.smsg || "smsg";
  }).catch(function () {});
}
function toggleSub(id, show) {
  $(id).classList.toggle("show", !!show);
}
$("cfg-qq").addEventListener("change", function () { toggleSub("qqFields", this.checked); });
$("cfg-ratelimit").addEventListener("change", function () { toggleSub("rlFields", this.checked); });
$("cfg-webui").addEventListener("change", function () { toggleSub("webuiFields", this.checked); });

$("configSave").addEventListener("click", function () {
  if (!cfgData) return;
  var f = cfgData.features || {};
  f.music = f.music || {};
  f.qq = f.qq || {};
  f.music.playPercussion = $("cfg-percussion").checked;
  f.qq.enabled = $("cfg-qq").checked;
  f.qq.groupId = parseInt($("cfg-qqgroup").value, 10) || 0;
  f.qq.port = parseInt($("cfg-qqport").value, 10) || 0;
  f.qq.host = $("cfg-qqhost").value.trim() || "127.0.0.1";
  f.qq.accessToken = $("cfg-qqtoken").value.trim();

  var rl = cfgData.rateLimit || {};
  rl.command = rl.command || {};
  rl.command.enabled = $("cfg-ratelimit").checked;
  rl.command.windowMs = parseInt($("cfg-rlwindow").value, 10) || 1000;
  rl.command.maxPerWindow = parseInt($("cfg-rlmax").value, 10) || 20;

  var webui = cfgData.webui || {};
  webui.enabled = $("cfg-webui").checked;
  webui.port = parseInt($("cfg-webport").value, 10) || 18888;
  webui.token = $("cfg-webtoken").value.trim();

  var ai = {
    baseURL: $("cfg-aibase").value.trim(),
    apiKey: $("cfg-aikey").value.trim(),
    chatModel: $("cfg-aichatmodel").value.trim() || "deepseek-chat",
    chatMaxTokens: parseInt($("cfg-aichattokens").value, 10) || 512,
    chatPrompt: $("cfg-aichatprompt").value,
    cmdModel: $("cfg-aicmdmodel").value.trim() || "deepseek-chat",
    cmdMaxTokens: parseInt($("cfg-aicmdtokens").value, 10) || 1024,
    cmdPrompt: $("cfg-aicmdprompt").value,
    chatCooldown: parseInt($("cfg-aicooldown").value, 10) || 5000,
  };
  var utils = {
    tellAllToTell: $("cfg-tellall").checked,
    enablePolling: $("cfg-polling").checked,
  };
  var sapi = {
    gmsg: $("cfg-gmsg").value.trim() || "gmsg",
    smsg: $("cfg-smsg").value.trim() || "smsg",
  };

  var payload = {
    config: {
      name: $("cfg-name").value.trim() || "EnderBridge",
      port: parseInt($("cfg-port").value, 10) || 8800,
      commandPrefix: $("cfg-prefix").value.trim() || "!",
      logLevel: $("cfg-loglevel").value,
      features: f,
      rateLimit: rl,
      webui: webui,
      ai: ai,
      utils: utils,
      sapi: sapi,
    }
  };
  api("/config", { method: "PUT", body: JSON.stringify(payload) })
    .then(function (data) {
      toast(data.message, data.ok ? "ok" : "err");
      if (data.ok) loadConfig();
    }).catch(function () {});
});

// ===== Mod 管理 =====
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
    return '<tr>' +
      "<td>" + escapeHtml(name) + "</td>" +
      '<td class="td-dim">' + escapeHtml(info.path) + "</td>" +
      '<td><span class="status-dot ' + (ok ? "ok" : "bad") + '"></span>' + (ok ? "可导入" : "导入失败") + "</td>" +
      "</tr>";
  }).join("");
}
$("modRefresh").addEventListener("click", loadMods);
$("modReloadAll").addEventListener("click", function () {
  var btn = this;
  btn.disabled = true;
  api("/mods/reload-all", { method: "POST" })
    .then(function (data) {
      toast(data.message || "重载完成", data.ok ? "ok" : "err");
    }).catch(function () {})
    .finally(function () { btn.disabled = false; });
});

// ===== 启动 =====
api("/status").then(function (data) {
  if (!data.ok) { showLogin(); return; }
  var role = sessionStorage.getItem(ROLE_KEY) || "";
  if (!data.webTokenSet) {
    // 未设置令牌:本机直接开放全部权限
    sessionStorage.removeItem(TOKEN_KEY);
    enterApp("admin");
    return;
  }
  if (role === "guest") {
    // 上次以访客进入
    enterApp("guest");
  } else if (role === "admin" && sessionStorage.getItem(TOKEN_KEY)) {
    // 校验上次的令牌是否仍有效
    api("/config").then(function (d) {
      if (d.ok) enterApp("admin");
      else { clearAuth(); showLogin(); }
    }).catch(function () { clearAuth(); showLogin(); });
  } else {
    showLogin();
  }
}).catch(function () {
  showLogin();
});
