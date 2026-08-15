export const AUTH_EXPIRED_EVENT_NAME = 'poly-agent-auth-expired'

/**
 * 判断 HTTP 状态是否表示登录失效。
 *
 * Args:
 *   status: HTTP 响应状态码。
 *
 * Returns:
 *   是否为 401 未认证响应。
 */
export function isUnauthorizedStatus(status) {
  return Number(status) === 401
}

/**
 * 清理会话并向应用派发统一的认证过期事件。
 *
 * Args:
 *   clearAuthSession: 清理当前登录态的回调。
 */
export function emitAuthExpired(clearAuthSession) {
  if (typeof clearAuthSession === 'function') clearAuthSession()
  if (typeof window === 'undefined' || typeof window.dispatchEvent !== 'function') return

  const event = typeof CustomEvent === 'function'
    ? new CustomEvent(AUTH_EXPIRED_EVENT_NAME)
    : { type: AUTH_EXPIRED_EVENT_NAME }
  window.dispatchEvent(event)
}

/**
 * 处理 fetch 响应中的未认证状态。
 *
 * Args:
 *   response: fetch 返回的 Response 对象。
 *   clearAuthSession: 清理当前登录态的回调。
 */
export function handleUnauthorizedResponse(response, clearAuthSession) {
  if (isUnauthorizedStatus(response?.status)) emitAuthExpired(clearAuthSession)
}
