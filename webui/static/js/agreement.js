// ===== 协议管理页面逻辑 =====
requireAuth(function (role) {
  initSidebar("agreement", role);
  if (role !== "admin") {
    $("guestBadge").style.display = "";
    return;
  }
  $("guestBadge").style.display = "none";

  var enabled = $("agreementEnabled");
  var title = $("agreementTitle");
  var text = $("agreementText");
  var list = $("agreedList");
  var saveBtn = $("saveBtn");
  var clearBtn = $("clearBtn");

  // 加载当前配置
  api("/agreement").then(function (d) {
    if (!d.ok) { toast(d.message || "加载失败", "err"); return; }
    var cfg = d.config || {};
    enabled.checked = !!cfg.enabled;
    title.value = cfg.title || "📋 服务器协议";
    text.value = cfg.text || "";
    renderAgreedPlayers(d.agreed || []);
  }).catch(function () {});

  function renderAgreedPlayers(players) {
    if (!players.length) {
      list.innerHTML = '<span style="color:#64748b;">暂无已同意的玩家</span>';
      return;
    }
    var html = '';
    for (var i = 0; i < players.length; i++) {
      html += '<div style="padding:4px 0;border-bottom:1px solid #1e293b;">👤 ' + escapeHtml(players[i]) + '</div>';
    }
    list.innerHTML = html;
  }

  // 保存配置
  saveBtn.addEventListener("click", function () {
    saveBtn.disabled = true;
    saveBtn.textContent = "⏳ 保存中...";
    api("/agreement", {
      method: "PUT",
      body: JSON.stringify({
        enabled: enabled.checked,
        title: title.value.trim(),
        text: text.value,
      }),
    }).then(function (d) {
      saveBtn.disabled = false;
      saveBtn.textContent = "💾 保存协议配置";
      if (d.ok) {
        toast("协议配置已保存");
      } else {
        toast(d.message || "保存失败", "err");
      }
    }).catch(function () {
      saveBtn.disabled = false;
      saveBtn.textContent = "💾 保存协议配置";
      toast("保存请求失败", "err");
    });
  });

  // 清除已同意记录
  clearBtn.addEventListener("click", function () {
    if (!confirm("确定要清除所有已同意记录吗？所有玩家将需要重新同意协议。")) return;
    clearBtn.disabled = true;
    api("/agreement/clear", { method: "POST" }).then(function (d) {
      clearBtn.disabled = false;
      if (d.ok) {
        toast("已清除所有同意记录");
        renderAgreedPlayers([]);
      } else {
        toast(d.message || "清除失败", "err");
      }
    }).catch(function () {
      clearBtn.disabled = false;
      toast("清除请求失败", "err");
    });
  });
});
