import assert from 'node:assert/strict'

import {
  mergeAssistantEvents,
  normalizeAssistantEvent,
  replayAssistantEvents,
} from './assistantEvents.js'

const routeEvent = {
  event_id: 'asevt_route',
  run_id: 'asrun_1',
  call_id: '',
  seq: 1,
  type: 'route.resolved',
  at: '2026-08-15T10:00:01Z',
  data: { type: 'route.resolved', route: { provider_id: 'p1', model_id: 'm1' } },
}
const toolRequested = {
  event_id: 'asevt_tool_1',
  run_id: 'asrun_1',
  call_id: 'atc_1',
  seq: 2,
  type: 'tool.proposed',
  at: '2026-08-15T10:00:02Z',
  data: { type: 'tool_call', call_id: 'atc_1', phase: 'requested', tool_id: 'algorithm:a' },
}
const toolCompleted = {
  event_id: 'asevt_tool_2',
  run_id: 'asrun_1',
  call_id: 'atc_1',
  seq: 3,
  type: 'tool.result',
  at: '2026-08-15T10:00:03Z',
  data: {
    type: 'tool_call',
    call_id: 'atc_1',
    phase: 'completed',
    tool_id: 'algorithm:a',
    result_summary: { score: 1 },
  },
}
const staleToolRequested = {
  event_id: 'asevt_tool_3',
  run_id: 'asrun_1',
  call_id: 'atc_1',
  seq: 4,
  type: 'tool.proposed',
  at: '2026-08-15T10:00:04Z',
  data: { type: 'tool_call', call_id: 'atc_1', phase: 'requested', tool_id: 'algorithm:a' },
}
const answerEvent = {
  event_id: 'asevt_answer',
  run_id: 'asrun_1',
  call_id: '',
  seq: 5,
  type: 'assistant.finalized',
  at: '2026-08-15T10:00:05Z',
  data: {
    type: 'final',
    data: {
      content: '最终回答',
      grounding_facts: { context: { digest: 'sha256:abc' } },
      tool_calls: [],
    },
  },
}

assert.equal(normalizeAssistantEvent(routeEvent).route.model_id, 'm1')
assert.equal(normalizeAssistantEvent(toolRequested).type, 'tool_call')

const merged = mergeAssistantEvents(
  [normalizeAssistantEvent(routeEvent)],
  [routeEvent, toolRequested],
)
assert.equal(merged.length, 2)

const state = replayAssistantEvents([
  staleToolRequested,
  answerEvent,
  toolCompleted,
  routeEvent,
  toolRequested,
])

assert.equal(state.route.model_id, 'm1')
assert.equal(state.content, '最终回答')
assert.equal(state.context_digest, 'sha256:abc')
assert.equal(state.tool_calls[0].phase, 'completed')
assert.equal(state.replay_errors, 0)

console.log('assistant event reducer tests passed')
