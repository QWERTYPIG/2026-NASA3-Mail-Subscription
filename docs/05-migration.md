# 部署與維運

## 準備部署環境

在 project root directory 執行本頁指令。先準備 Docker Compose、Docker daemon、可連線的 LDAP（含 CA 憑證）、PostgreSQL/Redis 所需主機資源，以及不含秘密的部署紀錄。設定欄位詳見[設定說明](./03-setup.md)；LDAP 是唯一真相來源，PostgreSQL 只是快取與待處理佇列。

| 項目 | 部署前必須確認 |
|---|---|
| Compose 邊界 | 現行 Compose 使用 Django `runserver`、Vite dev server 與 bind mount，僅適合開發/驗證；不可直接宣稱為正式環境部署。 |
| 秘密與設定 | `.env`、`.env.role`、`/etc/mailsub/monitor.env` 不得提交 Git；移除 Compose 預設密碼，並確認 `DEBUG`、`ALLOWED_HOSTS`、HTTPS 與 cookie 設定。 |
| LDAP 寫入 | 只能由 ACTIVE 節點的 Django-Q worker 經 task queue 寫入；不得執行 `ldapadd`、`ldapmodify` 或 `ldapdelete`。 |
| `/health` | monitor 綁定 `0.0.0.0:9123`、無驗證/TLS，且 unhealthy 仍回 HTTP 200；先以 host firewall/ACL 限制來源。 |
| HA | monitor 沒有 quorum、共識、distributed lease 或 fencing；網路分割可能造成 split-brain。正式切換前須有基礎設施 fencing。 |
| DB 同步 | `db_sync.sh` 是 dump/restore，不是 PostgreSQL replication；確認 `DB_REPLICA_HOSTS`、維護窗口、備份與回復責任。 |
| worker 狀態檔 | 先建立可由 UID/GID `10001` 寫入的 `LAST_SYNC_DIR`；例如 `sudo install -d -o 10001 -g 10001 /var/lib/mailsub`。 |

### 重要環境變數

此表非完整清單，完整設定請看[設定說明](./03-setup.md)。至少確認 `DB_NAME`、`DB_USER`、`DB_PASSWORD`、`DB_HOST`、`DB_REPLICA_HOSTS`、`LDAP_URI`、`LDAP_BIND_DN`、`LDAP_BIND_PASSWORD`、`LDAP_CA_CERT_FILE`、`REDIS_QUEUE_URL`、`REDIS_CACHE_URL`、`FLUSH_ENABLED`、`LAST_SYNC_DIR`、`LAST_SYNC_FILE` 與 `PG_MAJOR`。秘密不可寫入文件、命令列紀錄或 log。

## 啟動 Compose 服務並驗證

```bash
cd /opt/mailsub
export COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
docker compose -f "$COMPOSE_FILE" config >/tmp/mailsub-compose-config-$(date +%Y%m%d-%H%M%S).yml
docker compose -f "$COMPOSE_FILE" build
docker compose -f "$COMPOSE_FILE" up -d
docker compose -f "$COMPOSE_FILE" ps
```

預期結果：`config` 成功產生檔案，五個服務可見，`web`、`worker`、`frontend`、`postgres`、`redis` 狀態為 running。驗證應用程式與測試：

```bash
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
docker compose -f "$COMPOSE_FILE" exec web python manage.py check
docker compose -f "$COMPOSE_FILE" exec web python manage.py check --deploy || true
docker compose -f "$COMPOSE_FILE" exec web python manage.py showmigrations
docker compose -f "$COMPOSE_FILE" exec web python manage.py test
docker compose -f "$COMPOSE_FILE" exec web python -m unittest scripts/monitor/test_monitor.py
```

預期 `check` 無錯誤；`check --deploy` 的開發設定項目須先在阻擋項中處理。無法在未準備 LDAP、PostgreSQL、Redis 的主機直接宣稱測試通過。

## 執行資料庫遷移

首次啟動或版本更新後執行：

