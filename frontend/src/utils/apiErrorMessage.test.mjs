import assert from 'node:assert/strict'

import { getApiErrorMessage } from './apiErrorMessage.js'

const MODEL_ID_CONFLICT_DETAIL = "模型 ID 'demo_alg' 已存在，请从模型详情使用“上传新版本”流程"

function apiError(overrides = {}) {
  return {
    isApiError: true,
    kind: 'http',
    status: 409,
    message: 'internal error',
    ...overrides,
  }
}

// 409：后端统一错误响应 message 为通用文案时，仍展示中文 detail
assert.equal(
  getApiErrorMessage(apiError({ detail: MODEL_ID_CONFLICT_DETAIL })),
  `状态冲突：${MODEL_ID_CONFLICT_DETAIL}`,
)

// 409：后端 message 修正为 "conflict" 后，中文 detail 仍应优先展示
assert.equal(
  getApiErrorMessage(apiError({ message: 'conflict', detail: MODEL_ID_CONFLICT_DETAIL })),
  `状态冲突：${MODEL_ID_CONFLICT_DETAIL}`,
)

// 409：detail 为对象时取可读的 message 字段
assert.equal(
  getApiErrorMessage(apiError({ detail: { message: MODEL_ID_CONFLICT_DETAIL } })),
  `状态冲突：${MODEL_ID_CONFLICT_DETAIL}`,
)

// 422：errors 数组优先展示字段级校验明细
assert.equal(
  getApiErrorMessage(
    apiError({
      status: 422,
      message: 'validation failed',
      detail: 'request validation failed',
      errors: [{ loc: ['body', 'version'], msg: 'field required', type: 'value_error.missing' }],
    }),
  ),
  '参数校验失败：[body.version] field required',
)

// 无 detail 时回退到 error.message
assert.equal(
  getApiErrorMessage(apiError({ status: 400, message: 'invalid parameter', detail: undefined })),
  '参数有误：invalid parameter',
)

// 未知状态码直接返回原始消息
assert.equal(getApiErrorMessage(apiError({ status: 418, message: 'teapot' })), 'teapot')

// 网络 / 超时 / 取消 / 空参数 / 非 API 错误的既有兜底文案
assert.equal(getApiErrorMessage({ isApiError: true, kind: 'network' }), '网络连接失败，请检查网络')
assert.equal(getApiErrorMessage({ isApiError: true, kind: 'timeout' }), '请求超时')
assert.equal(getApiErrorMessage({ isApiError: true, kind: 'canceled' }), '请求已取消')
assert.equal(getApiErrorMessage(null), '未知错误')
assert.equal(getApiErrorMessage(undefined), '未知错误')
assert.equal(getApiErrorMessage({ message: 'boom' }), 'boom')
