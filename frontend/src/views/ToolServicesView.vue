<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, Edit, Refresh, View as ViewIcon } from '@element-plus/icons-vue'

import {
  checkIntegrationConfig,
  getAlgorithm,
  getApiErrorMessage,
  getIntegrationStatus,
  listAlgorithms,
  listIntegrationConfigs,
  upsertIntegrationConfig,
} from '../api/polyAgentApi'

const services = ref([])
const configs = ref([])
const loadingStatus = ref(false)
const loadingConfigs = ref(false)
const saving = ref(false)
const actionLoading = ref('')
const configError = ref('')
const editVisible = ref(false)
const editingServiceKey = ref('')
const activeTab = ref('status')

// ── ResearchEngine 算法清单 ──
const algorithms = ref([])
const algoLoading = ref(false)
const algoDetailVisible = ref(false)
const algoDetail = ref(null)
const algoFilters = reactive({ type: '', material_scope: '', keyword: '' })

const algoTypeOptions = [
  { label: '全部类型', value: '' },
  { label: '检索器', value: 'retriever' },
  { label: '预测器', value: 'predictor' },
  { label: '模拟器', value: 'simulator' },
  { label: '优化器', value: 'optimizer' },
]

function algoTypeTag(type) {
  const map = { retriever: 'info', predictor: 'success', simulator: 'warning', optimizer: 'danger' }
  return map[type] || 'info'
}

function algoTypeLabel(type) {
  const map = { retriever: '检索器', predictor: '预测器', simulator: '模拟器', optimizer: '优化器' }
  return map[type] || type
}

function algoStatusTag(status) {
  const map = { active: 'success', pending_encapsulation: 'warning', in_development: 'info', frozen: 'info', decommissioned: 'danger' }
  return map[status] || 'info'
}

function algoStatusLabel(status) {
  const map = { active: '已接入', pending_encapsulation: '待封装', in_development: '开发中', frozen: '冻结', decommissioned: '下线' }
  return map[status] || status
}

const filteredAlgos = computed(() => {
  const kw = algoFilters.keyword.trim().toLowerCase()
  return algorithms.value.filter((item) => {
    const matchesType = !algoFilters.type || item.type === algoFilters.type
    const matchesMaterial = !algoFilters.material_scope || (item.material_scope || []).includes(algoFilters.material_scope)
    const haystack = `${item.name} ${item.algorithm_id} ${item.description || ''}`.toLowerCase()
    return matchesType && matchesMaterial && (!kw || haystack.includes(kw))
  })
})

async function loadAlgos() {
  algoLoading.value = true
  try {
    const data = await listAlgorithms({ page: 1, page_size: 100 })
    algorithms.value = data.items || []
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    algoLoading.value = false
  }
}

async function showAlgoDetail(algo) {
  try {
    algoDetail.value = await getAlgorithm(algo.algorithm_id)
    algoDetailVisible.value = true
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  }
}

const form = reactive({
  display_name: '',
  service_type: 'workflow',
  enabled: false,
  endpoint: '',
  config_summary: '{}',
  secret_refs: '{}',
})

const serviceTypeOptions = [
  'experiment',
  'provenance',
  'workflow',
  'worker',
  'artifact',
  'optimizer',
]

const currentConfig = computed(() => configs.value.find((item) => item.service_key === editingServiceKey.value))

const serviceCatalog = {
  'computation-worker': { name: '计算 Worker', group: '运行组件', hint: '领取 queued run 并执行真实计算 workflow' },
  'artifact-store': { name: 'Artifact 存储', group: '核心存储', hint: '保存结构、日志、结果 JSON 和下载文件' },
  rdkit: { name: 'RDKit', group: '计算工具链', hint: 'SMILES 解析和三维结构初猜' },
  openbabel: { name: 'OpenBabel', group: '计算工具链', hint: '结构格式转换和备用三维结构生成' },
  xtb: { name: 'xTB', group: '计算工具链', hint: '低成本粗优化和单点计算' },
  crest: { name: 'CREST', group: '计算工具链', hint: '构象搜索，给 xTB/ORCA 提供合理姿态' },
  orca: { name: 'ORCA', group: '计算工具链', hint: '高精度 DFT/激发态精加工' },
  'alchemist-backend': { name: 'Alchemist', group: '优化与实验', hint: '贝叶斯优化和实验设计后端' },
  speclabos: { name: 'SpecLabOS', group: '优化与实验', hint: '真实实验系统接口，需配置 endpoint' },
  atlas: { name: 'Atlas', group: '优化与实验', hint: '优化器服务' },
  docker: { name: 'Docker', group: '运行组件', hint: '可选容器运行能力' },
}

