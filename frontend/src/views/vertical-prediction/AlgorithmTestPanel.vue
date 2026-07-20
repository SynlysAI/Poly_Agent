<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, VideoPlay } from '@element-plus/icons-vue'

import {
  createAlgorithmRun,
  getApiErrorMessage,
  listAlgorithms,
  listAlgorithmVersions,
} from '../../api/polyAgentApi'
import AlgorithmResultView from './AlgorithmResultView.vue'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
  algorithmId: { type: String, default: '' },
  showToolbar: { type: Boolean, default: true },
})
const emit = defineEmits(['run-created'])

const loading = ref(false)
const running = ref(false)
const algorithms = ref([])
const versions = ref([])
const algorithmId = ref('')
const versionId = ref('')
const inputs = ref({})
const jsonDrafts = ref({})
const lastRun = ref(null)

const selectedAlgorithm = computed(() => algorithms.value.find((item) => item.algorithm_id === algorithmId.value) || null)
const selectedVersion = computed(() => versions.value.find((item) => item.version_id === versionId.value) || null)
const schemaFields = computed(() => Object.keys(selectedVersion.value?.input_schema?.fields || {}))
const selectedAttributions = computed(() => algorithmAttributions(selectedAlgorithm.value))

watch(() => props.refreshKey, loadAlgorithms)
watch(() => props.algorithmId, loadAlgorithms)
watch(algorithmId, loadVersions)
watch(versionId, resetInputs)

