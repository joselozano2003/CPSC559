# Distributed File System

## Overview

The Distributed File System is a multi-node file storage system where uploaded files are split into chunks and replicated across independent storage nodes. No single node failure can cause data loss. If a storage node goes down, the system automatically serves chunks from another replica. If a main server goes down, a bully election among the remaining servers selects a new leader within seconds, and Nginx automatically routes traffic to it. A cluster of replicated main servers manages authentication, metadata, and node coordination, while each storage node handles its own object storage independently.

## Architecture

The system has four main components:

**Nginx** is the single entry point for all client traffic on port 80. It proxies requests to whichever main server is currently the elected leader. When a new leader is elected, Nginx is updated automatically so clients never need to change where they point.

**Main Servers** are five identical Django REST API instances that share a single PostgreSQL database. They handle user authentication, track all files and their chunks, and coordinate with storage nodes during uploads and downloads. Only the elected leader accepts client requests. The others remain on standby and participate in elections.

**Storage Nodes** are five independent Flask services, each backed by their own MinIO instance (S3-compatible object storage) and their own PostgreSQL database. A node's only job is to store chunk data and generate presigned URLs so clients can upload or download directly. Nodes know nothing about users, files, or other nodes.

**Client** is a browser-based interface where users log in, select a file, and trigger uploads or downloads. The client always talks to Nginx, which transparently forwards requests to the current leader.

```
Client (browser)
  |
  |--- all requests (port 80) ---> Nginx
  |                                  |
  |                     routes to current leader
  |                                  |
  |                         Main Server (Leader)
  |                         Django + Shared PostgreSQL
  |                                  |
  |                  +--------------+------------------+
  |                  |              |                  |
  |           Storage Node 1  Storage Node 2  ... Storage Node 5
  |           Flask + MinIO   Flask + MinIO       Flask + MinIO
  |           + PostgreSQL    + PostgreSQL         + PostgreSQL
  |
  |--- chunk data (presigned URLs) ---------> MinIO (direct)
```

## Core Features

- **Chunked uploads** - Files are split into chunks on the client before uploading. Each chunk is uploaded independently, which makes large files more manageable and allows parallel transfers.

- **Replication** - Every chunk is stored on 3 storage nodes (replication factor of 3). The main server selects which nodes receive each chunk using round-robin distribution.

- **Presigned URLs** - A presigned URL is a time-limited URL that grants temporary access to a specific object in MinIO without requiring credentials. Storage nodes generate these URLs and hand them to the main server, which forwards them to the client. The client then uploads or downloads directly to MinIO using that URL. This keeps the main server lightweight since it never handles file bytes.

- **JWT Authentication** - Users authenticate with email and password and receive a short-lived access token and a longer-lived refresh token. All file operations require a valid token. Storage nodes verify tokens by forwarding them to the main server through Nginx, so verification always reaches the current leader.

- **Heartbeat-based node health** - Storage nodes continuously report their availability to the main server every 30 seconds. The main server uses this signal to decide which nodes are healthy enough to receive new chunks. A node that misses its heartbeat for 90 seconds is considered inactive. Heartbeats also trigger eventual consistency recovery: when a node checks in, the main server automatically retries any chunk deletes that failed while the node was down.

- **Leader election** - Main servers elect a leader using the bully algorithm. The server with the highest ID wins. On startup, each server waits a staggered delay before starting an election, so the highest-ID server claims leadership first. If the leader stops responding, the remaining servers detect this and hold a new election within about 15 seconds.

## Upload and Download Flow

### Upload

1. The client splits the file into chunks locally and sends the main server a list of chunk metadata (order, size) along with the filename.
2. The main server creates a file record, then for each chunk it selects 3 active storage nodes and asks each one to register the chunk. Each node responds with a presigned upload URL pointing to its MinIO instance.
3. The main server returns all presigned URLs to the client.
4. The client uploads each chunk directly to MinIO using those URLs, hitting all 3 nodes in parallel.

### Download

