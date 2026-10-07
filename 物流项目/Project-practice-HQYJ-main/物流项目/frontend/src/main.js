/**
 * 应用入口。
 */

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import 'element-plus/dist/index.css'
import '@/styles/index.css'

import App from '@/App.vue'
import router from '@/router'
import permissionDirective from '@/directives/permission'

const app = createApp(App)

// Element Plus 图标全局注册（侧边栏菜单按名称动态取图标组件）
for (const [name, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(name, component)
}

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })

// 按钮级权限指令：v-permission="'users:manage'"
app.directive('permission', permissionDirective)

app.mount('#app')
