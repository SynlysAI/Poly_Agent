<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Check, Download, Refresh, UploadFilled, VideoPlay } from '@element-plus/icons-vue'

import {
  activateAlgorithmVersion,
  buildAlgorithmPackage,
  createAlgorithmHandoff,
  deployAlgorithmVersion,
  downloadAlgorithmHandoffPackage,
  downloadAlgorithmRequirementDocumentTemplate,
  getAlgorithmHandoff,
  getApiErrorMessage,
  listAlgorithmHandoffs,
  listAlgorithmPackageExamples,
  markAlgorithmHandoffSubmitted,
  parseAlgorithmRequirementDocument,
  uploadAlgorithmPackage,
  validateAlgorithmHandoffPackage,
  validateAlgorithmPackage,
} from '../../api/polyAgentApi'

const props = defineProps({
  initialHandoffId: { type: String, default: '' },
  entryMode: { type: String, default: 'upload' },
})
const emit = defineEmits(['changed'])
const route = useRoute()
const router = useRouter()

const loading = ref(false)
const deploying = ref(false)
const examples = ref([])
const handoffs = ref([])
const currentHandoff = ref(null)
const documentFiles = ref([])
const uploadFiles = ref([])
const validation = ref(null)
const parsedDocument = ref(null)
const applyingDocumentDraft = ref(false)
const handoffStep = ref(0)
const showHistory = ref(false)
const requirementDocumentAccept = '.docx,.md,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/markdown,text/x-markdown'
const requirementDocumentExtensions = new Set(['docx', 'md'])

const form = reactive({
  algorithm_id: 'electrolyte_formulation_predictor',
  name: '含氟电解液配方性能预测',
  version: '0.1.0',
  example_id: 'batch_formulation_predictor',
  owner_name: '',
  owner_contact: '',
  developer_organization: '',
  mentor_team: '',
  visibility: 'private',
  description: '根据锂盐、溶剂/单体/填料组成及配比，预测放电比容量和库仑效率。',
  material_scope: ['fluoropolymer'],
  requirements_hint: 'rdkit, scikit-learn, joblib',
  input_schema: JSON.stringify({ fields: { formulations: 'list' }, required: ['formulations'] }, null, 2),
  output_schema: JSON.stringify({ fields: { results: 'list' }, required: ['results'] }, null, 2),
  sample_input: JSON.stringify({
    formulations: [
      {
        formula_id: 'TEST-001',
        task_type: 'electrolyte',
        lithium_salt: 'LiTFSI',
        lithium_salt_mol_L: 1.0,
        electrolyte_component_1: 'FEC',
        electrolyte_component_1_mol_ratio: 1,
        electrolyte_component_2: 'DME',
        electrolyte_component_2_mol_ratio: 1,
      },
    ],
  }, null, 2),
})

const statusCards = computed(() => {
  const status = currentHandoff.value?.status || 'draft'
  return [
    { key: 'draft', label: '草案', done: ['draft', 'package_downloaded', 'self_test_failed', 'self_test_passed', 'submitted'].includes(status) },
    { key: 'package_downloaded', label: '接入包', done: ['package_downloaded', 'self_test_failed', 'self_test_passed', 'submitted'].includes(status) },
    { key: 'self_test_passed', label: status === 'self_test_failed' ? '自测失败' : '自测通过', done: ['self_test_passed', 'submitted'].includes(status), failed: status === 'self_test_failed' },
    { key: 'submitted', label: '提交正式部署', done: status === 'submitted' },
  ]
})

