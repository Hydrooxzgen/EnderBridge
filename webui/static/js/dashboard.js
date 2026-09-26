// ===== 仪表盘页面逻辑 =====
requireAuth(function (role) {
  initSidebar("dashboard", role);
  initTheme();
  refreshStatus();
  initPerformanceMonitor();
  loadReleaseNotes();
  checkAttackAlert();
});

var _attackToastShown = false;
/** 检查是否有被封禁的 IP (攻击警报) */
function checkAttackAlert() {
  if (!hasPermission("banlist")) return;
  api("/banlist").then(function (data) {
    if (!data.ok) return;
    var autoCount = data.autoBanCount || 0;
    if (autoCount > 0 && !_attackToastShown) {
      _attackToastShown = true;
      toast("🚨 服务器正遭受攻击 — " + autoCount + " 个 IP 被自动封禁", "warn", 6000);
    }
  }).catch(function () {});
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

// ===== 实时性能监控与 Canvas 图表 =====
var _perfHistory = [];
var _perfChannel = "all"; // "all" | "cpu" | "mem" | "traffic"
var _perfTimer = null;
var _perfMousePos = null;

function initPerformanceMonitor() {
  var canvas = $("perfCanvas");
  if (!canvas) return;

  // 选项卡切换
  var tabs = document.querySelectorAll("#perfTabGroup .chip-tab");
  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      tabs.forEach(function (t) { t.classList.remove("active"); });
      this.classList.add("active");
      _perfChannel = this.getAttribute("data-channel") || "all";
      renderPerformanceChart();
    });
  });

  // 鼠标悬停交互 Tooltip
  canvas.addEventListener("mousemove", function (e) {
    var rect = canvas.getBoundingClientRect();
    _perfMousePos = {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    };
    renderPerformanceChart();
  });

  canvas.addEventListener("mouseleave", function () {
    _perfMousePos = null;
    var tooltip = $("perfTooltip");
    if (tooltip) tooltip.style.display = "none";
    renderPerformanceChart();
  });

  // 窗口缩放自适应
  window.addEventListener("resize", function () {
    renderPerformanceChart();
  });

  // 首次拉取完整历史数据
  fetchPerformance();

  // 每 1000ms 定时采样刷新
  if (_perfTimer) clearInterval(_perfTimer);
  _perfTimer = setInterval(fetchPerformance, 1000);
}

function fetchPerformance() {
  api("/performance").then(function (res) {
    if (!res.ok) return;
    if (res.history && Array.isArray(res.history)) {
      _perfHistory = res.history;
    } else if (res.current) {
      _perfHistory.push(res.current);
      if (_perfHistory.length > 60) _perfHistory.shift();
    }
    updateMiniStats(res.current || (_perfHistory.length ? _perfHistory[_perfHistory.length - 1] : null));
    renderPerformanceChart();
  }).catch(function () {});
}

function updateMiniStats(cur) {
  if (!cur) return;
  var sysCpuEl = $("perfSysCpuVal");
  if (sysCpuEl) sysCpuEl.textContent = (cur.cpu || 0).toFixed(1) + " %";

  var procCpuEl = $("perfProcCpuSub");
  if (procCpuEl) procCpuEl.textContent = t("dash.tooltipProcCpu") + ": " + (cur.proc_cpu || 0).toFixed(1) + "%";

  var procMemEl = $("perfProcMemVal");
  if (procMemEl) procMemEl.textContent = (cur.proc_mem_mb || 0).toFixed(1) + " MB";

  var sysMemEl = $("perfSysMemSub");
  if (sysMemEl) sysMemEl.textContent = t("dash.tooltipSysMem") + ": " + (cur.mem_percent || 0).toFixed(1) + "%";

  var msgRateEl = $("perfMsgRateVal");
  if (msgRateEl) msgRateEl.textContent = (cur.msg_rate || 0).toFixed(0) + " msg/s";

  var clientsEl = $("perfClientsSub");
  if (clientsEl) clientsEl.textContent = t("dash.tooltipClients") + ": " + (cur.clients || 0);
}

