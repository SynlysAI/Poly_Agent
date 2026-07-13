<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  DataAnalysis, Files, FolderOpened, Refresh, Search, TrendCharts, View, Warning,
} from '@element-plus/icons-vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent, LegendComponent, TitleComponent, TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

import {
  getApiErrorMessage,
  getDataCatalogOverview,
  getDataCatalogRelationships,
  getDataCatalogCollectionRecord,
  listDataCatalogCollectionRecords,
  listDataCatalogDatasets,
  listDataCatalogMongoCollections,
} from '../api/polyAgentApi'
import { authState } from '../auth/authState'

use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  CanvasRenderer,
])

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const recordsLoading = ref(false)
const detailLoading = ref(false)
const activeTab = ref(['analysis', 'mongo', 'relations'].includes(String(route.query.tab)) ? String(route.query.tab) : 'analysis')
const overview = ref(null)
const relationships = ref({ nodes: [], edges: [], notes: [] })
const datasets = ref([])
const mongoCollections = ref([])
const legacyObjects = ref([])
const materialAnalysisRecords = ref([])
const computationAnalysisRecords = ref([])
const artifactAnalysisRecords = ref([])
const selectedDataset = ref(null)
const datasetDrawerVisible = ref(false)
const selectedCollectionName = ref('')
const collectionRecords = ref([])
const collectionTotal = ref(0)
const selectedRecord = ref(null)
const recordDrawerVisible = ref(false)

const recordFilters = reactive({
  page: Number(route.query.page || 1),
  page_size: 20,
  keyword: String(route.query.keyword || ''),
})

const canDrilldownRecords = computed(() => !authState.authEnabled || authState.role === 'admin')
const sourceReadyCount = computed(() => (overview.value?.sources || []).filter((item) => item.status === 'ready').length)
const sourceTotalCount = computed(() => (overview.value?.sources || []).length)
const selectedCollection = computed(() => mongoCollections.value.find((item) => collectionIdentity(item) === selectedCollectionName.value) || null)
const materialCollection = computed(() => mongoCollections.value.find((item) => collectionIdentity(item) === 'ai4ms.Poly_Agent') || null)
const computationRunCollection = computed(() => mongoCollections.value.find((item) => collectionIdentity(item) === 'computation_runs') || null)
const computationArtifactCollection = computed(() => mongoCollections.value.find((item) => collectionIdentity(item) === 'computation_artifacts') || null)

const collectionGroups = computed(() => {
  const grouped = {}
  for (const item of mongoCollections.value) {
    if (!grouped[item.group]) grouped[item.group] = []
    grouped[item.group].push(item)
  }
  return grouped
})

const keyMetrics = computed(() => [
  {
    key: 'materials',
    label: '材料记录',
    value: formatNumber(materialCollection.value?.count || 0),
    meta: materialCollection.value ? statusLabel(materialCollection.value.status) : '未配置',
    icon: DataAnalysis,
  },
  {
    key: 'runs',
    label: '计算任务',
    value: formatNumber(computationRunCollection.value?.count || 0),
    meta: computationRunCollection.value ? statusLabel(computationRunCollection.value.status) : '未配置',
    icon: Files,
  },
  {
    key: 'artifacts',
    label: '计算产物',
    value: formatNumber(computationArtifactCollection.value?.count || 0),
    meta: computationArtifactCollection.value ? statusLabel(computationArtifactCollection.value.status) : '未配置',
    icon: FolderOpened,
  },
  {
    key: 'health',
    label: '数据源健康',
    value: sourceTotalCount.value ? `${sourceReadyCount.value}/${sourceTotalCount.value}` : '-',
    meta: statusLabel(overview.value?.status),
    icon: TrendCharts,
  },
])

const collectionGroupColors = {
  材料数据资产: '#3b82f6',
  计算任务与产物: '#16a34a',
  研发流程与算法: '#d97706',
  优化闭环: '#0891b2',
  报告产物: '#64748b',
}

const collectionVolumeRows = computed(() => mongoCollections.value
  .map((item) => {
    const rawCount = Number(item.count || 0)
    return {
      name: item.display_name,
      collectionKey: collectionIdentity(item),
      group: item.group || '其他',
      status: item.status,
      rawCount,
      scaledValue: scaleCount(rawCount),
      color: collectionGroupColors[item.group] || '#64748b',
    }
  })
  .sort((a, b) => b.rawCount - a.rawCount || a.name.localeCompare(b.name)))

