import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildCapabilityConnectorPayload,
  capabilityAction,
  capabilityStatusLabel,
  normalizeCapabilityCatalog,
  visibleCapabilityItems,
} from './capabilityCenter.mjs'

const item = (id, overrides = {}) => ({
  id,
  name: id,
  description: 'safe',
  module_id: 'test',
  status: 'available',
  reason: null,
  policy: { allowed_roles: ['admin', 'user'], requires_confirmation: true, viewer_can_invoke: true, scope_note: 'safe' },
  invocation: { kind: 'dialogue_tool', method: 'navigate', target: '/dialogue?toolIds=x' },
  config_path: '/tools?tab=agent-tools',
  attributions: [{ name: 'ALchemist', role: 'method_reference' }],
  input_schema: { secret: true },
  output_schema: { secret: true },
  api_key: 'secret',
})

const mergeItem = (id, overrides = {}) => {
  const base = item(id)
  return {
    ...base,
    ...overrides,
    policy: { ...base.policy, ...(overrides.policy || {}) },
    invocation: { ...base.invocation, ...(overrides.invocation || {}) },
  }
}

test('normalizeCapabilityCatalog 只保留公开白名单字段', () => {
  const data = normalizeCapabilityCatalog({
    generated_at: '2026-08-28T10:00:00Z',
    viewer_role: 'user',
    is_admin: false,
    dialogue_tools: { group_id: 'dialogue_tools', title: '对话工具', description: 'x', status: 'available', total_count: 1, invocable_count: 1, unavailable_reason: null, items: [item('tool')] },
    agent_connectors: { group_id: 'agent_connectors', title: '外部 Agent 连接器', description: 'x', status: 'unavailable', total_count: 0, invocable_count: 0, unavailable_reason: '暂无', items: [] },
    report_skills: { group_id: 'report_skills', title: '报告 Skill', description: 'x', status: 'partial', total_count: 2, invocable_count: 1, unavailable_reason: 'x', items: [] },
    llm_capabilities: { group_id: 'llm_capabilities', title: 'LLM 能力', description: 'x', status: 'available', total_count: 1, invocable_count: 1, unavailable_reason: null, items: [] },
    api_key: 'secret',
  })
  assert.equal(data.viewer_role, 'user')
  assert.equal(data.dialogue_tools.items[0].name, 'tool')
  assert.equal(data.dialogue_tools.items[0].policy.viewer_can_invoke, true)
  assert.equal(data.dialogue_tools.items[0].attributions[0].name, 'ALchemist')
  assert.deepEqual(Object.keys(data.dialogue_tools.items[0]).sort(), [
    'attributions', 'config_path', 'description', 'id', 'invocation',
    'module_id', 'name', 'policy', 'reason', 'status',
  ])
})

test('visibleCapabilityItems 管理员看全部，普通用户只看可调用项', () => {
  const unavailable = mergeItem('disabled', { status: 'disabled', policy: { viewer_can_invoke: false } })
  const group = { items: [item('ok'), unavailable] }
  assert.deepEqual(visibleCapabilityItems(group, true).map((entry) => entry.id), ['ok', 'disabled'])
  assert.deepEqual(visibleCapabilityItems(group, false).map((entry) => entry.id), ['ok'])
})

test('状态与动作文案覆盖导航、API 与不可调用场景', () => {
  assert.equal(capabilityStatusLabel('available'), '可用')
  assert.equal(capabilityStatusLabel('disabled'), '已停用')
  assert.deepEqual(capabilityAction(item('ok')), { kind: 'navigate', label: '进入对话调用', disabled: false })
  assert.deepEqual(capabilityAction(mergeItem('connector', {
    invocation: { kind: 'agent_connector', method: 'api', target: 'agent-exec/runs' },
  })), { kind: 'api', label: '发起结构化任务', disabled: false })
  const blocked = mergeItem('blocked', { status: 'unavailable', policy: { viewer_can_invoke: false } })
  assert.deepEqual(capabilityAction(blocked), { kind: 'none', label: '暂不可调用', disabled: true })
})

test('连接器 payload 复用显式确认与结构化任务校验', () => {
  assert.throws(() => buildCapabilityConnectorPayload({ providerId: 'codex', prompt: 'x', timeoutSeconds: 5, confirmed: false }), /必须确认/)
  const payload = buildCapabilityConnectorPayload({ providerId: 'codex', prompt: ' x ', timeoutSeconds: 5.8, confirmed: true })
  assert.equal(payload.provider_id, 'codex')
  assert.equal(payload.task_type, 'structured_file_task')
  assert.equal(payload.confirmed, true)
  assert.equal(payload.timeout_seconds, 5)
})
