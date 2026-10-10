/**
 * 【临时脚本】诊断 H5 页面为什么没渲染（跑完即删）。
 * 收集 console 消息与 pageerror，并打印 body 内容。
 * 用法：node _tmp_diag.mjs [port] [route]
 */
import { spawn } from 'node:child_process'
import { setTimeout as sleep } from 'node:timers/promises'

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const APP = process.env.APP_BASE || 'http://127.0.0.1:5173'
const port = Number(process.argv[2] || 9446)
const route = process.argv[3] || 'pages/login/login'

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
    `--user-data-dir=${process.env.TEMP}\\edge-diag-${port}`,
    '--window-size=430,900',
    '--no-first-run',
    '--no-default-browser-check',
    'about:blank',
  ],
  { stdio: 'ignore' },
)

const logs = []
try {
  ws = new WebSocket(await pageWsUrl())
  await new Promise((r) => ws.addEventListener('open', r, { once: true }))
  ws.addEventListener('message', (event) => {
    const msg = JSON.parse(event.data)
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id)
      pending.delete(msg.id)
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result)
      return
    }
    if (msg.method === 'Runtime.consoleAPICalled') {
      logs.push(`[console.${msg.params.type}] ` + msg.params.args.map((a) => a.value ?? a.description ?? a.type).join(' '))
    }
    if (msg.method === 'Runtime.exceptionThrown') {
      const d = msg.params.exceptionDetails
      logs.push('[exception] ' + (d.exception?.description || d.text))
    }
    if (msg.method === 'Log.entryAdded') {
      logs.push(`[log.${msg.params.entry.level}] ${msg.params.entry.text} ${msg.params.entry.url || ''}`)
    }
  })

  const evaluate = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
    return r.result?.value
  }

  await send('Page.enable')
  await send('Runtime.enable')
  await send('Log.enable')
  await send('Page.navigate', { url: `${APP}/#/${route}` })
  await sleep(5000)

  console.log('--- 页面状态 ---')
  console.log(await evaluate(`JSON.stringify({
    hash: location.hash,
    title: document.title,
    appHtmlLen: (document.getElementById('app') || {}).innerHTML?.length ?? -1,
    appText: (document.getElementById('app') || {}).innerText?.slice(0, 300) ?? '',
    bodyText: document.body.innerText.slice(0, 300),
    uni: typeof window.uni,
    scripts: Array.from(document.querySelectorAll('script[src]')).map(function (s) { return s.getAttribute('src'); })
  })`))

  console.log('--- 控制台/异常 ---')
  for (const l of logs) console.log(l)
} finally {
  try { ws?.close() } catch {}
  edge.kill()
}
