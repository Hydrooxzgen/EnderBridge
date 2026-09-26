// ===== 共享工具函数 =====
function $(id) { return document.getElementById(id); }
var TOKEN_KEY = "enderbridge_web_token";
var ROLE_KEY = "enderbridge_web_role";
var USER_KEY = "enderbridge_user";

function clearAuth() {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(ROLE_KEY);
  sessionStorage.removeItem(USER_KEY);
}

/** 获取当前用户信息对象 {username, role, permissions} */
function getCurrentUser() {
  try {
    return JSON.parse(sessionStorage.getItem(USER_KEY) || "{}");
  } catch(e) { return {}; }
}

/** 检查当前用户是否拥有指定权限 */
function hasPermission(perm) {
  var user = getCurrentUser();
  var perms = user.permissions || [];
  return perms.indexOf(perm) !== -1;
}

function toast(msg, type, duration) {
  var t = $("toast");
  if (!t) return;
  t.className = type || "ok";
  t.textContent = msg;
  t.style.display = "block";
  clearTimeout(t._timer);
  t._timer = setTimeout(function () { t.style.display = "none"; }, duration || 3000);
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
      if (res.status === 401) { clearAuth(); location.href = "/login"; return Promise.reject(data); }
      if (res.status === 403) { var _t = (typeof t === "function") ? t : function (k) { return k; }; toast(data.message || _t("common.noPermission"), "err"); return Promise.reject(data); }
      return data;
    });
  });
}

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\'/g, "&#39;").replace(/"/g, "&quot;");
}

