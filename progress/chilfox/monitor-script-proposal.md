# Monitor Script Proposal (Aligned with HA Proposal)

## Overview

A monitor process runs on each of mail1/mail2/mail3 as a **host-level daemon** (not inside Docker). It runs a health-check loop every **15 seconds**, independently determines which machine should be ACTIVE, and performs failover/failback when the determination changes.

The monitor is **stdlib-only Python**, managed by **systemd**, configured via `/etc/mailsub/monitor.env`, and exposes a small **HTTP health endpoint** on `:9123` for peer checks (no auth, bound to private LAN).

mail4 (nginx) has no monitor; it is an accepted SPOF. Nginx uses **passive** backend health checks (`max_fails`/`fail_timeout`) only.

This version is aligned with `ha-proposal.md`:
- **Only one ACTIVE machine** handles PostgreSQL primary, Redis, worker flush, and DB sync.
- **Standby machines do not read/write DB** and do not perform worker flush.
- **Failback is automatic** when a higher-priority machine recovers.

---

## Leader Election

No external consensus store. Each monitor independently applies the same deterministic rule with **stability guards**:

> **ACTIVE = the highest-priority machine whose core services are healthy.**

Priority: mail1 > mail2 > mail3.

### Core Services (must all be healthy)
- PostgreSQL reachable (TCP 5432)
- Redis reachable (TCP 6379)
- Worker healthy (flush-capable when ACTIVE)
- DB sync worker available (runs inside worker container)

If **any core service on a machine is down**, that machine is **not eligible** to be ACTIVE.

### Stability + Split-Brain Guard
- **Failover threshold:** require N consecutive failed checks (default **3**, i.e., ~45s).
- **Failback threshold:** require M consecutive successful checks (default **2**).
- **Peer-reachability fence:** normally require at least one peer monitor reachable to activate.
- **Degraded mode fallback:** if **no peers reachable for a long window** (e.g., 2–5 minutes), allow self-activation with a degraded-mode warning to avoid total downtime.
- **No eligible ACTIVE:** keep current role/targets and log warning (do not force switch).

---

## Health Check Detail

| Check | Method | Target | Required for ACTIVE? |
|---|---|---|---|
| PostgreSQL reachable | TCP 5432 | peer IPs | Yes |
| Redis reachable | TCP 6379 | peer IPs | Yes |
| Worker healthy | peer `http://<ip>:9123/health` | peer IPs | Yes |
| DB sync worker available | peer `http://<ip>:9123/health` | peer IPs | Yes |

Notes:
- The monitor’s local **/health** endpoint reports:
  - `worker_running`: worker container is running
  - `db_sync_ready`: `scripts/db_sync.sh` exists and `pg_dump/pg_restore/psql` are available **inside the worker container**
- No SSH is used; peer checks are TCP + HTTP only.
- Web health is *not* part of leader election (web can be restarted independently).

---

## Failover Procedure

When monitor detects ACTIVE changed from `old_ip` → `new_ip`:

### On the machine that becomes ACTIVE (`new_ip`)
1. **Write dynamic env file** `.env.role` to ACTIVE:
   - `DB_HOST=<own IP>`
   - `REDIS_QUEUE_URL=redis://<own IP>:6379/0`
   - `REDIS_CACHE_URL=redis://<own IP>:6379/1`
   - `FLUSH_ENABLED=1`
2. **Promote local PostgreSQL to primary** (dump/restore model):
   - ensure local PG is writable
   - DB sync direction becomes outbound from this host (via `scripts/db_sync.sh`)
3. **Reload containers** to pick up `.env.role`:
   ```
   docker compose up -d --force-recreate web worker
   ```

### On STANDBY machines
1. **Write dynamic env file** `.env.role` to STANDBY:
   - `DB_HOST=<new_ip>`
   - `REDIS_QUEUE_URL=redis://<new_ip>:6379/0`
   - `REDIS_CACHE_URL=redis://<new_ip>:6379/1`
   - `FLUSH_ENABLED=0`
2. **Reload containers**:
   ```
   docker compose up -d --force-recreate web worker
   ```

Standby DB is **not used by API** (no read/write); it only receives sync.

---

## Failback Procedure

When a higher-priority machine (e.g., mail1) recovers:

1. Monitor detects that its **core services are healthy**.
2. **Failback requires freshness:** only promote if `last_sync` age ≤ **20 minutes** (2× sync interval).
3. If freshness check fails, stay on current ACTIVE and log warning.
4. Other monitors detect the new ACTIVE and switch DB/Redis targets accordingly.

---

## DB Sync (Primary → Standby, every 10 min)

- **Runs only on the ACTIVE machine**, triggered by the monitor.
- Execution is **inside the worker container**:
  ```
  docker compose exec -T worker scripts/db_sync.sh
  ```
