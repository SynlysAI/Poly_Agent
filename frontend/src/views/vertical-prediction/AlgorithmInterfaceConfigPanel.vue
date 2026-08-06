<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowDown, ArrowUp, Check, Delete, Link, MagicStick, Plus, Promotion, VideoPlay } from '@element-plus/icons-vue'

import {
  activateAlgorithmInterfaceVersion,
  createAlgorithmInterface,
  createAlgorithmInterfaceVersion,
  getApiErrorMessage,
  testAlgorithmInterface,
  updateAlgorithmInterfaceVersion,
} from '../../api/polyAgentApi'
import { INTERFACE_CONFIG_EXAMPLES } from '../../utils/interfaceConfigExamples.mjs'
import { interfaceProtocolLabel, suggestNextPatch } from '../../utils/verticalPredictionState.mjs'

const props = defineProps({
  mode: { type: String, default: 'new_interface' },
  targetAlgorithm: { type: Object, default: null },
  targetVersion: { type: Object, default: null },
  targetVersions: { type: Array, default: () => [] },
})
const emit = defineEmits(['changed', 'view-detail', 'cancel'])

const saving = ref(false)
const testing = ref(false)
const activating = ref(false)
const savedVersion = ref(null)
const testResult = ref(null)
const sessionMode = ref(['new_version', 'edit_version'].includes(props.mode) ? props.mode : 'new_interface')
const isNewVersion = computed(() => sessionMode.value === 'new_version')
const isEditVersion = computed(() => sessionMode.value === 'edit_version')
const currentStep = ref(0)
const stepItems = [
  { title: '模型信息', description: '先登记模型身份和来源' },
  { title: '接口地址', description: '选择协议并确认请求方式' },
  { title: '输入输出', description: '声明调用字段与结果字段' },
  { title: '请求映射', description: '绑定参数、Header 和密钥引用' },
  { title: '样例测试', description: '保存、验证并激活版本' },
]
const examples = INTERFACE_CONFIG_EXAMPLES
const activeExampleId = ref('')
const showGuide = computed(() => sessionMode.value === 'new_interface')
const tourVisible = ref(false)
const guideExpanded = ref(false)
const guidePromptVisible = ref(true)
const guideBannerRef = ref(null)
const wizardShellRef = ref(null)
const desktopStepsVisible = ref(true)
const tourStepTargets = [
  () => guideBannerRef.value,
  () => (desktopStepsVisible.value ? '.desktop-steps .el-step:nth-child(1)' : wizardShellRef.value),
  () => (desktopStepsVisible.value ? '.desktop-steps .el-step:nth-child(2)' : wizardShellRef.value),
  () => (desktopStepsVisible.value ? '.desktop-steps .el-step:nth-child(3)' : wizardShellRef.value),
  () => (desktopStepsVisible.value ? '.desktop-steps .el-step:nth-child(4)' : wizardShellRef.value),
  () => (desktopStepsVisible.value ? '.desktop-steps .el-step:nth-child(5)' : wizardShellRef.value),
]
const tourSteps = [
  { title: '欢迎使用接口配置', description: '从示例场景一键填入，或直接手动填写。' },
  { title: '第 1 步 · 模型信息', description: '登记模型身份与来源，来源会在模型中心展示。' },
  { title: '第 2 步 · 接口地址', description: '选择协议，填写 endpoint 与响应提取路径。' },
  { title: '第 3 步 · 输入输出', description: '声明输入输出字段，必填字段须在样例中给出。' },
  { title: '第 4 步 · 请求映射', description: '绑定参数与 Header；密钥只填引用名，不存明文。' },
  { title: '第 5 步 · 样例测试', description: '保存后测试，通过即可激活进入管理中心。' },
]
const canTest = computed(() => Boolean(savedVersion.value && form.protocol !== 'mcp'))
const canActivate = computed(() => Boolean(canTest.value && testResult.value?.ok))

function syncDesktopStepsVisibility() {
  if (typeof window === 'undefined') return
  desktopStepsVisible.value = window.matchMedia('(max-width: 680px)').matches === false
}

async function startTeaching() {
  guideExpanded.value = true
  guidePromptVisible.value = false
  await nextTick()
  tourVisible.value = true
}

function skipTeaching() {
  guidePromptVisible.value = false
}

function toggleGuide() {
  guideExpanded.value = !guideExpanded.value
  guidePromptVisible.value = false
}

async function playTour() {
  guideExpanded.value = true
  guidePromptVisible.value = false
  await nextTick()
  tourVisible.value = true
}

