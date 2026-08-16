/**
 * LUI 模型路由、上下文 manifest、工具提案与执行时间线的纯展示函数。
 * 不依赖 Vue / Element Plus，便于 Node 单元测试。
 */

const ROUTE_REASON_LABELS = {
  user_selected: '用户选择',
  purpose_default: '模式默认',
  tool_capability_override: '工具能力改选',
  fallback: '兜底路由',
  recommended: '推荐模型',
}

const CAPABILITY_SOURCE_LABELS = {
  configured: '配置确认',
  probed: '运行时探测',
  inferred: '能力推断',
}

const TOOL_PROTOCOL_LABELS = {
  openai_chat_tools: 'OpenAI Chat Tools',
  openai_responses: 'OpenAI Responses',
  anthropic_tools: 'Anthropic Tools',
  native: '原生工具协议',
}

const TOOL_EVENT_LABELS = {
  'tool.proposed': '模型提议',
  'tool.proposal.updated': '原始提案已更新',
  'tool.proposal.backfilled': '原始提案已回填',
  'tool.arguments.invalid': '参数校验失败',
  'tool.awaiting_input': '等待补充参数',
  'tool.awaiting_confirmation': '等待确认',
  'tool.queued': '排队中',
  'tool.started': '运行中',
  'tool.result': '已完成',
  'tool.failed': '执行失败',
  'tool.canceled': '已取消',
}

const TOOL_PHASE_LABELS = {
  requested: '模型提议',
  awaiting_input: '等待补充参数',
  awaiting_confirmation: '等待确认',
  queued: '排队中',
  running: '运行中',
  completed: '已完成',
  failed: '执行失败',
  canceled: '已取消',
}

export function normalizeAssistantRoute(route) {
  const source = route || {}
  return {
    provider_id: source.provider_id || '',
    provider_type: source.provider_type || '',
    model_id: source.model_id || '',
    requested_provider_id: source.requested_provider_id || '',
    requested_model_id: source.requested_model_id || '',
    route_reason: source.route_reason || '',
    fallback_reason: source.fallback_reason || '',
    capabilities: Array.isArray(source.capabilities) ? source.capabilities : [],
    capability_source: source.capability_source || '',
    tool_protocol: source.tool_protocol || '',
    supports_parallel_tool_calls: Boolean(source.supports_parallel_tool_calls),
    context_window: source.context_window || null,
    max_output_tokens: source.max_output_tokens || null,
    reasoning_model_available: Boolean(source.reasoning_model_available),
  }
}

export function routeReasonLabel(reason) {
  return ROUTE_REASON_LABELS[reason] || reason || ''
}

export function capabilitySourceLabel(source) {
  return CAPABILITY_SOURCE_LABELS[source] || source || ''
}

export function toolProtocolLabel(protocol) {
  return TOOL_PROTOCOL_LABELS[protocol] || protocol || ''
}

export function formatContextWindow(value) {
  const window = Number(value)
  if (!Number.isFinite(window) || window <= 0) return ''
  if (window >= 1024) {
    const scaled = window / 1024
    return `${Number.isInteger(scaled) ? scaled : scaled.toFixed(1)}K`
  }
  return String(window)
}

export function formatTokenCount(value) {
  const count = Number(value)
  if (!Number.isFinite(count) || count < 0) return ''
  return count >= 1000 ? `${(count / 1000).toFixed(1)}k` : String(count)
}

export function formatUsage(usage = {}) {
  const prompt = formatTokenCount(usage?.prompt_tokens)
  const completion = formatTokenCount(usage?.completion_tokens)
  const total = formatTokenCount(usage?.total_tokens)
  if (!prompt && !completion && !total) return ''
  const parts = []
  if (prompt) parts.push(`输入 ${prompt}`)
  if (completion) parts.push(`输出 ${completion}`)
  if (total) parts.push(`总计 ${total}`)
  return parts.join(' · ')
}

export function modelMetaLabel(route) {
  const normalized = normalizeAssistantRoute(route)
  if (!normalized.model_id) return ''
  const provider = normalized.provider_id || normalized.provider_type || ''
  return provider ? `${provider} / ${normalized.model_id}` : normalized.model_id
}

