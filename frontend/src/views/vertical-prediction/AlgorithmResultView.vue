<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Document, Download } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import AttributionBadges from '../../components/attribution/AttributionBadges.vue'
import JsonTreeView from '../../components/json/JsonTreeView.vue'
import {
  buildArrayObjectSection,
  buildBatchHighlights as buildAllBatchHighlights,
  paginateRows,
} from '../../utils/verticalPredictionJson.mjs'
import { downloadArtifact, getApiErrorMessage } from '../../api/polyAgentApi'
import { downloadArtifactToBrowser } from '../../utils/artifactDownload.mjs'

const props = defineProps({
  outputSummary: { type: [Object, Array, String, Number, Boolean], default: () => ({}) },
  inputSnapshot: { type: [Object, Array, String, Number, Boolean], default: () => ({}) },
  artifactRefs: { type: Array, default: () => [] },
  outputSchema: { type: Object, default: null },
  status: { type: String, default: '' },
  error: { type: Object, default: null },
  attributions: { type: Array, default: () => [] },
  algorithmId: { type: String, default: '' },
  runId: { type: String, default: '' },
  showInput: { type: Boolean, default: false },
})

const router = useRouter()
const tablePagination = ref({})
const downloadingArtifactId = ref('')
const expandedOtherSections = ref([])
const expandedRawPanels = ref([])

const priorityValueKeys = ['value', 'predicted_value', 'prediction', 'score']
const uncertaintyKeys = ['uncertainty', 'std', 'stddev', 'confidence', 'probability']
const modelKeys = ['model_version', 'model', 'algorithm', 'neighbor_count']
const semanticObjectKeys = ['feature_summary', 'metrics', 'metadata']
const metaPredictionKeys = ['property', 'unit', 'target', 'name']

const outputObject = computed(() => normalizeToObject(props.outputSummary))
const inputObject = computed(() => normalizeToObject(props.inputSnapshot))
const outputUiHints = computed(() => {
  const raw = props.outputSchema?.ui_hints
  if (!raw || !Object.keys(raw).length) return null
  const hasDisplay = Object.values(raw).some((h) => h && (h.display || h.group))
  return hasDisplay ? raw : null
})
const predictionObject = computed(() => {
  if (isPlainObject(outputObject.value.prediction)) return outputObject.value.prediction
  return outputObject.value
})

const isRamanFunctionalGroupModel = computed(() => props.algorithmId === 'raman_structure_analyzer')
const ramanFunctionalGroups = computed(() => {
  if (!isRamanFunctionalGroupModel.value || !Array.isArray(outputObject.value.candidates)) return []
  return outputObject.value.candidates
    .map((item) => item?.functional_group ?? item?.structure ?? item)
    .filter((item) => item !== null && item !== undefined && String(item).trim())
    .map(String)
})
const batchResultSections = computed(() => buildBatchResultSections(
  outputObject.value,
  isRamanFunctionalGroupModel.value ? new Set(['candidates']) : new Set(),
))
const batchHighlights = computed(() => buildAllBatchHighlights(batchResultSections.value))

const highlightCards = computed(() => {
  const hints = outputUiHints.value
  if (!hints) return []
  return Object.entries(hints)
    .filter(([, h]) => h?.display === 'highlight')
    .map(([key, h]) => ({
      key,
      label: h?.title || formatLabel(key),
      value: formatScalar(outputObject.value[key]),
      caption: '',
    }))
})
const mainPrediction = computed(() => buildMainPrediction(predictionObject.value, outputObject.value))
const evidence = computed(() => buildEvidence(
  outputObject.value,
  predictionObject.value,
  mainPrediction.value,
  new Set([
    ...batchResultSections.value.map((section) => section.key),
    ...(isRamanFunctionalGroupModel.value ? ['candidates'] : []),
  ]),
))
const rawPanels = computed(() => {
  const panels = [
    { name: 'input', title: '输入 JSON', data: props.inputSnapshot },
    { name: 'output', title: '输出 JSON', data: props.outputSummary },
  ]
  if (props.artifactRefs.length) panels.push({ name: 'artifacts', title: 'Artifacts JSON', data: props.artifactRefs })
  if (props.error) panels.push({ name: 'error', title: '错误 JSON', data: props.error })
  return panels
})

