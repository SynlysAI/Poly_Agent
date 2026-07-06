<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { VideoPlay } from '@element-plus/icons-vue'

import {
  createAlgorithmRun,
  getAlgorithmRun,
  getApiErrorMessage,
  listAlgorithmRuns,
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
const recentRuns = ref([])
const showRecentRuns = ref(false)

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
  running.value = true
  try {
    const payload = {
      algorithm_id: props.selectedAlgorithm.algorithm_id,
      trigger_source: 'human',
      problem_spec_id: props.problemSpecId || undefined,
      campaign_id: props.campaignId || undefined,
      input_snapshot: { ...formInputs.value },
    }
    const data = await createAlgorithmRun(payload)
    lastRun.value = data
    ElMessage.success(`算法运行已创建: ${data.run_id}`)
    emit('run-completed', data)

    // 轮询状态
    await pollRunStatus(data.run_id)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    running.value = false
  }
}

async function pollRunStatus(runId) {
  let attempts = 0
  const maxAttempts = 30
  while (attempts < maxAttempts) {
    await new Promise(resolve => setTimeout(resolve, 2000))
    try {
      const data = await getAlgorithmRun(runId)
      lastRun.value = data
      if (['completed', 'failed', 'cancelled'].includes(data.status)) {
        emit('run-completed', data)
        return
      }
    } catch {
      // 忽略轮询错误
    }
    attempts++
  }
}

function statusTag(status) {
  const map = { queued: 'info', running: 'warning', completed: 'success', failed: 'danger', cancelled: 'info' }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = { queued: '排队中', running: '运行中', completed: '已完成', failed: '失败', cancelled: '已取消' }
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
        运行算法
      </el-button>

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
