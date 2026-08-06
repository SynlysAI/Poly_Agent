import assert from 'node:assert/strict'

import { findInterfaceExample, INTERFACE_CONFIG_EXAMPLES } from './interfaceConfigExamples.mjs'

const SENSITIVE_PATTERN = /(authorization|token|password|api[-_]?key|secret|credential|signature)/i
const SECRET_REF_PATTERN = /^[A-Z0-9_]+$/
const VERSION_PATTERN = /^\d+\.\d+\.\d+$/
const PROTOCOLS = new Set(['http', 'fastapi', 'mcp'])
const METHODS = new Set(['GET', 'POST', 'PUT', 'PATCH'])
const FIELD_TYPES = new Set(['string', 'number', 'integer', 'boolean', 'object', 'list'])

function declaredInputNames(example) {
  return new Set(example.input_fields.map((row) => String(row.name).trim()).filter(Boolean))
}

function rowsFromMap(mapping) {
  return Object.entries(mapping || {}).map(([key, value]) => ({ key, value }))
}

function hasDuplicateKeys(rows) {
  const seen = new Set()
  for (const row of rows) {
    const key = String(row.key || '').trim().toLowerCase()
    if (!key) continue
    if (seen.has(key)) return true
    seen.add(key)
  }
  return false
}

function mappingReferencesDeclaredInputs(example, rows) {
  const inputNames = declaredInputNames(example)
  return rows.every((row) => inputNames.has(String(row.value || '').trim().split('.')[0]))
}

function mappingHasSensitiveKeys(rows) {
  return rows.some((row) => SENSITIVE_PATTERN.test(String(row.key || '').trim()))
}

assert.ok(INTERFACE_CONFIG_EXAMPLES.length >= 5, '至少提供 5 个示例场景')
assert.equal(new Set(INTERFACE_CONFIG_EXAMPLES.map((item) => item.id)).size, INTERFACE_CONFIG_EXAMPLES.length, '示例 id 必须唯一')
assert.equal(findInterfaceExample('fastapi_smiles')?.id, 'fastapi_smiles')
assert.equal(findInterfaceExample('not-exists'), null)

for (const example of INTERFACE_CONFIG_EXAMPLES) {
  const form = example.form
  assert.ok(example.id && example.title && example.description, `${example.id} 缺少标题或描述`)
  assert.ok(Array.isArray(example.tags) && example.tags.length > 0, `${example.id} 缺少标签`)
  assert.ok(Array.isArray(example.notes) && example.notes.every((note) => typeof note === 'string'), `${example.id} notes 必须是字符串数组`)

  // 版本号与基本信息
  assert.match(form.version, VERSION_PATTERN, `${example.id} 版本号必须是 x.y.z`)
  assert.ok(PROTOCOLS.has(form.protocol), `${example.id} 协议不合法`)
  assert.ok(METHODS.has(form.http_method), `${example.id} 请求方法不合法`)
  assert.ok(Number.isInteger(form.timeout_seconds) && form.timeout_seconds >= 1 && form.timeout_seconds <= 60, `${example.id} 超时必须在 1-60 秒`)
  assert.ok(['private', 'public'].includes(form.visibility), `${example.id} 公开范围不合法`)

  // endpoint 必须是 http/https 且不含凭据
  const url = new URL(form.endpoint_url)
  assert.ok(['http:', 'https:'].includes(url.protocol), `${example.id} endpoint 必须使用 HTTP/HTTPS`)
  assert.equal(url.username, '', `${example.id} endpoint 不能包含用户名`)
  assert.equal(url.password, '', `${example.id} endpoint 不能包含密码`)

  // 样例输入必须是 JSON object，且覆盖全部必填输入字段
  assert.ok(form.sample_input && typeof form.sample_input === 'object' && !Array.isArray(form.sample_input), `${example.id} 样例输入必须是 JSON object`)
  const inputNames = declaredInputNames(example)
  assert.ok(inputNames.size > 0, `${example.id} 至少声明一个输入字段`)
  assert.ok(example.output_fields.length > 0, `${example.id} 至少声明一个输出字段`)
  for (const row of example.input_fields) {
    assert.ok(FIELD_TYPES.has(row.type), `${example.id} 输入字段类型不合法: ${row.name}`)
    if (row.required) {
      assert.ok(
        form.sample_input[String(row.name).trim()] !== undefined && form.sample_input[String(row.name).trim()] !== null,
        `${example.id} 样例输入缺少必填字段 ${row.name}`,
      )
    }
  }
  for (const row of example.output_fields) {
    assert.ok(FIELD_TYPES.has(row.type), `${example.id} 输出字段类型不合法: ${row.name}`)
  }

  // 响应提取路径为空或合法点路径
  if (form.response_selector) {
    assert.ok(form.response_selector.split('.').every((part) => part.length > 0), `${example.id} 响应提取路径格式不正确`)
  }

  // 映射组：无重复键、引用已声明输入、无敏感键、密钥引用格式正确
  const queryRows = rowsFromMap(form.query_bindings)
  const headerRows = rowsFromMap(form.header_bindings)
  const staticHeaderRows = rowsFromMap(form.static_headers)
  const secretRows = rowsFromMap(form.secret_refs)

  assert.ok(!hasDuplicateKeys(queryRows), `${example.id} Query 绑定不能包含重复键`)
  assert.ok(!hasDuplicateKeys(headerRows), `${example.id} Header 绑定不能包含重复键`)
  assert.ok(!hasDuplicateKeys(staticHeaderRows), `${example.id} 静态 Header 不能包含重复键`)
  assert.ok(!hasDuplicateKeys(secretRows), `${example.id} 密钥引用不能包含重复键`)

  assert.ok(mappingReferencesDeclaredInputs(example, queryRows), `${example.id} Query 绑定必须引用已声明的输入字段`)
  assert.ok(mappingReferencesDeclaredInputs(example, headerRows), `${example.id} Header 绑定必须引用已声明的输入字段`)
  assert.ok(!mappingHasSensitiveKeys(queryRows), `${example.id} 认证 Query 不能从普通输入映射`)
  assert.ok(!mappingHasSensitiveKeys(headerRows), `${example.id} 认证 Header 必须使用密钥引用`)
  assert.ok(!mappingHasSensitiveKeys(staticHeaderRows), `${example.id} 静态 Header 不能包含敏感键`)
  assert.ok(secretRows.every((row) => SECRET_REF_PATTERN.test(String(row.value || ''))), `${example.id} 密钥引用必须使用大写字母、数字或下划线`)

  // Header 三类来源之间不能配置同一个键
  const headerKeys = [headerRows, staticHeaderRows, secretRows]
    .map((rows) => new Set(rows.map((row) => String(row.key || '').trim().toLowerCase()).filter(Boolean)))
  headerKeys.forEach((source, index) => {
    headerKeys.slice(index + 1).forEach((other) => {
      source.forEach((key) => assert.ok(!other.has(key), `${example.id} Header 键 ${key} 不能同时配置多个来源`))
    })
  })
}

console.log(`interfaceConfigExamples: ${INTERFACE_CONFIG_EXAMPLES.length} 个示例场景校验通过`)
