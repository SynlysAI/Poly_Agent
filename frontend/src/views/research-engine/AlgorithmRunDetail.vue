<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import { getAlgorithmRun, getApiErrorMessage } from '../../api/polyAgentApi'
import AlgorithmResultView from '../vertical-prediction/AlgorithmResultView.vue'

const props = defineProps({
  runId: { type: String, required: true },
})

const loading = ref(false)
const run = ref(null)

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
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
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

watch(() => props.runId, loadRun)
onMounted(loadRun)
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
        />
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

.empty-hint {
  color: var(--app-ink-muted);
  font-size: 14px;
  text-align: center;
  padding: 32px 0;
}
</style>
