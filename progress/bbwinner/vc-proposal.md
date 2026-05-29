# Vulnerability Check Proposal

## Goal

建立一套「可重複、可自動化」的弱點檢查流程，涵蓋：依賴套件 CVE、機密外洩、Django 部署安全設定、Docker image CVE、以及 production 機器上的執行期配置。

本流程分為兩個執行環境：
- **Local（repo 本機）**：靜態掃描，不需要連線到 production。
- **Remote（SSH 進 mail1/2/3）**：執行期配置檢查，需要 SSH 權限。

---

## Scope

| 類別 | 對象 |
|------|------|
| Backend | Django/DRF（`requirements.txt`、`apps/`） |
| Frontend | Vite/React（`frontend/package-lock.json`） |
| Docker | `Dockerfile`、`docker-compose.yml` |
| Secrets | `.env*`、hardcoded credentials、git history |
| Runtime config | production 機器上的 env var、Redis、Postgres、port 暴露 |
| HA infra | monitor daemon、`.env.role`、`scripts/db_sync.sh` 權限 |

## Non-goals

- 不做滲透測試（PT）/ fuzzing
- 不修改 LDAP（本 repo 原則：LDAP write 只能走 worker queue）
- 不評估 LDAP server 本身（由 identity service 組維護）

---

## Machines

| 名稱 | IP | 角色 |
|------|----|------|
| mail1 | 172.16.127.102 | default ACTIVE（DB/Redis primary） |
| mail2 | 172.16.127.116 | STANDBY |
| mail3 | 172.16.127.117 | STANDBY |
| mail4 | 172.16.127.118 | Nginx reverse-proxy（不在本 VC 範圍） |

---

## Known Issues

| # | Issue | Severity | 狀態 | 負責人 | PR / Commit |
|---|-------|----------|------|--------|-------------|
| 1 | Login `/api/v1/auth/login/` 無 rate limiting，可暴力破解 LDAP bind | High | 待修 | | |
| 2 | Redis 無密碼 | High | 待確認（視 port 暴露範圍） | | |
| 3 | `axios` high severity CVE（frontend） | High | 待升版 | | |
| 4 | `DEBUG=True`、`ALLOWED_HOSTS=["*"]`、hardcoded `SECRET_KEY`（`core/settings.py` 已確認） | High | 待修（env var 化） | | |
| 5 | LDAP 走 `ldap://`（plaintext） | Low | Accepted risk（內網），需記錄 | | |

---

## Proposed Checks

### Stage 1 — Local：靜態掃描（在 repo 本機執行，不需 SSH）

#### 1-A) Secrets / Credentials 掃描

**目的**：確認沒有密碼、token、key 被追蹤進 git（包含 commit history）。

**Step 1**：確認 `.env` 沒被 git 追蹤

```bash
git log --all --full-history --name-only --pretty=format: -- '.env' '.env.*' \
  | grep -v '^\s*$' \
  | grep -v '.env.example' \
  | grep -v '.env.role.example'
```

- `--name-only`：只印檔名，不印 commit message
- `--pretty=format:`：拿掉 commit hash 那行，輸出乾淨一點
- 最後兩個 `grep -v` 把你確定沒問題的過濾掉


**Step 2**：用 gitleaks 掃描整個 git history（含所有 commit）

```bash
docker run --rm \
  -v "$PWD:/repo" \
  zricethezav/gitleaks:latest \
  detect --source=/repo --no-banner --redact
```

gitleaks 會掃 commit history 中每一筆 diff，找出符合 secret pattern 的字串（API key、password、private key 等）。若有輸出，需判斷是否為真正的 secret，並考慮用 `git filter-repo` 從 history 移除。

**Step 3**：手動確認關鍵位置

- `core/settings.py`
- `docker-compose.yml`
- `.env.example`, `.env.role.example`
- `tasks.py`: LDAP

---

#### 1-B) Dependency CVE 掃描

**目的**：確認 Python/JS 依賴套件沒有已知 CVE。

