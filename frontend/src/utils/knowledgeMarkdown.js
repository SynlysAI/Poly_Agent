import DOMPurify from 'dompurify'
import { marked } from 'marked'

let markedConfigured = false
const COMPLETE_MARKDOWN_CODE_RE = /(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)/g
const CITATION_TAG_RE = /<kb\b([^>]*?)\s*\/?>/gi
const HTML_PLACEHOLDER_RE = /@@POLY_KB_HTML_PLACEHOLDER_(\d+)@@/g
const FULLWIDTH_IMAGE_OPEN_RE = /(!\[[^\]\n]*\])（(?=(?:https?|resource|storage|local|minio|s3|cos|tos|oss|obs|ks3):\/\/)/gi
const FULLWIDTH_IMAGE_CLOSE_RE = /(!\[[^\]\n]*\]\((?:https?|resource|storage|local|minio|s3|cos|tos|oss|obs|ks3):\/\/[^）\n]*?)）/gi

/** 解析 `<kb .../>` 属性字符串。 */
function parseTagAttributes(attrString) {
  const attributes = {}
  const pattern = /([\w-]+)\s*=\s*"([^"]*)"/g
  let match = pattern.exec(attrString || '')
  while (match) {
    attributes[match[1]] = match[2]
    match = pattern.exec(attrString || '')
  }
  return attributes
}

