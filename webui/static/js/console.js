// ===== 控制台页面逻辑(统一终端视图) =====
var _logLines = [];
var MAX_LOG_LINES = 1000;
var _logPaused = false;
var _logSSE = null;
var _logAutoScroll = true;
var _logLevelFilter = "all";
var _logConnected = false;

var LOG_LEVEL_ORDER = { debug: 0, info: 1, warning: 2, error: 3 };

// ===== 统一日志渲染 =====

function addEntry(record) {
  _logLines.push(record);
  if (_logLines.length > MAX_LOG_LINES) _logLines.shift();
  renderEntry(record);
  updateLogCount();
}

function renderEntry(record) {
  var viewer = $("logViewer");
  if (!viewer) return;
  // 级别过滤(命令输入行始终显示,命令失败视为 error 级别)
  if (record._type !== "cmd") {
    if (_logLevelFilter !== "all") {
      var want = LOG_LEVEL_ORDER[_logLevelFilter];
      var got = record._type === "cmd-result"
        ? (record._ok !== false ? 1 : 3)
        : LOG_LEVEL_ORDER[record.level];
      if (want !== undefined && (got === undefined || got < want)) return;
    }
  }
  var div = document.createElement("div");
  if (record._type === "cmd") {
    // 命令输入行
    div.className = "log-line log-cmd";
    div.innerHTML = '<span class="log-ts">' + escapeHtml(record._ts || "") + '</span>'
      + '<span class="log-msg">' + escapeHtml(record._text || "") + '</span>';
  } else if (record._type === "cmd-result") {
    // 命令执行结果
    var ok = record._ok !== false;
    div.className = "log-line " + (ok ? "log-cmd-ok" : "log-cmd-err");
    div.innerHTML = '<span class="log-ts">' + escapeHtml(record._ts || "") + '</span>'
      + '<span class="log-level">' + escapeHtml(ok ? "OK" : "ERR") + '</span>'
      + '<span class="log-msg">' + escapeHtml(record._text || "") + '</span>';
  } else {
    // 服务器日志
    var levelClass = "log-" + (record.level || "info");
    var ts = record.ts ? record.ts.split("T")[1] || record.ts : "";
    div.className = "log-line " + levelClass;
    div.innerHTML = '<span class="log-ts">' + escapeHtml(ts) + '</span>'
      + '<span class="log-level">' + escapeHtml((record.level || "").toUpperCase()) + '</span>'
      + '<span class="log-src">' + escapeHtml(record.source || "") + '</span>'
      + '<span class="log-msg">' + escapeHtml(record.message || "") + '</span>';
  }
  viewer.appendChild(div);
  // 限制 DOM 节点数
  while (viewer.children.length > MAX_LOG_LINES) {
    viewer.removeChild(viewer.firstChild);
  }
  // 自动滚动
  if (_logAutoScroll && !_logPaused) {
    viewer.scrollTop = viewer.scrollHeight;
  }
}

function renderAll() {
  var viewer = $("logViewer");
  if (!viewer) return;
  viewer.innerHTML = "";
  _logLines.forEach(function (r) { renderEntry(r); });
  updateLogCount();
}

function updateLogCount() {
  var el = $("logCount");
  if (el) el.textContent = _logLines.length + " 条";
}

function updateLogStatus(connected) {
  _logConnected = connected;
  var el = $("logStatus");
  if (!el) return;
  if (connected) {
    el.textContent = "● 已连接";
    el.style.color = "#4ade80";
  } else {
    el.textContent = "● 已断开";
    el.style.color = "#f87171";
  }
}

function nowTs() {
  return new Date().toLocaleTimeString("zh-CN");
}

// ===== 命令发送(结果插入统一终端) =====

