import { createSSRApp } from 'vue'
import App from './App.vue'

/**
 * uni-app（Vue 3）入口。
 *
 * ★ 必须用 createSSRApp：uni-app 的 Vue 3 编译器要求返回 { app } 结构，
 *   小程序端由它接管页面生命周期（onLoad / onShow 等）。
 */
export function createApp() {
  const app = createSSRApp(App)
  return { app }
}