```bash
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
docker compose -f "$COMPOSE_FILE" exec web python manage.py migrate
MIGRATION_FILE="/tmp/mailsub-migrations-$(date +%Y%m%d-%H%M%S).txt"
docker compose -f "$COMPOSE_FILE" exec web python manage.py showmigrations | tee "$MIGRATION_FILE"
```

預期建立 Django、Django-Q 與 subscriptions schema；`0002` 建立每 30 分鐘執行 `flush_ldap_tasks` 的 schedule，且 `showmigrations` 顯示已套用。migration 不會建立正式 alias fixture，也不會回復 LDAP；初始資料須經既有應用程式流程建立。

`db_sync.sh` 由 ACTIVE monitor 依 `SYNC_INTERVAL` 觸發：先 `pg_dump`，再對 `DB_REPLICA_HOSTS` 執行 `pg_restore --clean --if-exists`，成功後寫入 `LAST_SYNC_FILE`。它不是 native replication；可用下列命令確認工具與狀態：

```bash
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
docker compose -f "$COMPOSE_FILE" exec -T worker sh -lc 'test -x scripts/db_sync.sh && command -v pg_dump && command -v pg_restore && command -v psql'
docker compose -f "$COMPOSE_FILE" exec worker sh -lc 'printf "LAST_SYNC_FILE=%s\\n" "${LAST_SYNC_FILE:-unset}"; test -f "${LAST_SYNC_FILE:-/dev/null}" && cat "$LAST_SYNC_FILE" || true'
```

預期列出三個 PostgreSQL 工具；狀態檔存在時內容是 Unix timestamp。

## 安裝 HA monitor

每台節點安裝 host-level monitor；先編輯 `/etc/mailsub/monitor.env` 的本機 IP、peer 與路徑。project root directory 內的 unit 仍保留原樣；因 repository 位於 `/opt/mailsub`，以下先產生修正後的 unit，再安裝該份檔案：

```bash
cd /opt/mailsub
sudo install -d -m 0750 /etc/mailsub
sudo install -m 0640 scripts/monitor/monitor.env.example /etc/mailsub/monitor.env
sudo tee /tmp/mailsub-monitor.service >/dev/null <<'UNIT'
[Unit]
Description=MailSub HA Monitor
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
WorkingDirectory=/opt/mailsub
ExecStart=/usr/bin/python3 /opt/mailsub/scripts/monitor/monitor.py
EnvironmentFile=/etc/mailsub/monitor.env
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=mailsub-monitor

[Install]
WantedBy=multi-user.target
UNIT
sudo install -m 0644 /tmp/mailsub-monitor.service /etc/systemd/system/mailsub-monitor.service
sudo systemctl daemon-reload
sudo systemctl enable --now mailsub-monitor
curl -fsS http://127.0.0.1:9123/health
sudo systemctl status --no-pager mailsub-monitor
```

預期 health 回傳 JSON；`systemctl status` 顯示 `Active: active (running)`，並顯示 `/usr/bin/python3` 執行 `/opt/mailsub/scripts/monitor/monitor.py`。預設每 15 秒檢查，失效 3 次切換、恢復 2 次 failback、無 peer 8 次進入 degraded mode；ACTIVE 才設定 `FLUSH_ENABLED=1`。以 `journalctl -u mailsub-monitor` 驗證 `active_transition`、`db_sync_failed` 與 `failback_blocked_stale_sync`。

## 查看日誌與健康狀態

Compose 將 container log 送到 host `/dev/log` 的 syslog driver；monitor service 將 stdout/stderr 送到 systemd journal。repository 不會自動建立 rsyslog、log rotation、容量保護、dashboard 或告警：

```bash
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
docker compose -f "$COMPOSE_FILE" logs --tail=200 web worker postgres redis frontend
sudo journalctl -u mailsub-monitor --since "$(date -d '15 minutes ago' '+%Y-%m-%d %H:%M:%S')"
curl -fsS http://127.0.0.1:9123/health
```

預期可看到服務 log、JSON monitor event 與 health payload；正式環境仍須由主機維運配置收集、保留與告警規則。

## 備份資料庫

主機只決定備份目錄與檔名；資料庫名稱和使用者直接從 `postgres` container 的 `POSTGRES_DB`、`POSTGRES_USER` 讀取。

