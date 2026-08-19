/**
 * 构建可携带登录降级 token 的原生下载 URL。
 *
 * Args:
 *   options.baseUrl: API 基础路径。
 *   options.path: API 路径；若已包含基础路径则直接规范化。
 *   options.authorizationHeader: Authorization 请求头。
 *   options.urlSearchParamsCtor: 可注入的 URLSearchParams 构造器，便于测试。
 *
 * Returns:
 *   可赋给 anchor.href 的同源下载 URL。
 */
export function buildAuthenticatedDownloadUrl({
  baseUrl = '',
  path = '',
  authorizationHeader = '',
  urlSearchParamsCtor = globalThis.URLSearchParams,
}) {
  const normalizedBase = String(baseUrl || '').replace(/\/+$/, '')
  const normalizedPath = String(path || '')
  const pathAlreadyIncludesBase = normalizedBase && normalizedPath.startsWith(`${normalizedBase}/`)
  const pathname = pathAlreadyIncludesBase
    ? normalizedPath
    : `${normalizedBase}/${normalizedPath.replace(/^\/+/, '')}`.replace(/\/+$/, '')
  const token = String(authorizationHeader || '').replace(/^\s*Bearer\s+/i, '').trim()
  const params = new urlSearchParamsCtor()
  if (token) params.set('token', token)
  const query = params.toString()
  return query ? `${pathname}?${query}` : pathname
}

/**
 * 触发浏览器原生下载，不在 JavaScript 中缓存响应内容。
 *
 * Args:
 *   options.url: 下载 URL。
 *   options.filename: 下载文件名。
 *   options.documentRef: 可注入的 document 对象，便于测试。
 *
 * Returns:
 *   传入的下载 URL。
 */
export function openNativeDownload({
  url,
  filename = 'download.dat',
  documentRef = globalThis.document,
}) {
  const link = documentRef.createElement('a')
  link.href = url
  link.download = filename || 'download.dat'
  link.rel = 'noopener'
  documentRef.body.appendChild(link)
  try {
    link.click()
  } finally {
    documentRef.body.removeChild(link)
  }
  return url
}
