// ===== 检查更新页面逻辑 =====
var _releasesPage = 1;
var _selectedUpdateFile = null;
var _userRole = "guest";
var _minimumVersion = "";

/** 解析版本号为可比较的数字数组 */
function _parseVer(v) {
  if (!v) return [0];
  var nums = v.match(/\d+/g);
  return nums ? nums.map(Number) : [0];
}
/** 判断版本是否低于最低允许版本 */
function _isBelowMin(tag) {
  if (!_minimumVersion || !tag) return false;
  var a = _parseVer(tag), b = _parseVer(_minimumVersion);
  var len = Math.max(a.length, b.length);
  for (var i = 0; i < len; i++) {
    var x = a[i] || 0, y = b[i] || 0;
    if (x < y) return true;
    if (x > y) return false;
  }
  return false;
}

/** 轮询服务器状态,恢复后跳转到正确地址 */
function _pollAndRedirect(btn, restoreText) {
  var basePort = parseInt(location.port) || 18888;
  console.log("[update] 开始轮询,基础端口: " + basePort);
  toast(t("upd.restartWait"), "ok");

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
              toast(t("upd.recovered"), "ok");
              setTimeout(function () { location.href = url; }, 3000);
            }).catch(function () {
              var url = location.protocol + "//" + location.hostname + ":" + port;
              toast(t("upd.recovered"), "ok");
              setTimeout(function () { location.href = url; }, 3000);
            });
        }
      });
      if (waitLive >= 60) {
        clearInterval(phase2);
        btn.disabled = false;
        btn.textContent = restoreText;
        toast(t("upd.recoverTimeout"), "err");
        console.log("[update] 轮询超时");
      }
    }, 2000);
  }
}

function checkUpdate() {
  var btn = $("updateCheckBtn");
  if (!btn) return;
  btn.disabled = true;
  btn.textContent = t("upd.checking");
  api("/update/check").then(function (data) {
    btn.disabled = false;
    if (data.ok && data.update_available && _userRole !== "guest") {
      btn.textContent = t("upd.installNow");
      btn.classList.remove("btn-primary");
      btn.classList.add("btn-danger");
      btn.dataset.tag = data.latest || "";
      // 版本低于最低允许版本时禁止安装
      if (data.minimum_version && _isBelowMin(data.latest)) {
        btn.disabled = true;
        btn.textContent = t("upd.tooLow");
        btn.classList.remove("btn-danger");
        delete btn.dataset.tag;
      }
    } else {
      btn.textContent = t("upd.checkBtn");
      btn.classList.add("btn-primary");
      btn.classList.remove("btn-danger");
      delete btn.dataset.tag;
      _minimumVersion = data.minimum_version || _minimumVersion;
    }
    $("updateCheckResult").style.display = "";
    $("updateCurVer").textContent = data.current || "?";
    if (!data.ok) {
      $("updateLatestInfo").innerHTML = '<div class="update-msg err">' + escapeHtml(data.message || t("upd.checkFail")) + '</div>';
      return;
    }
    if (!data.latest) {
      $("updateLatestInfo").innerHTML = '<div class="update-msg info">' + t("upd.noRelease") + '</div>';
      return;
    }
    var badge = data.is_prerelease
      ? '<span class="release-badge badge-prerelease">' + t("upd.prerelease") + '</span>'
      : '<span class="release-badge badge-stable">' + t("upd.stable") + '</span>';
    var assetHint = data.has_asset ? "" : '<span class="update-msg warn" style="display:inline;margin-left:6px;">' + t("upd.noAsset") + '</span>';
    var html = '<div class="update-latest-row"><div class="update-latest-name">' + badge + ' ' + escapeHtml(data.latest_name || data.latest) + '</div>' + assetHint + '</div>';
    html += data.update_available
      ? '<div class="update-msg ok">' + t("upd.hasUpdate") + '</div>'
      : '<div class="update-msg info">' + t("upd.latest") + '</div>';
    if (data.html_url) html += '<a href="' + data.html_url + '" target="_blank" class="release-link">' + t("upd.viewGithub") + '</a>';
    $("updateLatestInfo").innerHTML = html;
  }).catch(function () {
    btn.disabled = false;
    btn.textContent = t("upd.checkBtn");
    toast(t("upd.checkFailToast"), "err");
  });
}

