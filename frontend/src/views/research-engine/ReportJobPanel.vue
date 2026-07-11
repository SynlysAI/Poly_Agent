<script setup>
import { computed, ref } from 'vue'
import { Document, Download, Refresh, RefreshRight } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { getApiErrorMessage, getReportPreview } from '../../api/polyAgentApi'

const props = defineProps({
  jobs: {
    type: Array,
    default: () => [],
  },
  loading: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['refresh', 'retry', 'download'])

const hasJobs = computed(() => props.jobs.length > 0)
const previewReportId = ref('')
const previewLoading = ref(false)
const previewContent = ref('')

function statusType(status) {
  const map = {
    queued: 'info',
    running: 'warning',
    converting: 'warning',
    completed: 'success',
    failed: 'danger',
    cancelled: 'info',
  }
  return map[status] || 'info'
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function downloadableArtifacts(job) {
  return (job.artifact_refs || []).filter(item => ['markdown', 'pdf', 'log'].includes(item.artifact_type))
}

async function togglePreview(job) {
  if (previewReportId.value === job.report_id) {
    previewReportId.value = ''
    previewContent.value = ''
    return
  }
  previewLoading.value = true
  try {
    const data = await getReportPreview(job.report_id)
    previewReportId.value = job.report_id
    previewContent.value = data.content || ''
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    previewLoading.value = false
  }
}
</script>

<template>
  <section class="report-job-panel">
    <div class="panel-header">
      <h5>最近报告</h5>
      <el-button size="small" :icon="Refresh" :loading="loading" @click="emit('refresh')">刷新</el-button>
    </div>

    <div v-loading="loading" class="report-job-body">
      <div v-if="!hasJobs" class="empty-report">暂无报告任务</div>
      <article v-for="job in jobs" v-else :key="job.report_id" class="report-job-item">
        <div class="job-main">
          <div class="job-title-row">
            <strong>{{ job.template_id }}</strong>
            <el-tag size="small" :type="statusType(job.status)">{{ job.status }}</el-tag>
          </div>
          <div class="job-meta">
            <span>{{ job.report_id }}</span>
            <span>{{ job.stage }} · {{ job.progress }}%</span>
            <span>{{ job.provider }} · {{ job.model || '未配置模型' }}</span>
            <span>{{ formatDate(job.created_at) }}</span>
          </div>
          <div v-if="job.error?.message" class="job-error">{{ job.error.message }}</div>
        </div>
        <div class="job-actions">
          <el-button
            v-if="job.status === 'completed' && (job.artifact_refs || []).some(item => item.artifact_type === 'markdown')"
            size="small"
            :icon="Document"
            :loading="previewLoading && previewReportId !== job.report_id"
            @click="togglePreview(job)"
          >
            {{ previewReportId === job.report_id ? '收起' : '预览' }}
          </el-button>
          <el-dropdown v-if="downloadableArtifacts(job).length" trigger="click">
            <el-button size="small" :icon="Download">下载</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="artifact in downloadableArtifacts(job)"
                  :key="artifact.artifact_id"
                  @click="emit('download', job, artifact)"
                >
                  {{ artifact.artifact_type }} · {{ artifact.filename }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button
            v-if="job.status === 'failed'"
            size="small"
            :icon="RefreshRight"
            @click="emit('retry', job)"
          >
            重试
          </el-button>
        </div>
        <pre v-if="previewReportId === job.report_id" class="report-preview">{{ previewContent }}</pre>
      </article>
    </div>
  </section>
</template>

<style scoped>
.report-job-panel {
  margin-bottom: 16px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #fff;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--app-border-soft);
}

.panel-header h5 {
  margin: 0;
  font-size: 14px;
  color: var(--app-ink);
}

.report-job-body {
  min-height: 72px;
  padding: 10px;
}

.empty-report {
  padding: 20px 0;
  color: var(--app-ink-muted);
  font-size: 13px;
  text-align: center;
}

.report-job-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 10px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  flex-wrap: wrap;
}

.report-job-item + .report-job-item {
  margin-top: 8px;
}

.job-main {
  min-width: 0;
}

.job-title-row,
.job-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.job-title-row strong {
  font-size: 13px;
  color: var(--app-ink);
}

.job-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 4px;
  font-size: 12px;
  color: var(--app-ink-muted);
}

.job-error {
  margin-top: 6px;
  color: #b91c1c;
  font-size: 12px;
  word-break: break-word;
}

.job-actions {
  flex-shrink: 0;
}

.report-preview {
  flex-basis: 100%;
  max-height: 420px;
  margin: 0;
  padding: 14px;
  overflow: auto;
  border-top: 1px solid var(--app-border-soft);
  background: #f8fafc;
  color: var(--app-ink);
  font: 13px/1.65 ui-monospace, SFMono-Regular, Menlo, monospace;
  white-space: pre-wrap;
}

@media (max-width: 720px) {
  .report-job-item {
    flex-direction: column;
  }
}
</style>
