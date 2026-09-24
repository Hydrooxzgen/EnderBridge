// ===== 自动化任务计划前端逻辑 (Task Scheduler) =====
var _currentTasks = [];
var _currentLogs = [];
var _autoRefreshTimer = null;

function _formatDate(isoStr) {
  if (!isoStr) return "--";
  try {
    var d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    var pad = function(n) { return n < 10 ? "0" + n : n; };
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " +
      pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
  } catch (e) {
    return isoStr;
  }
}

function _getActionBadge(task) {
  var at = task.action_type || "command";
  if (at === "command") {
    var lines = (task.action_payload || "").split("\n").filter(function(l){ return l.trim(); });
    return '<span class="sched-badge" style="background:rgba(59,130,246,0.15);color:#38bdf8;border:1px solid rgba(59,130,246,0.3);">'
      + '🎮 指令 (' + lines.length + '条)</span>';
  }
  if (at === "broadcast") {
    var bt = task.broadcast_type || "chat";
    var btLabel = bt === "title" ? "大标题" : (bt === "actionbar" ? "动作栏" : "聊天");
    return '<span class="sched-badge" style="background:rgba(168,85,247,0.15);color:#c084fc;border:1px solid rgba(168,85,247,0.3);">'
      + '📢 广播 (' + btLabel + ')</span>';
  }
  if (at === "mcfunc") {
    return '<span class="sched-badge" style="background:rgba(234,179,8,0.15);color:#facc15;border:1px solid rgba(234,179,8,0.3);">'
      + '📜 MCFunc (' + escapeHtml(task.action_payload || "") + ')</span>';
  }
  if (at === "backup") {
    return '<span class="sched-badge" style="background:rgba(34,197,94,0.15);color:#4ade80;border:1px solid rgba(34,197,94,0.3);">'
      + '📦 自动备份</span>';
  }
  return '<span class="sched-badge badge-idle">' + escapeHtml(at) + '</span>';
}

function _getTriggerDesc(task) {
  var tt = task.trigger_type || "interval";
  if (tt === "cron") {
    return '<div style="font-family:monospace;font-size:12px;color:#38bdf8;">'
      + '📅 <code>' + escapeHtml(task.cron_expr || "") + '</code></div>';
  }
  var val = task.interval_value || 30;
  var unit = task.interval_unit || "m";
  var unitNames = { s: "秒", m: "分钟", h: "小时", d: "天" };
  return '<div style="font-size:12.5px;color:var(--text);">'
    + '⏱️ 每 ' + val + ' ' + (unitNames[unit] || unit) + '</div>';
}

function _getStatusBadge(task) {
  var st = task.last_status;
  if (st === "success") {
    return '<span class="sched-badge badge-success">✓ 成功</span>';
  }
  if (st === "skipped") {
    return '<span class="sched-badge badge-skipped" title="' + escapeHtml(task.last_message || "") + '">⚠ 已跳过</span>';
  }
  if (st === "failed") {
    return '<span class="sched-badge badge-danger badge-failed" title="' + escapeHtml(task.last_message || "") + '">✕ 失败</span>';
  }
  return '<span class="sched-badge badge-idle">待触发</span>';
}

function renderTasksTable() {
  var tbody = $("schedTasksBody");
  if (!tbody) return;

  if (!_currentTasks || _currentTasks.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="td-faint" style="text-align:center;padding:32px;">'
      + (typeof t === "function" ? t("scheduler.noTasks") : "暂无计划任务，点击上方按钮创建")
      + '</td></tr>';
    return;
  }

  var html = "";
  _currentTasks.forEach(function(task) {
    var isEnabled = !!task.enabled;
    var nextRun = task.next_run ? _formatDate(task.next_run) : "--";
    var lastRun = task.last_run ? _formatDate(task.last_run) : "--";

    html += '<tr data-task-id="' + task.id + '">'
      + '<td>'
      +   '<div style="font-weight:600;font-size:14px;color:var(--text);">' + escapeHtml(task.name || "") + '</div>'
      +   (task.description ? '<div style="font-size:12px;color:var(--text-faint);margin-top:2px;">' + escapeHtml(task.description) + '</div>' : '')
      + '</td>'
      + '<td>' + _getTriggerDesc(task) + '</td>'
      + '<td>' + _getActionBadge(task) + '</td>'
      + '<td style="font-size:12.5px;color:var(--text-dim);">' + nextRun + '</td>'
      + '<td style="font-size:12.5px;color:var(--text-dim);">' + lastRun + '</td>'
      + '<td>'
      +   '<div style="display:flex;align-items:center;gap:8px;">'
      +     '<label class="switch" title="切换启用状态">'
      +       '<input type="checkbox" class="task-toggle-btn" data-id="' + task.id + '"' + (isEnabled ? ' checked' : '') + ' />'
      +       '<span class="slider"></span>'
      +     '</label>'
      +     _getStatusBadge(task)
      +   '</div>'
      + '</td>'
      + '<td style="text-align:right;">'
      +   '<div class="row gap-10" style="justify-content:flex-end;">'
      +     '<button class="btn btn-sm btn-primary task-run-btn" data-id="' + task.id + '" title="立即执行一次">▶</button>'
      +     '<button class="btn btn-sm task-edit-btn" data-id="' + task.id + '" title="编辑">✏️</button>'
      +     '<button class="btn btn-sm btn-danger task-del-btn" data-id="' + task.id + '" title="删除">🗑️</button>'
      +   '</div>'
      + '</td>'
      + '</tr>';
  });

  tbody.innerHTML = html;
  bindTableEvents();
}

