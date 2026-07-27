import assert from 'node:assert/strict'
import { extractGraphKeywords, promptToGraphQuery } from './knowledgeGraphKeywords.mjs'

const keywords = extractGraphKeywords('KrF 248 nm 光刻胶中常用的聚合物树脂有哪些？')
assert.deepEqual(keywords.slice(0, 5), ['KrF', '248', 'nm', '光刻胶', '聚合物'])
assert.equal(promptToGraphQuery('KrF 248 nm 光刻胶中常用的聚合物树脂有哪些？'), 'KrF 248 nm 光刻胶 聚合物 树脂')

assert.deepEqual(
  extractGraphKeywords('如何优化KrF光刻胶的显影工艺以改善线边粗糙度和粘度？', { maxKeywords: 10 }),
  ['优化', 'KrF', '光刻胶', '改善', '显影', '线边粗糙度', '粗糙度', '粘度', '工艺'],
)

assert.deepEqual(
  extractGraphKeywords('What PAG and resin strategies improve KrF lithography sensitivity?', { maxKeywords: 6 }),
  ['PAG', 'resin', 'strategies', 'improve', 'KrF', 'lithography'],
)

assert.equal(promptToGraphQuery('   '), '')

console.log('knowledgeGraphKeywords tests passed')
