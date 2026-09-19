// ===== 控制台页面逻辑(统一终端视图) =====
var _logLines = [];
var MAX_LOG_LINES = 1000;
var _logPaused = false;
var _logWS = null;
var _logSSE = null;
var _wsRetryCount = 0;
var _wsRetryTimer = null;
var _pendingCommands = {};
var _logAutoScroll = true;
var _logLevelFilter = "all";
var _logConnected = false;

var LOG_LEVEL_ORDER = { debug: 0, info: 1, warning: 2, error: 3 };

// ===== 命令历史记录 (↑ / ↓ 方向键切换) =====
var CMD_HISTORY_KEY = "enderbridge_cmd_history";
var MAX_CMD_HISTORY = 50;
var _cmdHistory = [];
var _historyIndex = -1;
var _tempInput = "";

function _loadCmdHistory() {
  try {
    var data = localStorage.getItem(CMD_HISTORY_KEY);
    if (data) {
      var parsed = JSON.parse(data);
      if (Array.isArray(parsed)) _cmdHistory = parsed;
    }
  } catch (e) {
    _cmdHistory = [];
  }
}

function _saveCmdHistory(cmd) {
  if (!cmd) return;
  var idx = _cmdHistory.lastIndexOf(cmd);
  if (idx !== -1) {
    _cmdHistory.splice(idx, 1);
  }
  _cmdHistory.push(cmd);
  if (_cmdHistory.length > MAX_CMD_HISTORY) {
    _cmdHistory.shift();
  }
  try {
    localStorage.setItem(CMD_HISTORY_KEY, JSON.stringify(_cmdHistory));
  } catch (e) {}
  _historyIndex = -1;
  _tempInput = "";
}

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
  if (el) el.textContent = _logLines.length + t("console.countSuffix");
}

function updateLogStatus(connected, mode) {
  _logConnected = connected;
  var el = $("logStatus");
  if (!el) return;
  if (connected) {
    if (mode === "ws") {
      el.textContent = t("console.connectedWs");
      el.style.color = "#4ade80";
    } else if (mode === "sse") {
      el.textContent = t("console.connectedSse");
      el.style.color = "#38bdf8";
    } else {
      el.textContent = t("console.connected");
      el.style.color = "#4ade80";
    }
  } else {
    if (mode === "reconnecting") {
      el.textContent = t("console.reconnecting");
      el.style.color = "#fbbf24";
    } else {
      el.textContent = t("console.disconnected");
      el.style.color = "#f87171";
    }
  }
}

function nowTs() {
  return new Date().toLocaleTimeString("zh-CN");
}

// ===== 命令发送(优先 WebSocket，失败回退 HTTP POST) =====

function _handleCmdResult(data) {
  var reqId = data.id;
  var callback = _pendingCommands[reqId];
  if (callback) {
    delete _pendingCommands[reqId];
    if (callback.timer) clearTimeout(callback.timer);
    callback.fn(data);
  } else {
    var ok = data.ok !== false;
    var msg = data.statusMessage || (ok ? t("console.noReturn") : (data.message || t("console.execFail")));
    var code = data.statusCode !== undefined ? " [" + data.statusCode + "]" : "";
    addEntry({ _type: "cmd-result", _ts: nowTs(), _ok: ok, _text: msg + code });
  }
}

function sendCommand() {
  var input = $("consoleInput");
  if (!input) return;
  var cmd = input.value.trim();
  if (!cmd) return;
  _saveCmdHistory(cmd);
  input.value = "";
  // 命令输入行
  addEntry({ _type: "cmd", _ts: nowTs(), _text: "> " + cmd });
  var execBtn = $("consoleExecBtn");
  if (execBtn) { execBtn.disabled = true; execBtn.textContent = t("console.execing"); }

  function onDone() {
    if (execBtn) { execBtn.disabled = false; execBtn.textContent = t("console.exec"); }
  }

  // 1) 优先使用已连接的 WebSocket 通道
  if (_logWS && _logWS.readyState === WebSocket.OPEN) {
    var reqId = "c_" + Date.now() + "_" + Math.random().toString(36).substr(2, 5);
    var timer = setTimeout(function () {
      if (_pendingCommands[reqId]) {
        delete _pendingCommands[reqId];
        onDone();
        addEntry({ _type: "cmd-result", _ts: nowTs(), _ok: false, _text: t("console.netFail") });
      }
    }, 15000);

    _pendingCommands[reqId] = {
      timer: timer,
      fn: function (data) {
        onDone();
        if (!data.ok) {
          addEntry({ _type: "cmd-result", _ts: nowTs(), _ok: false, _text: data.message || t("console.execFail") });
        } else {
          var msg = data.statusMessage || t("console.noReturn");
          var code = data.statusCode !== undefined ? " [" + data.statusCode + "]" : "";
          addEntry({ _type: "cmd-result", _ts: nowTs(), _ok: true, _text: msg + code });
        }
      }
    };

    try {
      _logWS.send(JSON.stringify({ type: "command", command: cmd, id: reqId }));
      return;
    } catch (e) {
      delete _pendingCommands[reqId];
      clearTimeout(timer);
    }
  }

  // 2) 回退 HTTP POST /api/console
  api("/console", { method: "POST", body: JSON.stringify({ command: cmd }) })
    .then(function (data) {
      onDone();
      if (!data.ok) {
        addEntry({ _type: "cmd-result", _ts: nowTs(), _ok: false, _text: data.message || t("console.execFail") });
      } else {
        var msg = data.statusMessage || t("console.noReturn");
        var code = data.statusCode !== undefined ? " [" + data.statusCode + "]" : "";
        addEntry({ _type: "cmd-result", _ts: nowTs(), _ok: true, _text: msg + code });
      }
    })
    .catch(function () {
      onDone();
      addEntry({ _type: "cmd-result", _ts: nowTs(), _ok: false, _text: t("console.netFail") });
    });
}

