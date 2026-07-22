const STATUS_PRIORITY = {
  available: 0,
  unknown: 1,
  degraded: 2,
  not_configured: 3,
  down: 4,
}

function modelKey(providerId, modelId) {
  return `${providerId}::${modelId}`
}

function routeMatches(row, route) {
  return Boolean(route?.provider_id && route?.model_id && row.providerId === route.provider_id && row.modelId === route.model_id)
}

function duplicatePriority(row, route) {
  if (routeMatches(row, route)) return -1
  return STATUS_PRIORITY[row.status] ?? STATUS_PRIORITY.unknown
}

function purposePriority(row, route, preferredPurpose) {
  if (routeMatches(row, route)) return -100
  if (row.recommendedFor.includes(preferredPurpose)) return -80
  if (preferredPurpose === 'deep' && row.capabilities.includes('reasoning')) return -60
  if (preferredPurpose === 'deep' && row.capabilities.includes('long_context')) return -50
  if (preferredPurpose === 'qa' && row.capabilities.includes('fast')) return -60
  if (preferredPurpose === 'qa' && row.recommendedFor.includes('deep')) return 30
  if (preferredPurpose === 'qa' && row.capabilities.includes('reasoning') && !row.capabilities.includes('fast')) return 20
  return 0
}

function sortForPurpose(rows, catalog, preferredPurpose) {
  if (!preferredPurpose) return rows
  const route = catalog?.routing?.[preferredPurpose]
  return [...rows].sort((a, b) => {
    const purposeDiff = purposePriority(a, route, preferredPurpose) - purposePriority(b, route, preferredPurpose)
    if (purposeDiff !== 0) return purposeDiff
    return (STATUS_PRIORITY[a.status] ?? STATUS_PRIORITY.unknown) - (STATUS_PRIORITY[b.status] ?? STATUS_PRIORITY.unknown)
  })
}

export function buildSelectableLlmModels(catalog, { dedupeByModelId = false, preferredPurpose = '' } = {}) {
  const rows = []
  for (const provider of catalog?.providers || []) {
    for (const model of provider.models || []) {
      rows.push({
        key: modelKey(provider.provider_id, model.model_id),
        providerId: provider.provider_id,
        providerName: provider.display_name || provider.provider_id,
        modelId: model.model_id,
        label: model.display_name || model.model_id,
        capabilities: model.capabilities || [],
        recommendedFor: model.recommended_for || [],
        status: provider.status,
      })
    }
  }

  if (!dedupeByModelId) return sortForPurpose(rows, catalog, preferredPurpose)

  const route = preferredPurpose ? catalog?.routing?.[preferredPurpose] : null
  const deduped = new Map()
  for (const row of rows) {
    const existing = deduped.get(row.modelId)
    if (!existing || duplicatePriority(row, route) < duplicatePriority(existing, route)) {
      deduped.set(row.modelId, row)
    }
  }
  return sortForPurpose(Array.from(deduped.values()), catalog, preferredPurpose)
}
