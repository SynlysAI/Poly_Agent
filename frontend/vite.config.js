import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const devApiProxyTarget = process.env.VITE_DEV_API_PROXY_TARGET || 'http://127.0.0.1:8003'

export default defineConfig({
  plugins: [vue()],
  build: {
    rolldownOptions: {
      onLog(level, log) {
        if (log.code === 'INVALID_ANNOTATION') return
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: devApiProxyTarget,
        changeOrigin: true,
      },
      '/static': {
        target: devApiProxyTarget,
        changeOrigin: true,
      },
    },
  },
})
