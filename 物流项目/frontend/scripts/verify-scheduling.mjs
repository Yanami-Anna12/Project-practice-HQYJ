/**
 * 调度相关页面自检（不跑求解，避免与 check_scheduling.py 重复）。
 *
 * 覆盖：页面渲染、数据行数、预检提示、方案卡片、异常页与分配结果页。
 * 创建调度任务的完整链路由 backend/check_scheduling.py 覆盖（那里的断言更细）。
 */

import { existsSync, mkdirSync } from 'node:fs'
import { chromium } from 'playwright-core'

const BASE = process.env.VERIFY_BASE || 'http://127.0.0.1:5175'
const CHROME = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
].find((p) => existsSync(p))

/**
 * 截图输出目录。
 *
 * ★ 末尾的斜杠不能省：早先写成 `.verify${path}` 会拼出 `.verify_base_stores.png`
 *   这种以点开头的散落文件（不是目录），既污染仓库根目录又匹配不到 .gitignore。
 */
const OUT = '.verify/'
mkdirSync(OUT, { recursive: true })

const results = []
const errors = []

function record(name, ok, note = '') {
  results.push({ name, ok })
  console.log(`${ok ? '✓' : '✗'} ${name}${note ? ' — ' + note : ''}`)
}

const browser = await chromium.launch({ executablePath: CHROME, headless: true })
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })

const EXPECTED_HTTP = ['409', '403']
page.on('console', (msg) => {
  const t = msg.text()
  if (
    msg.type() === 'error' &&
    !(t.includes('Failed to load resource') && EXPECTED_HTTP.some((c) => t.includes(c)))
  ) {
    errors.push(`[console] ${t}`)
  }
})
page.on('pageerror', (e) => errors.push(`[pageerror] ${e.message}`))

async function loginAs(label) {
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await page.locator('.account', { hasText: label }).click()
  await page.locator('button.submit').click()
  await page.waitForURL(/\/dashboard/, { timeout: 10000 })
  await page.waitForLoadState('networkidle')
}

try {
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await page.evaluate(() => localStorage.clear())
  await loginAs('系统管理员')

  /* ---------- 1. 车辆分配管理 ---------- */
  const assignPages = [
    { path: '/assign/available', title: '可出勤车辆', minRows: 30 },
    { path: '/assign/demand', title: '门店配送需求', minRows: 0 },
    { path: '/assign/result', title: '分配结果', minRows: 0 },
  ]
  for (const p of assignPages) {
    await page.goto(BASE + p.path, { waitUntil: 'networkidle' })
    await page.waitForTimeout(900)
    const title = await page.locator('.page-title').first().innerText().catch(() => '')
    const rowCount = await page.evaluate(() => {
      const tables = [...document.querySelectorAll('.el-table')]
      return tables.length
        ? Math.max(...tables.map((t) => t.querySelectorAll('.el-table__row').length))
        : 0
    })
    record(
      `分配页 ${p.title}`,
      title.trim() === p.title && (p.minRows === 0 || rowCount >= p.minRows),
      `标题=${title.trim()} 行数=${rowCount}`,
    )
    await page.screenshot({ path: `${OUT}${p.path.replace(/\//g, '_')}.png` })
  }

  /* ---------- 2. 调度任务页：预检应显示 16 店 / 40 车左右 ---------- */
  await page.goto(`${BASE}/scheduling/tasks`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)
  const taskTitle = await page.locator('.page-title').innerText()
  record('调度任务页渲染', taskTitle.trim() === '调度任务', taskTitle.trim())
  const pageText = await page.locator('.page-container').innerText()
  record('创建表单存在', pageText.includes('开始调度'))
  record('可行性预检已展示', pageText.includes('可行性预检') || pageText.includes('预检'))
  record('历史任务列表存在', pageText.includes('历史调度任务'))
  await page.screenshot({ path: '.verify/_scheduling_tasks.png' })

  /* ---------- 3. 多方案比选页 ---------- */
  await page.goto(`${BASE}/scheduling/plans`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)
  const planTitle = await page.locator('.page-title').innerText()
  record('多方案比选页渲染', planTitle.trim() === '多方案比选', planTitle.trim())
  const planCards = await page.locator('.plan-card').count()
  record('方案卡片已渲染', planCards >= 1, `${planCards} 张`)
  if (planCards > 0) {
    const compareTable = await page.locator('.el-table').count()
    record('指标对比表存在', compareTable >= 1)
    const bestMarks = await page.locator('.best-value').count()
    record('最优值高亮生效', bestMarks > 0, `${bestMarks} 处`)
  }
  await page.screenshot({ path: '.verify/_scheduling_plans.png' })

  /* ---------- 4. 人工确认页 ---------- */
  await page.goto(`${BASE}/scheduling/confirm`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)
  const confirmTitle = await page.locator('.page-title').innerText()
  record('人工确认页渲染', confirmTitle.trim() === '人工确认', confirmTitle.trim())
  const confirmText = await page.locator('.page-container').innerText()
  record('确认页展示任务列表', confirmText.includes('待确认') || confirmText.includes('方案'))
  await page.screenshot({ path: '.verify/_scheduling_confirm.png' })

  /* ---------- 5. 异常重排页 ---------- */
  await page.goto(`${BASE}/scheduling/exception`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
  const exTitle = await page.locator('.page-title').innerText()
  record('异常重排页渲染', exTitle.trim() === '异常重排', exTitle.trim())
  const exText = await page.locator('.page-container').innerText()
  record('展示重排次数上限', exText.includes('重排次数') || exText.includes('上限'))
  record('上报异常入口存在', exText.includes('上报异常'))
  await page.screenshot({ path: '.verify/_scheduling_exception.png' })

  /* ---------- 6. 权限：viewer 看不到创建按钮 ---------- */
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await page.evaluate(() => localStorage.clear())
  await loginAs('只读观察者')
  await page.goto(`${BASE}/scheduling/tasks`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
  const viewerText = await page.locator('.page-container').innerText()
  const hasCreateBtn = await page.locator('button:has-text("开始调度")').count()
  record('viewer 无「开始调度」按钮（v-permission 生效）', hasCreateBtn === 0, `按钮数=${hasCreateBtn}`)
  record('viewer 仍可查看任务列表', viewerText.includes('历史调度任务'))
} catch (err) {
  record('自检过程异常', false, err.message)
} finally {
  console.log('\n================ 控制台错误 ================')
  if (!errors.length) console.log('无控制台错误')
  else {
    for (const e of errors.slice(0, 20)) console.log(e)
    console.log(`共 ${errors.length} 条`)
  }
  const failed = results.filter((r) => !r.ok)
  console.log(`\n结果：${results.length - failed.length}/${results.length} 通过`)
  await browser.close()
  process.exit(failed.length || errors.length ? 1 : 0)
}
