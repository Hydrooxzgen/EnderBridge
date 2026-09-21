// ===== EnderBridge 创意资产与蓝图工坊 (Studio) 前端交互逻辑 =====

var _currentTab = "midi"; // "midi" | "image" | "ezmatic" | "mcfunc"
var _allAssets = { midi: [], image: [], ezmatic: [], mcfunc: [] };
var _searchKeyword = "";
var _blockPalette = []; // mod/image/blocks.json 方块调色板
var _selectedImageName = "";
var _currentMcfuncFile = "";

// Web Audio 播放器状态
var _audioCtx = null;
var _midiPlayer = {
  isPlaying: false,
  isPaused: false,
  trackName: "",
  timer: null,
  startTime: 0,
  pauseOffset: 0,
  duration: 0,
  events: [], // [{time, note, velocity, duration}]
  activeOscs: [],
};

requireAuth(function (role) {
  initSidebar("studio", role);
  initTheme();
  initLang();

  // 访客模式限制敏感操作
  if (role === "guest") {
    var upBtn = $("studioTriggerUploadBtn");
    if (upBtn) upBtn.style.display = "none";
    var dropZone = $("studioDropzone");
    if (dropZone) dropZone.style.display = "none";
  }

  initTabNavigation();
  initDropzoneUpload();
  initSearchFilter();
  initPixelArtControls();
  initMcfuncEditor();
  initBlueprintViewerEvents();
  loadBlockPalette();
  loadAllStudioAssets();
});

// ===== 1. 资产数据加载与 Tab 切换 =====

function loadAllStudioAssets() {
  var refreshBtn = $("studioRefreshBtn");
  if (refreshBtn) refreshBtn.disabled = true;

  api("/studio/assets").then(function (res) {
    if (!res.ok) return;
    _allAssets = res.assets || { midi: [], image: [], ezmatic: [], mcfunc: [] };
    updateTabBadges();
    renderCurrentTab();
  }).catch(function () {
    toast(t("mods.reqFail"), "err");
  }).finally(function () {
    if (refreshBtn) refreshBtn.disabled = false;
  });
}

function updateTabBadges() {
  ["midi", "image", "ezmatic", "mcfunc"].forEach(function (cat) {
    var list = _allAssets[cat] || [];
    var badgeId = "cnt" + cat.charAt(0).toUpperCase() + cat.slice(1);
    var el = $(badgeId);
    if (el) el.textContent = "(" + list.length + ")";
  });
}

function initTabNavigation() {
  var bar = $("studioTabs");
  if (!bar) return;
  bar.addEventListener("click", function (e) {
    var tab = e.target.closest(".chip-tab");
    if (!tab) return;
    bar.querySelectorAll(".chip-tab").forEach(function (el) { el.classList.remove("active"); });
    tab.classList.add("active");
    _currentTab = tab.dataset.tab || "midi";

    // 隐藏所有面板，展示对应面板
    document.querySelectorAll(".studio-panel").forEach(function (p) { p.style.display = "none"; });
    var targetPanel = $("panel" + _currentTab.charAt(0).toUpperCase() + _currentTab.slice(1));
    if (targetPanel) targetPanel.style.display = "block";

    renderCurrentTab();
  });
}

function renderCurrentTab() {
  var list = filterAssets(_allAssets[_currentTab] || []);
  if (_currentTab === "midi") renderMidiTab(list);
  else if (_currentTab === "image") renderImageTab(list);
  else if (_currentTab === "ezmatic") renderEzmaticTab(list);
  else if (_currentTab === "mcfunc") renderMcfuncTab(list);
}

function filterAssets(list) {
  if (!_searchKeyword) return list;
  var kw = _searchKeyword.toLowerCase();
  return list.filter(function (item) {
    return (item.name || "").toLowerCase().indexOf(kw) !== -1;
  });
}

function initSearchFilter() {
  var input = $("studioSearchInput");
  var clear = $("studioSearchClear");
  if (!input) return;

  input.addEventListener("input", function () {
    _searchKeyword = input.value.trim();
    if (clear) clear.style.display = _searchKeyword ? "block" : "none";
    renderCurrentTab();
  });

  if (clear) {
    clear.addEventListener("click", function () {
      input.value = "";
      _searchKeyword = "";
      clear.style.display = "none";
      renderCurrentTab();
      input.focus();
    });
  }

  var refreshBtn = $("studioRefreshBtn");
  if (refreshBtn) refreshBtn.addEventListener("click", loadAllStudioAssets);
}

// ===== 2. 文件上传与拖拽支持 =====

function initDropzoneUpload() {
  var dropzone = $("studioDropzone");
  var fileInput = $("studioFileInput");
  var triggerBtn = $("studioTriggerUploadBtn");

  if (triggerBtn && fileInput) {
    triggerBtn.addEventListener("click", function () {
      fileInput.click();
    });
  }

  if (dropzone && fileInput) {
    dropzone.addEventListener("click", function () {
      fileInput.click();
    });

    dropzone.addEventListener("dragover", function (e) {
      e.preventDefault();
      dropzone.classList.add("dragover");
    });
    ["dragleave", "dragend"].forEach(function (evt) {
      dropzone.addEventListener(evt, function () {
        dropzone.classList.remove("dragover");
      });
    });
    dropzone.addEventListener("drop", function (e) {
      e.preventDefault();
      dropzone.classList.remove("dragover");
      if (e.dataTransfer && e.dataTransfer.files.length) {
        handleUploadFile(e.dataTransfer.files[0]);
      }
    });

    fileInput.addEventListener("change", function () {
      if (fileInput.files.length) {
        handleUploadFile(fileInput.files[0]);
        fileInput.value = "";
      }
    });
  }
}

function handleUploadFile(file) {
  if (!file) return;
  var ext = "." + file.name.split(".").pop().toLowerCase();
  var category = _currentTab;

  // 自动根据后缀修正目标目录
  if (ext === ".mid" || ext === ".midi") category = "midi";
  else if (ext === ".mcfunc" || ext === ".mcfunction") category = "mcfunc";
  else if (ext === ".litematic" || ext === ".schematic" || ext === ".mcstructure") category = "ezmatic";
  else if ([".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"].indexOf(ext) !== -1) category = "image";

  toast("正在上传 " + file.name + "...", "ok");

  var reader = new FileReader();
  reader.onload = function (e) {
    var base64 = e.target.result.split(",")[1];
    api("/studio/upload", {
      method: "POST",
      body: JSON.stringify({
        category: category,
        filename: file.name,
        dataBase64: base64,
      }),
    }).then(function (res) {
      if (res.ok) {
        toast(t("studio.uploadSuccess") || "上传成功", "ok");
        loadAllStudioAssets();
      } else {
        toast(res.message || "上传失败", "err");
      }
    }).catch(function () {
      toast("上传网络失败", "err");
    });
  };
  reader.readAsDataURL(file);
}

// ===== 3. MIDI 音乐工作台与纯前端 Web Audio 合成播放器 =====

function renderMidiTab(list) {
  var tbody = $("midiTableBody");
  if (!tbody) return;
  if (!list.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="td-faint" style="text-align:center;padding:24px;">' + (t("studio.noAssets") || "暂无 MIDI 音乐") + '</td></tr>';
    return;
  }

  tbody.innerHTML = list.map(function (m) {
    var meta = m.metadata || {};
    var durationStr = meta.length_seconds ? formatDuration(meta.length_seconds) : "--:--";
    return '<tr>'
      + '<td><strong>' + escapeHtml(m.name) + '</strong></td>'
      + '<td>' + durationStr + '</td>'
      + '<td>' + (meta.tracks || 1) + '</td>'
      + '<td>' + (meta.notes_count || "--") + '</td>'
      + '<td class="td-dim">' + (m.size_formatted || "") + '</td>'
      + '<td style="white-space:nowrap;">'
      + '  <button class="btn btn-sm midi-preview-btn" data-name="' + escapeHtml(m.name) + '" style="margin-right:6px;">🎧 ' + (t("studio.previewAudio") || "试听") + '</button>'
      + '  <button class="btn btn-sm btn-primary midi-play-game-btn" data-name="' + escapeHtml(m.name) + '" style="margin-right:6px;">🎮 ' + (t("studio.playInGame") || "播放") + '</button>'
      + '  <button class="btn btn-sm btn-danger studio-delete-btn" data-cat="midi" data-name="' + escapeHtml(m.name) + '">🗑️</button>'
      + '</td>'
      + '</tr>';
  }).join("");
}

function formatDuration(secs) {
  var s = Math.round(secs);
  var m = Math.floor(s / 60);
  var remS = s % 60;
  return (m < 10 ? "0" : "") + m + ":" + (remS < 10 ? "0" : "") + remS;
}

// Web Audio 轻量 Standard MIDI File (SMF) 简单解析与播放
function playMidiWebAudio(filename) {
  stopWebAudioPlayer();
  var card = $("webMidiPlayerCard");
  var titleEl = $("webAudioTrackTitle");
  if (titleEl) titleEl.textContent = filename + " (加载中...)";
  var toggleBtn = $("webAudioToggleBtn");
  if (toggleBtn) toggleBtn.textContent = "⏳ 加载";

  fetch("/api/studio/asset-file?category=midi&file=" + encodeURIComponent(filename))
    .then(function (res) { return res.arrayBuffer(); })
    .then(function (buf) {
      if (!_audioCtx) {
        _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      }
      if (_audioCtx.state === "suspended") {
        _audioCtx.resume();
      }

      var events = parseMidiBufferToNotes(buf);
      _midiPlayer.events = events.notes;
      _midiPlayer.duration = events.duration || 10;
      _midiPlayer.trackName = filename;
      _midiPlayer.startTime = _audioCtx.currentTime;
      _midiPlayer.isPlaying = true;
      _midiPlayer.isPaused = false;

      if (titleEl) titleEl.textContent = filename;
      if (toggleBtn) toggleBtn.textContent = "⏸ 暂停";
      var gameBtn = $("midiPlayInGameCurrentBtn");
      if (gameBtn) {
        gameBtn.style.display = "inline-block";
        gameBtn.dataset.name = filename;
      }

      scheduleNotes(_audioCtx, events.notes, _audioCtx.currentTime);
      startPlayerTimeTicker();
    })
    .catch(function (err) {
      toast("解析 MIDI 播放失败: " + err, "err");
      stopWebAudioPlayer();
    });
}

