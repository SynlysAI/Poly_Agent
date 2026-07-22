<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowRight, Box, Clock, Cpu, DataAnalysis, Document, Key, Refresh, Search, UploadFilled, VideoPlay,
} from '@element-plus/icons-vue'

import {
  getApiErrorMessage,
  listAlgorithmPackages,
  listAlgorithmRuns,
  listAlgorithms,
  listAlgorithmVersions,
} from '../api/polyAgentApi'
import AlgorithmManagementPanel from './vertical-prediction/AlgorithmManagementPanel.vue'
import AlgorithmHandoffPanel from './vertical-prediction/AlgorithmHandoffPanel.vue'
import AlgorithmResourcePanel from './vertical-prediction/AlgorithmResourcePanel.vue'
import AlgorithmRunHistoryPanel from './vertical-prediction/AlgorithmRunHistoryPanel.vue'
import AlgorithmTestPanel from './vertical-prediction/AlgorithmTestPanel.vue'
import AlgorithmUploadPanel from './vertical-prediction/AlgorithmUploadPanel.vue'
import AttributionBadges from '../components/attribution/AttributionBadges.vue'
import { formatApiDateTime } from '../utils/datetime'

const route = useRoute()
const router = useRouter()

const detailTabMap = { management: 'api', test: 'experience', runs: 'api' }
const routeModes = new Set(['center', 'doc', 'upload', 'resources', 'detail'])

const activeMode = ref(normalizeMode(route.query.tab))
const detailActiveTab = ref(normalizeDetailTab(route.query.tab))
const loading = ref(false)
const refreshKey = ref(0)
const algorithms = ref([])
const versionMap = ref({})
const summary = ref({ packages: 0, activeAlgorithms: 0, recentRuns: 0, failedRuns: 0 })
const searchText = ref('')
const statusFilter = ref('')
const typeFilter = ref('')
const materialFilter = ref('')
const selectedAlgorithmId = ref(normalizeQueryString(route.query.algorithm_id))
const selectedHandoffId = ref(normalizeQueryString(route.query.handoff_id))
const docEntryMode = ref(normalizeQueryString(route.query.doc_mode) === 'download' ? 'download' : 'upload')

const selectedAlgorithm = computed(() => algorithms.value.find((item) => item.algorithm_id === selectedAlgorithmId.value) || null)
const selectedVersions = computed(() => versionMap.value[selectedAlgorithmId.value] || [])
const activeVersion = computed(() =>
  selectedVersions.value.find((item) => item.version_id === selectedAlgorithm.value?.active_version_id)
  || selectedVersions.value.find((item) => item.status === 'active')
  || selectedVersions.value[0]
  || null,
)

const statusItems = computed(() => [
  { label: '已接入模型', value: summary.value.packages, icon: UploadFilled },
  { label: '可用模型', value: summary.value.activeAlgorithms, icon: Box },
  { label: '最近运行', value: summary.value.recentRuns, icon: Clock },
  { label: '运行环境', value: '隔离执行', icon: Cpu },
])

const filteredAlgorithms = computed(() => {
  const keyword = searchText.value.trim().toLowerCase()
  return algorithms.value.filter((item) => {
    const textMatch = !keyword || [item.name, item.algorithm_id, item.description].some((value) => String(value || '').toLowerCase().includes(keyword))
    const statusMatch = !statusFilter.value || item.status === statusFilter.value
    const typeMatch = !typeFilter.value || item.type === typeFilter.value
    const materialMatch = !materialFilter.value || (item.material_scope || []).includes(materialFilter.value)
    return textMatch && statusMatch && typeMatch && materialMatch
  })
})

const typeOptions = computed(() => Array.from(new Set(algorithms.value.map((item) => item.type).filter(Boolean))))
const statusOptions = computed(() => Array.from(new Set(algorithms.value.map((item) => item.status).filter(Boolean))))
const materialOptions = computed(() => Array.from(new Set(algorithms.value.flatMap((item) => item.material_scope || []).filter(Boolean))))

