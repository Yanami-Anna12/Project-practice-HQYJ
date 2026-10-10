<script setup>
/**
 * 应用根组件。
 *
 * 放在这里的是「全应用级」的东西：全局样式、登录态兜底、未读红点与实时推送，
 * 具体页面逻辑一律写在 pages/ 下，保持和后端一样的分层。
 *
 * ★ 底部导航不再在这里「按角色改写文字」：pages.json 的静态 tabBar 已删除，
 *   改由 components/BottomNav.vue 按角色**渲染不同的条目**（不存在的入口
 *   根本不出现）。App.vue 只负责把未读数写进 utils/ui.js 的模块级状态，
 *   导航组件自己订阅那个状态。
 */
import { onLaunch, onShow } from '@dcloudio/uni-app'
import * as api from '@/api'
import { getToken } from '@/utils/storage'
import { bindNetworkWatcher, connectSocket, subscribeNotifications } from '@/utils/socket'
import { setUnread, unreadFromPayload } from '@/utils/ui'

/** 兜底：推送报文里没带未读数时，自己查一次 */
async function refreshUnread() {
  try {
    const res = await api.fetchUnreadCount()
    setUnread(res?.unread || 0)
  } catch (err) {
    console.warn('[app] 未读数获取失败', err)
  }
}

onLaunch(() => {
  // ★ 这里刻意不做「无 token 就 reLaunch 到登录页」：
  //   各页面自己有登录校验（utils/request.js 的 401 也会兜底跳登录），
  //   在 onLaunch 里跳转反而会和页面的校验打架，出现「闪一下又跳走」。
  console.log('[miniapp] 车辆智能调度小程序启动')

  // ★ 实时推送的「全局订阅」只做一件事：更新底部导航的未读红点。
  //   报文里带 unread（服务端推送那一刻算的），所以正常情况下不额外发请求；
  //   页面各自的反应（刷新列表、弹提示）由页面自己订阅，避免全局管太宽。
  //   ★ 「撤销下发」的报文带的是 unread_by_user（一次影响多个司机，
  //     每人未读数不同），所以统一用 unreadFromPayload() 取，取不到再查一次。
  subscribeNotifications((payload) => {
    if (payload.type !== 'notification' && payload.type !== 'connected') return
    const unread = unreadFromPayload(payload)
    if (unread !== null) {
      setUnread(unread)
    } else {
      refreshUnread()
    }
  })

  bindNetworkWatcher()
  // 冷启动时若已登录，直接把连接建起来（已连则什么都不做）
  if (getToken()) connectSocket()
})

onShow(() => {
  // 从后台切回前台：连接可能已被系统回收，这里补一次（connectSocket 幂等）
  if (getToken()) connectSocket()
})
</script>

<style>
/* ------------------------------------------------------------------ *
 * 全局样式：小程序端没有 CSS 框架，这里手写一套轻量样式，
 * 保证各页面视觉一致（与 web 前端的信息密度保持接近）。
 * ------------------------------------------------------------------ */
page {
  background-color: #f5f6f8;
  color: #1f2329;
  font-size: 28rpx;
  font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, sans-serif;
}

/*
 * 页面内容容器。
 * ★ 底部留白 = 自绘导航高度（100rpx）+ 安全区，否则最后一张卡片会被
 *   fixed 的底部导航盖住（滚到底也看不到最后一行）。
 *   100rpx 是 components/BottomNav.vue 里 .nav-inner 的高度，改那里要同步这里。
 */
.page {
  padding: 24rpx 24rpx 40rpx;
  padding-bottom: calc(140rpx + env(safe-area-inset-bottom));
  padding-bottom: calc(140rpx + constant(safe-area-inset-bottom));
}

/* 卡片 */
.card {
  background: #ffffff;
  border-radius: 16rpx;
  padding: 24rpx;
  margin-bottom: 20rpx;
  box-shadow: 0 2rpx 12rpx rgba(0, 0, 0, 0.04);
}

/* 状态栏 / 工具条 */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #ffffff;
  border-radius: 16rpx;
  padding: 20rpx 24rpx;
  margin-bottom: 20rpx;
}

/* 一行键值对 */
.row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 10rpx 0;
}

.row-label {
  color: #8a9099;
  flex-shrink: 0;
  margin-right: 20rpx;
}

.row-value {
  text-align: right;
  flex: 1;
  word-break: break-all;
}

/* 标题与说明 */
.title {
  font-size: 32rpx;
  font-weight: 600;
}

.desc {
  color: #8a9099;
  font-size: 24rpx;
  margin-top: 8rpx;
}

.muted {
  color: #8a9099;
}

/* 标签 */
.tag {
  display: inline-block;
  font-size: 22rpx;
  padding: 4rpx 14rpx;
  border-radius: 20rpx;
  margin-left: 12rpx;
}

.tag-planned {
  background: #eef0f3;
  color: #6b7280;
}

.tag-running {
  background: #e8f2ff;
  color: #1668dc;
}

.tag-done {
  background: #e8f7ee;
  color: #18a058;
}

.tag-warn {
  background: #fff4e6;
  color: #d97706;
}

.tag-danger {
  background: #fdecec;
  color: #d03050;
}

/*
 * 趟次「三色状态」标签（司机端趟次卡片/详情用）。
 * ★ 与卡片左侧色条同一套语义，别再各写颜色：
 *   待确认 = 红（要司机动手）  已接单未完成 = 黄（在手上）  已完成 = 绿（收工）
 */
.tag-pending {
  background: #fdecec;
  color: #d03050;
}

.tag-accepted {
  background: #fff7e0;
  color: #b7791f;
}

/* 按钮 */
.btn {
  border-radius: 12rpx;
  font-size: 28rpx;
  line-height: 2.4;
  text-align: center;
}

.btn-primary {
  background: #1668dc;
  color: #ffffff;
}

.btn-default {
  background: #ffffff;
  color: #1668dc;
  border: 1rpx solid #1668dc;
}

.btn-plain {
  background: #f0f1f3;
  color: #4b5563;
}

.btn-disabled {
  background: #e6e8eb;
  color: #a3a8b0;
}

/* 错误态 + 重试（离线容错，避免白屏） */
.error-box {
  background: #ffffff;
  border-radius: 16rpx;
  padding: 48rpx 24rpx;
  text-align: center;
}

.error-text {
  color: #d03050;
  margin-bottom: 24rpx;
}

/* 空态 */
.empty {
  text-align: center;
  color: #8a9099;
  padding: 80rpx 24rpx;
}

/* 未读红点 */
.red-dot {
  min-width: 32rpx;
  height: 32rpx;
  line-height: 32rpx;
  padding: 0 8rpx;
  border-radius: 16rpx;
  background: #d03050;
  color: #ffffff;
  font-size: 20rpx;
  text-align: center;
}
</style>
