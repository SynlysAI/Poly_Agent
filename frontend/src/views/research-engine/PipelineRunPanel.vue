<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { VideoPlay } from '@element-plus/icons-vue'

import {
  createExecutionDecision,
  createManualWorkflow,
  getActiveExecutionDecision,
  getAlgorithmRun,
  getApiErrorMessage,
  getWorkflowRun,
  startWorkflowRun,
} from '../../api/polyAgentApi'

const emit = defineEmits(['run-completed'])

const props = defineProps({
  pipelineSteps: { type: Array, default: () => [] },
  existingWorkflow: { type: Object, default: null },
  problemSpecId: { type: String, default: '' },
  campaignId: { type: String, default: '' },
})

const running = ref(false)
// 每个步骤的输入表单数据: { [step_id]: { field_key: value } }
const stepFormInputs = reactive({})
const lastWorkflowRun = ref(null)
const stepResults = ref([])  // 每个步骤的 AlgorithmRun 结果
// 从已选算法中获取完整算法信息（pipelineSteps 只含 algorithm_id/name/step_id）
// 需要通过 API 获取完整的 input_schema。
const algorithmDetails = ref({})

const displayPipelineSteps = computed(() => {
  if (props.pipelineSteps?.length) return props.pipelineSteps
  return (props.existingWorkflow?.steps || []).map((step, idx) => ({
    step_id: step.step_id || `step_${idx + 1}`,
    algorithm_id: step.algorithm_id,
    name: step.name || step.algorithm_name || step.algorithm_id,
    input_bindings: step.input_bindings || {},
    depends_on: step.depends_on || [],
  }))
})

const workflowTitle = computed(() => {
  if (props.existingWorkflow?.workflow_id) {
    return props.existingWorkflow.name || props.existingWorkflow.workflow_id
  }
  return `人工串联 ${displayPipelineSteps.value.map(s => s.name).join(' → ')}`
})

function literalInputsFromBindings(bindings) {
  return Object.fromEntries(
    Object.entries(bindings || {}).map(([key, binding]) => [
      key,
      binding?.source === 'literal' ? binding.value : binding?.value,
    ]),
  )
}

function initializeStepInputs(steps) {
  if (steps && steps.length > 0) {
    for (const step of steps) {
      if (!stepFormInputs[step.step_id]) {
        stepFormInputs[step.step_id] = {}
      }
      const algo = getAlgorithmInfo(step.algorithm_id)
      if (algo) {
        const savedInputs = literalInputsFromBindings(step.input_bindings)
        const inputs = { ...savedInputs }
        const fields = algo.input_schema?.fields || {}
        const fieldOptions = algo.input_schema?.field_options || {}
        const fieldDefaults = algo.input_schema?.field_defaults || {}
        const uiHints = algo.input_schema?.ui_hints || {}
        for (const key of Object.keys(fields)) {
          if (uiHints[key]?.widget === 'hidden') continue
          const fieldType = fields[key] || 'string'
          if (Object.prototype.hasOwnProperty.call(savedInputs, key)) {
            inputs[key] = savedInputs[key]
          } else if (Object.prototype.hasOwnProperty.call(fieldDefaults, key)) {
            inputs[key] = fieldDefaults[key]
          } else if (fieldOptions[key]?.length > 0) {
            inputs[key] = isListFieldWithSchema(algo, key) ? [] : fieldOptions[key][0]
          } else if (fieldType.includes('int') || fieldType.includes('float') || fieldType.includes('number')) {
            inputs[key] = 0
          } else if (fieldType.includes('list[') || fieldType.includes('list [')) {
            inputs[key] = []
          } else if (fieldType.includes('dict') || fieldType.includes('object')) {
            inputs[key] = {}
          } else {
            inputs[key] = ''
          }
        }
        stepFormInputs[step.step_id] = inputs
      }
    }
  }
}

// 初始化每个步骤的表单
watch(displayPipelineSteps, (steps) => {
  initializeStepInputs(steps)
}, { immediate: true, deep: true })

watch(displayPipelineSteps, async (steps) => {
  if (steps && steps.length > 0) {
    for (const step of steps) {
      if (!algorithmDetails.value[step.algorithm_id]) {
        try {
          const { getAlgorithm } = await import('../../api/polyAgentApi')
          const detail = await getAlgorithm(step.algorithm_id)
          algorithmDetails.value[step.algorithm_id] = detail
          initializeStepInputs(steps)
        } catch {
          // 如果 API 获取失败，使用 steps 中的基本信息
          algorithmDetails.value[step.algorithm_id] = step
          initializeStepInputs(steps)
        }
      }
    }
  }
}, { immediate: true })

