# Vulnerability Check

---

## Stage 1

### Stage 1-A

#### Step 1

```sh
git log --all --full-history --name-only --pretty=format: -- '.env' '.env.*' \
  | grep -v '^\s*$' \
  | grep -v '.env.example' \
  | grep -v '.env.role.example'
```
- Result: `.env` 未存在在 git history

#### Step 2
```sh
sudo docker run --rm \
  -v "$PWD:/repo" \
  zricethezav/gitleaks:latest \
  detect --source=/repo --no-banner --redact
```
```
6:23AM INF 156 commits scanned.
6:23AM INF scanned ~534060 bytes (534.06 KB) in 161ms
6:23AM INF no leaks found
```

#### Step 3

發現 `core/settings.py` 有 hardcoded 的 `SECRET_KEY`，已修正為從環境變數讀取

- `core/settings.py`：`DB_PASSWORD` 移除預設值（避免落回 `secret`）

```sh
sudo docker compose exec -T web env DJANGO_SETTINGS_MODULE=core.settings python - <<'PY'
from django.conf import settings
print("SECRET_KEY set:", bool(settings.SECRET_KEY))
PY
```

Result
```sh
SECRET_KEY set: True
```

後續動作：
- 需在三台機器的 `.env` 設定相同的 `SECRET_KEY` (`openssl rand -base64 48`)
- 更新 `.env` 後重啟 web/worker 使設定生效（例：`docker compose up -d --force-recreate web worker`）

備註：
- `DB_PASSWORD` 若未設定會變成空字串，DB 連線會失敗（安全失敗，避免默默使用弱預設值）

### Stage 1-B
 
目的：確認 Python/JS 依賴套件沒有已知 CVE。

#### Frontend（npm）

```
cd frontend
npm audit --package-lock-only --omit=dev
npm audit fix
```

`node_modules`: should be added in .gitignore
> [!Note]
> 更改 `package-lock.json` and `package.json` 要 rebuild
> `docker compose up -d --build`

#### Backend

```
No known vulnerabilities found
```

#### Python 靜態分析（Bandit）


```bash
docker compose run --rm web bash -c "pip install bandit && bandit -r apps/ -ll"
```

```
WARNING: Running pip as the 'root' user can result in broken permissions and conflicting behaviour with the system package manager, possibly rendering your system unusable. It is recommended to use a virtual environment instead: https://pip.pypa.io/warnings/venv. Use the --root-user-action option if you know what you are doing and want to suppress this warning.
[main]	INFO	profile include tests: None
[main]	INFO	profile exclude tests: None
[main]	INFO	cli include tests: None
[main]	INFO	cli exclude tests: None
[main]	INFO	running on Python 3.11.15
Run started:2026-05-30 01:29:55.949535+00:00

Test results:
	No issues identified.

Code scanned:
	Total lines of code: 1409
	Total lines skipped (#nosec): 0

Run metrics:
	Total issues (by severity):
		Undefined: 0
		Low: 14
		Medium: 0
		High: 0
	Total issues (by confidence):
		Undefined: 0
		Low: 0
		Medium: 14
		High: 0
Files skipped (0):
```

#### Django 部署安全設定

```
WARNINGS:
?: (security.W004) You have not set a value for the SECURE_HSTS_SECONDS setting. If your entire site is served only over SSL, you may want to consider setting a value and enabling HTTP Strict Transport Security. Be sure to read the documentation first; enabling HSTS carelessly can cause serious, irreversible problems.
?: (security.W008) Your SECURE_SSL_REDIRECT setting is not set to True. Unless your site should be available over both SSL and non-SSL connections, you may want to either set this setting True or configure a load balancer or reverse-proxy server to redirect all connections to HTTPS.
?: (security.W012) SESSION_COOKIE_SECURE is not set to True. Using a secure-only session cookie makes it more difficult for network traffic sniffers to hijack user sessions.
?: (security.W016) You have 'django.middleware.csrf.CsrfViewMiddleware' in your MIDDLEWARE, but you have not set CSRF_COOKIE_SECURE to True. Using a secure-only CSRF cookie makes it more difficult for network traffic sniffers to steal the CSRF token.
?: (security.W018) You should not have DEBUG set to True in deployment.
```