async function loadAlgorithms() {
  loading.value = true
  try {
    const data = await listAlgorithms({ algorithm_family: 'vertical_prediction', page: 1, page_size: 100 })
    algorithms.value = (data.items || []).filter((item) => item.source === 'uploaded_package')
    const preferredId = props.algorithmId || algorithmId.value
    if (!algorithms.value.some((item) => item.algorithm_id === preferredId)) {
      algorithmId.value = algorithms.value[0]?.algorithm_id || ''
    } else if (algorithmId.value !== preferredId) {
      algorithmId.value = preferredId
    } else {
      await loadVersions()
    }
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function loadVersions() {
  if (!algorithmId.value) {
    versions.value = []
    versionId.value = ''
    return
  }
  loading.value = true
  try {
    const data = await listAlgorithmVersions(algorithmId.value, { page: 1, page_size: 100 })
    versions.value = (data.items || []).filter((item) => ['active', 'deployed_staging'].includes(item.status))
    versionId.value = versions.value.find((item) => item.status === 'active')?.version_id || versions.value[0]?.version_id || ''
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

function resetInputs() {
  const schema = selectedVersion.value?.input_schema || {}
  const nextInputs = {}
  const nextDrafts = {}
  for (const [key, type] of Object.entries(schema.fields || {})) {
    if (Object.prototype.hasOwnProperty.call(schema.field_defaults || {}, key)) {
      nextInputs[key] = schema.field_defaults[key]
    } else if ((schema.field_options?.[key] || []).length) {
      nextInputs[key] = isListType(type) ? [] : schema.field_options[key][0]
    } else if (isNumberType(type)) {
      nextInputs[key] = 0
    } else if (type === 'boolean') {
      nextInputs[key] = false
    } else if (isJsonType(type)) {
      nextInputs[key] = type.startsWith('list') ? [] : {}
    } else {
      nextInputs[key] = ''
    }
    if (isJsonType(type)) nextDrafts[key] = JSON.stringify(nextInputs[key], null, 2)
  }
  inputs.value = nextInputs
  jsonDrafts.value = nextDrafts
  lastRun.value = null
}

function fieldType(key) {
  return selectedVersion.value?.input_schema?.fields?.[key] || 'string'
}

function fieldOptions(key) {
  return selectedVersion.value?.input_schema?.field_options?.[key] || []
}

function isListType(type) {
  return String(type).includes('list') || String(type).includes('array')
}

function isNumberType(type) {
  return ['number', 'integer', 'float', 'int'].some((item) => String(type).includes(item))
}

function isJsonType(type) {
  return ['object', 'dict', 'list', 'array'].some((item) => String(type).includes(item))
}

function updateJson(key, value) {
  jsonDrafts.value[key] = value
  try {
    inputs.value[key] = JSON.parse(value)
  } catch {
    inputs.value[key] = value
  }
}

function validateInputs() {
  const required = selectedVersion.value?.input_schema?.required || []
  for (const key of required) {
    const value = inputs.value[key]
    if (value === '' || value === null || value === undefined) return `请填写必填字段 ${key}`
  }
  for (const key of schemaFields.value) {
    if (isJsonType(fieldType(key)) && typeof inputs.value[key] === 'string') return `${key} 不是合法 JSON`
  }
  return ''
}

async function runPrediction() {
  const errorMessage = validateInputs()
  if (errorMessage) {
    ElMessage.warning(errorMessage)
    return
  }
  running.value = true
  try {
    lastRun.value = await createAlgorithmRun({
      algorithm_id: algorithmId.value,
      algorithm_version_id: versionId.value,
      trigger_source: 'human_workflow',
      input_snapshot: inputs.value,
      reason: '垂类预测模型工作台测试调用',
    })
    emit('run-created', lastRun.value)
    ElMessage.success('预测运行已完成')
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    running.value = false
  }
}

function duration(run) {
  if (!run?.started_at || !run?.finished_at) return '-'
  return `${Math.max(0, new Date(run.finished_at) - new Date(run.started_at))} ms`
}

function algorithmAttributions(algorithm) {
  if (!algorithm) return []
  return [
    algorithm.developer_attribution,
    ...(algorithm.framework_attributions || []),
    ...(algorithm.method_attributions || []),
  ].filter(Boolean)
}

onMounted(loadAlgorithms)
</script>

<template>
  <div class="test-panel" v-loading="loading">
    <div v-if="showToolbar" class="test-toolbar">
      <el-select v-model="algorithmId" filterable placeholder="选择算法" style="width: 320px">
        <el-option v-for="item in algorithms" :key="item.algorithm_id" :label="item.name" :value="item.algorithm_id" />
      </el-select>
      <el-select v-model="versionId" placeholder="选择版本" style="width: 260px">
        <el-option v-for="item in versions" :key="item.version_id" :label="`${item.version} · ${item.status}`" :value="item.version_id" />
      </el-select>
      <el-button :icon="Refresh" @click="loadAlgorithms">刷新</el-button>
    </div>

    <div v-if="selectedVersion" class="test-layout">
      <section class="input-pane">
        <div class="pane-heading"><h3>预测输入</h3><span>{{ selectedVersion.algorithm_id }} / {{ selectedVersion.version }}</span></div>
        <el-form label-position="top">
          <el-form-item v-for="key in schemaFields" :key="key" :label="`${key}${(selectedVersion.input_schema.required || []).includes(key) ? ' *' : ''}`">
            <el-select v-if="fieldOptions(key).length && isListType(fieldType(key))" v-model="inputs[key]" multiple style="width: 100%"><el-option v-for="option in fieldOptions(key)" :key="option" :label="option" :value="option" /></el-select>
            <el-select v-else-if="fieldOptions(key).length" v-model="inputs[key]" style="width: 100%"><el-option v-for="option in fieldOptions(key)" :key="option" :label="option" :value="option" /></el-select>
            <el-switch v-else-if="fieldType(key) === 'boolean'" v-model="inputs[key]" />
            <el-input-number v-else-if="isNumberType(fieldType(key))" v-model="inputs[key]" :step="fieldType(key).includes('int') ? 1 : 0.1" style="width: 100%" />
            <el-input v-else-if="isJsonType(fieldType(key))" :model-value="jsonDrafts[key]" type="textarea" :rows="5" class="code-input" @update:model-value="updateJson(key, $event)" />
            <el-input v-else v-model="inputs[key]" />
          </el-form-item>
        </el-form>
        <el-button type="primary" :icon="VideoPlay" :loading="running" :disabled="!versionId" @click="runPrediction">运行指定版本</el-button>
      </section>

      <section class="output-pane">
        <div class="pane-heading"><h3>运行结果</h3><el-tag v-if="lastRun" :type="lastRun.status === 'completed' ? 'success' : 'danger'">{{ lastRun.status }}</el-tag></div>
        <template v-if="lastRun">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="Run ID" :span="2">{{ lastRun.run_id }}</el-descriptions-item>
            <el-descriptions-item label="运行版本">{{ lastRun.algorithm_version_id }}</el-descriptions-item>
            <el-descriptions-item label="耗时">{{ duration(lastRun) }}</el-descriptions-item>
            <el-descriptions-item label="Package SHA" :span="2">{{ lastRun.package_sha256 || '-' }}</el-descriptions-item>
          </el-descriptions>
          <AlgorithmResultView
            class="run-result-view"
            :output-summary="lastRun.output_summary"
            :input-snapshot="lastRun.input_snapshot"
            :artifact-refs="lastRun.artifact_refs"
            :status="lastRun.status"
            :error="lastRun.error"
            :attributions="selectedAttributions"
          />
        </template>
        <div v-else class="empty-output">运行后将在此显示输出 JSON、artifact、版本与耗时。</div>
      </section>
    </div>

    <div v-else class="empty-output">暂无可调用版本。请先上传、部署并激活算法。</div>
  </div>
</template>

<style scoped>
.test-panel { display: grid; gap: 16px; }
.test-toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.test-layout { display: grid; grid-template-columns: minmax(300px, 0.8fr) minmax(0, 1.2fr); gap: 20px; align-items: start; }
.input-pane, .output-pane { min-width: 0; border-top: 1px solid var(--app-border-soft); padding-top: 14px; }
.pane-heading { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 14px; }
.pane-heading h3, h4 { margin: 0; font-size: 15px; }
.pane-heading span { color: var(--app-ink-muted); font-size: 12px; }
.run-result-view { margin-top: 14px; }
.code-input :deep(textarea) { font-family: var(--app-mono-font); }
.empty-output { min-height: 180px; display: grid; place-items: center; color: var(--app-ink-muted); text-align: center; }
@media (max-width: 900px) { .test-layout { grid-template-columns: 1fr; } }
@media (max-width: 620px) { .test-toolbar { align-items: stretch; flex-direction: column; } .test-toolbar :deep(.el-select) { width: 100% !important; } }
</style>
