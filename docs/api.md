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

## Subscriptions — `/api/v1/user/subscriptions/`

### `GET /api/v1/user/subscriptions/`

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

### `PUT /api/v1/user/subscriptions/`

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

---

## Aliases - `/api/v1/admin/aliases`

### `GET /api/v1/admin/aliases/`

取得所有 alias 列表。

**Admin** — 回傳 alias 列表，無需 `is_subscribed` 欄位（admin 不訂閱，只管理成員）。

**Response `200 OK`**

```json
[
  {
    "alias_name": "workstation",
    "display_name": "工作站",
    "description": "工作站清理、重開機公告"
  },
  {
    "alias_name": "activities",
    "display_name": "系上活動",
    "description": "演講、交流"
  }
]
```

---

### `POST /api/v1/admin/aliases/`

建立新的 mailing list alias。

**Permission** — `IsAdminUser`

**Request header**

```
X-CSRFToken: <csrftoken cookie 的值>
```

**Request body**

```json
{
  "alias_name": "new_alias",
  "display_name": "新群組",
  "description": "這是一個新建立的群組"
}
```

**Response `201 Created`**

```json
{
  "alias_name": "new_alias",
  "display_name": "新群組",
  "description": "這是一個新建立的群組"
}
```

---

### `DELETE /api/v1/admin/aliases/<alias_name>/`

刪除整個 mailing list alias。

**Permission** — `IsAdminUser`

**Request header**

```
X-CSRFToken: <csrftoken cookie 的值>
```

**Response `204 No Content`**

---

### `GET /api/v1/admin/aliases/<alias_name>/users/`

取得指定 alias 的所有訂閱用戶列表。

**Permission** — `IsAdminUser`

**Response `200 OK`**

```json
[
  "b13902001",
  "b13902002",
  "b13902003"
]
```

---

### `POST /api/v1/admin/aliases/<alias_name>/users/`

手動將指定用戶（依 UID）加入到 alias。

**Permission** — `IsAdminUser`

**Request header**

```
X-CSRFToken: <csrftoken cookie 的值>
```

**Request body**

```json
{
  "uid": "b13902xxx"
}
```

**Response `200 OK`**

```json
{
  "status": "success",
  "message": "用戶已加入此 alias"
}
```

---

### `DELETE /api/v1/admin/aliases/<alias_name>/users/<uid>/`

手動移除指定用戶從 alias。

**Permission** — `IsAdminUser`

**Request header**

```
X-CSRFToken: <csrftoken cookie 的值>
```

**Response `204 No Content`**

---

## Error Responses

### `400 Bad Request`

**Validation Error**

```json
{
  "error": "Validation failed",
  "code": "VALIDATION_ERROR",
  "details": {
    "alias_name": ["Alias name can only contain lowercase letters and numbers."],
    "uid": ["Ensure this field has exactly 9 characters."]
  }
}
```

### `401 Unauthorized`

**Authentication Error**

```json
{
  "error": "Authentication credentials were not provided or CSRF verification failed.",
  "code": "NOT_AUTHENTICATED"
}
```

### `403 Forbidden`

**Permission Denied**

```json
{
  "error": "You do not have permission to perform this action.",
  "code": "PERMISSION_DENIED"
}
```

### `404 Not Found`

**Resource Not Found**

```json
{
  "error": "The requested resource was not found.",
  "code": "NOT_FOUND"
}
```

### `409 Conflict`

**Resource Already Exists**

```json
{
  "error": "Alias name already exists.",
  "code": "CONFLICT",
  "details": {
    "existing_alias": "workstation"
  }
}
```

### `429 Too Many Requests`

**Rate Limited**

```json
{
  "error": "Request was throttled.",
  "code": "TOO_MANY_REQUESTS",
  "details": {
    "wait_seconds": 45
  }
}
```

### `500 Internal Server Error`

**Server Error**

```json
{
  "error": "An unexpected error occurred. Please contact the administrator.",
  "code": "INTERNAL_SERVER_ERROR"
}
```

