<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Download, DocumentChecked, Files, Refresh, Setting } from '@element-plus/icons-vue'

import AttributionBanner from '../components/attribution/AttributionBanner.vue'
import {
  downloadExperimentDispatch,
  evaluateExperimentDispatchProfile,
  getApiErrorMessage,
  getExperimentDispatch,
  listAlgorithms,
  listExperimentDispatchCandidates,
  listExperimentDispatchProfiles,
  listExperimentDispatchTargets,
  listExperimentDispatches,
  listIntegrationConfigs,
  saveProfileExperimentDispatch,
} from '../api/polyAgentApi'
import { formatApiDateTime } from '../utils/datetime'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const candidatesLoading = ref(false)
const previewLoading = ref(false)
const saveLoading = ref(false)
const historyLoading = ref(false)
const profiles = ref([])
const targets = ref([])
const algorithms = ref([])
const candidates = ref([])
const dispatches = ref([])
const evaluation = ref(null)
const detail = ref(null)
const detailVisible = ref(false)
const sidebarVisible = ref(localStorage.getItem('experiment-dispatch-sidebar') !== 'hidden')
const sidebarTab = ref('saved')
const historyKeyword = ref('')
const integrations = ref([])

const filters = reactive({
  trigger_source: '',
  algorithm_type: '',
  algorithm_family: '',
  algorithm_id: '',
  keyword: '',
})
const form = reactive({ runId: String(route.query.run_id || ''), profileKey: '', experimentName: '', experimentNotes: '', manualValues: {} })

const selectedProfile = computed(() => profiles.value.find((item) => `${item.profile_id}@${item.version}` === form.profileKey) || null)
const selectedTarget = computed(() => selectedProfile.value ? targets.value.find((item) => item.target_id === selectedProfile.value.target_id && item.version === selectedProfile.value.target_version) : null)
const selectedCandidate = computed(() => candidates.value.find((item) => item.run_id === form.runId) || null)
const algorithmOptions = computed(() => algorithms.value.filter((item) => !filters.algorithm_family || item.family === filters.algorithm_family || item.algorithm_family === filters.algorithm_family))
const algorithmFamilies = computed(() => [...new Set(algorithms.value.map((item) => item.family || item.algorithm_family).filter(Boolean))])
const triggerSources = computed(() => [...new Set(candidates.value.map((item) => item.trigger_source).filter(Boolean))])
const manualFields = computed(() => {
  if (!selectedProfile.value) return []
  const fields = selectedProfile.value.target_fields?.length ? selectedProfile.value.target_fields : (selectedTarget.value?.fields || [])
  const mappingOverrides = new Set((selectedProfile.value.mappings || []).filter((item) => item.allow_override).map((item) => item.target_path))
  return fields.filter((field) => field.allow_override || mappingOverrides.has(field.path))
})
const historyItems = computed(() => {
  const keyword = historyKeyword.value.trim().toLowerCase()
  if (!keyword) return dispatches.value
  return dispatches.value.filter((item) => [item.dispatch_id, item.run_id, item.experiment_name, item.profile_id, item.template_id].some((value) => String(value || '').toLowerCase().includes(keyword)))
})
const outputPayload = computed(() => evaluation.value?.result?.payload || {})
const outputRows = computed(() => Object.entries(outputPayload.value).map(([key, value]) => ({ key, value })))
const integration = computed(() => {
  const serviceKey = selectedTarget.value?.service_key
  return integrations.value.find((item) => item.service === serviceKey || item.service_key === serviceKey) || null
})

function syncRoute() {
  const query = { ...route.query }
  if (form.runId) query.run_id = form.runId
  else delete query.run_id
  router.replace({ query })
}

function invalidatePreview() { evaluation.value = null }
watch(() => form.runId, () => { invalidatePreview(); syncRoute() })
watch(() => form.profileKey, () => { invalidatePreview(); form.manualValues = {} })
watch(form.manualValues, invalidatePreview, { deep: true })
watch(() => [filters.trigger_source, filters.algorithm_type, filters.algorithm_family, filters.algorithm_id, filters.keyword, form.profileKey], loadCandidates)
watch(historyKeyword, loadHistory)

