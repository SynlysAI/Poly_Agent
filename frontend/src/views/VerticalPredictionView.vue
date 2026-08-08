<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowRight, Box, Clock, DataAnalysis, Delete, Document, Edit, Key, Link, Refresh, Search, UploadFilled, VideoPlay,
} from '@element-plus/icons-vue'

import {
  getApiErrorMessage,
  deleteAlgorithm,
  listAlgorithmPackages,
  listAlgorithmRuns,
  listAlgorithms,
  listAlgorithmVersions,
} from '../api/polyAgentApi'
import AlgorithmManagementPanel from './vertical-prediction/AlgorithmManagementPanel.vue'
import AlgorithmHandoffPanel from './vertical-prediction/AlgorithmHandoffPanel.vue'
import AlgorithmInterfaceConfigPanel from './vertical-prediction/AlgorithmInterfaceConfigPanel.vue'
import AlgorithmMetadataEditor from './vertical-prediction/AlgorithmMetadataEditor.vue'
import AlgorithmRunHistoryPanel from './vertical-prediction/AlgorithmRunHistoryPanel.vue'
import AlgorithmTestPanel from './vertical-prediction/AlgorithmTestPanel.vue'
import AlgorithmUploadPanel from './vertical-prediction/AlgorithmUploadPanel.vue'
import AttributionBadges from '../components/attribution/AttributionBadges.vue'
import { formatApiDateTime } from '../utils/datetime'
import {
  algorithmSourceLabel,
  canEditRemoteInterfaceVersion,
  canManageUploadedAlgorithm,
  interfaceProtocolLabel,
  shouldReturnToCenterAfterSelectionReconciliation,
} from '../utils/verticalPredictionState.mjs'
import { authState } from '../auth/authState'

const route = useRoute()
const router = useRouter()

const detailTabMap = { management: 'api', test: 'experience', runs: 'api' }
const routeModes = new Set(['center', 'doc', 'upload', 'interface-config', 'detail'])
const connectedPackageStatuses = ['built', 'deployed_staging', 'active']

const activeMode = ref(normalizeMode(route.query.tab))
const detailActiveTab = ref(normalizeDetailTab(route.query.tab))
const loading = ref(false)
const refreshKey = ref(0)
const algorithms = ref([])
const versionMap = ref({})
const summary = ref({ packages: 0, interfaces: 0, activeAlgorithms: 0, recentRuns: 0 })
const searchText = ref('')
const sourceFilter = ref('')
const statusFilter = ref('')
const typeFilter = ref('')
const materialFilter = ref('')
const selectedAlgorithmId = ref(normalizeQueryString(route.query.algorithm_id))
const interfaceConfigVersionId = ref(normalizeQueryString(route.query.version_id))
const selectedHandoffId = ref(normalizeQueryString(route.query.handoff_id))
const docEntryMode = ref(normalizeQueryString(route.query.doc_mode) === 'download' ? 'download' : 'upload')
const uploadContextMode = ref(normalizeQueryString(route.query.upload_mode) === 'new_version' ? 'new_version' : 'new_algorithm')
const metadataEditorVisible = ref(false)
const targetRunId = ref(normalizeQueryString(route.query.run_id))

const selectedAlgorithm = computed(() => algorithms.value.find((item) => item.algorithm_id === selectedAlgorithmId.value) || null)
const selectedVersions = computed(() => versionMap.value[selectedAlgorithmId.value] || [])
const activeVersion = computed(() =>
  selectedVersions.value.find((item) => item.version_id === selectedAlgorithm.value?.active_version_id)
  || selectedVersions.value.find((item) => item.status === 'active')
  || selectedVersions.value[0]
  || null,
)
const interfaceConfigTargetVersion = computed(() =>
  selectedVersions.value.find((item) => item.version_id === interfaceConfigVersionId.value)
  || activeVersion.value
  || null,
)
const interfaceConfigMode = computed(() => {
  if (interfaceConfigVersionId.value) return 'edit_version'
  return selectedAlgorithmId.value ? 'new_version' : 'new_interface'
})
const editableInterfaceVersion = computed(() => {
  if (selectedAlgorithm.value?.source !== 'remote_interface') return null
  return [...selectedVersions.value]
    .filter((version) => canEditRemoteInterfaceVersion(version))
    .sort((left, right) => new Date(right.updated_at || right.created_at || 0) - new Date(left.updated_at || left.created_at || 0))[0]
    || null
})

const statusItems = computed(() => [
  { label: '算法上传', value: summary.value.packages, icon: UploadFilled },
  { label: '接口调用', value: summary.value.interfaces, icon: Link },
  { label: '可用模型', value: summary.value.activeAlgorithms, icon: Box },
  { label: '最近运行', value: summary.value.recentRuns, icon: Clock },
])

const filteredAlgorithms = computed(() => {
  const keyword = searchText.value.trim().toLowerCase()
  return algorithms.value.filter((item) => {
    const textMatch = !keyword || [item.name, item.algorithm_id, item.description, item.mentor_team].some((value) => String(value || '').toLowerCase().includes(keyword))
    const sourceMatch = !sourceFilter.value || item.source === sourceFilter.value
    const statusMatch = !statusFilter.value || item.status === statusFilter.value
    const typeMatch = !typeFilter.value || item.type === typeFilter.value
    const materialMatch = !materialFilter.value || (item.material_scope || []).includes(materialFilter.value)
    return textMatch && sourceMatch && statusMatch && typeMatch && materialMatch
  })
})