function updateStats() {
  var total = _currentTasks.length;
  var active = _currentTasks.filter(function(t) { return !!t.enabled; }).length;

  var totalExecs = _currentLogs.length;

  var soonest = null;
  _currentTasks.forEach(function(t) {
    if (t.enabled && t.next_run) {
      if (!soonest || t.next_run < soonest) {
        soonest = t.next_run;
      }
    }
  });

  if ($("statTotalTasks")) $("statTotalTasks").textContent = total;
  if ($("statActiveTasks")) $("statActiveTasks").textContent = active;
  if ($("statRunCount")) $("statRunCount").textContent = totalExecs;
  if ($("statNextRun")) $("statNextRun").textContent = soonest ? _formatDate(soonest) : "--";
}

function renderLogsTable() {
  var tbody = $("schedLogsBody");
  if (!tbody) return;

  if (!_currentLogs || _currentLogs.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="td-faint" style="text-align:center;padding:24px;">'
      + (typeof t === "function" ? t("scheduler.noLogs") : "暂无执行流水记录")
      + '</td></tr>';
    return;
  }

  var html = "";
  _currentLogs.forEach(function(l) {
    var st = l.status;
    var stBadge = st === "success"
      ? '<span class="sched-badge badge-success">✓ 成功</span>'
      : (st === "skipped"
        ? '<span class="sched-badge badge-skipped">⚠ 已跳过</span>'
        : '<span class="sched-badge badge-failed">✕ 失败</span>');

    var src = l.trigger_source === "manual"
      ? '<span style="color:#a855f7;">手动执行</span>'
      : '<span style="color:var(--text-dim);">自动定时</span>';

    html += '<tr>'
      + '<td style="font-size:12px;white-space:nowrap;color:var(--text-dim);">' + _formatDate(l.timestamp) + '</td>'
      + '<td style="font-weight:600;font-size:13px;">' + escapeHtml(l.task_name || "--") + '</td>'
      + '<td style="font-size:12px;">' + src + '</td>'
      + '<td style="font-size:12px;">' + escapeHtml(l.action_type || "") + '</td>'
      + '<td style="font-size:12px;color:var(--text-dim);">' + (l.cost_ms || 0) + ' ms</td>'
      + '<td>' + stBadge + '</td>'
      + '<td style="font-size:12px;color:var(--text-faint);max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + escapeHtml(l.output || l.message || "") + '">'
      +   escapeHtml(l.message || l.output || "--")
      + '</td>'
      + '</tr>';
  });

  tbody.innerHTML = html;
}

function loadTasks() {
  return api("/scheduler/tasks").then(function(res) {
    if (res.ok) {
      _currentTasks = res.tasks || [];
      renderTasksTable();
      updateStats();
    }
  }).catch(function(err) {
    toast((err && err.message) || "获取任务列表失败", "err");
  });
}

function loadLogs() {
  return api("/scheduler/logs").then(function(res) {
    if (res.ok) {
      _currentLogs = res.logs || [];
      renderLogsTable();
      updateStats();
    }
  }).catch(function() {});
}

