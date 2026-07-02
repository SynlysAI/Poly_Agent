/**
 * ALchemist 实验设计与优化工具 — API 调用封装。
 *
 * 所有请求通过 Poly_Agent 的代理路由 /api/v1/alchemist/* 转发到 ALchemist 后端。
 * 认证拦截器与 polyAgentApi.js 共用同一套 auth state。
 */
import { getApiBaseUrl } from './polyAgentApi'
import { getAuthorizationHeader } from '../auth/authState'
import axios from 'axios'

const BASE = `${getApiBaseUrl()}/alchemist`

const alchemistClient = axios.create({
  baseURL: BASE,
  timeout: 120000,
})

alchemistClient.interceptors.request.use((config) => {
  const authHeader = getAuthorizationHeader()
  if (authHeader) {
    config.headers['Authorization'] = authHeader
  }
  return config
})

alchemistClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const message = error.response?.data?.detail || error.message || '请求失败'
    return Promise.reject(new Error(message))
  }
)

// ── Session 管理 ──

/** 列出所有 Session */
export function listSessions() {
  return alchemistClient.get('/sessions').then(r => r.data)
}

/** 创建新 Session，可选 name / description / tags */
export function createSession(data = {}) {
  return alchemistClient.post('/sessions', data).then(r => r.data)
}

/** 获取 Session 信息 */
export function getSession(sessionId) {
  return alchemistClient.get(`/sessions/${sessionId}`).then(r => r.data)
}

/** 删除 Session */
export function deleteSession(sessionId) {
  return alchemistClient.delete(`/sessions/${sessionId}`).then(r => r.data)
}

/** 保存 Session 到服务端磁盘 */
export function saveSession(sessionId) {
  return alchemistClient.post(`/sessions/${sessionId}/save`).then(r => r.data)
}

/** 导出 Session 文件（JSON 下载） */
export function exportSession(sessionId) {
  return alchemistClient.get(`/sessions/${sessionId}/export`, { responseType: 'blob' }).then(r => r.data)
}

/** 导入 Session 文件 */
export function importSession(file) {
  const formData = new FormData()
  formData.append('file', file)
  return alchemistClient.post('/sessions/import', formData).then(r => r.data)
}

/** 上传并恢复 Session JSON 文件 */
export function uploadSession(file) {
  const formData = new FormData()
  formData.append('file', file)
  return alchemistClient.post('/sessions/upload', formData).then(r => r.data)
}

// ── 变量管理 ──

/** 获取变量列表 */
export function getVariables(sessionId) {
  return alchemistClient.get(`/sessions/${sessionId}/variables`).then(r => r.data)
}

/** 添加变量 */
export function addVariable(sessionId, variableData) {
  return alchemistClient.post(`/sessions/${sessionId}/variables`, variableData).then(r => r.data)
}

/** 删除变量 */
export function deleteVariable(sessionId, variableId) {
  return alchemistClient.delete(`/sessions/${sessionId}/variables/${variableId}`).then(r => r.data)
}

/** 更新变量 */
export function updateVariable(sessionId, variableId, variableData) {
  return alchemistClient.put(`/sessions/${sessionId}/variables/${variableId}`, variableData).then(r => r.data)
}

// ── 实验设计 ──

/** 生成实验设计 */
export function generateDesign(sessionId, designConfig) {
  return alchemistClient.post(`/sessions/${sessionId}/experiments/design`, designConfig).then(r => r.data)
}

/** 生成初始实验设计 */
export function generateInitialDesign(sessionId, designConfig) {
  return alchemistClient.post(`/sessions/${sessionId}/initial-design`, designConfig).then(r => r.data)
}

/** 添加实验数据 */
export function addExperiments(sessionId, experiments) {
  return alchemistClient.post(`/sessions/${sessionId}/experiments/batch`, experiments).then(r => r.data)
}

/** 添加单条实验数据 */
export function addExperiment(sessionId, experiment, options = {}) {
  return alchemistClient.post(`/sessions/${sessionId}/experiments`, experiment, { params: options }).then(r => r.data)
}

/** 获取已完成实验数据 */
export function getExperiments(sessionId) {
  return alchemistClient.get(`/sessions/${sessionId}/experiments`).then(r => r.data)
}

/** 获取实验数据摘要 */
export function getExperimentsSummary(sessionId) {
  return alchemistClient.get(`/sessions/${sessionId}/experiments/summary`).then(r => r.data)
}

/** 暂存待执行实验 */
export function stageExperiments(sessionId, experiments) {
  return alchemistClient.post(`/sessions/${sessionId}/experiments/staged/batch`, experiments).then(r => r.data)
}

// ── GP 建模 ──

/** 训练 GP 模型 */
export function trainModel(sessionId, modelConfig) {
  return alchemistClient.post(`/sessions/${sessionId}/model/train`, modelConfig).then(r => r.data)
}

/** 获取模型状态 */
export function getModelStatus(sessionId) {
  return alchemistClient.get(`/sessions/${sessionId}/model`).then(r => r.data)
}

// ── 采集优化 ──

/** 获取下一个实验建议点 */
export function suggestNext(sessionId, acquisitionConfig) {
  return alchemistClient.post(`/sessions/${sessionId}/acquisition/suggest`, acquisitionConfig).then(r => r.data)
}

/** 寻找模型最优点 */
export function findOptimum(sessionId, config = {}) {
  return alchemistClient.post(`/sessions/${sessionId}/acquisition/find-optimum`, config).then(r => r.data)
}

// ── 可视化 ──

// ── 可视化 ──

/** 获取 Parity 图数据（实际值 vs 预测值） */
export function getParityData(sessionId, useCalibrated = false) {
  return alchemistClient.get(`/sessions/${sessionId}/visualizations/parity`, { params: { use_calibrated: useCalibrated } }).then(r => r.data)
}

/** 获取 CV 指标随训练量变化数据 */
export function getMetricsData(sessionId, cvSplits = 5) {
  return alchemistClient.get(`/sessions/${sessionId}/visualizations/metrics`, { params: { cv_splits: cvSplits } }).then(r => r.data)
}

/** 获取 Q-Q 图数据 */
export function getQQPlotData(sessionId, useCalibrated = false) {
  return alchemistClient.get(`/sessions/${sessionId}/visualizations/qq-plot`, { params: { use_calibrated: useCalibrated } }).then(r => r.data)
}

/** 获取校准曲线数据 */
export function getCalibrationCurveData(sessionId, useCalibrated = false) {
  return alchemistClient.get(`/sessions/${sessionId}/visualizations/calibration-curve`, { params: { use_calibrated: useCalibrated } }).then(r => r.data)
}

/** 获取模型超参数 */
export function getHyperparametersData(sessionId) {
  return alchemistClient.get(`/sessions/${sessionId}/visualizations/hyperparameters`).then(r => r.data)
}

/** 获取等值线图数据 */
export function getContourData(sessionId, contourConfig) {
  return alchemistClient.post(`/sessions/${sessionId}/visualizations/contour`, contourConfig).then(r => r.data)
}

// ── LLM ──

/** LLM 辅助实验建议 */
export function llmSuggest(sessionId, llmConfig) {
  return alchemistClient.post(`/llm/suggest-effects/${sessionId}`, llmConfig).then(r => r.data)
}
