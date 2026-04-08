# CPSC559 — Distributed File Storage

A fault-tolerant distributed file storage system with chunked uploads, multi-node replication, and JWT-authenticated access.

---

## Prerequisites

- Docker and Docker Compose
- Node.js 18+ and npm (for the frontend)
- A terminal in the repo root

---

## Quick Start

Boot everything in order:

### 1. Create the shared Docker network

```bash
docker network create cps559_network
```

Only needed once. Safe to re-run (Docker will report it already exists).

### 2. Start the storage nodes (5 nodes + MinIO)

```bash
cd storage-node
make up
```

This starts all five storage nodes along with their MinIO and PostgreSQL instances.

### 3. Start the main server (Django + nginx + PostgreSQL)

```bash
cd main-server
make up
```

This starts the five Django replicas, the nginx load balancer, and the shared database.

The API is now available at `http://localhost`.

### 4. Start the frontend

```bash
cd front-end
npm install       # first time only
npm run dev
```

The frontend runs at `http://localhost:3000`.

---

## Shutdown

```bash
# Stop main server
cd main-server && make down

# Stop storage nodes
cd storage-node && make down
```

---

## Frontend

The frontend is a React + TanStack Router app located in `front-end/`.

| Route | Description |
|---|---|
| `/login` | Sign in with email, password, and server URL |
| `/` | Dashboard: upload, download, list, and delete files |

**Default server URL:** `http://localhost`

To create a test user, run:

```bash
docker exec main-server-main-server-1-1 python manage.py shell -c "
from core.models import User; import uuid
u = User(user_id=str(uuid.uuid4())[:15], email='test@dfs.local', first_name='Test', last_name='User')
u.set_password('password123'); u.save()
print('Created:', u.email)
"
```

---

## Architecture Overview

```
Client (browser)
     |
  nginx :80          ← load balances across 5 Django replicas
     |
Django ×5            ← main-server (JWT auth, metadata, chunk routing)
     |
StorageNode ×5       ← Flask services, each backed by MinIO + PostgreSQL
```

Files are split into N chunks. Each chunk is replicated across all 5 storage nodes using presigned MinIO URLs. Metadata lives in the shared Django PostgreSQL database.

The five Django replicas coordinate writes using a **token ring** (sequential consistency) and elect a leader via a **bully algorithm** for cluster management.

---

## API Quick Reference

### Auth

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/auth/login/` | POST | No | Login, returns JWT tokens |
| `/auth/token/refresh/` | POST | No | Refresh access token |

### Files

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/files/` | GET | Yes | List files owned by the user |
| `/files/upload/` | POST | Yes | Init chunked upload, get presigned URLs |
| `/files/<id>/download/` | GET | Yes | Get presigned download URLs |
| `/files/<id>/delete/` | DELETE | Yes | Delete file and all replicas |

### Health

| Endpoint | Method | Description |
|---|---|---|
| `/health/` | GET | Server and database health status |

---

## Authentication

All authenticated endpoints require:

```
Authorization: Bearer <access_token>
```

Access tokens expire after 1 hour. Use `/auth/token/refresh/` with the refresh token to get a new one.

---

## MinIO Consoles

Each storage node exposes a MinIO web console:

| Node | Console URL |
|---|---|
| node1 | http://localhost:9001 |
| node2 | http://localhost:9003 |
| node3 | http://localhost:9005 |
| node4 | http://localhost:9007 |
| node5 | http://localhost:9009 |

Credentials: `minioadmin` / `minioadmin123`