### CI（GitHub Actions）

#### Gitleaks

- 觸發：`push`（**僅 `main`**）、`pull_request`
- 內容：掃描 git history 是否有 secrets（API key / password / private key）
- 檔案：`.github/workflows/gitleaks.yml`

#### Dependency CVE Check

- 觸發：`pull_request`
- 內容：
	- `pip-audit` 掃 `requirements.txt`
	- `npm audit --package-lock-only --omit=dev --audit-level=high` 掃 frontend production dependencies
- 檔案：`.github/workflows/dep-cve.yml`

#### Bandit SAST

- 觸發：`pull_request`
- 內容：`bandit -r apps/ -ll` 掃 Python code（只顯示 medium 以上）
- 檔案：`.github/workflows/bandit.yml`

#### 觸發行為（各情境跑哪些）

三個 workflow 皆加 `concurrency`（同一 ref 新 push 會取消尚未跑完的舊 run，避免堆積）。

| 情境 | Gitleaks | Dep-CVE | Bandit |
|------|----------|---------|--------|
| push 到 feature branch（無 PR） | — | — | — |
| 開 PR / push 到 PR branch | ✅（一次） | ✅ | ✅ |
| merge 進 `main`（= push to main） | ✅ | — | — |

- **重點**：merge 進 main 與「開 PR」**不同**——只有 Gitleaks 會在 main 的 push 重跑；Dep-CVE / Bandit 是在 merge **前**的 PR 跑過，不會在 main 重跑。
- Gitleaks 之前 `push`（全 branch）+ `pull_request` 會在 PR branch 每次 push **跑兩次**；改 `push: branches: [main]` 後消除重複，coverage 不變（feature branch 一開 PR 即被掃，沒有東西能未掃就進 main）。
- 修改 commit：`6bdeacb`。

---

## Stage 2

Run the [scripts](../../scripts/vc-remote.sh) locally

```sh
./scripts/vc-remote.sh mail1@172.16.127.102 2>&1 | tee logs/vc-mail1-$(date +%Y%m%d).log
./scripts/vc-remote.sh mail2@172.16.127.116 2>&1 | tee logs/vc-mail2-$(date +%Y%m%d).log
./scripts/vc-remote.sh mail3@172.16.127.117 2>&1 | tee logs/vc-mail3-$(date +%Y%m%d).log
```

### Results — mail1 (172.16.127.102)，2026-06-02


#### Runtime config checks (2-B ~ 2-I)

| 檢查 | 結果 | 說明 / 處置 |
|------|------|------------|
| 2-B Port exposure | INFO | 5432 / 6379 / 8000 / 55111 / 9123 皆 listen `0.0.0.0`。5432/6379 對 LAN 開放屬 HA 預期（mail2/3 需跨機存取），不判 FAIL；安全靠 2-C/2-F 的認證把關。 |
| 2-C Redis auth | FAIL→Accepted | `redis-cli ping` 回 `PONG`，**無密碼**。不啟用密碼，見下方說明。 |
| 2-D DEBUG | NOTE | `DEBUG=True`。**Accepted risk（已決議保留），仍回報。** |
| 2-D ALLOWED_HOSTS | PASS | 非 `*`。 |
| 2-D SECRET_KEY | PASS | 已設定，且非 `django-insecure-` 預設。 |
| 2-D DB_PASSWORD | **FAIL** | container env 實測為 `DB_PASSWORD=password`（見下方「DB_PASSWORD 處置」）。 |
| 2-E docker.sock mount | PASS | 無 container 掛載 docker.sock。 |
| 2-F Postgres auth | PASS | 拒絕無密碼 TCP 登入（但密碼若為 default 仍不安全，見 DB_PASSWORD 處置）。 |
| 2-G Container user | **FAIL** | web / worker 皆以 `root` 執行。 |
| 2-H Monitor file perms | 部分 | `.env.role` `-rw-------`(OK)、`/etc/mailsub/monitor.env` `-rw-r-----`(OK)、`scripts/db_sync.sh` `-rwxrwxr-x`（group-writable，建議收成 `755`）。 |
| 2-I LDAP protocol | PASS | `LDAP_URI=ldaps://...:636`（加密）。Known Issue #5（plaintext）在 mail1 不適用。 |

