<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { DataAnalysis, MagicStick, SetUp, Star } from '@element-plus/icons-vue'

import AlgorithmRegistryPanel from './research-engine/AlgorithmRegistryPanel.vue'
import AlgorithmRunPanel from './research-engine/AlgorithmRunPanel.vue'
import AlgorithmRunDetail from './research-engine/AlgorithmRunDetail.vue'
import ProblemSpecPanel from './research-engine/ProblemSpecPanel.vue'
import ResearchRunPanel from './research-engine/ResearchRunPanel.vue'

const route = useRoute()
const router = useRouter()

const activeTab = ref('problemspec')
const selectedAlgorithm = ref(null)
const selectedRunId = ref('')
const currentProblemSpecId = ref('')
const currentCampaignId = ref('')

// 从 URL query 中恢复状态
if (route.query.run_id) {
  selectedRunId.value = String(route.query.run_id)
  activeTab.value = 'algorithm-runs'
}
if (route.query.research_run_id) {
  activeTab.value = 'research-run'
}
if (route.query.problem_spec_id) {
  activeTab.value = 'problemspec'
}

function handleSpecSelected(spec) {
  currentProblemSpecId.value = spec?.problem_spec_id || ''
  currentCampaignId.value = spec?.campaign_id || ''
}

function handleAlgorithmSelected(algo) {
  selectedAlgorithm.value = algo
  activeTab.value = 'algorithm-run'
}

function handleRunCompleted(run) {
  selectedRunId.value = run?.run_id || ''
}

function handleResearchRunUpdated(run) {
  // 同步更新状态
}
</script>

<template>
  <div class="research-engine-view">
    <section class="panel overview-panel">
      <div class="overview-content">
        <div>
          <h3 class="panel-title">ResearchEngine 研发引擎</h3>
          <p class="panel-subtitle">定义材料研发任务、浏览算法能力清单、人工调用算法工具、启动 AutoResearch 自动编排并审批阶段门禁。</p>
        </div>
        <div class="overview-flow">
          <span><el-icon><DataAnalysis /></el-icon> ProblemSpec</span>
          <span><el-icon><MagicStick /></el-icon> 算法运行</span>
          <span><el-icon><Star /></el-icon> 自动编排</span>
          <span><el-icon><SetUp /></el-icon> Gate 审批</span>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-body" style="padding:0">
        <el-tabs v-model="activeTab">
          <el-tab-pane label="研发任务定义" name="problemspec">
            <div style="padding:14px">
              <ProblemSpecPanel @spec-selected="handleSpecSelected" />
            </div>
          </el-tab-pane>

          <el-tab-pane label="算法能力清单" name="algorithms">
            <div style="padding:14px">
              <AlgorithmRegistryPanel @run-created="handleAlgorithmSelected" />
            </div>
          </el-tab-pane>

          <el-tab-pane label="人工算法运行" name="algorithm-run">
            <div style="padding:14px">
              <div class="two-col">
                <div class="col-left">
                  <AlgorithmRunPanel
                    :selected-algorithm="selectedAlgorithm"
                    :problem-spec-id="currentProblemSpecId"
                    :campaign-id="currentCampaignId"
                    @run-completed="handleRunCompleted"
                  />
                </div>
                <div class="col-right">
                  <AlgorithmRunDetail v-if="selectedRunId" :run-id="selectedRunId" />
                  <div v-else class="empty-hint">运行算法后将在此处显示详情</div>
                </div>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="AutoResearch 编排" name="research-run">
            <div style="padding:14px">
              <ResearchRunPanel @research-run-updated="handleResearchRunUpdated" />
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
    </section>
  </div>
</template>

<style scoped>
.research-engine-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.overview-panel {
  padding: 0;
}

.overview-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px;
}

.panel-subtitle {
  margin: 6px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.overview-flow {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.overview-flow span {
  min-height: 32px;
  padding: 6px 10px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
  color: var(--app-ink-body);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
}

.overview-flow .el-icon {
  color: var(--app-primary-active);
}

.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.empty-hint {
  color: var(--app-ink-muted);
  font-size: 14px;
  text-align: center;
  padding: 32px 0;
}

@media (max-width: 960px) {
  .two-col {
    grid-template-columns: 1fr;
  }

  .overview-content {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
