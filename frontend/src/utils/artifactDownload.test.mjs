import assert from 'node:assert/strict'

import { downloadArtifactToBrowser } from './artifactDownload.mjs'

const calls = []
const documentRef = {
  body: {
    appendChild(node) {
      calls.push(['append', node])
    },
    removeChild(node) {
      calls.push(['remove', node])
    },
  },
  createElement() {
    return {
      click() {
        calls.push(['click', this])
      },
    }
  },
}
const urlApi = {
  createObjectURL(blob) {
    calls.push(['createObjectURL', blob])
    return 'blob:test-artifact'
  },
  revokeObjectURL(url) {
    calls.push(['revokeObjectURL', url])
  },
}
const blob = new Blob(['a,b\n1,2\n'], { type: 'text/csv' })
let requestedArtifactId = ''

await downloadArtifactToBrowser({
  artifactId: 'artifact-csv-1',
  fallbackName: 'result.csv',
  download: async (artifactId) => {
    requestedArtifactId = artifactId
    return { blob, filename: 'predictions.csv', contentType: 'text/csv' }
  },
  documentRef,
  urlApi,
})

assert.equal(requestedArtifactId, 'artifact-csv-1')
const anchor = calls.find(([type]) => type === 'append')[1]
assert.equal(anchor.href, 'blob:test-artifact')
assert.equal(anchor.download, 'predictions.csv')
assert.ok(calls.some(([type]) => type === 'click'))
assert.deepEqual(calls.at(-1), ['revokeObjectURL', 'blob:test-artifact'])

console.log('artifact download tests passed')
