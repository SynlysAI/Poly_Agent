<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { VideoPlay } from '@element-plus/icons-vue'

import {
  createExecutionDecision,
  createManualWorkflow,
  getActiveExecutionDecision,
  getAlgorithmRun,
  getApiErrorMessage,
  startWorkflowRun,
} from '../../api/polyAgentApi'

const emit = defineEmits(['run-completed'])

const props = defineProps({
  selectedAlgorithm: { type: Object, default: null },
  problemSpecId: { type: String, default: '' },
  campaignId: { type: String, default: '' },
})

const running = ref(false)
const formInputs = ref({})
const lastRun = ref(null)
const lastWorkflowRun = ref(null)

watch(() => props.selectedAlgorithm, (algo) => {
  if (algo) {
    const inputs = {}
    const required = algo.input_schema?.required || []
    const fields = algo.input_schema?.fields || {}
    for (const key of required) {
      const fieldType = fields[key] || 'string'
      if (fieldType.includes('int') || fieldType.includes('float') || fieldType.includes('number')) {
        inputs[key] = 0
      } else {
        inputs[key] = ''
      }
    }
    formInputs.value = inputs
  }
}, { immediate: true })

async function handleRun() {
  if (!props.selectedAlgorithm) return
  if (!props.problemSpecId) {
    ElMessage.warning('请先选择或创建 ProblemSpec，再进入人工算法工作台')
    return
  }
  running.value = true
  try {
    const decision = await ensureExecutionDecision(
      props.problemSpecId,
      'manual_workbench',
      `人工算法工作台运行 ${props.selectedAlgorithm.algorithm_id}`,
    )
    const workflow = await createManualWorkflow({
      problem_spec_id: props.problemSpecId,
      execution_decision_id: decision.decision_id,
      name: `人工运行 ${props.selectedAlgorithm.name || props.selectedAlgorithm.algorithm_id}`,
      description: '由人工算法工作台创建的单节点 Workflow',
      steps: [
        {
          step_id: 'step_1',
          algorithm_id: props.selectedAlgorithm.algorithm_id,
          input_bindings: buildLiteralBindings(formInputs.value),
        },
      ],
    })
    const workflowRun = await startWorkflowRun(workflow.workflow_id)
    lastWorkflowRun.value = workflowRun

    const firstStep = workflowRun.step_runs?.[0]
    if (!firstStep?.algorithm_run_id) {
      ElMessage.success(`WorkflowRun 已创建: ${workflowRun.workflow_run_id}`)
      return
    }

    const data = await getAlgorithmRun(firstStep.algorithm_run_id)
    lastRun.value = data
    ElMessage.success(`WorkflowRun 已完成，生成 AlgorithmRun: ${data.run_id}`)
    emit('run-completed', data)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    running.value = false
  }
}

async function ensureExecutionDecision(problemSpecId, mode, reason) {
  try {
    return await createExecutionDecision(problemSpecId, { mode, reason })
  } catch (error) {
    if (error.status !== 409) {
      throw error
    }
    const active = await getActiveExecutionDecision(problemSpecId)
    if (active?.mode === mode) {
      return active
    }
    throw error
  }
}

function buildLiteralBindings(inputs) {
  return Object.fromEntries(
    Object.entries(inputs || {}).map(([key, value]) => [
      key,
      {
        source: 'literal',
        value,
      },
    ]),
  )
}

function statusTag(status) {
  const map = { draft: 'info', queued: 'info', running: 'warning', completed: 'success', failed: 'danger', cancelled: 'info' }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = { draft: '草稿', queued: '排队中', running: '运行中', completed: '已完成', failed: '失败', cancelled: '已取消' }
  return map[status] || status
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}
</script>

