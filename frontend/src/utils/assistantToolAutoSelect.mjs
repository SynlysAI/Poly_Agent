/**
 * LUI 工具菜单的保守自动匹配逻辑。
 * 只做轻量文本匹配，不引入模型或外部依赖；用户显式选择由调用方优先保留。
 */

export const MAX_AUTO_SELECTED_TOOLS = 5

function normalizedText(value) {
  return String(value || '')
    .normalize('NFKC')
    .toLowerCase()
    .trim()
}

function fieldSearchText(tool) {
  const legacyFields = tool?.input_schema?.fields || {}
  const jsonProperties = tool?.input_json_schema?.properties || {}
  const parts = []
  for (const [key, description] of Object.entries(legacyFields)) {
    parts.push(key, description)
  }
  for (const [key, definition] of Object.entries(jsonProperties)) {
    parts.push(key, definition?.description, definition?.type)
  }
  return parts.filter(Boolean).join(' ')
}

export function toolSearchableText(tool) {
  return normalizedText([
    tool?.name,
    tool?.description,
    tool?.algorithm_id,
    tool?.tool_id,
    ...(tool?.material_scope || []),
    fieldSearchText(tool),
  ].filter(Boolean).join(' '))
}

export function queryTerms(text) {
  const normalized = normalizedText(text)
  if (!normalized) return []
  const segments = normalized.split(/[^0-9a-z\u4e00-\u9fff]+/i).filter(Boolean)
  const terms = []
  for (const segment of segments) {
    if (/[\u4e00-\u9fff]/.test(segment)) {
      terms.push({ text: segment, weight: segment.length >= 4 ? 4 : 2 })
      for (let index = 0; index < segment.length - 1; index += 1) {
        terms.push({ text: segment.slice(index, index + 2), weight: 1 })
      }
    } else {
      terms.push({ text: segment, weight: segment.length >= 3 ? 3 : 2 })
    }
  }

  const deduped = new Map()
  for (const term of terms) {
    const current = deduped.get(term.text)
    if (!current || term.weight > current.weight) deduped.set(term.text, term)
  }
  return [...deduped.values()].filter((term) => term.text.length > 0)
}

export function scoreToolRelevance(tool, prompt) {
  const corpus = toolSearchableText(tool)
  const promptText = normalizedText(prompt)
  if (!corpus || !promptText) return { score: 0, matchedTerms: [], reason: '' }

  const matched = []
  let score = 0
  for (const term of queryTerms(promptText)) {
    if (corpus.includes(term.text)) {
      score += term.weight
      matched.push(term.text)
    }
  }

  const toolName = normalizedText(tool?.name)
  if (
    toolName
    && (toolName.includes(promptText) || promptText.includes(toolName))
  ) {
    score += 6
    matched.push(tool.name)
  }

  const uniqueTerms = [...new Set(matched.filter(Boolean))]
  return {
    score,
    matchedTerms: uniqueTerms.slice(0, 5),
    reason: uniqueTerms.length
      ? `命中关键词：${uniqueTerms.slice(0, 5).join('、')}`
      : '',
  }
}

export function selectRelevantTools(tools = [], prompt = '', { max = MAX_AUTO_SELECTED_TOOLS } = {}) {
  const scored = (tools || [])
    .map((tool) => {
      const relevance = scoreToolRelevance(tool, prompt)
      return {
        tool_id: tool?.tool_id,
        score: relevance.score,
        matched_terms: relevance.matchedTerms,
        reason: relevance.reason,
      }
    })
    .filter((item) => item.score > 0)
    .sort((left, right) => (
      right.score - left.score
      || String(left.tool_id || '').localeCompare(String(right.tool_id || ''), 'zh-CN')
    ))

  return scored.slice(0, max)
}