#### DB_PASSWORD 處置

- 各機 `.env` 的 `DB_PASSWORD` 實際值就是弱密碼 `password`（非 stale container）。
- **三台必須同一個密碼**：`db_sync.sh` 用同一組 `DB_USER`/`DB_PASSWORD` 連 primary 與所有 replica（`pg_dump`→`pg_restore`），且 failover 後 standby 要接受同樣 creds；所以三台 Postgres 的 `MailAdmin` 密碼與三台 `.env` 的 `DB_PASSWORD` 必須一致。
- **rotation 注意**：
  - `POSTGRES_PASSWORD` env **只在 data dir 初次初始化時生效**；`postgres_data` 已存在，光改 `.env` 不會改到 DB 真正的密碼——必須在每台 running Postgres 內 `ALTER USER`。
  - `db_sync.sh` 是 `--no-owner --no-privileges` 的邏輯同步，**只搬資料、不搬 role 密碼**，所以無法靠 sync 傳遞；三台都要各自 `ALTER USER`
- **機器上需做（mail1 / mail2 / mail3 都要做，同一個 `$NEW_PW`）**：
  ```sh
  openssl rand -base64 36
  docker compose exec -T postgres psql -U MailAdmin -d Subscriptions \
    -c "ALTER USER \"MailAdmin\" WITH PASSWORD 'password';"
  docker compose up -d --force-recreate web worker
  # check
  docker compose exec -T web env | grep -c '^DB_PASSWORD=password$'   # 應為 0
  ```

#### Image CVE (2-A, Trivy `--severity HIGH,CRITICAL --ignore-unfixed`)

掃描對象由 `docker compose config --images` 推導，全部 **FAIL**（皆有 fixable HIGH/CRITICAL）：

| Image | Base | HIGH | CRITICAL | 備註 |
|-------|------|------|----------|------|
| `…-web` | debian 13.5 | 6 | 0 | OS 套件層 |
| `…-worker` | debian 12.14 | 9 | 2 | 含 `libgnutls30` CVE-2026-33845；**base 比 web 舊一個 release** |
| `…-frontend` | — | 11 | 0 | node 層 |
| `postgres:15-alpine` | alpine 3.23.3 | 12 | 2 | 上游 base image |
| `redis:7-alpine` | alpine 3.21.6 | 45 | 4 | 多數在內附 `gosu` go binary |

**修復方式（在每台機器上）**：
```sh
cd ~/2026-NASA3-Mail-Subscription
# 自建 image（web/worker/frontend）：拉最新 patched base 並重跑 apt/npm，不吃 cache
docker compose build --pull --no-cache
# 上游 base image（postgres/redis）：拉最新 patch 版
docker compose pull postgres redis
# 套用
docker compose up -d
# test again
./scripts/vc-remote.sh mail1@172.16.127.102 2>&1 | tee logs/vc-mail1-$(date +%Y%m%d).log
```
- 因為掃描已帶 `--ignore-unfixed`，列出的都是**上游已有修補版**的項目，rebuild/pull 後多數應消失。
- web 是 debian 13、worker 是 debian 12 → 兩者由不同時間 build。`--pull --no-cache` 會讓兩者對齊到同一 base，順帶清掉 worker 多出的 CVE。
- 殘留項目逐筆判斷：無法升版者記錄理由與到期日（依 proposal 的 Triage 分級）。

**After the rebuild（0602）**

- redis:7-alpine: was 45 HIGH / 4 CRIT → now 0, clean PASS ✅
- web: was debian 13.5 → now 12.14, aligned with worker (the base-mismatch anomaly is gone) ✅
- alpine bases bumped to 3.23.4

#### 重掃 — mail1，2026-06-03