const collectionVolumeOption = computed(() => ({
  grid: { left: 136, right: 104, top: 18, bottom: 36 },
  tooltip: {
    trigger: 'item',
    formatter: (item) => {
      const row = item.data
      return [
        row.name,
        `集合：${row.collectionKey}`,
        `分组：${row.group}`,
        `状态：${statusLabel(row.status)}`,
        `真实记录量：${formatNumber(row.rawCount)} 条`,
      ].join('<br/>')
    },
  },
  xAxis: {
    type: 'value',
    min: 0,
    splitNumber: 4,
    axisLabel: {
      color: '#64748b',
      formatter: (value) => formatScaleTick(value),
    },
    splitLine: { lineStyle: { color: '#e2e8f0' } },
  },
  yAxis: {
    type: 'category',
    inverse: true,
    data: collectionVolumeRows.value.map((row) => row.name),
    axisLabel: { color: '#334155', width: 124, overflow: 'truncate' },
    axisTick: { show: false },
  },
  series: [{
    type: 'bar',
    data: collectionVolumeRows.value.map((row) => ({
      ...row,
      value: row.scaledValue,
      itemStyle: { color: row.color, borderRadius: [0, 4, 4, 0] },
    })),
    barWidth: 16,
    barMinWidth: 4,
    label: {
      show: true,
      position: 'right',
      color: '#0f172a',
      fontSize: 12,
      formatter: (item) => formatNumber(item.data.rawCount),
    },
  }],
}))

const relationshipRows = computed(() => {
  const nodeMap = Object.fromEntries((relationships.value.nodes || []).map((item) => [item.node_id, item]))
  const maxLinkedCount = Math.max(
    1,
    ...(relationships.value.edges || []).map((item) => Number(item.linked_count || 0)),
  )
  return ((relationships.value.edges || [])
    .filter(item => item.linked_count > 0)
    .map((item) => {
      const sourceNode = nodeMap[item.source] || {}
      const targetNode = nodeMap[item.target] || {}
      const linkedCount = Number(item.linked_count || 0)
      return {
        key: `${item.source}-${item.target}`,
        sourceLabel: sourceNode.label || item.source,
        targetLabel: targetNode.label || item.target,
        sourceRecordCount: Number(sourceNode.record_count || 0),
        targetRecordCount: Number(targetNode.record_count || 0),
        linkedCount,
        coveragePercent: Math.round(Number(item.target_coverage || 0) * 1000) / 10,
        barWidth: Math.max(8, Math.round((linkedCount / maxLinkedCount) * 100)),
        sourceField: item.source_field,
        targetField: item.target_field,
      }
    })
    .sort((a, b) => b.linkedCount - a.linkedCount || a.sourceLabel.localeCompare(b.sourceLabel)))
})

const materialDatasetOption = computed(() => {
  const counts = countBy(materialAnalysisRecords.value.map((item) => ({ value: item.preview_fields?.dataset || 'unknown' })), 'value')
  return horizontalBarOption(counts, '#3b82f6')
})

const materialPropertyOption = computed(() => {
  const counts = {}
  for (const item of materialAnalysisRecords.value) {
    const groups = String(item.preview_fields?.property_groups || '').split(',').map((value) => value.trim()).filter(Boolean)
    for (const group of groups) counts[group] = (counts[group] || 0) + 1
  }
  return horizontalBarOption(counts, '#16a34a')
})

const materialTrendOption = computed(() => trendOption(materialAnalysisRecords.value, '#0891b2'))

const computationWorkflowOption = computed(() => {
  const counts = countBy(computationAnalysisRecords.value.map((item) => ({ value: item.preview_fields?.workflow_type || 'unknown' })), 'value')
  return horizontalBarOption(counts, '#d97706')
})

const computationStatusOption = computed(() => {
  const counts = countBy(computationAnalysisRecords.value, 'status')
  return pieOption(counts)
})

const artifactTypeOption = computed(() => {
  const counts = countBy(artifactAnalysisRecords.value.map((item) => ({ value: item.preview_fields?.artifact_type || 'unknown' })), 'value')
  return horizontalBarOption(counts, '#7c3aed')
})

const datasetCoverageOption = computed(() => {
  const fields = selectedDataset.value?.field_summaries || []
  return {
    color: ['#3b82f6'],
    grid: { left: 108, right: 24, top: 16, bottom: 28 },
    tooltip: { trigger: 'axis', formatter: (items) => `${items[0].name}<br/>覆盖率 ${items[0].value}%` },
    xAxis: { type: 'value', max: 100, axisLabel: { formatter: '{value}%' } },
    yAxis: {
      type: 'category',
      data: fields.map((field) => field.label),
      axisLabel: { color: '#64748b', width: 96, overflow: 'truncate' },
    },
    series: [{
      type: 'bar',
      data: fields.map((field) => coveragePercent(field)),
      barWidth: 14,
      itemStyle: { borderRadius: [0, 4, 4, 0] },
    }],
  }
})

const recordStatusOption = computed(() => {
  const counts = countBy(collectionRecords.value, 'status')
  return {
    color: ['#16a34a', '#d97706', '#dc2626', '#64748b'],
    tooltip: { trigger: 'item' },
    series: [{
      type: 'pie',
      radius: ['52%', '76%'],
      label: { formatter: '{b} {c}' },
      data: Object.entries(counts).map(([name, value]) => ({ name: name || 'unknown', value })),
    }],
  }
})