function bindTableEvents() {
  // Toggle enable
  document.querySelectorAll(".task-toggle-btn").forEach(function(cb) {
    cb.addEventListener("change", function() {
      var id = cb.getAttribute("data-id");
      api("/scheduler/tasks/toggle", {
        method: "POST",
        body: JSON.stringify({ id: id })
      }).then(function(res) {
        if (res.ok) {
          toast(res.enabled ? "任务已启用" : "任务已暂停", "ok");
          loadTasks();
        }
      }).catch(function(err) {
        cb.checked = !cb.checked;
        toast((err && err.message) || "切换状态失败", "err");
      });
    });
  });

  // Run now
  document.querySelectorAll(".task-run-btn").forEach(function(btn) {
    btn.addEventListener("click", function() {
      var id = btn.getAttribute("data-id");
      btn.disabled = true;
      toast("正在触发任务...", "ok", 2000);
      api("/scheduler/tasks/run", {
        method: "POST",
        body: JSON.stringify({ id: id })
      }).then(function(res) {
        btn.disabled = false;
        if (res.ok) {
          var r = res.result || {};
          if (r.status === "success") {
            toast("执行成功: " + (r.message || "OK"), "ok");
          } else if (r.status === "skipped") {
            toast("任务已跳过: " + (r.message || "无客户端连接"), "warn");
          } else {
            toast("执行失败: " + (r.message || "异常"), "err");
          }
          loadTasks();
          loadLogs();
        }
      }).catch(function(err) {
        btn.disabled = false;
        toast((err && err.message) || "触发任务失败", "err");
      });
    });
  });

  // Edit task
  document.querySelectorAll(".task-edit-btn").forEach(function(btn) {
    btn.addEventListener("click", function() {
      var id = btn.getAttribute("data-id");
      var task = _currentTasks.find(function(t) { return t.id === id; });
      if (task) openTaskModal(task);
    });
  });

  // Delete task
  document.querySelectorAll(".task-del-btn").forEach(function(btn) {
    btn.addEventListener("click", function() {
      var id = btn.getAttribute("data-id");
      var task = _currentTasks.find(function(t) { return t.id === id; });
      var name = task ? task.name : id;
      if (!confirm("确定要删除计划任务「" + name + "」吗？")) return;

      api("/scheduler/tasks", {
        method: "DELETE",
        body: JSON.stringify({ id: id })
      }).then(function(res) {
        if (res.ok) {
          toast("任务已删除", "ok");
          loadTasks();
        }
      }).catch(function(err) {
        toast((err && err.message) || "删除失败", "err");
      });
    });
  });
}

// ===== 模态框逻辑 =====
function openTaskModal(task) {
  var isEdit = !!task;
  $("taskId").value = isEdit ? task.id : "";
  $("taskModalTitle").textContent = isEdit ? "✏️ 编辑定时任务" : "➕ 新建定时任务";
  $("taskName").value = isEdit ? (task.name || "") : "";
  $("taskDesc").value = isEdit ? (task.description || "") : "";
  $("taskEnabled").checked = isEdit ? (task.enabled !== false) : true;
  $("skipIfOffline").checked = isEdit ? (task.skip_if_no_client !== false) : true;

  // 触发方式
  var ttype = isEdit ? (task.trigger_type || "interval") : "interval";
  var radios = document.getElementsByName("triggerType");
  for (var i = 0; i < radios.length; i++) {
    radios[i].checked = (radios[i].value === ttype);
  }
  updateTriggerPanels(ttype);

  $("intervalValue").value = isEdit ? (task.interval_value || 30) : 30;
  $("intervalUnit").value = isEdit ? (task.interval_unit || "m") : "m";
  $("cronExpr").value = isEdit ? (task.cron_expr || "") : "0 4 * * *";

  // 动作类型
  var atype = isEdit ? (task.action_type || "command") : "command";
  $("actionType").value = atype;
  updateActionPanels(atype);

  $("cmdPayload").value = (isEdit && atype === "command") ? (task.action_payload || "") : "";
  $("broadcastPayload").value = (isEdit && atype === "broadcast") ? (task.action_payload || "") : "";
  $("broadcastType").value = isEdit ? (task.broadcast_type || "chat") : "chat";
  $("mcfuncPayload").value = (isEdit && atype === "mcfunc") ? (task.action_payload || "") : "";

  $("taskModal").style.display = "flex";
}

function closeTaskModal() {
  $("taskModal").style.display = "none";
}

function updateTriggerPanels(type) {
  $("panelInterval").style.display = (type === "interval") ? "flex" : "none";
  $("panelCron").style.display = (type === "cron") ? "block" : "none";
}

