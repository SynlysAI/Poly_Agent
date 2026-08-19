/**
 * Assistant Execution Trace 状态归并与展示模型纯函数。
 * 不依赖 Vue / Element Plus，便于 Node 单元测试与断线重放验证。
 */

const MAX_SUMMARY_CHARACTERS = 512
const MAX_DETAIL_CHARACTERS = 4096

export const TRACE_TYPE_FILTERS = [
  { value: 'all', label: '全部' },
  { value: 'command', label: '命令' },
  { value: 'control', label: '控制' },
  { value: 'model', label: '模型' },
  { value: 'tool', label: '工具' },
  { value: 'export', label: '导出' },
  { value: 'feedback', label: '反馈' },
]

/**
 * 截断面向用户的主界面文本。
 *
 * @param {string} text 原始文本。
 * @param {number} limit 最大长度。
 * @returns {string} 截断后的文本。
 */
function boundedText(text, limit) {
  const value = String(text || '').replace(/\s+/g, ' ').trim()
  return value.length > limit ? `${value.slice(0, limit)}…` : value
}

/**
 * 初始化 Trace 快照状态。
 *
 * @param {object} snapshot 后端 AssistantTraceData 快照。
 * @returns {object} 可持续合并 SSE 事件的 Trace 状态。
 */
export function createTraceState(snapshot) {
  const steps = (snapshot?.steps || []).map(normalizeTraceStep)
  return {
    traceId: snapshot?.trace_id || '',
    rootRunId: snapshot?.root_run_id || '',
    status: snapshot?.status || 'planning',
    cursor: snapshot?.cursor || '',
    streaming: !['completed', 'failed', 'canceled'].includes(snapshot?.status),
    steps: sortTraceSteps(steps),
    summary: { ...(snapshot?.summary || {}) },
    replayWarnings: [...(snapshot?.replay_warnings || [])],
  }
}

/**
 * 初始化会话级 Trace 状态。
 *
 * @param {object} snapshot 后端 AssistantChatTraceData 快照。
 * @returns {object} 可增量合并的会话 Trace 状态。
 */
export function createChatTraceState(snapshot) {
  const state = createTraceState({
    ...snapshot,
    trace_id: snapshot?.chat_id || '',
    cursor: String(snapshot?.next_after_seq || 0),
  })
  return {
    ...state,
    chatId: snapshot?.chat_id || '',
    nextAfterSeq: Number(snapshot?.next_after_seq || 0),
    totalEvents: Number(snapshot?.total_events || 0),
    streaming: false,
  }
}

/**
 * 合并 chat scope Trace 增量快照。
 *
 * @param {object} current 当前会话 Trace 状态。
 * @param {object} snapshot 增量 AssistantChatTraceData 快照。
 * @returns {object} 合并后的会话 Trace 状态。
 */
export function mergeChatTraceState(current, snapshot) {
  const incoming = createChatTraceState(snapshot)
  const stepsById = new Map((current?.steps || []).map((step) => [step.step_id, step]))
  for (const step of incoming.steps) {
    stepsById.set(step.step_id, stepsById.has(step.step_id)
      ? mergeTraceStep(stepsById.get(step.step_id), step)
      : step)
  }
  return {
    ...(current || incoming),
    chatId: incoming.chatId,
    status: incoming.status,
    steps: sortTraceSteps([...stepsById.values()]),
    summary: { ...(current?.summary || {}), ...incoming.summary },
    replayWarnings: [...new Set([...(current?.replayWarnings || []), ...incoming.replayWarnings])],
    nextAfterSeq: Math.max(Number(current?.nextAfterSeq || 0), incoming.nextAfterSeq),
    totalEvents: Math.max(Number(current?.totalEvents || 0), incoming.totalEvents),
    streaming: false,
  }
}

/**
 * 规范化单条 Trace step，保证主界面文本和详情不会无限增长。
 *
 * @param {object} step 后端 Trace step。
 * @returns {object} 前端安全 step。
 */
export function normalizeTraceStep(step) {
  const details = { ...(step?.details || {}) }
  const refs = new Map()
  for (const ref of details.source_event_refs || []) {
    if (ref?.event_id) refs.set(ref.event_id, { ...ref })
  }
  details.source_event_refs = [...refs.values()]
  return {
    ...step,
    timestamp: step?.timestamp || '',
    type: step?.type || 'think',
    title: step?.title || '执行步骤',
    summary: boundedText(step?.summary, MAX_SUMMARY_CHARACTERS),
    status: step?.status || 'running',
    duration_ms: Number(step?.duration_ms || 0),
    details,
  }
}

/**
 * 按用户可见类型过滤 Trace step。
 *
 * @param {Array<object>} steps Trace step 列表。
 * @param {string} filter TRACE_TYPE_FILTERS 中的类型值。
 * @returns {Array<object>} 过滤后的 step 列表。
 */
export function filterTraceSteps(steps, filter = 'all') {
  const values = Array.isArray(steps) ? steps : []
  if (filter === 'all') return [...values]
  if (filter === 'command') return values.filter((step) => step?.type === 'command')
  if (filter === 'control') {
    return values.filter((step) => step?.type === 'control')
  }
  if (filter === 'model') {
    return values.filter((step) => step?.tool_type === 'llm' || ['think', 'context'].includes(step?.type))
  }
  if (filter === 'tool') {
    return values.filter((step) => ['tool_call', 'tool_result', 'read', 'write', 'edit', 'error'].includes(step?.type)
      && step?.tool_type !== 'llm')
  }
  if (filter === 'export') return values.filter((step) => step?.type === 'export')
  if (filter === 'feedback') return values.filter((step) => step?.type === 'feedback')
  return []
}