const selectedExample = computed(() => examples.value.find((item) => item.example_id === form.example_id) || null)
const canDeploy = computed(() => validation.value?.ok && uploadFiles.value[0]?.raw && currentHandoff.value?.handoff_id)
const handoffStepIndicator = computed(() => (handoffStep.value >= 4 ? 5 : handoffStep.value))
const entryHint = computed(() => (props.entryMode === 'download' ? '没有模板先下载 docx，再填写后上传。' : '支持上传已填写的 docx 或 Markdown 需求文档。'))
const handoffStepTitle = computed(() => {
  const titles = ['需求文档', '确认草案', '下载接入包', '上传自测', '正式部署结果']
  return titles[handoffStep.value] || titles[0]
})
const documentSummary = computed(() => {
  if (!parsedDocument.value) return null
  return {
    title: parsedDocument.value.summary?.title || form.name,
    warnings: parsedDocument.value.warnings || [],
    missingFields: parsedDocument.value.missing_fields || [],
  }
})

function stepForStatus(status) {
  if (status === 'submitted') return 4
  if (status === 'self_test_passed' || status === 'self_test_failed') return 3
  if (status === 'package_downloaded') return 3
  if (status === 'draft') return 2
  return 0
}

function syncHandoffRoute(handoffId) {
  if (!handoffId) return
  const query = {
    ...route.query,
    tab: 'doc',
    handoff_id: handoffId,
    doc_mode: props.entryMode === 'download' ? 'download' : 'upload',
  }
  if (JSON.stringify(query) !== JSON.stringify(route.query)) {
    router.replace({ query })
  }
}

watch(() => form.example_id, (value) => {
  if (applyingDocumentDraft.value) return
  if (value === 'batch_formulation_predictor') applyBatchDefaults()
  if (value === 'generic_python_predictor' || value === 'smiles_property_predictor') applySmilesDefaults()
})

function applyBatchDefaults() {
  form.algorithm_id = form.algorithm_id || 'electrolyte_formulation_predictor'
  form.material_scope = ['fluoropolymer']
  form.input_schema = JSON.stringify({ fields: { formulations: 'list' }, required: ['formulations'] }, null, 2)
  form.output_schema = JSON.stringify({ fields: { results: 'list' }, required: ['results'] }, null, 2)
}

function applySmilesDefaults() {
  form.material_scope = ['universal']
  form.input_schema = JSON.stringify({ fields: { smiles: 'string' }, required: ['smiles'] }, null, 2)
  form.output_schema = JSON.stringify({ fields: { prediction: 'object' }, required: ['prediction'] }, null, 2)
  form.sample_input = JSON.stringify({ smiles: 'C=C(F)F' }, null, 2)
}

function parseJsonField(value, label) {
  try {
    const parsed = JSON.parse(value)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error(`${label} 必须是 JSON object`)
    return parsed
  } catch (error) {
    throw new Error(`${label} 格式错误：${error.message}`)
  }
}

function requirementsHint() {
  return form.requirements_hint.split(',').map((item) => item.trim()).filter(Boolean)
}

function applyDocumentDraft(draft) {
  applyingDocumentDraft.value = true
  try {
    form.algorithm_id = draft.algorithm_id || form.algorithm_id
    form.name = draft.name || form.name
    form.version = draft.version || form.version
    form.example_id = draft.example_id || form.example_id
    form.owner_name = draft.owner_name || ''
    form.owner_contact = draft.owner_contact || ''
    form.developer_organization = draft.developer_organization || ''
    form.mentor_team = draft.mentor_team || ''
    form.visibility = draft.visibility === 'public' ? 'public' : 'private'
    form.description = draft.description || form.description
    form.material_scope = draft.material_scope?.length ? [...draft.material_scope] : form.material_scope
    form.requirements_hint = (draft.requirements_hint || []).join(', ')
    form.input_schema = JSON.stringify(draft.input_schema || {}, null, 2)
    form.output_schema = JSON.stringify(draft.output_schema || {}, null, 2)
    form.sample_input = JSON.stringify(draft.sample_input || {}, null, 2)
  } finally {
    applyingDocumentDraft.value = false
  }
}

