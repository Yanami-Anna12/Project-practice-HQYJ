/**
 * 用 Vue 官方编译器解析模板，精确报出错误行号。
 *
 * 用法（在 frontend 目录下）：
 *   node scripts/compile-check.mjs                      # 检查全部 .vue
 *   node scripts/compile-check.mjs src/views/x.vue      # 检查指定文件
 *
 * ★ 为什么要用 createRequire：pnpm 的 node_modules 是严格隔离的，
 *   @vue/compiler-sfc 是 @vitejs/plugin-vue 的传递依赖，直接 import 拿不到。
 *   用 createRequire 从 plugin-vue 的位置解析，才能拿到真实路径。
 */

import { createRequire } from 'node:module'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, dirname } from 'node:path'
import { pathToFileURL } from 'node:url'

const require = createRequire(import.meta.url)
// 从 @vitejs/plugin-vue 出发解析 @vue/compiler-sfc 的真实路径
const pluginVuePath = require.resolve('@vitejs/plugin-vue')
const requireFromPlugin = createRequire(pathToFileURL(pluginVuePath))
const sfcPath = requireFromPlugin.resolve('@vue/compiler-sfc')
const { parse, compileTemplate } = await import(pathToFileURL(sfcPath).href)

const SRC = 'src'

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (name.endsWith('.vue')) out.push(p)
  }
  return out
}

const targets = process.argv.slice(2)
const files = targets.length ? targets : walk(SRC)

let bad = 0
for (const file of files) {
  const source = readFileSync(file, 'utf-8')
  const { descriptor, errors } = parse(source, { filename: file })

  const problems = []
  for (const e of errors) {
    problems.push(`SFC: ${e.message}${e.loc ? ` @ line ${e.loc.start.line}` : ''}`)
  }

  if (descriptor.template) {
    // 定位模板在源文件中的起始行，便于把行号换算回整个文件
    const templateStartLine = source
      .slice(0, source.indexOf(descriptor.template.content))
      .split('\n').length

    const res = compileTemplate({
      source: descriptor.template.content,
      filename: file,
      id: 'check',
    })
    for (const e of res.errors) {
      const msg = typeof e === 'string' ? e : e.message
      let loc = ''
      if (typeof e === 'object' && e.loc) {
        loc = ` @ 文件第 ${templateStartLine + e.loc.start.line - 1} 行`
        // 打印出错那一行的内容
        const lines = source.split('\n')
        const n = templateStartLine + e.loc.start.line - 1
        loc += `\n         ${lines[n - 1]?.trim().slice(0, 130)}`
      }
      problems.push(`TEMPLATE: ${msg}${loc}`)
    }
  }

  if (problems.length) {
    bad += 1
    console.log(`\n✗ ${relative('.', file)}`)
    for (const p of problems) console.log('   ', p)
  }
}

console.log(`\n检查 ${files.length} 个文件，${bad} 个有编译错误`)
process.exit(bad ? 1 : 0)
