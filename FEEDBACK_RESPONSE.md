# Peer Audit Feedback Response

This document addresses each question and suggestion raised during the peer audit of our distributed file storage system.

---

## Questions Raised

### Replication Factor of 3

We chose 3 replicas because it is the standard default in systems like HDFS and Google File System. It gives us tolerance for one node failure while keeping storage overhead manageable. Replicating to all available nodes would increase durability but also increase upload time and storage costs proportionally with the number of nodes. For a system with 5+ storage nodes, that overhead is not justified. The tradeoff of "tolerate one failure" vs. "consume triple the storage" is a well-established industry decision, and 3 is the sweet spot.

That said, the feedback is correct that if 2 of the 3 nodes storing a given chunk fail simultaneously, that chunk is lost. This is a known and accepted risk in systems using this replication strategy, including production systems.

---

### In-Progress Uploads During Leader Failover

This is a real edge case. Pre-signed URLs are issued by MinIO directly, not by the leader, so they continue to work even if the leader crashes mid-upload. The gap is on the metadata side: if the client finishes uploading chunks but the leader crashes before writing the file and chunk records to PostgreSQL, those chunks will be orphaned in MinIO with no database entry pointing to them.

We do not currently have a recovery mechanism for this. The practical impact is limited because leader elections complete quickly and the client would receive an error on the finalize step, but the orphaned chunks would remain in MinIO. A production system would handle this with a background job that scans for unreferenced chunks and cleans them up. That is out of scope for this project but is the correct approach.

---

### Mid-Upload Crashes and Partial Uploads

If a client crashes mid-upload, whatever chunks were already uploaded to MinIO will remain there. The file record in PostgreSQL may have been created (we create it before issuing presigned URLs) but the chunk records for un-uploaded chunks will be missing or unconfirmed.

Currently there is no verification step that checks whether all expected chunks were received before marking a file as complete. The `File` model does not have a status field distinguishing between an in-progress and a completed upload. This means a user could see a file in their list that is only partially uploaded and get an error when they try to download it.

**This is a known gap.** The fix would be to add a `status` field to the `File` model (`pending`, `complete`, `failed`) and only transition to `complete` after all chunk uploads are confirmed. That is a reasonable code change that we could implement.

---

### Delete Consistency and the Retry Loop

The "guaranteed within 30 seconds" claim in our slides refers to the fact that pending deletes are retried on every heartbeat, and heartbeats fire every 30 seconds. When a node comes back online and sends a heartbeat, `_retry_pending_deletes` runs and attempts to delete any queued chunks on that node.

The feedback asks whether a retry can get stuck. The answer is: yes, currently it can. We track a `retry_count` on each `PendingDelete` record and increment it on each failure, but we never act on that count. There is no cap, no backoff, and no mechanism to flag a delete as permanently failed. A chunk that consistently fails to delete (for example, if a node comes back online but the chunk is corrupted or the delete endpoint has a bug) will retry forever.

**This is something we should fix.** The change is small: in `_retry_pending_deletes` in `views.py`, skip records where `retry_count` exceeds a threshold (e.g., 10) and log a warning so the issue can be investigated manually.

---

### Staggered Startup and Leader Election

We stagger startup with increasing delays per server ID so that the server with the highest ID starts last and immediately wins the election without conflict. This is a simplification. The real bully algorithm is designed to handle simultaneous starts: any node that does not receive a response from a higher-ID node within a timeout declares itself the leader, and the highest-ID node that is awake will always win because it bullies down anyone who tries to claim leadership.

The staggered approach works for our setup because the servers are in a controlled Docker Compose environment where startup order is predictable. The concern about race conditions is valid in a more dynamic environment. We do not use locks or mutexes during election because the bully messages themselves act as a serialization mechanism: a node steps down when it receives a message from a higher-ID node. The risk of a split where two nodes both believe they are the leader is low in practice with our current setup.

---

### Node Registration

Each storage node knows the addresses of the main servers through Docker Compose environment variables set at container start time. There is no dynamic discovery. On startup, a storage node sends heartbeats to a fixed main server address. The main server records the node's name and address in the database.

Name conflicts are possible if a node restarts and re-registers with the same name. We handle this with an `update_or_create` in the heartbeat endpoint, so the same name always maps to the same record and simply updates the address and heartbeat timestamp. Two different nodes using the same name would overwrite each other's registration, which would be a misconfiguration problem in our environment rather than something the code needs to defend against at runtime.

