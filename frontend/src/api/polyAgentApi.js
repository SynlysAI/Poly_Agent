import axios from 'axios'

import { clearAuthSession, getAuthorizationHeader } from '../auth/authState'

const AUTH_EXPIRED_EVENT_NAME = 'poly-agent-auth-expired'

const resolvedBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'

const apiClient = axios.create({
  baseURL: resolvedBaseUrl,
  timeout: 60000,
})

function generateRequestId() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

apiClient.interceptors.request.use((config) => {
  config.headers['X-Request-Id'] = generateRequestId()
  const authHeader = getAuthorizationHeader()
  if (authHeader) {
    config.headers['Authorization'] = authHeader
  }
  config.metadata = { ...(config.metadata || {}), requestId: config.headers['X-Request-Id'], startedAt: Date.now() }
  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (axios.isCancel(error)) {
      return Promise.reject(createApiError('canceled', error.message))
    }
    if (!error.response || error.code === 'ECONNABORTED') {
      const kind = error.code === 'ECONNABORTED' ? 'timeout' : 'network'
      return Promise.reject(createApiError(kind, error.message))
    }
    const { status, data } = error.response
    if (status === 401) {
      clearAuthSession()
      window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT_NAME))
    }
    const message = data?.message || data?.detail || error.message
    const err = createApiError('http', message)
    err.status = status
    err.code = data?.code
    err.detail = data?.data?.detail || data?.detail
    err.path = data?.data?.path
    err.errors = data?.data?.errors
    return Promise.reject(err)
  },
)

function createApiError(kind, message) {
  const error = new Error(message || '未知错误')
  error.kind = kind
  error.isApiError = true
  return error
}

function unwrapResponse(response) {
  const payload = response.data
  if (!payload) {
    return null
  }
  if (payload.code !== 0) {
    const err = createApiError('api_business', payload.message || '服务异常')
    err.code = payload.code
    throw err
  }
  return payload.data
}

function parseDownloadFilename(contentDisposition, fallbackName) {
  if (!contentDisposition) {
    return fallbackName
  }
  const encodedMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (encodedMatch?.[1]) {
    try {
      return decodeURIComponent(encodedMatch[1])
    } catch {
      return encodedMatch[1]
    }
  }
  const filenameMatch = contentDisposition.match(/filename="?([^";]+)"?/i)
  return filenameMatch?.[1] || fallbackName
}

export function getApiErrorMessage(error) {
  if (!error) return '未知错误'
  if (error.isApiError) {
    if (error.kind === 'network') return '网络连接失败，请检查网络'
    if (error.kind === 'timeout') return '请求超时'
    if (error.kind === 'canceled') return '请求已取消'
    const statusMsgMap = { 400: '参数有误', 401: '登录已过期', 403: '无权限', 404: '资源未找到', 422: '参数校验失败', 500: '服务器内部错误', 502: '上游服务异常', 504: '上游服务超时' }
    if (error.status && statusMsgMap[error.status]) {
      const genericMessages = new Set([
        'internal error',
        'invalid parameter',
        'validation failed',
        'resource not found',
        'upstream service error',
        'upstream timeout',
      ])
      const message = error.detail && genericMessages.has(error.message) ? error.detail : (error.message || error.detail || '')
      return `${statusMsgMap[error.status]}：${message}`
    }
    return error.message || '服务异常'
  }
  return error.message || '未知错误'
}

export function getApiBaseUrl() {
  return resolvedBaseUrl
}

// ── 认证 API ──

export function getAuthStatus() {
  return apiClient.get('/auth/status').then(unwrapResponse)
}

export function loginWithPassword(payload) {
  return apiClient.post('/auth/login', payload).then(unwrapResponse)
}

export function registerWithInviteCode(payload) {
  return apiClient.post('/auth/register', payload).then(unwrapResponse)
}

export function getCurrentUser() {
  return apiClient.get('/auth/me').then(unwrapResponse)
}

// ── 管理员 API ──

export function listAdminUsers() {
  return apiClient.get('/admin/users').then(unwrapResponse)
}

export function updateAdminUserStatus(userId, payload) {
  return apiClient.patch(`/admin/users/${userId}/status`, payload).then(unwrapResponse)
}

export function listInviteCodes() {
  return apiClient.get('/admin/invite-codes').then(unwrapResponse)
}

export function createInviteCode(payload) {
  return apiClient.post('/admin/invite-codes', payload).then(unwrapResponse)
}

export function disableInviteCode(inviteId) {
  return apiClient.patch(`/admin/invite-codes/${inviteId}/disable`).then(unwrapResponse)
}

// ── 审计 API ──

export function listAuditEvents(params = {}) {
  return apiClient.get('/audit-events', { params }).then(unwrapResponse)
}

// ── 计算智能 API ──

export function createComputation(payload) {
  return apiClient.post('/computations', payload).then(unwrapResponse)
}

export function listComputations(params = {}) {
  return apiClient.get('/computations', { params }).then(unwrapResponse)
}

export function getComputation(runId) {
  return apiClient.get(`/computations/${runId}`).then(unwrapResponse)
}