function getAlgorithmInfo(algorithmId) {
  return algorithmDetails.value[algorithmId] || null
}

// ── 表单辅助函数 ──
function hasFieldOptions(algo, key) {
  return (algo?.input_schema?.field_options?.[key]?.length || 0) > 0
}

function fieldOptions(algo, key) {
  return algo?.input_schema?.field_options?.[key] || []
}

function isListField(algo, key) {
  return isListFieldWithSchema(algo, key)
}

function isListFieldWithSchema(algo, key) {
  const desc = algo?.input_schema?.fields?.[key] || ''
  const widget = algo?.input_schema?.ui_hints?.[key]?.widget
  return widget === 'multiselect' || desc.includes('list[') || desc.includes('list [')
}

function schemaFields(algo) {
  const fields = algo?.input_schema?.fields || {}
  const uiHints = algo?.input_schema?.ui_hints || {}
  return Object.keys(fields).filter(key => uiHints[key]?.widget !== 'hidden')
}

function isJsonField(algo, key) {
  const desc = algo?.input_schema?.fields?.[key] || ''
  const widget = algo?.input_schema?.ui_hints?.[key]?.widget
  return widget === 'json' || desc.includes('dict') || desc.includes('object')
}

function jsonValue(stepId, key) {
  const value = stepFormInputs[stepId]?.[key]
  if (typeof value === 'string') return value
  return JSON.stringify(value ?? {}, null, 2)
}

function setJsonValue(stepId, key, value) {
  try {
    stepFormInputs[stepId][key] = value.trim() ? JSON.parse(value) : {}
  } catch {
    stepFormInputs[stepId][key] = value
  }
}

function isIntField(algo, key) {
  const desc = algo?.input_schema?.fields?.[key] || ''
  return desc.includes('int') && !desc.includes('float')
}

function isFloatField(algo, key) {
  const desc = algo?.input_schema?.fields?.[key] || ''
  return desc.includes('float') || desc.includes('number')
}

// ── 运行流水线 ──
async function handleRunPipeline() {
  const steps = displayPipelineSteps.value
  if (!steps || steps.length === 0) return
  if (!props.existingWorkflow?.workflow_id && !props.problemSpecId) {
    ElMessage.warning('请先选择或创建 ProblemSpec，再运行 Workflow')
    return
  }
  running.value = true
  try {
    let workflow = props.existingWorkflow
    if (!workflow?.workflow_id) {
      const decision = await ensureExecutionDecision(
        props.problemSpecId,
        'manual_workbench',
        `人工流水线运行 ${steps.map(s => s.name).join(' → ')}`,
      )
      workflow = await createManualWorkflow({
        problem_spec_id: props.problemSpecId,
        execution_decision_id: decision.decision_id,
        name: workflowTitle.value,
        description: '由多算法流水线创建的串联 Workflow',
        steps: steps.map((step, idx) => ({
          step_id: step.step_id,
          algorithm_id: step.algorithm_id,
          input_bindings: buildLiteralBindings(stepFormInputs[step.step_id] || {}),
          depends_on: idx > 0 ? [`step_${idx}`] : [],
        })),
      })
    }
    const workflowRun = await startWorkflowRun(workflow.workflow_id)
    lastWorkflowRun.value = workflowRun

    // 获取每个步骤的 AlgorithmRun 结果
    const results = []
    if (workflowRun.step_runs) {
      for (const stepRun of workflowRun.step_runs) {
        if (stepRun.algorithm_run_id) {
          try {
            const runData = await getAlgorithmRun(stepRun.algorithm_run_id)
            results.push(runData)
          } catch {
            results.push({ run_id: stepRun.algorithm_run_id, status: stepRun.status })
          }
        }
      }
    }
    stepResults.value = results
    ElMessage.success(`WorkflowRun 已完成: ${workflowRun.workflow_run_id}`)
    emit('run-completed', { workflowRun, stepResults: results, workflow })
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
    if (error.status !== 409) throw error
    const active = await getActiveExecutionDecision(problemSpecId)
    if (active?.mode === mode) return active
    throw error
  }
}