function renderMarkdown(md) {
  var html = escapeHtml(md);
  html = html.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^# (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  html = html.replace(/\*(.+?)\*/g, '<i>$1</i>');
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  html = html.replace(/^[*-] (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>');
  html = html.replace(/<\/ul>\s*<ul>/g, '');
  html = html.replace(/\n/g, '<br>');
  return html;
}

// ===== 页面认证守卫 =====
var _PAGE_PERM_MAP = {
  "dashboard": "dashboard",
  "permissions": "permissions",
  "config": "config",
  "mods": "mods",
  "studio": "mods",
  "console": "console",
  "scheduler": "scheduler",
  "banlist": "banlist",
  "audit": "audit",
  "update": "update",
};
var _PAGE_ORDER = ["dashboard", "permissions", "config", "mods", "studio", "console", "scheduler", "audit", "update", "banlist"];

/** 找到当前路径对应的活跃页面名 */
function _getActivePage() {
  var path = location.pathname.replace(/^\//, "").replace(/\/$/, "");
  if (!path || path === "index.html") return "dashboard";
  return path;
}

/** 如果当前页面无权限,自动跳转到第一个有权限的页面 */
function _redirectIfNoPermission(perms) {
  var active = _getActivePage();
  var needed = _PAGE_PERM_MAP[active];
  if (needed && perms.indexOf(needed) === -1) {
    // 当前页面无权限,找第一个有权限的页面
    for (var i = 0; i < _PAGE_ORDER.length; i++) {
      if (perms.indexOf(_PAGE_ORDER[i]) !== -1) {
        var target = _PAGE_ORDER[i];
        location.href = target === "dashboard" ? "/" : "/" + target;
        return true; // 已跳转
      }
    }
    // 没有任何权限——由 initSidebar 处理提示
  }
  return false;
}

function requireAuth(callback) {
  var role = sessionStorage.getItem(ROLE_KEY) || "";
  var token = sessionStorage.getItem(TOKEN_KEY) || "";
  if (!role) { location.href = "/login"; return; }
  if (role === "guest") {
    // 访客模式:设置默认权限
    var user = getCurrentUser();
    if (!user.username) {
      sessionStorage.setItem(USER_KEY, JSON.stringify({
        username: "guest", role: "guest", permissions: ["dashboard", "mods"], system: false
      }));
    }
    callback(role);
    return;
  }
  // 已登录用户:先验证会话,同时拉取最新用户信息
  api("/auth/me").then(function (d) {
    if (d.ok) {
      sessionStorage.setItem(USER_KEY, JSON.stringify({
        username: d.username, role: d.role, permissions: d.permissions || [], system: d.system || false
      }));
      // 检查是否需要跳转到有权限的页面
      if (!_redirectIfNoPermission(d.permissions || [])) {
        callback(d.role);
      }
    } else {
      clearAuth();
      location.href = "/login";
    }
  }).catch(function () {
    // 网络错误:如果有本地缓存就继续
    var user = getCurrentUser();
    if (user.username) {
      if (!_redirectIfNoPermission(user.permissions || [])) {
        callback(user.role || role);
      }
    }
    else { clearAuth(); location.href = "/login"; }
  });
}

// ===== 侧边栏 =====
function initSidebar(activePage, role) {
  // 动态侧边栏:先生成再高亮(页面只需留 <aside class="sidebar" data-auto-sidebar>)
  if (typeof renderSidebar === "function") renderSidebar(activePage);
  if (typeof initLang === "function") initLang();
  var nav = document.querySelector('.nav-item[data-page="' + activePage + '"]');
  if (nav) nav.classList.add("active");
  document.querySelectorAll(".nav-item[data-page]").forEach(function (el) {
    el.addEventListener("click", function () {
      var page = el.getAttribute("data-page");
      location.href = page === "dashboard" ? "/" : "/" + page;
    });
  });
  var isGuest = role === "guest";
  // 按权限控制侧边栏可见性
  var permMap = {
    "dashboard": "dashboard",
    "permissions": "permissions",
    "config": "config",
    "mods": "mods",
    "console": "console",
    "scheduler": "scheduler",
    "banlist": "banlist",
    "audit": "audit",
    "update": "update",
  };
  document.querySelectorAll(".nav-item[data-page]").forEach(function (el) {
    var page = el.getAttribute("data-page");
    var perm = permMap[page];
    if (perm) {
      el.style.display = hasPermission(perm) ? "" : "none";
    }
  });
  // 检查是否有任何权限,没有则显示无权限提示
  var user = getCurrentUser();
  var userPerms = user.permissions || [];
  if (!isGuest && userPerms.length === 0) {
    // 隐藏所有页面内容,显示无权限提示
    var mainEl = document.querySelector(".main");
    if (mainEl) {
      // 隐藏 main 内所有子元素
      Array.from(mainEl.children).forEach(function (child) {
        child.style.display = "none";
      });
      // 插入无权限提示
      var noPermDiv = document.createElement("div");
      noPermDiv.style.cssText = "display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:60vh;text-align:center;padding:40px;";
      var _t2 = (typeof t === "function") ? t : function (k) { return k; };
      noPermDiv.innerHTML = '<div style="font-size:48px;margin-bottom:16px;">🔒</div>'
        + '<h2 style="margin-bottom:8px;">' + _t2("dash.noPermTitle") + '</h2>'
        + '<p class="muted" style="margin-bottom:20px;">' + _t2("dash.noPermMsg") + '</p>'
        + '<button class="btn btn-primary" onclick="clearAuth();location.href=\'/login\'">' + _t2("dash.switchAccount") + '</button>';
      mainEl.appendChild(noPermDiv);
    }
    // 隐藏侧边栏所有导航项(仅保留品牌和退出)
    document.querySelectorAll(".nav-item[data-page]").forEach(function (el) {
      el.style.display = "none";
    });
  }
  var gb = $("guestBadge"); if (gb) gb.style.display = isGuest ? "block" : "none";
  var alb = $("adminLoginBtn");
  if (alb) {
    alb.style.display = isGuest ? "flex" : "none";
    alb.addEventListener("click", function () { clearAuth(); location.href = "/login"; });
  }
  var lb = $("logoutBtn");
  if (lb) lb.addEventListener("click", function () {
    api("/auth/logout", { method: "POST" }).catch(function(){});
    clearAuth(); location.href = "/login";
  });
  // 按权限隐藏管理按钮
  if (!hasPermission("restart")) {
    var el = $("restartBtn"); if (el) el.style.display = "none";
  }
  if (!hasPermission("permissions")) {
    ["permSave", "permReload"].forEach(function (id) {
      var el = $(id); if (el) el.style.display = "none";
    });
  }
  if (!hasPermission("config")) {
    var el = $("configSave"); if (el) el.style.display = "none";
  }
  if (!hasPermission("mods")) {
    var el = $("modReloadAll"); if (el) el.style.display = "none";
  }
  if (!hasPermission("update")) {
    var el = $("updateLocalCard"); if (el) el.style.display = "none";
  }
}

// ===== 主题切换 =====
var THEME_KEY = "enderbridge_theme";

function getPreferredTheme() {
  var saved = localStorage.getItem(THEME_KEY);
  if (saved) return saved;
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem(THEME_KEY, theme);
  updateThemeIcon(theme);
}

function updateThemeIcon(theme) {
  var btn = $("themeToggle");
  if (!btn) return;
  var icon = btn.querySelector(".theme-icon");
  var label = btn.querySelector(".theme-label");
  var getText = (typeof t === "function") ? t : function (k) { return k; };
  if (theme === "light") {
    icon.textContent = "☀️";
    label.textContent = getText("nav.lightMode");
  } else {
    icon.textContent = "🌙";
    label.textContent = getText("nav.darkMode");
  }
}

function toggleTheme() {
  var current = document.documentElement.getAttribute("data-theme") || "dark";
  applyTheme(current === "dark" ? "light" : "dark");
}

function initTheme() {
  applyTheme(getPreferredTheme());
  var btn = $("themeToggle");
  if (btn) btn.addEventListener("click", toggleTheme);
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener("change", function (e) {
    if (!localStorage.getItem(THEME_KEY)) {
      applyTheme(e.matches ? "dark" : "light");
    }
  });
}
