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
      + '<div class="row gap-10" style="margin-top:8px;justify-content:space-between;">'
      + '  <button class="btn btn-sm ezmatic-action-btn" data-action="preview_ezmatic" data-name="' + escapeHtml(item.name) + '">🔮 ' + (t("studio.previewHolo") || "投影") + '</button>'
      + '  <button class="btn btn-sm btn-primary ezmatic-action-btn" data-action="build_ezmatic" data-name="' + escapeHtml(item.name) + '">🔨 ' + (t("studio.buildHolo") || "建造") + '</button>'
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

  // 3) Ezmatic 蓝图操作按钮 (预览/建造)
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

