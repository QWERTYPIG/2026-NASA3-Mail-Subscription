# Database — PostgreSQL

PostgreSQL 是 LDAP 的本地 cache，**不是 source of truth**。所有資料以 LDAP 為準，PostgreSQL 每 5 分鐘做一次 consistency check。

---

## Table: `alias`

| 欄位 | 型別 | 說明 |
|------|------|------|
| `alias_name` | `CharField` | 對應 LDAP `cn`（唯一識別碼）|
| `display_name` | `CharField` | 前端顯示名稱 |
| `description` | `TextField` | 前端顯示介紹 |
| `user_id` | `ArrayField[CharField]` | 訂閱者 uid 列表（從 LDAP 同步，對應 LDAP `userid`）|

## Table: `alias_task_queue`

紀錄待同步至 LDAP 的 **alias 層級操作**（Admin 新增 / 刪除 alias entry）。Flush 時優先於 `user_task_queue` 執行。

| 欄位           | 型別          | 說明                    |
| ------------ | ----------- | --------------------- |
| `id`         | `AutoField` | 自動遞增                  |
| `alias_name` | `CharField` | 目標 alias 的 `cn`       |
| `action`     | `CharField` | `add` 或 `remove`      |

---

## Table: `user_task_queue`

紀錄待同步至 LDAP 的 **user 層級操作**（User 訂閱 / 退訂 或 Admin 編輯成員，對應 MOD_ADD / MOD_DELETE uniqueMember）。

每筆 task 存一個 alias 與一批 user uid，代表「把這批 user 加入 / 移出該 alias」。一般使用者操作時 `user_uid` 只含自己的 uid；Admin 批次新增 / 刪除成員時可包含多個 uid。每次操作各自建立新 task，不合併至已有 task。

| 欄位           | 型別                      | 說明                             |
| ------------ | ------------------------- | ------------------------------ |
| `id`         | `AutoField`               | 自動遞增                           |
| `alias_name` | `CharField`               | 目標 alias 的 `cn`               |
| `user_uid`   | `CharField`   | 要操作的 user uid 列表（對應 LDAP userid）|
| `action`     | `CharField`               | `add` 或 `remove`               |

