<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowDown, ArrowUp, Download, DocumentChecked, Fold, Refresh, Search, Setting, VideoPlay } from '@element-plus/icons-vue'

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
const extraCollapse = ref([])
const sidebarVisible = ref(localStorage.getItem('experiment-dispatch-sidebar') === 'visible')
const sidebarTab = ref('saved')
const historyKeyword = ref('')
const integrations = ref([])
const guideExpanded = ref(false)
const guidePromptVisible = ref(true)
const tourVisible = ref(false)
const tourIndex = ref(0)
const guideBannerRef = ref(null)
const tourTotal = 5
const tourPrevButtonProps = { children: '上一步' }
const tourNextButtonProps = computed(() => ({ children: tourIndex.value >= tourTotal - 1 ? '完成' : '下一步' }))

const filters = reactive({
  algorithm_family: '',
  algorithm_id: '',
  keyword: '',
})
const form = reactive({ runId: String(route.query.run_id || ''), profileKey: '', experimentName: '', experimentNotes: '', manualValues: {} })

const selectedProfile = computed(() => profiles.value.find((item) => `${item.profile_id}@${item.version}` === form.profileKey) || null)
const selectedTarget = computed(() => selectedProfile.value ? targets.value.find((item) => item.target_id === selectedProfile.value.target_id && item.version === selectedProfile.value.target_version) : null)
const selectedCandidate = computed(() => candidates.value.find((item) => item.run_id === form.runId) || null)
const currentStep = computed(() => (!form.runId ? 0 : !form.profileKey ? 1 : 2))
const algorithmOptions = computed(() => algorithms.value.filter((item) => !filters.algorithm_family || item.family === filters.algorithm_family || item.algorithm_family === filters.algorithm_family))
const algorithmFamilies = computed(() => [...new Set(algorithms.value.map((item) => item.family || item.algorithm_family).filter(Boolean))])
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
const outputPreviewRows = computed(() => outputRows.value.slice(0, 5))
const dispatchId = computed(() => evaluation.value?.saved_manifest?.dispatch_id || '')
const globalSearching = computed(() => filters.keyword.trim().length > 0)
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
watch(() => [filters.algorithm_family, filters.algorithm_id, filters.keyword, form.profileKey], loadCandidates)
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
    const params = { profile_id: selectedProfile.value?.profile_id || undefined, page: 1, page_size: 50 }
    if (globalSearching.value) params.keyword = filters.keyword.trim()
    else {
      if (filters.algorithm_family) params.algorithm_family = filters.algorithm_family
      if (filters.algorithm_id) params.algorithm_id = filters.algorithm_id
    }
    const data = await listExperimentDispatchCandidates(params)
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
    if (evaluation.value.result?.is_valid) ElMessage.success('预览已生成，可点击“一键解析并下发”')
    else ElMessage.warning('预览生成，但存在阻断校验问题')
  } catch (error) { ElMessage.error(getApiErrorMessage(error)) } finally { previewLoading.value = false }
}

async function runDispatch() {
  if (!form.runId || !selectedProfile.value) return ElMessage.warning('请先选择已完成 Run 和下发配置')
  saveLoading.value = true
  try {
    const evaluationData = await evaluateExperimentDispatchProfile({ run_id: form.runId, profile_id: selectedProfile.value.profile_id, profile_version: selectedProfile.value.version, manual_values: form.manualValues })
    evaluation.value = evaluationData
    if (!evaluationData.result?.is_valid) {
      ElMessage.warning('解析完成，但存在阻断校验问题，未保存')
      return
    }
    const saved = await saveProfileExperimentDispatch({ run_id: form.runId, profile_id: selectedProfile.value.profile_id, profile_version: selectedProfile.value.version, manual_values: form.manualValues, preview_digest: evaluationData.preview_digest, experiment_name: form.experimentName || null, experiment_notes: form.experimentNotes || null })
    await loadHistory()
    evaluation.value = { ...evaluationData, saved_manifest: saved }
    ElMessage.success('已解析并下发保存，状态为“已保存、未下发”')
  } catch (error) { ElMessage.error(getApiErrorMessage(error)) } finally { saveLoading.value = false }
}

