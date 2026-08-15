import assert from 'node:assert/strict'

import {
  MAX_AUTO_SELECTED_TOOLS,
  queryTerms,
  scoreToolRelevance,
  selectRelevantTools,
  toolSearchableText,
} from './assistantToolAutoSelect.mjs'

const tools = [
  {
    tool_id: 'algorithm:pi_score',
    name: 'PI Score',
    description: '预测聚合物加工指数',
    algorithm_id: 'pi_score',
    material_scope: ['polymer'],
    input_schema: { fields: { smiles: 'string - 聚合物 SMILES' } },
    input_json_schema: { properties: { smiles: { type: 'string', description: '聚合物 SMILES' } } },
  },
  {
    tool_id: 'algorithm:tg_predictor',
    name: 'Tg Predictor',
    description: '预测玻璃化转变温度',
    algorithm_id: 'tg_predictor',
    material_scope: ['polymer'],
    input_schema: { fields: { smiles: 'string - 聚合物 SMILES' } },
    input_json_schema: { properties: { smiles: { type: 'string', description: '聚合物 SMILES' } } },
  },
  {
    tool_id: 'algorithm:drug_adme',
    name: 'ADME Predictor',
    description: '预测小分子吸收分布代谢排泄性质',
    algorithm_id: 'drug_adme',
    material_scope: ['small_molecule'],
    input_schema: { fields: { smiles: 'string - 小分子 SMILES' } },
    input_json_schema: { properties: { smiles: { type: 'string', description: '小分子 SMILES' } } },
  },
]

assert.equal(MAX_AUTO_SELECTED_TOOLS, 5)
assert.equal(toolSearchableText(tools[0]).includes('pi score'), true)
assert.equal(toolSearchableText(tools[0]).includes('聚合物'), true)

const englishTerms = queryTerms('predict polymer tg')
assert.equal(englishTerms.some((item) => item.text === 'predict'), true)
assert.equal(englishTerms.some((item) => item.text === 'polymer'), true)
assert.equal(englishTerms.some((item) => item.text === 'tg'), true)

const chineseTerms = queryTerms('玻璃化温度')
assert.equal(chineseTerms.some((item) => item.text === '玻璃化温度'), true)
assert.equal(chineseTerms.some((item) => item.text === '玻璃'), true)

const tgScore = scoreToolRelevance(tools[1], '预测聚合物玻璃化转变温度')
const admeScore = scoreToolRelevance(tools[2], '预测聚合物玻璃化转变温度')
assert.equal(tgScore.score > 0, true)
assert.equal(admeScore.score < tgScore.score, true)

const selected = selectRelevantTools(tools, '预测聚合物玻璃化转变温度', { max: 2 })
assert.deepEqual(selected.map((item) => item.tool_id), ['algorithm:tg_predictor', 'algorithm:pi_score'])
assert.equal(selected[0].reason.includes('玻璃'), true)

assert.deepEqual(selectRelevantTools(tools, '完全无关的提示'), [])

console.log('assistantToolAutoSelect tests passed')
