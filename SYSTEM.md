# Distributed File System

## Overview

The Distributed File System is a multi-node file storage system where uploaded files are split into chunks and replicated across independent storage nodes. No single node failure can cause data loss. If one node goes down, the system automatically serves chunks from another. A central orchestration server manages authentication, metadata, and node coordination, while each storage node handles its own object storage independently. The system is stateless and the storage nodes have no knowledge of what happens in the main server. They only respond to requests and report their availability.

## Architecture

The system has three main components:

**Main Server** is a Django REST API that acts as the brain of the system. It handles user authentication, tracks all files and their chunks in a PostgreSQL database, and coordinates with storage nodes during uploads and downloads. Clients only ever talk to the main server directly.

**Storage Nodes** are independent Flask services, each backed by their own MinIO instance (S3-compatible object storage) and their own PostgreSQL database. A node's only job is to store chunk data and generate presigned URLs so clients can upload or download directly. Nodes know nothing about users, files, or other nodes.

**Client** is a browser-based interface where users log in, select a file, and trigger uploads or downloads. The client talks to the main server for coordination and then directly to MinIO for the actual data transfer via presigned URLs.

```
Client
  |
  |--- auth, metadata, coordination --->  Main Server (Django + PostgreSQL)
  |                                            |
  |                                            |--- registers / heartbeat --- Storage Node 1 (Flask + MinIO)
  |                                            |--- registers / heartbeat --- Storage Node 2 (Flask + MinIO)
  |
  |--- chunk data (presigned URLs) ---------> MinIO (Node 1 or Node 2)
```

## Core Features

- **Chunked uploads** - Files are split into chunks on the client before uploading. Each chunk is uploaded independently, which makes large files more manageable and allows parallel transfers.

- **Replication** - Every chunk is stored on 2 storage nodes (replication factor of 2). The main server selects which nodes receive each chunk using round-robin distribution.

- **Presigned URLs** - A presigned URL is a time-limited URL that grants temporary access to a specific object in MinIO without requiring credentials. Storage nodes generate these URLs and hand them to the main server, which forwards them to the client. The client then uploads or downloads directly to MinIO using that URL. This keeps the main server lightweight since it never handles file bytes.

- **JWT Authentication** - Users authenticate with email and password and receive a short-lived access token and a longer-lived refresh token. All file operations require a valid token.

- **Heartbeat-based node health** - Storage nodes continuously report their availability to the main server. The main server uses this signal to decide which nodes are healthy enough to receive new chunks.

## Upload & Download Flow

### Upload

1. The client splits the file into chunks locally and sends the main server a list of chunk metadata (order, size) along with the filename.
2. The main server creates a file record, then for each chunk it selects 2 active storage nodes and asks each one to register the chunk. Each node responds with a presigned upload URL pointing to its MinIO instance.
3. The main server returns all presigned URLs to the client.
4. The client uploads each chunk directly to MinIO using those URLs, hitting both nodes in parallel.

### Download

1. The client sends the file ID to the main server.
2. The main server looks up the chunks and their replicas, then contacts a storage node for each chunk to get a presigned download URL. It tries active nodes first, falling back to inactive ones if needed.
3. The main server returns the full list of chunk URLs to the client.
4. The client downloads each chunk directly from MinIO and reassembles them into the original file in the browser.

## Distributed Nodes

### Registration

Storage nodes do not need to be manually configured in the main server. When a node starts up, it immediately sends a registration heartbeat to the main server containing its name and address. The main server creates a record for that node if it does not exist, or updates it if it does. From that point on, the node is considered active and eligible to receive chunks.

### Heartbeats

Every 30 seconds, each storage node sends a POST request to the main server's `/nodes/heartbeat/` endpoint. The main server records the timestamp of each heartbeat. A node is considered active as long as its last heartbeat arrived within the past 90 seconds. If a node stops sending heartbeats, it will age out of the active pool after that window.

### Replication

When the main server processes an upload, it selects 2 active nodes per chunk using round-robin. This spreads the load evenly across nodes and ensures every chunk has 2 independent copies. The main server tracks which node holds which replica in a `ChunkReplica` table, decoupled from the chunk itself.

## Fault Tolerance

### When a node goes down during uploads

The main server will not assign new chunks to a node that has missed its heartbeat window. If the number of active nodes drops below the replication factor (2), new uploads are rejected entirely. This is intentional. The system prefers to refuse an upload rather than store data with insufficient redundancy.

### When a node goes down during downloads

Downloads degrade gracefully. For each chunk, the main server sorts replicas by node health and tries them in order. It attempts to fetch a presigned URL from the first replica. If that request fails or the node is unreachable, it moves on to the next. A download only fails if every replica for a given chunk is unreachable, which requires both nodes holding that chunk to be down simultaneously.

## How to Run

The system requires Docker and Docker Compose. Each component runs in its own compose stack and they communicate over a shared Docker network created by the main server. Start them in order.

**1. Start the main server**

```bash
cd main-server
cp .env.example .env
docker compose up --build
```

The `.env` file contains database credentials, a Django secret key, and debug settings. The defaults in `.env.example` work out of the box for local development.

**2. Start storage node 1**

```bash
cd storage-node
docker compose up --build
```

**3. Start storage node 2**

```bash
cd storage-node
docker compose -f docker-compose.node2.yml up --build
```

**4. Start storage node 3**
```bash
cd storage-node
docker compose -f docker-compose.node3.yml up --build
```

Once all three are running, the storage nodes will register themselves with the main server automatically. No manual configuration is needed. The system is ready when both nodes have sent their first heartbeat.

**5. stop processes, do this in main-server, and storage-node**
```bash
docker compose -f docker-compose.node3.yml down --remove-orphans
docker compose -f docker-compose.node2.yml down --remove-orphans
docker compose down --remove-orphans
```
