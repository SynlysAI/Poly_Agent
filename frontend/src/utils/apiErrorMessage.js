import { getCurrentLocale } from '../i18n/index.js'

const STATUS_MESSAGE_KEYS = {
  400: 'error.invalidParams',
  401: 'error.unauthorized',
  403: 'error.forbidden',
  404: 'error.notFound',
  409: 'error.conflict',
  422: 'error.validation',
  500: 'error.internal',
  501: 'error.notSupported',
  502: 'error.upstream',
  504: 'error.upstreamTimeout',
}

const ERROR_MESSAGES = {
  'zh-CN': {
    unknown: '未知错误', network: '网络连接失败，请检查网络', timeout: '请求超时', canceled: '请求已取消', service: '服务异常',
    ...Object.fromEntries(Object.entries(STATUS_MESSAGE_KEYS).map(([status, key]) => [key, {
      'error.invalidParams': '参数有误', 'error.unauthorized': '登录已过期', 'error.forbidden': '无权限', 'error.notFound': '资源未找到', 'error.conflict': '状态冲突', 'error.validation': '参数校验失败', 'error.internal': '服务器内部错误', 'error.notSupported': '功能暂不支持', 'error.upstream': '上游服务异常', 'error.upstreamTimeout': '上游服务超时',
    }[key]])),
  },
  'en-US': {
    unknown: 'Unknown error', network: 'Network connection failed. Check your connection.', timeout: 'Request timed out', canceled: 'Request canceled', service: 'Service error',
    'error.invalidParams': 'Invalid parameters', 'error.unauthorized': 'Your session has expired', 'error.forbidden': 'Permission denied', 'error.notFound': 'Resource not found', 'error.conflict': 'State conflict', 'error.validation': 'Validation failed', 'error.internal': 'Internal server error', 'error.notSupported': 'Feature not supported', 'error.upstream': 'Upstream service error', 'error.upstreamTimeout': 'Upstream service timed out',
  },
}

export function getApiErrorMessage(error, preferredLocale = null) {
  const locale = preferredLocale || getCurrentLocale()
  const copy = ERROR_MESSAGES[locale]
  if (!error) return copy.unknown
  if (error.isApiError) {
    if (error.kind === 'network') return copy.network
    if (error.kind === 'timeout') return copy.timeout
    if (error.kind === 'canceled') return copy.canceled
    if (error.status && STATUS_MESSAGE_KEYS[error.status]) {
      const structuredDetail = error.detail && typeof error.detail === 'object'
        ? (error.detail.message || error.detail.code || JSON.stringify(error.detail))
        : error.detail
      let message
      if (Array.isArray(error.errors) && error.errors.length) {
        message = error.errors.map(e => `[${(e.loc || []).join('.')}] ${e.msg}`).join('；')
      } else {
        message = structuredDetail || (error.message && error.message !== '[object Object]' ? error.message : '')
      }
      const separator = locale === 'en-US' ? ': ' : '：'
      return `${copy[STATUS_MESSAGE_KEYS[error.status]]}${separator}${message}`
    }
    return error.message || copy.service
  }
  return error.message || copy.unknown
}
