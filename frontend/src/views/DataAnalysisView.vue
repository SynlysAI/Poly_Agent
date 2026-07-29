<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowRight, DataAnalysis, Files, FolderOpened, Refresh } from '@element-plus/icons-vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, LineChart, PieChart, ScatterChart } from 'echarts/charts'
import {
  GridComponent, LegendComponent, TitleComponent, TooltipComponent, VisualMapComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

import {
  getApiErrorMessage,
  getDataCatalogCollectionAnalysis,
  getDataCatalogDatasetProfile,
  getDataCatalogDatasetVisualSamples,
  listDataCatalogCollectionRecords,
  listDataCatalogDatasets,
  listDataCatalogMongoCollections,
} from '../api/polyAgentApi'
import AttributionBanner from '../components/attribution/AttributionBanner.vue'
import {
  POLY_DATASET_IDS,
  buildPolyDataDatasetGroups,
  polyDataDatasetGroupCount,
} from '../utils/polyDataDatasetGroups'
import { normalizeCollectionAnalysis } from '../utils/dataCatalogAnalysis'

use([
  BarChart,
  LineChart,
  PieChart,
  ScatterChart,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
  CanvasRenderer,
])

const router = useRouter()
const loading = ref(false)
const activeTab = ref('poly-data')
const activePolyDataGroup = ref('structure')
const activeGroupAnalysisView = ref('overview')
const activeTableAnalysisCollectionKey = ref('')
const collectionAnalysisCache = ref({})
const collectionAnalysisLoading = ref(false)
const collectionAnalysisError = ref('')
const collectionAnalysisSampleSize = ref(1000)
const expandedFocusPanels = ref([])
const activeGroupChartsVisible = ref(false)
const datasets = ref([])
const mongoCollections = ref([])
const pi1mProfile = ref(null)
const pi1mVisualSamples = ref({ points: [], sample_count: 0, total: 0 })
const pi1mVisualSampleCache = ref({})
const mdAllatomProfile = ref(null)
const allDatasetProfiles = ref({})
const extraDatasetProfiles = ref({})
const polyDataCollectionSamples = ref({})
const materialAnalysisRecords = ref([])
const computationAnalysisRecords = ref([])
const artifactAnalysisRecords = ref([])
const pi1mSampleLimit = ref(1000)
const recordSampleSize = ref(100)
const profileSampleDisplayLimit = ref(1000)
const profileLoading = ref(false)
const pi1mVisualLoading = ref(false)
const materialSamplesLoaded = ref(false)
const computationSamplesLoaded = ref(false)
const groupSampleLoading = ref(false)

const PI1M_SA_COLOR_SCALE = ['#15803d', '#84cc16', '#facc15', '#f97316', '#dc2626']
const GROUP_ANALYSIS_VIEWS = [
  { key: 'overview', label: '总览' },
  { key: 'quality', label: '字段质量' },
  { key: 'samples', label: '样本分布' },
  { key: 'focus', label: '重点分析' },
  { key: 'table-analysis', label: '表分析' },
]
const EXTRA_DATASET_IDS = [
  'omg',
  'omg_physical_properties',
  'polyone',
  'toporg',
  'polysol',
  'polyomics',
  'pppdb',
  'polyid',
  'tropic',
  'nanomine',
]
const POLY_DATA_COLLECTION_ORDER = [
  'poly_data.material_records',
  'poly_data.radonpy_records',
  'poly_data.pi1m_samples',
  'poly_data.smipoly_monomers',
  'poly_data.polyuniverse_monomers',
  'poly_data.md_allatom_files',
  'poly_data.md_allatom_diamines',
  'poly_data.md_allatom_dianhydrides',
  'poly_data.md_allatom_carbon_results',
  'poly_data.omg_polymers',
  'poly_data.omg_physical_properties_records',
  'poly_data.polyone_smiles',
  'poly_data.toporg_records',
  'poly_data.polysol_records',
  'poly_data.polyomics_records',
  'poly_data.pppdb_records',
  'poly_data.polyid_records',
  'poly_data.tropic_records',
  'poly_data.nanomine_records',
]
const POLY_DATA_COLLECTION_GROUPS = {
  structure: [
    'poly_data.smipoly_monomers',
    'poly_data.toporg_records',
    'poly_data.polyid_records',
    'poly_data.nanomine_records',
  ],
  simulation: [
    'poly_data.radonpy_records',
    'poly_data.md_allatom_files',
    'poly_data.md_allatom_diamines',
    'poly_data.md_allatom_dianhydrides',
    'poly_data.md_allatom_carbon_results',
    'poly_data.polyomics_records',
  ],
  properties: [
    'poly_data.material_records',
    'poly_data.omg_physical_properties_records',
    'poly_data.polysol_records',
    'poly_data.pppdb_records',
    'poly_data.tropic_records',
  ],
  synthesis: [
    'poly_data.omg_polymers',
  ],
  generated: [
    'poly_data.pi1m_samples',
    'poly_data.polyuniverse_monomers',
    'poly_data.polyone_smiles',
  ],
}

const pi1mDataset = computed(() => datasets.value.find((item) => item.dataset_id === 'pi1m_v2') || null)
const mdAllatomDataset = computed(() => datasets.value.find((item) => item.dataset_id === 'md_allatom') || null)
const polyDataDatasets = computed(() => {
  const byId = new Map(datasets.value.map((item) => [item.dataset_id, item]))
  return POLY_DATASET_IDS.map((datasetId) => byId.get(datasetId)).filter(Boolean)
})
const polyDataDatasetGroups = computed(() => buildPolyDataDatasetGroups(datasets.value, { includeEmpty: true }))
const visiblePolyDataGroups = computed(() => polyDataDatasetGroups.value.filter((group) => group.items.length))
const activeDatasetGroup = computed(() => (
  polyDataDatasetGroups.value.find((group) => group.key === activePolyDataGroup.value)
  || visiblePolyDataGroups.value[0]
  || null
))
const activeGroupDatasetRows = computed(() => (activeDatasetGroup.value?.items || []).map((dataset) => {
  const profile = datasetProfileFor(dataset.dataset_id)
  return {
    dataset_id: dataset.dataset_id,
    display_name: dataset.display_name,
    description: dataset.description,
    source_category: dataset.source_category,
    confidence_label: dataset.confidence_label,
    row_count: Number(profile?.row_count || dataset.row_count || 0),
    record_count: Number(profile?.record_count || dataset.record_count || 0),
    coverage_percent: profile?.coverage_percent ?? dataset.coverage_percent,
    record_mode: profile?.record_mode || dataset.record_mode,
    verification_status: profile?.verification_status || dataset.verification_status,
    field_count: profile?.field_completeness?.length || dataset.field_summaries?.length || 0,
    field_summaries: profile?.field_completeness || dataset.field_summaries || [],
  }
}))
const activeGroupHasPi1m = computed(() => activeGroupDatasetRows.value.some((row) => row.dataset_id === 'pi1m_v2'))
const activeGroupHasMdAllatom = computed(() => activeGroupDatasetRows.value.some((row) => row.dataset_id === 'md_allatom'))
const activeGroupSummary = computed(() => ({
  datasets: activeGroupDatasetRows.value.length,
  rows: activeGroupDatasetRows.value.reduce((sum, row) => sum + row.row_count, 0),
  records: activeGroupDatasetRows.value.reduce((sum, row) => sum + row.record_count, 0),
  fields: activeGroupDatasetRows.value.reduce((sum, row) => sum + row.field_count, 0),
}))
const activeGroupDatasetIds = computed(() => activeGroupDatasetRows.value.map((row) => row.dataset_id))
const extraOpenDatasets = computed(() => datasets.value.filter((item) => EXTRA_DATASET_IDS.includes(item.dataset_id)))
const polyDataCollections = computed(() => {
  const byKey = new Map(mongoCollections.value.map((item) => [collectionIdentity(item), item]))
  const ordered = POLY_DATA_COLLECTION_ORDER.map((key) => byKey.get(key)).filter(Boolean)
  const orderedKeys = new Set(ordered.map((item) => collectionIdentity(item)))
  const remaining = mongoCollections.value.filter((item) => collectionIdentity(item).startsWith('poly_data.') && !orderedKeys.has(collectionIdentity(item)))
  return [...ordered, ...remaining]
})
const activeGroupCollectionKeys = computed(() => POLY_DATA_COLLECTION_GROUPS[activePolyDataGroup.value] || [])
const activeGroupCollectionRows = computed(() => {
  const keys = new Set(activeGroupCollectionKeys.value)
  return polyDataCollectionRows.value.filter((row) => keys.has(row.collection_key))
})
const activeTableAnalysisCollection = computed(() => activeGroupCollectionRows.value.find(
  (row) => row.collection_key === activeTableAnalysisCollectionKey.value,
) || activeGroupCollectionRows.value[0] || null)
const activeTableAnalysis = computed(() => (
  activeTableAnalysisCollection.value
    ? collectionAnalysisCache.value[activeTableAnalysisCollection.value.collection_key] || null
    : null
))
const activeTableNumericFields = computed(() => (
  (activeTableAnalysis.value?.field_stats || []).filter((field) => field.value_type === 'number' && Object.keys(field.numeric_summary || {}).length)
))
const activeTableCategoryFields = computed(() => (
  (activeTableAnalysis.value?.field_stats || []).filter((field) => field.top_values?.length && field.value_type !== 'number')
))
const activeTableNumericSummaryOption = computed(() => barOption(
  activeTableNumericFields.value.slice(0, 8).map((field) => field.label || field.field),
  activeTableNumericFields.value.slice(0, 8).map((field) => Number(field.numeric_summary?.mean || 0)),
  '#0891b2',
  { rotate: 26 },
))
const activeTableCategoryOption = computed(() => {
  const field = activeTableCategoryFields.value[0]
  return field ? categoryBarOption(Object.fromEntries(field.top_values.map((item) => [item.value, item.count])), '#d97706') : emptyChartOption('暂无类别分布')
})
const activeTableCorrelationOption = computed(() => {
  const rows = activeTableAnalysis.value?.correlations || []
  if (!rows.length) return emptyChartOption('暂无足够样本计算相关性')
  return barOption(
    rows.slice(0, 8).map((row) => `${row.field_x} · ${row.field_y}`),
    rows.slice(0, 8).map((row) => row.coefficient),
    '#7c3aed',
    { rotate: 30 },
  )
})
const activeGroupCollectionSamples = computed(() => (
  activeGroupCollectionRows.value.flatMap((row) => row.samples || [])
))
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
    key: 'open-datasets',
    label: '开放数据集',
    value: formatNumber(extraOpenDatasets.value.length),
    meta: `${formatNumber(extraOpenDatasets.value.reduce((sum, item) => sum + Number(item.record_count || 0), 0))} 条 Mongo 记录`,
    icon: FolderOpened,
  },
  {
    key: 'materials',
    label: '材料样本',
    value: formatNumber(materialAnalysisRecords.value.length),
    meta: `近 ${formatNumber(recordSampleSize.value)} 条`,
    icon: Files,
  },
])

