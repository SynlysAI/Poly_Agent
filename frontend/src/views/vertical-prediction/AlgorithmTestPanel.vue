<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument, Delete, Plus, Refresh, VideoPlay } from '@element-plus/icons-vue'

import {
  createAlgorithmRun,
  createAlgorithmRunMultipart,
  getApiErrorMessage,
  listAlgorithmRunArtifacts,
  listAlgorithms,
  listAlgorithmRuns,
  listAlgorithmVersions,
} from '../../api/polyAgentApi'
import { apiDateTimeMs, formatApiDateTime } from '../../utils/datetime'
import { inferValueKind } from '../../utils/verticalPredictionJson.mjs'
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
const startSections = ref([])
const advancedSections = ref([])
const templateRuns = ref([])
const templateRunId = ref('')
const hiddenColumns = ref({})
const lastRun = ref(null)
const inputFiles = ref({})
const runArtifacts = ref([])

const selectedAlgorithm = computed(() => algorithms.value.find((item) => item.algorithm_id === algorithmId.value) || null)
const activeRegistryVersion = computed(() => {
  const algorithm = selectedAlgorithm.value
  if (!algorithm?.active_version_id) return null
  return {
    version_id: algorithm.active_version_id,
    algorithm_id: algorithm.algorithm_id,
    version: algorithm.version,
    status: algorithm.status === 'active' ? 'active' : algorithm.status,
    source_kind: algorithm.source_kind || algorithm.source,
    interface_config: algorithm.interface_config || null,
    input_schema: algorithm.input_schema || {},
    output_schema: algorithm.output_schema || {},
    input_assets: algorithm.input_assets || [],
    output_assets: algorithm.output_assets || [],
    resource_assets: algorithm.resource_assets || [],
    mentor_team: algorithm.mentor_team || null,
  }
})
const versionOptions = computed(() => {
  if (versions.value.length) return versions.value
  return activeRegistryVersion.value ? [activeRegistryVersion.value] : []
})
const selectedVersion = computed(() => (
  versions.value.find((item) => item.version_id === versionId.value)
  || (activeRegistryVersion.value && (!versionId.value || activeRegistryVersion.value.version_id === versionId.value) ? activeRegistryVersion.value : null)
))
const schemaFields = computed(() => Object.keys(selectedVersion.value?.input_schema?.fields || {}))
const inputAssets = computed(() => selectedVersion.value?.input_assets || [])
const requiredInputAssets = computed(() => inputAssets.value.filter((item) => item.required))
const selectedAttributions = computed(() => algorithmAttributions(selectedAlgorithm.value))
const templateOptions = computed(() => templateRuns.value.map((run) => ({
  value: run.run_id,
  label: `${formatApiDateTime(run.created_at)} · ${summarizeInput(run.input_snapshot)}`,
})))
const primaryArrayObjectKey = computed(() => {
  const formulationsKey = schemaFields.value.find((key) => key === 'formulations' && isArrayObjectField(key))
  return formulationsKey || schemaFields.value.find((key) => isArrayObjectField(key)) || ''
})
const primaryRecords = computed(() => {
  const key = primaryArrayObjectKey.value
  return key && Array.isArray(inputs.value[key]) ? inputs.value[key] : []
})
const missingRequiredFields = computed(() => (selectedVersion.value?.input_schema?.required || [])
  .filter((key) => isEmptyValue(inputs.value[key]))
  .map((key) => fieldLabel(key)))
