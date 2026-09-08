export const APP_VERSION_FALLBACK = '1.0.0'
export const APP_RELEASE_REPOSITORY_URL = 'https://github.com/SynlysAI/Poly_Agent/releases'
export const APP_LATEST_RELEASE_API_URL =
  'https://api.github.com/repos/SynlysAI/Poly_Agent/releases/latest'

const SEMVER_PATTERN = /^v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)$/i

/**
 * 规范化应用版本号，去除 Git 标签的 v 前缀。
 *
 * Args:
 *   value: 构建环境或 Git 命令返回的原始版本字符串。
 *   fallback: 原始值不是语义化版本时使用的兜底版本。
 *
 * Returns:
 *   可直接展示的语义化版本号。
 */
export function normalizeAppVersion(value, fallback = APP_VERSION_FALLBACK) {
  const normalized = String(value || '').trim()
  const match = normalized.match(SEMVER_PATTERN)
  return match ? match[1] : fallback
}

/**
 * 根据应用版本号生成对应的 GitHub Release 链接。
 *
 * Args:
 *   version: 已规范化的语义化版本号。
 *
 * Returns:
 *   指向该版本 Release 页面的绝对 URL。
 */
export function buildAppReleaseUrl(version) {
  return `${APP_RELEASE_REPOSITORY_URL}/tag/v${normalizeAppVersion(version)}`
}

/**
 * 从 GitHub Releases API 动态获取最新发布版本号。
 *
 * Args:
 *   options: 可选配置对象；fetchImpl 为可注入的请求实现（便于测试），
 *     timeoutMs 为请求超时毫秒数。
 *
 * Returns:
 *   成功时返回去除 v 前缀的最新语义化版本号；请求失败、响应异常
 *   或版本号不合法时返回 null，由调用方保留原有展示版本。
 */
export async function fetchLatestAppVersion({
  fetchImpl = globalThis.fetch,
  timeoutMs = 5000,
} = {}) {
  if (typeof fetchImpl !== 'function') return null
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetchImpl(APP_LATEST_RELEASE_API_URL, {
      signal: controller.signal,
      headers: { Accept: 'application/vnd.github+json' },
    })
    if (!response.ok) return null
    const payload = await response.json()
    const tagName = payload?.tag_name
    if (typeof tagName !== 'string') return null
    return normalizeAppVersion(tagName, '') || null
  } catch {
    return null
  } finally {
    clearTimeout(timeoutId)
  }
}
