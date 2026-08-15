import assert from 'node:assert/strict'
import test from 'node:test'

import {
  AUTH_EXPIRED_EVENT_NAME,
  emitAuthExpired,
  isUnauthorizedStatus,
} from './apiAuth.mjs'
import { shouldAbortDialogueInitialization } from './dialogueInit.mjs'

test('emits one auth-expired event after clearing the session', () => {
  const events = []
  globalThis.window = { dispatchEvent: (event) => events.push(event) }
  let cleared = false

  emitAuthExpired(() => { cleared = true })

  assert.equal(cleared, true)
  assert.equal(events.length, 1)
  assert.equal(events[0].type, AUTH_EXPIRED_EVENT_NAME)

  delete globalThis.window
})

test('recognizes unauthorized HTTP status', () => {
  assert.equal(isUnauthorizedStatus(401), true)
  assert.equal(isUnauthorizedStatus(403), false)
  assert.equal(isUnauthorizedStatus(undefined), false)
})

test('aborts dialogue initialization when any loader rejects with 401', () => {
  assert.equal(
    shouldAbortDialogueInitialization([
      { status: 'fulfilled', value: null },
      { status: 'rejected', reason: { status: 401 } },
    ]),
    true,
  )
  assert.equal(
    shouldAbortDialogueInitialization([
      { status: 'rejected', reason: { status: 422 } },
    ]),
    false,
  )
})
