let authToken = null;
let refreshToken = localStorage.getItem("refreshToken");
let cachedFiles = [];
/**
 * used to display message in a log panel on the webpage
 * @param {*} msg
 * @param {*} level
 */
function log(msg, level = 'info') {
    const el = document.getElementById('log');
    const line = document.createElement('span');
    line.className = level;
    line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}\n`;
    el.appendChild(line);
    el.scrollTop = el.scrollHeight;
}

// ========== API calls ==========

async function realLogin(email, password, masterUrl) {
    const res = await fetch(`${masterUrl}/auth/login/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
    });
    if (!res.ok) throw new Error('Login failed: ' + res.status);
    return res.json();
}

async function handleLogin() {
    const master   = document.getElementById('master-url').value.trim();
    const email    = document.getElementById('email').value.trim();
    const password = document.getElementById('password').value;
    const statusEl = document.getElementById('auth-status');

    try {
        const data = await realLogin(email, password, master);
        authToken = data.tokens.access;
        localStorage.setItem("refreshToken", data.tokens.refresh)
        statusEl.textContent = `Logged in as ${data.user.email}`;
        statusEl.className = 'ok';
        log(`Logged in as ${data.user.email}`, 'ok');
    } catch (e) {
        statusEl.textContent = 'Login failed';
        statusEl.className = 'err';
        log('Login failed: ' + e.message, 'err');
    }
}