async function loadReference() {
  loading.value = true
  try {
    const [profileData, targetData, algorithmData, integrationData] = await Promise.all([
      listExperimentDispatchProfiles({ page: 1, page_size: 100 }),
      listExperimentDispatchTargets(),
      listAlgorithms({ page: 1, page_size: 100 }),
      listIntegrationConfigs().catch(() => ({ items: [] })),
    ])
    profiles.value = profileData.items || []
    targets.value = targetData.items || []
    algorithms.value = algorithmData.items || []
    integrations.value = integrationData.items || []
    if (!form.profileKey && profiles.value.length) form.profileKey = `${profiles.value[0].profile_id}@${profiles.value[0].version}`
    await Promise.all([loadCandidates(), loadHistory()])
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally { loading.value = false }
}

async function loadCandidates() {
  candidatesLoading.value = true
  try {
    const data = await listExperimentDispatchCandidates({ ...filters, profile_id: selectedProfile.value?.profile_id || undefined, page: 1, page_size: 50 })
    candidates.value = data.items || []
    if (!form.runId && candidates.value.length) form.runId = candidates.value[0].run_id
    if (form.runId && !candidates.value.some((item) => item.run_id === form.runId)) form.runId = ''
  } catch (error) { ElMessage.error(getApiErrorMessage(error)) } finally { candidatesLoading.value = false }
}

async function loadHistory() {
  historyLoading.value = true
  try {
    const data = await listExperimentDispatches({ page: 1, page_size: 50, profile_id: selectedProfile.value?.profile_id || undefined, keyword: historyKeyword.value || undefined })
    dispatches.value = data.items || []
  } catch (error) { ElMessage.error(getApiErrorMessage(error)) } finally { historyLoading.value = false }
}

async function generatePreview() {
  if (!form.runId || !selectedProfile.value) return ElMessage.warning('请先选择已完成 Run 和下发配置')
  previewLoading.value = true
  try {
    evaluation.value = await evaluateExperimentDispatchProfile({ run_id: form.runId, profile_id: selectedProfile.value.profile_id, profile_version: selectedProfile.value.version, manual_values: form.manualValues })
    if (evaluation.value.result?.is_valid) ElMessage.success('预览已生成，可保存')
    else ElMessage.warning('预览生成，但存在阻断校验问题')
  } catch (error) { ElMessage.error(getApiErrorMessage(error)) } finally { previewLoading.value = false }
}

async function saveDispatch() {
  if (!evaluation.value) await generatePreview()
  if (!evaluation.value?.result?.is_valid) return
  saveLoading.value = true
  try {
    const saved = await saveProfileExperimentDispatch({ run_id: form.runId, profile_id: selectedProfile.value.profile_id, profile_version: selectedProfile.value.version, manual_values: form.manualValues, preview_digest: evaluation.value.preview_digest, experiment_name: form.experimentName || null, experiment_notes: form.experimentNotes || null })
    await loadHistory()
    evaluation.value = { ...evaluation.value, saved_manifest: saved }
    ElMessage.success('已保存，状态为“已保存、未下发”')
  } catch (error) { ElMessage.error(getApiErrorMessage(error)) } finally { saveLoading.value = false }
}

function openProfiles() { router.push('/optimization/experiment-dispatch/profiles') }
function toggleSidebar() { sidebarVisible.value = !sidebarVisible.value; localStorage.setItem('experiment-dispatch-sidebar', sidebarVisible.value ? 'visible' : 'hidden') }
function formatDate(value) { return formatApiDateTime(value) }
function displayValue(value) { return typeof value === 'object' ? JSON.stringify(value) : String(value ?? '-') }
function statusType(status) { return { prepared: 'success', sent: 'warning', accepted: 'success', failed: 'danger' }[status] || 'info' }
function maskEndpoint(value) {
  try { const url = new URL(value); return `${url.protocol}//${url.host}${url.pathname}` } catch { return String(value || '').replace(/([?&](?:key|token|secret)=)[^&]+/ig, '$1***') }
}

async function openDetail(row) {
  detailVisible.value = true
  detail.value = null
  try { detail.value = await getExperimentDispatch(row.dispatch_id) } catch (error) { detailVisible.value = false; ElMessage.error(getApiErrorMessage(error)) }
}
async function downloadDispatch(id) {
  try {
    const file = await downloadExperimentDispatch(id)
    const url = URL.createObjectURL(file.blob); const link = document.createElement('a'); link.href = url; link.download = file.filename; link.click(); URL.revokeObjectURL(url)
  } catch (error) { ElMessage.error(`导出失败：${getApiErrorMessage(error)}`) }
}

onMounted(loadReference)
</script>

<template>
  <div class="experiment-dispatch-page">
    <AttributionBanner module-id="experiment_dispatch" label="工具支持" compact />
    <section class="panel page-heading">
      <div><h3 class="panel-title">实验方案转发台</h3><p class="panel-subtitle">从已完成 Run 选择兼容的下发配置，生成可追溯的目标接口参数。</p></div>
      <div class="heading-actions"><el-button :icon="Setting" @click="openProfiles">管理下发配置</el-button><el-button :icon="Refresh" :loading="loading" aria-label="刷新" @click="loadReference">刷新</el-button><el-button :icon="Files" :type="sidebarVisible ? 'default' : 'primary'" @click="toggleSidebar">{{ sidebarVisible ? '隐藏已保存' : '显示已保存' }}</el-button></div>
    </section>

    <section class="panel filter-panel">
      <div class="panel-header"><h3 class="panel-title">选择运行</h3><span class="panel-caption">服务端分页 · 只显示已完成且有权限的 Run</span></div>
      <div class="panel-body cascade-grid">
        <el-form-item label="运行来源"><el-select v-model="filters.trigger_source" clearable placeholder="全部来源"><el-option v-for="item in triggerSources" :key="item" :label="item" :value="item" /></el-select></el-form-item>
        <el-form-item label="算法类型"><el-select v-model="filters.algorithm_type" clearable placeholder="全部类型"><el-option v-for="item in [...new Set(algorithms.map((a) => a.algorithm_type || a.type).filter(Boolean))]" :key="item" :label="item" :value="item" /></el-select></el-form-item>
        <el-form-item label="算法族"><el-select v-model="filters.algorithm_family" clearable placeholder="全部算法族"><el-option v-for="item in algorithmFamilies" :key="item" :label="item" :value="item" /></el-select></el-form-item>
        <el-form-item label="算法"><el-select v-model="filters.algorithm_id" clearable filterable placeholder="选择算法"><el-option v-for="item in algorithmOptions" :key="item.algorithm_id" :label="item.name || item.algorithm_id" :value="item.algorithm_id" /></el-select></el-form-item>
        <el-form-item label="Run ID"><el-select v-model="form.runId" clearable filterable :loading="candidatesLoading" placeholder="选择 Run"><el-option v-for="item in candidates" :key="item.run_id" :label="`${item.algorithm_name || item.algorithm_id} · ${formatDate(item.finished_at || item.created_at)}`" :value="item.run_id"><div class="run-option"><strong>{{ item.algorithm_name || item.algorithm_id }}</strong><span>{{ formatDate(item.finished_at || item.created_at) }} · {{ item.run_id.slice(0, 12) }}</span></div></el-option></el-select></el-form-item>
        <el-form-item label="关键词"><el-input v-model="filters.keyword" clearable placeholder="算法名、Run ID" /></el-form-item>
      </div>
      <div v-if="selectedCandidate" class="selection-summary"><strong>{{ selectedCandidate.algorithm_name || selectedCandidate.algorithm_id }}</strong><span>{{ selectedCandidate.algorithm_type || '未分类' }} · {{ selectedCandidate.algorithm_family || '未分族' }}</span><code>{{ selectedCandidate.run_id }}</code><el-tag type="success" size="small">已完成</el-tag></div>
    </section>

    <div class="main-layout">
      <main class="main-workspace">
        <section class="panel profile-panel">
          <div class="panel-header"><div><h3 class="panel-title">选择实验下发配置</h3><p class="panel-caption">配置包含参数映射、条件分支和目标接口版本</p></div><el-button type="primary" plain @click="openProfiles">新建下发配置</el-button></div>
          <div class="panel-body">
            <el-select v-model="form.profileKey" filterable class="profile-select" placeholder="选择兼容配置"><el-option v-for="item in profiles" :key="`${item.profile_id}@${item.version}`" :label="`${item.name} · v${item.version}`" :value="`${item.profile_id}@${item.version}`"><div class="profile-option"><strong>{{ item.name }}</strong><span>v{{ item.version }} · {{ item.status === 'published' ? '已发布' : '草稿' }}</span></div></el-option></el-select>
            <div v-if="selectedProfile" class="profile-summary"><div><strong>{{ selectedProfile.name }}</strong><p>{{ selectedProfile.description || '暂无说明' }}</p></div><div class="summary-tags"><el-tag size="small">v{{ selectedProfile.version }}</el-tag><el-tag size="small" :type="selectedProfile.visibility === 'public' ? 'success' : 'info'">{{ selectedProfile.visibility === 'public' ? '公开' : '私有' }}</el-tag><el-tag size="small" effect="plain">{{ selectedTarget?.name || selectedProfile.target_id }}</el-tag></div><p v-if="selectedProfile.notes" class="profile-notes">{{ selectedProfile.notes }}</p></div>
          </div>
        </section>

        <section class="panel input-panel">
          <div class="panel-header"><div><h3 class="panel-title">实验信息与人工补充</h3><p class="panel-caption">仅显示配置声明允许覆盖的字段；备注不会参与规则计算</p></div></div>
          <div class="panel-body"><div class="form-grid"><el-form-item label="实验名称"><el-input v-model="form.experimentName" placeholder="可选，默认使用配置名称" /></el-form-item><el-form-item label="单次备注"><el-input v-model="form.experimentNotes" placeholder="可选" /></el-form-item></div><div v-if="manualFields.length" class="manual-grid"><el-form-item v-for="field in manualFields" :key="field.path" :label="field.label || field.path"><el-input-number v-if="['number', 'integer'].includes(field.value_type)" v-model="form.manualValues[field.path]" controls-position="right" class="full-width" /><el-switch v-else-if="field.value_type === 'boolean'" v-model="form.manualValues[field.path]" /><el-input v-else v-model="form.manualValues[field.path]" :placeholder="field.unit ? `单位：${field.unit}` : '按配置填写'" /></el-form-item></div><el-alert v-else title="此配置无需人工补充" type="info" :closable="false" /></div>
        </section>

        <section class="panel action-panel"><div class="panel-body action-row"><el-button :loading="previewLoading" :disabled="!form.runId || !selectedProfile" @click="generatePreview">生成预览</el-button><el-button type="primary" :loading="saveLoading" :disabled="!evaluation?.result?.is_valid" @click="saveDispatch"><el-icon><DocumentChecked /></el-icon>保存清单</el-button><span class="action-hint">{{ evaluation ? (evaluation.result?.is_valid ? '预览有效，可保存' : '预览存在阻断问题') : '修改 Run、配置或人工输入后需重新预览' }}</span></div></section>

        <section v-if="evaluation" class="panel preview-panel">
          <div class="panel-header"><div><h3 class="panel-title">生成结果</h3><p class="panel-caption">目标接口：{{ selectedTarget?.name || evaluation.target_id }} · 仅生成请求预览，不会发起外部请求</p></div><el-tag :type="evaluation.result?.is_valid ? 'success' : 'danger'">{{ evaluation.result?.is_valid ? '校验通过' : '禁止保存' }}</el-tag></div>
          <div class="panel-body preview-body"><el-alert v-if="evaluation.result?.errors?.length" type="error" :closable="false" show-icon><template #title>无法保存</template><template #default><div v-for="error in evaluation.result.errors" :key="error">{{ error }}</div></template></el-alert><el-alert v-if="evaluation.result?.warnings?.length" type="warning" :closable="false" show-icon><template #default><div v-for="warning in evaluation.result.warnings" :key="warning">{{ warning }}</div></template></el-alert><div class="preview-grid"><div><h4>最终实验参数</h4><el-table :data="outputRows" size="small" border><el-table-column prop="key" label="参数" min-width="170" /><el-table-column label="值"><template #default="{ row }"><code>{{ displayValue(row.value) }}</code></template></el-table-column></el-table></div><div><h4>执行状态</h4><div class="result-facts"><div><span>命中分支</span><strong>{{ evaluation.result?.matched_rules?.length || 0 }}</strong></div><div><span>字段追踪</span><strong>{{ evaluation.result?.trace?.length || 0 }}</strong></div><div><span>目标契约</span><strong>v{{ evaluation.target_version }}</strong></div><div><span>下发状态</span><el-tag type="info" size="small">已保存、未下发</el-tag></div></div></div></div><el-collapse><el-collapse-item title="查看映射追踪与原始 JSON" name="trace"><pre class="json-view">{{ JSON.stringify({ trace: evaluation.result?.trace || [], matched_rules: evaluation.result?.matched_rules || [], payload: evaluation.result?.payload || {} }, null, 2) }}</pre></el-collapse-item></el-collapse></div>
        </section>
      </main>

      <aside v-if="sidebarVisible" class="saved-sidebar panel"><div class="sidebar-header"><div><h3 class="panel-title">工作区侧栏</h3><span class="panel-caption">可隐藏 · 详情抽屉</span></div><el-button text aria-label="隐藏侧栏" @click="toggleSidebar">×</el-button></div><el-tabs v-model="sidebarTab"><el-tab-pane label="已保存" name="saved"><el-input v-model="historyKeyword" clearable placeholder="筛选清单" class="sidebar-search" /><el-table v-loading="historyLoading" :data="historyItems" size="small" :show-header="false" empty-text="暂无已保存清单"><el-table-column><template #default="{ row }"><button class="saved-item" type="button" @click="openDetail(row)"><strong>{{ row.experiment_name || row.profile_id || row.template_id || '未命名实验' }}</strong><span>{{ row.run_id }} · {{ formatDate(row.created_at) }}</span><el-tag :type="statusType(row.status)" size="small">{{ row.status === 'prepared' ? '已保存、未下发' : row.status }}</el-tag></button></template></el-table-column></el-table></el-tab-pane><el-tab-pane label="接口预览" name="interface"><div class="interface-preview"><el-alert title="本期不会发起 SpecLabOS 请求" type="info" :closable="false" /><dl><dt>目标系统</dt><dd>{{ selectedTarget?.name || '未选择' }}</dd><dt>HTTP</dt><dd>{{ selectedTarget?.method || 'POST' }} {{ selectedTarget?.path || '-' }}</dd><dt>服务配置</dt><dd>{{ integration?.endpoint ? maskEndpoint(integration.endpoint) : '由工具服务配置管理' }}</dd></dl><h4>请求 payload</h4><pre class="json-view">{{ JSON.stringify(outputPayload, null, 2) }}</pre><h4>预期响应</h4><pre class="json-view">{{ JSON.stringify(selectedTarget?.response_schema || {}, null, 2) }}</pre></div></el-tab-pane></el-tabs></aside>
    </div>

    <el-drawer v-model="detailVisible" title="已保存清单详情" size="min(760px, 94vw)"><template v-if="detail"><el-descriptions :column="1" border size="small"><el-descriptions-item label="Dispatch ID">{{ detail.dispatch_id }}</el-descriptions-item><el-descriptions-item label="Run ID">{{ detail.source?.run_id }}</el-descriptions-item><el-descriptions-item label="配置">{{ detail.profile?.profile_id || detail.template?.template_id }} · v{{ detail.profile?.profile_version || detail.template?.template_version }}</el-descriptions-item><el-descriptions-item label="状态"><el-tag type="info">已保存、未下发</el-tag></el-descriptions-item></el-descriptions><h4>请求 payload</h4><pre class="json-view">{{ JSON.stringify(detail.payload || detail.parameters || {}, null, 2) }}</pre><el-button :icon="Download" @click="downloadDispatch(detail.dispatch_id)">导出 JSON</el-button></template></el-drawer>
  </div>
</template>

<style scoped>
.experiment-dispatch-page { display:flex; flex-direction:column; gap:16px; }
.page-heading,.sidebar-header { display:flex; align-items:center; justify-content:space-between; gap:16px; }
.heading-actions { display:flex; gap:8px; flex-wrap:wrap; }
.panel-subtitle,.panel-caption { color:var(--app-ink-muted); font-size:13px; }
.panel-subtitle { margin:6px 0 0; }.panel-caption { font-size:12px; }
.cascade-grid { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:12px; }.cascade-grid .el-form-item { margin-bottom:0; }.cascade-grid :deep(.el-select),.cascade-grid :deep(.el-input) { width:100%; }
.selection-summary,.profile-summary { display:flex; align-items:center; gap:10px; flex-wrap:wrap; padding:10px 12px; border:1px solid var(--app-border-soft); border-radius:var(--app-radius-sm); background:#f8fbff; color:var(--app-ink-body); }.selection-summary strong,.profile-summary strong { color:var(--app-ink); }.selection-summary code { margin-left:auto; }.run-option,.profile-option { display:flex; flex-direction:column; gap:2px; }.run-option span,.profile-option span { color:var(--app-ink-muted); font-size:12px; }
.main-layout { display:grid; grid-template-columns:minmax(0,1fr) 320px; gap:16px; align-items:start; }.main-workspace { min-width:0; display:flex; flex-direction:column; gap:16px; }.profile-select { width:100%; }.profile-summary { margin-top:12px; justify-content:space-between; }.profile-summary p { margin:5px 0 0; color:var(--app-ink-muted); font-size:12px; }.profile-notes { width:100%; padding-top:8px; border-top:1px solid var(--app-border-soft); }
.summary-tags { display:flex; gap:6px; flex-wrap:wrap; }.form-grid,.manual-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }.full-width { width:100%; }.action-row { display:flex; align-items:center; justify-content:flex-end; gap:8px; }.action-hint { margin-left:auto; color:var(--app-ink-muted); font-size:12px; }.preview-body { display:flex; flex-direction:column; gap:14px; }.preview-grid { display:grid; grid-template-columns:minmax(0,1.5fr) minmax(220px,.7fr); gap:18px; }.preview-body h4 { margin:0 0 8px; font-size:13px; }.result-facts { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }.result-facts div { display:flex; flex-direction:column; gap:4px; padding:10px; border:1px solid var(--app-border-soft); border-radius:var(--app-radius-sm); }.result-facts span { color:var(--app-ink-muted); font-size:12px; }.result-facts strong { font-size:18px; }.json-view { margin:0; padding:10px; max-height:300px; overflow:auto; border:1px solid var(--app-border-soft); border-radius:var(--app-radius-sm); background:#f8fafc; color:var(--app-ink-body); font:12px/1.6 var(--app-mono-font); white-space:pre-wrap; word-break:break-word; }.saved-sidebar { position:sticky; top:16px; min-width:0; overflow:hidden; }.sidebar-header { padding:16px 16px 8px; }.sidebar-search { margin:0 12px 10px; width:calc(100% - 24px); }.saved-item { width:100%; display:flex; flex-direction:column; align-items:flex-start; gap:5px; padding:10px 12px; border:0; border-top:1px solid var(--app-border-soft); background:transparent; color:inherit; text-align:left; cursor:pointer; }.saved-item:hover { background:#f5f8fc; }.saved-item span { color:var(--app-ink-muted); font-size:11px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:100%; }.interface-preview { padding:2px 12px 16px; }.interface-preview dl { display:grid; grid-template-columns:90px 1fr; gap:8px; margin:14px 0; font-size:12px; }.interface-preview dt { color:var(--app-ink-muted); }.interface-preview dd { margin:0; word-break:break-all; }.interface-preview h4 { margin:14px 0 6px; font-size:12px; }
@media (max-width:1200px) { .cascade-grid { grid-template-columns:repeat(3,minmax(0,1fr)); } }
@media (max-width:900px) { .main-layout { grid-template-columns:1fr; }.saved-sidebar { position:fixed; z-index:20; inset:72px 0 0 auto; width:min(360px,92vw); box-shadow:-8px 0 24px rgba(25,45,75,.16); }.preview-grid { grid-template-columns:1fr; } }
@media (max-width:640px) { .page-heading,.action-row { align-items:stretch; flex-direction:column; }.heading-actions .el-button { flex:1; }.cascade-grid,.form-grid,.manual-grid { grid-template-columns:1fr; }.action-hint { margin-left:0; }.selection-summary code { margin-left:0; } }
</style>