const recordTypeOption = computed(() => {
  const field = detectDistributionField(collectionRecords.value)
  const counts = field ? countBy(collectionRecords.value.map((item) => ({ value: item.preview_fields?.[field] || item[field] })), 'value') : {}
  return {
    color: ['#3b82f6'],
    grid: { left: 92, right: 18, top: 18, bottom: 28 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'value' },
    yAxis: { type: 'category', data: Object.keys(counts), axisLabel: { color: '#64748b', width: 84, overflow: 'truncate' } },
    series: [{ type: 'bar', data: Object.values(counts), barWidth: 14, itemStyle: { borderRadius: [0, 4, 4, 0] } }],
  }
})

const recordTrendOption = computed(() => {
  const counts = {}
  for (const item of collectionRecords.value) {
    const day = String(item.created_at || '').slice(0, 10)
    if (!day) continue
    counts[day] = (counts[day] || 0) + 1
  }
  return {
    color: ['#0891b2'],
    grid: { left: 36, right: 18, top: 18, bottom: 32 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: Object.keys(counts), axisLabel: { color: '#64748b' } },
    yAxis: { type: 'value', minInterval: 1, axisLabel: { color: '#64748b' } },
    series: [{ type: 'line', data: Object.values(counts), smooth: true, symbolSize: 7, lineStyle: { width: 3 }, areaStyle: { opacity: 0.12 } }],
  }
})

function formatNumber(value) {
  if (value === null || value === undefined || value === '') return '-'
  return Number(value).toLocaleString()
}

function scaleCount(value) {
  return Math.log10(Number(value || 0) + 1)
}

function formatScaleTick(value) {
  const rawValue = Math.max(0, Math.round((10 ** Number(value || 0)) - 1))
  return rawValue ? `~${formatNumber(rawValue)}` : '0'
}