function applyExample(example) {
  const fill = example.form
  form.algorithm_id = fill.algorithm_id
  form.name = fill.name
  form.version = fill.version
  form.protocol = fill.protocol
  form.endpoint_url = fill.endpoint_url
  form.http_method = fill.http_method
  form.timeout_seconds = fill.timeout_seconds
  form.response_selector = fill.response_selector || ''
  form.description = fill.description || ''
  form.visibility = fill.visibility || 'private'
  form.sample_input = JSON.stringify(fill.sample_input, null, 2)
  form.developer = ''
  form.developer_organization = ''
  form.mentor_team = ''
  form.developer_contact = ''
  form.source_url = ''
  form.citation = ''
  form.logo_url = ''
  inputFields.value = example.input_fields.map((row) => ({ ...row }))
  outputFields.value = example.output_fields.map((row) => ({ ...row }))
  queryBindings.value = rowsFromMap(example.query_bindings)
  headerBindings.value = rowsFromMap(example.header_bindings)
  staticHeaders.value = rowsFromMap(example.static_headers)
  secretRefs.value = rowsFromMap(example.secret_refs)
  savedVersion.value = null
  testResult.value = null
  currentStep.value = 0
  activeExampleId.value = example.id
  ElMessage.success(`已填入示例「${example.title}」，请确认接口地址后继续`)
  if (example.notes?.length) ElMessage.info(example.notes.join('；'))
}

onMounted(() => {
  syncDesktopStepsVisibility()
  if (typeof window !== 'undefined') {
    window.addEventListener('resize', syncDesktopStepsVisibility)
  }
})

onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('resize', syncDesktopStepsVisibility)
  }
})

const form = reactive({
  algorithm_id: 'remote_property_predictor',
  name: 'Remote Property Predictor',
  version: '0.1.0',
  protocol: 'fastapi',
  endpoint_url: 'https://model.example.com/predict',
  http_method: 'POST',
  timeout_seconds: 30,
  response_selector: '',
  description: '',
  visibility: 'private',
  developer: '',
  developer_organization: '',
  mentor_team: '',
  developer_contact: '',
  source_url: '',
  citation: '',
  logo_url: '',
  sample_input: JSON.stringify({ smiles: 'CCO' }, null, 2),
})

const inputFields = ref([{ name: 'smiles', type: 'string', required: true, unit: '' }])
const outputFields = ref([{ name: 'prediction', type: 'number', required: true, unit: '' }])
const queryBindings = ref([])
const headerBindings = ref([])
const staticHeaders = ref([])
const secretRefs = ref([])

const sampleInputError = computed(() => {
  try {
    const value = JSON.parse(form.sample_input)
    return value && typeof value === 'object' && !Array.isArray(value) ? '' : '样例输入必须是 JSON object'
  } catch (error) {
    return `JSON 格式错误：${error.message}`
  }
})

watch(
  () => [props.targetAlgorithm, props.targetVersion, props.targetVersions],
  hydrateFromTarget,
  { immediate: true },
)

function hydrateFromTarget() {
  if ((!isNewVersion.value && !isEditVersion.value) || !props.targetAlgorithm || savedVersion.value) return
  const algorithm = props.targetAlgorithm
  const version = props.targetVersion || {}
  const config = version.interface_config || algorithm.interface_config || {}
  form.algorithm_id = algorithm.algorithm_id
  form.name = algorithm.name
  form.version = isEditVersion.value ? (version.version || form.version) : suggestNextPatch(props.targetVersions)
  form.protocol = config.protocol || 'http'
  form.endpoint_url = config.endpoint_url || ''
  form.http_method = config.http_method || 'POST'
  form.timeout_seconds = config.timeout_seconds || 30
  form.response_selector = config.response_selector || ''
  form.description = algorithm.description || ''
  form.visibility = algorithm.visibility || 'private'
  form.developer = algorithm.developer_attribution?.name || ''
  form.developer_organization = algorithm.developer_attribution?.organization || ''
  form.mentor_team = algorithm.mentor_team || ''
  form.developer_contact = algorithm.developer_contact || ''
  form.source_url = algorithm.developer_attribution?.url || ''
  form.citation = algorithm.developer_attribution?.citation_text || ''
  form.logo_url = algorithm.developer_attribution?.logo_asset || ''
  form.sample_input = JSON.stringify(version.contract?.sample_input || {}, null, 2)
  inputFields.value = rowsFromSchema(version.input_schema || algorithm.input_schema)
  outputFields.value = rowsFromSchema(version.output_schema || algorithm.output_schema)
  queryBindings.value = rowsFromMap(config.query_bindings)
  headerBindings.value = rowsFromMap(config.header_bindings)
  staticHeaders.value = rowsFromMap(config.static_headers)
  secretRefs.value = rowsFromMap(config.secret_refs)
  currentStep.value = 0
  savedVersion.value = null
  testResult.value = null
}

function rowsFromSchema(schema = {}) {
  const rows = Object.entries(schema?.fields || {}).map(([name, type]) => ({
    name,
    type,
    required: (schema.required || []).includes(name),
    unit: schema.ui_hints?.[name]?.unit || '',
  }))
  return rows.length ? rows : [{ name: '', type: 'string', required: false, unit: '' }]
}

