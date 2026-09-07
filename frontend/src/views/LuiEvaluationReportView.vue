<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DataAnalysis, Refresh, VideoPlay } from '@element-plus/icons-vue'

import {
  cancelLuiEvaluationRun,
  getApiErrorMessage,
  getLatestLuiEvaluationRun,
  getLlmModels,
  getLlmRouting,
  getLuiEvaluationSummary,
  runLuiEvaluation,
} from '../api/polyAgentApi'

const RUN_ACTIVE_STATUSES = new Set(['queued', 'capturing', 'evaluating'])
const RUN_STATUS_LABELS = {
  queued: '排队中',
  capturing: '录制中',
  evaluating: '评测中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

const loading = ref(false)
const mode = ref('smoke')
const summary = ref(null)
const runDialogVisible = ref(false)
const runSubmitting = ref(false)
const cancelling = ref(false)
const activeRun = ref(null)
const runForm = reactive({ mode: 'smoke', provider_id: '', model_id: '' })
const modelCatalog = ref({ providers: [], routing: {} })
const modelOptionsLoading = ref(false)
const logContainer = ref(null)
let runPollingTimer = null

const metricRows = computed(() => {
  const metrics = summary.value?.metrics || {}
  return Object.entries(metrics).map(([key, row]) => ({ key, ...row }))
})

const categoryRows = computed(() => {
  const rows = summary.value?.by_category || {}
  return Object.entries(rows).map(([name, row]) => ({ name, ...row }))
})

const modeRows = computed(() => {
  const rows = summary.value?.by_mode || {}
  return Object.entries(rows).map(([name, row]) => ({ name, ...row }))
})

const manualReviewRows = computed(() => {
  const metrics = summary.value?.manual_review?.metrics || {}
  return Object.entries(metrics).map(([key, row]) => ({ key, ...row }))
})

const providerOptions = computed(() => modelCatalog.value.providers || [])
const modelOptions = computed(() => {
  const provider = providerOptions.value.find(item => item.provider_id === runForm.provider_id)
  return provider?.models || []
})
const runRunning = computed(() => Boolean(activeRun.value && RUN_ACTIVE_STATUSES.has(activeRun.value.status)))
const runProgressPercent = computed(() => {
  const progress = activeRun.value?.progress
  if (!progress?.total) return activeRun.value ? 5 : 0
  return Math.min(100, Math.round(((progress.done || 0) / progress.total) * 100))
})
const runStageText = computed(() => {
  const run = activeRun.value
  if (!run) return ''
  if (run.status === 'capturing') {
    const total = run.progress?.total || 80
    return `录制中 ${run.progress?.done || 0}/${total}`
  }
  if (run.status === 'evaluating') return '评测中'
  return RUN_STATUS_LABELS[run.status] || run.status
})
const runModelText = computed(() => {
  const run = activeRun.value
  if (run?.mode !== 'full' || !run.provider_id || !run.model_id) return '—'
  return `${run.provider_id}/${run.model_id}`
})

/** 格式化比率为百分比文本。 */
function formatRate(value) {
  if (value === null || value === undefined) return '—'
  return `${(value * 100).toFixed(2)}%`
}

/** 展示任务状态标签颜色。 */
function runStatusType(status) {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'cancelled') return 'info'
  return 'primary'
}

/** 格式化任务时间。 */
function formatRunTime(value) {
  return (value || '').replace('T', ' ').slice(0, 19)
}

/** 打开运行配置对话框并恢复当前默认模型。 */
async function openRunDialog() {
  runDialogVisible.value = true
  runForm.mode = 'smoke'
  runForm.provider_id = ''
  runForm.model_id = ''
  await loadModelOptions()
}

/** 加载可选模型并取当前默认路由作为初始值。 */
async function loadModelOptions() {
  modelOptionsLoading.value = true
  try {
    const [catalog, routing] = await Promise.all([getLlmModels(), getLlmRouting()])
    modelCatalog.value = catalog || { providers: [], routing: {} }
    const defaultRoute = routing?.qa
    if (defaultRoute?.provider_id && defaultRoute?.model_id) {
      runForm.provider_id = defaultRoute.provider_id
      runForm.model_id = defaultRoute.model_id
    }
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error, '加载模型配置失败'))
  } finally {
    modelOptionsLoading.value = false
  }
}

/** 切换 provider 后修正模型默认值。 */
function handleProviderChange() {
  runForm.model_id = modelOptions.value[0]?.model_id || ''
}

