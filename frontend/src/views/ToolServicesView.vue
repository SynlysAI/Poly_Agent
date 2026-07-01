<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import { getApiErrorMessage, getIntegrationStatus } from '../api/polyAgentApi'

const services = ref([])
const loading = ref(false)

function statusTag(status) {
  if (['up', 'available'].includes(status)) return 'success'
  if (status === 'degraded') return 'warning'
  if (['down', 'failed'].includes(status)) return 'danger'
  return 'info'
}

function formatDetails(details) {
  if (!details || Object.keys(details).length === 0) return '{}'
  return JSON.stringify(details, null, 2)
}

async function loadStatus() {
  loading.value = true
  try {
    const data = await getIntegrationStatus()
    services.value = data.items || []
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

onMounted(loadStatus)
</script>

<template>
  <div class="tools-view">
    <section class="panel">
      <div class="panel-header tools-header">
        <div>
          <h3 class="panel-title">工具服务</h3>
          <p class="panel-subtitle">计算 worker、artifact store、ChemOS reference 和后续集成边界状态。</p>
        </div>
        <el-button :icon="Refresh" :loading="loading" @click="loadStatus">刷新</el-button>
      </div>
    </section>

    <section class="panel">
      <div class="panel-body">
        <el-table :data="services" v-loading="loading" stripe>
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
      </div>
    </section>
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

.details-json {
  margin: 0;
  max-height: 120px;
  overflow: auto;
  color: var(--app-ink-body);
  font-family: var(--app-mono-font);
  font-size: 12px;
  white-space: pre-wrap;
}
</style>
