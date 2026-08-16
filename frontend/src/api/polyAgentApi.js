import axios from 'axios'

import { clearAuthSession, getAuthorizationHeader } from '../auth/authState'
import {
  handleUnauthorizedResponse,
  emitAuthExpired,
} from '../utils/apiAuth.mjs'
import { resolveAlgorithmRunTimeoutMs } from '../utils/apiTimeout.mjs'

const resolvedBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'
const HIDDEN_KNOWLEDGE_SYSTEM_IDS = new Set([
  'agirent_welding',
  'agirent_rare_earth',
  'agirent_surface_treatment',
])
const HIDDEN_KNOWLEDGE_SYSTEM_MARKERS = ['安捷睿']

const apiClient = axios.create({
  baseURL: resolvedBaseUrl,
  timeout: 60000,
})

const SHARED_READ_CACHE_TTL_MS = 30_000
const sharedReadCache = new Map()

/**
 * 缓存短时间内不会频繁变化的只读接口，避免首页与问答页重复请求。
 *
 * Args:
 *   cacheKey: 缓存键。
 *   loader: 未命中缓存或缓存过期时执行的数据加载函数。
 *
 * Returns:
 *   缓存结果或新加载结果的 Promise。
 */
function cachedReadRequest(cacheKey, loader) {
  const cached = sharedReadCache.get(cacheKey)
  const now = Date.now()
  if (cached && now - cached.createdAt < SHARED_READ_CACHE_TTL_MS) {
    return Promise.resolve(cached.value)
  }
  if (cached?.promise) {
    return cached.promise
  }
  const promise = Promise.resolve()
    .then(loader)
    .then((value) => {
      sharedReadCache.set(cacheKey, { createdAt: Date.now(), value })
      return value
    })
    .catch((error) => {
      sharedReadCache.delete(cacheKey)
      throw error
    })
  sharedReadCache.set(cacheKey, { createdAt: now, promise })
  return promise
}

export function getResolvedApiBaseUrl() {
  return resolvedBaseUrl
}