**Frontend（npm）**

```bash
cd frontend
npm audit --package-lock-only --omit=dev
# --package-lock-only：只掃 lockfile，不需安裝
# --omit=dev：只看 production dependencies
```

輸出說明：每筆 advisory 會顯示 severity（critical/high/moderate/low）、受影響套件、以及建議修復版本。`npm audit fix` 可自動升版（注意確認不 breaking change）。

**Backend（pip-audit）**

```bash
pip install --user pip-audit
pip-audit -r requirements.txt
# 對 requirements.txt 中每個套件查詢 OSV/PyPI Advisory 資料庫
```

---

#### 1-C) Python 靜態分析（Bandit）

**目的**：找出常見的 Python 安全寫法問題（SQL injection、shell injection、hardcoded password、不安全的 pickle 等）。

```bash
pip install --user bandit
bandit -r apps/ -ll
# -r：遞迴掃整個 apps/ 目錄
# -ll：只顯示 medium severity 以上
```

重點關注：
- `B105`、`B106`、`B107`：hardcoded password
- `B608`：SQL injection（ORM 之外的 raw query）
- `B301`：pickle 反序列化（Redis queue 若用 pickle）
- `B110`：`except: pass`（吞掉例外，可能隱藏錯誤）

---

#### 1-D) Django 部署安全設定

**目的**：用 Django 官方的 deployment checklist 驗證設定。

```bash
docker compose run --rm \
  -e DJANGO_SETTINGS_MODULE=core.settings \
  web python manage.py check --deploy
```

`--deploy` 會檢查：`DEBUG`、`SECRET_KEY` 強度、`ALLOWED_HOSTS`、`SESSION_COOKIE_SECURE`、`CSRF_COOKIE_SECURE`、`SECURE_HSTS_SECONDS`、`SECURE_SSL_REDIRECT` 等項目，並給出 warning/error 分級。

目標：**所有 System checks 回報 0 issues（或至少 0 errors）**。

---

#### 1-E) HTTP Security Headers 檢查

**目的**：確認 API response 帶有必要的安全 header，防止 XSS、clickjacking。

```bash
# 啟動 stack 後，打 API 看 response headers
curl -sI http://localhost:8000/api/v1/auth/login/ | grep -iE \
  'x-content-type|x-frame-options|content-security-policy|strict-transport'
```

預期要看到的 headers：
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY` 或 `SAMEORIGIN`
- `Content-Security-Policy`（至少限制 `default-src`）

Django 預設**不加這些 headers**，需在 `settings.py` 加入 `SECURE_CONTENT_TYPE_NOSNIFF = True`、`X_FRAME_OPTIONS = 'DENY'` 等設定，或使用 middleware。

---

### Stage 2 — Remote：SSH 進 mail1 / mail2 / mail3 執行

SSH 進每台機器後，以下指令在各機器上獨立執行。除非特別標注，三台都要跑。

```bash
ssh <user>@172.16.127.102   # mail1
ssh <user>@172.16.127.116   # mail2
ssh <user>@172.16.127.117   # mail3
```

---

#### 2-A) Container Image CVE 掃描（Trivy）

**目的**：掃描已 build 的 Docker image 中的 OS 層與 Python/Node 套件 CVE。

```bash
# 在目標機器上，先確認 image 名稱
docker images

# 用 Trivy 掃描（以 web image 為例）
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy:latest image \
  --severity HIGH,CRITICAL \
  mailsub-web:latest     # 替換為實際 image 名稱

# 同樣方式掃 worker、frontend image
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy:latest image \
  --severity HIGH,CRITICAL \
  mailsub-worker:latest
