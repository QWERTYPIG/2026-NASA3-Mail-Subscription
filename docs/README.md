# NTU CSIE Mail Subscription System

這是系上 mail alias 訂閱管理系統。使用者以 LDAP 帳號登入後訂閱或退訂 alias；具 `mailAdmin` 權限的管理員可管理 alias 與成員。

本頁是文件入口，不取代各專題文件。系統的核心分工是：LDAP 是唯一真相來源；PostgreSQL 是本地快取與工作佇列；LDAP 同步 worker 負責非同步寫入與校正。

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
│   ├── accounts/             # LDAP 登入與權限
│   └── subscriptions/        # 訂閱與 alias 管理
├── core/                     # Django 專案設定
│   ├── settings.py           # 應用程式與環境設定
│   └── urls.py               # 根 URL 路由
├── frontend/                 # React + Vite 前端
│   └── src/                  # 前端原始碼
├── scripts/                  # 維運與同步 scripts
│   ├── monitor/              # HA monitor、service 與測試
│   └── db_sync.sh            # DB sync 執行入口
├── load-tests/               # 負載測試資料與腳本
├── docs/                     # 詳細技術文件
├── manage.py                 # Django 管理入口
├── Dockerfile                # 應用程式容器映像
├── docker-compose.yml        # 本機服務編排
├── pyproject.toml            # Python 專案與工具設定
├── .env.example              # 環境變數範例
└── .env.role.example         # 角色環境變數範例
```

## Files on Host Machine (Not in Repository)

部署所需的 host 檔案不提交 Git；設定內容與安裝步驟請見 [03 建置與啟動](./03-setup.md) 與 [05 Migration](./05-migration.md)。

| 路徑 | 用途 | 是否含敏感資料／權限注意 |
|---|---|---|
| `/opt/mailsub/.env` | 靜態 Compose 與 LDAP、資料庫設定 | 是；限部署帳號讀寫，勿提交 Git |
| `/opt/mailsub/.env.role` | monitor 產生的 ACTIVE／STANDBY 覆寫設定 | 是；monitor 與容器需可讀寫，勿提交 Git |
| `/opt/mailsub/ldap-ca.crt` | LDAP TLS CA 憑證，對應 container 內的 `LDAP_CA_CERT_FILE` | 通常否；限 web／worker 可讀 |
| `/etc/mailsub/monitor.env` | host-level monitor 設定與部署路徑 | 可能是；限 monitor 服務讀取，建議 `0640` |
| `/var/lib/mailsub/` | `LAST_SYNC_FILE` 的 host 目錄，bind-mount 給 worker | 否；需允許 worker UID/GID `10001` 寫入 |
| `/var/lib/mailsub/last_sync` | DB sync 成功時間戳（`LAST_SYNC_FILE`） | 否；需由 worker 寫入、由 monitor 讀取 |
| `/etc/systemd/system/mailsub-monitor.service` | 已安裝的 monitor systemd unit | 否；限 root 管理，來源為 `scripts/monitor/` |

## 文件索引

依任務選擇文件：

| 要完成的任務 | 文件 | 用途 |
|---|---|---|
| 了解系統如何分工與同步 | [01 系統架構](./01-architecture.md) | 系統邊界、資料流、業務規則與 HA 限制的概觀說明 |
| 準備執行環境或確認外部依賴 | [02 依賴與硬體](./02-dependency-hardware.md) | Docker、資料庫、LDAP、網路與選用 HA 的需求 |
| 設定、啟動或驗證服務 | [03 建置與啟動](./03-setup.md) | 環境變數、本機 Compose、LDAP 設定、HA 與驗證步驟 |
| 查詢 API 或資料表行為 | [04 API 與資料庫](./04-api-and-db.md) | API、資料模型、權限、佇列與實際回應規格 |
| 執行部署、migration 或維運操作 | [05 Migration](./05-migration.md) | migration、部署差異、同步、備份與營運限制 |

## Quick Start

需要設定、啟動或驗證服務時，請完整依序執行 [03 建置與啟動](./03-setup.md) 的 **Prerequisites**、**Environment Variables**、**啟動前 validation gate**、**Step-by-Step Local Launch** 與驗證步驟。不要在 validation gate 通過前啟動 Compose，也不要用本頁以外的命令繞過檢查。

系統的責任邊界是：LDAP 是唯一真相來源；PostgreSQL 是本地快取與工作佇列；LDAP 同步 worker 只在 ACTIVE 節點執行 LDAP 寫入。