const detailHighlights = computed(() => {
  const algo = selectedAlgorithm.value
  if (!algo) return []
  const inputFields = Object.keys(algo.input_schema?.fields || {})
  const outputFields = Object.keys(algo.output_schema?.fields || {})
  return [
    { title: '可直接测试', text: inputFields.length ? `根据 ${inputFields.join('、')} 自动生成输入表单。` : '模型输入字段已接入测试台。' },
    { title: '版本可治理', text: activeVersion.value ? `当前可用版本为 ${activeVersion.value.version}，支持日志、重部署、冻结和下线。` : '上传版本会进入校验、部署、激活流程。' },
    { title: '输出可追溯', text: outputFields.length ? `预测结果包含 ${outputFields.join('、')} 等字段。` : '每次运行都会保留输入、输出、结果文件与版本摘要。' },
  ]
})

const selectedAlgorithmAttributions = computed(() => algorithmAttributions(selectedAlgorithm.value))

const bestPracticeItems = computed(() => [
  '先在互动体验里用最小样例完成一次预测，确认字段名和类型与模型说明一致。',
  '上线新版本后保留旧版本一段时间；确认结果稳定后再冻结或下线旧版本。',
  '样例输入应覆盖常见材料结构，输出字段命名保持稳定，便于后续研发流程复用。',
])

function normalizeQueryString(value) {
  return Array.isArray(value) ? value[0] || '' : value || ''
}

function normalizeMode(tab) {
  const value = normalizeQueryString(tab)
  if (value === 'upload') return 'upload'
  if (value === 'doc' || value === 'handoff') return 'doc'
  if (value === 'detail' || detailTabMap[value]) return 'detail'
  return routeModes.has(value) ? value : 'doc'
}

function normalizeDetailTab(tab) {
  const value = normalizeQueryString(tab)
  return detailTabMap[value] || (['experience', 'highlights', 'practice', 'docs', 'api'].includes(value) ? value : 'experience')
}

function syncRoute() {
  const query = { ...route.query }
  if (activeMode.value === 'center') {
    query.tab = 'center'
    delete query.algorithm_id
    delete query.handoff_id
    delete query.doc_mode
  } else if (activeMode.value === 'doc') {
    query.tab = 'doc'
    delete query.algorithm_id
    if (selectedHandoffId.value) query.handoff_id = selectedHandoffId.value
    else delete query.handoff_id
    query.doc_mode = docEntryMode.value
  } else if (activeMode.value === 'upload') {
    query.tab = 'upload'
    delete query.algorithm_id
    delete query.handoff_id
    delete query.doc_mode
  } else if (activeMode.value === 'resources') {
    query.tab = 'resources'
    delete query.algorithm_id
    delete query.handoff_id
    delete query.doc_mode
  } else {
    query.tab = 'detail'
    if (selectedAlgorithmId.value) query.algorithm_id = selectedAlgorithmId.value
    delete query.handoff_id
    delete query.doc_mode
  }
  if (JSON.stringify(query) !== JSON.stringify(route.query)) router.replace({ query })
}

watch(
  () => route.query,
  (query) => {
    activeMode.value = normalizeMode(query.tab)
    detailActiveTab.value = normalizeDetailTab(query.tab)
    selectedAlgorithmId.value = normalizeQueryString(query.algorithm_id) || selectedAlgorithmId.value
    selectedHandoffId.value = normalizeQueryString(query.handoff_id)
    docEntryMode.value = normalizeQueryString(query.doc_mode) === 'download' ? 'download' : 'upload'
  },
)

watch([activeMode, selectedAlgorithmId, selectedHandoffId, docEntryMode], syncRoute)

