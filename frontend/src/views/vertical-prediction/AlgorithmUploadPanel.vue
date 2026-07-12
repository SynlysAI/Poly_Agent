<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, Download, Plus, UploadFilled } from '@element-plus/icons-vue'

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

const emit = defineEmits(['changed'])

const uploadMode = ref('script')
const loading = ref(false)
const sourceFiles = ref([])
const requirementsFiles = ref([])
const zipFiles = ref([])
const currentPackage = ref(null)

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
  if (sampleJsonError.value && uploadMode.value === 'script') {
    ElMessage.warning(sampleJsonError.value)
    return
  }
  loading.value = true
  currentPackage.value = null
  try {
    let pkg
    if (uploadMode.value === 'zip') {
      const file = zipFiles.value[0]?.raw
      if (!file) throw new Error('请选择标准 ZIP 文件')
      const data = new FormData()
      data.append('file', file)
      pkg = await uploadAlgorithmPackage(data)
    } else {
      if (!sourceFiles.value.length) throw new Error('请至少选择一个 Python 源文件')
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
    ElMessage.success('算法版本已完成校验、部署并激活')
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

function statusType(status) {
  return status === 'active' ? 'success' : status?.includes('failed') ? 'danger' : 'warning'
}
</script>

<template>
  <div class="upload-workspace" v-loading="loading">
    <div class="upload-toolbar">
      <el-segmented v-model="uploadMode" :options="[{ label: '上传 Python 脚本', value: 'script' }, { label: '上传标准 ZIP', value: 'zip' }]" />
      <el-button :icon="Download" @click="downloadTemplate">下载模板</el-button>
    </div>

    <template v-if="uploadMode === 'script'">
      <el-form label-position="top" class="metadata-form">
        <div class="form-grid">
          <el-form-item label="算法 ID"><el-input v-model="form.algorithm_id" /></el-form-item>
          <el-form-item label="算法名称"><el-input v-model="form.name" /></el-form-item>
          <el-form-item label="版本"><el-input v-model="form.version" /></el-form-item>
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
        <el-form-item label="说明"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
      </el-form>

      <section class="schema-section">
        <div class="section-heading"><div><h3>输入契约</h3><p>字段类型直接用于测试台表单渲染。</p></div><el-button :icon="Plus" @click="addField(inputFields)">添加字段</el-button></div>
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

      <div class="source-grid">
        <section>
          <h3>算法文件</h3>
          <el-upload v-model:file-list="sourceFiles" drag multiple :auto-upload="false" accept=".py,.json,.md,.txt,.pkl,.joblib,.npy,.npz,.csv">
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon><div class="el-upload__text">拖入 Python 源文件，或点击选择</div>
          </el-upload>
          <el-upload v-model:file-list="requirementsFiles" :auto-upload="false" :limit="1" accept=".txt"><el-button>选择 requirements.txt</el-button></el-upload>
        </section>
        <section>
          <h3>样例输入</h3>
          <el-input v-model="form.sample_input" type="textarea" :rows="9" class="code-input" />
          <el-alert v-if="sampleJsonError" :title="sampleJsonError" type="error" :closable="false" show-icon />
        </section>
      </div>

      <section class="contract-preview"><h3>polyagent.algorithm.yaml 预览</h3><pre>{{ contractPreview }}</pre></section>
    </template>

    <section v-else class="zip-upload">
      <el-upload v-model:file-list="zipFiles" drag :auto-upload="false" :limit="1" accept=".zip">
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon><div class="el-upload__text">拖入标准 ZIP，或点击选择</div>
      </el-upload>
    </section>

    <div class="submit-row">
      <div v-if="currentPackage" class="package-status">
        <el-tag :type="statusType(currentPackage.status)">{{ currentPackage.status }}</el-tag>
        <span>{{ currentPackage.algorithm_id || currentPackage.filename }}</span>
        <el-button text :icon="Download" @click="downloadGeneratedPackage">下载标准 ZIP</el-button>
      </div>
      <el-button type="primary" :loading="loading" @click="submit">校验、部署并激活</el-button>
    </div>

    <section v-if="currentPackage" class="validation-results">
      <div><strong>文件与契约</strong><span>{{ currentPackage.validation_logs?.[0] || '等待校验' }}</span></div>
      <div><strong>Schema 与入口</strong><span>{{ currentPackage.validation_logs?.[1] || '等待校验' }}</span></div>
      <div><strong>Dry-run</strong><span>{{ currentPackage.validation_logs?.[2] || '等待校验' }}</span></div>
      <div><strong>构建与部署</strong><span>{{ currentPackage.deployment_logs?.[0] || currentPackage.build_logs?.at(-1) || currentPackage.status }}</span></div>
    </section>
  </div>
</template>

<style scoped>
.upload-workspace { display: grid; gap: 18px; }
.upload-toolbar, .section-heading, .submit-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.metadata-form { padding-top: 4px; }
.form-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0 14px; }
.schema-section, .contract-preview, .validation-results { border-top: 1px solid var(--app-border-soft); padding-top: 16px; }
.section-heading { margin-bottom: 10px; }
h3 { margin: 0; font-size: 15px; }
.section-heading p { margin: 3px 0 0; color: var(--app-ink-muted); font-size: 12px; }
.range-inputs { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.source-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.source-grid section { min-width: 0; }
.source-grid h3, .contract-preview h3 { margin-bottom: 10px; }
.code-input :deep(textarea), pre { font-family: var(--app-mono-font); font-size: 12px; }
.contract-preview pre { margin: 0; max-height: 320px; overflow: auto; padding: 14px; border: 1px solid var(--app-border); border-radius: var(--app-radius-sm); background: #f8fafc; white-space: pre-wrap; }
.zip-upload { max-width: 680px; }
.package-status { display: flex; align-items: center; gap: 10px; min-width: 0; color: var(--app-ink-body); }
.validation-results { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.validation-results div { display: grid; gap: 4px; padding: 10px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-sm); }
.validation-results span { color: var(--app-ink-muted); font-size: 12px; overflow-wrap: anywhere; }
@media (max-width: 1100px) { .form-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .validation-results { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 720px) { .upload-toolbar, .section-heading, .submit-row { align-items: stretch; flex-direction: column; } .form-grid, .source-grid, .validation-results { grid-template-columns: 1fr; } }
</style>