async function refresh(){
    const data = await fetch(`${document.getElementById('master-url').value.trim()}/auth/token/refresh/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({refresh: localStorage.getItem("refreshToken")}),
    });
    res = await data.json()
    if (!data.ok) throw new Error('Token refresh failed.');
    // refresh the access token
    authToken = res.access;
}

/**
 * Tell the master server about the file and all its chunks.
 * Returns presigned upload URLs for each chunk from MinIO.
 */
async function realInitUpload(file, chunks, masterUrl) {
    const chunksMetadata = chunks.map((blob, i) => ({
        temp_chunk_id: `tmp_${i}_${Date.now()}`,
        order: i,
        size: blob.size,
    }));

    const res = await fetch(`${masterUrl}/files/upload/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${authToken}`,
        },
        body: JSON.stringify({
            filename: file.name,
            size: file.size,
            chunks: chunksMetadata,
        }),
    });

    if(res.status === 401){
        try{
            await refresh();
        } catch (e) {
            log(e.message + ' Log in first.');
        }
        // try again after refresh ?
    }
    else if (!res.ok) throw new Error('Upload init failed: ' + res.status);
    return res.json();
}

/**
 * Upload a chunk blob directly to MinIO via the presigned URL.
 * No auth header needed — auth is baked into the presigned URL.
 */
async function realUploadChunk(presignedUrl, chunkBlob) {
    const res = await fetch(presignedUrl, {
        method: 'PUT',
        body: chunkBlob,
    });
    if (!res.ok) throw new Error(`Chunk upload failed: ${res.status}`);
}

/**
 * Get download metadata (presigned URLs) for each chunk of a file.
 */
async function realDownloadFile(fileId, masterUrl) {
    const res = await fetch(`${masterUrl}/files/${fileId}/download/`, {
        headers: { 'Authorization': `Bearer ${authToken}` },
    });
    if(res.status === 401){
        try{
            await refresh();
        } catch (e) {
            log(e.message + ' Log in again.');
        }
    }
    else if (!res.ok) throw new Error('Download failed: ' + res.status);
    return res.json();
}

/**
 * Fetch a chunk's binary data from MinIO via the presigned URL.
 */
async function realDownloadChunk(presignedUrl) {
    const res = await fetch(presignedUrl);
    if (!res.ok) throw new Error(`Chunk download failed: ${res.status}`);
    return res.arrayBuffer();
}

// ========== Helpers ==========

function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(2) + ' MB';
}

/**
 * Slice a file into an array of Blobs.
 */
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
    const bar    = document.getElementById(`chunk-bar-${index}`);
    const status = document.getElementById(`chunk-status-${index}`);
    if (!bar) return;
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

// ========== Upload flow ==========

async function handleUpload() {
    const fileInput      = document.getElementById('file-input');
    const numChunksDesired = parseInt(document.getElementById('num-chunks').value) || 4;
    const master         = document.getElementById('master-url').value.trim();
    const file           = fileInput.files[0];

    if (!file) { log('No file selected', 'err'); return; }

    const chunkSize = Math.ceil(file.size / numChunksDesired);
    const chunks    = chunkFile(file, chunkSize);
    const numChunks = chunks.length;

    log(`File: ${file.name} (${formatBytes(file.size)})`);
    log(`Chunk size: ${formatBytes(chunkSize)} → ${numChunks} chunk(s)`);
    renderChunks(numChunks);
    document.getElementById('btn-upload').disabled = true;

    // Step 1: send file + chunk metadata to master, get presigned upload URLs
    log('Step 1: sending file metadata to master…');
    let chunkTargets;
    try {
        const initResp = await realInitUpload(file, chunks, master);
        chunkTargets = initResp.chunks;
        log(`file_id: ${initResp.file_id}`, 'ok');
        chunkTargets.forEach((t, i) =>
            log(`  chunk ${i} → presigned URL received (id: ${t.chunk_id})`)
        );
    } catch (e) {
        log('Init upload failed: ' + e.message, 'err');
        document.getElementById('btn-upload').disabled = false;
        return;
    }

    // Step 2: upload each chunk directly to MinIO via presigned URL
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
    const master = document.getElementById('master-url').value.trim();
    const fileId = document.getElementById('file-id-input').value.trim();

    if (!fileId) { log('No file ID entered', 'err'); return; }

    document.getElementById('btn-download').disabled = true;
    log(`Fetching metadata for file ${fileId}…`);

    // Step 1: get file metadata and presigned download URLs from master
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

    // Step 2: fetch each chunk from MinIO via presigned URL
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

    // Step 3: reassemble chunks and trigger browser download
    const blob = new Blob(buffers);
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = metadata.filename;
    a.click();
    URL.revokeObjectURL(url);

    log(`Download complete: ${metadata.filename}`, 'ok');
    document.getElementById('btn-download').disabled = false;
}

// ========== List Files flow ==========

async function realListFiles(masterUrl) {
    let res = await fetch(`${masterUrl}/files/`, {
        headers: {
            "Authorization": `Bearer ${authToken}`,
        },
    });

    if (res.status === 401) {
        await refresh();
        res = await fetch(`${masterUrl}/files/`, {
            headers: {
                "Authorization": `Bearer ${authToken}`,
            },
        });
    }

    if (!res.ok) throw new Error("failed to fetch files");
    return res.json();
}


async function handleListFiles() {
    const master = document.getElementById('master-url').value.trim();

    try {
        const data = await realListFiles(master);
        cachedFiles = data.files; // cache files (metadata) for sorting without refetching

        renderFiles(); // render after fetching

        log(`Loaded ${cachedFiles.length} file(s)`, 'ok');

    } catch (e) {
        log("failed to list files: " + e.message, "err");
    }
}

function renderFiles() {
    const sortBy = document.getElementById('sort-files').value;

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

    const container = document.getElementById('user-files');
    container.style.display = "block"; // show container if hidden
    container.innerHTML = "";

    if (files.length === 0) {
        container.innerHTML = `<div style="color:#888;">No files found</div>`;
        return;
    }

    files.forEach(file => {
        const div = document.createElement('div');
        div.className = 'file-row';

        const createdAtText = file.created_at
            ? new Date(file.created_at).toLocaleString()
            : 'Unknown date';

            

        div.innerHTML = `
            <span class="file-name">${file.filename}</span>
            <span class="file-size">${formatBytes(file.size)}</span>
            <span class="file-date">${createdAtText}</span>
            <span class="file-download">
                <button onclick="fillDownloadId('${file.file_id}')">
                    Select File
                </button>
            </span>
        `;

        container.appendChild(div);
    });
}

// fill file id input with selected file's id for easy downloading
function fillDownloadId(id) {
    document.getElementById("file-id-input").value = id;
}

// ========== Event Listeners ==========

document.getElementById('btn-login').addEventListener('click', handleLogin);
document.getElementById('btn-upload').addEventListener('click', handleUpload);
document.getElementById('btn-download').addEventListener('click', handleDownload);

document.getElementById('file-input').addEventListener('change', () => {
    const file = document.getElementById('file-input').files[0];
    if (file) log(`Selected: ${file.name} (${formatBytes(file.size)})`);
});

document.getElementById("btn-list-files").addEventListener("click", handleListFiles);
document.getElementById("sort-files").addEventListener("change", renderFiles);


log('Client ready.');


