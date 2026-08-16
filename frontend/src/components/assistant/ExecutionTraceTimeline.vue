<script setup>
import { computed } from 'vue'
import {
  formatTraceDuration,
  traceDetailText,
  traceDisplayGroups,
  traceSummaryRows,
} from '../../utils/assistantTrace.mjs'

/**
 * 消息内 Execution Trace 时间线。
 * 只展示后端投影出的真实步骤，不在前端补造执行动作。
 */
const props = defineProps({
  trace: {
    type: Object,
    required: true,
  },
})

const STATUS_LABELS = {
  planning: '规划中',
  running: '执行中',
  waiting_approval: '等待确认',
  recovering: '自动恢复',
  completed: '已完成',
  failed: '失败',
  canceled: '已取消',
}

const STEP_ICONS = {
  context: '◍',
  think: '◇',
  tool_call: '◆',
  tool_result: '◈',
  read: '▸',
  write: '✎',
  edit: '✎',
  approval: '✓',
  error: '!',
  final: '★',
}

const groups = computed(() => traceDisplayGroups(props.trace))
const summaryRows = computed(() => traceSummaryRows(props.trace))
const statusLabel = computed(() => STATUS_LABELS[props.trace?.status] || props.trace?.status || '执行中')
const openByDefault = computed(() => Boolean(props.trace?.streaming))

function stepIcon(step) {
  return STEP_ICONS[step?.type] || '◆'
}

function stepStatusLabel(step) {
  return {
    running: '执行中',
    success: '成功',
    failed: '失败',
    waiting: '等待',
  }[step?.status] || step?.status || '执行中'
}

function stepStatusClass(step) {
  return `trace-step-${step?.status || 'running'}`
}
</script>

<template>
  <section
    class="execution-trace"
    :class="`trace-${trace.status}`"
    role="region"
    aria-label="执行轨迹"
    :aria-busy="trace.streaming ? 'true' : 'false'"
  >
    <header class="trace-header">
      <div>
        <strong>执行轨迹</strong>
        <p>{{ trace.steps?.length || 0 }} 个真实步骤 · 每一步均可回溯原始事件</p>
      </div>
      <span class="trace-status" :class="`trace-status-${trace.status}`">{{ statusLabel }}</span>
    </header>

    <span class="trace-live" role="status" aria-live="polite">
      {{ statusLabel }}，{{ trace.steps?.length || 0 }} 个步骤
    </span>

    <div v-if="!groups.length" class="trace-empty">
      正在等待第一个真实执行事件…
    </div>

    <details class="trace-body" :open="openByDefault">
      <summary aria-label="展开执行时间线">展开时间线</summary>
      <div class="trace-groups">
        <section v-for="group in groups" :key="group.label" class="trace-group">
          <h4>{{ group.label }}</h4>
          <ol class="trace-step-list">
            <li
              v-for="step in group.steps"
              :key="step.step_id"
              :class="stepStatusClass(step)"
              :data-step-id="step.step_id"
            >
              <div class="trace-step-main">
                <span class="trace-icon" aria-hidden="true">{{ stepIcon(step) }}</span>
                <div>
                  <strong>{{ step.title }}</strong>
                  <small>{{ step.tool_name || step.type }}</small>
                  <p>{{ step.summary }}</p>
                </div>
              </div>
              <div class="trace-step-meta">
                <span>{{ stepStatusLabel(step) }}</span>
                <span>{{ formatTraceDuration(step) }}</span>
              </div>
              <details class="trace-detail">
                <summary :aria-label="`展开 ${step.title} 详情`">详情</summary>
                <pre>{{ traceDetailText(step) }}</pre>
              </details>
            </li>
          </ol>
        </section>
      </div>
    </details>

    <dl class="trace-summary">
      <template v-for="row in summaryRows" :key="row[0]">
        <dt>{{ row[0] }}</dt>
        <dd>{{ row[1] }}</dd>
      </template>
    </dl>
  </section>
</template>

<style scoped>
.execution-trace {
  margin-top: 10px;
  position: relative;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: color-mix(in srgb, var(--el-fill-color-extra-light) 72%, transparent);
  overflow: hidden;
}

.trace-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.trace-header p {
  margin: 2px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.trace-live {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}

.trace-status {
  flex: 0 0 auto;
  padding: 3px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  background: var(--el-color-info-light-9);
  color: var(--el-text-color-secondary);
}

.trace-status-running,
.trace-status-recovering {
  background: var(--el-color-warning-light-9);
  color: var(--el-color-warning-dark-2);
}

.trace-status-waiting_approval {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}

.trace-status-completed {
  background: var(--el-color-success-light-9);
  color: var(--el-color-success);
}

.trace-status-failed {
  background: var(--el-color-danger-light-9);
  color: var(--el-color-danger);
}

.trace-empty {
  padding: 14px 12px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.trace-body summary {
  padding: 8px 12px;
  cursor: pointer;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.trace-body summary:focus-visible,
.trace-detail summary:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
  border-radius: 4px;
}

.trace-groups {
  padding: 0 10px 8px;
}

.trace-group + .trace-group {
  margin-top: 8px;
}

.trace-group h4 {
  margin: 6px 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: 600;
}

.trace-step-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.trace-step-list li {
  padding: 7px 8px;
  border-left: 2px solid var(--el-border-color);
  border-radius: 0 6px 6px 0;
  background: var(--el-bg-color);
  margin: 6px 0;
}

.trace-step-success {
  border-left-color: var(--el-color-success);
}

.trace-step-running {
  border-left-color: var(--el-color-warning);
}

.trace-step-waiting {
  border-left-color: var(--el-color-primary);
}

.trace-step-failed {
  border-left-color: var(--el-color-danger);
}

.trace-step-main {
  display: flex;
  gap: 8px;
  min-width: 0;
}

.trace-step-main > div:last-child {
  min-width: 0;
  flex: 1;
}

.trace-icon {
  width: 20px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--el-fill-color);
  color: var(--el-text-color-secondary);
  font-size: 11px;
  flex: 0 0 auto;
}

.trace-step-main strong {
  display: block;
  font-size: 13px;
  line-height: 1.35;
}

.trace-step-main small {
  display: block;
  color: var(--el-text-color-secondary);
  font-size: 11px;
}

.trace-step-main p {
  margin: 3px 0 0;
  color: var(--el-text-color-regular);
  font-size: 12px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.trace-step-meta {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 5px;
  color: var(--el-text-color-secondary);
  font-size: 11px;
}

.trace-detail summary {
  margin-top: 4px;
  cursor: pointer;
  color: var(--el-color-primary);
  font-size: 11px;
}

.trace-detail pre {
  max-height: 220px;
  overflow: auto;
  margin: 5px 0 0;
  padding: 7px;
  border-radius: 5px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-regular);
  font-size: 11px;
  line-height: 1.45;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.trace-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px 8px;
  margin: 0;
  padding: 9px 12px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.trace-summary dt {
  color: var(--el-text-color-secondary);
  font-size: 11px;
}

.trace-summary dd {
  margin: 0;
  color: var(--el-text-color-primary);
  font-size: 12px;
  font-weight: 600;
}

@media (max-width: 520px) {
  .trace-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .trace-step-meta {
    justify-content: flex-start;
  }

  .trace-summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
