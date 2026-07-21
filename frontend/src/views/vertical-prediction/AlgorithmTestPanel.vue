<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { CopyDocument, Delete, Plus, Refresh, VideoPlay } from '@element-plus/icons-vue'

import {
  createAlgorithmRun,
  getApiErrorMessage,
  listAlgorithms,
  listAlgorithmRuns,
  listAlgorithmVersions,
} from '../../api/polyAgentApi'
import { apiDateTimeMs, formatApiDateTime } from '../../utils/datetime'
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
const fullJsonDraft = ref('{}')
const jsonParseError = ref('')
const inputMode = ref('form')
const templateRuns = ref([])
const templateRunId = ref('')
const newNestedField = ref({})
const lastRun = ref(null)

const selectedAlgorithm = computed(() => algorithms.value.find((item) => item.algorithm_id === algorithmId.value) || null)
const selectedVersion = computed(() => versions.value.find((item) => item.version_id === versionId.value) || null)
const schemaFields = computed(() => Object.keys(selectedVersion.value?.input_schema?.fields || {}))
const selectedAttributions = computed(() => algorithmAttributions(selectedAlgorithm.value))
const templateOptions = computed(() => templateRuns.value.map((run) => ({
  value: run.run_id,
  label: `${formatDate(run.created_at)} · ${summarizeInput(run.input_snapshot)}`,
})))

