const READABLE_FIELD_PATTERN = /(?:^|[_\-\s.])(formula|equation|description|recipe|recommendation|process|protocol|summary|rationale|instruction|notes?)(?:[_\-\s.]|$)/i
const RECIPE_FIELD_PATTERN = /(?:^|[_\-\s.])(recipe|recommendation|process|protocol)(?:[_\-\s.]|$)/i
const FORMULA_FIELD_PATTERN = /(?:^|[_\-\s.])(formula|equation|risk)(?:[_\-\s.]|$)/i
const FORMULA_TEXT_PATTERN = /(?:^|\n)\s*Risk[_A-Za-z0-9]*\s*=|\bclamp\s*\(/i
const RECIPE_TEXT_PATTERN = /推荐配方|推荐工艺|组装电池|组装工艺|前驱体液配制|原位聚合|配制步骤|实验步骤/
const LABELLED_LINE_PATTERN = /^\s*(?:#+\s*)?(?:\*\*)?([^：:]{1,30})(?:\*\*)?\s*[:：]\s*(.*)$/

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
  if (RECIPE_FIELD_PATTERN.test(normalizedKey) || RECIPE_TEXT_PATTERN.test(text)) return 'recipe'
  if (FORMULA_FIELD_PATTERN.test(normalizedKey) || FORMULA_TEXT_PATTERN.test(text)) return 'formula'
  return 'document'
}

/**
 * 将长文本拆分为卡片正文行，并为带标题前缀的行补充加粗标签。
 *
 * Args:
 *     value: 待展示的字符串值。
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
  if (kind === 'formula') return '评分公式'
  if (normalizedKey.includes('assembly_process')) return '组装工艺'
  const fieldName = normalizedKey.split('.').at(-1) || 'output'
  return formatLabel(fieldName)
}

/**
 * 格式化公式显示文本，保持原始数据不变。
 *
 * Args:
 *     value: 模型输出中的公式文本。
 *
 * Returns:
 *     将独立乘号标记 x 替换为 × 后的显示文本。
 */
export function formatReadableFormula(value) {
  return String(value || '').replace(/\bx\b/g, '×').trim()
}

function formatLabel(value) {
  return String(value || '-')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}
