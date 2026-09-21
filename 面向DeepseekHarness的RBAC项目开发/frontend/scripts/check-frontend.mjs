/**
 * 前端静态一致性检查。
 *
 * 为什么需要这个脚本：
 *   以下三类错误都是「构建能通过、但运行时报错/无声失效」的，在没有浏览器
 *   的情况下很难发现，而它们恰恰是本项目最容易犯的错：
 *
 *     1. 路由 meta 里引用的 .vue 组件文件不存在 → 打开页面白屏
 *     2. 菜单 icon 名字在 @element-plus/icons-vue 里不存在
 *        → 图标不渲染（Vue 只是打个警告，不报错，很容易漏掉）
 *     3. 前端用到的权限码在后端不存在 → v-permission 永远判定为无权限，
 *        按钮无声消失，排查起来很费劲
 *
 * 运行：  node scripts/check-frontend.mjs
 */

import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import * as icons from '@element-plus/icons-vue'

const __dirname = dirname(fileURLToPath(import.meta.url))
const SRC = resolve(__dirname, '..', 'src')

const failures = []
const notes = []

function ok(label, extra = '') {
  console.log(`  通过 ✓  ${label}${extra ? '  ' + extra : ''}`)
}

function fail(label, detail) {
  console.log(`  失败 ✗  ${label}`)
  if (detail) console.log(`          ${detail}`)
  failures.push(label)
}

/** 递归收集 src 下的所有文件 */
function walk(dir) {
  const result = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) result.push(...walk(full))
    else result.push(full)
  }
  return result
}

const files = walk(SRC)

