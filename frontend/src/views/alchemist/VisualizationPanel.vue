<script setup>
import { computed, nextTick, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Plotly from 'plotly.js-dist'
import {
  getCalibrationCurveData,
  getContourData,
  getHyperparametersData,
  getMetricsData,
  getParityData,
  getQQPlotData,
  getVariables,
} from '../../api/alchemistApi'

const PLOT_CONFIG = {
  responsive: true,
  displaylogo: false,
  modeBarButtonsToRemove: ['lasso2d', 'select2d'],
  toImageButtonOptions: {
    format: 'png',
    filename: 'alchemist_visualization',
    height: 600,
    width: 900,
    scale: 2,
  },
}
const AXIS_FONT = { size: 13 }
const TITLE_FONT = { size: 14 }
const GRID_COLOR = '#e5e7eb'
const PRIMARY_COLOR = '#3b82f6'
const REFERENCE_COLOR = '#ef4444'

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
const metricOptions = [
  { label: 'RMSE', value: 'RMSE' },
  { label: 'MAE', value: 'MAE' },
  { label: 'MAPE', value: 'MAPE' },
  { label: 'R²', value: 'R2' },
]
const sigmaOptions = [
  { label: '无', value: 'None' },
  { label: '1.0σ (68%)', value: '1.0' },
  { label: '1.96σ (95%)', value: '1.96' },
  { label: '2.0σ (95.4%)', value: '2.0' },
  { label: '2.58σ (99%)', value: '2.58' },
  { label: '3.0σ (99.7%)', value: '3.0' },
]
const colormapOptions = ['Viridis', 'Plasma', 'Inferno', 'Magma', 'Cividis', 'Jet', 'Hot', 'Cool', 'RdBu', 'YlOrRd']

const chartContainer = ref(null)
const selectedViz = ref('parity')
const loading = ref(false)
const vizData = ref(null)
const errorMsg = ref('')
const variables = ref([])
const contourXVar = ref('')
const contourYVar = ref('')
const contourResolution = ref(50)
const useCalibrated = ref(false)
const selectedMetric = ref('RMSE')
const cvSplits = ref(5)
const sigmaMultiplier = ref('1.96')
const showExperiments = ref(false)
const contourColormap = ref('Viridis')

const isHyperparams = computed(() => selectedViz.value === 'hyperparameters')
const isContour = computed(() => selectedViz.value === 'contour')
const isMetrics = computed(() => selectedViz.value === 'metrics')
const isParity = computed(() => selectedViz.value === 'parity')
const showCalibrated = computed(() =>
  ['parity', 'qq-plot', 'calibration-curve'].includes(selectedViz.value)
)
const realVariables = computed(() =>
  variables.value.filter(v => v.type === 'real')
)
const chartHeight = computed(() => (isContour.value ? '560px' : '470px'))

/** 获取当前 Session 中可用于可视化的变量。 */
async function loadVariables() {
  try {
    const data = await getVariables(props.sessionId)
    variables.value = data.variables || []
    if (realVariables.value.length >= 2 && !contourXVar.value) {
      contourXVar.value = realVariables.value[0].name
      contourYVar.value = realVariables.value[1].name
    }
  } catch {
    variables.value = []
  }
}

/** 加载当前可视化类型的数据并触发图表渲染。 */
async function loadVisualization() {
  errorMsg.value = ''
  vizData.value = null
  loading.value = true
  purgeChart()
  try {
    switch (selectedViz.value) {
      case 'parity':
        vizData.value = await getParityData(props.sessionId, useCalibrated.value)
        break
      case 'metrics':
        vizData.value = await getMetricsData(props.sessionId, cvSplits.value)
        break
      case 'qq-plot':
        vizData.value = await getQQPlotData(props.sessionId, useCalibrated.value)
        break
      case 'calibration-curve':
        vizData.value = await getCalibrationCurveData(props.sessionId, useCalibrated.value)
        break
      case 'contour':
        await loadContourData()
        break
      case 'hyperparameters':
        vizData.value = await getHyperparametersData(props.sessionId)
        break
    }
    await renderVisualization()
  } catch (e) {
    errorMsg.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

/** 加载等值线图数据。 */
async function loadContourData() {
  if (realVariables.value.length < 2) {
    errorMsg.value = '至少需要两个 Real 连续变量才能绘制等值线图'
    return
  }
  if (!contourXVar.value || !contourYVar.value) return
  vizData.value = await getContourData(props.sessionId, {
    x_var: contourXVar.value,
    y_var: contourYVar.value,
    fixed_values: {},
    grid_resolution: contourResolution.value,
    include_experiments: showExperiments.value,
    include_suggestions: false,
  })
}

/** 根据当前可视化类型渲染 Plotly 图表。 */
async function renderVisualization() {
  if (!vizData.value || isHyperparams.value) return
  await nextTick()
  if (!chartContainer.value) return
  const builders = {
    parity: buildParityPlot,
    metrics: buildMetricsPlot,
    'qq-plot': buildQQPlot,
    'calibration-curve': buildCalibrationPlot,
    contour: buildContourPlot,
  }
  const result = builders[selectedViz.value]?.()
  if (!result) return
  await Plotly.react(chartContainer.value, result.data, result.layout, {
    ...PLOT_CONFIG,
    toImageButtonOptions: {
      ...PLOT_CONFIG.toImageButtonOptions,
      filename: `alchemist_${selectedViz.value}`,
    },
  })
}

/** 清理当前 Plotly 实例。 */
function purgeChart() {
  if (chartContainer.value) {
    Plotly.purge(chartContainer.value)
  }
}

/** 生成通用 Plotly 布局配置。 */
function buildBaseLayout(title, xTitle, yTitle, extra = {}) {
  return {
    title: { text: title, font: TITLE_FONT, x: 0.5, xanchor: 'center' },
    autosize: true,
    margin: { l: 70, r: 45, t: 86, b: 64 },
    hovermode: 'closest',
    paper_bgcolor: 'white',
    plot_bgcolor: 'white',
    font: { family: 'Inter, PingFang SC, Microsoft YaHei, Arial, sans-serif', color: '#1f2937' },
    legend: {
      orientation: 'h',
      x: 0.98,
      y: 0.98,
      xanchor: 'right',
      yanchor: 'top',
      bgcolor: 'rgba(255,255,255,0.82)',
      font: { size: 12 },
    },
    xaxis: {
      title: { text: xTitle, font: AXIS_FONT },
      showgrid: true,
      gridcolor: GRID_COLOR,
      zeroline: false,
    },
    yaxis: {
      title: { text: yTitle, font: AXIS_FONT },
      showgrid: true,
      gridcolor: GRID_COLOR,
      zeroline: false,
    },
    ...extra,
  }
}

/** 构建 Parity 图配置。 */
function buildParityPlot() {
  const d = vizData.value
  if (!d.y_true?.length) return null
  const sigma = sigmaMultiplier.value === 'None' ? 0 : Number.parseFloat(sigmaMultiplier.value)
  const allValues = [...d.y_true, ...d.y_pred]
  const minVal = Math.min(...allValues)
  const maxVal = Math.max(...allValues)
  const resultsType = d.calibrated ? ' (Calibrated)' : ' (Uncalibrated)'
  const errorLine = sigma > 0 && d.y_std?.length
    ? `<br>误差棒: ±${sigmaMultiplier.value}σ (${getConfidenceLabel(sigmaMultiplier.value)})`
    : ''
  const title = `交叉验证 Parity 图${resultsType}<br>` +
    `RMSE: ${formatNumber(d.metrics?.rmse)}, MAE: ${formatNumber(d.metrics?.mae)}, R²: ${formatNumber(d.metrics?.r2)}` +
    errorLine

  return {
    data: [
      {
        type: 'scatter',
        mode: 'lines',
        name: '理想预测线',
        x: [minVal, maxVal],
        y: [minVal, maxVal],
        line: { color: REFERENCE_COLOR, width: 2, dash: 'dash' },
        hoverinfo: 'skip',
      },
      {
        type: 'scatter',
        mode: 'markers',
        name: '预测点',
        x: d.y_true,
        y: d.y_pred,
        marker: {
          color: 'white',
          size: 8,
          line: { color: PRIMARY_COLOR, width: 2 },
        },
        error_y: sigma > 0 && d.y_std?.length
          ? { type: 'data', array: d.y_std.map(v => sigma * v), visible: true, color: PRIMARY_COLOR, thickness: 1, width: 0 }
          : undefined,
        hovertemplate: '实际值: %{x:.4f}<br>预测值: %{y:.4f}<extra></extra>',
      },
    ],
    layout: buildBaseLayout(title, '实际值', '预测值'),
  }
}

/** 构建指标曲线图配置。 */
function buildMetricsPlot() {
  const d = vizData.value
  const metricMap = {
    RMSE: { values: d.rmse, label: 'RMSE', title: 'RMSE 随观测数量变化' },
    MAE: { values: d.mae, label: 'MAE', title: 'MAE 随观测数量变化' },
    MAPE: { values: d.mape, label: 'MAPE (%)', title: 'MAPE 随观测数量变化' },
    R2: { values: d.r2, label: 'R²', title: 'R² 随观测数量变化' },
  }
  const metric = metricMap[selectedMetric.value]
  const points = (metric.values || [])
    .map((value, index) => ({ x: index + cvSplits.value, y: value }))
    .filter(point => point.y !== null && point.y !== undefined && Number.isFinite(point.y))
  if (!points.length) return null
  return {
    data: [{
      type: 'scatter',
      mode: 'lines+markers',
      name: metric.label,
      x: points.map(p => p.x),
      y: points.map(p => p.y),
      line: { color: PRIMARY_COLOR, width: 2, shape: 'spline' },
      marker: { color: 'white', size: 8, line: { color: PRIMARY_COLOR, width: 2 } },
      hovertemplate: '观测数量 = %{x}<br>%{y:.4f}<extra></extra>',
    }],
    layout: buildBaseLayout(metric.title, '观测数量', metric.label),
  }
}

/** 构建 Q-Q 图配置。 */
function buildQQPlot() {
  const d = vizData.value
  if (!d.theoretical_quantiles?.length) return null
  const theoretical = d.theoretical_quantiles
  const sample = d.sample_quantiles
  const allValues = [...theoretical, ...sample]
  const minVal = Math.min(...allValues)
  const maxVal = Math.max(...allValues)
  const se = 1.96 / Math.sqrt(d.n_samples || 1)
  const resultsType = d.results_type === 'calibrated' ? ' (Calibrated)' : ' (Uncalibrated)'
  const title = `Q-Q 图：标准化残差 vs 正态分布${resultsType}<br>` +
    `Mean(z) = ${formatNumber(d.z_mean, 3)}, Std(z) = ${formatNumber(d.z_std, 3)}, N = ${d.n_samples}`
  const traces = []

  if ((d.n_samples || 0) < 100) {
    traces.push({
      type: 'scatter',
      mode: 'lines',
      name: '近似 95% 置信区间',
      x: [...theoretical, ...theoretical.slice().reverse()],
      y: [
        ...theoretical.map(v => v + se),
        ...theoretical.slice().reverse().map(v => v - se),
      ],
      fill: 'toself',
      fillcolor: 'rgba(254, 202, 202, 0.5)',
      line: { color: 'rgba(254, 202, 202, 0)' },
      hoverinfo: 'skip',
    })
  }
  traces.push(
    {
      type: 'scatter',
      mode: 'lines',
      name: '理想校准线',
      x: [minVal, maxVal],
      y: [minVal, maxVal],
      line: { color: REFERENCE_COLOR, width: 2, dash: 'dash' },
      hoverinfo: 'skip',
    },
    {
      type: 'scatter',
      mode: 'markers',
      name: '观测分位数',
      x: theoretical,
      y: sample,
      marker: { color: 'white', size: 8, line: { color: PRIMARY_COLOR, width: 2 } },
      hovertemplate: '理论分位数: %{x:.3f}<br>观测分位数: %{y:.3f}<extra></extra>',
    }
  )

  return {
    data: traces,
    layout: buildBaseLayout(title, '理论分位数（标准正态）', '观测分位数（标准化残差）'),
  }
}

/** 构建校准曲线配置。 */
function buildCalibrationPlot() {
  const d = vizData.value
  if (!d.nominal_coverage?.length) return null
  const resultsType = d.results_type === 'calibrated' ? ' (Calibrated)' : ' (Uncalibrated)'
  const warning = d.n_samples < 30
    ? '<br><span style="font-size:12px;color:#ca8a04">警告：样本量较小（N < 30），覆盖率估计可能有噪声。</span>'
    : ''
  return {
    data: [
      {
        type: 'scatter',
        mode: 'lines',
        name: '理想校准线',
        x: [0, 1],
        y: [0, 1],
        line: { color: REFERENCE_COLOR, width: 2, dash: 'dash' },
        hoverinfo: 'skip',
      },
      {
        type: 'scatter',
        mode: 'lines+markers',
        name: '经验覆盖率',
        x: d.nominal_coverage,
        y: d.empirical_coverage,
        line: { color: PRIMARY_COLOR, width: 2 },
        marker: { color: 'white', size: 8, line: { color: PRIMARY_COLOR, width: 2 } },
        hovertemplate: '名义覆盖率: %{x:.3f}<br>经验覆盖率: %{y:.3f}<extra></extra>',
      },
    ],
    layout: buildBaseLayout(
      `校准曲线（可靠性图）${resultsType}<br>N = ${d.n_samples}${warning}`,
      '名义覆盖概率',
      '经验覆盖概率',
      {
        margin: { l: 70, r: 380, t: 94, b: 64 },
        xaxis: { range: [0, 1], title: { text: '名义覆盖概率', font: AXIS_FONT }, showgrid: true, gridcolor: GRID_COLOR, zeroline: false },
        yaxis: { range: [0, 1], title: { text: '经验覆盖概率', font: AXIS_FONT }, showgrid: true, gridcolor: GRID_COLOR, zeroline: false },
        annotations: buildCoverageAnnotations(d),
      }
    ),
  }
}

/** 构建等值线图配置。 */
function buildContourPlot() {
  const d = vizData.value
  if (!d.x_grid?.length || !d.y_grid?.length) return null
  const xValues = d.x_grid[0]
  const yValues = d.y_grid.map(row => row[0])
  const data = [{
    type: 'contour',
    name: '预测值',
    x: xValues,
    y: yValues,
    z: d.predictions,
    colorscale: contourColormap.value,
    colorbar: {
      title: { text: '预测值', side: 'right' },
      thickness: 20,
      len: 0.7,
    },
    contours: { coloring: 'heatmap' },
    hovertemplate: `${d.x_var}: %{x:.3f}<br>${d.y_var}: %{y:.3f}<br>预测值: %{z:.3f}<extra></extra>`,
  }]
  if (showExperiments.value && d.experiments?.x?.length) {
    data.push({
      type: 'scatter',
      mode: 'markers',
      name: '实验点',
      x: d.experiments.x,
      y: d.experiments.y,
      text: d.experiments.output.map(v => formatNumber(v, 3)),
      marker: { color: 'white', size: 8, line: { color: 'black', width: 2 }, symbol: 'circle' },
      hovertemplate: `${d.x_var}: %{x:.3f}<br>${d.y_var}: %{y:.3f}<br>输出值: %{text}<extra></extra>`,
    })
  }
  return {
    data,
    layout: buildBaseLayout('模型预测等值线图', d.x_var, d.y_var, {
      margin: { l: 70, r: 110, t: 70, b: 58 },
      showlegend: showExperiments.value && Boolean(d.experiments),
      legend: {
        x: 1.04,
        y: 1,
        xanchor: 'left',
        yanchor: 'top',
        bgcolor: 'rgba(255,255,255,0.9)',
        bordercolor: '#ccc',
        borderwidth: 1,
      },
      xaxis: {
        range: d.x_bounds,
        title: { text: d.x_var, font: AXIS_FONT },
        showgrid: true,
        gridcolor: GRID_COLOR,
        zeroline: false,
      },
      yaxis: {
        range: d.y_bounds,
        title: { text: d.y_var, font: AXIS_FONT },
        showgrid: true,
        gridcolor: GRID_COLOR,
        zeroline: false,
      },
    }),
  }
}

/** 生成校准曲线右侧指标表注释。 */
function buildCoverageAnnotations(data) {
  const rows = getCoverageMetrics(data)
  const header = '<b>覆盖率指标</b><br><br>' +
    '<b>置信度&nbsp;&nbsp;名义&nbsp;&nbsp;经验&nbsp;&nbsp;偏差&nbsp;&nbsp;状态</b>'
  const body = rows.map(row =>
    `${row.level}&nbsp;&nbsp;${row.nominal.toFixed(3)}&nbsp;&nbsp;${row.empirical.toFixed(3)}&nbsp;&nbsp;` +
    `${row.diff > 0 ? '+' : ''}${row.diff.toFixed(3)}&nbsp;&nbsp;${row.status}`
  ).join('<br>')
  return [{
    xref: 'paper',
    yref: 'paper',
    x: 1.23,
    y: 0.98,
    xanchor: 'left',
    yanchor: 'top',
    align: 'left',
    showarrow: false,
    bgcolor: '#f8fafc',
    bordercolor: '#e5e7eb',
    borderwidth: 1,
    borderpad: 10,
    font: { size: 11, color: '#334155' },
    text: `${header}<br>${body}`,
  }]
}

/** 计算校准覆盖率指标表数据。 */
function getCoverageMetrics(data) {
  if (!data.confidence_levels) return []
  return data.confidence_levels.map((level, index) => {
    const nominal = data.nominal_probabilities?.[index] ?? data.nominal_coverage[index]
    const empirical = data.empirical_probabilities?.[index] ?? data.empirical_coverage[index]
    const diff = empirical - nominal
    let status = '可接受'
    if (Math.abs(diff) < 0.05) status = '良好'
    else if (diff > 0.1) status = '偏保守'
    else if (diff < -0.1) status = '偏自信'
    return { level, nominal, empirical, diff, status }
  })
}

/** 格式化数值，空值显示为短横线。 */
function formatNumber(value, digits = 4) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '-'
  return Number(value).toFixed(digits)
}

/** 获取误差棒置信区间标签。 */
function getConfidenceLabel(value) {
  const labels = {
    '1.0': '68% CI',
    '1.96': '95% CI',
    '2.0': '95.4% CI',
    '2.58': '99% CI',
    '3.0': '99.7% CI',
  }
  return labels[value] || `${value}σ`
}

watch(() => props.sessionId, async () => {
  if (props.sessionId) {
    await loadVariables()
    await loadVisualization()
  }
})
watch(selectedViz, () => { if (props.sessionId) loadVisualization() })
watch([contourXVar, contourYVar, contourResolution, showExperiments, contourColormap], () => {
  if (props.sessionId && isContour.value) loadVisualization()
})
watch([useCalibrated, sigmaMultiplier, selectedMetric, cvSplits], () => {
  if (!props.sessionId) return
  if (showCalibrated.value || isParity.value || isMetrics.value) loadVisualization()
})

onMounted(async () => {
  await loadVariables()
  if (props.sessionId) await loadVisualization()
})
onActivated(() => {
  if (props.sessionId) loadVisualization()
})
onBeforeUnmount(() => {
  purgeChart()
})
</script>

<template>
  <div class="panel">
    <div class="panel-header"><h3 class="panel-title">可视化诊断</h3></div>
    <div class="panel-body">
      <div class="viz-control-row">
        <el-radio-group v-model="selectedViz" size="small">
          <el-radio-button v-for="v in vizTypes" :key="v.value" :value="v.value">{{ v.label }}</el-radio-button>
        </el-radio-group>

        <template v-if="isParity">
          <span class="control-label">误差棒</span>
          <el-select v-model="sigmaMultiplier" size="small" style="width: 132px">
            <el-option v-for="option in sigmaOptions" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
        </template>

        <template v-if="isMetrics">
          <el-select v-model="selectedMetric" size="small" style="width: 100px">
            <el-option v-for="option in metricOptions" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
          <span class="control-label">CV 折数</span>
          <el-input-number v-model="cvSplits" :min="2" :max="10" size="small" style="width: 104px" />
        </template>

        <el-checkbox v-if="showCalibrated" v-model="useCalibrated" size="small">使用校准结果</el-checkbox>
      </div>

      <div v-if="isContour" class="viz-control-row contour-controls">
        <div>
          <div class="field-label">X 轴变量</div>
          <el-select v-model="contourXVar" style="width:160px" size="small">
            <el-option v-for="v in realVariables" :key="v.name" :label="v.name" :value="v.name" />
          </el-select>
        </div>
        <div>
          <div class="field-label">Y 轴变量</div>
          <el-select v-model="contourYVar" style="width:160px" size="small">
            <el-option v-for="v in realVariables" :key="v.name" :label="v.name" :value="v.name" />
          </el-select>
        </div>
        <div>
          <div class="field-label">色带</div>
          <el-select v-model="contourColormap" style="width:140px" size="small">
            <el-option v-for="name in colormapOptions" :key="name" :label="name" :value="name" />
          </el-select>
        </div>
        <div>
          <div class="field-label">分辨率</div>
          <el-slider v-model="contourResolution" :min="30" :max="150" :step="10" style="width:160px" />
        </div>
        <el-checkbox v-model="showExperiments" size="small">显示实验点</el-checkbox>
      </div>

      <el-alert v-if="errorMsg" :title="errorMsg" type="warning" :closable="false" show-icon style="margin-bottom:12px" />

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
        <div v-else-if="!loading" class="empty-state">暂无超参数数据，请先训练模型</div>
      </div>

      <div v-else v-loading="loading">
        <div v-if="!vizData && !loading && !errorMsg" class="empty-state">暂无数据，请先训练 GP 模型后再查看图表</div>
        <div ref="chartContainer" class="plotly-chart" :style="{ height: chartHeight }"></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.viz-control-row {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
  align-items: center;
}

.contour-controls {
  align-items: flex-end;
  padding: 8px 0 4px;
}

.control-label,
.field-label {
  font-size: 12px;
  color: var(--app-ink-muted);
}

.field-label {
  margin-bottom: 2px;
}

.plotly-chart {
  width: 100%;
  min-height: 420px;
}

.empty-state {
  padding: 40px;
  text-align: center;
  color: var(--app-ink-muted);
}
</style>
