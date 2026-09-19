// 封禁管理页面逻辑
requireAuth(function (role) {
  initSidebar("banlist", role);
  initTheme();
  initLang();
  loadBanlist();
});

function _updateBatchToolbar() {
  var allChecks = document.querySelectorAll(".ban-row-checkbox");
  var checked = document.querySelectorAll(".ban-row-checkbox:checked");
  var toolbar = $("banBatchToolbar");
  var countEl = $("banSelectedCount");
  var selectAll = $("banSelectAll");
  if (toolbar) toolbar.style.display = checked.length > 0 ? "inline-flex" : "none";
  if (countEl) countEl.textContent = t("ban.selectedCount").replace("{n}", checked.length);
  if (selectAll && allChecks.length > 0) {
    selectAll.checked = (checked.length === allChecks.length);
    selectAll.indeterminate = (checked.length > 0 && checked.length < allChecks.length);
  }
}

function loadBanlist() {
  var selectAll = $("banSelectAll");
  if (selectAll) { selectAll.checked = false; selectAll.indeterminate = false; }
  _updateBatchToolbar();
  api("/banlist").then(function (data) {
    if (!data.ok) return;
    var bans = data.bans || {};
    var keys = Object.keys(bans);
    $("banCount").textContent = "(" + keys.length + t("ban.countSuffix");
    if (keys.length === 0) {
      $("banTableBody").innerHTML = '<tr><td colspan="6" class="muted" style="text-align:center;padding:24px;">' + t("ban.empty") + '</td></tr>';
      return;
    }
    // 只有自动封禁的 IP 才触发攻击警报 toast(管理员手动封的不算)
    var autoBans = keys.filter(function (ip) {
      var reason = (bans[ip] || {}).reason || "";
      return reason.indexOf("自动封禁") !== -1;
    });
    if (autoBans.length > 0 && !_banlistAttackToastShown) {
      _banlistAttackToastShown = true;
      toast(t("ban.attackToast") + autoBans.length + t("ban.attackToastSuffix"), "warn", 6000);
    }
    $("banTableBody").innerHTML = keys.map(function (ip) {
      var info = bans[ip] || {};
      var expiresText = t("ban.permanent");
      if (info.expires) {
        var d = new Date(info.expires * 1000);
        expiresText = d.toLocaleString();
      }
      return '<tr style="border-bottom:1px solid #1e293b;">'
        + '<td style="padding:10px 12px;"><input type="checkbox" class="ban-row-checkbox" value="' + escapeHtml(ip) + '" /></td>'
        + '<td style="padding:10px 12px;font-family:monospace;">' + escapeHtml(ip) + '</td>'
        + '<td style="padding:10px 12px;">' + escapeHtml(info.reason || "—") + '</td>'
        + '<td style="padding:10px 12px;font-size:13px;" class="muted">' + escapeHtml(info.time || "—") + '</td>'
        + '<td style="padding:10px 12px;font-size:13px;" class="muted">' + escapeHtml(expiresText) + '</td>'
        + '<td style="padding:10px 12px;text-align:right;white-space:nowrap;">'
        + '<button class="btn btn-sm" style="color:var(--accent,#818cf8);" onclick="editBanDuration(\'' + escapeHtml(ip) + '\')">⏱️</button> '
        + '<button class="btn btn-sm" style="color:var(--err,#ef4444);" onclick="unbanIp(\'' + escapeHtml(ip) + '\')">' + t("ban.unban") + '</button>'
        + '</td></tr>';
    }).join("");

    // 绑定行勾选
    document.querySelectorAll(".ban-row-checkbox").forEach(function (cb) {
      cb.addEventListener("change", _updateBatchToolbar);
    });
  }).catch(function () {
    $("banTableBody").innerHTML = '<tr><td colspan="6" class="muted" style="text-align:center;padding:24px;">' + t("ban.loadFail") + '</td></tr>';
  });
}

function unbanIp(ip) {
  if (!confirm(t("ban.confirmUnban") + ip + " ?")) return;
  api("/banlist", { method: "DELETE", body: JSON.stringify({ ip: ip }) })
    .then(function (data) {
      toast(data.message, data.ok ? "ok" : "err");
      if (data.ok) loadBanlist();
    })
    .catch(function (e) { toast(t("ban.opFail") + (e.message || e), "err"); });
}

