const TRUE_VALUES = new Set(['true', '1', 'yes', 'y', '是']);
const FALSE_VALUES = new Set(['false', '0', 'no', 'n', '否']);

export function coerceClipboardValue(value, type = 'string') {
  const text = String(value ?? '').trim();
  if (!text) return '';
  const normalizedType = String(type || 'string').toLowerCase();
  if (normalizedType.includes('bool')) {
    const normalized = text.toLowerCase();
    if (TRUE_VALUES.has(normalized) || TRUE_VALUES.has(text)) return true;
    if (FALSE_VALUES.has(normalized) || FALSE_VALUES.has(text)) return false;
    return text;
  }
  if (normalizedType.includes('number') || normalizedType.includes('float') || normalizedType.includes('double')) {
    const number = Number(text.replace(/,/g, ''));
    return Number.isFinite(number) ? number : text;
  }
  if (normalizedType.includes('int')) {
    const number = Number.parseInt(text.replace(/,/g, ''), 10);
    return Number.isFinite(number) ? number : text;
  }
  return value == null ? '' : text;
}

function splitLine(line, separator) {
  if (separator === '\t') return line.split('\t');
  const cells = [];
  let cell = '';
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (char === '"' && line[index + 1] === '"' && quoted) {
      cell += '"';
      index += 1;
    } else if (char === '"') {
      quoted = !quoted;
    } else if (char === separator && !quoted) {
      cells.push(cell);
      cell = '';
    } else {
      cell += char;
    }
  }
  cells.push(cell);
  return cells;
}

export function parseClipboardTable(text, schema = {}) {
  const source = String(text || '').replace(/\r\n?/g, '\n').trim();
  if (!source) return { headers: [], rows: [], ignoredColumns: [], missingColumns: [] };
  const lines = source.split('\n').filter((line) => line.trim());
  const separator = lines[0].includes('\t') ? '\t' : ',';
  const headers = splitLine(lines[0], separator).map((value) => String(value || '').trim());
  const schemaFields = schema?.fields || {};
  const headerMap = new Map();
  Object.keys(schemaFields).forEach((field) => {
    headerMap.set(field.toLowerCase(), field);
    const label = String(schema?.labels?.[field] || '').trim();
    if (label) headerMap.set(label.toLowerCase(), field);
  });
  const mapped = headers.map((header) => headerMap.get(header.toLowerCase()) || null);
  const ignoredColumns = headers.filter((_, index) => !mapped[index]);
  const rows = lines.slice(1).map((line) => {
    const cells = splitLine(line, separator);
    return Object.fromEntries(mapped
      .map((field, index) => [field, field ? coerceClipboardValue(cells[index], schemaFields[field]) : undefined])
      .filter(([field]) => field));
  }).filter((row) => Object.values(row).some((value) => String(value ?? '').trim() !== ''));
  const missingColumns = Object.keys(schemaFields).filter((field) => !mapped.includes(field));
  return { headers, rows, ignoredColumns, missingColumns };
}

export function mergeRowsBySchema(existingRows = [], pastedRows = [], schema = {}, mode = 'append') {
  const fields = Object.keys(schema?.fields || {});
  const normalizedPasted = pastedRows.map((row) => Object.fromEntries(fields
    .filter((field) => Object.prototype.hasOwnProperty.call(row, field))
    .map((field) => [field, row[field]])));
  if (mode === 'replace') return normalizedPasted;
  return existingRows.filter((row) => row && typeof row === 'object').concat(normalizedPasted);
}

export function serializeRowsForClipboard(rows = [], columns = []) {
  const fields = columns.length ? columns : Object.keys(rows[0] || {});
  return [fields.join('\t'), ...rows.map((row) => fields.map((field) => String(row?.[field] ?? '')).join('\t'))].join('\n');
}