const hasBlankPrimaryRecords = computed(() => (
  Boolean(primaryArrayObjectKey.value)
  && primaryRecords.value.length > 0
  && !primaryRecords.value.some(hasEffectiveRecordValue)
))
const runBlocker = computed(() => {
  if (!selectedVersion.value) return '请选择可调用版本。'
  if (jsonParseError.value) return `输入 JSON 不合法：${jsonParseError.value}`
  if (missingRequiredFields.value.length) return `缺少必填字段：${missingRequiredFields.value.join('、')}`
  const missingAssets = requiredInputAssets.value.filter((item) => !inputFiles.value[item.key])
  if (missingAssets.length) return `上传必填文件：${missingAssets.map(assetLabel).join('、')}`
  for (const key of schemaFields.value) {
    if (isJsonType(fieldType(key)) && typeof inputs.value[key] === 'string') return `${key} 不是合法 JSON`
  }
  for (const asset of inputAssets.value) {
    const file = inputFiles.value[asset.key]
    if (!file) continue
    if (asset.max_size_bytes && file.size > asset.max_size_bytes) return `${assetLabel(asset)} 超过大小限制`
    const suffix = file.name.includes('.') ? `.${file.name.split('.').pop().toLowerCase()}` : ''
    const extensions = (asset.extensions || []).map((item) => String(item).toLowerCase())
    if (extensions.length && !extensions.includes(suffix)) return `${assetLabel(asset)} 文件类型不受支持`
  }
  if (hasBlankPrimaryRecords.value) return '请先填写至少一条记录的字段值。'
  return ''
})
watch(() => props.refreshKey, loadAlgorithms)
watch(() => props.algorithmId, loadAlgorithms)
watch(algorithmId, handleAlgorithmChanged)
watch(versionId, resetInputs)
watch(inputs, syncFullJsonDraft, { deep: true })

