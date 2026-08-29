/**
 * postinstall 脚本: 向 bedrock-protocol 注入版本兼容性补丁
 * 
 * 当 minecraft-data 还没包含最新 MCBE 版本时,修补三个文件让协议向下 fallback:
 * 1. options.js       — 补充版本号 → protocol 映射
 * 2. serializer.js    — 序列化器 fallback 到有数据的最近版本
 * 3. client.js        — _loadFeatures fallback 到有数据的最近版本
 * 
 * 运行时机: npm install 后自动执行 (package.json → scripts.postinstall)
 */
const fs = require('fs');
const path = require('path');

const base = path.join(__dirname, '..', 'node_modules', 'bedrock-protocol', 'src');

// ===== 1. options.js: 补充版本映射 =====
const optPath = path.join(base, 'options.js');
if (fs.existsSync(optPath)) {
  let src = fs.readFileSync(optPath, 'utf8');
  if (!src.includes('EXTRA_VERSIONS')) {
    const extraBlock = `\n// ===== PATCH: 手动补充 minecraft-data 尚未收录的新版本 =====\nconst EXTRA_VERSIONS = {\n  '1.26.45': 2169,\n  '1.26.40': 2168,\n  '1.26.30': 2160,\n  '1.26.20': 2150,\n  '1.26.10': 2140,\n};\nfor (const [ver, proto] of Object.entries(EXTRA_VERSIONS)) {\n  if (!Versions[ver]) Versions[ver] = proto;\n}\n// ===== END PATCH =====\n`;
    const marker = 'const testedVersions';
    if (src.includes(marker)) {
      src = src.replace(marker, extraBlock + marker);
    } else {
      src += extraBlock;
    }
    fs.writeFileSync(optPath, src, 'utf8');
    console.log('[patch-bedrock] options.js: \u6ce8\u5165\u7248\u672c\u6620\u5c04 \u2713');
  } else {
    console.log('[patch-bedrock] options.js: \u5df2\u6709\u8865\u4e01,\u8df3\u8fc7');
  }
}

// ===== 2. serializer.js: 序列化器 fallback =====
const serPath = path.join(base, 'transforms', 'serializer.js');
if (fs.existsSync(serPath)) {
  let src = fs.readFileSync(serPath, 'utf8');
  if (!src.includes('PATCH_CREATE_PROTOCOL')) {
    const oldCode = `// Compiles the ProtoDef schema at runtime\nfunction createProtocol (version) {\n  // Try and load from .js if available\n  try { require(\\`../../data/\\${version}/size.js\\`); return getProtocol(version) } catch {}\n\n  const protocol = require('minecraft-data')('bedrock_' + version).protocol`;
    const newCode = `// ===== PATCH_CREATE_PROTOCOL =====\n// Compiles the ProtoDef schema at runtime (with version fallback)\nfunction createProtocol (version) {\n  // Try and load from .js if available\n  try { require(\\`../../data/\\${version}/size.js\\`); return getProtocol(version) } catch {}\n\n  const mcData = require('minecraft-data');\n  let protocol = null;\n  let tryVersion = version;\n  for (let i = 0; i < 10; i++) {\n    const d = mcData('bedrock_' + tryVersion);\n    if (d && d.protocol) { protocol = d.protocol; break; }\n    const parts = tryVersion.split('.');\n    const patch = parseInt(parts[2] || '0', 10);\n    if (patch > 0) { parts[2] = String(patch - 1); tryVersion = parts.join('.'); }\n    else break;\n  }\n  if (!protocol) throw new Error('No protocol data for bedrock_' + version);`;
    if (src.includes(oldCode)) {
      src = src.replace(oldCode, newCode);
      fs.writeFileSync(serPath, src, 'utf8');
      console.log('[patch-bedrock] serializer.js: \u7248\u672c fallback \u2713');
    } else {
      console.log('[patch-bedrock] serializer.js: \u4ee3\u7801\u5df2\u53d8\u66f4,\u9700\u624b\u52a8 patch');
    }
  } else {
    console.log('[patch-bedrock] serializer.js: \u5df2\u6709\u8865\u4e01,\u8df3\u8fc7');
  }
}