- Implementation: `scripts/db_sync.sh` using `pg_dump` on primary and `pg_restore` on replicas.
- Primary is `DB_HOST` from `.env` + `.env.role`; replicas from `DB_REPLICA_HOSTS` (defaults to mail1/2/3).
- `scripts/db_sync.sh` must **load both** `.env` and `.env.role`.
- Requires `pg_dump`, `pg_restore`, `psql` (`postgresql-client`) on the machine/container running the script.
- The script itself has no lock; the monitor ensures only ACTIVE runs and enforces interval.
- After successful restore, the script **writes a local sync marker** (e.g., `/var/lib/mailsub/last_sync`) readable by the host monitor.
- If any replica is unreachable, the script exits with error.
- Standby machines do **not** run DB sync themselves.

---

## Worker Flush Control

- Only the ACTIVE worker runs **flush + consistency check** (Django-Q schedule: **every 3 min**).
- Standby workers remain idle.
- The worker checks **`FLUSH_ENABLED=1`** in `flush_ldap_tasks()`; otherwise it returns early.
- Duplicate flush after failover is acceptable; treat **LDAPNoSuchObject** as idempotent for alias delete + user modify to avoid noisy failures.

Redis lock is still useful as a safety net but is **not** the primary control mechanism.

---

## Environment Variables

### Static per machine (written once by operator)
```dotenv
THIS_MACHINE_IP=172.16.127.102   # 102 for mail1, 116 for mail2, 117 for mail3
THIS_MACHINE_NAME=mail1          # mail1 / mail2 / mail3
DB_NAME=Subscriptions
DB_USER=MailAdmin
DB_PASSWORD=********
DB_REPLICA_HOSTS=mail1,mail2,mail3
# Monitor config
MONITOR_PORT=9123
CHECK_INTERVAL=15
FAIL_THRESHOLD=3
RECOVER_THRESHOLD=2
DEGRADED_THRESHOLD=8   # e.g., 8 * 15s = 2 min
SYNC_INTERVAL=600      # seconds
COMPOSE_FILE=/opt/mailsub/docker-compose.yml
ENV_BASE=/opt/mailsub/.env
ENV_ROLE=/opt/mailsub/.env.role
LAST_SYNC_FILE=/var/lib/mailsub/last_sync
```

### Modified by monitor at runtime (`.env.role`)
| Variable | Purpose |
|---|---|
| `DB_HOST` | points to ACTIVE PostgreSQL |
| `REDIS_QUEUE_URL` | points to ACTIVE Redis (DB 0) |
| `REDIS_CACHE_URL` | points to ACTIVE Redis (DB 1) |
| `FLUSH_ENABLED` | `1` when ACTIVE, `0` when STANDBY |

`docker compose` should load both env files (e.g., `env_file: [.env, .env.role]`).

---

## Monitor Script Structure (Python, high level)

```
monitor.py
├── Config
│   ├── PEERS = [(1, "172.16.127.102"), (2, "172.16.127.116"), (3, "172.16.127.117")]
│   ├── THIS_IP = os.environ["THIS_MACHINE_IP"]
│   ├── CHECK_INTERVAL = 15  # seconds
│   ├── FAIL_THRESHOLD = 3
│   ├── RECOVER_THRESHOLD = 2
│   ├── DEGRADED_THRESHOLD = 8
│   ├── SYNC_INTERVAL = 600  # seconds
│   ├── HEALTH_PORT = 9123
│   ├── COMPOSE_FILE, ENV_BASE, ENV_ROLE, LAST_SYNC_FILE
│   └── PG_PORT = 5432, REDIS_PORT = 6379
│
├── health_check(ip) → bool
│   ├── pg_reachable(ip)
│   ├── redis_reachable(ip)
│   ├── peer_health_http(ip)  # worker_running + db_sync_ready
│   └── peer_reachable(ip)    # used for split-brain fence
│
├── determine_active_ip() → str
│   └── iterate PEERS by priority; return first that passes all core checks
│
├── apply_role(new_active_ip)
│   ├── write_env_role(DB_HOST, REDIS_QUEUE_URL, REDIS_CACHE_URL, FLUSH_ENABLED)
│   ├── if new_active_ip == THIS_IP:
│   │   └── promote_local_postgres_if_needed()
│   └── docker_compose_up(["web", "worker"], force_recreate=True)
│
├── maybe_run_db_sync()
│   ├── if ACTIVE and now - last_sync >= SYNC_INTERVAL:
│   │   └── docker compose exec -T worker scripts/db_sync.sh
│   └── read LAST_SYNC_FILE for freshness gating
│
├── main loop:
│   ├── current_active = determine_active_ip()
│   ├── apply failover/failback thresholds + degraded-mode fence
│   ├── if current_active != last_active:
│   │   ├── log transition
│   │   └── apply_role(current_active)
│   ├── last_active = current_active
│   ├── maybe_run_db_sync()
│   └── sleep(CHECK_INTERVAL)
```

---

## Tunable Parameters (defaults)

| Item | Default |
|---|---|
| Check interval | 15s |
| Failover threshold | 3 consecutive failures |
| Failback threshold | 2 consecutive successes |
| Degraded-mode threshold | 2–5 min with no peers |
| DB sync interval | 10 min |
| Failback freshness | ≤ 20 min since last sync |
