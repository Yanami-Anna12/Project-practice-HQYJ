/**
 * 构建前把微信小程序 AppID 注入 manifest.json；构建后再还原成占位符。
 *
 * ★ 为什么要有这个脚本（与物流项目 miniapp 同一套做法）：
 *   AppID 一旦硬编码进 manifest.json 并提交，GitHub 的 secret scanning 每次推送
 *   都会告警（它把 `wx` + 16 位十六进制识别成「腾讯微信 API 应用 ID」），
 *   而且历史提交里会永久留着 —— 清掉要改写 git 历史。
 *   所以：仓库里只放占位符 `touristappid`，真实 AppID 只存在本机 `.appid` 文件里。
 *
 * 两个模式：
 *   --restore-after  配合 prebuild/postbuild 钩子：注入 → 构建 → 还原，构建完工作区干净。
 *   不带参数          只注入不还原，给 `npm run dev:mp-weixin` 用（开发者工具要一直读到）。
 *
 * AppID 来源优先级：环境变量 WX_APPID > 项目根目录 .appid 文件 > 保留占位符（不阻断）。
 */
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const manifestPath = path.join(root, 'src', 'manifest.json')
const appidFile = path.join(root, '.appid')
const PLACEHOLDER = 'touristappid'

/** 合法 AppID 形如 wx + 16 位十六进制 */
const APPID_PATTERN = /^wx[0-9a-f]{16}$/i

const restoreAfter = process.argv.includes('--restore-after')

function resolveAppId() {
  const fromEnv = (process.env.WX_APPID || '').trim()
  if (fromEnv) return { appid: fromEnv, source: '环境变量 WX_APPID' }
  if (fs.existsSync(appidFile)) {
    const fromFile = fs.readFileSync(appidFile, 'utf8').trim()
    if (fromFile) return { appid: fromFile, source: '.appid 文件' }
  }
  return { appid: '', source: '' }
}

/** 读文件并记住行尾；★ 必须剥掉 UTF-8 BOM，否则 JSON.parse 直接抛错、注入静默失效 */
function readManifest() {
  const raw = fs.readFileSync(manifestPath, 'utf8').replace(/^\uFEFF/, '')
  return { manifest: JSON.parse(raw), eol: raw.includes('\r\n') ? '\r\n' : '\n' }
}

function writeManifest(manifest, eol) {
  const json = JSON.stringify(manifest, null, 2)
  const text = eol === '\r\n' ? json.replace(/\n/g, '\r\n') : json
  fs.writeFileSync(manifestPath, `${text}${eol}`, 'utf8')
}

function restoreByGit() {
  try {
    execFileSync('git', ['checkout', '--', 'src/manifest.json'], { cwd: root, stdio: 'pipe' })
    console.log('[appid] 已把 manifest.json 还原为仓库里的占位符（git checkout）')
    return true
  } catch {
    return false
  }
}

if (restoreAfter) {
  if (!restoreByGit()) {
    try {
      const { manifest, eol } = readManifest()
      const current = (manifest['mp-weixin'] && manifest['mp-weixin'].appid) || ''
      if (current && current !== PLACEHOLDER) {
        manifest['mp-weixin'] = { ...manifest['mp-weixin'], appid: PLACEHOLDER }
        writeManifest(manifest, eol)
        console.log(`[appid] 已把 manifest.json 还原为占位符 ${PLACEHOLDER}`)
      }
    } catch (err) {
      console.warn(`[appid] 还原失败（不影响构建产物）：${err.message}`)
    }
  }
  process.exit(0)
}

const { appid, source } = resolveAppId()
const { manifest, eol } = readManifest()
const current = (manifest['mp-weixin'] && manifest['mp-weixin'].appid) || ''

if (!appid) {
  console.log(
    '[appid] 未配置 AppID（既没有 WX_APPID 环境变量，也没有 .appid 文件）——\n' +
      '        真机预览/上传需要它；H5 构建不需要，继续。\n' +
      '        配置方式：在本目录建一个 .appid 文件，写一行 AppID 即可（已 gitignore）。',
  )
  process.exit(0)
}

if (!APPID_PATTERN.test(appid)) {
  console.warn(`[appid] 警告：${source} 里的值不像合法 AppID（应为 wx + 16 位十六进制），仍按原样写入并继续。`)
}

if (current === appid) {
  console.log(`[appid] manifest.json 已是目标 AppID（来自${source}），无需改动`)
  process.exit(0)
}

manifest['mp-weixin'] = { ...(manifest['mp-weixin'] || {}), appid }
writeManifest(manifest, eol)
console.log(`[appid] 已从${source}注入 manifest.json`)
