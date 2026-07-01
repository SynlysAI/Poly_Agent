<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { suggestNext } from '../../api/alchemistApi'

const props = defineProps({
  sessionId: { type: String, required: true }
})

const acquisitionOptions = [
  { label: 'q-期望改进 (qEI)', value: 'qEI' },
  { label: 'q-概率改进 (qPI)', value: 'qPI' },
  { label: 'q-上置信界 (qUCB)', value: 'qUCB' },
  { label: 'q-负积分后验方差 (qNIPV)', value: 'qNegIntegratedPosteriorVariance' },
]

const selectedAcquisition = ref('qEI')
const nSuggestions = ref(3)
const loading = ref(false)
const suggestions = ref([])

async function handleSuggest() {
  try {
    loading.value = true
    const config = {
      strategy: selectedAcquisition.value,
      n_suggestions: nSuggestions.value,
      goal: 'maximize',
    }
    const data = await suggestNext(props.sessionId, config)
    suggestions.value = data.suggestions || data.candidates || []
    ElMessage.success(`获得 ${suggestions.value.length} 组建议实验点`)
  } catch (e) {
    ElMessage.error(`获取建议失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

function getColumnNames() {
  if (suggestions.value.length === 0) return []
  const row = suggestions.value[0]
  if (typeof row === 'object' && !Array.isArray(row)) {
    return Object.keys(row)
  }
  return []
}
</script>

<template>
  <div class="panel">
    <div class="panel-header"><h3 class="panel-title">采集优化</h3></div>
    <div class="panel-body">
      <div style="display:flex;gap:16px;align-items:flex-end;margin-bottom:16px;flex-wrap:wrap">
        <div>
          <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">采集函数</div>
          <el-select v-model="selectedAcquisition" style="width:260px">
            <el-option v-for="a in acquisitionOptions" :key="a.value" :label="a.label" :value="a.value" />
          </el-select>
        </div>
        <div>
          <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">建议点数量</div>
          <el-input-number v-model="nSuggestions" :min="1" :max="20" style="width:100px" />
        </div>
        <div>
          <el-button type="primary" @click="handleSuggest" :loading="loading">生成建议</el-button>
        </div>
      </div>

      <el-table :data="suggestions" border stripe empty-text="请选好参数后点击"生成建议"" max-height="400">
        <el-table-column type="index" label="序号" width="60" />
        <el-table-column v-for="col in getColumnNames()" :key="col" :prop="col" :label="col" min-width="100" />
      </el-table>
    </div>
  </div>
</template>
