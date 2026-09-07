const READABLE_FIELD_PATTERN = /(?:^|[_\-\s.])(formula|equation|description|recipe|recommendation|process|protocol|summary|rationale|instruction|notes?)(?:[_\-\s.]|$)/i
const RECIPE_FIELD_PATTERN = /(?:^|[_\-\s.])(recipe|recommendation|process|protocol)(?:[_\-\s.]|$)/i
const FORMULA_FIELD_PATTERN = /(?:^|[_\-\s.])(formula|equation|risk)(?:[_\-\s.]|$)/i
const FORMULA_SEMANTIC_PATTERN = /formula|equation|公式|方程|评分式/i
const RECIPE_TEXT_PATTERN = /推荐配方|推荐工艺|组装电池|组装工艺|前驱体液配制|原位聚合|配制步骤|实验步骤/
const LABELLED_LINE_PATTERN = /^\s*(?:#+\s*)?(?:\*\*)?([^：:]{1,30})(?:\*\*)?\s*[:：]\s*(.*)$/
const BRACKET_HEADING_PATTERN = /^\s*【\d+】\s*(.+?)\s*$/
const MARKDOWN_HEADING_PATTERN = /^\s*#{1,6}\s+(.+?)\s*#*\s*$/
const NUMBERED_HEADING_PATTERN = /^\s*\d+[.、]\s*(.+?)\s*$/
const FUNCTION_FORMULA_PATTERN = /[A-Za-z_][\w.]*\s*=\s+[A-Za-z_][\w.]*\s*\(/g
const ASSIGNMENT_FORMULA_PATTERN = /[A-Za-z_][\w.]*\s*=/g
const HEADING_KEYWORD_PATTERN = /公式|方程|工艺|配方|流程|步骤|formula|equation|recipe|process/i
const COEFFICIENT_MULTIPLICATION_PATTERN = /(\b\d+(?:\.\d+)?)\s+x\s+(?=[A-Za-z_(\d])/g

/**
 * 判断字段值是否适合以可读文档卡片展示。
 *
 * Args:
 *     key: 字段名，可包含对象路径前缀。
 *     value: 待展示的字段值。
 *
 * Returns:
 *     字符串值较长、包含换行或具备说明语义时返回 true。
 */
export function isReadableText(key, value) {
  if (typeof value !== 'string') return false
  const text = value.trim()
  if (!text) return false
  return text.length > 80 || text.includes('\n') || READABLE_FIELD_PATTERN.test(String(key || ''))
}

/**
 * 判断可读文本的展示类型。
 *
 * Args:
 *     key: 字段名，可包含对象路径前缀。
 *     value: 待展示的字符串值。
 *
 * Returns:
 *     "formula"、"recipe" 或 "document"。
 */
export function classifyReadableText(key, value) {
  const normalizedKey = String(key || '').toLowerCase()
  const text = String(value || '')
  const formulaSemantics = FORMULA_FIELD_PATTERN.test(normalizedKey) || FORMULA_SEMANTIC_PATTERN.test(normalizedKey)
  if (formulaSemantics || findFunctionFormula(text)) return 'formula'
  if (RECIPE_FIELD_PATTERN.test(normalizedKey) || RECIPE_TEXT_PATTERN.test(text)) return 'recipe'
  return 'document'
}

/**
 * 将长文本拆分为卡片正文行，并为带标题前缀的行补充加粗标签。
 *
 * Args:
 *     value: 待展示的长文本。
 *
 * Returns:
 *     每行一个对象的数组，label 为空表示普通正文行。
 */
export function buildReadableTextLines(value) {
  const text = typeof value === 'string' ? value : String(value || '')
  return text
    .split(/\r?\n/)
    .map((line) => {
      const match = line.match(LABELLED_LINE_PATTERN)
      if (!match) return { label: '', text: line.trim() }
      return { label: match[1].trim(), text: match[2].trim() }
    })
    .filter((line) => line.label || line.text)
}

/**
 * 将模型返回的复合说明拆分为多个可读分区。
 *
 * Args:
 *     key: 原始字段名或对象路径。
 *     value: 包含公式、解释、配方或工艺的复合文本。
 *     hint: 可选的输出 schema 提示，可包含 kind 与 title。
 *
 * Returns:
 *     可读分区数组，每个分区包含唯一 key、类型、标题和正文行。
 */
export function buildReadableSections(key, value, hint = {}) {
  const normalizedKey = String(key || 'output')
  const text = typeof value === 'string' ? value : String(value || '')
  if (!text.trim()) return []

  const semanticParts = splitSemanticSections(text)
  if (semanticParts.length) {
    return semanticParts.flatMap((part, index) => buildSectionsFromPart(
      `${normalizedKey}::${index + 1}`,
      part.title,
      part.content,
      hint,
    ))
  }
  return buildSectionsFromPart(normalizedKey, '', text, hint)
}

/**
 * 生成可读卡片的中文标题。
 *
 * Args:
 *     key: 字段名，可包含对象路径前缀。
 *     kind: 可读文本类型，取值为 formula、recipe 或 document。
 *
 * Returns:
 *     优先使用语义映射的标题，否则返回字段名的人类可读格式。
 */
export function formatReadableTitle(key, kind) {
  const normalizedKey = String(key || '').toLowerCase()
  if (normalizedKey.includes('thermal_runaway_formula')) return '热失控风险评分公式'
  if (kind === 'recipe' && /recommend/.test(normalizedKey)) return '推荐配方与组装工艺'
  if (kind === 'recipe') return '推荐配方与工艺'
  if (kind === 'formula') return '公式'
  if (normalizedKey.includes('assembly_process')) return '组装工艺'
  const fieldName = normalizedKey.split('.').at(-1) || 'output'
  return formatLabel(fieldName)
}

/**
 * 格式化公式显示文本，消除上游 JSON 中的窄幅手工换行。
 *
 * Args:
 *     value: 模型输出中的公式文本。
 *
 * Returns:
 *     结构化换行后的显示文本；无法安全解析时返回压缩后的原文。
 */
export function formatReadableFormula(value) {
  const compact = normalizeFormulaSpacing(value)
  const candidate = findFunctionFormula(compact)
  if (!candidate) return compact

  const assignment = compact.slice(candidate.start, candidate.openIndex).trim()
  const body = compact.slice(candidate.openIndex + 1, candidate.end).trim()
  const terms = splitTopLevel(body, '+')
  if (terms.length <= 1) return compact

  const lastTerm = terms.at(-1)
  const commaPositions = topLevelOperatorPositions(lastTerm, ',')
  if (!commaPositions.length) {
    return [
      `${assignment}(`,
      ...terms.map((term, index) => formatFormulaTerm(term, index)),
      ')',
    ].join('\n')
  }

  const expression = lastTerm.slice(0, commaPositions[0]).trim()
  const trailingArguments = splitAtPositions(lastTerm, commaPositions).slice(1).map((item) => item.trim())
  const formattedTerms = [
    ...terms.slice(0, -1),
    `${expression},`,
  ].map((term, index) => formatFormulaTerm(term, index))
  return [
    `${assignment}(`,
    ...formattedTerms,
    `  ${trailingArguments.join(', ')}`,
    ')',
  ].join('\n')
}

/**
 * 格式化字段名或分块标题为人类可读文本。
 *
 * Args:
 *     value: 原始字段名或标题。
 *
 * Returns:
 *     下划线替换为空格并首字母大写后的文本。
 */
function formatLabel(value) {
  return String(value || '-')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

/**
 * 按标题语法拆分复合说明。
 *
 * Args:
 *     value: 模型输出的复合文本。
 *
 * Returns:
 *     语义分区数组；没有可靠标题时返回空数组。
 */
function splitSemanticSections(value) {
  const lines = value.split(/\r?\n/)
  const headings = []
  lines.forEach((line, index) => {
    const heading = parseHeadingLine(line)
    if (heading) headings.push({ line: index, ...heading })
  })
  if (!headings.length) return []

  return headings.flatMap((heading, headingIndex) => {
    const next = headings[headingIndex + 1]
    const contentLines = lines.slice(heading.line + 1, next?.line ?? lines.length)
    const content = [heading.inlineContent, ...contentLines]
      .filter((item) => String(item || '').trim())
      .join('\n')
    if (!content.trim()) return []
    return [{ title: heading.title, content }]
  })
}

/**
 * 解析一行文本中的标题语法。
 *
 * Args:
 *     line: 待解析的文本行。
 *
 * Returns:
 *     标题信息；非标题行返回 null。
 */
function parseHeadingLine(line) {
  const bracket = line.match(BRACKET_HEADING_PATTERN)
  if (bracket) return splitInlineHeading(bracket[1])

  const markdown = line.match(MARKDOWN_HEADING_PATTERN)
  if (markdown) return { title: markdown[1].trim(), inlineContent: '' }

  const numbered = line.match(NUMBERED_HEADING_PATTERN)
  if (numbered) {
    const inline = splitInlineHeading(numbered[1])
    if (inline.inlineContent) return inline
    if (HEADING_KEYWORD_PATTERN.test(numbered[1])) {
      return { title: numbered[1].trim(), inlineContent: '' }
    }
  }
  return null
}

/**
 * 拆分同行标题和内容。
 *
 * Args:
 *     value: 去掉编号或 Markdown 标记后的标题行内容。
 *
 * Returns:
 *     标题与可选的同行内容。
 */
function splitInlineHeading(value) {
  const match = value.match(/^([^：:]{1,40})[：:]\s*([\s\S]*)$/)
  if (match) {
    return { title: match[1].trim(), inlineContent: match[2].trim() }
  }
  return { title: value.trim(), inlineContent: '' }
}

/**
 * 根据字段、标题、schema 提示和正文生成可读分区。
 *
 * Args:
 *     key: 分区唯一键。
 *     explicitTitle: 分块文本显式给出的标题。
 *     content: 分区正文。
 *     hint: 可选的输出 schema 提示。
 *
 * Returns:
 *     可读分区数组。
 */
function buildSectionsFromPart(key, explicitTitle, content, hint = {}) {
  const hintedKind = explicitTitle ? '' : normalizeReadableKind(hint.kind)
  const semanticKey = [key, explicitTitle].filter(Boolean).join(' ')
  const preferFormula = hintedKind === 'formula' || classifySemanticContext(semanticKey)
  const formulaSections = buildFormulaSections(key, explicitTitle, content, preferFormula, hint)
  if (formulaSections) return formulaSections

  let kind = hintedKind || classifyReadableText(semanticKey, `${explicitTitle}\n${content}`)
  if (kind === 'formula' && ASSIGNMENT_FORMULA_PATTERN.test(content)) kind = 'document'
  ASSIGNMENT_FORMULA_PATTERN.lastIndex = 0

  const title = explicitTitle || hint.title || formatReadableTitle(key, kind)
  return [{
    key,
    kind,
    title,
    lines: buildReadableTextLines(content),
  }]
}

/**
 * 生成公式分区并分离公式后的变量说明。
 *
 * Args:
 *     key: 分区唯一键。
 *     explicitTitle: 分块文本显式给出的标题。
 *     content: 分区正文。
 *     preferFormula: 字段或标题是否明确指向公式。
 *     hint: 可选的输出 schema 提示。
 *
 * Returns:
 *     公式分区数组；无法安全提取公式时返回 null。
 */
function buildFormulaSections(key, explicitTitle, content, preferFormula, hint = {}) {
  const candidate = extractFormula(content, preferFormula)
  if (!candidate) return null

  const explanation = [
    content.slice(0, candidate.start),
    content.slice(candidate.end),
  ].join(' ').replace(/^[\s，,；;：:]+|[\s，,；;]+$/g, '')
  const sections = [{
    key: `${key}::formula`,
    kind: 'formula',
    title: hint.title || explicitTitle || formatReadableTitle(key, 'formula'),
    lines: buildReadableTextLines(candidate.formula),
  }]
  if (explanation.trim()) {
    sections.push({
      key: `${key}::notes`,
      kind: 'document',
      title: '公式变量与边界说明',
      lines: buildReadableTextLines(explanation),
    })
  }
  return sections
}

/**
 * 判断语义上下文是否明确指向公式。
 *
 * Args:
 *     value: 字段名和分块标题组成的上下文。
 *
 * Returns:
 *     明确指向公式时返回 true。
 */
function classifySemanticContext(value) {
  const normalizedValue = String(value || '').toLowerCase()
  return FORMULA_FIELD_PATTERN.test(normalizedValue) || FORMULA_SEMANTIC_PATTERN.test(normalizedValue)
}

/**
 * 提取完整公式表达式。
 *
 * Args:
 *     content: 包含公式的文本。
 *     preferFormula: 是否允许提取普通赋值表达式。
 *
 * Returns:
 *     公式位置与文本；无法安全提取时返回 null。
 */
function extractFormula(content, preferFormula) {
  const functionCandidate = findFunctionFormula(content)
  if (functionCandidate) {
    return {
      start: functionCandidate.start,
      end: functionCandidate.end + 1,
      formula: content.slice(functionCandidate.start, functionCandidate.end + 1),
    }
  }
  if (!preferFormula) return null

  ASSIGNMENT_FORMULA_PATTERN.lastIndex = 0
  let match = ASSIGNMENT_FORMULA_PATTERN.exec(content)
  while (match) {
    if (isIdentifierBoundary(content, match.index)) {
      const statement = formulaStatementFrom(content.slice(match.index))
      if (statement && hasBalancedParentheses(statement)) {
        return { start: match.index, end: match.index + statement.length, formula: statement }
      }
    }
    match = ASSIGNMENT_FORMULA_PATTERN.exec(content)
  }
  return null
}

/**
 * 查找赋值到函数调用的公式片段。
 *
 * Args:
 *     value: 待搜索文本。
 *
 * Returns:
 *     公式起点、函数左括号和匹配右括号位置；未找到时返回 null。
 */
function findFunctionFormula(value) {
  const text = String(value || '')
  FUNCTION_FORMULA_PATTERN.lastIndex = 0
  let match = FUNCTION_FORMULA_PATTERN.exec(text)
  while (match) {
    if (!isIdentifierBoundary(text, match.index)) {
      match = FUNCTION_FORMULA_PATTERN.exec(text)
      continue
    }
    const openIndex = text.indexOf('(', match.index)
    const endIndex = findMatchingParenthesis(text, openIndex)
    if (openIndex >= 0 && endIndex > openIndex) {
      FUNCTION_FORMULA_PATTERN.lastIndex = 0
      return { start: match.index, openIndex, end: endIndex }
    }
    match = FUNCTION_FORMULA_PATTERN.exec(text)
  }
  FUNCTION_FORMULA_PATTERN.lastIndex = 0
  return null
}

/**
 * 截取第一条完整公式语句。
 *
 * Args:
 *     value: 从赋值左侧开始的文本。
 *
 * Returns:
 *     去掉后续解释后的公式语句。
 */
function formulaStatementFrom(value) {
  const match = value.match(/^(.*?)(?:[，。；\n]|$)/)
  const statement = (match?.[1] || '').trim()
  return statement || null
}

/**
 * 判断匹配位置是否位于完整标识符边界。
 *
 * Args:
 *     value: 原始文本。
 *     index: 匹配起始位置。
 *
 * Returns:
 *     匹配位置前不是标识符字符时返回 true。
 */
function isIdentifierBoundary(value, index) {
  return index === 0 || !/[A-Za-z0-9_]/.test(value[index - 1] || '')
}

/**
 * 检查公式中的括号是否完全配对。
 *
 * Args:
 *     value: 公式文本。
 *
 * Returns:
 *     括号配对且未提前闭合时返回 true。
 */
function hasBalancedParentheses(value) {
  let depth = 0
  for (const character of value) {
    if (character === '(') depth += 1
    if (character === ')') {
      depth -= 1
      if (depth < 0) return false
    }
  }
  return depth === 0
}

/**
 * 查找左括号对应的右括号位置。
 *
 * Args:
 *     value: 待搜索文本。
 *     openIndex: 左括号位置。
 *
 * Returns:
 *     对应右括号位置；未找到时返回 -1。
 */
function findMatchingParenthesis(value, openIndex) {
  if (openIndex < 0) return -1
  let depth = 0
  for (let index = openIndex; index < value.length; index += 1) {
    if (value[index] === '(') depth += 1
    if (value[index] === ')') {
      depth -= 1
      if (depth === 0) return index
    }
  }
  return -1
}

/**
 * 规范公式空白并安全替换数字乘号。
 *
 * Args:
 *     value: 原始公式文本。
 *
 * Returns:
 *     单行规范文本，其中系数后的独立 x 转换为 ×。
 */
function normalizeFormulaSpacing(value) {
  return String(value || '')
    .replace(/\r?\n/g, ' ')
    .replace(/\s+/g, ' ')
    .replace(COEFFICIENT_MULTIPLICATION_PATTERN, '$1 × ')
    .trim()
}

/**
 * 在括号顶层按指定单字符操作符拆分文本。
 *
 * Args:
 *     value: 待拆分文本。
 *     separator: 单字符操作符。
 *
 * Returns:
 *     顶层片段数组。
 */
function splitTopLevel(value, separator) {
  return splitAtPositions(value, topLevelOperatorPositions(value, separator))
}

/**
 * 获取括号顶层指定操作符的位置。
 *
 * Args:
 *     value: 待扫描文本。
 *     separator: 单字符操作符。
 *
 * Returns:
 *     顶层操作符位置数组。
 */
function topLevelOperatorPositions(value, separator) {
  const positions = []
  let depth = 0
  for (let index = 0; index < value.length; index += 1) {
    if (value[index] === '(') depth += 1
    if (value[index] === ')') depth -= 1
    if (depth === 0 && value[index] === separator) positions.push(index)
  }
  return positions
}

/**
 * 按指定位置拆分文本。
 *
 * Args:
 *     value: 待拆分文本。
 *     positions: 拆分位置数组。
 *
 * Returns:
 *     拆分后的片段数组。
 */
function splitAtPositions(value, positions) {
  const parts = []
  let start = 0
  for (const position of positions) {
    parts.push(value.slice(start, position))
    start = position + 1
  }
  parts.push(value.slice(start))
  return parts.map((part) => part.trim()).filter(Boolean)
}

/**
 * 格式化公式项缩进和连接符。
 *
 * Args:
 *     term: 单个公式项。
 *     index: 公式项序号，从 0 开始。
 *
 * Returns:
 *     带缩进的公式项文本。
 */
function formatFormulaTerm(term, index) {
  return `${index === 0 ? '  ' : '  + '}${String(term).replace(/\s+/g, ' ').trim()}`
}

/**
 * 归一化输出 schema 提示中的展示类型。
 *
 * Args:
 *     value: schema 提示的 kind 或 display 字段。
 *
 * Returns:
 *     合法展示类型；无法识别时返回空字符串。
 */
function normalizeReadableKind(value) {
  const normalizedValue = String(value || '').trim().toLowerCase()
  return ['formula', 'recipe', 'document'].includes(normalizedValue) ? normalizedValue : ''
}
