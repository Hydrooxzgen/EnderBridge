// ===== 审计日志页面逻辑 =====

var PAGE_SIZE = 50;
var _auditOffset = 0;
var _auditTotal = 0;
var _autoRefresh = false;
var _autoTimer = null;

var TYPE_LABELS = {
  chat: "💬 聊天",
  command: "⚡ 命令",
  terminal: "🖥️ 终端",
  connect: "🟢 连接",
  disconnect: "🔴 断开"
};

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
  if (statusEl) statusEl.textContent = "加载中…";

  api("/audit-logs" + qs).then(function (d) {
    if (statusEl) statusEl.textContent = "";
    if (!d.ok) { toast(d.message || "加载失败", "err"); return; }
    _auditTotal = d.total || 0;
    renderLogs(d.records || []);
  }).catch(function () {
    if (statusEl) statusEl.textContent = "请求失败";
  });
}

function renderLogs(records) {
  var body = $("auditLogBody");
  var empty = $("auditEmpty");
  var countEl = $("auditCount");
  if (countEl) countEl.textContent = "共 " + _auditTotal + " 条";

  if (!records.length) {
    if (body) body.innerHTML = "";
    if (empty) empty.style.display = "block";
    updatePagination();
    return;
  }
  if (empty) empty.style.display = "none";

  var html = records.map(function (r) {
    var typeLabel = TYPE_LABELS[r.type] || r.type;
    var ts = r.ts ? r.ts.replace("T", " ").replace(/\+.+$/, "") : "";
    var msg = escapeHtml(r.message || "");
    if (r.type === "command") {
      msg = msg.replace(/\[OK\]/g, '<span style="color:#4ade80;">[OK]</span>')
               .replace(/\[FAIL\]/g, '<span style="color:#f87171;">[FAIL]</span>');
    }
    return '<tr style="border-bottom:1px solid #1e293b;">'
      + '<td style="padding:6px 12px;white-space:nowrap;color:#94a3b8;font-size:12px;">' + ts + '</td>'
      + '<td style="padding:6px 12px;white-space:nowrap;">' + typeLabel + '</td>'
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
  if (info) info.textContent = "第 " + currentPage + " / " + totalPages + " 页";
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
    this.textContent = "🔄 自动刷新: " + (_autoRefresh ? "开" : "关");
    this.style.borderColor = _autoRefresh ? "#6366f1" : "";
    if (_autoRefresh) {
      _autoTimer = setInterval(fetchLogs, 3000);
    } else {
      clearInterval(_autoTimer);
      _autoTimer = null;
    }
  });
});
