#!/usr/bin/env bash
# vc-remote.sh — Stage 2 remote checks
# Usage: ./vc-remote.sh <user>@<ip> 2>&1 | tee logs/vc-<machine>-$(date +%Y%m%d).log
set -euo pipefail

mkdir -p logs

TARGET=$1
echo "=== Running remote VC on $TARGET ==="

ssh "$TARGET" bash << 'REMOTE'
echo "--- [2-A] Trivy image scan ---"
for IMAGE in \
  2026-nasa3-mail-subscription-web:latest \
  2026-nasa3-mail-subscription-worker:latest \
  2026-nasa3-mail-subscription-frontend:latest; do
  echo "=== $IMAGE ==="
  docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    aquasec/trivy:latest image \
    --severity HIGH,CRITICAL \
    "$IMAGE"
done

echo "--- [2-B] Port exposure ---"
ss -tlnp | grep -E '5432|6379|9123|8000|55111' || echo "(no matching ports)"

echo "--- [2-C] Redis unauthenticated access ---"
redis-cli -h 127.0.0.1 -p 6379 ping 2>/dev/null \
  && echo "WARN: Redis accepts unauthenticated connections" \
  || echo "INFO: redis-cli not installed or connection refused"

echo "--- [2-D] Container env vars (key check only) ---"
docker compose -f ~/mailsub/docker-compose.yml exec -T web env \
  | grep -E '^(DEBUG|ALLOWED_HOSTS|SECRET_KEY)=' \
  | sed 's/SECRET_KEY=.*/SECRET_KEY=<redacted>/'

echo "--- [2-E] Docker socket mount ---"
docker inspect $(docker ps -q) \
  --format '{{.Name}}: {{range .Mounts}}{{.Source}} {{end}}' \
  | grep docker.sock && echo "WARN: docker.sock mounted" || echo "PASS: no docker.sock mount"

echo "--- [2-F] Postgres authentication ---"
docker compose -f ~/mailsub/docker-compose.yml exec -T db psql -U postgres -c '\l' 2>&1 \
  && echo "WARN: postgres accepts no-password connection" \
  || echo "PASS: postgres requires auth"

echo "--- [2-G] Container running user ---"
echo -n "web: "; docker compose -f ~/mailsub/docker-compose.yml exec -T web whoami
echo -n "worker: "; docker compose -f ~/mailsub/docker-compose.yml exec -T worker whoami

echo "--- [2-I] LDAP URI protocol ---"
docker compose -f ~/mailsub/docker-compose.yml exec -T web env | grep LDAP_URI
REMOTE

echo "=== Done: $TARGET ==="
