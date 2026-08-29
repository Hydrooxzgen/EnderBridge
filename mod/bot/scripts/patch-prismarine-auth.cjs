/**
 * postinstall 脚本: 向 prismarine-auth 注入认证容错补丁
 *
 * 问题: getTitleToken (title.auth.xboxlive.com) 对部分账号/区域返回 400/403,
 *      导致整个 Xbox Live 认证流程中断 ("400 Bad Request {}")。
 * 修复: getTitleToken 失败时降级继续 —— XSTS token 交换只需要
 *      userToken + deviceToken, titleToken 是可选的。
 *
 * 运行时机: npm install 后自动执行 (package.json → scripts.postinstall)
 */
const fs = require('fs');
const path = require('path');

const base = path.join(__dirname, '..', 'node_modules', 'prismarine-auth', 'src');

// ===== MicrosoftAuthFlow.js: getTitleToken 容错降级 =====
const flowPath = path.join(base, 'MicrosoftAuthFlow.js');
if (fs.existsSync(flowPath)) {
  let src = fs.readFileSync(flowPath, 'utf8');
  if (!src.includes('PATCH_TITLE_TOKEN_FALLBACK')) {
    const oldCode = `      const ut = userToken.token ?? await this.xbl.getUserToken(msaToken, options.flow === 'msal')
      const dt = deviceToken.token ?? await this.xbl.getDeviceToken(options)
      const tt = titleToken.token ?? (this.doTitleAuth ? await this.xbl.getTitleToken(msaToken, dt) : undefined)

      const xsts = await this.xbl.getXSTSToken({ userToken: ut, deviceToken: dt, titleToken: tt }, options)`;
    const newCode = `      const ut = userToken.token ?? await this.xbl.getUserToken(msaToken, options.flow === 'msal')
      const dt = deviceToken.token ?? await this.xbl.getDeviceToken(options)
      // ===== PATCH_TITLE_TOKEN_FALLBACK =====
      // getTitleToken (title.auth.xboxlive.com) 可能对部分账号/区域返回 400/403。
      // XSTS 交换不强制要求 titleToken, 失败时降级跳过, 避免中断整个认证流程。
      let tt = titleToken.token
      if (!tt && this.doTitleAuth) {
        try {
          tt = await this.xbl.getTitleToken(msaToken, dt)
        } catch (e) {
          debug('[xbl] getTitleToken failed, continuing without title token:', e.message)
        }
      }
      // ===== END PATCH =====

      const xsts = await this.xbl.getXSTSToken({ userToken: ut, deviceToken: dt, titleToken: tt }, options)`;
    if (src.includes(oldCode)) {
      src = src.replace(oldCode, newCode);
      fs.writeFileSync(flowPath, src, 'utf8');
      console.log('[patch-auth] MicrosoftAuthFlow.js: getTitleToken 容错降级 ✓');
    } else {
      console.log('[patch-auth] MicrosoftAuthFlow.js: 代码已变更,需手动 patch');
    }
  } else {
    console.log('[patch-auth] MicrosoftAuthFlow.js: 已有补丁,跳过');
  }
}

// ===== MicrosoftAuthFlow.js: titleId 缺失时降级 (不强制 throw) =====
if (fs.existsSync(flowPath)) {
  let src = fs.readFileSync(flowPath, 'utf8');
  if (!src.includes('PATCH_TITLE_ID_FALLBACK')) {
    const oldCode = `        const token = await this.mba.getAccessToken(publicKey, xsts)
        // If we want to auth with a title ID, make sure there's a TitleID in the response
        const body = JSON.parse(Buffer.from(token.chain[1].split('.')[1], 'base64').toString())
        if (!body.extraData.titleId && this.doTitleAuth) {
          throw Error('missing titleId in response')
        }
        return token.chain`;
    const newCode = `        const token = await this.mba.getAccessToken(publicKey, xsts)
        // ===== PATCH_TITLE_ID_FALLBACK =====
        // titleId 仅在客户端用于展示用途, 服务器认证不依赖它。
        // 当 getTitleToken 被降级跳过时 titleId 会缺失, 此时不应中断认证。
        const body = JSON.parse(Buffer.from(token.chain[1].split('.')[1], 'base64').toString())
        if (!body.extraData.titleId && this.doTitleAuth) {
          debug('[mc] missing titleId in response (non-fatal, continuing)')
        }
        // ===== END PATCH =====
        return token.chain`;
    if (src.includes(oldCode)) {
      src = src.replace(oldCode, newCode);
      fs.writeFileSync(flowPath, src, 'utf8');
      console.log('[patch-auth] MicrosoftAuthFlow.js: titleId 缺失降级 ✓');
    } else {
      console.log('[patch-auth] MicrosoftAuthFlow.js: titleId 代码已变更,需手动 patch');
    }
  } else {
    console.log('[patch-auth] MicrosoftAuthFlow.js: titleId 补丁已存在,跳过');
  }
}
// ===== XboxTokenManager.js: 在 XSTS 响应中提取 Gamertag =====
const xblPath = path.join(base, 'TokenManagers', 'XboxTokenManager.js');
if (fs.existsSync(xblPath)) {
  let src = fs.readFileSync(xblPath, 'utf8');
  if (!src.includes('PATCH_GAMERTAG')) {
    // getXSTSToken: 在 xsts 对象中添加 gamertag
    const oldXsts = `    const xsts = {
      userXUID: ret.DisplayClaims.xui[0].xid || null,
      userHash: ret.DisplayClaims.xui[0].uhs,
      XSTSToken: ret.Token,
      expiresOn: ret.NotAfter
    }`;
    const newXsts = `    const xsts = {
      userXUID: ret.DisplayClaims.xui[0].xid || null,
      userHash: ret.DisplayClaims.xui[0].uhs,
      XSTSToken: ret.Token,
      expiresOn: ret.NotAfter,
      // ===== PATCH_GAMERTAG =====
      gamertag: ret.DisplayClaims.xui[0].gtg || null
    }`;
    if (src.includes(oldXsts)) {
      src = src.replace(oldXsts, newXsts);
    }
    // doSisuAuth: 在 xsts 对象中添加 gamertag
    const oldSisu = `    const xsts = {
      userXUID: ret.AuthorizationToken.DisplayClaims.xui[0].xid || null,
      userHash: ret.AuthorizationToken.DisplayClaims.xui[0].uhs,
      XSTSToken: ret.AuthorizationToken.Token,
      expiresOn: ret.AuthorizationToken.NotAfter
    }`;
    const newSisu = `    const xsts = {
      userXUID: ret.AuthorizationToken.DisplayClaims.xui[0].xid || null,
      userHash: ret.AuthorizationToken.DisplayClaims.xui[0].uhs,
      XSTSToken: ret.AuthorizationToken.Token,
      expiresOn: ret.AuthorizationToken.NotAfter,
      // ===== PATCH_GAMERTAG =====
      gamertag: ret.AuthorizationToken.DisplayClaims.xui[0].gtg || null
    }`;
    if (src.includes(oldSisu)) {
      src = src.replace(oldSisu, newSisu);
    }
    fs.writeFileSync(xblPath, src, 'utf8');
    console.log('[patch-auth] XboxTokenManager.js: gamertag 提取 ✓');
  } else {
    console.log('[patch-auth] XboxTokenManager.js: 已有补丁,跳过');
  }
}