watch(
  () => evidence.value.otherSections.map((section) => section.title),
  (titles) => {
    const known = new Set(titles)
    const kept = expandedOtherSections.value.filter((title) => known.has(title))
    const added = titles.filter((title) => !expandedOtherSections.value.includes(title))
    expandedOtherSections.value = [...kept, ...added]
  },
  { immediate: true },
)

watch(
  () => rawPanels.value.map((panel) => panel.name),
  (names) => {
    const known = new Set(names)
    const kept = expandedRawPanels.value.filter((name) => known.has(name))
    const added = names.filter((name) => !expandedRawPanels.value.includes(name))
    expandedRawPanels.value = [...kept, ...added]
  },
  { immediate: true },
)

const artifactRows = computed(() => {
  const rows = props.artifactRefs.map((item, index) => ({
    id: item.artifact_id || item.id || `${index + 1}`,
    name: item.name || item.filename || item.artifact_id || item.id || `artifact_${index + 1}`,
    type: item.type || item.artifact_type || '-',
    stepKey: item.step_key || item.stepKey || '-',
    group: artifactGroup(item),
    description: item.description || '-',
    contentType: item.content_type || item.mime_type || '-',
    contentSummary: item.content === undefined ? '-' : summarizeValue(item.content),
    downloadable: Boolean(item.artifact_id || item.id),
  }))
  if (rows.length || isEmptyValue(props.outputSummary)) return rows
  return [{
    id: 'output_summary',
    name: '运行输出 JSON',
    type: 'json_artifact',
    stepKey: 'PREDICT',
    group: '模型输出',
    description: '模型运行输出',
    contentType: 'application/json',
    contentSummary: summarizeValue(props.outputSummary),
  }]
})

const hasOutput = computed(() => !isEmptyValue(props.outputSummary))
const hasStructuredContent = computed(() => Boolean(
  mainPrediction.value.value !== null ||
  evidence.value.metricSections.length ||
  evidence.value.listSections.length ||
  evidence.value.tableSections.length ||
  evidence.value.otherSections.length ||
  artifactRows.value.length,
))
const imageArtifacts = computed(() => artifactRows.value.filter(
  (row) => row.downloadable && (row.contentType.startsWith('image/') || row.type === 'image_png')
))

const hasHighlight = computed(() => {
  const hints = outputUiHints.value
  if (!hints) return false
  return Object.values(hints).some((h) => h?.display === 'highlight')
})

const inputHighlights = computed(() => scalarEntries(inputObject.value).slice(0, 4))

const uiMetricGroups = computed(() => {
  const hints = outputUiHints.value
  if (!hints) return []
  const output = outputObject.value
  const groupedKeys = new Set(Object.keys(hints))
  const groups = {}
  for (const [key, hint] of Object.entries(hints)) {
    const groupName = hint?.group
    if (!groupName || !isScalar(output[key])) continue
    if (!groups[groupName]) groups[groupName] = []
    groups[groupName].push({ key, label: hint?.label || formatLabel(key), value: output[key] })
  }
  const unhandled = Object.entries(output)
    .filter(([key, value]) => isScalar(value) && !groupedKeys.has(key))
    .map(([key, value]) => ({ key, label: formatLabel(key), value }))
  if (unhandled.length) groups['其他'] = unhandled
  return Object.entries(groups).map(([title, entries]) => ({ title: formatLabel(title), entries }))
})

