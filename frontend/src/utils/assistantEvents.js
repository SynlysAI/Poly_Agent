import { applyToolCallEvent } from './assistantToolCalls.mjs'

/**
 * Convert an append-only assistant event document to the legacy stream shape.
 *
 * @param {object} event Canonical event document or legacy stream event.
 * @returns {object} Legacy-compatible event payload.
 */
export function normalizeAssistantEvent(event) {
  if (!event?.data) return { ...(event || {}) }
  return {
    seq: event.seq,
    at: event.at,
    ...(event.data || {}),
  }
}

function assistantEventKey(event) {
  const callId = event?.call_id || event?.data?.call_id || ''
  const type = event?.data?.type || event?.type || ''
  return `${callId}:${event?.seq || 0}:${type}`
}

function eventSortValue(event) {
  return Number(event?.seq || 0)
}

/**
 * Merge legacy and canonical events without duplicate replay.
 *
 * @param {Array<object>} existing Previously replayed event payloads or documents.
 * @param {Array<object>} incoming New event payloads or documents.
 * @returns {Array<object>} Deduplicated events in seq order.
 */
export function mergeAssistantEvents(existing, incoming) {
  const merged = new Map()
  for (const event of [...(existing || []), ...(incoming || [])]) {
    if (!event) continue
    const key = assistantEventKey(event)
    const current = merged.get(key)
    if (!current || (!current.event_id && event.event_id)) merged.set(key, event)
  }
  return [...merged.values()].sort((a, b) => eventSortValue(a) - eventSortValue(b))
}

function applyFinalEvent(state, event) {
  const data = event.data || {}
  state.content = data.content || state.content || ''
  state.context_digest = data.grounding_facts?.context?.digest || state.context_digest || ''
  state.answer_mode = data.answer_mode || state.answer_mode || ''
  state.final = data
  return state
}

/**
 * Replay normalized assistant events into a compact UI state.
 *
 * @param {Array<object>} events Legacy or canonical assistant events.
 * @returns {object} Replay state with route, answer, context, and tool calls.
 */
export function replayAssistantEvents(events) {
  const state = {
    content: '',
    route: null,
    context_digest: '',
    answer_mode: '',
    stream_stage: '',
    tool_calls: [],
    replay_errors: 0,
  }
  const ordered = mergeAssistantEvents(events, []).map(normalizeAssistantEvent)
  for (const event of ordered) {
    try {
      if (event.type === 'tool_call' || event.type === 'tool_input_required') {
        applyToolCallEvent(state, event)
      } else if (event.type === 'route.resolved' || event.type === 'route.fallback') {
        state.route = event.route || state.route
      } else if (event.type === 'status') {
        state.stream_stage = event.stage || state.stream_stage
      } else if (event.type === 'answer_delta') {
        state.content += event.delta || ''
      } else if (event.type === 'context.assembled' || event.type === 'request.header') {
        state.context_digest = event.manifest?.context?.digest || state.context_digest
      } else if (event.type === 'final') {
        applyFinalEvent(state, event)
      }
    } catch {
      state.replay_errors += 1
    }
  }
  return state
}
