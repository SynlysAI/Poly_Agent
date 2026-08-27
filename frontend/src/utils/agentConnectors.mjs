/** Agent 连接器视图的纯函数工具。 */

/**
 * 计算连接器卡片状态。
 *
 * @param {object} card 连接器卡片数据。
 * @returns {{kind: string, label: string, tag: string, reason: string}} 状态信息。
 */
export function connectorStatus(card) {
  if (!card) {
    return { kind: 'unavailable', label: '不可用', tag: 'danger', reason: '连接器数据缺失' }
  }
  const readiness = card.readiness || {}
  if (!readiness.available) {
    return {
      kind: 'unavailable',
      label: '不可用',
      tag: 'danger',
      reason: readiness.message || readiness.reason_code || 'provider 未就绪',
    }
  }
  if (!card.policy?.enabled) {
    return { kind: 'disabled', label: '已关闭', tag: 'warning', reason: '策略未启用' }
  }
  return { kind: 'ready', label: '可调用', tag: 'success', reason: '' }
}

/**
 * 普通用户是否可以看到连接器卡片；管理员始终可见。
 *
 * @param {object} card 连接器卡片数据。
 * @param {string} role 当前用户角色。
 * @param {boolean} isAdmin 是否管理员。
 * @returns {boolean} 是否可见。
 */
export function connectorVisibleToUser(card, role, isAdmin) {
  if (isAdmin) return true
  return Boolean(card?.policy?.allowed_roles?.includes(role))
}

/**
 * 从卡片初始化策略表单。
 *
 * @param {object} card 连接器卡片数据。
 * @returns {object} 策略表单值。
 */
export function normalizePolicyForm(card) {
  const policy = card?.policy || {}
  return {
    enabled: Boolean(policy.enabled),
    allowed_roles: Array.isArray(policy.allowed_roles) ? [...policy.allowed_roles] : ['admin'],
    allowed_task_types: Array.isArray(policy.allowed_task_types)
      ? [...policy.allowed_task_types]
      : ['structured_file_task'],
    requires_confirmation: policy.requires_confirmation !== false,
  }
}

/**
 * 构建策略更新请求；前端不做执行判定，仅提交配置。
 *
 * @param {object} form 策略表单值。
 * @returns {object} PATCH 请求体。
 */
export function buildPolicyPayload(form) {
  return {
    enabled: Boolean(form.enabled),
    allowed_roles: [...form.allowed_roles],
    allowed_task_types: [...form.allowed_task_types],
    requires_confirmation: Boolean(form.requires_confirmation),
  }
}

/**
 * 构建并校验受控测试 run 请求。
 *
 * @param {object} options 测试表单。
 * @param {string} options.providerId provider ID。
 * @param {string} options.prompt 任务说明。
 * @param {number} options.timeoutSeconds 超时秒数。
 * @param {boolean} options.confirmed 是否已确认。
 * @returns {object} POST 请求体。
 * @throws {Error} 缺少 provider、任务说明或未确认时抛错。
 */
export function buildTestRunPayload({ providerId, prompt, timeoutSeconds, confirmed }) {
  if (!providerId) throw new Error('缺少 provider')
  const normalizedPrompt = String(prompt || '').trim()
  if (!normalizedPrompt) throw new Error('请填写任务说明')
  if (!confirmed) throw new Error('执行外部 Agent 任务前必须确认')
  const timeout = Number(timeoutSeconds)
  if (!Number.isFinite(timeout) || timeout <= 0) throw new Error('超时必须大于 0 秒')
  return {
    provider_id: providerId,
    task_type: 'structured_file_task',
    prompt: normalizedPrompt,
    input_files: [],
    output_schema: {
      type: 'object',
      required: ['summary'],
      properties: { summary: { type: 'string' } },
    },
    timeout_seconds: Math.floor(timeout),
    confirmed: true,
  }
}

/**
 * 格式化质量摘要文本。
 *
 * @param {object} summary 质量摘要。
 * @returns {{successRate: string, duration: string}} 展示文本。
 */
export function formatQualitySummary(summary) {
  const rate = summary?.success_rate
  const successRate = rate === null || rate === undefined
    ? '暂无数据'
    : `${Math.round(rate * 100)}%`
  const avg = summary?.avg_duration_ms
  const duration = avg === null || avg === undefined
    ? '暂无数据'
    : avg >= 1000 ? `${(avg / 1000).toFixed(1)}s` : `${avg}ms`
  return { successRate, duration }
}