/** 提交评测任务，full 模式额外要求二次确认。 */
async function submitRun() {
  if (runForm.mode === 'full') {
    try {
      await ElMessageBox.confirm(
        'full 模式将执行 80 条任务并调用真实模型链路，耗时可能约 1 小时、消耗真实模型额度；要求服务器已配置评测账号，且 MongoDB 与 assistant run worker 正在运行。',
        '确认运行 full 评测',
        { type: 'warning', confirmButtonText: '确认运行', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
  }
  runSubmitting.value = true
  try {
    const payload = { mode: runForm.mode }
    if (runForm.mode === 'full') {
      payload.provider_id = runForm.provider_id
      payload.model_id = runForm.model_id
    }
    activeRun.value = await runLuiEvaluation(payload)
    runDialogVisible.value = false
    startRunPolling()
    ElMessage.success('评测任务已启动')
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error, '启动评测失败'))
  } finally {
    runSubmitting.value = false
  }
}

/** 启动最新任务轮询，终态后自动刷新报告。 */
function startRunPolling() {
  stopRunPolling()
  runPollingTimer = setInterval(pollLatestRun, 5000)
}

/** 停止任务轮询。 */
function stopRunPolling() {
  if (!runPollingTimer) return
  clearInterval(runPollingTimer)
  runPollingTimer = null
}

/** 查询最新任务并处理终态刷新。 */
async function pollLatestRun() {
  try {
    const latest = await getLatestLuiEvaluationRun()
    if (!latest) return
    activeRun.value = latest
    if (!RUN_ACTIVE_STATUSES.has(latest.status)) {
      stopRunPolling()
      mode.value = latest.mode
      await loadSummary()
      if (latest.status === 'completed') ElMessage.success('评测完成，报告已刷新')
      if (latest.status === 'failed') ElMessage.error(latest.error || '评测失败')
      if (latest.status === 'cancelled') ElMessage.info('评测已取消')
    }
    await scrollLogToBottom()
  } catch (error) {
    console.warn('查询 LUI 评测任务失败', error)
  }
}

/** 页面加载时恢复未完成任务的进度。 */
async function restoreActiveRun() {
  try {
    const latest = await getLatestLuiEvaluationRun()
    activeRun.value = latest
    if (RUN_ACTIVE_STATUSES.has(latest?.status)) startRunPolling()
  } catch {
    activeRun.value = null
  }
}

/** 取消当前任务。 */
async function cancelRun() {
  const job = activeRun.value
  if (!job) return
  cancelling.value = true
  try {
    activeRun.value = await cancelLuiEvaluationRun(job.job_id)
    stopRunPolling()
    ElMessage.info('已发送取消请求')
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error, '取消评测失败'))
  } finally {
    cancelling.value = false
  }
}

/** 将日志滚动区定位到底部。 */
async function scrollLogToBottom() {
  await nextTick()
  if (logContainer.value) logContainer.value.scrollTop = logContainer.value.scrollHeight
}

/** 指标通过率标签颜色。 */
function metricTagType(row) {
  if (row.pass_rate === null || row.pass_rate === undefined) return 'info'
  if (row.pass_rate >= 0.9) return 'success'
  if (row.pass_rate >= 0.75) return 'primary'
  return 'danger'
}

/** 加载评测基线汇总。 */
async function loadSummary() {
  loading.value = true
  try {
    summary.value = await getLuiEvaluationSummary(mode.value)
  } catch (error) {
    summary.value = null
    ElMessage.error(getApiErrorMessage(error, '加载 LUI 评测基线失败'))
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await restoreActiveRun()
  await loadSummary()
})

onBeforeUnmount(stopRunPolling)
</script>

