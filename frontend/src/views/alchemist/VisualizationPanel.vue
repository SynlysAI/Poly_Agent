<script setup>
import { ref, onMounted, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import Plotly from 'plotly.js-dist'
import { getContourData, getVisualization } from '../../api/alchemistApi'

const props = defineProps({
  sessionId: { type: String, required: true }
})

const vizTypes = [
  { label: '校准曲线', value: 'calibration-curve' },
  { label: '等值线图', value: 'contour' },
  { label: 'QQ 图', value: 'qq-plot' },
  { label: 'Parity 图', value: 'parity' },
  { label: '评估指标', value: 'metrics' },
  { label: '超参数', value: 'hyperparameters' },
]

const selectedViz = ref('parity')
const loading = ref(false)
const chartContainer = ref(null)
const vizData = ref(null)

async function loadVisualization() {
  try {
    loading.value = true
    vizData.value = null
    const data = await getVisualization(props.sessionId, selectedViz.value)
    vizData.value = data
    await nextTick()
    if (chartContainer.value && data) {
      renderChart(data)
    }
  } catch (e) {
    ElMessage.error(`加载可视化数据失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

function renderChart(data) {
  const layout = {
    font: { family: 'Inter, PingFang SC, Microsoft YaHei, sans-serif' },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    margin: { l: 50, r: 30, t: 30, b: 50 },
    ...(data.layout || {}),
  }

  if (data.plotly_data) {
    Plotly.newPlot(chartContainer.value, data.plotly_data.data, data.plotly_data.layout || layout, {
      responsive: true,
      displaylogo: false,
    })
  } else if (selectedViz.value === 'parity' && data.y_true) {
    const perfectLine = {
      x: data.bounds || [Math.min(...data.y_true), Math.max(...data.y_true)],
      y: data.bounds || [Math.min(...data.y_true), Math.max(...data.y_true)],
      mode: 'lines',
      name: '完美预测线',
      line: { dash: 'dash', color: 'gray' },
    }
    const scatter = {
      x: data.y_true,
      y: data.y_pred,
      mode: 'markers',
      type: 'scatter',
      name: '预测结果',
      error_y: { type: 'data', array: data.y_std, visible: true },
      marker: { size: 8, opacity: 0.7 },
    }
    Plotly.newPlot(chartContainer.value, [scatter, perfectLine], {
      ...layout,
      title: '实际值 vs 预测值',
      xaxis: { title: '实际值' },
      yaxis: { title: '预测值' },
    }, { responsive: true, displaylogo: false })
  } else if (selectedViz.value === 'metrics' && data.training_sizes) {
    const traces = []
    const metricNames = [
      { key: 'rmse', name: 'RMSE', color: '#ef4444' },
      { key: 'mae', name: 'MAE', color: '#f59e0b' },
      { key: 'r2', name: 'R²', color: '#3b82f6' },
    ]
    for (const m of metricNames) {
      if (data[m.key]) {
        traces.push({ x: data.training_sizes, y: data[m.key], mode: 'lines+markers', name: m.name, line: { color: m.color } })
      }
    }
    Plotly.newPlot(chartContainer.value, traces, { ...layout, title: 'CV 指标 vs 训练样本量', xaxis: { title: '训练样本数' }, yaxis: { title: '指标值' } }, { responsive: true, displaylogo: false })
  } else {
    ElMessage.info('该可视化类型暂无数据或暂不支持自动渲染')
  }
}

watch(() => props.sessionId, () => { if (props.sessionId) loadVisualization() })
watch(selectedViz, () => { if (props.sessionId) loadVisualization() })
onMounted(() => { if (props.sessionId) loadVisualization() })
</script>

<template>
  <div class="panel">
    <div class="panel-header"><h3 class="panel-title">可视化诊断</h3></div>
    <div class="panel-body">
      <div style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap">
        <el-radio-group v-model="selectedViz" size="small">
          <el-radio-button v-for="v in vizTypes" :key="v.value" :value="v.value">{{ v.label }}</el-radio-button>
        </el-radio-group>
      </div>

      <div v-loading="loading" style="min-height:400px">
        <div v-if="vizData && selectedViz === 'hyperparameters'" style="padding:16px">
          <el-descriptions v-if="vizData.hyperparameters" border :column="2" size="small">
            <el-descriptions-item label="后端">{{ vizData.backend || '-' }}</el-descriptions-item>
            <el-descriptions-item label="核函数">{{ vizData.kernel || '-' }}</el-descriptions-item>
            <el-descriptions-item label="输入变换">{{ vizData.input_transform || '无' }}</el-descriptions-item>
            <el-descriptions-item label="输出变换">{{ vizData.output_transform || '无' }}</el-descriptions-item>
            <el-descriptions-item label="校准已启用">{{ vizData.calibration_enabled ? '是' : '否' }}</el-descriptions-item>
            <el-descriptions-item label="校准因子">{{ vizData.calibration_factor || '-' }}</el-descriptions-item>
          </el-descriptions>
        </div>
        <div v-else ref="chartContainer" style="width:100%;min-height:400px"></div>
      </div>
    </div>
  </div>
</template>