export function generateRequestId() {
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
    if (status === 401) emitAuthExpired(clearAuthSession)
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

/**
 * 生成算法运行 / 接口测试请求的 axios 配置。
 *
 * Args:
 *   timeoutSeconds: 算法契约中的 runtime.timeout_seconds。
 *
 * Returns:
 *   包含动态 timeout 的 axios 请求配置。
 */
function algorithmRunRequestConfig(timeoutSeconds) {
  return { timeout: resolveAlgorithmRunTimeoutMs(timeoutSeconds) }
}

/**
 * 将 fetch 错误响应转换为统一 API 错误，并处理 401 登录失效。
 *
 * Args:
 *   response: fetch 返回的 Response 对象。
 *
 * Returns:
 *   带 HTTP 状态码的 API 错误对象。
 */
async function createFetchApiError(response) {
  handleUnauthorizedResponse(response, clearAuthSession)
  let message = `HTTP ${response.status}`
  try {
    const data = await response.json()
    message = (
      data?.data?.detail ||
      data?.detail ||
      data?.message ||
      message
    )
  } catch {
    // Keep the HTTP status when the response is not JSON.
  }
  const error = createApiError('http', typeof message === 'string' ? message : JSON.stringify(message))
  error.status = response.status
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

function isHiddenKnowledgeSystem(system) {
  const corpusId = String(system?.corpus_id || system?.system_id || '').trim()
  const name = String(system?.name || '').trim()
  const tags = Array.isArray(system?.tags) ? system.tags.map((tag) => String(tag || '').trim()) : []
  if (HIDDEN_KNOWLEDGE_SYSTEM_IDS.has(corpusId)) {
    return true
  }
  const searchableText = [corpusId, name, ...tags].join(' ')
  return HIDDEN_KNOWLEDGE_SYSTEM_MARKERS.some((marker) => searchableText.includes(marker))
}

function filterVisibleKnowledgeSystems(data) {
  const items = Array.isArray(data?.items) ? data.items.filter((item) => !isHiddenKnowledgeSystem(item)) : []
  return {
    ...(data || {}),
    items,
    total: items.length,
  }
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

export { getApiErrorMessage } from '../utils/apiErrorMessage.js'

export function getApiBaseUrl() {
  return resolvedBaseUrl
}

// ── 来源与引用标注 API ──

export function listModuleAttributions() {
  return apiClient.get('/attributions/modules').then(unwrapResponse)
}

export function getModuleAttribution(moduleId) {
  return apiClient.get(`/attributions/modules/${encodeURIComponent(moduleId)}`).then(unwrapResponse)
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

export function listGlobalTasks(params = {}) {
  return apiClient.get('/tasks/center', { params }).then(unwrapResponse)
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

export function listCapabilities() {
  return apiClient.get('/capabilities').then(unwrapResponse)
}

// ── 数据目录 API ──

export function getDataCatalogOverview() {
  return apiClient.get('/data-catalog/overview').then(unwrapResponse)
}

export function getDataCatalogApiCatalog() {
  return apiClient.get('/data-catalog/api-catalog').then(unwrapResponse)
}

export function listDataCatalogDatasets() {
  return apiClient.get('/data-catalog/datasets').then(unwrapResponse)
}

export function getDataCatalogDatasetProfile(datasetId) {
  return apiClient.get(`/data-catalog/datasets/${encodeURIComponent(datasetId)}/profile`).then(unwrapResponse)
}

export function listDataCatalogDatasetRecords(datasetId, params = {}) {
  return apiClient.get(`/data-catalog/datasets/${encodeURIComponent(datasetId)}/records`, { params }).then(unwrapResponse)
}

export function getDataCatalogDatasetVisualSamples(datasetId, params = {}) {
  return apiClient.get(`/data-catalog/datasets/${encodeURIComponent(datasetId)}/visual-samples`, { params }).then(unwrapResponse)
}

export function listDataCatalogMongoCollections() {
  return apiClient.get('/data-catalog/mongo-collections').then(unwrapResponse)
}

export function getDataCatalogRelationships() {
  return apiClient.get('/data-catalog/relationships').then(unwrapResponse)
}

export function listDataCatalogMinioObjects(params = {}) {
  return apiClient.get('/data-catalog/minio-objects', { params }).then(unwrapResponse)
}

export function downloadDataCatalogMinioObject(assetId, fallbackName = 'data-asset.dat') {
  return apiClient
    .get(`/data-catalog/minio-objects/${encodeURIComponent(assetId)}/download`, { responseType: 'blob' })
    .then((response) => ({
      blob: response.data,
      filename: parseDownloadFilename(response.headers['content-disposition'], fallbackName),
      contentType: response.headers['content-type'] || 'application/octet-stream',
    }))
}

export function listMdAllatomCFiles(folder, params = {}) {
  return apiClient
    .get(`/data-catalog/md-allatom/c-files/${encodeURIComponent(folder)}`, { params })
    .then(unwrapResponse)
}

export function downloadMdAllatomCFile(folder, filename, fallbackName = 'md-allatom-c-file.dat') {
  return apiClient
    .get(
      `/data-catalog/md-allatom/c-files/${encodeURIComponent(folder)}/${encodeURIComponent(filename)}/download`,
      { responseType: 'blob' },
    )
    .then((response) => ({
      blob: response.data,
      filename: parseDownloadFilename(response.headers['content-disposition'], fallbackName),
      contentType: response.headers['content-type'] || 'application/octet-stream',
    }))
}

export function listDataCatalogCollectionRecords(collectionName, params = {}) {
  return apiClient.get(`/data-catalog/mongo-collections/${encodeURIComponent(collectionName)}/records`, { params }).then(unwrapResponse)
}

export function getDataCatalogCollectionAnalysis(collectionName, params = {}) {
  return apiClient.get(`/data-catalog/mongo-collections/${encodeURIComponent(collectionName)}/analysis`, { params }).then(unwrapResponse)
}

export function getDataCatalogCollectionRecord(collectionName, recordId) {
  return apiClient.get(`/data-catalog/mongo-collections/${encodeURIComponent(collectionName)}/records/${encodeURIComponent(recordId)}`).then(unwrapResponse)
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

// ── Knowledge Base API ──

export function listKnowledgeSystems() {
  return cachedReadRequest('knowledge-systems', () =>
    apiClient.get('/knowledge-bases/systems').then(unwrapResponse).then(filterVisibleKnowledgeSystems),
  )
}

export function getKnowledgeHealth() {
  return apiClient.get('/knowledge-bases/health').then(unwrapResponse).then((data) => {
    if (!data) {
      return data
    }
    const visibleSystems = filterVisibleKnowledgeSystems({ items: data.systems || [] }).items
    return {
      ...data,
      systems: visibleSystems,
    }
  })
}

export function queryKnowledgeBase(payload) {
  return apiClient.post('/knowledge-bases/query', payload).then(unwrapResponse)
}

export function generateKnowledgeSuggestions(systemId) {
  return apiClient.post(`/knowledge-bases/${encodeURIComponent(systemId)}/suggested-questions`).then(unwrapResponse)
}

export async function streamKnowledgeQuery(payload, onEvent) {
  const headers = { 'Content-Type': 'application/json', 'X-Request-Id': generateRequestId() }
  const authHeader = getAuthorizationHeader()
  if (authHeader) headers.Authorization = authHeader
  const response = await fetch(`${resolvedBaseUrl}/knowledge-bases/query/stream`, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw await createFetchApiError(response)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (line.trim()) onEvent(JSON.parse(line))
    }
    if (done) break
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer))
}

export function getKnowledgeGraph(systemId) {
  return apiClient.get(`/knowledge-bases/${systemId}/graph`).then(unwrapResponse)
}

export function getKnowledgeSubgraph(systemId, params = {}) {
  return apiClient.get(`/knowledge-bases/${systemId}/graph/subgraph`, { params }).then(unwrapResponse)
}

// ── LLM API ──

/** 通用对话接口 */
export function chatWithLLM(messages) {
  return apiClient.post('/llm/chat', { messages }).then(r => r.data)
}

export async function streamAssistantChat(payload, onEvent) {
  const headers = { 'Content-Type': 'application/json', 'X-Request-Id': generateRequestId() }
  const authHeader = getAuthorizationHeader()
  if (authHeader) headers.Authorization = authHeader
  const response = await fetch(`${resolvedBaseUrl}/assistant/chat/stream`, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw await createFetchApiError(response)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    const events = buffer.split('\n\n')
    buffer = events.pop() || ''
    for (const rawEvent of events) {
      const dataLines = rawEvent
        .split('\n')
        .filter((line) => line.startsWith('data: '))
        .map((line) => line.slice(6))
      if (dataLines.length) onEvent(JSON.parse(dataLines.join('\n')))
    }
    if (done) break
  }
  if (buffer.trim()) {
    const dataLines = buffer
      .split('\n')
      .filter((line) => line.startsWith('data: '))
      .map((line) => line.slice(6))
    if (dataLines.length) onEvent(JSON.parse(dataLines.join('\n')))
  }
}

/** LLM 辅助实验建议 */
export function suggestExperiments(payload) {
  return apiClient.post('/llm/suggest-experiments', payload).then(r => r.data)
}

/** 可选 LLM 模型目录 */
export function getLlmModels() {
  return cachedReadRequest('llm-models', () => apiClient.get('/llm/models').then(unwrapResponse))
}

/** 刷新 LLM 模型健康状态 */
export function checkLlmModels() {
  return apiClient.post('/llm/models/check').then(unwrapResponse)
}

/** 获取 LLM 默认路由 */
export function getLlmRouting() {
  return apiClient.get('/llm/routing').then(unwrapResponse)
}

/** 更新 LLM 默认路由 */
export function updateLlmRouting(payload) {
  return apiClient.put('/llm/routing', payload).then(unwrapResponse)
}

/** LLM provider 配置字段说明目录 */
export function getLlmConfigSchema() {
  return apiClient.get('/llm/config-schema').then(unwrapResponse)
}

/** LUI 调用质量指标 */
export function getAssistantQualityMetrics() {
  return apiClient.get('/assistant/quality-metrics/summary').then(unwrapResponse)
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

export function archiveProblemSpec(problemSpecId, payload = {}) {
  return apiClient.post(`/research-engine/problem-specs/${problemSpecId}:archive`, payload).then(unwrapResponse)
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

export function createAlgorithmInterface(payload) {
  return apiClient.post('/research-engine/algorithm-interfaces', payload).then(unwrapResponse)
}

export function createAlgorithmInterfaceVersion(algorithmId, payload) {
  return apiClient.post(`/research-engine/algorithm-interfaces/${algorithmId}/versions`, payload).then(unwrapResponse)
}

export function updateAlgorithmInterfaceVersion(algorithmId, versionId, payload) {
  return apiClient.patch(`/research-engine/algorithm-interfaces/${algorithmId}/versions/${versionId}`, payload).then(unwrapResponse)
}

export function listAlgorithmInterfaces(params = {}) {
  return apiClient.get('/research-engine/algorithm-interfaces', { params }).then(unwrapResponse)
}

export function getAlgorithmInterface(algorithmId) {
  return apiClient.get(`/research-engine/algorithm-interfaces/${algorithmId}`).then(unwrapResponse)
}

export function testAlgorithmInterface(algorithmId, versionId, inputSnapshot = null, options = {}) {
  const payload = inputSnapshot ? { input_snapshot: inputSnapshot } : undefined
  return apiClient
    .post(
      `/research-engine/algorithm-interfaces/${algorithmId}/versions/${versionId}:test`,
      payload,
      algorithmRunRequestConfig(options.timeoutSeconds),
    )
    .then(unwrapResponse)
}

export function testAlgorithmInterfaceMultipart(algorithmId, versionId, inputSnapshot = {}, files = {}, options = {}) {
  const formData = new FormData()
  formData.append('input_snapshot', JSON.stringify(inputSnapshot || {}))
  Object.entries(files || {}).forEach(([key, file]) => {
    if (file) formData.append(key, file)
  })
  return apiClient
    .post(
      `/research-engine/algorithm-interfaces/${algorithmId}/versions/${versionId}:test-multipart`,
      formData,
      algorithmRunRequestConfig(options.timeoutSeconds),
    )
    .then(unwrapResponse)
}

export function getAlgorithmIdAvailability(algorithmId) {
  return apiClient.get('/research-engine/algorithms/id-availability', { params: { algorithm_id: algorithmId } }).then(unwrapResponse)
}

export function deleteAlgorithm(algorithmId, confirmAlgorithmId) {
  return apiClient.delete(`/research-engine/algorithms/${encodeURIComponent(algorithmId)}`, { params: { confirm_algorithm_id: confirmAlgorithmId } }).then(unwrapResponse)
}

export function activateAlgorithmInterfaceVersion(algorithmId, versionId) {
  return apiClient.post(`/research-engine/algorithm-interfaces/${algorithmId}/versions/${versionId}:activate`).then(unwrapResponse)
}

export function getAlgorithm(algorithmId) {
  return apiClient.get(`/research-engine/algorithms/${algorithmId}`).then(unwrapResponse)
}

export function updateAlgorithmMetadata(algorithmId, payload) {
  return apiClient.patch(`/research-engine/algorithms/${algorithmId}/metadata`, payload).then(unwrapResponse)
}

export function getAlgorithmCreditSummary(algorithmId) {
  return apiClient.get(`/research-engine/algorithms/${algorithmId}/credit-summary`).then(unwrapResponse)
}

export function downloadAlgorithmPackageTemplate() {
  return apiClient
    .get('/research-engine/algorithm-packages/template', { responseType: 'blob' })
    .then((response) => ({
      blob: response.data,
      filename: parseDownloadFilename(response.headers['content-disposition'], 'polyagent-algorithm-template.zip'),
      contentType: response.headers['content-type'] || 'application/zip',
    }))
}

export function downloadAlgorithmRequirementDocumentTemplate() {
  return apiClient
    .get('/research-engine/algorithm-requirement-docs/template', { responseType: 'blob' })
    .then((response) => ({
      blob: response.data,
      filename: parseDownloadFilename(response.headers['content-disposition'], 'PolyAgent_模型数据集成需求收集_填写模板.docx'),
      contentType: response.headers['content-type'] || 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    }))
}

export function parseAlgorithmRequirementDocument(formData) {
  return apiClient.post('/research-engine/algorithm-requirement-docs:parse', formData).then(unwrapResponse)
}

export function createAlgorithmResource(payload) {
  return apiClient.post('/research-engine/algorithm-resources', payload).then(unwrapResponse)
}

export function listAlgorithmResources(params = {}) {
  return apiClient.get('/research-engine/algorithm-resources', { params }).then(unwrapResponse)
}

export function checkAlgorithmResource(resourceId) {
  return apiClient.post(`/research-engine/algorithm-resources/${resourceId}:check`).then(unwrapResponse)
}

export function listAlgorithmPackageExamples() {
  return apiClient.get('/research-engine/algorithm-package-examples').then(unwrapResponse)
}

export function downloadAlgorithmPackageExample(exampleId, fallbackName = 'algorithm-example.zip') {
  return apiClient
    .get(`/research-engine/algorithm-package-examples/${exampleId}/download`, { responseType: 'blob' })
    .then((response) => ({
      blob: response.data,
      filename: parseDownloadFilename(response.headers['content-disposition'], fallbackName),
      contentType: response.headers['content-type'] || 'application/zip',
    }))
}

export function createAlgorithmHandoff(payload) {
  return apiClient.post('/research-engine/algorithm-handoffs', payload).then(unwrapResponse)
}

export function listAlgorithmHandoffs(params = {}) {
  return apiClient.get('/research-engine/algorithm-handoffs', { params }).then(unwrapResponse)
}

export function getAlgorithmHandoff(handoffId) {
  return apiClient.get(`/research-engine/algorithm-handoffs/${handoffId}`).then(unwrapResponse)
}

export function downloadAlgorithmHandoffPackage(handoffId, fallbackName = 'algorithm-handoff.zip') {
  return apiClient
    .get(`/research-engine/algorithm-handoffs/${handoffId}/package`, { responseType: 'blob' })
    .then((response) => ({
      blob: response.data,
      filename: parseDownloadFilename(response.headers['content-disposition'], fallbackName),
      contentType: response.headers['content-type'] || 'application/zip',
    }))
}

export function validateAlgorithmHandoffPackage(handoffId, formData) {
  return apiClient.post(`/research-engine/algorithm-handoffs/${handoffId}:validate`, formData).then(unwrapResponse)
}

export function markAlgorithmHandoffSubmitted(handoffId) {
  return apiClient.post(`/research-engine/algorithm-handoffs/${handoffId}:submit`).then(unwrapResponse)
}

export function packAlgorithmPackage(formData) {
  return apiClient.post('/research-engine/algorithm-packages:pack', formData).then(unwrapResponse)
}

export function packAlgorithmVersionPackage(formData) {
  return apiClient.post('/research-engine/algorithm-packages:pack-version', formData).then(unwrapResponse)
}

export function inspectAlgorithmPackage(formData) {
  return apiClient.post('/research-engine/algorithm-packages:inspect', formData).then(unwrapResponse)
}

export function uploadAlgorithmPackage(formData) {
  return apiClient.post('/research-engine/algorithm-packages', formData).then(unwrapResponse)
}

export function getAlgorithmPackage(packageId) {
  return apiClient.get(`/research-engine/algorithm-packages/${packageId}`).then(unwrapResponse)
}

export function listAlgorithmPackages(params = {}) {
  return apiClient.get('/research-engine/algorithm-packages', { params }).then(unwrapResponse)
}

export function downloadAlgorithmPackage(packageId, fallbackName = 'algorithm-package.zip') {
  return apiClient
    .get(`/research-engine/algorithm-packages/${packageId}/download`, { responseType: 'blob' })
    .then((response) => ({
      blob: response.data,
      filename: parseDownloadFilename(response.headers['content-disposition'], fallbackName),
      contentType: response.headers['content-type'] || 'application/zip',
    }))
}

export function validateAlgorithmPackage(packageId, resourceBindings = []) {
  const payload = resourceBindings.length ? { resource_bindings: resourceBindings } : undefined
  return apiClient.post(`/research-engine/algorithm-packages/${packageId}:validate`, payload).then(unwrapResponse)
}

export function buildAlgorithmPackage(packageId) {
  return apiClient.post(`/research-engine/algorithm-packages/${packageId}:build`).then(unwrapResponse)
}

export function releaseAlgorithmPackage(packageId, resourceBindings = []) {
  const payload = resourceBindings.length ? { resource_bindings: resourceBindings } : undefined
  return apiClient.post(`/research-engine/algorithm-packages/${packageId}:release`, payload).then(unwrapResponse)
}

export function listAlgorithmVersions(algorithmId, params = {}) {
  return apiClient.get(`/research-engine/algorithms/${algorithmId}/versions`, { params }).then(unwrapResponse)
}

export function deployAlgorithmVersion(algorithmId, versionId) {
  return apiClient.post(`/research-engine/algorithms/${algorithmId}/versions/${versionId}:deploy`).then(unwrapResponse)
}

export function redeployAlgorithmVersion(algorithmId, versionId) {
  return apiClient.post(`/research-engine/algorithms/${algorithmId}/versions/${versionId}:redeploy`).then(unwrapResponse)
}

export function getAlgorithmVersionHealth(algorithmId, versionId) {
  return apiClient.get(`/research-engine/algorithms/${algorithmId}/versions/${versionId}/health`).then(unwrapResponse)
}

export function getAlgorithmVersionLogs(algorithmId, versionId) {
  return apiClient.get(`/research-engine/algorithms/${algorithmId}/versions/${versionId}/logs`).then(unwrapResponse)
}

export function activateAlgorithmVersion(algorithmId, versionId) {
  return apiClient.post(`/research-engine/algorithms/${algorithmId}/versions/${versionId}:activate`).then(unwrapResponse)
}

export function rollbackAlgorithmVersion(algorithmId, versionId) {
  return apiClient.post(`/research-engine/algorithms/${algorithmId}/versions/${versionId}:rollback`).then(unwrapResponse)
}

export function freezeAlgorithmVersion(algorithmId, versionId) {
  return apiClient.post(`/research-engine/algorithms/${algorithmId}/versions/${versionId}:freeze`).then(unwrapResponse)
}

export function decommissionAlgorithmVersion(algorithmId, versionId) {
  return apiClient.post(`/research-engine/algorithms/${algorithmId}/versions/${versionId}:decommission`).then(unwrapResponse)
}

export function deleteAlgorithmVersion(algorithmId, versionId) {
  return apiClient.delete(`/research-engine/algorithms/${algorithmId}/versions/${versionId}`).then(unwrapResponse)
}

// ── ResearchEngine Examples ──

export function listResearchEngineExamples() {
  return apiClient.get('/research-engine/examples').then(unwrapResponse)
}

export function instantiateResearchEngineExample(exampleId) {
  return apiClient.post(`/research-engine/examples/${exampleId}/instantiate`).then(unwrapResponse)
}

// ── AlgorithmRun ──

export function createAlgorithmRun(payload, options = {}) {
  return apiClient
    .post('/research-engine/algorithm-runs', payload, algorithmRunRequestConfig(options.timeoutSeconds))
    .then(unwrapResponse)
}

export function createAlgorithmRunMultipart(payload, files = {}, options = {}) {
  const formData = new FormData()
  formData.append('payload', JSON.stringify(payload))
  Object.entries(files).forEach(([key, file]) => {
    if (file) formData.append(key, file)
  })
  return apiClient
    .post('/research-engine/algorithm-runs:multipart', formData, algorithmRunRequestConfig(options.timeoutSeconds))
    .then(unwrapResponse)
}

export function listAlgorithmRuns(params = {}) {
  return apiClient.get('/research-engine/algorithm-runs', { params }).then(unwrapResponse)
}

export function getAlgorithmRun(runId) {
  return apiClient.get(`/research-engine/algorithm-runs/${runId}`).then(unwrapResponse)
}

export function getAlgorithmRunTraceability(runId) {
  return apiClient.get(`/research-engine/algorithm-runs/${runId}/traceability`).then(unwrapResponse)
}

export function listAlgorithmRunArtifacts(runId) {
  return apiClient.get(`/research-engine/algorithm-runs/${runId}/artifacts`).then(unwrapResponse)
}

// ── 实验方案转发 ──

export function listExperimentTemplates() {
  return apiClient.get('/experiment-templates').then(unwrapResponse)
}

export function listExperimentDispatchProfiles(params = {}) {
  return apiClient.get('/experiment-dispatch-profiles', { params }).then(unwrapResponse)
}

export function getExperimentDispatchProfile(profileId, version = null) {
  return apiClient.get(`/experiment-dispatch-profiles/${encodeURIComponent(profileId)}`, {
    params: version ? { version } : {},
  }).then(unwrapResponse)
}

export function createExperimentDispatchProfile(payload) {
  return apiClient.post('/experiment-dispatch-profiles', payload).then(unwrapResponse)
}

export function updateExperimentDispatchProfile(profileId, version, payload) {
  return apiClient.patch(`/experiment-dispatch-profiles/${encodeURIComponent(profileId)}/versions/${encodeURIComponent(version)}`, payload).then(unwrapResponse)
}

export function publishExperimentDispatchProfile(profileId, version) {
  return apiClient.post(`/experiment-dispatch-profiles/${encodeURIComponent(profileId)}/versions/${encodeURIComponent(version)}/publication`).then(unwrapResponse)
}

export function cloneExperimentDispatchProfile(profileId, version, nextVersion) {
  return apiClient.post(`/experiment-dispatch-profiles/${encodeURIComponent(profileId)}/versions/${encodeURIComponent(version)}/copies`, { version: nextVersion }).then(unwrapResponse)
}

export function updateExperimentDispatchProfileVisibility(profileId, version, visibility) {
  return apiClient.patch(`/experiment-dispatch-profiles/${encodeURIComponent(profileId)}/versions/${encodeURIComponent(version)}/visibility`, { visibility }).then(unwrapResponse)
}

export function listExperimentDispatchTargets() {
  return apiClient.get('/experiment-dispatch-targets').then(unwrapResponse)
}

export function listExperimentDispatchCandidates(params = {}) {
  return apiClient.get('/experiment-dispatch-candidates', { params }).then(unwrapResponse)
}

export function evaluateExperimentDispatchProfile(payload) {
  return apiClient.post('/experiment-dispatch-profile-evaluations', payload).then(unwrapResponse)
}

export function saveProfileExperimentDispatch(payload) {
  return apiClient.post('/experiment-dispatches', payload).then(unwrapResponse)
}

export function previewExperimentDispatch(runId, payload) {
  return apiClient.post(`/algorithm-runs/${encodeURIComponent(runId)}/experiment-dispatches/preview`, payload).then(unwrapResponse)
}

export function createExperimentDispatch(runId, payload) {
  return apiClient.post(`/algorithm-runs/${encodeURIComponent(runId)}/experiment-dispatches`, payload).then(unwrapResponse)
}

export function listExperimentDispatches(params = {}) {
  return apiClient.get('/experiment-dispatches', { params }).then(unwrapResponse)
}

export function getExperimentDispatch(dispatchId) {
  return apiClient.get(`/experiment-dispatches/${encodeURIComponent(dispatchId)}`).then(unwrapResponse)
}

export function downloadExperimentDispatch(dispatchId) {
  return apiClient
    .get(`/experiment-dispatches/${encodeURIComponent(dispatchId)}/export`, { responseType: 'blob' })
    .then((response) => ({
      blob: response.data,
      filename: parseDownloadFilename(response.headers['content-disposition'], `${dispatchId}.json`),
      contentType: response.headers['content-type'] || 'application/json',
    }))
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

export function archiveManualWorkflow(workflowId, payload = {}) {
  return apiClient.post(`/research-engine/manual-workflows/${workflowId}:archive`, payload).then(unwrapResponse)
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

export function getResearchEngineReadiness() {
  return apiClient.get('/research-engine/readiness').then(unwrapResponse)
}

export function listResearchRuns(params = {}) {
  return apiClient.get('/research-engine/research-runs', { params }).then(unwrapResponse)
}

export function getResearchRun(runId) {
  return apiClient.get(`/research-engine/research-runs/${runId}`).then(unwrapResponse)
}

export function archiveResearchRun(runId, payload = {}) {
  return apiClient.post(`/research-engine/research-runs/${runId}:archive`, payload).then(unwrapResponse)
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

export function getResearchRunTraceability(runId) {
  return apiClient.get(`/research-engine/research-runs/${runId}/traceability`).then(unwrapResponse)
}

export function getStageRunTraceability(runId, stageRunId) {
  return apiClient.get(`/research-engine/research-runs/${runId}/stages/${stageRunId}/traceability`).then(unwrapResponse)
}

// ── Report Generation API ──

export function getReportReadiness() {
  return apiClient.get('/reports/readiness').then(unwrapResponse)
}

export function createReport(payload) {
  return apiClient.post('/reports', payload).then(unwrapResponse)
}

export function getReport(reportId) {
  return apiClient.get(`/reports/${encodeURIComponent(reportId)}`).then(unwrapResponse)
}

export function getReportPreview(reportId) {
  return apiClient.get(`/reports/${encodeURIComponent(reportId)}/preview`).then(unwrapResponse)
}

export function listReports(params = {}) {
  return apiClient.get('/reports', { params }).then(unwrapResponse)
}

export function cancelReport(reportId) {
  return apiClient.post(`/reports/${encodeURIComponent(reportId)}/cancel`).then(unwrapResponse)
}

export function retryReport(reportId) {
  return apiClient.post(`/reports/${encodeURIComponent(reportId)}/retry`).then(unwrapResponse)
}

export function downloadReportArtifact(reportId, artifactId, fallbackName = 'report.dat') {
  return apiClient
    .get(`/reports/${encodeURIComponent(reportId)}/artifacts/${encodeURIComponent(artifactId)}/download`, { responseType: 'blob' })
    .then((response) => ({
      blob: response.data,
      filename: parseDownloadFilename(response.headers['content-disposition'], fallbackName),
      contentType: response.headers['content-type'] || 'application/octet-stream',
    }))
}

// ── Structured Assistant API ──

export function listAssistantChats(params = {}) {
  return apiClient.get('/assistant/chats', { params }).then(unwrapResponse)
}

export function listAssistantChatSummaries(params = {}) {
  return apiClient.get('/assistant/chat-summaries', { params }).then(unwrapResponse)
}

export function createAssistantChat(payload = {}) {
  return apiClient.post('/assistant/chats', payload).then(unwrapResponse)
}

export function getAssistantChat(chatId) {
  return apiClient.get(`/assistant/chats/${encodeURIComponent(chatId)}`).then(unwrapResponse)
}

export function updateAssistantChat(chatId, payload) {
  return apiClient.patch(`/assistant/chats/${encodeURIComponent(chatId)}`, payload).then(unwrapResponse)
}

export function deleteAssistantChat(chatId) {
  return apiClient.delete(`/assistant/chats/${encodeURIComponent(chatId)}`).then(unwrapResponse)
}

export function listAssistantMessages(chatId, params = {}) {
  return apiClient.get(`/assistant/chats/${encodeURIComponent(chatId)}/messages`, { params }).then(unwrapResponse)
}

export function createAssistantMessage(chatId, payload) {
  return apiClient.post(`/assistant/chats/${encodeURIComponent(chatId)}/messages`, payload).then(unwrapResponse)
}

export function createAssistantRun(chatId, payload) {
  return apiClient.post(`/assistant/chats/${encodeURIComponent(chatId)}/runs`, payload).then(unwrapResponse)
}

export function listAssistantRuns(chatId, params = {}) {
  return apiClient.get(`/assistant/chats/${encodeURIComponent(chatId)}/runs`, { params }).then(unwrapResponse)
}

export function getAssistantRun(runId) {
  return apiClient.get(`/assistant/runs/${encodeURIComponent(runId)}`).then(unwrapResponse)
}

export function getActiveAssistantRun() {
  return apiClient.get('/assistant/runs-active/current').then(unwrapResponse)
}

export function cancelAssistantRun(runId) {
  return apiClient.post(`/assistant/runs/${encodeURIComponent(runId)}/cancel`).then(unwrapResponse)
}

export async function streamAssistantRunEvents(runId, afterSeq, onEvent, signal) {
  const headers = { 'X-Request-Id': generateRequestId() }
  const authHeader = getAuthorizationHeader()
  if (authHeader) headers.Authorization = authHeader
  const params = new URLSearchParams({ after_seq: String(Math.max(0, afterSeq || 0)) })
  const response = await fetch(`${resolvedBaseUrl}/assistant/runs/${encodeURIComponent(runId)}/events?${params}`, {
    method: 'GET',
    headers,
    signal,
  })
  if (!response.ok) {
    throw await createFetchApiError(response)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    const events = buffer.split('\n\n')
    buffer = events.pop() || ''
    for (const rawEvent of events) {
      const dataLines = rawEvent.split('\n').filter((line) => line.startsWith('data: ')).map((line) => line.slice(6))
      if (dataLines.length) onEvent(JSON.parse(dataLines.join('\n')))
    }
    if (done) break
  }
  if (buffer.trim()) {
    const dataLines = buffer.split('\n').filter((line) => line.startsWith('data: ')).map((line) => line.slice(6))
    if (dataLines.length) onEvent(JSON.parse(dataLines.join('\n')))
  }
}

export function updateAssistantMessage(chatId, messageId, payload) {
  return apiClient.patch(
    `/assistant/chats/${encodeURIComponent(chatId)}/messages/${encodeURIComponent(messageId)}`,
    payload,
  ).then(unwrapResponse)
}

export function deleteAssistantMessage(chatId, messageId) {
  return apiClient.delete(
    `/assistant/chats/${encodeURIComponent(chatId)}/messages/${encodeURIComponent(messageId)}`,
  ).then(unwrapResponse)
}

export function chatWithAssistant(payload) {
  return apiClient.post('/assistant/chat', payload).then(unwrapResponse)
}

// ── 算法工具目录与调用 API ──

export function listAgentTools() {
  return cachedReadRequest('agent-tools', () => apiClient.get('/agent-tools').then(unwrapResponse))
}

export function listAgentToolRegistry() {
  return apiClient.get('/agent-tools/registry').then(unwrapResponse)
}

export function updateAgentToolPolicy(algorithmId, payload) {
  return apiClient.patch(`/agent-tools/${encodeURIComponent(algorithmId)}/policy`, payload).then(unwrapResponse)
}

export function syncAgentTools() {
  return apiClient.post('/agent-tools/sync').then(unwrapResponse)
}

export function createAssistantToolCall(payload) {
  return apiClient.post('/assistant/tool-calls', payload).then(unwrapResponse)
}

export function getAssistantToolCall(callId) {
  return apiClient.get(`/assistant/tool-calls/${encodeURIComponent(callId)}`).then(unwrapResponse)
}

export function updateAssistantToolCallInput(callId, payload) {
  return apiClient.patch(`/assistant/tool-calls/${encodeURIComponent(callId)}/input`, payload).then(unwrapResponse)
}

export function uploadAssistantToolCallInput(callId, formData) {
  return apiClient
    .post(`/assistant/tool-calls/${encodeURIComponent(callId)}/input:multipart`, formData)
    .then(unwrapResponse)
}

export function confirmAssistantToolCall(callId, payload = {}) {
  return apiClient.post(`/assistant/tool-calls/${encodeURIComponent(callId)}/confirm`, payload).then(unwrapResponse)
}

export function cancelAssistantToolCall(callId) {
  return apiClient.post(`/assistant/tool-calls/${encodeURIComponent(callId)}/cancel`).then(unwrapResponse)
}

export async function streamAssistantToolCallEvents(callId, onEvent) {
  const headers = { 'X-Request-Id': generateRequestId() }
  const authHeader = getAuthorizationHeader()
  if (authHeader) headers.Authorization = authHeader
  const response = await fetch(`${resolvedBaseUrl}/assistant/tool-calls/${encodeURIComponent(callId)}/events`, {
    method: 'GET',
    headers,
  })
  if (!response.ok) {
    throw await createFetchApiError(response)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    const events = buffer.split('\n\n')
    buffer = events.pop() || ''
    for (const rawEvent of events) {
      const dataLines = rawEvent
        .split('\n')
        .filter((line) => line.startsWith('data: '))
        .map((line) => line.slice(6))
      if (dataLines.length) onEvent(JSON.parse(dataLines.join('\n')))
    }
    if (done) break
  }
}
