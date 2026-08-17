import assert from 'node:assert/strict'

import {
  COMMAND_CATEGORY_ORDER,
  createCommandOption,
  createPaletteState,
  filterCommandPalette,
  getSlashContext,
  movePaletteHighlight,
  paletteKeyAction,
  resolveCaretPosition,
  resolveCommandSubmission,
} from './slashCommands.mjs'

const commands = [
  {
    name: 'status',
    title: '查看状态',
    description: '查看当前控制状态',
    usage: '/status',
    category: 'system',
    source: 'PolyAgent',
    argument_hint: '',
    available: true,
    risk_level: 'low',
  },
  {
    name: 'plan',
    title: '计划模式',
    description: '限制回答前先制定计划',
    usage: '/plan [message]',
    category: 'agent',
    source: 'DeepSeek Harness 参考',
    argument_hint: '[message]',
    available: true,
    risk_level: 'medium',
    variants: [
      { usage: '/plan', description: '启用计划模式' },
      { usage: '/plan off', description: '退出计划模式' },
    ],
  },
  {
    name: 'run-experiment',
    title: '运行实验',
    description: '执行材料实验工具',
    usage: '/run-experiment',
    category: 'tool',
    source: 'Uploaded algorithm',
    tool_id: 'tool-1',
    available: false,
    unavailable_reason: '当前权限为只读',
    risk_level: 'high',
  },
]

/**
 * 执行 slash 输入纯函数断言。
 */

assert.equal(getSlashContext('/', 1).active, true)
assert.equal(getSlashContext('/pl', 3).query, 'pl')
assert.equal(getSlashContext('/plan off', 9).token, 'off')
assert.equal(getSlashContext('  /PLAN', 7).query, 'PLAN')
assert.equal(getSlashContext('https://example.com/a', 21).active, false)
assert.equal(getSlashContext('路径 /tmp/file 不触发', 14).active, false)
assert.equal(getSlashContext('/home/user/file', 14).active, false)
assert.equal(getSlashContext('/tmp', 4).active, false)
assert.equal(getSlashContext('普通 /plan 不触发', 17).active, false)
assert.equal(getSlashContext('回答\n/plan', 8).query, 'plan')
assert.equal(getSlashContext('/plan\n回答', 8).active, false)
assert.equal(getSlashContext('', 0).active, false)

const options = commands.flatMap((command) => createCommandOption(command))
assert.equal(options.filter((option) => option.commandName === 'plan').length, 2)

const planOptions = filterCommandPalette(commands, 'pl')
assert.deepEqual(
  planOptions.flatMap((group) => group.items.map((item) => item.key)),
  ['plan', 'plan:off'],
)
assert.equal(planOptions[0].category, 'agent')
assert.equal(planOptions[0].items[0].argumentHint, '[message]')
assert.equal(planOptions[0].items[0].source, 'DeepSeek Harness 参考')

const allGroups = filterCommandPalette(commands, '')
assert.deepEqual(
  allGroups.map((group) => group.category),
  ['system', 'agent', 'tool'].filter((category) => COMMAND_CATEGORY_ORDER.includes(category)),
)
assert.deepEqual(
  allGroups.flatMap((group) => group.items.map((item) => item.key)),
  ['status', 'plan', 'plan:off', 'run-experiment'],
)

const unavailable = allGroups
  .flatMap((group) => group.items)
  .find((item) => item.commandName === 'run-experiment')
assert.equal(unavailable.available, false)
assert.equal(unavailable.unavailableReason, '当前权限为只读')
assert.equal(unavailable.riskLevel, 'high')

const fuzzy = filterCommandPalette(commands, 'exper')
assert.deepEqual(
  fuzzy.flatMap((group) => group.items.map((item) => item.key)),
  ['run-experiment'],
)

const offVariant = filterCommandPalette(commands, 'plan off')
assert.deepEqual(
  offVariant.flatMap((group) => group.items.map((item) => item.key)),
  ['plan:off'],
)

assert.equal(movePaletteHighlight(0, 1, 3), 1)
assert.equal(movePaletteHighlight(2, 1, 3), 0)
assert.equal(movePaletteHighlight(0, -1, 3), 2)
assert.equal(movePaletteHighlight(0, 1, 0), -1)

assert.deepEqual(
  paletteKeyAction({ key: 'ArrowDown', isComposing: false }),
  { action: 'move', direction: 1 },
)

assert.equal(resolveCaretPosition('/plan', 3, 1), 1)
assert.equal(resolveCaretPosition('/plan', 0, null), 5)
assert.equal(resolveCaretPosition({ target: { selectionStart: 4 } }, 9, 1), 4)
assert.deepEqual(
  paletteKeyAction({ key: 'Enter', isComposing: false }),
  { action: 'select' },
)
assert.deepEqual(
  paletteKeyAction({ key: 'Enter', isComposing: true }),
  { action: 'default' },
)
assert.deepEqual(
  paletteKeyAction({ key: 'Escape', isComposing: true }),
  { action: 'close' },
)

const state = createPaletteState({ visible: true, highlightedIndex: 1 })
assert.equal(state.visible, true)
assert.equal(state.highlightedIndex, 1)

const known = resolveCommandSubmission('/plan off', commands)
assert.equal(known.isCommand, true)
assert.equal(known.known, true)
assert.equal(known.name, 'plan')
assert.equal(known.rawArgs, ' off')

const unknown = resolveCommandSubmission('/unknown value', commands)
assert.equal(unknown.isCommand, true)
assert.equal(unknown.known, false)
assert.equal(unknown.name, 'unknown')
assert.equal(unknown.rawArgs, ' value')
assert.equal(unknown.error.includes('未知命令'), true)

assert.deepEqual(resolveCommandSubmission('https://example.com/a', commands), {
  isCommand: false,
})
assert.equal(resolveCommandSubmission('/PLAN', commands).name, 'plan')
assert.equal(resolveCommandSubmission('/tmp', commands).isCommand, false)

console.log('slashCommands tests passed')
