<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
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
const newNestedField = ref({})
const newNestedValue = ref({})
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
    input_schema: algorithm.input_schema || {},
    output_schema: algorithm.output_schema || {},
    input_assets: algorithm.input_assets || [],
    output_assets: algorithm.output_assets || [],
    resource_assets: algorithm.resource_assets || [],
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
  label: `${formatDate(run.created_at)} · ${summarizeInput(run.input_snapshot)}`,
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
  if (missingRequiredFields.value.length) return `补齐标记 * 的字段：${missingRequiredFields.value.join('、')}`
  const missingAssets = requiredInputAssets.value.filter((item) => !inputFiles.value[item.key])
  if (missingAssets.length) return `上传必填文件：${missingAssets.map(assetLabel).join('、')}`
  if (hasBlankPrimaryRecords.value) return `请先填写至少一条${primaryArrayObjectKey.value === 'formulations' ? '配方' : '记录'}的字段值。`
  return ''
})
const inputGuidance = computed(() => {
  if (requiredInputAssets.value.some((item) => !inputFiles.value[item.key])) return '补齐必填文件后再运行。'
  if (primaryArrayObjectKey.value && !primaryRecords.value.length) return '先新增一条配方，或从历史输入开始。'
  if (missingRequiredFields.value.length) return '补齐标记 * 的字段。'
  if (jsonParseError.value) return '修正高级设置中的 JSON 后再运行。'
  if (hasBlankPrimaryRecords.value) return '填写至少一条配方的字段值，或从历史输入开始。'
  return '输入已就绪，可以运行预测。'
})
const advancedFieldKeys = computed(() => schemaFields.value.filter((key) => isArrayObjectField(key) || isObjectField(key)))

watch(() => props.refreshKey, loadAlgorithms)
watch(() => props.algorithmId, loadAlgorithms)
watch(algorithmId, handleAlgorithmChanged)
watch(versionId, resetInputs)
watch(inputs, syncFullJsonDraft, { deep: true })

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
  syncFullJsonDraft()
  lastRun.value = null
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
    inputs.value = parsed
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

function ensureArrayValue(key) {
  if (!Array.isArray(inputs.value[key])) inputs.value[key] = []
}

