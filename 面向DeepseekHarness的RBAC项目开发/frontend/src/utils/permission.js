/**
 * 统一的权限判定工具。
 *
 * ★ 这个文件的存在本身就是需求里那句话的注解：
 *   「菜单和按钮的隐藏仅作为体验优化，后端接口始终是最终防线。」
 *
 *   这里所有函数读的都是「登录时后端告诉前端的权限清单」，
 *   它在浏览器里、用户可以随意篡改（改 Pinia 状态或 localStorage 即可）。
 *   所以本文件的任何结果都**不能**作为安全依据，只能用来决定界面怎么画。
 *   真正的判定发生在后端 app/deps.py 的 authorize() 里，每次都实时查库。
 */

/**
 * 判断权限集合中是否包含指定权限码。
 * @param {Set<string>|string[]} owned 当前用户持有的权限码
 * @param {string} code 需要的权限码，如 'products:edit'
 * @returns {boolean}
 */
export function hasPermission(owned, code) {
  if (!code) return true // 未声明权限要求的资源，登录即可访问
  const set = owned instanceof Set ? owned : new Set(owned || [])
  return set.has(code)
}

/**
 * 判断是否拥有任意一个权限（用于父级菜单这类"任一子项可见即可见"的场景）。
 */
export function hasAnyPermission(owned, codes) {
  if (!codes || codes.length === 0) return true
  const set = owned instanceof Set ? owned : new Set(owned || [])
  return codes.some((c) => set.has(c))
}
