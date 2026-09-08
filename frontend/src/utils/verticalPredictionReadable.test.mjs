import assert from 'node:assert/strict'

import {
  buildReadableSections,
  buildReadableTextLines,
  classifyReadableText,
  formatReadableFormula,
  formatReadableTitle,
  isCompactCardValue,
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
assert.equal(
  formatReadableFormula([
    'Risk_thermal = clamp(',
    '0.45 x ((DSC_1 - DSC_20) / DSC_1) +',
    '0.20 x ((DSC_1 - DSC_4) / DSC_1) +',
    '0.35 x (1 - CE_20), 0, 1',
    ')',
  ].join('\n')),
  [
    'Risk_thermal = clamp(',
    '  0.45 × ((DSC_1 - DSC_20) / DSC_1)',
    '  + 0.20 × ((DSC_1 - DSC_4) / DSC_1)',
    '  + 0.35 × (1 - CE_20),',
    '  0, 1',
    ')',
  ].join('\n'),
)
assert.equal(formatReadableFormula('0.45 x (1 - CE_20)'), '0.45 × (1 - CE_20)')

const thermalCompoundExplanation = [
  '【1】热失控风险评分公式：Risk_thermal = clamp(',
  '0.45 x ((DSC_1 - DSC_20) / DSC_1) + 0.20 x ((DSC_1 - DSC_4) / DSC_1) +',
  '0.35 x (1 - CE_20), 0, 1)，其中 CE_20 为第 20 圈预测库伦效率；',
  'clamp(x, 0, 1) 表示将结果限制在 0 到 1 之间。',
  '【2】对应推荐配方 Top1组装工艺：推荐配方：REC_T_electrolyte_component_0066。',
  '【3】前驱体液配制：20 wt% 单体 PEGDA + 80 wt% 电解液。',
].join('\n')

const thermalSections = buildReadableSections(
  'result_summary.explanation',
  thermalCompoundExplanation,
)
assert.equal(thermalSections.length, 4)
assert.equal(thermalSections[0].kind, 'formula')
assert.equal(thermalSections[0].title, '热失控风险评分公式')
assert.equal(formatReadableFormula(thermalSections[0].lines.map((line) => line.text).join('\n')).includes('0.45 ×'), true)
assert.equal(thermalSections[1].kind, 'document')
assert.equal(thermalSections[1].title, '公式变量与边界说明')
assert.equal(thermalSections[2].kind, 'recipe')
assert.equal(thermalSections[2].title, '对应推荐配方 Top1组装工艺')
assert.equal(thermalSections[3].kind, 'recipe')
assert.equal(thermalSections[3].title, '前驱体液配制')

const genericFormula = [
  'predicted_score = weighted_sum(',
  '0.60 x normalized_strength + 0.40 x normalized_stability,',
  '0, 1',
  ')',
].join('\n')

assert.equal(classifyReadableText('output.formula', genericFormula), 'formula')
assert.equal(
  formatReadableFormula(genericFormula),
  [
    'predicted_score = weighted_sum(',
    '  0.60 × normalized_strength',
    '  + 0.40 × normalized_stability,',
    '  0, 1',
    ')',
  ].join('\n'),
)

const markdownSections = buildReadableSections('output.explanation', [
  '## 评分公式',
  genericFormula,
  '## 推荐工艺',
  '推荐配方：REC_GENERIC_COMPONENT',
].join('\n'))
assert.equal(markdownSections.length, 2)
assert.equal(markdownSections[0].kind, 'formula')
assert.equal(markdownSections[0].title, '评分公式')
assert.equal(markdownSections[1].kind, 'recipe')
assert.equal(markdownSections[1].title, '推荐工艺')

const numberedSections = buildReadableSections('output.explanation', [
  '1. 评分公式：predicted_score = weighted_sum(0.60 x a + 0.40 x b, 0, 1)',
  '2. 推荐工艺：60 ℃ 加热 2 h',
].join('\n'))
assert.equal(numberedSections.length, 2)
assert.equal(numberedSections[0].kind, 'formula')
assert.equal(numberedSections[1].kind, 'recipe')

const unsafeSections = buildReadableSections(
  'output.formula',
  'broken_formula = weighted_sum(0.60 x normalized_strength + 0.40 x normalized_stability',
)
assert.equal(unsafeSections.length, 1)
assert.equal(unsafeSections[0].kind, 'document')
assert.equal(unsafeSections[0].lines[0].text.includes('0.60 x'), true)

assert.equal(formatReadableFormula('residual = predict(x) - x'), 'residual = predict(x) - x')

const simpleAssignmentSections = buildReadableSections(
  'output.formula',
  'glass_transition = base_temperature + plasticizer_effect',
)
assert.equal(simpleAssignmentSections.length, 1)
assert.equal(simpleAssignmentSections[0].kind, 'formula')
assert.equal(simpleAssignmentSections[0].lines[0].text, 'glass_transition = base_temperature + plasticizer_effect')

const schemaHintSections = buildReadableSections('output.note', [
  '## 评分公式',
  genericFormula,
  '## 推荐工艺',
  '推荐配方：REC_GENERIC_COMPONENT',
].join('\n'), { kind: 'formula', title: '通用模型评分公式' })
assert.equal(schemaHintSections.length, 2)
assert.equal(schemaHintSections[0].kind, 'formula')
assert.equal(schemaHintSections[0].title, '通用模型评分公式')
assert.equal(schemaHintSections[1].kind, 'recipe')
assert.equal(schemaHintSections[1].title, '推荐工艺')

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

assert.equal(isCompactCardValue(78.3), true)
assert.equal(isCompactCardValue(0.8208), true)
assert.equal(isCompactCardValue(true), true)
assert.equal(isCompactCardValue(false), true)
assert.equal(isCompactCardValue(null), true)
assert.equal(isCompactCardValue('Risk_thermal'), true)
assert.equal(isCompactCardValue('a'.repeat(40)), true)
assert.equal(isCompactCardValue(`   ${'a'.repeat(40)}   `), true)
assert.equal(isCompactCardValue('a'.repeat(41)), false)
assert.equal(isCompactCardValue(''), false)
assert.equal(isCompactCardValue('   '), false)
assert.equal(isCompactCardValue('first line\nsecond line'), false)
assert.equal(isCompactCardValue({ value: 1 }), false)
assert.equal(isCompactCardValue([1, 2]), false)
assert.equal(isCompactCardValue(undefined), false)
assert.equal(isCompactCardValue(thermalFormula), false)
assert.equal(isCompactCardValue(recipe), false)

console.log('vertical prediction readable tests passed')
