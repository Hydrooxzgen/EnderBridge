// ===== 检查更新页面逻辑 =====
var _releasesPage = 1;
var _selectedUpdateFile = null;

function checkUpdate() {
  var btn = $("updateCheckBtn");
  if (!btn) return;
  btn.disabled = true;
  btn.textContent = "⏳ 检查中...";
  api("/update/check").then(function (data) {
    btn.disabled = false;
    btn.textContent = "🔍 检查更新";
    $("updateCheckResult").style.display = "";
    $("updateCurVer").textContent = data.current || "?";
    if (!data.ok) {
      $("updateLatestInfo").innerHTML = '<div class="update-msg err">' + escapeHtml(data.message || "检查失败") + '</div>';
      return;
    }
    if (!data.latest) {
      $("updateLatestInfo").innerHTML = '<div class="update-msg info">暂无 Release</div>';
      return;
    }
    var badge = data.is_prerelease
      ? '<span class="release-badge badge-prerelease">预览版</span>'
      : '<span class="release-badge badge-stable">正式版</span>';
    var assetHint = data.has_asset ? "" : '<span class="update-msg warn" style="display:inline;margin-left:6px;">⚠ 无压缩包附件</span>';
    var html = '<div class="update-latest-row"><div class="update-latest-name">' + badge + ' ' + escapeHtml(data.latest_name || data.latest) + '</div>' + assetHint + '</div>';
    html += data.update_available
      ? '<div class="update-msg ok">🎉 有新版本可用!</div>'
      : '<div class="update-msg info">✅ 已是最新版本</div>';
    if (data.html_url) html += '<a href="' + data.html_url + '" target="_blank" class="release-link">在 GitHub 上查看 →</a>';
    $("updateLatestInfo").innerHTML = html;
  }).catch(function () {
    btn.disabled = false;
    btn.textContent = "🔍 检查更新";
    toast("检查更新失败", "err");
  });
}

requireAuth(function (role) {
  initSidebar("update", role);
  checkUpdate();
  loadReleases(1);
});

// 检查更新按钮
var checkBtn = $("updateCheckBtn");
if (checkBtn) {
  checkBtn.addEventListener("click", checkUpdate);
}

// 本地文件更新
var chooseBtn = $("updateChooseFileBtn");
if (chooseBtn) {
  chooseBtn.addEventListener("click", function () { $("updateFileInput").click(); });
}
var fileInput = $("updateFileInput");
if (fileInput) {
  fileInput.addEventListener("change", function () {
    var file = this.files[0];
    if (file) {
      _selectedUpdateFile = file;
      $("updateFileName").textContent = file.name;
      $("updateLocalBtn").disabled = false;
    } else {
      _selectedUpdateFile = null;
      $("updateFileName").textContent = "";
      $("updateLocalBtn").disabled = true;
    }
  });
}
var localBtn = $("updateLocalBtn");
if (localBtn) {
  localBtn.addEventListener("click", function () {
    if (!_selectedUpdateFile) return;
    if (!confirm("确定要执行本地更新吗？\n将使用选中的压缩包替换项目文件(保留配置),服务器会自动重启。")) return;
    var formData = new FormData();
    formData.append("file", _selectedUpdateFile);
    var btn = this;
    btn.disabled = true;
    btn.textContent = "⏳ 上传中...";
    // 构建认证头
    var uploadHeaders = {};
    var role = sessionStorage.getItem(ROLE_KEY) || "";
    if (role === "guest") {
      uploadHeaders["X-Auth-Guest"] = "1";
    } else {
      var token = sessionStorage.getItem(TOKEN_KEY) || "";
      if (token) uploadHeaders["X-Auth-Token"] = token;
    }
    fetch("/api/update/upload", { method: "POST", headers: uploadHeaders, body: formData })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (!data.ok) {
          toast(data.message || "上传失败", "err");
          btn.disabled = false;
          btn.textContent = "🚀 执行更新";
          return;
        }
        return api("/update/install", { method: "POST", body: JSON.stringify({ path: data.path }) })
          .then(function (result) {
            if (!result.ok) {
              toast(result.message || "更新失败", "err");
              btn.disabled = false;
              btn.textContent = "🚀 执行更新";
            } else {
              toast("服务器正在更新并重启...", "ok");
              var tries = 0;
              var timer = setInterval(function () {
                tries++;
                fetch("/api/status").then(function (r) { return r.json(); })
                  .then(function (d) { if (d.ok) { clearInterval(timer); location.reload(); } })
                  .catch(function () {});
                if (tries >= 60) { clearInterval(timer); btn.disabled = false; btn.textContent = "🚀 执行更新"; toast("等待服务器恢复超时", "err"); }
              }, 2000);
            }
          });
      }).catch(function () {
        toast("上传失败", "err");
        btn.disabled = false;
        btn.textContent = "🚀 执行更新";
      });
  });
}