async function loadAlgorithms() {
  loading.value = true
  try {
    const data = await listAlgorithms({ algorithm_family: 'vertical_prediction', page: 1, page_size: 100 })
    algorithms.value = (data.items || []).filter((item) => ['uploaded_package', 'remote_interface'].includes(item.source))
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
    versionId.value = versions.value.find((item) => item.status === 'active')?.version_id || versions.value[0]?.version_id || activeRegistryVersion.value?.version_id || ''
  } catch (error) {
    versions.value = []
    versionId.value = activeRegistryVersion.value?.version_id || ''
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
  inputFiles.value = {}
  runArtifacts.value = []
  jsonParseError.value = ''
  templateRunId.value = ''
  resetNestedFieldState()
  syncFullJsonDraft()
  lastRun.value = null
}

function resetNestedFieldState() {
  hiddenColumns.value = {}
}

function syncFullJsonDraft() {
  fullJsonDraft.value = JSON.stringify(inputs.value, null, 2)
  jsonParseError.value = ''
}

function updateFullJson(value) {
  fullJsonDraft.value = value
  try {
    const parsed = JSON.parse(value)
    if (!isPlainObject(parsed)) {
      jsonParseError.value = '输入 JSON 必须是 object'
      return
    }
    for (const key of schemaFields.value) {
      if (isListType(fieldType(key)) && parsed[key] !== undefined && !Array.isArray(parsed[key])) {
        jsonParseError.value = `"${key}" 应为数组类型`
        return
      }
    }
    inputs.value = parsed
    resetNestedFieldState()
    jsonParseError.value = ''
  } catch (error) {
    jsonParseError.value = error.message || 'JSON 解析失败'
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
  resetNestedFieldState()
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

function canUseStructuredEditor(key) {
  const type = fieldType(key)
  return isJsonType(type)
}

function isArrayObjectField(key) {
  const value = inputs.value[key]
  const hinted = Array.isArray(fieldHint(key).columns) && fieldHint(key).columns.length
  const templateRows = Array.isArray(historyValueFor(key)) ? historyValueFor(key) : []
  const type = String(fieldType(key))
  if (hinted || templateRows.some(isPlainObject)) return true
  if (key === 'formulations' && isListType(type)) return true
  if (isListType(type) && ['object', 'dict'].some((item) => type.includes(item))) return true
  if (Array.isArray(value) && value.length) return value.every((item) => isPlainObject(item))
  return false
}

function isScalarArrayField(key) {
  return isListType(fieldType(key)) || Array.isArray(inputs.value[key])
}

function isObjectField(key) {
  return isPlainObject(inputs.value[key]) || ['object', 'dict'].some((item) => String(fieldType(key)).includes(item))
}

function templateValueFor(key) {
  const selected = templateRuns.value.find((run) => run.run_id === templateRunId.value)
  return selected?.input_snapshot?.[key]
}

function historyValueFor(key) {
  for (const run of templateRuns.value) {
    const value = run.input_snapshot?.[key]
    if (!isEmptyValue(value)) return value
  }
  return undefined
}

function arrayRows(key) {
  return Array.isArray(inputs.value[key]) ? inputs.value[key] : []
}

function arrayColumns(key) {
  const hinted = Array.isArray(fieldHint(key).columns) ? fieldHint(key).columns : []
  const rows = Array.isArray(inputs.value[key]) ? inputs.value[key] : []
  const templateRows = Array.isArray(templateValueFor(key)) ? templateValueFor(key) : []
  const keys = new Set()
  hinted.forEach((column) => keys.add(String(column)))
  defaultArrayColumns(key).forEach((column) => keys.add(column))
  ;[...rows, ...templateRows].forEach((row) => {
    if (isPlainObject(row)) Object.keys(row).forEach((column) => keys.add(column))
  })
  return Array.from(keys)
}

function defaultArrayColumns(key) {
  if (key !== 'formulations') return []
  return [
    'formula_id',
    'task_type',
    'lithium_salt',
    'lithium_salt_mol_L',
    'electrolyte_component_1',
    'electrolyte_component_1_mol_ratio',
    'electrolyte_component_2',
    'electrolyte_component_2_mol_ratio',
  ]
}

function visibleArrayColumns(key) {
  const collapsed = new Set((fieldHint(key).collapsed_keys || []).map(String))
  return arrayColumns(key).filter((column) => !collapsed.has(column))
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
  return Object.fromEntries(columns.map((column) => [column, defaultValueForColumn(column, source?.[column])]))
}

function addArrayItem(key) {
  inputs.value[key].push(emptyItemTemplate(key))
  syncFullJsonDraft()
}

function addScalarArrayItem(key) {
  inputs.value[key].push('')
  syncFullJsonDraft()
}

function copyArrayItem(key, index) {
  inputs.value[key].splice(index + 1, 0, cloneJson(inputs.value[key][index]))
  syncFullJsonDraft()
}

function removeArrayItem(key, index) {
  inputs.value[key].splice(index, 1)
  syncFullJsonDraft()
}

async function promptPasteData(key) {
  try {
    const { value } = await ElMessageBox.prompt('从 Excel 复制数据后粘贴到下方（支持 Tab / 逗号分隔）', '粘贴数据', {
      confirmButtonText: '导入',
      cancelButtonText: '取消',
      inputType: 'textarea',
      inputPlaceholder: '在此粘贴 Excel / CSV 数据...',
      customClass: 'paste-data-dialog',
    })
    if (value && value.trim()) {
      importPastedData(key, value)
    }
  } catch {
    /* cancelled */
  }
}

function importPastedData(key, text) {
  const lines = text.trim().split(/\r?\n/).filter((line) => line.trim())
  if (!lines.length) return

  const delim = detectDelimiter(lines)
  const rawRows = lines.map((line) => parseRow(line, delim))
  if (!rawRows.length || !rawRows[0].length) return

  const columns = displayedArrayColumns(key)
  const headerRow = rawRows[0]
  const colIndex = new Map()
  columns.forEach((col) => colIndex.set(col.toLowerCase(), col))

  const hasHeader = headerRow.some((cell) => colIndex.has(String(cell).trim().toLowerCase()))
  const dataRows = hasHeader ? rawRows.slice(1) : rawRows

  const colMap = []
  for (let i = 0; i < headerRow.length; i++) {
    const name = String(headerRow[i] || '').trim().toLowerCase()
    colMap[i] = colIndex.has(name) ? colIndex.get(name) : (hasHeader ? null : columns[i] || null)
  }

  let added = 0
  for (const rawRow of dataRows) {
    if (rawRow.every((cell) => !String(cell).trim())) continue
    const record = emptyItemTemplate(key)
    for (let i = 0; i < rawRow.length && i < colMap.length; i++) {
      const col = colMap[i]
      if (col) {
        record[col] = coerceCellValue(key, col, rawRow[i])
      }
    }
    inputs.value[key].push(record)
    added++
  }
  if (added) {
    syncFullJsonDraft()
    ElMessage.success(`已导入 ${added} 行`)
  } else {
    ElMessage.warning('未能解析出有效数据，请检查格式')
  }
}

function detectDelimiter(lines) {
  const tabCount = lines.reduce((sum, line) => sum + (line.match(/\t/g) || []).length, 0)
  const commaCount = lines.reduce((sum, line) => sum + (line.match(/,/g) || []).length, 0)
  return tabCount >= commaCount ? '\t' : ','
}

function parseRow(line, delim) {
  if (delim === '\t') return line.split('\t')
  return line.split(',').map((cell) => {
    const trimmed = cell.trim()
    if ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
      return trimmed.slice(1, -1)
    }
    return trimmed
  })
}

function coerceCellValue(key, column, raw) {
  const text = String(raw ?? '').trim()
  if (!text) return ''
  const kind = nestedValueKind(key, column, {})
  if (kind === 'number') {
    const num = Number(text)
    return Number.isFinite(num) ? num : text
  }
  if (kind === 'boolean') return text.toLowerCase() === 'true'
  return text
}

function nestedValueKind(parentKey, field, item) {
  const rows = Array.isArray(inputs.value[parentKey]) ? inputs.value[parentKey] : []
  const historyRows = Array.isArray(historyValueFor(parentKey)) ? historyValueFor(parentKey) : []
  return inferValueKind(field, [
    item?.[field],
    ...rows.map((row) => row?.[field]),
    ...historyRows.map((row) => row?.[field]),
  ])
}


function displayedArrayColumns(key) {
  const hidden = hiddenColumns.value[key] || new Set()
  return arrayColumns(key).filter((column) => !hidden.has(column))
}

function toggleColumnVisibility(key, column, visible) {
  if (!hiddenColumns.value[key]) hiddenColumns.value[key] = new Set()
  if (visible) {
    hiddenColumns.value[key].delete(column)
  } else {
    hiddenColumns.value[key].add(column)
  }
}





function nestedNumberStep(field) {
  return /(count|index|number)/i.test(String(field || '')) ? 1 : 0.1
}

function defaultValueFrom(value) {
  if (typeof value === 'number') return 0
  if (typeof value === 'boolean') return false
  return ''
}

function defaultValueForColumn(column, sourceValue) {
  if (sourceValue !== undefined && sourceValue !== '') return defaultValueFrom(sourceValue)
  const kind = inferValueKind(column, [sourceValue])
  if (kind === 'boolean') return false
  if (kind === 'number') return 0
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

function hasEffectiveRecordValue(record) {
  if (!isPlainObject(record)) return !isEmptyValue(record)
  return Object.values(record).some((value) => {
    if (typeof value === 'string') return value.trim() !== ''
    if (typeof value === 'number') return value !== 0
    if (typeof value === 'boolean') return value
    return !isEmptyValue(value)
  })
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

function setInputAssetFile(key, file) {
  inputFiles.value = { ...inputFiles.value, [key]: file || null }
}

function assetLabel(asset) {
  return asset?.label || asset?.key || '文件'
}

function assetAccept(asset) {
  const extensions = asset?.extensions || []
  const mimeTypes = asset?.mime_types || []
  return [...extensions, ...mimeTypes].join(',')
}

function assetHint(asset) {
  const extensions = asset?.extensions || []
  const parser = asset?.parser || 'auto'
  const dataKind = asset?.data_kind || asset?.dataKind || 'file'
  const limit = asset?.max_size_bytes ? `，上限 ${formatBytes(asset.max_size_bytes)}` : ''
  return `${dataKind} / ${parser}${extensions.length ? `，支持 ${extensions.join('、')}` : ''}${limit}`
}

function formatBytes(value) {
  const size = Number(value || 0)
  if (!size) return '-'
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${size} B`
}

async function runPrediction() {
  if (runBlocker.value) {
    ElMessage.warning(runBlocker.value)
    return
  }
  lastRun.value = null
  runArtifacts.value = []
  running.value = true
  try {
    const explicitVersionId = versions.value.some((item) => item.version_id === versionId.value) ? versionId.value : ''
    const payload = {
      algorithm_id: algorithmId.value,
      trigger_source: 'human_workflow',
      input_snapshot: inputs.value,
      reason: '垂类预测模型工作台测试调用',
    }
    if (explicitVersionId) payload.algorithm_version_id = explicitVersionId
    lastRun.value = inputAssets.value.length
      ? await createAlgorithmRunMultipart(payload, inputFiles.value)
      : await createAlgorithmRun(payload)
    await loadRunArtifacts(lastRun.value)
    emit('run-created', lastRun.value)
    ElMessage.success('预测运行已完成')
  } catch (error) {
    const message = getApiErrorMessage(error)
    lastRun.value = {
      status: 'failed',
      input_snapshot: cloneJson(inputs.value),
      output_summary: {},
      artifact_refs: [],
      error: { message },
    }
    ElMessage.error(message)
  } finally {
    running.value = false
  }
}

async function loadRunArtifacts(run) {
  runArtifacts.value = []
  if (!run?.run_id) return
  try {
    const data = await listAlgorithmRunArtifacts(run.run_id)
    runArtifacts.value = data.items || []
    if (runArtifacts.value.length) {
      lastRun.value = {
        ...run,
        artifact_refs: runArtifacts.value,
      }
    }
  } catch {
    runArtifacts.value = []
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
        <el-option v-for="item in versionOptions" :key="item.version_id" :label="`${item.version} · ${item.status}`" :value="item.version_id" />
      </el-select>
      <el-button :icon="Refresh" @click="loadAlgorithms">刷新</el-button>
    </div>

    <div v-if="selectedVersion" class="test-layout">
      <section class="input-pane">
        <div class="pane-heading">
          <h3>预测输入</h3>
        </div>

        <el-collapse v-model="startSections" class="start-collapse">
          <el-collapse-item name="history">
            <template #title>
              <div class="start-collapse-title">
                <h4>从历史输入开始（可选）</h4>
                <small>
                  {{ templateOptions.length ? `${templateOptions.length} 条历史输入，可跳过` : '无历史输入，可跳过' }}
                </small>
              </div>
            </template>
            <div class="history-start">
              <el-select
                v-model="templateRunId"
                filterable
                clearable
                placeholder="从历史输入开始"
                :disabled="!templateOptions.length"
                @change="applySelectedTemplate"
              >
                <el-option v-for="item in templateOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-button :icon="CopyDocument" :disabled="!templateRuns.length" @click="applyLatestTemplate">载入最近成功输入</el-button>
              <span class="history-empty">
                {{ templateOptions.length ? `可选：从 ${templateOptions.length} 条历史输入开始；也可以跳过，直接新增记录。` : '可跳过：当前暂无历史模板，直接新增第一条配方即可。' }}
              </span>
            </div>
          </el-collapse-item>
        </el-collapse>

        <section class="input-step-section">
          <div class="step-section-head">
            <span>1</span>
            <h4>编辑输入</h4>
          </div>
          <el-form label-position="top" class="smart-input-form">
            <el-form-item
              v-for="key in schemaFields"
              :key="key"
              :class="{ 'json-form-item': canUseStructuredEditor(key) }"
            >
              <template #label>
                <span class="field-label">
                  {{ fieldLabel(key) }}
                  <em v-if="(selectedVersion?.input_schema?.required || []).includes(key)">*</em>
                  <small v-if="fieldHint(key).unit">{{ fieldHint(key).unit }}</small>
                </span>
                <span v-if="fieldHint(key).help" class="field-help">{{ fieldHint(key).help }}</span>
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
                <div class="flex-row nested-toolbar-right">
                  <el-button :icon="CopyDocument" @click="promptPasteData(key)">粘贴数据</el-button>
                  <el-button type="primary" plain :icon="Plus" @click="addArrayItem(key)">新增记录</el-button>
                </div>
              </div>
              <el-collapse v-if="arrayRows(key).length" class="schema-summary-collapse">
                <el-collapse-item :name="`schema-${key}`">
                  <template #title>
                    <span class="field-manager-title">字段显隐 · {{ visibleArrayColumns(key).length }} / {{ arrayColumns(key).length }} 个字段</span>
                  </template>
                  <div class="field-manager">
                    <div class="field-manager-list">
                      <div v-for="column in arrayColumns(key)" :key="column" class="field-manager-row">
                        <span class="field-column-name">{{ nestedFieldLabel(key, column) }}</span>
                        <el-tag size="small" effect="plain">{{ nestedValueKind(key, column, arrayRows(key)[0]) }}</el-tag>
                        <el-switch
                          :model-value="!hiddenColumns[key]?.has(column)"
                          size="small"
                          @update:model-value="toggleColumnVisibility(key, column, $event)"
                        />
                      </div>
                    </div>
                  </div>
                </el-collapse-item>
              </el-collapse>
              <div v-if="arrayRows(key).length" class="record-table-wrapper">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th class="row-num-col">#</th>
                      <th v-for="column in displayedArrayColumns(key)" :key="column">
                        {{ nestedFieldLabel(key, column) }}
                      </th>
                      <th class="row-actions-col"></th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(item, index) in arrayRows(key)" :key="index">
                      <td class="row-num-col">{{ index + 1 }}</td>
                      <td v-for="column in displayedArrayColumns(key)" :key="column" class="editable-cell">
                        <el-input-number
                          v-if="nestedValueKind(key, column, item) === 'number'"
                          :model-value="item[column]"
                          :step="nestedNumberStep(column)"
                          size="small"
                          :controls="false"
                          @update:model-value="setNestedValue(item, column, $event)"
                        />
                        <el-switch
                          v-else-if="nestedValueKind(key, column, item) === 'boolean'"
                          :model-value="item[column]"
                          size="small"
                          @update:model-value="setNestedValue(item, column, $event)"
                        />
                        <el-input
                          v-else
                          :model-value="item[column]"
                          size="small"
                          @update:model-value="setNestedValue(item, column, $event)"
                        />
                      </td>
                      <td class="row-actions-col">
                        <el-button text :icon="CopyDocument" size="small" @click="copyArrayItem(key, index)" />
                        <el-button text :icon="Delete" size="small" @click="removeArrayItem(key, index)" />
                      </td>
                    </tr>
                  </tbody>
                </table>
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
              </div>
              <div class="record-fields">
                <label v-for="column in objectColumns(key)" :key="column" class="nested-field">
                  <span>{{ nestedFieldLabel(key, column) }}</span>
                  <div class="object-field-row">
                    <el-input-number
                      v-if="nestedValueKind(key, column, inputs[key]) === 'number'"
                      :model-value="inputs[key]?.[column]"
                      :step="nestedNumberStep(column)"
                      class="full-control"
                      @update:model-value="setNestedValue(inputs[key], column, $event)"
                    />
                    <el-switch
                      v-else-if="nestedValueKind(key, column, inputs[key]) === 'boolean'"
                      :model-value="inputs[key]?.[column]"
                      @update:model-value="setNestedValue(inputs[key], column, $event)"
                    />
                    <el-input v-else :model-value="inputs[key]?.[column]" @update:model-value="setNestedValue(inputs[key], column, $event)" />
                  </div>
                </label>
              </div>
            </div>
            <el-input
              v-else
              :model-value="inputs[key]"
              :placeholder="fieldHint(key).placeholder"
              @update:model-value="setScalarValue(key, $event)"
            />
            </el-form-item>
          </el-form>
          <div v-if="inputAssets.length" class="asset-input-list">
            <label v-for="asset in inputAssets" :key="asset.key" class="asset-input-field">
              <span class="field-label">
                {{ assetLabel(asset) }}
                <em v-if="asset.required">*</em>
              </span>
              <input
                class="asset-file-input"
                type="file"
                :accept="assetAccept(asset)"
                @change="setInputAssetFile(asset.key, $event.target.files?.[0] || null)"
              >
              <small v-if="inputFiles[asset.key]">{{ inputFiles[asset.key].name }}</small>
              <small v-else>{{ assetHint(asset) }}</small>
            </label>
          </div>
        </section>

        <el-collapse v-model="advancedSections" class="advanced-settings">
          <el-collapse-item title="高级设置" name="settings">
            <div class="advanced-mode-row">
              <div>
                <strong>原始输入 JSON</strong>
                <span>这里和上方表单是同一份输入；粘贴 JSON 后会同步回表单。</span>
              </div>
            </div>
            <div class="json-editor">
              <el-input :model-value="fullJsonDraft" type="textarea" :rows="20" class="code-input" @update:model-value="updateFullJson" />
              <el-alert v-if="jsonParseError" class="json-error" :title="jsonParseError" type="error" :closable="false" show-icon />
            </div>
          </el-collapse-item>
        </el-collapse>

        <section class="input-step-section run-step-section">
          <div class="step-section-head">
            <span>2</span>
            <h4>运行预测</h4>
          </div>
          <div class="input-actions">
            <el-button type="primary" :icon="VideoPlay" :loading="running" :disabled="Boolean(runBlocker)" @click="runPrediction">运行指定版本</el-button>
            <el-button :icon="Refresh" @click="resetInputs">重置输入</el-button>
            <span class="run-status" :class="{ 'is-ready': !runBlocker }">{{ runBlocker || '输入已就绪，可以运行预测。' }}</span>
          </div>
        </section>
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
            :output-schema="selectedVersion?.output_schema"
            :status="lastRun.status"
            :error="lastRun.error"
            :attributions="selectedAttributions"
            :algorithm-id="algorithmId"
            :run-id="lastRun.run_id"
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
.pane-heading h3 { margin: 0; font-size: 15px; }
.history-start, .input-actions, .nested-toolbar, .object-field-row, .scalar-array-row, .advanced-mode-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.step-section-head span {
  display: inline-grid;
  place-items: center;
  width: 22px;
  height: 22px;
  flex: 0 0 22px;
  border-radius: 50%;
  background: #eef4ff;
  color: var(--app-primary-active);
  font-size: 12px;
  font-weight: 800;
  line-height: 1;
}
.input-step-section {
  display: grid;
  gap: 12px;
  padding: 12px 0;
  border-top: 1px solid var(--app-border-soft);
}
.input-step-section:first-of-type {
  border-top: 0;
}
.start-collapse {
  border-top: 1px solid var(--app-border-soft);
  border-bottom: 1px solid var(--app-border-soft);
}
.start-collapse :deep(.el-collapse-item__header) {
  height: auto;
  min-height: 48px;
  padding: 10px 0;
  border-bottom: 0;
}
.start-collapse :deep(.el-collapse-item__wrap) {
  border-bottom: 0;
}
.start-collapse-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-width: 0;
  gap: 12px;
}
.start-collapse-title small {
  color: var(--app-ink-muted);
  font-size: 12px;
  font-weight: 600;
  overflow-wrap: anywhere;
}
.step-section-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.step-section-head h4 {
  margin: 0;
  color: var(--app-ink);
  font-size: 14px;
}
.history-start {
  flex-wrap: wrap;
}
.history-start .el-select {
  flex: 1 1 240px;
  min-width: 0;
}
.history-empty {
  flex: 1 1 100%;
  color: var(--app-ink-muted);
  font-size: 12px;
  line-height: 1.45;
}
.smart-input-form {
  display: grid;
  gap: 2px;
  min-width: 0;
  max-width: 100%;
  width: 100%;
}
.json-form-item {
  margin-bottom: 18px;
  min-width: 0;
  max-width: 100%;
  width: 100%;
}
.json-form-item :deep(.el-form-item__content) {
  display: block;
  min-width: 0;
  width: 100%;
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
.asset-input-list {
  display: grid;
  gap: 10px;
  margin-top: 4px;
}
.asset-input-field {
  display: grid;
  gap: 6px;
  padding: 10px 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #fff;
}
.asset-input-field small {
  color: var(--app-ink-muted);
  font-size: 12px;
  overflow-wrap: anywhere;
}
.asset-file-input {
  width: 100%;
  min-width: 0;
  color: var(--app-ink);
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
  background: #f8fbff;
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
.schema-summary-collapse {
  margin-bottom: 12px;
  border-top: 1px solid var(--app-border-soft);
  border-bottom: 1px solid var(--app-border-soft);
}
.schema-summary-collapse :deep(.el-collapse-item__header) {
  min-height: 42px;
  height: auto;
  color: var(--app-ink-body);
  font-size: 12px;
  font-weight: 700;
  background: transparent;
}
.schema-summary-collapse :deep(.el-collapse-item__wrap) {
  border-bottom: 0;
  background: transparent;
}
.field-manager-title {
  overflow-wrap: anywhere;
}
.field-manager {
  display: grid;
  gap: 6px;
  padding-bottom: 10px;
}
.field-manager-list {
  display: grid;
  gap: 6px;
}
.field-manager-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 72px 48px;
  align-items: center;
  gap: 8px;
}
.field-column-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--app-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.record-table-wrapper {
  overflow-x: auto;
  max-height: 520px;
  overflow-y: auto;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
}
.data-table thead th { position: sticky; top: 0; z-index: 1; }
.data-table thead th, .data-table tbody td { border-right: 1px solid #e8e8e8; }
.data-table thead th:last-child, .data-table tbody td:last-child { border-right: 0; }
.row-num-col { width: 40px; text-align: center !important; color: var(--app-ink-muted); font-size: 12px; font-weight: 600; }
.row-actions-col { width: 72px; white-space: nowrap; text-align: center !important; }
.editable-cell { min-width: 110px; }
.editable-cell .el-input, .editable-cell .el-input-number { width: 100%; }
.editable-cell :deep(.el-input__wrapper) { box-shadow: none; background: transparent; padding: 0 2px; }
.editable-cell :deep(.el-input__inner) { padding: 4px 6px; min-height: 28px; font-size: 13px; }
.editable-cell :deep(.el-input-number .el-input__inner) { text-align: left; }
.editable-cell:hover :deep(.el-input__wrapper) { box-shadow: 0 0 0 1px var(--app-primary-active) inset; }
.editable-cell:focus-within :deep(.el-input__wrapper) { box-shadow: 0 0 0 1.5px var(--app-primary-active) inset; }
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
.advanced-settings {
  border-top: 1px solid var(--app-border-soft);
}
.advanced-mode-row {
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.advanced-mode-row > div {
  display: grid;
  gap: 2px;
}
.advanced-mode-row strong {
  color: var(--app-ink);
  font-size: 13px;
}
.advanced-mode-row span,
.run-status {
  color: var(--app-ink-muted);
  font-size: 12px;
  line-height: 1.45;
}
.json-error {
  margin-top: 2px;
}
.input-actions {
  flex-wrap: wrap;
}
.run-status {
  flex: 1 1 220px;
}
.run-status.is-ready {
  color: #047857;
  font-weight: 700;
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
  .start-collapse-title {
    align-items: flex-start;
    flex-direction: column;
    gap: 6px;
  }
  .test-toolbar, .pane-heading, .history-start, .nested-toolbar, .input-actions, .advanced-mode-row {
    align-items: stretch;
    flex-direction: column;
  }
  .test-toolbar :deep(.el-select), .history-start .el-select, .input-actions .el-button {
    width: 100% !important;
    max-width: none;
  }
  .run-status {
    flex-basis: auto;
  }
  .record-fields {
    grid-template-columns: 1fr;
  }
  .run-overview {
    grid-template-columns: 1fr;
  }
}
</style>
<style>
.paste-data-dialog {
  width: 640px;
  max-width: 92vw;
}
.paste-data-dialog .el-message-box__message {
  margin-bottom: 10px;
  color: var(--app-ink-muted, #666);
  font-size: 13px;
  line-height: 1.5;
}
.paste-data-dialog .el-textarea__inner {
  min-height: 260px;
  font-family: var(--app-mono-font, 'Consolas', 'Courier New', monospace);
  font-size: 13px;
  line-height: 1.6;
  resize: vertical;
}
</style>