function openProfiles() { router.push('/optimization/experiment-dispatch/profiles') }
function toggleSidebar() { sidebarVisible.value = !sidebarVisible.value; localStorage.setItem('experiment-dispatch-sidebar', sidebarVisible.value ? 'visible' : 'hidden') }
async function startTeaching() {
  guideExpanded.value = true
  guidePromptVisible.value = false
  await nextTick()
  tourVisible.value = true
}
async function playTour() {
  guideExpanded.value = true
  guidePromptVisible.value = false
  await nextTick()
  tourVisible.value = true
}
function skipTeaching() { guidePromptVisible.value = false }
function toggleGuide() { guideExpanded.value = !guideExpanded.value; guidePromptVisible.value = false }
function handleTourClose() { tourVisible.value = false }
function handleTourFinish() { tourVisible.value = false }
function handleTourChange(current) { tourIndex.value = current }
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

    <section ref="guideBannerRef" class="guide-banner">
      <div class="guide-bar" role="button" tabindex="0" :aria-expanded="guideExpanded" @click="toggleGuide" @keydown.enter="toggleGuide">
        <div class="guide-icon"><el-icon><VideoPlay /></el-icon></div>
        <div class="guide-copy">
          <h2>三步完成实验方案下发</h2>
          <p v-if="guidePromptVisible" class="guide-prompt">需要引导吗？</p>
        </div>
        <div class="guide-actions" @click.stop>
          <template v-if="guidePromptVisible">
            <el-button size="small" type="primary" :icon="VideoPlay" @click="startTeaching">开始教学</el-button>
            <el-button size="small" text @click="skipTeaching">跳过</el-button>
          </template>
          <template v-else>
            <el-button size="small" text type="primary" :icon="VideoPlay" @click="playTour">重新播放引导</el-button>
            <el-button size="small" text :aria-label="guideExpanded ? '收起引导' : '展开引导'" :icon="guideExpanded ? ArrowUp : ArrowDown" @click="toggleGuide" />
          </template>
        </div>
      </div>
      <div v-show="guideExpanded" class="guide-body">
        <p class="guide-intro">从已完成 Run 选择兼容的下发配置，一键生成可追溯的目标接口执行清单；完整流程可播放新手引导。</p>
        <div class="guide-steps" aria-label="使用教程">
          <div class="guide-step"><strong>01</strong><span>选择已完成 Run</span></div>
          <div class="guide-step"><strong>02</strong><span>选择下发配置</span></div>
          <div class="guide-step"><strong>03</strong><span>预览并确认校验</span></div>
          <div class="guide-step"><strong>04</strong><span>一键解析并下发</span></div>
        </div>
      </div>
    </section>

    <section class="page-heading">
      <div><h3 class="panel-title">实验方案转发台</h3><p class="panel-subtitle">从已完成 Run 选择兼容的下发配置，生成可追溯的目标接口参数。</p></div>
      <div class="heading-actions"><el-button text :icon="VideoPlay" @click="playTour">播放引导</el-button><el-button :icon="Setting" @click="openProfiles">管理下发配置</el-button><el-button :icon="Refresh" :loading="loading" aria-label="刷新" @click="loadReference">刷新</el-button></div>
    </section>

    <el-steps class="dispatch-steps" :active="currentStep" finish-status="success">
      <el-step title="选择 Run" description="从已完成 Run 中挑选本次实验" />
      <el-step title="选择配置" description="匹配版本化实验下发配置" />
      <el-step title="解析并下发" description="预览校验后保存执行清单" />
    </el-steps>

    <section class="panel step-card">
      <div class="step-card-header"><span class="step-badge">1</span><div class="step-card-title"><h3 class="panel-title">选择已完成 Run</h3><p class="panel-caption">只显示已完成且有权限的 Run</p></div></div>
      <div class="panel-body">
        <el-form-item label="关键词" class="keyword-search">
          <el-input v-model="filters.keyword" clearable :prefix-icon="Search" placeholder="全局快速搜索：算法名或 Run ID" />
        </el-form-item>
        <div class="cascade-grid">
          <el-form-item label="算法族"><el-select v-model="filters.algorithm_family" clearable :disabled="globalSearching" placeholder="全部算法族"><el-option v-for="item in algorithmFamilies" :key="item" :label="item" :value="item" /></el-select></el-form-item>
          <el-form-item label="算法"><el-select v-model="filters.algorithm_id" clearable filterable :disabled="globalSearching" placeholder="选择算法"><el-option v-for="item in algorithmOptions" :key="item.algorithm_id" :label="item.name || item.algorithm_id" :value="item.algorithm_id" /></el-select></el-form-item>
          <el-form-item label="Run ID"><el-select v-model="form.runId" clearable filterable :loading="candidatesLoading" placeholder="选择 Run" class="tour-step-run"><el-option v-for="item in candidates" :key="item.run_id" :label="`${item.run_id} · ${formatDate(item.finished_at || item.created_at)}`" :value="item.run_id"><div class="run-option"><strong>{{ item.run_id }}</strong><span>{{ item.algorithm_name || item.algorithm_id }} · {{ formatDate(item.finished_at || item.created_at) }}</span></div></el-option></el-select></el-form-item>
        </div>
        <p v-if="globalSearching" class="filter-hint">全局搜索中，忽略下方算法筛选</p>
        <div v-if="selectedCandidate" class="selection-summary"><strong>{{ selectedCandidate.algorithm_name || selectedCandidate.algorithm_id }}</strong><span>运行时间：{{ formatDate(selectedCandidate.finished_at || selectedCandidate.created_at) }}</span><code>{{ selectedCandidate.run_id }}</code><el-tag type="success" size="small">已完成</el-tag></div>
      </div>
    </section>

    <div class="main-layout" :class="{ 'sidebar-docked': !sidebarVisible }">
      <main class="main-workspace">
        <section class="panel step-card">
          <div class="step-card-header"><span class="step-badge">2</span><div class="step-card-title"><h3 class="panel-title">选择实验下发配置</h3><p class="panel-caption">配置包含参数映射、条件分支和目标接口版本</p></div><el-button type="primary" plain @click="openProfiles">新建下发配置</el-button></div>
          <div class="panel-body">
            <el-select v-model="form.profileKey" filterable class="profile-select tour-step-profile" placeholder="选择兼容配置"><el-option v-for="item in profiles" :key="`${item.profile_id}@${item.version}`" :label="`${item.name} · v${item.version}`" :value="`${item.profile_id}@${item.version}`"><div class="profile-option"><strong>{{ item.name }}</strong><span>v{{ item.version }} · {{ item.status === 'published' ? '已发布' : '草稿' }}</span></div></el-option></el-select>
            <div v-if="selectedProfile" class="profile-summary"><div><strong>{{ selectedProfile.name }}</strong><p>{{ selectedProfile.description || '暂无说明' }}</p></div><div class="summary-tags"><el-tag size="small">v{{ selectedProfile.version }}</el-tag><el-tag size="small" :type="selectedProfile.visibility === 'public' ? 'success' : 'info'">{{ selectedProfile.visibility === 'public' ? '公开' : '私有' }}</el-tag><el-tag size="small" effect="plain">{{ selectedTarget?.name || selectedProfile.target_id }}</el-tag></div><p v-if="selectedProfile.notes" class="profile-notes">{{ selectedProfile.notes }}</p></div>
            <el-collapse v-model="extraCollapse" class="extra-collapse">
              <el-collapse-item name="extra">
                <template #title><span class="extra-title">附加信息（可选）</span><span class="extra-caption">实验名称 / 单次备注 / 人工补充</span></template>
                <div class="extra-body">
                  <div class="form-grid"><el-form-item label="实验名称"><el-input v-model="form.experimentName" placeholder="可选，默认使用配置名称" /></el-form-item><el-form-item label="单次备注"><el-input v-model="form.experimentNotes" placeholder="可选" /></el-form-item></div>
                  <p class="extra-note">仅显示配置声明允许覆盖的字段；备注不会参与规则计算</p>
                  <div v-if="manualFields.length" class="manual-grid"><el-form-item v-for="field in manualFields" :key="field.path" :label="field.label || field.path"><el-input-number v-if="['number', 'integer'].includes(field.value_type)" v-model="form.manualValues[field.path]" controls-position="right" class="full-width" /><el-switch v-else-if="field.value_type === 'boolean'" v-model="form.manualValues[field.path]" /><el-input v-else v-model="form.manualValues[field.path]" :placeholder="field.unit ? `单位：${field.unit}` : '按配置填写'" /></el-form-item></div>
                  <el-alert v-else title="此配置无需人工补充" type="info" :closable="false" />
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>
        </section>

        <section class="panel step-card">
          <div class="step-card-header"><span class="step-badge">3</span><div class="step-card-title"><h3 class="panel-title">解析并下发</h3><p class="panel-caption">选好 Run 和下发配置后，一键生成可追溯的执行清单</p></div><el-tag v-if="evaluation" :type="evaluation.result?.is_valid ? 'success' : 'danger'">{{ evaluation.result?.is_valid ? '校验通过' : '禁止保存' }}</el-tag></div>
          <div class="panel-body">
            <div class="action-row"><div class="action-info"><strong>一键解析并下发</strong><span>保存后状态为“已保存、未下发”，不会发起外部请求</span></div><div class="action-buttons"><el-button :loading="previewLoading" :disabled="!form.runId || !selectedProfile" @click="generatePreview">仅预览</el-button><el-button type="primary" class="primary-action tour-step-action" :loading="saveLoading" :disabled="!form.runId || !selectedProfile" @click="runDispatch"><el-icon><DocumentChecked /></el-icon>一键解析并下发</el-button></div></div>
            <div v-if="evaluation" class="preview-block">
              <p class="preview-target">目标接口：{{ selectedTarget?.name || evaluation.target_id }} · v{{ evaluation.target_version }}</p>
          <div class="panel-body preview-body"><el-alert v-if="evaluation.result?.errors?.length" type="error" :closable="false" show-icon><template #title>阻断问题，未保存</template><template #default><div v-for="error in evaluation.result.errors" :key="error">{{ error }}</div></template></el-alert><el-alert v-if="evaluation.result?.warnings?.length" type="warning" :closable="false" show-icon><template #default><div v-for="warning in evaluation.result.warnings" :key="warning">{{ warning }}</div></template></el-alert><div class="preview-grid"><div><h4>输出摘要</h4><ul v-if="outputPreviewRows.length" class="output-list"><li v-for="row in outputPreviewRows" :key="row.key"><code>{{ row.key }}</code><span>{{ displayValue(row.value) }}</span></li></ul><p class="output-count">共 {{ outputRows.length }} 个输出参数</p><el-collapse><el-collapse-item :title="`查看全部参数（${outputRows.length}）`" name="all"><el-table :data="outputRows" size="small" border><el-table-column prop="key" label="参数" min-width="170" /><el-table-column label="值"><template #default="{ row }"><code>{{ displayValue(row.value) }}</code></template></el-table-column></el-table></el-collapse-item><el-collapse-item title="映射追踪与原始 JSON" name="trace"><pre class="json-view">{{ JSON.stringify({ trace: evaluation.result?.trace || [], matched_rules: evaluation.result?.matched_rules || [], payload: evaluation.result?.payload || {} }, null, 2) }}</pre></el-collapse-item></el-collapse></div><div><h4>执行状态</h4><div class="result-facts"><div><span>目标接口</span><strong>{{ selectedTarget?.name || evaluation.target_id }}<small>v{{ evaluation.target_version }}</small></strong></div><div><span>命中分支</span><strong>{{ evaluation.result?.matched_rules?.length || 0 }}</strong></div><div><span>输出参数</span><strong>{{ outputRows.length }}</strong></div><div><span>下发状态</span><el-tag :type="dispatchId ? 'success' : 'info'" size="small">{{ dispatchId ? '已保存、未下发' : '未保存' }}</el-tag></div><div v-if="dispatchId" class="fact-wide"><span>清单 ID</span><code>{{ dispatchId }}</code></div></div></div></div></div>
            </div>
          </div>
        </section>
      </main>

      <aside class="saved-sidebar panel" :class="{ docked: !sidebarVisible }">
        <template v-if="sidebarVisible">
          <div class="sidebar-header">
            <div><h3 class="panel-title">工作区侧栏</h3><span class="panel-caption">可收起 · 详情抽屉</span></div>
            <el-tooltip content="收起至侧边" placement="left">
              <el-button text aria-label="收起至侧边" @click="toggleSidebar">×</el-button>
            </el-tooltip>
          </div>
          <el-tabs v-model="sidebarTab">
            <el-tab-pane label="已保存" name="saved">
              <el-input v-model="historyKeyword" clearable placeholder="筛选清单" class="sidebar-search" />
              <el-table v-loading="historyLoading" :data="historyItems" size="small" :show-header="false" empty-text="暂无已保存清单">
                <el-table-column>
                  <template #default="{ row }">
                    <button class="saved-item" type="button" @click="openDetail(row)"><strong>{{ row.experiment_name || row.profile_id || row.template_id || '未命名实验' }}</strong><span>{{ row.run_id }} · {{ formatDate(row.created_at) }}</span><el-tag :type="statusType(row.status)" size="small">{{ row.status === 'prepared' ? '已保存、未下发' : row.status }}</el-tag></button>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="接口预览" name="interface">
              <div class="interface-preview">
                <el-alert title="本期不会发起 SpecLabOS 请求" type="info" :closable="false" />
                <dl><dt>目标系统</dt><dd>{{ selectedTarget?.name || '未选择' }}</dd><dt>HTTP</dt><dd>{{ selectedTarget?.method || 'POST' }} {{ selectedTarget?.path || '-' }}</dd><dt>服务配置</dt><dd>{{ integration?.endpoint ? maskEndpoint(integration.endpoint) : '由工具服务配置管理' }}</dd></dl>
                <h4>请求 payload</h4><pre class="json-view">{{ JSON.stringify(outputPayload, null, 2) }}</pre>
                <h4>预期响应</h4><pre class="json-view">{{ JSON.stringify(selectedTarget?.response_schema || {}, null, 2) }}</pre>
              </div>
            </el-tab-pane>
          </el-tabs>
        </template>
        <el-tooltip v-else content="展开侧栏" placement="left">
          <button type="button" class="sidebar-dock" aria-label="展开侧栏" @click="toggleSidebar">
            <el-icon><Fold /></el-icon>
            <span class="sidebar-dock-label">已保存</span>
          </button>
        </el-tooltip>
      </aside>
    </div>

    <el-drawer v-model="detailVisible" title="已保存清单详情" size="min(760px, 94vw)"><template v-if="detail"><el-descriptions :column="1" border size="small"><el-descriptions-item label="Dispatch ID">{{ detail.dispatch_id }}</el-descriptions-item><el-descriptions-item label="Run ID">{{ detail.source?.run_id }}</el-descriptions-item><el-descriptions-item label="配置">{{ detail.profile?.profile_id || detail.template?.template_id }} · v{{ detail.profile?.profile_version || detail.template?.template_version }}</el-descriptions-item><el-descriptions-item label="状态"><el-tag type="info">已保存、未下发</el-tag></el-descriptions-item></el-descriptions><h4>请求 payload</h4><pre class="json-view">{{ JSON.stringify(detail.payload || detail.parameters || {}, null, 2) }}</pre><el-button :icon="Download" @click="downloadDispatch(detail.dispatch_id)">导出 JSON</el-button></template></el-drawer>

    <el-tour v-model="tourVisible" :mask="true" @close="handleTourClose" @finish="handleTourFinish" @change="handleTourChange">
      <el-tour-step title="欢迎使用实验方案转发台" :target="guideBannerRef" description="这里会把已完成 Run 转换为实验接口的执行清单，全程可追溯；流程分三步完成。" :next-button-props="tourNextButtonProps" :prev-button-props="tourPrevButtonProps" />
      <el-tour-step title="第 1 步 · 选择已完成 Run" target=".tour-step-run" description="支持关键词全局搜索，也可按算法族与算法筛选；选中后自动进入下一步。" :next-button-props="tourNextButtonProps" :prev-button-props="tourPrevButtonProps" />
      <el-tour-step title="第 2 步 · 选择下发配置" target=".tour-step-profile" description="配置内含参数映射、条件分支与目标接口版本；可在下方展开附加信息。" :next-button-props="tourNextButtonProps" :prev-button-props="tourPrevButtonProps" />
      <el-tour-step title="第 3 步 · 解析并下发" target=".tour-step-action" description="先“仅预览”校验结果，通过后一键解析并保存为执行清单，不会发起外部请求。" :next-button-props="tourNextButtonProps" :prev-button-props="tourPrevButtonProps" />
      <el-tour-step title="工作区侧栏" target=".saved-sidebar" description="展开侧栏可查看已保存清单、接口预览与请求 payload。" :next-button-props="tourNextButtonProps" :prev-button-props="tourPrevButtonProps" />
    </el-tour>
  </div>
