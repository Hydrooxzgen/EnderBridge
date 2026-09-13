// 封禁管理页面逻辑
requireAuth(function (role) {
  initSidebar("banlist", role);
  initTheme();
  loadBanlist();
});

function loadBanlist() {
  api("/banlist").then(function (data) {
    if (!data.ok) return;
    var bans = data.bans || {};
    var keys = Object.keys(bans);
    $("banCount").textContent = "(" + keys.length + " 条)";
    if (keys.length === 0) {
      $("banTableBody").innerHTML = '<tr><td colspan="5" class="muted" style="text-align:center;padding:24px;">暂无封禁记录</td></tr>';
      $("alertCard").style.display = "none";
      return;
    }
    // 只有自动封禁的 IP 才触发攻击警报(管理员手动封的不算)
    var autoBans = keys.filter(function (ip) {
      var reason = (bans[ip] || {}).reason || "";
      return reason.indexOf("自动封禁") !== -1;
    });
    if (autoBans.length > 0) {
      $("alertCard").style.display = "";
      $("alertCount").textContent = "—" + autoBans.length + " 个 IP 被自动封禁";
    } else {
      $("alertCard").style.display = "none";
    }
    $("banTableBody").innerHTML = keys.map(function (ip) {
      var info = bans[ip] || {};
      var expiresText = "永久";
      if (info.expires) {
        var d = new Date(info.expires * 1000);
        expiresText = d.toLocaleString();
      }
      return '<tr style="border-bottom:1px solid #1e293b;">'
        + '<td style="padding:10px 12px;font-family:monospace;">' + escapeHtml(ip) + '</td>'
        + '<td style="padding:10px 12px;">' + escapeHtml(info.reason || "—") + '</td>'
        + '<td style="padding:10px 12px;font-size:13px;" class="muted">' + escapeHtml(info.time || "—") + '</td>'
        + '<td style="padding:10px 12px;font-size:13px;" class="muted">' + escapeHtml(expiresText) + '</td>'
        + '<td style="padding:10px 12px;text-align:right;">'
        + '<button class="btn btn-sm" style="color:var(--accent,#818cf8);" onclick="unbanIp(\'' + escapeHtml(ip) + '\')">解封</button>'
        + '</td></tr>';
    }).join("");
  }).catch(function () {
    $("banTableBody").innerHTML = '<tr><td colspan="5" class="muted" style="text-align:center;padding:24px;">加载失败</td></tr>';
  });
}

function unbanIp(ip) {
  if (!confirm("确认解封 " + ip + " ?")) return;
  api("/banlist", { method: "DELETE", body: JSON.stringify({ ip: ip }) })
    .then(function (data) {
      toast(data.message, data.ok ? "ok" : "err");
      if (data.ok) loadBanlist();
    })
    .catch(function (e) { toast("操作失败: " + (e.message || e), "err"); });
}

// 封禁按钮
var banBtn = $("banBtn");
if (banBtn) banBtn.addEventListener("click", function () {
  var ip = $("banIpInput").value.trim();
  var reason = $("banReasonInput").value.trim();
  var durSel = $("banDurationSelect");
  var duration = parseInt(durSel.value, 10) || 0;
  if (duration === -1) {
    // 自定义时长
    var custom = parseInt($("banCustomDuration").value, 10);
    if (!custom || custom <= 0) { toast("请输入有效的封禁时长(分钟)", "err"); return; }
    duration = custom;
  }
  if (!ip) { toast("请输入 IP 地址", "err"); return; }
  var durText = duration === 0 ? "永久" : duration + " 分钟";
  if (!confirm("确认封禁 " + ip + " ? (封禁时长: " + durText + ")")) return;
  api("/banlist", { method: "POST", body: JSON.stringify({ ip: ip, reason: reason, duration: duration }) })
    .then(function (data) {
      toast(data.message, data.ok ? "ok" : "err");
      if (data.ok) {
        $("banIpInput").value = "";
        $("banReasonInput").value = "";
        loadBanlist();
      }
    })
    .catch(function (e) { toast("操作失败: " + (e.message || e), "err"); });
});

// 自定义时长切换
var durSel = $("banDurationSelect");
var customDur = $("banCustomDuration");
if (durSel) durSel.addEventListener("change", function () {
  customDur.style.display = this.value === "-1" ? "" : "none";
});

// 回车封禁
var banIpInput = $("banIpInput");
if (banIpInput) banIpInput.addEventListener("keydown", function (e) {
  if (e.key === "Enter") { $("banBtn").click(); }
});

// 刷新
var refreshBtn = $("banRefreshBtn");
if (refreshBtn) refreshBtn.addEventListener("click", loadBanlist);

// ===== 自动封禁开关 =====
var autoBanToggle = $("autoBanToggle");
if (autoBanToggle) {
  // 加载当前状态
  api("/banlist/auto-ban").then(function (data) {
    if (data.ok) autoBanToggle.checked = !!data.enabled;
  }).catch(function () {});
  // 切换
  autoBanToggle.addEventListener("change", function () {
    var enabled = this.checked;
    api("/banlist/auto-ban", { method: "POST", body: JSON.stringify({ enabled: enabled }) })
      .then(function (data) {
        toast(enabled ? "自动封禁已开启" : "自动封禁已关闭", data.ok ? "ok" : "err");
        if (data.ok) autoBanToggle.checked = data.enabled;
      })
      .catch(function (e) { toast("操作失败: " + (e.message || e), "err"); });
  });
}
