<script setup>
/**
 * 应用根组件。
 *
 * 放在这里的是「全应用级」的东西：全局样式、实时未读推送。
 * 具体页面逻辑一律写在 pages/ 下，保持和后端一样的分层。
 *
 * ★ 底部导航不在 App.vue 里：pages.json 的静态 tabBar 已删除，
 *   改由 components/BottomNav.vue 按角色渲染不同的条目（不存在的入口根本不出现）。
 *   App.vue 只负责把未读数写进 utils/ui.js 的模块级状态，导航组件自己订阅。
 */
import { onLaunch, onShow } from '@dcloudio/uni-app'
import * as api from '@/api'
import { getToken } from '@/utils/storage'
import { connectNotificationSocket, subscribeNotifications } from '@/utils/socket'
import { setUnread, unreadFromPayload } from '@/utils/ui'

/** 兜底：推送报文里没带未读数时，自己查一次 */
async function refreshUnread() {
  try {
    const data = await api.fetchMessageList({ page: 1, pageSize: 1 })
    setUnread((data && data.unread_count) || 0)
  } catch (err) {
    console.warn('[app] 未读数获取失败', err)
  }
}

onLaunch(() => {
  // ★ 这里刻意不做「无 token 就 reLaunch 到登录页」：
  //   各页面自己有登录校验（utils/request.js 的 401 也会兜底跳登录），
  //   在 onLaunch 里跳转反而会和页面的校验打架，出现「闪一下又跳走」。
  console.log('[miniapp] 充电桩运维小程序启动')

  // ★ 实时未读：只做一件事 —— 更新底部导航的红点。
  //   页面各自的反应（刷新列表）由页面自己订阅，避免全局管太宽。
  subscribeNotifications((payload) => {
    const unread = unreadFromPayload(payload)
    if (unread !== null) {
      setUnread(unread)
    } else if (payload && payload.type === 'unread') {
      refreshUnread()
    }
  })

  // 冷启动时若已登录，直接把连接建起来（已连则什么都不做）
  if (getToken()) connectNotificationSocket()
})

onShow(() => {
  // 从后台切回前台：连接可能已被系统回收，这里补一次（connectNotificationSocket 幂等）
  if (getToken()) connectNotificationSocket()
})
</script>

<style>
/* ------------------------------------------------------------------ *
 * 全局样式：小程序端没有 CSS 框架，这里手写一套轻量样式，
 * 保证各页面视觉一致（与 web 管理后台的信息密度保持接近）。
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
  padding: 24rpx;
  padding-bottom: calc(140rpx + env(safe-area-inset-bottom));
  padding-bottom: calc(140rpx + constant(safe-area-inset-bottom));
}

/* 没有底部导航的页面（详情/表单/登录）：只留普通留白 */
.page-plain {
  padding-bottom: 40rpx;
}

/* 卡片 */
.card {
  background: #ffffff;
  border-radius: 16rpx;
  padding: 24rpx;
  margin-bottom: 20rpx;
  box-shadow: 0 2rpx 12rpx rgba(0, 0, 0, 0.04);
}

/* 区块标题 */
.section-title {
  font-size: 30rpx;
  font-weight: 600;
  margin: 8rpx 0 16rpx;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-more {
  font-size: 24rpx;
  color: #1677ff;
  font-weight: 400;
}

/* 工具条 */
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
  width: 170rpx;
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

.strong {
  font-weight: 600;
  color: #1f2329;
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
  color: #1677ff;
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
 * 「待办」标签：现场作业端最需要一眼看到的颜色。
 * 与 tag-warn 区分开：待办是「你要动手」，紧急/严重是「事情本身急」。
 */
.tag-pending {
  background: #fdecec;
  color: #d03050;
}

/* 按钮 */
.btn {
  border-radius: 12rpx;
  font-size: 28rpx;
  line-height: 2.4;
  text-align: center;
}

.btn::after {
  border: none;
}

.btn-primary {
  background: #1677ff;
  color: #ffffff;
}

.btn-default {
  background: #ffffff;
  color: #1677ff;
  border: 1rpx solid #1677ff;
}

.btn-plain {
  background: #f0f1f3;
  color: #4b5563;
}

.btn-danger {
  background: #ffffff;
  color: #d03050;
  border: 1rpx solid #d03050;
}

.btn-disabled {
  background: #e6e8eb;
  color: #a3a8b0;
}

/* 底部固定操作条（表单页/详情页用，避免主按钮被内容顶出屏幕） */
.footer-bar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  gap: 20rpx;
  padding: 16rpx 24rpx;
  padding-bottom: calc(16rpx + env(safe-area-inset-bottom));
  padding-bottom: calc(16rpx + constant(safe-area-inset-bottom));
  background: #ffffff;
  border-top: 1rpx solid #e6e8eb;
  /*
   * ★ 底部操作条与自绘底部导航**不要同时出现在一个页面**（二级页一律不挂导航，
   *   只有 pages/home、tasks/index、fault/index、messages/index、board/* 这些
   *   tab 页才挂）。z-index 刻意高于 .bottom-nav 的 100：万一哪天有人给带操作条的
   *   页面又加回了 BottomNav，也只会是「导航被压住」（用户还能用返回），
   *   而不会出现反向的致命问题 —— 导航盖住主按钮、按钮点不动。
   *   实测踩过：任务详情页曾同时有两者，「开始巡检」被导航整块拦截，
   *   点了完全没反应，而页面看起来一切正常。
   */
  z-index: 120;
}

.footer-bar .btn {
  flex: 1;
  margin: 0;
}

/* 有底部操作条的页面：给内容留出对应高度，否则最后一项被盖住 */
.page-with-footer {
  padding-bottom: calc(180rpx + env(safe-area-inset-bottom));
  padding-bottom: calc(180rpx + constant(safe-area-inset-bottom));
}

/* 筛选 chip（状态 tab / 消息类型） */
.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16rpx;
  margin-bottom: 20rpx;
}

