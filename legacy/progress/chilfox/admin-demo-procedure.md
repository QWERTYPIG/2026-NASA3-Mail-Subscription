# Demo Procedure — Admin Flow
## 前置準備

### 帳號需求

| 角色 | 說明 |
|------|------|
| Admin | `mailtest`（目前唯一有 mailAdmin group 的帳號） |

### 啟動服務（若尚未啟動）

```bash
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose ps
docker compose logs worker --tail=30
```

預期：`postgres`、`redis`、`web`、`worker` 都是 `Up`；worker log 看到 `Process-1 … running`。

---

## Step 1 — Admin Login（預期：Login success）

```bash
curl -s -c cookies.txt -X POST http://172.16.127.102:8000/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"mailtest\", \"password\": \"muddyq-dysqe8-sEdteb\"}" | python3 -m json.tool
```

**預期 200**：
```json
{ "username": "mailtest", "is_staff": true }
```

`cookies.txt` 儲存 `sessionid` 與 `csrftoken`，後續請求使用。

---

## Step 2 — Get User Data（預期：Admin flag set to true）

```bash
curl -s -b cookies.txt http://172.16.127.102:8000/api/v1/auth/me/ | python3 -m json.tool
```

**預期 200**：
```json
{ "username": "mailtest", "is_admin": true }
```

---

## Step 3 — Get All Aliases（預期：List of all aliases）

```bash
curl -s -b cookies.txt http://172.16.127.102:8000/api/v1/admin/aliases/ | python3 -m json.tool
```

**預期 200**，回傳所有 alias 清單（不含 `is_subscribed` 欄位）：
```json
[
  { "alias_name": "test-list", "display_name": "測試清單", "description": "..." },
  { "alias_name": "workstation", "display_name": "工作站", "description": "..." }
]
```

---

## Step 4 — Logout（預期：Logout success）

```bash
CSRF=$(grep csrftoken cookies.txt | awk '{print $NF}')
curl -s -b cookies.txt -c cookies.txt -X POST http://172.16.127.102:8000/api/v1/auth/logout/ \
  -H "X-CSRFToken: $CSRF" -v 2>&1 | grep "< HTTP"
```

**預期 `HTTP/1.1 205 Reset Content`**。

---

## Step 5 — Get All Aliases After Logout（預期：Fail — no credentials）

```bash
curl -s -b cookies.txt http://172.16.127.102:8000/api/v1/admin/aliases/ | python3 -m json.tool
```

**預期 403**（session 已清除）：
```json
{ "detail": "Authentication credentials were not provided." }
```
