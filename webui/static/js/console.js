// ===== 控制台页面逻辑 =====
var _consoleLines = [];
var MAX_LINES = 500;

function appendOutput(text, type) {
  var ts = new Date().toLocaleTimeString("zh-CN");
  var prefix = type === "cmd" ? "> " : type === "err" ? "✗ " : "";
  var color = type === "cmd" ? "#e2e8f0" : type === "err" ? "#f87171" : type === "ok" ? "#4ade80" : "#94a3b8";
  _consoleLines.push({ text: ts + " " + prefix + text, color: color });
  if (_consoleLines.length > MAX_LINES) _consoleLines.shift();
  renderOutput();
}

function renderOutput() {
  var el = $("consoleOutput");
  if (!el) return;
  el.innerHTML = _consoleLines.map(function (l) {
    return '<div style="color:' + l.color + ';">' + escapeHtml(l.text) + '</div>';
  }).join("");
  el.scrollTop = el.scrollHeight;
}

function sendCommand() {
  var input = $("consoleInput");
  if (!input) return;
  var cmd = input.value.trim();
  if (!cmd) return;
  input.value = "";
  appendOutput(cmd, "cmd");
  var execBtn = $("consoleExecBtn");
  if (execBtn) { execBtn.disabled = true; execBtn.textContent = "⏳ 执行中..."; }
  api("/console", { method: "POST", body: JSON.stringify({ command: cmd }) })
    .then(function (data) {
      if (execBtn) { execBtn.disabled = false; execBtn.textContent = "▶ 执行"; }
      if (!data.ok) {
        appendOutput(data.message || "执行失败", "err");
      } else {
        var msg = data.statusMessage || "(无返回消息)";
        var code = data.statusCode !== undefined ? " [" + data.statusCode + "]" : "";
        appendOutput(msg + code, "ok");
      }
    })
    .catch(function () {
      if (execBtn) { execBtn.disabled = false; execBtn.textContent = "▶ 执行"; }
      appendOutput("请求失败:网络错误或服务器未响应", "err");
    });
}

requireAuth(function (role) {
  initSidebar("console", role);
  appendOutput("控制台已就绪。输入命令后按回车或点击执行。", "info");
  // 如果是访客,隐藏输入区域
  if (role === "guest") {
    var input = $("consoleInput");
    if (input) { input.disabled = true; input.placeholder = "访客模式:无权发送命令"; }
    var btn = $("consoleExecBtn");
    if (btn) btn.disabled = true;
  }
});

// 执行按钮
var execBtn = $("consoleExecBtn");
if (execBtn) {
  execBtn.addEventListener("click", sendCommand);
}

// 回车发送
var input = $("consoleInput");
if (input) {
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendCommand();
    }
  });
  // 自动聚焦
  input.focus();
}

// 清空按钮
var clearBtn = $("consoleClearBtn");
if (clearBtn) {
  clearBtn.addEventListener("click", function () {
    _consoleLines = [];
    renderOutput();
  });
}
