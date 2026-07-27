<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Connection, Document, Histogram } from '@element-plus/icons-vue'

import AttributionBadges from '../../components/attribution/AttributionBadges.vue'

const props = defineProps({
  outputSummary: { type: [Object, Array, String, Number, Boolean], default: () => ({}) },
  inputSnapshot: { type: [Object, Array, String, Number, Boolean], default: () => ({}) },
  artifactRefs: { type: Array, default: () => [] },
  status: { type: String, default: '' },
  error: { type: Object, default: null },
  attributions: { type: Array, default: () => [] },
  algorithmId: { type: String, default: '' },
  runId: { type: String, default: '' },
})

const router = useRouter()

const priorityValueKeys = ['value', 'predicted_value', 'prediction', 'score']
const uncertaintyKeys = ['uncertainty', 'std', 'stddev', 'confidence', 'probability']
const modelKeys = ['model_version', 'model', 'algorithm', 'neighbor_count']
const semanticObjectKeys = ['feature_summary', 'metrics', 'metadata']
const metaPredictionKeys = ['property', 'unit', 'target', 'name']

const outputObject = computed(() => normalizeToObject(props.outputSummary))
const inputObject = computed(() => normalizeToObject(props.inputSnapshot))
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
const batchHighlights = computed(() => buildBatchHighlights(batchResultSections.value))
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
    downloadUrl: item.download_url || item.downloadUrl || '',
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
const inputHighlights = computed(() => scalarEntries(inputObject.value).slice(0, 4))
const jumpActions = computed(() => {
  const runId = String(props.runId || '').trim()
  const algorithmId = String(props.algorithmId || '').trim()
  const taskKeyword = runId || algorithmId
  return [
    { label: '知识库', icon: Connection, route: { path: '/knowledge', query: { tab: 'literature' } } },
    {
      label: '任务中心',
      icon: Histogram,
      route: { path: '/tasks/center', query: taskKeyword ? { module_id: 'research-engine', keyword: taskKeyword } : { module_id: 'research-engine' } },
    },
    ...(runId ? [{ label: '报告', icon: Document, route: { path: '/research-engine', query: { run_id: runId, action: 'report' } } }] : []),
  ]
})

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
    .map(([key, rows]) => buildFlatTableSection(key, rows, { preferredNestedKey: 'predictions', limitColumns: 14 }))
}

function buildBatchHighlights(sections) {
  const section = sections[0]
  if (!section) return []
  const numericColumns = section.columns.filter((column) =>
    section.rows.some((row) => typeof row[column] === 'number'),
  )
  const metricCards = numericColumns.slice(0, 5).map((column) => {
    const values = section.rows.map((row) => row[column]).filter((value) => typeof value === 'number')
    const average = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null
    return {
      key: column,
      label: formatLabel(column),
      value: average,
      caption: values.length > 1 ? '平均值' : '预测值',
    }
  })
  return [
    { key: `${section.key}.count`, label: '结果数量', value: section.totalRows, caption: section.title },
    ...metricCards,
  ]
}

function buildMainPrediction(prediction, output) {
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

  const predictionMetrics = []
  for (const [key, value] of Object.entries(prediction)) {
    if (hiddenKeys.has(key)) continue
    if (skippedPredictionKeys.has(key)) continue
    routeEvidenceValue(key, value, predictionMetrics, listSections, tableSections, otherSections)
  }
  if (predictionMetrics.length) {
    metricSections.push({ title: '预测附加信息', entries: predictionMetrics })
  }

  for (const key of semanticObjectKeys) {
    const value = output[key]
    if (isPlainObject(value)) {
      metricSections.push({ title: formatLabel(key), entries: objectEntries(value) })
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
      listSections.push({ title: formatLabel(key), items: value.map(formatScalar), total: value.length })
      return
    }
    if (value.every(isPlainObject)) {
      tableSections.push(buildTableSection(key, value))
      return
    }
  }
  if (isPlainObject(value) && Object.values(value).every((item) => isScalar(item))) {
    metricEntries.push(...objectEntries(value, key))
    return
  }
  if (!isEmptyValue(value)) {
    otherSections.push({ title: formatLabel(key), data: value })
  }
}

function buildTableSection(key, rows) {
  return buildFlatTableSection(key, rows, { limitColumns: 8 })
}

function buildFlatTableSection(key, rows, { preferredNestedKey = '', limitColumns = 8 } = {}) {
  const flatRows = rows.slice(0, 20).map((row) => flattenRow(row, preferredNestedKey))
  const allColumns = Array.from(new Set(rows.flatMap((row) => Object.keys(flattenRow(row, preferredNestedKey)))))
  return {
    key,
    title: formatLabel(key),
    rows: flatRows,
    columns: allColumns.slice(0, limitColumns),
    totalRows: rows.length,
    totalColumns: allColumns.length,
    limitColumns,
  }
}

