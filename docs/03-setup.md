# 建置與啟動

本頁是從 repository 完成本機開發環境的 how-to。所有命令從 project root directory 執行。此流程需要一個由 identity service 提供、可連線的 LDAP／LDAPS；repository 沒有 local LDAP fixture，也不會替你建立 LDAP server 或測試資料。LDAP 是唯一真相來源；PostgreSQL 提供本地快取與工作佇列，`ou=Aliases` 的寫入由 LDAP 同步 worker 非同步處理。正式 HA 環境僅由 ACTIVE 節點執行 LDAP 寫入。

## Prerequisites

頁首檢查清單：

- 工具：Docker Engine、Docker Compose v2（`docker compose`）；產生 secret 需 Python 3 或 OpenSSL。
- Repository 檔案：`.env.example`、`.env.role.example`、`docker-compose.yml`、`Dockerfile`。
- 外部檔案：identity service 提供的 LDAP CA certificate；container 內必須可讀。
- 外部服務：可達的 LDAPS endpoint、可查詢 `ou=people`／`ou=group` 的 bind account，以及對應密碼。不要假設 `localhost:389` 是 LDAP。
- Host ports：`5432`（PostgreSQL）、`6379`（Redis）、`8000`（Django web）、`55111`（Vite frontend）。這四個 port 必須可用。
- 本機資源：Docker daemon 可用，且 Docker network 的 `10.5.0.0/16` 不與既有 network 衝突。

可複製的工具檢查：

```bash
docker version
docker compose version
python3 --version
openssl version
for port in 5432 6379 8000 55111; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "port $port is already in use" >&2
    exit 1
  fi
done
```

**Expected result:** Docker Engine 與 Compose v2 可回報版本；Python／OpenSSL 可執行；四個 host port 都沒有輸出錯誤。若 port 已被使用，先停止衝突服務或依團隊設定調整 Compose mapping。

## Environment Variables (.env)

### 複製檔案

以下命令可直接複製：

```bash
cp .env.example .env
cp .env.role.example .env.role
chmod 600 .env .env.role
```

**Expected result:** `.env` 與 `.env.role` 建立完成，權限為目前使用者可讀寫；兩個檔案都未加入 Git。

### 必須手動填寫的設定

請手動編輯 `.env`。不要把下列內容當成可直接使用的設定：

| 變數 | 必須填寫的值 | 說明 |
|---|---|---|
| `SECRET_KEY` | 本機獨有的隨機值 | Django 必填；不可留空或使用 repository 範例值。 |
| `DB_HOST` | `postgres` | 單機 Compose 的 PostgreSQL service name。 |
| `DB_PASSWORD` | 非 `password` 的本機密碼 | Compose 具有不安全的 `password` fallback，必須明確覆蓋。 |
| `LDAP_URI` | 例如 `ldaps://ldap.example.edu:636` | 必須是實際可達的 LDAPS URI；不可使用 `ldap://localhost:389` fallback。 |
| `LDAP_BIND_DN` | 例如 `uid=mailtest,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw` | 由 identity service 提供。 |
| `LDAP_BIND_PASSWORD` | bind account 密碼 | 不可提交或貼入文件。 |
| `LDAP_CA_CERT_FILE` | 例如 `/app/ldap-ca.crt` | **container 內**的絕對路徑；host 檔案要放在 `ldap-ca.crt`。 |
| `REDIS_QUEUE_URL` | `redis://redis:6379/0` | 單機 queue。 |
| `REDIS_CACHE_URL` | `redis://redis:6379/1` | 單機 cache。 |
| `VITE_API_TARGET` | `http://web:8000` | frontend container 到 web 的 proxy target。 |
| `VITE_PORT` | `55111` | 必須與可用 host port 一致。 |

`.env` 的格式示例（僅示範格式，`<...>` 必須由你替換，不可原樣使用）：

```dotenv
SECRET_KEY=<generated-local-secret>
DB_HOST=postgres
DB_NAME=Subscriptions
DB_USER=MailAdmin
DB_PASSWORD=<local-postgres-password>
REDIS_QUEUE_URL=redis://redis:6379/0
REDIS_CACHE_URL=redis://redis:6379/1
LDAP_URI=ldaps://<identity-service-host>:636
LDAP_BIND_DN=uid=<service-user>,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw
LDAP_BIND_PASSWORD=<ldap-bind-password>
LDAP_CA_CERT_FILE=/app/ldap-ca.crt
VITE_API_TARGET=http://web:8000
VITE_PORT=55111
```