function parseMidiBufferToNotes(arrayBuffer) {
  var data = new DataView(arrayBuffer);
  var offset = 0;
  var header = readString(data, offset, 4); offset += 4;
  if (header !== "MThd") throw new Error("非有效 MIDI 文件头");
  var headerLen = data.getUint32(offset); offset += 4;
  var format = data.getUint16(offset); offset += 2;
  var numTracks = data.getUint16(offset); offset += 2;
  var division = data.getUint16(offset); offset += 2;
  offset += (headerLen - 6);

  var tempo = 500000; // 微秒/拍
  var notes = [];
  var maxTime = 0;

  for (var t = 0; t < numTracks && offset < data.byteLength; t++) {
    var trkId = readString(data, offset, 4); offset += 4;
    var trkLen = data.getUint32(offset); offset += 4;
    var trkEnd = offset + trkLen;
    var currentTimeTicks = 0;
    var activeNotes = {};

    while (offset < trkEnd) {
      var delta = readVarInt();
      currentTimeTicks += delta;
      var status = data.getUint8(offset++);
      if (status === 0xFF) {
        // Meta event
        var metaType = data.getUint8(offset++);
        var metaLen = readVarInt();
        if (metaType === 0x51 && metaLen === 3) {
          tempo = (data.getUint8(offset) << 16) | (data.getUint8(offset + 1) << 8) | data.getUint8(offset + 2);
        }
        offset += metaLen;
      } else if ((status & 0xF0) === 0x90) {
        // Note On
        var note = data.getUint8(offset++);
        var vel = data.getUint8(offset++);
        var timeSec = (currentTimeTicks / division) * (tempo / 1000000);
        if (vel > 0) {
          activeNotes[note] = timeSec;
        } else if (activeNotes[note] !== undefined) {
          var dur = Math.max(0.1, timeSec - activeNotes[note]);
          notes.push({ time: activeNotes[note], note: note, duration: dur });
          if (timeSec > maxTime) maxTime = timeSec;
          delete activeNotes[note];
        }
      } else if ((status & 0xF0) === 0x80) {
        // Note Off
        var nOff = data.getUint8(offset++);
        offset++; // skip vel
        var tSec = (currentTimeTicks / division) * (tempo / 1000000);
        if (activeNotes[nOff] !== undefined) {
          var d = Math.max(0.1, tSec - activeNotes[nOff]);
          notes.push({ time: activeNotes[nOff], note: nOff, duration: d });
          if (tSec > maxTime) maxTime = tSec;
          delete activeNotes[nOff];
        }
      } else if ((status & 0x80) === 0) {
        offset++; // running status param
      } else {
        // Other channel messages (Program change, control change, etc.)
        var type = status & 0xF0;
        if (type === 0xC0 || type === 0xD0) offset += 1;
        else offset += 2;
      }
    }
  }

  function readString(dv, off, len) {
    var str = "";
    for (var i = 0; i < len; i++) str += String.fromCharCode(dv.getUint8(off + i));
    return str;
  }

  function readVarInt() {
    var val = 0;
    while (true) {
      var b = data.getUint8(offset++);
      val = (val << 7) | (b & 0x7F);
      if (!(b & 0x80)) break;
    }
    return val;
  }

  notes.sort(function (a, b) { return a.time - b.time; });
  return { notes: notes, duration: maxTime };
}

function scheduleNotes(ctx, notes, baseTime) {
  var maxScheduleNotes = Math.min(notes.length, 1200); // 限制前 1200 个音符避免浏览器负载
  for (var i = 0; i < maxScheduleNotes; i++) {
    var n = notes[i];
    var noteTime = baseTime + n.time;
    if (noteTime < ctx.currentTime) continue;

    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    // MIDI note to frequency: 440 * 2^((note - 69) / 12)
    var freq = 440 * Math.pow(2, (n.note - 69) / 12);
    osc.type = n.note < 48 ? "sawtooth" : "triangle";
    osc.frequency.setValueAtTime(freq, noteTime);

    var attack = 0.02;
    var dur = Math.min(n.duration, 1.2);
    gain.gain.setValueAtTime(0.0001, noteTime);
    gain.gain.exponentialRampToValueAtTime(0.12, noteTime + attack);
    gain.gain.exponentialRampToValueAtTime(0.0001, noteTime + dur);

    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(noteTime);
    osc.stop(noteTime + dur);
    _midiPlayer.activeOscs.push(osc);
  }
}

function stopWebAudioPlayer() {
  if (_midiPlayer.timer) clearInterval(_midiPlayer.timer);
  if (_midiPlayer.activeOscs) {
    _midiPlayer.activeOscs.forEach(function (osc) {
      try { osc.stop(); osc.disconnect(); } catch (e) {}
    });
    _midiPlayer.activeOscs = [];
  }
  _midiPlayer.isPlaying = false;
  _midiPlayer.isPaused = false;
  var toggleBtn = $("webAudioToggleBtn");
  if (toggleBtn) toggleBtn.textContent = "▶ 播放";
  var timeInfo = $("webAudioTimeInfo");
  if (timeInfo) timeInfo.textContent = "00:00 / 00:00";
}

function startPlayerTimeTicker() {
  if (_midiPlayer.timer) clearInterval(_midiPlayer.timer);
  _midiPlayer.timer = setInterval(function () {
    if (!_audioCtx || !_midiPlayer.isPlaying) return;
    var cur = Math.max(0, _audioCtx.currentTime - _midiPlayer.startTime);
    var dur = _midiPlayer.duration;
    var timeInfo = $("webAudioTimeInfo");
    if (timeInfo) timeInfo.textContent = formatDuration(cur) + " / " + formatDuration(dur);
    if (cur >= dur) {
      stopWebAudioPlayer();
    }
  }, 500);
}

// ===== 4. ImageMod 像素画工坊与 Canvas 方块调色仿真 =====

function loadBlockPalette() {
  api("/studio/palette").then(function (res) {
    if (res.ok && res.blocks) {
      _blockPalette = res.blocks;
    }
  }).catch(function () {});
}

function renderImageTab(list) {
  var container = $("imageAssetList");
  if (!container) return;
  if (!list.length) {
    container.innerHTML = '<div class="td-faint" style="padding:16px;text-align:center;">' + (t("studio.noAssets") || "暂无图片资产") + '</div>';
    return;
  }

  container.innerHTML = list.map(function (img) {
    var meta = img.metadata || {};
    var dimStr = meta.width ? meta.width + "×" + meta.height : "";
    return '<div class="card image-select-item" data-name="' + escapeHtml(img.name) + '" style="padding:10px;cursor:pointer;display:flex;align-items:center;justify-content:space-between;transition:all 0.15s ease;">'
      + '<div>'
      + '  <div style="font-weight:600;font-size:13px;word-break:break-all;">' + escapeHtml(img.name) + '</div>'
      + '  <div style="font-size:11px;color:var(--text-dim);">' + dimStr + ' | ' + (img.size_formatted || "") + '</div>'
      + '</div>'
      + '<button class="btn btn-sm btn-danger studio-delete-btn" data-cat="image" data-name="' + escapeHtml(img.name) + '" title="删除">🗑️</button>'
      + '</div>';
  }).join("");

  // 默认选中第一张图片进行仿真
  if (!_selectedImageName && list.length) {
    selectImageForPixelArt(list[0].name);
  }
}

function selectImageForPixelArt(filename) {
  _selectedImageName = filename;
  document.querySelectorAll(".image-select-item").forEach(function (el) {
    el.classList.toggle("active", el.dataset.name === filename);
    if (el.dataset.name === filename) el.style.border = "1px solid var(--primary, #3b82f6)";
    else el.style.border = "1px solid var(--card-border)";
  });
  runPixelArtSimulation();
}

function initPixelArtControls() {
  ["pixelTargetWidth", "pixelTargetAxis", "pixelDitherAlgo"].forEach(function (id) {
    var el = $(id);
    if (el) el.addEventListener("change", runPixelArtSimulation);
  });
  var wInput = $("pixelTargetWidth");
  if (wInput) wInput.addEventListener("input", runPixelArtSimulation);

  var drawBtn = $("imgDrawInGameBtn");
  if (drawBtn) {
    drawBtn.addEventListener("click", function () {
      if (!_selectedImageName) {
        toast("请先选择图片", "err");
        return;
      }
      var axis = $("pixelTargetAxis").value;
      var coordsStr = ($("pixelCoordsInput").value || "").trim();
      var parts = coordsStr ? coordsStr.split(/\s+/) : ["~", "~", "~"];
      drawBtn.disabled = true;
      api("/studio/action", {
        method: "POST",
        body: JSON.stringify({
          action: "draw_image",
          category: "image",
          filename: _selectedImageName,
          params: { axis: axis, x: parts[0] || "~", y: parts[1] || "~", z: parts[2] || "~" },
        }),
      }).then(function (res) {
        toast(res.message || t("studio.actionSent"), res.ok ? "ok" : "err");
      }).finally(function () {
        drawBtn.disabled = false;
      });
    });
  }

  var confirmBtn = $("imgDrawConfirmBtn");
  if (confirmBtn) {
    confirmBtn.addEventListener("click", function () {
      api("/studio/action", {
        method: "POST",
        body: JSON.stringify({ action: "confirm_image" }),
      }).then(function (res) {
        toast(res.message || "已确认放置", res.ok ? "ok" : "err");
      });
    });
  }
}

function runPixelArtSimulation() {
  if (!_selectedImageName) return;
  var canvas = $("pixelArtCanvas");
  if (!canvas) return;
  var ctx = canvas.getContext("2d");

  var targetWidth = parseInt($("pixelTargetWidth").value, 10) || 64;
  targetWidth = Math.max(16, Math.min(256, targetWidth));
  var dither = $("pixelDitherAlgo").value;

  var img = new Image();
  img.crossOrigin = "anonymous";
  img.src = "/api/studio/asset-file?category=image&file=" + encodeURIComponent(_selectedImageName);
  img.onload = function () {
    var ratio = img.height / img.width;
    var targetHeight = Math.max(1, Math.round(targetWidth * ratio));

    canvas.width = targetWidth;
    canvas.height = targetHeight;
    ctx.drawImage(img, 0, 0, targetWidth, targetHeight);

    var imgData = ctx.getImageData(0, 0, targetWidth, targetHeight);
    var pixels = imgData.data;
    var blockCounts = {};

    if (!_blockPalette || !_blockPalette.length) {
      return;
    }

    // 方块调色板匹配 (含最近邻与 Floyd-Steinberg 误差扩散)
    if (dither === "floyd") {
      // Floyd-Steinberg
      var fData = [];
      for (var p = 0; p < pixels.length; p += 4) {
        fData.push([pixels[p], pixels[p + 1], pixels[p + 2]]);
      }
      for (var y = 0; y < targetHeight; y++) {
        for (var x = 0; x < targetWidth; x++) {
          var idx = y * targetWidth + x;
          var curR = fData[idx][0], curG = fData[idx][1], curB = fData[idx][2];
          var closest = findClosestBlock(curR, curG, curB);
          var matchR = closest.rgb[0], matchG = closest.rgb[1], matchB = closest.rgb[2];

          var errR = curR - matchR;
          var errG = curG - matchG;
          var errB = curB - matchB;

          // 记录方块用量
          blockCounts[closest.id] = (blockCounts[closest.id] || 0) + 1;

          var pIdx = idx * 4;
          pixels[pIdx] = matchR;
          pixels[pIdx + 1] = matchG;
          pixels[pIdx + 2] = matchB;

          // 扩散误差
          distributeErr(fData, targetWidth, targetHeight, x + 1, y, errR, errG, errB, 7 / 16);
          distributeErr(fData, targetWidth, targetHeight, x - 1, y + 1, errR, errG, errB, 3 / 16);
          distributeErr(fData, targetWidth, targetHeight, x, y + 1, errR, errG, errB, 5 / 16);
          distributeErr(fData, targetWidth, targetHeight, x + 1, y + 1, errR, errG, errB, 1 / 16);
        }
      }
    } else {
      // 最近邻采样
      for (var i = 0; i < pixels.length; i += 4) {
        var c = findClosestBlock(pixels[i], pixels[i + 1], pixels[i + 2]);
        pixels[i] = c.rgb[0];
        pixels[i + 1] = c.rgb[1];
        pixels[i + 2] = c.rgb[2];
        blockCounts[c.id] = (blockCounts[c.id] || 0) + 1;
      }
    }

    ctx.putImageData(imgData, 0, 0);
    renderBlockBOM(blockCounts, targetWidth * targetHeight);
  };
}

