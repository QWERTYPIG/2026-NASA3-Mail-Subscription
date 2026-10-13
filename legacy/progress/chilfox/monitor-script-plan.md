# Monitor Script Implementation Plan

This plan is based on docs/architecture.md, docs/HA.md, docs/sync.md, docs/setup.md, docs/ldap.md, and progress/chilfox/monitor-script-proposal.md.

## Phase 1: Wire runtime configuration for HA roles

1. Update docker-compose.yml so web and worker load both `.env` and `.env.role`. This requires adding `.env.role` to each service's `env_file` list and removing or adjusting any `environment:` entries that would override `DB_HOST`, `REDIS_QUEUE_URL`, `REDIS_CACHE_URL`, or the new `FLUSH_ENABLED`. Use `.env` for defaults and `.env.role` for monitor-written overrides so the active role can switch without editing `.env`.
2. Add `FLUSH_ENABLED` gate in apps/subscriptions/tasks.py. At the top of `flush_ldap_tasks()`, read `FLUSH_ENABLED` from environment and return early with a clear log if it is not `"1"`. This prevents standby workers from writing to LDAP while keeping the schedule intact.
3. Extend scripts/db_sync.sh to load both `.env` and `.env.role`. Add a second env file variable (for example `ENV_ROLE`) and parse it the same way as `ENV_FILE`. After a successful sync, write a timestamp to the monitor’s `LAST_SYNC_FILE` (from env) so the monitor can enforce failback freshness. Keep the script stdlib and avoid any LDAP operations.

## Phase 2: Add the host-level monitor script

1. Create a new script in the repo, for example `scripts/monitor/monitor.py`, implemented with Python standard library only. It should read its configuration from `/etc/mailsub/monitor.env` (loaded by systemd), including IPs, thresholds, compose paths, and env file paths described in the proposal.
2. Implement a lightweight HTTP server on `MONITOR_PORT` that exposes `/health` and returns JSON with:
   - `worker_running`: whether the worker container is running.
   - `db_sync_ready`: whether `scripts/db_sync.sh` exists and `pg_dump`, `pg_restore`, `psql` are available inside the worker container.
   Use `docker compose ps` and `docker compose exec -T worker ...` for checks.
3. Implement core checks and leader election:
   - TCP reachability for PostgreSQL (5432) and Redis (6379) on each peer.
   - Peer `/health` HTTP check for `worker_running` and `db_sync_ready`.
   - Determine `ACTIVE` as the highest-priority healthy machine (mail1 > mail2 > mail3).
   - Apply failure and recovery thresholds (FAIL_THRESHOLD and RECOVER_THRESHOLD).
   - Enforce the peer-reachability fence, then allow degraded self-activation after `DEGRADED_THRESHOLD` intervals with a warning.
4. Implement role application and container reload:
   - Write `.env.role` atomically with `DB_HOST`, `REDIS_QUEUE_URL`, `REDIS_CACHE_URL`, `FLUSH_ENABLED`.
   - Use `docker compose -f $COMPOSE_FILE up -d --force-recreate web worker` to apply changes.
   - When becoming ACTIVE, ensure local PostgreSQL is writable and treat it as primary by setting `DB_HOST` to the local IP in `.env.role`.
5. Implement DB sync scheduling:
   - Only run sync on ACTIVE.
   - Enforce `SYNC_INTERVAL` using `LAST_SYNC_FILE`.
   - Execute `docker compose exec -T worker scripts/db_sync.sh` and log failures.
   - Use `LAST_SYNC_FILE` age to gate failback (must be <= 20 minutes).

## Phase 3: systemd service and host configuration

1. Add a sample systemd unit file (for example `scripts/monitor/mailsub-monitor.service`) that runs the monitor as a host daemon, using:
   - `WorkingDirectory=/opt/mailsub`
   - `ExecStart=/usr/bin/python3 /opt/mailsub/scripts/monitor/monitor.py`
   - `EnvironmentFile=/etc/mailsub/monitor.env`
   - `Restart=always`
2. Add a sample `monitor.env` template in the repo (for example `scripts/monitor/monitor.env.example`) with all variables listed in the proposal. Include comments for each variable and keep secrets out of the repo.
3. Provide operator steps in docs to copy files into place, enable, and start the service:
   - `sudo install -m 0644 scripts/monitor/mailsub-monitor.service /etc/systemd/system/`
   - `sudo install -m 0640 scripts/monitor/monitor.env.example /etc/mailsub/monitor.env`
   - `sudo systemctl daemon-reload && sudo systemctl enable --now mailsub-monitor`

## Phase 4: Documentation updates

1. Update docs/HA.md to describe the monitor daemon, `.env.role` behavior, and the failover/failback rules that match the proposal.
2. Update docs/setup.md to document `.env.role`, `FLUSH_ENABLED`, `DB_REPLICA_HOSTS`, and the new monitor-specific env file at `/etc/mailsub/monitor.env`.
3. Update docs/sync.md to mention that `flush_ldap_tasks()` is gated by `FLUSH_ENABLED` and should only run on the ACTIVE host.

## Phase 5: Verification steps

1. Run unit tests for subscriptions after code changes: `docker compose exec web python manage.py test apps.subscriptions`.
2. Run the monitor in the foreground on one host with short intervals to verify:
   - `/health` returns expected JSON.
   - `.env.role` updates when ACTIVE changes.
   - `docker compose up -d --force-recreate web worker` is triggered only when role changes.
3. Simulate failover by stopping local PostgreSQL or Redis containers and confirm:
   - the monitor demotes the host after FAIL_THRESHOLD,
   - a higher-priority healthy host becomes ACTIVE,
   - standby workers have `FLUSH_ENABLED=0`.
4. Trigger `scripts/db_sync.sh` via monitor and confirm `LAST_SYNC_FILE` is updated and used to gate failback.
