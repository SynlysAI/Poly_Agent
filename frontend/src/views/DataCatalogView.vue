<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowRight, Back, DataAnalysis, Files, FolderOpened, Refresh, Right, Search, TrendCharts, View, Warning,
} from '@element-plus/icons-vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, LineChart, PieChart, SankeyChart, ScatterChart } from 'echarts/charts'
import {
  GridComponent, LegendComponent, TitleComponent, TooltipComponent, VisualMapComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

import {
  getApiErrorMessage,
  getDataCatalogDatasetProfile,
  getDataCatalogDatasetVisualSamples,
  getDataCatalogOverview,
  getDataCatalogRelationships,
  getDataCatalogCollectionRecord,
  listDataCatalogDatasetRecords,
  listDataCatalogCollectionRecords,
  listDataCatalogDatasets,
  listDataCatalogMongoCollections,
} from '../api/polyAgentApi'
import AttributionBanner from '../components/attribution/AttributionBanner.vue'

use([
  BarChart,
  LineChart,
  PieChart,
  SankeyChart,
  ScatterChart,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
  CanvasRenderer,
])

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const recordsLoading = ref(false)
const detailLoading = ref(false)
const activeTab = ref(['datasets', 'mongo', 'relations'].includes(String(route.query.tab)) ? String(route.query.tab) : 'datasets')
const datasetGroupFilter = ref('all')
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
const datasetCoverageVisible = ref(false)
const selectedCollectionName = ref('')
const collectionRecords = ref([])
const collectionTotal = ref(0)
const collectionCursor = ref(null)
const collectionNextCursor = ref(null)
const collectionCursorHistory = ref([])
const selectedRecord = ref(null)
const recordDrawerVisible = ref(false)
const pi1mProfile = ref(null)
const pi1mVisualSamples = ref({ points: [], sample_count: 0, total: 0 })
const pi1mRecords = ref([])
const pi1mNextCursor = ref(null)
const pi1mLoading = ref(false)

const recordFilters = reactive({
  page: Number(route.query.page || 1),
  page_size: 20,
  keyword: String(route.query.keyword || ''),
})

const pi1mFilters = reactive({
  keyword: '',
  sa_min: '',
  sa_max: '',
  row_start: '',
  row_end: '',
  sort_by: 'row_index',
  page_size: 50,
})

const sourceReadyCount = computed(() => (overview.value?.sources || []).filter((item) => item.status === 'ready').length)
const sourceTotalCount = computed(() => (overview.value?.sources || []).length)
const selectedCollection = computed(() => mongoCollections.value.find((item) => collectionIdentity(item) === selectedCollectionName.value) || null)
const collectionUsesCursor = computed(() => (
  selectedCollection.value?.source_id === 'poly_data'
  && selectedCollectionName.value !== 'poly_data.pi1m_samples'
  && Number(selectedCollection.value?.count || 0) >= 100000
))
const polyDataSource = computed(() => (overview.value?.sources || []).find((item) => item.source === 'mongodb.poly_data') || null)
const materialCollection = computed(() => mongoCollections.value.find((item) => item.data_domain === 'materials') || null)
const computationRunCollection = computed(() => mongoCollections.value.find((item) => collectionIdentity(item) === 'computation_runs') || null)
const computationArtifactCollection = computed(() => mongoCollections.value.find((item) => collectionIdentity(item) === 'computation_artifacts') || null)
const pi1mDataset = computed(() => datasets.value.find((item) => item.dataset_id === 'pi1m_v2') || null)

const datasetGroupMeta = {
  structure: { label: '结构与分子', description: '分子、单体与聚合物结构描述', tone: 'blue' },
  simulation: { label: '模拟与计算', description: '分子动力学、量化计算与轨迹结果', tone: 'teal' },
  properties: { label: '物性与表征', description: '热学、电学、溶解性与多性质数据', tone: 'amber' },
  synthesis: { label: '合成与反应', description: '反应条件、产物与结构映射', tone: 'coral' },
  generated: { label: '生成与候选', description: '模型生成的候选单体与聚合物结构', tone: 'violet' },
  other: { label: '其他数据', description: '尚未归入上述分类的数据资产', tone: 'slate' },
}

function datasetGroupKey(dataset) {
  const text = `${dataset?.dataset_id || ''} ${dataset?.source_category || ''} ${dataset?.description || ''}`.toLowerCase()
  if (/生成|候选|virtual|generation|polyone|polyuniverse/.test(text)) return 'generated'
  if (/反应|合成|mapping/.test(text)) return 'synthesis'
  if (/模拟|动力学|量化|md-|md_allatom|radonpy/.test(text)) return 'simulation'
  if (/物性|性质|溶解|热学|电学|相行为|表征|property|polyomics|polysol|pppdb|tropic/.test(text)) return 'properties'
  if (/结构|分子|单体|smiles|标识|openpoly|smipoly|polyid|nanomine/.test(text)) return 'structure'
  return 'other'
}

const datasetGroups = computed(() => {
  const grouped = Object.fromEntries(Object.keys(datasetGroupMeta).map((key) => [key, []]))
  for (const dataset of datasets.value) grouped[datasetGroupKey(dataset)].push(dataset)
  return Object.entries(grouped)
    .map(([key, items]) => ({ key, ...datasetGroupMeta[key], items }))
    .filter((group) => group.items.length)
})

const visibleDatasetGroups = computed(() => datasetGroupFilter.value === 'all'
  ? datasetGroups.value
  : datasetGroups.value.filter((group) => group.key === datasetGroupFilter.value))

const datasetGroupCount = (key) => key === 'all'
  ? datasets.value.length
  : datasetGroups.value.find((group) => group.key === key)?.items.length || 0

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
    value: formatNumber(overview.value?.material_record_count),
    meta: polyDataSource.value ? statusLabel(polyDataSource.value.status) : '未配置',
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
  计算任务与产物: '#22c55e',
  研发流程与算法: '#f59e0b',
  优化闭环: '#06b6d4',
  报告产物: '#8b5cf6',
}