```bash
BACKUP_DIR="${BACKUP_DIR:-/secure/backup}"
BACKUP_FILE="$BACKUP_DIR/mailsub-$(date +%Y%m%d-%H%M%S).dump"
mkdir -p "$BACKUP_DIR"
docker compose -f docker-compose.yml exec -T postgres sh -ec '
  : "${POSTGRES_USER:?POSTGRES_USER is not set in postgres container}"
  : "${POSTGRES_DB:?POSTGRES_DB is not set in postgres container}"
  pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"
' > "$BACKUP_FILE"
ls -lh "$BACKUP_FILE"
```

預期產生非零的 custom-format dump。`POSTGRES_DB` 與 `POSTGRES_USER` 不由主機的 `DB_*` 變數推測。

## 還原資料庫

`pg_restore --clean --if-exists` 會移除目標資料庫既有物件，可能造成不可逆資料遺失。只在確認備份、目標與維護窗口，並取得人工核准後執行。還原不會回復 LDAP；完成後須讓應用程式依 LDAP 這個唯一真相來源校正 PostgreSQL。

主機只初始化 `BACKUP_DIR`、`BACKUP_FILE`；還原前的 target values 由 container 顯示，必須人工輸入 `RESTORE` 確認：

```bash
BACKUP_DIR="${BACKUP_DIR:-/secure/backup}"
BACKUP_FILE="${BACKUP_FILE:-$BACKUP_DIR/mailsub-latest.dump}"
test -s "$BACKUP_FILE"

echo 'Target database values from postgres container:'
docker compose -f docker-compose.yml exec -T postgres sh -ec '
  : "${POSTGRES_USER:?POSTGRES_USER is not set in postgres container}"
  : "${POSTGRES_DB:?POSTGRES_DB is not set in postgres container}"
  printf "POSTGRES_USER=%s\\nPOSTGRES_DB=%s\\n" "$POSTGRES_USER" "$POSTGRES_DB"
'
printf 'Type RESTORE to continue: '
read -r CONFIRMATION
[ "$CONFIRMATION" = RESTORE ]

docker compose -f docker-compose.yml stop web worker
docker compose -f docker-compose.yml exec -T postgres sh -ec '
  : "${POSTGRES_USER:?POSTGRES_USER is not set in postgres container}"
  : "${POSTGRES_DB:?POSTGRES_DB is not set in postgres container}"
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    --clean --if-exists --no-owner --no-privileges
' < "$BACKUP_FILE"
docker compose -f docker-compose.yml up -d web worker
docker compose -f docker-compose.yml exec web python manage.py migrate
docker compose -f docker-compose.yml exec web python manage.py check
curl --fail --retry 30 --retry-delay 2 --retry-connrefused \
  http://127.0.0.1:8000/api/v1/health/
```

預期 `pg_restore`、migration、`check` 與 API health 均成功；最後回傳 `{"status":"ok"}`。

## 回滾版本

現況沒有 image registry、release promotion 或自動 rollback。部署前保存 Git commit、Compose 設定 checksum、image ID、migration 狀態與 backup 檔名；失敗時：

1. 記錄 `docker compose ps`、logs、monitor 狀態與 LDAP queue。
2. 將 build context 固定到已驗證的前一個 commit，或使用事先保存的 image，再執行 `docker compose build` 與 `up -d`。
3. 若新 migration 不可逆，不可只降版 image；依 migration 專屬方案處理，或在隔離資料庫驗證 backup。
4. 以 `docker compose ps`、`/api/v1/health/`、`/health`、logs 與 queue 驗證；未完成驗證前保持 `FLUSH_ENABLED=0`。

## 已知限制

- CI 只有 Bandit、dependency audit 與 Gitleaks；沒有 Django/frontend/monitor 測試、build/scan、部署 gate 或 rollback automation。
- backup/restore 沒有排程、遠端或離線副本、加密、retention、RPO/RTO、完整性檢查或定期 restore drill。
- migration 沒有正式 alias fixture 或 production reconciliation runbook；LDAP 永遠是唯一真相來源。