`.env.role` 在本機不要沿用範例中的外部 HA 位址；手動改成單機格式。設定 `FLUSH_ENABLED=0` 可避免本機 LDAP 同步 worker 執行排程 LDAP flush；這不是 LDAP 權限或 fencing。

```dotenv
DB_HOST=postgres
REDIS_QUEUE_URL=redis://redis:6379/0
REDIS_CACHE_URL=redis://redis:6379/1
FLUSH_ENABLED=0
```

**Expected result:** `.env` 包含真實但未提交的本機設定；`.env.role` 不再指向外部 HA host；CA host 檔案可對應到 `/app/ldap-ca.crt`。不要宣稱這是 local LDAP：LDAP 仍是外部服務。

產生 `SECRET_KEY` 的可複製命令（不要把值放進 shell history 以外的公開位置）：

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

**Expected result:** 輸出一個新的隨機字串；將它手動貼到 `.env` 的 `SECRET_KEY=` 後方，不要把命令輸出提交到 repository。

### 啟動前 validation gate

在 project root directory 執行以下可複製檢查。它只讀取 `.env` 與 CA 檔案，不會連線 LDAP，也不會寫入 LDAP tree：

```bash
python3 - <<'PY'
from pathlib import Path

values = {}
for line in Path('.env').read_text().splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip()

required = [
    'SECRET_KEY', 'DB_HOST', 'DB_PASSWORD', 'LDAP_URI',
    'LDAP_BIND_DN', 'LDAP_BIND_PASSWORD', 'LDAP_CA_CERT_FILE',
    'REDIS_QUEUE_URL', 'REDIS_CACHE_URL',
]
missing = [key for key in required if not values.get(key)]
blocked = []
if values.get('DB_PASSWORD') == 'password':
    blocked.append('DB_PASSWORD=password')
if values.get('LDAP_URI') == 'ldap://localhost:389':
    blocked.append('LDAP_URI=ldap://localhost:389')
ca = values.get('LDAP_CA_CERT_FILE', '')
if not ca.startswith('/app/'):
    blocked.append('LDAP_CA_CERT_FILE must be an absolute /app/... path')
else:
    ca_host_path = Path(ca.removeprefix('/app/'))
    if not ca_host_path.is_file() or not ca_host_path.stat().st_mode & 0o444:
        blocked.append(f'CA is not a readable host file: {ca_host_path}')
if missing or blocked:
    if missing:
        print('missing or empty:', ', '.join(missing))
    if blocked:
        print('blocked:', '; '.join(blocked))
    raise SystemExit(1)
print('validation passed: required values are non-empty, fallbacks are blocked, and CA is readable')
PY
```

**Expected result:** 顯示 `validation passed`。任何 missing、空值、`DB_PASSWORD=password`、`ldap://localhost:389` 或不可讀 CA 都會以非零狀態停止流程；修正 `.env` 或 CA 檔案後再執行。

確認 Compose 展開結果（不要將輸出貼到公開 issue，因為其中可能包含 secret）：

```bash
docker compose config >/tmp/mailsub-compose.config
grep -E 'password|ldap://localhost:389|LDAP_CA_CERT_FILE|DB_HOST|FLUSH_ENABLED' /tmp/mailsub-compose.config
```

**Expected result:** `docker compose config` 成功；檢查結果顯示單機 `DB_HOST=postgres`、`FLUSH_ENABLED=0`、實際 LDAPS URI 與 `/app/...` CA 路徑，且不顯示不安全 fallback。若輸出含 secret，刪除暫存檔並不要分享。

## Step-by-Step Local Launch

### 啟動 Compose

以下命令可直接複製；validation gate 通過後執行：

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 web worker
```

**Expected result:** `postgres`、`redis`、`web`、`worker`、`frontend` 都有 container；web／worker log 沒有設定載入或 CA 路徑錯誤。第一次 build 需要下載 image 與 npm 套件。

`docker compose ps` 的判準是五個 service 都顯示 `Up`（或 `running`），沒有 `Exited`、`Restarting` 或持續的 unhealthy 狀態。`depends_on` 只控制啟動順序，不代表 PostgreSQL／Redis 已 ready；若 web 暫時連線失敗，等待資料庫與 Redis ready 後重看 log。

### Migration

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py showmigrations
```

