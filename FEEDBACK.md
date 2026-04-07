## What People Wanted More Information On

**Replication Factor of 3**
- Why 3 nodes specifically? Is this based on performance benchmarks, storage constraints, or industry standards? If 2 of the 3 nodes storing a chunk fail, that data is lost. Replicating to all available nodes would improve fault tolerance at the cost of storage overhead.

**In-Progress Uploads During Leader Failover**
- If a client receives pre-signed URLs from the old leader and is mid-upload when the leader crashes, the URLs still work but who confirms the metadata? The file record may be incomplete in PostgreSQL. Recovery semantics here are unclear.

**Mid-Upload Crashes / Partial Uploads**
- What happens if a client crashes or fails to upload a chunk? Is there a mechanism to verify at least one replica of each chunk was uploaded? What if some chunks succeed and others fail -- how does the system avoid partial/inconsistent file state?

**Delete Consistency Guarantee**
- The slide states a chunk is "guaranteed to be removed within 30 seconds of the node coming back online." What if the retry fails? Is there a retry loop, or could the delete get stuck?

**Staggered Startup & Leader Election**
- How does staggering the startup delay ensure the highest-ID server wins? Did you consider letting all servers start simultaneously, since the bully algorithm is designed to handle concurrent elections? Locks/mutexes may be needed to prevent race conditions.

**Node Registration**
- How do nodes know which server is the master on startup so they can register? How do they avoid reusing the same name/address before they're aware of the other nodes?

**Single PostgreSQL Database as SPOF**
- All five main servers share one PostgreSQL instance. There's no mention of a backup or failover. What happens if the database crashes?

**NGINX Proxy as SPOF**
- One NGINX instance is a single point of failure and a potential bottleneck. What happens if the proxy crashes or if it receives a request while an election is in progress -- does it hold the request or let it fail?

**30-Second Heartbeat Interval**
- 90 seconds to mark a node inactive (3 missed heartbeats at 30s each) is a long time to be unaware of a crashed node. Lowering the interval would improve failure detection speed.

---

## Alternative Approaches Suggested

**Client Upload Path**
- Instead of the client uploading chunks to all 3 nodes in parallel, have the client upload to one node and let the backend replicate to the others. This reduces client upload time by ~3x, especially beneficial for users with slow connections, at the cost of added server-side complexity.

**Smarter Chunk Placement (vs. Round-Robin)**
- Round-robin doesn't account for node load, available capacity, or failure state. A placement strategy that weighs node health and remaining capacity would improve durability and performance, especially after a node has been offline for some time (causing imbalance).

**Route Reads to Followers**
- Download operations could be routed to follower/replica nodes rather than requiring the leader, improving load balancing and concurrency without strict coordination.

**Multiple Proxies**
- Deploy multiple NGINX proxies so failure of one doesn't crash the system, and so the proxy layer can scale with the number of clients.

**Raft Instead of Bully Algorithm**
- Replace the bully algorithm with Raft consensus and replicate metadata across main servers. Raft prevents split-brain via majority quorum and elects based on log completeness rather than just node ID.

**Erasure Coding**
- Consider erasure coding instead of full 3x replication to reduce storage overhead while maintaining redundancy.

**Chunk Integrity Verification**
- Hash each chunk (e.g., SHA-256) during transmission and verify on receipt. Store hashes in the database so the leader can detect divergence across replicas. This also guards against corruption from cross-platform encoding differences.

**Disk-Based Storage Instead of MinIO**
- Each node could manage an SQLite instance tracking file handles, with blobs written directly to disk. This would make the replication case more compelling vs. using MinIO/S3, which already handles replication internally.