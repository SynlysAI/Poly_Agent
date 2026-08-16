import assert from 'node:assert/strict'

import {
  ALGORITHM_TIMEOUT_BUFFER_SECONDS,
  DEFAULT_ALGORITHM_TIMEOUT_SECONDS,
  resolveAlgorithmRunTimeoutMs,
} from './apiTimeout.mjs'

assert.equal(resolveAlgorithmRunTimeoutMs(300), 310_000)
assert.equal(resolveAlgorithmRunTimeoutMs(30), 40_000)
assert.equal(resolveAlgorithmRunTimeoutMs(60.5), 70_500)
assert.equal(resolveAlgorithmRunTimeoutMs(0), (DEFAULT_ALGORITHM_TIMEOUT_SECONDS + ALGORITHM_TIMEOUT_BUFFER_SECONDS) * 1000)
assert.equal(resolveAlgorithmRunTimeoutMs(undefined), (DEFAULT_ALGORITHM_TIMEOUT_SECONDS + ALGORITHM_TIMEOUT_BUFFER_SECONDS) * 1000)
assert.equal(resolveAlgorithmRunTimeoutMs('120'), 130_000)
assert.equal(resolveAlgorithmRunTimeoutMs(30, 0), 30_000)

console.log('apiTimeout tests passed')
