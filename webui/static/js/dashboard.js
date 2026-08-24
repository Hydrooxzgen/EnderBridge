// ===== 仪表盘页面逻辑 =====
requireAuth(function (role) {
  initSidebar("dashboard", role);
  initTheme();
  refreshStatus();
  loadReleaseNotes();
});

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
