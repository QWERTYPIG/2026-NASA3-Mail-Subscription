# Setup

---

## 環境變數

在 `docker-compose.yml` 中設定，以下為預設值。實際可由 `.env` 覆蓋（`docker-compose.yml` 的 `env_file` 會讀取）。

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `DB_NAME` | `Subscriptions` | PostgreSQL 資料庫名稱 |
| `DB_USER` | `MailAdmin` | PostgreSQL 使用者 |
| `DB_PASSWORD` | `password` | PostgreSQL 密碼 |
| `DB_HOST` | `postgres` | PostgreSQL host（HA 可改為主機 IP，如 `172.16.127.102`） |
| `DB_REPLICA_HOSTS` | （無預設） | DB sync 目標（逗號分隔，HA 必填） |
| `LAST_SYNC_DIR` | `/var/lib/mailsub` | `LAST_SYNC_FILE` 所在的 host 目錄（供 bind-mount） |
| `PG_MAJOR` | `15` | PostgreSQL client 版本（pg_dump/pg_restore） |
| `REDIS_QUEUE_URL` | `redis://redis:6379/0` | Django-Q task queue |
| `REDIS_CACHE_URL` | `redis://redis:6379/1` | Rate limit TTL cache |
| `FLUSH_ENABLED` | `1` | LDAP flush 開關（由 monitor 寫入 `.env.role`） |
| `LDAP_URI` | `ldaps://172.16.127.109:636` | LDAP server（TLS）|
| `LDAP_CA_CERT_FILE` | （必填，無預設值）| LDAP CA 憑證路徑（container 內可讀取），未設定則拒絕啟動 |
| `LDAP_BIND_DN` | `uid=mailtest,ou=people,...` | LDAP 服務帳號 DN |
| `LDAP_BIND_PASSWORD` | （必填）| LDAP 服務帳號密碼 |
| `VITE_API_TARGET` | `http://web:8000` | Backend API service URL（HA/外部部署可設為 `http://mailsus.csie.org`） |
| `VITE_PORT` | `55111` | Frontend development server port（Vite） |
| `WEB_PORT` | `8000` | monitor 檢查 Django `/api/v1/health/` 的 port |
| `FRONTEND_PORT` | `VITE_PORT` 或 `55111` | monitor 檢查 frontend HTTP 的 port |
 

> [!warning] Redis index 分開
> index 0（queue）與 index 1（cache）刻意分開，避免 task queue 的 key 被 cache 操作誤刪。

---

## HA：`.env.role` 與 monitor 設定

HA 模式下，web/worker 會同時載入 `.env` 與 `.env.role`：

- `.env`：靜態設定（手動維護）
- `.env.role`：由 monitor 產生的角色覆蓋（DB_HOST/Redis/FLUSH_ENABLED）

monitor 透過 `/etc/mailsub/monitor.env` 讀取設定，常見項目：

- `THIS_MACHINE_IP`, `MONITOR_PEERS`
- `COMPOSE_FILE`, `ENV_BASE`, `ENV_ROLE`
- `SYNC_INTERVAL`, `LAST_SYNC_FILE`

詳細行為與理由請見 [monitor](./monitor.md)。

> [!note]
> `LAST_SYNC_FILE` 由 worker container 寫入，因此需在 `docker-compose.yml` 以 `LAST_SYNC_DIR` 進行 bind-mount，並確保 `LAST_SYNC_DIR` 與 `LAST_SYNC_FILE` 的目錄一致。

### 安裝 monitor daemon（每台 mail1/2/3）

**1. 建立設定目錄並寫入設定檔**

```bash
sudo mkdir -p /etc/mailsub
sudo install -m 0640 scripts/monitor/monitor.env.example /etc/mailsub/monitor.env
```

編輯 `/etc/mailsub/monitor.env`，至少修改：
- `THIS_MACHINE_IP`：本機 IP
- `THIS_MACHINE_NAME`：本機名稱（mail1 / mail2 / mail3）
- `MONITOR_PEERS`：依優先序排列（mail1 IP 排最前）

**2. 安裝 systemd service**

```bash
sudo install -m 0644 scripts/monitor/mailsub-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mailsub-monitor
```

**3. 確認服務狀態**

```bash
sudo systemctl status mailsub-monitor
sudo journalctl -u mailsub-monitor -f
```

健康檢查端點（供確認）：

```bash
curl http://127.0.0.1:9123/health
```

---

## Docker 網路設定

Docker 網段設定為 `10.5.0.0`，避免與系上網段 `172.16.0.0` 衝突。

---

## 常用指令

```bash
# 啟動服務
docker compose up -d

# 初次建置：migrate DB schema（第一次跑或 model 有改動時）
docker compose exec web python manage.py migrate

# 關閉服務
docker compose down

# 關閉並清除資料庫 volume
docker compose down -v
```

---

## 初始化 Django 專案（僅需做一次）

```bash
docker compose run --rm --user "$(id -u):$(id -g)" web django-admin startproject core .
```

產生的結構：
```
manage.py
core/
├── __init__.py
├── asgi.py
├── settings.py
├── urls.py
└── wsgi.py
```

---

## App 結構

```
apps/
└── accounts/
    ├── apps.py         # AppConfig，需加入 settings.py INSTALLED_APPS
    ├── permissions.py  # has_permission：檢查 admin 權限
    ├── views.py        # login / me / logout 行為
    └── urls.py         # endpoint 對應
core/
└── urls.py             # 掛載 api/v1/auth/ prefix
```

API endpoint 細節見 [api](./docs/api.md)。
