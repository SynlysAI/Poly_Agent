/**
 * Normalize a persisted assistant context digest.
 *
 * @param {unknown} digest Raw digest value from message metadata.
 * @returns {string} Non-empty digest string, or an empty string.
 */
export function normalizeAssistantContextDigest(digest) {
  return typeof digest === 'string' && digest.trim() ? digest.trim() : ''
}

/**
 * Build the short meta label for an assistant message context digest.
 *
 * @param {{ context_digest?: unknown }} message Assistant message object.
 * @returns {string} Short label such as `上下文 abcdef`, or an empty string.
 */
export function assistantContextLabel(message) {
  const digest = normalizeAssistantContextDigest(message?.context_digest)
  if (!digest) return ''
  return `上下文 ${digest.slice(-6)}`
}

/**
 * Build the full tooltip for an assistant context digest.
 *
 * @param {{ context_digest?: unknown }} message Assistant message object.
 * @returns {string} Full digest, or an empty string.
 */
export function assistantContextTooltip(message) {
  return normalizeAssistantContextDigest(message?.context_digest)
}