function distributeErr(fData, w, h, x, y, er, eg, eb, factor) {
  if (x < 0 || x >= w || y < 0 || y >= h) return;
  var idx = y * w + x;
  fData[idx][0] += er * factor;
  fData[idx][1] += eg * factor;
  fData[idx][2] += eb * factor;
}

function findClosestBlock(r, g, b) {
  var best = _blockPalette[0];
  var bestDist = Infinity;
  for (var i = 0; i < _blockPalette.length; i++) {
    var blk = _blockPalette[i];
    var dr = r - blk.rgb[0];
    var dg = g - blk.rgb[1];
    var db = b - blk.rgb[2];
    var dist = dr * dr + dg * dg + db * db;
    if (dist < bestDist) {
      bestDist = dist;
      best = blk;
    }
  }
  return best;
}

function renderBlockBOM(counts, total) {
  var totalEl = $("pixelTotalBlocksCount");
  if (totalEl) totalEl.textContent = "共 " + total + " 方块 (" + Object.keys(counts).length + " 种材料)";
  var bomBox = $("pixelBOMContainer");
  if (!bomBox) return;

  var sorted = Object.keys(counts).map(function (k) {
    return { id: k, count: counts[k] };
  }).sort(function (a, b) { return b.count - a.count; });

  bomBox.innerHTML = sorted.map(function (item) {
    return '<span style="display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:4px;background:var(--card);font-size:12px;border:1px solid var(--card-border);">'
      + '<span>' + escapeHtml(item.id) + '</span>'
      + '<strong style="color:var(--primary, #3b82f6);">×' + item.count + '</strong>'
      + '</span>';
  }).join("");
}

// ===== 5. Ezmatic 蓝图模型工坊 =====

function renderEzmaticTab(list) {
  var grid = $("ezmaticGrid");
  if (!grid) return;
  if (!list.length) {
    grid.innerHTML = '<div class="td-faint" style="grid-column:1/-1;text-align:center;padding:32px;">' + (t("studio.noAssets") || "暂无蓝图模型") + '</div>';
    return;
  }

  grid.innerHTML = list.map(function (item) {
    var meta = item.metadata || {};
    var dim = meta.dimensions || {};
    var dimStr = dim.x ? dim.x + " × " + dim.y + " × " + dim.z : "--";
    var volStr = meta.volume ? meta.volume.toLocaleString() + " 方块" : "--";
    var author = meta.author || "Unknown";

    return '<div class="blueprint-card">'
      + '<div>'
      + '  <div class="row" style="justify-content:space-between;align-items:flex-start;margin-bottom:8px;">'
      + '    <strong style="font-size:14px;word-break:break-all;">' + escapeHtml(item.name) + '</strong>'
      + '    <span class="badge-sec-safe" style="font-size:10px;text-transform:uppercase;">' + escapeHtml(meta.format || item.extension) + '</span>'
      + '  </div>'
      + '  <div style="font-size:12px;color:var(--text-dim);margin-bottom:4px;"><span data-i18n="studio.author">作者</span>: ' + escapeHtml(author) + '</div>'
      + '  <div style="font-size:12px;color:var(--text-dim);margin-bottom:4px;"><span data-i18n="studio.blueprintSize">尺寸</span>: <strong>' + dimStr + '</strong></div>'
      + '  <div style="font-size:12px;color:var(--text-dim);margin-bottom:4px;"><span data-i18n="studio.blueprintVol">体积</span>: ' + volStr + '</div>'
      + '  <div style="font-size:12px;color:var(--text-dim);margin-bottom:12px;"><span data-i18n="studio.blueprintBlocks">包含种类</span>: ' + (meta.block_types || "--") + ' 种</div>'
      + '</div>'
      + '<div class="row gap-10" style="margin-top:8px;justify-content:space-between;flex-wrap:wrap;">'
      + '  <div class="row gap-6">'
      + '    <button class="btn btn-sm ezmatic-3d-btn" data-name="' + escapeHtml(item.name) + '" style="background:rgba(59,130,246,0.15);border-color:#3b82f6;color:#60a5fa;">' + (t("studio.preview3D") || "3D 预览") + '</button>'
      + '    <button class="btn btn-sm ezmatic-action-btn" data-action="preview_ezmatic" data-name="' + escapeHtml(item.name) + '">' + (t("studio.previewHolo") || "投影预览") + '</button>'
      + '    <button class="btn btn-sm btn-primary ezmatic-action-btn" data-action="build_ezmatic" data-name="' + escapeHtml(item.name) + '">' + (t("studio.buildHolo") || "开始建造") + '</button>'
      + '  </div>'
      + '  <button class="btn btn-sm btn-danger studio-delete-btn" data-cat="ezmatic" data-name="' + escapeHtml(item.name) + '">🗑️</button>'
      + '</div>'
      + '</div>';
  }).join("");
}

// ===== 6. MCFunc 脚本工坊 =====

function renderMcfuncTab(list) {
  var fileList = $("mcfuncFileList");
  if (!fileList) return;
  if (!list.length) {
    fileList.innerHTML = '<div class="td-faint" style="padding:16px;text-align:center;">' + (t("studio.noAssets") || "暂无脚本") + '</div>';
    return;
  }

  fileList.innerHTML = list.map(function (f) {
    var meta = f.metadata || {};
    var isSel = f.name === _currentMcfuncFile;
    return '<div class="card mcfunc-select-item ' + (isSel ? "active" : "") + '" data-name="' + escapeHtml(f.name) + '" style="padding:10px;cursor:pointer;border:1px solid ' + (isSel ? "var(--primary, #3b82f6)" : "var(--card-border)") + ';">'
      + '<div style="font-weight:600;font-size:13px;word-break:break-all;">' + escapeHtml(f.name) + '</div>'
      + '<div style="font-size:11px;color:var(--text-dim);margin-top:3px;">' + (meta.total_lines || 0) + ' 行 | ' + (meta.command_lines || 0) + ' 条指令</div>'
      + '</div>';
  }).join("");

  if (!_currentMcfuncFile && list.length) {
    loadMcfuncFile(list[0].name);
  }
}

function loadMcfuncFile(filename) {
  _currentMcfuncFile = filename;
  var nameInput = $("mcfuncCurrentName");
  if (nameInput) nameInput.value = filename;
  var editor = $("mcfuncCodeEditor");
  if (editor) {
    editor.value = "# 加载中...";
    editor.disabled = true;
  }

  api("/studio/asset-file?category=mcfunc&file=" + encodeURIComponent(filename) + "&text=1")
    .then(function (res) {
      if (editor) {
        editor.disabled = false;
        editor.value = res.content || "";
        updateMcfuncStats();
      }
    }).catch(function () {
      if (editor) editor.disabled = false;
    });

  document.querySelectorAll(".mcfunc-select-item").forEach(function (el) {
    el.style.border = el.dataset.name === filename ? "1px solid var(--primary, #3b82f6)" : "1px solid var(--card-border)";
  });
}

function updateMcfuncStats() {
  var editor = $("mcfuncCodeEditor");
  var badge = $("mcfuncStatsBadge");
  if (!editor || !badge) return;
  var lines = editor.value.split("\n");
  var cmds = 0;
  for (var i = 0; i < lines.length; i++) {
    var s = lines[i].trim();
    if (s && !s.startsWith("#")) cmds++;
  }
  badge.textContent = lines.length + " 行 (" + cmds + " 条指令)";
}

function initMcfuncEditor() {
  var editor = $("mcfuncCodeEditor");
  if (editor) {
    editor.addEventListener("input", updateMcfuncStats);
    editor.addEventListener("keydown", function (e) {
      if (e.key === "Tab") {
        e.preventDefault();
        var start = this.selectionStart;
        var end = this.selectionEnd;
        this.value = this.value.substring(0, start) + "  " + this.value.substring(end);
        this.selectionStart = this.selectionEnd = start + 2;
        updateMcfuncStats();
      }
    });
  }

  var newBtn = $("mcfuncNewBtn");
  if (newBtn) {
    newBtn.addEventListener("click", function () {
      var name = prompt(t("studio.scriptNamePh") || "请输入新脚本名称 (如 custom.mcfunc):", "new_script.mcfunc");
      if (!name) return;
      if (!name.endsWith(".mcfunc") && !name.endsWith(".mcfunction")) name += ".mcfunc";
      _currentMcfuncFile = name;
      $("mcfuncCurrentName").value = name;
      $("mcfuncCodeEditor").value = "# Minecraft Function Script: " + name + "\nsay Hello from Studio!\n";
      updateMcfuncStats();
      $("mcfuncSaveBtn").click();
    });
  }

  var saveBtn = $("mcfuncSaveBtn");
  if (saveBtn) {
    saveBtn.addEventListener("click", function () {
      var name = ($("mcfuncCurrentName").value || "").trim();
      if (!name) {
        toast("请输入文件名", "err");
        return;
      }
      saveBtn.disabled = true;
      api("/studio/save-text", {
        method: "POST",
        body: JSON.stringify({
          category: "mcfunc",
          filename: name,
          content: $("mcfuncCodeEditor").value,
        }),
      }).then(function (res) {
        if (res.ok) {
          toast(t("studio.saveSuccess") || "脚本已保存", "ok");
          loadAllStudioAssets();
        } else {
          toast(res.message || "保存失败", "err");
        }
      }).finally(function () {
        saveBtn.disabled = false;
      });
    });
  }

  var runBtn = $("mcfuncRunOnceBtn");
  if (runBtn) {
    runBtn.addEventListener("click", function () {
      var name = ($("mcfuncCurrentName").value || "").trim();
      if (!name) return;
      runBtn.disabled = true;
      api("/studio/action", {
        method: "POST",
        body: JSON.stringify({
          action: "run_mcfunc",
          category: "mcfunc",
          filename: name,
        }),
      }).then(function (res) {
        toast(res.message || t("studio.actionSent"), res.ok ? "ok" : "err");
      }).finally(function () {
        runBtn.disabled = false;
      });
    });
  }

  var loopBtn = $("mcfuncLoopBtn");
  if (loopBtn) {
    loopBtn.addEventListener("click", function () {
      var name = ($("mcfuncCurrentName").value || "").trim();
      if (!name) return;
      var loopName = prompt(t("studio.loopNamePh") || "请输入循环任务名称:", "studio_loop");
      if (!loopName) return;
      var interval = prompt(t("studio.intervalPh") || "请输入循环间隔秒数:", "1.0");
      if (!interval) return;

      api("/studio/action", {
        method: "POST",
        body: JSON.stringify({
          action: "run_mcfunc",
          category: "mcfunc",
          filename: name,
          params: { loopName: loopName, interval: interval },
        }),
      }).then(function (res) {
        toast(res.message || t("studio.actionSent"), res.ok ? "ok" : "err");
      });
    });
  }

  var delBtn = $("mcfuncDeleteBtn");
  if (delBtn) {
    delBtn.addEventListener("click", function () {
      var name = ($("mcfuncCurrentName").value || "").trim();
      if (!name) return;
      if (!confirm((t("studio.deleteConfirm") || "确定要删除该脚本吗？"))) return;
      api("/studio/asset", {
        method: "DELETE",
        body: JSON.stringify({ category: "mcfunc", filename: name }),
      }).then(function (res) {
        if (res.ok) {
          toast(t("studio.deleteSuccess") || "已删除", "ok");
          _currentMcfuncFile = "";
          loadAllStudioAssets();
        } else {
          toast(res.message || "删除失败", "err");
        }
      });
    });
  }
}