function sendCommand() {
  var input = $("consoleInput");
  if (!input) return;
  var cmd = input.value.trim();
  if (!cmd) return;
  input.value = "";
  // 命令输入行
  addEntry({ _type: "cmd", _ts: nowTs(), _text: "> " + cmd });
  var execBtn = $("consoleExecBtn");
  if (execBtn) { execBtn.disabled = true; execBtn.textContent = "⏳ 执行中..."; }
  api("/console", { method: "POST", body: JSON.stringify({ command: cmd }) })
    .then(function (data) {
      if (execBtn) { execBtn.disabled = false; execBtn.textContent = "▶ 执行"; }
      if (!data.ok) {
        addEntry({ _type: "cmd-result", _ts: nowTs(), _ok: false, _text: data.message || "执行失败" });
      } else {
        var msg = data.statusMessage || "(无返回消息)";
        var code = data.statusCode !== undefined ? " [" + data.statusCode + "]" : "";
        addEntry({ _type: "cmd-result", _ts: nowTs(), _ok: true, _text: msg + code });
      }
    })
    .catch(function () {
      if (execBtn) { execBtn.disabled = false; execBtn.textContent = "▶ 执行"; }
      addEntry({ _type: "cmd-result", _ts: nowTs(), _ok: false, _text: "请求失败:网络错误或服务器未响应" });
    });
}

// ===== SSE 实时日志流 =====

function connectLogStream() {
  if (_logSSE) { _logSSE.close(); _logSSE = null; }
  // 先加载历史
  api("/logs/recent?limit=200").then(function (data) {
    if (data.ok && data.logs) {
      _logLines = data.logs;
      renderAll();
    }
  }).catch(function () {});
  // 建立 SSE 连接(EventSource 不支持自定义头,token 通过查询参数传递)
  var role = sessionStorage.getItem(ROLE_KEY) || "";
  var token = sessionStorage.getItem(TOKEN_KEY) || "";
  var url = "/api/logs/stream";
  if (role === "guest") {
    url += "?guest=1";
  } else if (token) {
    url += "?token=" + encodeURIComponent(token);
  }
  _logSSE = new EventSource(url);
  _logSSE.onmessage = function (e) {
    try {
      var record = JSON.parse(e.data);
      addEntry(record);
      updateLogStatus(true);
    } catch (err) {}
  };
  _logSSE.onerror = function () {
    updateLogStatus(false);
  };
  _logSSE.onopen = function () {
    updateLogStatus(true);
  };
}

// ===== 初始化 =====

requireAuth(function (role) {
  initSidebar("console", role);
  initTheme();
  // 访客隐藏命令输入
  if (role === "guest") {
    var cmdCard = $("consoleCmdCard");
    if (cmdCard) cmdCard.style.display = "none";
  }
  connectLogStream();
});

// 执行按钮
var execBtn = $("consoleExecBtn");
if (execBtn) execBtn.addEventListener("click", sendCommand);

// 回车发送
var input = $("consoleInput");
if (input) {
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendCommand();
    }
  });
  input.focus();
}

// ===== 控件 =====

// 级别过滤
var logFilterEl = $("logLevelFilter");
if (logFilterEl) {
  logFilterEl.addEventListener("change", function () {
    _logLevelFilter = this.value;
    renderAll();
  });
}

// 自动滚动
var autoScrollEl = $("logAutoScroll");
if (autoScrollEl) {
  autoScrollEl.addEventListener("change", function () {
    _logAutoScroll = this.checked;
    if (_logAutoScroll) {
      var viewer = $("logViewer");
      if (viewer) viewer.scrollTop = viewer.scrollHeight;
    }
  });
}

// 暂停/继续
var pauseBtn = $("logPauseBtn");
if (pauseBtn) {
  pauseBtn.addEventListener("click", function () {
    _logPaused = !_logPaused;
    this.textContent = _logPaused ? "▶ 继续" : "⏸ 暂停";
    this.className = _logPaused ? "btn btn-sm btn-primary" : "btn btn-sm";
  });
}

// 清空
var logClearBtn = $("logClearBtn");
if (logClearBtn) {
  logClearBtn.addEventListener("click", function () {
    _logLines = [];
    var viewer = $("logViewer");
    if (viewer) viewer.innerHTML = "";
    updateLogCount();
  });
}
