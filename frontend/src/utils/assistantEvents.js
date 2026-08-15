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
  state.grounding_facts = data.grounding_facts || state.grounding_facts || {}
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
    route_reason: '',
    context_digest: '',
    context_manifest: null,
    context_manifests: {},
    tool_catalog: [],
    tool_schema: [],
    usage: null,
    references: [],
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
        state.route_reason = event.route?.route_reason || event.reason || state.route_reason
        if (event.type === 'route.fallback' && event.reason) {
          state.route = { ...(state.route || {}), fallback_reason: event.reason }
        }
      } else if (event.type === 'route.requested') {
        state.requested_route = event.route || state.requested_route
      } else if (event.type === 'status') {
        state.stream_stage = event.stage || state.stream_stage
      } else if (event.type === 'answer_delta') {
        state.content += event.delta || ''
      } else if (event.type === 'context.assembled' || event.type === 'request.header') {
        state.context_digest = event.manifest?.context?.digest || state.context_digest
        state.context_manifest = event.manifest || state.context_manifest
        if (event.request_kind) {
          state.context_manifests = {
            ...(state.context_manifests || {}),
            [event.request_kind]: event.manifest,
          }
        }
      } else if (event.type === 'tool.catalog.resolved') {
        state.tool_catalog = event.tools || state.tool_catalog
      } else if (event.type === 'tool.schema.rendered') {
        state.tool_schema = event.tools || state.tool_schema
      } else if (event.type === 'llm.usage.recorded') {
        state.usage = event.usage || state.usage
      } else if (event.type === 'evidence' && Array.isArray(event.references)) {
        state.references = [...state.references, ...event.references]
      } else if (event.type === 'final') {
        applyFinalEvent(state, event)
      }
    } catch {
      state.replay_errors += 1
    }
  }
  return state
}
