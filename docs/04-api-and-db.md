# API 與資料庫參考

本頁是目前實作的 exhaustive reference；以 `core`、`apps` 與 `frontend` 為準。API 不直接寫入 LDAP：本地資料庫與 task queue 先更新，worker 再同步 LDAP。

## Base path

- Base path：`/api/v1`
- JSON：request/response 使用 `application/json`；`204`、`205` 無 body。
- Authentication：Django database session；不是 JWT。前端 Axios 使用 `withCredentials`、`csrftoken` cookie 與 `X-CSRFToken` header。
- Admin：session user 的 `is_staff=True`。LDAP `mailAdmin` group 同步至 local `is_staff`。
- 未登入的受保護 endpoint 目前通常回 `403`；CSRF rejection 也可能是 Django 原生 `403`。

## Endpoint index

| Endpoint | Methods |
|---|---|
| [`/api/v1/health/`](#health) | `GET` |
| [`/api/v1/auth/login/`](#login) | `POST` |
| [`/api/v1/auth/me/`](#me) | `GET` |
| [`/api/v1/auth/logout/`](#logout) | `POST` |
| [`/api/v1/manage/aliases/`](#alias-list) | `GET`, `POST` |
| [`/api/v1/manage/aliases/{alias_name}/`](#alias-detail) | `GET`, `PATCH`, `PUT`, `DELETE` |
| [`/api/v1/manage/aliases/{alias_name}/users/`](#member-list) | `GET`, `POST` |
| [`/api/v1/manage/aliases/{alias_name}/users/{uid}/`](#member-detail) | `DELETE` |
| [`/api/v1/user/subscriptions/`](#subscriptions) | `GET`, `PUT` |

## Endpoints

每個 endpoint 依序列出：權限、request/path、success status/body、主要 errors、side effects。JSON 片段均為 **contract example**，不是可直接使用的憑證或通用輸入。

<a id="health"></a>
### `GET /api/v1/health/`

- **權限**：公開。
- **Request/path**：無。
- **Success**：`200`，`{"status":"ok"}`。
- **主要 errors**：未預期錯誤可能為 `500`。
- **Side effects**：無。

<a id="login"></a>
### `POST /api/v1/auth/login/`

- **權限**：公開；此 view 不使用 API authentication class。
- **Request/path**：`{"username":"<uid>","password":"<password>"}`（contract example；`<uid>` 與 `<password>` 必須替換為真實 LDAP/Django credentials）。
- **Success**：`200`，`{"username":"<uid>","is_staff":false}`；建立 database session 並產生 CSRF token cookie。
- **主要 errors**：credentials 失敗為 `401`：`{"error":"Authentication credentials were not provided or CSRF verification failed.","code":"NOT_AUTHENTICATED"}`。
- **Side effects**：呼叫 Django authentication、`login()`、`get_token()`。

<a id="me"></a>
### `GET /api/v1/auth/me/`

- **權限**：已登入 session。
- **Request/path**：無。
- **Success**：`200`，`{"username":"<uid>","is_admin":true}`；`is_admin` 映射 `is_staff`。
- **主要 errors**：未登入通常 `403`；無統一 error body。
- **Side effects**：無。

<a id="logout"></a>
### `POST /api/v1/auth/logout/`

- **權限**：已登入 session；非 GET request 仍受 CSRF middleware 影響。
- **Request/path**：無 body；帶 session cookie 與 CSRF header。
- **Success**：`205 Reset Content`，無 body。
- **主要 errors**：未登入通常 `403`；CSRF 失敗可能為 Django 原生 `403`。
- **Side effects**：使 session 失效並清除 Django session cookies。

<a id="alias-list"></a>
### `GET /api/v1/manage/aliases/`

- **權限**：Admin。
- **Request/path**：無。
- **Success**：`200`，依 `alias_name` 升冪的陣列：`[{"alias_name":"activities","display_name":"Activities","description":"Dept events"}]`。
- **主要 errors**：權限失敗 `403`；其他 framework `5xx`。
- **Side effects**：無。

### `POST /api/v1/manage/aliases/`

- **權限**：Admin。
- **Request/path**：`alias_name`、`display_name`、`description` 必填且不可空白；alias name 僅允許英數字與 `-`。完整 contract example：`{"alias_name":"security-alerts","display_name":"Security Alerts","description":"重要通知"}`。
- **Success**：`201`，alias representation（同上）。
- **主要 errors**：validation `400` 為 DRF serializer 格式；重複名稱 `409`：`{"error":"Alias name already exists.","code":"CONFLICT","details":{"existing_alias":"security-alerts"}}`；未預期錯誤 `500` custom body。
- **Side effects**：同一 transaction 建立 `alias` 與 `sync_task(kind="alias", action="add")`。

<a id="alias-detail"></a>
### `GET|PATCH|PUT|DELETE /api/v1/manage/aliases/{alias_name}/`

- **權限**：Admin。
- **Request/path**：`GET`、`DELETE` 無 body。`PATCH`/`PUT` 可含 `display_name`、`description`；兩者目前都以 partial update 處理。`display_name` 最長 255、`description` 最長 500，均可空白。
- **Success**：`GET`/`PATCH`/`PUT` 為 `200` alias representation；`DELETE` 為 `204` 無 body。
- **主要 errors**：`GET` 不存在時為 DRF/framework `404`；`PATCH`/`PUT`/`DELETE` 不存在為 custom `404 NOT_FOUND`；更新 validation `400` custom `VALIDATION_ERROR`；未預期錯誤 `500` custom `INTERNAL_SERVER_ERROR`。
- **Side effects**：更新只改 `alias`，不建 queue。刪除在 transaction 內先建 `sync_task(kind="alias", action="remove")` 再刪除 `alias`；該 alias 的 `alias_member` rows 由 `ON DELETE CASCADE` 一併刪除；LDAP 由 worker 處理。

<a id="member-list"></a>
### `GET /api/v1/manage/aliases/{alias_name}/users/`

- **權限**：Admin。
- **Request/path**：無。
- **Success**：`200`，UID 陣列，依加入順序（`alias_member.id` 升冪），例如 `["b12345678"]`（contract example）。
- **主要 errors**：alias 不存在 `404` custom `NOT_FOUND`；未預期錯誤 `500` custom。
- **Side effects**：無。

### `POST /api/v1/manage/aliases/{alias_name}/users/`

- **權限**：Admin。
- **Request/path**：`{"uid":"b12345678"}`；server 會 trim/lowercase，最多 50 字元、僅英數字，並同步查 LDAP；`gidNumber` 必須含 `450`、`400`、`500` 或 `200`。
- **Success**：`200`，`{"status":"success","message":"User b12345678 added to activities"}`。
- **主要 errors**：UID/LDAP/GID validation `400` custom `VALIDATION_ERROR`（`details.uid`）；重複 UID `409` custom `CONFLICT`；alias 不存在 `404`；未預期錯誤 `500`。
- **Side effects**：transactionally 新增一筆 `alias_member`，並建立 `sync_task(kind="member", action="add")`。

<a id="member-detail"></a>
### `DELETE /api/v1/manage/aliases/{alias_name}/users/{uid}/`

- **權限**：Admin。
- **Request/path**：無 body。`uid` 是 Django `<str:uid>`；空字串不匹配 route，且不做 trim、lowercase 或格式 validation，必須精確匹配 `alias_member.user_uid`。
- **Success**：`204`，無 body。
- **主要 errors**：alias 不存在或 UID 不在 alias 為 `404` custom `NOT_FOUND`；未預期錯誤 `500` custom。
- **Side effects**：transactionally 刪除該 `alias_member` row，建立 `sync_task(kind="member", action="remove")`。

<a id="subscriptions"></a>
### `GET|PUT /api/v1/user/subscriptions/`

- **權限**：已登入 session；Admin 也可使用。
- **Request/path**：`GET` 無 body。`PUT` 必須送出每個現有 alias 恰好一次的完整 map，key 為 alias name、value 為 JSON boolean；不可缺漏或含未知 alias，例如 `{"activities":true,"workstation":false}`。
- **Success**：`GET` 為 `200`，依 alias name 排序的陣列，每筆含 `alias_name`、`display_name`、`description`、`is_subscribed`。`PUT` 為 `202`：`{"status":"accepted","message":"Subscription update accepted.","changed_aliases":["activities"],"task_ids":[42]}`。
- **主要 errors**：permission `403`；PUT validation `400` 為 DRF serializer 格式（通常 `non_field_errors`）；每 user cooldown 內再次 PUT 為 `429`，body 是 DRF 預設格式，未由本專案定義；未預期錯誤可能為 framework `5xx`。
- **Side effects**：只對實際變更在 transaction 內新增或刪除 `alias_member` row，並建立 `sync_task(kind="member")`；`changed_aliases` 依 alias name 排序，`task_ids` 為對應的 `sync_task.id`（同順序）；PUT 執行期間被刪除的 alias 直接略過；LDAP 非同步同步。

## Contract examples: session and mutation

以下 commands 只在 `BASE_URL`、`USERNAME`、`PASSWORD` 已由呼叫者提供真實值時可執行；文件不提供可重放 credentials。需要 `curl`、`jq` 與 `awk`，並保留 cookie jar 以完成 session/CSRF 前置：

```sh
set -eu
: "${BASE_URL:?set BASE_URL to the deployed API origin, e.g. https://mail.example.edu}"
: "${USERNAME:?set USERNAME to a real LDAP UID}"
: "${PASSWORD:?set PASSWORD to the real password}"
COOKIE_JAR="$(mktemp)"
trap 'rm -f "$COOKIE_JAR"' EXIT

curl --fail-with-body -sS -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --arg username "$USERNAME" --arg password "$PASSWORD" '{username:$username,password:$password}')" \
  "$BASE_URL/api/v1/auth/login/"

curl --fail-with-body -sS -b "$COOKIE_JAR" "$BASE_URL/api/v1/auth/me/"
CSRF_TOKEN="$(awk '$6 == "csrftoken" { print $7 }' "$COOKIE_JAR")"
curl --fail-with-body -sS -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
  -H 'Content-Type: application/json' -H "X-CSRFToken: $CSRF_TOKEN" \
  -d '{"activities":true,"workstation":false}' \
  "$BASE_URL/api/v1/user/subscriptions/"
```

`PUT` payload 必須與當下資料庫的完整 alias 集合一致；上例中的 alias 僅為 contract example，不保證部署環境存在。若只需 login/session，仍應保留 `-c`/`-b`，因 login response 才會建立 session 與 CSRF cookie。

## Error contract

目前**沒有全站一致的 error envelope**。部分 subscriptions handlers 使用 `{"error":"...","code":"...","details":{}}`，已知 custom code 為 `NOT_FOUND`、`VALIDATION_ERROR`、`CONFLICT`、`INTERNAL_SERVER_ERROR`；create 與 subscription PUT 的 serializer errors 是 DRF 原生格式；permission、CSRF、throttle 也可能是 framework 格式。不可假設每個 `4xx/5xx` 都有 `error` 或 `code`。`204`/`205` 沒有 JSON body。

## Schema

| Table | Columns | Constraints / purpose |
|---|---|---|
| `alias` | `alias_name varchar(255)`, `display_name varchar(255)`, `description text` | `alias_name` PK/unique/required，regex `^[a-zA-Z0-9-]+$`；其餘非 NULL、default `''`；description API max 500，非 DB constraint。 |
| `alias_member` | `id bigint`, `alias_name varchar(255)`, `user_uid varchar(255)` | 一列一個成員（3NF）。PK auto-increment，`id` 順序即加入順序；`alias_name` FK → `alias`，`ON DELETE CASCADE`；`UNIQUE(alias_name, user_uid)`；`user_uid` 有 index。 |
| `sync_task` | `id bigint`, `kind varchar(10)`, `action varchar(10)`, `alias_name varchar(255)`, `user_uid varchar(255) NULL`, `created_at timestamptz` | alias 與成員共用的單一 LDAP 同步 queue。PK auto-increment，`id` 即兩種 task 的全域處理順序（可能有空號）。`kind` 僅 `alias`/`member`、`action` 僅 `add`/`remove`（DB CHECK）；`kind="alias"` 時 `user_uid` 必須為 NULL，`kind="member"` 時必須有值（DB CHECK）。刻意不設 FK：task 須在 alias row 刪除後仍存在。`created_at` NOT NULL，寫入端建立 task 時自動填入 enqueue 時間（`writes.py` 函式不需傳入），用來看 task 在 queue 中等了多久；migration `0005` 之前就存在的 row 填入 migration 執行時間。index `(alias_name, id)`。 |

`alias_member` 以 FK、`sync_task` 以字串 `alias_name` 對應 `alias`；只有 `sync_task.created_at` 是 timestamp。PostgreSQL 儲存 metadata、member cache、queue；Redis 只供 cache、cooldown、flush lock。`TIME_ZONE=UTC`、`USE_TZ=True`，API 目前沒有 date/datetime 欄位。

## Runtime behavior

- LDAP 是 alias/member source of truth；Django API 不直接寫入 `ou=Aliases`。
- **寫入端**：所有會同步到 LDAP 的變更（alias 建立/刪除、成員新增/移除、使用者訂閱 PUT）都只經過 `apps/subscriptions/writes.py`；views 不直接寫 `alias_member` 或 `sync_task`。每個函式在同一 transaction 內先取 per-alias lock（PostgreSQL `pg_advisory_xact_lock(0x6D61696C, hashtext(alias_name))`，commit 才釋放），再更新 cache、建立 `sync_task`。因此同一 alias 的 `sync_task.id` 順序等於 commit 順序；alias row 尚不存在（建立）時也鎖得住。PUT 一次鎖多個 alias，依 alias name 排序取鎖以避免 deadlock。alias PATCH 只改顯示欄位，不經過此模組。`sync_task` 依 `id` 升冪處理，失敗 row 保留重試；LDAP retry delay 為 `0.5, 1, 2, 4, 8` 秒。
- **讀取端（sync interface）**：LDAP 同步端只 import `apps/subscriptions/sync.py`，依 `id` 逐筆取 task、回報結果，最後以 LDAP snapshot 在同一把 per-alias lock 內校正 cache；仍有 queued task 的 alias 不覆蓋。完整合約見 [06 同步介面](./06-sync-interface.md)。
- **過渡狀態**：`apps/subscriptions/tasks.py`（LDAP 同步 worker）尚未改用 `sync.py`，仍引用已移除的 `AliasTaskQueue`、`UserTaskQueue` 與 `alias.user_id`，在 port 到 [sync interface](./06-sync-interface.md) 前無法執行。此狀態不得部署。
- `PUT /user/subscriptions/` 每 user 以 Redis key `user_subscription_cooldown:<username>` 冷卻 600 秒；throttle 在 validation 前佔用 slot，失敗 request 也可能留下 cooldown。worker schedule 為 30 分鐘，flush lock TTL 為 300 秒；這些都是 duration，不是 API datetime。
- migration `0001_initial` 建立 `alias`、`alias_task_queue`、`user_task_queue`；`0002_add_flush_ldap_schedule` 建立 `flush_ldap_tasks` 的 30 分鐘 schedule；`0003_sync_task` 以 `sync_task` 取代兩張舊 queue（舊 queue 有資料時拒絕執行，反向時 `sync_task` 有資料亦拒絕）；`0004_alias_member` 把 `alias.user_id` array 搬進 `alias_member` 後刪除該欄位（可反向，依 `id` 重建 array）。部署步驟見 [05 Migration](./05-migration.md)。

## Known implementation differences

| Area | Actual behavior | Frontend/test mismatch |
|---|---|---|
| Member add | duplicate UID 回 `409`；POST 成功先更新 PostgreSQL、再排 queue。 | 舊 test `test_add_duplicate` 仍期待 `200`；UI 文案稱立即生效。 |
| Member delete | 不驗證 UID 格式；不在 alias 即 `404`。 | 舊 tests 曾期待 invalid UID `400`。 |
| Subscription cooldown | 實際為 10 分鐘；LDAP schedule 為 30 分鐘。 | frontend success toast 只說「30 分鐘內生效」，429 嘗試讀未定義的 `response.data.detail`。 |
| UID casing | POST normalized to lowercase；frontend 成功後仍以原始 trimmed input 更新 local state。 | 大寫輸入可能使後續 delete path 與 backend cache 不一致。 |
| Member timing | member add/delete 先改 PostgreSQL、非同步同步 LDAP。 | `AliasDetail.jsx` 警告文字稱立即生效。 |

敏感設定（`SECRET_KEY`、database/LDAP passwords、cookie/token values）不在本頁記錄。
