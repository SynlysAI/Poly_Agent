<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import { getAlgorithmRun, getAlgorithmRunTraceability, getApiErrorMessage } from '../../api/polyAgentApi'
import { formatApiDateTime } from '../../utils/datetime'
import AlgorithmResultView from '../vertical-prediction/AlgorithmResultView.vue'

const props = defineProps({
  runId: { type: String, required: true },
  showTraceability: { type: Boolean, default: false },
})

const loading = ref(false)
const traceabilityLoading = ref(false)
const run = ref(null)
const traceability = ref(null)

const linkedComputation = computed(() => traceability.value?.linked_computation || run.value?.linked_computation || null)
const auditEvents = computed(() => traceability.value?.audit_events || [])
const hasArtifactRefs = computed(() => Boolean((run.value?.artifact_refs || []).length))
const hasTraceabilitySummary = computed(() =>
  Boolean(linkedComputation.value || hasArtifactRefs.value || auditEvents.value.length),
)

function statusTag(status) {
  const map = { queued: 'info', running: 'warning', completed: 'success', failed: 'danger', cancelled: 'info' }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = { queued: '排队中', running: '运行中', completed: '已完成', failed: '失败', cancelled: '已取消' }
  return map[status] || status
}

function triggerLabel(source) {
  const map = { human_workflow: '人工 Workflow', autoresearch: 'AutoResearch', system: '系统触发' }
  return map[source] || source
}

function formatDate(value) {
  return formatApiDateTime(value)
}

