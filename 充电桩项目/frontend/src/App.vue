<template>
  <a-config-provider :locale="zhCN" :theme="theme">
    <router-view />
  </a-config-provider>
</template>

<script setup>
import zhCN from 'ant-design-vue/es/locale/zh_CN'

const theme = {
  token: {
    colorPrimary: '#2f6fb5',
    borderRadius: 6,
    fontFamily:
      "'Microsoft YaHei', 'PingFang SC', -apple-system, BlinkMacSystemFont, sans-serif",
  },
}
</script>
