# Authentication & Authorization

---

## 登入流程

```
① React     →  POST /auth/login          →  Django
② Django    →  Bind (django-auth-ldap)   →  LDAP (ou=people)
③ Django    →  查詢 cn=mailAdmin         →  LDAP (ou=group)
④ Django    →  INSERT session            →  PostgreSQL
⑤ Django    →  Set-Cookie (sessionid + csrftoken)  →  React
```

---

## RBAC

系統採單一入口，透過 LDAP 群組進行角色判定。

| 角色 | 判定條件 | Django 標記 |
|------|----------|-------------|
| 一般使用者 | 通過 LDAP bind 即可 | `is_admin=False` |
| Admin | `uid` 出現在 `cn=mailAdmin,ou=group` 的 `memberUid` | `is_admin=True` |

> [!note] `is_staff` vs `is_admin`
> - `POST /api/v1/auth/login/` 回傳 `is_staff`（Django 內建欄位，由 `django-auth-ldap` 的 group mapping 設定）
> - `GET /api/v1/auth/me/` 回傳 `is_admin`（前端應以此為準判斷角色）
> - 兩者語意相同，都代表是否為 mailAdmin 成員。

React 依據 `/me/` 回傳的 `is_admin` 決定是否渲染 `/admin` 管理介面。

DRF API 權限分層：
- User API：`IsAuthenticated`（驗證 Session Cookie）
- Admin API：`IsAdminUser`（額外驗證 `is_admin`）

詳細 LDAP 群組結構見 [ldap — Admin 群組判定](./docs/ldap.md#admin-群組判定)。

---

## Session Cookie

### 安全設定（`settings.py`）

```python
SESSION_COOKIE_HTTPONLY = True   # 禁止前端 JS 讀取 sessionid，防 XSS
SESSION_COOKIE_SECURE = True     # 僅 HTTPS 傳輸
SESSION_COOKIE_SAMESITE = 'Lax'  # 防 CSRF 第一道防線
```

### CSRF 防護

前端所有資料異動請求（`POST`、`PATCH`、`DELETE`）必須在 header 加上：

```
X-CSRFToken: <token_value>
```

Token 從 Django 登入後派發的 `csrftoken` cookie 讀取。後端需啟用：

```python
MIDDLEWARE = [
    ...
    'django.middleware.csrf.CsrfViewMiddleware',
    ...
]
```

---

## Rate Limiting

使用者送出訂閱更新後，冷卻時間為 **10 分鐘**。冷卻中的請求回傳 `HTTP 429 Too Many Requests`，Response Body 附上剩餘秒數。

採用 **Redis TTL**：使用者送出訂閱更新後，以 `user_uid` 為 key 寫入 Redis（index 1），TTL = 冷卻時間。key 存在即冷卻中，key 自動過期不需手動清除。不需要額外的 user table。