function buildLiteralBindings(inputs) {
  return Object.fromEntries(
    Object.entries(inputs || {}).map(([key, value]) => [
      key,
      { source: 'literal', value },
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
  <div class="pipeline-run-panel">
    <div v-if="!displayPipelineSteps || displayPipelineSteps.length === 0" class="empty-hint">
      请先从算法清单中选择至少一个算法
    </div>

    <template v-else>
      <!-- 流水线概览 -->
      <div class="pipeline-overview">
        <span class="pipeline-title">
          {{ existingWorkflow?.workflow_id ? `已保存 Workflow · ${existingWorkflow.workflow_id}` : '流水线串联' }}
        </span>
        <strong v-if="existingWorkflow?.workflow_id" class="workflow-name">{{ workflowTitle }}</strong>
        <div class="pipeline-chain">
          <template v-for="(step, idx) in displayPipelineSteps" :key="step.step_id">
            <div class="chain-node">
              <span class="chain-index">{{ idx + 1 }}</span>
              <span class="chain-name">{{ step.name }}</span>
            </div>
            <span v-if="idx < displayPipelineSteps.length - 1" class="chain-arrow">→</span>
          </template>
        </div>
      </div>

      <!-- 每个步骤的输入表单 -->
      <div class="step-forms">
        <div
          v-for="(step, idx) in displayPipelineSteps"
          :key="step.step_id"
          class="step-form-card"
        >
          <div class="step-form-header">
            <span class="step-number">步骤 {{ idx + 1 }}</span>
            <strong>{{ step.name }}</strong>
            <el-tag size="small">{{ step.algorithm_id }}</el-tag>
          </div>

          <el-form
            v-if="schemaFields(getAlgorithmInfo(step.algorithm_id)).length"
            label-position="top"
            class="step-form"
          >
            <el-form-item
              v-for="key in schemaFields(getAlgorithmInfo(step.algorithm_id))"
              :key="`${step.step_id}-${key}`"
              :label="`${key}${(getAlgorithmInfo(step.algorithm_id)?.input_schema?.required || []).includes(key) ? ' *' : ''}`"
            >
              <!-- 多选下拉：字段类型为 list -->
              <el-select
                v-if="hasFieldOptions(getAlgorithmInfo(step.algorithm_id), key) && isListField(getAlgorithmInfo(step.algorithm_id), key)"
                v-model="stepFormInputs[step.step_id][key]"
                multiple
                style="width:100%"
                :placeholder="`选择 ${key}`"
              >
                <el-option
                  v-for="opt in fieldOptions(getAlgorithmInfo(step.algorithm_id), key)"
                  :key="opt"
                  :label="opt"
                  :value="opt"
                />
              </el-select>
              <!-- 单选下拉 -->
              <el-select
                v-else-if="hasFieldOptions(getAlgorithmInfo(step.algorithm_id), key)"
                v-model="stepFormInputs[step.step_id][key]"
                style="width:100%"
                :placeholder="`选择 ${key}`"
              >
                <el-option
                  v-for="opt in fieldOptions(getAlgorithmInfo(step.algorithm_id), key)"
                  :key="opt"
                  :label="opt || '(留空)'"
                  :value="opt"
                />
              </el-select>
              <!-- 整数 -->
              <el-input-number
                v-else-if="isIntField(getAlgorithmInfo(step.algorithm_id), key)"
                v-model="stepFormInputs[step.step_id][key]"
                :step="1"
                style="width:100%"
              />
              <!-- 浮点数 -->
              <el-input-number
                v-else-if="isFloatField(getAlgorithmInfo(step.algorithm_id), key)"
                v-model="stepFormInputs[step.step_id][key]"
                :step="0.1"
                style="width:100%"
              />
              <!-- JSON -->
              <el-input
                v-else-if="isJsonField(getAlgorithmInfo(step.algorithm_id), key)"
                :model-value="jsonValue(step.step_id, key)"
                type="textarea"
                :rows="4"
                :placeholder="`输入 JSON: ${key}`"
                @update:model-value="setJsonValue(step.step_id, key, $event)"
              />
              <!-- 文本 -->
              <el-input
                v-else
                v-model="stepFormInputs[step.step_id][key]"
                :placeholder="`输入 ${key}`"
              />
            </el-form-item>
          </el-form>
          <div v-else class="no-input-hint">
            该算法无需额外输入参数
          </div>
        </div>
      </div>

      <!-- 运行按钮 -->
      <el-button
        type="primary"
        :icon="VideoPlay"
        :loading="running"
        :disabled="!displayPipelineSteps || displayPipelineSteps.length === 0"
        @click="handleRunPipeline"
        style="margin-top:16px;width:100%"
      >
        {{ existingWorkflow?.workflow_id ? '运行已保存 Workflow' : `运行流水线 (${displayPipelineSteps.length} 步骤)` }}
      </el-button>

      <!-- WorkflowRun 结果 -->
      <div v-if="lastWorkflowRun" class="run-result">
        <div class="result-header">
          <span>WorkflowRun</span>
          <el-tag size="small" :type="statusTag(lastWorkflowRun.status)">{{ statusLabel(lastWorkflowRun.status) }}</el-tag>
        </div>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="WorkflowRun ID">{{ lastWorkflowRun.workflow_run_id }}</el-descriptions-item>
          <el-descriptions-item label="Workflow ID">{{ lastWorkflowRun.workflow_id }}</el-descriptions-item>
          <el-descriptions-item label="总步骤数">{{ lastWorkflowRun.step_runs?.length || '-' }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatDate(lastWorkflowRun.created_at) }}</el-descriptions-item>
        </el-descriptions>
      </div>

      <!-- 各步骤运行结果 -->
      <div v-if="stepResults.length > 0" class="step-results">
        <h4>步骤运行结果</h4>
        <div v-for="(result, idx) in stepResults" :key="idx" class="step-result-item">
          <div class="step-result-header">
            <span>{{ displayPipelineSteps[idx]?.name || `步骤 ${idx + 1}` }}</span>
            <el-tag size="small" :type="statusTag(result.status)">{{ statusLabel(result.status) }}</el-tag>
          </div>
          <el-descriptions v-if="result.run_id" :column="2" border size="small">
            <el-descriptions-item label="Run ID">{{ result.run_id }}</el-descriptions-item>
            <el-descriptions-item label="状态">{{ statusLabel(result.status) }}</el-descriptions-item>
            <el-descriptions-item label="创建时间" :span="2">{{ formatDate(result.created_at) }}</el-descriptions-item>
          </el-descriptions>
          <details v-if="result.input_snapshot" style="margin-top:8px">
            <summary>输入快照</summary>
            <pre class="json-block">{{ JSON.stringify(result.input_snapshot, null, 2) }}</pre>
          </details>
          <details v-if="result.output_summary && Object.keys(result.output_summary).length" style="margin-top:4px">
            <summary>输出摘要</summary>
            <pre class="json-block">{{ JSON.stringify(result.output_summary, null, 2) }}</pre>
          </details>
          <details v-if="result.error" style="margin-top:4px">
            <summary>错误信息</summary>
            <pre class="json-block error-block">{{ JSON.stringify(result.error, null, 2) }}</pre>
          </details>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.pipeline-run-panel {
  min-height: 180px;
}

.empty-hint {
  color: var(--app-ink-muted);
  font-size: 14px;
  text-align: center;
  padding: 32px 0;
}

.pipeline-overview {
  margin-bottom: 16px;
  padding: 12px 14px;
  background: #f8fbff;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
}

.pipeline-title {
  font-size: 13px;
  color: var(--app-ink-muted);
  display: block;
  margin-bottom: 8px;
}

.workflow-name {
  display: block;
  margin-bottom: 8px;
  color: var(--app-ink);
  font-size: 14px;
}

.pipeline-chain {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.chain-node {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: var(--app-radius-sm);
}

.chain-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #3b82f6;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
}

.chain-name {
  font-size: 13px;
  color: var(--app-ink);
}

.chain-arrow {
  color: var(--app-ink-muted);
  font-size: 16px;
  font-weight: 600;
}

.step-forms {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 8px;
}

.step-form-card {
  padding: 14px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #fff;
}

.step-form-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--app-border-soft);
}

.step-number {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  height: 24px;
  padding: 0 8px;
  background: #3b82f6;
  color: #fff;
  border-radius: var(--app-radius-sm);
  font-size: 12px;
  font-weight: 600;
}

.step-form-header strong {
  font-size: 14px;
  color: var(--app-ink);
}

.step-form {
  margin-bottom: 0;
}

.no-input-hint {
  color: var(--app-ink-muted);
  font-size: 12px;
  text-align: center;
  padding: 8px 0;
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

.step-results {
  margin-top: 20px;
}

.step-results h4 {
  margin: 0 0 12px;
  font-size: 14px;
  color: var(--app-ink);
}

.step-result-item {
  padding: 14px;
  margin-bottom: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #f8fbff;
}

.step-result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  font-weight: 600;
  font-size: 13px;
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