const typeOptions = computed(() => Array.from(new Set(algorithms.value.map((item) => item.type).filter(Boolean))))
const statusOptions = computed(() => Array.from(new Set(algorithms.value.map((item) => item.status).filter(Boolean))))
const materialOptions = computed(() => Array.from(new Set(algorithms.value.flatMap((item) => item.material_scope || []).filter(Boolean))))

const selectedAlgorithmAttributions = computed(() => algorithmAttributions(selectedAlgorithm.value))
const canManageSelectedAlgorithm = computed(() => canManageUploadedAlgorithm(selectedAlgorithm.value, authState))
const algorithmSummary = computed(() => {
  const algorithm = selectedAlgorithm.value
  if (!algorithm) return null
  const rawSummary = algorithm.algorithm_summary || activeVersion.value?.algorithm_summary
  if (rawSummary?.overview) {
    return {
      overview: rawSummary.overview,
      highlights: normalizeSummaryItems(rawSummary.highlights),
      practices: normalizeSummaryItems(rawSummary.practices),
      generated_by: rawSummary.generated_by || 'rule',
    }
  }
  return buildSummaryFallback(algorithm, activeVersion.value)
})

function normalizeQueryString(value) {
  return Array.isArray(value) ? value[0] || '' : value || ''
}

function normalizeMode(tab) {
  const value = normalizeQueryString(tab)
  if (value === 'upload') return 'upload'
  if (value === 'doc' || value === 'handoff') return 'doc'
  if (value === 'detail' || detailTabMap[value]) return 'detail'
  return routeModes.has(value) ? value : 'center'
}

function normalizeDetailTab(tab) {
  const value = normalizeQueryString(tab)
  return detailTabMap[value] || (['experience', 'summary', 'docs', 'api'].includes(value) ? value : 'experience')
}

function syncRoute() {
  const query = { ...route.query }
  if (activeMode.value === 'center') {
    query.tab = 'center'
    delete query.algorithm_id
    delete query.handoff_id
    delete query.doc_mode
    delete query.upload_mode
    delete query.version_id
    delete query.run_id
  } else if (activeMode.value === 'doc') {
    query.tab = 'doc'
    delete query.algorithm_id
    delete query.upload_mode
    if (selectedHandoffId.value) query.handoff_id = selectedHandoffId.value
    else delete query.handoff_id
    query.doc_mode = docEntryMode.value
    delete query.version_id
    delete query.run_id
  } else if (activeMode.value === 'upload') {
    query.tab = 'upload'
    if (uploadContextMode.value === 'new_version' && selectedAlgorithmId.value) {
      query.upload_mode = 'new_version'
      query.algorithm_id = selectedAlgorithmId.value
    } else {
      delete query.upload_mode
      delete query.algorithm_id
    }
    delete query.handoff_id
    delete query.doc_mode
    delete query.version_id
    delete query.run_id
  } else if (activeMode.value === 'interface-config') {
    query.tab = 'interface-config'
    if (selectedAlgorithm.value?.source === 'remote_interface') query.algorithm_id = selectedAlgorithmId.value
    else delete query.algorithm_id
    if (interfaceConfigVersionId.value) query.version_id = interfaceConfigVersionId.value
    else delete query.version_id
    delete query.handoff_id
    delete query.doc_mode
    delete query.upload_mode
    delete query.run_id
  } else {
    query.tab = 'detail'
    if (selectedAlgorithmId.value) query.algorithm_id = selectedAlgorithmId.value
    delete query.handoff_id
    delete query.doc_mode
    delete query.upload_mode
    delete query.version_id
  }
  if (JSON.stringify(query) !== JSON.stringify(route.query)) router.replace({ query })
}

watch(
  () => route.query,
  (query) => {
    activeMode.value = normalizeMode(query.tab)
    detailActiveTab.value = normalizeDetailTab(query.tab)
    selectedAlgorithmId.value = normalizeQueryString(query.algorithm_id)
    interfaceConfigVersionId.value = normalizeQueryString(query.version_id)
    selectedHandoffId.value = normalizeQueryString(query.handoff_id)
    docEntryMode.value = normalizeQueryString(query.doc_mode) === 'download' ? 'download' : 'upload'
    uploadContextMode.value = normalizeQueryString(query.upload_mode) === 'new_version' ? 'new_version' : 'new_algorithm'
    targetRunId.value = normalizeQueryString(query.run_id)
  },
)

watch([activeMode, selectedAlgorithmId, interfaceConfigVersionId, selectedHandoffId, docEntryMode, uploadContextMode], syncRoute)

watch(targetRunId, (value) => {
  if (activeMode.value === 'detail' && value && selectedAlgorithm.value) {
    detailActiveTab.value = 'api'
  }
})

