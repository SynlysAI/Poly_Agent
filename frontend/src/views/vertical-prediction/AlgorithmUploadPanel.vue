<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, Delete, Download, Plus, UploadFilled } from '@element-plus/icons-vue'

import {
  activateAlgorithmVersion,
  buildAlgorithmPackage,
  deployAlgorithmVersion,
  downloadAlgorithmPackage,
  downloadAlgorithmPackageTemplate,
  getApiErrorMessage,
  packAlgorithmPackage,
  uploadAlgorithmPackage,
  validateAlgorithmPackage,
} from '../../api/polyAgentApi'

const emit = defineEmits(['changed', 'view-detail'])

const currentStep = ref(0)
const uploadMode = ref('script')
const loading = ref(false)
const sourceFiles = ref([])
const requirementsFiles = ref([])
const zipFiles = ref([])
const currentPackage = ref(null)
const expandedAdvanced = ref([])

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
  sample_input: JSON.stringify({ smiles: 'C=C(F)F' }, null, 2),
})

const inputFields = ref([
  { name: 'smiles', type: 'string', required: true, unit: '', options: '', min: '', max: '' },
])
const outputFields = ref([
  { name: 'prediction', type: 'object', required: true, unit: '', options: '', min: '', max: '' },
])

const sampleJsonError = computed(() => {
  try {
    const value = JSON.parse(form.sample_input)
    return value && typeof value === 'object' && !Array.isArray(value) ? '' : '样例输入必须是 JSON object'
  } catch (error) {
    return `JSON 格式错误：${error.message}`
  }
})