// ===== 7. 通用事件委托与动作派发 =====

document.addEventListener("click", function (e) {
  // 1) MIDI 试听按钮
  var prevBtn = e.target.closest(".midi-preview-btn");
  if (prevBtn) {
    playMidiWebAudio(prevBtn.dataset.name);
    return;
  }

  // 2) MIDI 游戏内播放按钮
  var midiPlayBtn = e.target.closest(".midi-play-game-btn");
  if (midiPlayBtn) {
    var fn = midiPlayBtn.dataset.name;
    var perc = $("midiPercussionToggle") ? $("midiPercussionToggle").checked : true;
    midiPlayBtn.disabled = true;
    api("/studio/action", {
      method: "POST",
      body: JSON.stringify({
        action: "play_midi",
        category: "midi",
        filename: fn,
        params: { percussion: perc },
      }),
    }).then(function (res) {
      toast(res.message || t("studio.actionSent"), res.ok ? "ok" : "err");
    }).finally(function () {
      midiPlayBtn.disabled = false;
    });
    return;
  }

  // 3a) Ezmatic 蓝图 3D 离线预览 (无需连接 MC 客户端)
  var bp3dBtn = e.target.closest(".ezmatic-3d-btn");
  if (bp3dBtn) {
    openBlueprint3dViewer(bp3dBtn.dataset.name);
    return;
  }

  // 3b) Ezmatic 蓝图游戏内操作 (投影/建造)
  var ezBtn = e.target.closest(".ezmatic-action-btn");
  if (ezBtn) {
    var action = ezBtn.dataset.action;
    var ezName = ezBtn.dataset.name;
    ezBtn.disabled = true;
    api("/studio/action", {
      method: "POST",
      body: JSON.stringify({
        action: action,
        category: "ezmatic",
        filename: ezName,
      }),
    }).then(function (res) {
      toast(res.message || t("studio.actionSent"), res.ok ? "ok" : "err");
    }).finally(function () {
      ezBtn.disabled = false;
    });
    return;
  }

  // 4) 图片选择
  var imgItem = e.target.closest(".image-select-item");
  if (imgItem && !e.target.closest(".studio-delete-btn")) {
    selectImageForPixelArt(imgItem.dataset.name);
    return;
  }

  // 5) MCFunc 选择
  var mcItem = e.target.closest(".mcfunc-select-item");
  if (mcItem) {
    loadMcfuncFile(mcItem.dataset.name);
    return;
  }

  // 6) 通用资产删除按钮
  var delBtn = e.target.closest(".studio-delete-btn");
  if (delBtn) {
    var cat = delBtn.dataset.cat;
    var name = delBtn.dataset.name;
    if (!confirm(t("studio.deleteConfirm") || "确定要删除该资产吗？已保留备份。")) return;
    delBtn.disabled = true;
    api("/studio/asset", {
      method: "DELETE",
      body: JSON.stringify({ category: cat, filename: name }),
    }).then(function (res) {
      if (res.ok) {
        toast(t("studio.deleteSuccess") || "已成功删除", "ok");
        if (cat === "image" && _selectedImageName === name) _selectedImageName = "";
        if (cat === "mcfunc" && _currentMcfuncFile === name) _currentMcfuncFile = "";
        loadAllStudioAssets();
      } else {
        toast(res.message || "删除失败", "err");
      }
    }).finally(function () {
      delBtn.disabled = false;
    });
    return;
  }
});

// Web Audio 控制器按钮绑定
var webToggle = $("webAudioToggleBtn");
if (webToggle) {
  webToggle.addEventListener("click", function () {
    if (_midiPlayer.isPlaying) {
      stopWebAudioPlayer();
    } else if (_midiPlayer.trackName) {
      playMidiWebAudio(_midiPlayer.trackName);
    }
  });
}
var webStop = $("webAudioStopBtn");
if (webStop) webStop.addEventListener("click", stopWebAudioPlayer);

var midiStopGame = $("midiStopInGameBtn");
if (midiStopGame) {
  midiStopGame.addEventListener("click", function () {
    api("/studio/action", {
      method: "POST",
      body: JSON.stringify({ action: "stop_midi" }),
    }).then(function (res) {
      toast(res.message || "已停止音乐", res.ok ? "ok" : "err");
    });
  });
}

// ===== 8. 投影预览 (Hardware-Accelerated WebGL Voxel Engine) =====

var _bpData = null;
var _bpVisiblePalette = {};
var _bpSliceMin = 0;
var _bpSliceMax = 0;
var _bpCameraMode = "persp"; // "persp" | "ortho"

// Orbit Camera with smooth damping inertia
var _bpRotX = 0.55;
var _bpRotY = 0.785;
var _bpPanX = 0;
var _bpPanY = 0;
var _bpDistance = 25.0;

var _bpTargetRotX = 0.55;
var _bpTargetRotY = 0.785;
var _bpTargetPanX = 0;
var _bpTargetPanY = 0;
var _bpTargetDistance = 25.0;

var _bpCanvas = null;
var _bpGL = null;
var _bpCtx = null; // Canvas 2D fallback
var _bpIsDragging = false;
var _bpDragMode = "rotate";
var _bpLastMouseX = 0;
var _bpLastMouseY = 0;
var _bpPinchDist = 0;
var _bpIsRendering = false;
var _bpColorCache = {};
var _bpShowTextures = true;
var _bpTexturesLoaded = false;

// WebGL Engine State
var _bpProgram = null;
var _bpGridProgram = null;
var _bpPosBuffer = null;
var _bpNormalBuffer = null;
var _bpTexBuffer = null;
var _bpColorBuffer = null;
var _bpGridPosBuffer = null;
var _bpGridColorBuffer = null;
var _bpAtlasTexture = null;
var _bpAtlasCanvas = null;
var _bpVoxelVertexCount = 0;
var _bpGridVertexCount = 0;

// High-Performance Matrix 4x4 Mathematics
var Mat4 = {
  create: function () {
    var out = new Float32Array(16);
    out[0] = 1; out[5] = 1; out[10] = 1; out[15] = 1;
    return out;
  },
  identity: function (out) {
    for (var i = 0; i < 16; i++) out[i] = (i % 5 === 0) ? 1 : 0;
    return out;
  },
  multiply: function (out, a, b) {
    var a00 = a[0], a01 = a[1], a02 = a[2], a03 = a[3];
    var a10 = a[4], a11 = a[5], a12 = a[6], a13 = a[7];
    var a20 = a[8], a21 = a[9], a22 = a[10], a23 = a[11];
    var a30 = a[12], a31 = a[13], a32 = a[14], a33 = a[15];
    var b0 = b[0], b1 = b[1], b2 = b[2], b3 = b[3];
    out[0] = b0*a00 + b1*a10 + b2*a20 + b3*a30;
    out[1] = b0*a01 + b1*a11 + b2*a21 + b3*a31;
    out[2] = b0*a02 + b1*a12 + b2*a22 + b3*a32;
    out[3] = b0*a03 + b1*a13 + b2*a23 + b3*a33;
    b0 = b[4]; b1 = b[5]; b2 = b[6]; b3 = b[7];
    out[4] = b0*a00 + b1*a10 + b2*a20 + b3*a30;
    out[5] = b0*a01 + b1*a11 + b2*a21 + b3*a31;
    out[6] = b0*a02 + b1*a12 + b2*a22 + b3*a32;
    out[7] = b0*a03 + b1*a13 + b2*a23 + b3*a33;
    b0 = b[8]; b1 = b[9]; b2 = b[10]; b3 = b[11];
    out[8] = b0*a00 + b1*a10 + b2*a20 + b3*a30;
    out[9] = b0*a01 + b1*a11 + b2*a21 + b3*a31;
    out[10] = b0*a02 + b1*a12 + b2*a22 + b3*a32;
    out[11] = b0*a03 + b1*a13 + b2*a23 + b3*a33;
    b0 = b[12]; b1 = b[13]; b2 = b[14]; b3 = b[15];
    out[12] = b0*a00 + b1*a10 + b2*a20 + b3*a30;
    out[13] = b0*a01 + b1*a11 + b2*a21 + b3*a31;
    out[14] = b0*a02 + b1*a12 + b2*a22 + b3*a32;
    out[15] = b0*a03 + b1*a13 + b2*a23 + b3*a33;
    return out;
  },
  perspective: function (out, fovy, aspect, near, far) {
    var f = 1.0 / Math.tan(fovy / 2);
    var nf = 1 / (near - far);
    out[0] = f / aspect; out[1] = 0; out[2] = 0; out[3] = 0;
    out[4] = 0; out[5] = f; out[6] = 0; out[7] = 0;
    out[8] = 0; out[9] = 0; out[10] = (far + near) * nf; out[11] = -1;
    out[12] = 0; out[13] = 0; out[14] = (2 * far * near) * nf; out[15] = 0;
    return out;
  },
  ortho: function (out, left, right, bottom, top, near, far) {
    var lr = 1 / (left - right);
    var bt = 1 / (bottom - top);
    var nf = 1 / (near - far);
    out[0] = -2 * lr; out[1] = 0; out[2] = 0; out[3] = 0;
    out[4] = 0; out[5] = -2 * bt; out[6] = 0; out[7] = 0;
    out[8] = 0; out[9] = 0; out[10] = 2 * nf; out[11] = 0;
    out[12] = (left + right) * lr; out[13] = (top + bottom) * bt; out[14] = (far + near) * nf; out[15] = 1;
    return out;
  },
  lookAt: function (out, eye, center, up) {
    var x0, x1, x2, y0, y1, y2, z0, z1, z2, len;
    var eyex = eye[0], eyey = eye[1], eyez = eye[2];
    var upx = up[0], upy = up[1], upz = up[2];
    var centerx = center[0], centery = center[1], centerz = center[2];

    z0 = eyex - centerx;
    z1 = eyey - centery;
    z2 = eyez - centerz;
    len = Math.hypot(z0, z1, z2);
    if (len === 0) z2 = 1; else { z0 /= len; z1 /= len; z2 /= len; }

    x0 = upy * z2 - upz * z1;
    x1 = upz * z0 - upx * z2;
    x2 = upx * z1 - upy * z0;
    len = Math.hypot(x0, x1, x2);
    if (len === 0) { x0 = 0; x1 = 0; x2 = 0; } else { x0 /= len; x1 /= len; x2 /= len; }

    y0 = z1 * x2 - z2 * x1;
    y1 = z2 * x0 - z0 * x2;
    y2 = z0 * x1 - z1 * x0;
    len = Math.hypot(y0, y1, y2);
    if (len === 0) { y0 = 0; y1 = 0; y2 = 0; } else { y0 /= len; y1 /= len; y2 /= len; }

    out[0] = x0; out[1] = y0; out[2] = z0; out[3] = 0;
    out[4] = x1; out[5] = y1; out[6] = z1; out[7] = 0;
    out[8] = x2; out[9] = y2; out[10] = z2; out[11] = 0;
    out[12] = -(x0 * eyex + x1 * eyey + x2 * eyez);
    out[13] = -(y0 * eyex + y1 * eyey + y2 * eyez);
    out[14] = -(z0 * eyex + z1 * eyey + z2 * eyez);
    out[15] = 1;
    return out;
  }
};

