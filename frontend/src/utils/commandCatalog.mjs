/** Assistant 命令目录缓存与加载状态模型。 */

function emptyState() {
  return {
    loading: false,
    error: '',
    items: [],
    sessionState: null,
    catalogVersion: '',
  }
}

/**
 * 创建命令目录缓存。
 *
 * Args:
 *   fetchCatalog: 调用 GET /assistant/commands 的异步函数。
 *
 * Returns:
 *   带 load、invalidate 与响应式 state 的目录缓存对象。
 */
export function createCommandCatalogCache(fetchCatalog) {
  let chatId = ''
  let cachedResponse = null
  let pendingRequest = null
  let requestSequence = 0
  const state = emptyState()

  /**
   * 归一化后端命令目录响应。
   *
   * Args:
   *   data: API 返回的原始目录数据。
   *
   * Returns:
   *   组件消费的目录字段。
   */
  const normalize = (data) => ({
    items: Array.isArray(data?.items) ? data.items : [],
    sessionState: data?.session_state || null,
    catalogVersion: data?.catalog_version || '',
    total: Number(data?.total || 0),
  })

  async function load(nextChatId, options = {}) {
    if (!nextChatId) throw new Error('缺少会话 ID')
    const versionChanged = options.expectedVersion
      && cachedResponse
      && options.expectedVersion !== cachedResponse.catalogVersion
    const cacheUsable = cachedResponse
      && chatId === nextChatId
      && !options.force
      && !versionChanged
    if (cacheUsable) return cachedResponse
    if (pendingRequest && pendingRequest.chatId === nextChatId && !options.force) return pendingRequest.request

    chatId = nextChatId
    state.loading = true
    state.error = ''
    const requestId = ++requestSequence
    const request = (async () => {
      try {
        const data = normalize(await fetchCatalog(nextChatId))
        if (requestId !== requestSequence) {
          return pendingRequest?.request ?? cachedResponse ?? data
        }
        cachedResponse = data
        state.items = data.items
        state.sessionState = data.sessionState
        state.catalogVersion = data.catalogVersion
        return data
      } catch (error) {
        if (requestId !== requestSequence) throw error
        state.error = error?.message || String(error)
        throw error
      } finally {
        if (requestId === requestSequence) state.loading = false
      }
    })()
    pendingRequest = { chatId: nextChatId, request }
    try {
      return await request
    } finally {
      if (pendingRequest?.request === request) pendingRequest = null
    }
  }

  function invalidate() {
    cachedResponse = null
    pendingRequest = null
    Object.assign(state, emptyState())
  }

  return { load, invalidate, state }
}
