/**
 * 检查所有 CRUD 页面：是否存在「编辑时被禁用、但校验要求必填、且 toForm 没回填」的字段。
 *
 * 这类字段一旦出现，编辑弹窗就会变成死循环：
 *   输入框是灰的（改不了）→ 里面是空的 → 点保存被必填校验拦住 → 永远存不了。
 *
 * 用法：node scripts/check-form-fields.mjs
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (name.endsWith('.vue')) out.push(p)
  }
  return out
}

/** 从源码里取出 toForm 箭头函数的返回体（按花括号配平） */
function extractToForm(text) {
  const idx = text.indexOf('toForm:')
  if (idx < 0) return null
  const open = text.indexOf('{', idx)
  if (open < 0) return null
  let depth = 0
  for (let i = open; i < text.length; i += 1) {
    const ch = text[i]
    if (ch === '{') depth += 1
    else if (ch === '}') {
      depth -= 1
      if (depth === 0) return text.slice(open, i + 1)
    }
  }
  return text.slice(open)
}

/** 取出 blank 工厂的返回体 */
function extractBlank(text) {
  const idx = text.indexOf('blank:')
  if (idx < 0) return null
  const open = text.indexOf('{', idx)
  if (open < 0) return null
  let depth = 0
  for (let i = open; i < text.length; i += 1) {
    const ch = text[i]
    if (ch === '{') depth += 1
    else if (ch === '}') {
      depth -= 1
      if (depth === 0) return text.slice(open, i + 1)
    }
  }
  return text.slice(open)
}

let problems = 0
let checked = 0

for (const file of walk('src')) {
  const text = readFileSync(file, 'utf-8')
  if (!text.includes('useCrud(')) continue
  checked += 1

  // 被 :disabled="isEditing" 禁用的 v-model 字段
  const disabledFields = []
  const re = /v-model="form\.(\w+)"[^>]*?:disabled="isEditing"/gs
  let m
  while ((m = re.exec(text)) !== null) disabledFields.push(m[1])

  if (!disabledFields.length) continue

  // 必填字段
  const requiredFields = []
  const rre = /(\w+):\s*\[\s*\{\s*required:\s*true/g
  while ((m = rre.exec(text)) !== null) requiredFields.push(m[1])

  const toFormBody = extractToForm(text) || ''
  const blankBody = extractBlank(text) || ''

  const label = relative('.', file)
  const bad = []
  for (const f of disabledFields) {
    const inToForm = new RegExp(`\\b${f}\\s*:`).test(toFormBody)
    const isRequired = requiredFields.includes(f)
    if (isRequired && !inToForm) bad.push(f)
  }

  if (bad.length) {
    problems += 1
    console.log(`✗ ${label}`)
    for (const f of bad) {
      console.log(`     字段 ${f}：编辑时被禁用（改不了）+ 校验要求必填 + toForm 未回填`)
      console.log(`     → 结果是编辑弹窗永远保存不了`)
    }
    console.log(`     toForm 实际回填的字段：${(toFormBody.match(/(\w+)\s*:/g) || []).map((s) => s.replace(/\s*:$/, '')).join(', ')}`)
    console.log(`     blank  提供的字段：${(blankBody.match(/(\w+)\s*:/g) || []).map((s) => s.replace(/\s*:$/, '')).join(', ')}`)
  } else {
    console.log(`✓ ${label}  （禁用字段 ${disabledFields.join('/')} 均已正确回填或无必填）`)
  }
}

console.log('')
console.log(`检查了 ${checked} 个使用 useCrud 的页面，发现 ${problems} 个有问题`)
process.exit(problems ? 1 : 0)