function createShader(gl, type, source) {
  var shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.error("Shader compile error:", gl.getShaderInfoLog(shader));
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

function createProgram(gl, vsSource, fsSource) {
  var vs = createShader(gl, gl.VERTEX_SHADER, vsSource);
  var fs = createShader(gl, gl.FRAGMENT_SHADER, fsSource);
  if (!vs || !fs) return null;
  var program = gl.createProgram();
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    console.error("Program link error:", gl.getProgramInfoLog(program));
    return null;
  }
  return program;
}

function initWebGL() {
  if (!_bpCanvas) return false;
  try {
    _bpGL = _bpCanvas.getContext("webgl", { antialias: true, alpha: false }) ||
            _bpCanvas.getContext("experimental-webgl", { antialias: true, alpha: false });
  } catch (e) {
    _bpGL = null;
  }
  if (!_bpGL) {
    console.warn("WebGL not available, falling back to Canvas 2D rasterizer.");
    _bpCtx = _bpCanvas.getContext("2d");
    return false;
  }

  var gl = _bpGL;

  // 1. Voxel Shaders
  var vsVoxel = [
    "attribute vec3 aPosition;",
    "attribute vec3 aNormal;",
    "attribute vec2 aTexCoord;",
    "attribute vec4 aColor;",
    "uniform mat4 uMVP;",
    "varying vec2 vTexCoord;",
    "varying vec4 vColor;",
    "varying float vLight;",
    "void main() {",
    "  gl_Position = uMVP * vec4(aPosition, 1.0);",
    "  vTexCoord = aTexCoord;",
    "  vColor = aColor;",
    "  float light = 0.82;",
    "  if (aNormal.y > 0.5) light = 1.0;",
    "  else if (aNormal.y < -0.5) light = 0.5;",
    "  else if (abs(aNormal.x) > 0.5) light = 0.65;",
    "  else if (abs(aNormal.z) > 0.5) light = 0.82;",
    "  vLight = light;",
    "}"
  ].join("\n");

  var fsVoxel = [
    "precision mediump float;",
    "varying vec2 vTexCoord;",
    "varying vec4 vColor;",
    "varying float vLight;",
    "uniform sampler2D uSampler;",
    "uniform bool uUseTexture;",
    "void main() {",
    "  vec4 base = vColor;",
    "  if (uUseTexture) {",
    "    vec4 tex = texture2D(uSampler, vTexCoord);",
    "    if (tex.a < 0.15) discard;",
    "    base = tex;",
    "  }",
    "  gl_FragColor = vec4(base.rgb * vLight, base.a);",
    "}"
  ].join("\n");

  _bpProgram = createProgram(gl, vsVoxel, fsVoxel);
  if (_bpProgram) {
    _bpProgram.aPosition = gl.getAttribLocation(_bpProgram, "aPosition");
    _bpProgram.aNormal = gl.getAttribLocation(_bpProgram, "aNormal");
    _bpProgram.aTexCoord = gl.getAttribLocation(_bpProgram, "aTexCoord");
    _bpProgram.aColor = gl.getAttribLocation(_bpProgram, "aColor");
    _bpProgram.uMVP = gl.getUniformLocation(_bpProgram, "uMVP");
    _bpProgram.uSampler = gl.getUniformLocation(_bpProgram, "uSampler");
    _bpProgram.uUseTexture = gl.getUniformLocation(_bpProgram, "uUseTexture");
  }

  // 2. Line Shaders for Ground Grid
  var vsLine = [
    "attribute vec3 aPosition;",
    "attribute vec4 aColor;",
    "uniform mat4 uMVP;",
    "varying vec4 vColor;",
    "void main() {",
    "  gl_Position = uMVP * vec4(aPosition, 1.0);",
    "  vColor = aColor;",
    "}"
  ].join("\n");

  var fsLine = [
    "precision mediump float;",
    "varying vec4 vColor;",
    "void main() {",
    "  gl_FragColor = vColor;",
    "}"
  ].join("\n");

  _bpGridProgram = createProgram(gl, vsLine, fsLine);
  if (_bpGridProgram) {
    _bpGridProgram.aPosition = gl.getAttribLocation(_bpGridProgram, "aPosition");
    _bpGridProgram.aColor = gl.getAttribLocation(_bpGridProgram, "aColor");
    _bpGridProgram.uMVP = gl.getUniformLocation(_bpGridProgram, "uMVP");
  }

  // 3. VBO Buffers
  _bpPosBuffer = gl.createBuffer();
  _bpNormalBuffer = gl.createBuffer();
  _bpTexBuffer = gl.createBuffer();
  _bpColorBuffer = gl.createBuffer();

  _bpGridPosBuffer = gl.createBuffer();
  _bpGridColorBuffer = gl.createBuffer();

  return true;
}

function isBlockTransparent(palEntry) {
  if (!palEntry) return true;
  var id = (palEntry.id || "").toLowerCase();
  if (id.includes("glass") || id.includes("leave") || id.includes("leaf") ||
      id.includes("water") || id.includes("ice") || id.includes("chain") ||
      id.includes("bar") || id.includes("fence") || id.includes("door") ||
      id.includes("torch") || id.includes("lantern") || id.includes("slab") ||
      id.includes("stair") || id.includes("carpet") || id.includes("pane") ||
      id.includes("trapdoor") || id.includes("air")) {
    return true;
  }
  return false;
}

function parseHexRgba(hex) {
  var c = (hex || "#888888").replace("#", "");
  if (c.length === 3) c = c[0] + c[0] + c[1] + c[1] + c[2] + c[2];
  var num = parseInt(c, 16);
  if (isNaN(num)) return [0.7, 0.7, 0.7, 1.0];
  return [(num >> 16) / 255.0, ((num >> 8) & 0xff) / 255.0, (num & 0xff) / 255.0, 1.0];
}

function buildTextureAtlas() {
  if (!_bpGL || !_bpData || !_bpData.palette) return;
  var gl = _bpGL;
  var palette = _bpData.palette;
  var tileSize = 16;
  var numTiles = palette.length * 2;
  var tilesPerRow = 16;
  while (tilesPerRow * tilesPerRow < numTiles && tilesPerRow < 64) {
    tilesPerRow *= 2;
  }
  var atlasSize = tilesPerRow * tileSize;

  if (!_bpAtlasCanvas) {
    _bpAtlasCanvas = document.createElement("canvas");
  }
  _bpAtlasCanvas.width = atlasSize;
  _bpAtlasCanvas.height = atlasSize;
  var actx = _bpAtlasCanvas.getContext("2d");
  actx.imageSmoothingEnabled = false;
  actx.clearRect(0, 0, atlasSize, atlasSize);

  var tileIdx = 0;
  palette.forEach(function (p) {
    ["top", "side"].forEach(function (face) {
      var col = tileIdx % tilesPerRow;
      var row = Math.floor(tileIdx / tilesPerRow);
      var x = col * tileSize;
      var y = row * tileSize;

      var img = p["_img_" + face];
      if (img && img.complete && img.naturalWidth > 0) {
        actx.drawImage(img, 0, 0, Math.min(16, img.naturalWidth), Math.min(16, img.naturalHeight), x, y, tileSize, tileSize);
      } else {
        actx.fillStyle = p.color || "#888888";
        actx.fillRect(x, y, tileSize, tileSize);
      }

      var eps = 0.1;
      var u0 = (x + eps) / atlasSize;
      var v0 = (y + eps) / atlasSize;
      var u1 = (x + tileSize - eps) / atlasSize;
      var v1 = (y + tileSize - eps) / atlasSize;

      if (face === "top") {
        p._uvTop = [u0, v0, u1, v1];
      } else {
        p._uvSide = [u0, v0, u1, v1];
      }

      tileIdx++;
    });
  });

  if (!_bpAtlasTexture) {
    _bpAtlasTexture = gl.createTexture();
  }
  gl.bindTexture(gl.TEXTURE_2D, _bpAtlasTexture);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, _bpAtlasCanvas);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
}

function rebuildBlueprintMesh() {
  if (!_bpData) return;
  if (!_bpGL) {
    // If WebGL is not available, Canvas 2D will render directly in requestBpRender
    return;
  }
  var gl = _bpGL;
  var voxels = _bpData.voxels || [];
  var palette = _bpData.palette || [];
  var dim = _bpData.dimensions || { x: 1, y: 1, z: 1 };
  var cx = dim.x / 2.0;
  var cy = (_bpData.minY + _bpData.maxY) / 2.0;
  var cz = dim.z / 2.0;

  // 1. Spatial Grid for High-Performance 6-direction Face Culling
  var spatial = {};
  for (var i = 0; i < voxels.length; i++) {
    var v = voxels[i];
    spatial[v[0] + "_" + v[1] + "_" + v[2]] = v[3];
  }

  var positions = [];
  var normals = [];
  var uvs = [];
  var colors = [];
  var renderedCount = 0;

  function pushQuad(p0, p1, p2, p3, norm, uvRect, rgba) {
    var u0 = uvRect[0], v0 = uvRect[1], u1 = uvRect[2], v1 = uvRect[3];
    var qVerts = [
      p0, [u0, v1],
      p1, [u1, v1],
      p2, [u1, v0],
      p0, [u0, v1],
      p2, [u1, v0],
      p3, [u0, v0],
    ];
    for (var vi = 0; vi < 6; vi++) {
      var pt = qVerts[vi * 2];
      var uv = qVerts[vi * 2 + 1];
      positions.push(pt[0], pt[1], pt[2]);
      normals.push(norm[0], norm[1], norm[2]);
      uvs.push(uv[0], uv[1]);
      colors.push(rgba[0], rgba[1], rgba[2], rgba[3]);
    }
  }

  for (var j = 0; j < voxels.length; j++) {
    var vox = voxels[j];
    var vx = vox[0], vy = vox[1], vz = vox[2], palIdx = vox[3];
    if (vy < _bpSliceMin || vy > _bpSliceMax) continue;
    if (_bpVisiblePalette[palIdx] === false) continue;

    renderedCount++;
    var palEntry = palette[palIdx] || {};
    var rgba = parseHexRgba(palEntry.color || "#888888");
    var uvTop = palEntry._uvTop || [0, 0, 1, 1];
    var uvSide = palEntry._uvSide || [0, 0, 1, 1];

    var bx = vx - cx + 0.5;
    var by = vy - cy + 0.5;
    var bz = vz - cz + 0.5;

    var x0 = bx - 0.5, x1 = bx + 0.5;
    var y0 = by - 0.5, y1 = by + 0.5;
    var z0 = bz - 0.5, z1 = bz + 0.5;

    // Top (+Y)
    var nTop = spatial[vx + "_" + (vy + 1) + "_" + vz];
    if (vy + 1 > _bpSliceMax || nTop === undefined || _bpVisiblePalette[nTop] === false || isBlockTransparent(palette[nTop])) {
      pushQuad(
        [x0, y1, z1], [x1, y1, z1], [x1, y1, z0], [x0, y1, z0],
        [0, 1, 0], uvTop, rgba
      );
    }

    // Bottom (-Y)
    var nBot = spatial[vx + "_" + (vy - 1) + "_" + vz];
    if (vy - 1 < _bpSliceMin || nBot === undefined || _bpVisiblePalette[nBot] === false || isBlockTransparent(palette[nBot])) {
      pushQuad(
        [x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1],
        [0, -1, 0], uvTop, rgba
      );
    }

    // East (+X)
    var nEast = spatial[(vx + 1) + "_" + vy + "_" + vz];
    if (nEast === undefined || _bpVisiblePalette[nEast] === false || isBlockTransparent(palette[nEast])) {
      pushQuad(
        [x1, y0, z1], [x1, y0, z0], [x1, y1, z0], [x1, y1, z1],
        [1, 0, 0], uvSide, rgba
      );
    }

    // West (-X)
    var nWest = spatial[(vx - 1) + "_" + vy + "_" + vz];
    if (nWest === undefined || _bpVisiblePalette[nWest] === false || isBlockTransparent(palette[nWest])) {
      pushQuad(
        [x0, y0, z0], [x0, y0, z1], [x0, y1, z1], [x0, y1, z0],
        [-1, 0, 0], uvSide, rgba
      );
    }

    // South (+Z)
    var nSouth = spatial[vx + "_" + vy + "_" + (vz + 1)];
    if (nSouth === undefined || _bpVisiblePalette[nSouth] === false || isBlockTransparent(palette[nSouth])) {
      pushQuad(
        [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1],
        [0, 0, 1], uvSide, rgba
      );
    }

    // North (-Z)
    var nNorth = spatial[vx + "_" + vy + "_" + (vz - 1)];
    if (nNorth === undefined || _bpVisiblePalette[nNorth] === false || isBlockTransparent(palette[nNorth])) {
      pushQuad(
        [x1, y0, z0], [x0, y0, z0], [x0, y1, z0], [x1, y1, z0],
        [0, 0, -1], uvSide, rgba
      );
    }
  }

  var countBadge = $("bpVoxelCountBadge");
  if (countBadge) {
    countBadge.textContent = renderedCount + " / " + _bpData.totalBlocks + " 体素";
  }

  _bpVoxelVertexCount = positions.length / 3;

  gl.bindBuffer(gl.ARRAY_BUFFER, _bpPosBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(positions), gl.DYNAMIC_DRAW);

  gl.bindBuffer(gl.ARRAY_BUFFER, _bpNormalBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(normals), gl.DYNAMIC_DRAW);

  gl.bindBuffer(gl.ARRAY_BUFFER, _bpTexBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(uvs), gl.DYNAMIC_DRAW);

  gl.bindBuffer(gl.ARRAY_BUFFER, _bpColorBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(colors), gl.DYNAMIC_DRAW);

  rebuildGridMesh();
}