async function handleDownloadArtifact(row) {
  if (!row.downloadable || !row.id || row.id === 'output_summary') return
  downloadingArtifactId.value = row.id
  try {
    await downloadArtifactToBrowser({
      artifactId: row.id,
      fallbackName: row.name,
      download: downloadArtifact,
    })
  } catch (error) {
    ElMessage.error(`下载失败：${getApiErrorMessage(error)}`)
  } finally {
    downloadingArtifactId.value = ''
  }
}

function openRunDetail() {
  if (!props.runId) return
  router.push({
    path: '/vertical-prediction',
    query: {
      tab: 'detail',
      algorithm_id: props.algorithmId || '',
      run_id: props.runId,
    },
  })
}

function artifactGroup(item) {
  const stepKey = item.step_key || item.stepKey || ''
  const type = item.artifact_type || item.type || ''
  if (stepKey === 'INPUT' || type === 'input_file') return '输入文件'
  if (stepKey === 'INPUT_PARSE' || ['parsed_input_json', 'table_json', 'series_json'].includes(type)) return '平台解析'
  return '模型输出'
}

function buildBatchResultSections(output, hiddenKeys = new Set()) {
  return Object.entries(output)
    .filter(([key]) => !hiddenKeys.has(key))
    .filter(([, value]) => Array.isArray(value) && value.length && value.every(isPlainObject))
    .map(([key, rows]) => buildArrayObjectSection(key, rows))
}

function buildMainPrediction(prediction, output) {
  const hints = outputUiHints.value
  if (hints) {
    const primaryField = Object.entries(hints).find(([, h]) => h?.display === 'primary')
    if (!primaryField) return { key: '', title: '', value: null, unit: '', uncertainty: null, modelInfo: [] }
    if (isScalar(output[primaryField[0]])) {
      const key = primaryField[0]
      const hint = primaryField[1] || {}
      const secondary = Object.entries(hints)
        .filter(([, h]) => h?.display === 'secondary')
        .map(([k, h]) => ({
          key: k,
          label: h?.label || formatLabel(k),
          value: isScalar(output[k]) ? output[k] : null,
        }))
        .filter((entry) => entry.value !== null)
      return { key, title: hint.title || formatLabel(key), value: output[key], unit: hint.unit || '', uncertainty: null, modelInfo: secondary }
    }
  }
  const valueEntry = findMainValue(prediction)
  const uncertainty = findFirstKey(prediction, uncertaintyKeys) || findFirstKey(output, uncertaintyKeys)
  const modelInfo = uniqueEntries([
    ...findEntries(prediction, modelKeys),
    ...findEntries(output, modelKeys),
  ])
  const title = prediction.property || prediction.target || prediction.name || valueEntry?.key || '预测结果'
  const unit = prediction.unit || output.unit || ''
  return {
    key: valueEntry?.key || '',
    title: formatLabel(title),
    value: valueEntry ? valueEntry.value : null,
    unit,
    uncertainty,
    modelInfo,
  }
}

function findMainValue(source) {
  for (const key of priorityValueKeys) {
    if (isScalar(source[key])) return { key, value: source[key] }
  }
  for (const [key, value] of Object.entries(source)) {
    if (!isScalar(value)) continue
    if ([...metaPredictionKeys, ...uncertaintyKeys, ...modelKeys].includes(key)) continue
    return { key, value }
  }
  return null
}

