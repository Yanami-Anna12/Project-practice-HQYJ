<script setup>
/**
 * 底部导航（自绘，替换 pages.json 的静态 tabBar）。
 *
 * ★ 为什么自己画：小程序 tabBar 是静态配置，条目的数量与 pagePath 编译期就定死，
 *   运行时既不能增删条目也不能改 pagePath —— 硬塞进同一组固定位置的结果是
 *   「运维人员看到一个点进去空空的看板」。自绘后条目按角色动态生成，
 *   **不存在的入口根本不出现**，H5 与微信小程序行为也完全一致
 *   （原生自定义 tabBar 在 H5 上不可靠）。
 *
 * ★ 跳转一律用 uni.redirectTo：这些页面已不是 tabBar 页面，switchTab 会失效。
 *   redirectTo 关掉当前页再开目标页，栈深度恒为 1，不会「越点越深」。
 *
 * ★ 「任务 / 工单」这一项指向哪个页面由谁决定：
 *   现场作业端看的是「我的作业任务」（/pages/tasks/index，子任务粒度），
 *   管理端看的是「工单列表」（/pages/board/orders，工单粒度）——
 *   两者关注的对象不同，所以放在 utils/ui.js 的 roleTabs() 里统一定义。
 *
 * 用法：在页面根节点的最后一行写 <BottomNav />（没有 props）。
 */
import { computed } from 'vue'

import { getStoredUser } from '@/utils/storage'
import { roleTabs, unreadCount } from '@/utils/ui'

/** 当前账号的导航条目（登录/退出都会 reLaunch 重建页面栈，所以进页面时读到的就是当前账号） */
const tabs = computed(() => roleTabs(getStoredUser()))

/** 当前页面路径（带前导斜杠，如 /pages/home/index） */
function readCurrentPath() {
  const pages = getCurrentPages()
  const page = pages.length ? pages[pages.length - 1] : null
  if (!page) return ''
  const route = page.route || page.$page?.fullPath?.split('?')[0] || ''
  return route ? `/${String(route).replace(/^\//, '')}` : ''
}

/** ★ 缓存成 computed：直接在模板里调 getCurrentPages() 会在每次渲染时重复取 */
const path = computed(readCurrentPath)

/** 未读红点文案：超过 99 显示 99+ */
const badgeText = computed(() => (unreadCount.value > 99 ? '99+' : String(unreadCount.value)))

/** 切到某个条目（点当前页直接返回，避免白闪） */
function go(tab) {
  if (path.value === tab.path) return
  uni.redirectTo({
    url: tab.path,
    fail: () => {
      uni.reLaunch({ url: tab.path })
    },
  })
}
</script>

<template>
  <view v-if="tabs.length" class="bottom-nav">
    <view class="nav-inner">
      <view
        v-for="tab in tabs"
        :key="tab.key"
        class="nav-item"
        :class="path === tab.path ? 'nav-item-active' : ''"
        @click="go(tab)"
      >
        <view class="nav-text-wrap">
          <text class="nav-text">{{ tab.text }}</text>
          <!-- 未读红点只挂在「消息」这一项上 -->
          <text v-if="tab.key === 'messages' && unreadCount > 0" class="nav-badge">
            {{ badgeText }}
          </text>
        </view>
        <view class="nav-underline" />
      </view>
    </view>
  </view>
</template>

<style scoped>
/*
 * 固定在最底部。
 * ★ 安全区：iPhone 底部横条用 env(safe-area-inset-bottom) 留白，
 *   否则最后一项会被横条盖住（微信小程序 iOS 端也有这个问题）。
 */
.bottom-nav {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 100;
  background: #ffffff;
  border-top: 1rpx solid #e6e8eb;
  padding-bottom: env(safe-area-inset-bottom);
  padding-bottom: constant(safe-area-inset-bottom);
}

.nav-inner {
  display: flex;
  align-items: stretch;
  height: 100rpx;
}

.nav-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #8a9099;
  font-size: 26rpx;
  position: relative;
}

.nav-item-active {
  color: #1677ff;
  font-weight: 600;
}

.nav-text-wrap {
  position: relative;
  padding: 0 16rpx;
}

/* 未读红点：数字角标挂在文字右上角 */
.nav-badge {
  position: absolute;
  top: -14rpx;
  right: -22rpx;
  min-width: 32rpx;
  height: 32rpx;
  line-height: 32rpx;
  padding: 0 8rpx;
  box-sizing: border-box;
  border-radius: 16rpx;
  background: #d03050;
  color: #ffffff;
  font-size: 20rpx;
  font-weight: 400;
  text-align: center;
}

/* 当前项的下划线：色块高亮，比「只变文字颜色」更容易一眼认出 */
.nav-underline {
  position: absolute;
  bottom: 8rpx;
  width: 48rpx;
  height: 6rpx;
  border-radius: 3rpx;
}

.nav-item-active .nav-underline {
  background: #1677ff;
}
</style>