function rebuildGridMesh() {
  if (!_bpData || !_bpGL) return;
  var gl = _bpGL;
  var dim = _bpData.dimensions || { x: 1, y: 1, z: 1 };
  var cx = dim.x / 2.0;
  var cy = (_bpData.minY + _bpData.maxY) / 2.0;
  var cz = dim.z / 2.0;
  var gy = _bpData.minY - cy;

  var step = Math.max(1, Math.floor(Math.max(dim.x, dim.z) / 10));
  var x0 = -cx, x1 = dim.x - cx;
  var z0 = -cz, z1 = dim.z - cz;

  var linePositions = [];
  var lineColors = [];
  var gridAlpha = 0.15;

  for (var z = 0; z <= dim.z; z += step) {
    var lz = z - cz;
    linePositions.push(x0, gy, lz, x1, gy, lz);
    lineColors.push(0.6, 0.7, 0.9, gridAlpha, 0.6, 0.7, 0.9, gridAlpha);
  }
  for (var x = 0; x <= dim.x; x += step) {
    var lx = x - cx;
    linePositions.push(lx, gy, z0, lx, gy, z1);
    lineColors.push(0.6, 0.7, 0.9, gridAlpha, 0.6, 0.7, 0.9, gridAlpha);
  }

  _bpGridVertexCount = linePositions.length / 3;
  gl.bindBuffer(gl.ARRAY_BUFFER, _bpGridPosBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(linePositions), gl.STATIC_DRAW);

  gl.bindBuffer(gl.ARRAY_BUFFER, _bpGridColorBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(lineColors), gl.STATIC_DRAW);
}

function renderBlueprintWebGL() {
  if (!_bpGL || !_bpData) return;
  var gl = _bpGL;
  var rect = _bpCanvas.getBoundingClientRect();
  var dpr = window.devicePixelRatio || 1;
  var w = Math.floor(rect.width * dpr);
  var h = Math.floor(rect.height * dpr);
  if (w <= 0 || h <= 0) return;

  if (_bpCanvas.width !== w || _bpCanvas.height !== h) {
    _bpCanvas.width = w;
    _bpCanvas.height = h;
  }
  gl.viewport(0, 0, w, h);

  gl.enable(gl.DEPTH_TEST);
  gl.depthFunc(gl.LEQUAL);
  gl.enable(gl.CULL_FACE);
  gl.cullFace(gl.BACK);

  gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

  gl.clearColor(0.082, 0.094, 0.118, 1.0);
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

  // Compute Camera Matrices
  var cosPitch = Math.cos(_bpRotX);
  var sinPitch = Math.sin(_bpRotX);
  var cosYaw = Math.cos(_bpRotY);
  var sinYaw = Math.sin(_bpRotY);

  var ex = _bpDistance * cosPitch * sinYaw;
  var ey = _bpDistance * sinPitch;
  var ez = _bpDistance * cosPitch * cosYaw;

  var fx = -ex, fy = -ey, fz = -ez;
  var flen = Math.hypot(fx, fy, fz) || 1;
  fx /= flen; fy /= flen; fz /= flen;

  var rx = -fz, ry = 0, rz = fx;
  var rlen = Math.hypot(rx, rz) || 1;
  rx /= rlen; rz /= rlen;

  var ux = ry * fz - rz * fy;
  var uy = rz * fx - rx * fz;
  var uz = rx * fy - ry * fx;

  var targetX = rx * _bpPanX + ux * _bpPanY;
  var targetY = ry * _bpPanX + uy * _bpPanY;
  var targetZ = rz * _bpPanX + uz * _bpPanY;

  var eyeX = targetX + ex;
  var eyeY = targetY + ey;
  var eyeZ = targetZ + ez;

  var viewMat = Mat4.create();
  Mat4.lookAt(viewMat, [eyeX, eyeY, eyeZ], [targetX, targetY, targetZ], [ux, uy, uz]);

  var projMat = Mat4.create();
  var aspect = w / h;
  var farDist = Math.max(3000, _bpDistance * 8);
  if (_bpCameraMode === "persp") {
    Mat4.perspective(projMat, 45 * Math.PI / 180, aspect, 0.5, farDist);
  } else {
    var orthoH = _bpDistance * 0.5;
    var orthoW = orthoH * aspect;
    Mat4.ortho(projMat, -orthoW, orthoW, -orthoH, orthoH, -farDist, farDist);
  }

  var mvpMat = Mat4.create();
  Mat4.multiply(mvpMat, projMat, viewMat);

  // 1. Draw Grid Lines
  if (_bpGridVertexCount > 0 && _bpGridProgram) {
    gl.useProgram(_bpGridProgram);
    gl.uniformMatrix4fv(_bpGridProgram.uMVP, false, mvpMat);

    gl.bindBuffer(gl.ARRAY_BUFFER, _bpGridPosBuffer);
    gl.vertexAttribPointer(_bpGridProgram.aPosition, 3, gl.FLOAT, false, 0, 0);
    gl.enableVertexAttribArray(_bpGridProgram.aPosition);

    gl.bindBuffer(gl.ARRAY_BUFFER, _bpGridColorBuffer);
    gl.vertexAttribPointer(_bpGridProgram.aColor, 4, gl.FLOAT, false, 0, 0);
    gl.enableVertexAttribArray(_bpGridProgram.aColor);

    gl.drawArrays(gl.LINES, 0, _bpGridVertexCount);
  }

  // 2. Draw Voxels (Single Draw Call)
  if (_bpVoxelVertexCount > 0 && _bpProgram) {
    gl.useProgram(_bpProgram);
    gl.uniformMatrix4fv(_bpProgram.uMVP, false, mvpMat);
    gl.uniform1i(_bpProgram.uUseTexture, _bpShowTextures ? 1 : 0);

    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, _bpAtlasTexture);
    gl.uniform1i(_bpProgram.uSampler, 0);

    gl.bindBuffer(gl.ARRAY_BUFFER, _bpPosBuffer);
    gl.vertexAttribPointer(_bpProgram.aPosition, 3, gl.FLOAT, false, 0, 0);
    gl.enableVertexAttribArray(_bpProgram.aPosition);

    gl.bindBuffer(gl.ARRAY_BUFFER, _bpNormalBuffer);
    gl.vertexAttribPointer(_bpProgram.aNormal, 3, gl.FLOAT, false, 0, 0);
    gl.enableVertexAttribArray(_bpProgram.aNormal);

    gl.bindBuffer(gl.ARRAY_BUFFER, _bpTexBuffer);
    gl.vertexAttribPointer(_bpProgram.aTexCoord, 2, gl.FLOAT, false, 0, 0);
    gl.enableVertexAttribArray(_bpProgram.aTexCoord);

    gl.bindBuffer(gl.ARRAY_BUFFER, _bpColorBuffer);
    gl.vertexAttribPointer(_bpProgram.aColor, 4, gl.FLOAT, false, 0, 0);
    gl.enableVertexAttribArray(_bpProgram.aColor);

    gl.drawArrays(gl.TRIANGLES, 0, _bpVoxelVertexCount);
  }
}

// Canvas 2D Fallback Rasterizer
function drawTexturedParallelogram(ctx, img, x0, y0, ux, uy, vx, vy, tint) {
  ctx.save();
  ctx.transform(ux / 16.0, uy / 16.0, vx / 16.0, vy / 16.0, x0, y0);
  var sw = Math.min(16, img.naturalWidth || 16);
  var sh = Math.min(16, img.naturalHeight || 16);
  ctx.drawImage(img, 0, 0, sw, sh, 0, 0, 16, 16);
  if (tint) {
    ctx.fillStyle = tint;
    ctx.fillRect(0, 0, 16, 16);
  }
  ctx.restore();
}

function shadeHex(hex, percent) {
  var clean = (hex || "#888888").replace("#", "");
  if (clean.length === 3) {
    clean = clean[0] + clean[0] + clean[1] + clean[1] + clean[2] + clean[2];
  }
  var num = parseInt(clean, 16);
  if (isNaN(num)) num = 0x888888;
  var r = (num >> 16) + Math.round(255 * (percent / 100));
  var g = ((num >> 8) & 0x00ff) + Math.round(255 * (percent / 100));
  var b = (num & 0x0000ff) + Math.round(255 * (percent / 100));
  r = Math.min(255, Math.max(0, r));
  g = Math.min(255, Math.max(0, g));
  b = Math.min(255, Math.max(0, b));
  return "#" + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
}

function getShadedColors(hex) {
  if (_bpColorCache[hex]) return _bpColorCache[hex];
  var res = {
    top: shadeHex(hex, 18),
    front: hex,
    side: shadeHex(hex, -22),
  };
  _bpColorCache[hex] = res;
  return res;
}

