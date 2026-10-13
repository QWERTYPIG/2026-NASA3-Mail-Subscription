# 依賴與硬體

本頁是可查閱的依賴 reference。版本、服務名稱、port、volume 與 mount 以 `docker-compose.yml`、`Dockerfile`、`pyproject.toml`、`requirements.txt` 和 `frontend/package.json` 為準；本頁不描述部署操作。啟動與驗證請見 [03 建置與啟動](./03-setup.md)，migration、同步、備份與 HA 維運請見 [05 部署、遷移與營運手冊](./05-migration.md)。

系統責任邊界是：LDAP 是唯一真相來源；PostgreSQL 提供本地快取與工作佇列；LDAP 同步 worker 由 ACTIVE 節點執行 LDAP 寫入。

## External Dependencies

### Software and services

| 類別 | 依賴 | Repository 可驗證的用途／限制 |
|---|---|---|
| Container runtime | Docker Engine、Docker Compose v2（`docker compose`） | 建立下列五個 Compose service 與 `mail_net` bridge network。 |
| Backend image | Python 3.11 slim Bookworm、Django、Django REST Framework、Django-Q2 | `Dockerfile` 建置 backend；web 執行 Django `runserver`，LDAP 同步 worker 執行 `python manage.py qcluster`。 |
| Frontend image | Node.js 20 Alpine、npm、React、Vite | `frontend` 執行 Vite development server；版本以 `frontend/package-lock.json` 為準。 |
| Database | PostgreSQL 15 Alpine | Django schema、session、PostgreSQL 本地快取與工作佇列。LDAP 是唯一真相來源。 |
| Queue／cache | Redis 7 Alpine | Redis DB 0 給 Django-Q queue，DB 1 給 rate-limit cache。 |
| Identity service | 可達的 LDAP／LDAPS server、bind account、CA certificate | `ou=people` 用於登入，`ou=group` 用於 `mailAdmin` 權限查詢；TLS CA 驗證是必要條件。LDAP 不由 Compose 建立。 |
| Package registry | npm registry（`frontend/.npmrc` 指定的 registry） | frontend 依賴安裝需要 registry 可達；registry 的可用性不是 repository 可驗證的本機服務。 |

Python 直接依賴包括 `django`、`django-auth-ldap`、`django-cors-headers`、`django-q2`、`djangorestframework`、`ldap3`、`psycopg2-binary`、`python-dotenv` 與 `redis`。Dockerfile 另安裝 LDAP／PostgreSQL 編譯工具與 PostgreSQL 15 client。Frontend 直接依賴與版本詳見 `frontend/package.json` 及 lockfile。

### Ports

| Service／用途 | Container port | Host mapping | 備註 |
|---|---:|---:|---|
| PostgreSQL | 5432 | `5432:5432` | Compose 直接暴露到 host；連線名稱為 `postgres`。 |
| Redis | 6379 | `6379:6379` | Compose 直接暴露到 host；連線名稱為 `redis`。 |
| Django web | 8000 | `8000:8000` | Development server；API health path 為 `/api/v1/health/`。 |
| Vite frontend | `${VITE_PORT}`，預設 55111 | `${VITE_PORT}:${VITE_PORT}` | Development server，預設 URL 是 `http://localhost:55111/`。 |
| LDAP／LDAPS | 外部服務提供 | 不在 Compose mapping | 通常為 LDAPS 636；實際 URI、DNS、port 與可達性由 identity service 提供。 |
| HA monitor（選用） | 9123 | host service | 不屬於本機 Compose 流程；拓撲與操作請見 [05](./05-migration.md)。 |

Compose 使用固定的 `mail_net` bridge subnet `10.5.0.0/16`、gateway `10.5.0.1`。這個 subnet 是否與主機或其他 Docker network 衝突，必須在目標環境另行檢查。

### Volumes and mounts

| Service | Mount | 用途 |
|---|---|---|
| `postgres` | named volume `postgres_data:/var/lib/postgresql/data` | PostgreSQL 資料。 |
| `redis` | named volume `redis_data:/data` | Redis queue／cache 資料。 |
| `web`、`worker` | `.:/app` | 開發時以 repository working tree 覆蓋 image 內程式。 |
| `frontend` | `frontend:/app`、anonymous `/app/node_modules` | 開發時掛載 frontend source，保留 container dependencies。 |
| `worker` | `${LAST_SYNC_DIR}:${LAST_SYNC_DIR}` | 同步時間戳目錄；實際 host 路徑由設定決定。 |

刪除 `postgres_data` 或 `redis_data` 會刪除本機狀態；這是資料破壞操作，執行前必須確認備份與目標 volume。Compose 對 service 設定 `restart: always`，並嘗試將 log 寫入 host `/dev/log`；host 是否有可用的 syslog socket 不由 repository 保證。

## Hardware Infrastructure

### Host-external files

以下檔案不是 repository 產物，且內容或權限無法由 repository 驗證：

- `LDAP_CA_CERT_FILE` 指向的 CA 憑證。它必須存在於 `web`、`worker` container 可讀取的路徑，例如 host 的 `mockldap_ca.crt` 對應 container 的 `/app/mockldap_ca.crt`；檔案內容與信任鏈由 identity service 提供。
- `.env`、`.env.role` 中的 secret、LDAP bind account、database credentials 與環境位址。
- `LAST_SYNC_DIR` 與 `LAST_SYNC_FILE` 對應的 host 目錄／檔案；worker image 以 UID/GID `10001` 執行，host 權限必須由部署者提供。
- HA 選用的 `/etc/mailsub/monitor.env`、systemd unit 與 `/var/lib/mailsub`。其建立方式、權限與切換操作請見 [05](./05-migration.md)。

### Unverified hardware and topology assumptions

本 repository 能驗證的是 Compose 服務，不是實體硬體或外部拓撲。以下項目屬於部署假設，不能從本 repository 得出可用性或維護狀態：

- mail1／mail2／mail3 主機、mail4–mail7、Nginx、Postfix／Mailpit 與其實際 IP、DNS、routing 和 firewall。
- 外部 LDAP／LDAPS server、identity service 的 `ou=people`、`ou=group`、`ou=Aliases` 資料與權限。
- CPU、RAM、磁碟容量、磁碟 RAID、備份媒介、UPS、實體網路設備與硬體維護 SOP。
- peer-to-peer HA 網路、fencing、共識／仲裁、監控、告警、備份保留和 disaster recovery 能力。

這些外部條件須由基礎設施與 identity service 維護者確認；repository 沒有 local LDAP fixture，也沒有提供硬體或網路可用性保證。
