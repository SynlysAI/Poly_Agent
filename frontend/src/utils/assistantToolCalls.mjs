/**
 * Assistant 算法工具调用状态展示与 SSE 事件归并的纯函数。
 * 不依赖 Vue / Element Plus，便于 Node 单元测试。
 */

export function toolPhaseLabel(phase) {
  return {
    requested: '已请求',
    awaiting_input: '等待补充参数',
    awaiting_confirmation: '等待确认',
    queued: '排队中',
    running: '运行中',
    completed: '已完成',
    failed: '失败',
    canceled: '已取消',
  }[phase] || phase || ''
}

export function toolPhaseTagType(phase) {
  if (phase === 'completed') return 'success'
  if (phase === 'running') return 'warning'
  if (phase === 'queued') return 'warning'
  if (phase === 'failed') return 'danger'
  if (phase === 'canceled') return 'info'
  return 'primary'
}

const EARLY_PHASES = new Set(['requested', 'awaiting_input', 'awaiting_confirmation'])
const TERMINAL_PHASES = new Set(['completed', 'failed', 'canceled'])

/**
 * 判断 incoming 事件中的调用状态是否比本地已有状态“更早”。
 * 运行/结束后的调用不允许被重放的旧事件降级回待确认等早期状态。
 */
export function isStaleToolCallPhase(existingPhase, incomingPhase) {
  if (!existingPhase || !incomingPhase) return false
  if (TERMINAL_PHASES.has(existingPhase)) return existingPhase !== incomingPhase
  if (existingPhase === 'queued' || existingPhase === 'running') return EARLY_PHASES.has(incomingPhase)
  return false
}

export function canEditToolCall(call) {
  return ['awaiting_input', 'awaiting_confirmation'].includes(call?.phase)
}