1. The client sends the file ID to the main server.
2. The main server looks up the chunks and their replicas, then contacts a storage node for each chunk to get a presigned download URL. It tries active nodes first, falling back to inactive ones if needed.
3. The main server returns the full list of chunk URLs to the client.
4. The client downloads each chunk directly from MinIO and reassembles them into the original file in the browser.

## Leader Election

### Bully Algorithm

Each main server has a unique integer ID (1 through 5). When a server suspects the current leader is down, it sends an ELECTION message to all servers with a higher ID. If any of them respond with a BULLY message, the initiating server backs off and waits for a COORDINATOR announcement. If no higher-ID server responds within a timeout, the initiating server declares itself leader by broadcasting a COORDINATOR message to all peers.

On declaring victory, the new leader:
1. Broadcasts COORDINATOR to all peer servers so they update their local leader state.
2. Calls `POST /set-leader` on all storage nodes so their heartbeats and JWT verification route to the new leader.
3. Calls `POST /set-leader` on the Nginx updater so client traffic is routed to the new leader.

### Startup Behavior

Server 5 (the highest ID) wins the initial election. Each server waits `10 + (max_id - server_id)` seconds before starting its first election, so server 5 waits 10 seconds while server 1 waits 14. This stagger gives the highest-ID server a head start and prevents unnecessary election rounds on a clean startup.

### Failover

If the leader crashes, the remaining servers detect the missed heartbeat and trigger a new election. The next highest-ID alive server wins. The whole process takes about 10 to 15 seconds. During that window, client requests may fail. Once the new leader announces itself, Nginx is updated and traffic resumes normally.

## Distributed Nodes

### Registration

Storage nodes do not need to be manually configured in the main server. When a node starts up, it immediately sends a registration heartbeat to the main server containing its name and address. The main server creates a record for that node if it does not exist, or updates it if it does. From that point on, the node is considered active and eligible to receive chunks.

### Heartbeats

Every 30 seconds, each storage node sends a POST request to the main server's `/nodes/heartbeat/` endpoint through Nginx. Because storage nodes always talk to Nginx rather than a specific main server, their heartbeats automatically reach the current leader even after a failover, with no restart required.

### Replication

When the main server processes an upload, it selects 3 active nodes per chunk using round-robin. This spreads the load evenly across nodes and ensures every chunk has 3 independent copies. The main server tracks which node holds which replica in a `ChunkReplica` table, decoupled from the chunk itself.

## Fault Tolerance

### When a storage node goes down during uploads

The main server will not assign new chunks to a node that has missed its heartbeat window. If the number of active nodes drops below the replication factor (3), new uploads are rejected entirely. The system prefers to refuse an upload rather than store data with insufficient redundancy.

### When a storage node goes down during downloads

Downloads degrade gracefully. For each chunk, the main server sorts replicas by node health and tries them in order. A download only fails if every replica for a given chunk is unreachable simultaneously. With 3 replicas per chunk, 2 of the 5 storage nodes can be down at the same time without losing access to any chunk.

### When a storage node goes down during deletes

If a chunk delete fails because the target node is unreachable, the main server records a `PendingDelete` entry for that node and chunk. The file record is still removed from the main server database immediately, so the file is no longer visible or accessible to users. When the storage node comes back online and sends its next heartbeat, the main server detects the pending delete and retries it automatically in a background thread. On success, the `PendingDelete` entry is cleared. This is the system's eventual consistency mechanism for deletes: the chunk data on a recovered node is guaranteed to be cleaned up within 30 seconds of the node rejoining the cluster.

### When a main server goes down

If the downed server was a follower, there is no impact. If it was the leader, the bully election runs and a new leader is elected within about 15 seconds. All main servers share the same PostgreSQL database, so no metadata is lost. Pending delete records are also stored in this shared database, so a leadership failover does not affect recovery.

## Consistency Model

**Metadata (PostgreSQL):** Strong consistency. All main servers share one database. Nginx ensures only the elected leader receives client requests, so there are no concurrent conflicting writes to file or chunk records.