// 版本历史
var releasesLoadBtn = $("releasesLoadBtn");
if (releasesLoadBtn) {
  releasesLoadBtn.addEventListener("click", function () { loadReleases(1); });
}
var releasesPrevBtn = $("releasesPrevBtn");
if (releasesPrevBtn) {
  releasesPrevBtn.addEventListener("click", function () { if (_releasesPage > 1) loadReleases(_releasesPage - 1); });
}
var releasesNextBtn = $("releasesNextBtn");
if (releasesNextBtn) {
  releasesNextBtn.addEventListener("click", function () { loadReleases(_releasesPage + 1); });
}

function loadReleases(page) {
  _releasesPage = page || 1;
  $("releasesLoadBtn").style.display = "none";
  $("releasesPager").style.display = "";
  $("releasesPageNum").textContent = "第 " + _releasesPage + " 页";
  $("releasesPrevBtn").disabled = _releasesPage <= 1;
  $("releasesList").innerHTML = '<div class="td-dim" style="padding:12px 0;">加载中...</div>';
  api("/update/releases?page=" + _releasesPage).then(function (data) {
    if (!data.ok) {
      $("releasesList").innerHTML = '<div class="update-msg err">' + escapeHtml(data.message || "加载失败") + '</div>';
      return;
    }
    var list = data.releases || [];
    if (!list.length) {
      $("releasesList").innerHTML = '<div class="td-dim" style="padding:12px 0;">暂无更多版本</div>';
      $("releasesNextBtn").disabled = true;
      return;
    }
    $("releasesNextBtn").disabled = list.length < 20;
    $("releasesList").innerHTML = list.map(function (r) {
      var badge = r.prerelease
        ? '<span class="release-badge badge-prerelease">预览版</span>'
        : '<span class="release-badge badge-stable">正式版</span>';
      var currentTag = r.current ? ' <span class="release-badge badge-current">当前</span>' : "";
      var assetTag = r.has_asset ? "" : '<span class="td-dim" style="margin-left:6px;font-size:12px;">(无附件)</span>';
      var date = r.published_at ? new Date(r.published_at).toLocaleDateString("zh-CN") : "";
      var bodyHtml = r.body ? renderMarkdown(r.body) : '<span class="td-dim">无描述</span>';
      var actionBtn = (!r.current && r.has_asset)
        ? '<button class="btn btn-sm release-install-btn" data-tag="' + escapeHtml(r.tag) + '">安装此版本</button>'
        : "";
      return '<div class="release-item">' +
        '<div class="release-header">' + badge + ' <b>' + escapeHtml(r.name || r.tag) + '</b>' + currentTag + assetTag +
        ' <span class="td-dim" style="margin-left:8px;font-size:12px;">' + date + '</span>' +
        (r.html_url ? ' <a href="' + r.html_url + '" target="_blank" class="release-link" style="margin-left:8px">查看</a>' : "") +
        '</div>' +
        '<div class="release-body">' + bodyHtml + '</div>' +
        (actionBtn ? '<div style="margin-top:8px">' + actionBtn + '</div>' : "") +
        '</div>';
    }).join("");
    // 绑定安装按钮
    document.querySelectorAll('.release-install-btn').forEach(function (btn) {
      btn.addEventListener("click", function () {
        var tag = btn.getAttribute("data-tag");
        if (!confirm("确定要安装 " + tag + " 吗？\n将从 GitHub 下载并更新,服务器会自动重启。")) return;
        btn.disabled = true;
        btn.textContent = "⏳ 安装中...";
        api("/update/install", { method: "POST", body: JSON.stringify({ github_tag: tag }) })
          .then(function (result) {
            if (!result.ok) {
              toast(result.message || "安装失败", "err");
              btn.disabled = false;
              btn.textContent = "安装此版本";
            } else {
              toast("服务器正在更新并重启...", "ok");
              var tries = 0;
              var timer = setInterval(function () {
                tries++;
                fetch("/api/status").then(function (r) { return r.json(); })
                  .then(function (d) { if (d.ok) { clearInterval(timer); location.reload(); } })
                  .catch(function () {});
                if (tries >= 60) { clearInterval(timer); btn.disabled = false; btn.textContent = "安装此版本"; toast("等待服务器恢复超时", "err"); }
              }, 2000);
            }
          }).catch(function () {
            toast("安装失败", "err");
            btn.disabled = false;
            btn.textContent = "安装此版本";
          });
      });
    });
  }).catch(function () {
    $("releasesList").innerHTML = '<div class="update-msg err">加载失败</div>';
  });
}
