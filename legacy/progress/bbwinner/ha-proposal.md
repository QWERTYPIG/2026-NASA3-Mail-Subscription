# High Availability
 
## What Dimensions of HA to Consider
 
1. **Application Layer** (Django web + Django-Q worker)
2. **Database** (PostgreSQL)
3. **Cache & Queue** (Redis)
4. **Nginx**
---
 
## Machine Distribution
 
```
Machine 0
- Nginx (dedicated reverse proxy)
 
Machine 1
- web
- PostgreSQL (primary)
- Django-Q LDAP worker (active)
- DB sync worker (standby)
- Redis
 
Machine 2
- web
- PostgreSQL (replica)
- Django-Q LDAP worker (standby)
- DB sync worker (active)
- Redis
 
Machine 3
- web
- PostgreSQL (replica)
- Django-Q LDAP worker (standby)
- DB sync worker (standby)
- Redis
```
 
All web instances write to M1 primary PostgreSQL over the network.
DB sync worker on M1 syncs primary → M2 and M3 every 10 minutes.
If M1 DB is down, promote M2 or M3 replica to primary manually.
 
Redis currently runs on all three machines and scrambles for the flush lock.
Plan to consolidate to one active Redis later.
 
---
 
## Application (Django web + worker)
 
### What can fail
- The `web` container crashes → Nginx routes it to the other two
- The `worker` container crashes → external monitoring script detects the stopped container and sends alert
### Nginx -- Load Balancing
 
Nginx runs as a dedicated reverse proxy on Machine 0. It distributes incoming
API requests across all three backends on M1, M2, and M3.
 
- Algorithm: least connection
Sends each new request to whichever backend currently has the fewest active
connections. This naturally compensates for the fact that login requests (which
involve an LDAP bind, ~50–200 ms) are significantly slower than read requests
(PostgreSQL cache hit, ~1–10 ms).
 
### Django Web -- 3 Instances
 
After 5 failed restarts, Docker gives up and leaves the container stopped.
 
- Restart policy: on-failure (Does not restart after an intentional `docker compose down`)
Mid-request fail
- `GET`: nginx retry
- `POST`: does not retry
### Django-Q LDAP Worker -- 1 Active 1 Standby
 
LDAP sync flush interval: 30 minutes (production).
 
```
Worker on Machine 1 stops
        │
        ▼
Is Machine 1 itself alive?
        │
   ┌────┴────┐
  YES        NO
   │          │
   ▼          ▼
Try to      Start Machine 3
restart     worker immediately
M1 worker   (M1 is unrecoverable)
   │
   ▼
Did it recover after max_attempts?
        │
   ┌────┴────┐
  YES        NO
   │          │
   ▼          ▼
Done      Investigate logs
          Is it a persistent bug?
               │
          ┌────┴────┐
         YES        NO
          │          │
          ▼          ▼
       Fix bug    Start Machine 3
       first,     worker as
       then       temporary measure
       restart    while debugging
```
 
- If Machine 1 is down, stop Machine 3 worker before restarting Machine 1.
### DB Sync Worker -- 1 Instance on M1
 
Syncs PostgreSQL primary (M1) → replicas (M2, M3) every 10 minutes.
Lives on M1. If M1 is down, sync stops — replicas freeze at last sync point.
On M1 recovery, sync resumes automatically.
 
---
 
## PostgreSQL
 
> PostgreSQL is a cache and task queue, not the
source of truth. LDAP holds the authoritative state. This significantly reduces
the severity of PostgreSQL failure compared to a system where the DB is the truth.
 
### What Can Fail
 
- **Container crash, volume intact** → `restart: on-failure` recovers automatically.
  PostgreSQL replays its WAL on startup. No data loss, no human intervention needed.
- **Machine 1 entirely down** → M2 and M3 replicas freeze at last sync point
  (up to 10 minutes behind). Promote M2 or M3 to primary manually.
- **Disk failure or volume corruption** → full recovery from backup required.
### Recovery From LDAP
 
Most PostgreSQL data is reconstructable from LDAP.
 
| Table / Field | Recoverable from LDAP? | How |
|---|---|---|
| `alias.alias_name` | ✓ Yes | `cn` of each `ou=Aliases` entry |
| `alias.user_id` | ✓ Yes | `uniqueMember` list of each alias |
| `alias.display_name` | ✗ No | PostgreSQL-exclusive metadata |
| `alias.description` | ✗ No | PostgreSQL-exclusive metadata |
| `alias_task_queue` | ✗ No | Pending changes not yet in LDAP |
| `user_task_queue` | ✗ No | Pending changes not yet in LDAP |
| Sessions | ✗ No | Not needed — users re-login |
 
The existing consistency check already performs this reconstruction automatically
after any recovery: it pulls `ou=Aliases` from LDAP and rebuilds `alias_name` and
`user_id`. No manual steps required for those fields.
 
The task queue tables represent changes queued but not yet flushed to LDAP. The
maximum unrecoverable window is **one flush cycle (30 minutes in production)**.
 
### Method
 
**Volume persistence:**
 
PostgreSQL data lives in a named Docker volume on each machine. The volume
survives container restarts and `docker compose down`. Only `docker compose down -v`
destroys it.
 
- Restart policy: `on-failure`.
**Replica promotion on M1 failure:**
 
```
① Confirm M1 PostgreSQL is dead
② Promote M2 or M3 replica to primary
③ Update DB_HOST on all web containers to point to the new primary
④ Restart web containers
⑤ DB sync worker is also gone (lives on M1) — sync is paused until M1 recovers
```
 
**Backup strategy:**
 
