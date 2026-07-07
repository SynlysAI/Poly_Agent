<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Search, View as ViewIcon } from '@element-plus/icons-vue'

import {
  getAlgorithm,
  getApiErrorMessage,
  listAlgorithms,
} from '../../api/polyAgentApi'

const emit = defineEmits(['run-created', 'workflow-confirmed'])

const loading = ref(false)
const algorithms = ref([])
const detailVisible = ref(false)
const detail = ref(null)
const showDemoAlgorithms = ref(false)
// 多选模式：已选算法列表 [{algorithm_id, name, step_id}]
const selectedAlgorithms = ref([])

const filters = reactive({
  algorithm_family: '',
  type: '',
  material_scope: '',
  trigger_mode: '',
  keyword: '',
})

const familyOptions = [
  { label: '全部算法族', value: '' },
  { label: '计算智能', value: 'computation' },
  { label: '湿实验优化', value: 'wetlab_optimization' },
  { label: '垂类预测模型', value: 'vertical_prediction' },
  { label: '文献知识', value: 'knowledge' },
  { label: '结构表示', value: 'structure' },
]

const typeOptions = [
  { label: '全部类型', value: '' },
  { label: '检索器', value: 'retriever' },
  { label: '预测器', value: 'predictor' },
  { label: '模拟器', value: 'simulator' },
  { label: '优化器', value: 'optimizer' },
]

const materialOptions = [
  { label: '全部材料', value: '' },
  { label: '氟基', value: 'fluoropolymer' },
  { label: '碳基', value: 'carbon_polymer' },
  { label: '硅基', value: 'silicon_polymer' },
  { label: '氟碳共聚', value: 'fluoro_carbon_copolymer' },
  { label: '通用', value: 'universal' },
]

const triggerOptions = [
  { label: '全部触发', value: '' },
  { label: '人工 Workflow', value: 'human_workflow' },
  { label: 'AutoResearch', value: 'autoresearch' },
  { label: '系统', value: 'system' },
]

const filteredAlgorithms = computed(() => {
  const kw = filters.keyword.trim().toLowerCase()
  return algorithms.value.filter((item) => {
    if (!showDemoAlgorithms.value && isDemoAlgorithm(item)) return false
    const matchesType = !filters.type || item.type === filters.type
    const matchesFamily = !filters.algorithm_family || item.algorithm_family === filters.algorithm_family
    const matchesMaterial = !filters.material_scope || (item.material_scope || []).includes(filters.material_scope)
    const matchesTrigger = !filters.trigger_mode || (item.trigger_modes || []).includes(filters.trigger_mode)
    const haystack = `${item.name} ${item.algorithm_id} ${item.algorithm_family || ''} ${item.description || ''}`.toLowerCase()
    const matchesKeyword = !kw || haystack.includes(kw)
    return matchesFamily && matchesType && matchesMaterial && matchesTrigger && matchesKeyword
  })
})

function isDemoAlgorithm(algo) {
  return Boolean(algo?.input_schema?.ui_hints?._algorithm?.hidden_by_default)
}

function familyLabel(family) {
  const map = {
    computation: '计算智能',
    wetlab_optimization: '湿实验优化',
    vertical_prediction: '垂类预测模型',
    knowledge: '文献知识',
    structure: '结构表示',
  }
  return map[family] || family || '未分类'
}

function familyTag(family) {
  const map = {
    computation: 'warning',
    wetlab_optimization: 'danger',
    vertical_prediction: 'success',
    knowledge: 'info',
    structure: 'primary',
  }
  return map[family] || 'info'
}

function typeTag(type) {
  const map = { retriever: 'info', predictor: 'success', simulator: 'warning', optimizer: 'danger' }
  return map[type] || 'info'
}

function typeLabel(type) {
  const map = { retriever: '检索器', predictor: '预测器', simulator: '模拟器', optimizer: '优化器' }
  return map[type] || type
}

function statusTag(status) {
  const map = { active: 'success', pending_encapsulation: 'warning', in_development: 'info', frozen: 'info', decommissioned: 'danger' }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = { active: '已接入', pending_encapsulation: '待封装', in_development: '开发中', frozen: '冻结', decommissioned: '下线' }
  return map[status] || status
}

function materialScopeLabel(scopes) {
  if (!scopes || !scopes.length) return '-'
  const map = {
    fluoropolymer: '氟基', carbon_polymer: '碳基', silicon_polymer: '硅基',
    fluoro_carbon_copolymer: '氟碳共聚', universal: '通用',
  }
  return scopes.map(s => map[s] || s).join(', ')
}

