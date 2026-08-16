<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Box, Check, Delete, Download, Plus, UploadFilled } from '@element-plus/icons-vue'

import {
  createAlgorithmResource,
  downloadAlgorithmPackage,
  downloadAlgorithmPackageTemplate,
  getApiErrorMessage,
  inspectAlgorithmPackage,
  listAlgorithmResources,
  packAlgorithmPackage,
  packAlgorithmVersionPackage,
  releaseAlgorithmPackage,
  uploadAlgorithmPackage,
} from '../../api/polyAgentApi'
import { suggestNextPatch } from '../../utils/verticalPredictionState.mjs'

const props = defineProps({
  mode: { type: String, default: 'new_algorithm' },
  targetAlgorithm: { type: Object, default: null },
  targetVersion: { type: Object, default: null },
  targetVersions: { type: Array, default: () => [] },
})
const emit = defineEmits(['changed', 'view-detail'])

const currentStep = ref(props.mode === 'new_version' ? 1 : 0)
const uploadMode = ref('script')
const loading = ref(false)
const sourceFiles = ref([])
const requirementsFiles = ref([])
const zipFiles = ref([])
const zipInspect = ref(null)
const zipInspectError = ref('')
const zipInspecting = ref(false)
const currentPackage = ref(null)
const sourceUploadRef = ref(null)
const requirementsUploadRef = ref(null)
const zipUploadRef = ref(null)
const expandedAdvanced = ref([])
const availableResources = reactive({})
const selectedResourceIds = reactive({})
const resourceDrafts = reactive({})
const registeringResourceKey = ref('')
const isNewVersion = computed(() => props.mode === 'new_version')
const submitVersion = computed(() => (
  uploadMode.value === 'zip' ? (zipInspect.value?.version || '—') : form.version
))
const effectiveVisibilityText = computed(() => {
  const label = (value) => (value === 'public' ? '公开发布' : '非公开发布')
  if (isNewVersion.value && uploadMode.value === 'zip') {
    if (!zipInspect.value?.version) return { label: '待选择 ZIP 后确定', hint: '以包内 polyagent.algorithm.yaml 为准' }
    if (zipInspect.value.visibility) return { label: label(zipInspect.value.visibility), hint: '以 polyagent.algorithm.yaml 为准' }
    return { label: label('private'), hint: 'YAML 未声明，默认非公开' }
  }
  return { label: label(form.visibility || 'private'), hint: '继承自活跃版本' }
})
const declaredResourceAssets = computed(() => currentPackage.value?.resource_assets || [])
const unresolvedRequiredBindings = computed(() => declaredResourceAssets.value.filter(
  (spec) => spec.binding_required && !selectedResourceIds[spec.key],
))

const uploadModeOptions = [
  {
    value: 'script',
    title: 'Python 脚本自动打包',
    description: '上传源码、依赖和样例输入，平台生成标准 ZIP 并完成校验部署。',
    icon: UploadFilled,
    tags: ['推荐', '自动生成契约', '适合首次接入'],
  },
  {
    value: 'zip',
    title: '标准 ZIP 直接上传',
    description: '适合已经按平台规范准备好的模型包，需包含 polyagent.algorithm.yaml。',
    icon: Box,
    tags: ['已有接入包', '保留目录结构'],
  },
]

const form = reactive({
  algorithm_id: 'vertical_tg_predictor',
  name: 'Polymer Tg Predictor',
  version: '0.1.0',
  algorithm_family: 'vertical_prediction',
  type: 'predictor',
  material_scope: ['universal'],
  task_scope: ['COMPUTE_PREDICT'],
  trigger_modes: ['human_workflow', 'autoresearch'],
  entrypoint: 'src.handler:predict',
  loader: 'src.handler:load',
  description: '',
  developer: '',
  developer_organization: '',
  mentor_team: '',
  developer_contact: '',
  source_url: '',
  citation: '',
  logo_asset: '',
  logo_url: '',
  visibility: 'private',
  sample_input: JSON.stringify({ smiles: 'C=C(F)F' }, null, 2),
  input_assets: '[]',
  output_assets: '[]',
  resource_assets: '[]',
  result_envelope: '',
})

const inputFields = ref([
  { name: 'smiles', type: 'string', required: true, unit: '', options: '', min: '', max: '' },
])
const outputFields = ref([
  { name: 'prediction', type: 'object', required: true, unit: '', options: '', min: '', max: '' },
])
const inputAssetRows = ref([])
const outputAssetRows = ref([])
const resourceAssetRows = ref([])
const contributorRows = ref([])

const dataKindOptions = [
  { label: '表格', value: 'table' },
  { label: '序列', value: 'series' },
  { label: '图片', value: 'image' },
  { label: 'JSON', value: 'json' },
  { label: '文本', value: 'text' },
  { label: '二进制', value: 'binary' },
]
const parserOptions = [
  { label: '自动', value: 'auto' },
  { label: '表格 table.v1', value: 'table.v1' },
  { label: 'x-y 序列 series_xy.v1', value: 'series_xy.v1' },
  { label: 'JSON json.v1', value: 'json.v1' },
  { label: '文本 text.v1', value: 'text.v1' },
  { label: '二进制 binary.v1', value: 'binary.v1' },
]
const artifactTypeOptions = ['result_json', 'structure_json', 'table_json', 'series_json', 'metrics_json', 'report_json', 'image_png', 'csv', 'binary_file']

const sampleJsonError = computed(() => {
  try {
    const value = JSON.parse(form.sample_input)
    return value && typeof value === 'object' && !Array.isArray(value) ? '' : '样例输入必须是 JSON object'
  } catch (error) {
    return `JSON 格式错误：${error.message}`
  }
})

const assetJsonError = computed(() => {
  for (const [label, value] of [
    ['输入文件规格', form.input_assets],
    ['输出文件规格', form.output_assets],
    ['受管资源需求', form.resource_assets],
  ]) {
    try {
      const parsed = JSON.parse(value || '[]')
      if (!Array.isArray(parsed)) return `${label} 必须是 JSON array`
    } catch (error) {
      return `${label} JSON 格式错误：${error.message}`
    }
  }
  return ''
})

const parsedInputAssets = computed(() => assetRowsToSpecs(inputAssetRows.value, 'input'))
const parsedOutputAssets = computed(() => assetRowsToSpecs(outputAssetRows.value, 'output'))
const parsedResourceAssets = computed(() => assetRowsToSpecs(resourceAssetRows.value, 'resource'))

const contract = computed(() => ({
  contract_version: parsedInputAssets.value.length || parsedOutputAssets.value.length || parsedResourceAssets.value.length || form.result_envelope ? '0.2' : '0.1',
  algorithm_id: form.algorithm_id,
  name: form.name,
  version: form.version,
  algorithm_family: form.algorithm_family,
  type: form.type,
  material_scope: form.material_scope,
  task_scope: form.task_scope,
  trigger_modes: form.trigger_modes,
  entrypoint: form.entrypoint,
  loader: form.loader || null,
  runtime: {
    python: '3.11',
    resources: { cpu: 1, memory: '1Gi', gpu: false },
    timeout_seconds: 30,
  },
  input_schema: schemaFromRows(inputFields.value),
  output_schema: schemaFromRows(outputFields.value),
  input_assets: parsedInputAssets.value,
  output_assets: parsedOutputAssets.value,
  resource_assets: parsedResourceAssets.value,
  result_envelope: form.result_envelope || null,
  sample_input_path: 'tests/sample_input.json',
  description: form.description || null,
  developer: form.developer || null,
  developer_organization: form.developer_organization || null,
  mentor_team: form.mentor_team || null,
  developer_contact: form.developer_contact || null,
  source_url: form.source_url || null,
  citation: form.citation || null,
  contributors: contributorsPayload(),
  method_attributions: [],
  logo_asset: form.logo_asset || null,
  logo_url: form.logo_url || null,
  visibility: form.visibility,
}))

const contractPreview = computed(() => toYaml(contract.value))

