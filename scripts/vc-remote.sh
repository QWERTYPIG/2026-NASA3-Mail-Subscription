#!/usr/bin/env bash
# vc-remote.sh — Stage 2 remote checks
# Requires sudo on the remote machine
# Usage: ./scripts/vc-remote.sh <user>@<ip> 2>&1 | tee logs/vc-<machine>-$(date +%Y%m%d).log
set -euo pipefail

mkdir -p logs

TARGET=$1
REMOTE_TMP="/tmp/vc-checks-$$.sh"
LOCAL_TMP=$(mktemp)

echo "=== Running remote VC on $TARGET ==="

cat > "$LOCAL_TMP" << 'CHECKS'
# Project location on the remote host (override with PROJECT_DIR=... if it differs).
PROJECT_DIR="${PROJECT_DIR:-/home/$SUDO_USER/2026-NASA3-Mail-Subscription}"
COMPOSE="docker compose -f $PROJECT_DIR/docker-compose.yml"

echo "--- [2-A] Trivy image scan ---"
# Derive image names from compose; don't hardcode the project prefix (it tracks the checkout dir name).
for IMAGE in $($COMPOSE config --images); do
  echo "=== $IMAGE ==="
  docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    aquasec/trivy:latest image \
    --severity HIGH,CRITICAL \
    --ignore-unfixed \
    --exit-code 1 \
    "$IMAGE" \
    || echo "FAIL: $IMAGE has fixable HIGH/CRITICAL CVEs"
done

echo "--- [2-B] Port exposure (informational) ---"
# 5432/6379 are intentionally LAN-reachable for HA cross-node access, so a 0.0.0.0
# bind is expected here; the security control is auth on those services (see 2-C/2-F).
ss -tlnp | grep -E '5432|6379|9123|8000|55111' || echo "(no matching ports)"

echo "--- [2-C] Redis unauthenticated access ---"
# Probe from the host network namespace, NOT via docker exec into the redis container
# (inside-container ping goes over loopback and passes regardless of auth/exposure).
docker run --rm --network host redis:7-alpine \
  redis-cli -h 127.0.0.1 -p 6379 ping 2>/dev/null \
  && echo "FAIL: Redis answers PING without auth" \
  || echo "PASS: Redis requires auth (or not reachable on 127.0.0.1)"

echo "--- [2-D] Container env vars (assert-only, values never printed) ---"
# Capture env once; pipe into grep -q so nothing is ever echoed to the log.
ENV_DUMP=$($COMPOSE exec -T web env)
grep -q '^DEBUG=False$'                <<<"$ENV_DUMP" && echo 'PASS: DEBUG=False'                || echo 'NOTE: DEBUG=True (accepted risk, see vc.md)'
grep -q '^ALLOWED_HOSTS=\*$'           <<<"$ENV_DUMP" && echo 'FAIL: ALLOWED_HOSTS is *'         || echo 'PASS: ALLOWED_HOSTS is not *'
grep -q '^SECRET_KEY='                 <<<"$ENV_DUMP" && echo 'PASS: SECRET_KEY is set'          || echo 'FAIL: SECRET_KEY missing'
grep -q '^SECRET_KEY=django-insecure-' <<<"$ENV_DUMP" && echo 'FAIL: SECRET_KEY is django-insecure-*' || echo 'PASS: SECRET_KEY is not the insecure default'
grep -q '^DB_PASSWORD=password$'       <<<"$ENV_DUMP" && echo 'FAIL: DB_PASSWORD still default'  || echo 'PASS: DB_PASSWORD not default (or not exposed)'

echo "--- [2-E] Docker socket mount ---"
docker inspect $(docker ps -q) \
  --format '{{.Name}}: {{range .Mounts}}{{.Source}} {{end}}' \
  | grep docker.sock && echo "WARN: docker.sock mounted" || echo "PASS: no docker.sock mount"

echo "--- [2-F] Postgres authentication ---"
# Probe over TCP from the host with NO password, expecting rejection (not docker exec, which
# uses the local socket's trust/peer auth and would pass regardless). Service is 'postgres', user 'MailAdmin'.
docker run --rm --network host -e PGPASSWORD= postgres:15-alpine \
  psql -h 127.0.0.1 -p 5432 -U "${DB_USER:-MailAdmin}" -d "${DB_NAME:-Subscriptions}" -c '\q' 2>/dev/null \
  && echo "FAIL: postgres accepts no-password TCP login" \
  || echo "PASS: postgres rejects no-password TCP login"

echo "--- [2-G] Container running user ---"
echo -n "web: "; $COMPOSE exec -T web whoami
echo -n "worker: "; $COMPOSE exec -T worker whoami

echo "--- [2-H] Monitor daemon file permissions ---"
echo -n ".env.role:   "; ls -la "$PROJECT_DIR/.env.role" 2>/dev/null || echo "(not found)"
echo -n "monitor.env: "; ls -la /etc/mailsub/monitor.env 2>/dev/null || echo "(not found)"
echo -n "db_sync.sh:  "; ls -la "$PROJECT_DIR/scripts/db_sync.sh" 2>/dev/null || echo "(not found)"

echo "--- [2-I] LDAP URI protocol ---"
$COMPOSE exec -T web env | grep LDAP_URI
CHECKS

scp -q "$LOCAL_TMP" "$TARGET:$REMOTE_TMP"
rm -f "$LOCAL_TMP"

ssh -t "$TARGET" "sudo bash $REMOTE_TMP; sudo rm -f $REMOTE_TMP"

echo "=== Done: $TARGET ==="
