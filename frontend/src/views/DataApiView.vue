<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Back, Connection, CopyDocument, Document, Download, FolderOpened, Hide, Refresh, Search, View,
} from '@element-plus/icons-vue'

import {
  downloadDataCatalogMinioObject,
  getApiErrorMessage,
  getDataCatalogApiCatalog,
  getResolvedApiBaseUrl,
  listDataCatalogMinioObjects,
  listMdAllatomCFiles,
} from '../api/polyAgentApi'
import { authState } from '../auth/authState'
import AttributionBanner from '../components/attribution/AttributionBanner.vue'
import {
  POLY_DATASET_GROUP_META,
  POLY_DATASET_GROUP_ORDER,
  polyDataDatasetGroupKey,
} from '../utils/polyDataDatasetGroups'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const minioLoading = ref(false)
const mdCLoading = ref(false)
const detailVisible = ref(false)
const selectedEndpoint = ref(null)
const activeExample = ref('curl')
const workbenchTabs = ['endpoints', 'minio', 'md-c-files', 'guide']
const activeWorkbenchTab = ref(workbenchTabs.includes(String(route.query.tab)) ? String(route.query.tab) : 'endpoints')
const sourceFilter = ref('all')
const keyword = ref('')
const activeMinioGroupKey = ref('')
const minioDatasetFilter = ref('')
const minioRoleFilter = ref('')
const downloadingAssetId = ref('')
const showAccessToken = ref(false)
const catalog = ref(null)
const minioObjects = ref([])
const mdCFiles = ref([])
const mdCTotal = ref(0)

const mdCForm = reactive({
  folder: String(route.query.folder || '1_1_16'),
  filename: String(route.query.filename || 'polymer_1_1_16minf.data'),
  keyword: String(route.query.keyword || ''),
  page: Number(route.query.page || 1),
  page_size: 50,
})

const sourceOptions = [
  { value: 'all', label: '全部接口' },
  { value: 'data_catalog', label: '数据目录' },
  { value: 'mongodb', label: 'MongoDB' },
  { value: 'minio', label: 'MinIO' },
]

const endpoints = computed(() => catalog.value?.endpoints || [])
const authHeader = computed(() => catalog.value?.authentication?.header || 'Authorization: Bearer $POLY_AGENT_TOKEN')
const tokenPlaceholder = computed(() => catalog.value?.authentication?.token_placeholder || '$POLY_AGENT_TOKEN')
const readOnlyStatement = computed(
  () => catalog.value?.read_only_statement || '登录后即可读取数据；外部脚本调用时使用登录接口返回的 access_token。',
)
const apiBaseUrl = computed(() => resolveAbsoluteApiBaseUrl())
const selectedEndpointUrl = computed(() => selectedEndpoint.value ? fullEndpointUrl(selectedEndpoint.value) : '')
const selectedEndpointExamples = computed(() => selectedEndpoint.value ? buildFrontendExamples(selectedEndpoint.value) : {})
const authGuideSteps = computed(() => buildAuthGuideSteps())
const currentSessionStatusLabel = computed(() => {
  if (!authState.authEnabled) return '未启用登录保护'
  if (authState.authenticated) return '已登录'
  return '未登录'
})
const currentSessionStatusType = computed(() => {
  if (!authState.authEnabled) return 'info'
  if (authState.authenticated) return 'success'
  return 'warning'
})
const currentSessionAccount = computed(() => {
  if (!authState.authenticated) return '-'
  if (authState.userId === '__portal__') return 'AI4MS 门户'
  return authState.username || '-'
})
const currentSessionRole = computed(() => {
  if (!authState.authenticated) return '-'
  if (authState.userId === '__portal__') return '门户用户'
  return authRoleLabel(authState.role)
})
const currentSessionExpiresAt = computed(() => (
  authState.expiresAt ? formatDate(authState.expiresAt * 1000) : '-'
))
const currentSessionTokenDisplay = computed(() => {
  const token = String(authState.accessToken || '').trim()
  if (!token) return '-'
  return showAccessToken.value ? token : maskToken(token)
})
const currentSessionHasToken = computed(() => authState.authenticated && Boolean(authState.accessToken))
const loginResponseExample = computed(() => compactJson({
  code: 0,
  message: 'ok',
  data: {
    access_token: '<ACCESS_TOKEN>',
    token_type: 'Bearer',
    expires_at: 1795600000,
  },
}))
const tokenUsageExample = computed(() => [
  'export POLY_AGENT_TOKEN="<ACCESS_TOKEN>"',
  `curl -H "Authorization: Bearer $POLY_AGENT_TOKEN" "${apiBaseUrl.value}/data-catalog/overview"`,
].join('\n'))

const minioGroupDefinitions = computed(() => [
  ...POLY_DATASET_GROUP_ORDER.map(key => ({ key, ...POLY_DATASET_GROUP_META[key] })),
  {
    key: 'other',
    label: '其他数据',
    description: '未归入当前 Poly Data 分类的数据文件',
    tone: 'slate',
  },
])

const filteredEndpoints = computed(() => {
  const normalizedKeyword = keyword.value.trim().toLowerCase()
  return endpoints.value.filter((endpoint) => {
    const matchesSource = sourceFilter.value === 'all' || endpoint.source === sourceFilter.value
    const haystack = [
      endpoint.name,
      endpoint.path,
      endpoint.summary,
      endpoint.source,
      endpoint.permission,
    ].join(' ').toLowerCase()
    return matchesSource && (!normalizedKeyword || haystack.includes(normalizedKeyword))
  })
})

const minioGroupOptions = computed(() => {
  const groups = new Map(minioGroupDefinitions.value.map(group => [
    group.key,
    { ...group, total: 0, datasetIds: new Set() },
  ]))
  for (const item of minioObjects.value) {
    const groupKey = minioObjectGroupKey(item)
    const group = groups.get(groupKey) || groups.get('other')
    group.total += 1
    if (item.dataset_id) group.datasetIds.add(item.dataset_id)
  }
  return minioGroupDefinitions.value
    .map((definition) => {
      const group = groups.get(definition.key)
      return {
        ...definition,
        total: group?.total || 0,
        datasetCount: group?.datasetIds.size || 0,
      }
    })
    .filter(group => group.total > 0)
})

const activeMinioGroup = computed(() => (
  minioGroupOptions.value.find(group => group.key === activeMinioGroupKey.value)
  || minioGroupOptions.value[0]
  || null
))

const filteredMinioObjectsByGroup = computed(() => {
  const groupKey = activeMinioGroup.value?.key
  if (!groupKey) return []
  return minioObjects.value.filter(item => minioObjectGroupKey(item) === groupKey)
})