**Expected result:** `migrate` 完成且沒有 traceback；`showmigrations` 中已套用 migration 以 `[X]` 標示，包括 Django、Django-Q 與 subscriptions app migration。不要用 `docker compose down -v` 處理 migration 問題，因為那會刪除本機 PostgreSQL／Redis volume。

### Health and browser endpoints

```bash
curl -fsS http://127.0.0.1:8000/api/v1/health/
curl -fsS http://127.0.0.1:55111/
```

**Expected result:** 第一個命令的 body 是 `{"status":"ok"}` 且 HTTP 200；第二個命令取得 Vite HTML 且 HTTP 200。這只證明 web／frontend 可達，不證明 LDAP credentials 或外部拓撲可用。

停止服務但保留資料：

```bash
docker compose down
```

**Expected result:** 五個 container 移除，`postgres_data` 與 `redis_data` named volume 保留；下次 `docker compose up -d` 可繼續使用本機資料。

> **資料破壞警告：** `docker compose down -v` 會刪除 PostgreSQL／Redis volume。只有在確認不需要本機資料後才可執行。

HA monitor、DB sync、role 切換、備份／restore 和故障處理不屬於本機流程；請連至 [05 部署、遷移與營運手冊](./05-migration.md)，不要在本頁重複 HA 操作。

## Testing Commands

以下命令可直接複製：

```bash
docker compose exec web python manage.py check
docker compose exec web python manage.py test
docker compose exec web python manage.py test apps.subscriptions
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
python3 -m unittest scripts/monitor/test_monitor.py
```

**Expected result:** Django `check` 沒有 error；Django 全部測試與 `apps.subscriptions` 測試通過；frontend lint／build 成功；monitor unittest 通過。測試中的 LDAP write 應為 mock；不要為了測試呼叫會 enqueue 或 flush 真實 LDAP 的管理操作。

API health smoke test：

```bash
curl -i http://127.0.0.1:8000/api/v1/health/
```

**Expected result:** status line 是 `HTTP/1.1 200`（或等效 HTTP/2 200），body 是 `{"status":"ok"}`。

## Troubleshooting / FAQ

### `SECRET_KEY must be set` 或 CA assert／worker CA error

重新執行 validation gate，確認 `.env` 而不是 `.env.example` 已填值；並確認 CA host 檔案的路徑能對應到 container 的 `/app/...`。若檔案已存在但 container 不可讀，檢查 bind mount 與檔案權限：

```bash
docker compose exec web sh -c 'test -r "$LDAP_CA_CERT_FILE" && echo CA-readable || { echo CA-not-readable; exit 1; }'
```

**Expected result:** 顯示 `CA-readable`。失敗時修正 `LDAP_CA_CERT_FILE` 或 CA 檔案權限，再重建／重啟 web 與 worker。

### Compose service `Exited` 或 database／Redis 尚未 ready

```bash
docker compose ps
docker compose logs --tail=100 postgres redis web worker
```

**Expected result:** `postgres`、`redis` 最終為 `Up`；log 不再出現 connection refused。port 衝突時先停止 host 上的衝突服務；container 之間使用 `postgres` 與 `redis`，不要改成 `localhost`。

### LDAP TLS 或 bind 失敗

```bash
docker compose logs --tail=200 web worker | grep -i ldap
```

**Expected result:** log 可指出 URI、DNS／路由、CA 或 bind failure 的類型；密碼不應出現在 log。確認 `LDAP_URI`、636 port、bind DN、bind password、CA chain 與 identity service ACL；不要以未驗證的 `ldap://` 取代 LDAPS。

### frontend build／npm 安裝失敗

```bash
docker compose build frontend
docker compose logs --tail=100 frontend
```

**Expected result:** build 成功並安裝 lockfile 所需套件；若 registry 不可達，log 會顯示網路或 registry 錯誤，需請 registry 維護者處理，不能宣稱 repository 提供替代的 local fixture。

### HA 或 production 操作需求

本頁不提供 HA 安裝、monitor election、DB sync、backup／restore 或 production hardening 的步驟。這些是外部拓撲與營運責任，請閱讀 [05 部署、遷移與營運手冊](./05-migration.md)；其中的破壞性 restore 操作必須依其人工核准與備份條件執行。
