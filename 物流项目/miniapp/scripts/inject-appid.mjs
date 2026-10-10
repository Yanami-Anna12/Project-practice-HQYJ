/**
 * 构建前把微信小程序 AppID 注入 manifest.json；构建后再还原成占位符。
 *
 * ★ 为什么要有这个脚本：AppID 一旦**硬编码进 manifest.json 并提交**，
 *   GitHub 的 secret scanning 每次推送都会告警（它把 `wx` + 16 位十六进制识别成
 *   「腾讯微信 API 应用 ID」），而且历史提交里会永久留着 —— 清掉要改写 git 历史。
 *   所以：**仓库里只放占位符 `touristappid`，真实 AppID 只存在本机**。
 *
 * 两个模式（由 package.json 的钩子决定）：
 *   `node scripts/inject-appid.mjs --restore-after`
 *       配合 `prebuild:mp-weixin`：注入 → 构建 → 由 `postbuild:mp-weixin` 还原。
 *       效果：每次构建后 `git status` 都是干净的，不会留下含真实 AppID 的改动。
 *   `node scripts/inject-appid.mjs`（不带参数）
 *       只注入不还原。给 `npm run dev:mp-weixin` 用 —— 开发者工具要一直读到 AppID。
 *
 * AppID 来源优先级（高 → 低）：
 *   1. 环境变量 `WX_APPID`
 *   2. 项目根目录的 `.appid` 文件（一行纯文本，已 gitignore）
 *   3. 都没有 → 保留占位符，只提示，不阻断（H5 构建不需要 AppID）
 */
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const manifestPath = path.join(root, 'src', 'manifest.json')
const appidFile = path.join(root, '.appid')
const PLACEHOLDER = 'touristappid'
const inGitRepo = fs.existsSync(path.join(root, '..', '..', '.git'))

/** 合法 AppID 形如 wx + 16 位十六进制（占位符不算） */
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

/** 读文件并记住它的行尾，写回时保持一致，避免产生纯行尾的假 diff */
function readManifest() {
  // ★ 必须剥掉 UTF-8 BOM：用 PowerShell 的 `Set-Content -Encoding UTF8` 改过这个文件的话
  //   开头会多出 EF BB BF，`JSON.parse` 会直接抛 `Unexpected token ''`，
  //   而 uni 自己又能容忍 BOM —— 结果就是「构建正常但注入静默失效」。踩过一次。
  const raw = fs.readFileSync(manifestPath, 'utf8').replace(/^\uFEFF/, '')
  return { manifest: JSON.parse(raw), eol: raw.includes('\r\n') ? '\r\n' : '\n' }
}

function writeManifest(manifest, eol) {
  const json = JSON.stringify(manifest, null, 2)
  const text = eol === '\r\n' ? json.replace(/\n/g, '\r\n') : json
  // 不带 BOM 写盘（第三个参数省略即 UTF-8 无 BOM）
  fs.writeFileSync(manifestPath, `${text}${eol}`, 'utf8')
}

/** 用 git 把 manifest 还原成索引里的版本（最可靠的还原方式） */
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
    // 不在 git 仓库里（或 git 不可用）时退化成「手写回占位符」
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
      '        配置方式：在该项目根目录建一个 .appid 文件，写一行 AppID 即可（已 gitignore）。',
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
if (current && current !== PLACEHOLDER) {
  console.log(`[appid] 注意：原值不是占位符（${current.slice(0, 6)}…），别把它提交进仓库 —— 用 .appid 文件保存。`)
}
void inGitRepo