const contract = computed(() => ({
  contract_version: '0.1',
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
  sample_input_path: 'tests/sample_input.json',
  description: form.description || null,
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

function saveBlob(file) {
  const url = URL.createObjectURL(file.blob)
  const link = document.createElement('a')
  link.href = url
  link.download = file.filename
  link.click()
  URL.revokeObjectURL(url)
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
    saveBlob(await downloadAlgorithmPackage(currentPackage.value.package_id, currentPackage.value.filename))
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  }
}

function validateBeforeSubmit() {
  if (uploadMode.value === 'zip') {
    if (!zipFiles.value[0]?.raw) return '请选择标准 ZIP 文件'
    return ''
  }
  if (!form.algorithm_id.trim()) return '请填写算法 ID'
  if (!form.name.trim()) return '请填写模型名称'
  if (!form.version.trim()) return '请填写版本号'
  if (!sourceFiles.value.length) return '请至少选择一个 Python 源文件'
  if (sampleJsonError.value) return sampleJsonError.value
  return ''
}

async function finalizePackage(pkg) {
  let current = pkg
  if (current.status !== 'validated') current = await validateAlgorithmPackage(current.package_id)
  currentPackage.value = current
  current = await buildAlgorithmPackage(current.package_id)
  currentPackage.value = current
  const version = await deployAlgorithmVersion(current.algorithm_id, current.version_id)
  currentPackage.value = { ...current, status: version.status }
  await activateAlgorithmVersion(current.algorithm_id, current.version_id)
  currentPackage.value = { ...currentPackage.value, status: 'active' }
}

async function submit() {
  const warning = validateBeforeSubmit()
  if (warning) {
    ElMessage.warning(warning)
    return
  }
  loading.value = true
  currentStep.value = 2
  currentPackage.value = null
  try {
    let pkg
    if (uploadMode.value === 'zip') {
      const data = new FormData()
      data.append('file', zipFiles.value[0].raw)
      pkg = await uploadAlgorithmPackage(data)
    } else {
      const data = new FormData()
      for (const key of ['algorithm_id', 'name', 'version', 'algorithm_family', 'type', 'entrypoint', 'loader', 'description']) {
        if (form[key]) data.append(key, form[key])
      }
      data.append('material_scope', JSON.stringify(form.material_scope))
      data.append('task_scope', JSON.stringify(form.task_scope))
      data.append('trigger_modes', JSON.stringify(form.trigger_modes))
      data.append('input_schema', JSON.stringify(contract.value.input_schema))
      data.append('output_schema', JSON.stringify(contract.value.output_schema))
      data.append('runtime', JSON.stringify(contract.value.runtime))
      data.append('sample_input', form.sample_input)
      sourceFiles.value.forEach((file) => data.append('files', file.raw))
      if (requirementsFiles.value[0]?.raw) data.append('requirements', requirementsFiles.value[0].raw)
      pkg = await packAlgorithmPackage(data)
    }
    currentPackage.value = pkg
    await finalizePackage(pkg)
    emit('changed', currentPackage.value)
    ElMessage.success('模型版本已完成校验、部署并激活')
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

function resetForNextUpload() {
  currentPackage.value = null
  currentStep.value = 0
  sourceFiles.value = []
  requirementsFiles.value = []
  zipFiles.value = []
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
          <p class="wizard-eyebrow">模型上传向导</p>
          <h2>用最少信息发布一个垂类预测模型</h2>
          <p>普通用户只需要模型信息、Python 文件和样例输入；契约和入口函数可在高级配置中调整。</p>
        </div>
        <el-button :icon="Download" @click="downloadTemplate">下载标准模板</el-button>
      </div>
      <el-steps :active="currentStep" finish-status="success" simple>
        <el-step title="选择方式" />
        <el-step title="填写信息" />
        <el-step title="校验部署" />
      </el-steps>
    </div>

    <section class="wizard-section">
      <div class="section-heading">
        <div>
          <h3>1. 选择上传方式</h3>
          <p>推荐直接上传 Python 脚本，平台会打包为标准 ZIP；高级用户也可以上传完整 ZIP。</p>
        </div>
      </div>
      <el-segmented
        v-model="uploadMode"
        :options="[{ label: 'Python 脚本', value: 'script' }, { label: '标准 ZIP', value: 'zip' }]"
        @change="currentStep = 1"
      />
    </section>

    <section class="wizard-section">
      <div class="section-heading">
        <div>
          <h3>2. 填写必要信息</h3>
          <p>{{ uploadMode === 'zip' ? 'ZIP 内需要包含 polyagent.algorithm.yaml。' : '这几项会生成模型卡片、版本记录和测试表单。' }}</p>
        </div>
      </div>

      <template v-if="uploadMode === 'script'">
        <el-form label-position="top" class="metadata-form">
          <div class="simple-form-grid">
            <el-form-item label="模型名称"><el-input v-model="form.name" placeholder="例如 Polymer Tg Predictor" /></el-form-item>
            <el-form-item label="算法 ID"><el-input v-model="form.algorithm_id" placeholder="vertical_tg_predictor" /></el-form-item>
            <el-form-item label="版本"><el-input v-model="form.version" placeholder="0.1.0" /></el-form-item>
          </div>
          <el-form-item label="一句话说明"><el-input v-model="form.description" type="textarea" :rows="2" placeholder="说明这个模型适合预测什么、输入是什么。" /></el-form-item>
        </el-form>

        <div class="source-grid">
          <section>
            <h3>算法文件</h3>
            <el-upload v-model:file-list="sourceFiles" drag multiple :auto-upload="false" accept=".py,.json,.md,.txt,.pkl,.joblib,.npy,.npz,.csv" @change="currentStep = Math.max(currentStep, 1)">
              <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
              <div class="el-upload__text">拖入 Python 源文件，或点击选择</div>
            </el-upload>
            <el-upload v-model:file-list="requirementsFiles" :auto-upload="false" :limit="1" accept=".txt">
              <el-button>选择 requirements.txt</el-button>
            </el-upload>
          </section>
          <section>
            <h3>样例输入</h3>
            <el-input v-model="form.sample_input" type="textarea" :rows="8" class="code-input" />
            <el-alert v-if="sampleJsonError" :title="sampleJsonError" type="error" :closable="false" show-icon />
          </section>
        </div>

        <el-collapse v-model="expandedAdvanced" class="advanced-collapse">
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
              </div>
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

      <section v-else class="zip-upload">
        <el-upload v-model:file-list="zipFiles" drag :auto-upload="false" :limit="1" accept=".zip" @change="currentStep = Math.max(currentStep, 1)">
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">拖入标准 ZIP，或点击选择</div>
        </el-upload>
      </section>
    </section>

    <section class="wizard-section">
      <div class="submit-row">
        <div>
          <h3>3. 校验、部署并激活</h3>
          <p>提交后平台会自动打包、校验、构建、部署并激活版本。</p>
        </div>
        <el-button type="primary" :loading="loading" @click="submit">校验部署</el-button>
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
          <span>{{ currentPackage.algorithm_id || currentPackage.filename }}</span>
          <el-button text :icon="Download" @click="downloadGeneratedPackage">下载标准 ZIP</el-button>
        </div>
        <div class="success-buttons">
          <el-button @click="resetForNextUpload">继续上传新版本</el-button>
          <el-button type="primary" @click="viewModelDetail">查看模型详情</el-button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.upload-workspace { display: grid; gap: 16px; }
.wizard-shell, .wizard-section { border: 1px solid var(--app-border); border-radius: var(--app-radius-md); background: #fff; padding: 16px; }
.wizard-head, .section-heading, .submit-row, .success-actions { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.wizard-eyebrow { margin: 0 0 4px; color: var(--app-primary-active); font-size: 12px; font-weight: 700; }
h2, h3 { margin: 0; color: var(--app-ink); letter-spacing: 0; }
h2 { font-size: 22px; line-height: 1.25; }
h3 { font-size: 15px; }
.wizard-head p:last-child, .section-heading p, .submit-row p { margin: 4px 0 0; color: var(--app-ink-muted); font-size: 13px; line-height: 1.55; }
.wizard-shell :deep(.el-steps) { margin-top: 16px; }
.metadata-form { margin-top: 12px; }
.simple-form-grid { display: grid; grid-template-columns: minmax(220px, 1.2fr) minmax(180px, 1fr) 140px; gap: 0 14px; }
.form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 0 14px; }
.source-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, 0.9fr); gap: 18px; margin-top: 8px; }
.source-grid section { min-width: 0; }
.source-grid h3, .contract-preview h3 { margin-bottom: 10px; }
.code-input :deep(textarea), pre { font-family: var(--app-mono-font); font-size: 12px; }
.advanced-collapse { margin-top: 16px; border-top: 1px solid var(--app-border-soft); border-bottom: none; }
.advanced-title { color: var(--app-ink); font-weight: 700; }
.schema-section, .contract-preview { border-top: 1px solid var(--app-border-soft); padding-top: 16px; margin-top: 14px; }
.section-heading { margin-bottom: 10px; }
.range-inputs { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.contract-preview pre { margin: 0; max-height: 260px; overflow: auto; padding: 14px; border: 1px solid var(--app-border); border-radius: var(--app-radius-sm); background: #f8fafc; white-space: pre-wrap; }
.zip-upload { max-width: 760px; margin-top: 8px; }
.validation-results { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 14px; }
.validation-results div { min-width: 0; display: grid; grid-template-columns: 20px 1fr; gap: 4px 8px; padding: 12px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-sm); background: #f8fbff; }
.validation-results .el-icon { grid-row: span 2; color: var(--app-ink-subtle); margin-top: 2px; }
.validation-results div.done { border-color: #bbf7d0; background: #f0fdf4; }
.validation-results div.done .el-icon { color: #16a34a; }
.validation-results strong { color: var(--app-ink); font-size: 13px; }
.validation-results span { color: var(--app-ink-muted); font-size: 12px; overflow-wrap: anywhere; }
.package-status, .success-buttons { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.package-status { min-width: 0; color: var(--app-ink-body); }
@media (max-width: 1100px) { .validation-results { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) {
  .wizard-head, .section-heading, .submit-row, .success-actions { align-items: stretch; flex-direction: column; }
  .simple-form-grid, .form-grid, .source-grid, .validation-results { grid-template-columns: 1fr; }
}
</style>
