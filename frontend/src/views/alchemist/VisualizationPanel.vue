<script setup>
import { ref, computed, onMounted, onActivated, watch } from 'vue'
import { ElMessage } from 'element-plus'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { ScatterChart, LineChart, HeatmapChart } from 'echarts/charts'
import {
  TitleComponent, TooltipComponent, LegendComponent,
  GridComponent, VisualMapComponent, ToolboxComponent,
} from 'echarts/components'

use([CanvasRenderer, ScatterChart, LineChart, HeatmapChart,
  TitleComponent, TooltipComponent, LegendComponent,
  GridComponent, VisualMapComponent, ToolboxComponent])

import {
  getContourData, getParityData, getMetricsData, getQQPlotData,
  getCalibrationCurveData, getHyperparametersData, getVariables,
} from '../../api/alchemistApi'

const props = defineProps({
  sessionId: { type: String, required: true },
})

const vizTypes = [
  { label: 'Parity 图', value: 'parity' },
  { label: '评估指标', value: 'metrics' },
  { label: 'QQ 图', value: 'qq-plot' },
  { label: '校准曲线', value: 'calibration-curve' },
  { label: '等值线图', value: 'contour' },
  { label: '超参数', value: 'hyperparameters' },
]

const selectedViz = ref('parity')
const loading = ref(false)
const vizData = ref(null)
const errorMsg = ref('')
const chartOption = ref(null)

const variables = ref([])
const contourXVar = ref('')
const contourYVar = ref('')
const contourResolution = ref(50)
const useCalibrated = ref(false)

const isHyperparams = computed(() => selectedViz.value === 'hyperparameters')
const isContour = computed(() => selectedViz.value === 'contour')
const showCalibrated = computed(() =>
  ['parity', 'qq-plot', 'calibration-curve'].includes(selectedViz.value)
)

const chartHeight = computed(() => (isContour.value ? '520px' : '440px'))

async function loadVariables() {
  try {
    const data = await getVariables(props.sessionId)
    variables.value = (data.variables || []).filter(
      v => v.type === 'real' || v.type === 'integer'
    )
    if (variables.value.length >= 2 && !contourXVar.value) {
      contourXVar.value = variables.value[0].name
      contourYVar.value = variables.value[1].name
    }
  } catch { /* 静默 */ }
}