<template>
  <div class="lui-eval-page">
    <section class="panel">
      <div class="panel-header lui-eval-header">
        <div>
          <h3 class="panel-title">LUI Agent 评测报告</h3>
          <p class="panel-subtitle">
            离线 Golden Set 的任务级 M1–M8 结果质量基线；与「工具服务」中的
            LUI 调用质量（生产链路侧）互补，不重复统计。
          </p>
        </div>
        <div class="lui-eval-actions">
          <el-select v-model="mode" style="width: 130px" @change="loadSummary">
            <el-option label="smoke 快速集" value="smoke" />
            <el-option label="full 完整集" value="full" />
          </el-select>
          <el-button :icon="Refresh" :loading="loading" @click="loadSummary">刷新</el-button>
          <el-button
            type="primary"
            :icon="VideoPlay"
            :disabled="runRunning"
            @click="openRunDialog"
          >
            运行评测
          </el-button>
        </div>
      </div>

      <el-dialog v-model="runDialogVisible" title="运行 LUI Agent 评测" width="520px">
        <el-form label-width="88px" :loading="modelOptionsLoading">
          <el-form-item label="评测模式">
            <el-radio-group v-model="runForm.mode">
              <el-radio-button label="smoke">smoke</el-radio-button>
              <el-radio-button label="full">full</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-alert
            v-if="runForm.mode === 'smoke'"
            title="离线 fixture，不调用真实模型，秒级完成。"
            type="info"
            show-icon
            :closable="false"
          />
          <template v-else>
            <el-alert
              title="80 条任务走真实链路，耗时可能约 1 小时并消耗真实模型额度。"
              type="warning"
              show-icon
              :closable="false"
              class="run-dialog-alert"
            />
            <el-form-item label="Provider">
              <el-select v-model="runForm.provider_id" @change="handleProviderChange">
                <el-option
                  v-for="provider in providerOptions"
                  :key="provider.provider_id"
                  :value="provider.provider_id"
                  :label="provider.display_name || provider.provider_id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="Model">
              <el-select v-model="runForm.model_id">
                <el-option
                  v-for="model in modelOptions"
                  :key="model.model_id"
                  :value="model.model_id"
                  :label="model.display_name || model.model_id"
                />
              </el-select>
            </el-form-item>
          </template>
        </el-form>
        <template #footer>
          <el-button @click="runDialogVisible = false">取消</el-button>
          <el-button
            type="primary"
            :loading="runSubmitting"
            :disabled="runForm.mode === 'full' && (!runForm.provider_id || !runForm.model_id)"
            @click="submitRun"
          >
            启动
          </el-button>
        </template>
      </el-dialog>

      <el-card v-if="activeRun" class="run-card" shadow="never">
        <div class="run-card-header">
          <div class="run-card-title">
            <el-tag :type="runStatusType(activeRun.status)">{{ runStageText }}</el-tag>
            <strong>{{ activeRun.mode.toUpperCase() }}</strong>
            <span>模型：{{ runModelText }}</span>
            <span>批次：{{ activeRun.evaluation_id }}</span>
          </div>
          <el-button
            v-if="runRunning"
            size="small"
            type="danger"
            plain
            :loading="cancelling"
            @click="cancelRun"
          >
            取消
          </el-button>
        </div>
        <el-progress :percentage="runProgressPercent" :stroke-width="10" />
        <div class="run-card-meta">
          <span>任务：{{ activeRun.progress?.current_task || '—' }}</span>
          <span>创建：{{ formatRunTime(activeRun.created_at) }}</span>
          <span v-if="activeRun.error" class="run-error">{{ activeRun.error }}</span>
        </div>
        <div ref="logContainer" class="run-log">
          <div v-for="(line, index) in activeRun.log_tail" :key="index" class="run-log-line">
            {{ line }}
          </div>
        </div>
      </el-card>

      <div v-loading="loading" class="panel-body">
        <el-alert
          v-if="summary && !summary.available"
          :title="`暂无 ${mode} 基线：请先运行 scripts/run_lui_eval.py 并保存基线到 baselines/ 目录。`"
          :description="`可用模式：${(summary.available_modes || []).join('、') || '无'}`"
          type="info"
          show-icon
          :closable="false"
          class="lui-eval-alert"
        />

        <template v-if="summary?.available">
          <div class="lui-eval-meta">
            <span>评测批次：<code>{{ summary.evaluation_id }}</code></span>
            <span>数据集版本：<code>{{ summary.dataset_version }}</code></span>
            <span>生成时间：{{ (summary.generated_at || '').replace('T', ' ').slice(0, 19) }}</span>
            <span>基线文件：<code>{{ summary.source_file }}</code></span>
          </div>

          <div class="lui-eval-cards">
            <article>
              <span>评测任务</span>
              <strong>{{ summary.summary?.evaluated_tasks ?? '—' }}</strong>
              <small>成功 {{ summary.summary?.successful_tasks ?? '—' }} 条</small>
            </article>
            <article>
              <span>任务成功率</span>
              <strong>{{ formatRate(summary.summary?.task_success_rate) }}</strong>
              <small>M1 主指标</small>
            </article>
            <article>
              <span>跳过任务</span>
              <strong>{{ (summary.summary?.skipped_tasks || []).length }}</strong>
              <small>无 fixture 或未录制</small>
            </article>
            <article>
              <span>人工抽检</span>
              <strong>{{ manualReviewRows.length ? '已归档' : '未归档' }}</strong>
              <small>M4/M5 判定校准</small>
            </article>
          </div>

          <h4 class="lui-eval-section-title">八项指标</h4>
          <el-table :data="metricRows" size="small" border>
            <el-table-column label="指标" min-width="190">
              <template #default="{ row }">{{ row.label }}（{{ row.key }}）</template>
            </el-table-column>
            <el-table-column prop="applicable" label="适用" width="70" align="right" />
            <el-table-column prop="passed" label="通过" width="70" align="right" />
            <el-table-column label="通过率" min-width="100" align="right">
              <template #default="{ row }">
                <el-tag size="small" :type="metricTagType(row)">{{ formatRate(row.pass_rate) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="not_evaluable" label="未判定" width="80" align="right" />
            <el-table-column label="均分" width="90" align="right">
              <template #default="{ row }">{{ formatRate(row.score_mean) }}</template>
            </el-table-column>
          </el-table>
          <p class="lui-eval-note">通过率分母只含明确 True/False 判定；未设置阈值（如 fixture 模式的 M6/M7 预算）单列为未判定。</p>

          <div class="lui-eval-grid">
            <div>
              <h4 class="lui-eval-section-title">分桶成功率</h4>
              <el-table :data="categoryRows" size="small" border>
                <el-table-column prop="name" label="分桶" min-width="150" />
                <el-table-column prop="tasks" label="任务数" width="80" align="right" />
                <el-table-column prop="success" label="成功" width="70" align="right" />
                <el-table-column label="成功率" min-width="90" align="right">
                  <template #default="{ row }">{{ formatRate(row.success_rate) }}</template>
                </el-table-column>
              </el-table>
            </div>
            <div>
              <h4 class="lui-eval-section-title">模式成功率</h4>
              <el-table :data="modeRows" size="small" border>
                <el-table-column prop="name" label="模式" min-width="100" />
                <el-table-column prop="tasks" label="任务数" width="80" align="right" />
                <el-table-column prop="success" label="成功" width="70" align="right" />
                <el-table-column label="成功率" min-width="90" align="right">
                  <template #default="{ row }">{{ formatRate(row.success_rate) }}</template>
                </el-table-column>
              </el-table>
            </div>
          </div>

          <template v-if="manualReviewRows.length">
            <h4 class="lui-eval-section-title">人工抽检结论</h4>
            <el-table :data="manualReviewRows" size="small" border>
              <el-table-column prop="key" label="指标" width="80" />
              <el-table-column prop="sampled" label="抽样" width="80" align="right" />
              <el-table-column prop="reviewed" label="已复核" width="90" align="right" />
              <el-table-column prop="disagreements" label="不一致" width="90" align="right" />
              <el-table-column label="不一致率" min-width="100" align="right">
                <template #default="{ row }">{{ formatRate(row.disagreement_rate) }}</template>
              </el-table-column>
              <el-table-column label="5% 门限" width="100" align="center">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.within_limit ? 'success' : 'danger'">
                    {{ row.within_limit ? '通过' : '超限' }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
            <p class="lui-eval-note">不一致原因归类：任务歧义 / 判定器误判 / 判定器漏判。</p>
          </template>
        </template>
      </div>
    </section>
  </div>
</template>

<style scoped>
.lui-eval-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.lui-eval-header {
  align-items: flex-start;
  gap: 12px;
}

.panel-subtitle {
  margin: 6px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.lui-eval-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.run-card {
  margin-bottom: 16px;
  border: 1px solid #d9e8ff;
  border-radius: var(--app-radius-md);
}

.run-card :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.run-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.run-card-title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  color: var(--app-ink);
  font-size: 14px;
}

.run-card-title span {
  color: var(--app-ink-muted);
  font-size: 13px;
}

.run-card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.run-error {
  color: var(--el-color-danger);
}

.run-log {
  height: 180px;
  overflow: auto;
  padding: 10px;
  background: #0f172a;
  border-radius: 6px;
  color: #e2e8f0;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  line-height: 1.6;
}

.run-log-line {
  white-space: pre-wrap;
  word-break: break-word;
}

.run-dialog-alert {
  margin: 0 0 16px;
}

.lui-eval-alert {
  margin-bottom: 12px;
}

.lui-eval-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  color: var(--app-ink-muted);
  font-size: 13px;
  margin-bottom: 14px;
}

.lui-eval-meta code {
  color: var(--app-sidebar-from);
}

.lui-eval-cards {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}

.lui-eval-cards article {
  background: linear-gradient(180deg, #f8fbff 0%, #f2f7ff 100%);
  border: 1px solid #dde9fb;
  border-radius: var(--app-radius-md);
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.lui-eval-cards span {
  color: var(--app-ink-muted);
  font-size: 13px;
}

.lui-eval-cards strong {
  color: var(--app-sidebar-from);
  font-size: 24px;
  font-weight: 700;
}

.lui-eval-cards small {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.lui-eval-section-title {
  margin: 0 0 10px;
  color: var(--app-ink);
  font-size: 14px;
}

.lui-eval-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin-top: 18px;
}

.lui-eval-note {
  margin: 8px 0 0;
  color: var(--app-ink-muted);
  font-size: 12px;
}

@media (max-width: 960px) {
  .lui-eval-cards,
  .lui-eval-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .lui-eval-header {
    flex-direction: column;
  }
}
</style>