function applyHandoffRecord(handoff) {
  if (!handoff) return
  applyingDocumentDraft.value = true
  try {
    form.algorithm_id = handoff.algorithm_id || form.algorithm_id
    form.name = handoff.name || form.name
    form.version = handoff.version || form.version
    form.example_id = handoff.example_id || form.example_id
    form.owner_name = handoff.owner_name || ''
    form.owner_contact = handoff.owner_contact || ''
    form.developer_organization = handoff.developer_organization || ''
    form.mentor_team = handoff.mentor_team || ''
    form.visibility = handoff.visibility === 'public' ? 'public' : 'private'
    form.description = handoff.description || ''
    form.material_scope = handoff.material_scope?.length ? [...handoff.material_scope] : form.material_scope
    form.requirements_hint = (handoff.requirements_hint || []).join(', ')
    form.input_schema = JSON.stringify(handoff.input_schema || {}, null, 2)
    form.output_schema = JSON.stringify(handoff.output_schema || {}, null, 2)
    form.sample_input = JSON.stringify(handoff.sample_input || {}, null, 2)
  } finally {
    applyingDocumentDraft.value = false
  }
}

function saveBlob(file) {
  const url = URL.createObjectURL(file.blob)
  const link = document.createElement('a')
  link.href = url
  link.download = file.filename
  link.click()
  URL.revokeObjectURL(url)
}

function handleDocumentFileChange(file, files) {
  const name = file?.name || file?.raw?.name || ''
  const extension = name.split('.').pop()?.toLowerCase()
  if (!requirementDocumentExtensions.has(extension)) {
    documentFiles.value = files.filter((item) => item.uid !== file.uid)
    ElMessage.warning('需求文档仅支持 .docx 或 .md 文件')
  }
}

