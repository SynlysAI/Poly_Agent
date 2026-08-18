/** Slash Command 输入、过滤与面板交互的纯函数集合。 */

export const COMMAND_CATEGORY_ORDER = ['system', 'agent', 'skill', 'tool', 'custom']

export const COMMAND_CATEGORY_LABELS = {
  system: 'System',
  agent: 'Agent',
  skill: 'Skills',
  tool: 'Tools',
  custom: 'Custom',
}

const COMMAND_NAME_PATTERN = /^[a-z][a-z0-9_-]*$/i
const UNIX_PATH_ROOTS = new Set([
  'bin', 'dev', 'etc', 'home', 'lib', 'media', 'mnt', 'opt', 'proc', 'root', 'sbin', 'tmp', 'usr', 'var',
])

/**
 * 判断命令 token 是否更像单段 Unix 路径。
 *
 * Args:
 *   token: slash 后的第一个空白分隔 token。
 *
 * Returns:
 *   常见文件系统根下的单段路径返回 true。
 */
function isUnixPathToken(token) {
  return UNIX_PATH_ROOTS.has(token.toLowerCase())
}

/**
 * 获取光标所在行的 slash 输入上下文。
 *
 * Args:
 *   text: composer 的完整文本。
 *   caretPosition: textarea 当前光标位置。
 *
 * Returns:
 *   active 表示是否应打开命令面板；query 是 slash 后到光标前的输入；
 *   token 是最后一个空白分隔 token，用于高亮当前输入片段。
 */
export function getSlashContext(text, caretPosition = 0) {
  const value = String(text || '')
  const caret = Math.min(Math.max(Number(caretPosition) || 0, 0), value.length)
  const lineStart = value.lastIndexOf('\n', Math.max(caret - 1, 0)) + 1
  const nextBreak = value.indexOf('\n', lineStart)
  const lineEnd = nextBreak >= 0 ? nextBreak : value.length
  const line = value.slice(lineStart, caret)
  const slashOffset = line.search(/\S/)

  if (slashOffset < 0 || line[slashOffset] !== '/') return { active: false, query: '', token: '' }

  const query = line.slice(slashOffset + 1)
  if (query.includes('/')) return { active: false, query: '', token: '' }

  const commandPart = query.split(/\s+/)[0] || ''
  if (commandPart && (!COMMAND_NAME_PATTERN.test(commandPart) || isUnixPathToken(commandPart))) {
    return { active: false, query: '', token: '' }
  }

  const tokens = query.split(/\s+/).filter(Boolean)
  return {
    active: true,
    query,
    token: tokens[tokens.length - 1] || '',
    lineStart,
    lineEnd,
    slashOffset: lineStart + slashOffset,
  }
}

/**
 * 把命令 descriptor 展开为面板可渲染选项。
 *
 * Args:
 *   command: 后端返回的 handler-free 命令 descriptor。
 *
 * Returns:
 *   该命令的基础选项与各 variant 选项数组。
 */
export function createCommandOption(command) {
  const descriptor = command || {}
  const base = {
    key: descriptor.name || '',
    commandName: descriptor.name || '',
    title: descriptor.title || descriptor.name || '',
    description: descriptor.description || '',
    usage: descriptor.usage || `/${descriptor.name || ''}`,
    argumentHint: descriptor.argument_hint || '',
    category: descriptor.category || 'custom',
    categoryLabel: COMMAND_CATEGORY_LABELS[descriptor.category] || 'Custom',
    source: descriptor.source || '',
    sourceKind: descriptor.source_kind || '',
    available: descriptor.available !== false,
    enabled: descriptor.enabled !== false,
    unavailableReason: descriptor.unavailable_reason || '',
    inputMode: descriptor.input_mode || 'none',
    riskLevel: descriptor.risk_level || 'low',
    requiresConfirmation: Boolean(descriptor.requires_confirmation),
    toolId: descriptor.tool_id || '',
    choices: descriptor.choices || [],
    attributions: descriptor.attributions || [],
  }
  const variants = Array.isArray(descriptor.variants) ? descriptor.variants : []
  return [
    base,
    ...variants.filter((variant) => variant.usage !== `/${base.commandName}`).map((variant) => ({
      ...base,
      key: variant.usage?.startsWith(`/${base.commandName} `)
        ? `${base.commandName}:${variant.usage.slice(base.commandName.length + 2)}`
        : `${base.commandName}:${variant.usage || ''}`,
      usage: variant.usage || base.usage,
      description: variant.description || base.description,
      argumentHint: variant.usage?.startsWith('/')
        ? variant.usage.slice(1).slice(base.commandName.length).trim()
        : base.argumentHint,
    })),
  ]
}

/**
 * 计算命令选项与当前过滤词的匹配分数。
 *
 * Args:
 *   option: 面板命令选项。
 *   query: slash 后的过滤词。
 *
 * Returns:
 *   分数越高排序越靠前；0 表示不匹配。
 */
function commandMatchScore(option, query) {
  const normalizedQuery = query.trim().toLowerCase()
  if (!normalizedQuery) return 1

  const variantQuery = option.usage.slice(1).toLowerCase()
  if (variantQuery === normalizedQuery) return 500
  if (variantQuery.startsWith(normalizedQuery)) return 400

  const name = option.commandName.toLowerCase()
  if (name.startsWith(normalizedQuery)) return 300
  if (name.includes(normalizedQuery)) return 250

  const haystack = `${option.commandName} ${option.title}`.toLowerCase()
  if (haystack.includes(normalizedQuery)) return 180

  const queryStart = haystack.indexOf(normalizedQuery[0])
  if (queryStart < 0) return 0
  let cursor = queryStart
  for (const character of normalizedQuery) {
    cursor = haystack.indexOf(character, cursor)
    if (cursor < 0) return 0
    cursor += 1
  }
  return 100 - queryStart
}