const polyDataDatasetRows = computed(() => polyDataDatasets.value.map((dataset) => {
  const profile = datasetProfileFor(dataset.dataset_id)
  return {
    dataset_id: dataset.dataset_id,
    display_name: dataset.display_name,
    source_category: dataset.source_category,
    row_count: Number(profile?.row_count || dataset.row_count || 0),
    record_count: Number(profile?.record_count || dataset.record_count || 0),
    coverage_percent: profile?.coverage_percent ?? dataset.coverage_percent,
    record_mode: profile?.record_mode || dataset.record_mode,
    verification_status: profile?.verification_status || dataset.verification_status,
    field_count: profile?.field_completeness?.length || dataset.field_summaries?.length || 0,
    field_summaries: dataset.field_summaries || [],
    has_stats: hasProfileStats(profile),
    sample_count: datasetSamplePoints(dataset.dataset_id, profile).length,
  }
}))

const polyDataCollectionRows = computed(() => polyDataCollections.value.map((collection) => {
  const collectionKey = collectionIdentity(collection)
  const samples = polyDataCollectionSamples.value[collectionKey] || []
  return {
    collection_key: collectionKey,
    collection_name: collection.collection_name,
    display_name: collection.display_name,
    data_domain: collection.data_domain,
    description: collection.description,
    status: collection.status,
    count: Number(collection.count || 0),
    sample_count: samples.length,
    sample_fields: collection.sample_fields || [],
    analysis_facets: collection.analysis_facets || [],
    samples,
  }
}))

const polyDataCoverageOption = computed(() => barOption(
  polyDataDatasetRows.value.map((row) => row.display_name),
  polyDataDatasetRows.value.map((row) => Number(row.coverage_percent || 0)),
  '#3b82f6',
  { rotate: 28 },
))

const polyDataCollectionRecordOption = computed(() => barOption(
  polyDataCollectionRows.value.map((row) => collectionShortName(row)),
  polyDataCollectionRows.value.map((row) => row.count),
  '#16a34a',
  { rotate: 28 },
))

const polyDataStatusOption = computed(() => pieOption(countBy(
  polyDataDatasetRows.value.map((row) => row.verification_status || 'unknown'),
)))

const activeGroupRecordOption = computed(() => barOption(
  activeGroupDatasetRows.value.map((row) => row.display_name),
  activeGroupDatasetRows.value.map((row) => row.record_count),
  '#16a34a',
  { rotate: 24 },
))

const activeGroupCoverageOption = computed(() => barOption(
  activeGroupDatasetRows.value.map((row) => row.display_name),
  activeGroupDatasetRows.value.map((row) => Number(row.coverage_percent || 0)),
  '#3b82f6',
  { rotate: 24 },
))

const activeGroupFieldCompletenessOption = computed(() => barOption(
  activeGroupDatasetRows.value.map((row) => row.display_name),
  activeGroupDatasetRows.value.map((row) => averageFieldCompleteness(row.field_summaries)),
  '#64748b',
  { rotate: 24 },
))

const activeGroupVerificationOption = computed(() => pieOption(countBy(
  activeGroupDatasetRows.value.map((row) => row.verification_status || 'unknown'),
)))

const activeGroupRecordModeOption = computed(() => pieOption(countBy(
  activeGroupDatasetRows.value.map((row) => row.record_mode || 'unknown'),
)))

const activeGroupCollectionRecordOption = computed(() => barOption(
  activeGroupCollectionRows.value.map((row) => collectionShortName(row)),
  activeGroupCollectionRows.value.map((row) => row.count),
  '#0891b2',
  { rotate: 24 },
))

const activeGroupSampleFacetOption = computed(() => {
  const samples = activeGroupCollectionSamples.value
  if (!samples.length) return emptyChartOption('暂无样本分布')
  const counts = {}
  for (const row of activeGroupCollectionRows.value) {
    const field = detectCollectionDistributionField(row.samples)
    if (!field) continue
    for (const sample of row.samples) {
      const value = sample.preview_fields?.[field] || sample[field] || 'unknown'
      const label = `${field}: ${value}`
      counts[label] = (counts[label] || 0) + 1
    }
  }
  return Object.keys(counts).length ? categoryBarOption(counts, '#16a34a') : emptyChartOption('暂无样本分布')
})

const activeGroupSampleTrendOption = computed(() => (
  activeGroupCollectionSamples.value.length
    ? trendOption(activeGroupCollectionSamples.value, '#d97706')
    : emptyChartOption('暂无导入趋势')
))

