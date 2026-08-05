export function parseObjectJson(value, label = 'JSON') {
  try {
    const parsed = JSON.parse(value)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error(`${label} 必须是 JSON 对象`)
    }
    return parsed
  } catch (error) {
    throw new Error(`${label} 格式错误：${error.message}`)
  }
}

export function buildExperimentDispatchPayload(form, template) {
  const parameters = parseObjectJson(form.parametersJson, '实验参数')
  const selectionInputs = parseObjectJson(form.selectionInputsJson || '{}', '选择输入')
  return {
    template_id: template.template_id,
    template_version: template.template_version,
    experiment_name: String(form.experimentName || '').trim() || null,
    experiment_notes: String(form.experimentNotes || '').trim() || null,
    selection_inputs: selectionInputs,
    parameter_overrides: parameters,
    variant_id: String(form.variantId || '').trim() || null,
  }
}

export function manifestParameterJson(manifest) {
  return JSON.stringify(manifest?.parameters || {}, null, 2)
}

export function manifestSelectionJson(manifest) {
  return JSON.stringify(manifest?.selection || {}, null, 2)
}

export function valueType(value) {
  if (Array.isArray(value)) return 'array'
  if (value === null) return 'any'
  if (typeof value === 'number') return Number.isInteger(value) ? 'integer' : 'number'
  if (typeof value === 'object') return 'object'
  return typeof value
}

export function flattenDispatchFields(value, basePath = '') {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return []
  const fields = []
  for (const [key, child] of Object.entries(value)) {
    const path = `${basePath}/${String(key).replace(/~/g, '~0').replace(/\//g, '~1')}`
    if (child && typeof child === 'object' && !Array.isArray(child)) {
      fields.push(...flattenDispatchFields(child, path))
    } else {
      fields.push({ path, label: key, value_type: valueType(child), sample: child })
    }
  }
  return fields
}

function normalizedFieldName(path) {
  return String(path || '').split('/').at(-1)?.replace(/[_\-.]/g, '').toLowerCase() || ''
}

function compatibleType(targetType, sourceType) {
  if (!targetType || targetType === 'any' || !sourceType || sourceType === 'any') return true
  if (targetType === sourceType) return true
  return targetType === 'number' && sourceType === 'integer'
}

export function autoMatchDispatchMappings(targetFields, sourceFields) {
  const output = []
  for (const target of targetFields || []) {
    const name = normalizedFieldName(target.path)
    const matches = (sourceFields || []).filter((source) => (
      normalizedFieldName(source.path) === name
      && compatibleType(target.value_type, source.value_type)
    ))
    if (matches.length === 1) {
      output.push({ target_path: target.path, source_path: matches[0].path })
    }
  }
  return output
}
