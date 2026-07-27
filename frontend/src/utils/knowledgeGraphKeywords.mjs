const ENGLISH_STOP_WORDS = new Set([
  'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from', 'how', 'in', 'is', 'of', 'on', 'or', 'that',
  'the', 'to', 'what', 'when', 'where', 'which', 'why', 'with', 'about', 'please', 'search', 'find', 'show',
])

const CHINESE_STOP_PATTERN = /有哪些|是什么|为什么|如何|怎么|请问|请|能否|是否|相关|对应|检索|搜索|文献|论文|资料|常用的|常见的|常用|常见|主要|以及|或者|和|与|及|或|在|中|里|对|关于|用于|用来|具有|哪些|什么|的|了|是|为|有/g

const DOMAIN_TERMS = [
  '光刻胶', '聚合物', '树脂', '单体', '光酸', '光酸产生剂', 'PAG', '添加剂', '交联剂', '抑制剂',
  '优化', '改善', '提升', '影响', '控制', '因素', '显影', '曝光', '刻蚀', '线边粗糙度', '边缘粗糙度',
  '粗糙度', '粘度', '黏度', '溶解', '溶解度', '对比度', '介电常数', '折射率', '透过率', '分辨率',
  '灵敏度', '材料', '工艺',
]

/**
 * 将自然语言问题拆成适合知识图谱子图检索的关键词数组。
 *
 * @param {string} input 用户输入的问题或 prompt。
 * @param {{ maxKeywords?: number }} options 关键词数量上限。
 * @returns {string[]} 去重后的关键词数组。
 */
export function extractGraphKeywords(input, options = {}) {
  const maxKeywords = Math.max(1, Number(options.maxKeywords || 12))
  const text = String(input || '').trim()
  if (!text) return []

  const normalized = text
    .replace(/[，。！？；：、（）【】《》“”‘’]/g, ' ')
    .replace(/[(),.;:!?[\]{}<>"']/g, ' ')
    .replace(/[\r\n\t]+/g, ' ')

  const rawTokens = normalized.match(/[A-Za-z][A-Za-z0-9+./-]*|\d+(?:\.\d+)?|[\p{Script=Han}]{2,}/gu) || []
  const keywordCandidates = []

  for (const token of rawTokens) {
    if (/^[\p{Script=Han}]+$/u.test(token)) {
      let matchedDomainTerm = false
      DOMAIN_TERMS.forEach((term) => {
        if (token.includes(term)) {
          matchedDomainTerm = true
          keywordCandidates.push(term)
        }
      })
      if (matchedDomainTerm) continue
      token
        .replace(CHINESE_STOP_PATTERN, ' ')
        .split(/\s+/)
        .filter(Boolean)
        .forEach((part) => keywordCandidates.push(part))
      continue
    }

    const cleaned = token.trim()
    if (!cleaned) continue
    if (/^[A-Za-z]+$/.test(cleaned) && ENGLISH_STOP_WORDS.has(cleaned.toLowerCase())) continue
    keywordCandidates.push(cleaned)
  }

  const seen = new Set()
  const keywords = []
  for (const candidate of keywordCandidates) {
    const keyword = candidate.trim()
    if (!keyword || keyword.length < 2) continue
    const key = keyword.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    keywords.push(keyword)
    if (keywords.length >= maxKeywords) break
  }
  return keywords
}

/**
 * 生成图谱子图接口使用的 query 字符串；无法拆解时回退原始输入。
 *
 * @param {string} input 用户输入的问题或 prompt。
 * @param {{ maxKeywords?: number }} options 关键词数量上限。
 * @returns {string} 图谱检索 query。
 */
export function promptToGraphQuery(input, options = {}) {
  const keywords = extractGraphKeywords(input, options)
  return keywords.length ? keywords.join(' ') : String(input || '').trim()
}
