/**
 * 界面自检脚本（开发期使用，不参与构建）。
 *
 * 用本机已安装的 Chrome 无头运行，检查：
 *   1. 控制台是否有报错
 *   2. 登录流程是否可用
 *   3. 系统管理 7 个页面是否都能正常渲染
 *   4. 权限裁剪是否生效（viewer 账号看不到「系统管理」）
 *
 * 用法：node scripts/verify-ui.mjs
 */

import { chromium } from 'playwright-core'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const BASE = process.env.VERIFY_BASE || 'http://127.0.0.1:5175'
/** 截图输出到 frontend/.verify/ */
const OUT = fileURLToPath(new URL('../.verify/', import.meta.url))

const CHROME_CANDIDATES = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
]

const executablePath = CHROME_CANDIDATES.find((p) => existsSync(p))
if (!executablePath) {
  console.error('找不到 Chrome/Edge，无法运行界面自检')
  process.exit(1)
}

const PAGES = [
  { path: '/system/users', title: '用户管理' },
  { path: '/system/roles', title: '角色管理' },
  { path: '/system/permissions', title: '权限管理' },
  { path: '/system/dicts', title: '字典管理' },
  { path: '/system/params', title: '参数管理' },
  { path: '/system/attachments', title: '附件管理' },
  { path: '/system/logs', title: '日志管理' },
]

/** 业务基础数据：每页都应有表格且有数据行 */
const BASE_PAGES = [
  { path: '/base/stores', title: '门店管理', minRows: 16 },
  { path: '/base/routes', title: '线路管理', minRows: 5 },
  { path: '/base/mappings', title: '门店线路映射', minRows: 19 },
  { path: '/base/vehicles', title: '车辆档案', minRows: 40 },
  { path: '/base/vehicle-types', title: '车型能力配置', minRows: 3 },
  { path: '/base/drivers', title: '司机管理', minRows: 8 },
  { path: '/base/terrain', title: '地形与通行规则', minRows: 0 },
]

const errors = []
const results = []

function record(name, ok, note = '') {
  results.push({ name, ok, note })
  console.log(`${ok ? '✓' : '✗'} ${name}${note ? ' — ' + note : ''}`)
}

