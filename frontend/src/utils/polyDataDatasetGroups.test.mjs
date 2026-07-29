import assert from 'node:assert/strict'

import {
  POLY_DATASET_GROUP_ASSIGNMENTS,
  POLY_DATASET_IDS,
  buildPolyDataDatasetGroups,
  polyDataDatasetGroupCount,
  polyDataDatasetGroupKey,
} from './polyDataDatasetGroups.js'

const fixtureDatasets = POLY_DATASET_IDS.map((datasetId) => ({ dataset_id: datasetId, display_name: datasetId }))

const groups = buildPolyDataDatasetGroups(fixtureDatasets)

assert.deepEqual(groups.map((group) => group.label), [
  '结构与分子',
  '模拟与计算',
  '物性与表征',
  '合成与反应',
  '生成与候选',
])

assert.deepEqual(groups.map((group) => group.items.length), [4, 3, 5, 1, 3])
assert.equal(polyDataDatasetGroupCount(fixtureDatasets, 'all'), 16)
assert.equal(polyDataDatasetGroupKey('pi1m_v2'), 'generated')
assert.equal(polyDataDatasetGroupKey({ dataset_id: 'md_allatom' }), 'simulation')
assert.equal(polyDataDatasetGroupKey('unknown_dataset'), '')

assert.equal(new Set(POLY_DATASET_IDS).size, 16)
assert.deepEqual(POLY_DATASET_GROUP_ASSIGNMENTS.structure, ['smipoly', 'toporg', 'polyid', 'nanomine'])