const serviceGroups = computed(() => {
  const groups = ['核心存储', '计算工具链', '优化与实验', '运行组件']
  return groups.map((group) => ({
    name: group,
    items: services.value.filter((item) => (serviceCatalog[item.service]?.group || '运行组件') === group),
  })).filter((group) => group.items.length)
})

const healthSummary = computed(() => {
  const required = ['artifact-store', 'rdkit', 'openbabel', 'xtb', 'crest', 'orca']
  const items = services.value.filter((item) => required.includes(item.service))
  const ready = items.filter((item) => ['up', 'available'].includes(item.status)).length
  return { ready, total: items.length }
})

function statusTag(status) {
  if (['up', 'available'].includes(status)) return 'success'
  if (status === 'degraded') return 'warning'
  if (['down', 'failed'].includes(status)) return 'danger'
  return 'info'
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function formatDetails(details) {
  if (!details || Object.keys(details).length === 0) return '{}'
  return JSON.stringify(details, null, 2)
}

function serviceName(service) {
  return serviceCatalog[service]?.name || service
}

function serviceHint(service) {
  return serviceCatalog[service]?.hint || '外部集成服务'
}

function statusLabel(status) {
  const map = {
    up: '可用',
    available: '可用',
    degraded: '异常',
    down: '不可用',
    failed: '失败',
    not_available: '未安装',
    not_configured: '未配置',
    disabled: '已停用',
    unknown: '未知',
  }
  return map[status] || status
}

function servicePrimaryDetail(row) {
  const details = row.details || {}
  if (details.path) return details.path
  if (details.url) return details.url
  if (details.root) return details.root
  if (details.host && details.port) return `${details.host}:${details.port}`
  if (details.worker_id) return details.worker_id
  return '-'
}

function serviceReason(row) {
  const details = row.details || {}
  return details.reason || details.last_error_summary || details.stderr || ''
}

function formatConfigSummary(row) {
  const parts = []
  if (row.endpoint) parts.push(row.endpoint)
  if (row.config_summary && Object.keys(row.config_summary).length) parts.push(JSON.stringify(row.config_summary))
  if (row.secret_refs && Object.keys(row.secret_refs).length) parts.push(`secrets:${Object.keys(row.secret_refs).join(',')}`)
  return parts.join('\n') || '-'
}

function parseJsonObject(value, label) {
  const text = String(value || '').trim()
  if (!text) return {}
  let parsed
  try {
    parsed = JSON.parse(text)
  } catch {
    throw new Error(`${label} 必须是 JSON object`)
  }
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error(`${label} 必须是 JSON object`)
  }
  return parsed
}

async function loadStatus() {
  loadingStatus.value = true
  try {
    const data = await getIntegrationStatus()
    services.value = data.items || []
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loadingStatus.value = false
  }
}

async function loadConfigs({ quiet = false } = {}) {
  loadingConfigs.value = true
  configError.value = ''
  try {
    const data = await listIntegrationConfigs()
    configs.value = data.items || []
  } catch (error) {
    configError.value = getApiErrorMessage(error)
    if (!quiet) ElMessage.error(configError.value)
  } finally {
    loadingConfigs.value = false
  }
}

async function loadAll() {
  await Promise.all([loadStatus(), loadConfigs({ quiet: true })])
}

