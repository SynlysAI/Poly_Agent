/**
 * Assistant Execution Trace reducer 纯函数测试。
 */
import assert from 'node:assert/strict'

import {
  applyTraceEvent,
  createTraceState,
  filterTraceSteps,
  formatTraceDuration,
  traceDetailText,
  traceDisplayGroups,
  traceSummaryRows,
} from './assistantTrace.mjs'

const snapshot = {
  trace_id: 'asrun_trace',
  status: 'running',
  cursor: 'event-2',
  steps: [
    {
      trace_id: 'asrun_trace',
      step_id: 'context:final_answer',
      timestamp: '2026-08-16T01:00:00Z',
      type: 'context',
      title: '上下文准备',
      summary: '已注入 2 个上下文 section',
      status: 'success',
      duration_ms: 500,
      details: { duration_known: true, source_event_refs: [{ event_id: 'event-1', seq: 1 }] },
    },
    {
      trace_id: 'asrun_trace',
      step_id: 'tool:atc_1',
      timestamp: '2026-08-16T01:00:01Z',
      type: 'tool_call',
      title: '算法工具调用',
      summary: '已生成 Demo 调用提案',
      tool_name: 'Demo',
      tool_type: 'algorithm',
      status: 'waiting',
      duration_ms: 0,
      details: {
        duration_known: false,
        source_event_refs: [{ event_id: 'event-2', seq: 2 }],
        argument_keys: ['smiles'],
      },
      parent_step_id: null,
    },
  ],
  summary: {
    total_steps: 2,
    tool_calls: 1,
    llm_calls: 0,
    approvals: 0,
    errors: 0,
    duration_known: false,
    duration_ms: 0,
  },
  replay_warnings: [],
}

let state = createTraceState(snapshot)
assert.equal(state.traceId, 'asrun_trace')
assert.equal(state.status, 'running')
assert.equal(state.cursor, 'event-2')
assert.equal(state.steps.length, 2)

state = applyTraceEvent(state, {
  type: 'trace.step',
  step: {
    ...snapshot.steps[1],
    timestamp: '2026-08-16T01:00:02Z',
    summary: 'Demo 正在执行',
    status: 'running',
    details: {
      duration_known: false,
      source_event_refs: [{ event_id: 'event-2', seq: 2 }, { event_id: 'event-3', seq: 3 }],
    },
  },
})
assert.equal(state.steps.length, 2)
const updatedTool = state.steps.find((step) => step.step_id === 'tool:atc_1')
assert.equal(updatedTool.status, 'running')
assert.equal(updatedTool.details.source_event_refs.length, 2)

state = applyTraceEvent(state, {
  type: 'trace.step',
  step: {
    trace_id: 'asrun_trace',
    step_id: 'approval:atc_1',
    timestamp: '2026-08-16T01:00:00.500Z',
    type: 'approval',
    title: '用户已确认',
    summary: 'Demo 参数已确认',
    status: 'success',
    duration_ms: 100,
    details: { duration_known: true, source_event_refs: [{ event_id: 'event-4', seq: 4 }] },
    parent_step_id: 'tool:atc_1',
  },
})
state = applyTraceEvent(state, {
  type: 'trace.step',
  step: {
    trace_id: 'asrun_trace',
    step_id: 'final:asrun_trace',
    timestamp: '2026-08-16T01:00:04Z',
    type: 'final',
    title: '任务完成',
    summary: '最终回答已生成',
    status: 'success',
    details: { source_event_refs: [{ event_id: 'event-5', seq: 5 }] },
  },
})
state = applyTraceEvent(state, { type: 'unknown', ignored: true })
assert.equal(state.steps.length, 4)

const groups = traceDisplayGroups(state)
assert.deepEqual(groups.map((group) => group.label), ['请求与上下文', '工具审批与执行', '结果与续答'])
assert.ok(groups.some((group) => group.steps.some((step) => step.step_id === 'approval:atc_1')))

state = applyTraceEvent(state, {
  type: 'trace.summary',
  status: 'completed',
  summary: { ...snapshot.summary, total_steps: 5, approvals: 1 },
})
state = applyTraceEvent(state, { type: 'trace.end', status: 'completed' })
assert.equal(state.status, 'completed')
assert.equal(state.streaming, false)
assert.equal(traceSummaryRows(state).at(-1)[1], '未记录')

const controlStep = {
  trace_id: 'chat_trace',
  step_id: 'control:goal-1',
  timestamp: '2026-08-18T01:00:00Z',
  type: 'control',
  title: '会话目标已更新',
  summary: '目标已记录',
  status: 'success',
  details: { event_types: ['goal.changed'], source_event_refs: [] },
}
const commandStep = {
  trace_id: 'chat_trace',
  step_id: 'command:cmd-1',
  timestamp: '2026-08-18T01:00:01Z',
  type: 'command',
  title: 'Slash 命令',
  summary: '/status',
  status: 'success',
  details: { event_types: ['command.run', 'command.done'], source_event_refs: [] },
}
const exportStep = {
  trace_id: 'chat_trace',
  step_id: 'export:cmd-2',
  timestamp: '2026-08-18T01:00:02Z',
  type: 'export',
  title: '会话已导出',
  summary: 'ZIP 导出完成',
  status: 'success',
  details: { event_types: ['session.exported'], source_event_refs: [] },
}
const chatSteps = [...state.steps, controlStep, commandStep, exportStep]
assert.equal(filterTraceSteps(chatSteps, 'all').length, chatSteps.length)
assert.deepEqual(filterTraceSteps(chatSteps, 'command').map((step) => step.step_id), ['command:cmd-1'])
assert.deepEqual(filterTraceSteps(chatSteps, 'control').map((step) => step.step_id), ['control:goal-1'])
assert.deepEqual(filterTraceSteps(chatSteps, 'export').map((step) => step.step_id), ['export:cmd-2'])
assert.deepEqual(filterTraceSteps(chatSteps, 'unknown-filter'), [])

const chatGroups = traceDisplayGroups({ steps: chatSteps })
assert.ok(chatGroups.some((group) => group.steps.some((step) => step.step_id === 'command:cmd-1')))
assert.ok(chatGroups.some((group) => group.steps.some((step) => step.step_id === 'control:goal-1')))
assert.ok(chatGroups.some((group) => group.steps.some((step) => step.step_id === 'export:cmd-2')))

assert.equal(formatTraceDuration({ duration_ms: 1200, details: { duration_known: true } }), '1.2s')
assert.equal(formatTraceDuration({ duration_ms: 0, details: { duration_known: false } }), '未记录')

const longText = 'x'.repeat(5000)
const detail = traceDetailText({ details: { source_event_refs: [], safe_value: longText } })
assert.ok(detail.length <= 4100)
assert.match(detail, /内容已截断/)

console.log('assistant trace reducer tests passed')