</template>

<style scoped>
.experiment-dispatch-page { display:flex; flex-direction:column; gap:20px; max-width:1440px; margin:0 auto; }

/* ---- 顶部引导横幅 ---- */
.guide-banner { overflow:hidden; border:1px solid var(--app-border); border-radius:var(--app-radius-lg); background:linear-gradient(180deg,#ffffff 0%,#f2f7ff 100%); box-shadow:var(--app-card-shadow); }
.guide-bar { display:flex; align-items:center; gap:14px; padding:14px 18px; cursor:pointer; user-select:none; }
.guide-icon { display:grid; place-items:center; width:46px; height:46px; flex:none; border-radius:var(--app-radius-md); background:var(--app-primary-light); color:var(--app-primary-active); font-size:22px; }
.guide-copy { min-width:0; flex:1 1 auto; }
.guide-copy h2 { margin:0; font-size:18px; font-weight:700; color:var(--app-ink); letter-spacing:-0.3px; }
.guide-copy p { margin:5px 0 0; color:var(--app-ink-muted); font-size:13px; line-height:1.6; }
.guide-copy .guide-prompt { margin:2px 0 0; color:var(--app-primary-active); }
.guide-actions { display:flex; gap:8px; flex-shrink:0; }
.guide-body { display:grid; gap:16px; padding:18px; border-top:1px solid var(--app-border-soft); }
.guide-intro { margin:0; color:var(--app-ink-muted); font-size:13px; line-height:1.6; }
.guide-steps { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }
.guide-step { display:flex; align-items:center; gap:10px; padding:10px 12px; border:1px solid var(--app-border-soft); border-radius:var(--app-radius-sm); background:#ffffff; }
.guide-step strong { color:var(--app-primary-active); font-size:13px; flex:none; }
.guide-step span { color:var(--app-ink-body); font-size:13px; }

/* ---- 页头与步骤条 ---- */
.page-heading,.sidebar-header { display:flex; align-items:center; justify-content:space-between; gap:16px; }
.page-heading .panel-title { font-size:20px; letter-spacing:-0.3px; }
.heading-actions { display:flex; gap:8px; flex-wrap:wrap; }
.panel-subtitle,.panel-caption { color:var(--app-ink-muted); font-size:13px; }
.panel-subtitle { margin:6px 0 0; }.panel-caption { font-size:12px; }
.dispatch-steps { padding:2px 2px 6px; }
.dispatch-steps :deep(.el-step__title) { font-size:13px; }
.dispatch-steps :deep(.el-step__description) { font-size:12px; color:var(--app-ink-muted); }

/* ---- 三步卡片 ---- */
.step-card { overflow:hidden; }
.step-card-header { display:flex; align-items:center; gap:12px; padding:18px 20px; border-bottom:1px solid var(--app-border-soft); }
.step-card-header .panel-title { font-size:15px; }
.step-badge { width:28px; height:28px; flex:none; display:grid; place-items:center; border-radius:50%; background:var(--app-primary); color:#ffffff; font-size:14px; font-weight:700; }
.step-card-title { min-width:0; flex:1 1 auto; }
.step-card-title .panel-title { margin:0; }
.step-card-title .panel-caption { margin:4px 0 0; display:block; }
.step-card > .panel-body { padding:18px 20px 22px; }

/* ---- 筛选与配置 ---- */
.cascade-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }.cascade-grid .el-form-item { margin-bottom:0; }.cascade-grid :deep(.el-select),.cascade-grid :deep(.el-input) { width:100%; }
.keyword-search { margin-bottom:12px; }
.keyword-search :deep(.el-input) { width:100%; }
.filter-hint { margin:-6px 0 10px; color:var(--app-ink-muted); font-size:12px; }
.selection-summary,.profile-summary { display:flex; align-items:center; gap:10px; flex-wrap:wrap; padding:10px 12px; border:1px solid var(--app-border-soft); border-radius:var(--app-radius-sm); background:#f8fbff; color:var(--app-ink-body); }.selection-summary strong,.profile-summary strong { color:var(--app-ink); }.selection-summary code { margin-left:auto; }.run-option,.profile-option { display:flex; flex-direction:column; gap:2px; }.run-option span,.profile-option span { color:var(--app-ink-muted); font-size:12px; }
.profile-select { width:100%; }.profile-summary { margin-top:12px; justify-content:space-between; }.profile-summary p { margin:5px 0 0; color:var(--app-ink-muted); font-size:12px; }.profile-notes { width:100%; padding-top:8px; border-top:1px solid var(--app-border-soft); }
.summary-tags { display:flex; gap:6px; flex-wrap:wrap; }.form-grid,.manual-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }.full-width { width:100%; }

/* ---- 第三步：操作与预览 ---- */
.action-row { display:flex; align-items:center; justify-content:space-between; gap:8px; }
.action-info { display:flex; flex-direction:column; gap:3px; min-width:0; }
.action-info strong { color:var(--app-ink); font-size:14px; }
.action-info span { color:var(--app-ink-muted); font-size:12px; }
.action-buttons { display:flex; gap:8px; flex-shrink:0; }
.primary-action { min-width:180px; }
.preview-block { margin-top:18px; padding-top:18px; border-top:1px dashed var(--app-border); }
.preview-target { margin:0 0 12px; color:var(--app-ink-muted); font-size:12px; }
.preview-body { display:flex; flex-direction:column; gap:14px; padding:0; }
.preview-grid { display:grid; grid-template-columns:minmax(0,1.5fr) minmax(220px,.7fr); gap:18px; }
.preview-body h4 { margin:0 0 8px; font-size:13px; }
.result-facts { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
.result-facts div { display:flex; flex-direction:column; gap:4px; padding:10px; border:1px solid var(--app-border-soft); border-radius:var(--app-radius-sm); }
.result-facts span { color:var(--app-ink-muted); font-size:12px; }
.result-facts strong { font-size:18px; }
.result-facts small { display:block; font-size:11px; color:var(--app-ink-muted); font-weight:400; }
.result-facts code { font-size:12px; word-break:break-all; }
.fact-wide { grid-column:1 / -1; }
.json-view { margin:0; padding:10px; max-height:300px; overflow:auto; border:1px solid var(--app-border-soft); border-radius:var(--app-radius-sm); background:#f8fafc; color:var(--app-ink-body); font:12px/1.6 var(--app-mono-font); white-space:pre-wrap; word-break:break-word; }

/* ---- 附加信息 ---- */
.extra-collapse { margin-top:12px; }
.extra-collapse :deep(.el-collapse-item__header) { padding:8px 12px; font-size:13px; }
.extra-title { font-weight:600; color:var(--app-ink); }
.extra-caption { margin-left:10px; color:var(--app-ink-muted); font-size:12px; font-weight:400; }
.extra-body { display:flex; flex-direction:column; gap:12px; padding:4px 2px; }
.extra-note { margin:0; color:var(--app-ink-muted); font-size:12px; }
.output-list { list-style:none; margin:0 0 10px; padding:0; display:flex; flex-direction:column; gap:6px; }
.output-list li { display:flex; gap:10px; align-items:flex-start; padding:6px 10px; border:1px solid var(--app-border-soft); border-radius:var(--app-radius-sm); background:#f8fafc; font-size:12px; }
.output-list code { flex:0 0 38%; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.output-list span { word-break:break-all; }
.output-count { margin:0 0 8px; color:var(--app-ink-muted); font-size:12px; }

/* ---- 侧栏 ---- */
.main-layout { display:grid; grid-template-columns:minmax(0,1fr) 360px; gap:20px; align-items:start; }
.main-workspace { min-width:0; display:flex; flex-direction:column; gap:20px; }
.saved-sidebar { position:sticky; top:16px; min-width:0; overflow:hidden; }
.sidebar-header { padding:16px 16px 8px; }
.sidebar-search { margin:0 12px 10px; width:calc(100% - 24px); }
.saved-item { width:100%; display:flex; flex-direction:column; align-items:flex-start; gap:5px; padding:10px 12px; border:0; border-top:1px solid var(--app-border-soft); background:transparent; color:inherit; text-align:left; cursor:pointer; }.saved-item:hover { background:#f5f8fc; }
.saved-item span { color:var(--app-ink-muted); font-size:11px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:100%; }
.interface-preview { padding:2px 12px 16px; }.interface-preview dl { display:grid; grid-template-columns:90px 1fr; gap:8px; margin:14px 0; font-size:12px; }.interface-preview dt { color:var(--app-ink-muted); }.interface-preview dd { margin:0; word-break:break-all; }.interface-preview h4 { margin:14px 0 6px; font-size:12px; }
.main-layout.sidebar-docked { grid-template-columns:minmax(0,1fr) 32px; }
.saved-sidebar.docked { width:32px; padding:0; display:flex; align-items:stretch; align-self:stretch; box-shadow:none; }
.saved-sidebar.docked :deep(.el-tooltip__trigger) { flex:1; display:flex; min-height:140px; }
.sidebar-dock { flex:1; width:100%; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:10px; padding:0; border:0; background:transparent; color:var(--app-ink-muted); cursor:pointer; font:inherit; }
.sidebar-dock:hover { color:var(--app-primary); background:#f5f8fc; }
.sidebar-dock-label { writing-mode:vertical-rl; letter-spacing:3px; font-size:12px; }

/* ---- 响应式 ---- */
@media (max-width:1200px) { .cascade-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (max-width:900px) { .main-layout { grid-template-columns:1fr; }.main-layout.sidebar-docked { grid-template-columns:1fr; }.saved-sidebar { position:fixed; z-index:20; inset:72px 0 0 auto; width:min(360px,92vw); box-shadow:-8px 0 24px rgba(25,45,75,.16); }.saved-sidebar.docked { width:32px; box-shadow:none; }.preview-grid { grid-template-columns:1fr; } }
@media (max-width:640px) { .page-heading,.action-row { align-items:stretch; flex-direction:column; }.heading-actions .el-button { flex:1; }.cascade-grid,.form-grid,.manual-grid { grid-template-columns:1fr; }.selection-summary code { margin-left:0; }.guide-bar { flex-wrap:wrap; row-gap:10px; }.guide-actions { width:100%; }.guide-actions .el-button { flex:1; }.guide-steps { grid-template-columns:1fr; }.action-buttons { width:100%; flex-direction:column; }.action-buttons .el-button { width:100%; margin-left:0; } }
</style>
