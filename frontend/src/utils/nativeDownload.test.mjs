import assert from 'node:assert/strict'

import {
  buildAuthenticatedDownloadUrl,
  openNativeDownload,
} from './nativeDownload.mjs'

class Params {
  constructor(initial = {}) {
    this.value = new URLSearchParams(initial)
  }

  set(key, value) {
    this.value.set(key, value)
  }

  toString() {
    return this.value.toString()
  }
}

assert.equal(
  buildAuthenticatedDownloadUrl({
    baseUrl: '/api/v1/',
    path: '/api/v1/assistant/commands/cmd-1/download',
    authorizationHeader: 'Bearer token-1',
    urlSearchParamsCtor: Params,
  }),
  '/api/v1/assistant/commands/cmd-1/download?token=token-1',
)

assert.equal(
  buildAuthenticatedDownloadUrl({
    baseUrl: '/api/v1',
    path: 'assistant/commands/cmd-1/download',
    authorizationHeader: '',
    urlSearchParamsCtor: Params,
  }),
  '/api/v1/assistant/commands/cmd-1/download',
)

const clicks = []
const createdLinks = []
const documentRef = {
  body: {
    appendChild(link) {
      createdLinks.push(link)
    },
    removeChild(link) {
      assert.equal(link, createdLinks[0])
    },
  },
  createElement(tag) {
    return {
      tag,
      href: '',
      download: '',
      rel: '',
      click() {
        clicks.push(this)
      },
    }
  },
}

const url = openNativeDownload({
  url: '/api/v1/assistant/commands/cmd-1/download?token=token-1',
  filename: 'session.zip',
  documentRef,
})
assert.equal(url, createdLinks[0].href)
assert.equal(createdLinks[0].download, 'session.zip')
assert.equal(createdLinks[0].rel, 'noopener')
assert.equal(clicks.length, 1)

console.log('native download tests passed')