/** HTML 转义。 */
function escapeHtml(text) {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** 去掉文件名后缀，避免正文里直接暴露 .pdf。 */
function stripKnownFileSuffix(text) {
  return String(text || '')
    .replace(/\.(pdf|docx?|pptx?|md|markdown|txt|html?)$/i, '')
    .trim()
}

/** 获取适合正文展示的引用短标题。 */
function citationDisplayTitle(attrs) {
  const doc = stripKnownFileSuffix(attrs.doc || attrs.title || '知识引用')
  return doc.length > 16 ? `${doc.slice(0, 8)}...${doc.slice(-5)}` : doc
}

/** 获取引用标签的悬浮说明。 */
function citationTooltipText(attrs) {
  const doc = attrs.doc || attrs.title || '知识引用'
  return doc
}

/** 仅对非代码块内容执行替换。 */
function replaceOutsideCodeBlocks(content, replacer) {
  const parts = String(content || '').split(COMPLETE_MARKDOWN_CODE_RE)
  for (let i = 0; i < parts.length; i += 2) {
    parts[i] = replacer(parts[i])
  }
  return parts.join('')
}

/** 生成知识库引用标签的安全 HTML。 */
function buildCitationTagHtml(attrString, citationUrl) {
  const attrs = parseTagAttributes(attrString)
  const doc = attrs.doc || attrs.title || '知识引用'
  const title = citationTooltipText(attrs)
  const displayTitle = citationDisplayTitle(attrs)
  const href = citationUrl ? String(citationUrl(attrs) || '').trim() : ''
  const tagName = href ? 'a' : 'span'
  const hrefAttrs = href ? ` href="${escapeHtml(href)}" target="_blank" rel="noreferrer noopener"` : ''
  const roleAttr = href ? '' : ' role="note"'

  return `<${tagName} class="answer-citation-tag"${roleAttr} title="${escapeHtml(title)}" data-doc="${escapeHtml(doc)}"${hrefAttrs}><span class="answer-citation-tag__icon" aria-hidden="true"></span><span class="answer-citation-tag__text">${escapeHtml(displayTitle)}</span><span class="answer-citation-tag__tooltip" aria-hidden="true"><span class="answer-citation-tag__tooltip-title">${escapeHtml(title)}</span><span class="answer-citation-tag__tooltip-meta">${href ? '点击打开来源' : '来自知识库命中证据'}</span></span></${tagName}>`
}

/** 初始化 marked，仅执行一次。 */
export function configureKnowledgeMarkdown() {
  if (markedConfigured) return
  marked.use({ breaks: true, gfm: true })
  markedConfigured = true
}

/** 把全角括号图片语法修正为标准 markdown。 */
export function normalizeFullwidthMarkdownImageParentheses(content) {
  if (!content || (!content.includes('（') && !content.includes('）'))) return content

  return replaceOutsideCodeBlocks(content, (segment) =>
    segment
      .replace(FULLWIDTH_IMAGE_OPEN_RE, '$1(')
      .replace(FULLWIDTH_IMAGE_CLOSE_RE, '$1)'),
  )
}

/** 将 `<kb .../>` 标签替换为占位符，便于 markdown 解析后恢复。 */
export function extractCitationHtmlPlaceholders(content, citationUrl) {
  const htmlSnippets = []
  const contentWithPlaceholders = replaceOutsideCodeBlocks(content, (segment) =>
    segment.replace(CITATION_TAG_RE, (_match, attrString) => {
      const snippet = buildCitationTagHtml(attrString, citationUrl)
      const index = htmlSnippets.length
      htmlSnippets.push(snippet)
      return `@@POLY_KB_HTML_PLACEHOLDER_${index}@@`
    }),
  )
  return { content: contentWithPlaceholders, htmlSnippets }
}

/** 恢复 markdown 解析期间占位的引用标签。 */
export function restoreCitationHtmlPlaceholders(html, htmlSnippets) {
  if (!htmlSnippets.length) return html
  return html.replace(HTML_PLACEHOLDER_RE, (_match, idx) => htmlSnippets[Number(idx)] || '')
}

/** 给表格包一层滚动容器。 */
export function wrapKnowledgeMarkdownTables(html) {
  if (!html || !html.includes('<table')) return html
  return html.replace(
    /<table\b[\s\S]*?<\/table>/gi,
    (tableHtml) => `<div class="knowledge-markdown-table">${tableHtml}</div>`,
  )
}

/**
 * 渲染知识库回答 markdown。
 *
 * Args:
 *   rawMarkdown: 后端返回的原始回答文本。
 *   resolveImageUrl: 将原始图片地址转换为可访问地址的函数。
 *   citationUrl: 将 `<kb>` 引用属性转换为来源链接的函数。
 *
 * Returns:
 *   可直接用于 v-html 的安全 HTML。
 */
export function renderKnowledgeMarkdown(rawMarkdown, { resolveImageUrl, citationUrl } = {}) {
  const rawText = typeof rawMarkdown === 'string' ? rawMarkdown : String(rawMarkdown || '')
  if (!rawText.trim()) return ''

  configureKnowledgeMarkdown()

  const normalizedText = normalizeFullwidthMarkdownImageParentheses(rawText)
  const { content, htmlSnippets } = extractCitationHtmlPlaceholders(normalizedText, citationUrl)
  const renderer = new marked.Renderer()

  renderer.link = ({ href, title, text }) => {
    const safeHref = String(href || '').trim()
    const safeTitle = title ? ` title="${escapeHtml(title)}"` : ''
    const body = text || ''
    if (!safeHref) return body
    return `<a href="${escapeHtml(safeHref)}" target="_blank" rel="noreferrer noopener"${safeTitle}>${body}</a>`
  }

  renderer.image = ({ href, title, text }) => {
    const rawHref = String(href || '').trim()
    const resolvedHref = resolveImageUrl ? String(resolveImageUrl(rawHref) || '').trim() : rawHref
    const altText = escapeHtml(text || '回答图片')
    const caption = text ? `<figcaption>${escapeHtml(text)}</figcaption>` : ''
    const safeTitle = title ? ` title="${escapeHtml(title)}"` : ''

    if (!resolvedHref) {
      return `<figure class="knowledge-image-block knowledge-image-block--unavailable"><div class="knowledge-image-unavailable"><strong>${altText}</strong><span>图片资源暂不可用。</span></div></figure>`
    }

    return `<figure class="knowledge-image-block"><img src="${escapeHtml(resolvedHref)}" alt="${altText}" loading="lazy"${safeTitle}>${caption}</figure>`
  }

  const html = marked.parse(content, {
    renderer,
    breaks: true,
    async: false,
  })

  const restoredHtml = restoreCitationHtmlPlaceholders(html, htmlSnippets)
  const wrappedHtml = wrapKnowledgeMarkdownTables(restoredHtml)
  return DOMPurify.sanitize(wrappedHtml, {
    USE_PROFILES: { html: true },
    ADD_TAGS: ['figure', 'figcaption'],
    ADD_ATTR: ['class', 'role', 'title', 'target', 'rel', 'loading', 'data-doc', 'data-chunk-id', 'data-kb-id'],
  })
}