async function loadData() {
  loading.value = true
  try {
    const [connectedPackages, algorithmData, runs] = await Promise.all([
      listConnectedAlgorithmPackages(),
      listAlgorithms({ algorithm_family: 'vertical_prediction', page: 1, page_size: 100 }),
      listAlgorithmRuns({ page: 1, page_size: 100 }),
    ])
    algorithms.value = (algorithmData.items || []).filter((item) => ['uploaded_package', 'remote_interface'].includes(item.source))
    const governedRuns = (runs.items || []).filter((item) => item.algorithm_version_id)
    summary.value = {
      packages: connectedAlgorithmCount(connectedPackages),
      interfaces: algorithms.value.filter((item) => item.source === 'remote_interface').length,
      activeAlgorithms: algorithms.value.filter((item) => item.status === 'active').length,
      recentRuns: governedRuns.length,
    }
    reconcileSelectedAlgorithm()
    if (activeMode.value === 'detail' && targetRunId.value && selectedAlgorithm.value) {
      detailActiveTab.value = 'api'
    }
    await loadVersionsForCards()
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function listConnectedAlgorithmPackages() {
  const pagesByStatus = await Promise.all(
    connectedPackageStatuses.map((status) => listAllAlgorithmPackages({ status })),
  )
  return pagesByStatus.flat()
}

async function listAllAlgorithmPackages(params = {}) {
  const pageSize = 100
  const firstPage = await listAlgorithmPackages({ ...params, page: 1, page_size: pageSize })
  const items = [...(firstPage.items || [])]
  const total = firstPage.total || items.length
  const pageCount = Math.ceil(total / pageSize)
  if (pageCount <= 1) return items

  const remainingPages = await Promise.all(
    Array.from({ length: pageCount - 1 }, (_, index) => listAlgorithmPackages({ ...params, page: index + 2, page_size: pageSize })),
  )
  return items.concat(remainingPages.flatMap((page) => page.items || []))
}

function connectedAlgorithmCount(packages) {
  const algorithmIds = new Set()
  for (const item of packages || []) {
    const algorithmId = String(item.algorithm_id || item.target_algorithm_id || '').trim()
    if (algorithmId) algorithmIds.add(algorithmId)
  }
  return algorithmIds.size
}

async function loadVersionsForCards() {
  const entries = await Promise.all(
    algorithms.value.map(async (algorithm) => {
      try {
        const data = await listAlgorithmVersions(algorithm.algorithm_id, { page: 1, page_size: 100 })
        return [algorithm.algorithm_id, data.items || []]
      } catch {
        return [algorithm.algorithm_id, []]
      }
    }),
  )
  versionMap.value = Object.fromEntries(entries)
}

function reconcileSelectedAlgorithm() {
  const currentId = selectedAlgorithmId.value
  const currentExists = currentId && algorithms.value.some((item) => item.algorithm_id === currentId)
  if (!shouldReturnToCenterAfterSelectionReconciliation({
    activeMode: activeMode.value,
    uploadContextMode: uploadContextMode.value,
    selectedAlgorithmId: currentId,
    selectedAlgorithmExists: currentExists,
  })) return

  selectedAlgorithmId.value = ''
  activeMode.value = 'center'
  ElMessage.info('模型已删除，已返回模型中心')
}

function handleChanged(packageInfo) {
  refreshKey.value += 1
  if (packageInfo?.registry_deleted && packageInfo.algorithm_id === selectedAlgorithmId.value) {
    selectedAlgorithmId.value = ''
    activeMode.value = 'center'
  } else if (packageInfo?.algorithm_id && !packageInfo?.deleted) {
    selectedAlgorithmId.value = packageInfo.algorithm_id
  }
  loadData()
}

function handleRunCreated() {
  loadData()
}

function openUpload() {
  uploadContextMode.value = 'new_algorithm'
  selectedAlgorithmId.value = ''
  activeMode.value = 'upload'
}

function openInterfaceConfig(algorithmId = '') {
  selectedAlgorithmId.value = algorithmId
  interfaceConfigVersionId.value = ''
  activeMode.value = 'interface-config'
}

function openEditInterfaceConfig(version) {
  if (!selectedAlgorithmId.value || !canEditRemoteInterfaceVersion(version)) return
  interfaceConfigVersionId.value = version.version_id
  activeMode.value = 'interface-config'
}

function openNewVersion() {
  if (!selectedAlgorithmId.value) return
  if (selectedAlgorithm.value?.source === 'remote_interface') {
    interfaceConfigVersionId.value = ''
    activeMode.value = 'interface-config'
    return
  }
  uploadContextMode.value = 'new_version'
  activeMode.value = 'upload'
}

function openMetadataEditor() {
  if (!canManageSelectedAlgorithm.value) return
  metadataEditorVisible.value = true
}

async function removeSelectedAlgorithm() {
  if (!selectedAlgorithm.value || !canManageSelectedAlgorithm.value) return
  try {
    await ElMessageBox.confirm(
      `删除模型将移除全部接口版本，但保留历史运行、Artifact 和审计记录。请输入模型 ID「${selectedAlgorithm.value.algorithm_id}」确认。`,
      '删除模型确认',
      { type: 'warning', inputPattern: new RegExp(`^${selectedAlgorithm.value.algorithm_id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`), inputErrorMessage: '模型 ID 不匹配' },
    )
    await deleteAlgorithm(selectedAlgorithm.value.algorithm_id, selectedAlgorithm.value.algorithm_id)
    ElMessage.success('模型及其版本已删除，历史运行记录已保留')
    selectedAlgorithmId.value = ''
    activeMode.value = 'center'
    await loadData()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getApiErrorMessage(error))
  }
}

function handleMetadataSaved(updated) {
  const index = algorithms.value.findIndex((item) => item.algorithm_id === updated?.algorithm_id)
  if (index >= 0) algorithms.value[index] = updated
  refreshKey.value += 1
  loadData()
}

function openDoc(mode = 'upload') {
  docEntryMode.value = mode
  selectedHandoffId.value = ''
  activeMode.value = 'doc'
}

function openCenter() {
  activeMode.value = 'center'
}

function openDetail(algorithmId, tab = 'experience') {
  selectedAlgorithmId.value = algorithmId
  detailActiveTab.value = tab
  activeMode.value = 'detail'
}

function formatDate(value) {
  return formatApiDateTime(value)
}

function statusType(status) {
  const map = { active: 'success', frozen: 'info', decommissioned: 'danger', pending_encapsulation: 'warning', in_development: 'warning' }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = { active: '已激活', frozen: '已冻结', decommissioned: '已下线', pending_encapsulation: '待封装', in_development: '开发中' }
  return map[status] || status || '-'
}

function typeLabel(type) {
  const map = { retriever: '检索器', predictor: '预测器', simulator: '模拟器', optimizer: '优化器' }
  return map[type] || type || '-'
}

function materialLabel(value) {
  const map = { universal: '通用', fluoropolymer: '氟基', carbon_polymer: '碳基', silicon_polymer: '硅基', fluoro_carbon_copolymer: '氟碳共聚' }
  return map[value] || value
}

function fieldRows(schema) {
  return Object.entries(schema?.fields || {}).map(([name, type]) => ({
    name,
    type,
    required: (schema.required || []).includes(name) ? '是' : '否',
    unit: schema.ui_hints?.[name]?.unit || '-',
  }))
}

function normalizeSummaryItems(items) {
  if (typeof items === 'string') return [items].filter(Boolean)
  if (!Array.isArray(items)) return []
  return items.map((item) => String(item || '').trim()).filter(Boolean)
}

function buildSummaryFallback(algorithm, version) {
  const inputFields = Object.keys(algorithm.input_schema?.fields || {})
  const outputFields = Object.keys(algorithm.output_schema?.fields || {})
  const materialScope = (algorithm.material_scope || []).map((value) => materialLabel(value)).filter(Boolean)
  const versionLabel = version?.version || algorithm.version || '-'
  return {
    overview:
      algorithm.description
      || `${algorithm.name} 是一个 ${typeLabel(algorithm.type)}，当前版本 ${versionLabel} 可用于垂类预测。`,
    highlights: [
      inputFields.length ? `输入字段：${inputFields.slice(0, 4).join('、')}` : '输入契约已接入测试台',
      outputFields.length ? `输出字段：${outputFields.slice(0, 4).join('、')}` : '结果会保留版本和运行记录',
      materialScope.length ? `适用范围：${materialScope.join('、')}` : '',
      version?.resource_assets?.length ? `支持 ${version.resource_assets.length} 项受管资源绑定` : '',
    ].filter(Boolean),
    practices: algorithm.source === 'remote_interface'
      ? [
        '先完成连通性测试，确认响应提取路径和输出字段一致。',
        `版本 ${versionLabel} 激活后保留旧版本一段时间，再冻结或下线。`,
        '凭据只填写环境变量或密钥引用名，不在配置中保存明文。',
      ]
      : [
        '先用样例输入完成一次自测，确认字段名和类型一致。',
        `版本 ${versionLabel} 上线后保留旧版本一段时间，再冻结或下线。`,
        version?.resource_assets?.length ? '大资源通过资源管理绑定，不要直接打进 ZIP 包。' : '',
      ].filter(Boolean),
    generated_by: 'rule',
  }
}

function summarySourceLabel(summary) {
  return summary?.generated_by === 'llm' ? 'AI 生成摘要' : '规则摘要'
}

function sourceLine(algorithm) {
  const parts = []
  const author = authorLabel(algorithm)
  if (author && author !== '未标注') parts.push(author)
  const mentor = mentorTeamLabel(algorithm)
  if (mentor && mentor !== '未标注') parts.push(`导师课题组：${mentor}`)
  return parts.length ? parts.join(' · ') : '来源信息未标注'
}

function algorithmAttributions(algorithm) {
  if (!algorithm) return []
  return [
    algorithm.developer_attribution,
    ...(algorithm.framework_attributions || []),
    ...(algorithm.method_attributions || []),
  ].filter(isPublicAttribution)
}

function protocolLabel(algorithm, version = null) {
  return interfaceProtocolLabel(version?.interface_config?.protocol || algorithm?.interface_config?.protocol)
}

function endpointSummary(algorithm, version = null) {
  const value = version?.interface_config?.endpoint_url || algorithm?.interface_config?.endpoint_url
  if (!value) return '-'
  try {
    const url = new URL(value)
    return `${url.protocol}//${url.host}${url.pathname}`
  } catch {
    return value
  }
}

function authorLabel(algorithm) {
  const attribution = algorithm?.developer_attribution
  const developer = cleanAuthorValue(attribution?.name) || cleanAuthorValue(algorithm?.owner)
  const organization = cleanAuthorValue(attribution?.organization)
  if (developer && organization) return `${developer} / ${organization}`
  return developer || organization || '未标注'
}

function mentorTeamLabel(algorithm) {
  return cleanAuthorValue(algorithm?.mentor_team) || '未标注'
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

function visibilityLabel(value) {
  return value === 'public' ? '公开发布' : '非公开'
}

onMounted(() => {
  loadData()
})
</script>

<template>
  <div class="vertical-prediction-page">
    <template v-if="activeMode === 'center'">
      <header class="model-page-hero">
      <div>
        <p class="eyebrow">任务提交 / 预测模型</p>
        <h1>垂类预测模型</h1>
        <p>通过需求文档或模型文件接入预测能力，统一完成测试、版本管理和运行追溯。</p>
      </div>
      <div class="hero-actions">
        <el-button :icon="Refresh" :loading="loading" @click="loadData">刷新</el-button>
      </div>
      </header>

      <section class="status-band" v-loading="loading" aria-label="垂类预测模型状态摘要">
        <div v-for="item in statusItems" :key="item.label" class="status-item">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </div>
      </section>
    </template>

    <template v-if="activeMode === 'doc'">
      <div class="subnav-row">
        <el-button text @click="openCenter">返回模型中心</el-button>
        <el-button text type="primary" @click="openUpload">高级导入</el-button>
      </div>
      <AlgorithmHandoffPanel :entry-mode="docEntryMode" :initial-handoff-id="selectedHandoffId" @changed="handleChanged" />
    </template>

    <template v-if="activeMode === 'upload'">
      <div class="subnav-row">
        <el-button text @click="openCenter">返回模型中心</el-button>
        <el-button text type="primary" @click="openDoc('upload')">需求文档</el-button>
      </div>
      <AlgorithmUploadPanel
        v-if="uploadContextMode !== 'new_version' || (!loading && selectedAlgorithm)"
        :mode="uploadContextMode"
        :target-algorithm="selectedAlgorithm"
        :target-version="activeVersion"
        :target-versions="selectedVersions"
        @changed="handleChanged"
        @view-detail="openDetail"
      />
      <el-skeleton v-else :rows="8" animated />
    </template>

    <template v-if="activeMode === 'interface-config'">
      <div class="subnav-row">
        <el-button text @click="openCenter">返回模型中心</el-button>
      </div>
      <AlgorithmInterfaceConfigPanel
        :mode="interfaceConfigMode"
        :target-algorithm="selectedAlgorithm"
        :target-version="interfaceConfigTargetVersion"
        :target-versions="selectedVersions"
        @changed="handleChanged"
        @view-detail="openDetail"
        @cancel="openCenter"
      />
    </template>

    <template v-else-if="activeMode === 'detail' && selectedAlgorithm">
      <div class="subnav-row">
        <el-button text @click="openCenter">返回模型中心</el-button>
        <el-button v-if="canManageSelectedAlgorithm" text type="primary" @click="openNewVersion">{{ selectedAlgorithm.source === 'remote_interface' ? '新建接口版本' : '上传新版本' }}</el-button>
      </div>
      <section class="detail-banner">
        <div class="model-avatar"><el-icon><DataAnalysis /></el-icon></div>
        <div class="detail-main">
          <div class="detail-title-row">
            <h2>{{ selectedAlgorithm.name }}</h2>
            <el-tag :type="statusType(selectedAlgorithm.status)">{{ statusLabel(selectedAlgorithm.status) }}</el-tag>
          </div>
          <p>{{ selectedAlgorithm.description || '该模型已接入垂类预测工作台，可用于测试调用、版本管理和研发流程。' }}</p>
          <div class="author-line">来源：{{ sourceLine(selectedAlgorithm) }}</div>
          <AttributionBadges :attributions="selectedAlgorithmAttributions" />
          <div class="detail-meta">
            <span>{{ selectedAlgorithm.algorithm_id }}</span>
            <span>{{ algorithmSourceLabel(selectedAlgorithm.source) }}</span>
            <span v-if="selectedAlgorithm.source === 'remote_interface'">{{ protocolLabel(selectedAlgorithm, activeVersion) }}</span>
            <span>{{ typeLabel(selectedAlgorithm.type) }}</span>
            <span>{{ visibilityLabel(selectedAlgorithm.visibility) }}</span>
            <span>版本 {{ activeVersion?.version || selectedAlgorithm.version || '-' }}</span>
            <span>更新 {{ formatDate(activeVersion?.updated_at) }}</span>
          </div>
        </div>
        <div class="detail-actions">
          <el-button
            v-if="selectedAlgorithm.source === 'remote_interface' && canManageSelectedAlgorithm && editableInterfaceVersion"
            :icon="Edit"
            @click="openEditInterfaceConfig(editableInterfaceVersion)"
          >编辑接口配置</el-button>
          <el-button v-if="canManageSelectedAlgorithm" :icon="Edit" @click="openMetadataEditor">编辑信息</el-button>
          <el-button v-if="canManageSelectedAlgorithm" type="danger" plain :icon="Delete" @click="removeSelectedAlgorithm">删除模型</el-button>
          <el-button :icon="VideoPlay" type="primary" @click="detailActiveTab = 'experience'">立即体验</el-button>
          <el-button :icon="Key" @click="detailActiveTab = 'api'">版本治理</el-button>
        </div>
      </section>

      <section class="detail-panel">
        <el-tabs v-model="detailActiveTab" class="detail-tabs">
          <el-tab-pane label="互动体验" name="experience">
            <AlgorithmTestPanel :refresh-key="refreshKey" :algorithm-id="selectedAlgorithm.algorithm_id" :show-toolbar="false" @run-created="handleRunCreated" />
          </el-tab-pane>
          <el-tab-pane label="算法摘要" name="summary">
            <div v-if="algorithmSummary" class="summary-panel">
              <div class="summary-head">
                <div>
                  <h3>算法摘要</h3>
                  <p>{{ summarySourceLabel(algorithmSummary) }}</p>
                </div>
                <el-tag size="small" effect="plain">{{ algorithmSummary.generated_by === 'llm' ? 'AI 生成' : '规则回退' }}</el-tag>
              </div>
              <p class="summary-overview">{{ algorithmSummary.overview }}</p>
              <div class="summary-grid">
                <section>
                  <h4>亮点</h4>
                  <ul>
                    <li v-for="item in algorithmSummary.highlights" :key="item">{{ item }}</li>
                  </ul>
                </section>
                <section>
                  <h4>实践建议</h4>
                  <ul>
                    <li v-for="item in algorithmSummary.practices" :key="item">{{ item }}</li>
                  </ul>
                </section>
              </div>
            </div>
          </el-tab-pane>
          <el-tab-pane label="API 使用手册" name="docs">
            <div class="docs-layout">
              <section>
                <h3>输入字段</h3>
                <el-table :data="fieldRows(selectedAlgorithm.input_schema)" border size="small">
                  <el-table-column prop="name" label="字段" min-width="140" />
                  <el-table-column prop="type" label="类型" width="120" />
                  <el-table-column prop="required" label="必填" width="90" />
                  <el-table-column prop="unit" label="单位" width="100" />
                </el-table>
              </section>
              <section>
                <h3>输出字段</h3>
                <el-table :data="fieldRows(selectedAlgorithm.output_schema)" border size="small">
                  <el-table-column prop="name" label="字段" min-width="140" />
                  <el-table-column prop="type" label="类型" width="120" />
                  <el-table-column prop="required" label="必填" width="90" />
                  <el-table-column prop="unit" label="单位" width="100" />
                </el-table>
              </section>
              <section class="api-note">
                <el-icon><Document /></el-icon>
                <span v-if="selectedAlgorithm.source === 'remote_interface'">{{ protocolLabel(selectedAlgorithm, activeVersion) }} · {{ endpointSummary(selectedAlgorithm, activeVersion) }}。调用时仅使用已登记的版本，凭据不会展示在页面中。</span>
                <span v-else>外部集成时按输入字段提交请求，并记录模型 ID 与版本 ID，便于结果追溯。</span>
              </section>
            </div>
          </el-tab-pane>
          <el-tab-pane label="API Key / 版本治理" name="api">
            <div class="governance-layout">
              <AlgorithmManagementPanel :refresh-key="refreshKey" :algorithm-id="selectedAlgorithm.algorithm_id" :show-selector="false" @changed="handleChanged" @edit-interface-config="openEditInterfaceConfig" />
              <section class="history-panel">
                <h3>运行记录</h3>
                <AlgorithmRunHistoryPanel :refresh-key="refreshKey" :algorithm-id="selectedAlgorithm.algorithm_id" :focus-run-id="targetRunId" :output-schema="selectedAlgorithm?.output_schema" />
              </section>
            </div>
          </el-tab-pane>
        </el-tabs>
      </section>
    </template>

    <template v-else-if="activeMode === 'detail'">
      <div class="empty-models" v-loading="loading">
        <template v-if="!loading">
          <el-icon><UploadFilled /></el-icon>
          <strong>模型不存在或已删除</strong>
          <span>返回模型中心后可以继续管理其他垂类预测模型。</span>
          <div class="empty-actions">
            <el-button type="primary" @click="openCenter">返回模型中心</el-button>
          </div>
        </template>
      </div>
    </template>

    <template v-else-if="activeMode === 'center'">
      <div class="model-center-layout">
        <aside class="filter-panel">
          <div class="filter-title">筛选</div>
          <el-input v-model="searchText" :prefix-icon="Search" placeholder="搜索模型名称、ID" clearable />
          <div class="filter-group">
            <span>模型来源</span>
            <el-radio-group v-model="sourceFilter">
              <el-radio-button value="">全部</el-radio-button>
              <el-radio-button value="uploaded_package">算法上传</el-radio-button>
              <el-radio-button value="remote_interface">接口调用</el-radio-button>
            </el-radio-group>
          </div>
          <div class="filter-group">
            <span>状态</span>
            <el-radio-group v-model="statusFilter">
              <el-radio-button value="">全部</el-radio-button>
              <el-radio-button v-for="status in statusOptions" :key="status" :value="status">{{ statusLabel(status) }}</el-radio-button>
            </el-radio-group>
          </div>
          <div class="filter-group">
            <span>类型</span>
            <el-radio-group v-model="typeFilter">
              <el-radio-button value="">全部</el-radio-button>
              <el-radio-button v-for="type in typeOptions" :key="type" :value="type">{{ typeLabel(type) }}</el-radio-button>
            </el-radio-group>
          </div>
          <div class="filter-group">
            <span>材料范围</span>
            <el-radio-group v-model="materialFilter">
              <el-radio-button value="">全部</el-radio-button>
              <el-radio-button v-for="item in materialOptions" :key="item" :value="item">{{ materialLabel(item) }}</el-radio-button>
            </el-radio-group>
          </div>
        </aside>

        <main class="model-list-panel">
          <div class="list-head">
            <div>
              <h2>模型中心</h2>
              <p>共 {{ filteredAlgorithms.length }} 个可管理模型</p>
            </div>
            <div class="list-actions">
              <el-button type="primary" plain :icon="Document" @click="openDoc('upload')">需求文档导入</el-button>
              <el-button type="primary" plain :icon="UploadFilled" @click="openUpload">高级导入</el-button>
              <el-button type="primary" plain :icon="Link" @click="openInterfaceConfig()">接口配置</el-button>
            </div>
          </div>

          <div v-if="filteredAlgorithms.length" class="model-card-grid" v-loading="loading">
            <button v-for="item in filteredAlgorithms" :key="item.algorithm_id" type="button" class="model-card" @click="openDetail(item.algorithm_id)">
              <div class="model-card-top">
                <div class="model-avatar small"><el-icon><DataAnalysis /></el-icon></div>
                <div class="model-card-title">
                  <strong>{{ item.name }}</strong>
                  <span>{{ item.algorithm_id }}</span>
                </div>
                <el-tag :type="statusType(item.status)" size="small">{{ statusLabel(item.status) }}</el-tag>
              </div>
              <p>{{ item.description || (item.source === 'remote_interface' ? '已登记的远程接口模型，可在详情页完成连通性测试和版本调用。' : '已上传的垂类预测模型，可在详情页进行测试调用、版本治理和运行追溯。') }}</p>
              <div class="author-line compact">来源：{{ sourceLine(item) }}</div>
              <AttributionBadges :attributions="algorithmAttributions(item)" />
              <div class="model-tags">
                <el-tag size="small" effect="plain">{{ algorithmSourceLabel(item.source) }}</el-tag>
                <el-tag v-if="item.source === 'remote_interface'" size="small" effect="plain">{{ protocolLabel(item) }}</el-tag>
                <el-tag size="small" effect="plain">{{ typeLabel(item.type) }}</el-tag>
                <el-tag size="small" effect="plain">{{ visibilityLabel(item.visibility) }}</el-tag>
                <el-tag v-for="scope in item.material_scope" :key="scope" size="small" effect="plain">{{ materialLabel(scope) }}</el-tag>
              </div>
              <div class="model-card-foot">
                <span>当前版本 {{ item.active_version_id || '无' }}</span>
                <el-icon><ArrowRight /></el-icon>
              </div>
            </button>
          </div>

          <div v-else class="empty-models">
            <el-icon><UploadFilled /></el-icon>
            <strong>还没有符合条件的垂类预测模型</strong>
            <span>先走需求文档或高级导入，模型会出现在这里。</span>
            <div class="empty-actions">
              <el-button type="primary" plain :icon="Document" @click="openDoc('upload')">需求文档导入</el-button>
              <el-button type="primary" plain :icon="UploadFilled" @click="openUpload">高级导入</el-button>
              <el-button type="primary" plain :icon="Link" @click="openInterfaceConfig()">接口配置</el-button>
            </div>
          </div>
        </main>
      </div>
    </template>

    <AlgorithmMetadataEditor
      v-model:visible="metadataEditorVisible"
      :algorithm="selectedAlgorithm"
      :active-version="activeVersion"
      @saved="handleMetadataSaved"
    />
  </div>
</template>

<style scoped>
.vertical-prediction-page { display: grid; gap: 16px; }
.model-page-hero, .detail-banner, .detail-panel, .filter-panel, .model-list-panel {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: #fff;
  box-shadow: var(--app-card-shadow);
}
.model-page-hero { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 18px; }
.eyebrow { margin: 0 0 4px; color: var(--app-primary-active); font-size: 12px; font-weight: 700; }
h1, h2, h3 { margin: 0; color: var(--app-ink); letter-spacing: 0; }
h1 { font-size: 26px; line-height: 1.25; }
h2 { font-size: 20px; line-height: 1.3; }
h3 { font-size: 15px; }
.model-page-hero p:last-child, .list-head p, .detail-main p { margin: 7px 0 0; color: var(--app-ink-muted); font-size: 14px; line-height: 1.6; }
.hero-actions, .detail-actions, .subnav-row, .list-actions, .empty-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; user-select: none; }
.hero-actions { justify-content: flex-end; }
.status-band { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border: 1px solid var(--app-border); border-radius: var(--app-radius-sm); background: #fff; }
.status-item { min-width: 0; display: grid; grid-template-columns: 22px 1fr auto; align-items: center; gap: 8px; padding: 12px 14px; border-right: 1px solid var(--app-border-soft); }
.status-item:last-child { border-right: 0; }
.status-item .el-icon { color: var(--app-primary); }
.status-item span { color: var(--app-ink-muted); font-size: 12px; }
.status-item strong { color: var(--app-ink); font-size: 14px; overflow-wrap: anywhere; }
.model-center-layout { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 16px; align-items: start; }
.filter-panel { position: sticky; top: 76px; display: grid; gap: 16px; padding: 16px; }
.filter-title { color: var(--app-ink); font-size: 16px; font-weight: 700; }
.filter-group { display: grid; gap: 8px; }
.filter-group > span { color: var(--app-ink-muted); font-size: 13px; font-weight: 600; }
.filter-group :deep(.el-radio-group) { display: flex; flex-wrap: wrap; gap: 6px; }
.filter-group :deep(.el-radio-button__inner) { border-radius: var(--app-radius-sm) !important; border-left: 1px solid var(--app-border) !important; font-size: 12px; }
.model-list-panel { min-width: 0; padding: 16px; }
.list-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.model-card-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.model-card { min-width: 0; display: grid; gap: 12px; padding: 16px; border: 1px solid var(--app-border); border-radius: var(--app-radius-md); background: #fff; color: inherit; text-align: left; cursor: pointer; transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease; }
.model-card:hover { border-color: #bfdbfe; box-shadow: 0 10px 22px rgba(37, 99, 235, 0.09); transform: translateY(-1px); }
.model-card:focus-visible { outline: 3px solid var(--app-primary-light); outline-offset: 2px; }
.model-card-top { display: grid; grid-template-columns: 48px minmax(0, 1fr) auto; align-items: center; gap: 12px; }
.model-avatar { display: grid; place-items: center; width: 82px; height: 82px; border-radius: var(--app-radius-md); background: linear-gradient(180deg, #f8fbff, #e7f0ff); color: var(--app-primary-active); border: 1px solid #dbeafe; }
.model-avatar.small { width: 48px; height: 48px; }
.model-avatar .el-icon { font-size: 30px; }
.model-card-title { min-width: 0; display: grid; gap: 3px; }
.model-card-title strong { overflow: hidden; color: var(--app-ink); font-size: 16px; text-overflow: ellipsis; white-space: nowrap; }
.model-card-title span, .model-card-foot span, .detail-meta span { color: var(--app-ink-muted); font-size: 12px; overflow-wrap: anywhere; }
.model-card p { display: -webkit-box; min-height: 44px; margin: 0; overflow: hidden; color: var(--app-ink-body); font-size: 13px; line-height: 1.65; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.author-line { margin-top: 8px; color: var(--app-ink-body); font-size: 13px; line-height: 1.45; overflow-wrap: anywhere; }
.author-line.compact { margin-top: -4px; font-size: 12px; }
.model-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.model-card-foot { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding-top: 10px; border-top: 1px solid var(--app-border-soft); }
.empty-models { min-height: 320px; display: grid; place-items: center; align-content: center; gap: 8px; color: var(--app-ink-muted); text-align: center; }
.empty-models .el-icon { color: var(--app-primary); font-size: 42px; }
.empty-models strong { color: var(--app-ink); font-size: 16px; }
.detail-banner { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 18px; align-items: center; padding: 18px; background: linear-gradient(90deg, #ffffff 0%, #f4f8ff 100%); }
.detail-main { min-width: 0; }
.detail-title-row, .detail-meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.detail-meta { margin-top: 12px; }
.detail-meta span { padding-right: 10px; border-right: 1px solid var(--app-border-soft); }
.detail-meta span:last-child { border-right: 0; }
.detail-panel { min-width: 0; padding: 0 16px 18px; }
.detail-tabs :deep(.el-tabs__header) { margin-bottom: 18px; user-select: none; }
.detail-tabs :deep(.el-tabs__nav), .detail-tabs :deep(.el-tabs__item) { user-select: none; }
.summary-panel { display: grid; gap: 14px; max-width: 980px; }
.summary-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.summary-head p { margin: 4px 0 0; color: var(--app-ink-muted); font-size: 12px; }
.summary-overview { margin: 0; color: var(--app-ink-body); font-size: 14px; line-height: 1.75; }
.summary-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.summary-grid section { padding: 16px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-md); background: #f8fbff; }
.summary-grid h4 { margin: 0 0 10px; color: var(--app-ink); font-size: 14px; }
.summary-grid ul { margin: 0; padding-left: 18px; display: grid; gap: 8px; color: var(--app-ink-body); font-size: 13px; line-height: 1.6; }
.docs-layout, .governance-layout { display: grid; gap: 16px; }
.docs-layout section h3, .history-panel h3 { margin-bottom: 10px; }
.api-note { display: flex; align-items: center; gap: 10px; padding: 12px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-sm); background: #f8fbff; color: var(--app-ink-muted); font-size: 13px; }
.history-panel { padding-top: 16px; border-top: 1px solid var(--app-border-soft); }
@media (max-width: 1180px) {
  .model-card-grid, .summary-grid { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .model-page-hero, .list-head, .detail-banner { grid-template-columns: 1fr; flex-direction: column; align-items: stretch; }
  .hero-actions { justify-content: flex-start; }
  .status-band { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .status-item:nth-child(2) { border-right: 0; }
  .status-item:nth-child(-n+2) { border-bottom: 1px solid var(--app-border-soft); }
  .model-center-layout { grid-template-columns: 1fr; }
  .filter-panel { position: static; }
}
@media (max-width: 560px) {
  .status-band { grid-template-columns: 1fr; }
  .status-item { border-right: 0; border-bottom: 1px solid var(--app-border-soft); }
  .status-item:last-child { border-bottom: 0; }
  .model-card-top { grid-template-columns: 42px minmax(0, 1fr); }
  .model-card-top .el-tag { grid-column: 1 / -1; justify-self: start; }
}
</style>