async function loadData() {
  loading.value = true
  try {
    const [exampleData, handoffData] = await Promise.all([
      listAlgorithmPackageExamples(),
      listAlgorithmHandoffs({ page: 1, page_size: 50 }),
    ])
    examples.value = exampleData.items || []
    handoffs.value = handoffData.items || []
    const handoffId = props.initialHandoffId || currentHandoff.value?.handoff_id
    if (handoffId) {
      currentHandoff.value = await getAlgorithmHandoff(handoffId)
      applyHandoffRecord(currentHandoff.value)
      validation.value = currentHandoff.value.last_validation || null
      handoffStep.value = stepForStatus(currentHandoff.value.status)
      syncHandoffRoute(handoffId)
    }
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function downloadRequirementTemplate() {
  try {
    saveBlob(await downloadAlgorithmRequirementDocumentTemplate())
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  }
}

async function parseRequirementDocument() {
  if (!documentFiles.value[0]?.raw) {
    ElMessage.warning('请先上传已填写的需求文档')
    return
  }
  loading.value = true
  try {
    const data = new FormData()
    data.append('file', documentFiles.value[0].raw)
    parsedDocument.value = await parseAlgorithmRequirementDocument(data)
    currentHandoff.value = null
    validation.value = null
    applyDocumentDraft(parsedDocument.value.draft)
    handoffStep.value = 1
    ElMessage.success('需求文档已解析为接入草案')
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function createHandoff() {
  loading.value = true
  validation.value = null
  try {
    const payload = {
      algorithm_id: form.algorithm_id.trim(),
      name: form.name.trim(),
      version: form.version.trim(),
      example_id: form.example_id,
      owner_name: form.owner_name.trim() || null,
      owner_contact: form.owner_contact.trim() || null,
      developer_organization: form.developer_organization.trim() || null,
      mentor_team: form.mentor_team.trim() || null,
      description: form.description.trim() || null,
      material_scope: form.material_scope,
      input_schema: parseJsonField(form.input_schema, '输入契约'),
      output_schema: parseJsonField(form.output_schema, '输出契约'),
      sample_input: parseJsonField(form.sample_input, '样例输入'),
      requirements_hint: requirementsHint(),
      visibility: form.visibility,
    }
    currentHandoff.value = await createAlgorithmHandoff(payload)
    validation.value = null
    syncHandoffRoute(currentHandoff.value.handoff_id)
    await loadData()
    handoffStep.value = 2
    ElMessage.success('接入任务已创建')
  } catch (error) {
    ElMessage.error(error.message || getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function downloadHandoffPackage() {
  if (!currentHandoff.value?.handoff_id) return
  try {
    saveBlob(await downloadAlgorithmHandoffPackage(currentHandoff.value.handoff_id))
    currentHandoff.value = await getAlgorithmHandoff(currentHandoff.value.handoff_id)
    await loadData()
    handoffStep.value = 3
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  }
}

async function validateUpload() {
  if (!currentHandoff.value?.handoff_id) {
    ElMessage.warning('请先创建接入任务')
    return
  }
  if (!uploadFiles.value[0]?.raw) {
    ElMessage.warning('请选择对接人上传的 ZIP')
    return
  }
  loading.value = true
  try {
    const data = new FormData()
    data.append('file', uploadFiles.value[0].raw)
    validation.value = await validateAlgorithmHandoffPackage(currentHandoff.value.handoff_id, data)
    currentHandoff.value = await getAlgorithmHandoff(currentHandoff.value.handoff_id)
    await loadData()
    handoffStep.value = 3
    ElMessage[validation.value.ok ? 'success' : 'warning'](validation.value.ok ? '自测通过' : '自测失败，请查看修复建议')
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function deployValidatedPackage() {
  if (!canDeploy.value) return
  deploying.value = true
  try {
    const data = new FormData()
    data.append('file', uploadFiles.value[0].raw)
    data.append('handoff_id', currentHandoff.value.handoff_id)
    let pkg = await uploadAlgorithmPackage(data)
    pkg = await validateAlgorithmPackage(pkg.package_id)
    pkg = await buildAlgorithmPackage(pkg.package_id)
    const version = await deployAlgorithmVersion(pkg.algorithm_id, pkg.version_id)
    await activateAlgorithmVersion(pkg.algorithm_id, pkg.version_id)
    currentHandoff.value = await markAlgorithmHandoffSubmitted(currentHandoff.value.handoff_id)
    syncHandoffRoute(currentHandoff.value.handoff_id)
    emit('changed', { ...pkg, status: 'active', version_id: version.version_id })
    await loadData()
    handoffStep.value = 4
    ElMessage.success('已提交正式部署并激活')
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    deploying.value = false
  }
}

function selectHandoff(row) {
  currentHandoff.value = row
  applyHandoffRecord(row)
  validation.value = row.last_validation || null
  handoffStep.value = stepForStatus(row.status)
  syncHandoffRoute(row.handoff_id)
  showHistory.value = false
}

function statusLabel(status) {
  const map = {
    draft: '草案',
    package_downloaded: '接入包',
    self_test_failed: '自测失败',
    self_test_passed: '自测通过',
    submitted: '提交正式部署',
  }
  return map[status] || status || '-'
}

function statusType(status) {
  const map = {
    draft: 'info',
    package_downloaded: 'warning',
    self_test_failed: 'danger',
    self_test_passed: 'success',
    submitted: 'success',
  }
  return map[status] || 'info'
}

watch(() => props.initialHandoffId, () => {
  loadData()
}, { immediate: true })
</script>

<template>
  <div class="handoff-panel" v-loading="loading">
    <section class="handoff-card">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">需求文档接入</p>
          <h2>{{ handoffStepTitle }}</h2>
          <p>按步骤完成垂类模型需求解析、草案确认、接入包下载、自测和正式部署。</p>
        </div>
        <div class="heading-actions">
          <el-button @click="showHistory = true">接入任务历史</el-button>
          <el-button :icon="Refresh" @click="loadData">刷新</el-button>
        </div>
      </div>

      <el-steps :active="handoffStepIndicator" finish-status="success" simple class="handoff-steps">
        <el-step title="需求文档" />
        <el-step title="确认草案" />
        <el-step title="接入包" />
        <el-step title="自测" />
        <el-step title="部署结果" />
      </el-steps>

      <section v-if="handoffStep === 0" class="handoff-step">
        <div class="doc-entry">
          <div class="doc-entry-head">
            <div>
              <h3>上传垂类模型需求</h3>
              <p>{{ entryHint }}</p>
            </div>
            <el-button :icon="Download" @click="downloadRequirementTemplate">下载 docx 模板</el-button>
          </div>
          <div class="doc-entry-actions">
            <el-upload
              v-model:file-list="documentFiles"
              :auto-upload="false"
              :limit="1"
              :accept="requirementDocumentAccept"
              drag
              class="requirement-upload"
              @change="handleDocumentFileChange"
            >
              <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
              <div class="el-upload__text">拖入已填写的 docx / md，或点击选择</div>
              <template #tip>
                <div class="upload-tip">请使用标准模板填写；Markdown 需保留 YAML front matter。</div>
              </template>
            </el-upload>
            <el-button type="primary" :loading="loading" @click="parseRequirementDocument">解析草案</el-button>
            <el-button text @click="handoffStep = 1">手动填写草案</el-button>
          </div>
        </div>
      </section>

      <section v-else-if="handoffStep === 1" class="handoff-step">
        <el-alert v-if="documentSummary" :closable="false" type="info" show-icon class="draft-alert">
          <template #title>已生成草案：{{ documentSummary.title }}</template>
          <div class="doc-summary">
            <span v-if="parsedDocument?.draft?.algorithm_id">算法 ID：{{ parsedDocument.draft.algorithm_id }}</span>
            <span v-if="parsedDocument?.draft?.example_id">模板：{{ parsedDocument.draft.example_id }}</span>
            <span v-if="documentSummary.missingFields.length">待补：{{ documentSummary.missingFields.join('、') }}</span>
          </div>
          <div v-if="documentSummary.warnings.length" class="doc-warnings">
            <p v-for="warning in documentSummary.warnings" :key="warning">{{ warning }}</p>
          </div>
        </el-alert>

        <el-form label-position="top">
          <div class="form-grid">
            <el-form-item label="模板类型">
              <el-select v-model="form.example_id" filterable>
                <el-option v-for="item in examples" :key="item.example_id" :label="item.name" :value="item.example_id" />
              </el-select>
            </el-form-item>
            <el-form-item label="算法 ID"><el-input v-model="form.algorithm_id" /></el-form-item>
            <el-form-item label="算法名称"><el-input v-model="form.name" /></el-form-item>
            <el-form-item label="版本"><el-input v-model="form.version" /></el-form-item>
          </div>
          <div class="form-grid">
            <el-form-item label="负责人"><el-input v-model="form.owner_name" /></el-form-item>
            <el-form-item label="联系方式"><el-input v-model="form.owner_contact" /></el-form-item>
            <el-form-item label="机构"><el-input v-model="form.developer_organization" placeholder="开发机构或单位，可留空" /></el-form-item>
            <el-form-item label="导师课题组"><el-input v-model="form.mentor_team" placeholder="例如 张三教授课题组" /></el-form-item>
            <el-form-item label="材料范围">
              <el-select v-model="form.material_scope" multiple>
                <el-option label="通用" value="universal" />
                <el-option label="氟基" value="fluoropolymer" />
                <el-option label="碳基" value="carbon_polymer" />
                <el-option label="硅基" value="silicon_polymer" />
                <el-option label="氟碳共聚" value="fluoro_carbon_copolymer" />
              </el-select>
            </el-form-item>
          </div>
          <el-form-item label="发布范围">
            <el-radio-group v-model="form.visibility" class="visibility-options">
              <el-radio-button label="private">非公开发布</el-radio-button>
              <el-radio-button label="public">公开发布</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="说明"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
          <el-form-item label="依赖提示"><el-input v-model="form.requirements_hint" placeholder="rdkit, scikit-learn, joblib" /></el-form-item>
        </el-form>

        <el-collapse class="advanced-contract">
          <el-collapse-item title="高级契约">
            <div class="contract-grid">
              <el-form-item label="输入契约 JSON"><el-input v-model="form.input_schema" type="textarea" :rows="6" class="code-input" /></el-form-item>
              <el-form-item label="输出契约 JSON"><el-input v-model="form.output_schema" type="textarea" :rows="6" class="code-input" /></el-form-item>
              <el-form-item label="样例输入 JSON"><el-input v-model="form.sample_input" type="textarea" :rows="8" class="code-input" /></el-form-item>
            </div>
          </el-collapse-item>
        </el-collapse>

        <div class="action-row">
          <el-button @click="handoffStep = 0">上一步</el-button>
          <el-button type="primary" :icon="Check" @click="createHandoff">创建接入任务</el-button>
          <span v-if="selectedExample">{{ selectedExample.input_pattern }} -> {{ selectedExample.output_pattern }}</span>
        </div>
      </section>

      <section v-else-if="handoffStep === 2" class="handoff-step">
        <div class="status-strip">
          <div v-for="item in statusCards" :key="item.key" :class="{ done: item.done, failed: item.failed }">
            <el-icon><Check /></el-icon>
            <span>{{ item.label }}</span>
          </div>
        </div>
        <div v-if="currentHandoff" class="handoff-link">
          <span>{{ currentHandoff.handoff_url }}</span>
          <el-button :icon="Download" type="primary" @click="downloadHandoffPackage">下载接入包</el-button>
        </div>
        <div v-else class="empty-step">请先确认草案并创建接入任务。</div>
        <div class="replace-list">
          <h3>对接人替换清单</h3>
          <div><strong>src/predictor_service.py</strong><span>模型加载、预处理、推理、后处理</span></div>
          <div><strong>model/</strong><span>权重文件</span></div>
          <div><strong>requirements.txt</strong><span>运行依赖</span></div>
          <div><strong>tests/sample_input.json</strong><span>真实样例输入</span></div>
        </div>
        <div class="action-row">
          <el-button @click="handoffStep = 1">上一步</el-button>
          <el-button type="primary" :disabled="!currentHandoff" @click="handoffStep = 3">继续上传自测</el-button>
        </div>
      </section>

      <section v-else-if="handoffStep === 3" class="handoff-step">
        <div class="status-strip">
          <div v-for="item in statusCards" :key="item.key" :class="{ done: item.done, failed: item.failed }">
            <el-icon><Check /></el-icon>
            <span>{{ item.label }}</span>
          </div>
        </div>

        <el-upload v-model:file-list="uploadFiles" drag :auto-upload="false" :limit="1" accept=".zip" class="self-test-upload">
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">拖入对接 ZIP，或点击选择</div>
        </el-upload>

        <div class="action-row">
          <el-button @click="handoffStep = 2">上一步</el-button>
          <el-button :icon="VideoPlay" @click="validateUpload">上传前自测</el-button>
          <el-button type="primary" :loading="deploying" :disabled="!canDeploy" @click="deployValidatedPackage">提交正式部署</el-button>
        </div>

        <div v-if="validation" :class="['validation-box', { ok: validation.ok }]">
          <div class="validation-title">
            <strong>{{ validation.ok ? '自测通过' : '自测失败' }}</strong>
            <el-tag :type="validation.ok ? 'success' : 'danger'">{{ validation.status }}</el-tag>
          </div>
          <div class="check-list">
            <div v-for="check in validation.checks" :key="`${check.name}-${check.message}`">
              <el-icon><Check /></el-icon>
              <span>{{ check.name }}</span>
              <small>{{ check.message }}</small>
            </div>
          </div>
          <div v-if="validation.fixes?.length" class="fix-list">
            <h3>修复建议</h3>
            <p v-for="item in validation.fixes" :key="item">{{ item }}</p>
          </div>
          <pre v-if="validation.ok" class="output-preview">{{ JSON.stringify(validation.output_preview, null, 2) }}</pre>
        </div>
      </section>

      <section v-else class="handoff-step">
        <div class="status-strip">
          <div v-for="item in statusCards" :key="item.key" :class="{ done: item.done, failed: item.failed }">
            <el-icon><Check /></el-icon>
            <span>{{ item.label }}</span>
          </div>
        </div>
        <div class="done-panel">
          <el-icon><Check /></el-icon>
          <strong>{{ currentHandoff?.name || form.name }} 已提交正式部署</strong>
          <span>{{ currentHandoff?.algorithm_id || form.algorithm_id }}</span>
        </div>
      </section>
    </section>

    <el-drawer v-model="showHistory" title="接入任务历史" size="720px">
      <el-table :data="handoffs" border empty-text="暂无接入任务" @row-click="selectHandoff">
        <el-table-column prop="name" label="算法名称" min-width="180" />
        <el-table-column prop="algorithm_id" label="Algorithm ID" min-width="190" />
        <el-table-column label="模板" min-width="160"><template #default="{ row }">{{ row.example_id }}</template></el-table-column>
        <el-table-column label="状态" width="140"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="发布范围" width="120"><template #default="{ row }">{{ row.visibility === 'public' ? '公开' : '非公开' }}</template></el-table-column>
        <el-table-column prop="developer_organization" label="机构" min-width="150" />
        <el-table-column prop="mentor_team" label="导师课题组" min-width="160" />
        <el-table-column prop="owner_contact" label="联系方式" min-width="160" />
      </el-table>
    </el-drawer>
  </div>
</template>

<style scoped>
.handoff-panel { display: grid; gap: 16px; }
.handoff-main { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(360px, 0.95fr); gap: 16px; align-items: start; }
.handoff-card, .handoff-form, .provider-panel, .handoff-table { min-width: 0; border: 1px solid var(--app-border); border-radius: var(--app-radius-md); background: #fff; padding: 18px; }
.panel-heading, .heading-actions, .action-row, .validation-title { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.heading-actions { align-items: center; }
.panel-heading.compact { margin-bottom: 12px; }
.eyebrow { margin: 0 0 4px; color: var(--app-primary-active); font-size: 12px; font-weight: 700; }
h2, h3 { margin: 0; color: var(--app-ink); letter-spacing: 0; }
h2 { font-size: 18px; line-height: 1.3; }
h3 { font-size: 14px; }
.panel-heading p:last-child, .handoff-table p { margin: 4px 0 0; color: var(--app-ink-muted); font-size: 13px; line-height: 1.6; }
.handoff-steps { margin: 16px 0; }
.handoff-step { min-height: 380px; display: grid; align-content: start; gap: 14px; max-width: 1120px; }
.doc-entry { display: grid; gap: 10px; margin: 10px 0 14px; padding: 14px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-sm); background: #f8fbff; }
.doc-entry-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.doc-entry-actions { display: grid; grid-template-columns: minmax(280px, 520px) auto auto; align-items: center; gap: 10px; }
.doc-entry-head h3 { margin: 0; font-size: 14px; }
.doc-entry-head p { margin: 4px 0 0; color: var(--app-ink-muted); font-size: 12px; }
.doc-summary { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 6px; color: var(--app-ink-body); font-size: 12px; }
.doc-warnings { display: grid; gap: 4px; margin-top: 8px; }
.doc-warnings p { margin: 0; color: var(--app-ink-muted); font-size: 12px; }
.draft-alert { margin-bottom: 2px; }
.requirement-upload { width: 100%; }
.requirement-upload :deep(.el-upload-dragger) { padding: 18px 16px; border-radius: var(--app-radius-sm); }
.upload-tip { margin-top: 6px; color: var(--app-ink-muted); font-size: 12px; line-height: 1.5; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; }
.visibility-options { display: flex; flex-wrap: wrap; gap: 8px; }
.advanced-contract { margin-top: 4px; border-top: 1px solid var(--app-border-soft); border-bottom: 0; }
.contract-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; }
.contract-grid .el-form-item:last-child { grid-column: 1 / -1; }
.code-input :deep(textarea), .output-preview { font-family: var(--app-mono-font); font-size: 12px; }
.action-row { align-items: center; margin-top: 12px; }
.action-row span { color: var(--app-ink-muted); font-size: 12px; overflow-wrap: anywhere; }
.status-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-bottom: 14px; }
.status-strip div { display: grid; gap: 4px; justify-items: center; min-height: 64px; padding: 10px 6px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-sm); color: var(--app-ink-muted); text-align: center; font-size: 12px; }
.status-strip div.done { border-color: #bbf7d0; background: #f0fdf4; color: #15803d; }
.status-strip div.failed { border-color: #fecaca; background: #fef2f2; color: #b91c1c; }
.handoff-link { display: grid; gap: 10px; padding: 12px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-sm); background: #f8fbff; }
.handoff-link span { color: var(--app-ink-body); font-size: 13px; overflow-wrap: anywhere; }
.empty-step { padding: 18px; border: 1px dashed var(--app-border); border-radius: var(--app-radius-sm); color: var(--app-ink-muted); text-align: center; }
.replace-list { display: grid; gap: 8px; margin: 14px 0; }
.replace-list div { display: grid; grid-template-columns: minmax(130px, 0.7fr) minmax(0, 1fr); gap: 10px; padding: 9px 0; border-bottom: 1px solid var(--app-border-soft); }
.replace-list strong { color: var(--app-ink); font-family: var(--app-mono-font); font-size: 12px; }
.replace-list span { color: var(--app-ink-muted); font-size: 13px; }
.self-test-upload { margin-top: 10px; }
.validation-box { display: grid; gap: 12px; margin-top: 14px; padding: 14px; border: 1px solid #fecaca; border-radius: var(--app-radius-sm); background: #fff7f7; }
.validation-box.ok { border-color: #bbf7d0; background: #f7fff9; }
.check-list { display: grid; gap: 8px; }
.check-list div { display: grid; grid-template-columns: 18px minmax(90px, 0.45fr) minmax(0, 1fr); gap: 8px; align-items: start; }
.check-list span { color: var(--app-ink); font-size: 13px; }
.check-list small, .fix-list p { color: var(--app-ink-muted); font-size: 12px; line-height: 1.6; }
.fix-list { display: grid; gap: 6px; }
.fix-list p { margin: 0; }
.output-preview { max-height: 220px; overflow: auto; margin: 0; padding: 12px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-sm); background: #fff; white-space: pre-wrap; }
.done-panel { min-height: 220px; display: grid; place-items: center; align-content: center; gap: 8px; border: 1px solid #bbf7d0; border-radius: var(--app-radius-md); background: #f7fff9; text-align: center; }
.done-panel .el-icon { color: #16a34a; font-size: 38px; }
.done-panel strong { color: var(--app-ink); font-size: 16px; }
.done-panel span { color: var(--app-ink-muted); font-size: 13px; overflow-wrap: anywhere; }
@media (max-width: 1180px) { .handoff-main { grid-template-columns: 1fr; } }
@media (max-width: 760px) {
  .form-grid, .contract-grid, .status-strip, .replace-list div, .check-list div { grid-template-columns: 1fr; }
  .handoff-card, .handoff-form, .provider-panel, .handoff-table { padding: 12px; }
  .panel-heading, .heading-actions, .action-row { align-items: stretch; flex-direction: column; }
  .doc-entry-actions { grid-template-columns: 1fr; align-items: stretch; }
}
</style>
