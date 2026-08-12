import assert from 'node:assert/strict'

import {
  applyToolCallEvent,
  canEditToolCall,
  normalizeToolCall,
  parseToolArguments,
  replaceToolCall,
  toolCallRunDetailRoute,
  toolPhaseLabel,
  toolPhaseTagType,
  schemaFieldType,
  normalizeSchemaArguments,
} from './assistantToolCalls.mjs'

assert.equal(toolPhaseLabel('awaiting_confirmation'), '等待确认')
assert.equal(toolPhaseLabel('completed'), '已完成')
assert.equal(toolPhaseLabel('unknown-phase'), 'unknown-phase')
assert.equal(toolPhaseTagType('completed'), 'success')
assert.equal(toolPhaseTagType('running'), 'warning')
assert.equal(toolPhaseTagType('failed'), 'danger')
assert.equal(toolPhaseTagType('canceled'), 'info')
assert.equal(toolPhaseTagType('awaiting_input'), 'primary')
assert.equal(toolPhaseLabel('queued'), '排队中')
assert.equal(schemaFieldType('number - 温度'), 'number')
assert.equal(schemaFieldType('list[string]'), 'array')
assert.equal(normalizeSchemaArguments({ field_schema: { fields: { smiles: 'string' }, required: ['smiles'] }, arguments: { smiles: 'CCO' } })[0].value, 'CCO')

assert.equal(canEditToolCall({ phase: 'awaiting_input' }), true)
assert.equal(canEditToolCall({ phase: 'awaiting_confirmation' }), true)
assert.equal(canEditToolCall({ phase: 'running' }), false)
assert.equal(canEditToolCall(null), false)

const normalized = normalizeToolCall({ call_id: 'atc-1', arguments: { smiles: 'CCO' } })
assert.equal(normalized.arguments_text, JSON.stringify({ smiles: 'CCO' }, null, 2))
assert.deepEqual(normalizeToolCall(null), { arguments_text: '{}' })

assert.deepEqual(parseToolArguments('{"smiles": "CCO"}'), { ok: true, arguments: { smiles: 'CCO' } })
assert.equal(parseToolArguments('not json').ok, false)
assert.equal(parseToolArguments('"str"').ok, false)

const message = { role: 'user', tool_calls: [] }
applyToolCallEvent(message, {
  type: 'tool_call',
  call_id: 'atc-1',
  phase: 'requested',
  tool_id: 'algorithm:vertical-tool',
  tool_name: 'Vertical Tool',
  arguments: { smiles: 'CCO' },
})
assert.equal(message.tool_calls.length, 1)
assert.equal(message.tool_calls[0].phase, 'requested')
applyToolCallEvent(message, {
  type: 'tool_call',
  call_id: 'atc-1',
  phase: 'awaiting_confirmation',
  tool_name: 'Vertical Tool',
  arguments: { smiles: 'CCO', temperature: 300 },
})
assert.equal(message.tool_calls.length, 1)
assert.equal(message.tool_calls[0].phase, 'awaiting_confirmation')
assert.deepEqual(JSON.parse(message.tool_calls[0].arguments_text), { smiles: 'CCO', temperature: 300 })

applyToolCallEvent(message, {
  type: 'tool_input_required',
  call_id: 'atc-1',
  missing_fields: ['smiles'],
})
assert.deepEqual(message.tool_calls[0].missing_fields, ['smiles'])

replaceToolCall(message, {
  call_id: 'atc-1',
  phase: 'completed',
  tool_id: 'algorithm:vertical-tool',
  tool_name: 'Vertical Tool',
  arguments: { smiles: 'CCO' },
  result_summary: { score: 0.91 },
})
assert.equal(message.tool_calls.length, 1)
assert.equal(message.tool_calls[0].phase, 'completed')
assert.equal(message.tool_calls[0].result_summary.score, 0.91)

assert.deepEqual(
  toolCallRunDetailRoute({ algorithm_id: 'PI_Tg_predictor', run_id: 'arun_abc123' }),
  {
    path: '/vertical-prediction',
    query: {
      tab: 'detail',
      algorithm_id: 'PI_Tg_predictor',
      run_id: 'arun_abc123',
    },
  },
)
assert.deepEqual(toolCallRunDetailRoute(null), {
  path: '/vertical-prediction',
  query: { tab: 'detail', algorithm_id: '', run_id: '' },
})

console.log('assistantToolCalls tests passed')