function rowsFromMap(value = {}) {
  return Object.entries(value || {}).map(([key, item]) => ({ key, value: item }))
}

function addField(rows) {
  rows.push({ name: '', type: 'string', required: false, unit: '' })
}

function addMapping(rows) {
  rows.push({ key: '', value: '' })
}

function removeRow(rows, index) {
  rows.splice(index, 1)
}

function schemaFromRows(rows) {
  const validRows = rows.filter((row) => row.name.trim())
  return {
    fields: Object.fromEntries(validRows.map((row) => [row.name.trim(), row.type])),
    required: validRows.filter((row) => row.required).map((row) => row.name.trim()),
    constraints: {},
    field_defaults: {},
    ui_hints: Object.fromEntries(validRows.filter((row) => row.unit).map((row) => [row.name.trim(), { unit: row.unit.trim() }])),
    field_options: {},
  }
}

function mapFromRows(rows) {
  return Object.fromEntries(rows.filter((row) => row.key.trim() && row.value.trim()).map((row) => [row.key.trim(), row.value.trim()]))
}

function interfaceConfig() {
  return {
    protocol: form.protocol,
    endpoint_url: form.endpoint_url.trim(),
    http_method: form.http_method,
    body_mode: 'json',
    query_bindings: mapFromRows(queryBindings.value),
    header_bindings: mapFromRows(headerBindings.value),
    static_headers: mapFromRows(staticHeaders.value),
    response_selector: form.response_selector.trim() || null,
    timeout_seconds: Number(form.timeout_seconds),
    secret_refs: mapFromRows(secretRefs.value),
  }
}

function versionPayload({ includeVersion = true } = {}) {
  return {
    ...(includeVersion ? { version: form.version.trim() } : {}),
    input_schema: schemaFromRows(inputFields.value),
    output_schema: schemaFromRows(outputFields.value),
    interface_config: interfaceConfig(),
    sample_input: JSON.parse(form.sample_input),
    description: form.description.trim() || null,
    visibility: form.visibility,
  }
}

function validateRows(rows, label) {
  const names = rows.map((row) => String(row.name || '').trim()).filter(Boolean)
  if (!names.length) return `${label}至少需要声明一个字段`
  if (new Set(names).size !== names.length) return `${label}字段名不能重复`
  return ''
}

function validateStep(step = currentStep.value) {
  if (step === 0) {
    if (!form.algorithm_id.trim()) return '请填写模型 ID'
    if (!form.name.trim()) return '请填写模型名称'
    if (!form.version.trim()) return '请填写版本号'
    if (!/^\d+\.\d+\.\d+$/.test(form.version.trim())) return '版本号必须是 x.y.z 格式'
    if (isNewVersion.value && props.targetVersions.some((item) => item.version === form.version.trim())) return '该版本号已存在，请修改后继续'
    return ''
  }
  if (step === 1) {
    if (!form.endpoint_url.trim()) return '请填写 Endpoint URL'
    try {
      const url = new URL(form.endpoint_url.trim())
      if (!['http:', 'https:'].includes(url.protocol)) return 'Endpoint URL 必须使用 HTTP 或 HTTPS'
      if (url.username || url.password) return 'Endpoint URL 不能包含用户名或密码'
    } catch {
      return 'Endpoint URL 格式不正确'
    }
    return ''
  }
  if (step === 2) return validateRows(inputFields.value, '输入字段') || validateRows(outputFields.value, '输出字段')
  if (step === 3) {
    const inputNames = new Set(inputFields.value.map((row) => String(row.name || '').trim()).filter(Boolean))
    for (const [label, rows, usesInputField] of [
      ['Query 绑定', queryBindings.value, true],
      ['Header 绑定', headerBindings.value, true],
      ['静态 Header', staticHeaders.value, false],
      ['密钥引用', secretRefs.value, false],
    ]) {
      const completeRows = rows.filter((row) => row.key || row.value)
      if (completeRows.some((row) => !String(row.key || '').trim() || !String(row.value || '').trim())) return `${label}存在未填写完整的映射`
      const keys = completeRows.map((row) => String(row.key).trim().toLowerCase())
      if (new Set(keys).size !== keys.length) return `${label}不能包含重复键`
      if (usesInputField && completeRows.some((row) => !inputNames.has(String(row.value).trim().split('.')[0]))) return `${label}必须引用已声明的输入字段`
    }
    const sensitivePattern = /(authorization|token|password|api[-_]?key|secret|credential|signature)/i
    if (queryBindings.value.some((row) => sensitivePattern.test(String(row.key || '')))) return '认证 Query 不能从普通输入映射'
    if (headerBindings.value.some((row) => sensitivePattern.test(String(row.key || '')))) return '认证 Header 必须使用密钥引用'
    const headerSources = [headerBindings.value, staticHeaders.value, secretRefs.value]
      .map((rows) => new Set(rows.map((row) => String(row.key || '').trim().toLowerCase()).filter(Boolean)))
    if (headerSources.some((source, index) => headerSources.slice(index + 1).some((other) => [...source].some((key) => other.has(key))))) return '同一个 Header 不能同时配置多个来源'
    if (secretRefs.value.some((row) => row.value && !/^[A-Z0-9_]+$/.test(String(row.value).trim()))) return '密钥引用必须使用大写字母、数字或下划线'
    return ''
  }
  if (step === 4) {
    if (sampleInputError.value) return sampleInputError.value
    const sample = JSON.parse(form.sample_input)
    const missing = inputFields.value
      .filter((row) => row.required && row.name.trim() && (sample[row.name.trim()] === undefined || sample[row.name.trim()] === null))
      .map((row) => row.name.trim())
    if (missing.length) return `样例输入缺少必填字段：${missing.join('、')}`
  }
  return ''
}

