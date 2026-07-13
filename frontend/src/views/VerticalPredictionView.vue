<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Box, Clock, Cpu, UploadFilled } from '@element-plus/icons-vue'

import { getApiErrorMessage, listAlgorithmPackages, listAlgorithmRuns, listAlgorithms } from '../api/polyAgentApi'
import AlgorithmManagementPanel from './vertical-prediction/AlgorithmManagementPanel.vue'
import AlgorithmRunHistoryPanel from './vertical-prediction/AlgorithmRunHistoryPanel.vue'
import AlgorithmTestPanel from './vertical-prediction/AlgorithmTestPanel.vue'
import AlgorithmUploadPanel from './vertical-prediction/AlgorithmUploadPanel.vue'

const route = useRoute()
const router = useRouter()
const tabNames = new Set(['upload', 'management', 'test', 'runs'])

const activeTab = ref(normalizeTab(route.query.tab))
const loading = ref(false)
const refreshKey = ref(0)
const uploadCompleted = ref(false)
const summary = ref({ packages: 0, activeAlgorithms: 0, recentRuns: 0, failedRuns: 0 })

const statusItems = computed(() => [
  { label: '上传包', value: summary.value.packages, icon: UploadFilled },
  { label: 'Active 算法', value: summary.value.activeAlgorithms, icon: Box },
  { label: '最近运行', value: summary.value.recentRuns, icon: Clock },
  { label: '运行器', value: '本机适配层', icon: Cpu },
])

const guideItems = computed(() => {
  const common = [
    { title: '上传格式', text: '推荐上传标准 ZIP 包，至少包含 Python 源文件和依赖说明。系统会生成算法契约并校验输入输出。' },
    { title: '管理版本', text: '上传成功后进入算法管理，确认版本状态、运行依赖和 schema，再激活可用版本。' },
    { title: '测试调用', text: '使用测试调用验证输入 JSON、输出摘要和 artifact；运行记录用于回溯每次调用。' },
  ]
  if (activeTab.value === 'upload') return common
  if (activeTab.value === 'management') {
    return [
      { title: '管理中心', text: '这里处理算法版本治理、激活状态和版本元信息，不直接运行预测。' },
      ...common.slice(1),
    ]
  }
  if (activeTab.value === 'test') {
    return [
      { title: '测试输入', text: '按算法版本的 input schema 填写 JSON。失败时先检查字段名、类型和必填项。' },
      { title: '运行结果', text: '测试调用会生成运行记录，可在运行记录 tab 查看状态、输出和错误信息。' },
    ]
  }
  return [
    { title: '运行记录', text: '这里展示上传模型产生的预测调用记录，用于追溯输入、输出、版本和失败原因。' },
    { title: '下一步', text: '需要重新验证时回到测试调用；需要切换版本时回到算法管理。' },
  ]
})

function normalizeTab(tab) {
  const value = Array.isArray(tab) ? tab[0] : tab
  return tabNames.has(value) ? value : 'upload'
}

function syncActiveTabQuery() {
  if (route.query.tab === activeTab.value) return
  router.replace({ query: { ...route.query, tab: activeTab.value } })
}

watch(
  () => route.query.tab,
  (tab) => {
    const nextTab = normalizeTab(tab)
    if (activeTab.value !== nextTab) activeTab.value = nextTab
  },
)

watch(activeTab, syncActiveTabQuery)