const activeGroupTopFieldRows = computed(() => {
  const fields = []
  for (const row of activeGroupDatasetRows.value) {
    for (const field of row.field_summaries || []) {
      const total = Number(field.total_count || row.row_count || 0)
      const nonEmpty = Number(field.non_empty_count || 0)
      fields.push({
        dataset: row.display_name,
        label: field.label || field.canonical_name || field.raw_name || '-',
        completeness: total ? Number(((nonEmpty / total) * 100).toFixed(2)) : 0,
      })
    }
  }
  return fields
    .sort((a, b) => a.completeness - b.completeness)
    .slice(0, 8)
})

const activeGroupTopFieldsOption = computed(() => {
  if (!activeGroupTopFieldRows.value.length) return emptyChartOption('暂无字段完整度')
  return barOption(
    activeGroupTopFieldRows.value.map((row) => `${row.dataset} · ${row.label}`),
    activeGroupTopFieldRows.value.map((row) => row.completeness),
    '#d97706',
    { rotate: 32 },
  )
})

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
  const points = (mdAllatomProfile.value?.analysis_samples || []).slice(0, profileSampleDisplayLimit.value)
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

const extraDatasetRows = computed(() => extraOpenDatasets.value.map((dataset) => {
  const profile = extraDatasetProfiles.value[dataset.dataset_id] || {}
  return {
    dataset_id: dataset.dataset_id,
    display_name: dataset.display_name,
    row_count: Number(dataset.row_count || 0),
    record_count: Number(profile.record_count || dataset.record_count || 0),
    coverage_percent: profile.coverage_percent,
    record_mode: dataset.record_mode,
    source_category: dataset.source_category,
    field_count: dataset.field_summaries?.length || 0,
  }
}))

const extraCoverageOption = computed(() => barOption(
  extraDatasetRows.value.map((row) => row.display_name),
  extraDatasetRows.value.map((row) => Number(row.coverage_percent || 0)),
  '#3b82f6',
  { rotate: 28 },
))

const extraRecordOption = computed(() => barOption(
  extraDatasetRows.value.map((row) => row.display_name),
  extraDatasetRows.value.map((row) => row.record_count),
  '#16a34a',
  { rotate: 28 },
))