---

### Single PostgreSQL Database as SPOF

This is a real single point of failure. All five main servers share one PostgreSQL instance. If it crashes, the entire system goes down. We do not have a backup, a read replica, or a failover strategy.

For the scope of this project, we accepted this limitation. The alternative would be to replicate metadata across the main servers themselves (similar to what Raft does) and remove the dependency on a single external database. That is a significant architectural change that was out of scope. In a production deployment, this would be addressed with PostgreSQL streaming replication and a failover solution like Patroni.

---

### NGINX Proxy as SPOF

Same category as the database: one NGINX instance means the proxy is a single point of failure. If NGINX crashes, no client requests reach the system at all. During a leader election, NGINX continues to forward requests to the same upstream. If the current leader is the one being replaced, requests will fail until the new leader is elected and NGINX is updated (or if NGINX is configured to route to a stable endpoint that always reflects the current leader).

We do not currently have logic to hold requests during an election. Requests that arrive during the election window will fail and the client would need to retry. This is acceptable for a class project but would need to be addressed in production with either a request queue in the proxy or a virtual IP that floats to the current leader.

---

### 30-Second Heartbeat Interval

The 30-second interval was chosen for simplicity and observability during development. The tradeoff is real: with 3 missed heartbeats before marking a node inactive, the system can take up to 90 seconds to detect a crashed node. During that window, the system may attempt to route chunk reads or deletes to a node that is no longer available.

Lowering the interval to something like 5 seconds would reduce detection time to 15 seconds. The cost is more frequent network traffic between nodes and the main server. For a class project with 5 nodes, this traffic is negligible. If we were tuning for production responsiveness, we would lower the interval.

---

## Alternative Approaches

### Client Uploads to One Node, Backend Replicates

The suggestion is valid: having the client upload to one node and letting the backend push to the other two would reduce the client's upload work by roughly 3x. The tradeoff is that the primary node becomes a temporary bottleneck for replication and adds latency to the upload from the server's perspective. We chose the parallel client upload approach because it is simpler to implement and does not require node-to-node data transfer logic. For users on fast connections the difference is negligible.

### Smarter Chunk Placement

We use round-robin because it is simple and deterministic. The feedback is correct that it does not account for node load or remaining capacity. If one node has been offline for a while and then comes back, it will receive new chunks via round-robin but will not have the historical chunks it missed, creating an imbalance. A capacity-aware placement strategy would improve durability. This is a reasonable future improvement.

### Route Reads to Followers

Currently all requests are routed through the leader. Download requests do not need to involve the leader at all since any replica of a chunk is equivalent. Routing reads directly to follower nodes would reduce load on the leader and allow download throughput to scale with the number of nodes. This is a good suggestion that we did not implement due to time constraints.

### Multiple NGINX Proxies

Deploying multiple proxies with a virtual IP or DNS-based load balancing would eliminate the proxy as a SPOF. This was out of scope but is the standard solution.

### Raft Instead of Bully Algorithm

Raft would give us stronger consistency guarantees, split-brain prevention via majority quorum, and metadata replication across main servers (eliminating the single PostgreSQL dependency). The bully algorithm we implemented is simpler and sufficient for our scale, but Raft would be the right choice for a production system.

### Erasure Coding

Erasure coding (e.g., Reed-Solomon) can achieve the same fault tolerance as 3x replication with significantly less storage overhead. For example, a 4+2 configuration tolerates 2 node failures using only 1.5x the original data size instead of 3x. The implementation complexity is higher and requires a library. For a class project demonstrating distributed systems concepts, full replication is easier to reason about and explain.

### Chunk Integrity Verification

Hashing each chunk (SHA-256) on upload and storing the hash in the database would let us detect corruption across replicas and during transmission. This is a good defensive measure that we did not implement. It would also help catch the cross-platform encoding issues mentioned in the feedback.

### Disk-Based Storage Instead of MinIO

Using MinIO was a deliberate choice to separate concerns: MinIO handles object storage and we handle distribution and metadata. Replacing it with direct disk writes and SQLite per node would make our replication code more visible but would also require us to reimplement much of what MinIO provides. The feedback is fair that using MinIO somewhat obscures the replication story, since MinIO itself has replication features that we are not leveraging.
