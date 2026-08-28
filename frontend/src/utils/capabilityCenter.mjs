/** 能力中心视图纯函数。 */

import { buildTestRunPayload } from './agentConnectors.mjs'

export const CAPABILITY_GROUP_ORDER = [
  'dialogue_tools',
  'agent_connectors',
  'report_skills',
  'llm_capabilities',
]

/**
 * 把服务端 catalog 契约转换为前端展示对象，并做字段白名单。
 *
 * @param {object} data 服务端 catalog 数据。
 * @returns {object} 仅包含公开展示字段的 catalog。
 */
export function normalizeCapabilityCatalog(data) {
  const source = data || {}
  return {
    generated_at: source.generated_at || '',
    viewer_role: source.viewer_role || 'user',
    is_admin: Boolean(source.is_admin),
    ...Object.fromEntries(CAPABILITY_GROUP_ORDER.map((key) => [key, normalizeGroup(source[key], key)])),
  }
}

/**
 * 规范化单个能力分组。
 *
 * @param {object} group 服务端分组。
 * @param {string} key 固定分组 key。
 * @returns {object} 前端分组。
 */
function normalizeGroup(group, key) {
  const source = group || {}
  return {
    group_id: key,
    title: source.title || key,
    description: source.description || '',
    status: source.status || 'unavailable',
    total_count: Number(source.total_count || 0),
    invocable_count: Number(source.invocable_count || 0),
    unavailable_reason: source.unavailable_reason || '',
    items: Array.isArray(source.items) ? source.items.map(publicItem).filter(Boolean) : [],
  }
}

/**
 * 输出能力卡片公开字段，防止未来服务端字段扩展直接进入页面。
 *
 * @param {object} raw 服务端卡片。
 * @returns {object|null} 白名单卡片；缺少必要结构时返回 null。
 */
export function publicItem(raw) {
  const source = raw || {}
  if (!source.id || !source.invocation) return null
  return {
    id: String(source.id),
    name: String(source.name || source.id),
    description: String(source.description || ''),
    module_id: String(source.module_id || ''),
    status: String(source.status || 'unavailable'),
    reason: source.reason || '',
    policy: {
      allowed_roles: Array.isArray(source.policy?.allowed_roles) ? [...source.policy.allowed_roles] : [],
      requires_confirmation: Boolean(source.policy?.requires_confirmation),
      viewer_can_invoke: Boolean(source.policy?.viewer_can_invoke),
      scope_note: String(source.policy?.scope_note || ''),
    },
    invocation: { ...source.invocation },
    config_path: String(source.config_path || ''),
    attributions: Array.isArray(source.attributions)
      ? source.attributions.map((item) => ({
        name: String(item?.name || ''),
        role: String(item?.role || ''),
        organization: String(item?.organization || ''),
        visibility: String(item?.visibility || 'detail'),
      })).filter((item) => item.name)
      : [],
  }
}

/**
 * 按角色计算可见卡片。
 *
 * @param {object} group 能力分组。
 * @param {boolean} isAdmin 是否管理员。
 * @returns {Array<object>} 可见卡片。
 */
export function visibleCapabilityItems(group, isAdmin) {
  const items = Array.isArray(group?.items) ? group.items : []
  if (isAdmin) return items
  return items.filter((item) => item.status === 'available' && item.policy?.viewer_can_invoke)
}

/**
 * 返回能力状态中文文案。
 *
 * @param {string} status 服务端状态。
 * @returns {string} 中文状态。
 */
export function capabilityStatusLabel(status) {
  const labels = { available: '可用', degraded: '降级', disabled: '已停用', unavailable: '不可用' }
  return labels[status] || '不可用'
}

/**
 * 计算卡片主调用动作。
 *
 * @param {object} item 能力卡片。
 * @returns {{kind: string, label: string, disabled: boolean}} 动作描述。
 */
export function capabilityAction(item) {
  if (!item?.policy?.viewer_can_invoke || item.status !== 'available') {
    return { kind: 'none', label: '暂不可调用', disabled: true }
  }
  if (item.invocation?.method === 'api') {
    return { kind: 'api', label: '发起结构化任务', disabled: false }
  }
  return { kind: 'navigate', label: '进入对话调用', disabled: false }
}

/**
 * 构建连接器调用请求体，复用既有确认与参数校验。
 *
 * @param {object} options 调用表单。
 * @returns {object} POST /agent-exec/runs 请求体。
 */
export function buildCapabilityConnectorPayload(options) {
  return buildTestRunPayload(options)
}