/**
 * 根据当前 slash 输入过滤并分组命令。
 *
 * Args:
 *   commands: 后端命令 descriptor 数组。
 *   query: slash 后的原始输入。
 *
 * Returns:
 *   按 System → Agent → Skills → Tools → Custom 排序的分组结果。
 */
export function filterCommandPalette(commands, query = '') {
  const options = (Array.isArray(commands) ? commands : []).flatMap((command) => createCommandOption(command))
  const matched = options
    .map((option) => ({ option, score: commandMatchScore(option, String(query || '')) }))
    .filter((item) => item.score > 0)
    .sort((left, right) => right.score - left.score
      || left.option.commandName.localeCompare(right.option.commandName)
      || left.option.usage.localeCompare(right.option.usage))
    .map((item) => item.option)

  return COMMAND_CATEGORY_ORDER
    .map((category) => ({
      category,
      categoryLabel: COMMAND_CATEGORY_LABELS[category],
      items: matched.filter((item) => item.category === category),
    }))
    .filter((group) => group.items.length > 0)
}

/**
 * 创建命令面板的纯 UI 状态。
 *
 * Args:
 *   overrides: 需要覆盖的默认面板状态。
 *
 * Returns:
 *   面板可见性、高亮位置与加载错误状态。
 */
export function createPaletteState(overrides = {}) {
  return {
    visible: false,
    highlightedIndex: 0,
    query: '',
    loading: false,
    error: '',
    ...overrides,
  }
}

/**
 * 计算循环移动后的高亮索引。
 *
 * Args:
 *   currentIndex: 当前高亮索引。
 *   direction: 1 表示向下，-1 表示向上。
 *   itemCount: 可选项数量。
 *
 * Returns:
 *   下一个高亮索引；无选项时返回 -1。
 */
export function movePaletteHighlight(currentIndex, direction, itemCount) {
  if (!itemCount || itemCount <= 0) return -1
  const current = Number.isInteger(currentIndex) && currentIndex >= 0 && currentIndex < itemCount
    ? currentIndex
    : 0
  return (current + direction + itemCount) % itemCount
}

/**
 * 归一化原生事件与 Element Plus input 字符串事件中的光标位置。
 *
 * Args:
 *   event: 原生事件、数字或 Element Plus emit 的输入字符串。
 *   fallback: 无法解析时使用的兜底位置。
 *   nativeSelectionStart: 组件实例暴露的原生 textarea selectionStart。
 *
 * Returns:
 *   可用于 slash 检测的光标位置。
 */
export function resolveCaretPosition(event, fallback = 0, nativeSelectionStart = null) {
  if (typeof event === 'number') return event
  if (typeof event === 'string') return nativeSelectionStart ?? event.length
  const eventPosition = event?.target?.selectionStart
  if (typeof eventPosition === 'number') return eventPosition
  return nativeSelectionStart ?? fallback
}

/**
 * 把键盘事件归约为面板动作，避免组件直接理解浏览器差异。
 *
 * Args:
 *   event: 包含 key 与 isComposing 的键盘事件快照。
 *
 * Returns:
 *   move、select、close 或 default 动作；IME 组合期间的 Enter 保持 default。
 */
export function paletteKeyAction(event) {
  const key = event?.key || ''
  const composing = Boolean(event?.isComposing || event?.keyCode === 229)
  if (key === 'Escape') return { action: 'close' }
  if (composing) return { action: 'default' }
  if (key === 'ArrowDown') return { action: 'move', direction: 1 }
  if (key === 'ArrowUp') return { action: 'move', direction: -1 }
  if (key === 'Enter') return { action: 'select' }
  return { action: 'default' }
}

/**
 * 判断提交文本是否为命令，并在本地识别未知命令。
 *
 * Args:
 *   text: 用户提交的完整文本。
 *   commands: 当前命令 descriptor 数组。
 *
 * Returns:
 *   非 slash 输入返回 isCommand=false；slash 输入返回规范化名称、
 *   原样参数与是否已在目录中。
 */
export function resolveCommandSubmission(text, commands = []) {
  const value = String(text || '')
  const stripped = value.replace(/^\s+/, '')
  if (!stripped.startsWith('/')) return { isCommand: false }

  const body = stripped.slice(1)
  const matched = body.match(/\S+/)
  if (!matched) {
    return { isCommand: true, known: false, name: '', rawArgs: '', error: '未知命令 /' }
  }
  const token = matched[0]
  const name = token.toLowerCase()
  if (!COMMAND_NAME_PATTERN.test(name) || isUnixPathToken(name)) return { isCommand: false }
  const rawArgs = body.slice(matched.index + matched[0].length)
  const known = (Array.isArray(commands) ? commands : []).some((command) => command?.name === name)
  return {
    isCommand: true,
    known,
    name,
    rawArgs,
    error: known ? '' : `未知命令 /${name}`,
  }
}

/**
 * 构造从首页跳转到对话页执行 Slash Command 的路由。
 *
 * Args:
 *   commandLine: 首页提交的完整命令行。
 *   chatId: 首页为命令目录预创建的会话 ID。
 *
 * Returns:
 *   Vue Router 路由对象；缺少命令行时返回 null。
 */
export function buildCommandDialogueRoute(commandLine, chatId) {
  const line = String(commandLine || '').trim()
  if (!line) return null
  if (!chatId) return { path: '/dialogue', query: { prompt: line } }
  return {
    path: `/dialogue/${encodeURIComponent(chatId)}`,
    query: { prompt: line },
  }
}
