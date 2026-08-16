import assert from 'node:assert/strict'

import {
  capabilitySourceLabel,
  contextDigest,
  contextSectionRows,
  contextToolRows,
  formatContextWindow,
  formatUsage,
  modelMetaLabel,
  normalizeAssistantRoute,
  routeCapabilityLabels,
  routeReasonLabel,
  toolArgumentDiff,
  toolCapableModelOptions,
  toolProtocolLabel,
  toolTimelineRows,
} from './assistantUi.mjs'

const route = normalizeAssistantRoute({
  provider_id: 'deepseek_primary',
  model_id: 'deepseek-v4-flash',
  route_reason: 'user_selected',
  capabilities: ['chat', 'tool_calling'],
  capability_source: 'configured',
  tool_protocol: 'openai_chat_tools',
  context_window: 131072,
})

assert.equal(route.provider_id, 'deepseek_primary')
assert.equal(route.model_id, 'deepseek-v4-flash')
assert.equal(routeReasonLabel('tool_capability_override'), '工具能力改选')
assert.equal(capabilitySourceLabel('configured'), '配置确认')
assert.equal(toolProtocolLabel('openai_chat_tools'), 'OpenAI Chat Tools')
assert.equal(formatContextWindow(131072), '128K')
assert.equal(modelMetaLabel(route), 'deepseek_primary / deepseek-v4-flash')
assert.deepEqual(routeCapabilityLabels(route), ['工具调用'])
assert.equal(formatUsage({ prompt_tokens: 1200, completion_tokens: 300, total_tokens: 1500 }), '输入 1.2k · 输出 300 · 总计 1.5k')
assert.equal(formatUsage({}), '')

const manifest = {
  context: {
    digest: 'sha256:abc',
    sections: [
      { name: 'project_facts', source: 'ProjectService', token_estimate: 80, included: true, omitted_reason: null },
      { name: 'web_evidence', source: 'WebService', token_estimate: 0, included: false, omitted_reason: 'budget' },
    ],
  },
  tools: [{ tool_id: 'algorithm:a', function_name: 'algorithm_a', version: '1.0.0', schema_digest: 'sha256:xyz' }],
}

assert.equal(contextDigest(manifest), 'sha256:abc')
assert.equal(contextSectionRows(manifest).length, 2)
assert.equal(contextSectionRows(manifest)[0].name, 'project_facts')
assert.equal(contextSectionRows(manifest)[1].omitted_reason, 'budget')
assert.equal(contextToolRows(manifest).length, 1)

const diff = toolArgumentDiff({
  raw_arguments: '{"temperature": 300, "mode": "fast"}',
  arguments: { temperature: 310, mode: 'fast' },
})
assert.equal(diff.ok, true)
assert.equal(diff.changes.length, 1)
assert.equal(diff.changes[0].key, 'temperature')
assert.equal(diff.changes[0].proposed, 300)
assert.equal(diff.changes[0].confirmed, 310)

const invalidDiff = toolArgumentDiff({
  raw_arguments: '{"temperature": ',
  arguments: { temperature: 310 },
})
assert.equal(invalidDiff.ok, false)
assert.equal(invalidDiff.error, '原始参数 JSON 解析失败')

const timeline = toolTimelineRows({
  events: [
    { seq: 1, at: '2026-08-15T10:00:00Z', type: 'tool.proposed', phase: 'requested' },
    { seq: 2, at: '2026-08-15T10:01:00Z', type: 'tool.proposal.updated', message: '模型原始提案已更新' },
    { seq: 3, at: '2026-08-15T10:02:00Z', type: 'tool.proposal.backfilled', message: '历史原始提案已按最终参数回填' },
    { seq: 4, at: '2026-08-15T10:03:00Z', type: 'tool.awaiting_confirmation', phase: 'awaiting_confirmation' },
  ],
})
assert.equal(timeline.length, 4)
assert.equal(timeline[0].label, '模型提议')
assert.equal(timeline[1].label, '原始提案已更新')
assert.equal(timeline[1].detail, '模型原始提案已更新')
assert.equal(timeline[2].label, '原始提案已回填')
assert.equal(timeline[3].label, '等待确认')

const fallbackTimeline = toolTimelineRows({
  created_at: '2026-08-15T10:00:00Z',
  confirmed_at: '2026-08-15T10:01:00Z',
  finished_at: '2026-08-15T10:02:00Z',
  phase: 'completed',
})
assert.equal(fallbackTimeline.length, 3)
assert.equal(fallbackTimeline[0].label, '已创建')
assert.equal(fallbackTimeline[2].label, '执行完成')

const models = [
  { key: 'a', capabilities: ['chat'] },
  { key: 'b', capabilities: ['chat', 'tool_calling'] },
]
assert.deepEqual(toolCapableModelOptions(models).map((item) => item.key), ['b'])

console.log('assistant ui helpers tests passed')