async function loadData() {
  loading.value = true
  try {
    const [packages, algorithmData, runs] = await Promise.all([
      listAlgorithmPackages({ page: 1, page_size: 100 }),
      listAlgorithms({ algorithm_family: 'vertical_prediction', page: 1, page_size: 100 }),
      listAlgorithmRuns({ page: 1, page_size: 100 }),
    ])
    algorithms.value = (algorithmData.items || []).filter((item) => item.source === 'uploaded_package')
    const uploadedRuns = (runs.items || []).filter((item) => item.algorithm_version_id)
    summary.value = {
      packages: packages.total || packages.items?.length || 0,
      activeAlgorithms: algorithms.value.filter((item) => item.status === 'active').length,
      recentRuns: uploadedRuns.length,
      failedRuns: uploadedRuns.filter((item) => item.status === 'failed').length,
    }
    if (!selectedAlgorithmId.value && algorithms.value[0]) selectedAlgorithmId.value = algorithms.value[0].algorithm_id
    await loadVersionsForCards()
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
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

function handleChanged(packageInfo) {
  refreshKey.value += 1
  if (packageInfo?.algorithm_id) selectedAlgorithmId.value = packageInfo.algorithm_id
  loadData()
}

function handleRunCreated() {
  loadData()
}

function openUpload() {
  activeMode.value = 'upload'
}

function openDoc(mode = 'upload') {
  docEntryMode.value = mode
  selectedHandoffId.value = ''
  activeMode.value = 'doc'
}

function openCenter() {
  activeMode.value = 'center'
}

function openResources() {
  activeMode.value = 'resources'
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

function algorithmAttributions(algorithm) {
  if (!algorithm) return []
  return [
    algorithm.developer_attribution,
    ...(algorithm.framework_attributions || []),
    ...(algorithm.method_attributions || []),
  ].filter(Boolean)
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

      <section class="entry-band" v-loading="loading" aria-label="算法接入入口">
        <button class="entry-card" type="button" @click="openDoc('upload')">
          <span>有需求文档</span>
          <strong>上传文档，系统生成草案</strong>
        </button>
        <button class="entry-card" type="button" @click="openDoc('download')">
          <span>没有需求文档</span>
          <strong>先下载模板，再填写上传</strong>
        </button>
        <button class="entry-card subtle" type="button" @click="openUpload">
          <span>更多方式</span>
          <strong>模型文件 / 标准 ZIP</strong>
        </button>
        <button class="entry-card subtle" type="button" @click="openResources">
          <span>大文件资源</span>
          <strong>登记权重 / 数据库路径</strong>
        </button>
      </section>

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
        <el-button text type="primary" @click="openResources">资源管理</el-button>
      </div>
      <AlgorithmUploadPanel @changed="handleChanged" @view-detail="openDetail" />
    </template>

    <template v-if="activeMode === 'resources'">
      <div class="subnav-row">
        <el-button text @click="openCenter">返回模型中心</el-button>
        <el-button text type="primary" @click="openUpload">高级导入</el-button>
      </div>
      <AlgorithmResourcePanel @changed="handleChanged" />
    </template>

    <template v-else-if="activeMode === 'detail' && selectedAlgorithm">
      <div class="subnav-row">
        <el-button text @click="openCenter">返回模型中心</el-button>
        <el-button text type="primary" @click="openUpload">上传新版本</el-button>
      </div>
      <section class="detail-banner">
        <div class="model-avatar"><el-icon><DataAnalysis /></el-icon></div>
        <div class="detail-main">
          <div class="detail-title-row">
            <h2>{{ selectedAlgorithm.name }}</h2>
            <el-tag :type="statusType(selectedAlgorithm.status)">{{ statusLabel(selectedAlgorithm.status) }}</el-tag>
          </div>
          <p>{{ selectedAlgorithm.description || '该模型已接入垂类预测工作台，可用于测试调用、版本管理和研发流程。' }}</p>
          <AttributionBadges :attributions="selectedAlgorithmAttributions" />
          <div class="detail-meta">
            <span>{{ selectedAlgorithm.algorithm_id }}</span>
            <span>{{ typeLabel(selectedAlgorithm.type) }}</span>
            <span>版本 {{ activeVersion?.version || selectedAlgorithm.version || '-' }}</span>
            <span>更新 {{ formatDate(activeVersion?.updated_at) }}</span>
          </div>
        </div>
        <div class="detail-actions">
          <el-button :icon="VideoPlay" type="primary" @click="detailActiveTab = 'experience'">立即体验</el-button>
          <el-button :icon="Key" @click="detailActiveTab = 'api'">版本治理</el-button>
        </div>
      </section>

      <section class="detail-panel">
        <el-tabs v-model="detailActiveTab" class="detail-tabs">
          <el-tab-pane label="互动体验" name="experience">
            <AlgorithmTestPanel :refresh-key="refreshKey" :algorithm-id="selectedAlgorithm.algorithm_id" :show-toolbar="false" @run-created="handleRunCreated" />
          </el-tab-pane>
          <el-tab-pane label="亮点介绍" name="highlights">
            <div class="info-grid">
              <article v-for="item in detailHighlights" :key="item.title" class="info-card">
                <h3>{{ item.title }}</h3>
                <p>{{ item.text }}</p>
              </article>
            </div>
          </el-tab-pane>
          <el-tab-pane label="最佳实践" name="practice">
            <div class="practice-list">
              <div v-for="(item, index) in bestPracticeItems" :key="item" class="practice-item">
                <strong>{{ index + 1 }}</strong>
                <span>{{ item }}</span>
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
                <span>外部集成时按输入字段提交请求，并记录模型 ID 与版本 ID，便于结果追溯。</span>
              </section>
            </div>
          </el-tab-pane>
          <el-tab-pane label="API Key / 版本治理" name="api">
            <div class="governance-layout">
              <AlgorithmManagementPanel :refresh-key="refreshKey" :algorithm-id="selectedAlgorithm.algorithm_id" :show-selector="false" @changed="handleChanged" />
              <section class="history-panel">
                <h3>运行记录</h3>
                <AlgorithmRunHistoryPanel :refresh-key="refreshKey" />
              </section>
            </div>
          </el-tab-pane>
        </el-tabs>
      </section>
    </template>

    <template v-else-if="activeMode === 'center'">
      <div class="model-center-layout">
        <aside class="filter-panel">
          <div class="filter-title">筛选</div>
          <el-input v-model="searchText" :prefix-icon="Search" placeholder="搜索模型名称、ID" clearable />
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
              <el-button :icon="Document" @click="openDoc('upload')">需求文档</el-button>
              <el-button :icon="Key" @click="openResources">资源管理</el-button>
              <el-button type="primary" :icon="UploadFilled" @click="openUpload">高级导入</el-button>
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
              <p>{{ item.description || '已上传的垂类预测模型，可在详情页进行测试调用、版本治理和运行追溯。' }}</p>
              <AttributionBadges :attributions="algorithmAttributions(item)" />
              <div class="model-tags">
                <el-tag size="small" effect="plain">{{ typeLabel(item.type) }}</el-tag>
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
              <el-button @click="openDoc('download')">需求文档</el-button>
              <el-button type="primary" @click="openUpload">高级导入</el-button>
            </div>
          </div>
        </main>
      </div>
    </template>
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
.hero-actions, .detail-actions, .subnav-row, .list-actions, .empty-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.hero-actions { justify-content: flex-end; }
.entry-band { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.entry-card { min-width: 0; display: grid; gap: 6px; padding: 14px 16px; border: 1px solid var(--app-border); border-radius: var(--app-radius-md); background: #fff; color: inherit; text-align: left; cursor: pointer; transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease; }
.entry-card:hover { border-color: #bfdbfe; box-shadow: 0 10px 22px rgba(37, 99, 235, 0.09); transform: translateY(-1px); }
.entry-card:focus-visible { outline: 3px solid var(--app-primary-light); outline-offset: 2px; }
.entry-card span { color: var(--app-ink-muted); font-size: 12px; }
.entry-card strong { color: var(--app-ink); font-size: 15px; line-height: 1.35; overflow-wrap: anywhere; }
.entry-card.subtle { background: #f8fbff; }
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
.detail-tabs :deep(.el-tabs__header) { margin-bottom: 18px; }
.info-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.info-card { padding: 16px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-md); background: #f8fbff; }
.info-card p { margin: 8px 0 0; color: var(--app-ink-muted); font-size: 13px; line-height: 1.65; }
.practice-list { display: grid; gap: 12px; max-width: 880px; }
.practice-item { display: grid; grid-template-columns: 32px minmax(0, 1fr); gap: 12px; align-items: start; padding: 14px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-md); }
.practice-item strong { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 50%; background: var(--app-primary-light); color: var(--app-primary-active); }
.practice-item span { color: var(--app-ink-body); font-size: 14px; line-height: 1.7; }
.docs-layout, .governance-layout { display: grid; gap: 16px; }
.docs-layout section h3, .history-panel h3 { margin-bottom: 10px; }
.api-note { display: flex; align-items: center; gap: 10px; padding: 12px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-sm); background: #f8fbff; color: var(--app-ink-muted); font-size: 13px; }
.history-panel { padding-top: 16px; border-top: 1px solid var(--app-border-soft); }
@media (max-width: 1180px) {
  .entry-band { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .model-card-grid, .info-grid { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .model-page-hero, .list-head, .detail-banner { grid-template-columns: 1fr; flex-direction: column; align-items: stretch; }
  .hero-actions { justify-content: flex-start; }
  .entry-band { grid-template-columns: 1fr; }
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