const processSteps = computed(() => {
  const status = currentPackage.value?.status || ''
  return [
    { title: uploadMode.value === 'zip' ? '上传标准 ZIP' : '生成标准 ZIP', done: Boolean(currentPackage.value), text: currentPackage.value?.filename || '等待提交' },
    { title: '校验契约', done: ['validated', 'built', 'deployed_staging', 'active'].includes(status), text: currentPackage.value?.validation_logs?.[0] || '校验文件、schema 与入口函数' },
    { title: '构建部署', done: ['deployed_staging', 'active'].includes(status), text: currentPackage.value?.deployment_logs?.[0] || currentPackage.value?.build_logs?.at(-1) || '构建运行环境并部署版本' },
    { title: '激活可用', done: status === 'active', text: status === 'active' ? '版本已进入模型中心' : '等待激活' },
  ]
})

const uploadStepTitle = computed(() => {
  const titles = [
    '选择上传方式',
    isNewVersion.value ? '上传新版本内容' : (uploadMode.value === 'zip' ? '上传标准 ZIP' : '填写信息并上传文件'),
    '校验部署',
    '完成',
  ]
  return titles[currentStep.value] || titles[0]
})

watch(
  () => [props.mode, props.targetAlgorithm, props.targetVersion, props.targetVersions],
  () => {
    if (!isNewVersion.value || !props.targetAlgorithm || currentStep.value === 3) return
    const contract = props.targetVersion?.contract || {}
    form.algorithm_id = props.targetAlgorithm.algorithm_id
    form.name = props.targetAlgorithm.name || contract.name || props.targetAlgorithm.algorithm_id
    form.version = suggestNextPatch(props.targetVersions)
    form.visibility = props.targetVersion?.visibility || props.targetAlgorithm?.visibility || 'private'
    form.sample_input = JSON.stringify(contract.sample_input || {}, null, 2)
    if (currentStep.value === 0) currentStep.value = 1
  },
  { immediate: true, deep: true },
)

function schemaFromRows(rows) {
  const fields = {}
  const required = []
  const constraints = {}
  const fieldOptions = {}
  const uiHints = {}
  for (const row of rows) {
    const name = row.name.trim()
    if (!name) continue
    fields[name] = row.type
    if (row.required) required.push(name)
    const constraint = {}
    if (row.min !== '') constraint.min = Number(row.min)
    if (row.max !== '') constraint.max = Number(row.max)
    if (Object.keys(constraint).length) constraints[name] = constraint
    const options = row.options.split(',').map((item) => item.trim()).filter(Boolean)
    if (options.length) fieldOptions[name] = options
    if (row.unit.trim()) uiHints[name] = { unit: row.unit.trim() }
  }
  return { fields, required, constraints, field_options: fieldOptions, ui_hints: uiHints }
}

