# NTU CSIE Mail Subscription System

這是系上 mail alias subscription 管理系統。使用者以 LDAP account 登入後 subscribe 或 unsubscribe alias；具 `mailAdmin` permission 的 administrator 可管理 alias 與 member。

本頁是文件入口，不取代各專題文件。系統的核心分工是：LDAP 是唯一的 source of truth；PostgreSQL 是 local cache 與 task queue；LDAP sync worker 負責非同步寫入與校正。

## Developers

| 成員 | 負責範圍 |
|---|---|
| Qwertypig | Basic Structure and Utilities |
| chilfox | Synchronization |
| bbwinner (wen) | Database and API |

## Repository Layout

```text
.
├── apps/                     # Django applications
│   ├── accounts/             # LDAP login and permissions
│   └── subscriptions/        # Subscription and alias management
├── core/                     # Django project configuration
│   ├── settings.py           # Application and environment settings
│   └── urls.py               # Root URL routing
├── frontend/                 # React + Vite frontend
│   └── src/                  # Frontend source code
├── scripts/                  # Operations and sync scripts
│   ├── monitor/              # HA monitor, systemd service, and tests
│   └── db_sync.sh            # DB sync entry point
├── load-tests/               # Load test data and scripts
├── docs/                     # Detailed technical documentation
├── manage.py                 # Django management entry point
├── Dockerfile                # Application container image
├── docker-compose.yml        # Local service orchestration
├── pyproject.toml            # Python project and tool configuration
├── .env.example              # Environment variable example
└── .env.role.example         # Role environment variable example
```

## Files on Host Machine (Not in Repository)

部署所需的 host 檔案不提交 Git；設定內容與安裝步驟請見 [03 建置與啟動](./docs/03-setup.md) 與 [05 Migration](./docs/05-migration.md)。

| 路徑 | 用途 | 是否含敏感資料／權限注意 |
|---|---|---|
| `/opt/mailsub/.env` | 靜態 Compose 與 LDAP、database 設定 | 是；限 deploy account 讀寫，勿提交 Git |
| `/opt/mailsub/.env.role` | monitor 產生的 ACTIVE／STANDBY override 設定 | 是；monitor 與 container 需可讀寫，勿提交 Git |
| `/opt/mailsub/ldap-ca.crt` | LDAP TLS CA certificate，對應 container 內的 `LDAP_CA_CERT_FILE` | 通常否；限 web／worker 可讀 |
| `/etc/mailsub/monitor.env` | host-level monitor 設定與部署路徑 | 可能是；限 monitor service 讀取，建議 `0640` |
| `/var/lib/mailsub/` | `LAST_SYNC_FILE` 的 host 目錄，bind-mount 給 worker | 否；需允許 worker UID/GID `10001` 寫入 |
| `/var/lib/mailsub/last_sync` | DB sync 成功 timestamp（`LAST_SYNC_FILE`） | 否；需由 worker 寫入、由 monitor 讀取 |
| `/etc/systemd/system/mailsub-monitor.service` | 已安裝的 monitor systemd unit | 否；限 root 管理，來源為 `scripts/monitor/` |

## 文件索引

| 要完成的任務 | 文件 | 用途 |
|---|---|---|
| 了解系統如何分工與同步 | [01 系統架構](./docs/01-architecture.md) | system boundary、data flow、business rule 與 HA 限制的概觀說明 |
| 準備執行環境或確認 external dependency | [02 依賴與硬體](./docs/02-dependency-hardware.md) | Docker、database、LDAP、network 與選用 HA 的需求 |
| 設定、啟動或驗證服務 | [03 建置與啟動](./docs/03-setup.md) | environment variable、本機 Compose、LDAP 設定、HA 與驗證步驟 |
| 查詢 API 或 database table 行為 | [04 API 與資料庫](./docs/04-api-and-db.md) | API、data model、permission、queue 與實際 response 規格 |
| 執行部署、migration 或維運操作 | [05 Migration](./docs/05-migration.md) | migration、部署差異、sync、backup 與營運限制 |

## Quick Start

需要設定、啟動或驗證服務時，請完整依序執行 [03 建置與啟動](./docs/03-setup.md) 的 **Prerequisites**、**Environment Variables**、**啟動前 validation gate**、**Step-by-Step Local Launch** 與驗證步驟。不要在 validation gate 通過前啟動 Compose，也不要用本頁以外的命令繞過檢查。

系統的責任邊界是：LDAP 是唯一的 source of truth；PostgreSQL 是 local cache 與 task queue；LDAP sync worker 只在 ACTIVE node 執行 LDAP 寫入。
