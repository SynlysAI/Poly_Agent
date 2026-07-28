const TITLE_FIELDS = ['formula_id', 'id', 'name', 'title']
const NUMBER_FIELD_TOKENS = [
  'amount',
  'concentration',
  'count',
  'density',
  'fraction',
  'mass',
  'mol',
  'number',
  'pct',
  'percent',
  'percentage',
  'ratio',
  'temperature',
  'value',
  'weight',
]

export function isPlainObject(value) {
  return Object.prototype.toString.call(value) === '[object Object]'
}

export function recordTitleField(record) {
  if (!isPlainObject(record)) return ''
  return TITLE_FIELDS.find((key) => Object.prototype.hasOwnProperty.call(record, key)) || ''
}

export function inferValueKind(field, values = []) {
  const defined = values.filter((value) => value !== null && value !== undefined && value !== '')
  if (defined.some((value) => typeof value === 'number')) return 'number'
  if (defined.some((value) => typeof value === 'boolean')) return 'boolean'
  const normalized = String(field || '').toLowerCase()
  if (NUMBER_FIELD_TOKENS.some((token) => normalized.includes(token))) return 'number'
  if (['is_', 'has_', 'enable_', 'enabled_', 'use_'].some((prefix) => normalized.startsWith(prefix))) return 'boolean'
  return 'string'
}

export function coerceFieldValue(kind, value) {
  if (kind === 'number') {
    if (value === null || value === undefined || String(value).trim() === '') return 0
    const parsed = Number(value)
    if (!Number.isFinite(parsed)) throw new Error('数值默认值不合法')
    return parsed
  }
  if (kind === 'boolean') {
    if (typeof value === 'boolean') return value
    return String(value || '').trim().toLowerCase() === 'true'
  }
  return value === null || value === undefined ? '' : String(value)
}

function normalizedFieldName(value) {
  const name = String(value || '').trim()
  if (!name) throw new Error('字段名不能为空')
  return name
}

export function addFieldToRecords(records, field, kind = 'string', defaultValue = '') {
  const name = normalizedFieldName(field)
  if (records.some((record) => isPlainObject(record) && Object.prototype.hasOwnProperty.call(record, name))) {
    throw new Error(`字段已存在：${name}`)
  }
  const value = coerceFieldValue(kind, defaultValue)
  return records.map((record) => (isPlainObject(record) ? { ...record, [name]: value } : record))
}

export function renameFieldInRecords(records, sourceField, targetField) {
  const source = normalizedFieldName(sourceField)
  const target = normalizedFieldName(targetField)
  if (source === target) return records.map((record) => (isPlainObject(record) ? { ...record } : record))
  if (records.some((record) => isPlainObject(record) && Object.prototype.hasOwnProperty.call(record, target))) {
    throw new Error(`字段已存在：${target}`)
  }
  if (!records.some((record) => isPlainObject(record) && Object.prototype.hasOwnProperty.call(record, source))) {
    throw new Error(`字段不存在：${source}`)
  }
  return records.map((record) => {
    if (!isPlainObject(record) || !Object.prototype.hasOwnProperty.call(record, source)) return record
    return Object.fromEntries(Object.entries(record).map(([key, value]) => [key === source ? target : key, value]))
  })
}

export function removeFieldFromRecords(records, field) {
  const name = normalizedFieldName(field)
  return records.map((record) => {
    if (!isPlainObject(record)) return record
    return Object.fromEntries(Object.entries(record).filter(([key]) => key !== name))
  })
}

export function flattenJsonObject(source, prefix = '', target = {}) {
  if (!isPlainObject(source)) return target
  for (const [key, value] of Object.entries(source)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (isPlainObject(value) && Object.keys(value).length) flattenJsonObject(value, path, target)
    else target[path] = value
  }
  return target
}

export function buildArrayObjectSection(key, rows) {
  const flatRows = rows.map((row) => flattenJsonObject(row))
  const columns = Array.from(new Set(flatRows.flatMap((row) => Object.keys(row))))
  return {
    key,
    title: key,
    rows: flatRows,
    columns,
    totalRows: rows.length,
    totalColumns: columns.length,
  }
}

export function buildBatchHighlights(sections) {
  return sections.flatMap((section) => {
    const numericColumns = section.columns.filter((column) =>
      section.rows.some((row) => typeof row[column] === 'number' && Number.isFinite(row[column])),
    )
    const metrics = numericColumns.map((column) => {
      const values = section.rows
        .map((row) => row[column])
        .filter((value) => typeof value === 'number' && Number.isFinite(value))
      return {
        key: `${section.key}.${column}`,
        label: sections.length > 1 ? `${section.title} / ${column}` : column,
        value: values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null,
        caption: values.length > 1 ? '平均值' : '预测值',
      }
    })
    return [
      {
        key: `${section.key}.count`,
        label: sections.length > 1 ? `${section.title} 结果数量` : '结果数量',
        value: section.totalRows,
        caption: section.title,
      },
      ...metrics,
    ]
  })
}

export function paginateRows(rows, page = 1, pageSize = 20) {
  const size = Math.max(1, Number(pageSize) || 20)
  const totalPages = Math.max(1, Math.ceil(rows.length / size))
  const currentPage = Math.min(Math.max(1, Number(page) || 1), totalPages)
  const start = (currentPage - 1) * size
  return {
    rows: rows.slice(start, start + size),
    page: currentPage,
    pageSize: size,
    total: rows.length,
    totalPages,
  }
}