```

Trivy 會掃：OS package（apt/apk）、Python site-packages、npm packages。`--severity HIGH,CRITICAL` 過濾雜訊，只看高風險項目。

---

#### 2-B) Port 暴露檢查

**目的**：確認 Postgres（5432）、Redis（6379）、monitor `/health`（9123）沒有對外暴露。

```bash
ss -tlnp | grep -E '5432|6379|9123|8000|55111'
```

預期結果：

| Port | 預期監聽位址 | 說明 |
|------|-------------|------|
| 5432 | 127.0.0.1 或 Docker 內部網路 | Postgres 不應對外 |
| 6379 | 127.0.0.1 或 Docker 內部網路 | Redis 不應對外 |
| 9123 | LAN（172.16.x.x）或 127.0.0.1 | monitor /health 僅限內網 |
| 8000 | 視設計而定 | web API |
| 55111 | 視設計而定 | frontend |

如果 5432 或 6379 監聽在 `0.0.0.0`，表示該 port 可從外部網路連線，需在 `docker-compose.yml` 改為 `127.0.0.1:5432:5432`。

---

#### 2-C) Redis 認證設定檢查

**目的**：確認 Redis 有設定密碼（或至少確認只允許 Docker 內部網路存取）。

```bash
redis-cli -h 127.0.0.1 -p 6379 ping
# 若回傳 PONG 且無需密碼，表示 Redis 無認證保護
```

若 Redis 無密碼且 port 6379 對 LAN 開放，任何 LAN 上的機器可以：
- `FLUSHDB`：清空 task queue（刪掉所有待 flush 的 LDAP 任務）
- `DEL <user_uid>`：刪除 rate limit key，讓特定 user 可繞過 10 分鐘冷卻

修復方式：在 `docker-compose.yml` 的 redis service 加入 `--requirepass <password>`，並更新 `REDIS_QUEUE_URL` 與 `REDIS_CACHE_URL`。

---

#### 2-D) 執行期環境變數檢查

**目的**：確認 production 機器的環境變數已覆蓋不安全的預設值。

> [!important] 不要把 secrets 印到終端
> 下列指令用 `grep -q` 做判斷，只輸出 PASS/FAIL。

```bash
# DEBUG 必須是 False
(docker compose exec -T web env | grep -q '^DEBUG=False$' \
  && echo 'PASS: DEBUG=False' \
  || echo 'FAIL: DEBUG is not False')

# ALLOWED_HOSTS 不應是 *
(docker compose exec -T web env | grep -q '^ALLOWED_HOSTS=\*$' \
  && echo 'FAIL: ALLOWED_HOSTS is *' \
  || echo 'PASS: ALLOWED_HOSTS is not *')

# SECRET_KEY 必須存在，且不應是 django-insecure- 開頭
(docker compose exec -T web env | grep -q '^SECRET_KEY=' \
  && echo 'PASS: SECRET_KEY is set' \
  || echo 'FAIL: SECRET_KEY missing')

(docker compose exec -T web env | grep -q '^SECRET_KEY=django-insecure-' \
  && echo 'FAIL: SECRET_KEY is django-insecure-*' \
  || echo 'PASS: SECRET_KEY is not django-insecure-*')

# DB_PASSWORD 不應是預設的 password
(docker compose exec -T web env | grep -q '^DB_PASSWORD=password$' \
  && echo 'FAIL: DB_PASSWORD still default' \
  || echo 'PASS: DB_PASSWORD not default (or not exposed)')
```

---

#### 2-E) Docker Socket 掛載檢查

**目的**：確認沒有 container 掛載了 `/var/run/docker.sock`（掛載等於給 container root 權限到 host）。

```bash
docker inspect $(docker ps -q) \
  --format '{{.Name}}: {{range .Mounts}}{{.Source}} {{end}}' \
  | grep docker.sock
# 預期：無輸出
```

---

#### 2-F) Monitor Daemon 檔案權限檢查

**目的**：確認 `.env.role`、`monitor.env`、`db_sync.sh` 沒有過寬的讀取或寫入權限。

```bash
# .env.role：含 DB_HOST / Redis URL，不應 world-readable
ls -la /path/to/project/.env.role
# 預期：-rw------- 或 -rw-r-----

# monitor.env：含 THIS_MACHINE_IP、MONITOR_PEERS 等敏感設定
ls -la /etc/mailsub/monitor.env
# 預期：owner 為 root 或負責的 system user，不應 world-readable