function renderBlueprintCanvas2D() {
  if (!_bpData || !_bpCanvas || !_bpCtx) return;
  var rect = _bpCanvas.getBoundingClientRect();
  var dpr = window.devicePixelRatio || 1;
  var w = Math.floor(rect.width * dpr);
  var h = Math.floor(rect.height * dpr);
  if (w <= 0 || h <= 0) return;
  if (_bpCanvas.width !== w || _bpCanvas.height !== h) {
    _bpCanvas.width = w; _bpCanvas.height = h;
  }
  var ctx = _bpCtx;
  ctx.save();
  ctx.scale(dpr, dpr);
  var vw = rect.width, vh = rect.height;
  ctx.fillStyle = "#15181e";
  ctx.fillRect(0, 0, vw, vh);

  var dim = _bpData.dimensions || { x: 1, y: 1, z: 1 };
  var cx = dim.x / 2.0, cy = (_bpData.minY + _bpData.maxY) / 2.0, cz = dim.z / 2.0;
  var cosY = Math.cos(_bpRotY), sinY = Math.sin(_bpRotY);
  var cosX = Math.cos(_bpRotX), sinX = Math.sin(_bpRotX);
  var centerX = vw / 2.0 + _bpPanX, centerY = vh / 2.0 + _bpPanY;
  var s = Math.max(1.5, Math.min(200, (vw * 0.45) / Math.max(1, _bpDistance)));

  var voxels = _bpData.voxels || [];
  var list = [];
  for (var i = 0; i < voxels.length; i++) {
    var v = voxels[i];
    if (v[1] < _bpSliceMin || v[1] > _bpSliceMax || _bpVisiblePalette[v[3]] === false) continue;
    var dx = v[0] - cx + 0.5, dy = v[1] - cy + 0.5, dz = v[2] - cz + 0.5;
    var x1 = dx * cosY - dz * sinY;
    var z1 = dx * sinY + dz * cosY;
    var y2 = dy * cosX - z1 * sinX;
    var z2 = dy * sinX + z1 * cosX;
    list.push({ x1: x1, y2: y2, z2: z2, pal: v[3] });
  }
  var countBadge = $("bpVoxelCountBadge");
  if (countBadge) countBadge.textContent = list.length + " / " + _bpData.totalBlocks + " 体素";
  list.sort(function (a, b) { return a.z2 - b.z2; });

  for (var j = 0; j < list.length; j++) {
    var it = list[j];
    var palEntry = _bpData.palette[it.pal] || {};
    ctx.fillStyle = palEntry.color || "#888";
    ctx.fillRect(centerX + it.x1 * s - s / 2, centerY - it.y2 * s - s / 2, s, s);
  }
  ctx.restore();
}

// Rendering Loop with Smooth Inertia
function requestBpRender() {
  if (_bpIsRendering) return;
  _bpIsRendering = true;
  requestAnimationFrame(bpRenderLoop);
}

function bpRenderLoop() {
  var damp = 0.25;
  var dX = _bpTargetRotX - _bpRotX;
  var dY = _bpTargetRotY - _bpRotY;
  var dPX = _bpTargetPanX - _bpPanX;
  var dPY = _bpTargetPanY - _bpPanY;
  var dDist = _bpTargetDistance - _bpDistance;

  _bpRotX += dX * damp;
  _bpRotY += dY * damp;
  _bpPanX += dPX * damp;
  _bpPanY += dPY * damp;
  _bpDistance += dDist * damp;

  var isMoving = Math.abs(dX) > 0.0001 || Math.abs(dY) > 0.0001 ||
                 Math.abs(dPX) > 0.001 || Math.abs(dPY) > 0.001 ||
                 Math.abs(dDist) > 0.005;

  if (_bpGL) {
    renderBlueprintWebGL();
  } else {
    renderBlueprintCanvas2D();
  }

  if (isMoving || _bpIsDragging) {
    requestAnimationFrame(bpRenderLoop);
  } else {
    _bpIsRendering = false;
  }
}

function updateTextureToggleBtn() {
  var btn = $("bpToggleTextureBtn");
  if (!btn) return;
  var text = _bpShowTextures ? (t("studio.bpTextureOn") || "纹理: 开") : (t("studio.bpTextureOff") || "纹理: 关");
  btn.innerHTML = '<span>' + escapeHtml(text) + '</span>';
  btn.classList.toggle("btn-primary", _bpShowTextures);
}

function updateCameraToggleBtn() {
  var btn = $("bpToggleCameraBtn");
  if (!btn) return;
  var isPersp = _bpCameraMode === "persp";
  var text = isPersp ? (t("studio.bpCamPersp") || "透视视角") : (t("studio.bpCamOrtho") || "正交等距");
  btn.innerHTML = '<span>' + escapeHtml(text) + '</span>';
}

function toggleBlueprintCameraMode() {
  _bpCameraMode = (_bpCameraMode === "persp" ? "ortho" : "persp");
  updateCameraToggleBtn();
  requestBpRender();
}

function updateSliceLabels() {
  var lbl = $("bpSliceLabel");
  if (lbl) lbl.textContent = "Y: " + _bpSliceMin + " ~ " + _bpSliceMax;
  var minV = $("bpSliceMinVal");
  if (minV) minV.textContent = _bpSliceMin;
  var maxV = $("bpSliceMaxVal");
  if (maxV) maxV.textContent = _bpSliceMax;
}

function syncPaletteCheckboxes() {
  document.querySelectorAll(".bp-pal-checkbox").forEach(function (cb) {
    var idx = parseInt(cb.dataset.idx, 10);
    cb.checked = _bpVisiblePalette[idx] !== false;
  });
}

function initBlueprintViewerEvents() {
  _bpCanvas = $("blueprint3dCanvas");
  if (!_bpCanvas) return;

  initWebGL();

  // 关闭按钮
  var closeBtn = $("bpModalCloseBtn");
  if (closeBtn) closeBtn.addEventListener("click", closeBlueprintViewer);

  var modal = $("blueprintViewerModal");
  if (modal) {
    modal.addEventListener("click", function (e) {
      if (e.target === modal) closeBlueprintViewer();
    });
  }

  // 重置视角
  var resetBtn = $("bpResetCameraBtn");
  if (resetBtn) resetBtn.addEventListener("click", resetBlueprintCamera);

  // 切换视角模式 (透视 / 正交)
  var camBtn = $("bpToggleCameraBtn");
  if (camBtn) {
    camBtn.addEventListener("click", toggleBlueprintCameraMode);
  }

  // 切换真实方块纹理
  var toggleTexBtn = $("bpToggleTextureBtn");
  if (toggleTexBtn) {
    toggleTexBtn.addEventListener("click", function () {
      _bpShowTextures = !_bpShowTextures;
      updateTextureToggleBtn();
      requestBpRender();
    });
  }

  window.addEventListener("keydown", function (e) {
    var modal = $("blueprintViewerModal");
    if (!modal || modal.style.display === "none") return;
    if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA")) return;
    if (e.key === "t" || e.key === "T") {
      _bpShowTextures = !_bpShowTextures;
      updateTextureToggleBtn();
      requestBpRender();
    } else if (e.key === "p" || e.key === "P") {
      toggleBlueprintCameraMode();
    }
  });

  // 导出独立离线 HTML 网页
  var exportHtmlBtn = $("bpExportHtmlBtn");
  if (exportHtmlBtn) {
    exportHtmlBtn.addEventListener("click", function () {
      if (!_bpData) return;
      window.location.href = "/api/studio/blueprint-html?file=" + encodeURIComponent(_bpData.name);
    });
  }

  // 本地直接选择蓝图文件进行 3D 预览
  var localPickBtn = $("bpLocalPickBtn");
  var localFileInput = $("bpLocalFileInput");
  if (localPickBtn && localFileInput) {
    localPickBtn.addEventListener("click", function () {
      localFileInput.click();
    });
    localFileInput.addEventListener("change", function () {
      if (localFileInput.files.length) {
        previewLocalBlueprintFile(localFileInput.files[0]);
        localFileInput.value = "";
      }
    });
  }

  // 切片滑块
  var sMin = $("bpSliceMin");
  var sMax = $("bpSliceMax");
  if (sMin && sMax) {
    sMin.addEventListener("input", function () {
      var val = parseInt(sMin.value, 10);
      if (val > _bpSliceMax) {
        sMin.value = _bpSliceMax;
        val = _bpSliceMax;
      }
      _bpSliceMin = val;
      updateSliceLabels();
      rebuildBlueprintMesh();
      requestBpRender();
    });
    sMax.addEventListener("input", function () {
      var val = parseInt(sMax.value, 10);
      if (val < _bpSliceMin) {
        sMax.value = _bpSliceMin;
        val = _bpSliceMin;
      }
      _bpSliceMax = val;
      updateSliceLabels();
      rebuildBlueprintMesh();
      requestBpRender();
    });
  }

  // 快捷切片按钮
  var upBtn = $("bpSliceSingleUpBtn");
  if (upBtn) {
    upBtn.addEventListener("click", function () {
      if (!_bpData) return;
      if (_bpSliceMax < _bpData.maxY) {
        _bpSliceMax++;
        _bpSliceMin = _bpSliceMax;
        if (sMin) sMin.value = _bpSliceMin;
        if (sMax) sMax.value = _bpSliceMax;
        updateSliceLabels();
        rebuildBlueprintMesh();
        requestBpRender();
      }
    });
  }

  var downBtn = $("bpSliceSingleDownBtn");
  if (downBtn) {
    downBtn.addEventListener("click", function () {
      if (!_bpData) return;
      if (_bpSliceMin > _bpData.minY) {
        _bpSliceMin--;
        _bpSliceMax = _bpSliceMin;
        if (sMin) sMin.value = _bpSliceMin;
        if (sMax) sMax.value = _bpSliceMax;
        updateSliceLabels();
        rebuildBlueprintMesh();
        requestBpRender();
      }
    });
  }

  var allBtn = $("bpSliceResetBtn");
  if (allBtn) {
    allBtn.addEventListener("click", function () {
      if (!_bpData) return;
      _bpSliceMin = _bpData.minY;
      _bpSliceMax = _bpData.maxY;
      if (sMin) sMin.value = _bpSliceMin;
      if (sMax) sMax.value = _bpSliceMax;
      updateSliceLabels();
      rebuildBlueprintMesh();
      requestBpRender();
    });
  }

  // 材质全选 / 反选
  var selAll = $("bpPaletteSelectAll");
  if (selAll) {
    selAll.addEventListener("click", function () {
      if (!_bpData) return;
      for (var i = 0; i < _bpData.palette.length; i++) {
        _bpVisiblePalette[i] = true;
      }
      syncPaletteCheckboxes();
      rebuildBlueprintMesh();
      requestBpRender();
    });
  }

  var clearAll = $("bpPaletteClearAll");
  if (clearAll) {
    clearAll.addEventListener("click", function () {
      if (!_bpData) return;
      for (var i = 0; i < _bpData.palette.length; i++) {
        _bpVisiblePalette[i] = !_bpVisiblePalette[i];
      }
      syncPaletteCheckboxes();
      rebuildBlueprintMesh();
      requestBpRender();
    });
  }

  // 游戏内建造
  var buildBtn = $("bpModalBuildInGameBtn");
  if (buildBtn) {
    buildBtn.addEventListener("click", function () {
      if (!_bpData) return;
      api("/studio/action", {
        method: "POST",
        body: JSON.stringify({
          action: "build_ezmatic",
          category: "ezmatic",
          filename: _bpData.name,
        }),
      }).then(function (res) {
        toast(res.message || t("studio.actionSent"), res.ok ? "ok" : "err");
      });
    });
  }

  // 交互控制: 鼠标
  var wrapper = $("bpCanvasWrapper");
  if (wrapper) {
    wrapper.addEventListener("contextmenu", function (e) { e.preventDefault(); });
    wrapper.addEventListener("mousedown", function (e) {
      _bpIsDragging = true;
      _bpLastMouseX = e.clientX;
      _bpLastMouseY = e.clientY;
      _bpDragMode = (e.button === 2 || e.shiftKey) ? "pan" : "rotate";
      wrapper.style.cursor = _bpDragMode === "pan" ? "move" : "grabbing";
    });

    window.addEventListener("mousemove", function (e) {
      if (!_bpIsDragging) return;
      var dx = e.clientX - _bpLastMouseX;
      var dy = e.clientY - _bpLastMouseY;
      _bpLastMouseX = e.clientX;
      _bpLastMouseY = e.clientY;

      if (_bpDragMode === "rotate") {
        _bpTargetRotY -= dx * 0.008;
        _bpTargetRotX += dy * 0.008;
        _bpTargetRotX = Math.max(-1.48, Math.min(1.48, _bpTargetRotX));
      } else {
        var panSpeed = _bpDistance * 0.0018;
        _bpTargetPanX -= dx * panSpeed;
        _bpTargetPanY += dy * panSpeed;
      }
      requestBpRender();
    });

    window.addEventListener("mouseup", function () {
      if (_bpIsDragging) {
        _bpIsDragging = false;
        if (wrapper) wrapper.style.cursor = "grab";
      }
    });

    wrapper.addEventListener("wheel", function (e) {
      e.preventDefault();
      var factor = e.deltaY < 0 ? 0.88 : 1.14;
      _bpTargetDistance = Math.max(2.0, Math.min(600.0, _bpTargetDistance * factor));
      requestBpRender();
    }, { passive: false });

    // 触摸控制
    wrapper.addEventListener("touchstart", function (e) {
      if (e.touches.length === 1) {
        _bpIsDragging = true;
        _bpDragMode = "rotate";
        _bpLastMouseX = e.touches[0].clientX;
        _bpLastMouseY = e.touches[0].clientY;
      } else if (e.touches.length === 2) {
        _bpIsDragging = true;
        _bpDragMode = "pinch";
        var t1 = e.touches[0], t2 = e.touches[1];
        _bpPinchDist = Math.hypot(t1.clientX - t2.clientX, t1.clientY - t2.clientY);
        _bpLastMouseX = (t1.clientX + t2.clientX) / 2;
        _bpLastMouseY = (t1.clientY + t2.clientY) / 2;
      }
    }, { passive: false });

    wrapper.addEventListener("touchmove", function (e) {
      if (!_bpIsDragging) return;
      e.preventDefault();
      if (e.touches.length === 1 && _bpDragMode === "rotate") {
        var dx = e.touches[0].clientX - _bpLastMouseX;
        var dy = e.touches[0].clientY - _bpLastMouseY;
        _bpLastMouseX = e.touches[0].clientX;
        _bpLastMouseY = e.touches[0].clientY;
        _bpTargetRotY -= dx * 0.01;
        _bpTargetRotX += dy * 0.01;
        _bpTargetRotX = Math.max(-1.48, Math.min(1.48, _bpTargetRotX));
        requestBpRender();
      } else if (e.touches.length === 2) {
        var t1 = e.touches[0], t2 = e.touches[1];
        var dist = Math.hypot(t1.clientX - t2.clientX, t1.clientY - t2.clientY);
        var curX = (t1.clientX + t2.clientX) / 2;
        var curY = (t1.clientY + t2.clientY) / 2;
        if (_bpPinchDist > 0) {
          var factor = _bpPinchDist / dist;
          _bpTargetDistance = Math.max(2.0, Math.min(600.0, _bpTargetDistance * factor));
        }
        var pSpeed = _bpDistance * 0.0018;
        _bpTargetPanX -= (curX - _bpLastMouseX) * pSpeed;
        _bpTargetPanY += (curY - _bpLastMouseY) * pSpeed;
        _bpPinchDist = dist;
        _bpLastMouseX = curX;
        _bpLastMouseY = curY;
        requestBpRender();
      }
    }, { passive: false });

    wrapper.addEventListener("touchend", function () {
      _bpIsDragging = false;
    });
  }

  // 窗口大小变动重绘
  window.addEventListener("resize", function () {
    var modal = $("blueprintViewerModal");
    if (modal && modal.style.display !== "none") {
      requestBpRender();
    }
  });
}

