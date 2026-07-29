import assert from 'node:assert/strict'

import {
  addFieldToRecords,
  buildArrayObjectSection,
  buildBatchHighlights,
  inferValueKind,
  paginateRows,
  recordTitleField,
  removeFieldFromRecords,
  renameFieldInRecords,
} from './verticalPredictionJson.mjs'

const formulations = [
  { formula_id: 'TEST-001', task_type: 'additive' },
  { formula_id: 'TEST-002', task_type: 'monomer' },
]

const withRatio = addFieldToRecords(formulations, 'additive_mass_ratio', 'number', '1.5')
assert.deepEqual(withRatio.map((item) => item.additive_mass_ratio), [1.5, 1.5])
assert.equal(inferValueKind('electrolyte_component_3_mol_ratio', ['', null]), 'number')
assert.equal(recordTitleField(withRatio[0]), 'formula_id')

const renamed = renameFieldInRecords(withRatio, 'additive_mass_ratio', 'additive_weight_ratio')
assert.equal(renamed[0].additive_weight_ratio, 1.5)
assert.equal('additive_mass_ratio' in renamed[0], false)
assert.throws(
  () => renameFieldInRecords(renamed, 'additive_weight_ratio', 'task_type'),
  /字段已存在/,
)

const removed = removeFieldFromRecords(renamed, 'additive_weight_ratio')
assert.equal('additive_weight_ratio' in removed[0], false)
assert.equal(removed[0].formula_id, 'TEST-001')

const output = {
  results: [
    {
      formula_id: 'TEST-ADDITIVE-001',
      task_type: 'additive',
      predictions: {
        DSC_1: 154.56651078703706,
        DSC_4: 143.94259875661362,
        DSC_20: 143.96517462301588,
        coulombic_efficiency_1: 0.9770074207671966,
        coulombic_efficiency_4: 0.9458165511243389,
        coulombic_efficiency_20: 0.9894630847883596,
      },
      model_name: 'random_forest',
    },
    {
      formula_id: 'TEST-MONOMER-001',
      task_type: 'monomer',
      predictions: {
        DSC_1: 151.83496302368937,
        DSC_4: 140.18535205026444,
        DSC_20: 121.16317160052921,
        coulombic_efficiency_1: 0.9784905062169311,
        coulombic_efficiency_4: 0.9315360927248688,
        coulombic_efficiency_20: 0.96393171468254,
      },
      model_name: 'random_forest',
    },
  ],
}

const section = buildArrayObjectSection('results', output.results)
assert.deepEqual(section.columns, [
  'formula_id',
  'task_type',
  'predictions.DSC_1',
  'predictions.DSC_4',
  'predictions.DSC_20',
  'predictions.coulombic_efficiency_1',
  'predictions.coulombic_efficiency_4',
  'predictions.coulombic_efficiency_20',
  'model_name',
])
assert.equal(section.rows[1]['predictions.coulombic_efficiency_20'], 0.96393171468254)

const highlights = buildBatchHighlights([section])
assert.equal(highlights.length, 7)
assert.equal(highlights.filter((item) => item.caption === '平均值').length, 6)
assert.equal(highlights.some((item) => item.key === 'results.predictions.coulombic_efficiency_20'), true)

const auxiliarySection = buildArrayObjectSection('diagnostics', [
  { model: 'random_forest', elapsed_ms: 18.4 },
  { model: 'random_forest', elapsed_ms: 20.6 },
])
const allHighlights = buildBatchHighlights([section, auxiliarySection])
assert.equal(allHighlights.length, 9)
assert.equal(allHighlights.some((item) => item.key === 'diagnostics.count'), true)
assert.equal(allHighlights.some((item) => item.key === 'diagnostics.elapsed_ms'), true)

const page = paginateRows(Array.from({ length: 45 }, (_, index) => ({ index })), 2, 20)
assert.equal(page.total, 45)
assert.deepEqual(page.rows.map((item) => item.index), Array.from({ length: 20 }, (_, index) => index + 20))

console.log('vertical prediction JSON tests passed')
