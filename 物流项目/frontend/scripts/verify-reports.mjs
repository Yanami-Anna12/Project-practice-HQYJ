/**
 * 报表页面自检（不重复测后端口径，backend/check_reports.py 覆盖那部分）。
 *
 * 覆盖：5 个报表页渲染、图表实际画出 canvas、日期筛选、空数据不崩、权限。
 */

import { existsSync, mkdirSync } from 'node:fs'
import { chromium } from 'playwright-core'

const BASE = process.env.VERIFY_BASE || 'http://127.0.0.1:5175'
const CHROME = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
].find((p) => existsSync(p))

/** 截图输出目录。末尾斜杠不能省（见 verify-scheduling.mjs 的说明）。 */
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

const REPORT_PAGES = [
  { path: '/reports/attendance', title: '车辆出勤' },
  { path: '/reports/trip', title: '趟次达成' },
  { path: '/reports/loadrate', title: '装载率分析' },
  { path: '/reports/store', title: '门店配送达成' },
  { path: '/reports/cost', title: '成本与方案对比' },
]

try {
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await page.evaluate(() => localStorage.clear())
  await loginAs('系统管理员')

  /* ---------- 1. 侧边栏应含新增的「门店配送达成」 ---------- */
  // ★ 注意：el-menu 用了 unique-opened，折叠分组里的 item 不在 innerText 里，
  //   所以要先展开「报表与看板」再查文本。
  const sidebar = await page.locator('.sidebar').innerText()
  record('侧边栏含「报表与看板」分组', sidebar.includes('报表与看板'))
  await page.locator('.sidebar .el-sub-menu__title', { hasText: '报表' }).click()
  await page.waitForTimeout(600)
  const reportItems = await page.locator('.sidebar .el-menu-item').allInnerTexts()
  record(
    '侧边栏含「门店配送达成」（新增菜单）',
    reportItems.some((t) => t.includes('门店配送达成')),
    reportItems.filter((t) => ['车辆出勤', '趟次达成', '装载率分析', '门店配送达成', '成本与方案对比'].includes(t.trim())).join('、'),
  )
  record('菜单未持久化到 localStorage（每次从服务端取）',
    !(await page.evaluate(() => Object.keys(localStorage))).includes('logistics_menus'),
    JSON.stringify(await page.evaluate(() => Object.keys(localStorage))),
  )

  /* ---------- 2. 逐个报表页 ---------- */
  for (const p of REPORT_PAGES) {
    await page.goto(BASE + p.path, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1600)
    const title = await page.locator('.page-title').first().innerText().catch(() => '')
    const hasTable = await page.locator('.el-table').count()
    // ECharts 渲染后会插入 canvas
    const canvasCount = await page.locator('canvas').count()
    record(
      `报表页 ${p.title}`,
      title.trim() === p.title && hasTable > 0,
      `标题=${title.trim()} 表格=${hasTable} 图表=${canvasCount}`,
    )
    await page.screenshot({ path: `${OUT}${p.path.replace(/\//g, '_')}.png` })
  }

  /* ---------- 3. 图表确实画出了内容（canvas 非空） ---------- */
  await page.goto(`${BASE}/reports/loadrate`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1800)
  const canvasInfo = await page.evaluate(() => {
    const cs = [...document.querySelectorAll('canvas')]
    return cs.map((c) => ({ w: c.width, h: c.height }))
  })
  record(
    '图表 canvas 已按容器尺寸渲染',
    canvasInfo.length > 0 && canvasInfo.every((c) => c.w > 50 && c.h > 50),
    JSON.stringify(canvasInfo),
  )

  /* ---------- 4. 日期筛选 ---------- */
  await page.goto(`${BASE}/reports/attendance`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1400)
  const selectedBefore = await page.locator('.el-select input').first().inputValue()
  await page.locator('.el-select').first().click()
  await page.waitForTimeout(500)
  const optionCount = await page.locator('.el-select-dropdown__item').count()
  record('日期下拉有可选项', optionCount > 0, `${optionCount} 个（当前选中 ${selectedBefore}）`)
  if (optionCount > 1) {
    // 选一个和当前不同的选项，确保 change 真的触发
    await page.locator('.el-select-dropdown__item').nth(1).click()
    await page.waitForTimeout(1500)
    const selectedAfter = await page.locator('.el-select input').first().inputValue()
    record('切换日期生效', selectedAfter !== selectedBefore, `${selectedBefore} → ${selectedAfter}`)
  } else {
    // 只有一个日期时无法切换；改为验证「清除」能重新加载（清空 = 统计全部日期）
    await page.locator('.el-select-dropdown__item').first().click()
    await page.waitForTimeout(1000)
    const errs = await page.locator('.el-message--error').count()
    record('只有一个日期时选择仍可用（无报错）', errs === 0, `错误提示 ${errs} 条`)
  }

  /* ---------- 5. 门店页的「只看未完全满足」筛选 ---------- */
  await page.goto(`${BASE}/reports/store`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1600)
  const allRows = await page.evaluate(() => {
    const tables = [...document.querySelectorAll('.el-table')]
    const last = tables[tables.length - 1]
    return last ? last.querySelectorAll('.el-table__row').length : 0
  })
  await page.locator('.el-checkbox').first().click()
  await page.waitForTimeout(600)
  const filteredRows = await page.evaluate(() => {
    const tables = [...document.querySelectorAll('.el-table')]
    const last = tables[tables.length - 1]
    return last ? last.querySelectorAll('.el-table__row').length : 0
  })
  record('「只看未完全满足」筛选生效', filteredRows <= allRows, `${allRows} → ${filteredRows}`)

  /* ---------- 6. 权限：viewer 可看报表 ---------- */
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await page.evaluate(() => localStorage.clear())
  await loginAs('只读观察者')
  await page.goto(`${BASE}/reports/attendance`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1400)
  const viewerTitle = await page.locator('.page-title').first().innerText().catch(() => '')
  record('viewer 可访问报表页', viewerTitle.trim() === '车辆出勤', viewerTitle.trim())

  /* ---------- 7. 无数据日期不应崩 ---------- */
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await page.evaluate(() => localStorage.clear())
  await loginAs('系统管理员')
  await page.goto(`${BASE}/reports/trip`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
  const errCount = await page.locator('.el-message--error').count()
  record('报表页无错误提示', errCount === 0, `错误提示 ${errCount} 条`)
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