const extraSourceFileOption = computed(() => {
  const counts = {}
  for (const profile of Object.values(extraDatasetProfiles.value)) {
    const sourceCounts = profile?.category_counts?.source_file || {}
    for (const [name, count] of Object.entries(sourceCounts)) {
      counts[name] = (counts[name] || 0) + Number(count || 0)
    }
  }
  return categoryBarOption(counts, '#d97706')
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

function datasetProfileFor(datasetId) {
  if (datasetId === 'pi1m_v2' && pi1mProfile.value) return pi1mProfile.value
  if (datasetId === 'md_allatom' && mdAllatomProfile.value) return mdAllatomProfile.value
  return allDatasetProfiles.value[datasetId] || null
}

function hasProfileStats(profile) {
  if (!profile) return false
  return Boolean(
    (profile.sa_score_histogram?.length || 0) > 0
    || Object.keys(profile.numeric_histograms || {}).length > 0
    || Object.keys(profile.category_counts || {}).length > 0
    || (profile.analysis_samples?.length || 0) > 0,
  )
}

function datasetSamplePoints(datasetId, profile) {
  if (datasetId === 'pi1m_v2') {
    return (pi1mVisualSamples.value.points || []).slice(0, profileSampleDisplayLimit.value)
  }
  return (profile?.analysis_samples || []).slice(0, profileSampleDisplayLimit.value)
}

function firstHistogramEntry(profile) {
  if (profile?.sa_score_histogram?.length) {
    return ['SA Score', profile.sa_score_histogram]
  }
  const entries = Object.entries(profile?.numeric_histograms || {})
  return entries.find(([, bins]) => Array.isArray(bins) && bins.length) || null
}

function firstCategoryEntry(profile) {
  const entries = Object.entries(profile?.category_counts || {})
  return entries.find(([, counts]) => counts && Object.keys(counts).length) || null
}

function datasetHistogramOption(profile, color = '#3b82f6') {
  const entry = firstHistogramEntry(profile)
  if (!entry) return emptyChartOption('暂无数值直方图')
  const [, bins] = entry
  return barOption(
    bins.map((bin) => `${bin.start}-${bin.end}`),
    bins.map((bin) => bin.count),
    color,
    { rotate: 24 },
  )
}

function datasetCategoryOption(profile, color = '#d97706') {
  const entry = firstCategoryEntry(profile)
  if (!entry) return emptyChartOption('暂无类别分布')
  return categoryBarOption(entry[1], color)
}

function datasetScatterOption(datasetId, profile) {
  const points = datasetSamplePoints(datasetId, profile)
    .map((item) => {
      if (datasetId === 'pi1m_v2') {
        return [toFiniteNumber(item.x), toFiniteNumber(item.y), item.record_id, item.sa_score]
      }
      return [
        toFiniteNumber(item.x ?? item.row_index),
        toFiniteNumber(item.y),
        item.record_id,
        item.category || item.source_file || item.title || '',
      ]
    })
    .filter((item) => item[0] !== null && item[1] !== null)
  if (!points.length) return emptyChartOption('暂无抽样散点')
  return {
    grid: { left: 42, right: 18, top: 18, bottom: 34 },
    tooltip: {
      trigger: 'item',
      formatter: ({ data }) => [
        data[2] || '-',
        `x：${formatNumber(data[0])}`,
        `y：${formatNumber(data[1])}`,
        data[3] === null || data[3] === undefined || data[3] === '' ? '' : `标注：${data[3]}`,
      ].filter(Boolean).join('<br/>'),
    },
    xAxis: axis('value'),
    yAxis: axis('value'),
    series: [{ type: 'scatter', symbolSize: 6, data: points, itemStyle: { color: '#0891b2', opacity: 0.72 } }],
  }
}

function datasetFallbackOption(dataset) {
  const profile = datasetProfileFor(dataset.dataset_id)
  const fields = profile?.field_completeness || dataset.field_summaries || []
  if (!fields.length) return emptyChartOption('暂无字段完整度')
  return barOption(
    fields.slice(0, 8).map((field) => field.label || field.canonical_name || field.raw_name),
    fields.slice(0, 8).map((field) => {
      const total = Number(field.total_count || 0)
      return total ? Number(((Number(field.non_empty_count || 0) / total) * 100).toFixed(2)) : 0
    }),
    '#64748b',
    { rotate: 24 },
  )
}

function averageFieldCompleteness(fields = []) {
  const validFields = fields
    .map((field) => {
      const total = Number(field.total_count || 0)
      return total ? (Number(field.non_empty_count || 0) / total) * 100 : null
    })
    .filter((value) => value !== null)
  if (!validFields.length) return 0
  return Number((validFields.reduce((sum, value) => sum + value, 0) / validFields.length).toFixed(2))
}

function collectionSampleOption(row) {
  const field = detectCollectionDistributionField(row.samples)
  if (!field) return emptyChartOption('暂无样本分布')
  const counts = countBy(row.samples.map((item) => item.preview_fields?.[field] || item[field] || 'unknown'))
  return categoryBarOption(counts, '#3b82f6')
}

function detectCollectionDistributionField(items) {
  const candidates = [
    'dataset',
    'monomer_class',
    'source_file',
    'family',
    'extension',
    'sync_status',
    'status',
    'workflow_type',
    'artifact_type',
  ]
  return candidates.find((field) => items.some((item) => item.preview_fields?.[field] || item[field]))
}

function emptyChartOption(text) {
  return {
    title: {
      text,
      left: 'center',
      top: 'middle',
      textStyle: { color: '#94a3b8', fontSize: 12, fontWeight: 400 },
    },
    xAxis: { show: false },
    yAxis: { show: false },
    series: [],
  }
}

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
    grid: { left: 48, right: 18, top: 18, bottom: labelOptions.rotate ? 66 : 42 },
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

function collectionIdentity(collection) {
  return collection?.collection_key || collection?.collection_name || ''
}

function collectionShortName(row) {
  return String(row.collection_key || row.collection_name || '').replace(/^poly_data\./, '')
}

function statusTagType(status) {
  if (status === 'verified' || status === 'ready') return 'success'
  if (status === 'partial' || status === 'running' || status === 'sample') return 'warning'
  if (status === 'failed' || status === 'degraded' || status === 'unavailable') return 'danger'
  return 'info'
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
    const [datasetData, mongoData] = await Promise.allSettled([
      listDataCatalogDatasets(),
      listDataCatalogMongoCollections(),
    ])
    datasets.value = datasetData.status === 'fulfilled' ? (datasetData.value.items || []) : []
    mongoCollections.value = mongoData.status === 'fulfilled' ? (mongoData.value.items || []) : []
    scheduleActiveGroupCharts()
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function scheduleActiveGroupCharts() {
  activeGroupChartsVisible.value = false
  await nextTick()
  window.requestAnimationFrame(() => {
    window.requestAnimationFrame(() => {
      activeGroupChartsVisible.value = true
    })
  })
}

async function loadDatasetProfiles(ids = polyDataDatasets.value.map((item) => item.dataset_id)) {
  if (!ids.length) {
    return
  }
  const missingIds = ids.filter((datasetId) => !allDatasetProfiles.value[datasetId])
  if (!missingIds.length) return
  profileLoading.value = true
  const results = await Promise.allSettled(missingIds.map((datasetId) => getDataCatalogDatasetProfile(datasetId)))
  const profiles = { ...allDatasetProfiles.value }
  results.forEach((result, index) => {
    if (result.status === 'fulfilled') {
      profiles[missingIds[index]] = result.value
    }
  })
  allDatasetProfiles.value = profiles
  extraDatasetProfiles.value = Object.fromEntries(
    Object.entries(profiles).filter(([datasetId]) => EXTRA_DATASET_IDS.includes(datasetId)),
  )
  pi1mProfile.value = profiles.pi1m_v2 || null
  mdAllatomProfile.value = profiles.md_allatom || null
  profileLoading.value = false
}

async function ensureDatasetProfile(datasetId) {
  await loadDatasetProfiles([datasetId])
  return allDatasetProfiles.value[datasetId] || null
}

async function ensureMdAllatomProfile() {
  await ensureDatasetProfile('md_allatom')
}

async function ensurePi1mAnalysis({ refreshSamples = false } = {}) {
  await ensureDatasetProfile('pi1m_v2')
  const cacheKey = String(pi1mSampleLimit.value)
  if (!refreshSamples && pi1mVisualSampleCache.value[cacheKey]) {
    pi1mVisualSamples.value = pi1mVisualSampleCache.value[cacheKey]
    return
  }
  if (refreshSamples || !(pi1mVisualSamples.value.points || []).length) {
    await loadPi1mVisualSamples({ force: refreshSamples })
  }
}

async function loadPi1mVisualSamples({ force = false } = {}) {
  const cacheKey = String(pi1mSampleLimit.value)
  if (!force && pi1mVisualSampleCache.value[cacheKey]) {
    pi1mVisualSamples.value = pi1mVisualSampleCache.value[cacheKey]
    return
  }
  pi1mVisualLoading.value = true
  try {
    const result = await getDataCatalogDatasetVisualSamples('pi1m_v2', { limit: pi1mSampleLimit.value })
    pi1mVisualSamples.value = result || { points: [], sample_count: 0, total: 0 }
    pi1mVisualSampleCache.value = {
      ...pi1mVisualSampleCache.value,
      [cacheKey]: pi1mVisualSamples.value,
    }
  } catch {
    pi1mVisualSamples.value = { points: [], sample_count: 0, total: 0 }
  } finally {
    pi1mVisualLoading.value = false
  }
}

async function loadMaterialRecordSamples() {
  if (materialSamplesLoaded.value) return
  const materialCollectionName = materialCollection.value?.collection_key || materialCollection.value?.collection_name || ''
  if (!materialCollectionName) {
    materialAnalysisRecords.value = []
    materialSamplesLoaded.value = true
    return
  }
  const result = await Promise.allSettled([
    listDataCatalogCollectionRecords(materialCollectionName, { page: 1, page_size: recordSampleSize.value }),
  ])
  materialAnalysisRecords.value = result[0].status === 'fulfilled' ? (result[0].value.items || []) : []
  materialSamplesLoaded.value = true
}

async function loadComputationRecordSamples() {
  if (computationSamplesLoaded.value) return
  const requests = [
    listDataCatalogCollectionRecords('computation_runs', { page: 1, page_size: recordSampleSize.value }),
    listDataCatalogCollectionRecords('computation_artifacts', { page: 1, page_size: recordSampleSize.value }),
  ]
  const [computations, artifacts] = await Promise.allSettled(requests)
  computationAnalysisRecords.value = computations.status === 'fulfilled' ? (computations.value.items || []) : []
  artifactAnalysisRecords.value = artifacts.status === 'fulfilled' ? (artifacts.value.items || []) : []
  computationSamplesLoaded.value = true
}

async function loadRecordSamples() {
  await Promise.allSettled([
    loadMaterialRecordSamples(),
    loadComputationRecordSamples(),
  ])
}

async function loadPolyDataCollectionSamples(collectionKeys = activeGroupCollectionKeys.value) {
  const wantedKeys = new Set(collectionKeys)
  const collections = polyDataCollections.value.filter((collection) => wantedKeys.has(collectionIdentity(collection)))
  const missingCollections = collections.filter((collection) => !polyDataCollectionSamples.value[collectionIdentity(collection)])
  if (!missingCollections.length) return
  groupSampleLoading.value = true
  const results = await Promise.allSettled(missingCollections.map((collection) => (
    listDataCatalogCollectionRecords(collectionIdentity(collection), { page: 1, page_size: recordSampleSize.value })
  )))
  const samples = { ...polyDataCollectionSamples.value }
  results.forEach((result, index) => {
    if (result.status === 'fulfilled') {
      samples[collectionIdentity(missingCollections[index])] = result.value.items || []
    }
  })
  polyDataCollectionSamples.value = samples
  groupSampleLoading.value = false
}

function syncActiveTableAnalysisCollection() {
  const rows = activeGroupCollectionRows.value
  if (!rows.some((row) => row.collection_key === activeTableAnalysisCollectionKey.value)) {
    activeTableAnalysisCollectionKey.value = rows[0]?.collection_key || ''
  }
}

async function ensureCollectionAnalysis({ refresh = false } = {}) {
  syncActiveTableAnalysisCollection()
  const collectionKey = activeTableAnalysisCollectionKey.value
  if (!collectionKey) return
  if (!refresh && collectionAnalysisCache.value[collectionKey]) return
  collectionAnalysisLoading.value = true
  collectionAnalysisError.value = ''
  try {
    const result = await getDataCatalogCollectionAnalysis(collectionKey, {
      sample_size: collectionAnalysisSampleSize.value,
      refresh,
    })
    collectionAnalysisCache.value = {
      ...collectionAnalysisCache.value,
      [collectionKey]: normalizeCollectionAnalysis(result),
    }
  } catch (error) {
    collectionAnalysisError.value = getApiErrorMessage(error)
  } finally {
    collectionAnalysisLoading.value = false
  }
}

function datasetGroupCount(key) {
  return polyDataDatasetGroupCount(datasets.value, key)
}

function handleGroupAnalysisViewChange(viewKey) {
  scheduleActiveGroupCharts()
  if (viewKey === 'quality') {
    loadDatasetProfiles(activeGroupDatasetIds.value)
  }
  if (viewKey === 'samples') {
    loadPolyDataCollectionSamples()
  }
  if (viewKey === 'focus') {
    loadDatasetProfiles(activeGroupDatasetIds.value)
    if (activeGroupHasMdAllatom.value) ensureMdAllatomProfile()
  }
  if (viewKey === 'table-analysis') {
    syncActiveTableAnalysisCollection()
    ensureCollectionAnalysis()
  }
}

function handleFocusPanelChange(names) {
  scheduleActiveGroupCharts()
  const panelNames = Array.isArray(names) ? names : [names]
  if (panelNames.includes('pi1m')) {
    ensurePi1mAnalysis()
  }
  if (panelNames.includes('md-allatom')) {
    ensureMdAllatomProfile()
  }
}

function openCatalogPage() {
  router.push('/database/data-catalog')
}

watch(activePolyDataGroup, (groupKey) => {
  expandedFocusPanels.value = []
  activeGroupAnalysisView.value = 'overview'
  activeTableAnalysisCollectionKey.value = ''
  scheduleActiveGroupCharts()
  if (groupKey === 'simulation') {
    ensureMdAllatomProfile()
  }
})

watch(activeGroupCollectionRows, () => {
  syncActiveTableAnalysisCollection()
  if (activeGroupAnalysisView.value === 'table-analysis') ensureCollectionAnalysis()
}, { deep: true })

watch(activeTableAnalysisCollectionKey, () => {
  if (activeGroupAnalysisView.value === 'table-analysis') ensureCollectionAnalysis()
})

watch(activeGroupAnalysisView, handleGroupAnalysisViewChange)

watch(activeTab, (tabName) => {
  if (tabName === 'materials') {
    loadMaterialRecordSamples()
  }
  if (tabName === 'computations') {
    loadComputationRecordSamples()
  }
})

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

    <el-tabs v-model="activeTab" class="analysis-tabs">
      <el-tab-pane label="Poly Data" name="poly-data" lazy>
        <section class="analysis-section">
          <div class="section-heading">
            <div>
              <h2>Poly Data 数据集</h2>
              <p class="section-description">按数据用途分组管理，聚合同类数据集后再查看重点分析。</p>
            </div>
            <span>{{ formatNumber(polyDataDatasets.length) }} 个数据集 / {{ formatNumber(polyDataCollectionRows.length) }} 张表</span>
          </div>

          <div class="dataset-browser-layout">
            <nav class="dataset-rail" aria-label="Poly Data 数据分类">
              <div class="dataset-rail-label">数据分类</div>
              <button
                v-for="group in visiblePolyDataGroups"
                :key="group.key"
                type="button"
                class="dataset-filter"
                :class="[`tone-${group.tone}`, { active: activePolyDataGroup === group.key }]"
                @click="activePolyDataGroup = group.key"
              >
                <span>{{ group.label }}</span><strong>{{ datasetGroupCount(group.key) }}</strong>
              </button>
            </nav>

            <div class="dataset-group-stack">
              <section v-if="activeDatasetGroup" class="dataset-group" :class="`tone-${activeDatasetGroup.tone}`">
                <header class="dataset-group-header">
                  <div class="dataset-group-title">
                    <span class="dataset-group-marker" aria-hidden="true"></span>
                    <div>
                      <h3>{{ activeDatasetGroup.label }}</h3>
                      <p>{{ activeDatasetGroup.description }}</p>
                    </div>
                  </div>
                  <span class="dataset-group-count">{{ activeGroupSummary.datasets }} 个数据集</span>
                </header>

                <div class="summary-grid grouped-summary">
                  <div class="summary-item"><span>登记原始行数</span><strong>{{ formatNumber(activeGroupSummary.rows) }}</strong></div>
                  <div class="summary-item"><span>Mongo 入库记录</span><strong>{{ formatNumber(activeGroupSummary.records) }}</strong></div>
                  <div class="summary-item"><span>字段总数</span><strong>{{ formatNumber(activeGroupSummary.fields) }}</strong></div>
                  <div class="summary-item"><span>Poly Data 总数</span><strong>{{ formatNumber(datasetGroupCount('all')) }}</strong></div>
                </div>

                <div class="analysis-view-bar">
                  <el-radio-group v-model="activeGroupAnalysisView" size="small">
                    <el-radio-button
                      v-for="view in GROUP_ANALYSIS_VIEWS"
                      :key="view.key"
                      :value="view.key"
                    >
                      {{ view.label }}
                    </el-radio-button>
                  </el-radio-group>
                </div>

                <div
                  v-if="activeGroupAnalysisView === 'table-analysis'"
                  v-loading="collectionAnalysisLoading"
                  class="table-analysis-shell"
                >
                  <div class="table-analysis-layout">
                    <nav class="table-analysis-selector" aria-label="选择数据表进行分析">
                      <div class="table-analysis-selector-heading">
                        <span>数据表</span>
                        <small>{{ activeGroupCollectionRows.length }} 张</small>
                      </div>
                      <button
                        v-for="row in activeGroupCollectionRows"
                        :key="row.collection_key"
                        type="button"
                        class="table-analysis-selector-row"
                        :class="{ active: activeTableAnalysisCollectionKey === row.collection_key }"
                        @click="activeTableAnalysisCollectionKey = row.collection_key"
                      >
                        <span>
                          <strong>{{ row.display_name }}</strong>
                          <small>{{ formatNumber(row.count) }} 条 · {{ row.data_domain || '数据表' }}</small>
                        </span>
                        <el-tag size="small" :type="statusTagType(row.status)">{{ row.status || '-' }}</el-tag>
                      </button>
                      <el-empty v-if="!activeGroupCollectionRows.length" description="当前分类暂无登记数据表" />
                    </nav>

                    <section v-if="activeTableAnalysisCollection" class="table-analysis-detail">
                      <header class="table-analysis-header">
                        <div>
                          <h3>{{ activeTableAnalysisCollection.display_name }}</h3>
                          <p>{{ activeTableAnalysisCollection.description }}</p>
                        </div>
                        <div class="table-analysis-actions">
                          <el-input-number
                            v-model="collectionAnalysisSampleSize"
                            :min="200"
                            :max="5000"
                            :step="200"
                            controls-position="right"
                            size="small"
                            aria-label="表分析样本量"
                          />
                          <el-button size="small" :loading="collectionAnalysisLoading" @click="ensureCollectionAnalysis({ refresh: true })">刷新分析</el-button>
                        </div>
                      </header>

                      <el-alert
                        v-if="collectionAnalysisError"
                        type="error"
                        :closable="false"
                        show-icon
                        :title="collectionAnalysisError"
                      />
                      <template v-if="activeTableAnalysis">
                        <div class="summary-grid table-analysis-summary">
                          <div class="summary-item"><span>全表记录数</span><strong>{{ formatNumber(activeTableAnalysis.total_count) }}</strong></div>
                          <div class="summary-item"><span>分析样本</span><strong>{{ formatNumber(activeTableAnalysis.sample_count) }}</strong></div>
                          <div class="summary-item"><span>分析字段</span><strong>{{ formatNumber(activeTableAnalysis.field_stats?.length || 0) }}</strong></div>
                          <div class="summary-item"><span>分析口径</span><strong>{{ activeTableAnalysis.analysis_status === 'partial' ? '全量计数 + 抽样' : (activeTableAnalysis.analysis_scope || '-') }}</strong></div>
                        </div>
                        <el-alert
                          v-if="activeTableAnalysis.analysis_message"
                          class="table-analysis-status"
                          :type="activeTableAnalysis.analysis_status === 'degraded' ? 'warning' : 'info'"
                          :closable="false"
                          :title="activeTableAnalysis.analysis_message"
                        />
                        <div class="visual-grid three-column table-analysis-charts">
                          <div class="visual-panel">
                            <h3>数值字段均值</h3>
                            <v-chart v-if="activeTableNumericFields.length" class="chart-medium" :option="activeTableNumericSummaryOption" autoresize />
                            <el-empty v-else description="暂无数值字段" />
                          </div>
                          <div class="visual-panel">
                            <h3>类别字段分布</h3>
                            <v-chart v-if="activeTableCategoryFields.length" class="chart-medium" :option="activeTableCategoryOption" autoresize />
                            <el-empty v-else description="暂无类别字段" />
                          </div>
                          <div class="visual-panel">
                            <h3>字段相关性</h3>
                            <v-chart v-if="activeTableAnalysis.correlations?.length" class="chart-medium" :option="activeTableCorrelationOption" autoresize />
                            <el-empty v-else description="暂无足够样本计算相关性" />
                          </div>
                        </div>

                        <section class="table-analysis-section">
                          <div class="section-heading">
                            <h3>字段统计</h3>
                            <span>基于 {{ formatNumber(activeTableAnalysis.sample_count) }} 条分析样本</span>
                          </div>
                          <el-table :data="activeTableAnalysis.field_stats" size="small" stripe>
                            <el-table-column prop="field" label="字段" min-width="150" />
                            <el-table-column prop="label" label="含义" min-width="150" />
                            <el-table-column prop="value_type" label="类型" width="90" />
                            <el-table-column label="非空率" width="100">
                              <template #default="{ row }">{{ (100 - Number(row.missing_percent || 0)).toFixed(1) }}%</template>
                            </el-table-column>
                            <el-table-column prop="unique_count" label="唯一值" width="90" />
                            <el-table-column label="数值摘要" min-width="250">
                              <template #default="{ row }">
                                <span v-if="row.value_type === 'number' && row.numeric_summary?.mean !== undefined">
                                  均值 {{ Number(row.numeric_summary.mean).toFixed(3) }} · 范围 {{ Number(row.numeric_summary.min).toFixed(3) }}–{{ Number(row.numeric_summary.max).toFixed(3) }}
                                </span>
                                <span v-else>{{ row.example ?? '-' }}</span>
                              </template>
                            </el-table-column>
                          </el-table>
                        </section>

                        <section class="table-analysis-section">
                          <div class="section-heading">
                            <h3>机理线索 / 规则解读</h3>
                            <span>描述性统计，不代表因果关系</span>
                          </div>
                          <div class="table-analysis-insights">
                            <article v-for="insight in activeTableAnalysis.insights" :key="`${insight.title}-${insight.conclusion}`" class="table-analysis-insight">
                              <div class="table-analysis-insight-header">
                                <strong>{{ insight.title }}</strong>
                                <el-tag size="small" :type="insight.level === 'warning' ? 'warning' : (insight.level === 'notice' ? 'primary' : 'info')">{{ insight.level }}</el-tag>
                              </div>
                              <p>{{ insight.conclusion }}</p>
                              <small>证据字段：{{ insight.evidence_fields?.join('、') || '-' }} · 样本 {{ formatNumber(insight.sample_count) }}</small>
                            </article>
                          </div>
                        </section>
                      </template>
                      <el-empty v-else description="选择数据表后加载分析" />
                    </section>
                  </div>
                </div>

                <div v-if="activeGroupAnalysisView === 'overview'" class="visual-grid two-column grouped-visuals">
                  <div class="visual-panel">
                    <h3>入库记录数</h3>
                    <v-chart v-if="activeGroupChartsVisible && activeGroupDatasetRows.length" class="chart-medium" :option="activeGroupRecordOption" autoresize />
                  </div>
                  <div class="visual-panel">
                    <h3>Mongo 覆盖率</h3>
                    <v-chart v-if="activeGroupChartsVisible && activeGroupDatasetRows.length" class="chart-medium" :option="activeGroupCoverageOption" autoresize />
                  </div>
                </div>

                <div
                  v-if="activeGroupAnalysisView === 'quality'"
                  v-loading="profileLoading"
                  class="visual-grid three-column grouped-visuals"
                >
                  <div class="visual-panel">
                    <h3>字段平均完整度</h3>
                    <v-chart v-if="activeGroupChartsVisible && activeGroupDatasetRows.length" class="chart-medium" :option="activeGroupFieldCompletenessOption" autoresize />
                  </div>
                  <div class="visual-panel">
                    <h3>低完整字段</h3>
                    <v-chart v-if="activeGroupChartsVisible && activeGroupDatasetRows.length" class="chart-medium" :option="activeGroupTopFieldsOption" autoresize />
                  </div>
                  <div class="visual-panel">
                    <h3>验证状态</h3>
                    <v-chart v-if="activeGroupChartsVisible && activeGroupDatasetRows.length" class="chart-medium" :option="activeGroupVerificationOption" autoresize />
                  </div>
                  <div class="visual-panel">
                    <h3>记录模式</h3>
                    <v-chart v-if="activeGroupChartsVisible && activeGroupDatasetRows.length" class="chart-medium" :option="activeGroupRecordModeOption" autoresize />
                  </div>
                </div>

                <div
                  v-if="activeGroupAnalysisView === 'samples'"
                  v-loading="groupSampleLoading"
                  class="visual-grid three-column grouped-visuals"
                >
                  <div class="visual-panel">
                    <h3>关联表记录量</h3>
                    <v-chart v-if="activeGroupChartsVisible && activeGroupCollectionRows.length" class="chart-medium" :option="activeGroupCollectionRecordOption" autoresize />
                  </div>
                  <div class="visual-panel">
                    <h3>来源/类型分布</h3>
                    <v-chart v-if="activeGroupChartsVisible" class="chart-medium" :option="activeGroupSampleFacetOption" autoresize />
                  </div>
                  <div class="visual-panel">
                    <h3>样本导入趋势</h3>
                    <v-chart v-if="activeGroupChartsVisible" class="chart-medium" :option="activeGroupSampleTrendOption" autoresize />
                  </div>
                </div>

                <div
                  v-if="activeGroupAnalysisView === 'focus'"
                  v-loading="profileLoading"
                  class="focus-analysis-shell"
                >
                  <el-collapse
                    v-if="activeGroupHasPi1m || activeGroupHasMdAllatom"
                    v-model="expandedFocusPanels"
                    class="focus-collapse"
                    @change="handleFocusPanelChange"
                  >
                    <el-collapse-item v-if="activeGroupHasPi1m" name="pi1m">
                      <template #title>
                        <span class="focus-title">PI1M v2 重点分析</span>
                      </template>
                      <div
                        v-if="expandedFocusPanels.includes('pi1m')"
                        v-loading="profileLoading || pi1mVisualLoading"
                        class="focus-analysis-panel"
                      >
                        <div class="focus-toolbar">
                          <span>结构空间抽样</span>
                          <el-input-number
                            v-model="pi1mSampleLimit"
                            :min="100"
                            :max="20000"
                            :step="500"
                            controls-position="right"
                            size="small"
                          />
                          <el-button size="small" :loading="pi1mVisualLoading" @click="ensurePi1mAnalysis({ refreshSamples: true })">刷新抽样</el-button>
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
                            <v-chart v-if="activeGroupChartsVisible && pi1mProfile" class="chart-large" :option="pi1mSaHistogramOption" autoresize />
                          </div>
                          <div class="visual-panel">
                            <h3>结构空间抽样</h3>
                            <v-chart v-if="activeGroupChartsVisible && pi1mVisualSamples.sample_count" class="chart-large" :option="pi1mMapOption" autoresize />
                          </div>
                        </div>
                      </div>
                    </el-collapse-item>

                    <el-collapse-item v-if="activeGroupHasMdAllatom" name="md-allatom">
                      <template #title>
                        <span class="focus-title">MD-AllAtom 重点分析</span>
                      </template>
                      <div
                        v-if="expandedFocusPanels.includes('md-allatom')"
                        v-loading="profileLoading"
                        class="focus-analysis-panel"
                      >
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
                              <v-chart v-if="activeGroupChartsVisible" class="chart-medium" :option="mdFamilyFilesOption" autoresize />
                            </div>
                            <div class="visual-panel">
                              <h3>温度分布</h3>
                              <v-chart v-if="activeGroupChartsVisible" class="chart-medium" :option="mdTemperatureOption" autoresize />
                            </div>
                            <div class="visual-panel">
                              <h3>聚合度分布</h3>
                              <v-chart v-if="activeGroupChartsVisible" class="chart-medium" :option="mdDpOption" autoresize />
                            </div>
                            <div class="visual-panel">
                              <h3>端到端距离</h3>
                              <v-chart v-if="activeGroupChartsVisible" class="chart-medium" :option="mdE2eOption" autoresize />
                            </div>
                            <div class="visual-panel">
                              <h3>回转半径</h3>
                              <v-chart v-if="activeGroupChartsVisible" class="chart-medium" :option="mdRgOption" autoresize />
                            </div>
                            <div class="visual-panel">
                              <h3>温度-链构象散点</h3>
                              <v-chart v-if="activeGroupChartsVisible" class="chart-medium" :option="mdScatterOption" autoresize />
                            </div>
                          </div>
                        </template>
                        <el-empty v-else description="MD-AllAtom 统计数据尚未导入，先补充碳基结果和 dataset_stats 后再展示分析图。" />
                      </div>
                    </el-collapse-item>
                  </el-collapse>

                  <div v-else class="visual-grid three-column grouped-visuals">
                    <div
                      v-for="dataset in activeGroupDatasetRows"
                      :key="dataset.dataset_id"
                      class="visual-panel"
                    >
                      <h3>{{ dataset.display_name }} 字段完整度</h3>
                      <v-chart v-if="datasetProfileFor(dataset.dataset_id) || dataset.field_summaries.length" class="chart-medium" :option="datasetFallbackOption(dataset)" autoresize />
                    </div>
                  </div>
                </div>

                <div class="dataset-list" role="list">
                  <button
                    v-for="dataset in activeGroupDatasetRows"
                    :key="dataset.dataset_id"
                    type="button"
                    class="dataset-list-row"
                    @click="openCatalogPage"
                  >
                    <span class="dataset-list-main">
                      <span class="dataset-list-name">{{ dataset.display_name }}</span>
                      <span class="dataset-list-description">{{ dataset.description }}</span>
                      <span class="dataset-list-tags">
                        <el-tag size="small" effect="plain">{{ dataset.source_category }}</el-tag>
                        <el-tag size="small" effect="plain">{{ dataset.confidence_label }}</el-tag>
                      </span>
                    </span>
                    <span class="dataset-list-stat"><strong>{{ formatNumber(dataset.row_count) }}</strong><small>原始行</small></span>
                    <span class="dataset-list-stat"><strong>{{ formatNumber(dataset.field_count) }}</strong><small>字段</small></span>
                    <span class="dataset-list-status">
                      <span class="dataset-list-status-line">
                        <el-tag size="small" :type="statusTagType(dataset.verification_status)">{{ dataset.verification_status || '-' }}</el-tag>
                        <small>{{ dataset.record_mode || '-' }}</small>
                      </span>
                      <el-progress
                        class="dataset-list-progress"
                        :percentage="Number(dataset.coverage_percent || 0)"
                        :show-text="false"
                        :stroke-width="6"
                      />
                      <small>{{ formatNumber(dataset.record_count) }} 条 · {{ formatPercent(dataset.coverage_percent) }}</small>
                    </span>
                    <el-icon class="dataset-list-arrow" aria-hidden="true"><ArrowRight /></el-icon>
                  </button>
                </div>
              </section>
            </div>
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="材料数据" name="materials" lazy>
        <section class="analysis-section">
          <div class="section-heading">
            <h2>材料数据分级</h2>
            <span>近 {{ materialAnalysisRecords.length }} 条样本</span>
          </div>
          <div v-if="materialAnalysisRecords.length" class="visual-grid three-column">
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
          <el-empty v-else description="暂无可分析的材料样本" />
        </section>
      </el-tab-pane>

      <el-tab-pane label="计算数据" name="computations" lazy>
        <section class="analysis-section">
          <div class="section-heading">
            <h2>计算数据分析</h2>
            <span>近 {{ computationAnalysisRecords.length }} 条任务样本</span>
          </div>
          <div v-if="computationAnalysisRecords.length || artifactAnalysisRecords.length" class="visual-grid three-column">
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
          <el-empty v-else description="暂无可分析的计算样本" />
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

.section-description {
  margin: 4px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
  line-height: 1.45;
}

.header-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.sampling-panel {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  padding: 12px;
  border: 1px solid var(--app-card-border);
  border-radius: var(--app-radius-sm);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: var(--app-card-shadow);
}

.sampling-control {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sampling-control span {
  color: var(--app-ink-muted);
  font-size: 12px;
  white-space: nowrap;
}

.sampling-control :deep(.el-input-number) {
  width: 146px;
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

.compact-heading {
  margin-top: 4px;
}

.summary-grid,
.visual-grid,
.dataset-card-grid,
.collection-card-grid,
.mini-metric-grid,
.profile-chart-grid {
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

.dataset-card-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.collection-card-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
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

.dataset-filter.active strong {
  color: var(--app-primary);
}

.dataset-filter.tone-blue.active { border-left: 3px solid #2563eb; }
.dataset-filter.tone-teal.active { border-left: 3px solid #0f766e; }
.dataset-filter.tone-amber.active { border-left: 3px solid #d97706; }
.dataset-filter.tone-coral.active { border-left: 3px solid #be5a35; }
.dataset-filter.tone-violet.active { border-left: 3px solid #7c3aed; }

.dataset-group-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}

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

.dataset-group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 13px 15px 11px;
  background: #fbfcfe;
  border-bottom: 1px solid var(--app-border-soft);
}

.dataset-group-title {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.dataset-group-marker {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: var(--app-border);
}

.tone-blue .dataset-group-marker { background: #2563eb; }
.tone-teal .dataset-group-marker { background: #0f766e; }
.tone-amber .dataset-group-marker { background: #d97706; }
.tone-coral .dataset-group-marker { background: #be5a35; }
.tone-violet .dataset-group-marker { background: #7c3aed; }

.dataset-group-header h3 {
  margin: 0;
  color: var(--app-ink);
  font-size: 18px;
  letter-spacing: 0;
}

.dataset-group-header p {
  margin: 3px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.dataset-group-count {
  color: var(--app-ink-muted);
  font-size: 14px;
  white-space: nowrap;
}

.grouped-summary,
.grouped-visuals {
  margin: 12px;
}

.analysis-view-bar {
  display: flex;
  justify-content: flex-start;
  margin: 0 12px 12px;
  overflow-x: auto;
}

.analysis-view-bar :deep(.el-radio-group) {
  flex-wrap: nowrap;
}

.analysis-view-bar :deep(.el-radio-button__inner) {
  white-space: nowrap;
}

.table-analysis-shell {
  margin: 0 12px 12px;
}

.table-analysis-layout {
  display: grid;
  grid-template-columns: 250px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}

.table-analysis-selector,
.table-analysis-detail,
.table-analysis-section {
  min-width: 0;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #fff;
}

.table-analysis-selector {
  overflow: hidden;
}

.table-analysis-selector-heading {
  display: flex;
  justify-content: space-between;
  padding: 11px 12px;
  border-bottom: 1px solid var(--app-border-soft);
  color: var(--app-ink);
  font-size: 13px;
  font-weight: 700;
}

.table-analysis-selector-heading small {
  color: var(--app-ink-muted);
  font-weight: 400;
}

.table-analysis-selector-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  min-height: 60px;
  padding: 9px 11px;
  border: 0;
  border-bottom: 1px solid #eef2f7;
  background: #fff;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.table-analysis-selector-row:hover,
.table-analysis-selector-row:focus-visible,
.table-analysis-selector-row.active {
  background: #f3f8ff;
  outline: none;
}

.table-analysis-selector-row.active {
  box-shadow: inset 3px 0 0 var(--app-primary);
}

.table-analysis-selector-row span {
  min-width: 0;
}

.table-analysis-selector-row strong,
.table-analysis-selector-row small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.table-analysis-selector-row strong {
  color: var(--app-ink);
  font-size: 13px;
}

.table-analysis-selector-row small {
  margin-top: 3px;
  color: var(--app-ink-muted);
  font-size: 11px;
}

.table-analysis-detail {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
}

.table-analysis-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.table-analysis-header h3 {
  margin: 0;
  color: var(--app-ink);
  font-size: 17px;
}

.table-analysis-header p {
  margin: 4px 0 0;
  color: var(--app-ink-muted);
  font-size: 12px;
  line-height: 1.45;
}

.table-analysis-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.table-analysis-actions :deep(.el-input-number) {
  width: 130px;
}

.table-analysis-summary {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.table-analysis-status {
  margin: 0;
}

.table-analysis-charts {
  margin: 0;
}

.table-analysis-section {
  padding: 12px;
}

.table-analysis-section .section-heading {
  align-items: center;
  margin-bottom: 9px;
}

.table-analysis-section .section-heading h3 {
  margin: 0;
  color: var(--app-ink);
  font-size: 14px;
}

.table-analysis-section .section-heading span {
  color: var(--app-ink-muted);
  font-size: 11px;
}

.table-analysis-insights {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.table-analysis-insight {
  padding: 11px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #fbfcfe;
}

.table-analysis-insight-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.table-analysis-insight-header strong {
  color: var(--app-ink);
  font-size: 13px;
}

.table-analysis-insight p {
  margin: 7px 0;
  color: var(--app-ink-body);
  font-size: 12px;
  line-height: 1.55;
}

.table-analysis-insight small {
  color: var(--app-ink-muted);
  font-size: 11px;
  line-height: 1.4;
}

.dataset-list {
  display: flex;
  flex-direction: column;
  border-top: 1px solid #eef2f7;
}

.dataset-list-row {
  display: grid;
  grid-template-columns: minmax(240px, 1.8fr) 96px 76px minmax(210px, 0.82fr) 22px;
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

.dataset-list-row:last-child {
  border-bottom: 0;
}

.dataset-list-row:hover,
.dataset-list-row:focus-visible {
  background: #f7faff;
  outline: none;
}

.dataset-list-main {
  min-width: 0;
}

.dataset-list-name {
  display: block;
  overflow: hidden;
  color: var(--app-ink);
  font-size: 16px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dataset-list-description {
  display: block;
  overflow: hidden;
  margin-top: 4px;
  color: var(--app-ink-muted);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dataset-list-tags {
  display: flex;
  gap: 5px;
  margin-top: 7px;
  overflow: hidden;
}

.dataset-list-tags .el-tag {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dataset-list-stat strong {
  display: block;
  color: var(--app-sidebar-from);
  font-size: 18px;
  line-height: 1.1;
}

.dataset-list-stat small,
.dataset-list-status small {
  display: block;
  margin-top: 5px;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.dataset-list-status {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  min-width: 0;
}

.dataset-list-status-line {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.dataset-list-status-line small {
  margin-top: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dataset-list-progress {
  width: 100%;
  margin-top: 7px;
}

.dataset-list-arrow {
  color: var(--app-ink-subtle);
}

.dataset-list-row:hover .dataset-list-arrow {
  color: var(--app-primary);
}

.focus-collapse {
  overflow: hidden;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #fff;
}

.focus-analysis-shell {
  margin: 12px;
}

.focus-analysis-shell .grouped-visuals {
  margin: 0;
}

.focus-title {
  color: var(--app-ink);
  font-weight: 700;
}

.focus-analysis-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 4px 0 10px;
}

.focus-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.focus-toolbar span {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.focus-toolbar :deep(.el-input-number) {
  width: 146px;
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

.dataset-analysis-card,
.collection-analysis-card {
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--app-card-border);
  border-radius: var(--app-radius-sm);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: none;
}

.dataset-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  min-height: 44px;
}

.dataset-card-header h3 {
  margin: 0;
  color: var(--app-ink);
  font-size: 13px;
  line-height: 1.3;
  letter-spacing: 0;
  overflow-wrap: anywhere;
}

.dataset-card-header small {
  display: block;
  margin-top: 3px;
  color: var(--app-ink-muted);
  font-size: 11px;
  line-height: 1.3;
  overflow-wrap: anywhere;
}

.mini-metric-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-top: 10px;
}

.mini-metric-grid div {
  min-width: 0;
  padding: 8px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
}

.mini-metric-grid span {
  display: block;
  color: var(--app-ink-muted);
  font-size: 11px;
  line-height: 1.2;
}

.mini-metric-grid strong {
  display: block;
  margin-top: 4px;
  color: var(--app-ink);
  font-size: 14px;
  line-height: 1.25;
  overflow-wrap: anywhere;
}

.profile-chart-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 10px;
}

.profile-chart {
  min-width: 0;
  margin-top: 10px;
}

.profile-chart-grid .profile-chart {
  margin-top: 0;
}

.profile-chart h4 {
  margin: 0 0 4px;
  color: var(--app-ink);
  font-size: 12px;
  line-height: 1.25;
  font-weight: 600;
  letter-spacing: 0;
  overflow-wrap: anywhere;
}

.facet-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 26px;
  margin-top: 10px;
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

.chart-small {
  width: 100%;
  height: 150px;
}

@media (max-width: 1280px) {
  .metric-grid,
  .summary-grid,
  .two-column,
  .three-column,
  .collection-card-grid,
  .profile-chart-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .dataset-card-grid {
    grid-template-columns: 1fr;
  }

  .dataset-browser-layout {
    grid-template-columns: 160px minmax(0, 1fr);
  }

  .dataset-list-row {
    grid-template-columns: minmax(190px, 1.5fr) 82px 66px minmax(180px, 0.85fr) 20px;
    gap: 10px;
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
  .three-column,
  .dataset-card-grid,
  .collection-card-grid,
  .mini-metric-grid,
  .profile-chart-grid {
    grid-template-columns: 1fr;
  }

  .sampling-control {
    width: 100%;
    justify-content: space-between;
  }

  .sampling-control :deep(.el-input-number) {
    width: 164px;
  }

  .dataset-browser-layout {
    grid-template-columns: 1fr;
  }

  .table-analysis-layout,
  .table-analysis-insights {
    grid-template-columns: 1fr;
  }

  .table-analysis-header {
    flex-direction: column;
  }

  .table-analysis-actions {
    justify-content: flex-start;
  }

  .dataset-rail {
    position: static;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    padding: 0 0 10px;
    border-right: 0;
    border-bottom: 1px solid var(--app-border-soft);
  }

  .dataset-rail-label {
    grid-column: 1 / -1;
    margin: 0 0 2px;
  }

  .dataset-list-row {
    grid-template-columns: minmax(0, 1fr) 20px;
    gap: 6px 10px;
  }

  .dataset-list-stat {
    display: none;
  }

  .dataset-list-status {
    grid-column: 1 / -1;
  }

  .dataset-list-description {
    white-space: normal;
  }
}
</style>
