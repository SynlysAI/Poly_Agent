import assert from 'node:assert/strict'

import { TOOL_MENU_CATEGORIES, categorizeTool, groupToolsByCategory } from './toolMenuCategories.mjs'

assert.equal(categorizeTool({ algorithm_family: 'vertical_prediction' }), 'vertical')
assert.equal(categorizeTool({ capability_group: 'vertical_algorithm' }), 'vertical')
assert.equal(categorizeTool({ tool_type: 'predictor' }), 'vertical')
assert.equal(categorizeTool({ algorithm_family: 'computation' }), 'compute')
assert.equal(categorizeTool({ tool_type: 'xtb' }), 'compute')
assert.equal(categorizeTool({ tool_type: 'optimizer' }), 'compute')
assert.equal(categorizeTool({ tool_type: 'simulator' }), 'compute')
assert.equal(categorizeTool({ tool_type: 'workflow' }), 'compute')
assert.equal(categorizeTool({ tool_type: 'unknown' }), 'other')
assert.equal(categorizeTool(null), 'other')

const groups = groupToolsByCategory([
  { tool_id: 't1', algorithm_family: 'vertical_prediction' },
  { tool_id: 't2', tool_type: 'xtb' },
  { tool_id: 't3', tool_type: 'retriever' },
])
assert.deepEqual(
  groups.map((item) => [item.key, item.count]),
  [['compute', 1], ['vertical', 1], ['other', 1]],
)
assert.equal(TOOL_MENU_CATEGORIES.length, 3)

console.log('toolMenuCategories tests passed')
