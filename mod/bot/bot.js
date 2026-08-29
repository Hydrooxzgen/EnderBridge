#!/usr/bin/env node
/**
 * EnderBridge 假人 Bot
 *
 * 使用 bedrock-protocol 连接 MCBE 服务器,作为独立玩家出现在 Tab 列表和游戏世界中。
 * 通过 stdin/stdout JSON 行协议与 Python 主进程通信。
 *
 * 协议:
 *   stdin  → JSON 行: {"type":"spawn","name":"xxx","x":0,"y":0,"z":0}
 *   stdout → JSON 行: {"type":"join"} | {"type":"error","message":"xxx"} | ...
 */

import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const { createClient } = require('bedrock-protocol');

// ========== 全局状态 ==========
let client = null;
let botReady = false;
let username = 'FakeBot';
const players = {};   // name → { uuid, xuid, x, y, z }
const LOG_PREFIX = '[Bot]';

function log(...args) {
  process.stderr.write(`${LOG_PREFIX} ${args.join(' ')}\n`);
}

function send(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
}

// ========== 启动 ==========

async function main() {
  // 1. 从 stdin 第一行读取配置
  const configLine = await readLine();
  let config;
  try {
    config = JSON.parse(configLine);
  } catch (e) {
    send({ type: 'error', message: `配置解析失败: ${e.message}` });
    process.exit(1);
  }

  const {
    mode = 'server',
    host = '127.0.0.1',
    port = 19132,
    offline = true,
    version = null,
    authTitle = null,
    profilesFolder = null,
    realmId = null,
    realmInvite = null,
  } = config;
  username = config.username || 'FakeBot';

  // Realm 模式强制 online
  const isRealm = mode === 'realm';
  const effectiveOffline = isRealm ? false : offline;

  if (isRealm) {
    log(`正在加入 Realm (用户: ${username}, Realm: ${realmId || realmInvite})`);
  } else {
    log(`正在连接 ${host}:${port} (用户: ${username}, 离线: ${effectiveOffline})`);
  }

  // 2. 连接服务器
  try {
    const opts = {
      host,
      port,
      username,
      offline: effectiveOffline,
    };
    if (version) opts.version = version;

    // Xbox Live 认证配置（Realm 模式强制启用）
    if (!effectiveOffline) {
      log('Xbox Live 在线模式: 需要认证才能连接服务器');
      log('首次认证需要在浏览器中完成设备码流程');

      opts.onMsaCode = (code) => {
        send({
          type: 'auth',
          user_code: code.user_code,
          verification_uri: code.verification_uri,
          message: code.message || `请访问 ${code.verification_uri} 并输入代码: ${code.user_code}`,
        });
        log(`========================================`);
        log(`  Xbox Live 认证需要你的操作！`);
        log(`  1. 在浏览器中打开: ${code.verification_uri}`);
        log(`  2. 输入验证码: ${code.user_code}`);
        log(`  3. 使用 Microsoft 账号登录`);
        log(`  完成后 Bot 将自动继续连接`);
        log(`========================================`);
      };

      if (authTitle) {
        // 支持友好名称(如 'MinecraftAndroid')或 Title ID(如 '0000000048183522')
        try {
          const { Titles } = require('prismarine-auth');
          const resolved = Titles[authTitle] || authTitle;
          opts.authTitle = resolved;

          // auth.js 的 validateOptions 只在 authTitle===undefined 时设置 flow/deviceType,
          // 自定义 authTitle 时需要手动补充,否则 prismarine-auth 会报错
          if (!opts.flow) opts.flow = 'live';
          if (!opts.deviceType) {
            // 根据 Title ID 推断设备类型
            if (resolved === Titles.MinecraftAndroid) opts.deviceType = 'Android';
            else if (resolved === Titles.MinecraftIOS) opts.deviceType = 'iOS';
            else if (resolved === Titles.MinecraftPlaystation) opts.deviceType = 'PlayStation';
            else if (resolved === Titles.MinecraftNintendoSwitch) opts.deviceType = 'Nintendo';
            else opts.deviceType = 'Android'; // 默认 Android
          }
        } catch {
          opts.authTitle = authTitle;
          if (!opts.flow) opts.flow = 'live';
          if (!opts.deviceType) opts.deviceType = 'Android';
        }
      }

      if (profilesFolder) {
        opts.profilesFolder = profilesFolder;
      } else {
        opts.profilesFolder = '.minecraft/nmp-cache';
      }
    }

    // Realm 模式：加入指定的 Realm 房间
    if (isRealm) {
      opts.realms = {};
      if (realmId) {
        opts.realms.realmId = realmId;
      } else if (realmInvite) {
        opts.realms.realmInvite = realmInvite;
      } else {
        send({ type: 'error', message: 'Realm 模式需要提供 realmId 或 realmInvite' });
        process.exit(1);
      }
    }

    client = createClient(opts);
  } catch (e) {
    send({ type: 'error', message: `连接失败: ${e.message}` });
    process.exit(1);
  }

  // 3. 等待加入游戏
  client.on('spawn', () => {
    botReady = true;
    log('已加入游戏');
    send({ type: 'join' });
  });

  client.on('error', (err) => {
    log('连接错误:', err.message, err.stack || '');
    send({ type: 'error', message: err.message });
  });

  let disconnectReported = false;

  client.on('disconnect', (packet) => {
    const reason = packet?.message || '服务器主动断开';
    log('被服务器踢出 (disconnect):', JSON.stringify(packet));
    disconnectReported = true;
    send({ type: 'disconnect', reason: `服务器踢出: ${reason}` });
  });

  client.on('kick', (packet) => {
    const reason = packet?.message || '被服务器踢出';
    log('被服务器踢出 (kick):', JSON.stringify(packet));
    disconnectReported = true;
    send({ type: 'disconnect', reason: `服务器踢出: ${reason}` });
  });

  client.on('close', (hadError) => {
    if (!disconnectReported) {
      log('连接已关闭 (hadError:', hadError, ')');
      send({ type: 'disconnect', reason: `连接已关闭 (error: ${hadError || false})` });
    }
    botReady = false;
    process.exit(0);
  });

  // 4. 启动命令读取循环
  readCommandLoop();
}

