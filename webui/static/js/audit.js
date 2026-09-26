// ===== 审计日志页面逻辑 =====

var PAGE_SIZE = 50;
var _auditOffset = 0;
var _auditTotal = 0;
var _autoRefresh = false;
var _autoTimer = null;

function getTypeLabel(key) {
  var map = {
    chat: "audit.typeChat",
    command: "audit.typeCommand",
    terminal: "audit.typeTerminal",
    connect: "audit.typeConnect",
    disconnect: "audit.typeDisconnect",
    ban: "audit.typeBan",
    config: "audit.typeConfig",
    user: "audit.typeUser",
    role: "audit.typeRole",
    update: "audit.typeUpdate"
  };
  return t(map[key] || key);
}

function exportAuditLogs(format) {
  var typeFilter = $("auditTypeFilter").value;
  var senderFilter = $("auditSenderFilter").value.trim();
  var params = [];
  params.push("format=" + encodeURIComponent(format));
  if (typeFilter) params.push("type=" + encodeURIComponent(typeFilter));
  if (senderFilter) params.push("sender=" + encodeURIComponent(senderFilter));
  var qs = params.join("&");

  var headers = {};
  var role = sessionStorage.getItem(ROLE_KEY) || "";
  if (role === "guest") {
    headers["X-Auth-Guest"] = "1";
  } else {
    var token = sessionStorage.getItem(TOKEN_KEY) || "";
    if (token) headers["X-Auth-Token"] = token;
  }

  fetch("/api/audit-logs/export?" + qs, { headers: headers })
    .then(function (res) {
      if (!res.ok) {
        return res.json().then(function (err) {
          throw new Error(err.message || t("audit.exportFail"));
        });
      }
      var disposition = res.headers.get("Content-Disposition") || "";
      var filename = "audit_log." + format;
      var match = disposition.match(/filename="?([^";]+)"?/);
      if (match && match[1]) filename = match[1];
      return res.blob().then(function (blob) {
        var url = window.URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        toast(t("audit.exportSuccess"), "ok");
      });
    })
    .catch(function (err) {
      toast(err.message || t("audit.exportFail"), "err");
    });
}

function fetchLogs() {
  var typeFilter = $("auditTypeFilter").value;
  var senderFilter = $("auditSenderFilter").value.trim();
  var params = [];
  if (typeFilter) params.push("type=" + encodeURIComponent(typeFilter));
  if (senderFilter) params.push("sender=" + encodeURIComponent(senderFilter));
  params.push("limit=" + PAGE_SIZE);
  params.push("offset=" + _auditOffset);
  var qs = params.length ? "?" + params.join("&") : "";

  var statusEl = $("auditStatus");
  if (statusEl) statusEl.textContent = t("audit.loading");

  api("/audit-logs" + qs).then(function (d) {
    if (statusEl) statusEl.textContent = "";
    if (!d.ok) { toast(d.message || t("audit.loadFail"), "err"); return; }
    _auditTotal = d.total || 0;
    renderLogs(d.records || []);
  }).catch(function (err) {
    console.error("fetchLogs error:", err);
    if (statusEl) statusEl.textContent = t("audit.reqFail");
  });
}

function renderLogs(records) {
  var body = $("auditLogBody");
  var empty = $("auditEmpty");
  var countEl = $("auditCount");
  if (countEl) countEl.textContent = t("audit.totalPrefix") + _auditTotal + t("audit.totalSuffix");

  if (!records.length) {
    if (body) body.innerHTML = "";
    if (empty) empty.style.display = "block";
    updatePagination();
    return;
  }
  if (empty) empty.style.display = "none";

  var html = records.map(function (r) {
    var typeLbl = getTypeLabel(r.type);
    var ts = r.ts ? r.ts.replace("T", " ").replace(/\+.+$/, "") : "";
    var msg = escapeHtml(r.message || "");
    if (r.type === "command") {
      msg = msg.replace(/\[OK\]/g, '<span style="color:#4ade80;">[OK]</span>')
               .replace(/\[FAIL\]/g, '<span style="color:#f87171;">[FAIL]</span>');
    }
    return '<tr style="border-bottom:1px solid #1e293b;">'
      + '<td style="padding:6px 12px;white-space:nowrap;color:#94a3b8;font-size:12px;">' + ts + '</td>'
      + '<td style="padding:6px 12px;white-space:nowrap;">' + typeLbl + '</td>'
      + '<td style="padding:6px 12px;white-space:nowrap;color:#e2e8f0;">' + escapeHtml(r.sender || "") + '</td>'
      + '<td style="padding:6px 12px;color:#cbd5e1;word-break:break-all;">' + msg + '</td>'
      + '</tr>';
  }).join("");
  if (body) body.innerHTML = html;
  updatePagination();
}

function updatePagination() {
  var totalPages = Math.max(1, Math.ceil(_auditTotal / PAGE_SIZE));
  var currentPage = Math.floor(_auditOffset / PAGE_SIZE) + 1;
  var info = $("auditPageInfo");
  if (info) info.textContent = t("audit.pageMid1") + currentPage + t("audit.pageMid2") + totalPages + t("audit.pageSuffix");
  var prev = $("auditPrevBtn");
  var next = $("auditNextBtn");
  if (prev) prev.disabled = currentPage <= 1;
  if (next) next.disabled = currentPage >= totalPages;
}

function doQuery() {
  _auditOffset = 0;
  fetchLogs();
}

requireAuth(function (role) {
  initSidebar("audit", role);
  initTheme();
  initLang();
  fetchLogs();

  $("auditQueryBtn").addEventListener("click", doQuery);
  $("auditSenderFilter").addEventListener("keydown", function (e) {
    if (e.key === "Enter") doQuery();
  });
  $("auditTypeFilter").addEventListener("change", doQuery);

  $("auditPrevBtn").addEventListener("click", function () {
    _auditOffset = Math.max(0, _auditOffset - PAGE_SIZE);
    fetchLogs();
  });
  $("auditNextBtn").addEventListener("click", function () {
    if (_auditOffset + PAGE_SIZE < _auditTotal) {
      _auditOffset += PAGE_SIZE;
      fetchLogs();
    }
  });

  $("auditAutoBtn").addEventListener("click", function () {
    _autoRefresh = !_autoRefresh;
    this.textContent = _autoRefresh ? t("audit.autoOn") : t("audit.autoOff");
    this.style.borderColor = _autoRefresh ? "#6366f1" : "";
    if (_autoRefresh) {
      _autoTimer = setInterval(fetchLogs, 3000);
    } else {
      clearInterval(_autoTimer);
      _autoTimer = null;
    }
  });

  var exportCsvBtn = $("auditExportCsvBtn");
  if (exportCsvBtn) exportCsvBtn.addEventListener("click", function () { exportAuditLogs("csv"); });

  var exportJsonBtn = $("auditExportJsonBtn");
  if (exportJsonBtn) exportJsonBtn.addEventListener("click", function () { exportAuditLogs("json"); });
});