async function loadSummary() {
  loading.value = true
  try {
    const [packages, algorithms, runs] = await Promise.all([
      listAlgorithmPackages({ page: 1, page_size: 100 }),
      listAlgorithms({ algorithm_family: 'vertical_prediction', page: 1, page_size: 100 }),
      listAlgorithmRuns({ page: 1, page_size: 100 }),
    ])
    const uploadedAlgorithms = (algorithms.items || []).filter((item) => item.source === 'uploaded_package')
    const uploadedRuns = (runs.items || []).filter((item) => item.algorithm_version_id)
    summary.value = {
      packages: packages.total || packages.items?.length || 0,
      activeAlgorithms: uploadedAlgorithms.filter((item) => item.status === 'active').length,
      recentRuns: uploadedRuns.length,
      failedRuns: uploadedRuns.filter((item) => item.status === 'failed').length,
    }
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

function handleChanged() {
  refreshKey.value += 1
  uploadCompleted.value = true
  loadSummary()
}

function goToManagement() {
  activeTab.value = 'management'
}

onMounted(() => {
  syncActiveTabQuery()
  loadSummary()
})
</script>

<template>
  <div class="vertical-prediction-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">任务提交 / 预测模型</p>
        <h1>垂类预测模型</h1>
        <p>上传和治理 Python 算法版本，执行指定版本预测，并追溯每次运行的输入、输出与摘要。</p>
      </div>
      <el-tag type="success" effect="dark">P0-MVP 在线</el-tag>
    </header>

    <section v-if="activeTab !== 'upload'" class="status-band" v-loading="loading" aria-label="垂类预测模型状态摘要">
      <div v-for="item in statusItems" :key="item.label" class="status-item">
        <el-icon><component :is="item.icon" /></el-icon>
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
      </div>
    </section>

    <div class="prediction-workspace">
      <section class="workspace-panel">
        <template v-if="activeTab === 'upload'">
          <AlgorithmUploadPanel @changed="handleChanged" />
          <div v-if="uploadCompleted" class="upload-next-action">
            <el-button type="primary" @click="goToManagement">进入模型管理</el-button>
          </div>
        </template>
        <el-tabs v-else v-model="activeTab" class="workspace-tabs">
          <el-tab-pane label="算法管理" name="management"><AlgorithmManagementPanel :refresh-key="refreshKey" @changed="handleChanged" /></el-tab-pane>
          <el-tab-pane label="测试调用" name="test"><AlgorithmTestPanel :refresh-key="refreshKey" @run-created="handleChanged" /></el-tab-pane>
          <el-tab-pane label="运行记录" name="runs"><AlgorithmRunHistoryPanel :refresh-key="refreshKey" /></el-tab-pane>
        </el-tabs>
      </section>

      <aside class="guide-panel">
        <h3>使用说明</h3>
        <div class="guide-list">
          <div v-for="item in guideItems" :key="item.title" class="guide-item">
            <strong>{{ item.title }}</strong>
            <span>{{ item.text }}</span>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.vertical-prediction-page { display: grid; gap: 16px; }
.page-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.eyebrow { margin: 0 0 4px; color: var(--app-primary-active); font-size: 12px; font-weight: 700; }
h1 { margin: 0; color: var(--app-ink); font-size: 26px; line-height: 1.25; letter-spacing: 0; }
.page-heading p:last-child { max-width: 760px; margin: 7px 0 0; color: var(--app-ink-muted); font-size: 14px; }
.status-band { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border: 1px solid var(--app-border); border-radius: var(--app-radius-sm); background: #fff; }
.status-item { min-width: 0; display: grid; grid-template-columns: 22px 1fr auto; align-items: center; gap: 8px; padding: 12px 14px; border-right: 1px solid var(--app-border-soft); }
.status-item:last-child { border-right: 0; }
.status-item .el-icon { color: var(--app-primary); }
.status-item span { color: var(--app-ink-muted); font-size: 12px; }
.status-item strong { color: var(--app-ink); font-size: 14px; overflow-wrap: anywhere; }
.prediction-workspace { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 16px; align-items: start; }
.workspace-panel { min-width: 0; overflow-x: auto; padding: 0 14px 18px; border: 1px solid var(--app-border); border-radius: var(--app-radius-sm); background: #fff; }
.workspace-tabs :deep(.el-tabs__header) { margin-bottom: 18px; }
.upload-next-action { display: flex; justify-content: flex-end; padding-top: 14px; border-top: 1px solid var(--app-border-soft); }
.guide-panel { position: sticky; top: 76px; padding: 16px; border: 1px solid var(--app-border); border-radius: var(--app-radius-sm); background: #fff; }
.guide-panel h3 { margin: 0 0 12px; color: var(--app-ink); font-size: 15px; }
.guide-list { display: grid; gap: 12px; }
.guide-item { display: grid; gap: 4px; padding: 12px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-sm); background: #f8fbff; }
.guide-item strong { color: var(--app-ink); font-size: 14px; }
.guide-item span { color: var(--app-ink-muted); font-size: 13px; line-height: 1.6; }
@media (max-width: 900px) { .status-band { grid-template-columns: repeat(2, minmax(0, 1fr)); } .status-item:nth-child(2) { border-right: 0; } .status-item:nth-child(-n+2) { border-bottom: 1px solid var(--app-border-soft); } .prediction-workspace { grid-template-columns: 1fr; } .guide-panel { position: static; } }
@media (max-width: 560px) { .page-heading { flex-direction: column; } .status-band { grid-template-columns: 1fr; } .status-item { border-right: 0; border-bottom: 1px solid var(--app-border-soft); } .status-item:last-child { border-bottom: 0; } .workspace-panel { padding-inline: 10px; } }
</style>
