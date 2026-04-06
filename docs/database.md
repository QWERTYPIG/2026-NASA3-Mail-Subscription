# Database — PostgreSQL

PostgreSQL 是 LDAP 的本地 cache，**不是 source of truth**。所有資料以 LDAP 為準，PostgreSQL 每 5 分鐘做一次 consistency check。

---

## Table: `alias`

| 欄位 | 型別 | 說明 |
|------|------|------|
| `alias_name` | `CharField` | 對應 LDAP `cn`（唯一識別碼）|
| `display_name` | `CharField` | 前端顯示名稱 |
| `description` | `TextField` | 前端顯示介紹 |
| `user_ids` | `ArrayField[CharField]` | 訂閱者 uid 列表（從 LDAP 同步）|

## Table: `task_queue`

紀錄待同步至 LDAP 的變更，分為兩類：alias 操作與 user 操作。Flush 時 alias task 優先執行。

| 欄位           | 型別              | 說明                                                     |
| ------------ | --------------- | ------------------------------------------------------ |
| `id`         | `AutoField`     | 自動遞增                                                   |
| `task_type`  | `CharField`     | `alias`（新增/刪除 alias entry）或 `user`（MOD_ADD/MOD_DELETE） |
| `alias_name` | `CharField`     | 目標 alias 的 `cn`                                        |
| `user_uid`   | `CharField`     | 操作對象的 uid（`task_type=user` 時使用）                        |
| `action`     | `CharField`     | `add` 或 `remove`                                       |
| `status`     | `CharField`     | `pending` / `done` / `failed`                          |
| `created_at` | `DateTimeField` | 建立時間                                                   |
|              |                 |                                                        |

> [!todo] User table
> proposal 提到可能需要獨立的 user table（例如存放最後操作時間，用於 rate limit 的 DB timestamp 方案）。目前 rate limit 實作方式尚未確定，此 table 是否需要待 [open-decisions](./docs/open-decisions.md) 解決後補充。