export function normalizeToolCall(call) {
  return {
    ...(call || {}),
    arguments_text: JSON.stringify((call?.arguments) || {}, null, 2),
    raw_arguments_text: call?.raw_arguments || '',
    events: Array.isArray(call?.events) ? call.events.map((event) => ({ ...event })) : [],
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
 * 构建确认执行请求体：优先提交用户当前编辑的 arguments_text，
 * 避免必须先点“更新参数”保存后才能确认运行。
 */
export function buildToolCallConfirmPayload(call) {
  const inputAssetRefs = call?.input_asset_refs || {}
  const raw = call?.arguments_text
  if (typeof raw === 'string' && raw.trim()) {
    const parsed = parseToolArguments(raw)
    if (!parsed.ok) return { ok: false, error: parsed.error }
    return {
      ok: true,
      payload: { arguments: parsed.arguments, input_asset_refs: inputAssetRefs },
    }
  }
  return {
    ok: true,
    payload: { arguments: call?.arguments || {}, input_asset_refs: inputAssetRefs },
  }
}

function toolCallEventKey(event) {
  return [
    event?.call_id || '',
    event?.seq || 0,
    event?.type || '',
    event?.phase || '',
    event?.at || '',
  ].join(':')
}

/**
 * 合并工具调用的 append-only 事件列表，避免重放重复事件。
 *
 * @param {Array<object>} current 已有事件。
 * @param {Array<object>|object|undefined} incoming 新事件或事件列表。
 * @returns {Array<object>} 按 seq 排序去重后的完整事件列表。
 */
export function mergeToolCallEvents(current, incoming) {
  const list = Array.isArray(current) ? current.map((event) => ({ ...event })) : []
  const nextItems = Array.isArray(incoming) ? incoming : incoming ? [incoming] : []
  const seen = new Set(list.map(toolCallEventKey))
  for (const event of nextItems) {
    if (!event) continue
    const key = toolCallEventKey(event)
    if (!seen.has(key)) {
      seen.add(key)
      list.push({ ...event })
    }
  }
  return list.sort((a, b) => (Number(a?.seq || 0) || 0) - (Number(b?.seq || 0) || 0))
}

/**
 * 把 SSE 的 tool_call / tool_input_required 事件归并到消息的 tool_calls 列表。
 */
export function applyToolCallEvent(message, event) {
  if (!message || !event?.call_id) return message
  const calls = Array.isArray(message.tool_calls) ? [...message.tool_calls] : []
  const existingIndex = calls.findIndex((call) => call.call_id === event.call_id)
  const existing = existingIndex >= 0 ? calls[existingIndex] : null
  const stalePhase = existing ? isStaleToolCallPhase(existing.phase, event.phase) : false
  const record = normalizeToolCall({
    ...(existing || {}),
    ...event,
    ...(stalePhase ? { phase: existing.phase } : {}),
  })
  record.events = mergeToolCallEvents(existing?.events, event)
  if (existingIndex >= 0) calls.splice(existingIndex, 1, record)
  else calls.push(record)
  message.tool_calls = calls
  return message
}

/**
 * 用快照/最终事件中的调用列表合并到现有列表，避免把已确认或已结束的调用重置回待确认。
 */
export function mergeToolCalls(existing, incoming) {
  const merged = (Array.isArray(existing) ? existing : []).map((call) => ({ ...call }))
  for (const call of incoming || []) {
    const index = merged.findIndex((item) => item.call_id === call.call_id)
    const incomingRecord = normalizeToolCall({ ...call })
    if (index < 0) {
      merged.push(incomingRecord)
      continue
    }
    const current = merged[index]
    const stalePhase = isStaleToolCallPhase(current.phase, call.phase)
    const mergedEvents = mergeToolCallEvents(current.events, incomingRecord.events)
    merged[index] = normalizeToolCall({
      ...current,
      ...incomingRecord,
      ...(stalePhase ? { phase: current.phase } : {}),
      events: mergedEvents,
    })
  }
  return merged
}

export function replaceToolCall(message, updated) {
  if (!message || !updated?.call_id) return message
  message.tool_calls = (message.tool_calls || []).map((call) =>
    call.call_id === updated.call_id ? normalizeToolCall(updated) : call,
  )
  return message
}

/**
 * 构建垂类预测运行详情的深链路由。
 */
export function toolCallRunDetailRoute(call) {
  return {
    path: '/vertical-prediction',
    query: {
      tab: 'detail',
      algorithm_id: call?.algorithm_id || '',
      run_id: call?.run_id || '',
    },
  }
}

export function schemaFieldType(description = '') {
  const token = String(description).split(' -', 1)[0].trim().toLowerCase()
  if (/^(number|float)$/.test(token)) return 'number'
  if (/^(integer|int)$/.test(token)) return 'integer'
  if (/^(boolean|bool)$/.test(token)) return 'boolean'
  if (/^(list|array)(\[|$)/.test(token)) return 'array'
  if (/^(dict|map)(\[|$)/.test(token)) return 'object'
  return 'string'
}

export function normalizeSchemaArguments(call) {
  const jsonSchema = call?.input_json_schema
  if (jsonSchema?.properties) {
    const values = { ...(call?.arguments || {}) }
    const required = new Set(jsonSchema.required || [])
    return Object.entries(jsonSchema.properties).map(([key, property]) => ({
      key,
      description: property?.description || '',
      type: property?.type || 'string',
      value: values[key] ?? property?.default ?? '',
      required: (call?.missing_fields || []).includes(key) || required.has(key),
      options: property?.enum || [],
    }))
  }
  const fields = call?.field_schema?.fields || call?.input_schema?.fields || {}
  const values = { ...(call?.arguments || {}) }
  return Object.entries(fields).map(([key, description]) => ({
    key,
    description,
    type: schemaFieldType(description),
    value: values[key] ?? '',
    required: (call?.missing_fields || []).includes(key) || (call?.field_schema?.required || []).includes(key),
    options: call?.field_schema?.field_options?.[key] || call?.input_schema?.field_options?.[key] || [],
  }))
}
