const AUTH_STORAGE_KEY = 'poly_agent_auth_session'

/**
 * 校验会话对象结构是否完整。
 *
 * Args:
 *   session: 待校验的会话对象。
 *
 * Returns:
 *   会话结构是否合法。
 */
function isAuthSessionShapeValid(session) {
  const expiresAt = Number(session?.expiresAt)
  return Boolean(
    session &&
      typeof session.userId === 'string' &&
      session.userId.trim() &&
      typeof session.username === 'string' &&
      session.username.trim() &&
      ['admin', 'user'].includes(session.role) &&
      ['active', 'disabled'].includes(session.status) &&
      typeof session.tokenType === 'string' &&
      session.tokenType.trim() &&
      typeof session.accessToken === 'string' &&
      session.accessToken.trim() &&
      Number.isFinite(expiresAt) &&
      expiresAt > 0,
  )
}

/**
 * 读取本地会话信息。
 *
 * Returns:
 *   当前已保存的登录会话；不存在时返回 null。
 */
export function getStoredAuthSession() {
  if (typeof window === 'undefined') {
    return null
  }
  const raw = window.sessionStorage.getItem(AUTH_STORAGE_KEY)
  if (!raw) {
    return null
  }
  try {
    const session = JSON.parse(raw)
    if (!isAuthSessionShapeValid(session)) {
      window.sessionStorage.removeItem(AUTH_STORAGE_KEY)
      return null
    }
    session.expiresAt = Number(session.expiresAt)
    return session
  } catch {
    window.sessionStorage.removeItem(AUTH_STORAGE_KEY)
    return null
  }
}

/**
 * 保存登录会话信息。
 *
 * Args:
 *   session: 待保存的会话对象。
 */
export function setStoredAuthSession(session) {
  if (typeof window === 'undefined') {
    return
  }
  window.sessionStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session))
}

/**
 * 清理登录会话信息。
 */
export function clearStoredAuthSession() {
  if (typeof window === 'undefined') {
    return
  }
  window.sessionStorage.removeItem(AUTH_STORAGE_KEY)
}

/**
 * 判断当前会话是否仍在有效期内。
 *
 * Args:
 *   session: 会话对象。
 *
 * Returns:
 *   是否有效。
 */
export function isAuthSessionValid(session) {
  if (!isAuthSessionShapeValid(session)) {
    return false
  }
  return Number(session.expiresAt) * 1000 > Date.now()
}
