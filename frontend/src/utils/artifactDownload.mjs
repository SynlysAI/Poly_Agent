/**
 * Download an authenticated artifact response through a browser Blob URL.
 * Keeping the request in the caller-provided function ensures the API client
 * can attach its Authorization header before the browser starts saving.
 */
export async function downloadArtifactToBrowser({
  artifactId,
  fallbackName = 'artifact.dat',
  download,
  documentRef = globalThis.document,
  urlApi = globalThis.URL,
}) {
  const data = await download(artifactId)
  const blob = data.blob instanceof Blob
    ? data.blob
    : new Blob([data.blob], { type: data.contentType || 'application/octet-stream' })
  const url = urlApi.createObjectURL(blob)
  const link = documentRef.createElement('a')
  link.href = url
  link.download = data.filename || fallbackName
  documentRef.body.appendChild(link)
  try {
    link.click()
  } finally {
    documentRef.body.removeChild(link)
    urlApi.revokeObjectURL(url)
  }
  return data
}
