<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, Edit, Refresh } from '@element-plus/icons-vue'

import {
  checkIntegrationConfig,
  getApiErrorMessage,
  getIntegrationStatus,
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

onMounted(loadAll)
</script>

<template>
  <div class="tools-view">
    <section class="panel">
      <div class="panel-header tools-header">
        <div>
          <h3 class="panel-title">工具服务</h3>
          <p class="panel-subtitle">计算 worker、artifact store、ChemOS reference 和外部服务集成状态。</p>
        </div>
        <el-button :icon="Refresh" :loading="loadingStatus || loadingConfigs" @click="loadAll">刷新</el-button>
      </div>
    </section>

    <section class="panel">
      <div class="panel-body">
        <el-tabs v-model="activeTab">
          <el-tab-pane label="状态" name="status">
            <el-table :data="services" v-loading="loadingStatus" stripe>
              <el-table-column prop="service" label="Service" min-width="180" />
              <el-table-column prop="status" label="状态" width="140">
                <template #default="{ row }">
                  <el-tag size="small" :type="statusTag(row.status)">{{ row.status }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="checked_at" label="检查时间" min-width="190" />
              <el-table-column label="Details" min-width="420">
                <template #default="{ row }">
                  <pre class="details-json">{{ formatDetails(row.details) }}</pre>
                </template>
              </el-table-column>
            </el-table>
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
  </div>
</template>

<style scoped>
.tools-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.tools-header {
  display: flex;
  align-items: center;
  gap: 16px;
}

.panel-subtitle {
  margin: 6px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.config-alert {
  margin-bottom: 12px;
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
}
</style>
