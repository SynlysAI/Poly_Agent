export const POLY_DATASET_GROUP_ORDER = [
  'structure',
  'simulation',
  'properties',
  'synthesis',
  'generated',
]

export const POLY_DATASET_GROUP_META = {
  structure: { label: '结构与分子', description: '分子、单体与聚合物结构描述', tone: 'blue' },
  simulation: { label: '模拟与计算', description: '分子动力学、量化计算与轨迹结果', tone: 'teal' },
  properties: { label: '物性与表征', description: '热学、电学、溶解性与多性质数据', tone: 'amber' },
  synthesis: { label: '合成与反应', description: '反应条件、产物与结构映射', tone: 'coral' },
  generated: { label: '生成与候选', description: '模型生成的候选单体与聚合物结构', tone: 'violet' },
}

export const POLY_DATASET_GROUP_ASSIGNMENTS = {
  structure: ['smipoly', 'toporg', 'polyid', 'nanomine'],
  simulation: ['radonpy_pi1070', 'md_allatom', 'polyomics'],
  properties: ['openpoly', 'omg_physical_properties', 'polysol', 'pppdb', 'tropic'],
  synthesis: ['omg'],
  generated: ['pi1m_v2', 'polyuniverse', 'polyone'],
}

export const POLY_DATASET_IDS = POLY_DATASET_GROUP_ORDER.flatMap(
  (groupKey) => POLY_DATASET_GROUP_ASSIGNMENTS[groupKey],
)

const DATASET_GROUP_BY_ID = Object.fromEntries(
  Object.entries(POLY_DATASET_GROUP_ASSIGNMENTS).flatMap(([groupKey, datasetIds]) => (
    datasetIds.map((datasetId) => [datasetId, groupKey])
  )),
)

export function polyDataDatasetGroupKey(datasetOrId) {
  const datasetId = typeof datasetOrId === 'string' ? datasetOrId : datasetOrId?.dataset_id
  return DATASET_GROUP_BY_ID[datasetId] || ''
}

export function isPolyDataDataset(datasetOrId) {
  return Boolean(polyDataDatasetGroupKey(datasetOrId))
}

export function buildPolyDataDatasetGroups(datasets, { includeEmpty = false } = {}) {
  const grouped = Object.fromEntries(POLY_DATASET_GROUP_ORDER.map((groupKey) => [groupKey, []]))
  for (const dataset of datasets || []) {
    const groupKey = polyDataDatasetGroupKey(dataset)
    if (groupKey) grouped[groupKey].push(dataset)
  }
  return POLY_DATASET_GROUP_ORDER
    .map((key) => ({ key, ...POLY_DATASET_GROUP_META[key], items: grouped[key] }))
    .filter((group) => includeEmpty || group.items.length)
}

export function polyDataDatasetGroupCount(datasets, groupKey) {
  if (groupKey === 'all') return (datasets || []).filter(isPolyDataDataset).length
  return buildPolyDataDatasetGroups(datasets, { includeEmpty: true })
    .find((group) => group.key === groupKey)?.items.length || 0
}
