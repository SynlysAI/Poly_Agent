import assert from 'node:assert/strict'

import {
  toolHealthClass,
  toolHealthLabel,
  toolRecentSuccessClass,
  toolRecentSuccessText,
  toolRequiresFile,
} from './assistantToolMenu.mjs'

assert.equal(toolHealthLabel('healthy'), '健康')
assert.equal(toolHealthLabel('unknown'), '状态未知')
assert.equal(toolHealthLabel('unavailable'), '不可用')
assert.equal(toolHealthLabel('missing'), '状态未知')
assert.equal(toolHealthClass('healthy'), 'is-healthy')
assert.equal(toolHealthClass('unknown'), 'is-unknown')
assert.equal(toolHealthClass('unavailable'), 'is-unavailable')

assert.equal(toolRequiresFile({ input_assets: [] }), false)
assert.equal(toolRequiresFile({ input_assets: [{ key: 'structure', required: true }] }), true)
assert.equal(toolRequiresFile({ input_assets: [{ key: 'structure', required: false }] }), false)
assert.equal(toolRequiresFile(null), false)

assert.equal(toolRecentSuccessText({ recent_run_count: 0 }), '暂无运行数据')
assert.equal(toolRecentSuccessText({ recent_run_count: 8 }), '暂无成功率')
assert.equal(toolRecentSuccessText({ recent_run_count: 8, recent_success_rate: 0.875 }), '最近成功率 88%')
assert.equal(toolRecentSuccessClass({ recent_run_count: 0 }), 'is-muted')
assert.equal(toolRecentSuccessClass({ recent_run_count: 8, recent_success_rate: 0.9 }), 'is-success')
assert.equal(toolRecentSuccessClass({ recent_run_count: 8, recent_success_rate: 0.7 }), 'is-warning')
assert.equal(toolRecentSuccessClass({ recent_run_count: 8, recent_success_rate: 0.4 }), 'is-danger')

console.log('assistantToolMenu tests passed')