// ========== 命令处理 ==========

function handleCommand(cmd) {
  if (!cmd || !cmd.type) return;

  switch (cmd.type) {
    case 'spawn':
      handleSpawn(cmd);
      break;
    case 'remove':
      handleRemove(cmd);
      break;
    case 'move':
      handleMove(cmd);
      break;
    case 'chat':
      handleChat(cmd);
      break;
    case 'list':
      handleList(cmd);
      break;
    case 'command':
      handleGameCommand(cmd);
      break;
    case 'quit':
      handleQuit();
      break;
    default:
      send({ type: 'error', message: `未知命令: ${cmd.type}` });
  }
}

function handleSpawn(cmd) {
  const { name, x = 0, y = 4, z = 0 } = cmd;
  if (!name) {
    send({ type: 'error', message: '缺少 name 参数' });
    return;
  }
  if (players[name]) {
    send({ type: 'error', message: `假人 "${name}" 已存在` });
    return;
  }

  // 生成随机 UUID
  const uuid = generateUUID();
  const xuid = '0'; // 离线模式 XUID

  players[name] = { uuid, xuid, x, y, z };

  // 发送 Player List 包: 添加条目
  try {
    client.queue('player_list', {
      uuid,
      action: 'add',
      entries: [{
        uuid,
        xuid,
        build_platform: '',
        entity_id: BigInt(0),
        command_permission: 0n,
        permission_level: 0,
        ...getSkinData(name),
      }],
    });
  } catch (e) {
    log('player_list 发送失败:', e.message);
  }

  // 发送 Add Player 包: 在世界中生成
  try {
    client.queue('add_player', {
      uuid,
      username: name,
      entity_id: BigInt(Math.floor(Math.random() * 100000) + 1000),
      position: { x, y, z },
      motion: { x: 0, y: 0, z: 0 },
      pitch: 0,
      yaw: 0,
      head_yaw: 0,
      ...getSkinData(name),
    });
  } catch (e) {
    log('add_player 发送失败:', e.message);
  }

  log(`已生成假人 "${name}" 于 (${x}, ${y}, ${z})`);
  send({ ok: true, action: 'spawn', name });
}

function handleRemove(cmd) {
  const { name } = cmd;
  if (!name || !players[name]) {
    send({ type: 'error', message: `假人 "${name}" 不存在` });
    return;
  }

  const { uuid } = players[name];

  // 发送 Player List 包: 移除条目
  try {
    client.queue('player_list', {
      uuid,
      action: 'remove',
      entries: [{ uuid }],
    });
  } catch (e) {
    log('player_list remove 发送失败:', e.message);
  }

  delete players[name];
  log(`已移除假人 "${name}"`);
  send({ ok: true, action: 'remove', name });
}

function handleMove(cmd) {
  const { name, x = 0, y = 4, z = 0 } = cmd;
  if (!name || !players[name]) {
    send({ type: 'error', message: `假人 "${name}" 不存在` });
    return;
  }

  players[name].x = x;
  players[name].y = y;
  players[name].z = z;

  // 发送 Move Player 包
  try {
    client.queue('move_player', {
      entity_id: BigInt(0),
      position: { x, y, z },
      mode: 'teleport',
      tick: 0,
    });
  } catch (e) {
    log('move_player 发送失败:', e.message);
  }

  log(`假人 "${name}" 已移动至 (${x}, ${y}, ${z})`);
  send({ ok: true, action: 'move', name });
}