function openEdit(row) {
  editingServiceKey.value = row.service_key
  form.display_name = row.display_name || ''
  form.service_type = row.service_type || 'workflow'
  form.enabled = Boolean(row.enabled)
  form.endpoint = row.endpoint || ''
  form.config_summary = JSON.stringify(row.config_summary || {}, null, 2)
  form.secret_refs = JSON.stringify(row.secret_refs || {}, null, 2)
  editVisible.value = true
}

async function saveConfig() {
  if (!editingServiceKey.value) return
  saving.value = true
  try {
    const configSummary = parseJsonObject(form.config_summary, 'Config summary')
    const secretRefs = parseJsonObject(form.secret_refs, 'Secret refs')
    await upsertIntegrationConfig(editingServiceKey.value, {
      display_name: form.display_name,
      service_type: form.service_type,
      enabled: form.enabled,
      endpoint: form.endpoint || null,
      config_summary: configSummary,
      secret_refs: secretRefs,
    })
    ElMessage.success('配置已保存')
    editVisible.value = false
    await Promise.all([loadConfigs(), loadStatus()])
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error) || error.message)
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(row, enabled) {
  actionLoading.value = `${row.service_key}:toggle`
  try {
    await upsertIntegrationConfig(row.service_key, {
      display_name: row.display_name,
      service_type: row.service_type,
      enabled,
      endpoint: row.endpoint,
      config_summary: row.config_summary || {},
      secret_refs: row.secret_refs || {},
    })
    await loadConfigs()
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
    await loadConfigs({ quiet: true })
  } finally {
    actionLoading.value = ''
  }
}

async function handleCheck(row) {
  actionLoading.value = `${row.service_key}:check`
  try {
    const data = await checkIntegrationConfig(row.service_key)
    ElMessage.success(`${row.display_name}: ${data.status}`)
    await Promise.all([loadConfigs(), loadStatus()])
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    actionLoading.value = ''
  }
}

onMounted(() => {
  loadAll()
  loadAlgos()
})
</script>