**Chunk data (MinIO):** Eventual consistency. The client uploads to all 3 presigned URLs in parallel. If one upload fails partway through, that replica will be missing the chunk. There is no confirmation step back to the main server, so the missing replica is not detected until a download attempt hits that specific node.

**Deletes:** Eventual consistency. When a file is deleted, the main server removes its metadata immediately and attempts to delete every chunk replica from each storage node. If a node is unreachable, the delete for that node is queued as a `PendingDelete` record. The next time that node sends a heartbeat, the main server retries the delete. The chunk is guaranteed to be removed within 30 seconds of the node coming back online.

**Leader state:** Eventually consistent across the cluster. On election win, the leader broadcasts COORDINATOR to all peers and updates Nginx and all storage nodes. A peer that misses the broadcast self-corrects on the next heartbeat check.

## How to Run

The system requires Docker and Docker Compose. Each component runs in its own compose stack and they communicate over a shared Docker network. Start them in order.

**1. Create the shared network**

```bash
docker network create cps559_network
```

**2. Start the main server cluster**

```bash
cd main-server
cp .env.example .env
docker compose up --build
```

This starts all 5 main server instances, the shared PostgreSQL database, and the Nginx load balancer together. Server 5 will win the initial election within about 10 seconds.

**3. Start the storage nodes**

Each storage node must be started with a unique project name to avoid network naming conflicts. Run each of the following in a separate terminal from the `storage-node` directory.

```bash
cd storage-node

docker compose -p node1 -f docker-compose.yml up --build
docker compose -p node2 -f docker-compose.node2.yml up --build
docker compose -p node3 -f docker-compose.node3.yml up --build
docker compose -p node4 -f docker-compose.node4.yml up --build
docker compose -p node5 -f docker-compose.node5.yml up --build
```

Once all nodes are running, they will register themselves with the main server automatically via heartbeat. No manual configuration is needed.

**4. Open the client**
first register on the main server with the command:
```bash
curl -X POST http://localhost/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{"email":"test@email.com","password":"password","first_name":"Test","last_name":"User"}'
```

Open `client/login.html` in a browser and log in. The default server URL is `http://localhost`, which routes through Nginx to the current leader.

**5. Tear down**

Stop storage nodes (from the `storage-node` directory):

```bash
docker compose -p node5 -f docker-compose.node5.yml down --remove-orphans
docker compose -p node4 -f docker-compose.node4.yml down --remove-orphans
docker compose -p node3 -f docker-compose.node3.yml down --remove-orphans
docker compose -p node2 -f docker-compose.node2.yml down --remove-orphans
docker compose -p node1 -f docker-compose.yml down --remove-orphans
```

Stop the main server cluster (from the `main-server` directory):

```bash
docker compose down --remove-orphans
```

## Port Reference

| Service | Host Port |
|---------|-----------|
| Nginx (client entry point) | 80 |
| Main Server 1 (debug) | 8001 |
| Main Server 2 (debug) | 8002 |
| Main Server 3 (debug) | 8003 |
| Main Server 4 (debug) | 8004 |
| Main Server 5 (debug) | 8005 |
| Nginx updater API | 8080 |
| Storage Node 1 | 6000 |
| Storage Node 2 | 6001 |
| Storage Node 3 | 6002 |
| Storage Node 4 | 6003 |
| Storage Node 5 | 6004 |
| MinIO Node 1 (API / Console) | 9000 / 9001 |
| MinIO Node 2 (API / Console) | 9002 / 9003 |
| MinIO Node 3 (API / Console) | 9004 / 9005 |
| MinIO Node 4 (API / Console) | 9006 / 9007 |
| MinIO Node 5 (API / Console) | 9008 / 9009 |
| PostgreSQL (main server) | 5432 |
| PostgreSQL (storage node 1) | 5433 |
| PostgreSQL (storage node 2) | 5434 |
| PostgreSQL (storage node 3) | 5435 |
| PostgreSQL (storage node 4) | 5436 |
| PostgreSQL (storage node 5) | 5437 |