function handleChat(cmd) {
  const { name, message } = cmd;
  if (!message) {
    send({ type: 'error', message: '缺少 message 参数' });
    return;
  }

  const proto = client.options?.protocolVersion || 0;
  const srcName = name || 'Bot';

  try {
    if (proto >= 898) {
      // 1.21.130+: needs_translation 在前,新增 category,filtered_message 变为 has_filtered_message + switch
      client.queue('text', {
        needs_translation: false,
        category: 'authored',
        type: 'chat',
        source_name: srcName,
        message,
        xuid: '',
        platform_chat_id: '',
        has_filtered_message: false,
      });
    } else {
      // 1.21.120 及更早版本
      client.queue('text', {
        type: 'chat',
        needs_translation: false,
        source_name: srcName,
        message,
        xuid: '',
        platform_chat_id: '',
        filtered_message: '',
      });
    }
  } catch (e) {
    log('text 发送失败:', e.message);
  }

  send({ ok: true, action: 'chat' });
}

function handleList() {
  const list = Object.entries(players).map(([name, data]) => ({
    name,
    x: data.x,
    y: data.y,
    z: data.z,
  }));
  send({ ok: true, action: 'list', players: list });
}

function handleGameCommand(cmd) {
  const { command } = cmd;
  if (!command) {
    send({ type: 'error', message: '缺少 command 参数' });
    return;
  }

  // 必须用 command_request 包发送命令
  // text 包的 /command 只是聊天文字,服务器不会当命令执行
  // 1.21.130+(proto>=898): player_entity_id 是必填 li64,version 必须是字符串 'latest'
  // 之前断连就是因为缺 player_entity_id 或 version 格式错误(数字而非字符串),
  // 导致 packet_violation_warning
  const crypto = require('crypto');
  const uuid = crypto.randomUUID();
  const cmdText = command.startsWith('/') ? command : `/${command}`;
  const entityId = client.entityId || 0n;

  let resolved = false;

  // 监听命令输出
  const handler = (packet) => {
    if (resolved) return;
    if (packet.origin && packet.origin.uuid === uuid) {
      resolved = true;
      client.removeListener('command_output', handler);
      clearTimeout(timer);
      const output = (packet.output || []).map(o => o.message || String(o)).join('\n');
      send({ ok: packet.success !== false, action: 'command', command, output: output || undefined });
    }
  };
  client.on('command_output', handler);

  // 超时:某些命令(如 /say)不产生 command_output
  const timer = setTimeout(() => {
    if (!resolved) {
      resolved = true;
      client.removeListener('command_output', handler);
      send({ ok: true, action: 'command', command });
    }
  }, 3000);

  try {
    client.queue('command_request', {
      command: cmdText,
      origin: {
        type: 'player',
        uuid,
        request_id: '',
        player_entity_id: entityId,
      },
      internal: false,
      version: 'latest',
    });
    log(`发送命令: ${cmdText} (entityId: ${entityId})`);
  } catch (e) {
    resolved = true;
    client.removeListener('command_output', handler);
    clearTimeout(timer);
    log('命令发送失败:', e.message);
    send({ type: 'error', message: `命令发送失败: ${e.message}` });
  }
}

function handleQuit() {
  log('收到退出指令');
  if (client) {
    try { client.close(); } catch (e) {}
  }
  process.exit(0);
}

// ========== 工具函数 ==========

function generateUUID() {
  const hex = '0123456789abcdef';
  let uuid = '';
  for (let i = 0; i < 32; i++) {
    uuid += hex[Math.floor(Math.random() * 16)];
    if (i === 7 || i === 11 || i === 15 || i === 19) uuid += '-';
  }
  return uuid;
}

function getSkinData(name) {
  // 返回默认皮肤数据(Steve 皮肤)
  return {
    skin: {
      skin_id: '0',
      play_fab_id: '',
      skin_resource_key: '',
      data: Buffer.alloc(0), // 空皮肤数据
      cape: { data: Buffer.alloc(0) },
      geometry: '',
      animation: '',
    },
    skin_animation: [],
    cape: null,
    primary_user: true,
    current_entity_id: BigInt(0),
    original_entity_id: BigInt(0),
    player_list_count: 0,
    teacher: false,
    host: false,
    trusted: false,
  };
}

// ========== stdin 读取 ==========

let stdinBuffer = '';

function readLine() {
  return new Promise((resolve) => {
    if (stdinBuffer.includes('\n')) {
      const idx = stdinBuffer.indexOf('\n');
      const line = stdinBuffer.slice(0, idx).trim();
      stdinBuffer = stdinBuffer.slice(idx + 1);
      resolve(line);
      return;
    }
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => {
      stdinBuffer += chunk;
      const idx = stdinBuffer.indexOf('\n');
      if (idx !== -1) {
        const line = stdinBuffer.slice(0, idx).trim();
        stdinBuffer = stdinBuffer.slice(idx + 1);
        resolve(line);
      }
    });
  });
}

function readCommandLoop() {
  readLine().then((line) => {
    if (!line) {
      readCommandLoop();
      return;
    }
    try {
      const cmd = JSON.parse(line);
      handleCommand(cmd);
    } catch (e) {
      send({ type: 'error', message: `命令解析失败: ${e.message}` });
    }
    readCommandLoop();
  });
}

// ========== 启动 ==========
main().catch((err) => {
  log('启动失败:', err.message);
  send({ type: 'error', message: `启动失败: ${err.message}` });
  process.exit(1);
});
