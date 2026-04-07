# API

所有 endpoint 以 `/api/v1/` 為前綴。

---

## Auth — `/api/v1/auth/`

### `POST /api/v1/auth/login/`

登入並取得 session cookie。

**Request body**

```json
{ "username": "b13902xxx", "password": "..." }
```

**Response `200 OK`**

```json
{ "username": "b13902xxx", "is_staff": true }
```

**Set-Cookie**

- `csrftoken`：SameSite=Lax，Max-Age=31449600
- `sessionid`：HttpOnly，SameSite=Lax，Max-Age=1209600

> [!note] `is_staff` 是 Django 內建欄位 前端判斷 admin 身份請用 `GET /me/` 回傳的 `is_admin`，不要依賴此欄位。見 [auth — RBAC](https://claude.ai/chat/docs/auth.md#rbac)。

---

### `GET /api/v1/auth/me/`

取得目前登入使用者的資訊與角色。需帶 session cookie。

**Response `200 OK`**

```json
{ "username": "b13902xxx", "is_admin": true }
```

---

### `POST /api/v1/auth/logout/`

登出，清除 session。需帶 session cookie 與 CSRF token。

**Request header**

```
X-CSRFToken: <csrftoken cookie 的值>
```

**Response `205 Reset Content`**（無 body，sessionid cookie 清空）

---

## Subscriptions — `/api/v1/subscriptions/`

> [!todo] 以下 endpoints 尚未實作，schema 待確認 目前只有 auth 部分完成。

### `GET /api/v1/subscriptions/`

取得所有 alias 的資訊。

**User** — 回傳每個 alias 的訂閱狀態：

```json
[
  {
    "alias_name": "workstation",
    "display_name": "工作站",
    "description": "工作站清理、重開機公告",
    "is_subscribed": true
  },
  {
    "alias_name": "activities",
    "display_name": "系上活動",
    "description": "演講、交流",
    "is_subscribed": false
  }
]
```

**Admin** — 回傳 alias 列表，無需 `is_subscribed` 欄位（admin 不訂閱，只管理成員）。

> [!todo] Admin response schema 待後端確認 是回傳不含 `is_subscribed` 的同一結構，還是完全不同的 endpoint？

---

### `POST /api/v1/subscriptions/update/`

更新訂閱狀態。冷卻時間 10 分鐘，冷卻中回傳 `429`。

**重要：Request body 包含使用者所有 alias 的完整狀態，不是 diff。** 後端需自行與 DB 比較判斷哪些有變動。

**Request body**

```json
{
  "workstation": true,
  "activities": false
}
```

**前端行為：** 送出後按鈕進入 Disabled 狀態並顯示倒數計時 10 分鐘。

> [!todo] Response status code 待確認 frontend.md 的實作回傳 `200 OK`，但此操作為非同步（寫入 task queue，3 分鐘後才真正送至 LDAP）。 `202 Accepted` 語意更準確（代表「已收到，處理中」），需後端決定。

**Response（status 待確認）**

```json
{ "status": "success", "message": "已收到訂閱狀態更新請求，將於 10 分鐘內生效" }
```

**Response `429 Too Many Requests`**（冷卻中）

```json
{ "detail": "請等待 X 秒後再試" }
```