function setupBlueprintViewerWithData(res, filename, isLocal) {
  _bpData = res;
  _bpData.isLocal = !!isLocal;
  _bpSliceMin = res.minY;
  _bpSliceMax = res.maxY;

  var titleEl = $("bpModalTitle");
  if (titleEl) {
    var tag = isLocal ? 'LOCAL' : 'LITEMATIC';
    titleEl.innerHTML = '<span>' + escapeHtml(filename) + '</span><span class="badge-sec-safe" style="font-size:10px;">' + tag + '</span>';
  }

  _bpVisiblePalette = {};
  for (var i = 0; i < res.palette.length; i++) {
    _bpVisiblePalette[i] = true;
  }

  var sMin = $("bpSliceMin");
  var sMax = $("bpSliceMax");
  if (sMin) {
    sMin.min = res.minY;
    sMin.max = res.maxY;
    sMin.value = res.minY;
  }
  if (sMax) {
    sMax.min = res.minY;
    sMax.max = res.maxY;
    sMax.value = res.maxY;
  }
  updateSliceLabels();

  // 预载真实方块纹理图像并生成 Atlas
  _bpTexturesLoaded = false;
  var toLoad = 0, loaded = 0;
  if (res.palette) {
    res.palette.forEach(function (p) {
      if (p.textures) {
        ["top", "side"].forEach(function (face) {
          var url = p.textures[face];
          if (url) {
            toLoad++;
            var img = new Image();
            img.crossOrigin = "anonymous";
            img.onload = img.onerror = function () {
              loaded++;
              if (loaded >= toLoad) {
                _bpTexturesLoaded = true;
                buildTextureAtlas();
                requestBpRender();
              }
            };
            img.src = url;
            p["_img_" + face] = img;
          }
        });
      }
    });
  }

  buildTextureAtlas();
  if (toLoad === 0) _bpTexturesLoaded = true;
  updateTextureToggleBtn();
  updateCameraToggleBtn();

  renderBlueprintPaletteList(res.palette);
  rebuildBlueprintMesh();
  resetBlueprintCamera();

  var loading = $("bpCanvasLoading");
  if (loading) loading.style.display = "none";
}

function openBlueprint3dViewer(filename) {
  var modal = $("blueprintViewerModal");
  if (!modal) return;
  modal.style.display = "flex";

  var titleEl = $("bpModalTitle");
  if (titleEl) {
    titleEl.innerHTML = '<span>' + escapeHtml(filename) + '</span><span class="badge-sec-safe" style="font-size:10px;">LITEMATIC</span>';
  }
  var loading = $("bpCanvasLoading");
  if (loading) loading.style.display = "flex";

  var loadingText = $("bpLoadingText");
  if (loadingText) loadingText.textContent = "正在解析蓝图三维体素...";

  api("/studio/blueprint-voxels?category=ezmatic&file=" + encodeURIComponent(filename))
    .then(function (res) {
      if (!res.ok) {
        toast(res.message || "解析蓝图失败", "err");
        closeBlueprintViewer();
        return;
      }
      setupBlueprintViewerWithData(res, filename, false);
    })
    .catch(function (err) {
      toast("网络请求失败: " + err, "err");
      closeBlueprintViewer();
    });
}

function previewLocalBlueprintFile(file) {
  if (!file) return;
  var modal = $("blueprintViewerModal");
  if (!modal) return;
  modal.style.display = "flex";

  var loading = $("bpCanvasLoading");
  if (loading) loading.style.display = "flex";
  var loadingText = $("bpLoadingText");
  if (loadingText) loadingText.textContent = "正在读取并解析本地蓝图...";

  var reader = new FileReader();
  reader.onload = function (e) {
    var base64 = e.target.result.split(",")[1];
    api("/studio/blueprint-voxels", {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        dataBase64: base64,
      }),
    }).then(function (res) {
      if (!res.ok) {
        toast(res.message || "解析本地蓝图失败", "err");
        closeBlueprintViewer();
        return;
      }
      setupBlueprintViewerWithData(res, file.name, true);
    }).catch(function (err) {
      toast("本地蓝图请求失败: " + err, "err");
      closeBlueprintViewer();
    });
  };
  reader.readAsDataURL(file);
}

function closeBlueprintViewer() {
  var modal = $("blueprintViewerModal");
  if (modal) modal.style.display = "none";
  _bpIsRendering = false;
  _bpData = null;
}

function resetBlueprintCamera() {
  if (!_bpData) return;
  _bpRotX = _bpTargetRotX = 0.55;
  _bpRotY = _bpTargetRotY = 0.785;
  _bpPanX = _bpTargetPanX = 0;
  _bpPanY = _bpTargetPanY = 0;

  var dim = _bpData.dimensions || { x: 1, y: 1, z: 1 };
  var maxDim = Math.max(dim.x, dim.y, dim.z, 1);
  _bpDistance = _bpTargetDistance = Math.max(10, maxDim * 2.2);

  requestBpRender();
}

function renderBlueprintPaletteList(palette) {
  var container = $("bpPaletteContainer");
  if (!container) return;
  if (!palette || !palette.length) {
    container.innerHTML = '<div class="td-faint" style="font-size:12px;padding:8px;">暂无材质</div>';
    return;
  }

  container.innerHTML = palette.map(function (item, idx) {
    var iconHtml = "";
    var texSrc = item.textures ? (item.textures.side || item.textures.top) : null;
    if (texSrc) {
      iconHtml = '<img src="' + escapeHtml(texSrc) + '" style="width:14px;height:14px;image-rendering:pixelated;object-fit:cover;border-radius:2px;border:1px solid rgba(0,0,0,0.2);flex-shrink:0;" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'inline-block\';" /><span style="display:none;width:12px;height:12px;border-radius:2px;background:' + escapeHtml(item.color) + ';border:1px solid rgba(0,0,0,0.2);flex-shrink:0;"></span>';
    } else {
      iconHtml = '<span style="display:inline-block;width:12px;height:12px;border-radius:2px;background:' + escapeHtml(item.color) + ';border:1px solid rgba(0,0,0,0.2);flex-shrink:0;"></span>';
    }
    return '<label style="display:flex;align-items:center;gap:8px;padding:4px 8px;border-radius:6px;background:var(--input-bg);font-size:11px;cursor:pointer;border:1px solid var(--card-border);">'
      + '<input type="checkbox" class="bp-pal-checkbox" data-idx="' + idx + '" checked style="cursor:pointer;" />'
      + iconHtml
      + '<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + escapeHtml(item.id) + '">' + escapeHtml(item.shortId || item.id) + '</span>'
      + '<strong style="color:var(--text-dim);font-size:10px;">×' + item.count + '</strong>'
      + '</label>';
  }).join("");

  container.querySelectorAll(".bp-pal-checkbox").forEach(function (cb) {
    cb.addEventListener("change", function () {
      var idx = parseInt(cb.dataset.idx, 10);
      _bpVisiblePalette[idx] = cb.checked;
      rebuildBlueprintMesh();
      requestBpRender();
    });
  });
}