# db_sync.sh：monitor 會呼叫此 script，不可被 container user 寫入
ls -la /path/to/project/scripts/db_sync.sh
```

---

#### 2-G) LDAP 連線協定確認

**目的**：確認 LDAP bind 是否走 plaintext `ldap://`，評估 credential 暴露風險。

```bash
docker compose exec web env | grep LDAP_URI
# 若輸出 ldap:// 而非 ldaps://，表示 LDAP bind（含 uid+password）以明文在網路上傳輸。
# 在系內 LAN 環境屬 accepted risk，但需明確記錄。
```

---

### Stage 3 — API Authorization & Contract 驗證

> [!note] 此 stage 的 permission / CSRF / status code 驗證（未登入 403、admin endpoint 拒一般 user、CSRF missing 403 等）應由 `apps/accounts/tests.py` 與 `apps/subscriptions/tests.py` 的 unit test 覆蓋。待 test coverage 補齊後，本 stage 僅需執行以下步驟。

#### 3-A) 跑現有 unit tests

```bash
docker compose exec web python manage.py test apps.subscriptions
docker compose exec web python manage.py test apps.accounts
```

#### 3-B) Login rate limiting 手動驗證

此為 known issue（#1），unit test 難以模擬，待實作後手動確認。

```bash
BASE=http://localhost:8000

# 連續送出錯誤登入，確認超過門檻後回 429
for i in $(seq 1 6); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST -H "Content-Type: application/json" \
    -d '{"username":"wronguser","password":"wrongpass"}' \
    $BASE/api/v1/auth/login/
done
# 實作前：全部回 401，無 429
# 實作後：前 N 次 401，之後 429
```

---

## Workflow 總覽

### 執行順序

```
Stage 1（Local）                    Stage 2（Remote：每台機器）
─────────────────────────────       ──────────────────────────────
1-A  Secrets scan（gitleaks）       2-A  Trivy image scan
1-B  Dependency CVE（pip-audit /    2-B  Port 暴露（ss -tlnp）
     npm audit）                    2-C  Redis 認證
1-C  Bandit SAST                    2-D  Env var（DEBUG / SECRET_KEY）
1-D  Django --deploy check          2-E  Docker socket mount
1-E  HTTP headers（local stack）    2-F  Monitor file permissions
                                    2-G  LDAP protocol

Stage 3（Local dev stack）
───────────────────────────
3-A  Unit tests
3-B  Login rate limiting（known issue #1，實作後驗證）
```

### 快速重跑腳本（Stage 1，可加入 CI）

```bash
#!/usr/bin/env bash
# vc-local.sh — Stage 1 local scan
set -euo pipefail

echo "=== [1-A] Secrets: git ls-files ==="
TRACKED=$(git ls-files .env .env.* 2>/dev/null | grep -v '.env.example' | grep -v '.env.example.role' || true)
if [ -n "$TRACKED" ]; then
  echo "FAIL: .env files tracked in git: $TRACKED"
else
  echo "PASS: no .env files tracked"
fi

echo ""
echo "=== [1-A] Secrets: gitleaks ==="
docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:latest \
  detect --source=/repo --no-banner --redact || echo "WARN: gitleaks found findings (review above)"

echo ""
echo "=== [1-B] Frontend npm audit ==="
(cd frontend && npm audit --package-lock-only --omit=dev) || true

echo ""
echo "=== [1-B] Backend pip-audit ==="
pip-audit -r requirements.txt || true

echo ""
echo "=== [1-C] Bandit SAST ==="
bandit -r apps/ -ll || true

echo ""
echo "=== [1-D] Django deploy check ==="
docker compose run --rm \
  -e DJANGO_SETTINGS_MODULE=core.settings \
  web python manage.py check --deploy || true

echo ""
echo "=== Done. Review findings above. ==="
```

使用方式：
```bash
chmod +x vc-local.sh
./vc-local.sh 2>&1 | tee vc-$(date +%Y%m%d).log
```

