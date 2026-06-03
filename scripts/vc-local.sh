#!/usr/bin/env bash
# vc-local.sh — Stage 1 local scan (checks NOT covered by CI)
# CI covers: gitleaks (.github/workflows/gitleaks.yml),
#            pip-audit + npm audit (.github/workflows/dep-cve.yml),
#            bandit (.github/workflows/bandit.yml)
# Usage: ./vc-local.sh 2>&1 | tee logs/vc-local-$(date +%Y%m%d).log
set -euo pipefail

echo "=== [1-D] Django deploy check ==="
docker compose run --rm \
  -e DJANGO_SETTINGS_MODULE=core.settings \
  web python manage.py check --deploy || true

echo ""
echo "=== Done. ==="