async function loadRun() {
  if (!props.runId) return
  loading.value = true
  try {
    run.value = await getAlgorithmRun(props.runId)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function loadTraceability() {
  if (!props.showTraceability || !props.runId) {
    traceability.value = null
    return
  }
  traceabilityLoading.value = true
  try {
    traceability.value = await getAlgorithmRunTraceability(props.runId)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    traceabilityLoading.value = false
  }
}

function shortJson(value) {
  if (!value || (typeof value === 'object' && Object.keys(value).length === 0)) return '-'
  return JSON.stringify(value, null, 2)
}

watch(() => props.runId, () => {
  loadRun()
  loadTraceability()
})

watch(() => props.showTraceability, loadTraceability)

onMounted(() => {
  loadRun()
  loadTraceability()
})
</script>

<template>
  <div class="algorithm-run-detail" v-loading="loading">
    <template v-if="run">
      <div class="detail-header">
        <div>
          <h3>算法运行详情</h3>
          <span class="run-id-text">{{ run.run_id }}</span>
        </div>
        <el-tag size="large" :type="statusTag(run.status)">{{ statusLabel(run.status) }}</el-tag>
        <el-button :icon="Refresh" :loading="loading" @click="loadRun">刷新</el-button>
      </div>

      <el-descriptions :column="2" border size="small" style="margin-top:14px">
        <el-descriptions-item label="Run ID">{{ run.run_id }}</el-descriptions-item>
        <el-descriptions-item label="算法 ID">{{ run.algorithm_id }}</el-descriptions-item>
        <el-descriptions-item label="触发来源">
          <el-tag size="small">{{ triggerLabel(run.trigger_source) }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag size="small" :type="statusTag(run.status)">{{ statusLabel(run.status) }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="ProblemSpec">{{ run.problem_spec_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Campaign">{{ run.campaign_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="ResearchRun">{{ run.research_run_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="StageRun">{{ run.stage_run_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="WorkflowRun">{{ run.workflow_run_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="WorkflowStepRun">{{ run.workflow_step_run_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="关联计算任务">{{ run.linked_computation_run_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="关联 Suggestion">{{ run.linked_suggestion_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="创建者">{{ run.created_by }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatDate(run.created_at) }}</el-descriptions-item>
        <el-descriptions-item v-if="run.started_at" label="开始时间">{{ formatDate(run.started_at) }}</el-descriptions-item>
        <el-descriptions-item v-if="run.finished_at" label="完成时间">{{ formatDate(run.finished_at) }}</el-descriptions-item>
      </el-descriptions>

      <section class="detail-section">
        <AlgorithmResultView
          :output-summary="run.output_summary"
          :input-snapshot="run.input_snapshot"
          :artifact-refs="run.artifact_refs"
          :status="run.status"
          :error="run.error"
          :run-id="run.run_id"
        />
      </section>

      <section v-if="showTraceability" v-loading="traceabilityLoading" class="trace-detail-section">
        <div class="trace-detail-header">
          <h4>运行追溯</h4>
          <span>{{ hasTraceabilitySummary ? '仅展示本次运行产生的关联记录' : '本次运行无额外关联记录' }}</span>
        </div>

        <div v-if="hasTraceabilitySummary" class="trace-summary-grid">
          <article v-if="linkedComputation" class="trace-summary-item">
            <strong>关联计算</strong>
            <span>{{ linkedComputation.workflow_type || linkedComputation.engine || 'computation' }}</span>
            <code>{{ linkedComputation.run_id }}</code>
          </article>
          <article v-if="hasArtifactRefs" class="trace-summary-item">
            <strong>产物</strong>
            <span>{{ run.artifact_refs.length }} 个运行产物</span>
            <code>{{ run.artifact_refs[0]?.name || run.artifact_refs[0]?.filename || run.artifact_refs[0]?.type }}</code>
          </article>
          <article v-if="auditEvents.length" class="trace-summary-item">
            <strong>过程事件</strong>
            <span>{{ auditEvents.length }} 条记录</span>
            <code>{{ auditEvents[0]?.event_type }}</code>
          </article>
        </div>

        <el-collapse class="trace-collapse">
          <el-collapse-item title="展开完整追溯明细" name="algorithm-trace">
            <div class="trace-json-block">
              <h5>输入快照</h5>
              <pre>{{ shortJson(run.input_snapshot) }}</pre>
            </div>
            <div class="trace-json-block">
              <h5>输出摘要</h5>
              <pre>{{ shortJson(run.output_summary) }}</pre>
            </div>
            <div v-if="auditEvents.length" class="trace-json-block">
              <h5>审计事件</h5>
              <pre>{{ shortJson(auditEvents) }}</pre>
            </div>
          </el-collapse-item>
        </el-collapse>
      </section>
    </template>

    <div v-else-if="!loading" class="empty-hint">
      未找到运行记录
    </div>
  </div>
</template>

<style scoped>
.algorithm-run-detail {
  min-height: 200px;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 16px;
}

.detail-header h3 {
  margin: 0;
  font-size: 18px;
}

.run-id-text {
  color: var(--app-ink-muted);
  font-family: var(--app-mono-font);
  font-size: 13px;
}

.detail-section {
  margin-top: 16px;
}

.trace-detail-section {
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid var(--app-border-soft);
}

.trace-detail-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.trace-detail-header h4 {
  margin: 0;
  color: var(--app-ink);
  font-size: 15px;
}

.trace-detail-header span {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.trace-summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.trace-summary-item {
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #fff;
}

.trace-summary-item strong,
.trace-summary-item span,
.trace-summary-item code {
  display: block;
}

.trace-summary-item strong {
  color: var(--app-ink);
  font-size: 13px;
}

.trace-summary-item span {
  margin-top: 4px;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.trace-summary-item code {
  overflow: hidden;
  margin-top: 6px;
  color: var(--app-ink-body);
  font-family: var(--app-mono-font);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-collapse {
  margin-top: 12px;
}

.trace-json-block + .trace-json-block {
  margin-top: 12px;
}

.trace-json-block h5 {
  margin: 0 0 6px;
  color: var(--app-ink);
  font-size: 13px;
}

.trace-json-block pre {
  overflow-x: auto;
  margin: 0;
  padding: 10px;
  border-radius: var(--app-radius-sm);
  background: #f8fafc;
  color: var(--app-ink-body);
  font: 12px/1.55 var(--app-mono-font);
  white-space: pre-wrap;
  word-break: break-word;
}

.empty-hint {
  color: var(--app-ink-muted);
  font-size: 14px;
  text-align: center;
  padding: 32px 0;
}

@media (max-width: 720px) {
  .detail-header,
  .trace-detail-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .trace-summary-grid {
    grid-template-columns: 1fr;
  }
}
</style>