.chip {
  padding: 10rpx 26rpx;
  border-radius: 32rpx;
  background: #ffffff;
  color: #4b5563;
  font-size: 25rpx;
  border: 1rpx solid #e6e8eb;
}

.chip-active {
  background: #1677ff;
  color: #ffffff;
  border-color: #1677ff;
  font-weight: 600;
}

/* 统计卡（工作台 / 看板） */
.stat-grid {
  display: flex;
  gap: 16rpx;
  margin-bottom: 20rpx;
}

.stat-card {
  flex: 1;
  background: #ffffff;
  border-radius: 16rpx;
  padding: 22rpx 16rpx;
  text-align: center;
  box-shadow: 0 2rpx 12rpx rgba(0, 0, 0, 0.04);
}

.stat-value {
  font-size: 40rpx;
  font-weight: 700;
  line-height: 1.2;
}

.stat-label {
  font-size: 22rpx;
  color: #8a9099;
  margin-top: 8rpx;
}

.stat-primary {
  color: #1677ff;
}

.stat-warn {
  color: #d97706;
}

.stat-danger {
  color: #d03050;
}

.stat-done {
  color: #18a058;
}

/* 表单 */
.form-item {
  padding: 18rpx 0;
  border-bottom: 1rpx solid #f0f1f3;
}

.form-item:last-child {
  border-bottom: none;
}

.form-label {
  font-size: 26rpx;
  color: #4b5563;
  margin-bottom: 12rpx;
  display: block;
}

.form-label-required::before {
  content: '*';
  color: #d03050;
  margin-right: 6rpx;
}

.form-input {
  background: #f7f8fa;
  border-radius: 12rpx;
  padding: 18rpx 20rpx;
  font-size: 28rpx;
  min-height: 40rpx;
}

.form-textarea {
  background: #f7f8fa;
  border-radius: 12rpx;
  padding: 18rpx 20rpx;
  font-size: 28rpx;
  width: 100%;
  box-sizing: border-box;
  min-height: 180rpx;
}

.form-picker {
  background: #f7f8fa;
  border-radius: 12rpx;
  padding: 18rpx 20rpx;
  font-size: 28rpx;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.picker-arrow {
  color: #8a9099;
}

/* 图片九宫格 */
.image-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 14rpx;
  margin-top: 8rpx;
}

.grid-img {
  width: 180rpx;
  height: 180rpx;
  border-radius: 12rpx;
  background: #f0f1f3;
}

/* 上传占位（虚线框 + 加号） */
.upload-add {
  width: 180rpx;
  height: 180rpx;
  border-radius: 12rpx;
  border: 2rpx dashed #c9ced6;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #8a9099;
  font-size: 22rpx;
}

.upload-plus {
  font-size: 56rpx;
  line-height: 1;
  color: #c9ced6;
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
  font-size: 26rpx;
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

/* 提示条：蓝（说明）/ 橙（要动手）/ 红（告警）/ 绿（完成） */
.hint-bar {
  background: #eef3fb;
  border-left: 8rpx solid #1677ff;
  color: #3d5a80;
  border-radius: 12rpx;
  padding: 16rpx 24rpx;
  margin-bottom: 20rpx;
  font-size: 24rpx;
  line-height: 1.7;
}

.warn-bar {
  background: #fff4e6;
  border-left: 8rpx solid #d97706;
  color: #b45309;
  border-radius: 12rpx;
  padding: 16rpx 24rpx;
  margin-bottom: 20rpx;
  font-size: 25rpx;
  line-height: 1.6;
}

.danger-bar {
  background: #fdecec;
  border-left: 8rpx solid #d03050;
  color: #a52240;
  border-radius: 12rpx;
  padding: 16rpx 24rpx;
  margin-bottom: 20rpx;
  font-size: 25rpx;
  line-height: 1.6;
}

.success-bar {
  background: #e8f7ee;
  border-left: 8rpx solid #18a058;
  color: #14724a;
  border-radius: 12rpx;
  padding: 16rpx 24rpx;
  margin-bottom: 20rpx;
  font-size: 25rpx;
  line-height: 1.6;
}

/* 进度条 */
.progress-bar {
  height: 12rpx;
  background: #eef0f3;
  border-radius: 6rpx;
  overflow: hidden;
}

.progress-inner {
  height: 100%;
  background: #1677ff;
}

/* 分布条形（看板：工单类型 / 等级分布） */
.dist-row {
  display: flex;
  align-items: center;
  margin-bottom: 14rpx;
  font-size: 24rpx;
}

.dist-name {
  width: 150rpx;
  color: #4b5563;
  flex-shrink: 0;
}

.dist-bar-wrap {
  flex: 1;
  height: 20rpx;
  background: #f0f1f3;
  border-radius: 10rpx;
  overflow: hidden;
  margin: 0 16rpx;
}

.dist-bar {
  height: 100%;
  background: #1677ff;
  border-radius: 10rpx;
}

.dist-value {
  width: 70rpx;
  text-align: right;
  color: #8a9099;
  flex-shrink: 0;
}
</style>
