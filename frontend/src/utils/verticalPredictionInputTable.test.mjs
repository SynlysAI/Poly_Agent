import assert from 'node:assert/strict'

import {
  coerceClipboardValue,
  mergeRowsBySchema,
  parseClipboardTable,
  serializeRowsForClipboard,
} from './verticalPredictionInputTable.mjs'

const schema = {
  fields: { ratio: 'number', enabled: 'boolean', note: 'string' },
  labels: { ratio: '比例', enabled: '启用', note: '备注' },
}

assert.equal(coerceClipboardValue('2.53%', 'number'), '2.53%')
assert.equal(coerceClipboardValue('2.53', 'number'), 2.53)
assert.equal(coerceClipboardValue('是', 'boolean'), true)
assert.equal(coerceClipboardValue('否', 'boolean'), false)

const parsed = parseClipboardTable('ratio\tenabled\tnote\textra\n2.5\t是\tfirst\tignored\n3\t否\tsecond\tignored', schema)
assert.deepEqual(parsed.rows, [
  { ratio: 2.5, enabled: true, note: 'first' },
  { ratio: 3, enabled: false, note: 'second' },
])
assert.deepEqual(parsed.ignoredColumns, ['extra'])
assert.deepEqual(parsed.missingColumns, [])

const csv = parseClipboardTable('ratio,enabled,note\n4.2,true,third', schema)
assert.deepEqual(csv.rows, [{ ratio: 4.2, enabled: true, note: 'third' }])

const labeled = parseClipboardTable('比例\t启用\t备注\n5.5\t是\t中文表头', schema)
assert.deepEqual(labeled.rows, [{ ratio: 5.5, enabled: true, note: '中文表头' }])

const withBlankRow = parseClipboardTable('ratio\tenabled\tnote\n\t\t\n6\t是\t', schema)
assert.deepEqual(withBlankRow.rows, [{ ratio: 6, enabled: true, note: '' }])

assert.deepEqual(
  mergeRowsBySchema([{ ratio: 9 }], [{ ratio: 1, unknown: 'x' }], schema),
  [{ ratio: 9 }, { ratio: 1 }],
)
assert.deepEqual(mergeRowsBySchema([{ ratio: 9 }], [{ ratio: 1 }], schema, 'replace'), [{ ratio: 1 }])
assert.equal(serializeRowsForClipboard([{ ratio: 1, enabled: true }], ['ratio', 'enabled']), 'ratio\tenabled\n1\ttrue')

console.log('verticalPredictionInputTable tests passed')