async function loadData() {
  loading.value = true
  try {
    const data = await listAlgorithms({ page: 1, page_size: 100 })
    algorithms.value = data.items || []
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function showDetail(algo) {
  try {
    detail.value = await getAlgorithm(algo.algorithm_id)
    detailVisible.value = true
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  }
}

function isSelected(algorithmId) {
  return selectedAlgorithms.value.some(s => s.algorithm_id === algorithmId)
}

function toggleAlgorithm(algo) {
  const idx = selectedAlgorithms.value.findIndex(s => s.algorithm_id === algo.algorithm_id)
  if (idx >= 0) {
    selectedAlgorithms.value.splice(idx, 1)
  } else {
    selectedAlgorithms.value.push({
      algorithm_id: algo.algorithm_id,
      name: algo.name,
      step_id: `step_${selectedAlgorithms.value.length + 1}`,
    })
  }
}

function removeAlgorithm(algorithmId) {
  const idx = selectedAlgorithms.value.findIndex(s => s.algorithm_id === algorithmId)
  if (idx >= 0) {
    selectedAlgorithms.value.splice(idx, 1)
    // 重新编号 step_id
    selectedAlgorithms.value.forEach((s, i) => {
      s.step_id = `step_${i + 1}`
    })
  }
}

function confirmWorkflow() {
  if (selectedAlgorithms.value.length === 0) {
    ElMessage.warning('请先选择至少一个算法')
    return
  }
  emit('workflow-confirmed', [...selectedAlgorithms.value])
}

function handleRun(algo) {
  emit('run-created', algo)
}

function handleReset() {
  filters.algorithm_family = ''
  filters.type = ''
  filters.material_scope = ''
  filters.trigger_mode = ''
  filters.keyword = ''
}

onMounted(loadData)
</script>

<template>
  <div class="algorithm-registry-panel">
    <!-- 筛选栏 -->
    <div class="filter-bar">
      <el-select v-model="filters.algorithm_family" placeholder="算法族" clearable style="width:150px">
        <el-option v-for="item in familyOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-select v-model="filters.type" placeholder="算法类型" clearable style="width:130px">
        <el-option v-for="item in typeOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-select v-model="filters.material_scope" placeholder="材料体系" clearable style="width:130px">
        <el-option v-for="item in materialOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-select v-model="filters.trigger_mode" placeholder="触发方式" clearable style="width:130px">
        <el-option v-for="item in triggerOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-input v-model="filters.keyword" placeholder="搜索算法名称" clearable style="width:200px">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-switch
        v-model="showDemoAlgorithms"
        active-text="显示演示算法"
        inactive-text="隐藏演示算法"
      />
      <el-button text @click="handleReset">重置</el-button>
      <el-button :icon="Refresh" :loading="loading" @click="loadData">刷新</el-button>
    </div>

    <!-- 已选算法摘要条 -->
    <div v-if="selectedAlgorithms.length > 0" class="selected-algo-bar">
      <div class="selected-algo-info">
        <span class="selected-label">已选算法 ({{ selectedAlgorithms.length }})：</span>
        <el-tag
          v-for="(algo, idx) in selectedAlgorithms"
          :key="algo.algorithm_id"
          closable
          size="small"
          type="primary"
          effect="plain"
          style="margin:2px 4px"
          @close="removeAlgorithm(algo.algorithm_id)"
        >
          {{ idx + 1 }}. {{ algo.name }}
        </el-tag>
      </div>
      <el-button type="success" size="small" @click="confirmWorkflow">
        确认 Workflow
      </el-button>
    </div>

    <!-- 算法卡片网格 -->
    <div class="algo-grid" v-loading="loading">
      <article v-for="algo in filteredAlgorithms" :key="algo.algorithm_id" class="algo-card" :class="{ 'is-selected': isSelected(algo.algorithm_id) }">
        <div class="algo-card-top">
          <div>
            <strong>{{ algo.name }}</strong>
            <small>{{ algo.algorithm_id }}</small>
          </div>
          <el-tag size="small" :type="typeTag(algo.type)">{{ typeLabel(algo.type) }}</el-tag>
        </div>
        <p class="algo-desc">{{ algo.description || '暂无描述' }}</p>
        <div class="algo-tags">
          <el-tag size="small" effect="plain" :type="familyTag(algo.algorithm_family)">{{ familyLabel(algo.algorithm_family) }}</el-tag>
          <el-tag size="small" effect="plain">{{ materialScopeLabel(algo.material_scope) }}</el-tag>
          <el-tag size="small" effect="plain" :type="statusTag(algo.status)">{{ statusLabel(algo.status) }}</el-tag>
          <el-tag v-if="isDemoAlgorithm(algo)" size="small" effect="plain" type="info">演示</el-tag>
        </div>
        <div class="algo-actions">
          <el-button text type="primary" size="small" :icon="ViewIcon" @click="showDetail(algo)">查看详情</el-button>
          <el-button
            v-if="(algo.trigger_modes || []).includes('human_workflow') && algo.status === 'active'"
            :type="isSelected(algo.algorithm_id) ? 'warning' : 'primary'"
            size="small"
            @click="toggleAlgorithm(algo)"
          >
            {{ isSelected(algo.algorithm_id) ? '取消选择' : '选择' }}
          </el-button>
        </div>
      </article>
      <div v-if="!loading && !filteredAlgorithms.length" class="registry-empty">
        <strong>暂无匹配算法</strong>
        <span>调整算法族、类型、材料体系或触发方式后重试。若清单为空，点击刷新会从默认注册表恢复算法条目。</span>
        <el-button :icon="Refresh" @click="loadData">刷新算法清单</el-button>
      </div>
    </div>

    <!-- 算法详情 drawer -->
    <el-drawer v-model="detailVisible" :title="detail?.name || '算法详情'" size="520px">
      <template v-if="detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="ID">{{ detail.algorithm_id }}</el-descriptions-item>
          <el-descriptions-item label="类型">
            <el-tag size="small" :type="typeTag(detail.type)">{{ typeLabel(detail.type) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="算法族">
            <el-tag size="small" :type="familyTag(detail.algorithm_family)">{{ familyLabel(detail.algorithm_family) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag size="small" :type="statusTag(detail.status)">{{ statusLabel(detail.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="版本">{{ detail.version }}</el-descriptions-item>
          <el-descriptions-item label="调用方式">{{ detail.call_method }}</el-descriptions-item>
          <el-descriptions-item label="运行依赖">{{ detail.runtime_dependency || '无' }}</el-descriptions-item>
          <el-descriptions-item label="负责人">{{ detail.owner || '-' }}</el-descriptions-item>
          <el-descriptions-item label="材料范围">{{ materialScopeLabel(detail.material_scope) }}</el-descriptions-item>
          <el-descriptions-item label="触发方式" :span="2">{{ (detail.trigger_modes || []).join(', ') }}</el-descriptions-item>
        </el-descriptions>

        <h4 style="margin:16px 0 8px">输入 Schema</h4>
        <pre class="schema-json">{{ JSON.stringify(detail.input_schema, null, 2) }}</pre>

        <h4 style="margin:16px 0 8px">输出 Schema</h4>
        <pre class="schema-json">{{ JSON.stringify(detail.output_schema, null, 2) }}</pre>

        <h4 v-if="detail.validation_metric && Object.keys(detail.validation_metric).length" style="margin:16px 0 8px">验证指标</h4>
        <pre v-if="detail.validation_metric && Object.keys(detail.validation_metric).length" class="schema-json">{{ JSON.stringify(detail.validation_metric, null, 2) }}</pre>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.algorithm-registry-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.algo-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  min-height: 200px;
}

.registry-empty {
  grid-column: 1 / -1;
  min-height: 180px;
  border: 1px dashed var(--app-border);
  border-radius: var(--app-radius-md);
  background: #f8fbff;
  color: var(--app-ink-body);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 24px;
  text-align: center;
}

.registry-empty strong {
  color: var(--app-ink);
  font-size: 15px;
}

.registry-empty span {
  max-width: 520px;
  font-size: 13px;
  line-height: 1.6;
}

.algo-card {
  min-height: 180px;
  padding: 14px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #ffffff;
  display: flex;
  flex-direction: column;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.algo-card.is-selected {
  border-color: #3b82f6;
  box-shadow: 0 0 0 1px #3b82f6;
  background: #f8fbff;
}

.selected-algo-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  margin-bottom: 14px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: var(--app-radius-md);
  flex-wrap: wrap;
  gap: 8px;
}

.selected-algo-info {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}

.selected-label {
  font-size: 13px;
  color: var(--app-ink);
  font-weight: 500;
}

.algo-card-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.algo-card-top strong {
  display: block;
  color: var(--app-ink);
  font-size: 15px;
}

.algo-card-top small {
  display: block;
  margin-top: 2px;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.algo-desc {
  flex: 1;
  margin: 0 0 10px;
  color: var(--app-ink-body);
  font-size: 13px;
  line-height: 1.5;
}

.algo-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.algo-actions {
  display: flex;
  gap: 8px;
  border-top: 1px solid var(--app-border-soft);
  padding-top: 10px;
}

.schema-json {
  margin: 0;
  padding: 10px;
  background: #f8fbff;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  font-family: var(--app-mono-font);
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow: auto;
}

@media (max-width: 1024px) {
  .algo-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .algo-grid {
    grid-template-columns: 1fr;
  }
}
</style>
