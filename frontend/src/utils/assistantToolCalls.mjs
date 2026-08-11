/**
 * Assistant 算法工具调用状态展示与 SSE 事件归并的纯函数。
 * 不依赖 Vue / Element Plus，便于 Node 单元测试。
 */

export function toolPhaseLabel(phase) {
  return {
    requested: '已请求',
    awaiting_input: '等待补充参数',
    awaiting_confirmation: '等待确认',
    running: '运行中',
    completed: '已完成',
    failed: '失败',
    canceled: '已取消',
  }[phase] || phase || ''
}

export function toolPhaseTagType(phase) {
  if (phase === 'completed') return 'success'
  if (phase === 'running') return 'warning'
  if (phase === 'failed') return 'danger'
  if (phase === 'canceled') return 'info'
  return 'primary'
}

export function canEditToolCall(call) {
  return ['awaiting_input', 'awaiting_confirmation'].includes(call?.phase)
}

export function normalizeToolCall(call) {
  return {
    ...(call || {}),
    arguments_text: JSON.stringify((call?.arguments) || {}, null, 2),
  }
}

export function parseToolArguments(text) {
  try {
    const parsed = JSON.parse(text || '{}')
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { ok: false, error: '参数必须是 JSON 对象' }
    }
    return { ok: true, arguments: parsed }
  } catch {
    return { ok: false, error: '参数 JSON 格式不正确' }
  }
}

/**
 * 把 SSE 的 tool_call / tool_input_required 事件归并到消息的 tool_calls 列表。
 */
export function applyToolCallEvent(message, event) {
  if (!message || !event?.call_id) return message
  const calls = Array.isArray(message.tool_calls) ? [...message.tool_calls] : []
  const existingIndex = calls.findIndex((call) => call.call_id === event.call_id)
  const record = normalizeToolCall({
    ...(existingIndex >= 0 ? calls[existingIndex] : {}),
    ...event,
  })
  if (existingIndex >= 0) calls.splice(existingIndex, 1, record)
  else calls.push(record)
  message.tool_calls = calls
  return message
}

export function replaceToolCall(message, updated) {
  if (!message || !updated?.call_id) return message
  message.tool_calls = (message.tool_calls || []).map((call) =>
    call.call_id === updated.call_id ? normalizeToolCall(updated) : call,
  )
  return message
}