function editBanDuration(ip) {
  // 弹出输入框让用户输入新的封禁时长(分钟),0=永久
  var val = prompt(t("ban.promptDuration"), "0");
  if (val === null) return; // 用户取消
  var duration = parseInt(val, 10);
  if (isNaN(duration) || duration < 0) { toast(t("ban.invalidNumber"), "err"); return; }
  var durText = duration === 0 ? t("ban.permanent") : duration + " " + t("ban.minute");
  if (!confirm(t("ban.confirmUnban") + ip + t("ban.confirmDuration") + durText + " ?")) return;
  api("/banlist/edit", { method: "POST", body: JSON.stringify({ ip: ip, duration: duration }) })
    .then(function (data) {
      toast(data.message, data.ok ? "ok" : "err");
      if (data.ok) loadBanlist();
    })
    .catch(function (e) { toast(t("ban.opFail") + (e.message || e), "err"); });
}

var _banlistAttackToastShown = false;

// 封禁按钮
var banBtn = $("banBtn");
if (banBtn) banBtn.addEventListener("click", function () {
  var ip = $("banIpInput").value.trim();
  var reason = $("banReasonInput").value.trim();
  var durSel = $("banDurationSelect");
  var duration = parseInt(durSel.value, 10) || 0;
  if (duration === -1) {
    // 自定义时长:根据单位转换为分钟
    var custom = parseInt($("banCustomDuration").value, 10);
    if (!custom || custom <= 0) { toast(t("ban.invalidDuration"), "err"); return; }
    var unit = $("banDurationUnit").value;
    if (unit === "s") {
      duration = Math.max(Math.round(custom / 60), 1); // 秒→分钟,最少1分钟
    } else if (unit === "h") {
      duration = custom * 60; // 时→分钟
    } else {
      duration = custom; // 已经是分钟
    }
  }
  if (!ip) { toast(t("ban.needIp"), "err"); return; }
  var durText = duration === 0 ? t("ban.permanent") : duration + " " + t("ban.minute");
  if (!confirm(t("ban.confirmBan") + ip + " ?" + t("ban.banDurationLabel") + durText + ")")) return;
  api("/banlist", { method: "POST", body: JSON.stringify({ ip: ip, reason: reason, duration: duration }) })
    .then(function (data) {
      toast(data.message, data.ok ? "ok" : "err");
      if (data.ok) {
        $("banIpInput").value = "";
        $("banReasonInput").value = "";
        loadBanlist();
      }
    })
    .catch(function (e) { toast(t("ban.opFail") + (e.message || e), "err"); });
});

