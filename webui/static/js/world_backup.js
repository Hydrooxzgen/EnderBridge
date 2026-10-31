// webui/static/js/world_backup.js — 世界存档备份与快照 WebUI 管理脚本

var _allSnapshots = [];
var _allWorlds = [];

function initWorldBackupPage() {
  initSidebar("world_backup");

  $("wbRefreshBtn").addEventListener("click", function () {
    loadSnapshots();
    loadWorlds();
    loadConfig();
    toast("已刷新数据", "ok");
  });

  $("wbCreateBtn").addEventListener("click", handleCreateSnapshot);
  $("cfgSaveBtn").addEventListener("click", handleSaveConfig);

  $("wbSearchInput").addEventListener("input", function () {
    renderSnapshotsTable(_allSnapshots);
  });

  loadSnapshots();
  loadWorlds();
  loadConfig();
}

function loadSnapshots() {
  api("/world_backup/snapshots")
    .then(function (res) {
      if (!res || !res.ok) {
        toast((res && res.message) || "加载快照列表失败", "err");
        return;
      }
      _allSnapshots = res.snapshots || [];
      $("statSnapshotCount").textContent = res.count || "0";
      $("statTotalSize").textContent = res.total_size_formatted || "0 B";

      if (res.active_world) {
        $("statActiveWorld").textContent = res.active_world.world_name || res.active_world.folder_name;
        $("statActiveWorld").title = res.active_world.path;
      } else {
        $("statActiveWorld").textContent = "未检测到活跃世界";
      }

      renderSnapshotsTable(_allSnapshots);
    })
    .catch(function (err) {
      toast("请求快照失败: " + err, "err");
    });
}

function renderSnapshotsTable(list) {
  var tbody = $("wbSnapshotsList");
  if (!tbody) return;

  var filter = ($("wbSearchInput").value || "").trim().toLowerCase();
  var filtered = list.filter(function (s) {
    if (!filter) return true;
    var nameMatch = (s.world_name || "").toLowerCase().indexOf(filter) !== -1;
    var fnMatch = (s.filename || "").toLowerCase().indexOf(filter) !== -1;
    var tagMatch = (s.tag || "").toLowerCase().indexOf(filter) !== -1;
    return nameMatch || fnMatch || tagMatch;
  });

  if (filtered.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="muted" style="text-align:center;padding:24px;">' +
      (list.length === 0 ? "当前暂无世界快照。请点击上方按钮创建第一份快照！" : "没有匹配的快照记录") +
      '</td></tr>';
    return;
  }

  var html = "";
  filtered.forEach(function (s, idx) {
    var pinBadge = s.pinned
      ? '<span class="badge-pin">📌 已锁定</span>'
      : '<span class="badge-unpin">未锁定</span>';
    var tagBadge = s.tag ? '<span class="tag-pill">' + escapeHtml(s.tag) + '</span>' : '';

    html += '<tr>' +
      '<td>' + (idx + 1) + '</td>' +
      '<td>' + pinBadge + '</td>' +
      '<td>' +
        '<span style="font-weight:600;font-family:monospace;color:var(--text);">' + escapeHtml(s.filename) + '</span>' +
        tagBadge +
      '</td>' +
      '<td><span style="color:#38bdf8;">' + escapeHtml(s.world_name) + '</span></td>' +
      '<td>' + s.size_formatted + '</td>' +
      '<td><span style="font-size:12px;color:var(--muted);">' + s.created_at_str + '</span></td>' +
      '<td style="text-align:right;">' +
        '<div class="row" style="justify-content:flex-end;gap:6px;">' +
          '<a class="btn btn-sm btn-ghost" href="/api/world_backup/download?id=' + encodeURIComponent(s.snapshot_id) + '" download title="下载 .mcworld 快照">' +
            '📥 下载' +
          '</a>' +
          '<button class="btn btn-sm btn-ghost" onclick="togglePin(\'' + s.snapshot_id + '\', ' + (s.pinned ? 'true' : 'false') + ')">' +
            (s.pinned ? '🔓 解锁' : '📌 锁定') +
          '</button>' +
          '<button class="btn btn-sm btn-danger" onclick="deleteSnapshot(\'' + s.snapshot_id + '\', \'' + escapeHtml(s.filename) + '\', ' + (s.pinned ? 'true' : 'false') + ')">' +
            '🗑️' +
          '</button>' +
        '</div>' +
      '</td>' +
    '</tr>';
  });

  tbody.innerHTML = html;
}

function loadWorlds() {
  api("/world_backup/worlds")
    .then(function (res) {
      if (!res || !res.ok) return;
      _allWorlds = res.worlds || [];
      var select = $("wbWorldSelect");
      var tbody = $("wbDetectedWorldsList");

      if (select) {
        if (_allWorlds.length === 0) {
          select.innerHTML = '<option value="">未探测到世界存档</option>';
        } else {
          var selHtml = '<option value="">自动检测当前活跃世界 (推荐)</option>';
          _allWorlds.forEach(function (w) {
            var activeText = w.is_most_recent ? " ★ [当前活跃]" : "";
            selHtml += '<option value="' + escapeHtml(w.path) + '">' + escapeHtml(w.world_name) + activeText + ' (' + w.size_formatted + ')</option>';
          });
          select.innerHTML = selHtml;
        }
      }

      if (tbody) {
        if (_allWorlds.length === 0) {
          tbody.innerHTML = '<tr><td colspan="5" class="muted" style="text-align:center;padding:16px;">未在标准位置扫描到基岩版世界目录</td></tr>';
        } else {
          var wHtml = "";
          _allWorlds.forEach(function (w) {
            var activeBadge = w.is_most_recent
              ? '<span class="badge-active-world">★ 当前活跃</span>'
              : '<span class="badge-unpin">历史存档</span>';
            wHtml += '<tr>' +
              '<td><b>' + escapeHtml(w.world_name) + '</b></td>' +
              '<td>' + activeBadge + '</td>' +
              '<td><code style="font-size:12px;color:var(--muted);">' + escapeHtml(w.path) + '</code></td>' +
              '<td>' + w.size_formatted + '</td>' +
              '<td><span style="font-size:12px;color:var(--muted);">' + w.last_modified_str + '</span></td>' +
            '</tr>';
          });
          tbody.innerHTML = wHtml;
        }
      }
    })
    .catch(function () {});
}