function goNext() {
  const error = validateStep()
  if (error) {
    ElMessage.warning(error)
    return
  }
  currentStep.value = Math.min(currentStep.value + 1, stepItems.length - 1)
}

function goPrevious() {
  if (saving.value || testing.value || activating.value) return
  currentStep.value = Math.max(currentStep.value - 1, 0)
}

async function saveConfig() {
  const formError = stepItems.map((_item, index) => validateStep(index)).find(Boolean)
  if (formError) {
    ElMessage.error(formError)
    return
  }
  saving.value = true
  try {
    if (isEditVersion.value) {
      if (!props.targetVersion?.version_id) {
        throw new Error('目标接口版本不存在，请返回版本治理后重试')
      }
      savedVersion.value = await updateAlgorithmInterfaceVersion(
        form.algorithm_id,
        props.targetVersion?.version_id,
        versionPayload({ includeVersion: false }),
      )
    } else if (isNewVersion.value) {
      savedVersion.value = await createAlgorithmInterfaceVersion(form.algorithm_id, versionPayload())
    } else {
      const result = await createAlgorithmInterface({
        algorithm_id: form.algorithm_id.trim(),
        name: form.name.trim(),
        version: form.version.trim(),
        algorithm_family: 'vertical_prediction',
        type: 'predictor',
        material_scope: ['universal'],
        task_scope: ['COMPUTE_PREDICT'],
        trigger_modes: ['human_workflow', 'autoresearch'],
        input_schema: schemaFromRows(inputFields.value),
        output_schema: schemaFromRows(outputFields.value),
        interface_config: interfaceConfig(),
        sample_input: JSON.parse(form.sample_input),
        description: form.description.trim() || null,
        developer: form.developer.trim() || null,
        developer_organization: form.developer_organization.trim() || null,
        mentor_team: form.mentor_team.trim() || null,
        developer_contact: form.developer_contact.trim() || null,
        source_url: form.source_url.trim() || null,
        citation: form.citation.trim() || null,
        logo_url: form.logo_url.trim() || null,
        contributors: [],
        method_attributions: [],
        visibility: form.visibility,
      })
      savedVersion.value = result.version
      form.algorithm_id = result.algorithm.algorithm_id
    }
    testResult.value = null
    emit('changed', { algorithm_id: form.algorithm_id, version_id: savedVersion.value.version_id })
    ElMessage.success('接口配置已保存')
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    saving.value = false
  }
}

async function testConfig() {
  if (!canTest.value) return
  const formError = validateStep(4)
  if (formError) {
    ElMessage.error(formError)
    return
  }
  testing.value = true
  try {
    testResult.value = await testAlgorithmInterface(
      form.algorithm_id,
      savedVersion.value.version_id,
      JSON.parse(form.sample_input),
    )
    if (testResult.value.ok) ElMessage.success('接口样例测试通过')
  } catch (error) {
    testResult.value = null
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    testing.value = false
  }
}

async function activateConfig() {
  if (!canActivate.value) return
  activating.value = true
  try {
    savedVersion.value = await activateAlgorithmInterfaceVersion(form.algorithm_id, savedVersion.value.version_id)
    emit('changed', { algorithm_id: form.algorithm_id, version_id: savedVersion.value.version_id })
    ElMessage.success('接口版本已激活，可在模型管理中心调用')
    emit('view-detail', form.algorithm_id)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    activating.value = false
  }
}
</script>