const minioDatasetOptions = computed(() => Array.from(
  new Set(filteredMinioObjectsByGroup.value.map(item => item.dataset_id).filter(Boolean)),
).sort())

const minioRoleOptions = computed(() => Array.from(
  new Set(filteredMinioObjectsByDataset.value.map(item => item.role).filter(Boolean)),
).sort())

const filteredMinioObjectsByDataset = computed(() => {
  if (!minioDatasetFilter.value) return filteredMinioObjectsByGroup.value
  return filteredMinioObjectsByGroup.value.filter(item => item.dataset_id === minioDatasetFilter.value)
})

const filteredMinioObjects = computed(() => {
  if (!minioRoleFilter.value) return filteredMinioObjectsByDataset.value
  return filteredMinioObjectsByDataset.value.filter(item => item.role === minioRoleFilter.value)
})

const groupedMinioObjects = computed(() => {
  const groups = new Map()
  for (const item of filteredMinioObjects.value) {
    const datasetId = item.dataset_id || '未归属数据集'
    const role = item.role || 'other'
    if (!groups.has(datasetId)) {
      groups.set(datasetId, { datasetId, total: 0, roles: new Map() })
    }
    const datasetGroup = groups.get(datasetId)
    datasetGroup.total += 1
    if (!datasetGroup.roles.has(role)) {
      datasetGroup.roles.set(role, { role, items: [] })
    }
    datasetGroup.roles.get(role).items.push(item)
  }
  return Array.from(groups.values())
    .sort((a, b) => a.datasetId.localeCompare(b.datasetId))
    .map(group => ({
      ...group,
      roles: Array.from(group.roles.values()).sort((a, b) => roleLabel(a.role).localeCompare(roleLabel(b.role))),
    }))
})
const detailParameters = computed(() => [
  ...(selectedEndpoint.value?.path_parameters || []),
  ...(selectedEndpoint.value?.query_parameters || []),
])

const loginCurlExample = computed(() => [
  `curl -X POST "${apiBaseUrl.value}/auth/login" \\`,
  '  -H "Content-Type: application/json" \\',
  '  -d \'{"username":"你的账号","password":"你的密码"}\'',
  '',
  `export POLY_AGENT_TOKEN="把返回 data.access_token 粘贴到这里"`,
].join('\n'))
const mdCListCurl = computed(() => [
  `curl -X GET "${mdCListUrl()}" \\`,
  `  -H "Authorization: Bearer ${tokenPlaceholder.value}"`,
].join('\n'))
const mdCDownloadCurl = computed(() => buildMdCDownloadCurl(mdCForm.folder, mdCForm.filename))

function sourceLabel(source) {
  const map = { data_catalog: '数据目录', mongodb: 'MongoDB', minio: 'MinIO' }
  return map[source] || source || '-'
}

function sourceTone(source) {
  const map = { data_catalog: 'primary', mongodb: 'success', minio: 'warning' }
  return map[source] || 'info'
}

function permissionLabel(permission) {
  return permission === 'download' ? '下载' : '只读'
}

function permissionTone(permission) {
  return permission === 'download' ? 'warning' : 'success'
}

function roleLabel(role) {
  const map = {
    readme: '说明文档',
    raw_table: '原始表格',
    requirements_doc: '接入需求',
    raw_file: '原始文件',
    metadata: '元数据',
  }
  return map[role] || role || '其他文件'
}

function authRoleLabel(role) {
  if (role === 'admin') return '管理员'
  if (role === 'user') return '普通用户'
  return role || '-'
}

function maskToken(token) {
  const value = String(token || '').trim()
  if (!value) return '-'
  if (value.length <= 12) return `${value.slice(0, 4)}····`
  return `${value.slice(0, 6)}···${value.slice(-4)}`
}

function minioObjectGroupKey(item) {
  return polyDataDatasetGroupKey(item?.dataset_id) || 'other'
}

function minioGroupName(datasetId, role) {
  return `${datasetId}-${role}`
}

function setWorkbenchTab(tabName) {
  activeWorkbenchTab.value = tabName
}

function openDataManagement() {
  router.push('/database/data-catalog')
}

function selectMinioGroup(groupKey) {
  activeMinioGroupKey.value = groupKey
  minioDatasetFilter.value = ''
  minioRoleFilter.value = ''
}

function formatBytes(value) {
  if (!value) return '-'
  const units = ['B', 'KB', 'MB', 'GB']
  let size = Number(value)
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex += 1
  }
  return `${size.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`
}