function updateActionPanels(type) {
  $("panelActCommand").style.display = (type === "command") ? "block" : "none";
  $("panelActBroadcast").style.display = (type === "broadcast") ? "block" : "none";
  $("panelActMcfunc").style.display = (type === "mcfunc") ? "block" : "none";
  $("panelActBackup").style.display = (type === "backup") ? "block" : "none";
}

function initModalEvents() {
  $("schedNewTaskBtn").addEventListener("click", function() {
    openTaskModal(null);
  });

  $("taskModalCloseBtn").addEventListener("click", closeTaskModal);
  $("taskCancelBtn").addEventListener("click", closeTaskModal);

  // 触发模式单选切换
  document.getElementsByName("triggerType").forEach(function(r) {
    r.addEventListener("change", function() {
      updateTriggerPanels(this.value);
    });
  });

  // 动作类型下拉切换
  $("actionType").addEventListener("change", function() {
    updateActionPanels(this.value);
  });

  // Cron 快捷预设点击填充
  document.querySelectorAll(".preset-tag[data-cron]").forEach(function(tag) {
    tag.addEventListener("click", function() {
      var c = tag.getAttribute("data-cron");
      $("cronExpr").value = c;
    });
  });

  // 表单提交
  $("taskForm").addEventListener("submit", function(e) {
    e.preventDefault();

    var id = $("taskId").value.trim();
    var name = $("taskName").value.trim();
    var desc = $("taskDesc").value.trim();
    var enabled = $("taskEnabled").checked;
    var skipIfOffline = $("skipIfOffline").checked;

    var radios = document.getElementsByName("triggerType");
    var ttype = "interval";
    for (var i = 0; i < radios.length; i++) {
      if (radios[i].checked) { ttype = radios[i].value; break; }
    }

    var intervalVal = parseInt($("intervalValue").value, 10) || 30;
    var intervalUnit = $("intervalUnit").value;
    var cronExpr = $("cronExpr").value.trim();

    var actionType = $("actionType").value;
    var actionPayload = "";
    var broadcastType = "chat";

    if (actionType === "command") {
      actionPayload = $("cmdPayload").value.trim();
      if (!actionPayload) {
        toast("请填写待执行的指令", "err");
        return;
      }
    } else if (actionType === "broadcast") {
      actionPayload = $("broadcastPayload").value.trim();
      broadcastType = $("broadcastType").value;
      if (!actionPayload) {
        toast("请填写广播内容", "err");
        return;
      }
    } else if (actionType === "mcfunc") {
      actionPayload = $("mcfuncPayload").value.trim();
      if (!actionPayload) {
        toast("请填写 MCFunc 脚本名称", "err");
        return;
      }
    } else if (actionType === "backup") {
      actionPayload = "auto_backup";
    }

    if (ttype === "cron" && !cronExpr) {
      toast("请填写 Cron 表达式", "err");
      return;
    }

    var payload = {
      name: name,
      description: desc,
      enabled: enabled,
      trigger_type: ttype,
      interval_value: intervalVal,
      interval_unit: intervalUnit,
      cron_expr: cronExpr,
      action_type: actionType,
      action_payload: actionPayload,
      broadcast_type: broadcastType,
      skip_if_no_client: skipIfOffline,
    };

    var isEdit = !!id;
    var method = isEdit ? "PUT" : "POST";
    if (isEdit) payload.id = id;

    $("taskSaveBtn").disabled = true;
    api("/scheduler/tasks", {
      method: method,
      body: JSON.stringify(payload)
    }).then(function(res) {
      $("taskSaveBtn").disabled = false;
      if (res.ok) {
        toast(isEdit ? "任务更新成功" : "任务创建成功", "ok");
        closeTaskModal();
        loadTasks();
      }
    }).catch(function(err) {
      $("taskSaveBtn").disabled = false;
      toast((err && err.message) || "保存失败", "err");
    });
  });
}

// ===== 初始化入口 =====
requireAuth(function(role) {
  initSidebar("scheduler", role);

  if ($("schedRefreshBtn")) {
    $("schedRefreshBtn").addEventListener("click", function() {
      loadTasks();
      loadLogs();
      toast("已刷新", "ok", 1500);
    });
  }

  if ($("schedLogsRefreshBtn")) {
    $("schedLogsRefreshBtn").addEventListener("click", function() {
      loadLogs();
      toast("已刷新流水", "ok", 1500);
    });
  }

  initModalEvents();
  loadTasks();
  loadLogs();

  // 10 秒自动轮询状态与流水
  _autoRefreshTimer = setInterval(function() {
    loadTasks();
    loadLogs();
  }, 10000);
});

