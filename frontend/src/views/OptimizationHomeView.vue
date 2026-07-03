<script setup>
import { useRouter } from 'vue-router'
import { Connection, DataAnalysis, MagicStick, SetUp } from '@element-plus/icons-vue'

const router = useRouter()

const entries = [
  {
    key: 'campaigns',
    title: 'Campaign 闭环管理',
    category: '湿实验优化',
    description: '管理候选库、生成推荐、提交计算验证并回填 observation。',
    icon: MagicStick,
    actionText: '进入 Campaign',
    route: '/optimization/campaigns',
    metrics: ['候选库', 'Suggestion', 'Observation'],
  },
  {
    key: 'alchemist',
    title: 'Alchemist 实验设计',
    category: '贝叶斯优化',
    description: '定义变量、生成实验设计、训练 GP 模型并执行采集优化。',
    icon: SetUp,
    actionText: '进入 Alchemist',
    route: '/optimization/alchemist',
    metrics: ['变量定义', 'GP 建模', '采集优化'],
  },
]

function openEntry(entry) {
  router.push(entry.route)
}
</script>

<template>
  <div class="optimization-home">
    <section class="panel overview-panel">
      <div class="overview-content">
        <div>
          <h3 class="panel-title">湿实验优化</h3>
          <p class="panel-subtitle">从统一入口进入贝叶斯优化 campaign、实验设计和 Alchemist 主动学习链路。</p>
        </div>
        <div class="overview-flow" aria-label="湿实验优化链路">
          <span><el-icon><DataAnalysis /></el-icon> 候选</span>
          <span><el-icon><MagicStick /></el-icon> 推荐</span>
          <span><el-icon><Connection /></el-icon> 验证</span>
        </div>
      </div>
    </section>

    <section class="entry-grid" aria-label="湿实验优化入口">
      <article v-for="entry in entries" :key="entry.key" class="entry-card">
        <div class="entry-card-top">
          <div class="entry-icon">
            <el-icon><component :is="entry.icon" /></el-icon>
          </div>
          <span>{{ entry.category }}</span>
        </div>
        <h4>{{ entry.title }}</h4>
        <p>{{ entry.description }}</p>
        <div class="entry-tags">
          <el-tag v-for="item in entry.metrics" :key="item" size="small" effect="plain">{{ item }}</el-tag>
        </div>
        <el-button type="primary" @click="openEntry(entry)">{{ entry.actionText }}</el-button>
      </article>
    </section>
  </div>
</template>

<style scoped>
.optimization-home {
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

.entry-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.entry-card {
  min-height: 250px;
  padding: 18px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #ffffff;
  box-shadow: var(--app-card-shadow);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}

.entry-card-top {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
  color: var(--app-ink-muted);
  font-size: 12px;
  font-weight: 700;
}

.entry-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--app-radius-sm);
  background: var(--app-primary-light);
  color: var(--app-primary-active);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}

.entry-card h4 {
  margin: 0 0 8px;
  color: var(--app-ink);
  font-size: 18px;
}

.entry-card p {
  flex: 1;
  margin: 0;
  color: var(--app-ink-body);
  font-size: 13px;
  line-height: 1.7;
}

.entry-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin: 16px 0;
}

@media (max-width: 760px) {
  .overview-content {
    align-items: flex-start;
    flex-direction: column;
  }

  .entry-grid {
    grid-template-columns: 1fr;
  }
}
</style>
