<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { DataAnalysis, Refresh } from '@element-plus/icons-vue'

import { getApiErrorMessage, getLuiEvaluationSummary } from '../api/polyAgentApi'

const loading = ref(false)
const mode = ref('smoke')
const summary = ref(null)

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

/** 格式化比率为百分比文本。 */
function formatRate(value) {
  if (value === null || value === undefined) return '—'
  return `${(value * 100).toFixed(2)}%`
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

onMounted(loadSummary)
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
        </div>
      </div>

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