function buildEvidence(output, prediction, main, hiddenKeys = new Set()) {
  const metricSections = []
  const listSections = []
  const tableSections = []
  const otherSections = []
  const topLevelMetrics = []
  const skippedPredictionKeys = new Set([
    ...metaPredictionKeys,
    ...uncertaintyKeys,
    ...modelKeys,
    main.key,
  ].filter(Boolean))

  if (prediction !== output) {
    const predictionMetrics = []
    for (const [key, value] of Object.entries(prediction)) {
      if (hiddenKeys.has(key)) continue
      if (skippedPredictionKeys.has(key)) continue
      routeEvidenceValue(key, value, predictionMetrics, listSections, tableSections, otherSections)
    }
    if (predictionMetrics.length) {
      metricSections.push({ title: '预测附加信息', entries: predictionMetrics })
    }
  }

  for (const key of semanticObjectKeys) {
    const value = output[key]
    if (isPlainObject(value)) {
      if (Object.keys(value).length && Object.values(value).every((item) => isScalar(item))) {
        metricSections.push({ title: formatLabel(key), entries: objectEntries(value) })
      } else {
        otherSections.push({ title: formatLabel(key), data: value })
      }
    }
  }

  for (const [key, value] of Object.entries(output)) {
    if (hiddenKeys.has(key)) continue
    if (key === 'prediction' || semanticObjectKeys.includes(key)) continue
    routeEvidenceValue(key, value, topLevelMetrics, listSections, tableSections, otherSections)
  }
  if (topLevelMetrics.length) {
    metricSections.push({ title: '其他指标', entries: topLevelMetrics })
  }

  return { metricSections, listSections, tableSections, otherSections }
}

function routeEvidenceValue(key, value, metricEntries, listSections, tableSections, otherSections) {
  if (isScalar(value)) {
    metricEntries.push({ key, label: formatLabel(key), value })
    return
  }
  if (Array.isArray(value)) {
    if (value.every(isScalar)) {
      listSections.push({ key, title: formatLabel(key), items: value.map(formatScalar), total: value.length })
      return
    }
    if (value.every(isPlainObject)) {
      tableSections.push(buildTableSection(key, value))
      return
    }
  }
  if (isPlainObject(value) && Object.keys(value).length && Object.values(value).every((item) => isScalar(item))) {
    metricEntries.push(...objectEntries(value, key))
    return
  }
  if (isComplexValue(value) || !isEmptyValue(value)) {
    otherSections.push({ title: formatLabel(key), data: value })
  }
}

function buildTableSection(key, rows) {
  const section = buildArrayObjectSection(key, rows)
  return { ...section, title: formatLabel(key) }
}

function paginationFor(key) {
  return tablePagination.value[key] || { page: 1, pageSize: 20 }
}

function pagedRows(section) {
  const pagination = paginationFor(section.key)
  return paginateRows(section.rows, pagination.page, pagination.pageSize).rows
}

function pagedItems(section) {
  const pagination = paginationFor(`list.${section.key}`)
  return paginateRows(section.items, pagination.page, pagination.pageSize).rows
}

function setPage(key, page) {
  tablePagination.value[key] = { ...paginationFor(key), page }
}

function setPageSize(key, pageSize) {
  tablePagination.value[key] = { page: 1, pageSize }
}

function findFirstKey(source, keys) {
  for (const key of keys) {
    if (source[key] !== undefined && source[key] !== null && source[key] !== '') {
      return { key, label: formatLabel(key), value: source[key] }
    }
  }
  return null
}

function findEntries(source, keys) {
  return keys
    .filter((key) => source[key] !== undefined && source[key] !== null && source[key] !== '')
    .map((key) => ({ key, label: formatLabel(key), value: source[key] }))
}

function uniqueEntries(entries) {
  const seen = new Set()
  return entries.filter((entry) => {
    if (seen.has(entry.key)) return false
    seen.add(entry.key)
    return true
  })
}

function objectEntries(source, prefix = '') {
  return Object.entries(source).map(([key, value]) => ({
    key: prefix ? `${prefix}.${key}` : key,
    label: formatLabel(key),
    value,
  }))
}

function scalarEntries(source) {
  if (!isPlainObject(source)) return []
  return Object.entries(source)
    .filter(([, value]) => isScalar(value))
    .map(([key, value]) => ({ key, label: formatLabel(key), value }))
}

function normalizeToObject(value) {
  if (isPlainObject(value)) return value
  if (Array.isArray(value)) return { result: value }
  if (!isEmptyValue(value)) return { result: value }
  return {}
}