const browser = await chromium.launch({ executablePath, headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await context.newPage()

/**
 * 预期的失败请求状态码。
 *
 * 浏览器会把 4xx/5xx 响应也记一条 console error（"Failed to load resource"）。
 * 但本自检里有几处**故意**触发业务拒绝（例如删除被引用的线路应返回 409），
 * 那不是缺陷，所以这些状态码不计入「控制台错误」。
 */
const EXPECTED_HTTP = ['409', '403']

function isExpectedHttpNoise(text) {
  return (
    text.includes('Failed to load resource') &&
    EXPECTED_HTTP.some((code) => text.includes(code))
  )
}

page.on('console', (msg) => {
  if (msg.type() === 'error' && !isExpectedHttpNoise(msg.text())) {
    errors.push(`[console] ${msg.text()}`)
  }
})
page.on('pageerror', (err) => errors.push(`[pageerror] ${err.message}`))

/** 登录：点击演示账号卡片填入，再点登录 */
async function loginAs(label) {
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await page.locator('.account', { hasText: label }).click()
  await page.locator('button.submit').click()
  await page.waitForURL(/\/dashboard/, { timeout: 10000 })
  await page.waitForLoadState('networkidle')
}

try {
  /* ---------- 1. 登录页 ---------- */
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  record('登录页渲染', await page.locator('.login-card').isVisible())

  /* ---------- 2. 管理员登录 ---------- */
  await loginAs('系统管理员')
  record('管理员登录并跳转看板', page.url().includes('/dashboard'))

  // 侧边栏应包含系统管理分组
  const sidebarText = await page.locator('.sidebar').innerText()
  record('侧边栏含「系统管理」', sidebarText.includes('系统管理'))
  record('侧边栏含「智能调度 Agent」', sidebarText.includes('智能调度 Agent'))

  /* ---------- 3. 逐个访问系统管理页 ---------- */
  for (const p of PAGES) {
    await page.goto(BASE + p.path, { waitUntil: 'networkidle' })
    await page.waitForTimeout(400)
    const heading = await page.locator('.page-title').first().innerText().catch(() => '')
    const hasTable = await page.locator('.el-table').first().isVisible().catch(() => false)
    const hasError = await page.locator('.el-message--error').count()
    record(
      `页面 ${p.title}`,
      heading.trim() === p.title && hasTable && hasError === 0,
      heading.trim() !== p.title ? `标题=${heading.trim()}` : hasError ? '有错误提示' : '',
    )
    await page.screenshot({ path: `${OUT}${p.path.replace(/\//g, '_')}.png` })
  }

  /* ---------- 4. 逐个访问业务基础数据页（含数据行数校验） ---------- */
  for (const p of BASE_PAGES) {
    await page.goto(BASE + p.path, { waitUntil: 'networkidle' })
    await page.waitForTimeout(700)
    const heading = await page.locator('.page-title').first().innerText().catch(() => '')
    const hasError = await page.locator('.el-message--error').count()
    // 车辆档案页有多个表格（统计卡不是表格），取行数最多的那个
    const rowCount = await page.evaluate(() => {
      const tables = [...document.querySelectorAll('.el-table')]
      return tables.length
        ? Math.max(...tables.map((t) => t.querySelectorAll('.el-table__row').length))
        : 0
    })
    const ok =
      heading.trim() === p.title &&
      hasError === 0 &&
      (p.minRows === 0 || rowCount >= p.minRows)
    record(
      `基础数据 ${p.title}`,
      ok,
      heading.trim() !== p.title
        ? `标题=${heading.trim()}`
        : hasError
          ? '有错误提示'
          : `行数=${rowCount}（期望 ≥${p.minRows}）`,
    )
    await page.screenshot({ path: `${OUT}${p.path.replace(/\//g, '_')}.png` })
  }

  /* ---------- 5. 基础数据写操作：新建门店 → 列表出现 → 删除 ---------- */
  await page.goto(`${BASE}/base/stores`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(600)
  const code = `V${Date.now().toString().slice(-6)}`
  await page.locator('button:has-text("新建门店")').click()
  await page.waitForTimeout(400)
  await page.locator('.el-dialog input').first().fill(code)
  await page.locator('.el-dialog input').nth(1).fill('验证用临时门店')
  await page.locator('.el-dialog button:has-text("保存")').click()
  await page.waitForTimeout(1000)
  const afterCreate = await page.locator('.el-table').first().innerText()
  record('新建门店成功并出现在列表', afterCreate.includes('验证用临时门店'), code)

  // 删除刚建的门店，保持数据干净
  const row = page.locator('.el-table__row', { hasText: '验证用临时门店' }).first()
  await row.locator('button:has-text("删除")').click()
  await page.waitForTimeout(400)
  await page.locator('.el-message-box button:has-text("删除")').click()
  await page.waitForTimeout(900)
  const afterDelete = await page.locator('.el-table').first().innerText()
  record('删除门店成功', !afterDelete.includes('验证用临时门店'))

  /* ---------- 6. 基础数据删除保护：线路仍关联门店时不许删 ---------- */
  await page.goto(`${BASE}/base/routes`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(600)
  await page.locator('.el-table__row').first().locator('button:has-text("删除")').click()
  await page.waitForTimeout(400)
  await page.locator('.el-message-box button:has-text("删除")').click()
  await page.waitForTimeout(900)
  const errText = await page.locator('.el-message--error').first().innerText().catch(() => '')
  record('删除有关联门店的线路被拒（409）', errText.includes('409') || errText.includes('关联') || errText.includes('解除'), errText.slice(0, 60))

  /* ---------- 7. 地形通行矩阵可切换 ---------- */
  await page.goto(`${BASE}/base/terrain`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(700)
  const cellCount = await page.locator('.matrix td.cell').count()
  record('地形矩阵渲染 9 个格子', cellCount === 9, `实际 ${cellCount}`)
  const beforeText = await page.locator('.matrix td.cell').first().innerText()
  await page.locator('.matrix td.cell').first().click()
  await page.waitForTimeout(1200)
  const afterText = await page.locator('.matrix td.cell').first().innerText()
  record('点击格子成功切换通行状态', beforeText.trim() !== afterText.trim(), `${beforeText.trim()} → ${afterText.trim()}`)
  // 切回去，保持初始配置
  await page.locator('.matrix td.cell').first().click()
  await page.waitForTimeout(1200)
  const restored = await page.locator('.matrix td.cell').first().innerText()
  record('再次点击已还原', restored.trim() === beforeText.trim(), restored.trim())

  /* ---------- 8. 写操作：改参数 → 日志应新增 ---------- */
  await page.goto(`${BASE}/system/params`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(600)

  await page.locator('button:has-text("修改")').first().click()
  await page.waitForTimeout(300)
  await page.locator('.el-dialog input').last().fill('999')
  await page.locator('.el-dialog button:has-text("确认修改")').click()
  await page.waitForTimeout(800)
  record('参数修改成功提示', (await page.locator('.el-message--success').count()) > 0)

  await page.goto(`${BASE}/system/logs`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(600)
  const logText = await page.locator('.el-table').first().innerText()
  record('日志页出现 param.update 记录', logText.includes('修改参数'))
  await page.screenshot({ path: `${OUT}_logs_after_edit.png` })

  /* ---------- 9. 权限裁剪：viewer 看不到系统管理 ---------- */
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await page.evaluate(() => localStorage.clear())
  await loginAs('只读观察者')
  const viewerSidebar = await page.locator('.sidebar').innerText()
  record('viewer 侧边栏不含「系统管理」', !viewerSidebar.includes('系统管理'))
  record('viewer 侧边栏含「报表与看板」', viewerSidebar.includes('报表与看板'))

  /* ---------- 6. 越权访问应被守卫拦截 ---------- */
  await page.goto(`${BASE}/system/users`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(500)
  record('viewer 访问用户管理被拦截', page.url().includes('/forbidden'))
  await page.screenshot({ path: `${OUT}_forbidden.png` })

  /* ---------- 7. 未知路由应落到 404 页（不是白屏） ---------- */
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await page.evaluate(() => localStorage.clear())
  await loginAs('系统管理员')
  await page.goto(`${BASE}/this-route-does-not-exist`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(500)
  const notFoundTitle = await page.locator('.page-title').first().innerText().catch(() => '')
  const notFoundBody = await page.locator('.page-container').innerText().catch(() => '')
  record(
    '未知路由落到 404 页（不是白屏）',
    notFoundTitle.trim() === '页面不存在' || notFoundBody.includes('404'),
    `标题=${notFoundTitle.trim()}`,
  )
} catch (err) {
  record('自检过程异常', false, err.message)
} finally {
  console.log('\n================ 控制台错误 ================')
  if (!errors.length) {
    console.log('无控制台错误')
  } else {
    for (const e of errors.slice(0, 30)) console.log(e)
    console.log(`共 ${errors.length} 条`)
  }

  const failed = results.filter((r) => !r.ok)
  console.log(`\n================ 结果：${results.length - failed.length}/${results.length} 通过 ================`)
  await browser.close()
  process.exit(failed.length || errors.length ? 1 : 0)
}
