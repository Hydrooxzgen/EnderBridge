// ===== 仪表盘页面逻辑 =====
requireAuth(function (role) {
  initSidebar("dashboard", role);
  initTheme();
  refreshStatus();
  loadReleaseNotes();
  checkAttackAlert();
});

/** 检查是否有被封禁的 IP (攻击警报) */
function checkAttackAlert() {
  var el = $("attackAlert");
  if (!el) return;
  // 仅管理员可见
  var me = getCurrentUser();
  if (!me || (me.role !== "admin" && me.role !== "operator")) {
    el.style.display = "none";
    return;
  }
  api("/banlist").then(function (data) {
    if (!data.ok) return;
    var autoCount = data.autoBanCount || 0;
    if (autoCount > 0) {
      el.style.display = "";
      $("attackAlertInfo").textContent = "—" + autoCount + " 个 IP 被自动封禁";
    } else {
      el.style.display = "none";
    }
  }).catch(function () {
    el.style.display = "none";
  });
}

function formatDuration(seconds) {
  var h = Math.floor(seconds / 3600),
      m = Math.floor((seconds % 3600) / 60),
      s = Math.floor(seconds % 60);
  if (h > 0) return h + "时 " + m + "分";
  if (m > 0) return m + "分 " + s + "秒";
  return s + "秒";
}

function renderPlayers(players) {
  var el = $("playersList");
  if (!el) return;
  if (!players || !players.length) {
    el.innerHTML = '<div class="td-dim" style="padding:12px 0;">暂无客户端连接</div>';
    return;
  }
  var now = Date.now() / 1000;
  el.innerHTML = players.map(function (p) {
    var dur = p.connectedAt ? formatDuration(now - p.connectedAt) : "未知";
    var badge = p.isMain ? '<span class="badge badge-main">主客户端</span>' : '<span class="badge">副客户端</span>';
    var display = p.name ? escapeHtml(p.name) + ' <span class="player-ip">(' + escapeHtml(p.ip) + ')</span>' : escapeHtml(p.ip);
    return '<div class="player-row">'
      + display
      + badge
      + '<span class="player-dur">⏱ ' + dur + '</span>'
      + '</div>';
  }).join("");
}

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
      statCard("⏱️", uptimeText, "运行时间");
    renderPlayers(data.players || []);
  }).catch(function () {});
}
function statCard(icon, val, label) {
  return '<div class="stat"><div class="val">' + icon + " " + escapeHtml(String(val)) + '</div><div class="label">' + label + "</div></div>";
}

function loadReleaseNotes() {
  api("/release-notes").then(function (data) {
    if (!data.ok) return;
    var card = $("releaseNotesCard");
    card.style.display = "";
    if (!data.release) {
      $("releaseTag").textContent = "";
      $("releaseBody").innerHTML = '<span class="td-dim">' + escapeHtml(data.message || "暂无 Release Notes") + '</span>';
      $("releaseLink").style.display = "none";
      return;
    }
    var r = data.release;
    $("releaseTag").textContent = r.tag ? ("(" + r.tag + ")") : "";
    var body = r.body || "";
    if (body.trim()) {
      $("releaseBody").innerHTML = renderMarkdown(body);
    } else {
      $("releaseBody").innerHTML = '<span class="td-dim">无 Release Notes</span>';
    }
    if (r.html_url) {
      $("releaseLink").href = r.html_url;
      $("releaseLink").style.display = "";
    }
  }).catch(function () {});
}

// ===== 一键重启 =====
var restartBtn = $("restartBtn");
if (restartBtn) {
  restartBtn.addEventListener("click", function () {
    if (!confirm("确定要重启服务器吗？\n当前所有连接将被断开,重启完成后页面将自动刷新。")) return;
    var btn = this;
    btn.disabled = true;
    api("/restart", { method: "POST" })
      .then(function (data) {
        if (!data.ok) {
          toast(data.message || "重启失败", "err");
          btn.disabled = false;
          return;
        }
        toast("服务器正在重启...", "ok");
        var tries = 0;
        var timer = setInterval(function () {
          tries++;
          fetch("/api/status").then(function (res) { return res.json(); })
            .then(function (d) { if (d.ok) { clearInterval(timer); location.reload(); } })
            .catch(function () {});
          if (tries >= 60) {
            clearInterval(timer);
            btn.disabled = false;
            toast("等待服务器恢复超时,请手动刷新页面", "err");
          }
        }, 2000);
      })
      .catch(function () { btn.disabled = false; });
  });
}
