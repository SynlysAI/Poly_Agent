import assert from 'node:assert/strict'
import { collectionAnalysisStatusLabel, normalizeCollectionAnalysis } from './dataCatalogAnalysis.js'

const normalized = normalizeCollectionAnalysis({
  total_count: 230,
  field_stats: [{ field: 'Rg2', numeric_summary: null, top_values: null, histogram: null }],
  correlations: null,
  insights: [{ title: '线索', evidence_fields: null }],
})

assert.equal(normalized.total_count, 230)
assert.deepEqual(normalized.field_stats[0].numeric_summary, {})
assert.deepEqual(normalized.field_stats[0].top_values, [])
assert.deepEqual(normalized.correlations, [])
assert.deepEqual(normalized.insights[0].evidence_fields, [])
assert.equal(collectionAnalysisStatusLabel('partial'), '全量计数 + 抽样分析')
assert.equal(collectionAnalysisStatusLabel('unknown'), '未知')

console.log('data catalog analysis tests passed')