const PI1M_SA_COLOR_SCALE = ['#15803d', '#84cc16', '#facc15', '#f97316', '#dc2626']

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
  grid: { left: 164, right: 122, top: 24, bottom: 46 },
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
    axisLabel: { color: '#475569', width: 150, overflow: 'truncate', fontSize: 14 },
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
    barMinWidth: 6,
    barMaxWidth: 20,
    barCategoryGap: '34%',
    label: {
      show: true,
      position: 'right',
      color: '#1e293b',
      fontSize: 13,
      distance: 8,
      formatter: (item) => formatNumber(item.data.rawCount),
    },
  }],
}))

// Keep the complete volume chart inside the viewport so the x-axis remains visible.
const collectionVolumeChartHeight = computed(() => 'min(900px, max(520px, calc(100vh - 280px)))')

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

const relationSummary = computed(() => ({
  nodes: (relationships.value.nodes || []).length,
  links: relationshipRows.value.length,
  linked: relationshipRows.value.reduce((sum, row) => sum + row.linkedCount, 0),
}))

const relationshipSankeyOption = computed(() => {
  const nodeMap = Object.fromEntries((relationships.value.nodes || []).map((node) => [node.node_id, node]))
  const links = relationshipRows.value.map((row) => ({
    source: row.sourceLabel,
    target: row.targetLabel,
    value: row.linkedCount,
    sourceField: row.sourceField,
    targetField: row.targetField,
    coveragePercent: row.coveragePercent,
  }))
  const connectedIds = new Set((relationships.value.edges || [])
    .filter((edge) => Number(edge.linked_count || 0) > 0)
    .flatMap((edge) => [edge.source, edge.target]))
  const colors = ['#2563eb', '#0f766e', '#d97706', '#be5a35', '#7c3aed', '#64748b', '#0e7490']
  return {
    tooltip: {
      trigger: 'item',
      formatter: (params) => {
        if (params.dataType === 'edge') {
          return `${params.data.source} → ${params.data.target}<br/>已验证关联：${formatNumber(params.data.value)} 条<br/>覆盖率：${params.data.coveragePercent}%<br/><span style="color:#64748b">${params.data.sourceField} → ${params.data.targetField}</span>`
        }
        const node = Object.values(nodeMap).find((item) => item.label === params.name)
        return `${params.name}<br/>记录量：${formatNumber(node?.record_count || 0)} 条`
      },
    },
    series: [{
      type: 'sankey',
      left: 12,
      right: 96,
      top: 18,
      bottom: 18,
      nodeWidth: 18,
      nodeGap: 18,
      draggable: true,
      emphasis: { focus: 'adjacency' },
      layoutIterations: 32,
      data: (relationships.value.nodes || [])
        .filter((node) => connectedIds.has(node.node_id))
        .map((node, index) => ({
          name: node.label,
          itemStyle: { color: colors[index % colors.length], borderColor: '#ffffff', borderWidth: 1, shadowBlur: 8, shadowColor: 'rgba(37, 99, 235, 0.22)' },
          recordCount: node.record_count,
        })),
      links,
      lineStyle: { color: 'gradient', curveness: 0.56, opacity: 0.5 },
      label: { color: '#1e293b', fontSize: 14, fontWeight: 600, distance: 10 },
    }],
  }
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

const pi1mSaHistogramOption = computed(() => {
  const bins = pi1mProfile.value?.sa_score_histogram || []
  return {
    color: ['#3b82f6'],
    grid: { left: 46, right: 18, top: 20, bottom: 36 },
    tooltip: {
      trigger: 'axis',
      formatter: (items) => {
        const bin = bins[items[0].dataIndex]
        return `${bin.start} - ${bin.end}<br/>${formatNumber(bin.count)} 条`
      },
    },
    xAxis: {
      type: 'category',
      data: bins.map((bin) => `${bin.start}-${bin.end}`),
      axisLabel: { color: '#64748b', rotate: 28 },
    },
    yAxis: { type: 'value', axisLabel: { color: '#64748b' }, splitLine: { lineStyle: { color: '#e2e8f0' } } },
    series: [{ type: 'bar', data: bins.map((bin) => bin.count), barWidth: 16, itemStyle: { borderRadius: [4, 4, 0, 0] } }],
  }
})

const pi1mMapOption = computed(() => {
  const points = pi1mVisualSamples.value.points || []
  const scoreValues = points
    .map((item) => toFiniteNumber(item.sa_score))
    .filter((value) => value !== null)
  const scoreRange = visualRange(scoreValues)
  return {
    color: ['#0891b2'],
    grid: { left: 38, right: 18, top: 34, bottom: 30 },
    tooltip: {
      trigger: 'item',
      formatter: ({ data }) => [
        data[4],
        `行号：${formatNumber(data[2])}`,
        `SA Score：${data[3] === null || data[3] === undefined ? '-' : data[3].toFixed(3)}`,
        data[5] || '',
      ].filter(Boolean).join('<br/>'),
    },
    xAxis: { type: 'value', min: -1, max: 1, axisLabel: { color: '#64748b' }, splitLine: { lineStyle: { color: '#e2e8f0' } } },
    yAxis: { type: 'value', min: -1, max: 1, axisLabel: { color: '#64748b' }, splitLine: { lineStyle: { color: '#e2e8f0' } } },
    ...(scoreRange ? {
      visualMap: {
        type: 'continuous',
        min: scoreRange.min,
        max: scoreRange.max,
        dimension: 3,
        orient: 'horizontal',
        right: 24,
        top: 0,
        itemWidth: 12,
        itemHeight: 180,
        precision: 2,
        calculable: true,
        text: ['高 SA', '低 SA'],
        textStyle: { color: '#475569' },
        formatter: (value) => Number(value).toFixed(2),
        inRange: { color: PI1M_SA_COLOR_SCALE },
        outOfRange: { color: '#94a3b8' },
      },
    } : {}),
    series: [{
      type: 'scatter',
      symbolSize: 7,
      data: points.map((item) => [
        item.x,
        item.y,
        item.row_index,
        toFiniteNumber(item.sa_score),
        item.record_id,
        item.smiles,
      ]),
      itemStyle: { opacity: 0.82 },
      emphasis: { focus: 'self', itemStyle: { opacity: 1, borderColor: '#0f172a', borderWidth: 1 } },
      progressive: 1000,
      progressiveThreshold: 3000,
    }],
  }
})

const pi1mImportStatusText = computed(() => {
  const status = pi1mProfile.value?.import_status
  if (!status) return '未加载'
  const imported = status.imported_count !== null && status.imported_count !== undefined
    ? `${formatNumber(status.imported_count)} 条`
    : '无导入计数'
  return `${statusLabel(status.status)} · ${imported}`
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

function formatPercent(value) {
  if (value === null || value === undefined || value === '') return '-'
  return `${Number(value).toFixed(Number(value) < 1 && Number(value) > 0 ? 4 : 2)}%`
}

function statusTag(status) {
  const map = { ready: 'success', degraded: 'warning', not_configured: 'info', imported: 'success', completed: 'success', verifying: 'warning', running: 'warning', failed: 'danger', queued: 'info', cancelled: 'info', active: 'success', disabled: 'danger' }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = { ready: '正常', degraded: '部分可用', not_configured: '未配置', imported: '完成', completed: '完成', verifying: '校验中', running: '运行中', failed: '失败', queued: '排队', cancelled: '取消', active: '正常', disabled: '禁用' }
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

function datasetRecordModeLabel(mode) {
  const map = { full: '全量记录', sample: '样本记录', metadata_only: '仅元数据' }
  return map[mode] || '仅元数据'
}

function datasetRecordModeTag(mode) {
  const map = { full: 'success', sample: 'warning', metadata_only: 'info' }
  return map[mode] || 'info'
}

function datasetObjectSummary(dataset) {
  const objects = dataset?.objects || []
  const ready = objects.filter((item) => item.exists).length
  return `${ready}/${objects.length || 0} 文件`
}

function datasetRecordCountText(dataset) {
  if (!dataset?.record_collection_key) return '未导入'
  if (dataset.record_count === null || dataset.record_count === undefined) return '未配置'
  const coverage = Number(dataset.coverage_percent || 0)
  return `${formatNumber(dataset.record_count)} / ${formatNumber(dataset.row_count)} · ${formatPercent(coverage)}`
}

function verificationStatusLabel(status) {
  const map = { verified: '已校验', partial: '未完整', metadata_only: '未导入', running: '导入中', failed: '校验失败', unavailable: '不可用' }
  return map[status] || '待校验'
}

function verificationStatusType(status) {
  const map = { verified: 'success', partial: 'warning', metadata_only: 'info', running: 'warning', failed: 'danger', unavailable: 'danger' }
  return map[status] || 'info'
}

function datasetStatusLabel(dataset) {
  if (dataset?.verification_status === 'verified') return datasetRecordModeLabel(dataset.record_mode)
  return verificationStatusLabel(dataset?.verification_status)
}

function datasetImportPercent(dataset) {
  const status = dataset?.import_status || {}
  const current = Number(status.processed_count ?? status.imported_count ?? dataset?.record_count ?? 0)
  const expected = Number(status.expected_count ?? dataset?.row_count ?? 0)
  if (!expected) return 0
  return Math.min(100, Math.max(0, Number(((current / expected) * 100).toFixed(2))))
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

function toFiniteNumber(value) {
  const numericValue = Number(value)
  return Number.isFinite(numericValue) ? numericValue : null
}

function visualRange(values) {
  if (!values.length) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  if (min !== max) return { min, max }
  const padding = Math.max(Math.abs(min) * 0.05, 0.5)
  return { min: min - padding, max: max + padding }
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
  const candidates = [
    'monomer_class',
    'source_file',
    'dataset',
    'workflow_type',
    'engine',
    'artifact_type',
    'event_type',
    'planner_type',
    'trigger_source',
  ]
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
    if (selectedCollectionName.value) await loadCollectionRecords()
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

function openAnalysisPage() {
  router.push('/database/data-analysis')
}

async function loadPi1mOverview() {
  try {
    const [profile, samples] = await Promise.allSettled([
      getDataCatalogDatasetProfile('pi1m_v2'),
      getDataCatalogDatasetVisualSamples('pi1m_v2', { limit: 5000 }),
    ])
    pi1mProfile.value = profile.status === 'fulfilled' ? profile.value : null
    pi1mVisualSamples.value = samples.status === 'fulfilled' ? samples.value : { points: [], sample_count: 0, total: 0 }
  } catch {
    pi1mProfile.value = null
    pi1mVisualSamples.value = { points: [], sample_count: 0, total: 0 }
  }
}

async function loadAnalysisSamples() {
  const materialCollectionName = materialCollection.value ? collectionIdentity(materialCollection.value) : ''
  const requests = [
    materialCollectionName
      ? listDataCatalogCollectionRecords(materialCollectionName, { page: 1, page_size: 100 })
      : Promise.resolve({ items: [] }),
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
  datasetCoverageVisible.value = false
  datasetDrawerVisible.value = true
}

function showDatasetCoverageChart() {
  datasetCoverageVisible.value = true
}

function hideDatasetCoverageChart() {
  datasetCoverageVisible.value = false
}

async function openDatasetRecords(dataset) {
  if (!dataset?.record_collection_key) {
    ElMessage.info('该数据集当前只登记了文件和字段说明')
    return
  }
  datasetDrawerVisible.value = false
  if (dataset.dataset_id === 'pi1m_v2') {
    activeTab.value = 'mongo'
    selectedCollectionName.value = dataset.record_collection_key
    recordFilters.page = 1
    recordFilters.keyword = ''
    syncRouteQuery({ tab: 'mongo', collection: selectedCollectionName.value, page: 1, keyword: undefined })
    await loadPi1mRecords({ reset: true })
    return
  }
  activeTab.value = 'mongo'
  selectedCollectionName.value = dataset.record_collection_key
  recordFilters.page = 1
  recordFilters.keyword = ''
  resetCollectionCursor()
  syncRouteQuery({ tab: 'mongo', collection: selectedCollectionName.value, page: 1, keyword: undefined })
  await loadCollectionRecords()
}

async function openCollection(collection) {
  activeTab.value = 'mongo'
  selectedCollectionName.value = collectionIdentity(collection)
  recordFilters.page = 1
  resetCollectionCursor()
  syncRouteQuery({ collection: selectedCollectionName.value, page: 1 })
  await loadCollectionRecords()
}

function resetCollectionCursor() {
  collectionCursor.value = null
  collectionNextCursor.value = null
  collectionCursorHistory.value = []
}

async function loadCollectionRecords() {
  if (!selectedCollectionName.value) return
  if (selectedCollectionName.value === 'poly_data.pi1m_samples') {
    await loadPi1mRecords({ reset: true })
    return
  }
  recordsLoading.value = true
  try {
    const data = await listDataCatalogCollectionRecords(selectedCollectionName.value, {
      page: recordFilters.page,
      page_size: recordFilters.page_size,
      keyword: recordFilters.keyword || undefined,
      use_cursor: collectionUsesCursor.value || undefined,
      cursor: collectionUsesCursor.value ? (collectionCursor.value || undefined) : undefined,
    })
    collectionRecords.value = data.items || []
    collectionTotal.value = data.total || 0
    collectionNextCursor.value = data.next_cursor || null
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    recordsLoading.value = false
  }
}

function pi1mQueryParams(cursor = null) {
  return {
    page_size: pi1mFilters.page_size,
    sort_by: pi1mFilters.sort_by,
    cursor: cursor || undefined,
    keyword: pi1mFilters.keyword || undefined,
    sa_min: pi1mFilters.sa_min !== '' ? Number(pi1mFilters.sa_min) : undefined,
    sa_max: pi1mFilters.sa_max !== '' ? Number(pi1mFilters.sa_max) : undefined,
    row_start: pi1mFilters.row_start !== '' ? Number(pi1mFilters.row_start) : undefined,
    row_end: pi1mFilters.row_end !== '' ? Number(pi1mFilters.row_end) : undefined,
  }
}

async function loadPi1mRecords({ reset = false } = {}) {
  pi1mLoading.value = true
  recordsLoading.value = true
  try {
    const data = await listDataCatalogDatasetRecords('pi1m_v2', pi1mQueryParams(reset ? null : pi1mNextCursor.value))
    pi1mRecords.value = reset ? (data.items || []) : [...pi1mRecords.value, ...(data.items || [])]
    collectionRecords.value = pi1mRecords.value
    pi1mNextCursor.value = data.next_cursor || null
    collectionTotal.value = data.total || 0
    recordFilters.page = 1
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    recordsLoading.value = false
    pi1mLoading.value = false
  }
}

async function handleRecordSearch() {
  if (selectedCollectionName.value === 'poly_data.pi1m_samples') {
    pi1mFilters.keyword = recordFilters.keyword
    pi1mNextCursor.value = null
    syncRouteQuery({ collection: selectedCollectionName.value, keyword: recordFilters.keyword, page: undefined })
    await loadPi1mRecords({ reset: true })
    return
  }
  recordFilters.page = 1
  resetCollectionCursor()
  syncRouteQuery({ collection: selectedCollectionName.value, keyword: recordFilters.keyword, page: 1 })
  await loadCollectionRecords()
}

async function handleRecordPageChange(page) {
  if (selectedCollectionName.value === 'poly_data.pi1m_samples') return
  recordFilters.page = page
  syncRouteQuery({ collection: selectedCollectionName.value, keyword: recordFilters.keyword, page })
  await loadCollectionRecords()
}

async function loadNextCollectionCursor() {
  if (!collectionNextCursor.value) return
  collectionCursorHistory.value.push(collectionCursor.value)
  collectionCursor.value = collectionNextCursor.value
  await loadCollectionRecords()
}

async function loadPreviousCollectionCursor() {
  if (!collectionCursorHistory.value.length) return
  collectionCursor.value = collectionCursorHistory.value.pop() || null
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
  if (selectedCollectionName.value) {
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
      <div class="header-actions">
        <el-button :icon="TrendCharts" @click="openAnalysisPage">数据分析</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="loadDataCatalog">刷新</el-button>
      </div>
    </header>

    <AttributionBanner module-id="data_catalog" label="数据来源" compact />

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
      <el-tab-pane label="数据目录" name="datasets" lazy>
        <div class="analysis-layout">
          <section class="catalog-section dataset-section">
            <div class="section-heading">
              <div>
                <h2>Poly Data 数据集</h2>
                <p class="section-description">按数据用途分组管理，点击数据行查看字段、对象和入库状态。</p>
              </div>
              <span>{{ datasets.length }} 个数据集</span>
            </div>
            <div class="dataset-browser-layout">
              <nav class="dataset-rail" aria-label="数据集分类">
                <div class="dataset-rail-label">数据分类</div>
                <button
                  type="button"
                  class="dataset-filter"
                  :class="{ active: datasetGroupFilter === 'all' }"
                  @click="datasetGroupFilter = 'all'"
                >
                  <span>全部数据集</span><strong>{{ datasetGroupCount('all') }}</strong>
                </button>
                <button
                  v-for="group in datasetGroups"
                  :key="group.key"
                  type="button"
                  class="dataset-filter"
                  :class="[`tone-${group.tone}`, { active: datasetGroupFilter === group.key }]"
                  @click="datasetGroupFilter = group.key"
                >
                  <span>{{ group.label }}</span><strong>{{ group.items.length }}</strong>
                </button>
              </nav>

              <div class="dataset-group-stack">
                <section v-for="group in visibleDatasetGroups" :key="group.key" class="dataset-group" :class="`tone-${group.tone}`">
                  <header class="dataset-group-header">
                    <div class="dataset-group-title">
                      <span class="dataset-group-marker" aria-hidden="true"></span>
                      <div>
                        <h3>{{ group.label }}</h3>
                        <p>{{ group.description }}</p>
                      </div>
                    </div>
                    <span class="dataset-group-count">{{ group.items.length }} 个</span>
                  </header>
                  <div class="dataset-list" role="list">
                    <button v-for="dataset in group.items" :key="dataset.dataset_id" type="button" class="dataset-list-row" @click="openDataset(dataset)">
                      <span class="dataset-list-main">
                        <span class="dataset-list-name">{{ dataset.display_name }}</span>
                        <span class="dataset-list-description">{{ dataset.description }}</span>
                        <span class="dataset-list-tags">
                          <el-tag size="small" effect="plain">{{ dataset.source_category }}</el-tag>
                          <el-tag size="small" effect="plain">{{ dataset.confidence_label }}</el-tag>
                        </span>
                      </span>
                      <span class="dataset-list-stat"><strong>{{ formatNumber(dataset.row_count) }}</strong><small>原始行</small></span>
                      <span class="dataset-list-stat"><strong>{{ formatNumber(dataset.column_count) }}</strong><small>字段</small></span>
                      <span class="dataset-list-status">
                        <el-tag size="small" :type="verificationStatusType(dataset.verification_status)">{{ datasetStatusLabel(dataset) }}</el-tag>
                        <small>{{ datasetRecordCountText(dataset) }}</small>
                      </span>
                      <el-icon class="dataset-list-arrow" aria-hidden="true"><ArrowRight /></el-icon>
                    </button>
                  </div>
                </section>
                <el-empty v-if="!visibleDatasetGroups.length" description="暂无数据集" />
              </div>
            </div>
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

              <div class="record-tools">
                <el-input v-model="recordFilters.keyword" clearable placeholder="搜索主键、状态、类型或文本" @keyup.enter="handleRecordSearch">
                  <template #prefix><el-icon><Search /></el-icon></template>
                </el-input>
                <el-button @click="handleRecordSearch">查询</el-button>
              </div>

              <div v-if="selectedCollectionName === 'poly_data.pi1m_samples'" class="pi1m-filter-panel">
                <el-input v-model="pi1mFilters.row_start" placeholder="起始行号" clearable />
                <el-input v-model="pi1mFilters.row_end" placeholder="结束行号" clearable />
                <el-input v-model="pi1mFilters.sa_min" placeholder="SA 最小值" clearable />
                <el-input v-model="pi1mFilters.sa_max" placeholder="SA 最大值" clearable />
                <el-select v-model="pi1mFilters.sort_by" placeholder="排序">
                  <el-option label="按行号" value="row_index" />
                  <el-option label="按 SA Score" value="sa_score" />
                </el-select>
                <el-button type="primary" :loading="pi1mLoading" @click="loadPi1mRecords({ reset: true })">筛选</el-button>
              </div>

              <div class="record-visual-grid">
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

              <el-table :data="collectionRecords" v-loading="recordsLoading" stripe class="record-table">
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
                v-if="selectedCollectionName !== 'poly_data.pi1m_samples' && !collectionUsesCursor"
                class="record-pagination"
                background
                layout="prev, pager, next, total"
                :current-page="recordFilters.page"
                :page-size="recordFilters.page_size"
                :total="collectionTotal"
                @current-change="handleRecordPageChange"
              />
              <div v-if="selectedCollectionName === 'poly_data.pi1m_samples'" class="pi1m-cursor-actions">
                <span>已加载 {{ formatNumber(collectionRecords.length) }} 条，游标分页避免千万级 skip 扫描。</span>
                <el-button :disabled="!pi1mNextCursor" :loading="pi1mLoading" @click="loadPi1mRecords()">加载下一页</el-button>
              </div>
              <div v-else-if="collectionUsesCursor" class="collection-cursor-actions">
                <span>共 {{ formatNumber(collectionTotal) }} 条</span>
                <div>
                  <el-button :icon="Back" :disabled="!collectionCursorHistory.length" @click="loadPreviousCollectionCursor">上一页</el-button>
                  <el-button type="primary" :icon="Right" :disabled="!collectionNextCursor" @click="loadNextCollectionCursor">下一页</el-button>
                </div>
              </div>
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
        <div class="relation-page">
          <section class="relation-summary" aria-label="关系概览">
            <div><span>关系节点</span><strong>{{ relationSummary.nodes }}</strong><small>已登记集合</small></div>
            <div><span>有效链路</span><strong>{{ relationSummary.links }}</strong><small>有真实外键记录</small></div>
            <div><span>关联记录</span><strong>{{ formatNumber(relationSummary.linked) }}</strong><small>跨集合关联总量</small></div>
            <div class="relation-summary-note"><span>数据口径</span><p>{{ relationships.notes?.[0] || '仅展示数据库中可验证的外键关系。' }}</p></div>
          </section>

          <section class="catalog-section relation-volume relation-volume-main">
            <div class="section-heading">
              <div>
                <h2>集合记录量</h2>
                <p class="section-description">柱长按对数尺度，标签显示真实记录量；不同颜色对应数据域。</p>
              </div>
              <span>{{ mongoCollections.length }} 张表</span>
            </div>
            <v-chart class="collection-volume-chart" :style="{ height: collectionVolumeChartHeight }" :option="collectionVolumeOption" autoresize />
          </section>

          <section class="relation-lower-grid">
            <section class="catalog-section relation-sankey">
              <div class="section-heading">
                <div>
                  <h2>数据流向</h2>
                  <p class="section-description">桑基图展示材料、任务、产物和报告之间的真实依赖关系。</p>
                </div>
                <span>{{ relationshipRows.length }} 条有效链路</span>
              </div>
              <v-chart v-if="relationshipRows.length" class="relationship-sankey-chart" :option="relationshipSankeyOption" autoresize />
              <div v-else class="relation-empty"><el-empty description="暂无可验证的跨集合关联" /></div>
            </section>
            <section class="catalog-section relation-index">
              <div class="section-heading"><div><h2>关系索引</h2><p class="section-description">按关联数量排序，快速定位高价值链路。</p></div><span>{{ relationshipRows.length }} 条链路</span></div>
              <div v-if="relationshipRows.length" class="relation-index-list">
                <div v-for="row in relationshipRows" :key="row.key" class="relation-index-row">
                  <span class="relation-index-flow"><strong>{{ row.sourceLabel }}</strong><el-icon><ArrowRight /></el-icon><strong>{{ row.targetLabel }}</strong></span>
                  <span class="relation-index-value"><b>{{ formatNumber(row.linkedCount) }}</b> 条</span>
                  <small>{{ row.sourceField }} → {{ row.targetField }}</small>
                </div>
              </div>
              <el-empty v-else description="暂无链路" />
            </section>
          </section>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-drawer
      v-model="datasetDrawerVisible"
      size="56%"
      class="catalog-drawer"
      title="数据集详情"
      @opened="showDatasetCoverageChart"
      @closed="hideDatasetCoverageChart"
    >
      <template v-if="selectedDataset">
        <div class="drawer-heading">
          <div>
            <h2>{{ selectedDataset.display_name }}</h2>
            <p>{{ selectedDataset.description }}</p>
          </div>
          <div class="drawer-actions">
            <el-tag :type="verificationStatusType(selectedDataset.verification_status)" effect="plain">
              {{ verificationStatusLabel(selectedDataset.verification_status) }}
            </el-tag>
            <el-tag :type="datasetRecordModeTag(selectedDataset.record_mode)" effect="plain">
              {{ datasetRecordModeLabel(selectedDataset.record_mode) }}
            </el-tag>
            <el-button
              v-if="selectedDataset.record_collection_key"
              type="primary"
              :icon="View"
              @click="openDatasetRecords(selectedDataset)"
            >
              查看记录
            </el-button>
          </div>
        </div>
        <div class="drawer-stat-row">
          <span>{{ formatNumber(selectedDataset.row_count) }} 行</span>
          <span>{{ formatNumber(selectedDataset.column_count) }} 列</span>
          <span>{{ datasetRecordCountText(selectedDataset) }}</span>
          <code>{{ selectedDataset.storage_prefix }}</code>
        </div>
        <div
          v-if="['running', 'verifying', 'queued'].includes(selectedDataset.import_status?.status)"
          class="dataset-import-progress"
        >
          <div>
            <strong>{{ statusLabel(selectedDataset.import_status.status) }}</strong>
            <span>{{ formatNumber(selectedDataset.import_status.processed_count || 0) }} / {{ formatNumber(selectedDataset.import_status.expected_count || selectedDataset.row_count) }}</span>
          </div>
          <el-progress :percentage="datasetImportPercent(selectedDataset)" :stroke-width="8" />
        </div>
        <el-alert
          v-if="selectedDataset.verification_status === 'failed'"
          type="error"
          :closable="false"
          show-icon
          :title="selectedDataset.import_status?.error || '最近一次导入未通过校验'"
        />

        <h3 class="drawer-section-title">字段覆盖率</h3>
        <v-chart v-if="datasetCoverageVisible" class="coverage-chart" :option="datasetCoverageOption" autoresize />
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

.header-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
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
  font-size: 20px;
}

.section-heading span {
  color: var(--app-ink-muted);
  font-size: 14px;
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

.pi1m-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.pi1m-summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.pi1m-summary-item {
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
}

.pi1m-summary-item span {
  display: block;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.pi1m-summary-item strong {
  display: block;
  margin-top: 5px;
  color: var(--app-ink);
  font-size: 17px;
  line-height: 1.3;
  overflow-wrap: anywhere;
}

.pi1m-visual-grid {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  gap: 12px;
}

.pi1m-chart {
  width: 100%;
  height: 260px;
}

.pi1m-filter-panel {
  display: grid;
  grid-template-columns: repeat(4, minmax(110px, 1fr)) minmax(140px, 0.8fr) auto;
  gap: 10px;
  margin: 0 0 14px;
}

.pi1m-cursor-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 14px;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.mongo-layout {
  grid-template-columns: 360px minmax(0, 1fr);
  align-items: start;
}

.relation-grid {
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 0.8fr);
}

.relation-page { display: flex; flex-direction: column; gap: 14px; }

.relation-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 0.75fr)) minmax(260px, 1.5fr);
  gap: 1px;
  overflow: hidden;
  border: 1px solid var(--app-card-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-border-soft);
}

.relation-summary > div { min-height: 88px; padding: 14px 16px; background: #fff; }
.relation-summary span { display: block; color: var(--app-ink-muted); font-size: 12px; }
.relation-summary strong { display: block; margin-top: 3px; color: var(--app-sidebar-from); font-size: 23px; line-height: 1.1; }
.relation-summary small { display: block; margin-top: 4px; color: var(--app-ink-subtle); font-size: 11px; }
.relation-summary-note p { margin: 6px 0 0; color: var(--app-ink-body); font-size: 12px; line-height: 1.45; }

.relation-heading { align-items: center; }
.relationship-sankey-chart { width: 100%; height: 460px; }
.relation-empty { min-height: 360px; display: grid; place-items: center; }

.relation-volume-main { min-width: 0; }
.relation-lower-grid { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(340px, 0.8fr); gap: 14px; align-items: stretch; }
.relation-sankey, .relation-index, .relation-volume { min-width: 0; }
.relation-index-list { display: flex; flex-direction: column; }
.relation-index-row { display: grid; grid-template-columns: minmax(0, 1fr) 86px; gap: 8px 12px; align-items: center; width: 100%; padding: 13px 0; border-bottom: 1px solid var(--app-border-soft); background: transparent; color: inherit; text-align: left; }
.relation-index-row:last-child { border-bottom: 0; }
.relation-index-flow { display: flex; align-items: center; gap: 7px; min-width: 0; color: var(--app-ink-body); font-size: 14px; }
.relation-index-flow strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.relation-index-flow .el-icon { flex: 0 0 auto; color: var(--app-primary); }
.relation-index-value { color: var(--app-primary); text-align: right; white-space: nowrap; }
.relation-index-value b { font-size: 17px; }
.relation-index-row small { grid-column: 1 / -1; color: var(--app-ink-muted); font-family: var(--app-mono-font); font-size: 12px; }

.dataset-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.section-description {
  margin: 5px 0 0;
  color: var(--app-ink-muted);
  font-size: 12px;
  font-weight: 400;
}

.dataset-browser-layout {
  display: grid;
  grid-template-columns: 188px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.dataset-rail {
  position: sticky;
  top: 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-right: 14px;
  border-right: 1px solid var(--app-border-soft);
}

.dataset-rail-label {
  margin: 2px 10px 8px;
  color: var(--app-ink-subtle);
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.dataset-filter {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-height: 48px;
  padding: 10px 14px;
  border: 1px solid transparent;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: var(--app-ink-body);
  text-align: left;
  font-size: 16px;
  cursor: pointer;
}

.dataset-filter strong {
  min-width: 26px;
  color: var(--app-ink-subtle);
  font-size: 14px;
  font-weight: 600;
  text-align: right;
}

.dataset-filter:hover,
.dataset-filter.active {
  border-color: var(--app-border-soft);
  background: #f5f8fd;
  color: var(--app-sidebar-from);
  font-weight: 600;
}

.dataset-filter.active strong { color: var(--app-primary); }

.dataset-filter.tone-blue.active { border-left: 3px solid #2563eb; }
.dataset-filter.tone-teal.active { border-left: 3px solid #0f766e; }
.dataset-filter.tone-amber.active { border-left: 3px solid #d97706; }
.dataset-filter.tone-coral.active { border-left: 3px solid #be5a35; }
.dataset-filter.tone-violet.active { border-left: 3px solid #7c3aed; }
.dataset-filter.tone-slate.active { border-left: 3px solid #64748b; }

.dataset-group-stack { display: flex; flex-direction: column; gap: 18px; min-width: 0; }

.dataset-group {
  overflow: hidden;
  border: 1px solid var(--app-border-soft);
  border-left: 3px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: #fff;
}

.dataset-group.tone-blue { border-left-color: #2563eb; }
.dataset-group.tone-teal { border-left-color: #0f766e; }
.dataset-group.tone-amber { border-left-color: #d97706; }
.dataset-group.tone-coral { border-left-color: #be5a35; }
.dataset-group.tone-violet { border-left-color: #7c3aed; }
.dataset-group.tone-slate { border-left-color: #64748b; }

.dataset-group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 13px 15px 11px;
  background: #fbfcfe;
  border-bottom: 1px solid var(--app-border-soft);
}

.dataset-group-title { display: flex; align-items: center; gap: 10px; min-width: 0; }
.dataset-group-marker { width: 8px; height: 8px; flex: 0 0 auto; border-radius: 50%; background: var(--app-border); }
.tone-blue .dataset-group-marker { background: #2563eb; }
.tone-teal .dataset-group-marker { background: #0f766e; }
.tone-amber .dataset-group-marker { background: #d97706; }
.tone-coral .dataset-group-marker { background: #be5a35; }
.tone-violet .dataset-group-marker { background: #7c3aed; }
.tone-slate .dataset-group-marker { background: #64748b; }
.dataset-group-header h3 { margin: 0; color: var(--app-ink); font-size: 18px; }
.dataset-group-header p { margin: 3px 0 0; color: var(--app-ink-muted); font-size: 13px; }
.dataset-group-count { color: var(--app-ink-muted); font-size: 14px; white-space: nowrap; }

.dataset-list { display: flex; flex-direction: column; }

.dataset-list-row {
  display: grid;
  grid-template-columns: minmax(240px, 1.8fr) 86px 72px 130px 22px;
  gap: 14px;
  align-items: center;
  width: 100%;
  min-height: 104px;
  padding: 15px 16px;
  border: 0;
  border-bottom: 1px solid #eef2f7;
  background: #fff;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.dataset-list-row:last-child { border-bottom: 0; }
.dataset-list-row:hover, .dataset-list-row:focus-visible { background: #f7faff; outline: none; }
.dataset-list-main { min-width: 0; }
.dataset-list-name { display: block; overflow: hidden; color: var(--app-ink); font-size: 16px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.dataset-list-description { display: block; overflow: hidden; margin-top: 4px; color: var(--app-ink-muted); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.dataset-list-tags { display: flex; gap: 5px; margin-top: 7px; overflow: hidden; }
.dataset-list-tags .el-tag { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dataset-list-stat strong { display: block; color: var(--app-sidebar-from); font-size: 18px; line-height: 1.1; }
.dataset-list-stat small, .dataset-list-status small { display: block; margin-top: 5px; color: var(--app-ink-muted); font-size: 12px; }
.dataset-list-status { display: flex; flex-direction: column; align-items: flex-start; min-width: 0; }
.dataset-list-arrow { color: var(--app-ink-subtle); }
.dataset-list-row:hover .dataset-list-arrow { color: var(--app-primary); }

.dataset-card {
  padding: 14px;
  box-shadow: none;
}

.dataset-card-button {
  width: 100%;
  min-height: 188px;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.dataset-card-button:hover,
.dataset-card-button:focus-visible {
  border-color: #9fc2fb;
  background: #f8fbff;
  outline: none;
}

.dataset-card h3,
.collection-group h3 {
  font-size: 18px;
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
  height: 560px;
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
  min-height: 70px;
  padding: 12px 14px;
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

.collection-row strong { font-size: 16px; }
.collection-row code { margin-top: 3px; font-size: 14px; }

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

.collection-cursor-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 40px;
  margin-top: 14px;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.collection-cursor-actions > div {
  display: flex;
  gap: 8px;
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

.drawer-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
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

.dataset-import-progress {
  margin-bottom: 16px;
  padding: 10px 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
}

.dataset-import-progress > div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  color: var(--app-ink-body);
  font-size: 13px;
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
  .pi1m-summary-grid,
  .pi1m-visual-grid,
  .record-visual-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .pi1m-filter-panel {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .dataset-browser-layout { grid-template-columns: 160px minmax(0, 1fr); }
  .dataset-list-row { grid-template-columns: minmax(190px, 1.6fr) 76px 62px 120px 20px; gap: 10px; }
  .relation-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .relation-summary-note { grid-column: 1 / -1; min-height: auto !important; }
  .relation-lower-grid { grid-template-columns: 1fr; }
}

@media (max-width: 760px) {
  .catalog-header,
  .record-header,
  .drawer-heading {
    flex-direction: column;
  }

  .header-actions,
  .drawer-actions {
    justify-content: flex-start;
  }

  .metric-grid,
  .dataset-grid,
  .analysis-grid,
  .pi1m-summary-grid,
  .pi1m-visual-grid,
  .record-visual-grid {
    grid-template-columns: 1fr;
  }

  .dataset-browser-layout { grid-template-columns: 1fr; }
  .dataset-rail { position: static; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); padding: 0 0 10px; border-right: 0; border-bottom: 1px solid var(--app-border-soft); }
  .dataset-rail-label { grid-column: 1 / -1; margin: 0 0 2px; }
  .dataset-list-row { grid-template-columns: minmax(0, 1fr) 20px; gap: 6px 10px; }
  .dataset-list-stat, .dataset-list-status { display: none; }
  .dataset-list-description { white-space: normal; }
  .relation-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .relation-summary-note { grid-column: 1 / -1; }
  .relation-heading { align-items: flex-start; flex-direction: column; }
  .relationship-sankey-chart { height: 340px; }

  .record-tools {
    flex-direction: column;
  }

  .record-tools .el-input {
    max-width: none;
  }

  .pi1m-filter-panel,
  .pi1m-cursor-actions,
  .collection-cursor-actions {
    grid-template-columns: 1fr;
    flex-direction: column;
    align-items: stretch;
  }

  .collection-cursor-actions > div {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
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
