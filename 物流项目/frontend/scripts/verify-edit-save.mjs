/**
 * 编辑保存回归测试。
 *
 * ★ 这个用例来自一个真实 bug：编辑弹窗里「门店编码」是禁用的（改不了），
 *   但校验规则要求它必填，而表单里它是空的 —— 导致编辑永远保存不了。
 *   同一个 bug 存在于 4 个页面（门店/线路/车辆/司机）。
 *
 * 本脚本对每个 CRUD 页面走一遍「打开编辑 → 直接点保存」，
 * 断言能保存成功（没有"请输入 xxx"的校验错误）。
 */

import { existsSync, mkdirSync } from 'node:fs'
import { chromium } from 'playwright-core'

const BASE = process.env.VERIFY_BASE || 'http://127.0.0.1:5175'
mkdirSync('.verify', { recursive: true })
const CHROME = [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
].find((p) => existsSync(p))

const results = []
const errors = []

function record(name, ok, note = '') {
  results.push({ name, ok })
  console.log(`${ok ? '✓' : '✗'} ${name}${note ? ' — ' + note : ''}`)
}

const browser = await chromium.launch({ executablePath: CHROME, headless: true })
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })

page.on('console', (msg) => {
  if (msg.type() === 'error' && !msg.text().includes('Failed to load resource')) {
    errors.push(`[console] ${msg.text()}`)
  }
})
page.on('pageerror', (e) => errors.push(`[pageerror] ${e.message}`))

/** 每个页面的编辑入口。roles 不是 useCrud 页面，一并覆盖以防同类问题。 */
const PAGES = [
  { path: '/base/stores', label: '门店' },
  { path: '/base/routes', label: '线路' },
  { path: '/base/vehicles', label: '车辆' },
  { path: '/base/drivers', label: '司机' },
  { path: '/system/roles', label: '角色' },
]

try {
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await page.evaluate(() => localStorage.clear())
  await page.locator('.account', { hasText: '系统管理员' }).click()
  await page.locator('button.submit').click()
  await page.waitForURL(/\/dashboard/, { timeout: 10000 })

  for (const p of PAGES) {
    await page.goto(BASE + p.path, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1200)

    // 记录第一行的标识字段值（编辑后应保持不变）
    const firstRowText = await page.locator('.el-table__row').first().innerText()

    // 打开编辑
    await page.locator('.el-table__row').first().locator('button:has-text("编辑")').click()
    await page.waitForTimeout(700)

    const dialog = page.locator('.el-dialog').last()
    const dialogVisible = await dialog.isVisible().catch(() => false)
    if (!dialogVisible) {
      record(`编辑弹窗可打开（${p.label}）`, false, '弹窗未出现')
      continue
    }

    // 关键断言：禁用字段里不该是空的
    const disabledInputs = await dialog.locator('input[disabled]').all()
    let emptyDisabled = []
    for (const input of disabledInputs) {
      const v = await input.inputValue()
      if (!v || !v.trim()) {
        const label = await input.evaluate((el) => {
          const item = el.closest('.el-form-item')
          return item ? item.querySelector('.el-form-item__label')?.textContent?.trim() : ''
        })
        emptyDisabled.push(label || '(未命名)')
      }
    }
    record(
      `禁用字段已回填（${p.label}）`,
      emptyDisabled.length === 0,
      emptyDisabled.length ? `空的禁用字段：${emptyDisabled.join('、')}` : `${disabledInputs.length} 个禁用字段都有值`,
    )

    // 什么都不改，直接保存 —— 应能成功
    await dialog.locator('button:has-text("保存")').click()
    await page.waitForTimeout(1500)

    const stillOpen = await dialog.isVisible().catch(() => false)
    const formError = await dialog
      .locator('.el-form-item__error')
      .first()
      .innerText()
      .catch(() => '')
    const successMsg = await page.locator('.el-message--success').count()

    record(
      `直接保存能成功（${p.label}）`,
      !stillOpen && !formError,
      stillOpen ? `弹窗未关闭，校验错误：${formError || '(无)'}` : '弹窗已关闭',
    )
    if (successMsg > 0) {
      // 等提示消失，避免影响下一页
      await page.waitForTimeout(2000)
    }

    // 数据没被改坏
    await page.waitForTimeout(500)
    const afterText = await page.locator('.el-table__row').first().innerText()
    record(`标识字段保持不变（${p.label}）`, afterText.split('\n')[0] === firstRowText.split('\n')[0],
      `${firstRowText.split('\n')[0]} → ${afterText.split('\n')[0]}`)

    await page.screenshot({ path: `.verify/_edit_${p.path.replace(/\//g, '_')}.png` })
  }
} catch (err) {
  record('自检过程异常', false, err.message)
} finally {
  console.log('\n================ 控制台错误 ================')
  if (!errors.length) console.log('无控制台错误')
  else {
    for (const e of errors.slice(0, 10)) console.log(e)
    console.log(`共 ${errors.length} 条`)
  }
  const failed = results.filter((r) => !r.ok)
  console.log(`\n结果：${results.length - failed.length}/${results.length} 通过`)
  await browser.close()
  process.exit(failed.length || errors.length ? 1 : 0)
}