| Image | 仍 FAIL 的內容 | 狀態 |
|-------|---------------|------|
| `…-web` / `…-worker` | debian OS CVE **已清空**（`libgnutls30` / `libkrb5*` 消失）；python `jaraco.context` / `wheel` 也已清 | **0603 rebuild 後 0，CLEAN** ✅ |
| `…-frontend` | 11 HIGH：`cross-spawn` / `glob` / `minimatch` / `tar`，實為 **base image `node:20-alpine` 內 npm 自帶的 bundled deps**（`/usr/local/lib/node_modules/npm/...`），**非專案依賴** | build-time only、**Accept**；根本解 = 靜態 build 提案 |
| `postgres:15-alpine` | `libxml2`(1 HIGH) + `gosu` 的 Go `stdlib`(14 HIGH / 1 CRIT)，baked 在官方 image 內 | upstream 依賴，**Accept** |
| `redis:7-alpine` | image 乾淨（0）；唯一 FAIL 是 2-C 無密碼 | 已決議 Accept（見上） |

**處置**

- **web/worker — debian OS（libgnutls30 / libkrb5*）**：根因為 `Dockerfile` 只 `apt-get install`、從不 `upgrade`，base 舊套件永遠留著。
  - repo 已修：`Dockerfile` 加 `apt-get upgrade -y`（commit `f9c7b0c`）→ **0603 已驗證消失** ✅
- **web/worker — python（jaraco.context / wheel）**：build-time only，不被執行期 import。
  - repo 已修：`Dockerfile` 改 `pip install --upgrade pip setuptools wheel`（commit `2dab8c4`）→ 待 rebuild 重掃。
  - 若 rebuild 後 Trivy 仍報 `setuptools/_vendor/` 內的 copy → frozen build artifact、無 runtime path，記錄為 Accept。
- **frontend — 11 HIGH（`cross-spawn` / `glob` / `minimatch` / `tar`）→ 來源是 base image 的 npm，非專案依賴**：
  - **關鍵：看 Trivy 的 Target 路徑**。被報的全在 `usr/local/lib/node_modules/npm/node_modules/...`，也就是 `node:20-alpine` **base image 內附的 npm CLI 自帶的 libraries**。專案自己的 `app/node_modules/...` 全部掃 **0**。
  - 這四個是 **npm 內部用的工具套件**（build-time，runtime 不會被呼叫）：
    - `cross-spawn`：跨平台啟動子行程（npm 跑 script 用）。CVE-2024-21538 = ReDoS。
    - `glob`：用萬用字元找檔案（`*.js`）。CVE-2025-64756 = 惡意檔名觸發 command injection。
    - `minimatch`：glob pattern → regex 的比對引擎（glob 的核心）。CVE = 特製 pattern 造成 catastrophic backtracking（DoS）。
    - `tar`：解/打包 `.tar`（npm 解壓 package tarball 用）。CVE = 惡意 archive 透過 path traversal / hardlink 覆寫檔案。
  - **所以 `rm -rf node_modules` / `.dockerignore` / `npm install` 都無效**——它們動的是專案 deps，不是 npm 自帶的那份。0603 多次 rebuild 後版本完全沒變（`tar 6.2.1` / `glob 10.4.2` / `minimatch 9.0.5` / `cross-spawn 7.0.3`）即為此。
  - **Triage**：build-time tooling、runtime（`vite dev` 服務）不會呼叫 npm，遠端打不到 → real-world 風險低。
  - **處置**：
    - **Accept**（記錄為 base-image npm-bundled、build-time-only）；不採 `npm install -g npm@latest` 暫行（純降數字、npm 永遠 re-bundle，無實質效益）。
    - **根本解 = multi-stage 靜態 build**（node build → `nginx:alpine` 服務 `dist/`，最終 image 無 node/npm → 11 個全消）。frontend container 只在 mail1-3，可讓容器內 nginx 維持 listen `55111` 並自行 proxy `/api`，使 mail4 RR 不需改。牽涉 serving model／`/api` proxy 位置，已登錄為 open decision，見 [open-decisions.md](../../docs/open-decisions.md)；決定前維持 Accept。
  - 注意 `npm audit fix` 報 0 ≠ image 乾淨：npm audit 只看專案 deps（且不收錄這些 base-image npm libs），Trivy 掃整個 image filesystem，兩者範圍不同。判斷以「Trivy 的 Target 路徑 + 實際版本」為準。