<template>
  <div class="algorithm-run-panel">
    <div v-if="!selectedAlgorithm" class="empty-hint">
      请先从算法清单中选择一个算法
    </div>

    <template v-else>
      <!-- 算法信息 -->
      <div class="selected-algo-info">
        <strong>{{ selectedAlgorithm.name }}</strong>
        <el-tag size="small">{{ selectedAlgorithm.algorithm_id }}</el-tag>
      </div>

      <!-- 输入表单 -->
      <el-form v-if="selectedAlgorithm.input_schema?.required?.length" label-position="top" class="run-form">
        <el-form-item
          v-for="key in (selectedAlgorithm.input_schema.required || [])"
          :key="key"
          :label="key"
        >
          <el-input-number
            v-if="(selectedAlgorithm.input_schema.fields?.[key] || '').includes('int')"
            v-model="formInputs[key]"
            :step="1"
            style="width:100%"
          />
          <el-input-number
            v-else-if="(selectedAlgorithm.input_schema.fields?.[key] || '').includes('float') || (selectedAlgorithm.input_schema.fields?.[key] || '').includes('number')"
            v-model="formInputs[key]"
            :step="0.1"
            style="width:100%"
          />
          <el-input
            v-else
            v-model="formInputs[key]"
            :placeholder="`输入 ${key}`"
          />
        </el-form-item>
      </el-form>
      <div v-else class="empty-hint" style="font-size:12px">
        该算法无需额外输入参数
      </div>

      <!-- 运行按钮 -->
      <el-button
        type="primary"
        :icon="VideoPlay"
        :loading="running"
        :disabled="!selectedAlgorithm"
        @click="handleRun"
        style="margin-top:12px;width:100%"
      >
        创建并运行 Workflow
      </el-button>

      <div v-if="lastWorkflowRun" class="run-result">
        <div class="result-header">
          <span>WorkflowRun</span>
          <el-tag size="small" :type="statusTag(lastWorkflowRun.status)">{{ statusLabel(lastWorkflowRun.status) }}</el-tag>
        </div>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="WorkflowRun ID">{{ lastWorkflowRun.workflow_run_id }}</el-descriptions-item>
          <el-descriptions-item label="Workflow ID">{{ lastWorkflowRun.workflow_id }}</el-descriptions-item>
          <el-descriptions-item label="ExecutionDecision">{{ lastWorkflowRun.execution_decision_id }}</el-descriptions-item>
        </el-descriptions>
      </div>

      <!-- 最近运行结果 -->
      <div v-if="lastRun" class="run-result">
        <div class="result-header">
          <span>运行结果</span>
          <el-tag size="small" :type="statusTag(lastRun.status)">{{ statusLabel(lastRun.status) }}</el-tag>
        </div>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="Run ID">{{ lastRun.run_id }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ statusLabel(lastRun.status) }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatDate(lastRun.created_at) }}</el-descriptions-item>
          <el-descriptions-item v-if="lastRun.finished_at" label="完成时间">{{ formatDate(lastRun.finished_at) }}</el-descriptions-item>
        </el-descriptions>

        <!-- 输入快照 -->
        <details style="margin-top:10px">
          <summary>输入快照</summary>
          <pre class="json-block">{{ JSON.stringify(lastRun.input_snapshot, null, 2) }}</pre>
        </details>

        <!-- 输出摘要 -->
        <details v-if="lastRun.output_summary && Object.keys(lastRun.output_summary).length" style="margin-top:8px">
          <summary>输出摘要</summary>
          <pre class="json-block">{{ JSON.stringify(lastRun.output_summary, null, 2) }}</pre>
        </details>

        <!-- 错误 -->
        <details v-if="lastRun.error" style="margin-top:8px">
          <summary>错误信息</summary>
          <pre class="json-block error-block">{{ JSON.stringify(lastRun.error, null, 2) }}</pre>
        </details>
      </div>
    </template>
  </div>
</template>

<style scoped>
.algorithm-run-panel {
  min-height: 180px;
}

.empty-hint {
  color: var(--app-ink-muted);
  font-size: 14px;
  text-align: center;
  padding: 32px 0;
}

.selected-algo-info {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--app-border-soft);
}

.selected-algo-info strong {
  font-size: 16px;
  color: var(--app-ink);
}

.run-form {
  margin-bottom: 8px;
}

.run-result {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--app-border-soft);
}

.result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  font-weight: 600;
  font-size: 14px;
}

.json-block {
  margin: 0;
  padding: 10px;
  background: #f8fbff;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  font-family: var(--app-mono-font);
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow: auto;
}

.error-block {
  color: #b91c1c;
  background: #fef2f2;
  border-color: #fecaca;
}

summary {
  cursor: pointer;
  font-size: 13px;
  color: var(--app-primary-active);
  font-weight: 500;
  margin-bottom: 6px;
}
</style>
