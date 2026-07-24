<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { DataAnalysis, Files, FolderOpened, Refresh, Search } from '@element-plus/icons-vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, LineChart, PieChart, ScatterChart } from 'echarts/charts'
import {
  GridComponent, LegendComponent, TooltipComponent, VisualMapComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

import {
  getApiErrorMessage,
  getDataCatalogDatasetProfile,
  getDataCatalogDatasetVisualSamples,
  listDataCatalogCollectionRecords,
  listDataCatalogDatasets,
  listDataCatalogMongoCollections,
} from '../api/polyAgentApi'
import { authState } from '../auth/authState'
import AttributionBanner from '../components/attribution/AttributionBanner.vue'

use([
  BarChart,
  LineChart,
  PieChart,
  ScatterChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  VisualMapComponent,
  CanvasRenderer,
])

const router = useRouter()
const loading = ref(false)
const activeTab = ref('pi1m')
const datasets = ref([])
const mongoCollections = ref([])
const pi1mProfile = ref(null)
const pi1mVisualSamples = ref({ points: [], sample_count: 0, total: 0 })
const mdAllatomProfile = ref(null)
const materialAnalysisRecords = ref([])
const computationAnalysisRecords = ref([])
const artifactAnalysisRecords = ref([])

const PI1M_SA_COLOR_SCALE = ['#15803d', '#84cc16', '#facc15', '#f97316', '#dc2626']

const canDrilldownRecords = computed(() => !authState.authEnabled || authState.role === 'admin')
const pi1mDataset = computed(() => datasets.value.find((item) => item.dataset_id === 'pi1m_v2') || null)
const mdAllatomDataset = computed(() => datasets.value.find((item) => item.dataset_id === 'md_allatom') || null)
const materialCollection = computed(() => mongoCollections.value.find((item) => item.data_domain === 'materials') || null)
const mdAllatomHasData = computed(() => Number(mdAllatomProfile.value?.record_count || 0) > 0
  || Number(mdAllatomProfile.value?.asset_coverage?.structured_records?.carbon_results || 0) > 0
  || Number(mdAllatomProfile.value?.asset_coverage?.file_count || 0) > 0
  || Object.keys(mdAllatomProfile.value?.category_counts || {}).length > 0
  || (mdAllatomProfile.value?.analysis_samples?.length || 0) > 0)
const fileCoverageRows = computed(() => {
  const families = mdAllatomProfile.value?.asset_coverage?.families || {}
  return ['C', 'F', 'Si'].map((family) => ({ family, count: Number(families[family] || 0) }))
})

const headlineMetrics = computed(() => [
  {
    key: 'pi1m',
    label: 'PI1M 入库',
    value: `${formatNumber(pi1mProfile.value?.record_count || pi1mDataset.value?.record_count || 0)} / ${formatNumber(pi1mDataset.value?.row_count || 0)}`,
    meta: formatPercent(pi1mProfile.value?.coverage_percent),
    icon: DataAnalysis,
  },
  {
    key: 'md',
    label: 'MD-AllAtom 碳基',
    value: formatNumber(mdAllatomProfile.value?.record_count || mdAllatomDataset.value?.record_count || 0),
    meta: `${formatNumber(mdAllatomProfile.value?.asset_coverage?.file_count || 0)} 个原始文件索引`,
    icon: FolderOpened,
  },
  {
    key: 'materials',
    label: '材料样本',
    value: formatNumber(materialAnalysisRecords.value.length),
    meta: canDrilldownRecords.value ? '近 100 条' : '管理员可见',
    icon: Files,
  },
  {
    key: 'compute',
    label: '计算样本',
    value: formatNumber(computationAnalysisRecords.value.length),
    meta: canDrilldownRecords.value ? '近 100 条' : '管理员可见',
    icon: Search,
  },
])

const pi1mSaHistogramOption = computed(() => {
  const bins = pi1mProfile.value?.sa_score_histogram || []
  return barOption(
    bins.map((bin) => `${bin.start}-${bin.end}`),
    bins.map((bin) => bin.count),
    '#3b82f6',
    { rotate: 28 },
  )
})

const pi1mMapOption = computed(() => {
  const points = pi1mVisualSamples.value.points || []
  const scoreValues = points.map((item) => toFiniteNumber(item.sa_score)).filter((value) => value !== null)
  const scoreRange = visualRange(scoreValues)
  return {
    grid: { left: 40, right: 20, top: 36, bottom: 34 },
    tooltip: {
      trigger: 'item',
      formatter: ({ data }) => [
        data[4],
        `行号：${formatNumber(data[2])}`,
        `SA Score：${data[3] === null || data[3] === undefined ? '-' : data[3].toFixed(3)}`,
        data[5] || '',
      ].filter(Boolean).join('<br/>'),
    },
    xAxis: axis('value', { min: -1, max: 1 }),
    yAxis: axis('value', { min: -1, max: 1 }),
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
        inRange: { color: PI1M_SA_COLOR_SCALE },
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

const mdFamilyFilesOption = computed(() => barOption(
  fileCoverageRows.value.map((row) => row.family),
  fileCoverageRows.value.map((row) => row.count),
  '#0891b2',
))

const mdTemperatureOption = computed(() => categoryBarOption(mdAllatomProfile.value?.category_counts?.temperature || {}, '#3b82f6'))
const mdDpOption = computed(() => categoryBarOption(mdAllatomProfile.value?.category_counts?.dp || {}, '#16a34a'))
const mdE2eOption = computed(() => histogramOption('e2e_mean', '#3b82f6'))
const mdRgOption = computed(() => histogramOption('rg_mean', '#16a34a'))
const mdPersistOption = computed(() => histogramOption('persist_len_mean', '#d97706'))

const mdScatterOption = computed(() => {
  const points = mdAllatomProfile.value?.analysis_samples || []
  return {
    grid: { left: 48, right: 20, top: 18, bottom: 38 },
    tooltip: {
      trigger: 'item',
      formatter: ({ data }) => [
        data[4],
        `温度：${formatNumber(data[0])} K`,
        `e2e_mean：${formatNumber(data[1])}`,
        `rg_mean：${formatNumber(data[2])}`,
        `persist_len_mean：${formatNumber(data[3])}`,
      ].join('<br/>'),
    },
    xAxis: axis('value'),
    yAxis: axis('value'),
    series: [{
      type: 'scatter',
      symbolSize: 8,
      data: points.map((item) => [
        toFiniteNumber(item.temperature ?? item.x),
        toFiniteNumber(item.y),
        toFiniteNumber(item.rg_mean),
        toFiniteNumber(item.persist_len_mean),
        item.record_id,
      ]),
      itemStyle: { color: '#0891b2', opacity: 0.78 },
    }],
  }
})

const materialDatasetOption = computed(() => categoryBarOption(countBy(
  materialAnalysisRecords.value.map((item) => item.preview_fields?.dataset || 'unknown'),
), '#3b82f6'))

const materialPropertyOption = computed(() => {
  const values = []
  for (const item of materialAnalysisRecords.value) {
    values.push(...String(item.preview_fields?.property_groups || '').split(',').map((value) => value.trim()).filter(Boolean))
  }
  return categoryBarOption(countBy(values), '#16a34a')
})

const materialTrendOption = computed(() => trendOption(materialAnalysisRecords.value, '#0891b2'))
const computationStatusOption = computed(() => pieOption(countBy(computationAnalysisRecords.value.map((item) => item.status || 'unknown'))))
const computationWorkflowOption = computed(() => categoryBarOption(countBy(
  computationAnalysisRecords.value.map((item) => item.preview_fields?.workflow_type || 'unknown'),
), '#d97706'))
const artifactTypeOption = computed(() => categoryBarOption(countBy(
  artifactAnalysisRecords.value.map((item) => item.preview_fields?.artifact_type || 'unknown'),
), '#64748b'))

function axis(type, extra = {}) {
  return {
    type,
    axisLabel: { color: '#64748b' },
    splitLine: { lineStyle: { color: '#e2e8f0' } },
    ...extra,
  }
}

function barOption(labels, values, color, labelOptions = {}) {
  return {
    color: [color],
    grid: { left: 48, right: 18, top: 18, bottom: 42 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: '#64748b', ...labelOptions },
    },
    yAxis: axis('value'),
    series: [{ type: 'bar', data: values, barWidth: 18, itemStyle: { borderRadius: [4, 4, 0, 0] } }],
  }
}

function categoryBarOption(counts, color) {
  const entries = Object.entries(counts)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 10)
  return {
    color: [color],
    grid: { left: 104, right: 18, top: 18, bottom: 32 },
    tooltip: { trigger: 'axis' },
    xAxis: axis('value'),
    yAxis: {
      type: 'category',
      data: entries.map(([name]) => name),
      axisLabel: { color: '#64748b', width: 92, overflow: 'truncate' },
    },
    series: [{ type: 'bar', data: entries.map(([, value]) => value), barWidth: 14, itemStyle: { borderRadius: [0, 4, 4, 0] } }],
  }
}

function histogramOption(field, color) {
  const bins = mdAllatomProfile.value?.numeric_histograms?.[field] || []
  return barOption(
    bins.map((bin) => `${bin.start}-${bin.end}`),
    bins.map((bin) => bin.count),
    color,
    { rotate: 24 },
  )
}

function pieOption(counts) {
  return {
    color: ['#16a34a', '#d97706', '#dc2626', '#64748b', '#3b82f6'],
    tooltip: { trigger: 'item' },
    series: [{
      type: 'pie',
      radius: ['52%', '76%'],
      label: { formatter: '{b} {c}' },
      data: Object.entries(counts).map(([name, value]) => ({ name, value })),
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
  return barOption(Object.keys(counts), Object.values(counts), color)
}

function countBy(values) {
  const counts = {}
  for (const value of values) {
    const key = value || 'unknown'
    counts[key] = (counts[key] || 0) + 1
  }
  return counts
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

function formatNumber(value) {
  if (value === null || value === undefined || value === '') return '-'
  return Number(value).toLocaleString()
}

function formatPercent(value) {
  if (value === null || value === undefined || value === '') return '-'
  return `${Number(value).toFixed(Number(value) < 1 && Number(value) > 0 ? 4 : 2)}%`
}

async function loadAnalysisData() {
  loading.value = true
  try {
    const [datasetData, mongoData, pi1mProfileResult, pi1mSamplesResult, mdProfileResult] = await Promise.allSettled([
      listDataCatalogDatasets(),
      listDataCatalogMongoCollections(),
      getDataCatalogDatasetProfile('pi1m_v2'),
      getDataCatalogDatasetVisualSamples('pi1m_v2', { limit: 5000 }),
      getDataCatalogDatasetProfile('md_allatom'),
    ])
    datasets.value = datasetData.status === 'fulfilled' ? (datasetData.value.items || []) : []
    mongoCollections.value = mongoData.status === 'fulfilled' ? (mongoData.value.items || []) : []
    pi1mProfile.value = pi1mProfileResult.status === 'fulfilled' ? pi1mProfileResult.value : null
    pi1mVisualSamples.value = pi1mSamplesResult.status === 'fulfilled' ? pi1mSamplesResult.value : { points: [], sample_count: 0, total: 0 }
    mdAllatomProfile.value = mdProfileResult.status === 'fulfilled' ? mdProfileResult.value : null
    await loadRecordSamples()
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function loadRecordSamples() {
  if (!canDrilldownRecords.value) {
    materialAnalysisRecords.value = []
    computationAnalysisRecords.value = []
    artifactAnalysisRecords.value = []
    return
  }
  const materialCollectionName = materialCollection.value?.collection_key || materialCollection.value?.collection_name || ''
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

function openCatalogPage() {
  router.push('/database/data-catalog')
}

onMounted(loadAnalysisData)
</script>

<template>
  <div class="data-analysis-page" v-loading="loading">
    <header class="analysis-header">
      <div>
        <h1>数据分析</h1>
        <p>PI1M、MD-AllAtom、材料数据和计算数据的细节视图。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="FolderOpened" @click="openCatalogPage">数据目录</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="loadAnalysisData">刷新</el-button>
      </div>
    </header>

    <AttributionBanner module-id="data_catalog" label="数据来源" compact />

    <section class="metric-grid" aria-label="数据分析关键指标">
      <article v-for="metric in headlineMetrics" :key="metric.key" class="metric-panel">
        <el-icon><component :is="metric.icon" /></el-icon>
        <div>
          <span>{{ metric.label }}</span>
          <strong>{{ metric.value }}</strong>
          <small>{{ metric.meta }}</small>
        </div>
      </article>
    </section>

    <el-tabs v-model="activeTab" class="analysis-tabs">
      <el-tab-pane label="PI1M v2" name="pi1m" lazy>
        <section class="analysis-section">
          <div class="section-heading">
            <h2>PI1M v2 全量结构库</h2>
            <span>{{ formatNumber(pi1mProfile?.record_count || pi1mDataset?.record_count || 0) }} / {{ formatNumber(pi1mDataset?.row_count || 0) }} 条</span>
          </div>
          <div class="summary-grid">
            <div class="summary-item"><span>入库覆盖率</span><strong>{{ formatPercent(pi1mProfile?.coverage_percent) }}</strong></div>
            <div class="summary-item"><span>唯一结构</span><strong>{{ formatNumber(pi1mProfile?.unique_smiles_count) }}</strong></div>
            <div class="summary-item"><span>重复结构</span><strong>{{ formatNumber(pi1mProfile?.duplicate_smiles_count) }}</strong></div>
            <div class="summary-item"><span>抽样点</span><strong>{{ formatNumber(pi1mVisualSamples.sample_count) }}</strong></div>
          </div>
          <div class="visual-grid two-column">
            <div class="visual-panel">
              <h3>SA Score 分布</h3>
              <v-chart class="chart-large" :option="pi1mSaHistogramOption" autoresize />
            </div>
            <div class="visual-panel">
              <h3>结构空间抽样</h3>
              <v-chart class="chart-large" :option="pi1mMapOption" autoresize />
            </div>
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="MD-AllAtom" name="md-allatom" lazy>
        <section class="analysis-section">
          <div class="section-heading">
            <h2>MD-AllAtom</h2>
            <span>{{ formatNumber(mdAllatomProfile?.record_count || mdAllatomDataset?.record_count || 0) }} 条碳基结果</span>
          </div>
          <template v-if="mdAllatomHasData">
            <div class="summary-grid">
              <div class="summary-item"><span>原始文件索引</span><strong>{{ formatNumber(mdAllatomProfile?.asset_coverage?.file_count || 0) }}</strong></div>
              <div v-for="row in fileCoverageRows" :key="row.family" class="summary-item">
                <span>{{ row.family }} 文件</span>
                <strong>{{ formatNumber(row.count) }}</strong>
              </div>
            </div>
            <div class="visual-grid three-column">
              <div class="visual-panel">
                <h3>C/F/Si 文件</h3>
                <v-chart class="chart-medium" :option="mdFamilyFilesOption" autoresize />
              </div>
              <div class="visual-panel">
                <h3>温度分布</h3>
                <v-chart class="chart-medium" :option="mdTemperatureOption" autoresize />
              </div>
              <div class="visual-panel">
                <h3>聚合度分布</h3>
                <v-chart class="chart-medium" :option="mdDpOption" autoresize />
              </div>
            </div>
            <div class="visual-grid three-column">
              <div class="visual-panel">
                <h3>e2e_mean</h3>
                <v-chart class="chart-medium" :option="mdE2eOption" autoresize />
              </div>
              <div class="visual-panel">
                <h3>rg_mean</h3>
                <v-chart class="chart-medium" :option="mdRgOption" autoresize />
              </div>
              <div class="visual-panel">
                <h3>persist_len_mean</h3>
                <v-chart class="chart-medium" :option="mdPersistOption" autoresize />
              </div>
            </div>
            <div class="visual-panel">
              <h3>温度 / e2e_mean 抽样</h3>
              <v-chart class="chart-wide" :option="mdScatterOption" autoresize />
            </div>
          </template>
          <el-empty v-else description="MD-AllAtom 统计数据尚未导入，先补充碳基结果和 dataset_stats 后再展示分析图。" />
        </section>
      </el-tab-pane>

      <el-tab-pane label="材料数据" name="materials" lazy>
        <section class="analysis-section">
          <div class="section-heading">
            <h2>材料数据分级</h2>
            <span>近 {{ materialAnalysisRecords.length }} 条样本</span>
          </div>
          <div v-if="canDrilldownRecords && materialAnalysisRecords.length" class="visual-grid three-column">
            <div class="visual-panel">
              <h3>数据集来源</h3>
              <v-chart class="chart-medium" :option="materialDatasetOption" autoresize />
            </div>
            <div class="visual-panel">
              <h3>物性类别覆盖</h3>
              <v-chart class="chart-medium" :option="materialPropertyOption" autoresize />
            </div>
            <div class="visual-panel">
              <h3>导入趋势</h3>
              <v-chart class="chart-medium" :option="materialTrendOption" autoresize />
            </div>
          </div>
          <el-empty v-else description="暂无可分析的材料样本或当前账号无下钻权限" />
        </section>
      </el-tab-pane>

      <el-tab-pane label="计算数据" name="computations" lazy>
        <section class="analysis-section">
          <div class="section-heading">
            <h2>计算数据分析</h2>
            <span>近 {{ computationAnalysisRecords.length }} 条任务样本</span>
          </div>
          <div v-if="canDrilldownRecords && (computationAnalysisRecords.length || artifactAnalysisRecords.length)" class="visual-grid three-column">
            <div class="visual-panel">
              <h3>任务状态</h3>
              <v-chart class="chart-medium" :option="computationStatusOption" autoresize />
            </div>
            <div class="visual-panel">
              <h3>Workflow 分布</h3>
              <v-chart class="chart-medium" :option="computationWorkflowOption" autoresize />
            </div>
            <div class="visual-panel">
              <h3>产物类型</h3>
              <v-chart class="chart-medium" :option="artifactTypeOption" autoresize />
            </div>
          </div>
          <el-empty v-else description="暂无可分析的计算样本或当前账号无下钻权限" />
        </section>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.data-analysis-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: calc(100vh - 96px);
}

.analysis-header,
.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.analysis-header h1,
.analysis-section h2,
.visual-panel h3 {
  margin: 0;
  color: var(--app-ink);
  letter-spacing: 0;
}

.analysis-header h1 {
  font-size: 24px;
  line-height: 1.2;
}

.analysis-header p {
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
.analysis-section,
.summary-item,
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
.metric-panel small,
.summary-item span,
.section-heading span {
  display: block;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.metric-panel strong {
  display: block;
  margin: 3px 0;
  color: var(--app-ink);
  font-size: 20px;
  line-height: 1.15;
  overflow-wrap: anywhere;
}

.analysis-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}

.analysis-section h2 {
  font-size: 16px;
}

.summary-grid,
.visual-grid {
  display: grid;
  gap: 12px;
}

.summary-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.summary-item {
  min-width: 0;
  padding: 12px;
  box-shadow: none;
}

.summary-item strong {
  display: block;
  margin-top: 5px;
  color: var(--app-ink);
  font-size: 17px;
  line-height: 1.3;
  overflow-wrap: anywhere;
}

.two-column {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.three-column {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.visual-panel {
  min-width: 0;
  padding: 12px;
  box-shadow: none;
}

.visual-panel h3 {
  margin-bottom: 6px;
  font-size: 13px;
}

.chart-large,
.chart-wide {
  width: 100%;
  height: 300px;
}

.chart-medium {
  width: 100%;
  height: 220px;
}

@media (max-width: 1280px) {
  .metric-grid,
  .summary-grid,
  .two-column,
  .three-column {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .analysis-header,
  .section-heading {
    flex-direction: column;
  }

  .header-actions {
    justify-content: flex-start;
  }

  .metric-grid,
  .summary-grid,
  .two-column,
  .three-column {
    grid-template-columns: 1fr;
  }
}
</style>