// ---------------------------------------------------------------------------
// 1. 路由引用的组件文件是否存在
// ---------------------------------------------------------------------------
console.log('\n[1] 路由组件文件')
const routerSource = readFileSync(join(SRC, 'router', 'index.js'), 'utf-8')
const componentRefs = [...routerSource.matchAll(/import\(\s*['"]@\/(.+?)['"]\s*\)/g)].map(
  (m) => m[1],
)

if (componentRefs.length === 0) {
  fail('路由中未解析到任何组件引用', '正则可能失效，请检查 router/index.js 写法')
} else {
  for (const ref of componentRefs) {
    const target = join(SRC, ref)
    if (existsSync(target)) ok(`@/${ref}`)
    else fail(`@/${ref}`, '路由引用的组件文件不存在')
  }
}

// ---------------------------------------------------------------------------
// 2. 图标名字是否都存在于 @element-plus/icons-vue
// ---------------------------------------------------------------------------
console.log('\n[2] Element Plus 图标名')
const iconNames = new Set(Object.keys(icons))

// 2a. 后端菜单数据里的 icon（最容易出错的地方：写错了前端只是不显示图标）
const menuSource = readFileSync(
  resolve(__dirname, '..', '..', 'backend', 'app', 'menus.py'),
  'utf-8',
)
const menuIcons = [...menuSource.matchAll(/"icon":\s*"([A-Za-z]+)"/g)].map((m) => m[1])

for (const name of [...new Set(menuIcons)]) {
  if (iconNames.has(name)) ok(`菜单图标 ${name}`)
  else fail(`菜单图标 ${name}`, 'BACKEND app/menus.py 中的图标名在 Element Plus 里不存在')
}

// 2b. 模板里 <component :is="..."> 与动态图标、以及直接使用的全局图标组件
const templateIconUsage = new Set()
for (const file of files.filter((f) => f.endsWith('.vue'))) {
  const source = readFileSync(file, 'utf-8')
  // 匹配模板中的 <ElIcon><Xxx /></ElIcon>、<el-icon><Xxx /></el-icon>
  for (const m of source.matchAll(/<el-icon[^>]*>\s*<([A-Z][A-Za-z0-9]*)\s*\/>/g)) {
    templateIconUsage.add(m[1])
  }
  // 匹配 :icon="Xxx" / :prefix-icon="Xxx"
  for (const m of source.matchAll(/:(?:prefix-)?icon="([A-Z][A-Za-z0-9]*)"/g)) {
    templateIconUsage.add(m[1])
  }
}

for (const name of [...templateIconUsage].sort()) {
  if (iconNames.has(name)) ok(`模板图标 ${name}`)
  else fail(`模板图标 ${name}`, '该名字在 @element-plus/icons-vue 中不存在（请检查大小写）')
}

// ---------------------------------------------------------------------------
// 3. 前端使用的权限码是否都存在于后端
// ---------------------------------------------------------------------------
console.log('\n[3] 权限码一致性')
const seedSource = readFileSync(
  resolve(__dirname, '..', '..', 'backend', 'seed.py'),
  'utf-8',
)
const backendCodes = new Set(
  [...seedSource.matchAll(/"code":\s*"([a-z]+:[a-z]+)"/g)].map((m) => m[1]),
)

const frontendCodes = new Set()
for (const file of files) {
  if (!/\.(vue|js)$/.test(file)) continue
  const source = readFileSync(file, 'utf-8')
  // v-permission="'xxx:yyy'" 与 v-permission.disable="'xxx:yyy'"
  for (const m of source.matchAll(/v-permission(?:\.\w+)*="'([a-z]+:[a-z]+)'"/g)) {
    frontendCodes.add(m[1])
  }
  // auth.has('xxx:yyy')
  for (const m of source.matchAll(/\.has\(\s*'([a-z]+:[a-z]+)'\s*\)/g)) {
    frontendCodes.add(m[1])
  }
  // 路由 meta 里的 permission: 'xxx:yyy'
  for (const m of source.matchAll(/permission:\s*'([a-z]+:[a-z]+)'/g)) {
    frontendCodes.add(m[1])
  }
}

if (frontendCodes.size === 0) {
  notes.push('未在源码中解析到权限码引用，正则可能需要更新')
} else {
  for (const code of [...frontendCodes].sort()) {
    if (backendCodes.has(code)) ok(`权限码 ${code}`)
    else fail(`权限码 ${code}`, '后端 seed.py 中没有该权限点，前端判断将永远为 false')
  }
}

// ---------------------------------------------------------------------------
// 4. v-permission 指令是否已注册
// ---------------------------------------------------------------------------
console.log('\n[4] v-permission 指令注册')
const mainSource = readFileSync(join(SRC, 'main.js'), 'utf-8')
if (mainSource.includes("directive('permission'") && mainSource.includes('directives/permission')) {
  ok("指令已在 main.js 中注册为 'permission'")
} else {
  fail('v-permission 指令未注册', "main.js 中缺少 app.directive('permission', ...)")
}

// ---------------------------------------------------------------------------
// 5. api 层调用的后端路径是否都存在
// ---------------------------------------------------------------------------
console.log('\n[5] 前端调用的后端路径')
const apiSource = readFileSync(join(SRC, 'api', 'index.js'), 'utf-8')
const calledPaths = [...apiSource.matchAll(/request\.(?:get|post|put|patch|delete)\(\s*[`'"]([^`'"]+)/g)].map(
  (m) => m[1],
)

const routersDir = resolve(__dirname, '..', '..', 'backend', 'app', 'routers')
const routeStrings = []
for (const f of readdirSync(routersDir).filter((f) => f.endsWith('.py'))) {
  routeStrings.push(readFileSync(join(routersDir, f), 'utf-8'))
}
const allBackendRoutes = routeStrings.join('\n')

for (const path of [...new Set(calledPaths)].sort()) {
  // 把前端模板变量 {id} 还原成正则形式，再粗略匹配后端是否声明过该路由
  const normalized = path.replace(/\$\{[^}]+\}/g, '').replace(/\/$/, '')
  const base = normalized.split('/').slice(0, 3).join('/')
  if (allBackendRoutes.includes(base)) ok(`${path}`)
  else fail(`${path}`, `后端路由中未找到 ${base}`)
}

// ---------------------------------------------------------------------------
// 汇总
// ---------------------------------------------------------------------------
console.log('\n' + '='.repeat(72))
if (notes.length) {
  console.log('提示：')
  notes.forEach((n) => console.log('  · ' + n))
}
if (failures.length) {
  console.log(`结果：${failures.length} 项失败 ✗`)
  failures.forEach((f) => console.log('  · ' + f))
  process.exit(1)
}
console.log('结果：全部通过 ✓')
console.log('='.repeat(72))
