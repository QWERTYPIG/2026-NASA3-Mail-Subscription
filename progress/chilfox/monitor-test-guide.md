# Monitor Script — Server-Side Test Guide (Phase 5)

Run these steps on the HA servers (mail1/mail2/mail3) after deploying the monitor daemon.

---

## Prerequisites

- monitor daemon installed and configured per `docs/setup.md`
- `.env` and `.env.role` in `/opt/mailsub/`
- `LAST_SYNC_FILE` path exists and is writable by the monitor

---

## Step 1: Foreground smoke test

Run the monitor manually with a short check interval on **mail1** to observe behavior without systemd interference:

```bash
sudo CHECK_INTERVAL=5 FAIL_THRESHOLD=2 RECOVER_THRESHOLD=1 \
  python3 /opt/mailsub/scripts/monitor/monitor.py
```

**Verify:**

```bash
# From any machine on the LAN
curl http://172.16.127.102:9123/health
# Expected:
# {"worker_running": true, "db_sync_ready": true}
```

Check that `.env.role` reflects ACTIVE state:

```bash
cat /opt/mailsub/.env.role
# DB_HOST should equal this machine's IP
# FLUSH_ENABLED=1
```

Confirm containers were (re)started when ACTIVE was first determined:

```bash
docker compose -f /opt/mailsub/docker-compose.yml ps
# web and worker should be running
```

---

## Step 2: Failover — stop PostgreSQL on mail1

On **mail1** (current ACTIVE), stop the postgres container:

```bash
docker compose -f /opt/mailsub/docker-compose.yml stop postgres
```

Watch monitor logs on mail1 (in the foreground session or journalctl):

```bash
sudo journalctl -u mailsub-monitor -f
```

**Expected sequence:**
1. mail1 monitor logs `candidate ACTIVE=172.16.127.116 (1/2)`, `(2/2)` (FAIL_THRESHOLD hits)
2. mail2 monitor logs `ACTIVE transition None -> 172.16.127.116`
3. mail2 writes `.env.role` with `DB_HOST=172.16.127.116` and `FLUSH_ENABLED=1`
4. mail2 restarts web/worker

**Verify on mail2:**

```bash
cat /opt/mailsub/.env.role
# DB_HOST=172.16.127.116
# FLUSH_ENABLED=1

docker compose -f /opt/mailsub/docker-compose.yml ps
# web and worker running
```

**Verify on mail1 (now STANDBY):**

```bash
cat /opt/mailsub/.env.role
# DB_HOST=172.16.127.116
# FLUSH_ENABLED=0
```

---

## Step 3: Failback — restore PostgreSQL on mail1

Restart postgres on mail1:

```bash
docker compose -f /opt/mailsub/docker-compose.yml start postgres
```

**Expected sequence (after RECOVER_THRESHOLD consecutive healthy checks):**
1. mail1 monitor checks `LAST_SYNC_FILE` — must be ≤ 20 min old
2. mail1 checks local postgres is writable (`pg_is_in_recovery() = f`)
3. mail1 logs `ACTIVE transition 172.16.127.116 -> 172.16.127.102`
4. mail1 writes `.env.role` with `FLUSH_ENABLED=1`, restarts web/worker
5. mail2 writes `.env.role` with `FLUSH_ENABLED=0`, restarts web/worker

**If failback is blocked** (sync too old), you'll see:
```
failback blocked: last sync too old or missing.
```
Trigger a manual sync first (see Step 4), then wait for RECOVER_THRESHOLD.

---

## Step 4: DB sync — trigger and verify LAST_SYNC_FILE

On the current ACTIVE machine, trigger a sync manually to confirm the mechanism works before relying on the scheduled run:

```bash
docker compose -f /opt/mailsub/docker-compose.yml exec -T worker scripts/db_sync.sh
```

**Verify sync marker written:**

```bash
cat /var/lib/mailsub/last_sync
# Should be a Unix timestamp (epoch seconds)
date -d @$(cat /var/lib/mailsub/last_sync)
# Should be within the last minute
```

**Verify failback freshness gating**: set the timestamp to stale and confirm failback is blocked:

```bash
# Simulate stale sync (25 min ago, beyond 2*SYNC_INTERVAL=20 min)
echo $(($(date +%s) - 1500)) | sudo tee /var/lib/mailsub/last_sync

# Force failover/failback cycle and watch logs for:
# "failback blocked: last sync too old or missing."
```

Restore a fresh timestamp to re-enable failback:

```bash
date +%s | sudo tee /var/lib/mailsub/last_sync
```

---

## Step 5: Standby worker flush check

While mail2 is STANDBY, confirm its worker does NOT flush LDAP:

```bash
# On mail2
docker compose -f /opt/mailsub/docker-compose.yml exec worker \
  python manage.py shell -c "import os; print(os.environ.get('FLUSH_ENABLED'))"
# Expected: 0

# Check worker logs for the skip message
docker compose -f /opt/mailsub/docker-compose.yml logs worker | grep FLUSH_ENABLED
# Expected: "flush_ldap_tasks: FLUSH_ENABLED is not 1, skipping"
```

---

## Step 6: Split-brain / peer fence check

Simulate network isolation on mail1 (block peer HTTP port) and confirm degraded mode kicks in after `DEGRADED_THRESHOLD` intervals:

```bash
# On mail1 — block outbound to peer monitor ports
sudo iptables -A OUTPUT -p tcp --dport 9123 -j DROP
```

Watch logs on mail1:

```bash
sudo journalctl -u mailsub-monitor -f
```

**Expected:**
1. `no peers reachable; deferring self-activation until degraded threshold.`
2. After `DEGRADED_THRESHOLD × CHECK_INTERVAL` seconds (default 8 × 15s = 2 min):
   `no peers reachable; entering degraded mode for self-activation.`

Restore:

```bash
sudo iptables -D OUTPUT -p tcp --dport 9123 -j DROP
```

---

## Quick Pass/Fail Checklist

| Test | Expected result |
|------|----------------|
| `/health` returns JSON | `worker_running: true, db_sync_ready: true` |
| `.env.role` on ACTIVE | `FLUSH_ENABLED=1`, `DB_HOST=own IP` |
| `.env.role` on STANDBY | `FLUSH_ENABLED=0`, `DB_HOST=ACTIVE IP` |
| Failover after FAIL_THRESHOLD | New ACTIVE elected, containers restarted |
| Failback blocked if stale | Log: `failback blocked: last sync too old` |
| Failback allowed if fresh | Role transitions to higher-priority machine |
| Standby worker skip log | `FLUSH_ENABLED is not 1, skipping` |
| Degraded mode entry | Log: `entering degraded mode for self-activation` |