function handleCreateSnapshot() {
  var btn = $("wbCreateBtn");
  var worldSelect = $("wbWorldSelect");
  var tagInput = $("wbTagInput");
  var flushCheck = $("wbFlushSaveCheck");

  var tag = (tagInput.value || "").trim();
  var worldPath = worldSelect ? worldSelect.value : "";
  var flushSave = flushCheck ? flushCheck.checked : true;

  btn.disabled = true;
  btn.textContent = "⏳ 正在创建快照...";

  api("/world_backup/create", {
    method: "POST",
    body: JSON.stringify({
      tag: tag,
      world_path: worldPath || null,
      flush_save: flushSave
    })
  })
  .then(function (res) {
    btn.disabled = false;
    btn.textContent = "🚀 立即创建快照";
    if (res && res.ok) {
      toast("世界快照创建成功: " + res.snapshot.filename, "ok");
      tagInput.value = "";
      loadSnapshots();
    } else {
      toast("创建失败: " + ((res && res.message) || "未知错误"), "err");
    }
  })
  .catch(function (err) {
    btn.disabled = false;
    btn.textContent = "🚀 立即创建快照";
    toast("请求异常: " + err, "err");
  });
}

function togglePin(snapshotId, currentPinned) {
  var newPinned = !currentPinned;
  api("/world_backup/pin", {
    method: "POST",
    body: JSON.stringify({
      snapshot_id: snapshotId,
      pinned: newPinned
    })
  })
  .then(function (res) {
    if (res && res.ok) {
      toast(res.message || "更新成功", "ok");
      loadSnapshots();
    } else {
      toast("操作失败: " + ((res && res.message) || "未知错误"), "err");
    }
  })
  .catch(function (err) {
    toast("操作失败: " + err, "err");
  });
}

function deleteSnapshot(snapshotId, filename, isPinned) {
  if (isPinned) {
    toast("该快照处于锁定保护状态，无法直接删除！请先解锁。", "warn");
    return;
  }
  if (!confirm("确定要永久删除世界快照【" + filename + "】吗？此操作无法撤销。")) {
    return;
  }
  api("/world_backup/delete", {
    method: "POST",
    body: JSON.stringify({ snapshot_id: snapshotId })
  })
  .then(function (res) {
    if (res && res.ok) {
      toast("快照已删除", "ok");
      loadSnapshots();
    } else {
      toast("删除失败: " + ((res && res.message) || "未知错误"), "err");
    }
  })
  .catch(function (err) {
    toast("删除失败: " + err, "err");
  });
}

function loadConfig() {
  api("/world_backup/config")
    .then(function (res) {
      if (!res || !res.ok) return;
      var c = res.config || {};
      $("cfgEnabled").checked = !!c.enabled;
      $("cfgInterval").value = c.interval_minutes || 60;
      $("cfgMaxKeep").value = c.max_snapshots || 10;
      $("cfgNotify").checked = !!c.notify_in_game;
      $("cfgCustomDir").value = c.custom_world_dir || "";

      var statBadge = $("statAutoStatus");
      if (statBadge) {
        if (c.enabled) {
          statBadge.innerHTML = '<span style="color:#4ade80;">🟢 开启 (' + (c.interval_minutes || 60) + ' 分钟/次)</span>';
        } else {
          statBadge.innerHTML = '<span style="color:#94a3b8;">⚪ 已禁用</span>';
        }
      }
    })
    .catch(function () {});
}

function handleSaveConfig() {
  var btn = $("cfgSaveBtn");
  var enabled = $("cfgEnabled").checked;
  var interval = parseInt($("cfgInterval").value, 10) || 60;
  var maxKeep = parseInt($("cfgMaxKeep").value, 10) || 10;
  var notify = $("cfgNotify").checked;
  var customDir = ($("cfgCustomDir").value || "").trim();

  btn.disabled = true;
  api("/world_backup/config", {
    method: "POST",
    body: JSON.stringify({
      enabled: enabled,
      interval_minutes: interval,
      max_snapshots: maxKeep,
      notify_in_game: notify,
      custom_world_dir: customDir
    })
  })
  .then(function (res) {
    btn.disabled = false;
    if (res && res.ok) {
      toast("世界备份设置已保存！", "ok");
      loadConfig();
    } else {
      toast("保存失败: " + ((res && res.message) || "未知错误"), "err");
    }
  })
  .catch(function (err) {
    btn.disabled = false;
    toast("保存失败: " + err, "err");
  });
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

document.addEventListener("DOMContentLoaded", initWorldBackupPage);