// ===== 3. client.js: _loadFeatures fallback =====
const cliPath = path.join(base, 'client.js');
if (fs.existsSync(cliPath)) {
  let src = fs.readFileSync(cliPath, 'utf8');
  if (!src.includes('PATCH_LOAD_FEATURES')) {
    const oldCode = `  _loadFeatures () {\n    try {\n      const mcData = require('minecraft-data')('bedrock_' + this.options.version)\n      this.features = {\n        compressorInHeader: mcData.supportFeature('compressorInPacketHeader'),\n        itemRegistryPacket: mcData.supportFeature('itemRegistryPacket'),\n        newLoginIdentityFields: mcData.supportFeature('newLoginIdentityFields')\n      }\n    } catch (e) {\n      throw new Error(\\`Unsupported version: '\\${this.options.version}', no data available\\`)\n    }\n  }`;
    const newCode = `  // ===== PATCH_LOAD_FEATURES =====\n  _loadFeatures () {\n    let mcData = null;\n    let tryVersion = this.options.version;\n    for (let i = 0; i < 10; i++) {\n      const d = require('minecraft-data')('bedrock_' + tryVersion);\n      if (d && d.supportFeature) { mcData = d; break; }\n      const parts = tryVersion.split('.');\n      const patch = parseInt(parts[2] || '0', 10);\n      if (patch > 0) { parts[2] = String(patch - 1); tryVersion = parts.join('.'); }\n      else break;\n    }\n    if (!mcData) throw new Error(\\`Unsupported version: '\\${this.options.version}', no data available\\`);\n    this.features = {\n      compressorInHeader: mcData.supportFeature('compressorInPacketHeader'),\n      itemRegistryPacket: mcData.supportFeature('itemRegistryPacket'),\n      newLoginIdentityFields: mcData.supportFeature('newLoginIdentityFields')\n    }\n  }`;
    if (src.includes(oldCode)) {
      src = src.replace(oldCode, newCode);
      fs.writeFileSync(cliPath, src, 'utf8');
      console.log('[patch-bedrock] client.js: _loadFeatures fallback \u2713');
    } else {
      console.log('[patch-bedrock] client.js: \u4ee3\u7801\u5df2\u53d8\u66f4,\u9700\u624b\u52a8 patch');
    }
  } else {
    console.log('[patch-bedrock] client.js: \u5df2\u6709\u8865\u4e01,\u8df3\u8fc7');
  }
}

// ===== 4. login.js: defaultSkin fallback =====
const loginPath = path.join(base, 'handshake', 'login.js');
if (fs.existsSync(loginPath)) {
  let src = fs.readFileSync(loginPath, 'utf8');
  if (!src.includes('PATCH_LOGIN_DEFAULTSKIN')) {
    const oldCode = `module.exports = (client, server, options) => {
  const skinData = require('minecraft-data')('bedrock_' + options.version).defaultSkin`;
    const newCode = `module.exports = (client, server, options) => {
  // ===== PATCH_LOGIN_DEFAULTSKIN =====
  const { getMinecraftData } = require('../versionCompat');
  const _mcData = getMinecraftData(options.version);
  if (!_mcData) throw new Error(\`No data for bedrock_\${options.version}\`);
  const skinData = _mcData.defaultSkin;`;
    if (src.includes(oldCode)) {
      src = src.replace(oldCode, newCode);
      fs.writeFileSync(loginPath, src, 'utf8');
      console.log('[patch-bedrock] login.js: defaultSkin fallback \u2713');
    } else {
      console.log('[patch-bedrock] login.js: \u4ee3\u7801\u5df2\u53d8\u66f4,\u9700\u624b\u52a8 patch');
    }
  } else {
    console.log('[patch-bedrock] login.js: \u5df2\u6709\u8865\u4e01,\u8df3\u8fc7');
  }
}

// ===== 5. versionCompat.js: 共享 helper =====
const vcPath = path.join(base, 'versionCompat.js');
const vcContent = `/**
 * bedrock-protocol \u7248\u672c\u517c\u5bb9\u6027 patch \u2014 \u5171\u4eab helper
 * \u5f53 minecraft-data \u5c1a\u672a\u6536\u5f55\u6700\u65b0 MCBE \u7248\u672c\u65f6,
 * \u6b64\u6a21\u5757\u63d0\u4f9b fallback \u903b\u8f91,\u4ece\u9ad8\u7248\u672c\u9012\u51cf\u67e5\u627e\u53ef\u7528\u6570\u636e\u3002
 */
const mcData = require('minecraft-data');

function getMinecraftData(version) {
  let tryVersion = version;
  for (let i = 0; i < 10; i++) {
    try {
      const d = mcData('bedrock_' + tryVersion);
      if (d) return d;
    } catch {}
    const parts = tryVersion.split('.');
    const patch = parseInt(parts[2] || '0', 10);
    if (patch > 0) { parts[2] = String(patch - 1); tryVersion = parts.join('.'); }
    else break;
  }
  return null;
}

module.exports = { getMinecraftData };
`;
if (!fs.existsSync(vcPath)) {
  fs.writeFileSync(vcPath, vcContent, 'utf8');
  console.log('[patch-bedrock] versionCompat.js: \u521b\u5efa \u2713');
} else {
  console.log('[patch-bedrock] versionCompat.js: \u5df2\u5b58\u5728,\u8df3\u8fc7');
}

console.log('[patch-bedrock] \u5b8c\u6210');
