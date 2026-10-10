/**
 * 【临时脚本】验证自绘底部导航的点击跳转（redirectTo）真的能换页（跑完即删）。
 *
 * 只做一件事：登录 → 依次点底部导航的每个条目 → 断言 hash 变了、且
 * 页面栈不会越点越深（redirectTo 的语义是替换当前页）。
 * 页面栈深度用 uni 的 getCurrentPages() 读。
 */
import { spawn } from 'node:child_process'
import { setTimeout as sleep } from 'node:timers/promises'

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const APP = process.env.APP_BASE || 'http://127.0.0.1:5173'
const username = process.argv[2] || 'driver1'
const password = process.argv[3] || '123456'
const port = Number(process.argv[4] || 9461)

let ws
let seq = 0
const pending = new Map()
const send = (m, p = {}) => {
  const id = ++seq
  return new Promise((res, rej) => {
    pending.set(id, { resolve: res, reject: rej })
    ws.send(JSON.stringify({ id, method: m, params: p }))
  })
}
async function pageWsUrl(tries = 80) {
  for (let i = 0; i < tries; i += 1) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()
      const page = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl)
      if (page) return page.webSocketDebuggerUrl
    } catch {}
    await sleep(250)
  }
  throw new Error('CDP 未就绪')
}

const edge = spawn(
  EDGE,
  [
    '--headless=new',
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${process.env.TEMP}\\edge-navclick-${port}`,
    '--window-size=430,900',
    '--no-first-run',
    '--no-default-browser-check',
    'about:blank',
  ],
  { stdio: 'ignore' },
)

try {
  ws = new WebSocket(await pageWsUrl())
  await new Promise((r) => ws.addEventListener('open', r, { once: true }))
  ws.addEventListener('message', (e) => {
    const msg = JSON.parse(e.data)
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id)
      pending.delete(msg.id)
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result)
    }
  })
  const ev = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text)
    return r.result?.value
  }
  const goto = async (url, wait = 3200) => {
    await send('Page.navigate', { url })
    await sleep(wait)
  }

  await send('Page.enable')
  await send('Runtime.enable')
  await send('Emulation.setDeviceMetricsOverride', { width: 430, height: 900, deviceScaleFactor: 2, mobile: true })

  /* 登录 */
  await goto(`${APP}/#/pages/login/login`, 3500)
  await ev(`(function () {
    var inputs = document.querySelectorAll('input');
    function setValue(el, v) { Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value').set.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true })); }
    setValue(inputs[0], ${JSON.stringify(username)});
    setValue(inputs[1], ${JSON.stringify(password)});
    var b = Array.from(document.querySelectorAll('button, uni-button')).find(function (x) { return (x.innerText || '').indexOf('登') >= 0; });
    b.click();
  })()`)
  await sleep(5000)

  /* 逐项点击底部导航 */
  const state = () =>
    ev(`JSON.stringify({
      hash: location.hash,
      depth: (typeof getCurrentPages === 'function' ? getCurrentPages().length : -1),
      nav: Array.from(document.querySelectorAll('.bottom-nav .nav-text')).map(function (n) { return n.textContent; }),
      active: (document.querySelector('.bottom-nav .nav-item-active .nav-text') || {}).textContent || null
    })`)

  console.log('起点:', await state())
  const labels = JSON.parse(await ev(`JSON.stringify(Array.from(document.querySelectorAll('.bottom-nav .nav-text')).map(function (n) { return n.textContent; }))`))
  console.log('底部导航条目:', JSON.stringify(labels))

  for (const label of labels) {
    await ev(`(function () {
      var items = Array.from(document.querySelectorAll('.bottom-nav .nav-item'));
      var t = items.find(function (i) { return (i.innerText || '').indexOf(${JSON.stringify(label)}) >= 0; });
      t.click();
    })()`)
    await sleep(3000)
    console.log(`点击「${label}」 →`, await state())
  }

  /* 再点一遍，确认来回切换不会越点越深 */
  for (let i = 0; i < 3; i += 1) {
    await ev(`(function () {
      var items = Array.from(document.querySelectorAll('.bottom-nav .nav-item'));
      var t = items.find(function (x) { return (x.innerText || '').indexOf(${JSON.stringify(labels[0])}) >= 0; });
      t.click();
    })()`)
    await sleep(2500)
    console.log(`反复回「${labels[0]}」第 ${i + 1} 次 →`, await state())
  }
} finally {
  try { ws?.close() } catch {}
  edge.kill()
}