function formatBytes(value) {
  if (!value) return '-'
  const units = ['B', 'KB', 'MB', 'GB']
  let size = Number(value)
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex += 1
  }
  return `${size.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function coveragePercent(field) {
  if (!field.total_count) return 0
  return Math.round((Number(field.non_empty_count || 0) / Number(field.total_count)) * 100)
}

function statusTag(status) {
  const map = { ready: 'success', degraded: 'warning', not_configured: 'info', completed: 'success', running: 'warning', failed: 'danger', queued: 'info', cancelled: 'info', active: 'success', disabled: 'danger' }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = { ready: '正常', degraded: '部分可用', not_configured: '未配置', completed: '完成', running: '运行中', failed: '失败', queued: '排队', cancelled: '取消', active: '正常', disabled: '禁用' }
  return map[status] || status || '-'
}

function objectStatusLabel(row) {
  if (row.exists) return '规范路径已就绪'
  if (row.legacy_exists) return '旧路径待迁移'
  return '未找到'
}

function objectStatusType(row) {
  if (row.exists) return 'success'
  if (row.legacy_exists) return 'warning'
  return 'info'
}

function countBy(items, field) {
  const counts = {}
  for (const item of items) {
    const value = item?.[field] || 'unknown'
    counts[value] = (counts[value] || 0) + 1
  }
  return counts
}

function collectionIdentity(item) {
  return item?.collection_key || item?.collection_name || ''
}

function groupCollectionCount(group) {
  return mongoCollections.value
    .filter((item) => item.group === group)
    .reduce((sum, item) => sum + Number(item.count || 0), 0)
}

function horizontalBarOption(counts, color) {
  const entries = Object.entries(counts)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 8)
  return {
    color: [color],
    grid: { left: 104, right: 18, top: 18, bottom: 28 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'value', minInterval: 1, axisLabel: { color: '#64748b' } },
    yAxis: {
      type: 'category',
      data: entries.map(([name]) => name),
      axisLabel: { color: '#64748b', width: 92, overflow: 'truncate' },
    },
    series: [{ type: 'bar', data: entries.map(([, value]) => value), barWidth: 14, itemStyle: { borderRadius: [0, 4, 4, 0] } }],
  }
}

function pieOption(counts) {
  return {
    color: ['#16a34a', '#d97706', '#dc2626', '#64748b', '#3b82f6'],
    tooltip: { trigger: 'item' },
    series: [{
      type: 'pie',
      radius: ['52%', '76%'],
      label: { formatter: '{b} {c}' },
      data: Object.entries(counts).map(([name, value]) => ({ name: statusLabel(name), value })),
    }],
  }
}

function trendOption(items, color) {
  const counts = {}
  for (const item of items) {
    const day = String(item.created_at || '').slice(0, 10)
    if (!day) continue
    counts[day] = (counts[day] || 0) + 1
  }
  return {
    color: [color],
    grid: { left: 36, right: 18, top: 18, bottom: 32 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: Object.keys(counts), axisLabel: { color: '#64748b' } },
    yAxis: { type: 'value', minInterval: 1, axisLabel: { color: '#64748b' } },
    series: [{ type: 'line', data: Object.values(counts), smooth: true, symbolSize: 7, lineStyle: { width: 3 }, areaStyle: { opacity: 0.12 } }],
  }
}

function detectDistributionField(items) {
  const candidates = ['workflow_type', 'engine', 'artifact_type', 'event_type', 'planner_type', 'trigger_source']
  return candidates.find((field) => items.some((item) => item.preview_fields?.[field] || item[field]))
}

function compactJson(value) {
  if (!value) return '{}'
  return JSON.stringify(value, null, 2)
}

function previewFieldText(fields) {
  const entries = Object.entries(fields || {})
  if (!entries.length) return '-'
  return entries.map(([key, value]) => `${key}: ${typeof value === 'object' ? JSON.stringify(value) : value}`).join(' · ')
}

function syncRouteQuery(extra = {}) {
  const query = {
    ...route.query,
    tab: activeTab.value,
    ...extra,
  }
  Object.keys(query).forEach((key) => {
    if (query[key] === '' || query[key] === null || query[key] === undefined) delete query[key]
  })
  router.replace({ path: '/database/data-catalog', query })
}

async function loadDataCatalog() {
  loading.value = true
  try {
    const [overviewData, datasetData, mongoData, relationshipData] = await Promise.all([
      getDataCatalogOverview(),
      listDataCatalogDatasets(),
      listDataCatalogMongoCollections(),
      getDataCatalogRelationships(),
    ])
    overview.value = overviewData
    datasets.value = datasetData.items || []
    legacyObjects.value = datasetData.legacy_objects || overviewData.legacy_objects || []
    mongoCollections.value = mongoData.items || []
    relationships.value = relationshipData
    await loadAnalysisSamples()
    if (selectedCollectionName.value) await loadCollectionRecords()
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function loadAnalysisSamples() {
  if (!canDrilldownRecords.value) {
    materialAnalysisRecords.value = []
    computationAnalysisRecords.value = []
    artifactAnalysisRecords.value = []
    return
  }
  const requests = [
    listDataCatalogCollectionRecords('ai4ms.Poly_Agent', { page: 1, page_size: 100 }),
    listDataCatalogCollectionRecords('computation_runs', { page: 1, page_size: 100 }),
    listDataCatalogCollectionRecords('computation_artifacts', { page: 1, page_size: 100 }),
  ]
  const [materials, computations, artifacts] = await Promise.allSettled(requests)
  materialAnalysisRecords.value = materials.status === 'fulfilled' ? (materials.value.items || []) : []
  computationAnalysisRecords.value = computations.status === 'fulfilled' ? (computations.value.items || []) : []
  artifactAnalysisRecords.value = artifacts.status === 'fulfilled' ? (artifacts.value.items || []) : []
}

function openDataset(dataset) {
  selectedDataset.value = dataset
  datasetDrawerVisible.value = true
}

async function openCollection(collection) {
  if (!canDrilldownRecords.value) {
    ElMessage.warning('集合记录下钻仅管理员可用')
    return
  }
  activeTab.value = 'mongo'
  selectedCollectionName.value = collectionIdentity(collection)
  recordFilters.page = 1
  syncRouteQuery({ collection: selectedCollectionName.value, page: 1 })
  await loadCollectionRecords()
}

async function loadCollectionRecords() {
  if (!selectedCollectionName.value || !canDrilldownRecords.value) return
  recordsLoading.value = true
  try {
    const data = await listDataCatalogCollectionRecords(selectedCollectionName.value, {
      page: recordFilters.page,
      page_size: recordFilters.page_size,
      keyword: recordFilters.keyword || undefined,
    })
    collectionRecords.value = data.items || []
    collectionTotal.value = data.total || 0
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    recordsLoading.value = false
  }
}

async function handleRecordSearch() {
  recordFilters.page = 1
  syncRouteQuery({ collection: selectedCollectionName.value, keyword: recordFilters.keyword, page: 1 })
  await loadCollectionRecords()
}

async function handleRecordPageChange(page) {
  recordFilters.page = page
  syncRouteQuery({ collection: selectedCollectionName.value, keyword: recordFilters.keyword, page })
  await loadCollectionRecords()
}

async function openRecord(row) {
  selectedRecord.value = null
  recordDrawerVisible.value = true
  syncRouteQuery({ collection: selectedCollectionName.value, record: row.record_id, page: recordFilters.page, keyword: recordFilters.keyword })
  await loadRecordDetail(row.record_id)
}

async function loadRecordDetail(recordId) {
  if (!selectedCollectionName.value || !recordId) return
  detailLoading.value = true
  try {
    selectedRecord.value = await getDataCatalogCollectionRecord(selectedCollectionName.value, recordId)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    detailLoading.value = false
  }
}

watch(activeTab, (value) => {
  syncRouteQuery({ tab: value })
})

watch(recordDrawerVisible, (visible) => {
  if (!visible) {
    selectedRecord.value = null
    const nextQuery = { ...route.query }
    delete nextQuery.record
    router.replace({ path: '/database/data-catalog', query: nextQuery })
  }
})

onMounted(async () => {
  selectedCollectionName.value = String(route.query.collection || '')
  await loadDataCatalog()
  if (selectedCollectionName.value && canDrilldownRecords.value) {
    activeTab.value = 'mongo'
    await loadCollectionRecords()
    if (route.query.record) {
      await nextTick()
      recordDrawerVisible.value = true
      await loadRecordDetail(String(route.query.record))
    }
  }
})
</script>

<template>
  <div class="data-catalog-page" v-loading="loading">
    <header class="catalog-header">
      <div>
        <h1>数据管理</h1>
        <p>材料数据资产、计算结果和 Mongo 结构化索引的统一视图。</p>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadDataCatalog">刷新</el-button>
    </header>

    <section class="metric-grid" aria-label="数据管理关键指标">
      <article v-for="metric in keyMetrics" :key="metric.key" class="metric-panel">
        <el-icon><component :is="metric.icon" /></el-icon>
        <div>
          <span>{{ metric.label }}</span>
          <strong>{{ metric.value }}</strong>
          <small>{{ metric.meta }}</small>
        </div>
      </article>
    </section>

    <el-collapse v-if="legacyObjects.length" class="legacy-collapse">
      <el-collapse-item name="legacy">
        <template #title>
          <span class="legacy-title"><el-icon><Warning /></el-icon>检测到 {{ legacyObjects.length }} 个旧路径残留</span>
        </template>
        <div class="legacy-list">
          <code v-for="item in legacyObjects" :key="item">{{ item }}</code>
        </div>
      </el-collapse-item>
    </el-collapse>

    <el-tabs v-model="activeTab" class="catalog-tabs">
      <el-tab-pane label="数据分析" name="analysis" lazy>
        <div class="analysis-layout">
          <section class="catalog-section analysis-main">
            <div class="section-heading">
              <h2>材料数据分级</h2>
              <span>近 {{ materialAnalysisRecords.length }} 条样本</span>
            </div>
            <div v-if="canDrilldownRecords && materialAnalysisRecords.length" class="analysis-grid">
              <div class="visual-panel">
                <h3>数据集来源</h3>
                <v-chart class="record-chart" :option="materialDatasetOption" autoresize />
              </div>
              <div class="visual-panel">
                <h3>物性类别覆盖</h3>
                <v-chart class="record-chart" :option="materialPropertyOption" autoresize />
              </div>
              <div class="visual-panel">
                <h3>导入趋势</h3>
                <v-chart class="record-chart" :option="materialTrendOption" autoresize />
              </div>
            </div>
            <el-empty v-else description="暂无可分析的材料样本或当前账号无下钻权限" />
          </section>

          <section class="catalog-section analysis-main">
            <div class="section-heading">
              <h2>计算数据分析</h2>
              <span>近 {{ computationAnalysisRecords.length }} 条任务样本</span>
            </div>
            <div v-if="canDrilldownRecords && (computationAnalysisRecords.length || artifactAnalysisRecords.length)" class="analysis-grid">
              <div class="visual-panel">
                <h3>任务状态</h3>
                <v-chart class="record-chart" :option="computationStatusOption" autoresize />
              </div>
              <div class="visual-panel">
                <h3>Workflow 分布</h3>
                <v-chart class="record-chart" :option="computationWorkflowOption" autoresize />
              </div>
              <div class="visual-panel">
                <h3>产物类型</h3>
                <v-chart class="record-chart" :option="artifactTypeOption" autoresize />
              </div>
            </div>
            <el-empty v-else description="暂无可分析的计算样本或当前账号无下钻权限" />
          </section>
        </div>
      </el-tab-pane>

      <el-tab-pane label="数据表" name="mongo" lazy>
        <div class="mongo-layout">
          <section class="catalog-section collection-browser">
            <div class="section-heading">
              <h2>结构化数据表</h2>
              <span>{{ mongoCollections.length }} 张表</span>
            </div>
            <div class="collection-groups">
              <div v-for="(items, group) in collectionGroups" :key="group" class="collection-group">
                <h3>{{ group }}</h3>
                <button
                  v-for="item in items"
                  :key="collectionIdentity(item)"
                  type="button"
                  class="collection-row"
                  :class="{ active: selectedCollectionName === collectionIdentity(item) }"
                  @click="openCollection(item)"
                >
                  <span>
                    <strong>{{ item.display_name }}</strong>
                    <code>{{ collectionIdentity(item) }}</code>
                  </span>
                  <span class="collection-row-right">
                    <el-tag size="small" :type="statusTag(item.status)">{{ statusLabel(item.status) }}</el-tag>
                    <small>{{ formatNumber(item.count || 0) }}</small>
                  </span>
                </button>
              </div>
            </div>
          </section>

          <section class="catalog-section record-panel">
            <template v-if="selectedCollection">
              <div class="record-header">
                <div>
                  <h2>{{ selectedCollection.display_name }}</h2>
                  <p>{{ selectedCollection.description }}</p>
                </div>
                <el-tag :type="statusTag(selectedCollection.status)">{{ collectionIdentity(selectedCollection) }}</el-tag>
              </div>

              <div v-if="canDrilldownRecords" class="record-tools">
                <el-input v-model="recordFilters.keyword" clearable placeholder="搜索主键、状态、类型或文本" @keyup.enter="handleRecordSearch">
                  <template #prefix><el-icon><Search /></el-icon></template>
                </el-input>
                <el-button @click="handleRecordSearch">查询</el-button>
              </div>

              <el-alert
                v-else
                type="info"
                :closable="false"
                title="集合记录下钻仅管理员可用"
                description="当前账号可以查看集合规模和说明，原始记录详情需要管理员权限。"
              />

              <div v-if="canDrilldownRecords" class="record-visual-grid">
                <div class="visual-panel">
                  <h3>状态分布</h3>
                  <v-chart class="record-chart" :option="recordStatusOption" autoresize />
                </div>
                <div class="visual-panel">
                  <h3>类型分布</h3>
                  <v-chart class="record-chart" :option="recordTypeOption" autoresize />
                </div>
                <div class="visual-panel">
                  <h3>创建趋势</h3>
                  <v-chart class="record-chart" :option="recordTrendOption" autoresize />
                </div>
              </div>

              <el-table v-if="canDrilldownRecords" :data="collectionRecords" v-loading="recordsLoading" stripe class="record-table">
                <el-table-column prop="record_id" label="Record ID" min-width="170" />
                <el-table-column prop="title" label="标题" min-width="180" />
                <el-table-column label="状态" width="110">
                  <template #default="{ row }">
                    <el-tag v-if="row.status" size="small" :type="statusTag(row.status)">{{ statusLabel(row.status) }}</el-tag>
                    <span v-else>-</span>
                  </template>
                </el-table-column>
                <el-table-column label="摘要字段" min-width="260">
                  <template #default="{ row }">{{ previewFieldText(row.preview_fields) }}</template>
                </el-table-column>
                <el-table-column label="创建时间" min-width="170">
                  <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
                </el-table-column>
                <el-table-column label="操作" width="96" fixed="right">
                  <template #default="{ row }">
                    <el-button text type="primary" size="small" :icon="View" @click="openRecord(row)">查看</el-button>
                  </template>
                </el-table-column>
              </el-table>

              <el-pagination
                v-if="canDrilldownRecords"
                class="record-pagination"
                background
                layout="prev, pager, next, total"
                :current-page="recordFilters.page"
                :page-size="recordFilters.page_size"
                :total="collectionTotal"
                @current-change="handleRecordPageChange"
              />
            </template>
            <div v-else class="empty-state">
              <el-icon><FolderOpened /></el-icon>
              <h2>选择一张数据表</h2>
              <p>从左侧集合列表进入记录分页和单条详情。</p>
            </div>
          </section>
        </div>
      </el-tab-pane>

      <el-tab-pane label="数据关系" name="relations" lazy>
        <div class="relation-grid">
          <section class="catalog-section relation-main">
            <div class="section-heading">
              <h2>集合记录量（条）</h2>
            </div>
            <v-chart class="collection-volume-chart" :option="collectionVolumeOption" autoresize />
            <p class="relationship-note">柱长为对数尺度，数值为真实记录量。</p>
          </section>
          <section class="catalog-section">
            <div class="section-heading">
              <h2>已验证跨集合关联（条）</h2>
            </div>
            <div v-if="relationshipRows.length" class="relationship-list">
              <div v-for="row in relationshipRows" :key="row.key" class="relationship-row">
                <div class="relationship-endpoint">
                  <span>来源</span>
                  <strong>{{ row.sourceLabel }}</strong>
                  <small>{{ formatNumber(row.sourceRecordCount) }} 条记录</small>
                </div>
                <div class="relationship-metric">
                  <div class="relationship-count">
                    <strong>{{ formatNumber(row.linkedCount) }}</strong>
                    <span>条已验证关联</span>
                  </div>
                  <div class="relationship-bar" aria-hidden="true">
                    <span :style="{ width: `${row.barWidth}%` }"></span>
                  </div>
                  <code>{{ row.sourceField }} -> {{ row.targetField }}</code>
                </div>
                <div class="relationship-endpoint target">
                  <span>目标</span>
                  <strong>{{ row.targetLabel }}</strong>
                  <small>覆盖 {{ row.coveragePercent }}% · {{ formatNumber(row.targetRecordCount) }} 条记录</small>
                </div>
              </div>
            </div>
            <el-empty v-else description="暂无可验证的跨集合关联" />
            <p class="relationship-note">{{ relationships.notes?.[0] || '仅展示数据库中可验证的外键关系。' }}</p>
          </section>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-drawer v-model="datasetDrawerVisible" size="56%" class="catalog-drawer" title="数据集详情">
      <template v-if="selectedDataset">
        <div class="drawer-heading">
          <div>
            <h2>{{ selectedDataset.display_name }}</h2>
            <p>{{ selectedDataset.description }}</p>
          </div>
          <el-tag type="success" effect="plain">{{ selectedDataset.confidence_label }}</el-tag>
        </div>
        <div class="drawer-stat-row">
          <span>{{ formatNumber(selectedDataset.row_count) }} 行</span>
          <span>{{ formatNumber(selectedDataset.column_count) }} 列</span>
          <code>{{ selectedDataset.storage_prefix }}</code>
        </div>

        <h3 class="drawer-section-title">字段覆盖率</h3>
        <v-chart class="coverage-chart" :option="datasetCoverageOption" autoresize />
        <el-table :data="selectedDataset.field_summaries" size="small" border>
          <el-table-column prop="label" label="字段" min-width="150" />
          <el-table-column prop="canonical_name" label="Canonical" min-width="160">
            <template #default="{ row }"><code>{{ row.canonical_name }}</code></template>
          </el-table-column>
          <el-table-column label="覆盖率" width="130">
            <template #default="{ row }">{{ coveragePercent(row) }}%</template>
          </el-table-column>
          <el-table-column prop="example" label="样例" min-width="180" />
        </el-table>

        <h3 class="drawer-section-title">对象状态</h3>
        <el-table :data="selectedDataset.objects" size="small" border>
          <el-table-column prop="role" label="角色" width="130" />
          <el-table-column label="规范对象路径" min-width="320">
            <template #default="{ row }"><code>{{ row.object_key }}</code></template>
          </el-table-column>
          <el-table-column label="状态" width="140">
            <template #default="{ row }">
              <el-tag size="small" :type="objectStatusType(row)">{{ objectStatusLabel(row) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="大小" width="110">
            <template #default="{ row }">{{ formatBytes(row.size_bytes) }}</template>
          </el-table-column>
        </el-table>
      </template>
    </el-drawer>

    <el-drawer v-model="recordDrawerVisible" size="58%" class="catalog-drawer" title="记录详情">
      <div v-loading="detailLoading" class="record-detail">
        <template v-if="selectedRecord">
          <div class="drawer-heading">
            <div>
              <h2>{{ selectedRecord.title }}</h2>
              <p>{{ selectedRecord.collection_name }} · {{ selectedRecord.record_id }}</p>
            </div>
            <el-tag v-if="selectedRecord.status" :type="statusTag(selectedRecord.status)">{{ statusLabel(selectedRecord.status) }}</el-tag>
          </div>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="Record ID">{{ selectedRecord.record_id }}</el-descriptions-item>
            <el-descriptions-item label="Primary Key">{{ compactJson(selectedRecord.primary_key) }}</el-descriptions-item>
            <el-descriptions-item label="Created">{{ formatDate(selectedRecord.created_at) }}</el-descriptions-item>
            <el-descriptions-item label="Updated">{{ formatDate(selectedRecord.updated_at) }}</el-descriptions-item>
          </el-descriptions>
          <h3 class="drawer-section-title">Document</h3>
          <pre class="json-block">{{ compactJson(selectedRecord.document) }}</pre>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.data-catalog-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: calc(100vh - 96px);
}

.catalog-header,
.section-heading,
.dataset-card-main,
.record-header,
.drawer-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.catalog-header h1,
.catalog-section h2,
.dataset-card h3,
.collection-group h3,
.drawer-heading h2,
.visual-panel h3,
.drawer-section-title {
  margin: 0;
  color: var(--app-ink);
  letter-spacing: 0;
}

.catalog-header h1 {
  font-size: 24px;
  line-height: 1.2;
}

.catalog-header p,
.dataset-card p,
.record-header p,
.drawer-heading p,
.empty-state p {
  margin: 6px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.metric-panel,
.catalog-section,
.dataset-card,
.visual-panel {
  border: 1px solid var(--app-card-border);
  border-radius: var(--app-radius-sm);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: var(--app-card-shadow);
}

.metric-panel {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 86px;
  padding: 14px;
}

.metric-panel .el-icon {
  width: 34px;
  height: 34px;
  border-radius: var(--app-radius-sm);
  color: var(--app-primary);
  background: var(--app-primary-light);
}

.metric-panel span,
.metric-panel small {
  display: block;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.metric-panel strong {
  display: block;
  margin: 3px 0;
  color: var(--app-ink);
  font-size: 22px;
  line-height: 1.1;
}

.legacy-collapse {
  border: 1px solid #f6d9a8;
  border-radius: var(--app-radius-sm);
  overflow: hidden;
}

.legacy-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #8a5a10;
  font-weight: 600;
}

.legacy-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.catalog-section {
  padding: 16px;
}

.section-heading {
  margin-bottom: 12px;
}

.section-heading h2,
.record-header h2 {
  font-size: 16px;
}

.section-heading span {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.asset-layout,
.analysis-layout,
.mongo-layout,
.relation-grid {
  display: grid;
  gap: 14px;
}

.asset-layout {
  grid-template-columns: minmax(0, 1fr) 360px;
}

.analysis-layout {
  grid-template-columns: 1fr;
}

.analysis-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.mongo-layout {
  grid-template-columns: 360px minmax(0, 1fr);
  align-items: start;
}

.relation-grid {
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 0.8fr);
}

.dataset-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.dataset-card {
  padding: 14px;
  box-shadow: none;
}

.dataset-card h3,
.collection-group h3 {
  font-size: 15px;
}

.dataset-card-main {
  align-items: flex-start;
}

.dataset-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;
}

.dataset-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.dataset-stats strong {
  display: block;
  color: var(--app-sidebar-from);
  font-size: 18px;
}

.collection-volume-chart {
  width: 100%;
  height: 420px;
}

.relationship-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 340px;
}

.relationship-row {
  display: grid;
  grid-template-columns: minmax(0, 0.95fr) minmax(132px, 1.1fr) minmax(0, 0.95fr);
  gap: 10px;
  align-items: center;
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
}

.relationship-endpoint,
.relationship-metric {
  min-width: 0;
}

.relationship-endpoint span,
.relationship-count span,
.relationship-endpoint small {
  display: block;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.relationship-endpoint strong {
  display: block;
  margin: 4px 0;
  color: var(--app-ink);
  font-size: 14px;
  line-height: 1.35;
}

.relationship-endpoint.target {
  text-align: right;
}

.relationship-metric {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.relationship-count {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 5px;
  white-space: nowrap;
}

.relationship-count strong {
  color: var(--app-primary);
  font-size: 18px;
  line-height: 1;
}

.relationship-bar {
  width: 100%;
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: #e2e8f0;
}

.relationship-bar span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--app-primary);
}

.relationship-metric code {
  color: var(--app-ink-muted);
  text-align: center;
}

.relationship-note {
  margin: 0 0 10px;
  color: var(--app-ink-muted);
  font-size: 12px;
  text-align: center;
}

.collection-browser {
  max-height: calc(100vh - 176px);
  overflow: auto;
}

.collection-groups {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.collection-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.collection-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  min-height: 58px;
  padding: 10px 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
  color: var(--app-ink);
  text-align: left;
  cursor: pointer;
}

.collection-row:hover,
.collection-row.active {
  border-color: #9fc2fb;
  background: #f5f9ff;
}

.collection-row strong,
.collection-row code {
  display: block;
}

.collection-row code,
code {
  font-family: var(--app-mono-font);
  color: #1e3a8a;
  font-size: 12px;
  word-break: break-all;
}

.collection-row-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.record-panel {
  min-height: 480px;
}

.record-tools {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}

.record-tools .el-input {
  max-width: 360px;
}

.record-visual-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin: 14px 0;
}

.visual-panel {
  padding: 12px;
  box-shadow: none;
}

.visual-panel h3 {
  font-size: 13px;
  margin-bottom: 6px;
}

.record-chart {
  width: 100%;
  height: 180px;
}

.record-table {
  width: 100%;
}

.record-pagination {
  justify-content: flex-end;
  margin-top: 14px;
}

.empty-state {
  min-height: 360px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 8px;
  color: var(--app-ink-muted);
  text-align: center;
}

.empty-state .el-icon {
  font-size: 36px;
  color: var(--app-primary);
}

.drawer-heading {
  margin-bottom: 14px;
}

.drawer-heading h2 {
  font-size: 18px;
}

.drawer-stat-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 16px;
  color: var(--app-ink-body);
  font-size: 13px;
}

.drawer-stat-row span,
.drawer-stat-row code {
  padding: 6px 8px;
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
}

.drawer-section-title {
  margin: 18px 0 10px;
  font-size: 14px;
}

.coverage-chart {
  width: 100%;
  height: 260px;
  margin-bottom: 12px;
}

.record-detail {
  min-height: 420px;
}

.json-block {
  max-height: 520px;
  overflow: auto;
  margin: 0;
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #0f172a;
  color: #dbeafe;
  font-family: var(--app-mono-font);
  font-size: 12px;
  line-height: 1.55;
}

@media (max-width: 1280px) {
  .asset-layout,
  .mongo-layout,
  .relation-grid {
    grid-template-columns: 1fr;
  }

  .dataset-grid,
  .analysis-grid,
  .record-visual-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .catalog-header,
  .record-header,
  .drawer-heading {
    flex-direction: column;
  }

  .metric-grid,
  .dataset-grid,
  .analysis-grid,
  .record-visual-grid {
    grid-template-columns: 1fr;
  }

  .record-tools {
    flex-direction: column;
  }

  .record-tools .el-input {
    max-width: none;
  }

  .relationship-row {
    grid-template-columns: 1fr;
  }

  .relationship-endpoint.target {
    text-align: left;
  }

  .relationship-count {
    justify-content: flex-start;
  }

  .relationship-metric code {
    text-align: left;
  }
}
</style>