/**
 * 合并同一条 Trace step 的状态更新。
 *
 * @param {object} current 已有 step。
 * @param {object} incoming 新 step。
 * @returns {object} 合并后的 step。
 */
function mergeTraceStep(current, incoming) {
  const details = {
    ...current.details,
    ...incoming.details,
    source_event_refs: [
      ...current.details.source_event_refs,
      ...incoming.details.source_event_refs,
    ].filter((ref, index, list) => list.findIndex((item) => item.event_id === ref.event_id) === index),
  }
  return normalizeTraceStep({ ...current, ...incoming, details })
}

/**
 * 应用 Trace SSE 事件。
 *
 * @param {object} state 当前 Trace 状态。
 * @param {object} event SSE payload。
 * @returns {object} 新的 Trace 状态。
 */
export function applyTraceEvent(state, event) {
  const current = state || createTraceState(null)
  if (!event?.type) return current
  if (event.type === 'trace.step' && event.step?.step_id) {
    const incoming = normalizeTraceStep(event.step)
    const exists = current.steps.some((step) => step.step_id === incoming.step_id)
    const steps = exists
      ? current.steps.map((step) => (step.step_id === incoming.step_id ? mergeTraceStep(step, incoming) : step))
      : [...current.steps, incoming]
    return { ...current, steps: sortTraceSteps(steps) }
  }
  if (event.type === 'trace.summary') {
    return {
      ...current,
      status: event.status || current.status,
      summary: { ...current.summary, ...(event.summary || {}) },
    }
  }
  if (event.type === 'trace.end') {
    return { ...current, status: event.status || current.status, streaming: false }
  }
  if (event.type === 'trace.heartbeat' && event.cursor) {
    return { ...current, cursor: event.cursor }
  }
  return current
}

/**
 * 按 timestamp 和 step_id 稳定排序。
 *
 * @param {Array<object>} steps Trace steps。
 * @returns {Array<object>} 排序后的 steps。
 */
function sortTraceSteps(steps) {
  return [...steps].sort((left, right) => {
    const leftTime = Date.parse(left.timestamp || '') || 0
    const rightTime = Date.parse(right.timestamp || '') || 0
    return leftTime - rightTime || String(left.step_id).localeCompare(String(right.step_id))
  })
}

/**
 * 生成分组展示模型；分组只影响视觉层级，不改变步骤排序。
 *
 * @param {object} state Trace 状态。
 * @returns {Array<{label:string, steps:Array<object>}>} 展示分组。
 */
export function traceDisplayGroups(state) {
  const steps = state?.steps || []
  return [
    {
      label: '命令与控制',
      steps: steps.filter((step) => ['command', 'control'].includes(step.type)),
    },
    {
      label: '请求与上下文',
      steps: steps.filter((step) => ['think', 'context'].includes(step.type) || step.tool_type === 'retrieval'),
    },
    {
      label: '模型调用',
      steps: steps.filter((step) => step.tool_type === 'llm'),
    },
    {
      label: '工具审批与执行',
      steps: steps.filter((step) => ['tool_call', 'approval', 'error'].includes(step.type) && step.tool_type !== 'llm' && step.tool_type !== 'retrieval'),
    },
    {
      label: '结果与续答',
      steps: steps.filter((step) => ['tool_result', 'write', 'read', 'edit', 'final'].includes(step.type)),
    },
    {
      label: '导出与反馈',
      steps: steps.filter((step) => ['export', 'feedback'].includes(step.type)),
    },
  ].filter((group) => group.steps.length > 0)
}

/**
 * 构造执行摘要展示行。
 *
 * @param {object} state Trace 状态。
 * @returns {Array<[string, string]>} 摘要键值行。
 */
export function traceSummaryRows(state) {
  const summary = state?.summary || {}
  return [
    ['总步骤', String(summary.total_steps ?? state?.steps?.length ?? 0)],
    ['命令', String(summary.commands ?? 0)],
    ['控制变更', String(summary.control_changes ?? 0)],
    ['工具调用', String(summary.tool_calls ?? 0)],
    ['模型请求', String(summary.llm_calls ?? 0)],
    ['审批', String(summary.approvals ?? 0)],
    ['导出', String(summary.exports ?? 0)],
    ['反馈', String(summary.feedback ?? 0)],
    ['异常', String(summary.errors ?? 0)],
    ['总耗时', summary.duration_known ? formatDurationMs(summary.duration_ms) : '未记录'],
  ]
}

/**
 * 格式化 step 耗时；未知耗时不伪造为 0。
 *
 * @param {object} step Trace step。
 * @returns {string} 用户可读耗时。
 */
export function formatTraceDuration(step) {
  if (!step?.details?.duration_known) return '未记录'
  return formatDurationMs(Number(step.duration_ms || 0))
}

/**
 * 格式化毫秒耗时。
 *
 * @param {number} milliseconds 耗时毫秒数。
 * @returns {string} 用户可读耗时。
 */
function formatDurationMs(milliseconds) {
  const value = Number(milliseconds || 0)
  if (value >= 1000) return `${(value / 1000).toFixed(1)}s`
  return `${Math.round(value)}ms`
}

/**
 * 生成限长的详情 JSON 文本。
 *
 * @param {object} step Trace step。
 * @returns {string} 可放入详情折叠区的文本。
 */
export function traceDetailText(step) {
  const raw = JSON.stringify(
    {
      title: step?.title,
      summary: step?.summary,
      status: step?.status,
      duration_ms: step?.duration_ms,
      details: step?.details,
    },
    null,
    2,
  ) || ''
  if (raw.length <= MAX_DETAIL_CHARACTERS) return raw
  return `${raw.slice(0, MAX_DETAIL_CHARACTERS - 20)}\n…内容已截断`
}