function formatDate(value) {
  if (!value) return '-'
  const normalized = typeof value === 'number' && value < 1e12 ? value * 1000 : value
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function cleanQuery(query) {
  const nextQuery = { ...(query || {}) }
  Object.keys(nextQuery).forEach((key) => {
    if (nextQuery[key] === '' || nextQuery[key] === null || nextQuery[key] === undefined) delete nextQuery[key]
  })
  return nextQuery
}

function encodePathSegment(value) {
  return encodeURIComponent(String(value || '').trim())
}

function mdCPageValue() {
  const page = Number(mdCForm.page || 1)
  return Number.isFinite(page) && page > 0 ? Math.floor(page) : 1
}

function mdCPageSizeValue() {
  const pageSize = Number(mdCForm.page_size || 50)
  return Number.isFinite(pageSize) && pageSize > 0 ? Math.floor(pageSize) : 50
}

function mdCListUrl(folder = mdCForm.folder) {
  const params = new URLSearchParams()
  params.set('page', String(mdCPageValue()))
  params.set('page_size', String(mdCPageSizeValue()))
  if (mdCForm.keyword) params.set('keyword', mdCForm.keyword)
  return `${apiBaseUrl.value}/data-catalog/md-allatom/c-files/${encodePathSegment(folder)}?${params.toString()}`
}

function mdCDownloadUrl(folder = mdCForm.folder, filename = mdCForm.filename) {
  return `${apiBaseUrl.value}/data-catalog/md-allatom/c-files/${encodePathSegment(folder)}/${encodePathSegment(filename)}/download`
}

function buildMdCDownloadCurl(folder, filename) {
  const outputName = String(filename || 'md-allatom-c-file.dat').trim() || 'md-allatom-c-file.dat'
  return [
    `curl -L "${mdCDownloadUrl(folder, filename)}" \\`,
    `  -H "Authorization: Bearer ${tokenPlaceholder.value}" \\`,
    `  -o "${outputName}"`,
  ].join('\n')
}

function syncMdCQuery() {
  const query = cleanQuery({
    ...route.query,
    tab: 'md-c-files',
    folder: mdCForm.folder,
    filename: mdCForm.filename,
    keyword: mdCForm.keyword,
    page: mdCPageValue() > 1 ? mdCPageValue() : undefined,
  })
  router.replace({ path: '/database/data-api', query })
}

function syncWorkbenchTabQuery(tabName) {
  router.replace({
    path: '/database/data-api',
    query: cleanQuery({ ...route.query, tab: tabName }),
  })
}

function buildAuthGuideSteps() {
  return [
    {
      title: '登录拿 token',
      description: `用账号密码调用 ${apiBaseUrl.value}/auth/login，先拿到登录响应。`,
    },
    {
      title: '定位 data.access_token',
      description: '在响应 JSON 里复制 data.access_token，它就是后续接口调用要用的 token。',
    },
    {
      title: '放入 Authorization 请求头',
      description: `把 token 写成 Authorization: Bearer ${tokenPlaceholder.value}。`,
    },
    {
      title: '调用接口',
      description: 'curl、Python、JavaScript 都可以复用同一个 token 去请求数据目录接口。',
    },
  ]
}

function compactJson(value) {
  return JSON.stringify(value || {}, null, 2)
}

function normalizeBaseUrl(value) {
  return String(value || '').replace(/\/+$/, '')
}

function resolveAbsoluteApiBaseUrl() {
  const configuredBaseUrl = normalizeBaseUrl(getResolvedApiBaseUrl() || catalog.value?.base_path || '/api/v1')
  if (/^https?:\/\//i.test(configuredBaseUrl)) return configuredBaseUrl
  if (typeof window === 'undefined') return configuredBaseUrl || '/api/v1'
  const normalizedPath = configuredBaseUrl.startsWith('/') ? configuredBaseUrl : `/${configuredBaseUrl}`
  return `${window.location.origin}${normalizedPath}`
}

function fullEndpointUrl(endpoint) {
  return `${apiBaseUrl.value}${endpoint?.path || ''}`
}

function samplePath(path) {
  return String(path || '')
    .replace('{dataset_id}', 'pi1m_v2')
    .replace('{collection_name}', 'poly_data.material_records')
    .replace('{record_id}', 'OPENPOLY-16172')
    .replace('{asset_id}', 'radonpy_pi1070__readme')
}

function sampleQuery(parameters = []) {
  const samples = {
    dataset_id: 'radonpy_pi1070',
    page: 1,
    page_size: 20,
    limit: 5000,
  }
  const pairs = parameters
    .filter(parameter => Object.prototype.hasOwnProperty.call(samples, parameter.name))
    .map(parameter => [parameter.name, samples[parameter.name]])
  return pairs.length ? `?${new URLSearchParams(pairs).toString()}` : ''
}

function fullEndpointSampleUrl(endpoint) {
  return `${apiBaseUrl.value}${samplePath(endpoint?.path)}${sampleQuery(endpoint?.query_parameters || [])}`
}

function buildFrontendExamples(endpoint) {
  const url = fullEndpointSampleUrl(endpoint)
  const isDownload = endpoint?.permission === 'download' || endpoint?.response_type === 'binary stream'
  return {
    curl: [
      `curl -X GET "${url}" \\`,
      `  -H "Authorization: Bearer ${tokenPlaceholder.value}"${isDownload ? ' \\' : ''}`,
      ...(isDownload ? ['  -o data-asset.dat'] : []),
    ].join('\n'),
    python: [
      'import requests',
      '',
      `url = "${url}"`,
      `headers = {"Authorization": "Bearer ${tokenPlaceholder.value}"}`,
      'response = requests.get(url, headers=headers)',
      'response.raise_for_status()',
      isDownload
        ? 'open("data-asset.dat", "wb").write(response.content)'
        : 'print(response.json())',
    ].join('\n'),
    javascript: [
      `const response = await fetch("${url}", {`,
      `  headers: { Authorization: "Bearer ${tokenPlaceholder.value}" },`,
      '});',
      'if (!response.ok) throw new Error(`HTTP ${response.status}`);',
      isDownload
        ? 'const data = await response.blob();'
        : 'const data = await response.json();',
      'console.log(data);',
    ].join('\n'),
  }
}

function openEndpoint(endpoint) {
  selectedEndpoint.value = endpoint
  activeExample.value = 'curl'
  detailVisible.value = true
}

async function copyText(text) {
  if (!text) return
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.setAttribute('readonly', 'readonly')
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
    }
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

async function copyCurrentAccessToken() {
  if (!currentSessionHasToken.value) {
    ElMessage.warning(authState.authEnabled ? '请先登录后再复制 token' : '当前无需登录')
    return
  }
  await copyText(authState.accessToken)
}

function toggleAccessTokenVisibility() {
  showAccessToken.value = !showAccessToken.value
}

function saveBlob(file) {
  const blobUrl = URL.createObjectURL(file.blob)
  const link = document.createElement('a')
  link.href = blobUrl
  link.download = file.filename || 'data-asset.dat'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(blobUrl)
}

async function handleDownload(asset) {
  downloadingAssetId.value = asset.asset_id
  try {
    saveBlob(await downloadDataCatalogMinioObject(asset.asset_id, asset.filename))
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    downloadingAssetId.value = ''
  }
}

async function loadMdCFiles(options = {}) {
  if (!String(mdCForm.folder || '').trim()) {
    ElMessage.warning('请填写 C 类目录')
    return
  }
  if (options.reset) mdCForm.page = 1
  mdCLoading.value = true
  try {
    const data = await listMdAllatomCFiles(mdCForm.folder, {
      page: mdCPageValue(),
      page_size: mdCPageSizeValue(),
      keyword: mdCForm.keyword || undefined,
    })
    mdCFiles.value = data.items || []
    mdCTotal.value = data.total || 0
    syncMdCQuery()
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    mdCLoading.value = false
  }
}

function handleMdCSearch() {
  loadMdCFiles({ reset: true })
}

function handleMdCPageChange(page) {
  mdCForm.page = page
  loadMdCFiles()
}

async function copyMdCDownloadCurl(row) {
  const folder = row?.folder || mdCForm.folder
  const filename = row?.filename || mdCForm.filename
  mdCForm.folder = folder
  mdCForm.filename = filename
  syncMdCQuery()
  await copyText(buildMdCDownloadCurl(folder, filename))
}

async function loadApiCatalog() {
  loading.value = true
  try {
    catalog.value = await getDataCatalogApiCatalog()
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function loadMinioObjects() {
  minioLoading.value = true
  try {
    const data = await listDataCatalogMinioObjects()
    minioObjects.value = data.items || []
    ensureActiveMinioGroup()
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    minioLoading.value = false
  }
}

async function loadData() {
  await Promise.all([loadApiCatalog(), loadMinioObjects()])
}

onMounted(async () => {
  await loadData()
  if (activeWorkbenchTab.value === 'md-c-files') {
    await loadMdCFiles()
  }
})

function ensureActiveMinioGroup() {
  if (!minioGroupOptions.value.length) {
    activeMinioGroupKey.value = ''
    return
  }
  if (!minioGroupOptions.value.some(group => group.key === activeMinioGroupKey.value)) {
    activeMinioGroupKey.value = minioGroupOptions.value[0].key
  }
}

watch(minioGroupOptions, ensureActiveMinioGroup)

watch(activeMinioGroupKey, () => {
  minioDatasetFilter.value = ''
  minioRoleFilter.value = ''
})

watch(minioDatasetFilter, () => {
  minioRoleFilter.value = ''
})

watch(activeWorkbenchTab, (value) => {
  if (!workbenchTabs.includes(value)) return
  if (value === 'md-c-files') {
    syncMdCQuery()
    if (!mdCFiles.value.length) loadMdCFiles()
    return
  }
  syncWorkbenchTabQuery(value)
})
</script>

<template>
  <div class="data-api-page" v-loading="loading">
    <header class="api-header">
      <div>
        <h1>数据调用 API</h1>
        <p>当前数据目录域的只读接口、MongoDB 查询接口和 MinIO 下载接口。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Back" @click="openDataManagement">数据管理</el-button>
        <el-button :icon="Refresh" :loading="loading || minioLoading" @click="loadData">刷新</el-button>
      </div>
    </header>

    <AttributionBanner module-id="data_catalog" label="数据来源" compact />

    <section class="feature-strip" aria-label="数据调用功能">
      <button type="button" @click="openDataManagement">
        <el-icon><Connection /></el-icon>
        <span>页面查询</span>
        <strong>登录后在数据管理页查询记录，权限自动携带。</strong>
      </button>
      <button type="button" @click="setWorkbenchTab('minio')">
        <el-icon><FolderOpened /></el-icon>
        <span>文件下载</span>
        <strong>按分类浏览 MinIO 文件，页面下载走 PolyAgent API。</strong>
      </button>
      <button type="button" @click="setWorkbenchTab('md-c-files')">
        <el-icon><CopyDocument /></el-icon>
        <span>MD C curl</span>
        <strong>按 C 类目录和文件名生成文献文件下载 curl。</strong>
      </button>
      <button type="button" @click="setWorkbenchTab('guide')">
        <el-icon><Document /></el-icon>
        <span>脚本接口</span>
        <strong>外部 curl、Python、JS 使用登录接口返回的 access_token。</strong>
      </button>
    </section>

    <section class="api-workbench">
      <el-tabs v-model="activeWorkbenchTab" class="workbench-tabs">
        <el-tab-pane label="接口调用" name="endpoints">
          <div class="api-toolbar">
            <el-radio-group v-model="sourceFilter" size="small">
              <el-radio-button v-for="option in sourceOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </el-radio-button>
            </el-radio-group>
            <el-input v-model="keyword" clearable class="api-search" placeholder="搜索接口名称、路径或用途">
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
          </div>

          <el-table :data="filteredEndpoints" stripe class="api-table" empty-text="暂无接口">
            <el-table-column label="接口" min-width="220">
              <template #default="{ row }">
                <button type="button" class="endpoint-name" @click="openEndpoint(row)">
                  <strong>{{ row.name }}</strong>
                  <span>{{ row.summary }}</span>
                </button>
              </template>
            </el-table-column>
            <el-table-column label="方法" width="86">
              <template #default="{ row }"><el-tag size="small" type="success">{{ row.method }}</el-tag></template>
            </el-table-column>
            <el-table-column label="路径" min-width="320">
              <template #default="{ row }"><code>{{ row.path }}</code></template>
            </el-table-column>
            <el-table-column label="数据源" width="118">
              <template #default="{ row }"><el-tag size="small" :type="sourceTone(row.source)" effect="plain">{{ sourceLabel(row.source) }}</el-tag></template>
            </el-table-column>
            <el-table-column label="权限" width="106">
              <template #default="{ row }"><el-tag size="small" :type="permissionTone(row.permission)" effect="plain">{{ permissionLabel(row.permission) }}</el-tag></template>
            </el-table-column>
            <el-table-column label="操作" width="96" fixed="right">
              <template #default="{ row }">
                <el-button text type="primary" size="small" :icon="View" @click="openEndpoint(row)">详情</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="MD C curl" name="md-c-files">
          <section class="md-c-call-panel">
            <div class="section-heading md-c-heading">
              <div>
                <h2>MD-AllAtom C 类 curl</h2>
                <p>面向已入库 C 类非结构化文件，按目录和文件名生成 PolyAgent API 调用命令。</p>
              </div>
              <el-tag effect="plain">{{ mdCTotal }} 个文件</el-tag>
            </div>
            <div class="md-c-form-grid">
              <label class="md-c-field">
                <span>C 类目录</span>
                <el-input
                  v-model="mdCForm.folder"
                  clearable
                  placeholder="1_1_16"
                  @keyup.enter="handleMdCSearch"
                />
              </label>
              <label class="md-c-field">
                <span>下载文件名</span>
                <el-input
                  v-model="mdCForm.filename"
                  clearable
                  placeholder="polymer_1_1_16minf.data"
                  @keyup.enter="copyText(mdCDownloadCurl)"
                />
              </label>
              <label class="md-c-field">
                <span>文件名筛选</span>
                <el-input
                  v-model="mdCForm.keyword"
                  clearable
                  placeholder="minf"
                  @keyup.enter="handleMdCSearch"
                >
                  <template #prefix><el-icon><Search /></el-icon></template>
                </el-input>
              </label>
              <div class="md-c-actions">
                <el-button type="primary" :icon="Search" :loading="mdCLoading" @click="handleMdCSearch">查询</el-button>
                <el-button :icon="Refresh" :loading="mdCLoading" @click="loadMdCFiles">刷新</el-button>
              </div>
            </div>
          </section>

          <div class="md-c-curl-grid">
            <section class="guide-panel md-c-curl-panel">
              <h2>列目录 curl</h2>
              <div class="example-toolbar">
                <span>GET list</span>
                <el-button :icon="CopyDocument" @click="copyText(mdCListCurl)">复制</el-button>
              </div>
              <pre class="code-block compact">{{ mdCListCurl }}</pre>
            </section>
            <section class="guide-panel md-c-curl-panel">
              <h2>下载指定文件 curl</h2>
              <div class="example-toolbar">
                <span>GET file stream</span>
                <el-button type="primary" :icon="CopyDocument" @click="copyText(mdCDownloadCurl)">复制</el-button>
              </div>
              <pre class="code-block compact">{{ mdCDownloadCurl }}</pre>
            </section>
          </div>

          <section class="md-c-files-panel">
            <div class="section-heading md-c-heading">
              <div>
                <h2>目录文件</h2>
                <p>表格操作只复制 curl，不在浏览器内发起文件下载。</p>
              </div>
            </div>
            <el-table :data="mdCFiles" v-loading="mdCLoading" stripe class="api-table" empty-text="暂无文件">
              <el-table-column prop="filename" label="文件名" min-width="240">
                <template #default="{ row }"><code>{{ row.filename }}</code></template>
              </el-table-column>
              <el-table-column label="大小" width="118">
                <template #default="{ row }">{{ formatBytes(row.size_bytes) }}</template>
              </el-table-column>
              <el-table-column label="对象状态" width="118">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.exists ? 'success' : 'info'">
                    {{ row.exists ? '对象已就绪' : '对象未就绪' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="同步状态" width="138">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.sync_status === 'uploaded' || row.sync_status === 'already_migrated' || row.sync_status === 'verified' ? 'success' : 'info'" effect="plain">
                    {{ row.sync_status || '-' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="mime_type" label="MIME" min-width="170" />
              <el-table-column label="更新时间" min-width="170">
                <template #default="{ row }">{{ formatDate(row.updated_at) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="148" fixed="right">
                <template #default="{ row }">
                  <el-button text type="primary" size="small" :icon="CopyDocument" @click="copyMdCDownloadCurl(row)">
                    复制下载 curl
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-pagination
              class="md-c-pagination"
              background
              layout="prev, pager, next, total"
              :current-page="mdCForm.page"
              :page-size="mdCForm.page_size"
              :total="mdCTotal"
              @current-change="handleMdCPageChange"
            />
          </section>
        </el-tab-pane>

        <el-tab-pane label="MinIO 文件" name="minio">
          <div class="section-heading minio-heading">
            <div>
              <h2>MinIO 文件</h2>
              <p>按数据分类、数据集和文件类型浏览；下载仍走 PolyAgent API。</p>
            </div>
            <div class="minio-filters">
              <el-select v-model="minioDatasetFilter" clearable placeholder="全部数据集" class="dataset-select">
                <el-option v-for="datasetId in minioDatasetOptions" :key="datasetId" :label="datasetId" :value="datasetId" />
              </el-select>
              <el-select v-model="minioRoleFilter" clearable placeholder="全部文件类型" class="dataset-select">
                <el-option v-for="role in minioRoleOptions" :key="role" :label="roleLabel(role)" :value="role" />
              </el-select>
            </div>
          </div>

          <div v-loading="minioLoading" class="minio-browser-layout">
            <nav v-if="minioGroupOptions.length" class="minio-rail" aria-label="MinIO 数据分类">
              <div class="minio-rail-label">数据分类</div>
              <button
                v-for="group in minioGroupOptions"
                :key="group.key"
                type="button"
                class="minio-filter"
                :class="[`tone-${group.tone}`, { active: activeMinioGroup?.key === group.key }]"
                @click="selectMinioGroup(group.key)"
              >
                <span>{{ group.label }}</span>
                <strong>{{ group.total }}</strong>
              </button>
            </nav>

            <div class="minio-groups">
              <header v-if="activeMinioGroup" class="minio-category-heading" :class="`tone-${activeMinioGroup.tone}`">
                <span class="minio-category-marker" aria-hidden="true"></span>
                <div>
                  <h3>{{ activeMinioGroup.label }}</h3>
                  <p>{{ activeMinioGroup.description }}，共 {{ activeMinioGroup.datasetCount }} 个数据集、{{ activeMinioGroup.total }} 个文件。</p>
                </div>
              </header>
              <el-empty v-if="!groupedMinioObjects.length" description="暂无文件" />
              <section v-for="datasetGroup in groupedMinioObjects" :key="datasetGroup.datasetId" class="minio-dataset-group">
                <div class="minio-dataset-title">
                  <h3>{{ datasetGroup.datasetId }}</h3>
                  <el-tag size="small" effect="plain">{{ datasetGroup.total }} 个文件</el-tag>
                </div>
                <el-collapse class="minio-role-collapse">
                  <el-collapse-item
                    v-for="roleGroup in datasetGroup.roles"
                    :key="minioGroupName(datasetGroup.datasetId, roleGroup.role)"
                    :name="minioGroupName(datasetGroup.datasetId, roleGroup.role)"
                  >
                    <template #title>
                      <span class="role-title">{{ roleLabel(roleGroup.role) }}</span>
                      <el-tag size="small" effect="plain">{{ roleGroup.items.length }}</el-tag>
                    </template>
                    <el-table :data="roleGroup.items" stripe class="minio-table" empty-text="暂无对象">
                      <el-table-column prop="asset_id" label="Asset ID" min-width="220">
                        <template #default="{ row }"><code>{{ row.asset_id }}</code></template>
                      </el-table-column>
                      <el-table-column prop="filename" label="文件名" min-width="180" />
                      <el-table-column label="大小" width="110">
                        <template #default="{ row }">{{ formatBytes(row.size_bytes) }}</template>
                      </el-table-column>
                      <el-table-column label="更新时间" min-width="170">
                        <template #default="{ row }">{{ formatDate(row.last_modified) }}</template>
                      </el-table-column>
                      <el-table-column label="状态" width="100">
                        <template #default="{ row }">
                          <el-tag size="small" :type="row.exists ? 'success' : 'info'">{{ row.exists ? '可下载' : '未就绪' }}</el-tag>
                        </template>
                      </el-table-column>
                      <el-table-column label="操作" width="188" fixed="right">
                        <template #default="{ row }">
                          <div class="minio-action-group">
                            <el-button text type="primary" size="small" :icon="CopyDocument" @click="copyText(row.asset_id)">复制 ID</el-button>
                            <el-button
                              text
                              type="primary"
                              size="small"
                              :icon="Download"
                              :disabled="!row.exists"
                              :loading="downloadingAssetId === row.asset_id"
                              @click="handleDownload(row)"
                            >
                              下载
                            </el-button>
                          </div>
                        </template>
                      </el-table-column>
                    </el-table>
                  </el-collapse-item>
                </el-collapse>
              </section>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="调用说明" name="guide">
          <section class="auth-summary">
            <div>
              <h2>当前会话</h2>
              <p v-if="authState.authEnabled">
                {{ authState.authenticated ? '当前浏览器会话已登录。这里可以直接查看、隐藏和复制 access_token。' : '先登录后，这里会显示当前 access_token。' }}
              </p>
              <p v-else>当前环境未启用登录保护，页面内查询和下载可直接访问；如果后续启用登录，这里会显示 access_token。</p>
            </div>
            <el-tag :type="currentSessionStatusType" effect="plain">{{ currentSessionStatusLabel }}</el-tag>
          </section>
          <section class="session-summary-panel">
            <div class="session-summary-grid">
              <div class="session-summary-item">
                <span>账号</span>
                <strong>{{ currentSessionAccount }}</strong>
              </div>
              <div class="session-summary-item">
                <span>角色</span>
                <strong>{{ currentSessionRole }}</strong>
              </div>
              <div class="session-summary-item">
                <span>Token 类型</span>
                <strong>{{ authState.tokenType || 'Bearer' }}</strong>
              </div>
              <div class="session-summary-item">
                <span>过期时间</span>
                <strong>{{ currentSessionExpiresAt }}</strong>
              </div>
            </div>
            <div class="session-token-card">
              <div class="session-token-header">
                <div>
                  <span>Access token</span>
                  <p>{{ currentSessionHasToken ? '默认隐藏，确认后可查看或复制当前会话 token。' : '登录后会显示当前会话的 access_token。' }}</p>
                </div>
                <div class="session-token-actions">
                  <el-button
                    text
                    size="small"
                    :icon="showAccessToken ? Hide : View"
                    :disabled="!currentSessionHasToken"
                    @click="toggleAccessTokenVisibility"
                  >
                    {{ showAccessToken ? '隐藏' : '查看' }}
                  </el-button>
                  <el-button
                    text
                    size="small"
                    :icon="CopyDocument"
                    :disabled="!currentSessionHasToken"
                    @click="copyCurrentAccessToken"
                  >
                    复制 token
                  </el-button>
                </div>
              </div>
              <code class="session-token-value" :class="{ masked: !showAccessToken }">{{ currentSessionTokenDisplay }}</code>
            </div>
          </section>
          <section class="guide-flow-panel">
            <div class="section-heading guide-flow-heading">
              <div>
                <h2>外部脚本怎么调用</h2>
                <p>顺序很重要：先登录，再找 data.access_token，然后放进请求头，最后发起请求。</p>
              </div>
              <el-tag effect="plain">{{ authHeader }}</el-tag>
            </div>
            <ol class="guide-timeline">
              <li v-for="(step, index) in authGuideSteps" :key="step.title" class="guide-timeline-item">
                <div class="guide-timeline-marker">
                  <span>{{ index + 1 }}</span>
                  <i v-if="index < authGuideSteps.length - 1" class="guide-timeline-line" />
                </div>
                <div class="guide-timeline-content">
                  <strong>{{ step.title }}</strong>
                  <p>{{ step.description }}</p>
                </div>
              </li>
            </ol>
            <div class="guide-api-row">
              <span>当前 API 地址</span>
              <div class="path-copy-row">
                <code>{{ apiBaseUrl }}</code>
                <el-button :icon="CopyDocument" @click="copyText(apiBaseUrl)">复制</el-button>
              </div>
            </div>
          </section>

          <div class="guide-layout">
            <section class="guide-panel">
              <h2>登录拿 token</h2>
              <div class="example-toolbar">
                <span>curl</span>
                <el-button :icon="CopyDocument" @click="copyText(loginCurlExample)">复制</el-button>
              </div>
              <pre class="code-block">{{ loginCurlExample }}</pre>
            </section>
            <section class="guide-panel">
              <h2>登录响应位置</h2>
              <pre class="json-block">{{ loginResponseExample }}</pre>
              <p class="guide-note">复制响应 JSON 中 <code>data.access_token</code> 的值，替换示例里的 <code>&lt;ACCESS_TOKEN&gt;</code> 或设置为 <code>POLY_AGENT_TOKEN</code>。</p>
            </section>
            <section class="guide-panel">
              <h2>放入请求头</h2>
              <div class="example-toolbar">
                <span>shell</span>
                <el-button :icon="CopyDocument" @click="copyText(tokenUsageExample)">复制</el-button>
              </div>
              <pre class="code-block compact">{{ tokenUsageExample }}</pre>
            </section>
          </div>
        </el-tab-pane>
      </el-tabs>
    </section>

    <el-drawer v-model="detailVisible" size="58%" class="api-drawer" title="接口详情">
      <template v-if="selectedEndpoint">
        <div class="drawer-heading">
          <div>
            <h2>{{ selectedEndpoint.name }}</h2>
            <p>{{ selectedEndpoint.summary }}</p>
          </div>
          <div class="drawer-tags">
            <el-tag type="success">{{ selectedEndpoint.method }}</el-tag>
            <el-tag :type="sourceTone(selectedEndpoint.source)" effect="plain">{{ sourceLabel(selectedEndpoint.source) }}</el-tag>
            <el-tag :type="permissionTone(selectedEndpoint.permission)" effect="plain">{{ permissionLabel(selectedEndpoint.permission) }}</el-tag>
          </div>
        </div>

        <div class="path-copy-row">
          <code>{{ selectedEndpointUrl }}</code>
          <el-button :icon="CopyDocument" @click="copyText(selectedEndpointUrl)">复制地址</el-button>
        </div>

        <div class="call-mode-note">
          <div>
            <span>PolyAgent 页面内使用</span>
            <strong>已登录后，数据管理查询和 MinIO 下载会自动带上权限。</strong>
          </div>
          <div>
            <span>外部脚本调用</span>
            <strong>先调用登录接口，从响应 JSON 的 <code>data.access_token</code> 取值并放入 Authorization 请求头。</strong>
          </div>
        </div>

        <div class="call-steps">
          <h3>怎么调用</h3>
          <ol class="guide-timeline guide-timeline--compact">
            <li v-for="(step, index) in authGuideSteps" :key="`${step.title}-drawer`" class="guide-timeline-item">
              <div class="guide-timeline-marker">
                <span>{{ index + 1 }}</span>
                <i v-if="index < authGuideSteps.length - 1" class="guide-timeline-line" />
              </div>
              <div class="guide-timeline-content">
                <strong>{{ step.title }}</strong>
                <p>{{ step.description }}</p>
              </div>
            </li>
          </ol>
          <p v-if="selectedEndpoint.path.includes('{asset_id}')" class="guide-note">这里的 <code>asset_id</code> 可以从 “MinIO 文件” tab 复制。</p>
          <p v-else-if="selectedEndpoint.path.includes('{')" class="guide-note">把路径里的大括号参数替换成参数表里的示例值后，再使用上面的 token 调用。</p>
        </div>

        <h3 class="drawer-section-title">参数</h3>
        <el-table v-if="detailParameters.length" :data="detailParameters" size="small" border>
          <el-table-column prop="name" label="名称" min-width="130" />
          <el-table-column prop="location" label="位置" width="88" />
          <el-table-column label="必填" width="80">
            <template #default="{ row }">{{ row.required ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column prop="type" label="类型" width="100" />
          <el-table-column prop="description" label="说明" min-width="220" />
          <el-table-column label="示例" min-width="140">
            <template #default="{ row }"><code>{{ row.example ?? '-' }}</code></template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="无参数" />

        <h3 class="drawer-section-title">返回格式</h3>
        <div class="response-grid">
          <div>
            <span>Response Type</span>
            <code>{{ selectedEndpoint.response_type }}</code>
            <p v-if="selectedEndpoint.response_type === 'binary stream'">这个接口返回文件内容，保存到本地文件即可，不需要按 JSON 解析。</p>
          </div>
          <pre class="json-block">{{ compactJson(selectedEndpoint.response_example) }}</pre>
        </div>

        <h3 class="drawer-section-title">代码示例</h3>
        <el-tabs v-model="activeExample" class="example-tabs">
          <el-tab-pane v-for="(_, name) in selectedEndpointExamples" :key="name" :label="name" :name="name">
            <div class="example-toolbar">
              <span>{{ name }}</span>
              <el-button :icon="CopyDocument" @click="copyText(selectedEndpointExamples[name])">复制示例</el-button>
            </div>
            <pre class="code-block">{{ selectedEndpointExamples[name] }}</pre>
          </el-tab-pane>
        </el-tabs>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.data-api-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: calc(100vh - 96px);
}

.api-header,
.section-heading,
.drawer-heading,
.api-toolbar,
.example-toolbar,
.path-copy-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.api-header h1,
.section-heading h2,
.drawer-heading h2,
.drawer-section-title {
  margin: 0;
  color: var(--app-ink);
  letter-spacing: 0;
}

.api-header h1 {
  font-size: 24px;
  line-height: 1.2;
}

.api-header p,
.section-heading p,
.drawer-heading p {
  margin: 6px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.header-actions,
.drawer-tags {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.feature-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(190px, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid var(--app-card-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-border-soft);
}

.feature-strip > button {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 2px 12px;
  align-items: center;
  width: 100%;
  min-height: 86px;
  padding: 14px;
  border: 0;
  background: #fff;
  text-align: left;
  cursor: pointer;
}

.feature-strip > button:hover,
.feature-strip > button:focus-visible {
  background: #f8fbff;
}

.feature-strip > button:focus-visible {
  outline: 2px solid var(--app-primary);
  outline-offset: -2px;
}

.feature-strip .el-icon {
  grid-row: 1 / span 2;
  width: 34px;
  height: 34px;
  border-radius: var(--app-radius-sm);
  color: var(--app-primary);
  background: var(--app-primary-light);
}

.feature-strip span {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.feature-strip strong {
  color: var(--app-ink-body);
  font-size: 13px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.api-workbench,
.minio-section {
  padding: 16px;
  border: 1px solid var(--app-card-border);
  border-radius: var(--app-radius-sm);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: var(--app-card-shadow);
}

.workbench-tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
}

.api-toolbar {
  align-items: center;
  margin-bottom: 14px;
}

.api-search {
  max-width: 360px;
}

.api-table,
.minio-table {
  width: 100%;
}

.md-c-call-panel,
.md-c-files-panel {
  min-width: 0;
  margin-bottom: 16px;
  padding: 14px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
}

.md-c-heading {
  align-items: center;
  margin-bottom: 12px;
}

.md-c-form-grid {
  display: grid;
  grid-template-columns: minmax(150px, 0.7fr) minmax(240px, 1fr) minmax(180px, 0.8fr) auto;
  gap: 10px;
  align-items: end;
}

.md-c-field {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 6px;
}

.md-c-field span {
  color: var(--app-ink-muted);
  font-size: 12px;
  font-weight: 600;
}

.md-c-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.md-c-curl-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.md-c-curl-panel {
  min-width: 0;
}

.md-c-files-panel {
  background: #fff;
}

.md-c-pagination {
  margin-top: 14px;
  justify-content: flex-end;
}

.endpoint-name {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.endpoint-name strong {
  color: var(--app-ink);
  font-size: 14px;
}

.endpoint-name span {
  color: var(--app-ink-muted);
  font-size: 12px;
  line-height: 1.4;
}

.dataset-select {
  width: 220px;
}

.minio-heading {
  align-items: center;
  margin-bottom: 12px;
}

.minio-filters {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.minio-browser-layout {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 18px;
  min-height: 260px;
}

.minio-rail {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  padding-right: 14px;
  border-right: 1px solid var(--app-border-soft);
}

.minio-rail-label {
  margin-bottom: 4px;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.minio-filter {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-height: 36px;
  padding: 8px 10px;
  border: 1px solid transparent;
  border-left: 3px solid transparent;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: var(--app-ink-body);
  text-align: left;
  cursor: pointer;
}

.minio-filter:hover,
.minio-filter.active {
  border-color: var(--app-border-soft);
  background: #f8fbff;
}

.minio-filter span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.minio-filter strong {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.minio-filter.tone-blue,
.minio-category-heading.tone-blue {
  border-left-color: #2563eb;
}

.minio-filter.tone-teal,
.minio-category-heading.tone-teal {
  border-left-color: #0f766e;
}

.minio-filter.tone-amber,
.minio-category-heading.tone-amber {
  border-left-color: #d97706;
}

.minio-filter.tone-coral,
.minio-category-heading.tone-coral {
  border-left-color: #be5a35;
}

.minio-filter.tone-violet,
.minio-category-heading.tone-violet {
  border-left-color: #7c3aed;
}

.minio-filter.tone-slate,
.minio-category-heading.tone-slate {
  border-left-color: #64748b;
}

.minio-groups {
  min-height: 220px;
  min-width: 0;
}

.minio-category-heading {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding: 10px 12px;
  border-left: 3px solid var(--app-border);
  background: #f8fbff;
}

.minio-category-heading h3 {
  margin: 0;
  color: var(--app-ink);
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0;
}

.minio-category-heading p {
  margin: 3px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.minio-category-marker {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: currentColor;
}

.minio-dataset-group {
  padding: 16px 0 8px;
  border-top: 1px solid var(--app-border-soft);
}

.minio-dataset-group:first-child {
  border-top: 0;
}

.minio-dataset-title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.minio-dataset-title h3 {
  margin: 0;
  color: var(--app-ink);
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0;
}

.minio-role-collapse {
  padding-left: 6px;
}

.minio-role-collapse :deep(.el-collapse-item__header) {
  min-height: 46px;
  padding-right: 0;
  border-bottom-color: var(--app-border-soft);
  background: transparent;
}

.minio-role-collapse :deep(.el-collapse-item__content) {
  padding-bottom: 12px;
}

.role-title {
  display: inline-flex;
  min-width: 86px;
  margin-right: 8px;
  color: var(--app-ink-body);
  font-size: 13px;
  font-weight: 500;
}

.minio-action-group {
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  gap: 6px;
  min-height: 32px;
  white-space: nowrap;
}

.minio-action-group :deep(.el-button + .el-button) {
  margin-left: 0;
}

.auth-summary,
.call-mode-note {
  display: grid;
  gap: 12px;
  margin-bottom: 16px;
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
}

.auth-summary {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
}

.auth-summary h2 {
  margin: 0;
  color: var(--app-ink);
  font-size: 16px;
  letter-spacing: 0;
}

.auth-summary p {
  margin: 4px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
  line-height: 1.5;
}

.session-summary-panel,
.guide-flow-panel {
  margin-bottom: 16px;
  padding: 14px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
}

.session-summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.session-summary-item {
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #fff;
}

.session-summary-item span,
.session-token-header span,
.guide-api-row > span {
  display: block;
  margin-bottom: 4px;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.session-summary-item strong {
  color: var(--app-ink-body);
  font-size: 13px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.session-token-card {
  margin-top: 12px;
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #fff;
}

.session-token-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.session-token-header p {
  margin: 0;
  color: var(--app-ink-muted);
  font-size: 13px;
  line-height: 1.5;
}

.session-token-actions {
  display: inline-flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.session-token-value {
  display: block;
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #0f172a;
  color: #dbeafe;
  font-family: var(--app-mono-font);
  font-size: 12px;
  line-height: 1.6;
  word-break: break-all;
}

.session-token-value.masked {
  letter-spacing: 0.03em;
}

.guide-flow-panel {
  padding: 14px 16px 12px;
}

.guide-flow-heading {
  margin-bottom: 12px;
}

.guide-flow-heading h2 {
  margin: 0;
}

.guide-flow-heading p {
  margin-top: 4px;
}

.guide-timeline {
  display: flex;
  flex-direction: column;
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}

.guide-timeline-item {
  display: flex;
  gap: 12px;
  min-height: 54px;
}

.guide-timeline-marker {
  width: 30px;
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
  flex: 0 0 auto;
}

.guide-timeline-marker span {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 999px;
  background: var(--app-primary-light);
  color: var(--app-primary);
  font-size: 12px;
  font-weight: 700;
}

.guide-timeline-line {
  flex: 1;
  width: 2px;
  min-height: 20px;
  margin-top: 4px;
  background: #dbe4f0;
}

.guide-timeline-content {
  flex: 1;
  padding-bottom: 12px;
}

.guide-timeline-content strong {
  color: var(--app-ink-body);
  font-size: 13px;
  line-height: 1.45;
}

.guide-timeline-content p {
  margin: 4px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
  line-height: 1.55;
}

.guide-timeline--compact .guide-timeline-item {
  min-height: 46px;
}

.guide-timeline--compact .guide-timeline-marker {
  width: 26px;
}

.guide-timeline--compact .guide-timeline-marker span {
  width: 20px;
  height: 20px;
  font-size: 11px;
}

.guide-timeline--compact .guide-timeline-content {
  padding-bottom: 10px;
}

.guide-api-row {
  margin-top: 12px;
}

.guide-api-row .path-copy-row {
  margin-bottom: 0;
}

.call-mode-note {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.call-mode-note > div {
  min-width: 0;
}

.call-mode-note span {
  display: block;
  margin-bottom: 4px;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.call-mode-note strong {
  color: var(--app-ink-body);
  font-size: 13px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.guide-layout {
  display: grid;
  grid-template-columns: minmax(280px, 1fr) minmax(320px, 1.2fr);
  gap: 18px;
}

.guide-panel {
  min-width: 0;
}

.guide-panel h2,
.call-steps h3 {
  margin: 0 0 10px;
  color: var(--app-ink);
  font-size: 16px;
  letter-spacing: 0;
}

.guide-panel:last-child {
  grid-column: 1 / -1;
  padding-top: 14px;
  border-top: 1px solid var(--app-border-soft);
}

.guide-note {
  margin: 8px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
  line-height: 1.6;
}

.drawer-heading {
  margin-bottom: 14px;
}

.drawer-heading h2 {
  font-size: 18px;
}

.path-copy-row {
  align-items: center;
  margin-bottom: 16px;
  padding: 10px 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
}

.path-copy-row code {
  min-width: 0;
}

.call-steps {
  margin-bottom: 16px;
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
}

.call-steps .guide-note {
  margin-top: 10px;
}

.drawer-section-title {
  margin: 18px 0 10px;
  font-size: 14px;
}

.response-grid {
  display: grid;
  grid-template-columns: minmax(180px, 0.45fr) minmax(0, 1fr);
  gap: 12px;
}

.response-grid > div {
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
}

.response-grid span {
  display: block;
  margin-bottom: 8px;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.response-grid p {
  margin: 10px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
  line-height: 1.5;
}

.json-block,
.code-block {
  overflow: auto;
  margin: 0;
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #0f172a;
  color: #dbeafe;
  font-family: var(--app-mono-font);
  font-size: 12px;
  line-height: 1.55;
}

.json-block {
  max-height: 260px;
}

.code-block {
  min-height: 170px;
  max-height: 360px;
}

.code-block.compact {
  min-height: 96px;
}

.example-toolbar {
  align-items: center;
  margin-bottom: 8px;
  color: var(--app-ink-muted);
  font-size: 13px;
}

code {
  font-family: var(--app-mono-font);
  color: #1e3a8a;
  font-size: 12px;
  word-break: break-all;
}

@media (max-width: 1100px) {
  .feature-strip,
  .call-mode-note,
  .session-summary-grid {
    grid-template-columns: 1fr;
  }

  .response-grid {
    grid-template-columns: 1fr;
  }

  .guide-layout,
  .minio-browser-layout,
  .md-c-form-grid,
  .md-c-curl-grid {
    grid-template-columns: 1fr;
  }

  .md-c-actions {
    justify-content: flex-start;
  }

  .minio-rail {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    padding-right: 0;
    padding-bottom: 12px;
    border-right: 0;
    border-bottom: 1px solid var(--app-border-soft);
  }

  .minio-rail-label {
    grid-column: 1 / -1;
  }
}

@media (max-width: 760px) {
  .api-header,
  .section-heading,
  .drawer-heading,
  .api-toolbar,
  .path-copy-row {
    flex-direction: column;
  }

  .header-actions,
  .drawer-tags,
  .md-c-actions {
    justify-content: flex-start;
  }

  .api-search,
  .dataset-select {
    width: 100%;
    max-width: none;
  }

  .minio-filters {
    width: 100%;
  }

  .md-c-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .auth-summary,
  .minio-rail {
    grid-template-columns: 1fr;
  }
}
</style>