requireAuth(function (role) {
  _userRole = role;
  initSidebar("update", role);
  initTheme();
  initLang();
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
      if (!confirm(t("upd.confirmUpdatePrefix") + tag + t("upd.confirmUpdate"))) return;
      checkBtn.disabled = true;
      checkBtn.textContent = t("upd.updating");
      api("/update/install", { method: "POST", body: JSON.stringify({ github_tag: tag }) })
        .then(function (result) {
          if (!result.ok) {
            toast(result.message || t("upd.updateFail"), "err");
            checkBtn.disabled = false;
            checkBtn.textContent = t("upd.installNow");
          } else {
            toast(t("upd.updatingRestart"), "ok");
            _pollAndRedirect(checkBtn, t("upd.installNow"));
          }
        }).catch(function () {
          toast(t("upd.updateFail"), "err");
          checkBtn.disabled = false;
          checkBtn.textContent = t("upd.installNow");
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
    if (!confirm(t("upd.confirmLocal"))) return;
    var formData = new FormData();
    formData.append("file", _selectedUpdateFile);
    var btn = this;
    btn.disabled = true;
    btn.textContent = t("upd.uploading");
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
          toast(data.message || t("upd.uploadFail"), "err");
          btn.disabled = false;
          btn.textContent = t("upd.doUpdate");
          return;
        }
        return api("/update/install", { method: "POST", body: JSON.stringify({ path: data.path }) })
          .then(function (result) {
            if (!result.ok) {
              toast(result.message || t("upd.updateFail"), "err");
              btn.disabled = false;
              btn.textContent = t("upd.doUpdate");
            } else {
              toast(t("upd.updatingRestart"), "ok");
              _pollAndRedirect(btn, t("upd.doUpdate"));
            }
          });
      }).catch(function () {
        toast(t("upd.uploadFail"), "err");
        btn.disabled = false;
        btn.textContent = t("upd.doUpdate");
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
  $("releasesPageNum").textContent = _releasesPage;
  $("releasesPrevBtn").disabled = _releasesPage <= 1;
  $("releasesList").innerHTML = '<div class="td-dim" style="padding:12px 0;">' + t("upd.loading") + '</div>';
  api("/update/releases?page=" + _releasesPage).then(function (data) {
    if (!data.ok) {
      $("releasesList").innerHTML = '<div class="update-msg err">' + escapeHtml(data.message || t("upd.loadFail")) + '</div>';
      return;
    }
    var list = data.releases || [];
    if (!list.length) {
      $("releasesList").innerHTML = '<div class="td-dim" style="padding:12px 0;">' + t("upd.noMore") + '</div>';
      $("releasesNextBtn").disabled = true;
      return;
    }
    $("releasesNextBtn").disabled = list.length < 3;
    $("releasesList").innerHTML = list.map(function (r) {
      var badge = r.prerelease
        ? '<span class="release-badge badge-prerelease">' + t("upd.prerelease") + '</span>'
        : '<span class="release-badge badge-stable">' + t("upd.stable") + '</span>';
      var currentTag = r.current ? ' <span class="release-badge badge-current">' + t("upd.current") + '</span>' : "";
      var assetTag = r.has_asset ? "" : '<span class="td-dim" style="margin-left:6px;font-size:12px;">' + t("upd.noAssetShort") + '</span>';
      var date = r.published_at ? new Date(r.published_at).toLocaleDateString("zh-CN") : "";
      var bodyHtml = r.body ? renderMarkdown(r.body) : '<span class="td-dim">' + t("upd.noDesc") + '</span>';
      _minimumVersion = r.below_min !== undefined ? (data.minimum_version || _minimumVersion) : _minimumVersion;
      var belowMin = r.below_min || _isBelowMin(r.tag);
      var actionBtn = (!r.current && r.has_asset && _userRole !== "guest" && !belowMin)
        ? '<button class="btn btn-sm release-install-btn" data-tag="' + escapeHtml(r.tag) + '">' + t("upd.installVer") + '</button>'
        : (belowMin && !r.current ? '<span class="td-dim" style="font-size:12px;">' + t("upd.tooLowShort") + '</span>' : "");
      return '<div class="release-item">' +
        '<div class="release-header">' + badge + ' <b>' + escapeHtml(r.name || r.tag) + '</b>' + currentTag + assetTag +
        ' <span class="td-dim" style="margin-left:8px;font-size:12px;">' + date + '</span>' +
        (r.html_url ? ' <a href="' + r.html_url + '" target="_blank" class="release-link" style="margin-left:8px">' + t("upd.view") + '</a>' : "") +
        '</div>' +
        '<div class="release-body">' + bodyHtml + '</div>' +
        (actionBtn ? '<div style="margin-top:8px">' + actionBtn + '</div>' : "") +
        '</div>';
    }).join("");
    // 绑定安装按钮
    document.querySelectorAll('.release-install-btn').forEach(function (btn) {
      btn.addEventListener("click", function () {
        var tag = btn.getAttribute("data-tag");
        if (!confirm(t("upd.confirmInstallPrefix") + tag + t("upd.confirmUpdate"))) return;
        btn.disabled = true;
        btn.textContent = t("upd.installing");
        api("/update/install", { method: "POST", body: JSON.stringify({ github_tag: tag }) })
          .then(function (result) {
            if (!result.ok) {
              toast(result.message || t("upd.installFail"), "err");
              btn.disabled = false;
              btn.textContent = t("upd.installVer");
            } else {
              toast(t("upd.updatingRestart"), "ok");
              _pollAndRedirect(btn, t("upd.installVer"));
            }
          }).catch(function () {
            toast(t("upd.installFail"), "err");
            btn.disabled = false;
            btn.textContent = t("upd.installVer");
          });
      });
    });
  }).catch(function () {
    $("releasesList").innerHTML = '<div class="update-msg err">' + t("upd.loadFail") + '</div>';
  });
}

// ===== 历史备份 / 回滚 =====
function loadBackups() {
  var list = $("backupsList");
  if (!list) return;
  list.innerHTML = '<div class="td-dim">' + t("upd.loading") + '</div>';
  api("/update/backups").then(function (data) {
    if (!data.ok) {
      list.innerHTML = '<div class="update-msg err">' + escapeHtml(data.message || t("upd.backupLoadFail")) + '</div>';
      return;
    }
    var backups = data.backups || [];
    if (!backups.length) {
      list.innerHTML = '<div class="td-dim">' + t("upd.backupEmpty") + '</div>';
      return;
    }
    list.innerHTML = backups.map(function (b) {
      var date = b.mtime ? new Date(b.mtime * 1000).toLocaleString("zh-CN") : b.stamp;
      var sizeMB = b.size ? (b.size / 1048576).toFixed(1) + " MB" : "";
      var canRollback = _userRole !== "guest";
      var btn = canRollback
        ? '<button class="btn btn-sm" data-path="' + escapeHtml(b.path) + '">' + t("upd.backupRollback") + '</button>'
        : '';
      return '<div class="release-item" style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">' +
        '<div>' +
          '<span style="font-weight:600;">' + escapeHtml(b.filename) + '</span>' +
          '<span class="td-dim" style="margin-left:8px;font-size:12px;">' + date + '</span>' +
          (sizeMB ? '<span class="td-dim" style="margin-left:8px;font-size:12px;">' + t("upd.backupSize") + ': ' + sizeMB + '</span>' : '') +
        '</div>' +
        btn +
        '</div>';
    }).join("");
    // 绑定回滚按钮
    list.querySelectorAll("button[data-path]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var path = btn.getAttribute("data-path");
        if (!confirm(t("upd.backupConfirm"))) return;
        btn.disabled = true;
        btn.textContent = t("upd.backupRollingBack");
        api("/update/rollback", { method: "POST", body: JSON.stringify({ path: path }) })
          .then(function (result) {
            if (!result.ok) {
              toast(result.message || t("upd.backupRollbackFail"), "err");
              btn.disabled = false;
              btn.textContent = t("upd.backupRollback");
            } else {
              toast(t("upd.backupRollbackOk"), "ok");
              _pollAndRedirect(btn, t("upd.backupRollback"));
            }
          }).catch(function () {
            toast(t("upd.backupRollbackFail"), "err");
            btn.disabled = false;
            btn.textContent = t("upd.backupRollback");
          });
      });
    });
  }).catch(function () {
    list.innerHTML = '<div class="update-msg err">' + t("upd.backupLoadFail") + '</div>';
  });
}

var backupsLoadBtn = $("backupsLoadBtn");
if (backupsLoadBtn) {
  backupsLoadBtn.addEventListener("click", loadBackups);
}
// 访客隐藏整个备份卡片
if (_userRole === "guest") {
  var backupsCard = $("updateBackupsCard");
  if (backupsCard) backupsCard.style.display = "none";
}
