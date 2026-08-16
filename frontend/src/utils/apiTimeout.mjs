/**
 * 算法运行 / 接口测试请求超时计算工具。
 *
 * 后端算法契约声明 runtime.timeout_seconds，前端 HTTP 请求必须预留额外缓冲，
 * 否则后端仍在正常执行时，前端会先触发 axios 超时并误报「请求超时」。
 */

export const DEFAULT_ALGORITHM_TIMEOUT_SECONDS = 60
export const ALGORITHM_TIMEOUT_BUFFER_SECONDS = 10

/**
 * 根据算法契约超时计算 axios timeout。
 *
 * Args:
 *   timeoutSeconds: 算法契约中的 runtime.timeout_seconds。
 *   bufferSeconds: 前端额外预留的缓冲秒数。
 *
 * Returns:
 *   axios timeout 毫秒数。
 */
export function resolveAlgorithmRunTimeoutMs(
  timeoutSeconds,
  bufferSeconds = ALGORITHM_TIMEOUT_BUFFER_SECONDS,
) {
  const parsedTimeoutSeconds = Number(timeoutSeconds)
  const parsedBufferSeconds = Number(bufferSeconds)
  const contractSeconds = Number.isFinite(parsedTimeoutSeconds) && parsedTimeoutSeconds > 0
    ? parsedTimeoutSeconds
    : DEFAULT_ALGORITHM_TIMEOUT_SECONDS
  const safeBufferSeconds = Number.isFinite(parsedBufferSeconds) && parsedBufferSeconds > 0
    ? parsedBufferSeconds
    : 0
  return Math.ceil((contractSeconds + safeBufferSeconds) * 1000)
}
