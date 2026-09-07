import assert from 'node:assert/strict'

import {
  buildReadableTextLines,
  classifyReadableText,
  formatReadableFormula,
  formatReadableTitle,
  isReadableText,
} from './verticalPredictionReadable.mjs'

const thermalFormula = [
  'Risk_thermal = clamp(',
  '0.45 x ((DSC_1 - DSC_20) / DSC_1) +',
  '0.20 x ((DSC_1 - DSC_4) / DSC_1) +',
  '0.35 x (1 - CE_20), 0, 1',
].join('\n')

assert.equal(isReadableText('structured_input.thermal_runaway_formula', thermalFormula), true)
assert.equal(classifyReadableText('structured_input.thermal_runaway_formula', thermalFormula), 'formula')
assert.equal(formatReadableTitle('structured_input.thermal_runaway_formula', 'formula'), '热失控风险评分公式')
assert.equal(formatReadableFormula('0.45 x (1 - CE_20)'), '0.45 × (1 - CE_20)')

const recipe = [
  '推荐配方：REC_T_electrolyte_component_0066',
  '前驱体液配制：20 wt% 单体 PEGDA (SMILES: C=CC(=O)OCCOC(=O)C=C) + 80 wt% 电解液',
  '组装电池：50 μL 前驱体液 + GF 隔膜 + 50 μL 前驱体液 + 锂片',
  '原位聚合：60 ℃ 加热 2 h',
].join('\n')

assert.equal(isReadableText('output.recommended_recipe', recipe), true)
assert.equal(classifyReadableText('output.recommended_recipe', recipe), 'recipe')
assert.equal(formatReadableTitle('output.recommended_recipe', 'recipe'), '推荐配方与组装工艺')

const recipeLines = buildReadableTextLines(recipe)
assert.equal(recipeLines.length, 4)
assert.equal(recipeLines[0].label, '推荐配方')
assert.equal(recipeLines[0].text, 'REC_T_electrolyte_component_0066')
assert.equal(recipeLines[1].label, '前驱体液配制')
assert.equal(recipeLines[1].text.includes('SMILES: C=CC(=O)OCCOC(=O)C=C'), true)

const description = '该配方通过降低第 20 圈放电容量的衰减幅度并提升第 20 圈库仑效率来降低热失控风险，适用于优先评估长循环安全性的配方初筛场景。'
assert.equal(isReadableText('result_summary.description', description), true)
assert.equal(classifyReadableText('result_summary.description', description), 'document')

assert.equal(isReadableText('DSC_1', 78.3), false)
assert.equal(isReadableText('DSC_1', '78.3'), false)

console.log('vertical prediction readable tests passed')
