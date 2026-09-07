import { execFileSync } from 'node:child_process'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

import { APP_VERSION_FALLBACK, normalizeAppVersion } from './src/utils/appVersion.mjs'

const backendPort = Number(process.env.POLY_AGENT_BACKEND_PORT || '5201')
const frontendPort = Number(process.env.POLY_AGENT_FRONTEND_PORT || '5200')
const devApiProxyTarget =
  process.env.VITE_DEV_API_PROXY_TARGET || `http://127.0.0.1:${backendPort}`

/**
 * 读取构建时应用版本，优先使用环境变量，其次读取 Git 最近标签。
 *
 * Returns:
 *   去除 v 前缀的语义化版本号；两者都不可用时返回兜底版本。
 */
function resolveAppVersion() {
  const configuredVersion = process.env.POLY_AGENT_RELEASE_VERSION || process.env.VITE_APP_VERSION
  if (configuredVersion) return normalizeAppVersion(configuredVersion)

  try {
    const gitTag = execFileSync('git', ['describe', '--tags', '--abbrev=0'], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim()
    return normalizeAppVersion(gitTag)
  } catch {
    return APP_VERSION_FALLBACK
  }
}

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(resolveAppVersion()),
  },
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