<template>
  <div class="tools-view">
    <section class="panel">
      <div class="panel-header tools-header">
        <div>
          <h3 class="panel-title">工具服务</h3>
          <p class="panel-subtitle">真实计算工具链、Mongo/artifact、SpecLabOS 和优化服务状态。</p>
        </div>
        <el-tag size="large" :type="healthSummary.ready === healthSummary.total ? 'success' : 'warning'">
          核心服务 {{ healthSummary.ready }}/{{ healthSummary.total }}
        </el-tag>
        <el-button :icon="Refresh" :loading="loadingStatus || loadingConfigs" @click="loadAll">刷新</el-button>
      </div>
    </section>

    <section class="panel">
      <div class="panel-body">
        <el-tabs v-model="activeTab">
          <el-tab-pane label="状态" name="status">
            <div v-loading="loadingStatus" class="service-groups">
              <section v-for="group in serviceGroups" :key="group.name" class="service-group">
                <h4>{{ group.name }}</h4>
                <div class="service-card-grid">
                  <article v-for="row in group.items" :key="row.service" class="service-card">
                    <div class="service-card-header">
                      <div>
                        <strong>{{ serviceName(row.service) }}</strong>
                        <span>{{ serviceHint(row.service) }}</span>
                      </div>
                      <el-tag size="small" :type="statusTag(row.status)">{{ statusLabel(row.status) }}</el-tag>
                    </div>
                    <dl class="service-facts">
                      <div>
                        <dt>位置</dt>
                        <dd>{{ servicePrimaryDetail(row) }}</dd>
                      </div>
                      <div>
                        <dt>版本</dt>
                        <dd>{{ row.details?.version || '-' }}</dd>
                      </div>
                      <div v-if="serviceReason(row)" class="service-reason">
                        <dt>原因</dt>
                        <dd>{{ serviceReason(row) }}</dd>
                      </div>
                    </dl>
                    <details>
                      <summary>查看原始检查结果</summary>
                      <pre class="details-json">{{ formatDetails(row.details) }}</pre>
                    </details>
                  </article>
                </div>
              </section>
            </div>
          </el-tab-pane>

          <el-tab-pane label="算法清单" name="algorithms">
            <div class="algo-filter-bar">
              <el-select v-model="algoFilters.type" placeholder="算法类型" clearable style="width:130px">
                <el-option v-for="item in algoTypeOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
              <el-select v-model="algoFilters.material_scope" placeholder="材料体系" clearable style="width:130px">
                <el-option label="氟基" value="fluoropolymer" />
                <el-option label="碳基" value="carbon_polymer" />
                <el-option label="硅基" value="silicon_polymer" />
                <el-option label="通用" value="universal" />
              </el-select>
              <el-input v-model="algoFilters.keyword" placeholder="搜索算法" clearable style="width:200px" />
              <el-button text @click="algoFilters.type = ''; algoFilters.material_scope = ''; algoFilters.keyword = ''">重置</el-button>
              <el-button :icon="Refresh" :loading="algoLoading" @click="loadAlgos">刷新</el-button>
            </div>
            <el-table v-if="filteredAlgos.length" :data="filteredAlgos" v-loading="algoLoading" stripe style="margin-top:10px">
              <el-table-column prop="name" label="算法名称" min-width="180" />
              <el-table-column label="类型" width="100">
                <template #default="{ row }"><el-tag size="small" :type="algoTypeTag(row.type)">{{ algoTypeLabel(row.type) }}</el-tag></template>
              </el-table-column>
              <el-table-column label="材料范围" min-width="160">
                <template #default="{ row }">{{ (row.material_scope || []).join(', ') }}</template>
              </el-table-column>
              <el-table-column label="触发方式" min-width="140">
                <template #default="{ row }">{{ (row.trigger_modes || []).join(', ') }}</template>
              </el-table-column>
              <el-table-column label="状态" width="100">
                <template #default="{ row }"><el-tag size="small" :type="algoStatusTag(row.status)">{{ algoStatusLabel(row.status) }}</el-tag></template>
              </el-table-column>
              <el-table-column label="操作" width="100" fixed="right">
                <template #default="{ row }">
                  <el-button text type="primary" size="small" :icon="ViewIcon" @click="showAlgoDetail(row)">详情</el-button>
                </template>
              </el-table-column>
            </el-table>
            <div v-else-if="!algoLoading" class="empty-inline" style="min-height:100px;justify-content:center">
              暂无算法数据
            </div>
          </el-tab-pane>
          <el-tab-pane label="配置" name="configs">
            <el-alert v-if="configError" :title="configError" type="warning" :closable="false" class="config-alert" />
            <el-table v-else :data="configs" v-loading="loadingConfigs" stripe>
              <el-table-column prop="service_key" label="Service" min-width="150" />
              <el-table-column prop="display_name" label="名称" min-width="180" />
              <el-table-column prop="service_type" label="类型" width="130" />
              <el-table-column label="启用" width="96">
                <template #default="{ row }">
                  <el-switch
                    :model-value="row.enabled"
                    :loading="actionLoading === `${row.service_key}:toggle`"
                    @change="(value) => toggleEnabled(row, value)"
                  />
                </template>
              </el-table-column>
              <el-table-column label="状态" width="130">
                <template #default="{ row }">
                  <el-tag size="small" :type="statusTag(row.last_status)">{{ row.last_status }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="配置摘要" min-width="320">
                <template #default="{ row }">
                  <pre class="details-json">{{ formatConfigSummary(row) }}</pre>
                </template>
              </el-table-column>
              <el-table-column label="最后检查" min-width="180">
                <template #default="{ row }">
                  <span>{{ formatDate(row.last_checked_at) }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="last_error_summary" label="错误" min-width="220" show-overflow-tooltip />
              <el-table-column label="操作" width="150" fixed="right">
                <template #default="{ row }">
                  <el-button text type="primary" size="small" :icon="Edit" @click="openEdit(row)">编辑</el-button>
                  <el-button
                    text
                    type="primary"
                    size="small"
                    :icon="Check"
                    :loading="actionLoading === `${row.service_key}:check`"
                    @click="handleCheck(row)"
                  >
                    检查
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </div>
    </section>

    <el-dialog v-model="editVisible" :title="currentConfig?.display_name || editingServiceKey" width="680px">
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="名称">
            <el-input v-model="form.display_name" />
          </el-form-item>
          <el-form-item label="类型">
            <el-select v-model="form.service_type">
              <el-option v-for="item in serviceTypeOptions" :key="item" :label="item" :value="item" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="Endpoint">
          <el-input v-model="form.endpoint" placeholder="https://service.example/api" />
        </el-form-item>
        <el-form-item label="Config summary">
          <el-input v-model="form.config_summary" type="textarea" :rows="6" spellcheck="false" />
        </el-form-item>
        <el-form-item label="Secret refs">
          <el-input v-model="form.secret_refs" type="textarea" :rows="4" spellcheck="false" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveConfig">保存</el-button>
      </template>
    </el-dialog>

    <!-- 算法详情 drawer -->
    <el-drawer v-model="algoDetailVisible" :title="algoDetail?.name || '算法详情'" size="520px">
      <template v-if="algoDetail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="ID">{{ algoDetail.algorithm_id }}</el-descriptions-item>
          <el-descriptions-item label="类型"><el-tag size="small" :type="algoTypeTag(algoDetail.type)">{{ algoTypeLabel(algoDetail.type) }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="状态"><el-tag size="small" :type="algoStatusTag(algoDetail.status)">{{ algoStatusLabel(algoDetail.status) }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="版本">{{ algoDetail.version }}</el-descriptions-item>
          <el-descriptions-item label="调用方式">{{ algoDetail.call_method }}</el-descriptions-item>
          <el-descriptions-item label="运行依赖">{{ algoDetail.runtime_dependency || '无' }}</el-descriptions-item>
          <el-descriptions-item label="触发方式">{{ (algoDetail.trigger_modes || []).join(', ') }}</el-descriptions-item>
          <el-descriptions-item label="材料范围">{{ (algoDetail.material_scope || []).join(', ') }}</el-descriptions-item>
        </el-descriptions>
        <h4 style="margin:16px 0 8px">输入 Schema</h4>
        <pre class="details-json" style="max-height:200px">{{ JSON.stringify(algoDetail.input_schema, null, 2) }}</pre>
        <h4 style="margin:16px 0 8px">输出 Schema</h4>
        <pre class="details-json" style="max-height:200px">{{ JSON.stringify(algoDetail.output_schema, null, 2) }}</pre>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.tools-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.algo-filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.tools-header {
  display: flex;
  align-items: center;
  gap: 16px;
}

.tools-header > div {
  flex: 1;
}

.panel-subtitle {
  margin: 6px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.config-alert {
  margin-bottom: 12px;
}

.service-groups {
  min-height: 180px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.service-group h4 {
  margin: 0 0 10px;
  color: var(--app-ink);
  font-size: 14px;
}

.service-card-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.service-card {
  min-height: 190px;
  padding: 14px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #ffffff;
}

.service-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.service-card-header strong {
  display: block;
  color: var(--app-ink);
  font-size: 15px;
}

.service-card-header span {
  display: block;
  margin-top: 4px;
  color: var(--app-ink-muted);
  font-size: 12px;
  line-height: 1.5;
}

.service-facts {
  margin: 14px 0 10px;
  display: grid;
  gap: 8px;
}

.service-facts div {
  min-width: 0;
}

.service-facts dt {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.service-facts dd {
  margin: 2px 0 0;
  color: var(--app-ink-body);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.service-reason dd {
  color: #b45309;
}

summary {
  cursor: pointer;
  color: var(--app-primary-active);
  font-size: 12px;
}

.details-json {
  margin: 0;
  max-height: 120px;
  overflow: auto;
  color: var(--app-ink-body);
  font-family: var(--app-mono-font);
  font-size: 12px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}

.form-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 180px;
  gap: 12px;
}

@media (max-width: 720px) {
  .tools-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }

  .service-card-grid {
    grid-template-columns: 1fr;
  }
}

@media (min-width: 721px) and (max-width: 1180px) {
  .service-card-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
