import assert from 'node:assert/strict'

import {
  applyToolCallEvent,
  buildToolCallConfirmPayload,
  buildToolCallRawArgumentsPayload,
  canEditToolCall,
  isStaleToolCallPhase,
  mergeToolCalls,
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
assert.equal(schemaFieldType('list'), 'array')
assert.equal(schemaFieldType('array'), 'array')
assert.equal(schemaFieldType('dict'), 'object')
assert.equal(schemaFieldType('map[string]'), 'object')
assert.equal(normalizeSchemaArguments({ field_schema: { fields: { smiles: 'string' }, required: ['smiles'] }, arguments: { smiles: 'CCO' } })[0].value, 'CCO')
const schemaDrivenFields = normalizeSchemaArguments({
  input_json_schema: {
    properties: {
      temperature: { type: 'number', description: '温度', minimum: 0, maximum: 500, default: 298 },
      mode: { type: 'string', enum: ['fast', 'accurate'] },
    },
    required: ['temperature'],
  },
  arguments: { temperature: 300 },
})
assert.equal(schemaDrivenFields.length, 2)
assert.equal(schemaDrivenFields[0].type, 'number')
assert.equal(schemaDrivenFields[0].required, true)
assert.deepEqual(schemaDrivenFields[0].options, [])
assert.deepEqual(schemaDrivenFields[1].options, ['fast', 'accurate'])

assert.equal(canEditToolCall({ phase: 'awaiting_input' }), true)
assert.equal(canEditToolCall({ phase: 'awaiting_confirmation' }), true)
assert.equal(canEditToolCall({ phase: 'running' }), false)
assert.equal(canEditToolCall(null), false)

assert.equal(isStaleToolCallPhase('queued', 'awaiting_confirmation'), true)
assert.equal(isStaleToolCallPhase('running', 'requested'), true)
assert.equal(isStaleToolCallPhase('completed', 'awaiting_confirmation'), true)
assert.equal(isStaleToolCallPhase('awaiting_confirmation', 'queued'), false)
assert.equal(isStaleToolCallPhase('queued', 'running'), false)
assert.equal(isStaleToolCallPhase('', 'awaiting_confirmation'), false)

const normalized = normalizeToolCall({ call_id: 'atc-1', arguments: { smiles: 'CCO' } })
assert.equal(normalized.arguments_text, JSON.stringify({ smiles: 'CCO' }, null, 2))
const rawProposal = normalizeToolCall({
  call_id: 'atc-raw',
  arguments: {},
  raw_arguments: '{"smiles": "CCO"',
  arguments_parse_error: 'Expecting object',
})
assert.equal(rawProposal.raw_arguments_text, '{"smiles": "CCO"')
assert.equal(rawProposal.arguments_parse_error, 'Expecting object')
assert.deepEqual(normalizeToolCall(null), { arguments_text: '{}', raw_arguments_text: '', events: [] })

assert.deepEqual(parseToolArguments('{"smiles": "CCO"}'), { ok: true, arguments: { smiles: 'CCO' } })
assert.equal(parseToolArguments('not json').ok, false)
assert.equal(parseToolArguments('"str"').ok, false)

const rawProposalPayload = buildToolCallRawArgumentsPayload({
  raw_arguments_text: '{"smiles": "CCC"}',
  arguments: { smiles: 'CCO' },
})
assert.deepEqual(rawProposalPayload, {
  ok: true,
  payload: { raw_arguments: '{"smiles": "CCC"}' },
})
assert.equal(buildToolCallRawArgumentsPayload({ raw_arguments_text: '  ' }).ok, false)
assert.equal(buildToolCallRawArgumentsPayload({ raw_arguments_text: 'not json' }).ok, false)

const confirmPayload = buildToolCallConfirmPayload({
  arguments_text: '{"smiles": "CCO", "temperature": 300}',
  arguments: { smiles: 'stale' },
  input_asset_refs: { structure: { artifact_id: 'art-1' } },
})
assert.deepEqual(confirmPayload, {
  ok: true,
  payload: {
    arguments: { smiles: 'CCO', temperature: 300 },
    input_asset_refs: { structure: { artifact_id: 'art-1' } },
  },
})
assert.equal(buildToolCallConfirmPayload({ arguments_text: 'not json' }).ok, false)
assert.deepEqual(
  buildToolCallConfirmPayload({
    arguments: { smiles: 'CCO' },
    input_asset_refs: { structure: { artifact_id: 'art-1' } },
  }),
  {
    ok: true,
    payload: {
      arguments: { smiles: 'CCO' },
      input_asset_refs: { structure: { artifact_id: 'art-1' } },
    },
  },
)
assert.deepEqual(
  buildToolCallConfirmPayload({
    arguments_text: '  ',
    arguments: { smiles: 'CCO' },
  }),
  {
    ok: true,
    payload: {
      arguments: { smiles: 'CCO' },
      input_asset_refs: {},
    },
  },
)

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

// 已进入执行/结束状态的调用不允许被重放的旧事件降级回待确认。
const racingMessage = { role: 'user', tool_calls: [] }
applyToolCallEvent(racingMessage, {
  type: 'tool_call',
  call_id: 'atc-race',
  phase: 'awaiting_confirmation',
  tool_id: 'algorithm:vertical-tool',
  tool_name: 'Vertical Tool',
  arguments: { smiles: 'CCO' },
})
applyToolCallEvent(racingMessage, {
  type: 'tool_call',
  call_id: 'atc-race',
  phase: 'queued',
  tool_name: 'Vertical Tool',
  arguments: { smiles: 'CCO' },
})
applyToolCallEvent(racingMessage, {
  type: 'tool_call',
  call_id: 'atc-race',
  phase: 'awaiting_confirmation',
  tool_name: 'Vertical Tool',
  arguments: { smiles: 'CCO' },
})
assert.equal(racingMessage.tool_calls[0].phase, 'queued')

const merged = mergeToolCalls(
  [
    {
      call_id: 'atc-final',
      phase: 'completed',
      tool_id: 'algorithm:vertical-tool',
      tool_name: 'Vertical Tool',
      arguments: { smiles: 'CCO' },
      result_summary: { score: 0.91 },
    },
  ],
  [
    {
      call_id: 'atc-final',
      phase: 'awaiting_confirmation',
      tool_id: 'algorithm:vertical-tool',
      tool_name: 'Vertical Tool',
      arguments: { smiles: 'CCO' },
    },
  ],
)
assert.equal(merged.length, 1)
assert.equal(merged[0].phase, 'completed')
assert.equal(merged[0].result_summary.score, 0.91)

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
