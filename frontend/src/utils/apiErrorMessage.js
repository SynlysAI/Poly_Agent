export function getApiErrorMessage(error) {
  if (!error) return '未知错误'
  if (error.isApiError) {
    if (error.kind === 'network') return '网络连接失败，请检查网络'
    if (error.kind === 'timeout') return '请求超时'
    if (error.kind === 'canceled') return '请求已取消'
    const statusMsgMap = { 400: '参数有误', 401: '登录已过期', 403: '无权限', 404: '资源未找到', 409: '状态冲突', 422: '参数校验失败', 500: '服务器内部错误', 501: '功能暂不支持', 502: '上游服务异常', 504: '上游服务超时' }
    if (error.status && statusMsgMap[error.status]) {
      const structuredDetail = error.detail && typeof error.detail === 'object'
        ? (error.detail.message || error.detail.code || JSON.stringify(error.detail))
        : error.detail
      let message
      if (Array.isArray(error.errors) && error.errors.length) {
        message = error.errors.map(e => `[${(e.loc || []).join('.')}] ${e.msg}`).join('；')
      } else {
        message = structuredDetail || (error.message && error.message !== '[object Object]' ? error.message : '')
      }
      return `${statusMsgMap[error.status]}：${message}`
    }
    return error.message || '服务异常'
  }
  return error.message || '未知错误'
}