export function cancelComputation(runId) {
  return apiClient.post(`/computations/${runId}/cancel`).then(unwrapResponse)
}

export function retryComputation(runId) {
  return apiClient.post(`/computations/${runId}/retry`).then(unwrapResponse)
}

export function listComputationArtifacts(runId) {
  return apiClient.get(`/computations/${runId}/artifacts`).then(unwrapResponse)
}

export function previewArtifact(artifactId) {
  return apiClient.get(`/artifacts/${artifactId}/preview`).then(unwrapResponse)
}

export function getArtifact(artifactId) {
  return apiClient.get(`/artifacts/${artifactId}`).then(unwrapResponse)
}

export function getArtifactStructure(artifactId) {
  return apiClient.get(`/artifacts/${artifactId}/structure`).then(unwrapResponse)
}

export function getArtifactSpectrum(artifactId) {
  return apiClient.get(`/artifacts/${artifactId}/spectrum`).then(unwrapResponse)
}

export function downloadArtifact(artifactId) {
  return apiClient
    .get(`/artifacts/${encodeURIComponent(artifactId)}/download`, { responseType: 'blob' })
    .then((response) => ({
      blob: response.data,
      filename: parseDownloadFilename(response.headers['content-disposition'], `${artifactId}.dat`),
      contentType: response.headers['content-type'] || 'application/octet-stream',
    }))
}

// ── 优化闭环 API ──

export function createCampaign(payload) {
  return apiClient.post('/optimization/campaigns', payload).then(unwrapResponse)
}

export function listCampaigns(params = {}) {
  return apiClient.get('/optimization/campaigns', { params }).then(unwrapResponse)
}

export function getCampaign(campaignId) {
  return apiClient.get(`/optimization/campaigns/${campaignId}`).then(unwrapResponse)
}

export function getCampaignHistory(campaignId) {
  return apiClient.get(`/optimization/campaigns/${campaignId}/history`).then(unwrapResponse)
}

export function pauseCampaign(campaignId, payload = {}) {
  return apiClient.post(`/optimization/campaigns/${campaignId}:pause`, payload).then(unwrapResponse)
}

export function resumeCampaign(campaignId, payload = {}) {
  return apiClient.post(`/optimization/campaigns/${campaignId}:resume`, payload).then(unwrapResponse)
}

export function archiveCampaign(campaignId, payload = {}) {
  return apiClient.post(`/optimization/campaigns/${campaignId}:archive`, payload).then(unwrapResponse)
}

export function completeCampaign(campaignId, payload = {}) {
  return apiClient.post(`/optimization/campaigns/${campaignId}:complete`, payload).then(unwrapResponse)
}

export function failCampaign(campaignId, payload = {}) {
  return apiClient.post(`/optimization/campaigns/${campaignId}:fail`, payload).then(unwrapResponse)
}

export function importCampaignCandidates(campaignId, payload) {
  return apiClient.post(`/optimization/campaigns/${campaignId}/candidates:import`, payload).then(unwrapResponse)
}

export function importCampaignCandidatesCsv(campaignId, csvText) {
  const formData = new FormData()
  formData.append('csv_text', csvText)
  return apiClient.post(`/optimization/campaigns/${campaignId}/candidates:import-csv`, formData).then(unwrapResponse)
}

export function generateSuggestion(campaignId, payload = { batch_size: 1 }) {
  return apiClient.post(`/optimization/campaigns/${campaignId}/suggestions`, payload).then(unwrapResponse)
}

export function createObservation(campaignId, payload) {
  return apiClient.post(`/optimization/campaigns/${campaignId}/observations`, payload).then(unwrapResponse)
}

export function createObservationFromComputation(runId) {
  return apiClient.post(`/optimization/computations/${runId}/create-observation`).then(unwrapResponse)
}

export function submitSuggestionComputation(suggestionId) {
  return apiClient.post(`/optimization/suggestions/${suggestionId}/submit-computation`).then(unwrapResponse)
}

export function rejectSuggestion(suggestionId, payload) {
  return apiClient.post(`/optimization/suggestions/${suggestionId}/reject`, payload).then(unwrapResponse)
}

export function markSuggestionFailed(suggestionId, payload) {
  return apiClient.post(`/optimization/suggestions/${suggestionId}/failed`, payload).then(unwrapResponse)
}

export function getIntegrationStatus() {
  return apiClient.get('/integrations/status').then(unwrapResponse)
}

export function listIntegrationConfigs() {
  return apiClient.get('/integrations/configs').then(unwrapResponse)
}

export function upsertIntegrationConfig(serviceKey, payload) {
  return apiClient.put(`/integrations/configs/${serviceKey}`, payload).then(unwrapResponse)
}

export function checkIntegrationConfig(serviceKey) {
  return apiClient.post(`/integrations/configs/${serviceKey}/check`).then(unwrapResponse)
}

// ── LLM API ──

/** 通用对话接口 */
export function chatWithLLM(messages) {
  return apiClient.post('/llm/chat', { messages }).then(r => r.data)
}

