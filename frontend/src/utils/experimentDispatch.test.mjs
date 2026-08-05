import assert from 'node:assert/strict'

import {
  autoMatchDispatchMappings,
  buildExperimentDispatchPayload,
  flattenDispatchFields,
  manifestParameterJson,
  valueType,
  parseObjectJson,
} from './experimentDispatch.mjs'

assert.deepEqual(parseObjectJson('{"score": 42}'), { score: 42 })
assert.throws(() => parseObjectJson('[]'), /必须是 JSON 对象/)
assert.throws(() => parseObjectJson('{'), /格式错误/)

const payload = buildExperimentDispatchPayload(
  {
    experimentName: 'PI round 1',
    experimentNotes: 'manual review',
    parametersJson: '{"temperature": 25}',
    selectionInputsJson: '{"difficulty_score": 50}',
    variantId: '',
  },
  { template_id: 'pi_synthesis', template_version: '1.0.0' },
)
assert.deepEqual(payload, {
  template_id: 'pi_synthesis',
  template_version: '1.0.0',
  experiment_name: 'PI round 1',
  experiment_notes: 'manual review',
  selection_inputs: { difficulty_score: 50 },
  parameter_overrides: { temperature: 25 },
  variant_id: null,
})
assert.equal(manifestParameterJson({ parameters: { temperature: 25 } }), '{\n  "temperature": 25\n}')

assert.equal(valueType(1.2), 'number')
assert.equal(valueType({ value: 1 }), 'object')
assert.deepEqual(flattenDispatchFields({ result: { score: 42 }, tags: ['a'] }, '/output'), [
  { path: '/output/result/score', label: 'score', value_type: 'integer', sample: 42 },
  { path: '/output/tags', label: 'tags', value_type: 'array', sample: ['a'] },
])
assert.deepEqual(
  autoMatchDispatchMappings(
    [
      { path: '/payload/score', value_type: 'number' },
      { path: '/payload/name', value_type: 'string' },
    ],
    [
      { path: '/output/prediction/name', value_type: 'string' },
      { path: '/output/score', value_type: 'number' },
      { path: '/output/name', value_type: 'number' },
    ],
  ),
  [
    { target_path: '/payload/score', source_path: '/output/score' },
    { target_path: '/payload/name', source_path: '/output/prediction/name' },
  ],
)

console.log('experiment dispatch utility tests passed')