<template>
  <section class="interface-config-panel">
    <header class="config-header">
      <div class="config-title">
        <el-icon><Link /></el-icon>
        <div>
          <h1>{{ isEditVersion ? '编辑接口配置' : (isNewVersion ? '新建接口版本' : '垂类模型（接口配置）') }}</h1>
          <p>{{ isEditVersion ? `${form.name} / ${form.version} · 保存后需重新测试` : (isNewVersion ? `${form.name} / ${form.algorithm_id}` : '登记远程模型服务并定义可复用的输入输出。') }}</p>
        </div>
      </div>
      <el-button @click="emit('cancel')">返回管理中心</el-button>
    </header>

    <template v-if="showGuide">
      <section ref="guideBannerRef" class="guide-banner">
        <div class="guide-bar" role="button" tabindex="0" :aria-expanded="guideExpanded" @click="toggleGuide" @keydown.enter="toggleGuide">
          <div class="guide-icon"><el-icon><VideoPlay /></el-icon></div>
          <div class="guide-copy">
            <h2>教学引导</h2>
            <p v-if="guidePromptVisible" class="guide-prompt">需要引导吗？</p>
          </div>
          <div class="guide-actions" @click.stop>
            <template v-if="guidePromptVisible">
              <el-button size="small" type="primary" :icon="VideoPlay" @click="startTeaching">开始教学</el-button>
              <el-button size="small" text @click="skipTeaching">跳过</el-button>
            </template>
            <el-button v-else size="small" text type="primary" :icon="VideoPlay" @click="playTour">重新播放引导</el-button>
            <el-button
              size="small"
              text
              :aria-label="guideExpanded ? '收起引导' : '展开引导'"
              :icon="guideExpanded ? ArrowUp : ArrowDown"
              @click="toggleGuide"
            />
          </div>
        </div>
        <div v-show="guideExpanded" class="guide-body">
          <p class="guide-intro">四步完成配置；可一键填入示例，再替换成你的真实服务。</p>
          <div class="guide-examples">
            <div class="examples-head">
              <h3>示例场景 · 一键填入</h3>
              <span>仅预填技术字段，来源与归属请在正式接入时填写</span>
            </div>
            <div class="example-cards">
              <article
                v-for="example in examples"
                :key="example.id"
                class="example-card"
                :class="{ active: activeExampleId === example.id }"
              >
                <div class="example-card-head">
                  <strong>{{ example.title }}</strong>
                  <span>{{ example.tags.join(' · ') }}</span>
                </div>
                <p>{{ example.description }}</p>
                <el-button size="small" type="primary" plain :icon="MagicStick" @click="applyExample(example)">
                  {{ activeExampleId === example.id ? '已填入' : '填入此示例' }}
                </el-button>
              </article>
            </div>
          </div>
        </div>
      </section>
    </template>
    <el-alert
      v-else
      class="mode-tip"
      type="info"
      :closable="false"
      show-icon
      title="该模式沿用已登记模型信息与来源字段，仅可修改接口定义、输入输出、映射与样例；修改地址或协议请新建接口版本。"
    />

    <section ref="wizardShellRef" class="wizard-shell" aria-label="接口配置流程">
      <el-steps class="desktop-steps" :active="currentStep" finish-status="success" simple>
        <el-step v-for="(step, index) in stepItems" :key="step.title" :title="step.title">
          <template #description>{{ index === currentStep ? step.description : '' }}</template>
        </el-step>
      </el-steps>
      <div class="mobile-progress-track" aria-hidden="true">
        <i :style="{ width: `${((currentStep + 1) / stepItems.length) * 100}%` }" />
      </div>
      <div class="wizard-progress">
        <span>第 {{ currentStep + 1 }} 步，共 {{ stepItems.length }} 步</span>
        <strong>{{ stepItems[currentStep].description }}</strong>
      </div>
    </section>

    <el-alert
      v-if="form.protocol === 'mcp'"
      type="warning"
      :closable="false"
      show-icon
      title="MCP 配置可以保存；当前版本暂不支持样例测试和激活。"
    />

    <el-form label-position="top" class="config-form">
      <section v-if="currentStep === 0" class="form-band step-card">
        <div class="band-heading"><span>1</span><h2>模型信息</h2></div>
        <el-alert
          class="step-tip"
          type="info"
          :closable="false"
          show-icon
          title="来源与归属字段会展示在模型中心、详情页和结果附近；正式接入请填写真实开发者与机构，未提供授权 Logo 时使用文字来源牌。"
        />
        <div class="form-grid three-cols">
        <el-form-item label="模型 ID"><el-input v-model="form.algorithm_id" :disabled="isNewVersion || isEditVersion" /></el-form-item>
          <el-form-item label="模型名称"><el-input v-model="form.name" :disabled="isNewVersion || isEditVersion" /></el-form-item>
          <el-form-item label="版本"><el-input v-model="form.version" :disabled="isEditVersion" /></el-form-item>
          <el-form-item label="公开范围">
            <el-segmented v-model="form.visibility" :options="[{ label: '非公开', value: 'private' }, { label: '公开发布', value: 'public' }]" />
          </el-form-item>
          <el-form-item label="开发者"><el-input v-model="form.developer" :disabled="isNewVersion || isEditVersion" /></el-form-item>
          <el-form-item label="开发机构"><el-input v-model="form.developer_organization" :disabled="isNewVersion || isEditVersion" /></el-form-item>
          <el-form-item label="导师课题组"><el-input v-model="form.mentor_team" :disabled="isNewVersion || isEditVersion" /></el-form-item>
          <el-form-item label="开发者联系方式"><el-input v-model="form.developer_contact" :disabled="isNewVersion || isEditVersion" /></el-form-item>
          <el-form-item label="来源 URL"><el-input v-model="form.source_url" :disabled="isNewVersion || isEditVersion" /></el-form-item>
          <el-form-item label="Logo URL"><el-input v-model="form.logo_url" :disabled="isNewVersion || isEditVersion" placeholder="仅填写已授权或官方公开 Logo" /></el-form-item>
        </div>
        <el-form-item label="模型说明"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="引用"><el-input v-model="form.citation" type="textarea" :rows="2" :disabled="isNewVersion || isEditVersion" /></el-form-item>
      </section>

      <section v-else-if="currentStep === 1" class="form-band step-card">
        <div class="band-heading"><span>2</span><h2>接口定义</h2></div>
        <p class="step-copy">接口配置会作为不可变版本保存；修改地址或协议时，请创建新的接口版本。</p>
        <el-alert
          class="step-tip"
          type="info"
          :closable="false"
          show-icon
          title="生产环境要求 HTTPS；本地调试可指向 127.0.0.1（需开发环境允许私网访问）。响应提取路径示例：data.prediction；留空表示使用完整 JSON。"
        />
        <div class="form-grid three-cols">
          <el-form-item label="接口类型">
            <el-select v-model="form.protocol">
              <el-option label="HTTP" value="http" />
              <el-option label="FastAPI" value="fastapi" />
              <el-option label="MCP（暂不可调用）" value="mcp" />
            </el-select>
          </el-form-item>
          <el-form-item label="请求方法">
            <el-select v-model="form.http_method"><el-option v-for="method in ['GET', 'POST', 'PUT', 'PATCH']" :key="method" :label="method" :value="method" /></el-select>
          </el-form-item>
          <el-form-item label="超时（秒）"><el-input-number v-model="form.timeout_seconds" :min="1" :max="60" /></el-form-item>
        </div>
        <el-form-item label="Endpoint URL"><el-input v-model="form.endpoint_url" /></el-form-item>
        <el-form-item label="响应提取路径"><el-input v-model="form.response_selector" placeholder="例如 data.prediction；留空使用完整 JSON" /></el-form-item>
        <div class="protocol-summary">{{ interfaceProtocolLabel(form.protocol) }} · {{ form.http_method }} · JSON</div>
      </section>

      <section v-else-if="currentStep === 2" class="form-band step-card">
        <div class="band-heading"><span>3</span><h2>输入输出</h2></div>
        <p class="step-copy">字段名会用于输入表单、请求映射和结果校验；必填字段必须出现在样例输入中。</p>
        <el-alert
          class="step-tip"
          type="info"
          :closable="false"
          show-icon
          title="字段名会生成输入表单并用于请求映射；必填字段必须出现在样例输入中，建议先想清楚请求与响应结构再配置。"
        />
        <div class="schema-columns">
          <div class="schema-editor">
            <div class="editor-heading"><h3>输入字段</h3><el-button text :icon="Plus" @click="addField(inputFields)">添加</el-button></div>
            <div v-for="(row, index) in inputFields" :key="`input-${index}`" class="field-row">
              <el-input v-model="row.name" placeholder="字段名" />
              <el-select v-model="row.type"><el-option v-for="type in ['string', 'number', 'integer', 'boolean', 'object', 'list']" :key="type" :label="type" :value="type" /></el-select>
              <el-checkbox v-model="row.required">必填</el-checkbox>
              <el-input v-model="row.unit" placeholder="单位" />
              <el-button :icon="Delete" circle text aria-label="删除输入字段" @click="removeRow(inputFields, index)" />
            </div>
          </div>
          <div class="schema-editor">
            <div class="editor-heading"><h3>输出字段</h3><el-button text :icon="Plus" @click="addField(outputFields)">添加</el-button></div>
            <div v-for="(row, index) in outputFields" :key="`output-${index}`" class="field-row">
              <el-input v-model="row.name" placeholder="字段名" />
              <el-select v-model="row.type"><el-option v-for="type in ['string', 'number', 'integer', 'boolean', 'object', 'list']" :key="type" :label="type" :value="type" /></el-select>
              <el-checkbox v-model="row.required">必填</el-checkbox>
              <el-input v-model="row.unit" placeholder="单位" />
              <el-button :icon="Delete" circle text aria-label="删除输出字段" @click="removeRow(outputFields, index)" />
            </div>
          </div>
        </div>
      </section>

      <section v-else-if="currentStep === 3" class="form-band step-card">
        <div class="band-heading"><span>4</span><h2>请求映射与凭据</h2></div>
        <p class="step-copy">密钥只填写环境变量或密钥引用名，平台不会保存或回显明文凭据。</p>
        <el-alert
          class="step-tip"
          type="info"
          :closable="false"
          show-icon
          title="密钥只填写环境变量或密钥引用名（如 MODEL_API_TOKEN），平台不保存明文；认证 Query/Header 不能从普通输入映射。"
        />
        <div class="mapping-columns">
          <div v-for="group in [
            { title: 'Query 绑定', rows: queryBindings, keyPlaceholder: '远程参数', valuePlaceholder: '输入字段' },
            { title: 'Header 绑定', rows: headerBindings, keyPlaceholder: 'Header', valuePlaceholder: '输入字段' },
            { title: '静态 Header', rows: staticHeaders, keyPlaceholder: 'Header', valuePlaceholder: '非敏感值' },
            { title: '密钥引用', rows: secretRefs, keyPlaceholder: '认证 Header', valuePlaceholder: 'ENV_SECRET_REF' },
          ]" :key="group.title" class="mapping-editor">
            <div class="editor-heading"><h3>{{ group.title }}</h3><el-button text :icon="Plus" @click="addMapping(group.rows)">添加</el-button></div>
            <div v-for="(row, index) in group.rows" :key="`${group.title}-${index}`" class="mapping-row">
              <el-input v-model="row.key" :placeholder="group.keyPlaceholder" />
              <el-input v-model="row.value" :placeholder="group.valuePlaceholder" />
              <el-button :icon="Delete" circle text :aria-label="`删除${group.title}`" @click="removeRow(group.rows, index)" />
            </div>
            <span v-if="!group.rows.length" class="mapping-empty">未配置</span>
          </div>
        </div>
      </section>

      <section v-else class="form-band step-card">
        <div class="band-heading"><span>5</span><h2>样例测试与激活</h2></div>
        <el-alert
          class="step-tip"
          type="info"
          :closable="false"
          show-icon
          title="流程：保存配置 → 样例测试 → 激活并进入管理中心。接口版本不可变，修改地址或协议请新建版本。"
        />
        <el-form-item label="样例输入" :error="sampleInputError"><el-input v-model="form.sample_input" type="textarea" :rows="8" class="json-input" /></el-form-item>
        <el-alert v-if="testResult?.ok" type="success" :closable="false" show-icon :title="`调用成功 · HTTP ${testResult.status_code} · ${testResult.latency_ms} ms`" />
        <el-alert v-else-if="testResult && !testResult.ok" type="error" :closable="false" show-icon :title="testResult.error_message || '样例测试未通过'" />
        <div class="test-status">{{ savedVersion ? `已保存版本 ${savedVersion.version || form.version}，可开始样例测试。` : '先保存配置，再进行样例测试。' }}</div>
      </section>
    </el-form>

    <footer class="wizard-footer">
      <el-button :disabled="currentStep === 0 || saving || testing || activating" @click="goPrevious">上一步</el-button>
      <el-button v-if="currentStep < stepItems.length - 1" type="primary" @click="goNext">下一步</el-button>
      <template v-else>
        <el-button :loading="saving" @click="saveConfig">保存配置</el-button>
        <el-button :icon="Check" :disabled="!canTest" :loading="testing" @click="testConfig">样例测试</el-button>
        <el-button type="primary" :icon="Promotion" :disabled="!canActivate" :loading="activating" @click="activateConfig">激活并进入管理中心</el-button>
      </template>
    </footer>

    <el-tour v-model="tourVisible" :mask="true">
      <el-tour-step
        v-for="(step, index) in tourSteps"
        :key="step.title"
        :title="step.title"
        :description="step.description"
        :target="tourStepTargets[index]()"
      />
    </el-tour>
  </section>
