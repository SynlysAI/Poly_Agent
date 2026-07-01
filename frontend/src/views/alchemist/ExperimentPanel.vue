<script setup>
import { ref, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { generateInitialDesign, addExperiments, getVariables } from '../../api/alchemistApi'

const props = defineProps({
  sessionId: { type: String, required: true }
})

const designMethods = [
  { label: '拉丁超立方采样 (LHS)', value: 'lhs' },
  { label: 'Sobol 序列', value: 'sobol' },
  { label: '全因子设计', value: 'full_factorial' },
  { label: '中心复合设计 (CCD)', value: 'ccd' },
  { label: 'Box-Behnken 设计', value: 'box_behnken' },
  { label: 'Plackett-Burman 设计', value: 'plackett_burman' },
  { label: 'D-最优设计', value: 'd_optimal' },
]

const selectedMethod = ref('lhs')
const nExperiments = ref(10)
const loading = ref(false)
const designMatrix = ref([])
const variables = ref([])

async function loadVariables() {
  try {
    const data = await getVariables(props.sessionId)
    variables.value = data.variables || []
  } catch (e) { /* 静默失败 */ }
}

async function handleGenerateDesign() {
  if (variables.value.length === 0) {
    ElMessage.warning('请先在"变量定义"中添加变量')
    return
  }
  try {
    loading.value = true
    const config = { method: selectedMethod.value, n_points: nExperiments.value }
    const data = await generateInitialDesign(props.sessionId, config)
    designMatrix.value = data.points || data.design_matrix || data.experiments || []
    ElMessage.success(`生成 ${designMatrix.value.length} 组实验方案`)
  } catch (e) {
    ElMessage.error(`生成实验设计失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

async function handleAddExperiments() {
  if (designMatrix.value.length === 0) {
    ElMessage.warning('请先生成实验设计方案')
    return
  }
  try {
    loading.value = true
    await addExperiments(props.sessionId, { experiments: designMatrix.value.map(row => ({ inputs: row })) })
    ElMessage.success('实验数据已添加')
  } catch (e) {
    ElMessage.error(`添加实验数据失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

function getColumnNames() {
  if (designMatrix.value.length === 0) return []
  const row = designMatrix.value[0]
  if (typeof row === 'object' && !Array.isArray(row)) {
    return Object.keys(row)
  }
  return variables.value.map(v => v.name)
}

watch(() => props.sessionId, () => { loadVariables() })
onMounted(() => { loadVariables() })
</script>

<template>
  <div class="panel">
    <div class="panel-header"><h3 class="panel-title">实验设计</h3></div>
    <div class="panel-body">
      <div style="display:flex;gap:16px;align-items:flex-end;margin-bottom:16px;flex-wrap:wrap">
        <div>
          <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">设计方法</div>
          <el-select v-model="selectedMethod" style="width:220px">
            <el-option v-for="m in designMethods" :key="m.value" :label="m.label" :value="m.value" />
          </el-select>
        </div>
        <div>
          <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">实验数量</div>
          <el-input-number v-model="nExperiments" :min="2" :max="1000" style="width:120px" />
        </div>
        <div>
          <el-button type="primary" @click="handleGenerateDesign" :loading="loading">生成实验设计</el-button>
          <el-button @click="handleAddExperiments" :disabled="designMatrix.length === 0" :loading="loading">添加到实验数据</el-button>
        </div>
      </div>

      <el-table :data="designMatrix" border stripe empty-text="请先生成实验设计方案" max-height="400">
        <el-table-column type="index" label="序号" width="60" />
        <el-table-column v-for="col in getColumnNames()" :key="col" :prop="col" :label="col" min-width="100" />
      </el-table>
    </div>
  </div>
</template>
