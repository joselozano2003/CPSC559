let authToken = localStorage.getItem("accessToken");
let refreshToken = localStorage.getItem("refreshToken");
let cachedFiles = [];
let deletingFiles = new Set();

// ========== Auth / Routing Helpers ==========

function getMasterUrl() {
    return localStorage.getItem("masterUrl") || "http://localhost";
}

function redirectToLogin() {
    window.location.href = "login.html";
}

function handleLogout() {
    authToken = null;
    refreshToken = null;
    cachedFiles = [];

    localStorage.removeItem("accessToken");
    localStorage.removeItem("refreshToken");
    localStorage.removeItem("masterUrl");

    redirectToLogin();
}

async function refresh() {
    const response = await fetch(`${getMasterUrl()}/auth/token/refresh/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            refresh: localStorage.getItem("refreshToken")
        }),
    });

    const data = await response.json();

    if (!response.ok) {
        authToken = null;
        refreshToken = null;
        localStorage.removeItem("accessToken");
        localStorage.removeItem("refreshToken");
        redirectToLogin();
        throw new Error('Token refresh failed.');
    }

    authToken = data.access;
    localStorage.setItem("accessToken", data.access);
}

async function fetchWithAuth(url, options = {}) {
    let res = await fetch(url, {
        ...options,
        headers: {
            ...(options.headers || {}),
            Authorization: `Bearer ${authToken}`,
        },
    });

    if (res.status === 401) {
        await refresh();

        res = await fetch(url, {
            ...options,
            headers: {
                ...(options.headers || {}),
                Authorization: `Bearer ${authToken}`,
            },
        });
    }

    return res;
}

/**
 * used to display message in a log panel on the webpage
 */
function log(msg, level = 'info') {
    const el = document.getElementById('log');
    if (!el) return;

    const line = document.createElement('span');
    line.className = level;
    line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}\n`;
    el.appendChild(line);
    el.scrollTop = el.scrollHeight;
}

// ========== API calls ==========

async function realInitUpload(file, chunks, masterUrl) {
    const chunksMetadata = chunks.map((blob, i) => ({
        temp_chunk_id: `tmp_${i}_${Date.now()}`,
        order: i,
        size: blob.size,
    }));

    const res = await fetchWithAuth(`${masterUrl}/files/upload/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            filename: file.name,
            size: file.size,
            chunks: chunksMetadata,
        }),
    });

    if (!res.ok) {
        throw new Error('Upload init failed: ' + res.status);
    }

    return res.json();
}

async function realUploadChunk(presignedUrl, chunkBlob) {
    const res = await fetch(presignedUrl, {
        method: 'PUT',
        body: chunkBlob,
    });

    if (!res.ok) {
        throw new Error(`Chunk upload failed: ${res.status}`);
    }
}

async function realDownloadFile(fileId, masterUrl) {
    const res = await fetchWithAuth(`${masterUrl}/files/${fileId}/download/`, {
        method: 'GET',
    });

    if (!res.ok) {
        throw new Error('Download failed: ' + res.status);
    }

    return res.json();
}

async function realDownloadChunk(presignedUrl) {
    const res = await fetch(presignedUrl);

    if (!res.ok) {
        throw new Error(`Chunk download failed: ${res.status}`);
    }

    return res.arrayBuffer();
}

async function realListFiles(masterUrl) {
    const res = await fetchWithAuth(`${masterUrl}/files/`, {
        method: 'GET',
    });

    if (!res.ok) {
        throw new Error("Failed to fetch files");
    }

    return res.json();
}

// ========== Helpers ==========

function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(2) + ' MB';
}

function chunkFile(file, chunkSize) {
    const chunks = [];
    let offset = 0;

    while (offset < file.size) {
        chunks.push(file.slice(offset, offset + chunkSize));
        offset += chunkSize;
    }

    return chunks;
}

function renderChunks(numChunks) {
    const list = document.getElementById('chunk-list');
    list.innerHTML = '';

    for (let i = 0; i < numChunks; i++) {
        list.innerHTML += `
        <div class="chunk-row" id="chunk-row-${i}">
            <span class="chunk-label">Chunk ${i + 1}</span>
            <div class="chunk-bar-wrap">
                <div class="chunk-bar" id="chunk-bar-${i}"></div>
            </div>
            <span class="chunk-status" id="chunk-status-${i}">waiting</span>
        </div>`;
    }
}

function setChunkState(index, state) {
    const bar = document.getElementById(`chunk-bar-${index}`);
    const status = document.getElementById(`chunk-status-${index}`);

    if (!bar || !status) return;

    if (state === 'uploading') {
        bar.style.width = '60%';
        bar.className = 'chunk-bar';
        status.textContent = 'uploading';
    } else if (state === 'done') {
        bar.style.width = '100%';
        bar.className = 'chunk-bar done';
        status.textContent = 'done';
    } else if (state === 'error') {
        bar.style.width = '100%';
        bar.className = 'chunk-bar error';
        status.textContent = 'error';
    }
}

function renderFiles() {
    const sortBy = document.getElementById('sort-files').value;
    const container = document.getElementById('user-files');
    const files = [...cachedFiles];

    files.sort((a, b) => {
        if (sortBy === "newest") {
            return new Date(b.created_at) - new Date(a.created_at);
        }
        if (sortBy === "oldest") {
            return new Date(a.created_at) - new Date(b.created_at);
        }
        if (sortBy === "size") {
            return b.size - a.size;
        }
        if (sortBy === "name") {
            return a.filename.localeCompare(b.filename);
        }
        return 0;
    });

    if (files.length === 0) {
        container.style.display = "none";
        container.innerHTML = "";
        return;
    }

    container.style.display = "block";
    container.innerHTML = "";

    files.forEach(file => {
        const div = document.createElement('div');
        div.className = 'file-row';

        const createdAtText = file.created_at
            ? new Date(file.created_at).toLocaleString()
            : 'Unknown date';

        const chunkDetails = (file.chunks || []).map(chunk => `
            <div style="margin-left: 12px; font-size: 12px; color: #888;">
                Chunk ${chunk.order}: ${chunk.replica_nodes.join(', ')}
            </div>
        `).join('');

        div.innerHTML = `
            <span class="file-name">${file.filename}</span>
            <span class="file-size">${formatBytes(file.size)}</span>
            <span class="file-date">${createdAtText}</span>
            <span class="file-download">
                <button onclick="fillDownloadId('${file.file_id}')">
                    Select File
                </button>
                <button onclick="handleDeleteFile('${file.file_id}')">
                    Delete
                </button>
            </span>
            <div style="width: 100%; margin-top: 6px;">
                ${chunkDetails}
            </div>
        `;

        container.appendChild(div);
    });
}

function fillDownloadId(id) {
    document.getElementById("file-id-input").value = id;
}

async function realDeleteFile(fileId, masterUrl) {
    const res = await fetchWithAuth(`${masterUrl}/files/${fileId}/delete/`, {
        method: 'DELETE',
    });

    if (res.status === 404) {
        return {
            success: true,
            already_deleted: true,
            file_id: fileId,
            message: 'File was already deleted',
            chunks: [],
        };
    }

    if (!res.ok) {
        throw new Error('Delete failed: ' + res.status);
    }

    return res.json();
}

async function handleDeleteFile(fileId) {
    const file = cachedFiles.find(f => f.file_id === fileId);
    const displayName = file ? file.filename : fileId;

    if (deletingFiles.has(fileId)) {
        log(`Delete already in progress for: ${displayName}`, 'warn');
        return;
    }

    const confirmed = window.confirm(`Delete ${displayName}?`);
    if (!confirmed) {
        return;
    }

    deletingFiles.add(fileId);

    log(`Deleting file: ${displayName}`, 'warn');
    log(`Step 1: sending delete request to leader...`, 'info');

    try {
        const data = await realDeleteFile(fileId, getMasterUrl());

        if (data.already_deleted) {
            log(`File already deleted: ${displayName}`, 'warn');
            await handleListFiles();
            return;
        }

        log(`Step 2: leader coordinated replica deletion`, 'info');

        if (data.chunks && data.chunks.length > 0) {
            data.chunks.forEach((chunk) => {
                log(`  deleting chunk ${chunk.order + 1}/${data.chunks.length}...`, 'info');
                log(`  chunk ${chunk.order + 1} (${chunk.chunk_id})`, 'info');

                if (chunk.replicas && chunk.replicas.length > 0) {
                    chunk.replicas.forEach(replica => {
                        const nodeName = replica.node || 'unknown-node';

                        if (replica.status === 'deleted') {
                            log(`    ${nodeName} → deleted`, 'ok');
                        } else if (replica.status === 'missing') {
                            log(`    ${nodeName} → already missing`, 'warn');
                        } else if (replica.status === 'skipped') {
                            log(`    ${nodeName} → skipped (${replica.message})`, 'warn');
                        } else {
                            log(`    ${nodeName} → error (${replica.message})`, 'err');
                        }
                    });
                }
            });
        }

        log(`Step 3: metadata removed from leader database`, 'info');
        log(`Delete complete: ${displayName}`, 'ok');

        await handleListFiles();
    } catch (e) {
        log(`Delete failed: ${e.message}`, 'err');
        await handleListFiles();
    } finally {
        deletingFiles.delete(fileId);
    }
}

// ========== Upload flow ==========

async function handleUpload() {
    const fileInput = document.getElementById('file-input');
    const numChunksDesired = parseInt(document.getElementById('num-chunks').value, 10) || 4;
    const master = getMasterUrl();
    const file = fileInput.files[0];

    if (!file) {
        log('No file selected', 'err');
        return;
    }

    const chunkSize = Math.ceil(file.size / numChunksDesired);
    const chunks = chunkFile(file, chunkSize);
    const numChunks = chunks.length;

    log(`File: ${file.name} (${formatBytes(file.size)})`);
    log(`Chunk size: ${formatBytes(chunkSize)} → ${numChunks} chunk(s)`);

    renderChunks(numChunks);
    document.getElementById('btn-upload').disabled = true;

    log('Step 1: sending file metadata to master…');

    let chunkTargets;
    try {
        const initResp = await realInitUpload(file, chunks, master);
        if (initResp.sc) {
            log(`SC token acquired: ${initResp.sc.token_acquired}`, 'info');
            log(`SC operation id: ${initResp.sc.op_id}`, 'info');
            log(`SC peer ACKs expected: ${initResp.sc.acks_expected}`, 'info');
            log(`SC ACK phase complete or timed out: ${initResp.sc.acks_received_or_timed_out}`, 'info');
        }
        chunkTargets = initResp.chunks;

        log(`file_id: ${initResp.file_id}`, 'ok');
        chunkTargets.forEach((t, i) => {
            const replicas = t.replica_nodes ? t.replica_nodes.join(', ') : 'unknown nodes';
            log(`  chunk ${i} → id: ${t.chunk_id} replicas: ${replicas}`);
        });
    } catch (e) {
        log('Init upload failed: ' + e.message, 'err');
        document.getElementById('btn-upload').disabled = false;
        return;
    }

    log('Step 2: uploading chunks to storage node…');

    let success = 0;

    for (let i = 0; i < chunkTargets.length; i++) {
        const target = chunkTargets[i];
        const urls = (target.presigned_urls && target.presigned_urls.length > 0)
            ? target.presigned_urls
            : [target.presigned_url];

        setChunkState(i, 'uploading');
        log(`  Uploading chunk ${i + 1}/${numChunks} to ${urls.length} replica(s)…`);

        try {
            await Promise.all(urls.map(url => realUploadChunk(url, chunks[i])));
            log(`  chunk ${i} stored`, 'ok');
            setChunkState(i, 'done');
            success++;
        } catch (e) {
            log(`  chunk ${i} FAILED: ${e.message}`, 'err');
            setChunkState(i, 'error');
        }
    }

    if (success === numChunks) {
        log(`Upload complete. All ${numChunks} chunk(s) stored successfully.`, 'ok');
    } else {
        log(`Upload finished with errors. ${success}/${numChunks} chunks succeeded.`, 'err');
    }

    document.getElementById('btn-upload').disabled = false;
}

// ========== Download flow ==========

async function handleDownload() {
    const master = getMasterUrl();
    const fileId = document.getElementById('file-id-input').value.trim();

    if (!fileId) {
        log('No file ID entered', 'err');
        return;
    }

    document.getElementById('btn-download').disabled = true;
    log(`Fetching metadata for file ${fileId}…`);

    let metadata;
    try {
        metadata = await realDownloadFile(fileId, master);
        log(`File: ${metadata.filename} (${formatBytes(metadata.size)})`, 'ok');
        log(`Chunks: ${metadata.total_chunks}`);
        renderChunks(metadata.chunks.length);
    } catch (e) {
        log('Download metadata failed: ' + e.message, 'err');
        document.getElementById('btn-download').disabled = false;
        return;
    }

    const buffers = [];

    for (let i = 0; i < metadata.chunks.length; i++) {
        const { presigned_url } = metadata.chunks[i];
        setChunkState(i, 'uploading');
        log(`  Downloading chunk ${i + 1}/${metadata.chunks.length}…`);

        try {
            const buf = await realDownloadChunk(presigned_url);
            buffers.push(buf);
            setChunkState(i, 'done');
        } catch (e) {
            log(`  chunk ${i} FAILED: ${e.message}`, 'err');
            setChunkState(i, 'error');
        }
    }

    const blob = new Blob(buffers);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = metadata.filename;
    a.click();
    URL.revokeObjectURL(url);

    log(`Download complete: ${metadata.filename}`, 'ok');
    document.getElementById('btn-download').disabled = false;
}

// ========== File list flow ==========

async function handleListFiles() {
    const master = getMasterUrl();

    try {
        const data = await realListFiles(master);
        cachedFiles = data.files;
        renderFiles();
        log(`Loaded ${cachedFiles.length} file(s)`, 'ok');
    } catch (e) {
        log("Failed to list files: " + e.message, "err");
    }
}

// ========== Event Listeners ==========

window.addEventListener("DOMContentLoaded", async () => {
    if (!refreshToken) {
        redirectToLogin();
        return;
    }

    if (!authToken) {
        try {
            await refresh();
        } catch (e) {
            return;
        }
    }

    document.getElementById('btn-logout').addEventListener('click', handleLogout);
    document.getElementById('btn-upload').addEventListener('click', handleUpload);
    document.getElementById('btn-download').addEventListener('click', handleDownload);
    document.getElementById('btn-list-files').addEventListener('click', handleListFiles);
    document.getElementById('sort-files').addEventListener('change', renderFiles);

    document.getElementById('file-input').addEventListener('change', () => {
        const file = document.getElementById('file-input').files[0];
        if (file) {
            log(`Selected: ${file.name} (${formatBytes(file.size)})`);
        }
    });

    log('Client ready.');
});
