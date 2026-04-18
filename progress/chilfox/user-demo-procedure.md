# Demo Procedure — User Flow

> 最後更新：2026-04-18
>
> 依照 demo slides「Demo Steps: User」順序排列，共 9 步 + 2 次 Mail Testing。
> 所有指令均根據 [testing-procedure.md](./testing-procedure.md) 驗證過的流程。

---

## 前置準備

### 帳號需求

| 角色 | 說明 |
|------|------|
| 一般使用者 | 一般 LDAP 帳號，無 mailAdmin group，`is_staff=false` |
| Admin | `mailtest`（目前唯一有 mailAdmin group 的帳號） |

### 載入環境變數

```bash
export $(grep MAILTEST_PASSWORD .env | xargs)
```

### 啟動服務（若尚未啟動）

```bash
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose ps
docker compose logs worker --tail=30
```

預期：`postgres`、`redis`、`web`、`worker` 都是 `Up`；worker log 看到 `Process-1 … running`。

### 建立 Demo 用 Alias（若尚未存在）

```bash
docker compose exec web python manage.py shell -c "
from apps.subscriptions.models import AliasTaskQueue
AliasTaskQueue.objects.create(alias_name='test-list', action='add')
AliasTaskQueue.objects.create(alias_name='workstation', action='add')
print('done')
"
```

```bash
docker compose exec web python manage.py shell -c "
from apps.subscriptions.tasks import flush_ldap_tasks
flush_ldap_tasks()
"
```

確認 DB 已有這兩筆：

```bash
docker compose exec web python manage.py shell -c "
from apps.subscriptions.models import Alias
print(list(Alias.objects.values('alias_name', 'display_name')))
"
```

---

## Step 1 — User Login（預期：Login success）

```bash
curl -s -c cookies.txt -X POST http://localhost:8000/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "b13902992", "password": "b13902992"}' | python3 -m json.tool
```

**預期 200**：
```json
{ "username": "b13902992", "is_staff": false }
```

`cookies.txt` 儲存 `sessionid` 與 `csrftoken`，後續請求使用。

---

## Step 2 — Get User Data（預期：Admin flag set to false）

```bash
curl -s -b cookies.txt http://localhost:8000/api/v1/auth/me/ | python3 -m json.tool
```

**預期 200**：
```json
{ "username": "b13902992", "is_admin": false }
```

---

## Step 3 — Get Admin Page（預期：Fail — no permission）

```bash
curl -s -b cookies.txt http://localhost:8000/api/v1/admin/aliases/ | python3 -m json.tool
```

**預期 403**：
```json
{ "detail": "You do not have permission to perform this action." }
```

---

## Step 4 — Get Aliases（預期：List of aliases and status）

```bash
curl -s -b cookies.txt http://localhost:8000/api/v1/user/subscriptions/ | python3 -m json.tool
```

**預期 200**，每筆含 `is_subscribed` 欄位，初始皆為 `false`：
```json
[
  { "alias_name": "test-list", "display_name": "測試清單", "description": "...", "is_subscribed": false },
  { "alias_name": "workstation", "display_name": "工作站", "description": "...", "is_subscribed": false }
]
```

---

## Step 5 — Modify Subscriptions（預期：Modification success）

取出 CSRF token：

```bash
CSRF=$(grep csrftoken cookies.txt | awk '{print $NF}')
```

送出訂閱更新（完整 alias→boolean map）：

```bash
curl -s -b cookies.txt -X PUT http://localhost:8000/api/v1/user/subscriptions/ \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: $CSRF" \
  -d '{"test-list": true, "workstation": false}' | python3 -m json.tool
```

**預期 202**：
```json
{
  "status": "accepted",
  "message": "Subscription update accepted.",
  "changed_aliases": ["test-list"],
  "task_ids": [1]
}
```

---

## Step 6 — Modify Subscriptions Again（預期：Fail — too many requests）

立刻再送一次相同請求（10 分鐘 cooldown 未到）：

```bash
curl -s -b cookies.txt -X PUT http://localhost:8000/api/v1/user/subscriptions/ \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: $CSRF" \
  -d '{"test-list": true, "workstation": false}' | python3 -m json.tool
```

**預期 429**：
```json
{ "detail": "請等待 600 秒後再試" }
```

> throttle 只針對 PUT，後續的 GET（step 7）不受影響，可直接繼續。

---

## Step 7 — Get Alias（預期：Aliases status modified）

先手動觸發 LDAP 同步（不等排程的 3 分鐘）：

```bash
docker compose exec web python manage.py shell -c "
from apps.subscriptions.tasks import flush_ldap_tasks
flush_ldap_tasks()
"
```

再查 alias 清單：

```bash
curl -s -b cookies.txt http://localhost:8000/api/v1/user/subscriptions/ | python3 -m json.tool
```

**預期 200**，`test-list` 的 `is_subscribed` 現為 `true`：
```json
[
  { "alias_name": "test-list", "display_name": "測試清單", "description": "...", "is_subscribed": true },
  { "alias_name": "workstation", "display_name": "工作站", "description": "...", "is_subscribed": false }
]
```

確認 LDAP 端 `test-list` 的 `uniqueMember` 現在包含使用者（由使用者自行執行）：

```bash
ldapsearch -H ldap://172.16.127.109:389 \
  -D "uid=mailtest,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw" \
  -w "$MAILTEST_PASSWORD" \
  -b "ou=Aliases,dc=csie,dc=ntu,dc=edu,dc=tw" \
  "(cn=test-list)" uniqueMember
```

**預期**：`uniqueMember` 包含 `uid=b13902992,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw`。

---

## Step 8 — Logout（預期：Logout success）

```bash
CSRF=$(grep csrftoken cookies.txt | awk '{print $NF}')
curl -s -b cookies.txt -c cookies.txt -X POST http://localhost:8000/api/v1/auth/logout/ \
  -H "X-CSRFToken: $CSRF" -v 2>&1 | grep "< HTTP"
```

**預期 `HTTP/1.1 205 Reset Content`**。

---

## Step 9 — Get Aliases After Logout（預期：Fail — no credentials）

```bash
curl -s -b cookies.txt http://localhost:8000/api/v1/user/subscriptions/ | python3 -m json.tool
```

**預期 403**（session 已清除）：
```json
{ "detail": "Authentication credentials were not provided." }
```

## Step 10 - Mimic consistency check sending alert mail when unable to connect LDAP server

```bash
docker compose exec web python manage.py shell -c "
import os
os.environ['LDAP_URI'] = 'ldap://127.0.0.1:1'

import importlib
import apps.subscriptions.tasks as t
importlib.reload(t)

try:
    t._connect()
except Exception as e:
    print('expected error:', e)
"
```

**預期在 mailpit 看到送給 admin 的 alert mail**
