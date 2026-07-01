import { reactive } from 'vue'

import {
  clearStoredAuthSession,
  getStoredAuthSession,
  isAuthSessionValid,
  setStoredAuthSession,
} from './authStorage'

const initialSession = getStoredAuthSession()
const hasValidInitialSession = isAuthSessionValid(initialSession)

export const authState = reactive({
  initialized: false,
  authEnabled: false,
  authenticated: hasValidInitialSession,
  userId: hasValidInitialSession ? initialSession.userId || '' : '',
  username: hasValidInitialSession ? initialSession.username || '' : '',
  role: hasValidInitialSession ? initialSession.role || '' : '',
  status: hasValidInitialSession ? initialSession.status || '' : '',
  tokenType: hasValidInitialSession ? initialSession.tokenType || 'Bearer' : 'Bearer',
  accessToken: hasValidInitialSession ? initialSession.accessToken || '' : '',
  expiresAt: hasValidInitialSession ? initialSession.expiresAt || 0 : 0,
})

/**
 * 更新服务端鉴权开关状态。
 *
 * Args:
 *   enabled: 后端是否启用登录校验。
 */
export function setAuthEnabled(enabled) {
  authState.authEnabled = Boolean(enabled)
  authState.initialized = true
  if (!authState.authEnabled) {
    clearAuthSession()
  }
}

/**
 * 写入新的登录会话。
 *
 * Args:
 *   session: 登录会话信息。
 */
export function setAuthSession(session) {
  authState.authenticated = true
  authState.userId = session.userId || ''
  authState.username = session.username || ''
  authState.role = session.role || ''
  authState.status = session.status || ''
  authState.tokenType = session.tokenType || 'Bearer'
  authState.accessToken = session.accessToken || ''
  authState.expiresAt = session.expiresAt || 0
  setStoredAuthSession({
    userId: authState.userId,
    username: authState.username,
    role: authState.role,
    status: authState.status,
    tokenType: authState.tokenType,
    accessToken: authState.accessToken,
    expiresAt: authState.expiresAt,
  })
}

/**
 * 清空当前登录会话。
 */
export function clearAuthSession() {
  authState.authenticated = false
  authState.userId = ''
  authState.username = ''
  authState.role = ''
  authState.status = ''
  authState.tokenType = 'Bearer'
  authState.accessToken = ''
  authState.expiresAt = 0
  clearStoredAuthSession()
}

/**
 * 接收 AI4MS 门户通过 URL hash 传递的统一登录 token。
 *
 * AI4MS 跳转子平台时会将 token 写入 URL hash：
 *   https://polyagent.example.com/#token=xxx
 * 本函数在应用初始化时被调用，提取 token 并写入会话存储，
 * 同时清理 URL 中的 token 避免泄露。
 *
 * Returns:
 *   是否成功接收了门户 token。
 */
export function acceptPortalToken() {
  if (typeof window === 'undefined') {
    return false
  }
  const hash = window.location.hash || ''
  const params = new URLSearchParams(hash.replace(/^#/, ''))
  const token = params.get('token')
  if (!token) {
    return false
  }

  const pendingExpiresAt = Math.floor(Date.now() / 1000) + 12 * 3600
  authState.authenticated = true
  authState.userId = '__portal__'
  authState.username = '__portal__'
  authState.role = 'user'
  authState.status = 'active'
  authState.tokenType = 'Bearer'
  authState.accessToken = token
  authState.expiresAt = pendingExpiresAt

  setStoredAuthSession({
    userId: '__portal__',
    username: '__portal__',
    role: 'user',
    status: 'active',
    tokenType: 'Bearer',
    accessToken: token,
    expiresAt: pendingExpiresAt,
  })

  params.delete('token')
  const remaining = params.toString()
  const newUrl =
    window.location.pathname +
    window.location.search +
    (remaining ? `#${remaining}` : '')
  window.history.replaceState(null, '', newUrl)
  return true
}

/**
 * 获取可用于请求头的 Authorization 值。
 *
 * Returns:
 *   Authorization 请求头值；无可用会话时返回空字符串。
 */
export function getAuthorizationHeader() {
  if (!authState.authenticated) {
    return ''
  }
  if (!isAuthSessionValid(authState)) {
    clearAuthSession()
    return ''
  }
  return `${authState.tokenType} ${authState.accessToken}`
}
