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

const conversionSchema = {
  fields: { ratio: 'number', conversion1: 'number', conversion2: 'number' },
  labels: { ratio: '比例', conversion1: '转化率1', conversion2: '转化率2' },
}

const mixedSeparators = parseClipboardTable('比例 转化率1 转化率2\n0.5\t0.9\t0.8\n0.6\t0.85\t0.7', conversionSchema)
assert.deepEqual(mixedSeparators.rows, [
  { ratio: 0.5, conversion1: 0.9, conversion2: 0.8 },
  { ratio: 0.6, conversion1: 0.85, conversion2: 0.7 },
])
assert.deepEqual(mixedSeparators.ignoredColumns, [])
assert.deepEqual(mixedSeparators.missingColumns, [])

const pureData = parseClipboardTable('0.5\t0.9\t0.8\n0.6\t0.85\t0.7', conversionSchema)
assert.deepEqual(pureData.headers, [])
assert.deepEqual(pureData.rows, [
  { ratio: 0.5, conversion1: 0.9, conversion2: 0.8 },
  { ratio: 0.6, conversion1: 0.85, conversion2: 0.7 },
])
assert.deepEqual(pureData.ignoredColumns, [])
assert.deepEqual(pureData.missingColumns, [])

const pureDataMissingColumns = parseClipboardTable('0.5\t0.9\n0.6\t0.85', conversionSchema)
assert.deepEqual(pureDataMissingColumns.rows, [
  { ratio: 0.5, conversion1: 0.9 },
  { ratio: 0.6, conversion1: 0.85 },
])
assert.deepEqual(pureDataMissingColumns.missingColumns, ['conversion2'])

const forcedNoHeader = parseClipboardTable('比例\t转化率1\t转化率2\n0.5\t0.9\t0.8', conversionSchema, { hasHeader: 'no' })
assert.deepEqual(forcedNoHeader.rows, [
  { ratio: '比例', conversion1: '转化率1', conversion2: '转化率2' },
  { ratio: 0.5, conversion1: 0.9, conversion2: 0.8 },
])

const forcedHeader = parseClipboardTable('unknown\textra\n2.5\tignored', schema, { hasHeader: 'yes' })
assert.deepEqual(forcedHeader.rows, [])
assert.deepEqual(forcedHeader.ignoredColumns, ['unknown', 'extra'])
assert.deepEqual(forcedHeader.missingColumns, ['ratio', 'enabled', 'note'])

assert.deepEqual(
  mergeRowsBySchema([{ ratio: 9 }], [{ ratio: 1, unknown: 'x' }], schema),
  [{ ratio: 9 }, { ratio: 1 }],
)
assert.deepEqual(mergeRowsBySchema([{ ratio: 9 }], [{ ratio: 1 }], schema, 'replace'), [{ ratio: 1 }])
assert.equal(serializeRowsForClipboard([{ ratio: 1, enabled: true }], ['ratio', 'enabled']), 'ratio\tenabled\n1\ttrue')

console.log('verticalPredictionInputTable tests passed')
