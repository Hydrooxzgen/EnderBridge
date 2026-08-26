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
    host = '127.0.0.1',
    port = 19132,
    username = 'FakeBot',
    offline = true,
    version = null,
  } = config;

  log(`正在连接 ${host}:${port} (用户: ${username}, 离线: ${offline})`);

  // 2. 连接服务器
  try {
    const opts = {
      host,
      port,
      username,
      offline,
      // authTitle: '00000000-0000-0000-0000-000000000000', // 离线模式不需要
    };
    if (version) opts.version = version;

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
    log('连接错误:', err.message);
    send({ type: 'error', message: err.message });
  });

  client.on('close', (reason) => {
    log('连接断开:', reason || '未知原因');
    send({ type: 'disconnect', reason: reason || '未知原因' });
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
  send({ type: 'ok', action: 'spawn', name });
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
  send({ type: 'ok', action: 'remove', name });
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
  send({ type: 'ok', action: 'move', name });
}

function handleChat(cmd) {
  const { name, message } = cmd;
  if (!message) {
    send({ type: 'error', message: '缺少 message 参数' });
    return;
  }

  // 使用假人名称发送聊天消息
  try {
    client.queue('text', {
      type: 'chat',
      message,
      needs_translation: false,
      source_name: name || 'Bot',
      xuid: '',
    });
  } catch (e) {
    log('text 发送失败:', e.message);
  }

  send({ type: 'ok', action: 'chat' });
}

function handleList() {
  const list = Object.entries(players).map(([name, data]) => ({
    name,
    x: data.x,
    y: data.y,
    z: data.z,
  }));
  send({ type: 'ok', action: 'list', players: list });
}

function handleGameCommand(cmd) {
  const { command } = cmd;
  if (!command) {
    send({ type: 'error', message: '缺少 command 参数' });
    return;
  }
  try {
    client.queue('command_request', {
      command: command,
      origin: { type: 0, uuid: generateUUID() },
      interval: false,
      version: 55,
    });
    send({ type: 'ok', action: 'command', command });
  } catch (e) {
    log('command_request 发送失败:', e.message);
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
