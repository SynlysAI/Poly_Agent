import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildPolicyPayload,
  buildTestRunPayload,
  connectorStatus,
  connectorVisibleToUser,
  formatQualitySummary,
  normalizePolicyForm,
} from './agentConnectors.mjs'

test('connectorStatus 覆盖 unavailable / disabled / ready', () => {
  assert.deepEqual(connectorStatus(null).kind, 'unavailable')

  const unavailable = connectorStatus({
    readiness: { available: false, message: 'AGENT_EXEC_ENABLED 未开启' },
  })
  assert.equal(unavailable.kind, 'unavailable')
  assert.equal(unavailable.reason, 'AGENT_EXEC_ENABLED 未开启')

  const disabled = connectorStatus({
    readiness: { available: true },
    policy: { enabled: false },
  })
  assert.equal(disabled.kind, 'disabled')

  const ready = connectorStatus({
    readiness: { available: true },
    policy: { enabled: true },
  })
  assert.equal(ready.kind, 'ready')
  assert.equal(ready.tag, 'success')
})

test('普通用户仅在角色被允许时可见，管理员始终可见', () => {
  const card = { policy: { allowed_roles: ['admin'] } }
  assert.equal(connectorVisibleToUser(card, 'user', false), false)
  assert.equal(connectorVisibleToUser(card, 'admin', true), true)
  assert.equal(
    connectorVisibleToUser({ policy: { allowed_roles: ['admin', 'user'] } }, 'user', false),
    true,
  )
})

test('策略表单初始化与请求体构建保持安全默认值', () => {
  const form = normalizePolicyForm(null)
  assert.equal(form.enabled, false)
  assert.deepEqual(form.allowed_roles, ['admin'])
  assert.deepEqual(form.allowed_task_types, ['structured_file_task'])
  assert.equal(form.requires_confirmation, true)

  const payload = buildPolicyPayload({ ...form, enabled: true })
  assert.equal(payload.enabled, true)
  assert.equal(payload.requires_confirmation, true)
})

test('测试 run 请求必须显式确认且参数合法', () => {
  assert.throws(() => buildTestRunPayload({ providerId: '', prompt: 'x', timeoutSeconds: 5, confirmed: true }), /缺少 provider/)
  assert.throws(() => buildTestRunPayload({ providerId: 'codex', prompt: '', timeoutSeconds: 5, confirmed: true }), /任务说明/)
  assert.throws(() => buildTestRunPayload({ providerId: 'codex', prompt: 'x', timeoutSeconds: 5, confirmed: false }), /必须确认/)
  assert.throws(() => buildTestRunPayload({ providerId: 'codex', prompt: 'x', timeoutSeconds: 0, confirmed: true }), /超时/)

  const payload = buildTestRunPayload({ providerId: 'codex', prompt: ' 汇总 ', timeoutSeconds: 5.8, confirmed: true })
  assert.equal(payload.provider_id, 'codex')
  assert.equal(payload.task_type, 'structured_file_task')
  assert.equal(payload.prompt, '汇总')
  assert.equal(payload.timeout_seconds, 5)
  assert.equal(payload.confirmed, true)
})

test('质量摘要格式化', () => {
  assert.deepEqual(formatQualitySummary(null), { successRate: '暂无数据', duration: '暂无数据' })
  assert.deepEqual(
    formatQualitySummary({ success_rate: 0.856, avg_duration_ms: 1530 }),
    { successRate: '86%', duration: '1.5s' },
  )
  assert.deepEqual(
    formatQualitySummary({ success_rate: 1, avg_duration_ms: 90 }),
    { successRate: '100%', duration: '90ms' },
  )
})
