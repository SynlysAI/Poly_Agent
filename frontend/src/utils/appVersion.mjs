export const APP_VERSION_FALLBACK = '1.0.0'
export const APP_RELEASE_REPOSITORY_URL = 'https://github.com/SynlysAI/Poly_Agent/releases'

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
