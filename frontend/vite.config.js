import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backendPort = Number(process.env.POLY_AGENT_BACKEND_PORT || '5101')
const frontendPort = Number(process.env.POLY_AGENT_FRONTEND_PORT || '5100')
const devApiProxyTarget =
  process.env.VITE_DEV_API_PROXY_TARGET || `http://127.0.0.1:${backendPort}`

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
    port: frontendPort,
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
