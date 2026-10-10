/**
 * 【临时脚本】用无头 Edge + CDP 给小程序 H5 端截图（跑完即删）。
 *
 * 为什么不用 `msedge --screenshot=...` 一条命令：
 *   登录态在 localStorage 里，一条命令的 headless 每次都是全新的临时用户目录，
 *   进去只会看到登录页 —— 截不到「司机 / 管理者各自的底部导航」。
 *   这里连同一个 Edge 实例的 CDP 通道：**先在页面上真实走一遍登录流程**
 *   （填账号 → 点登录 → 等 reLaunch），再导航到目标页截图。
 *   走 App 自己的登录代码，存储键名与写入格式都由 App 决定，脚本不猜、
 *   也不改 App 的任何代码。
 *
 * 用法：node _tmp_shot_nav.mjs <outDir> <user> <pass> <pages/xxx/yyy> [tag] [port]
 */

import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { setTimeout as sleep } from 'node:timers/promises'

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const APP = process.env.APP_BASE || 'http://127.0.0.1:5173'
const [outDir, username, password, pageRoute, tag = username, portArg = '9455'] = process.argv.slice(2)
if (!outDir || !username || !password || !pageRoute) {
  console.error('usage: node _tmp_shot_nav.mjs <outDir> <user> <pass> <pages/xxx/yyy> [tag] [port]')
  process.exit(2)
}
const port = Number(portArg)
mkdirSync(outDir, { recursive: true })

let ws
let seq = 0
const pending = new Map()
const send = (method, params = {}) => {
  const id = ++seq
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject })
    ws.send(JSON.stringify({ id, method, params }))
  })
}

/** 取**页面级** target（浏览器级端点每条命令都要带 sessionId，页面级可以直接发） */
async function pageWsUrl(tries = 80) {
  for (let i = 0; i < tries; i += 1) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()
      const page = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl)
      if (page) return page.webSocketDebuggerUrl
    } catch {
      /* 还没起来 */
    }
    await sleep(250)
  }
  throw new Error(`CDP 页面端点未就绪（port=${port}）`)
}

const edge = spawn(
  EDGE,
  [
    '--headless=new',
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${process.env.TEMP}\\edge-nav-${tag}`,
    '--window-size=430,900',
    '--hide-scrollbars',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    'about:blank',
  ],
  { stdio: 'ignore' },
)

try {
  ws = new WebSocket(await pageWsUrl())
  await new Promise((r, j) => {
    ws.addEventListener('open', r, { once: true })
    ws.addEventListener('error', j, { once: true })
  })
  ws.addEventListener('message', (event) => {
    const msg = JSON.parse(event.data)
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id)
      pending.delete(msg.id)
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result)
    }
  })

  const evaluate = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + ' :: ' + expression.slice(0, 120))
    return r.result?.value
  }
  const goto = async (url, wait = 3000) => {
    await send('Page.navigate', { url })
    await sleep(wait)
  }

  await send('Page.enable')
  await send('Runtime.enable')
  await send('Emulation.setDeviceMetricsOverride', {
    width: 430,
    height: 900,
    deviceScaleFactor: 2,
    mobile: true,
  })

  /* ---------------- 1. 真实走一遍登录流程 ---------------- */
  await goto(`${APP}/#/pages/login/login`, 3500)
  const filled = await evaluate(`(function () {
    var inputs = document.querySelectorAll('input');
    if (inputs.length < 2) return 'inputs=' + inputs.length;
    function setValue(el, value) {
      var proto = Object.getPrototypeOf(el);
      var desc = Object.getOwnPropertyDescriptor(proto, 'value');
      desc.set.call(el, value);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    }
    setValue(inputs[0], ${JSON.stringify(username)});
    setValue(inputs[1], ${JSON.stringify(password)});
    return 'filled';
  })()`)
  console.log('[login] 表单:', filled)
  await sleep(400)

  const clicked = await evaluate(`(function () {
    var list = Array.from(document.querySelectorAll('button, uni-button, .uni-button, [class*="btn"]'));
    var info = list.map(function (b) { return (b.tagName || '') + '|' + (b.innerText || '').trim().slice(0, 12); });
    var target = list.find(function (b) { return (b.innerText || '').indexOf('登') >= 0; });
    if (!target) return 'no-button; candidates=' + JSON.stringify(info);
    target.click();
    return 'clicked:' + target.tagName + ':' + (target.innerText || '').trim();
  })()`)
  console.log('[login] 按钮:', clicked)
  await sleep(5000)

  const afterLogin = await evaluate(`JSON.stringify({
    hash: location.hash,
    storageKeys: Object.keys(localStorage),
    bodyHead: document.body.innerText.slice(0, 150)
  })`)
  console.log('[login] 登录后:', afterLogin)

  /* ---------------- 2. 进目标页截图 ---------------- */
  await goto(`${APP}/#/${pageRoute}`, 3500)

  const diag = await evaluate(`JSON.stringify({
    hash: location.hash,
    navTexts: Array.from(document.querySelectorAll('.bottom-nav .nav-text')).map(function (n) { return n.textContent; }),
    activeText: (document.querySelector('.bottom-nav .nav-item-active .nav-text') || {}).textContent || null,
    badge: (document.querySelector('.bottom-nav .nav-badge') || {}).textContent || null,
    navPosition: (function () { var el = document.querySelector('.bottom-nav'); if (!el) return null; var s = getComputedStyle(el); return s.position + ' / bottom:' + s.bottom + ' / padBottom:' + s.paddingBottom; })(),
    pagePadBottom: (function () { var el = document.querySelector('.page'); return el ? getComputedStyle(el).paddingBottom : null; })(),
    uniTabBarDom: document.querySelectorAll('uni-tabbar').length,
    bodyHead: document.body.innerText.slice(0, 150)
  })`)
  console.log('[page] ' + pageRoute + ' ->', diag)

  const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
  const file = `${outDir}\\${tag}-${pageRoute.replace(/\//g, '-')}.png`
  writeFileSync(file, Buffer.from(shot.data, 'base64'))
  console.log('[shot] ' + file)
} finally {
  try {
    ws?.close()
  } catch {
    /* ignore */
  }
  edge.kill()
}