function isPlainObject(value) {
  return Object.prototype.toString.call(value) === '[object Object]'
}

function isScalar(value) {
  return value === null || ['string', 'number', 'boolean'].includes(typeof value)
}

function isEmptyValue(value) {
  if (value === null || value === undefined || value === '') return true
  if (Array.isArray(value)) return value.length === 0
  if (isPlainObject(value)) return Object.keys(value).length === 0
  return false
}

function formatLabel(value) {
  return String(value || '-')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function formatScalar(value) {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(4)))
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return String(value)
}

function summarizeValue(value) {
  if (isScalar(value)) return formatScalar(value)
  if (Array.isArray(value)) return `${value.length} items`
  if (isPlainObject(value)) return `${Object.keys(value).length} fields`
  return String(value)
}

function isComplexValue(value) {
  return Array.isArray(value) || isPlainObject(value)
}

function stringifyJson(value) {
  return JSON.stringify(value ?? null, null, 2)
}
</script>

<template>
  <div class="algorithm-result-view">
    <el-alert
      v-if="error"
      class="result-error"
      :title="error.message || error.error || '算法运行失败'"
      type="error"
      show-icon
      :closable="false"
    />

    <template v-if="status !== 'failed' && hasOutput">
      <el-alert
        v-if="isRamanFunctionalGroupModel"
        title="当前模型识别拉曼光谱中的官能团，不输出完整分子结构或置信分数。"
        type="info"
        :closable="false"
        show-icon
      />

      <section v-if="isRamanFunctionalGroupModel" class="result-section">
        <div class="section-heading">
          <h4>检测到的官能团</h4>
          <span>{{ ramanFunctionalGroups.length }} 项</span>
        </div>
        <div v-if="ramanFunctionalGroups.length" class="tag-list">
          <el-tag v-for="item in ramanFunctionalGroups" :key="item" effect="plain">{{ item }}</el-tag>
        </div>
        <div v-else class="empty-result">未检测到官能团</div>
      </section>

      <section v-if="showInput && inputHighlights.length" class="result-section">
        <h4>关键输入</h4>
        <div class="metric-grid compact">
          <div v-for="entry in inputHighlights" :key="entry.key" class="metric-item">
            <span>{{ entry.label }}</span>
            <strong>{{ formatScalar(entry.value) }}</strong>
          </div>
        </div>
      </section>

      <section v-if="highlightCards.length" class="result-section">
        <h4>核心指标</h4>
        <div class="prediction-dashboard" aria-label="核心指标">
          <article v-for="item in highlightCards" :key="item.key" class="signal-card">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
            <small>{{ item.caption }}</small>
          </article>
        </div>
      </section>

      <section v-if="batchHighlights.length" class="prediction-dashboard" aria-label="批量预测概览">
        <article v-for="item in batchHighlights" :key="item.key" class="signal-card">
          <span>{{ item.label }}</span>
          <strong>{{ formatScalar(item.value) }}</strong>
          <small>{{ item.caption }}</small>
        </article>
      </section>

      <section v-if="mainPrediction.value !== null" class="prediction-summary" aria-label="预测结论">
        <div class="prediction-main">
          <span class="summary-label">{{ mainPrediction.title }}</span>
          <div class="summary-value">
            <strong>{{ formatScalar(mainPrediction.value) }}</strong>
            <span v-if="mainPrediction.unit">{{ mainPrediction.unit }}</span>
          </div>
          <span v-if="mainPrediction.key" class="summary-key">{{ mainPrediction.key }}</span>
        </div>
        <div class="summary-side">
          <div v-if="mainPrediction.uncertainty" class="summary-chip">
            <span>{{ mainPrediction.uncertainty.label }}</span>
            <strong>{{ formatScalar(mainPrediction.uncertainty.value) }}</strong>
          </div>
          <div v-for="entry in mainPrediction.modelInfo" :key="entry.key" class="summary-chip">
            <span>{{ entry.label }}</span>
            <strong>{{ formatScalar(entry.value) }}</strong>
          </div>
        </div>
      </section>

      <section v-for="section in batchResultSections" :key="section.key" class="result-section featured-table-section">
        <div class="section-heading">
          <h4>{{ section.title }}</h4>
          <span>{{ section.totalRows }} 行 / {{ section.totalColumns }} 列，全部字段可横向滚动查看</span>
        </div>
        <el-table :data="pagedRows(section)" border size="small" class="result-table featured-table">
          <el-table-column
            v-for="column in section.columns"
            :key="column"
            :prop="column"
            :label="formatLabel(column)"
            min-width="128"
            show-overflow-tooltip
          >
            <template #default="{ row }">
              <el-popover v-if="isComplexValue(row[column])" trigger="click" width="min(560px, 88vw)">
                <template #reference>
                  <el-button text :icon="Document" :aria-label="`展开 ${column}`">
                    {{ summarizeValue(row[column]) }}
                  </el-button>
                </template>
                <JsonTreeView :value="row[column]" />
              </el-popover>
              <span v-else>{{ summarizeValue(row[column]) }}</span>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-if="section.totalRows > 10"
          class="result-pagination"
          :current-page="paginationFor(section.key).page"
          :page-size="paginationFor(section.key).pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="section.totalRows"
          layout="total, sizes, prev, pager, next"
          @current-change="setPage(section.key, $event)"
          @size-change="setPageSize(section.key, $event)"
        />
      </section>

      <section v-for="group in uiMetricGroups" :key="group.title" class="result-section">
        <h4>{{ group.title }}</h4>
        <div class="metric-grid">
          <div v-for="entry in group.entries" :key="entry.key" class="metric-item">
            <span>{{ entry.label }}</span>
            <strong>{{ summarizeValue(entry.value) }}</strong>
          </div>
        </div>
      </section>

      <section v-if="!outputUiHints" v-for="section in evidence.metricSections" :key="section.title" class="result-section">
        <h4>{{ section.title }}</h4>
        <div class="metric-grid">
          <div v-for="entry in section.entries" :key="entry.key" class="metric-item">
            <span>{{ entry.label }}</span>
            <strong>{{ summarizeValue(entry.value) }}</strong>
          </div>
        </div>
      </section>

      <section v-for="section in evidence.listSections" :key="section.title" class="result-section">
        <div class="section-heading">
          <h4>{{ section.title }}</h4>
          <span>{{ section.total }} 项</span>
        </div>
        <div class="tag-list">
          <el-tag v-for="(item, index) in pagedItems(section)" :key="`${section.title}-${index}`" effect="plain">
            {{ item }}
          </el-tag>
        </div>
        <el-pagination
          v-if="section.total > 10"
          class="result-pagination"
          :current-page="paginationFor(`list.${section.key}`).page"
          :page-size="paginationFor(`list.${section.key}`).pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="section.total"
          layout="total, sizes, prev, pager, next"
          @current-change="setPage(`list.${section.key}`, $event)"
          @size-change="setPageSize(`list.${section.key}`, $event)"
        />
      </section>

      <section v-for="section in evidence.tableSections" :key="section.title" class="result-section">
        <div class="section-heading">
          <h4>{{ section.title }}</h4>
          <span>{{ section.totalRows }} 行 / {{ section.totalColumns }} 列，全部字段可横向滚动查看</span>
        </div>
        <el-table :data="pagedRows(section)" border size="small" class="result-table">
          <el-table-column
            v-for="column in section.columns"
            :key="column"
            :prop="column"
            :label="formatLabel(column)"
            min-width="120"
            show-overflow-tooltip
          >
            <template #default="{ row }">
              <el-popover v-if="isComplexValue(row[column])" trigger="click" width="min(560px, 88vw)">
                <template #reference>
                  <el-button text :icon="Document" :aria-label="`展开 ${column}`">
                    {{ summarizeValue(row[column]) }}
                  </el-button>
                </template>
                <JsonTreeView :value="row[column]" />
              </el-popover>
              <span v-else>{{ summarizeValue(row[column]) }}</span>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-if="section.totalRows > 10"
          class="result-pagination"
          :current-page="paginationFor(section.key).page"
          :page-size="paginationFor(section.key).pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="section.totalRows"
          layout="total, sizes, prev, pager, next"
          @current-change="setPage(section.key, $event)"
          @size-change="setPageSize(section.key, $event)"
        />
      </section>

      <section v-if="evidence.otherSections.length" class="result-section">
        <h4>其他输出</h4>
        <el-collapse v-model="expandedOtherSections">
          <el-collapse-item v-for="section in evidence.otherSections" :key="section.title" :title="section.title" :name="section.title">
            <div class="json-tree-panel"><JsonTreeView :value="section.data" /></div>
          </el-collapse-item>
        </el-collapse>
      </section>
    </template>

    <div v-else-if="!error && !hasStructuredContent" class="empty-result">
      暂无结构化输出
    </div>

    <section v-if="imageArtifacts.length" class="result-section">
      <h4>图表预览</h4>
      <div class="image-preview-grid">
        <div v-for="img in imageArtifacts" :key="img.id" class="image-preview-card">
          <span class="image-label">{{ img.name }}</span>
          <img :src="`/api/v1/artifacts/${img.id}/download`" :alt="img.name" class="preview-image" />
        </div>
      </div>
    </section>

    <section v-if="artifactRows.length" class="result-section artifact-section">
      <div class="section-heading">
        <h4>运行产物</h4>
        <span>{{ artifactRows.length }} 项</span>
      </div>
      <el-table :data="artifactRows" border size="small" class="result-table">
        <el-table-column label="操作" width="96">
          <template #default="{ row }">
            <el-button
              v-if="row.downloadable"
              text
              type="primary"
              :icon="Download"
              :loading="downloadingArtifactId === row.id"
              @click="handleDownloadArtifact(row)"
            >下载</el-button>
            <el-button
              v-else-if="runId && row.id !== 'output_summary'"
              text
              type="primary"
              @click="openRunDetail"
            >查看</el-button>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="180" show-overflow-tooltip />
        <el-table-column prop="group" label="分组" width="100" show-overflow-tooltip />
        <el-table-column prop="type" label="类型" width="130" show-overflow-tooltip />
        <el-table-column prop="stepKey" label="步骤" width="120" show-overflow-tooltip />
        <el-table-column prop="description" label="描述" min-width="180" show-overflow-tooltip />
        <el-table-column prop="contentType" label="内容类型" width="150" show-overflow-tooltip />
        <el-table-column prop="contentSummary" label="内容摘要" width="120" show-overflow-tooltip />
      </el-table>
    </section>

    <section class="result-section">
      <h4>补充数据</h4>
      <el-collapse v-model="expandedRawPanels">
        <el-collapse-item v-for="panel in rawPanels" :key="panel.name" :title="panel.title" :name="panel.name">
          <pre class="json-block">{{ stringifyJson(panel.data) }}</pre>
        </el-collapse-item>
      </el-collapse>
    </section>
  </div>
