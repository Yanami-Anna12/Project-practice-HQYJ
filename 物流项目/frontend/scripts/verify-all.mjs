/**
 * 前端全量自检入口：依次跑 4 个 verify 脚本 + 模板编译检查，汇总结果。
 *
 * 用法（在 frontend 目录下，需先 pnpm run dev）：
 *   node scripts/verify-all.mjs
 */

import { spawnSync } from 'node:child_process'

const SCRIPTS = [
  ['verify-ui.mjs', '系统管理 + 基础数据 + 权限裁剪'],
  ['verify-edit-save.mjs', '各编辑弹窗的保存回归（禁用字段必须已回填）'],
  ['verify-scheduling.mjs', '车辆分配 + 调度页面'],
  ['verify-reports.mjs', '报表与看板'],
  ['verify-rules-monitor.mjs', '规则配置 + 监控集成'],
]

const rows = []
let totalPass = 0
let totalFail = 0
let totalErrors = 0

for (const [file, label] of SCRIPTS) {
  process.stdout.write(`\n${'='.repeat(66)}\n${file}  ——  ${label}\n${'='.repeat(66)}\n`)
  const r = spawnSync('node', [`scripts/${file}`], {
    stdio: 'inherit',
    shell: false,
  })
  // 子脚本退出码非 0 说明有失败项或控制台错误，具体数字从它自己的输出里看
  rows.push({ file, label, code: r.status })
}

// 模板编译检查
process.stdout.write(`\n${'='.repeat(66)}\ncompile-check.mjs  ——  模板编译检查\n${'='.repeat(66)}\n`)
const cc = spawnSync('node', ['scripts/compile-check.mjs'], { stdio: 'inherit', shell: false })
rows.push({ file: 'compile-check.mjs', label: '模板编译检查', code: cc.status })

console.log(`\n${'='.repeat(66)}`)
console.log('前端自检汇总')
console.log('='.repeat(66))
let failed = 0
for (const row of rows) {
  const ok = row.code === 0
  if (!ok) failed += 1
  console.log(`  ${ok ? '✓' : '✗'} ${row.file.padEnd(28)} ${row.label}`)
}
console.log('='.repeat(66))
console.log(
  failed === 0
    ? '全部通过（各项通过数见上方各脚本的输出）'
    : `${failed} 个脚本未通过，请查看上方详细输出`,
)
process.exit(failed ? 1 : 0)
