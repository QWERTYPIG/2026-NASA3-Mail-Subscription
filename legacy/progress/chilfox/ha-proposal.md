# High Availability Proposal (Refactored)

## Principles / Context
- LDAP is the source of truth. All LDAP writes are performed by the Django-Q worker.
- PostgreSQL is a cache + task queue only.
- Goal: keep the web layer reachable and ensure background sync continues.
- Nginx on mail4 is an accepted single point of failure.

---

## Machines & Containers

### mail1 / mail2 / mail3
Each runs **four containers**:
- `web`
- `postgres`
- `worker` (Django-Q + DB sync worker)
- `redis`

### mail4
- `nginx` only (dedicated reverse proxy)

---

## Role Model & Priority

Priority: **mail1 > mail2 > mail3**

At any time, exactly **one machine is ACTIVE** for:
- PostgreSQL primary
- Redis
- Django-Q flush + consistency check
- DB sync worker

Other machines are **STANDBY** for those roles.

All three `web` containers are always active and receive traffic.

### Role Matrix

| Role | Active host | Standby hosts | Notes |
|---|---|---|---|
| Web | mail1/2/3 | — | All three receive traffic |
| PostgreSQL primary | highest-priority alive | others | standby is **not read/write**, only sync |
| Redis | highest-priority alive | others | standby not used |
| Worker flush | highest-priority alive | others | standby runs but does not flush |
| DB sync worker | highest-priority alive | others | runs inside worker container |

---

## Traffic & Connections
- Nginx on **mail4** routes requests to `web` on mail1/2/3 (LB algorithm TBD).
- Web instances connect **only** to the ACTIVE PostgreSQL and ACTIVE Redis.
- Standby PostgreSQL is **not used by API at all** (no read, no write), only receives sync.

---

## PostgreSQL (cache + task queue)
- Primary lives on the ACTIVE machine.
- Standby replicas live on the other two machines.
- DB sync worker (inside worker container) runs `scripts/db_sync.sh` every **10 min** (pg_dump → pg_restore).
  - Primary is `DB_HOST` in the ACTIVE machine's `.env`.
  - Replicas from `DB_REPLICA_HOSTS` (defaults to mail1/2/3).
  - Requires `pg_dump`, `pg_restore`, `psql` (`postgresql-client`) on the worker machine.
  - The script itself has no lock; the parent scheduler/monitor ensures only ACTIVE runs.
  - If any replica is unreachable, the script exits with error.
- Failover is automatic by monitor (see below).

**Expected staleness:** replicas may be up to **10 minutes behind**.  
On promotion, tasks and metadata created after the last sync may be lost.  
LDAP remains the source of truth.

---

## Worker (Django-Q)
- All worker containers are running.
- Only the ACTIVE worker executes **flush + consistency check** (**every 30 min**).
- Standby workers remain idle (no flush).
- Activation is controlled by monitor via environment variables (mechanism TBD).

---

## Redis
- Only ACTIVE Redis is used.
  - DB 0: Django-Q lock / scheduler trigger
  - DB 1: rate-limit TTL keys
- Standby Redis is not used.
- Redis data is non-persistent; losing rate-limit keys is acceptable.

---

## Nginx (mail4)
- Dedicated reverse proxy.
- If mail4 is down, the service is unreachable (accepted).
- DNS points to mail4 (if not set yet, it is a pending infra task).

---

## Monitoring & Failover
- A monitor runs on **each machine**.
- Monitors determine active/standby by priority and update env-based role flags.
- When the ACTIVE machine or any core service fails, monitor promotes the next machine automatically.
- **Failback:** when a higher-priority machine recovers, monitor automatically switches back.

**TBD**
- How env changes are applied (restart/rolling/etc).
- Health-check method (HTTP / TCP / container status).

---

## TBD / To Be Filled After Implementation
- DB sync scheduler trigger & lock coordination (cron vs monitor).
- Monitor health-check method and env variable schema.
- Nginx health-check behavior / backend removal strategy.