</template>

<style scoped>
.interface-config-panel { display: grid; gap: 16px; }
.config-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; padding: 18px; border: 1px solid var(--app-border); border-radius: var(--app-radius-md); background: #fff; }
.config-title { display: flex; gap: 12px; align-items: flex-start; }
.config-title > .el-icon { width: 42px; height: 42px; border-radius: var(--app-radius-sm); background: var(--app-primary-light); color: var(--app-primary-active); font-size: 22px; }
h1, h2, h3 { margin: 0; color: var(--app-ink); letter-spacing: 0; }
h1 { font-size: 22px; }
h2 { font-size: 16px; }
h3 { font-size: 14px; }
.config-title p { margin: 6px 0 0; color: var(--app-ink-muted); font-size: 13px; }
.wizard-shell { padding: 14px 18px 12px; border: 1px solid var(--app-border); border-radius: var(--app-radius-md); background: #f8fafc; }
.mobile-progress-track { display: none; height: 6px; overflow: hidden; border-radius: 3px; background: var(--app-border-soft); }
.mobile-progress-track i { display: block; height: 100%; border-radius: inherit; background: var(--app-primary); transition: width 180ms ease; }
.wizard-progress { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 10px; color: var(--app-ink-muted); font-size: 12px; }
.wizard-progress strong { color: var(--app-ink); font-weight: 600; }
.config-form { display: grid; gap: 14px; }
.form-band { padding: 20px; border: 1px solid var(--app-border); border-radius: var(--app-radius-md); background: #fff; }
.step-card { min-height: 330px; }
.step-copy { margin: -8px 0 16px; color: var(--app-ink-muted); font-size: 13px; line-height: 1.55; }
.band-heading { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; }
.band-heading > span { display: grid; place-items: center; width: 26px; height: 26px; border-radius: 50%; background: var(--app-primary-light); color: var(--app-primary-active); font-size: 12px; font-weight: 700; }
.form-grid { display: grid; gap: 12px; }
.three-cols { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.schema-columns, .mapping-columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.schema-editor, .mapping-editor { min-width: 0; padding-top: 12px; border-top: 1px solid var(--app-border-soft); }
.editor-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 10px; }
.field-row { display: grid; grid-template-columns: minmax(110px, 1fr) 110px 64px 90px 32px; gap: 8px; align-items: center; margin-bottom: 8px; }
.mapping-row { display: grid; grid-template-columns: minmax(110px, 1fr) minmax(130px, 1fr) 32px; gap: 8px; align-items: center; margin-bottom: 8px; }
.mapping-empty { color: var(--app-ink-muted); font-size: 12px; }
.protocol-summary { color: var(--app-ink-muted); font-size: 12px; }
.json-input :deep(textarea) { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.test-status { margin-top: 12px; color: var(--app-ink-muted); font-size: 13px; }
.wizard-footer { display: flex; justify-content: flex-end; gap: 10px; flex-wrap: wrap; padding: 2px 2px 8px; }
.guide-banner { overflow: hidden; border: 1px solid var(--app-border); border-radius: var(--app-radius-md); background: linear-gradient(180deg, #ffffff 0%, #f4f8ff 100%); }
.guide-bar { display: flex; align-items: center; gap: 14px; padding: 14px 18px; cursor: pointer; user-select: none; }
.guide-icon { display: grid; place-items: center; width: 40px; height: 40px; flex: none; border-radius: var(--app-radius-sm); background: var(--app-primary-light); color: var(--app-primary-active); font-size: 20px; }
.guide-copy { min-width: 0; flex: 1 1 auto; }
.guide-copy h2 { font-size: 16px; }
.guide-copy p { margin: 4px 0 0; color: var(--app-ink-muted); font-size: 13px; line-height: 1.5; }
.guide-actions { display: flex; align-items: center; gap: 6px; flex: none; }
.guide-body { display: grid; gap: 20px; padding: 18px 18px 20px; border-top: 1px solid var(--app-border-soft); }
.guide-intro { margin: 0; color: var(--app-ink-muted); font-size: 13px; line-height: 1.6; }
.guide-examples { display: grid; gap: 12px; }
.examples-head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.examples-head h3 { font-size: 14px; }
.examples-head span { color: var(--app-ink-muted); font-size: 12px; }
.example-cards { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
.example-card { display: flex; flex-direction: column; gap: 10px; padding: 16px; border: 1px solid var(--app-border); border-radius: var(--app-radius-sm); background: #fff; }
.example-card.active { border-color: var(--app-primary-active); box-shadow: 0 0 0 1px var(--app-primary-active); }
.example-card-head strong { display: block; color: var(--app-ink); font-size: 13px; }
.example-card-head span { color: var(--app-primary-active); font-size: 11px; }
.example-card p { margin: 0; flex: 1 1 auto; color: var(--app-ink-muted); font-size: 12px; line-height: 1.5; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; }
.step-tip { margin-bottom: 16px; }
.mode-tip { margin-bottom: 14px; }
@media (max-width: 1200px) { .example-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 680px) { .guide-bar { flex-wrap: wrap; row-gap: 10px; } .guide-actions { flex: 1 1 100%; justify-content: flex-end; } .example-cards { grid-template-columns: 1fr; } }
@media (max-width: 1024px) { .three-cols { grid-template-columns: repeat(2, minmax(0, 1fr)); } .schema-columns, .mapping-columns { grid-template-columns: 1fr; } }
@media (max-width: 680px) { .config-header { flex-direction: column; } .desktop-steps { display: none; } .mobile-progress-track { display: block; } .three-cols { grid-template-columns: 1fr; } .field-row { grid-template-columns: minmax(0, 1fr) 100px; } .field-row > :nth-child(n + 3) { grid-column: auto; } .wizard-progress { align-items: flex-start; flex-direction: column; } .wizard-footer { justify-content: stretch; } .wizard-footer .el-button { flex: 1 1 100%; margin-left: 0; } }
</style>