watch(() => props.refreshKey, loadAlgorithms)
watch(() => props.algorithmId, loadAlgorithms)
watch(algorithmId, handleAlgorithmChanged)
watch(versionId, resetInputs)
watch(inputs, () => {
  if (inputMode.value === 'form') syncFullJsonDraft()
}, { deep: true })

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
      await handleAlgorithmChanged()
    }
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function handleAlgorithmChanged() {
  lastRun.value = null
  templateRunId.value = ''
  await Promise.all([loadVersions(), loadRunTemplates()])
  if (selectedVersion.value) resetInputs()
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

async function loadRunTemplates() {
  if (!algorithmId.value) {
    templateRuns.value = []
    return
  }
  try {
    const data = await listAlgorithmRuns({ algorithm_id: algorithmId.value, page: 1, page_size: 20 })
    templateRuns.value = (data.items || [])
      .filter((run) => run.status === 'completed' && isUsableTemplate(run.input_snapshot))
      .sort((a, b) => (apiDateTimeMs(b.created_at) || 0) - (apiDateTimeMs(a.created_at) || 0))
      .slice(0, 12)
  } catch {
    templateRuns.value = []
  }
}

function isUsableTemplate(snapshot) {
  if (!isPlainObject(snapshot) || !Object.keys(snapshot).length) return false
  const required = selectedAlgorithm.value?.input_schema?.required || selectedVersion.value?.input_schema?.required || []
  if (!required.length) return true
  return required.every((key) => !isEmptyValue(snapshot[key]))
}

function buildDefaultInputs() {
  const schema = selectedVersion.value?.input_schema || {}
  const nextInputs = {}
  for (const [key, type] of Object.entries(schema.fields || {})) {
    if (Object.prototype.hasOwnProperty.call(schema.field_defaults || {}, key)) {
      nextInputs[key] = cloneJson(schema.field_defaults[key])
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
  }
  return nextInputs
}

function resetInputs() {
  inputs.value = buildDefaultInputs()
  jsonParseError.value = ''
  templateRunId.value = ''
  syncFullJsonDraft()
  lastRun.value = null
}

function syncFullJsonDraft() {
  fullJsonDraft.value = JSON.stringify(inputs.value, null, 2)
}

function updateFullJson(value) {
  fullJsonDraft.value = value
  try {
    const parsed = JSON.parse(value)
    if (!isPlainObject(parsed)) {
      jsonParseError.value = '输入 JSON 必须是 object'
      return
    }
    inputs.value = parsed
    jsonParseError.value = ''
  } catch (error) {
    jsonParseError.value = error.message || 'JSON 解析失败'
  }
}

function handleModeChange(mode) {
  if (mode === 'json') {
    syncFullJsonDraft()
  } else if (!jsonParseError.value) {
    syncFullJsonDraft()
  }
}

function applySelectedTemplate(runId) {
  const run = templateRuns.value.find((item) => item.run_id === runId)
  if (run) applyTemplate(run.input_snapshot)
}

function applyLatestTemplate() {
  const run = templateRuns.value[0]
  if (!run) return
  templateRunId.value = run.run_id
  applyTemplate(run.input_snapshot)
}

function applyTemplate(snapshot) {
  inputs.value = {
    ...buildDefaultInputs(),
    ...cloneJson(snapshot),
  }
  jsonParseError.value = ''
  syncFullJsonDraft()
  ElMessage.success('已载入历史输入')
}

function fieldHint(key) {
  return selectedVersion.value?.input_schema?.ui_hints?.[key] || {}
}

function fieldLabel(key) {
  return fieldHint(key).label || formatLabel(key)
}

function nestedFieldLabel(parentKey, key) {
  return fieldHint(parentKey).column_labels?.[key] || formatLabel(key)
}

function fieldHelp(key) {
  return fieldHint(key).help || ''
}

function fieldUnit(key) {
  return fieldHint(key).unit || ''
}

function fieldPlaceholder(key) {
  return fieldHint(key).placeholder || ''
}

function isRequiredField(key) {
  return (selectedVersion.value?.input_schema?.required || []).includes(key)
}

function canUseStructuredEditor(key) {
  const type = fieldType(key)
  return isJsonType(type)
}

function isArrayObjectField(key) {
  const value = inputs.value[key]
  const hinted = Array.isArray(fieldHint(key).columns) && fieldHint(key).columns.length
  const templateRows = Array.isArray(templateValueFor(key)) ? templateValueFor(key) : []
  if (hinted || templateRows.some(isPlainObject)) return true
  if (Array.isArray(value) && value.length) return value.every((item) => isPlainObject(item))
  return false
}

function isScalarArrayField(key) {
  return isListType(fieldType(key)) || Array.isArray(inputs.value[key])
}

function isObjectField(key) {
  return isPlainObject(inputs.value[key]) || ['object', 'dict'].some((item) => String(fieldType(key)).includes(item))
}

function ensureArrayValue(key) {
  if (!Array.isArray(inputs.value[key])) inputs.value[key] = []
}

function ensureObjectValue(key) {
  if (!isPlainObject(inputs.value[key])) inputs.value[key] = {}
}

function templateValueFor(key) {
  for (const run of templateRuns.value) {
    const value = run.input_snapshot?.[key]
    if (!isEmptyValue(value)) return value
  }
  return undefined
}

function arrayRows(key) {
  ensureArrayValue(key)
  return inputs.value[key]
}

function arrayColumns(key) {
  const hinted = Array.isArray(fieldHint(key).columns) ? fieldHint(key).columns : []
  const rows = Array.isArray(inputs.value[key]) ? inputs.value[key] : []
  const templateRows = Array.isArray(templateValueFor(key)) ? templateValueFor(key) : []
  const keys = new Set()
  hinted.forEach((column) => keys.add(String(column)))
  ;[...rows, ...templateRows].forEach((row) => {
    if (isPlainObject(row)) Object.keys(row).forEach((column) => keys.add(column))
  })
  return Array.from(keys)
}

function visibleArrayColumns(key) {
  const collapsed = new Set((fieldHint(key).collapsed_keys || []).map(String))
  return arrayColumns(key).filter((column) => !collapsed.has(column))
}

function collapsedArrayColumns(key) {
  const collapsed = new Set((fieldHint(key).collapsed_keys || []).map(String))
  return arrayColumns(key).filter((column) => collapsed.has(column))
}

function objectColumns(key) {
  const hinted = Array.isArray(fieldHint(key).columns) ? fieldHint(key).columns : []
  const value = isPlainObject(inputs.value[key]) ? inputs.value[key] : {}
  const template = isPlainObject(templateValueFor(key)) ? templateValueFor(key) : {}
  return Array.from(new Set([...hinted.map(String), ...Object.keys(value), ...Object.keys(template)]))
}

function emptyItemTemplate(key) {
  const templateRows = Array.isArray(templateValueFor(key)) ? templateValueFor(key) : []
  const source = templateRows.find(isPlainObject) || (Array.isArray(inputs.value[key]) ? inputs.value[key].find(isPlainObject) : null)
  const columns = arrayColumns(key)
  return Object.fromEntries(columns.map((column) => [column, defaultValueFrom(source?.[column])]))
}

function addArrayItem(key) {
  ensureArrayValue(key)
  inputs.value[key].push(emptyItemTemplate(key))
  syncFullJsonDraft()
}

function addScalarArrayItem(key) {
  ensureArrayValue(key)
  inputs.value[key].push('')
  syncFullJsonDraft()
}

function copyArrayItem(key, index) {
  ensureArrayValue(key)
  inputs.value[key].splice(index + 1, 0, cloneJson(inputs.value[key][index]))
  syncFullJsonDraft()
}

function removeArrayItem(key, index) {
  ensureArrayValue(key)
  inputs.value[key].splice(index, 1)
  syncFullJsonDraft()
}

function addNestedFieldToArray(key) {
  const name = String(newNestedField.value[key] || '').trim()
  if (!name) return
  ensureArrayValue(key)
  if (!inputs.value[key].length) inputs.value[key].push({})
  inputs.value[key].forEach((item) => {
    if (isPlainObject(item) && !Object.prototype.hasOwnProperty.call(item, name)) item[name] = ''
  })
  newNestedField.value[key] = ''
  syncFullJsonDraft()
}

function addNestedFieldToObject(key) {
  const name = String(newNestedField.value[key] || '').trim()
  if (!name) return
  ensureObjectValue(key)
  if (!Object.prototype.hasOwnProperty.call(inputs.value[key], name)) inputs.value[key][name] = ''
  newNestedField.value[key] = ''
  syncFullJsonDraft()
}

function removeObjectField(key, field) {
  ensureObjectValue(key)
  delete inputs.value[key][field]
  syncFullJsonDraft()
}

function itemTitle(key, item, index) {
  const titleKey = fieldHint(key).item_title_key || ['formula_id', 'id', 'name', 'title'].find((candidate) => item?.[candidate])
  return titleKey && item?.[titleKey] ? String(item[titleKey]) : `${fieldLabel(key)} ${index + 1}`
}

function valueKind(value) {
  if (typeof value === 'number') return 'number'
  if (typeof value === 'boolean') return 'boolean'
  return 'string'
}

function defaultValueFrom(value) {
  if (typeof value === 'number') return 0
  if (typeof value === 'boolean') return false
  return ''
}

function cloneJson(value) {
  return JSON.parse(JSON.stringify(value ?? null))
}

function formatLabel(value) {
  return String(value || '-')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function formatDate(value) {
  return formatApiDateTime(value)
}

function summarizeInput(value) {
  if (!isPlainObject(value)) return '输入快照'
  const fields = Object.keys(value)
  if (!fields.length) return '空输入'
  const first = value[fields[0]]
  if (Array.isArray(first)) return `${fields[0]} · ${first.length} 条`
  return fields.slice(0, 3).join('、')
}

function isPlainObject(value) {
  return Object.prototype.toString.call(value) === '[object Object]'
}

function isEmptyValue(value) {
  if (value === null || value === undefined || value === '') return true
  if (Array.isArray(value)) return value.length === 0
  if (isPlainObject(value)) return Object.keys(value).length === 0
  return false
}

function setScalarValue(key, value) {
  inputs.value[key] = value
  syncFullJsonDraft()
}

function setNestedValue(target, key, value) {
  target[key] = value
  syncFullJsonDraft()
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

function validateInputs() {
  if (jsonParseError.value) return `输入 JSON 不合法：${jsonParseError.value}`
  const required = selectedVersion.value?.input_schema?.required || []
  for (const key of required) {
    const value = inputs.value[key]
    if (isEmptyValue(value)) return `请填写必填字段 ${fieldLabel(key)}`
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
  const started = apiDateTimeMs(run.started_at)
  const finished = apiDateTimeMs(run.finished_at)
  if (Number.isNaN(started) || Number.isNaN(finished)) return '-'
  return `${Math.max(0, finished - started)} ms`
}

function shortText(value, length = 34) {
  if (!value) return '-'
  const text = String(value)
  return text.length > length ? `${text.slice(0, length - 3)}...` : text
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
        <div class="pane-heading">
          <div>
            <h3>预测输入</h3>
            <span>{{ selectedVersion.algorithm_id }} / {{ selectedVersion.version }}</span>
          </div>
          <el-radio-group v-model="inputMode" size="small" @change="handleModeChange">
            <el-radio-button value="form">表单</el-radio-button>
            <el-radio-button value="json">JSON</el-radio-button>
          </el-radio-group>
        </div>

        <div class="template-toolbar">
          <el-select
            v-model="templateRunId"
            filterable
            clearable
            placeholder="历史输入模板"
            :disabled="!templateOptions.length"
            @change="applySelectedTemplate"
          >
            <el-option v-for="item in templateOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-button :icon="CopyDocument" :disabled="!templateRuns.length" @click="applyLatestTemplate">载入最近成功输入</el-button>
        </div>

        <el-form v-if="inputMode === 'form'" label-position="top" class="smart-input-form">
          <el-form-item
            v-for="key in schemaFields"
            :key="key"
            :class="{ 'json-form-item': canUseStructuredEditor(key) }"
          >
            <template #label>
              <span class="field-label">
                {{ fieldLabel(key) }}
                <em v-if="isRequiredField(key)">*</em>
                <small v-if="fieldUnit(key)">{{ fieldUnit(key) }}</small>
              </span>
              <span v-if="fieldHelp(key)" class="field-help">{{ fieldHelp(key) }}</span>
            </template>

            <el-select
              v-if="fieldOptions(key).length && isListType(fieldType(key))"
              :model-value="inputs[key]"
              multiple
              class="full-control"
              @update:model-value="setScalarValue(key, $event)"
            >
              <el-option v-for="option in fieldOptions(key)" :key="option" :label="option" :value="option" />
            </el-select>
            <el-select
              v-else-if="fieldOptions(key).length"
              :model-value="inputs[key]"
              class="full-control"
              @update:model-value="setScalarValue(key, $event)"
            >
              <el-option v-for="option in fieldOptions(key)" :key="option" :label="option" :value="option" />
            </el-select>
            <el-switch
              v-else-if="fieldType(key) === 'boolean'"
              :model-value="inputs[key]"
              @update:model-value="setScalarValue(key, $event)"
            />
            <el-input-number
              v-else-if="isNumberType(fieldType(key))"
              :model-value="inputs[key]"
              :step="fieldType(key).includes('int') ? 1 : 0.1"
              class="full-control"
              @update:model-value="setScalarValue(key, $event)"
            />
            <div v-else-if="isArrayObjectField(key)" class="array-object-editor">
              <div class="nested-toolbar">
                <div class="nested-count">{{ arrayRows(key).length }} 条记录</div>
                <div class="nested-actions">
                  <el-input v-model="newNestedField[key]" placeholder="自定义字段名" clearable @keyup.enter="addNestedFieldToArray(key)" />
                  <el-button :icon="Plus" @click="addNestedFieldToArray(key)">字段</el-button>
                  <el-button type="primary" :icon="Plus" @click="addArrayItem(key)">记录</el-button>
                </div>
              </div>
              <div v-if="arrayRows(key).length" class="record-list">
                <article v-for="(item, index) in arrayRows(key)" :key="index" class="record-card">
                  <header class="record-head">
                    <strong>{{ itemTitle(key, item, index) }}</strong>
                    <div class="record-actions">
                      <el-button text :icon="CopyDocument" aria-label="复制记录" @click="copyArrayItem(key, index)" />
                      <el-button text :icon="Delete" aria-label="删除记录" @click="removeArrayItem(key, index)" />
                    </div>
                  </header>
                  <div class="record-fields">
                    <label v-for="column in visibleArrayColumns(key)" :key="column" class="nested-field">
                      <span>{{ nestedFieldLabel(key, column) }}</span>
                      <el-input-number
                        v-if="valueKind(item[column]) === 'number'"
                        :model-value="item[column]"
                        :step="1"
                        class="full-control"
                        @update:model-value="setNestedValue(item, column, $event)"
                      />
                      <el-switch
                        v-else-if="valueKind(item[column]) === 'boolean'"
                        :model-value="item[column]"
                        @update:model-value="setNestedValue(item, column, $event)"
                      />
                      <el-input
                        v-else
                        :model-value="item[column]"
                        :placeholder="nestedFieldLabel(key, column)"
                        @update:model-value="setNestedValue(item, column, $event)"
                      />
                    </label>
                  </div>
                  <el-collapse v-if="collapsedArrayColumns(key).length" class="record-collapse">
                    <el-collapse-item title="更多字段" :name="`${key}-${index}`">
                      <div class="record-fields">
                        <label v-for="column in collapsedArrayColumns(key)" :key="column" class="nested-field">
                          <span>{{ nestedFieldLabel(key, column) }}</span>
                          <el-input :model-value="item[column]" @update:model-value="setNestedValue(item, column, $event)" />
                        </label>
                      </div>
                    </el-collapse-item>
                  </el-collapse>
                </article>
              </div>
              <div v-else class="nested-empty">
                <el-button type="primary" :icon="Plus" @click="addArrayItem(key)">新增第一条记录</el-button>
              </div>
            </div>
            <div v-else-if="isScalarArrayField(key)" class="scalar-array-editor">
              <div class="nested-toolbar">
                <div class="nested-count">{{ arrayRows(key).length }} 项</div>
                <el-button type="primary" :icon="Plus" @click="addScalarArrayItem(key)">添加</el-button>
              </div>
              <div class="scalar-array-list">
                <div v-for="(item, index) in arrayRows(key)" :key="index" class="scalar-array-row">
                  <el-input :model-value="item" @update:model-value="setNestedValue(inputs[key], index, $event)" />
                  <el-button text :icon="Delete" aria-label="删除项目" @click="removeArrayItem(key, index)" />
                </div>
              </div>
            </div>
            <div v-else-if="isObjectField(key)" class="object-editor">
              <div class="nested-toolbar">
                <div class="nested-count">{{ objectColumns(key).length }} 个字段</div>
                <div class="nested-actions">
                  <el-input v-model="newNestedField[key]" placeholder="自定义字段名" clearable @keyup.enter="addNestedFieldToObject(key)" />
                  <el-button :icon="Plus" @click="addNestedFieldToObject(key)">字段</el-button>
                </div>
              </div>
              <div class="record-fields">
                <label v-for="column in objectColumns(key)" :key="column" class="nested-field">
                  <span>{{ nestedFieldLabel(key, column) }}</span>
                  <div class="object-field-row">
                    <el-input :model-value="inputs[key]?.[column]" @update:model-value="setNestedValue(inputs[key], column, $event)" />
                    <el-button text :icon="Delete" aria-label="删除字段" @click="removeObjectField(key, column)" />
                  </div>
                </label>
              </div>
            </div>
            <el-input
              v-else
              :model-value="inputs[key]"
              :placeholder="fieldPlaceholder(key)"
              @update:model-value="setScalarValue(key, $event)"
            />
          </el-form-item>
        </el-form>

        <div v-else class="json-editor">
          <el-input :model-value="fullJsonDraft" type="textarea" :rows="20" class="code-input" @update:model-value="updateFullJson" />
          <el-alert v-if="jsonParseError" class="json-error" :title="jsonParseError" type="error" :closable="false" show-icon />
        </div>

        <div class="input-actions">
          <el-button type="primary" :icon="VideoPlay" :loading="running" :disabled="!versionId" @click="runPrediction">运行指定版本</el-button>
          <el-button :icon="Refresh" @click="resetInputs">重置输入</el-button>
        </div>
      </section>

      <section class="output-pane">
        <div class="pane-heading"><h3>运行结果</h3><el-tag v-if="lastRun" :type="lastRun.status === 'completed' ? 'success' : 'danger'">{{ lastRun.status }}</el-tag></div>
        <template v-if="lastRun">
          <div class="run-overview">
            <div>
              <span>Run ID</span>
              <strong>{{ shortText(lastRun.run_id) }}</strong>
            </div>
            <div>
              <span>耗时</span>
              <strong>{{ duration(lastRun) }}</strong>
            </div>
            <div>
              <span>版本</span>
              <strong>{{ shortText(lastRun.algorithm_version_id) }}</strong>
            </div>
          </div>
          <AlgorithmResultView
            class="run-result-view"
            :output-summary="lastRun.output_summary"
            :input-snapshot="lastRun.input_snapshot"
            :artifact-refs="lastRun.artifact_refs"
            :status="lastRun.status"
            :error="lastRun.error"
            :attributions="selectedAttributions"
          />
          <el-collapse class="run-metadata">
            <el-collapse-item title="运行元数据" name="metadata">
              <el-descriptions :column="1" border size="small">
                <el-descriptions-item label="Run ID">{{ lastRun.run_id }}</el-descriptions-item>
                <el-descriptions-item label="运行版本">{{ lastRun.algorithm_version_id }}</el-descriptions-item>
                <el-descriptions-item label="耗时">{{ duration(lastRun) }}</el-descriptions-item>
                <el-descriptions-item label="Package SHA">{{ lastRun.package_sha256 || '-' }}</el-descriptions-item>
              </el-descriptions>
            </el-collapse-item>
          </el-collapse>
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
.pane-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 14px; }
.pane-heading h3, h4 { margin: 0; font-size: 15px; }
.pane-heading span { color: var(--app-ink-muted); font-size: 12px; }
.template-toolbar, .input-actions, .nested-toolbar, .nested-actions, .record-actions, .object-field-row, .scalar-array-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.template-toolbar {
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.template-toolbar .el-select {
  flex: 1 1 240px;
}
.smart-input-form {
  display: grid;
  gap: 2px;
}
.json-form-item {
  margin-bottom: 18px;
}
.field-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  color: var(--app-ink);
  font-weight: 700;
}
.field-label em {
  color: #dc2626;
  font-style: normal;
}
.field-label small {
  color: var(--app-ink-muted);
  font-size: 11px;
  font-weight: 600;
}
.field-help {
  display: block;
  margin-top: 2px;
  color: var(--app-ink-muted);
  font-size: 12px;
  line-height: 1.45;
}
.full-control {
  width: 100%;
}
.array-object-editor,
.object-editor,
.scalar-array-editor {
  min-width: 0;
  width: 100%;
  padding: 12px;
  border: 1px solid var(--app-stat-border);
  border-radius: var(--app-radius-sm);
  background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
}
.nested-toolbar {
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.nested-count {
  color: var(--app-ink-muted);
  font-size: 12px;
  font-weight: 700;
}
.nested-actions {
  flex: 1 1 260px;
  justify-content: flex-end;
  flex-wrap: wrap;
}
.nested-actions .el-input {
  max-width: 180px;
}
.record-list {
  display: grid;
  gap: 10px;
}
.record-card {
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #fff;
}
.record-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.record-head strong {
  min-width: 0;
  color: var(--app-ink);
  font-size: 14px;
  overflow-wrap: anywhere;
}
.record-actions {
  flex: 0 0 auto;
}
.record-fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 10px;
}
.nested-field {
  display: grid;
  gap: 5px;
  min-width: 0;
}
.nested-field > span {
  color: var(--app-ink-muted);
  font-size: 12px;
  font-weight: 700;
  overflow-wrap: anywhere;
}
.record-collapse {
  margin-top: 10px;
}
.nested-empty {
  min-height: 90px;
  display: grid;
  place-items: center;
  border: 1px dashed var(--app-border);
  border-radius: var(--app-radius-sm);
  background: rgba(255, 255, 255, 0.72);
}
.scalar-array-list {
  display: grid;
  gap: 8px;
}
.scalar-array-row .el-input,
.object-field-row .el-input {
  min-width: 0;
  flex: 1;
}
.json-editor {
  display: grid;
  gap: 10px;
}
.json-error {
  margin-top: 2px;
}
.input-actions {
  margin-top: 14px;
  flex-wrap: wrap;
}
.run-overview {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--app-stat-border);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
}
.run-overview div {
  min-width: 0;
}
.run-overview span {
  display: block;
  color: var(--app-ink-muted);
  font-size: 12px;
}
.run-overview strong {
  display: block;
  margin-top: 3px;
  color: var(--app-ink);
  font-size: 13px;
  overflow-wrap: anywhere;
}
.run-metadata {
  margin-top: 12px;
}
.run-result-view { margin-top: 14px; }
.code-input :deep(textarea) { font-family: var(--app-mono-font); }
.empty-output { min-height: 180px; display: grid; place-items: center; color: var(--app-ink-muted); text-align: center; }
@media (max-width: 900px) { .test-layout { grid-template-columns: 1fr; } }
@media (max-width: 620px) {
  .test-toolbar, .pane-heading, .template-toolbar, .nested-toolbar, .nested-actions, .input-actions {
    align-items: stretch;
    flex-direction: column;
  }
  .test-toolbar :deep(.el-select), .template-toolbar .el-select, .nested-actions .el-input, .input-actions .el-button {
    width: 100% !important;
    max-width: none;
  }
  .record-fields {
    grid-template-columns: 1fr;
  }
  .run-overview {
    grid-template-columns: 1fr;
  }
}
</style>
