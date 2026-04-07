import { createFileRoute, useRouter } from '@tanstack/react-router'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ChevronDown,
  Download,
  FileText,
  HardDrive,
  LogOut,
  RefreshCw,
  Server,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import { Badge } from '#/components/ui/badge'
import { Button } from '#/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '#/components/ui/dialog'
import { Input } from '#/components/ui/input'
import { ScrollArea } from '#/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '#/components/ui/select'
import {
  apiDeleteFile,
  apiDownloadChunk,
  apiDownloadFile,
  apiInitUpload,
  apiListFiles,
  apiUploadChunk,
  chunkFile,
  clearTokens,
  formatBytes,
  getMasterUrl,
  getRefreshToken,
  syncAccessToken,
  type DeleteChunkInfo,
  type FileMetadata,
} from '#/lib/api'

export const Route = createFileRoute('/')({ component: DashboardPage })

// ===== Types =====

type ChunkState = 'waiting' | 'uploading' | 'done' | 'error'

interface LogEntry {
  id: number
  level: 'info' | 'ok' | 'warn' | 'err'
  msg: string
  time: string
}

let _logId = 0

// ===== Dashboard =====

function DashboardPage() {
  const router = useRouter()

  useEffect(() => {
    if (!getRefreshToken()) {
      router.navigate({ to: '/login' })
      return
    }
    syncAccessToken()
    handleListFiles()
  }, [])

  // Server URL (client-only read)
  const [masterUrl, setMasterUrlDisplay] = useState('http://localhost')
  useEffect(() => { setMasterUrlDisplay(getMasterUrl()) }, [])

  // Files
  const [files, setFiles] = useState<FileMetadata[]>([])
  const [sortBy, setSortBy] = useState('newest')
  const [loadingFiles, setLoadingFiles] = useState(false)

  // Upload
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [numChunks, setNumChunks] = useState(4)
  const [uploading, setUploading] = useState(false)
  const [uploadChunkStates, setUploadChunkStates] = useState<ChunkState[]>([])
  const [isDragOver, setIsDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Download
  const [downloadFileId, setDownloadFileId] = useState('')
  const [downloading, setDownloading] = useState(false)
  const [downloadChunkStates, setDownloadChunkStates] = useState<ChunkState[]>([])

  // Delete
  const [deleteTarget, setDeleteTarget] = useState<FileMetadata | null>(null)
  const [deleting, setDeleting] = useState(false)
  const deletingIds = useRef<Set<string>>(new Set())

  // Log
  const [logEntries, setLogEntries] = useState<LogEntry[]>([])
  const logRef = useRef<HTMLDivElement>(null)

  const log = useCallback((msg: string, level: LogEntry['level'] = 'info') => {
    setLogEntries((prev) => [
      ...prev.slice(-299),
      {
        id: ++_logId,
        level,
        msg,
        time: new Date().toLocaleTimeString('en-US', {
          hour12: false,
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        }),
      },
    ])
  }, [])

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [logEntries])

  function handleLogout() {
    clearTokens()
    router.navigate({ to: '/login' })
  }

  // Sorted file list
  const sortedFiles = [...files].sort((a, b) => {
    if (sortBy === 'newest') return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    if (sortBy === 'oldest') return new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    if (sortBy === 'size') return b.size - a.size
    if (sortBy === 'name') return a.filename.localeCompare(b.filename)
    return 0
  })

  const totalSize = files.reduce((s, f) => s + f.size, 0)

  // ===== Handlers =====

  async function handleListFiles() {
    setLoadingFiles(true)
    try {
      const data = await apiListFiles()
      setFiles(data.files)
      log(`Loaded ${data.files.length} file(s)`, 'ok')
    } catch (e: any) {
      log('Failed to list files: ' + e.message, 'err')
    } finally {
      setLoadingFiles(false)
    }
  }

  function handleFileSelect(file: File) {
    setSelectedFile(file)
    setUploadChunkStates([])
    log(`Selected: ${file.name} (${formatBytes(file.size)})`)
  }

  async function handleUpload() {
    if (!selectedFile) { log('No file selected', 'err'); return }

    const chunkSize = Math.ceil(selectedFile.size / numChunks)
    const chunks = chunkFile(selectedFile, chunkSize)
    const n = chunks.length

    log(`Uploading: ${selectedFile.name} (${formatBytes(selectedFile.size)})`)
    log(`Chunks: ${n} × ~${formatBytes(chunkSize)}`)
    setUploadChunkStates(Array(n).fill('waiting'))
    setUploading(true)

    let chunkTargets
    try {
      log('Step 1: initializing upload with master...')
      const init = await apiInitUpload(selectedFile, chunks)
      if (init.sc) {
        log(`SC token: ${init.sc.token_acquired} — op_id: ${init.sc.op_id}`, 'info')
        log(`SC acks expected: ${init.sc.acks_expected}`, 'info')
      }
      chunkTargets = init.chunks
      log(`file_id: ${init.file_id}`, 'ok')
      chunkTargets.forEach((t, i) =>
        log(`  chunk ${i} → ${t.chunk_id} [${(t.replica_nodes || []).join(', ')}]`),
      )
    } catch (e: any) {
      log('Init upload failed: ' + e.message, 'err')
      setUploading(false)
      return
    }

    log('Step 2: uploading chunks to storage nodes...')
    let success = 0
    for (let i = 0; i < chunkTargets.length; i++) {
      const target = chunkTargets[i]
      const urls = target.presigned_urls?.length ? target.presigned_urls : [target.presigned_url!]
      setUploadChunkStates((prev) => { const s = [...prev]; s[i] = 'uploading'; return s })
      log(`  chunk ${i + 1}/${n} → ${urls.length} replica(s)...`)
      try {
        await Promise.all(urls.map((url) => apiUploadChunk(url, chunks[i])))
        setUploadChunkStates((prev) => { const s = [...prev]; s[i] = 'done'; return s })
        log(`  chunk ${i + 1} stored`, 'ok')
        success++
      } catch (e: any) {
        setUploadChunkStates((prev) => { const s = [...prev]; s[i] = 'error'; return s })
        log(`  chunk ${i + 1} FAILED: ${e.message}`, 'err')
      }
    }

    if (success === n) {
      log(`Upload complete. All ${n} chunk(s) stored.`, 'ok')
      await handleListFiles()
    } else {
      log(`Upload finished with errors. ${success}/${n} succeeded.`, 'err')
    }
    setUploading(false)
  }

  async function handleDownload() {
    const fileId = downloadFileId.trim()
    if (!fileId) { log('No file ID entered', 'err'); return }

    setDownloading(true)
    log(`Fetching metadata for ${fileId}...`)

    let metadata
    try {
      metadata = await apiDownloadFile(fileId)
      log(`File: ${metadata.filename} (${formatBytes(metadata.size)})`, 'ok')
      log(`Total chunks: ${metadata.total_chunks}`)
      setDownloadChunkStates(Array(metadata.chunks.length).fill('waiting'))
    } catch (e: any) {
      log('Download metadata failed: ' + e.message, 'err')
      setDownloading(false)
      return
    }

    const buffers: ArrayBuffer[] = []
    for (let i = 0; i < metadata.chunks.length; i++) {
      const { presigned_url } = metadata.chunks[i]
      setDownloadChunkStates((prev) => { const s = [...prev]; s[i] = 'uploading'; return s })
      log(`  downloading chunk ${i + 1}/${metadata.chunks.length}...`)
      try {
        const buf = await apiDownloadChunk(presigned_url)
        buffers.push(buf)
        setDownloadChunkStates((prev) => { const s = [...prev]; s[i] = 'done'; return s })
      } catch (e: any) {
        log(`  chunk ${i + 1} FAILED: ${e.message}`, 'err')
        setDownloadChunkStates((prev) => { const s = [...prev]; s[i] = 'error'; return s })
      }
    }

    const blob = new Blob(buffers)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = metadata.filename
    a.click()
    URL.revokeObjectURL(url)
    log(`Download complete: ${metadata.filename}`, 'ok')
    setDownloading(false)
  }

  async function confirmDelete() {
    if (!deleteTarget) return
    const { file_id, filename } = deleteTarget

    if (deletingIds.current.has(file_id)) {
      log(`Delete already in progress: ${filename}`, 'warn')
      setDeleteTarget(null)
      return
    }

    deletingIds.current.add(file_id)
    setDeleting(true)
    setDeleteTarget(null)
    log(`Deleting: ${filename}`, 'warn')
    log('Step 1: sending delete request to leader...')

    try {
      const data = await apiDeleteFile(file_id)
      if (data.already_deleted) {
        log(`Already deleted: ${filename}`, 'warn')
        await handleListFiles()
        return
      }
      log('Step 2: leader coordinated replica deletion', 'info')
      logDeleteChunks(data.chunks || [])
      log('Step 3: metadata removed from leader database', 'info')
      log(`Delete complete: ${filename}`, 'ok')
      await handleListFiles()
    } catch (e: any) {
      log(`Delete failed: ${e.message}`, 'err')
      await handleListFiles()
    } finally {
      deletingIds.current.delete(file_id)
      setDeleting(false)
    }
  }

  function logDeleteChunks(chunks: DeleteChunkInfo[]) {
    chunks.forEach((chunk) => {
      log(`  chunk ${chunk.order + 1} (${chunk.chunk_id})`, 'info')
      ;(chunk.replicas || []).forEach((r) => {
        const n = r.node || 'unknown'
        if (r.status === 'deleted')  log(`    ${n} → deleted`, 'ok')
        else if (r.status === 'missing') log(`    ${n} → already missing`, 'warn')
        else if (r.status === 'skipped') log(`    ${n} → skipped`, 'warn')
        else log(`    ${n} → error (${r.message})`, 'err')
      })
    })
  }

  // ===== Render =====

  return (
    <div className="min-h-screen" style={{ background: 'var(--bg-base)' }}>

      {/* Header */}
      <header className="app-header">
        <div className="page-wrap flex items-center gap-3 h-14 px-4">
          <div className="flex items-center gap-2 flex-shrink-0">
            <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center shadow-[0_2px_8px_rgba(37,99,235,0.35)]">
              <NodeIcon />
            </div>
            <span className="font-bold text-gray-900 text-sm tracking-tight hidden sm:block" style={{ fontFamily: 'Syne, sans-serif' }}>
              DFS
            </span>
          </div>

          <div className="h-4 w-px bg-gray-200 mx-1 flex-shrink-0" />

          <div className="flex items-center gap-1.5 rounded-full border border-gray-200 bg-gray-50 px-3 py-1 text-xs font-mono text-gray-500" suppressHydrationWarning>
            <Server size={11} className="text-blue-500 flex-shrink-0" />
            <span className="truncate max-w-[180px]" suppressHydrationWarning>{masterUrl}</span>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <Badge
              variant="secondary"
              className="text-xs font-mono hidden sm:flex border-blue-100 text-blue-600 bg-blue-50"
            >
              {files.length} file{files.length !== 1 ? 's' : ''} · {formatBytes(totalSize)}
            </Badge>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleLogout}
              className="text-gray-400 hover:text-red-600 hover:bg-red-50 h-8 gap-1.5 text-xs"
            >
              <LogOut size={13} />
              <span className="hidden sm:inline">Logout</span>
            </Button>
          </div>
        </div>
      </header>

      {/* Page */}
      <main className="page-wrap px-4 py-6 space-y-5">

        {/* Row 1: Upload + Files */}
        <div className="grid gap-5 lg:grid-cols-2">

          {/* Upload */}
          <div className="card-shell p-6 fade-up">
            <SectionHeader icon={<Upload size={14} />} title="Upload File" />

            {/* Drop zone */}
            <div
              className={`drop-zone p-7 text-center mb-4 ${isDragOver ? 'drag-over' : ''}`}
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setIsDragOver(true) }}
              onDragLeave={() => setIsDragOver(false)}
              onDrop={(e) => {
                e.preventDefault()
                setIsDragOver(false)
                const file = e.dataTransfer.files[0]
                if (file) handleFileSelect(file)
              }}
            >
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                onChange={(e) => { if (e.target.files?.[0]) handleFileSelect(e.target.files[0]) }}
              />
              {selectedFile ? (
                <div className="flex items-center gap-3 justify-center">
                  <FileText size={18} className="text-blue-500 flex-shrink-0" />
                  <div className="text-left min-w-0">
                    <p className="font-semibold text-gray-800 text-sm truncate max-w-[180px]">{selectedFile.name}</p>
                    <p className="text-gray-400 text-xs mt-0.5">{formatBytes(selectedFile.size)}</p>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      setSelectedFile(null)
                      setUploadChunkStates([])
                    }}
                    className="ml-auto p-1.5 rounded-md text-gray-300 hover:text-red-500 hover:bg-red-50 transition-colors"
                  >
                    <X size={13} />
                  </button>
                </div>
              ) : (
                <>
                  <div className="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center mx-auto mb-3">
                    <Upload size={18} className="text-blue-500" />
                  </div>
                  <p className="text-sm text-gray-500">
                    <span className="text-blue-600 font-semibold">Click to choose</span> or drag and drop
                  </p>
                  <p className="text-xs text-gray-400 mt-1">Any file type supported</p>
                </>
              )}
            </div>

            {/* Chunk count */}
            <div className="flex items-center gap-3 mb-4">
              <label className="text-[11px] font-bold text-gray-400 uppercase tracking-widest whitespace-nowrap">
                Chunks
              </label>
              <input
                type="number"
                value={numChunks}
                min={1}
                max={32}
                onChange={(e) => setNumChunks(parseInt(e.target.value) || 1)}
                className="w-20 h-9 rounded-lg border border-gray-200 px-3 text-sm font-mono text-center bg-white focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-100 transition"
              />
              <span className="text-xs text-gray-400">equal splits</span>
            </div>

            <Button
              onClick={handleUpload}
              disabled={uploading || !selectedFile}
              className="w-full h-10 bg-blue-600 hover:bg-blue-700 text-white font-semibold gap-2 shadow-[0_2px_10px_rgba(37,99,235,0.25)] transition-all"
            >
              {uploading ? <><Spinner /> Uploading...</> : <><Upload size={14} /> Upload</>}
            </Button>

            <ChunkProgress states={uploadChunkStates} label="Upload Progress" />
          </div>

          {/* My Files */}
          <div className="card-shell p-6 fade-up" style={{ animationDelay: '70ms' }}>
            <div className="flex items-center gap-2 mb-5">
              <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center flex-shrink-0">
                <HardDrive size={14} className="text-blue-600" />
              </div>
              <h2 className="font-bold text-gray-900 text-[15px] flex-1" style={{ fontFamily: 'Syne, sans-serif' }}>
                My Files
              </h2>
              <Select value={sortBy} onValueChange={setSortBy}>
                <SelectTrigger className="h-8 text-xs w-[136px] border-gray-200">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="newest">Newest first</SelectItem>
                  <SelectItem value="oldest">Oldest first</SelectItem>
                  <SelectItem value="name">Name A–Z</SelectItem>
                  <SelectItem value="size">Largest first</SelectItem>
                </SelectContent>
              </Select>
              <Button
                variant="outline"
                size="sm"
                onClick={handleListFiles}
                disabled={loadingFiles}
                className="h-8 w-8 p-0 border-gray-200 flex-shrink-0"
                title="Refresh"
              >
                <RefreshCw size={12} className={loadingFiles ? 'animate-spin' : ''} />
              </Button>
            </div>

            <ScrollArea className="h-[290px]">
              {files.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full py-14 text-center">
                  <div className="w-12 h-12 rounded-full bg-gray-100 flex items-center justify-center mb-3">
                    <HardDrive size={20} className="text-gray-300" />
                  </div>
                  <p className="text-sm text-gray-400 font-medium">No files yet</p>
                  <p className="text-xs text-gray-300 mt-1">Upload a file or click refresh</p>
                </div>
              ) : (
                <div className="space-y-0.5 pr-1">
                  {sortedFiles.map((file) => (
                    <FileRow
                      key={file.file_id}
                      file={file}
                      isDeleting={deletingIds.current.has(file.file_id)}
                      onSelectForDownload={() => setDownloadFileId(file.file_id)}
                      onDelete={() => setDeleteTarget(file)}
                    />
                  ))}
                </div>
              )}
            </ScrollArea>
          </div>
        </div>

        {/* Row 2: Download */}
        <div className="card-shell p-6 fade-up" style={{ animationDelay: '140ms' }}>
          <SectionHeader icon={<Download size={14} />} title="Download File" />

          <div className="flex gap-3">
            <Input
              value={downloadFileId}
              onChange={(e) => setDownloadFileId(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleDownload()}
              placeholder="Paste file_id here..."
              className="font-mono text-sm border-gray-200 focus-visible:ring-blue-500/30 focus-visible:border-blue-400 flex-1"
            />
            <Button
              onClick={handleDownload}
              disabled={downloading || !downloadFileId.trim()}
              className="bg-blue-600 hover:bg-blue-700 text-white font-semibold gap-2 px-5 flex-shrink-0 shadow-[0_2px_10px_rgba(37,99,235,0.25)]"
            >
              {downloading ? <><Spinner /> Downloading...</> : <><Download size={14} /> Download</>}
            </Button>
          </div>

          <ChunkProgress states={downloadChunkStates} label="Download Progress" />
        </div>

        {/* Row 3: Activity Log */}
        <div className="card-shell overflow-hidden fade-up" style={{ animationDelay: '210ms' }}>
          <div className="flex items-center gap-2 px-5 py-3.5 border-b" style={{ borderColor: 'var(--line)' }}>
            <div className="w-2 h-2 rounded-full bg-emerald-400 flex-shrink-0" style={{ animation: 'chunk-pulse 2s ease-in-out infinite' }} />
            <h2 className="font-bold text-gray-900 text-sm" style={{ fontFamily: 'Syne, sans-serif' }}>
              Activity Log
            </h2>
            <span className="ml-auto text-xs text-gray-400">{logEntries.length} events</span>
            {logEntries.length > 0 && (
              <button
                onClick={() => setLogEntries([])}
                className="text-xs text-gray-300 hover:text-gray-500 ml-2 transition-colors"
              >
                Clear
              </button>
            )}
          </div>
          <div ref={logRef} className="log-panel px-5 py-4 h-48 overflow-y-auto">
            {logEntries.length === 0 ? (
              <span className="log-line-info opacity-40">System ready. Perform an action to see activity.</span>
            ) : (
              logEntries.map((e) => (
                <div key={e.id} className={`log-line-${e.level}`}>
                  <span className="opacity-30 select-none mr-2">{e.time}</span>
                  {e.msg}
                </div>
              ))
            )}
          </div>
        </div>
      </main>

      {/* Delete Dialog */}
      <Dialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Delete file?</DialogTitle>
            <DialogDescription className="pt-1">
              This will permanently delete{' '}
              <span className="font-semibold text-gray-900">{deleteTarget?.filename}</span>{' '}
              ({deleteTarget ? formatBytes(deleteTarget.size) : ''}) and all its replicas across the cluster.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 pt-2">
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={confirmDelete} disabled={deleting}>
              {deleting ? 'Deleting...' : 'Delete permanently'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ===== Sub-components =====

function SectionHeader({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2 mb-5">
      <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center flex-shrink-0 text-blue-600">
        {icon}
      </div>
      <h2 className="font-bold text-gray-900 text-[15px]" style={{ fontFamily: 'Syne, sans-serif' }}>
        {title}
      </h2>
    </div>
  )
}

function ChunkProgress({ states, label }: { states: ChunkState[]; label: string }) {
  if (states.length === 0) return null
  return (
    <div className="mt-4 space-y-2">
      <p className="text-[11px] font-bold text-gray-400 uppercase tracking-widest">{label}</p>
      {states.map((state, i) => (
        <div key={i} className="flex items-center gap-3">
          <span className="text-xs font-mono text-gray-400 w-[70px] flex-shrink-0">
            {i + 1}/{states.length}
          </span>
          <div className="chunk-pill flex-1">
            <div className={`chunk-pill-inner ${state !== 'waiting' ? state : ''}`} />
          </div>
          <span
            className={`text-[11px] font-semibold w-16 text-right flex-shrink-0 ${
              state === 'done'      ? 'text-emerald-500' :
              state === 'error'     ? 'text-red-500' :
              state === 'uploading' ? 'text-blue-500' :
              'text-gray-300'
            }`}
          >
            {state}
          </span>
        </div>
      ))}
    </div>
  )
}

function FileRow({
  file,
  isDeleting,
  onSelectForDownload,
  onDelete,
}: {
  file: FileMetadata
  isDeleting: boolean
  onSelectForDownload: () => void
  onDelete: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const hasChunks = (file.chunks || []).length > 0

  return (
    <div className="rounded-xl border border-transparent hover:border-blue-100 hover:bg-[#EFF6FF] transition-all">
      <div className="flex items-center gap-2.5 px-3 py-2.5">
        <FileText size={13} className="text-blue-400 flex-shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-gray-800 truncate leading-snug">{file.filename}</p>
          <p className="text-[11px] text-gray-400 font-mono mt-0.5">
            {formatBytes(file.size)}
            {file.created_at && (
              <span className="ml-2 opacity-70">{new Date(file.created_at).toLocaleDateString()}</span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-0.5 flex-shrink-0">
          {hasChunks && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="p-1.5 rounded-md text-gray-300 hover:text-blue-500 hover:bg-blue-50 transition-colors"
              title="View chunk topology"
            >
              <ChevronDown
                size={12}
                style={{ transition: 'transform 180ms ease', transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)' }}
              />
            </button>
          )}
          <button
            onClick={onSelectForDownload}
            className="p-1.5 rounded-md text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors"
            title="Fill download ID"
          >
            <Download size={12} />
          </button>
          <button
            onClick={onDelete}
            disabled={isDeleting}
            className="p-1.5 rounded-md text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors disabled:opacity-30"
            title="Delete"
          >
            <Trash2 size={12} />
          </button>
        </div>
      </div>

      {expanded && hasChunks && (
        <div className="px-3 pb-3 pt-0 space-y-1.5">
          {(file.chunks || []).map((chunk) => (
            <div key={chunk.chunk_id} className="flex items-start gap-2 ml-5">
              <div className="w-1.5 h-1.5 rounded-full bg-blue-300 mt-[5px] flex-shrink-0" />
              <span className="text-[11px] text-gray-400 font-mono leading-tight">
                chunk {chunk.order}:{' '}
                {chunk.replica_nodes.map((n, i) => (
                  <span key={n}>
                    <span className="text-blue-500">{n}</span>
                    {i < chunk.replica_nodes.length - 1 && <span className="text-gray-300">, </span>}
                  </span>
                ))}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function NodeIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 20 20" fill="none">
      <circle cx="10" cy="4"  r="2.5" fill="white" />
      <circle cx="3"  cy="15" r="2.5" fill="white" />
      <circle cx="17" cy="15" r="2.5" fill="white" />
      <line x1="10" y1="4" x2="3"  y2="15" stroke="white" strokeWidth="1.4" strokeOpacity="0.65" />
      <line x1="10" y1="4" x2="17" y2="15" stroke="white" strokeWidth="1.4" strokeOpacity="0.65" />
      <line x1="3"  y1="15" x2="17" y2="15" stroke="white" strokeWidth="1.4" strokeOpacity="0.65" />
    </svg>
  )
}

function Spinner() {
  return (
    <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeOpacity="0.25" />
      <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}