/** LLM 辅助实验建议 */
export function suggestExperiments(payload) {
  return apiClient.post('/llm/suggest-experiments', payload).then(r => r.data)
}

// ── ResearchEngine API ──

// ── ProblemSpec ──

export function createProblemSpec(payload) {
  return apiClient.post('/research-engine/problem-specs', payload).then(unwrapResponse)
}

export function listProblemSpecs(params = {}) {
  return apiClient.get('/research-engine/problem-specs', { params }).then(unwrapResponse)
}

export function getProblemSpec(problemSpecId) {
  return apiClient.get(`/research-engine/problem-specs/${problemSpecId}`).then(unwrapResponse)
}

export function updateProblemSpec(problemSpecId, payload) {
  return apiClient.patch(`/research-engine/problem-specs/${problemSpecId}`, payload).then(unwrapResponse)
}

export function freezeProblemSpec(problemSpecId) {
  return apiClient.post(`/research-engine/problem-specs/${problemSpecId}/freeze`).then(unwrapResponse)
}

// ── ExecutionDecision ──

export function createExecutionDecision(problemSpecId, payload) {
  return apiClient.post(`/research-engine/problem-specs/${problemSpecId}/execution-decisions`, payload).then(unwrapResponse)
}

export function listExecutionDecisions(problemSpecId, params = {}) {
  return apiClient.get(`/research-engine/problem-specs/${problemSpecId}/execution-decisions`, { params }).then(unwrapResponse)
}

export function getActiveExecutionDecision(problemSpecId) {
  return apiClient.get(`/research-engine/problem-specs/${problemSpecId}/execution-decisions/active`).then(unwrapResponse)
}

// ── AlgorithmRegistry ──

export function listAlgorithms(params = {}) {
  return apiClient.get('/research-engine/algorithms', { params }).then(unwrapResponse)
}

export function getAlgorithm(algorithmId) {
  return apiClient.get(`/research-engine/algorithms/${algorithmId}`).then(unwrapResponse)
}

// ── AlgorithmRun ──

export function createAlgorithmRun(payload) {
  return apiClient.post('/research-engine/algorithm-runs', payload).then(unwrapResponse)
}

export function listAlgorithmRuns(params = {}) {
  return apiClient.get('/research-engine/algorithm-runs', { params }).then(unwrapResponse)
}

export function getAlgorithmRun(runId) {
  return apiClient.get(`/research-engine/algorithm-runs/${runId}`).then(unwrapResponse)
}

// ── ManualWorkflow / WorkflowRun ──

export function createManualWorkflow(payload) {
  return apiClient.post('/research-engine/manual-workflows', payload).then(unwrapResponse)
}

export function listManualWorkflows(params = {}) {
  return apiClient.get('/research-engine/manual-workflows', { params }).then(unwrapResponse)
}

export function getManualWorkflow(workflowId) {
  return apiClient.get(`/research-engine/manual-workflows/${workflowId}`).then(unwrapResponse)
}

export function startWorkflowRun(workflowId) {
  return apiClient.post(`/research-engine/manual-workflows/${workflowId}/runs`).then(unwrapResponse)
}

export function listWorkflowRuns(params = {}) {
  return apiClient.get('/research-engine/workflow-runs', { params }).then(unwrapResponse)
}

export function getWorkflowRun(workflowRunId) {
  return apiClient.get(`/research-engine/workflow-runs/${workflowRunId}`).then(unwrapResponse)
}

// ── ResearchRun ──

export function createResearchRun(payload) {
  return apiClient.post('/research-engine/research-runs', payload).then(unwrapResponse)
}

export function listResearchRuns(params = {}) {
  return apiClient.get('/research-engine/research-runs', { params }).then(unwrapResponse)
}

export function getResearchRun(runId) {
  return apiClient.get(`/research-engine/research-runs/${runId}`).then(unwrapResponse)
}

export function startResearchRun(runId, payload) {
  return apiClient.post(`/research-engine/research-runs/${runId}/start`, payload).then(unwrapResponse)
}

export function advanceResearchRun(runId, payload) {
  return apiClient.post(`/research-engine/research-runs/${runId}/advance`, payload).then(unwrapResponse)
}

export function pauseResearchRun(runId, payload) {
  return apiClient.post(`/research-engine/research-runs/${runId}/pause`, payload).then(unwrapResponse)
}

export function resumeResearchRun(runId, payload) {
  return apiClient.post(`/research-engine/research-runs/${runId}/resume`, payload).then(unwrapResponse)
}

export function failResearchRun(runId, payload) {
  return apiClient.post(`/research-engine/research-runs/${runId}/fail`, payload).then(unwrapResponse)
}

// ── Stage/Gate 审批 ──

export function approveStage(runId, stageRunId, payload) {
  return apiClient.post(`/research-engine/research-runs/${runId}/stages/${stageRunId}/approve`, payload).then(unwrapResponse)
}

export function rejectStage(runId, stageRunId, payload) {
  return apiClient.post(`/research-engine/research-runs/${runId}/stages/${stageRunId}/reject`, payload).then(unwrapResponse)
}