function parseJsonArray(value) {
  try {
    const parsed = JSON.parse(value || '[]')
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function newAssetRow(kind) {
  if (kind === 'resource') {
    return { key: '', label: '', required: true, data_kind: 'binary', parser: 'binary.v1', extensions: '', mime_types: '', max_size_bytes: '', sample_path: '', artifact_type: '', mime_type: '', env_var: '', resource_type: '', required_files: '', binding_required: true, description: '' }
  }
  if (kind === 'output') {
    return { key: '', label: '', required: false, data_kind: 'json', parser: 'json.v1', extensions: '.json', mime_types: 'application/json', max_size_bytes: '', sample_path: '', artifact_type: 'result_json', mime_type: 'application/json', env_var: '', description: '' }
  }
  return { key: '', label: '', required: true, data_kind: 'table', parser: 'auto', extensions: '.csv,.xlsx', mime_types: 'text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', max_size_bytes: '10485760', sample_path: '', artifact_type: '', mime_type: '', env_var: '', description: '' }
}

function addAssetRow(target, kind) {
  target.push(newAssetRow(kind))
}

function removeAssetRow(target, index) {
  target.splice(index, 1)
}

function assetRowsToSpecs(rows, kind) {
  return rows.map((row) => {
    const spec = {
      key: String(row.key || '').trim(),
      label: String(row.label || '').trim() || null,
      required: Boolean(row.required),
      asset_role: kind,
      data_kind: row.data_kind || null,
      parser: row.parser || null,
      extensions: splitList(row.extensions),
      mime_types: splitList(row.mime_types),
      max_size_bytes: row.max_size_bytes === '' ? null : Number(row.max_size_bytes),
      sample_path: String(row.sample_path || '').trim() || null,
      artifact_type: String(row.artifact_type || '').trim() || null,
      mime_type: String(row.mime_type || '').trim() || null,
      env_var: String(row.env_var || '').trim() || null,
      resource_type: String(row.resource_type || '').trim() || null,
      required_files: splitList(row.required_files),
      binding_required: Boolean(row.binding_required),
      description: String(row.description || '').trim() || null,
    }
    if (kind !== 'resource') {
      delete spec.resource_type
      delete spec.required_files
      delete spec.binding_required
    }
    Object.keys(spec).forEach((key) => {
      if (spec[key] === null || (Array.isArray(spec[key]) && !spec[key].length)) delete spec[key]
    })
    return spec
  }).filter((item) => item.key)
}

function splitList(value) {
  return String(value || '').split(',').map((item) => item.trim()).filter(Boolean)
}

function applyAssetJsonDraft(target, key) {
  const parsed = parseJsonArray(form[key])
  target.splice(0, target.length, ...parsed.map((item) => ({
    key: item.key || '',
    label: item.label || '',
    required: Boolean(item.required),
    data_kind: item.data_kind || '',
    parser: item.parser || '',
    extensions: (item.extensions || []).join(','),
    mime_types: (item.mime_types || []).join(','),
    max_size_bytes: item.max_size_bytes || '',
    sample_path: item.sample_path || '',
    artifact_type: item.artifact_type || '',
    mime_type: item.mime_type || '',
    env_var: item.env_var || '',
    resource_type: item.resource_type || '',
    required_files: (item.required_files || []).join(','),
    binding_required: Boolean(item.binding_required),
    description: item.description || '',
  })))
}

watch(parsedInputAssets, (value) => { form.input_assets = JSON.stringify(value, null, 2) }, { deep: true })
watch(parsedOutputAssets, (value) => { form.output_assets = JSON.stringify(value, null, 2) }, { deep: true })
watch(parsedResourceAssets, (value) => { form.resource_assets = JSON.stringify(value, null, 2) }, { deep: true })

function toYaml(value, depth = 0) {
  const indent = '  '.repeat(depth)
  if (Array.isArray(value)) return value.length ? `[${value.map((item) => JSON.stringify(item)).join(', ')}]` : '[]'
  if (value && typeof value === 'object') {
    return Object.entries(value).map(([key, item]) => {
      if (item && typeof item === 'object' && !Array.isArray(item)) {
        return `${indent}${key}:\n${toYaml(item, depth + 1)}`
      }
      return `${indent}${key}: ${toYaml(item, depth + 1)}`
    }).join('\n')
  }
  if (value === null) return 'null'
  if (typeof value === 'string') return JSON.stringify(value)
  return String(value)
}

function addField(target) {
  target.push({ name: '', type: 'string', required: false, unit: '', options: '', min: '', max: '' })
}

function removeField(target, index) {
  target.splice(index, 1)
}

function addContributorRow() {
  contributorRows.value.push({
    user_id: '',
    name: '',
    role: 'developer',
    organization: form.developer_organization || '',
    mentor_relation: '',
    description: '',
  })
}

function removeContributorRow(index) {
  contributorRows.value.splice(index, 1)
}

function contributorsPayload() {
  return contributorRows.value
    .map((row) => ({
      user_id: String(row.user_id || '').trim() || null,
      name: String(row.name || '').trim(),
      role: String(row.role || '').trim() || 'developer',
      organization: String(row.organization || '').trim() || null,
      mentor_relation: String(row.mentor_relation || '').trim() || null,
      description: String(row.description || '').trim() || null,
    }))
    .filter((item) => item.name && item.role)
}

function saveBlob(file) {
  const url = URL.createObjectURL(file.blob)
  const link = document.createElement('a')
  link.href = url
  link.download = file.filename
  link.click()
  URL.revokeObjectURL(url)
}

function openUploadPicker(uploadRef) {
  const instance = uploadRef?.value || uploadRef
  const input = instance?.$el?.querySelector('input[type="file"]') || instance?.querySelector?.('input[type="file"]')
  input?.click()
}

function clearFileList(target) {
  target.splice(0, target.length)
}

function replaceSingleFile(target, uploadRef) {
  clearFileList(target)
  openUploadPicker(uploadRef)
}

function formatFileSize(value) {
  const size = Number(value || 0)
  if (!size) return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

async function downloadTemplate() {
  try {
    saveBlob(await downloadAlgorithmPackageTemplate())
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  }
}

async function downloadGeneratedPackage() {
  if (!currentPackage.value?.package_id) return
  try {
    const fallbackName = currentPackage.value.filename
      || `${currentPackage.value.algorithm_id || form.algorithm_id}-${currentPackage.value.version || form.version}.zip`
    saveBlob(await downloadAlgorithmPackage(currentPackage.value.package_id, fallbackName))
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  }
}

function validateBeforeSubmit() {
  if (isNewVersion.value) {
    if (!props.targetAlgorithm?.algorithm_id) return '未找到目标模型，请返回模型详情后重试'
    if (uploadMode.value === 'zip') {
      if (!zipFiles.value[0]?.raw) return '请选择标准 ZIP 文件'
      if (zipInspecting.value) return '正在读取 ZIP 内契约，请稍候'
      if (!zipInspect.value?.version) return zipInspectError.value || '无法读取 ZIP 内契约，请检查 polyagent.algorithm.yaml'
      if (!/^\d+\.\d+\.\d+$/.test(zipInspect.value.version)) return 'ZIP 内版本号必须是 x.y.z 格式，请修改 polyagent.algorithm.yaml 后重试'
      if (props.targetVersions.some((item) => item.version === zipInspect.value.version)) return `该语义版本 ${zipInspect.value.version} 已存在，请修改 ZIP 内 YAML 的 version 后重试`
      if (zipInspect.value.algorithm_id && zipInspect.value.algorithm_id !== props.targetAlgorithm.algorithm_id) return 'ZIP 内算法 ID 与目标模型不一致，请检查 polyagent.algorithm.yaml'
      return ''
    }
    if (!/^\d+\.\d+\.\d+$/.test(form.version.trim())) return '版本号必须是 x.y.z 格式'
    if (props.targetVersions.some((item) => item.version === form.version.trim())) return '该语义版本已存在，请修改版本号'
    if (!sourceFiles.value.length) return '请至少选择一个 Python 源文件'
    return ''
  }
  if (uploadMode.value === 'zip') {
    if (!zipFiles.value[0]?.raw) return '请选择标准 ZIP 文件'
    return ''
  }
  if (!form.algorithm_id.trim()) return '请填写算法 ID'
  if (!form.name.trim()) return '请填写模型名称'
  if (!form.version.trim()) return '请填写版本号'
  if (!sourceFiles.value.length) return '请至少选择一个 Python 源文件'
  if (sampleJsonError.value) return sampleJsonError.value
  if (assetJsonError.value) return assetJsonError.value
  return ''
}

async function inspectSelectedZip() {
  const raw = zipFiles.value[0]?.raw
  zipInspect.value = null
  zipInspectError.value = ''
  if (!raw) return
  zipInspecting.value = true
  try {
    const data = new FormData()
    data.append('file', raw)
    zipInspect.value = await inspectAlgorithmPackage(data)
  } catch (error) {
    zipInspectError.value = getApiErrorMessage(error)
  } finally {
    zipInspecting.value = false
  }
}

function onZipFileChange() {
  currentStep.value = Math.max(currentStep.value, 1)
  inspectSelectedZip()
}

function goNext() {
  if (currentStep.value === 0) {
    currentStep.value = 1
    return
  }
  if (currentStep.value === 1) {
    const warning = validateBeforeSubmit()
    if (warning) {
      ElMessage.warning(warning)
      return
    }
    currentStep.value = 2
  }
}

function clearResourceBindingState() {
  for (const target of [availableResources, selectedResourceIds, resourceDrafts]) {
    Object.keys(target).forEach((key) => delete target[key])
  }
}

function goPrevious() {
  if (loading.value || currentStep.value === 0) return
  if (currentStep.value === 2) {
    currentPackage.value = null
    clearResourceBindingState()
  }
  currentStep.value -= 1
}

function resourceBindingsPayload() {
  return declaredResourceAssets.value
    .filter((spec) => selectedResourceIds[spec.key])
    .map((spec) => ({ asset_key: spec.key, resource_id: selectedResourceIds[spec.key] }))
}

async function prepareResourceBindings(pkg) {
  clearResourceBindingState()
  const inheritedBindings = new Map(
    (props.targetVersion?.resource_bindings || []).map((item) => [item.asset_key, item.resource_id]),
  )
  await Promise.all((pkg.resource_assets || []).map(async (spec) => {
    const response = await listAlgorithmResources({
      algorithm_id: pkg.algorithm_id || props.targetAlgorithm?.algorithm_id || form.algorithm_id,
      asset_key: spec.key,
      status: 'active',
      page_size: 100,
    })
    const items = response.items || []
    availableResources[spec.key] = items
    const inheritedId = inheritedBindings.get(spec.key)
    if (inheritedId && items.some((item) => item.resource_id === inheritedId)) {
      selectedResourceIds[spec.key] = inheritedId
    } else if (items.length === 1) {
      selectedResourceIds[spec.key] = items[0].resource_id
    } else {
      selectedResourceIds[spec.key] = ''
    }
    resourceDrafts[spec.key] = {
      expanded: false,
      name: spec.label || spec.key,
      path: '',
    }
  }))
}

async function registerInlineResource(spec) {
  const draft = resourceDrafts[spec.key]
  if (!draft?.path?.trim()) {
    ElMessage.warning('请填写后端宿主机可访问的资源路径')
    return
  }
  registeringResourceKey.value = spec.key
  try {
    const resource = await createAlgorithmResource({
      algorithm_id: currentPackage.value?.algorithm_id || props.targetAlgorithm?.algorithm_id || form.algorithm_id,
      asset_key: spec.key,
      name: draft.name.trim() || spec.label || spec.key,
      path: draft.path.trim(),
      storage_mode: 'mounted_path',
      resource_type: spec.resource_type || null,
      required_files: spec.required_files || [],
      description: spec.description || null,
    })
    availableResources[spec.key] = [resource, ...(availableResources[spec.key] || [])]
    selectedResourceIds[spec.key] = resource.resource_id
    draft.expanded = false
    ElMessage.success('资源路径已校验并绑定')
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    registeringResourceKey.value = ''
  }
}

async function finalizePackage(pkg) {
  currentPackage.value = await releaseAlgorithmPackage(pkg.package_id, resourceBindingsPayload())
}

async function submit() {
  const warning = validateBeforeSubmit()
  if (warning) {
    ElMessage.warning(warning)
    return
  }
  loading.value = true
  currentStep.value = 2
  try {
    let pkg = currentPackage.value
    if (!pkg && uploadMode.value === 'zip') {
      const data = new FormData()
      data.append('file', zipFiles.value[0].raw)
      if (isNewVersion.value) {
        data.append('target_algorithm_id', props.targetAlgorithm.algorithm_id)
      } else {
        data.append('visibility', form.visibility)
      }
      pkg = await uploadAlgorithmPackage(data)
    } else if (!pkg && isNewVersion.value) {
      const data = new FormData()
      data.append('target_algorithm_id', props.targetAlgorithm.algorithm_id)
      data.append('version', form.version.trim())
      data.append('sample_input', form.sample_input)
      sourceFiles.value.forEach((file) => data.append('files', file.raw))
      if (requirementsFiles.value[0]?.raw) data.append('requirements', requirementsFiles.value[0].raw)
      pkg = await packAlgorithmVersionPackage(data)
    } else if (!pkg) {
      const data = new FormData()
      for (const key of [
        'algorithm_id',
        'name',
        'version',
        'algorithm_family',
        'type',
        'entrypoint',
        'loader',
        'description',
        'developer',
        'developer_organization',
        'mentor_team',
        'developer_contact',
        'source_url',
        'citation',
        'logo_asset',
        'logo_url',
        'visibility',
      ]) {
        if (form[key]) data.append(key, form[key])
      }
      data.append('method_attributions', JSON.stringify(contract.value.method_attributions))
      data.append('contributors', JSON.stringify(contract.value.contributors))
      data.append('material_scope', JSON.stringify(form.material_scope))
      data.append('task_scope', JSON.stringify(form.task_scope))
      data.append('trigger_modes', JSON.stringify(form.trigger_modes))
      data.append('input_schema', JSON.stringify(contract.value.input_schema))
      data.append('output_schema', JSON.stringify(contract.value.output_schema))
      data.append('input_assets', JSON.stringify(contract.value.input_assets))
      data.append('output_assets', JSON.stringify(contract.value.output_assets))
      data.append('resource_assets', JSON.stringify(contract.value.resource_assets))
      if (contract.value.result_envelope) data.append('result_envelope', contract.value.result_envelope)
      data.append('runtime', JSON.stringify(contract.value.runtime))
      data.append('sample_input', form.sample_input)
      sourceFiles.value.forEach((file) => data.append('files', file.raw))
      if (requirementsFiles.value[0]?.raw) data.append('requirements', requirementsFiles.value[0].raw)
      pkg = await packAlgorithmPackage(data)
    }
    currentPackage.value = pkg
    if (declaredResourceAssets.value.length && !Object.keys(availableResources).length) {
      await prepareResourceBindings(pkg)
    }
    if (unresolvedRequiredBindings.value.length) {
      ElMessage.warning('请先为必需资源选择或登记后端挂载路径')
      return
    }
    await finalizePackage(pkg)
    currentStep.value = 3
    emit('changed', currentPackage.value)
    ElMessage.success(currentPackage.value?.rollback_status === 'completed' ? '模型版本已完成回滚' : '模型版本已完成校验、部署并激活')
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

function resetForNextUpload() {
  currentPackage.value = null
  currentStep.value = isNewVersion.value ? 1 : 0
  sourceFiles.value = []
  requirementsFiles.value = []
  zipFiles.value = []
  zipInspect.value = null
  zipInspectError.value = ''
  clearResourceBindingState()
}

function viewModelDetail() {
  const algorithmId = currentPackage.value?.algorithm_id || form.algorithm_id
  if (algorithmId) emit('view-detail', algorithmId)
}
</script>

<template>
  <div class="upload-workspace" v-loading="loading">
    <div class="wizard-shell">
      <div class="wizard-head">
        <div>
          <p class="wizard-eyebrow">{{ isNewVersion ? '上传新版本' : '高级导入' }}</p>
          <h2>{{ uploadStepTitle }}</h2>
          <p v-if="isNewVersion">目标模型已锁定；选择新脚本或标准 ZIP，确认版本后将直接校验、部署并激活。</p>
          <p v-else>Python 脚本会由平台打包为标准 ZIP；已有完整包时可直接上传标准 ZIP。</p>
        </div>
        <el-button :icon="Download" @click="downloadTemplate">下载标准模板</el-button>
      </div>
      <el-steps :active="isNewVersion ? currentStep - 1 : currentStep" finish-status="success" simple>
        <el-step v-if="!isNewVersion" title="选择方式" />
        <el-step title="上传内容" />
        <el-step title="校验部署" />
        <el-step title="完成" />
      </el-steps>
    </div>

    <section v-if="currentStep === 0" class="wizard-section step-card">
      <div class="section-heading">
        <div>
          <h3>选择上传方式</h3>
          <p>{{ isNewVersion ? '新脚本会继承当前活动版本的完整包内容和契约。' : '根据手头材料选择接入路径。首次接入建议使用 Python 脚本自动打包。' }}</p>
        </div>
      </div>
      <div class="upload-mode-grid" role="radiogroup" aria-label="选择上传方式">
        <button
          v-for="option in uploadModeOptions"
          :key="option.value"
          type="button"
          class="upload-mode-card"
          :class="{ active: uploadMode === option.value }"
          role="radio"
          :aria-checked="uploadMode === option.value"
          @click="uploadMode = option.value"
        >
          <span class="mode-icon"><el-icon><component :is="option.icon" /></el-icon></span>
          <span class="mode-copy">
            <strong>{{ option.title }}</strong>
            <small>{{ option.description }}</small>
          </span>
          <span class="mode-tags">
            <el-tag v-for="tag in option.tags" :key="tag" size="small" effect="plain">{{ tag }}</el-tag>
          </span>
        </button>
      </div>
    </section>

    <section v-else-if="currentStep === 1" class="wizard-section step-card">
      <div class="section-heading">
        <div>
          <h3>{{ isNewVersion ? '上传文件并确认版本' : (uploadMode === 'zip' ? '上传标准 ZIP' : '填写必要信息') }}</h3>
          <p>{{ isNewVersion ? '模型信息和契约均从当前活动版本继承；ZIP 模式的版本以包内 polyagent.algorithm.yaml 为准。' : (uploadMode === 'zip' ? 'ZIP 内需要包含 polyagent.algorithm.yaml，版本以包内 YAML 为准。' : '这几项会生成模型卡片、版本记录和测试表单。') }}</p>
        </div>
      </div>

      <el-segmented
        v-if="isNewVersion"
        v-model="uploadMode"
        class="new-version-mode-switch"
        :options="[
          { label: '上传新脚本或模型文件', value: 'script' },
          { label: '上传标准 ZIP', value: 'zip' },
        ]"
      />

      <template v-if="uploadMode === 'script'">
        <template v-if="isNewVersion">
          <el-form label-position="top" class="metadata-form new-version-form">
            <div class="simple-form-grid">
              <el-form-item label="目标模型">
                <el-input :model-value="form.name" disabled />
              </el-form-item>
              <el-form-item label="算法 ID">
                <el-input :model-value="form.algorithm_id" disabled />
              </el-form-item>
              <el-form-item label="新版本">
                <el-input v-model="form.version" placeholder="0.1.1" />
              </el-form-item>
              <el-form-item label="发布范围">
                <el-input :model-value="`${effectiveVisibilityText.label}（${effectiveVisibilityText.hint}）`" disabled />
              </el-form-item>
            </div>
          </el-form>
          <section class="proposal-upload-section">
            <h3>模型提案 / 样例输入</h3>
            <p>新版本会使用该 JSON 作为 LUI 工具提案和样例输入。</p>
            <el-input v-model="form.sample_input" type="textarea" :rows="8" class="code-input" />
            <el-alert v-if="sampleJsonError" :title="sampleJsonError" type="error" :closable="false" show-icon />
          </section>
          <div class="source-grid new-version-source">
            <section>
              <h3>新版本文件</h3>
              <el-upload
                ref="sourceUploadRef"
                v-model:file-list="sourceFiles"
                drag
                multiple
                :auto-upload="false"
                :show-file-list="false"
                accept=".py,.json,.md,.txt,.dat,.pkl,.joblib,.npy,.npz,.csv,.xlsx,.png,.jpg,.jpeg,.webp"
              >
                <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
                <div class="el-upload__text">拖入新脚本或模型文件，或点击选择</div>
              </el-upload>
              <div v-if="sourceFiles.length" class="selected-file-panel">
                <div class="selected-file-head">
                  <strong>当前已选文件</strong>
                  <el-button text @click="replaceSingleFile(sourceFiles, sourceUploadRef)">替换全部</el-button>
                </div>
                <div class="selected-file-list">
                  <div v-for="(file, index) in sourceFiles" :key="file.uid || file.name" class="selected-file-row">
                    <div class="selected-file-copy">
                      <strong>{{ file.name }}</strong>
                      <small>{{ formatFileSize(file.size) }}</small>
                    </div>
                    <div class="selected-file-actions">
                      <el-button text type="danger" @click="sourceFiles.splice(index, 1)">移除</el-button>
                    </div>
                  </div>
                </div>
              </div>
              <el-upload
                ref="requirementsUploadRef"
                v-model:file-list="requirementsFiles"
                :auto-upload="false"
                :limit="1"
                :show-file-list="false"
                accept=".txt"
              >
                <el-button>选择 requirements.txt</el-button>
              </el-upload>
              <div v-if="requirementsFiles.length" class="selected-file-panel compact">
                <div class="selected-file-row single-file">
                  <div class="selected-file-copy">
                    <strong>{{ requirementsFiles[0].name }}</strong>
                    <small>{{ formatFileSize(requirementsFiles[0].size) }}</small>
                  </div>
                  <div class="selected-file-actions">
                    <el-button text @click="replaceSingleFile(requirementsFiles, requirementsUploadRef)">替换</el-button>
                    <el-button text type="danger" @click="clearFileList(requirementsFiles)">移除</el-button>
                  </div>
                </div>
              </div>
            </section>
            <el-alert
              title="名称、作者、机构、输入输出契约、资源声明和发布范围均继承当前活动版本。"
              type="info"
              :closable="false"
              show-icon
            />
          </div>
        </template>
        <template v-else>
        <el-form label-position="top" class="metadata-form">
          <div class="simple-form-grid">
            <el-form-item label="模型名称"><el-input v-model="form.name" placeholder="例如 Polymer Tg Predictor" /></el-form-item>
            <el-form-item label="算法 ID"><el-input v-model="form.algorithm_id" placeholder="vertical_tg_predictor" /></el-form-item>
            <el-form-item label="版本"><el-input v-model="form.version" placeholder="0.1.0" /></el-form-item>
            <el-form-item label="开发者"><el-input v-model="form.developer" placeholder="模型开发者或团队" /></el-form-item>
            <el-form-item label="机构"><el-input v-model="form.developer_organization" placeholder="开发机构或单位" /></el-form-item>
            <el-form-item label="导师课题组"><el-input v-model="form.mentor_team" placeholder="例如 张三教授课题组" /></el-form-item>
            <el-form-item label="联系方式"><el-input v-model="form.developer_contact" placeholder="邮箱或内部联系人" /></el-form-item>
          </div>
          <el-form-item label="发布范围">
            <el-radio-group v-model="form.visibility" class="visibility-options">
              <el-radio-button value="private">非公开发布</el-radio-button>
              <el-radio-button value="public">公开发布</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="一句话说明"><el-input v-model="form.description" type="textarea" :rows="2" placeholder="说明这个模型适合预测什么、输入是什么。" /></el-form-item>
        </el-form>

        <div class="source-grid">
          <section>
            <h3>算法文件</h3>
            <el-upload
              ref="sourceUploadRef"
              v-model:file-list="sourceFiles"
              drag
              multiple
              :auto-upload="false"
              :show-file-list="false"
              accept=".py,.json,.md,.txt,.dat,.pkl,.joblib,.npy,.npz,.csv,.xlsx,.png,.jpg,.jpeg,.webp"
              @change="currentStep = Math.max(currentStep, 1)"
            >
              <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
              <div class="el-upload__text">拖入 Python 源文件，或点击选择</div>
            </el-upload>
            <div v-if="sourceFiles.length" class="selected-file-panel">
              <div class="selected-file-head">
                <strong>当前已选文件</strong>
                <el-button text @click="replaceSingleFile(sourceFiles, sourceUploadRef)">替换全部</el-button>
              </div>
              <div class="selected-file-list">
                <div v-for="(file, index) in sourceFiles" :key="file.uid || file.name" class="selected-file-row">
                  <div class="selected-file-copy">
                    <strong>{{ file.name }}</strong>
                    <small>{{ formatFileSize(file.size) }}</small>
                  </div>
                  <div class="selected-file-actions">
                    <el-button text type="danger" @click="sourceFiles.splice(index, 1)">移除</el-button>
                  </div>
                </div>
              </div>
            </div>
            <el-upload
              ref="requirementsUploadRef"
              v-model:file-list="requirementsFiles"
              :auto-upload="false"
              :limit="1"
              :show-file-list="false"
              accept=".txt"
            >
              <el-button>选择 requirements.txt</el-button>
            </el-upload>
            <div v-if="requirementsFiles.length" class="selected-file-panel compact">
              <div class="selected-file-row single-file">
                <div class="selected-file-copy">
                  <strong>{{ requirementsFiles[0].name }}</strong>
                  <small>{{ formatFileSize(requirementsFiles[0].size) }}</small>
                </div>
                <div class="selected-file-actions">
                  <el-button text @click="replaceSingleFile(requirementsFiles, requirementsUploadRef)">替换</el-button>
                  <el-button text type="danger" @click="clearFileList(requirementsFiles)">移除</el-button>
                </div>
              </div>
            </div>
          </section>
          <section>
            <h3>样例输入</h3>
            <el-input v-model="form.sample_input" type="textarea" :rows="8" class="code-input" />
            <el-alert v-if="sampleJsonError" :title="sampleJsonError" type="error" :closable="false" show-icon />
          </section>
        </div>

        <section class="schema-section asset-spec-section">
          <div class="section-heading">
            <div><h3>输入文件规格</h3><p>声明运行时可上传的通用文件资产。</p></div>
            <el-button :icon="Plus" @click="addAssetRow(inputAssetRows, 'input')">添加输入文件</el-button>
          </div>
          <el-table :data="inputAssetRows" border size="small" empty-text="未声明文件输入，模型按 JSON-only 运行">
            <el-table-column label="Key" min-width="130"><template #default="{ row }"><el-input v-model="row.key" placeholder="data_file" /></template></el-table-column>
            <el-table-column label="名称" min-width="130"><template #default="{ row }"><el-input v-model="row.label" placeholder="输入文件" /></template></el-table-column>
            <el-table-column label="必填" width="72" align="center"><template #default="{ row }"><el-checkbox v-model="row.required" /></template></el-table-column>
            <el-table-column label="数据类型" width="120"><template #default="{ row }"><el-select v-model="row.data_kind"><el-option v-for="item in dataKindOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></template></el-table-column>
            <el-table-column label="解析器" width="170"><template #default="{ row }"><el-select v-model="row.parser"><el-option v-for="item in parserOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></template></el-table-column>
            <el-table-column label="扩展名" min-width="150"><template #default="{ row }"><el-input v-model="row.extensions" placeholder=".csv,.xlsx" /></template></el-table-column>
            <el-table-column label="样例路径" min-width="180"><template #default="{ row }"><el-input v-model="row.sample_path" placeholder="tests/sample_assets/sample.csv" /></template></el-table-column>
            <el-table-column width="52"><template #default="{ $index }"><el-button text :icon="Delete" aria-label="删除输入文件规格" @click="removeAssetRow(inputAssetRows, $index)" /></template></el-table-column>
          </el-table>
        </section>

        <section class="schema-section asset-spec-section">
          <div class="section-heading">
            <div><h3>输出文件规格</h3><p>声明模型会写入 output_dir 的通用文件产物。</p></div>
            <el-button :icon="Plus" @click="addAssetRow(outputAssetRows, 'output')">添加输出文件</el-button>
          </div>
          <el-table :data="outputAssetRows" border size="small" empty-text="未声明文件输出，结果只展示 JSON summary">
            <el-table-column label="Key" min-width="130"><template #default="{ row }"><el-input v-model="row.key" placeholder="result_file" /></template></el-table-column>
            <el-table-column label="名称" min-width="130"><template #default="{ row }"><el-input v-model="row.label" placeholder="结果文件" /></template></el-table-column>
            <el-table-column label="数据类型" width="120"><template #default="{ row }"><el-select v-model="row.data_kind"><el-option v-for="item in dataKindOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></template></el-table-column>
            <el-table-column label="Artifact" width="150"><template #default="{ row }"><el-select v-model="row.artifact_type" filterable allow-create><el-option v-for="item in artifactTypeOptions" :key="item" :label="item" :value="item" /></el-select></template></el-table-column>
            <el-table-column label="MIME" min-width="180"><template #default="{ row }"><el-input v-model="row.mime_type" placeholder="application/json" /></template></el-table-column>
            <el-table-column label="扩展名" min-width="130"><template #default="{ row }"><el-input v-model="row.extensions" placeholder=".json" /></template></el-table-column>
            <el-table-column width="52"><template #default="{ $index }"><el-button text :icon="Delete" aria-label="删除输出文件规格" @click="removeAssetRow(outputAssetRows, $index)" /></template></el-table-column>
          </el-table>
        </section>

        <section class="schema-section asset-spec-section">
          <div class="section-heading">
            <div><h3>受管资源需求</h3><p>声明权重、数据库、tokenizer 等只读运行资源。</p></div>
            <el-button :icon="Plus" @click="addAssetRow(resourceAssetRows, 'resource')">添加资源</el-button>
          </div>
          <el-table :data="resourceAssetRows" border size="small" empty-text="未声明受管资源">
            <el-table-column label="Key" min-width="150"><template #default="{ row }"><el-input v-model="row.key" placeholder="model_weights" /></template></el-table-column>
            <el-table-column label="名称" min-width="150"><template #default="{ row }"><el-input v-model="row.label" placeholder="模型权重" /></template></el-table-column>
            <el-table-column label="资源类型" min-width="140"><template #default="{ row }"><el-input v-model="row.resource_type" placeholder="checkpoints" /></template></el-table-column>
            <el-table-column label="必需文件" min-width="190"><template #default="{ row }"><el-input v-model="row.required_files" placeholder="model.pth, vocab.json" /></template></el-table-column>
            <el-table-column label="环境变量" min-width="190"><template #default="{ row }"><el-input v-model="row.env_var" placeholder="MODEL_WEIGHTS_ROOT" /></template></el-table-column>
            <el-table-column label="必填" width="72" align="center"><template #default="{ row }"><el-checkbox v-model="row.required" /></template></el-table-column>
            <el-table-column label="需绑定" width="84" align="center"><template #default="{ row }"><el-checkbox v-model="row.binding_required" /></template></el-table-column>
            <el-table-column label="说明" min-width="180"><template #default="{ row }"><el-input v-model="row.description" /></template></el-table-column>
            <el-table-column width="52"><template #default="{ $index }"><el-button text :icon="Delete" aria-label="删除资源规格" @click="removeAssetRow(resourceAssetRows, $index)" /></template></el-table-column>
          </el-table>
        </section>

        <el-collapse v-model="expandedAdvanced" class="advanced-collapse">
          <el-collapse-item name="contributors">
            <template #title>
              <span class="advanced-title">贡献者台账（可选）</span>
            </template>
            <section class="schema-section contributor-section">
              <div class="section-heading">
                <div>
                  <h3>结构化贡献者</h3>
                  <p>用于详情页贡献分析，旧包不填写也可正常上传运行。</p>
                </div>
                <el-button :icon="Plus" @click="addContributorRow">添加贡献者</el-button>
              </div>
              <el-table :data="contributorRows" border size="small" empty-text="未填写结构化贡献者">
                <el-table-column label="姓名" min-width="140"><template #default="{ row }"><el-input v-model="row.name" placeholder="开发者姓名" /></template></el-table-column>
                <el-table-column label="角色" width="140"><template #default="{ row }"><el-select v-model="row.role"><el-option label="开发" value="developer" /><el-option label="审核" value="reviewer" /><el-option label="指导" value="mentor" /><el-option label="维护" value="maintainer" /><el-option label="数据" value="data" /><el-option label="方法" value="method" /></el-select></template></el-table-column>
                <el-table-column label="机构" min-width="150"><template #default="{ row }"><el-input v-model="row.organization" placeholder="单位或团队" /></template></el-table-column>
                <el-table-column label="导师关系" min-width="150"><template #default="{ row }"><el-input v-model="row.mentor_relation" placeholder="指导、审核或课题组归属" /></template></el-table-column>
                <el-table-column label="说明" min-width="180"><template #default="{ row }"><el-input v-model="row.description" placeholder="贡献说明" /></template></el-table-column>
                <el-table-column width="52"><template #default="{ $index }"><el-button text :icon="Delete" aria-label="删除贡献者" @click="removeContributorRow($index)" /></template></el-table-column>
              </el-table>
            </section>
          </el-collapse-item>
          <el-collapse-item name="advanced">
            <template #title>
              <span class="advanced-title">高级配置 / 契约编辑</span>
            </template>
            <el-form label-position="top" class="metadata-form">
              <div class="form-grid">
                <el-form-item label="算法类型">
                  <el-select v-model="form.type"><el-option label="预测器" value="predictor" /><el-option label="模拟器" value="simulator" /><el-option label="优化器" value="optimizer" /></el-select>
                </el-form-item>
                <el-form-item label="材料范围">
                  <el-select v-model="form.material_scope" multiple><el-option label="通用" value="universal" /><el-option label="氟基" value="fluoropolymer" /><el-option label="碳基" value="carbon_polymer" /><el-option label="硅基" value="silicon_polymer" /></el-select>
                </el-form-item>
                <el-form-item label="触发方式">
                  <el-select v-model="form.trigger_modes" multiple><el-option label="人工 Workflow" value="human_workflow" /><el-option label="AutoResearch" value="autoresearch" /></el-select>
                </el-form-item>
                <el-form-item label="入口函数"><el-input v-model="form.entrypoint" /></el-form-item>
                <el-form-item label="加载函数"><el-input v-model="form.loader" clearable /></el-form-item>
                <el-form-item label="来源链接"><el-input v-model="form.source_url" placeholder="论文、仓库或模型说明链接" /></el-form-item>
                <el-form-item label="Logo 资产"><el-input v-model="form.logo_asset" placeholder="/attributions/example-logo.png" /></el-form-item>
                <el-form-item label="Logo URL"><el-input v-model="form.logo_url" placeholder="仅使用授权或公开可用 Logo" /></el-form-item>
              </div>
              <el-form-item label="推荐引用"><el-input v-model="form.citation" type="textarea" :rows="2" placeholder="可填写模型、论文或方法引用文本" /></el-form-item>
              <div class="form-grid">
                <el-form-item label="结果封装">
                  <el-input v-model="form.result_envelope" placeholder="polyagent_run_result.v1" clearable />
                </el-form-item>
              </div>
              <div class="asset-contract-grid">
                <el-form-item label="输入文件规格">
                  <el-input v-model="form.input_assets" type="textarea" :rows="5" class="code-input" @blur="applyAssetJsonDraft(inputAssetRows, 'input_assets')" />
                </el-form-item>
                <el-form-item label="输出文件规格">
                  <el-input v-model="form.output_assets" type="textarea" :rows="5" class="code-input" @blur="applyAssetJsonDraft(outputAssetRows, 'output_assets')" />
                </el-form-item>
                <el-form-item label="受管资源需求">
                  <el-input v-model="form.resource_assets" type="textarea" :rows="5" class="code-input" @blur="applyAssetJsonDraft(resourceAssetRows, 'resource_assets')" />
                </el-form-item>
              </div>
              <el-alert v-if="assetJsonError" :title="assetJsonError" type="error" :closable="false" show-icon />
            </el-form>

            <section class="schema-section">
              <div class="section-heading"><div><h3>输入契约</h3><p>字段会直接渲染为详情页测试表单。</p></div><el-button :icon="Plus" @click="addField(inputFields)">添加字段</el-button></div>
              <el-table :data="inputFields" border size="small">
                <el-table-column label="字段名" min-width="140"><template #default="{ row }"><el-input v-model="row.name" /></template></el-table-column>
                <el-table-column label="类型" width="130"><template #default="{ row }"><el-select v-model="row.type"><el-option v-for="type in ['string','number','integer','boolean','object','list[string]']" :key="type" :label="type" :value="type" /></el-select></template></el-table-column>
                <el-table-column label="必填" width="72" align="center"><template #default="{ row }"><el-checkbox v-model="row.required" /></template></el-table-column>
                <el-table-column label="单位" width="110"><template #default="{ row }"><el-input v-model="row.unit" /></template></el-table-column>
                <el-table-column label="枚举（逗号分隔）" min-width="170"><template #default="{ row }"><el-input v-model="row.options" /></template></el-table-column>
                <el-table-column label="范围" width="170"><template #default="{ row }"><div class="range-inputs"><el-input v-model="row.min" placeholder="min" /><el-input v-model="row.max" placeholder="max" /></div></template></el-table-column>
                <el-table-column width="52"><template #default="{ $index }"><el-button text :icon="Delete" aria-label="删除输入字段" @click="removeField(inputFields, $index)" /></template></el-table-column>
              </el-table>
            </section>

            <section class="schema-section">
              <div class="section-heading"><div><h3>输出契约</h3><p>定义 predict 返回对象的字段。</p></div><el-button :icon="Plus" @click="addField(outputFields)">添加字段</el-button></div>
              <el-table :data="outputFields" border size="small">
                <el-table-column label="字段名" min-width="160"><template #default="{ row }"><el-input v-model="row.name" /></template></el-table-column>
                <el-table-column label="类型" width="150"><template #default="{ row }"><el-select v-model="row.type"><el-option v-for="type in ['string','number','integer','boolean','object','list[string]']" :key="type" :label="type" :value="type" /></el-select></template></el-table-column>
                <el-table-column label="必填" width="72" align="center"><template #default="{ row }"><el-checkbox v-model="row.required" /></template></el-table-column>
                <el-table-column label="单位" min-width="120"><template #default="{ row }"><el-input v-model="row.unit" /></template></el-table-column>
                <el-table-column width="52"><template #default="{ $index }"><el-button text :icon="Delete" aria-label="删除输出字段" @click="removeField(outputFields, $index)" /></template></el-table-column>
              </el-table>
            </section>

            <section class="contract-preview"><h3>polyagent.algorithm.yaml 预览</h3><pre>{{ contractPreview }}</pre></section>
          </el-collapse-item>
        </el-collapse>
        </template>
      </template>

      <section v-else class="zip-upload">
        <el-form v-if="isNewVersion" label-position="top" class="metadata-form new-version-form">
          <div class="simple-form-grid">
            <el-form-item label="目标模型"><el-input :model-value="form.name" disabled /></el-form-item>
            <el-form-item label="算法 ID"><el-input :model-value="form.algorithm_id" disabled /></el-form-item>
            <el-form-item label="ZIP 内版本">
              <el-input :model-value="zipInspecting ? '读取中…' : (zipInspect?.version || '请选择 ZIP')" disabled />
            </el-form-item>
          </div>
        </el-form>
        <el-form v-else label-position="top" class="metadata-form">
          <el-form-item label="发布范围">
            <el-radio-group v-model="form.visibility" class="visibility-options">
              <el-radio-button value="private">非公开发布</el-radio-button>
              <el-radio-button value="public">公开发布</el-radio-button>
            </el-radio-group>
          </el-form-item>
        </el-form>
        <el-upload
          ref="zipUploadRef"
          v-model:file-list="zipFiles"
          drag
          :auto-upload="false"
          :limit="1"
          :show-file-list="false"
          accept=".zip"
          @change="onZipFileChange"
        >
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">拖入标准 ZIP，或点击选择</div>
        </el-upload>
        <div v-if="zipFiles.length" class="selected-file-panel compact">
          <div class="selected-file-row single-file">
            <div class="selected-file-copy">
              <strong>{{ zipFiles[0].name }}</strong>
              <small>{{ formatFileSize(zipFiles[0].size) }}</small>
            </div>
            <div class="selected-file-actions">
              <el-button text @click="replaceSingleFile(zipFiles, zipUploadRef)">替换</el-button>
              <el-button text type="danger" @click="clearFileList(zipFiles)">移除</el-button>
            </div>
          </div>
        </div>
        <el-alert
          v-if="zipInspectError"
          :title="zipInspectError"
          type="error"
          :closable="false"
          show-icon
        />
        <el-alert
          v-else-if="zipInspect?.version"
          :title="isNewVersion ? `将以 ZIP 内版本 ${zipInspect.version} 登记为新版本（以 polyagent.algorithm.yaml 为准）` : `ZIP 内版本：${zipInspect.version}`"
          :description="isNewVersion ? `发布范围：${effectiveVisibilityText.label}（${effectiveVisibilityText.hint}）` : ''"
          type="info"
          :closable="false"
          show-icon
        />
      </section>
    </section>

    <section v-else-if="currentStep === 2" class="wizard-section step-card">
      <div class="submit-row">
        <div>
          <h3>校验、部署并激活</h3>
          <p>确认无误后提交，平台会自动打包、校验、构建、部署并激活版本。</p>
        </div>
      </div>
      <div class="deploy-summary">
        <span>上传方式：{{ uploadMode === 'zip' ? '标准 ZIP' : 'Python 脚本' }}</span>
        <span>发布范围：{{ effectiveVisibilityText.label }}<template v-if="isNewVersion">（{{ effectiveVisibilityText.hint }}）</template></span>
        <span v-if="isNewVersion">目标：{{ form.algorithm_id }} / {{ submitVersion }}</span>
        <span v-if="uploadMode === 'script'">模型：{{ form.name }} / {{ form.version }}</span>
        <span v-if="uploadMode === 'zip'">文件：{{ zipFiles[0]?.name || '已选择 ZIP' }}</span>
      </div>
      <section v-if="declaredResourceAssets.length" class="resource-binding-panel">
        <div class="section-heading">
          <div>
            <h3>运行资源绑定</h3>
            <p>该模型声明了 ZIP 外的权重或数据库。请选择已登记资源，或在这里登记后端可访问的挂载路径。</p>
          </div>
        </div>
        <div v-for="spec in declaredResourceAssets" :key="spec.key" class="resource-binding-row">
          <div class="resource-binding-copy">
            <strong>{{ spec.label || spec.key }}</strong>
            <span>{{ spec.key }}<template v-if="spec.resource_type"> · {{ spec.resource_type }}</template></span>
            <small v-if="spec.required_files?.length">必需文件：{{ spec.required_files.join(', ') }}</small>
          </div>
          <el-select
            v-model="selectedResourceIds[spec.key]"
            clearable
            filterable
            :placeholder="spec.binding_required ? '请选择必需资源' : '可选：使用服务默认资源'"
          >
            <el-option
              v-for="resource in availableResources[spec.key] || []"
              :key="resource.resource_id"
              :label="`${resource.name} · ${resource.path}`"
              :value="resource.resource_id"
            />
          </el-select>
          <el-button @click="resourceDrafts[spec.key].expanded = !resourceDrafts[spec.key].expanded">登记新路径</el-button>
          <div v-if="resourceDrafts[spec.key]?.expanded" class="inline-resource-form">
            <el-input v-model="resourceDrafts[spec.key].name" placeholder="资源名称" />
            <el-input v-model="resourceDrafts[spec.key].path" placeholder="后端宿主机挂载路径" />
            <el-button
              type="primary"
              :loading="registeringResourceKey === spec.key"
              @click="registerInlineResource(spec)"
            >校验并绑定</el-button>
          </div>
        </div>
        <el-alert
          v-if="unresolvedRequiredBindings.length"
          title="仍有必需资源未绑定，完成选择后可继续校验部署。"
          type="warning"
          :closable="false"
          show-icon
        />
      </section>
      <div v-if="loading || currentPackage" class="validation-results">
        <div v-for="step in processSteps" :key="step.title" :class="{ done: step.done }">
          <el-icon><Check /></el-icon>
          <strong>{{ step.title }}</strong>
          <span>{{ step.text }}</span>
        </div>
      </div>
    </section>

    <section v-else class="wizard-section step-card">
      <div class="submit-row">
        <div>
          <h3>完成</h3>
          <p>模型版本已完成校验、部署并激活，可进入详情页测试或继续上传新版本。</p>
        </div>
      </div>
      <div class="validation-results">
        <div v-for="step in processSteps" :key="step.title" :class="{ done: step.done }">
          <el-icon><Check /></el-icon>
          <strong>{{ step.title }}</strong>
          <span>{{ step.text }}</span>
        </div>
      </div>
      <div v-if="currentPackage" class="success-actions">
        <div class="package-status">
          <el-tag :type="currentPackage.status === 'active' ? 'success' : 'warning'">{{ currentPackage.status }}</el-tag>
          <span>{{ currentPackage.name || currentPackage.algorithm_id || currentPackage.filename }}<template v-if="currentPackage.version"> · {{ currentPackage.version }}</template></span>
          <el-button text :icon="Download" @click="downloadGeneratedPackage">下载标准 ZIP</el-button>
        </div>
        <div class="success-buttons">
          <el-button @click="resetForNextUpload">继续上传新版本</el-button>
          <el-button type="primary" @click="viewModelDetail">查看模型详情</el-button>
        </div>
      </div>
    </section>

    <div class="wizard-footer">
      <el-button :disabled="currentStep === 0 || (isNewVersion && currentStep === 1) || loading || currentStep === 3" @click="goPrevious">上一步</el-button>
      <el-button v-if="currentStep < 2" type="primary" @click="goNext">下一步</el-button>
      <el-button v-else-if="currentStep === 2" type="primary" :loading="loading" @click="submit">校验部署</el-button>
      <el-button v-else type="primary" @click="viewModelDetail">查看模型详情</el-button>
    </div>
  </div>
</template>

<style scoped>
.upload-workspace { display: grid; gap: 16px; }
.wizard-shell, .wizard-section { border: 1px solid var(--app-border); border-radius: var(--app-radius-md); background: #fff; padding: 16px; }
.wizard-head, .section-heading, .submit-row, .success-actions { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.step-card { min-height: 260px; }
.resource-binding-panel { display: grid; gap: 12px; padding: 14px; border: 1px solid var(--app-border); background: #f8fafc; }
.resource-binding-panel h3, .resource-binding-panel p { margin: 0; }
.resource-binding-row { display: grid; grid-template-columns: minmax(180px, 0.8fr) minmax(260px, 1.3fr) auto; gap: 10px; align-items: center; padding-top: 12px; border-top: 1px solid var(--app-border); }
.resource-binding-copy { display: grid; gap: 3px; min-width: 0; }
.resource-binding-copy span, .resource-binding-copy small { color: var(--app-text-muted); overflow-wrap: anywhere; }
.inline-resource-form { grid-column: 1 / -1; display: grid; grid-template-columns: minmax(160px, 0.7fr) minmax(260px, 1.3fr) auto; gap: 10px; }
.wizard-eyebrow { margin: 0 0 4px; color: var(--app-primary-active); font-size: 12px; font-weight: 700; }
h2, h3 { margin: 0; color: var(--app-ink); letter-spacing: 0; }
h2 { font-size: 22px; line-height: 1.25; }
h3 { font-size: 15px; }
.wizard-head p:last-child, .section-heading p, .submit-row p { margin: 4px 0 0; color: var(--app-ink-muted); font-size: 13px; line-height: 1.55; }
.wizard-shell :deep(.el-steps) { margin-top: 16px; }
.metadata-form { margin-top: 12px; }
.proposal-upload-section { display: grid; gap: 8px; margin-top: 12px; }
.new-version-mode-switch { margin: 4px 0 16px; }
.visibility-options { display: flex; flex-wrap: wrap; gap: 8px; }
.simple-form-grid { display: grid; grid-template-columns: minmax(220px, 1.2fr) minmax(180px, 1fr) 140px; gap: 0 14px; }
.form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 0 14px; }
.asset-contract-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0 14px; }
.source-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, 0.9fr); gap: 18px; margin-top: 8px; }
.source-grid section { min-width: 0; }
.source-grid h3, .contract-preview h3 { margin-bottom: 10px; }
.selected-file-panel { display: grid; gap: 10px; margin-top: 12px; padding: 12px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-sm); background: #f8fbff; }
.selected-file-panel.compact { margin-top: 10px; }
.selected-file-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.selected-file-head strong { color: var(--app-ink); font-size: 13px; }
.selected-file-list { display: grid; gap: 8px; }
.selected-file-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 8px; border-top: 1px solid var(--app-border-soft); }
.selected-file-row:first-child { padding-top: 0; border-top: 0; }
.selected-file-row.single-file { padding-top: 0; border-top: 0; }
.selected-file-copy { min-width: 0; display: grid; gap: 3px; }
.selected-file-copy strong { color: var(--app-ink); font-size: 13px; overflow-wrap: anywhere; }
.selected-file-copy small { color: var(--app-ink-muted); font-size: 12px; }
.selected-file-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.code-input :deep(textarea), pre { font-family: var(--app-mono-font); font-size: 12px; }
.advanced-collapse { margin-top: 16px; border-top: 1px solid var(--app-border-soft); border-bottom: none; }
.advanced-title { color: var(--app-ink); font-weight: 700; }
.schema-section, .contract-preview { border-top: 1px solid var(--app-border-soft); padding-top: 16px; margin-top: 14px; }
.section-heading { margin-bottom: 10px; }
.upload-mode-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; max-width: 920px; }
.upload-mode-card { min-width: 0; display: grid; grid-template-columns: 42px minmax(0, 1fr); gap: 10px 12px; align-items: start; padding: 14px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-md); background: #fff; color: inherit; text-align: left; cursor: pointer; transition: border-color 0.18s ease, box-shadow 0.18s ease, background-color 0.18s ease; }
.upload-mode-card:hover, .upload-mode-card:focus-visible { border-color: #3b82f6; box-shadow: 0 2px 12px rgba(59, 130, 246, 0.1); outline: none; }
.upload-mode-card.active { border-color: #3b82f6; background: #f8fbff; box-shadow: inset 0 0 0 1px #3b82f6; }
.mode-icon { display: inline-grid; place-items: center; width: 42px; height: 42px; border-radius: var(--app-radius-sm); background: var(--app-primary-light); color: var(--app-primary-active); }
.mode-copy { min-width: 0; display: grid; gap: 6px; }
.mode-copy strong { color: var(--app-ink); font-size: 15px; line-height: 1.35; }
.mode-copy small { color: var(--app-ink-muted); font-size: 12px; line-height: 1.5; }
.mode-tags { grid-column: 2; display: flex; flex-wrap: wrap; gap: 6px; }
.range-inputs { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.contract-preview pre { margin: 0; max-height: 260px; overflow: auto; padding: 14px; border: 1px solid var(--app-border); border-radius: var(--app-radius-sm); background: #f8fafc; white-space: pre-wrap; }
.zip-upload { max-width: 760px; margin-top: 8px; }
.deploy-summary { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.deploy-summary span { padding: 7px 10px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-sm); background: #f8fbff; color: var(--app-ink-body); font-size: 12px; overflow-wrap: anywhere; }
.validation-results { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 14px; }
.validation-results div { min-width: 0; display: grid; grid-template-columns: 20px 1fr; gap: 4px 8px; padding: 12px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-sm); background: #f8fbff; }
.validation-results .el-icon { grid-row: span 2; color: var(--app-ink-subtle); margin-top: 2px; }
.validation-results div.done { border-color: #bbf7d0; background: #f0fdf4; }
.validation-results div.done .el-icon { color: #16a34a; }
.validation-results strong { color: var(--app-ink); font-size: 13px; }
.validation-results span { color: var(--app-ink-muted); font-size: 12px; overflow-wrap: anywhere; }
.package-status, .success-buttons { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.package-status { min-width: 0; color: var(--app-ink-body); }
.wizard-footer { position: sticky; bottom: 14px; z-index: 2; display: flex; justify-content: flex-end; gap: 10px; padding: 12px; border: 1px solid var(--app-border); border-radius: var(--app-radius-md); background: rgba(255, 255, 255, 0.96); box-shadow: var(--app-card-shadow); }
@media (max-width: 1100px) { .validation-results { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) {
  .wizard-head, .section-heading, .submit-row, .success-actions, .wizard-footer { align-items: stretch; flex-direction: column; }
  .simple-form-grid, .form-grid, .asset-contract-grid, .source-grid, .validation-results, .upload-mode-grid, .resource-binding-row, .inline-resource-form { grid-template-columns: 1fr; }
  .inline-resource-form { grid-column: 1; }
  .new-version-mode-switch { width: 100%; }
  .new-version-mode-switch :deep(.el-segmented__group) { display: grid; grid-template-columns: 1fr; width: 100%; }
}
</style>