Only two things genuinely need backing up:
 
- `display_name` and `description` — daily `pg_dump --table=alias`. These fields
  change rarely (admin edits only) and losing them is low severity — aliases still
  function, display names just revert to `alias_name` until re-entered.
- Task queue tables — optional. ???
> Task queue backup frequency depends on the production flush interval.
> | Environment | Flush interval | Task queue backup interval | Max loss on disk failure |
> |---|---|---|---|
> | Development | 3 minutes | not needed | 3 minutes |
> | Production | 30 minutes | every 10 minutes | 10 minutes |
 
**Recovery procedure on disk failure:**
 
target: promote M2 or M3 replica
 
```
1 Promote M2 replica to primary (or M3 if M2 is also unavailable)
2 Update DB_HOST on all web containers to point to new primary
3 Restart web containers
4 Start Machine 3 LDAP worker if M1 worker is also gone
5 Worker runs next flush → consistency check rebuilds alias_name
   and user_id from LDAP automatically
   → display_name / description may be partially recovered from replica
   → pending task rows since last sync are lost (up to 10 minutes)
   → affected users resubmit their changes
```
 
- Sessions are lost — users need to login again.
- Default Configuration: `fsync = on`, flush to disk
---
 
## Redis
 
### What Redis Stores
 
- **DB 0 — Django-Q broker**: the flush lock (`FLUSH_LOCK_KEY`) and the Django-Q
  scheduler trigger. It does **not** store actual task data — tasks live entirely
  in PostgreSQL. The worker pulls tasks from PostgreSQL directly.
- **DB 1 — Rate limit TTL keys**: one key per user uid, expires automatically
  after the 10-minute cooldown window.
### Current State
 
Redis runs on M1, M2, and M3. All three scramble for the flush lock — only one
holds it at a time, so only one worker executes a flush cycle. This is functional
but not the intended final design.
 
Plan: consolidate to one active Redis instance later.
 
### What Can Fail
 
- **DB 0 loss:** The worker stops flushing until Redis recovers. Tasks safely
  accumulate in PostgreSQL — no data loss.
- **DB 1 loss:** Users in cooldown can submit again immediately. Duplicate tasks
  are handled by idempotent LDAP operations. No data integrity risk.
### Method
 
- `restart: on-failure` on all three Redis instances.
- No persistence needed — nothing in Redis is worth persisting.
### One Thing to Verify
 
Confirm Django-Q re-registers its flush schedule automatically after Redis
restarts. If it does not, the worker silently stops flushing even after Redis
recovers — the monitor script would need to detect this by checking whether
the last flush timestamp in PostgreSQL is stale.
 
---
 
## Nginx
 
### What Can Fail
 
- **M0 entirely down** → service completely unreachable. Send alert mail only.
  No automatic failover — if M0 dies, manual intervention is required.
### Setup
 
DNS record for `mailsus.csie.org` points to M0's static IP. Nginx on M0 listens
on port 80, responds to `mailsus.csie.org`, and proxies to web on M1, M2, M3.
 
> Note: DNS setup is a prerequisite that is not yet implemented. Currently users
> access via direct static IP. Setting up `mailsus.csie.org → M0's IP` is a
> pending task.
 
---
 
## Monitor Script and Alert Mail
 
The monitor is a cross-cutting concern that watches components across all layers.
Each monitor script runs every minute via cron.
 
### Where Monitors Live
 
A monitor cannot live on the same machine as what it is watching — if the machine
dies, both the service and the monitor die together.
 
```
Machine 2 monitor → watches M0 Nginx, M1 web, M3 web, M1 PostgreSQL, M1 Redis, M1 worker
Machine 3 monitor → watches M0 Nginx, M1 web, M2 web, M1 PostgreSQL, M1 Redis, M1 worker
```
 
### Implementation
 
HTTP health checks against `GET /health/` on each web instance and a dedicated
worker health endpoint. TCP connection checks against M1 port 5432 (PostgreSQL)
and Redis ports. This avoids needing SSH or Docker daemon access across machines.
 
For the stale flush check, the monitor queries the `last_flush_at` timestamp
stored in PostgreSQL and compares it against the current time.
 
### What Triggers Alert Mail
 
1. **Worker down** — worker health endpoint on M1 stops responding.
2. **Web container exhausted restarts** — container is stopped with a high restart
   count, indicating it hit max_attempts rather than being intentionally stopped.
3. **2+ web instances down simultaneously** — monitor counts how many of the three
   web health endpoints are responding; alerts when fewer than two are alive.
4. **Any whole machine down** — covered by the above: a dead machine causes all
   its health endpoints to stop responding, triggering rules 1–3.
5. **PostgreSQL unreachable** — TCP connection to M1:5432 fails. All web instances
   write to M1 primary — this is an immediate full-service outage.
6. **Redis unreachable** — worker stops flushing; tasks accumulate in PostgreSQL
   but are not lost.
7. **Flush timestamp stale** — last recorded flush in PostgreSQL is older than 2×
   the production flush interval (60 minutes). Indicates the worker is alive but
   not flushing, most likely because Django-Q did not re-register its schedule
   after a Redis restart.
8. **Nginx down** — M0 health endpoint stops responding. Service is completely
   unreachable. Alert only, no automatic failover.
### Backup Verification
 
Once per day, confirm the latest backup file exists and is non-empty. A silent
backup failure is worse than no backup at all — it creates false confidence.
This check runs as part of the monitor script on M2 or M3.
 
### Log File Fallback
 
Every alert is written to a local log file before sending mail. If SMTP is down,
the log remains as evidence.