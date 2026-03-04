let authToken = null;

/**
 * used to display message in a log panel on the webpage
 * @param {*} msg
 * @param {*} level
 */
function log(msg, level = 'info') {
    const el = document.getElementById('log');  // Finds a <div id="log" element in the HTML>
    const line = document.createElement('span');    // Creates a <span>
    line.className = level;
    // Prepend the timestamp to the message
    line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}\n`;
    el.appendChild(line);   // Adds <span> into the <div>
    el.scrollTop = el.scrollHeight;
}

/**
 * API calls
 */

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
        statusEl.textContent = `Logged in as ${data.user.email}`;
        statusEl.className = 'ok';
        log(`Logged in as ${data.user.email}`, 'ok');
    } catch (e) {
        statusEl.textContent = 'Login failed';
        statusEl.className = 'err';
        log('Login failed: ' + e.message, 'err');
    }
}

async function realInitUpload(metadata, masterUrl) {
    const res = await fetch(`${masterUrl}/upload/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${authToken}`,
        },
        body: JSON.stringify(metadata),
    });

    if (!res.ok) throw new Error('Upload init failed: ' + res.status);
    return res.json();
}

async function realUploadChunk(uploadUrl, chunkBlob) {
    const res = await fetch(uploadUrl, {
        method: 'POST',
        body: chunkBlob,
    });

    if (!res.ok) throw new Error(`Chunk upload failed: ${res.status}`);

    return res.json();
}

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
    const fileInput = document.getElementById('file-input');
    const chunkSize = parseInt(document.getElementById('chunk-size').value);
    const master    = document.getElementById('master-url').value.trim();
    const file      = fileInput.files[0];

    if (!file) { log('No file selected', 'err'); return; }

    const chunks    = chunkFile(file, chunkSize);
    const numChunks = chunks.length;

    log(`File: ${file.name} (${formatBytes(file.size)})`);
    log(`Chunk size: ${formatBytes(chunkSize)} → ${numChunks} chunk(s)`);
    renderChunks(numChunks);
    document.getElementById('btn-upload').disabled = true;

    // Step 1: send metadata to master, get upload targets
    const metadata = {
      filename:   file.name,
      size:       file.size,
      chunk_size: chunkSize,
      num_chunks: numChunks,
    };

    log('Step 1: sending file metadata to master…');
    let chunkTargets;
    try {
      const initResp = await realInitUpload(metadata, master);
      chunkTargets = initResp.chunks;
      log(`file_id: ${initResp.file_id}`, 'ok');
      chunkTargets.forEach((t, i) =>
        log(`  chunk ${i} → ${t.upload_url} (id: ${t.chunk_id})`)
      );
    } catch (e) {
      log('Init upload failed: ' + e.message, 'err');
      document.getElementById('btn-upload').disabled = false;
      return;
    }

    // Step 2: upload each chunk to its storage node
    log('Step 2: uploading chunks to storage nodes…');
    let success = 0;

    for (let i = 0; i < chunkTargets.length; i++) {
      const { upload_url } = chunkTargets[i];
      setChunkState(i, 'uploading');
      log(`  Uploading chunk ${i + 1}/${numChunks} → ${upload_url}`);
      try {
        const result = await realUploadChunk(upload_url, chunks[i]);
        log(`  chunk ${i} stored: ${result.message}`, 'ok');
        setChunkState(i, 'done');
        success++;
      } catch (e) {
        log(`  chunk ${i} FAILED: ${e.message}`, 'err');
        setChunkState(i, 'error');
      }
    }

    // Done 
    if (success === numChunks) {
      log(`Upload complete. All ${numChunks} chunk(s) stored successfully.`, 'ok');
    } else {
      log(`Upload finished with errors. ${success}/${numChunks} chunks succeeded.`, 'err');
    }

    document.getElementById('btn-upload').disabled = false;
}

// ========== Event Listeners ==========
document.getElementById('btn-login').addEventListener('click', handleLogin);
document.getElementById('btn-upload').addEventListener('click', handleUpload);

document.getElementById('file-input').addEventListener('change', () => {
    const file = document.getElementById('file-input').files[0];
    if (file) log(`Selected: ${file.name} (${formatBytes(file.size)})`);
});

log('Client ready.');