</template>

<style scoped>
.algorithm-result-view {
  display: grid;
  gap: 14px;
  min-width: 0;
  color: var(--app-ink-body);
}

.result-error {
  margin-bottom: 2px;
}

.result-attribution {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  padding: 10px 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
}

.result-attribution span {
  color: var(--app-ink-muted);
  font-size: 12px;
  font-weight: 700;
}

.prediction-dashboard {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
  gap: 10px;
}

.signal-card {
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--app-stat-border);
  border-radius: var(--app-radius-sm);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.96) 0%, rgba(248, 251, 255, 0.96) 100%),
    linear-gradient(90deg, rgba(59, 130, 246, 0.15), rgba(14, 165, 233, 0.08));
}

.signal-card span,
.signal-card small {
  display: block;
  color: var(--app-ink-muted);
  font-size: 12px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.signal-card strong {
  display: block;
  margin: 5px 0 3px;
  color: var(--app-ink);
  font-size: 22px;
  line-height: 1.15;
  overflow-wrap: anywhere;
}

.prediction-summary {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(180px, 0.8fr);
  gap: 14px;
  padding: 16px;
  border: 1px solid var(--app-stat-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-stat-bg);
}

.prediction-main,
.summary-side,
.metric-item {
  min-width: 0;
}

.summary-label,
.summary-key,
.summary-chip span,
.metric-item span,
.section-heading span {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.summary-label,
.metric-item span {
  overflow-wrap: anywhere;
}

.summary-value {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-top: 6px;
  min-width: 0;
}

.summary-value strong {
  color: var(--app-ink);
  font-size: 32px;
  line-height: 1.1;
  overflow-wrap: anywhere;
}

.summary-value span {
  color: var(--app-ink-body);
  font-size: 14px;
}

.summary-key {
  display: block;
  margin-top: 6px;
  font-family: var(--app-mono-font);
  overflow-wrap: anywhere;
}

.summary-side {
  display: grid;
  gap: 8px;
  align-content: start;
}

.summary-chip {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: rgba(255, 255, 255, 0.76);
}

.summary-chip strong {
  min-width: 0;
  color: var(--app-ink);
  font-size: 13px;
  text-align: right;
  overflow-wrap: anywhere;
}

.result-section {
  min-width: 0;
}

.result-section h4 {
  margin: 0 0 8px;
  color: var(--app-ink);
  font-size: 14px;
}

.result-section :deep(.el-collapse-item__header),
.result-section :deep(.el-collapse-item__wrap) {
  color: var(--app-ink-body);
}

.result-section :deep(.el-collapse-item__header.is-active) {
  color: var(--app-ink);
}

.section-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
}

.metric-grid.compact {
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
}

.metric-item {
  padding: 10px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
}

.metric-item strong {
  display: block;
  margin-top: 4px;
  color: var(--app-ink);
  font-size: 14px;
  overflow-wrap: anywhere;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.tag-list :deep(.el-tag__content) {
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.result-table {
  width: 100%;
}

.result-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
  overflow-x: auto;
  padding-bottom: 2px;
}

.featured-table-section {
  padding: 12px;
  border: 1px solid var(--app-stat-border);
  border-radius: var(--app-radius-sm);
  background: #fbfdff;
}

.featured-table {
  margin-top: 2px;
}

.artifact-section {
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #ffffff;
}

.json-block {
  max-height: 300px;
  overflow: auto;
  margin: 0;
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fafc;
  color: var(--app-ink-body);
  font: 12px/1.5 var(--app-mono-font);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.json-tree-panel {
  max-height: 420px;
  overflow: auto;
  padding: 10px 2px;
}

.image-preview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 12px;
}

.image-preview-card {
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #fff;
  overflow: hidden;
}

.image-label {
  display: block;
  padding: 8px 12px;
  background: #f8fafc;
  color: var(--app-ink-muted);
  font-size: 12px;
  font-weight: 600;
  border-bottom: 1px solid var(--app-border-soft);
}

.preview-image {
  display: block;
  max-width: 100%;
  height: auto;
}

.empty-result {
  min-height: 120px;
  display: grid;
  place-items: center;
  color: var(--app-ink-muted);
  text-align: center;
}

@media (max-width: 720px) {
  .prediction-summary {
    grid-template-columns: 1fr;
  }

  .summary-value strong {
    font-size: 26px;
  }

  .section-heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .result-pagination {
    justify-content: flex-start;
  }
}
</style>