function ensureObjectValue(key) {
  if (!isPlainObject(inputs.value[key])) inputs.value[key] = {}
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
  if (!keys.size) defaultArrayColumns(key).forEach((column) => keys.add(column))
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

function collapsedArrayColumns(key) {
  const core = new Set(coreArrayColumns(key))
  return arrayColumns(key).filter((column) => !core.has(column))
}

function coreArrayColumns(key) {
  const explicit = fieldHint(key).core_columns || fieldHint(key).primary_columns
  const columns = arrayColumns(key)
  const visible = Array.isArray(explicit) && explicit.length
    ? explicit.map(String).filter((column) => columns.includes(column))
    : visibleArrayColumns(key)
  if (visible.length <= 6) return visible
  const priority = [
    'formula_id',
    'id',
    'name',
    'title',
    'task_type',
    'smiles',
    'psmiles',
    'polymer_smiles',
    'material',
    'component',
    'composition',
    'mass_fraction',
    'weight_fraction',
    'volume_fraction',
    'ratio',
    'solvent',
    'salt',
    'additive',
  ]
  const ranked = [...visible].sort((a, b) => {
    const left = priority.includes(a) ? priority.indexOf(a) : priority.length + visible.indexOf(a)
    const right = priority.includes(b) ? priority.indexOf(b) : priority.length + visible.indexOf(b)
    return left - right
  })
  return ranked.slice(0, 6)
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
  const value = parseCustomFieldValue(newNestedValue.value[key])
  ensureArrayValue(key)
  if (!inputs.value[key].length) inputs.value[key].push({})
  inputs.value[key].forEach((item) => {
    if (isPlainObject(item) && !Object.prototype.hasOwnProperty.call(item, name)) item[name] = cloneJson(value)
  })
  newNestedField.value[key] = ''
  newNestedValue.value[key] = ''
  syncFullJsonDraft()
}

function addNestedFieldToObject(key) {
  const name = String(newNestedField.value[key] || '').trim()
  if (!name) return
  const value = parseCustomFieldValue(newNestedValue.value[key])
  ensureObjectValue(key)
  if (!Object.prototype.hasOwnProperty.call(inputs.value[key], name)) inputs.value[key][name] = value
  newNestedField.value[key] = ''
  newNestedValue.value[key] = ''
  syncFullJsonDraft()
}

function removeObjectField(key, field) {
  ensureObjectValue(key)
  delete inputs.value[key][field]
  syncFullJsonDraft()
}

function addAdvancedField(key) {
  if (isArrayObjectField(key)) addNestedFieldToArray(key)
  else if (isObjectField(key)) addNestedFieldToObject(key)
}

function itemTitle(key, item, index) {
  const titleKey = fieldHint(key).item_title_key || ['formula_id', 'id', 'name', 'title'].find((candidate) => item?.[candidate])
  return titleKey && item?.[titleKey] ? String(item[titleKey]) : `${fieldLabel(key)} ${index + 1}`
}

function firstRecordButtonLabel(key) {
  return key === 'formulations' ? '新增第一条配方' : '新增第一条记录'
}

function addRecordButtonLabel(key) {
  return key === 'formulations' ? '新增配方' : '新增记录'
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

function defaultValueForColumn(column, sourceValue) {
  if (sourceValue !== undefined) return defaultValueFrom(sourceValue)
  const normalized = String(column || '').toLowerCase()
  if (['is_', 'has_', 'enable_', 'enabled_', 'use_'].some((prefix) => normalized.startsWith(prefix))) return false
  if ([
    'amount',
    'concentration',
    'count',
    'density',
    'fraction',
    'mol',
    'mol_l',
    'molar',
    'number',
    'percent',
    'percentage',
    'ratio',
    'temperature',
    'value',
    'weight',
  ].some((token) => normalized.includes(token))) return 0
  return ''
}

function parseCustomFieldValue(value) {
  const text = String(value ?? '').trim()
  if (!text) return ''
  if (text === 'true') return true
  if (text === 'false') return false
  if (!Number.isNaN(Number(text)) && text !== '') return Number(text)
  return text
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
  const missingAssets = requiredInputAssets.value.filter((item) => !inputFiles.value[item.key])
  if (missingAssets.length) return `请上传必填文件 ${missingAssets.map(assetLabel).join('、')}`
  for (const asset of inputAssets.value) {
    const file = inputFiles.value[asset.key]
    if (!file) continue
    if (asset.max_size_bytes && file.size > asset.max_size_bytes) return `${assetLabel(asset)} 超过大小限制`
    const suffix = file.name.includes('.') ? `.${file.name.split('.').pop().toLowerCase()}` : ''
    const extensions = (asset.extensions || []).map((item) => String(item).toLowerCase())
    if (extensions.length && !extensions.includes(suffix)) return `${assetLabel(asset)} 文件类型不受支持`
  }
  return ''
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
  const errorMessage = validateInputs()
  if (errorMessage) {
    ElMessage.warning(errorMessage)
    return
  }
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
    ElMessage.error(getApiErrorMessage(error))
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
  ].filter(isPublicAttribution)
}

function authorLabel(algorithm) {
  const attribution = algorithm?.developer_attribution
  const developer = cleanAuthorValue(attribution?.name) || cleanAuthorValue(algorithm?.owner)
  const organization = cleanAuthorValue(attribution?.organization)
  if (developer && organization) return `${developer} / ${organization}`
  return developer || organization || '未标注'
}

function cleanAuthorValue(value) {
  const text = String(value || '').trim()
  const normalized = text.toLowerCase()
  if (!text) return ''
  if (['anonymous', 'demo_user', 'system', 'raman demo adapter', 'local raman reference'].includes(normalized)) return ''
  if (/^u_[0-9a-z]{8,}$/i.test(text)) return ''
  return text
}

function isPublicAttribution(item) {
  const name = cleanAuthorValue(item?.name)
  const organization = cleanAuthorValue(item?.organization)
  return Boolean(item && (name || organization))
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
          <div>
            <h3>预测输入</h3>
            <span>{{ selectedVersion.algorithm_id }} / {{ selectedVersion.version }}</span>
            <small>作者：{{ authorLabel(selectedAlgorithm) }}</small>
          </div>
        </div>

        <div class="prediction-steps" aria-label="预测流程">
          <div class="prediction-step is-done"><span>1</span><strong>选择起点</strong></div>
          <div class="prediction-step is-active"><span>2</span><strong>填写输入</strong></div>
          <div class="prediction-step"><span>3</span><strong>查看结果</strong></div>
        </div>

        <el-alert class="input-guidance" :title="inputGuidance" type="info" :closable="false" show-icon />

        <el-collapse v-model="startSections" class="start-collapse">
          <el-collapse-item name="history">
            <template #title>
              <div class="start-collapse-title">
                <div class="step-section-head">
                  <span>1</span>
                  <h4>可选起点</h4>
                </div>
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
                {{ templateOptions.length ? `可选：从 ${templateOptions.length} 条历史输入开始；也可以跳过，直接新增配方。` : '可跳过：当前暂无历史模板，直接新增第一条配方即可。' }}
              </span>
            </div>
          </el-collapse-item>
        </el-collapse>

        <section class="input-step-section">
          <div class="step-section-head">
            <span>2</span>
            <h4>编辑配方</h4>
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
              <div v-if="arrayRows(key).length" class="nested-toolbar">
                <div class="nested-count">{{ arrayRows(key).length }} 条记录</div>
                <el-button type="primary" plain :icon="Plus" @click="addArrayItem(key)">{{ addRecordButtonLabel(key) }}</el-button>
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
                    <label v-for="column in coreArrayColumns(key)" :key="column" class="nested-field">
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
                  <p class="record-ready-hint">填写可见字段即可开始；更多字段和原始 JSON 在高级设置中调整。</p>
                </article>
              </div>
              <div v-else class="nested-empty">
                <el-button type="primary" :icon="Plus" @click="addArrayItem(key)">{{ firstRecordButtonLabel(key) }}</el-button>
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
            <div v-if="advancedFieldKeys.length" class="advanced-field-tools">
              <div v-for="key in advancedFieldKeys" :key="key" class="advanced-field-row">
                <span>{{ fieldLabel(key) }}</span>
                <el-input v-model="newNestedField[key]" placeholder="字段名" clearable @keyup.enter="addAdvancedField(key)" />
                <el-input v-model="newNestedValue[key]" placeholder="默认值（可选）" clearable @keyup.enter="addAdvancedField(key)" />
                <el-button :icon="Plus" @click="addAdvancedField(key)">新增字段</el-button>
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
            <span>3</span>
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
.pane-heading span, .pane-heading small { color: var(--app-ink-muted); font-size: 12px; }
.pane-heading small { display: block; margin-top: 4px; overflow-wrap: anywhere; }
.history-start, .input-actions, .nested-toolbar, .nested-actions, .record-actions, .object-field-row, .scalar-array-row, .advanced-mode-row, .advanced-field-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.prediction-steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 12px;
}
.prediction-step {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #fff;
  color: var(--app-ink-muted);
}
.prediction-step span,
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
.prediction-step strong {
  min-width: 0;
  font-size: 13px;
  overflow-wrap: anywhere;
}
.prediction-step.is-active {
  border-color: var(--app-primary-active);
  color: var(--app-ink);
}
.prediction-step.is-done {
  color: var(--app-ink);
  background: #f8fbff;
}
.input-guidance {
  margin-bottom: 12px;
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
.record-ready-hint {
  margin: 10px 0 0;
  color: var(--app-ink-muted);
  font-size: 12px;
  line-height: 1.45;
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
.advanced-mode-row strong,
.advanced-field-row > span {
  color: var(--app-ink);
  font-size: 13px;
}
.advanced-mode-row span,
.run-status {
  color: var(--app-ink-muted);
  font-size: 12px;
  line-height: 1.45;
}
.advanced-field-tools {
  display: grid;
  gap: 8px;
  margin-bottom: 12px;
}
.advanced-field-row {
  flex-wrap: wrap;
}
.advanced-field-row > span {
  flex: 0 0 120px;
  overflow-wrap: anywhere;
}
.advanced-field-row .el-input {
  flex: 1 1 180px;
  min-width: 0;
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
  .prediction-steps {
    grid-template-columns: 1fr;
  }
  .start-collapse-title {
    align-items: flex-start;
    flex-direction: column;
    gap: 6px;
  }
  .test-toolbar, .pane-heading, .history-start, .nested-toolbar, .nested-actions, .input-actions, .advanced-mode-row, .advanced-field-row {
    align-items: stretch;
    flex-direction: column;
  }
  .test-toolbar :deep(.el-select), .history-start .el-select, .nested-actions .el-input, .input-actions .el-button, .advanced-field-row .el-input, .advanced-field-row .el-button {
    width: 100% !important;
    max-width: none;
  }
  .advanced-field-row > span,
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