export function routeCapabilityLabels(route) {
  const normalized = normalizeAssistantRoute(route)
  const labels = []
  if (normalized.capabilities.includes('tool_calling')) labels.push('工具调用')
  if (normalized.capabilities.includes('reasoning')) labels.push('推理')
  if (normalized.capabilities.includes('long_context')) labels.push('长上下文')
  if (normalized.capabilities.includes('structured_json')) labels.push('结构化 JSON')
  if (normalized.capabilities.includes('fast')) labels.push('快速')
  return labels
}

export function contextSectionRows(manifest) {
  const sections = manifest?.context?.sections
  if (!Array.isArray(sections)) return []
  return sections.map((section) => ({
    name: section?.name || '',
    source: section?.source || '',
    token_estimate: Number(section?.token_estimate || 0),
    included: section?.included !== false,
    omitted_reason: section?.omitted_reason || '',
    digest: section?.digest || '',
  }))
}

export function contextToolRows(manifest) {
  return Array.isArray(manifest?.tools) ? manifest.tools : []
}

export function contextDigest(manifest) {
  return manifest?.context?.digest || ''
}

export function parseRawToolArguments(raw) {
  if (typeof raw !== 'string' || !raw.trim()) {
    return { ok: false, error: '模型未返回原始参数', arguments: {} }
  }
  try {
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { ok: false, error: '原始参数必须是 JSON 对象', arguments: {} }
    }
    return { ok: true, error: '', arguments: parsed }
  } catch {
    return { ok: false, error: '原始参数 JSON 解析失败', arguments: {} }
  }
}

function valueChanged(left, right) {
  return JSON.stringify(left) !== JSON.stringify(right)
}

/**
 * 对比模型原始提案与用户最终确认/修正后的参数。
 *
 * @param {object} call Assistant tool call。
 * @returns {{ok: boolean, error: string, changes: Array<{key:string, proposed:unknown, confirmed:unknown}>}}
 */
export function toolArgumentDiff(call) {
  const parsed = parseRawToolArguments(call?.raw_arguments)
  if (!parsed.ok) return { ok: false, error: parsed.error, changes: [] }
  const proposed = parsed.arguments
  const confirmed = call?.arguments && typeof call.arguments === 'object' ? call.arguments : {}
  const keys = new Set([...Object.keys(proposed), ...Object.keys(confirmed)])
  const changes = []
  for (const key of keys) {
    if (valueChanged(proposed[key], confirmed[key])) {
      changes.push({ key, proposed: proposed[key], confirmed: confirmed[key] })
    }
  }
  return { ok: true, error: '', changes }
}

function toolTimelineLabel(event) {
  const type = event?.type || ''
  const phase = event?.phase || ''
  return TOOL_EVENT_LABELS[type] || TOOL_EVENT_LABELS[`tool.${phase}`] || TOOL_PHASE_LABELS[phase] || type || phase || '状态更新'
}

function toolTimelineDetail(event) {
  if (event?.error?.message) return event.error.message
  if (event?.message) return event.message
  if (event?.arguments_parse_error) return `参数解析失败：${event.arguments_parse_error}`
  return ''
}

/**
 * 由工具调用 events 生成 UI timeline；旧调用无事件时使用关键时间点兜底。
 *
 * @param {object} call Assistant tool call。
 * @returns {Array<{at:string, label:string, detail:string, type:string}>}
 */
export function toolTimelineRows(call) {
  const events = Array.isArray(call?.events) && call.events.length ? call.events : []
  if (events.length) {
    return events
      .map((event) => ({
        at: event?.at || '',
        label: toolTimelineLabel(event),
        detail: toolTimelineDetail(event),
        type: event?.type || event?.phase || '',
      }))
      .filter((row) => row.label)
  }
  const rows = []
  const append = (at, label, detail = '') => {
    if (at) rows.push({ at, label, detail, type: '' })
  }
  append(call?.created_at, '已创建')
  append(call?.confirmed_at, '用户确认')
  append(call?.started_at, '算法启动')
  append(call?.finished_at, call?.phase === 'failed' ? '执行失败' : '执行完成')
  append(call?.canceled_at, '已取消')
  return rows
}

export function toolCapableModelOptions(models) {
  return (models || []).filter((item) => item?.capabilities?.includes('tool_calling'))
}