async function loadVisualization() {
  errorMsg.value = ''
  vizData.value = null
  chartOption.value = null
  loading.value = true
  try {
    switch (selectedViz.value) {
      case 'parity':
        vizData.value = await getParityData(props.sessionId, useCalibrated.value)
        break
      case 'metrics':
        vizData.value = await getMetricsData(props.sessionId)
        break
      case 'qq-plot':
        vizData.value = await getQQPlotData(props.sessionId, useCalibrated.value)
        break
      case 'calibration-curve':
        vizData.value = await getCalibrationCurveData(props.sessionId, useCalibrated.value)
        break
      case 'contour':
        if (contourXVar.value && contourYVar.value) {
          vizData.value = await getContourData(props.sessionId, {
            x_var: contourXVar.value,
            y_var: contourYVar.value,
            grid_resolution: contourResolution.value,
            include_experiments: true,
          })
        }
        break
      case 'hyperparameters':
        vizData.value = await getHyperparametersData(props.sessionId)
        break
    }
    if (vizData.value && !isHyperparams.value) {
      chartOption.value = buildChartOption()
    }
  } catch (e) {
    errorMsg.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

function buildChartOption() {
  switch (selectedViz.value) {
    case 'parity': return buildParityOption()
    case 'metrics': return buildMetricsOption()
    case 'qq-plot': return buildQQOption()
    case 'calibration-curve': return buildCalibrationOption()
    case 'contour': return buildContourOption()
    default: return null
  }
}

function buildParityOption() {
  const d = vizData.value
  const m = d.metrics || {}
  return {
    title: {
      text: `Parity 图  RMSE=${m.rmse?.toFixed(4)}  MAE=${m.mae?.toFixed(4)}  R²=${m.r2?.toFixed(4)}`,
      left: 'center', textStyle: { fontSize: 14 },
    },
    tooltip: { trigger: 'item', formatter: p => `实际值: ${p.value[0]}<br/>预测值: ${p.value[1]}` },
    legend: { top: 8, right: 10, data: ['预测点', '完美预测'] },
    xAxis: { name: '实际值', nameLocation: 'center', nameGap: 30, type: 'value' },
    yAxis: { name: '预测值', nameLocation: 'center', nameGap: 40, type: 'value' },
    series: [
      {
        name: '完美预测', type: 'line',
        data: [[d.bounds[0], d.bounds[0]], [d.bounds[1], d.bounds[1]]],
        lineStyle: { type: 'dashed', color: '#9ca3af' }, symbol: 'none',
        z: 1,
      },
      {
        name: '预测点', type: 'scatter',
        data: d.y_true.map((v, i) => [v, d.y_pred[i]]),
        symbolSize: 8, itemStyle: { color: '#3b82f6', opacity: 0.7 },
        z: 2,
      },
    ],
    grid: { left: 65, right: 30, top: 50, bottom: 40 },
  }
}

function buildMetricsOption() {
  const d = vizData.value
  const colors = { rmse: '#ef4444', mae: '#f59e0b', r2: '#3b82f6', mape: '#22c55e' }
  const names = { rmse: 'RMSE', mae: 'MAE', r2: 'R²', mape: 'MAPE' }
  return {
    title: { text: 'CV 指标 vs 训练样本量', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend: { top: 8, right: 10, data: Object.values(names) },
    xAxis: { name: '训练样本数', nameLocation: 'center', nameGap: 30, type: 'category', data: d.training_sizes },
    yAxis: { name: '指标值', nameLocation: 'center', nameGap: 40, type: 'value' },
    series: Object.entries(colors)
      .filter(([key]) => d[key])
      .map(([key, color]) => ({
        name: names[key], type: 'line',
        data: d[key].map(v => v ?? '-'),
        lineStyle: { color }, itemStyle: { color },
        connectNulls: false,
      })),
    grid: { left: 65, right: 30, top: 50, bottom: 40 },
  }
}

function buildQQOption() {
  const d = vizData.value
  const status = Math.abs(d.z_mean) < 0.2 ? '校准良好' : (Math.abs(d.z_mean) > 0.5 ? '存在偏差' : '轻微偏差')
  const lineMin = d.bounds ? d.bounds[0] : Math.min(...d.theoretical_quantiles, ...d.sample_quantiles)
  const lineMax = d.bounds ? d.bounds[1] : Math.max(...d.theoretical_quantiles, ...d.sample_quantiles)
  return {
    title: {
      text: `Q-Q 图  z_mean=${d.z_mean?.toFixed(3)}  z_std=${d.z_std?.toFixed(3)}  n=${d.n_samples}  ${status}`,
      left: 'center', textStyle: { fontSize: 14 },
    },
    tooltip: { trigger: 'item', formatter: p => `理论: ${p.value[0].toFixed(3)}<br/>样本: ${p.value[1].toFixed(3)}` },
    legend: { top: 8, right: 10, data: ['残差分位数', '标准正态'] },
    xAxis: { name: '理论分位数（标准正态）', nameLocation: 'center', nameGap: 30, type: 'value' },
    yAxis: { name: '样本分位数', nameLocation: 'center', nameGap: 40, type: 'value' },
    series: [
      {
        name: '标准正态', type: 'line',
        data: [[lineMin, lineMin], [lineMax, lineMax]],
        lineStyle: { type: 'dashed', color: '#9ca3af' }, symbol: 'none', z: 1,
      },
      {
        name: '残差分位数', type: 'scatter',
        data: d.theoretical_quantiles.map((v, i) => [v, d.sample_quantiles[i]]),
        symbolSize: 6, itemStyle: { color: '#3b82f6', opacity: 0.7 }, z: 2,
      },
    ],
    grid: { left: 70, right: 30, top: 50, bottom: 40 },
  }
}

function buildCalibrationOption() {
  const d = vizData.value
  return {
    title: { text: `校准曲线  n=${d.n_samples}`, left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis', formatter: p => `名义: ${(p[0].value[0] * 100).toFixed(0)}%<br/>经验: ${(p[0].value[1] * 100).toFixed(1)}%` },
    legend: { top: 8, right: 10, data: ['实际覆盖', '理想校准'] },
    xAxis: { name: '名义覆盖率', nameLocation: 'center', nameGap: 30, type: 'value', min: 0, max: 1, axisLabel: { formatter: '{value}' } },
    yAxis: { name: '经验覆盖率', nameLocation: 'center', nameGap: 40, type: 'value', min: 0, max: 1 },
    series: [
      {
        name: '理想校准', type: 'line',
        data: [[0, 0], [1, 1]],
        lineStyle: { type: 'dashed', color: '#9ca3af' }, symbol: 'none', z: 1,
      },
      {
        name: '实际覆盖', type: 'line',
        data: d.nominal_coverage.map((v, i) => [v, d.empirical_coverage[i]]),
        lineStyle: { color: '#3b82f6' }, itemStyle: { color: '#3b82f6' },
        symbolSize: 6, z: 2,
      },
    ],
    grid: { left: 65, right: 30, top: 50, bottom: 40 },
  }
}

function buildContourOption() {
  const d = vizData.value
  const xVals = d.x_grid[0]
  const yVals = d.y_grid.map(r => r[0])
  const heatData = []
  for (let i = 0; i < xVals.length; i++) {
    for (let j = 0; j < yVals.length; j++) {
      heatData.push([i, j, d.predictions[j][i]])
    }
  }
  const series = [{
    name: '预测值', type: 'heatmap',
    data: heatData,
    label: { show: false },
    emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' } },
  }]
  if (d.experiments) {
    series.push({
      name: '实验点', type: 'scatter',
      data: d.experiments.x.map((v, i) => {
        // 找到散点在热力图坐标中的近似位置
        const xi = xVals.findIndex(xx => xx >= v)
        const yi = yVals.findIndex(yy => yy >= d.experiments.y[i])
        return [xi >= 0 ? xi : 0, yi >= 0 ? yi : 0]
      }),
      symbolSize: 12, itemStyle: { color: '#fff', borderColor: '#1e293b', borderWidth: 1.5 },
      z: 10,
    })
  }
  return {
    title: { text: `等值线图 (${d.x_var} × ${d.y_var})`, left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'item', formatter: p => {
      if (p.seriesName === '实验点') return `实验点<br/>${d.x_var}: ${d.experiments.x[p.dataIndex]}<br/>${d.y_var}: ${d.experiments.y[p.dataIndex]}<br/>Output: ${d.experiments.output[p.dataIndex]?.toFixed(4)}`
      const xi = p.data[0], yi = p.data[1]
      return `${d.x_var}: ${xVals[xi].toFixed(3)}<br/>${d.y_var}: ${yVals[yi].toFixed(3)}<br/>预测值: ${d.predictions[yi][xi].toFixed(4)}`
    }},
    xAxis: {
      name: d.x_var, nameLocation: 'center', nameGap: 30, type: 'category',
      data: xVals.map(v => v.toFixed(2)),
      nameTextStyle: { fontSize: 13 },
    },
    yAxis: {
      name: d.y_var, nameLocation: 'center', nameGap: 50, type: 'category',
      data: yVals.map(v => v.toFixed(2)),
      nameTextStyle: { fontSize: 13 },
    },
    visualMap: {
      min: d.colorbar_bounds[0], max: d.colorbar_bounds[1],
      calculable: true, orient: 'vertical', right: 10, top: 'center',
      inRange: { color: ['#313695', '#4575b4', '#74add1', '#abd9e9', '#e0f3f8', '#ffffbf', '#fee090', '#fdae61', '#f46d43', '#d73027', '#a50026'] },
    },
    grid: { left: 65, right: 80, top: 50, bottom: 60 },
    series,
  }
}

watch(() => props.sessionId, () => {
  if (props.sessionId) { loadVariables(); loadVisualization() }
})
watch(selectedViz, () => { if (props.sessionId) loadVisualization() })
watch([contourXVar, contourYVar, contourResolution], () => {
  if (props.sessionId && isContour.value) loadVisualization()
})
watch(useCalibrated, () => {
  if (props.sessionId && showCalibrated.value) loadVisualization()
})

onMounted(() => {
  loadVariables()
  if (props.sessionId) loadVisualization()
})
onActivated(() => {
  if (props.sessionId) loadVisualization()
})
</script>

<template>
  <div class="panel">
    <div class="panel-header"><h3 class="panel-title">可视化诊断</h3></div>
    <div class="panel-body">
      <!-- 图表类型选择 -->
      <div style="display:flex;gap:12px;margin-bottom:12px;flex-wrap:wrap;align-items:center">
        <el-radio-group v-model="selectedViz" size="small">
          <el-radio-button v-for="v in vizTypes" :key="v.value" :value="v.value">{{ v.label }}</el-radio-button>
        </el-radio-group>
        <el-checkbox v-if="showCalibrated" v-model="useCalibrated" size="small">使用校准结果</el-checkbox>
      </div>

      <!-- 等值线图控制 -->
      <div v-if="isContour" style="display:flex;gap:16px;margin-bottom:12px;flex-wrap:wrap;align-items:flex-end">
        <div>
          <div style="font-size:12px;color:var(--app-ink-muted);margin-bottom:2px">X 轴变量</div>
          <el-select v-model="contourXVar" style="width:160px" size="small">
            <el-option v-for="v in variables" :key="v.name" :label="v.name" :value="v.name" />
          </el-select>
        </div>
        <div>
          <div style="font-size:12px;color:var(--app-ink-muted);margin-bottom:2px">Y 轴变量</div>
          <el-select v-model="contourYVar" style="width:160px" size="small">
            <el-option v-for="v in variables" :key="v.name" :label="v.name" :value="v.name" />
          </el-select>
        </div>
        <div>
          <div style="font-size:12px;color:var(--app-ink-muted);margin-bottom:2px">分辨率</div>
          <el-slider v-model="contourResolution" :min="20" :max="100" :step="10" style="width:120px" show-input />
        </div>
      </div>

      <!-- 错误提示 -->
      <el-alert v-if="errorMsg" :title="errorMsg" type="warning" :closable="false" show-icon style="margin-bottom:12px" />

      <!-- 超参数 -->
      <div v-if="isHyperparams">
        <div v-if="vizData" style="padding:8px">
          <el-descriptions v-if="vizData.hyperparameters" border :column="2" size="small">
            <el-descriptions-item label="后端">{{ vizData.backend || '-' }}</el-descriptions-item>
            <el-descriptions-item label="核函数">{{ vizData.kernel || '-' }}</el-descriptions-item>
            <el-descriptions-item label="输入变换">{{ vizData.input_transform || '无' }}</el-descriptions-item>
            <el-descriptions-item label="输出变换">{{ vizData.output_transform || '无' }}</el-descriptions-item>
            <el-descriptions-item label="校准">{{ vizData.calibration_enabled ? '已启用' : '未启用' }}</el-descriptions-item>
            <el-descriptions-item label="校准因子">{{ vizData.calibration_factor ?? '-' }}</el-descriptions-item>
          </el-descriptions>
          <div v-if="vizData.hyperparameters" style="margin-top:14px">
            <h4 style="font-size:14px;font-weight:600;margin-bottom:8px;color:var(--app-ink)">超参数值</h4>
            <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px">
              <div v-for="(val, key) in vizData.hyperparameters" :key="key" style="border:1px solid var(--app-hairline);border-radius:6px;padding:8px 12px;background:var(--app-stat-bg)">
                <span style="font-size:11px;color:var(--app-ink-muted)">{{ key }}</span>
                <strong style="display:block;font-size:14px;color:var(--app-ink)">{{ typeof val === 'number' ? val.toFixed(6) : val }}</strong>
              </div>
            </div>
          </div>
        </div>
        <div v-else-if="!loading" style="padding:40px;text-align:center;color:var(--app-ink-muted)">暂无超参数数据，请先训练模型</div>
      </div>

      <!-- 图表 -->
      <div v-else v-loading="loading">
        <div v-if="!vizData && !loading && !errorMsg" style="padding:40px;text-align:center;color:var(--app-ink-muted)">暂无数据，请先训练 GP 模型后再查看图表</div>
        <v-chart v-if="chartOption" :option="chartOption" :autoresize="true" :style="`width:100%;height:${chartHeight}`" />
      </div>
    </div>
  </div>
</template>
