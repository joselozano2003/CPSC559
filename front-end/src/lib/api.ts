// ===== Types =====

export interface LoginResponse {
  tokens: { access: string; refresh: string }
  user: { email: string; id: number }
}

export interface ChunkReplica {
  chunk_id: string
  order: number
  replica_nodes: string[]
}

export interface FileMetadata {
  file_id: string
  filename: string
  size: number
  created_at: string
  chunks?: ChunkReplica[]
}

export interface FileListResponse {
  files: FileMetadata[]
}

export interface UploadChunkTarget {
  chunk_id: string
  order: number
  presigned_url?: string
  presigned_urls?: string[]
  replica_nodes?: string[]
}

export interface SCToken {
  token_acquired: boolean
  op_id: string
  acks_expected: number
  acks_received_or_timed_out: boolean
}

export interface UploadInitResponse {
  file_id: string
  chunks: UploadChunkTarget[]
  sc?: SCToken
}

export interface DownloadChunk {
  presigned_url: string
  order: number
  expected_hash?: string | null
}

export interface DownloadMetadata {
  filename: string
  size: number
  total_chunks: number
  chunks: DownloadChunk[]
}

export interface DeleteReplicaInfo {
  node: string
  status: 'deleted' | 'missing' | 'skipped' | 'error'
  message?: string
}

export interface DeleteChunkInfo {
  chunk_id: string
  order: number
  replicas?: DeleteReplicaInfo[]
}

export interface DeleteResponse {
  success: boolean
  already_deleted?: boolean
  file_id: string
  message?: string
  chunks?: DeleteChunkInfo[]
}

// ===== Integrity =====

export async function sha256Hex(buffer: ArrayBuffer): Promise<string> {
  const hashBuffer = await crypto.subtle.digest('SHA-256', buffer)
  return Array.from(new Uint8Array(hashBuffer))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

// ===== Storage Helpers (SSR-safe) =====

function store(key: string): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem(key)
}

function storeSet(key: string, val: string): void {
  if (typeof window === 'undefined') return
  localStorage.setItem(key, val)
}

function storeDel(key: string): void {
  if (typeof window === 'undefined') return
  localStorage.removeItem(key)
}

// ===== Auth Helpers =====

export function getMasterUrl(): string {
  return store('masterUrl') || 'http://localhost:8080'
}

export function setMasterUrl(url: string): void {
  storeSet('masterUrl', url)
}

export function getAccessToken(): string | null {
  return store('accessToken')
}

export function getRefreshToken(): string | null {
  return store('refreshToken')
}

export function setTokens(access: string, refresh: string): void {
  storeSet('accessToken', access)
  storeSet('refreshToken', refresh)
}

export function clearTokens(): void {
  storeDel('accessToken')
  storeDel('refreshToken')
  storeDel('masterUrl')
}

// ===== Token Refresh =====

let _accessToken: string | null = null

export function syncAccessToken(): void {
  _accessToken = store('accessToken')
}

export async function refresh(): Promise<void> {
  const refreshToken = store('refreshToken')
  if (!refreshToken) throw new Error('No refresh token')

  const res = await fetch(`${getMasterUrl()}/auth/token/refresh/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh: refreshToken }),
  })

  const data = await res.json()
  if (!res.ok) {
    clearTokens()
    throw new Error('Token refresh failed')
  }

  _accessToken = data.access
  storeSet('accessToken', data.access)
}

export async function fetchWithAuth(url: string, options: RequestInit = {}): Promise<Response> {
  if (!_accessToken) _accessToken = store('accessToken')

  let res = await fetch(url, {
    ...options,
    headers: { ...(options.headers || {}), Authorization: `Bearer ${_accessToken}` },
  })

  if (res.status === 401) {
    await refresh()
    res = await fetch(url, {
      ...options,
      headers: { ...(options.headers || {}), Authorization: `Bearer ${_accessToken}` },
    })
  }

  return res
}

// ===== Helpers =====

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1048576).toFixed(2) + ' MB'
}

export function chunkFile(file: File, chunkSize: number): Blob[] {
  const chunks: Blob[] = []
  let offset = 0
  while (offset < file.size) {
    chunks.push(file.slice(offset, offset + chunkSize))
    offset += chunkSize
  }
  return chunks
}

// ===== API Calls =====

export async function apiLogin(
  email: string,
  password: string,
  masterUrl: string,
): Promise<LoginResponse> {
  const res = await fetch(`${masterUrl}/auth/login/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) throw new Error(`Login failed: ${res.status}`)
  return res.json()
}

export async function apiListFiles(): Promise<FileListResponse> {
  const res = await fetchWithAuth(`${getMasterUrl()}/files/`)
  if (!res.ok) throw new Error('Failed to fetch files')
  return res.json()
}

export async function apiInitUpload(file: File, chunks: Blob[], hashes: string[]): Promise<UploadInitResponse> {
  const chunksMetadata = chunks.map((blob, i) => ({
    temp_chunk_id: `tmp_${i}_${Date.now()}`,
    order: i,
    size: blob.size,
    hash: hashes[i],
  }))

  const res = await fetchWithAuth(`${getMasterUrl()}/files/upload/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename: file.name, size: file.size, chunks: chunksMetadata }),
  })

  if (!res.ok) throw new Error('Upload init failed: ' + res.status)
  return res.json()
}

export async function apiUploadChunk(presignedUrl: string, chunkBlob: Blob): Promise<void> {
  console.log(`Uploading chunk to ${presignedUrl} with size ${chunkBlob.size} bytes`)
  let res: Response
  try {
    res = await fetch(presignedUrl, { method: 'PUT', body: chunkBlob })
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    throw new Error(`Chunk upload network error. This is often a MinIO CORS issue: ${message}`)
  }

  if (!res.ok) {
    const details = await res.text().catch(() => '')
    throw new Error(`Chunk upload failed: ${res.status}${details ? ` ${details}` : ''}`)
  }
}

export async function apiDownloadFile(fileId: string): Promise<DownloadMetadata> {
  const res = await fetchWithAuth(`${getMasterUrl()}/files/${fileId}/download/`)
  if (!res.ok) throw new Error('Download failed: ' + res.status)
  return res.json()
}

export async function apiDownloadChunk(presignedUrl: string): Promise<ArrayBuffer> {
  const res = await fetch(presignedUrl)
  if (!res.ok) throw new Error(`Chunk download failed: ${res.status}`)
  return res.arrayBuffer()
}

export async function apiDeleteFile(fileId: string): Promise<DeleteResponse> {
  const res = await fetchWithAuth(`${getMasterUrl()}/files/${fileId}/delete/`, {
    method: 'DELETE',
  })

  if (res.status === 404) {
    return {
      success: true,
      already_deleted: true,
      file_id: fileId,
      message: 'File was already deleted',
      chunks: [],
    }
  }

  if (!res.ok) throw new Error('Delete failed: ' + res.status)
  return res.json()
}