// 自定义时长切换(显示/隐藏自定义输入框和单位选择器)
var durSel = $("banDurationSelect");
var customDur = $("banCustomDuration");
var durUnit = $("banDurationUnit");
if (durSel) durSel.addEventListener("change", function () {
  var isCustom = this.value === "-1";
  customDur.style.display = isCustom ? "" : "none";
  durUnit.style.display = isCustom ? "" : "none";
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
var autoBanConfigArea = $("autoBanConfigArea");
if (autoBanToggle) {
  // 加载当前状态
  api("/banlist/auto-ban").then(function (data) {
    if (data.ok) {
      autoBanToggle.checked = !!data.enabled;
      if (autoBanConfigArea) autoBanConfigArea.style.display = data.enabled ? "" : "none";
    }
  }).catch(function () {});
  // 切换
  autoBanToggle.addEventListener("change", function () {
    var enabled = this.checked;
    if (autoBanConfigArea) autoBanConfigArea.style.display = enabled ? "" : "none";
    api("/banlist/auto-ban", { method: "POST", body: JSON.stringify({ enabled: enabled }) })
      .then(function (data) {
        toast(enabled ? t("ban.autoOn") : t("ban.autoOff"), data.ok ? "ok" : "err");
        if (data.ok) autoBanToggle.checked = data.enabled;
      })
      .catch(function (e) { toast(t("ban.opFail") + (e.message || e), "err"); });
  });
}

// ===== 自动封禁参数配置 =====
function loadAutoBanConfig() {
  api("/banlist/auto-ban-config").then(function (data) {
    if (!data.ok) return;
    $("abWindowInput").value = data.window || 60;
    $("abThresholdInput").value = data.threshold || 5;
    $("abDurationInput").value = data.banDuration || 10;
  }).catch(function () {});
}
loadAutoBanConfig();

var abSaveBtn = $("abConfigSaveBtn");
if (abSaveBtn) abSaveBtn.addEventListener("click", function () {
  var window_ = parseInt($("abWindowInput").value, 10);
  var threshold = parseInt($("abThresholdInput").value, 10);
  var banDuration = parseInt($("abDurationInput").value, 10);
  if (!window_ || window_ < 1) { toast(t("ban.windowMin"), "err"); return; }
  if (!threshold || threshold < 1) { toast(t("ban.thresholdMin"), "err"); return; }
  if (banDuration < 0) { toast(t("ban.durationNeg"), "err"); return; }
  api("/banlist/auto-ban-config", {
    method: "POST",
    body: JSON.stringify({ window: window_, threshold: threshold, banDuration: banDuration })
  }).then(function (data) {
    if (data.ok) {
      toast(t("ban.saved"), "ok");
      // 更新提示文本
      var hint = abSaveBtn.parentElement.nextElementSibling;
      if (hint) {
        var durText = banDuration === 0 ? t("ban.permanent") : banDuration + " " + t("ban.minute");
        hint.textContent = "例: " + window_ + " " + t("ban.second") + "内失败 " + threshold + " " + t("ban.times") + " → 自动封禁 " + durText;
      }
    } else {
      toast(t("ban.saveFail"), "err");
    }
  }).catch(function (e) { toast(t("ban.opFail") + (e.message || e), "err"); });
});

// ===== 单个 / 批量封禁 Tab 切换 =====
var tabSingleBtn = $("banTabSingleBtn");
var tabBatchBtn = $("banTabBatchBtn");
var singlePanel = $("banSinglePanel");
var batchPanel = $("banBatchPanel");

if (tabSingleBtn && tabBatchBtn) {
  tabSingleBtn.addEventListener("click", function () {
    if (singlePanel) singlePanel.style.display = "";
    if (batchPanel) batchPanel.style.display = "none";
    tabSingleBtn.className = "btn btn-sm btn-primary";
    tabBatchBtn.className = "btn btn-sm";
  });
  tabBatchBtn.addEventListener("click", function () {
    if (singlePanel) singlePanel.style.display = "none";
    if (batchPanel) batchPanel.style.display = "";
    tabBatchBtn.className = "btn btn-sm btn-primary";
    tabSingleBtn.className = "btn btn-sm";
  });
}

// ===== 批量封禁提交 =====
var batchBtn = $("banBatchBtn");
if (batchBtn) {
  batchBtn.addEventListener("click", function () {
    var raw = ($("banBatchIpsInput").value || "").trim();
    if (!raw) { toast(t("ban.needBatchIps"), "err"); return; }
    var reason = ($("banBatchReasonInput").value || "").trim();
    var duration = parseInt($("banBatchDurationSelect").value, 10) || 0;
    // 粗略统计行数供二次确认
    var lines = raw.split(/[\r\n,;\s]+/).filter(Boolean);
    if (!lines.length) { toast(t("ban.needBatchIps"), "err"); return; }
    if (!confirm(t("ban.batchConfirmPrefix") + lines.length + t("ban.batchConfirmSuffix"))) return;
    batchBtn.disabled = true;
    api("/banlist/batch", {
      method: "POST",
      body: JSON.stringify({ ips: raw, reason: reason, duration: duration })
    }).then(function (data) {
      batchBtn.disabled = false;
      toast(data.message, data.ok ? "ok" : "err");
      if (data.ok) {
        $("banBatchIpsInput").value = "";
        $("banBatchReasonInput").value = "";
        loadBanlist();
      }
    }).catch(function (e) {
      batchBtn.disabled = false;
      toast(t("ban.opFail") + (e.message || e), "err");
    });
  });
}

// ===== 表格全选 / 取消全选 =====
var selectAllBox = $("banSelectAll");
if (selectAllBox) {
  selectAllBox.addEventListener("change", function () {
    var checked = this.checked;
    document.querySelectorAll(".ban-row-checkbox").forEach(function (cb) {
      cb.checked = checked;
    });
    _updateBatchToolbar();
  });
}

// ===== 批量解封提交 =====
var batchDeleteBtn = $("banBatchDeleteBtn");
if (batchDeleteBtn) {
  batchDeleteBtn.addEventListener("click", function () {
    var checkedBoxes = document.querySelectorAll(".ban-row-checkbox:checked");
    var ips = [];
    checkedBoxes.forEach(function (cb) { ips.push(cb.value); });
    if (!ips.length) { toast(t("ban.noSelected"), "err"); return; }
    if (!confirm(t("ban.batchDeleteConfirmPrefix") + ips.length + t("ban.batchDeleteConfirmSuffix"))) return;
    batchDeleteBtn.disabled = true;
    api("/banlist", {
      method: "DELETE",
      body: JSON.stringify({ ips: ips })
    }).then(function (data) {
      batchDeleteBtn.disabled = false;
      toast(data.message, data.ok ? "ok" : "err");
      if (data.ok) loadBanlist();
    }).catch(function (e) {
      batchDeleteBtn.disabled = false;
      toast(t("ban.opFail") + (e.message || e), "err");
    });
  });
}

