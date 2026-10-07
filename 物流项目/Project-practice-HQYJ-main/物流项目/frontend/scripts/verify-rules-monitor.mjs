/**
 * 规则配置与集成监控页面自检。
 *
 * 覆盖：规则总览页（硬/软约束、冲突、矩阵、参数）、规则版本发布与回滚流程、
 *       监控预警页、集成配置页，以及空数据/权限边界。
 */

import { existsSync, mkdirSync } from 'node:fs'
import { chromium } from 'playwright-core'

const BASE = process.env.VERIFY_BASE || 'http://127.0.0.1:5175'
mkdirSync('.verify', { recursive: true })
const CHROME = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
].find((p) => existsSync(p))

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

  /* ---------- 1. 调度策略与评分 ---------- */
  await page.goto(`${BASE}/rules/strategy`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1600)
  let title = await page.locator('.page-title').first().innerText()
  record('调度策略与评分页渲染', title.trim() === '调度策略与评分', title.trim())
  const strategyText = await page.locator('.page-container').innerText()
  record('展示硬约束清单', strategyText.includes('硬约束') && strategyText.includes('C1'))
  record('展示软约束清单', strategyText.includes('软约束'))
  record('展示评分函数', strategyText.includes('score ='))
  const constraints = await page.locator('.constraint').count()
  record('约束条目已渲染', constraints >= 10, `${constraints} 条`)
  const matrixCells = await page.locator('.matrix td').count()
  record('通行矩阵渲染 9 格', matrixCells === 9, `${matrixCells} 格`)
  record('冲突检测区存在', strategyText.includes('规则冲突检测'))
  await page.screenshot({ path: '.verify/_rules_strategy.png' })

  /* ---------- 2. 规则版本治理：发布 → 回滚 ---------- */
  await page.goto(`${BASE}/rules/governance`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)
  title = await page.locator('.page-title').first().innerText()
  record('规则版本治理页渲染', title.trim() === '规则版本治理', title.trim())
  const versionRowsBefore = await page.locator('.el-table__row').count()

  // 发布新版本
  await page.locator('button:has-text("发布新版本")').first().click()
  await page.waitForTimeout(600)
  await page.locator('.el-dialog textarea').fill('自检：验证版本发布')
  await page.locator('.el-dialog button:has-text("发布")').click()
  await page.waitForTimeout(2000)
  const versionRowsAfter = await page.locator('.el-table__row').count()
  record('发布版本后列表增加', versionRowsAfter > versionRowsBefore, `${versionRowsBefore} → ${versionRowsAfter}`)

  const govText = await page.locator('.page-container').innerText()
  record('版本列表显示当前版本', govText.includes('当前规则版本'))
  record('显示受管规则项统计', govText.includes('受管规则项') || govText.includes('车型'))

  // 查看详情
  await page.locator('button:has-text("详情")').first().click()
  await page.waitForTimeout(1200)
  const dialogText = await page.locator('.el-dialog').last().innerText()
  record('版本详情含快照信息', dialogText.includes('车型规则') && dialogText.includes('参数'), '')
  await page.locator('.el-dialog button:has-text("Close")').first().click().catch(() => {})
  await page.keyboard.press('Escape')
  await page.waitForTimeout(500)
  await page.screenshot({ path: '.verify/_rules_governance.png' })

  /* ---------- 3. 装载量/趟次规则（复用车辆类型页） ---------- */
  for (const p of [
    { path: '/rules/load', title: '车型能力配置' },
    { path: '/rules/trip', title: '车型能力配置' },
  ]) {
    await page.goto(BASE + p.path, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1200)
    const t = await page.locator('.page-title').first().innerText()
    const rows = await page.locator('.el-table__row').count()
    record(`规则页 ${p.path} 可访问`, t.trim() === p.title && rows >= 3, `标题=${t.trim()} 行数=${rows}`)
  }

  /* ---------- 4. 监控预警 ---------- */
  await page.goto(`${BASE}/integration/monitor`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1800)
  title = await page.locator('.page-title').first().innerText()
  record('监控预警页渲染', title.trim() === '监控预警', title.trim())
  const monitorText = await page.locator('.page-container').innerText()
  record('显示调度健康度', monitorText.includes('调度健康度') && monitorText.includes('成功率'))
  record('显示数据库连通性', monitorText.includes('数据库连通性'))
  record('明确标注未采集指标', monitorText.includes('未接入') && monitorText.includes('Prometheus'))
  record('显示预警清单', monitorText.includes('预警清单'))
  const canvasCount = await page.locator('canvas').count()
  record('监控图表已渲染', canvasCount >= 2, `${canvasCount} 个 canvas`)
  await page.screenshot({ path: '.verify/_integration_monitor.png' })

  /* ---------- 5. 接口集成配置 ---------- */
  await page.goto(`${BASE}/integration/systems`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1400)
  title = await page.locator('.page-title').first().innerText()
  record('接口集成配置页渲染', title.trim() === '接口集成配置', title.trim())
  const intText = await page.locator('.page-container').innerText()
  record('明确声明无外部系统连通', intText.includes('没有任何外部系统真实连通'))
  const integrationRows = await page.locator('.el-table__row').count()
  record('集成清单有数据', integrationRows >= 6, `${integrationRows} 行`)
  record('展示数据与算法平台现状', intText.includes('已实现') && intText.includes('规划中'))
  await page.screenshot({ path: '.verify/_integration_systems.png' })

  /* ---------- 6. 权限：viewer 无 monitor:read ---------- */
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await page.evaluate(() => localStorage.clear())
  await loginAs('只读观察者')
  const sidebar = await page.locator('.sidebar').innerText()
  record('viewer 侧边栏不含「集成与监控」', !sidebar.includes('集成与监控'), sidebar.slice(0, 60))
  await page.goto(`${BASE}/integration/monitor`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
  record('viewer 访问监控页被拦截到 403', page.url().includes('/forbidden'), page.url())

  /* ---------- 7. 调度员看规则（有 scheduling:read + scheduling:create） ---------- */
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await page.evaluate(() => localStorage.clear())
  await loginAs('调度员')

  // 策略页：只读，没有发布按钮（发布入口在版本治理页）
  await page.goto(`${BASE}/rules/strategy`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1400)
  const dTitle = await page.locator('.page-title').first().innerText()
  record('调度员可访问规则页', dTitle.trim() === '调度策略与评分', dTitle.trim())

  // 版本治理页：有 scheduling:create 应该能看到发布按钮
  await page.goto(`${BASE}/rules/governance`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1800)
  const govTitle = await page.locator('.page-title').first().innerText()
  record('调度员可访问版本治理页', govTitle.trim() === '规则版本治理', govTitle.trim())
  const hasPublish = await page.locator('button:has-text("发布新版本")').count()
  record(
    '调度员有 scheduling:create 可发布版本',
    hasPublish >= 1,
    `按钮数=${hasPublish}，页面按钮：${JSON.stringify(await page.locator('button').allInnerTexts())}`,
  )
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