// ===== WebSocket 实时推流 (含 SSE 自动降级) =====

function connectLogStream() {
  if (_logWS) {
    _logWS.onclose = null;
    _logWS.onerror = null;
    _logWS.close();
    _logWS = null;
  }
  if (_logSSE) {
    _logSSE.close();
    _logSSE = null;
  }
  if (_wsRetryTimer) {
    clearTimeout(_wsRetryTimer);
    _wsRetryTimer = null;
  }

  var role = sessionStorage.getItem(ROLE_KEY) || "";
  var token = sessionStorage.getItem(TOKEN_KEY) || "";
  var q = "";
  if (role === "guest") {
    q = "?guest=1";
  } else if (token) {
    q = "?token=" + encodeURIComponent(token);
  }

  // 若支持 WebSocket 且未超重试上限，优先使用 WebSocket
  if (window.WebSocket && _wsRetryCount < 3) {
    var proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    var wsUrl = proto + "//" + window.location.host + "/api/ws/console" + q;

    try {
      updateLogStatus(false, "reconnecting");
      _logWS = new WebSocket(wsUrl);

      _logWS.onopen = function () {
        _wsRetryCount = 0;
        updateLogStatus(true, "ws");
      };

      _logWS.onmessage = function (e) {
        try {
          var data = JSON.parse(e.data);
          if (data.type === "history" && Array.isArray(data.logs)) {
            _logLines = data.logs;
            renderAll();
          } else if (data.type === "log" && data.record) {
            addEntry(data.record);
          } else if (data.type === "cmd-result") {
            _handleCmdResult(data);
          } else if (data.level && data.message) {
            addEntry(data);
          }
        } catch (err) {}
      };

      _logWS.onerror = function () {};

      _logWS.onclose = function () {
        _logWS = null;
        _wsRetryCount++;
        if (_wsRetryCount >= 3) {
          // 连续失败 3 次，无缝降级到 SSE
          _fallbackToSSE(q);
        } else {
          updateLogStatus(false, "reconnecting");
          var delay = Math.min(2000 * Math.pow(2, _wsRetryCount - 1), 8000);
          _wsRetryTimer = setTimeout(connectLogStream, delay);
        }
      };
      return;
    } catch (e) {
      // 实例化异常直接降级
    }
  }

  _fallbackToSSE(q);
}

function _fallbackToSSE(q) {
  if (_logSSE) { _logSSE.close(); _logSSE = null; }
  // 加载最近历史
  api("/logs/recent?limit=200").then(function (data) {
    if (data.ok && data.logs) {
      _logLines = data.logs;
      renderAll();
    }
  }).catch(function () {});

  var url = "/api/logs/stream" + q;
  _logSSE = new EventSource(url);
  _logSSE.onmessage = function (e) {
    try {
      var record = JSON.parse(e.data);
      addEntry(record);
      updateLogStatus(true, "sse");
    } catch (err) {}
  };
  _logSSE.onerror = function () {
    updateLogStatus(false);
  };
  _logSSE.onopen = function () {
    updateLogStatus(true, "sse");
  };
}

// ===== 初始化 =====

requireAuth(function (role) {
  initSidebar("console", role);
  initTheme();
  initLang();
  _loadCmdHistory();
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

// 回车发送与历史命令切换 (↑ / ↓)
var input = $("consoleInput");
if (input) {
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendCommand();
    } else if (e.key === "ArrowUp") {
      if (!_cmdHistory.length) return;
      e.preventDefault();
      if (_historyIndex === -1 || _historyIndex >= _cmdHistory.length) {
        _tempInput = input.value;
        _historyIndex = _cmdHistory.length - 1;
      } else if (_historyIndex > 0) {
        _historyIndex--;
      }
      input.value = _cmdHistory[_historyIndex] || "";
      input.selectionStart = input.selectionEnd = input.value.length;
    } else if (e.key === "ArrowDown") {
      if (_historyIndex === -1 || _historyIndex >= _cmdHistory.length) return;
      e.preventDefault();
      _historyIndex++;
      if (_historyIndex >= _cmdHistory.length) {
        _historyIndex = -1;
        input.value = _tempInput;
      } else {
        input.value = _cmdHistory[_historyIndex] || "";
      }
      input.selectionStart = input.selectionEnd = input.value.length;
    } else if (e.key === "Escape") {
      if (_historyIndex !== -1) {
        _historyIndex = -1;
        input.value = _tempInput;
        input.selectionStart = input.selectionEnd = input.value.length;
      }
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
    this.textContent = _logPaused ? t("console.resume") : t("console.pause");
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
