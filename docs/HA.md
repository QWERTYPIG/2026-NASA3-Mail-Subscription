# Mail Subscription System — High Availability

## Machines
| Name | IP | Usage |
|------|----|-------|
| mail1 | 172.16.127.102 | default main DB/Redis; frontend + backend |
| mail2 | 172.16.127.116 | standby DB/Redis; frontend + backend |
| mail3 | 172.16.127.117 | standby DB/Redis; frontend + backend |
| mail4 | 172.16.127.118 | Nginx reverse-proxy |

---

## 架構總覽

- mail1/2/3 各自跑完整容器（postgres/redis/web/worker）。
- 只有 **一台 ACTIVE**：同時是 DB/Redis primary，且允許 worker flush LDAP。
- 其他機器為 STANDBY：只跟隨 DB sync，不對 LDAP 寫入。
- mail4 僅做 Nginx reverse-proxy（round-robin）。

ACTIVE 的選舉、切換、與檢查細節由 monitor daemon 負責，詳見
[monitor](./monitor.md)。

---

## 角色切換與設定來源

monitor 會在每台機器寫入 `.env.role`：

- `DB_HOST=<ACTIVE_IP>`
- `REDIS_QUEUE_URL=redis://<ACTIVE_IP>:6379/0`
- `REDIS_CACHE_URL=redis://<ACTIVE_IP>:6379/1`
- `FLUSH_ENABLED=1`（ACTIVE）或 `0`（STANDBY）

並透過 `docker compose up -d --force-recreate web worker` 讓 web/worker
立即讀取新設定。

---

## DB/Redis 與 failover

- ACTIVE 必須同時通過 DB、Redis、worker、DB sync 健康檢查。
- 若本機 PostgreSQL 仍為 read-only replica，monitor 不會允許切為 ACTIVE。
- 若無 peer 可達，monitor 會在降級門檻後允許自啟動，避免全站停擺。

---

## DB Sync

DB sync 只由 ACTIVE 觸發：

- Script: [scripts/db_sync.sh](../scripts/db_sync.sh)
- Primary: `DB_HOST`（由 `.env.role` 決定）
- Targets: `DB_REPLICA_HOSTS`
- Trigger: monitor 依 `SYNC_INTERVAL` 排程
- Failback freshness：`LAST_SYNC_FILE` 必須在 2×`SYNC_INTERVAL` 內

設計理由：避免故障切換時使用過舊資料的 primary。