function flattenRow(row, preferredNestedKey = '') {
  const result = {}
  for (const [key, value] of Object.entries(row)) {
    if (key === preferredNestedKey && isPlainObject(value)) {
      Object.entries(value).forEach(([nestedKey, nestedValue]) => {
        result[nestedKey] = nestedValue
      })
    } else if (isPlainObject(value)) {
      Object.entries(value).forEach(([nestedKey, nestedValue]) => {
        result[`${key}.${nestedKey}`] = nestedValue
      })
    } else {
      result[key] = value
    }
  }
  return result
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

function stringifyJson(value) {
  return JSON.stringify(value ?? null, null, 2)
}

function openJump(route) {
  if (!route) return
  router.push(route)
}
</script>

<template>
  <div class="algorithm-result-view">
    <div v-if="jumpActions.length" class="result-jumpbar">
      <span>快捷跳转</span>
      <div class="jump-actions">
        <el-button
          v-for="action in jumpActions"
          :key="action.label"
          size="small"
          :icon="action.icon"
          @click="openJump(action.route)"
        >
          {{ action.label }}
        </el-button>
      </div>
    </div>

    <section v-if="attributions.length" class="result-attribution">
      <span>模型开发者来源</span>
      <AttributionBadges :attributions="attributions" :limit="3" />
    </section>

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
          <span v-if="section.totalRows > 20 || section.totalColumns > section.limitColumns">
            已显示前 20 行 / {{ section.limitColumns }} 列
          </span>
        </div>
        <el-table :data="section.rows" border size="small" class="result-table featured-table">
          <el-table-column
            v-for="column in section.columns"
            :key="column"
            :prop="column"
            :label="formatLabel(column)"
            min-width="128"
            show-overflow-tooltip
          >
            <template #default="{ row }">{{ summarizeValue(row[column]) }}</template>
          </el-table-column>
        </el-table>
      </section>

      <section v-if="inputHighlights.length" class="result-section">
        <h4>关键输入</h4>
        <div class="metric-grid compact">
          <div v-for="entry in inputHighlights" :key="entry.key" class="metric-item">
            <span>{{ entry.label }}</span>
            <strong>{{ formatScalar(entry.value) }}</strong>
          </div>
        </div>
      </section>

      <section v-for="section in evidence.metricSections" :key="section.title" class="result-section">
        <h4>{{ section.title }}</h4>
        <div class="metric-grid">
          <div v-for="entry in section.entries" :key="entry.key" class="metric-item">
            <span>{{ entry.label }}</span>
            <strong>{{ summarizeValue(entry.value) }}</strong>
          </div>
        </div>
      </section>

      <section v-for="section in evidence.listSections" :key="section.title" class="result-section">
        <h4>{{ section.title }}</h4>
        <div class="tag-list">
          <el-tag v-for="(item, index) in section.items.slice(0, 24)" :key="`${section.title}-${index}`" effect="plain">
            {{ item }}
          </el-tag>
          <span v-if="section.total > 24" class="truncate-note">还有 {{ section.total - 24 }} 项在原始 JSON 中</span>
        </div>
      </section>

      <section v-for="section in evidence.tableSections" :key="section.title" class="result-section">
        <div class="section-heading">
          <h4>{{ section.title }}</h4>
          <span v-if="section.totalRows > 20 || section.totalColumns > section.limitColumns">
            已显示前 20 行 / {{ section.limitColumns }} 列
          </span>
        </div>
        <el-table :data="section.rows" border size="small" class="result-table">
          <el-table-column
            v-for="column in section.columns"
            :key="column"
            :prop="column"
            :label="formatLabel(column)"
            min-width="120"
            show-overflow-tooltip
          >
            <template #default="{ row }">{{ summarizeValue(row[column]) }}</template>
          </el-table-column>
        </el-table>
      </section>

      <section v-if="evidence.otherSections.length" class="result-section">
        <h4>其他输出</h4>
        <el-collapse>
          <el-collapse-item v-for="section in evidence.otherSections" :key="section.title" :title="section.title" :name="section.title">
            <pre class="json-block">{{ stringifyJson(section.data) }}</pre>
          </el-collapse-item>
        </el-collapse>
      </section>
    </template>

    <div v-else-if="!error && !hasStructuredContent" class="empty-result">
      暂无结构化输出
    </div>

    <section v-if="artifactRows.length" class="result-section artifact-section">
      <div class="section-heading">
        <h4>运行产物</h4>
        <span>{{ artifactRows.length }} 项</span>
      </div>
      <el-table :data="artifactRows" border size="small" class="result-table">
        <el-table-column prop="name" label="名称" min-width="180" show-overflow-tooltip />
        <el-table-column prop="group" label="分组" width="100" show-overflow-tooltip />
        <el-table-column prop="type" label="类型" width="130" show-overflow-tooltip />
        <el-table-column prop="stepKey" label="步骤" width="120" show-overflow-tooltip />
        <el-table-column prop="description" label="描述" min-width="180" show-overflow-tooltip />
        <el-table-column prop="contentType" label="内容类型" width="150" show-overflow-tooltip />
        <el-table-column prop="contentSummary" label="内容摘要" width="120" show-overflow-tooltip />
        <el-table-column label="下载" width="86">
          <template #default="{ row }">
            <el-link v-if="row.downloadUrl" :href="row.downloadUrl" type="primary">下载</el-link>
            <span v-else>-</span>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section class="result-section">
      <h4>补充数据</h4>
      <el-collapse>
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
}

.result-jumpbar {
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

.result-jumpbar > span {
  color: var(--app-ink-muted);
  font-size: 12px;
  font-weight: 700;
}

.jump-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
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
.section-heading span,
.truncate-note {
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
}
</style>