- **postgres:15-alpine — gosu Go stdlib / libxml2**：image 由官方建，我們不 build 它；只能 `docker compose pull postgres` 等上游 rebuild gosu（常落後）。比照其他 accepted-risk，**記錄為 upstream 依賴風險**。
  ```
  docker compose pull postgres
  docker compose up -d postgres
  ```

#### 再掃一次

```sh
sudo rm -rf frontend/node_modules

# Rebuild the self-built images WITHOUT cache (so apt upgrade / pip upgrade /
#    .dockerignore actually take effect — a plain rebuild or recreate won't).
docker compose build --pull --no-cache web worker frontend

# Swap running containers onto the new images.
#    --renew-anon-volumes refreshes the frontend's /app/node_modules volume so it
#    picks up the clean image build (otherwise the old anon volume lingers).
docker compose up -d --force-recreate --renew-anon-volumes web worker frontend
```

### 2-H `db_sync.sh` group-writable

機器上 `chmod 755 ~/2026-NASA3-Mail-Subscription/scripts/db_sync.sh`。

### 2-G Docker non-root user
  - **repo 已做**：`Dockerfile` 末段建立固定 `appuser`（UID/GID **10001**）、`chown -R appuser /app`、`USER appuser`。web/worker 共用此 image。
  - **為何要固定 UID 10001**：worker 會寫 `LAST_SYNC_FILE`（bind-mount 自 host 的 `/var/lib/mailsub`，預設 root-owned）。若 worker 以非 root 跑卻無法寫該目錄，`monitor.py` 會讀到過舊/缺失的 `last_sync` → **暫停 failback**（`docs/HA.md`）。固定 UID 才能在 host 端確定性地 `chown`。
  - **機器上需做（mail1/2/3，rebuild 前先做）**：
    ```sh
    # 1) 讓 appuser(10001) 能寫 LAST_SYNC_DIR
    sudo chown -R 10001:10001 /var/lib/mailsub      # = LAST_SYNC_DIR

    # 2) rebuild 套用非 root image
    docker compose build --pull web worker
    docker compose up -d --force-recreate web worker
    ```
  - **驗收（一定要測，先在 mail1）**：
    ```sh
    docker compose exec web id        # expect uid=10001(appuser)
    docker compose exec worker id     # expect uid=10001(appuser)
    docker compose exec -T web whoami      # 預期 appuser（非 root）
    docker compose exec -T worker whoami   # 預期 appuser
    
    # worker 能寫 last_sync：等一個 SYNC_INTERVAL 或手動觸發後
    ls -l /var/lib/mailsub/last_sync       # mtime 有更新、owner 10001
    curl -s http://127.0.0.1:9123/health   # monitor 讀得到 last_sync、failback 未因 stale 暫停
    ```
  - **若 mail2/3 有其他 host-mount 寫入點**（log 等）一併 `chown` 給 10001，否則 worker 會 permission denied。確認三台都過驗收再算完成。


#### 其他待辦

- **2-C Redis 無密碼（Known Issue #2）→  Accept（不啟用密碼）**：
  - **決策依據**：5432/6379 僅在 VPN 內可達，外部網路無法觸及；比照 DEBUG、LDAP 內網等既有 accepted-risk 立場處理。
  - **殘留風險（記錄即可，不處理）**：VPN 內任一 host（含被入侵的內網機器）仍可 `redis-cli -h <active> FLUSHDB`（清掉待 flush 的 LDAP 任務）或刪 rate-limit key。
  - **未來若要再收斂**（非本次範圍）：首選防火牆 allowlist（只放行三台 mail IP 連 5432/6379，不動 app/monitor）；Redis 密碼（`--requirepass`）屬 defense-in-depth，且會牽動 `scripts/monitor/monitor.py:799-800`（failover 時重寫無密碼 Redis URL），需與 monitor owner 協調，故暫不做。