function renderPerformanceChart() {
  var canvas = $("perfCanvas");
  if (!canvas) return;
  var ctx = canvas.getContext("2d");
  if (!ctx) return;

  var rect = canvas.getBoundingClientRect();
  var dpr = window.devicePixelRatio || 1;
  var w = rect.width;
  var h = rect.height;
  if (w <= 0 || h <= 0) return;

  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  if (ctx.resetTransform) ctx.resetTransform();
  ctx.scale(dpr, dpr);

  var isLight = document.documentElement.getAttribute("data-theme") === "light";
  var gridColor = isLight ? "rgba(100, 116, 139, 0.12)" : "rgba(148, 163, 184, 0.12)";
  var textColor = isLight ? "#64748b" : "#94a3b8";

  // 边距
  var padLeft = 46;
  var padRight = 16;
  var padTop = 16;
  var padBottom = 26;
  var plotW = w - padLeft - padRight;
  var plotH = h - padTop - padBottom;

  ctx.clearRect(0, 0, w, h);

  // 历史采样点数据 (取最近 60 个点)
  var points = _perfHistory.slice(-60);
  if (points.length < 2) {
    ctx.fillStyle = textColor;
    ctx.font = "12px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("正在收集性能指标时序数据...", w / 2, h / 2);
    return;
  }

  // 确定 Y 轴最大值
  var maxY = 100;
  if (_perfChannel === "cpu") {
    maxY = 100;
  } else if (_perfChannel === "mem") {
    var maxMem = 0;
    points.forEach(function (p) {
      if (p.proc_mem_mb > maxMem) maxMem = p.proc_mem_mb;
      if (p.mem_percent > maxMem) maxMem = p.mem_percent;
    });
    maxY = Math.max(100, Math.ceil((maxMem * 1.15) / 20) * 20);
  } else if (_perfChannel === "traffic") {
    var maxRate = 0;
    points.forEach(function (p) {
      if (p.msg_rate > maxRate) maxRate = p.msg_rate;
    });
    maxY = Math.max(10, Math.ceil((maxRate * 1.25) / 5) * 5);
  } else {
    // all: 0~100% 统一标准刻度
    maxY = 100;
  }

  // 1. 绘制水平网格辅助线与 Y 轴标尺
  ctx.lineWidth = 1;
  ctx.strokeStyle = gridColor;
  ctx.fillStyle = textColor;
  ctx.font = "10px monospace";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";

  var gridSteps = 4;
  for (var i = 0; i <= gridSteps; i++) {
    var ratio = i / gridSteps;
    var y = padTop + plotH * (1 - ratio);
    var labelVal = Math.round(maxY * ratio);
    var unit = (_perfChannel === "traffic") ? "" : (_perfChannel === "mem" && maxY > 100 ? "M" : "%");

    ctx.beginPath();
    ctx.moveTo(padLeft, y);
    ctx.lineTo(padLeft + plotW, y);
    ctx.stroke();

    ctx.fillText(labelVal + unit, padLeft - 6, y);
  }

  // 2. 绘制时间 X 轴标尺 (-60s, -45s, -30s, -15s, 现在)
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  var timeMarks = [
    { frac: 0.0, text: "-60s" },
    { frac: 0.25, text: "-45s" },
    { frac: 0.5, text: "-30s" },
    { frac: 0.75, text: "-15s" },
    { frac: 1.0, text: "现在" },
  ];
  timeMarks.forEach(function (tm) {
    var x = padLeft + plotW * tm.frac;
    ctx.fillText(tm.text, x, padTop + plotH + 6);
  });

  // 绘制单条平滑贝塞尔曲线
  function drawSpline(valExtractor, strokeColor, fillColor) {
    if (!points.length) return [];
    var coords = [];
    var n = points.length;

    for (var idx = 0; idx < n; idx++) {
      var xFrac = (n <= 1) ? 1.0 : (1.0 - (n - 1 - idx) / 59);
      if (xFrac < 0) xFrac = 0;
      var x = padLeft + plotW * xFrac;
      var val = valExtractor(points[idx]) || 0;
      var yRatio = Math.max(0, Math.min(1, val / maxY));
      var y = padTop + plotH * (1 - yRatio);
      coords.push({ x: x, y: y, val: val, raw: points[idx] });
    }

    // 渐变面积填充
    if (fillColor && coords.length > 1) {
      ctx.save();
      var grad = ctx.createLinearGradient(0, padTop, 0, padTop + plotH);
      grad.addColorStop(0, fillColor);
      grad.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.moveTo(coords[0].x, padTop + plotH);
      ctx.lineTo(coords[0].x, coords[0].y);

      for (var k = 1; k < coords.length; k++) {
        var prev = coords[k - 1];
        var cur = coords[k];
        var mx = (prev.x + cur.x) / 2;
        var my = (prev.y + cur.y) / 2;
        ctx.quadraticCurveTo(prev.x, prev.y, mx, my);
      }
      ctx.lineTo(coords[coords.length - 1].x, coords[coords.length - 1].y);
      ctx.lineTo(coords[coords.length - 1].x, padTop + plotH);
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    }

    // 绘制主曲线
    ctx.save();
    ctx.beginPath();
    ctx.lineWidth = 2;
    ctx.strokeStyle = strokeColor;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.moveTo(coords[0].x, coords[0].y);

    for (var j = 1; j < coords.length; j++) {
      var prev = coords[j - 1];
      var cur = coords[j];
      var mx = (prev.x + cur.x) / 2;
      var my = (prev.y + cur.y) / 2;
      ctx.quadraticCurveTo(prev.x, prev.y, mx, my);
    }
    ctx.lineTo(coords[coords.length - 1].x, coords[coords.length - 1].y);
    ctx.stroke();

    // 最新点高亮圆点
    var lastPt = coords[coords.length - 1];
    ctx.fillStyle = strokeColor;
    ctx.beginPath();
    ctx.arc(lastPt.x, lastPt.y, 3.5, 0, Math.PI * 2);
    ctx.fill();

    ctx.restore();
    return coords;
  }

  // 3. 根据所选通道渲染曲线
  var cpuCoords = [];
  var memCoords = [];
  var trafficCoords = [];

  if (_perfChannel === "all") {
    cpuCoords = drawSpline(function (p) { return p.cpu; }, "#38bdf8", "rgba(56, 189, 248, 0.22)");
    memCoords = drawSpline(function (p) { return p.mem_percent; }, "#a855f7", "rgba(168, 85, 247, 0.15)");
    trafficCoords = drawSpline(function (p) { return p.msg_rate; }, "#10b981", null);
  } else if (_perfChannel === "cpu") {
    cpuCoords = drawSpline(function (p) { return p.cpu; }, "#38bdf8", "rgba(56, 189, 248, 0.25)");
    drawSpline(function (p) { return p.proc_cpu; }, "#06b6d4", null);
  } else if (_perfChannel === "mem") {
    memCoords = drawSpline(function (p) { return p.proc_mem_mb; }, "#a855f7", "rgba(168, 85, 247, 0.25)");
    drawSpline(function (p) { return p.mem_percent; }, "#c084fc", null);
  } else if (_perfChannel === "traffic") {
    trafficCoords = drawSpline(function (p) { return p.msg_rate; }, "#10b981", "rgba(16, 185, 129, 0.25)");
  }

  // 4. 鼠标悬停十字准星与 Tooltip
  var tooltip = $("perfTooltip");
  var activeCoords = cpuCoords.length ? cpuCoords : (memCoords.length ? memCoords : trafficCoords);
  if (_perfMousePos && activeCoords.length > 0) {
    var mx = _perfMousePos.x;
    if (mx >= padLeft && mx <= padLeft + plotW) {
      var closest = activeCoords[0];
      var minDiff = Math.abs(mx - closest.x);
      for (var c = 1; c < activeCoords.length; c++) {
        var diff = Math.abs(mx - activeCoords[c].x);
        if (diff < minDiff) {
          minDiff = diff;
          closest = activeCoords[c];
        }
      }

      if (closest) {
        // 画十字垂线
        ctx.save();
        ctx.strokeStyle = isLight ? "rgba(100, 116, 139, 0.4)" : "rgba(255, 255, 255, 0.35)";
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(closest.x, padTop);
        ctx.lineTo(closest.x, padTop + plotH);
        ctx.stroke();

        // 焦点圆环
        ctx.setLineDash([]);
        ctx.strokeStyle = "#fff";
        ctx.fillStyle = "#38bdf8";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(closest.x, closest.y, 4.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.restore();

        // Tooltip 内容与定位
        if (tooltip) {
          var pData = closest.raw;
          var timeStr = pData.time ? new Date(pData.time * 1000).toLocaleTimeString() : "";
          tooltip.innerHTML =
            '<div style="font-weight:700;margin-bottom:4px;color:var(--text);border-bottom:1px solid rgba(148,163,184,0.2);padding-bottom:2px;">⏱ ' + timeStr + '</div>' +
            '<div style="color:#38bdf8;">' + t("dash.tooltipSysCpu") + ': <strong>' + (pData.cpu || 0).toFixed(1) + '%</strong> (' + t("dash.tooltipProcCpu") + ': ' + (pData.proc_cpu || 0).toFixed(1) + '%)</div>' +
            '<div style="color:#a855f7;">' + t("dash.tooltipProcMem") + ': <strong>' + (pData.proc_mem_mb || 0).toFixed(1) + ' MB</strong> (' + t("dash.tooltipSysMem") + ': ' + (pData.mem_percent || 0).toFixed(1) + '%)</div>' +
            '<div style="color:#10b981;">' + t("dash.tooltipMsgRate") + ': <strong>' + (pData.msg_rate || 0).toFixed(0) + ' msg/s</strong> (' + t("dash.tooltipClients") + ': ' + (pData.clients || 0) + ')</div>';

          tooltip.style.display = "block";
          var tipW = 200;
          var leftPos = closest.x + 14;
          if (leftPos + tipW > w) leftPos = closest.x - tipW - 14;
          tooltip.style.left = Math.max(10, leftPos) + "px";
          tooltip.style.top = Math.max(10, Math.min(h - 90, closest.y - 30)) + "px";
        }
      }
    } else {
      if (tooltip) tooltip.style.display = "none";
    }
  } else {
    if (tooltip) tooltip.style.display = "none";
  }
}

