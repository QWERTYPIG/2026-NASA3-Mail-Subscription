# Monitor Daemon — `scripts/monitor/monitor.py`

本文件說明 monitor daemon 的設計目的、行為與配置方式。它是 HA 方案的核心元件，負責在多機環境中選出唯一的 ACTIVE，並確保 DB/Redis/worker 切換一致。

---

## 設計目標與理由

1. **單一 ACTIVE，避免 split-brain**
   - 只有一台機器能同時作為 DB/Redis primary 與 LDAP flush 的執行者。
   - 透過 deterministic 選舉規則，所有 monitor 能獨立得出同一結論。

2. **Host-level daemon（非容器內）**
   - 容器故障時仍需能重啟 web/worker、切換 env、觸發同步。
   - systemd 管理比 container lifecycle 更穩定。

3. **無外部共識系統**
   - 不引入 etcd/consul，降低維運複雜度。
   - 使用「優先序 + 健康檢查 + 門檻」達到穩定切換。

4. **LDAP 寫入的嚴格收斂**
   - LDAP 是唯一 source of truth。
   - 只有 ACTIVE 的 worker 可以 flush，其他機器必須明確停用。

---

## 運作方式（高層）

- 每台 mail1/mail2/mail3 都執行 monitor（systemd）。
- 設定由 `/etc/mailsub/monitor.env` 載入。
- 每 `CHECK_INTERVAL` 秒進行一次健康檢查與選舉。
- `/health` 提供簡單 JSON 供同儕機器檢查。
- 若 ACTIVE 改變，寫入 `.env.role` 並重啟 web/worker 容器。

---

## 健康檢查（Core Services）

ACTIVE 必須同時滿足以下條件：

1. **PostgreSQL 可連線**：TCP 5432 可達
2. **Redis 可連線**：TCP 6379 可達
3. **Worker 可用**：`/health` 回報 `worker_running=true`
4. **DB Sync 可用**：`/health` 回報 `db_sync_ready=true`

理由：
- DB/Redis 必須可用，否則切到該機器只會擴大故障。
- worker 必須能 flush LDAP 才能被視為 ACTIVE。
- DB sync 可用才能保障 failback 時資料新鮮度。

---

## /health 端點

`GET /health` 回傳：

```json
{
  "worker_running": true,
  "db_sync_ready": true
}
```

檢查方式：
- `docker compose ps` 檢查 worker 是否 running
- `docker compose exec -T worker ...` 檢查 `scripts/db_sync.sh` 與 `pg_dump/pg_restore/psql`

設計理由：避免 SSH、降低攻擊面，只用 LAN 上的 HTTP + TCP。

---

## Leader Election 與穩定性

- **規則**：ACTIVE = 優先序最高且 core 健康的機器  
  （預設 mail1 > mail2 > mail3，以 `MONITOR_PEERS` 順序為準）

- **Failover 門檻**：`FAIL_THRESHOLD` 次連續失敗才切換  
  → 避免短暫抖動造成角色抖動

- **Failback 門檻**：`RECOVER_THRESHOLD` 次連續成功才切回  
  → 避免剛恢復就立刻切回

- **Peer Fence**：通常需至少一台 peer monitor 可達才允許自我啟動  
  → 防止網路分割造成雙 ACTIVE

- **Degraded Mode**：若長時間無 peer 可達，超過 `DEGRADED_THRESHOLD` 才允許自我啟動  
  → 在全網隔離時仍能維持服務

---

## 角色切換與容器重載

當 ACTIVE 變更：

1. 產生 `.env.role`（原子寫入）：
   - `DB_HOST=<ACTIVE_IP>`
   - `REDIS_QUEUE_URL=redis://<ACTIVE_IP>:6379/0`
   - `REDIS_CACHE_URL=redis://<ACTIVE_IP>:6379/1`
   - `FLUSH_ENABLED=1`（ACTIVE）或 `0`（STANDBY）

2. 重新啟動 web/worker：

```
docker compose up -d --force-recreate web worker
```

理由：讓 Django/worker 立刻讀取最新 DB/Redis 及 FLUSH_ENABLED。

---

## PostgreSQL 可寫性檢查（ACTIVE 必須可寫）

當本機要成為 ACTIVE 時，monitor 會在 `postgres` container 內執行：

```
SELECT pg_is_in_recovery();
```

若回傳 `true`（read-only replica），則**拒絕切換為 ACTIVE**。

理由：避免把 read-only 副本當成 primary，導致寫入失敗或資料倒退。

---

## DB Sync 排程與 failback 新鮮度

只有 ACTIVE 才會排程 `scripts/db_sync.sh`：

```
docker compose exec -T worker scripts/db_sync.sh
```

機制：
1. `LAST_SYNC_FILE` 記錄最後同步時間
2. `SYNC_INTERVAL` 控制同步頻率
3. **Failback 新鮮度**：`last_sync` 必須在 `2 * SYNC_INTERVAL` 內  
   （預設 600s → 20 分鐘）

理由：failback 時若資料過舊，切回高優先序機器會造成回溯。

---

## 設定（/etc/mailsub/monitor.env）

必要：

| 變數 | 說明 |
|---|---|
| `THIS_MACHINE_IP` | 本機 IP（需在 `MONITOR_PEERS` 內） |
| `MONITOR_PEERS` | 依優先序排列的 IP 列表（預設 mail1,2,3） |
| `COMPOSE_FILE` | `docker-compose.yml` 路徑 |
| `ENV_BASE` | `.env` 路徑（monitor 不改寫，供運維對齊） |
| `ENV_ROLE` | `.env.role` 路徑（monitor 會寫入） |

常用可調：

| 變數 | 預設 | 目的 |
|---|---|---|
| `MONITOR_PORT` | `9123` | /health 監聽 port |
| `CHECK_INTERVAL` | `15` | 健康檢查週期（秒） |
| `FAIL_THRESHOLD` | `3` | failover 門檻 |
| `RECOVER_THRESHOLD` | `2` | failback 門檻 |
| `DEGRADED_THRESHOLD` | `8` | 無 peer 時允許自啟動門檻 |
| `SYNC_INTERVAL` | `600` | DB sync 週期（秒） |
| `LAST_SYNC_FILE` | unset | 同步時間記錄檔 |
| `PG_PORT` | `5432` | PostgreSQL port |
| `REDIS_PORT` | `6379` | Redis port |
| `TCP_TIMEOUT` | `2.0` | TCP 健康檢查 timeout |
| `HEALTH_TIMEOUT` | `2.0` | /health 讀取 timeout |
| `DB_NAME` | `Subscriptions` | 本機 PostgreSQL DB 名稱 |
| `DB_USER` | `MailAdmin` | 本機 PostgreSQL user |

---

## 注意事項

- monitor **不直接寫 LDAP**，只控制 `FLUSH_ENABLED`。
- `/health` 僅限內網使用，不應公開對外。
- `.env.role` 必須由 web/worker 的 `env_file` 載入。
- 若 `LAST_SYNC_FILE` 未設定，monitor 會跳過 DB sync 排程並記錄警告。