### Remote 逐台執行腳本（Stage 2）

```bash
#!/usr/bin/env bash
# vc-remote.sh — Stage 2 remote checks
# Usage: ./vc-remote.sh <user>@<ip>
set -euo pipefail

TARGET=$1
echo "=== Running remote VC on $TARGET ==="

ssh "$TARGET" bash << 'REMOTE'
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

echo "--- [2-G] LDAP URI protocol ---"
docker compose -f ~/mailsub/docker-compose.yml exec -T web env | grep LDAP_URI
REMOTE

echo "=== Done: $TARGET ==="
```

使用方式：
```bash
chmod +x vc-remote.sh
./vc-remote.sh user@172.16.127.102   # mail1
./vc-remote.sh user@172.16.127.116   # mail2
./vc-remote.sh user@172.16.127.117   # mail3
```

---

## Proposed Automation（GitHub Actions）

### 1) Dependabot

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "npm"
    directory: "/frontend"
    schedule:
      interval: "weekly"
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
```

### 2) CodeQL

```yaml
# .github/workflows/codeql.yml
name: CodeQL
on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: '0 3 * * 1'

jobs:
  analyze:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        language: [python, javascript]
    steps:
      - uses: actions/checkout@v4
      - uses: github/codeql-action/init@v3
        with:
          languages: ${{ matrix.language }}
      - uses: github/codeql-action/autobuild@v3
      - uses: github/codeql-action/analyze@v3
```

### 3) Gitleaks Action（Secret Scanning）

```yaml
# .github/workflows/gitleaks.yml
name: Gitleaks
on: [push, pull_request]

jobs:
  gitleaks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### 4) pip-audit + npm audit on PR

```yaml
# .github/workflows/dep-cve.yml
name: Dependency CVE Check
on: [pull_request]

jobs:
  pip-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install pip-audit && pip-audit -r requirements.txt

  npm-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: cd frontend && npm audit --package-lock-only --omit=dev --audit-level=high
```

---

## Triage & Remediation

### 分級標準

| Severity | 判定條件 |
|----------|----------|
| **Critical** | 可直接 RCE、完整 credential 外洩、可繞過認證 |
| **High** | 未授權資料存取、LDAP injection、Redis 無認證且對外 |
| **Medium** | Missing security headers、rate limiting bypass、設定缺陷 |
| **Low** | 過舊但低 CVSS 的套件、LDAP 走 plaintext（內網 accepted risk） |

### SLA（建議）

| Severity | 修補期限 |
|----------|----------|
| Critical | 24–48h |
| High | 7d |
| Medium | 30d |
| Low | best-effort |

### 修補策略

- **依賴套件 CVE**：優先升版至修補版；無修補版才考慮 workaround 或 ignore（需記錄理由與到期日）。
- **設定缺陷**：以環境變數切換（production env 設安全值），並用 `manage.py check --deploy` 作為 deploy gate。
- **Login rate limiting**（known issue #1）：在 `apps/accounts/views.py` 加上與訂閱更新相同機制的 Redis TTL rate limit（建議：5 次失敗後 15 分鐘冷卻）。

---

## Deliverables

- 本文件（`vc-proposal.md`）：固定 checklist，每次掃描更新 Known Issues 表格。
- `vc-local.sh`：Stage 1 可重複執行的本地掃描腳本。
- `vc-remote.sh`：Stage 2 SSH 遠端檢查腳本。
- 每次掃描產出記錄格式：

```
日期：YYYY-MM-DD
執行者：
工具版本：
  - gitleaks: x.x.x
  - pip-audit: x.x.x
  - trivy: x.x.x
摘要：
  - Secrets：PASS / FAIL（說明）
  - Python CVE：x 筆（severity breakdown）
  - JS CVE：x 筆
  - Django check：x warnings / x errors
  - Image CVE：x HIGH / x CRITICAL
  - Runtime config：PASS / FAIL（說明）
新增 / 修復項目：
```