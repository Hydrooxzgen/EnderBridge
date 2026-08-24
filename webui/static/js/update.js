// ===== 检查更新页面逻辑 =====
var _releasesPage = 1;
var _selectedUpdateFile = null;
var _userRole = "guest";

/** 轮询服务器状态,恢复后跳转到正确地址 */
function _pollAndRedirect(btn, restoreText) {
  var basePort = parseInt(location.port) || 18888;
  console.log("[update] 开始轮询,基础端口: " + basePort);
  toast("服务器正在重启,请稍候...", "ok");

  // 带超时的 fetch,防止某个端口卡住导致整个 probe 挂起
  function fetchWithTimeout(url, ms) {
    var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var opts = ctrl ? { signal: ctrl.signal } : {};
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, ms) : null;
    return fetch(url, opts).finally(function () { if (timer) clearTimeout(timer); });
  }

  // 尝试所有端口,返回第一个存活的端口号(或 null)
  function probe() {
    // WebUIServer 最多尝试 10 个端口,轮询覆盖相同范围
    var ports = [basePort];
    for (var i = 1; i <= 9; i++) { ports.push(basePort + i); }
    var tryIdx = 0;
    return new Promise(function (resolve) {
      function tryPort() {
        if (tryIdx >= ports.length) { resolve(null); return; }
        var p = ports[tryIdx];
        fetchWithTimeout(location.protocol + "//" + location.hostname + ":" + p + "/api/status", 3000)
          .then(function (r) { return r.json(); })
          .then(function (d) { resolve(d.ok ? p : (tryIdx++, tryPort())); })
          .catch(function () { tryIdx++; tryPort(); });
      }
      tryPort();
    });
  }

  var started = false; // 防止 startPhase2 被重复调用

  // Phase 1: 等服务器死掉(连接失败)
  var waitDead = 0;
  var phase1 = setInterval(function () {
    waitDead++;
    console.log("[update] 等待服务器关闭... (" + waitDead + ")");
    probe().then(function (port) {
      if (started) return;
      if (port === null) {
        // 所有端口都连不上 = 服务器已关闭
        clearInterval(phase1);
        console.log("[update] 服务器已关闭,等待重新上线...");
        started = true;
        startPhase2();
      } else if (waitDead >= 30) {
        // 还活着但已等了30秒,直接进入 Phase2(服务器可能已重启但端口偏移)
        clearInterval(phase1);
        console.log("[update] 超过30秒服务器仍在运行,跳过等待直接轮询");
        started = true;
        startPhase2();
      }
      // 还活着且未超时 → 下一秒再试
    });
  }, 1000);

  // Phase 2: 等服务器重新上线,然后跳转
  function startPhase2() {
    var waitLive = 0;
    var phase2 = setInterval(function () {
      waitLive++;
      console.log("[update] 轮询第 " + waitLive + " 次...");
      probe().then(function (port) {
        if (port !== null) {
          clearInterval(phase2);
          // 用 /api/status 返回的 webPort 做最终跳转
          fetchWithTimeout(location.protocol + "//" + location.hostname + ":" + port + "/api/status", 3000)
            .then(function (r) { return r.json(); })
            .then(function (d) {
              var host = location.hostname;
              var finalPort = d.webPort || port;
              var url = location.protocol + "//" + host + ":" + finalPort;
              console.log("[update] 服务器已恢复,3秒后跳转到 " + url);
              toast("服务器已恢复,正在跳转...", "ok");
              setTimeout(function () { location.href = url; }, 3000);
            }).catch(function () {
              var url = location.protocol + "//" + location.hostname + ":" + port;
              toast("服务器已恢复,正在跳转...", "ok");
              setTimeout(function () { location.href = url; }, 3000);
            });
        }
      });
      if (waitLive >= 60) {
        clearInterval(phase2);
        btn.disabled = false;
        btn.textContent = restoreText;
        toast("等待服务器恢复超时", "err");
        console.log("[update] 轮询超时");
      }
    }, 2000);
  }
}

function checkUpdate() {
  var btn = $("updateCheckBtn");
  if (!btn) return;
  btn.disabled = true;
  btn.textContent = "⏳ 检查中...";
  api("/update/check").then(function (data) {
    btn.disabled = false;
    if (data.ok && data.update_available && _userRole !== "guest") {
      btn.textContent = "🚀 立刻更新";
      btn.classList.remove("btn-primary");
      btn.classList.add("btn-danger");
      btn.dataset.tag = data.latest || "";
    } else {
      btn.textContent = "🔍 检查更新";
      btn.classList.add("btn-primary");
      btn.classList.remove("btn-danger");
      delete btn.dataset.tag;
    }
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
  _userRole = role;
  initSidebar("update", role);
  initTheme();
  checkUpdate();
  loadReleases(1);
  // 访客:隐藏本地更新卡片
  if (role === "guest") {
    var localCard = $("updateLocalCard");
    if (localCard) localCard.style.display = "none";
  }
});

// 检查更新按钮
var checkBtn = $("updateCheckBtn");
if (checkBtn) {
  checkBtn.addEventListener("click", function () {
    if (checkBtn.dataset.tag) {
      // 立刻更新模式
      var tag = checkBtn.dataset.tag;
      if (!confirm("确定要更新到 " + tag + " 吗？\n将从 GitHub 下载并更新,服务器会自动重启。")) return;
      checkBtn.disabled = true;
      checkBtn.textContent = "⏳ 更新中...";
      api("/update/install", { method: "POST", body: JSON.stringify({ github_tag: tag }) })
        .then(function (result) {
          if (!result.ok) {
            toast(result.message || "更新失败", "err");
            checkBtn.disabled = false;
            checkBtn.textContent = "🚀 立刻更新";
          } else {
            toast("服务器正在更新并重启...", "ok");
            _pollAndRedirect(checkBtn, "🚀 立刻更新");
          }
        }).catch(function () {
          toast("更新失败", "err");
          checkBtn.disabled = false;
          checkBtn.textContent = "🚀 立刻更新";
        });
    } else {
      checkUpdate();
    }
  });
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
              _pollAndRedirect(btn, "🚀 执行更新");
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
      var actionBtn = (!r.current && r.has_asset && _userRole !== "guest")
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
