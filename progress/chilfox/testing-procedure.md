# Ubuntu Server 測試流程

> 最後更新：2026-04-15

---

## 前置條件

- Docker Engine + Docker Compose Plugin 已安裝
- 可連到 LDAP server（`ldap://172.16.127.109:389`）
- 有一組可用的 LDAP 帳號（測試用，需能登入）

---

## 一、啟動服務

### 1.1 設定環境變數

建立 `.env` 檔（如果不建，docker-compose.yml 內有預設值，但 LDAP 憑證必須自己設）：

```bash
cat > .env << 'EOF'
LDAP_URI=ldap://172.16.127.109:389
LDAP_BIND_DN=uid=mailtest,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw
LDAP_BIND_PASSWORD=<實際密碼>
EOF
```

### 1.2 建置並啟動

```bash
sudo docker compose up -d --build
```

### 1.3 套用 DB Migration

```bash
sudo docker compose exec web python manage.py migrate
```

### 1.4 確認四個服務都在跑

```bash
sudo docker compose ps
```

預期輸出：`postgres`、`redis`、`web`、`worker` 都是 `Up`。

### 1.5 確認 worker 有抓到 Django-Q 排程

```bash
sudo docker compose logs worker --tail=30
```

預期看到類似 `Process-1 … running` 的訊息，代表 Django-Q cluster 正常啟動。

---

## 二、自動化 Unit Tests

```bash
# 執行全部 subscriptions 測試（313 行，共 7 個 test class）
sudo docker compose exec web python manage.py test apps.subscriptions

# 只測 model 驗證
sudo docker compose exec web python manage.py test apps.subscriptions.tests.SubscriptionModelsTest

# 只測 API 層
sudo docker compose exec web python manage.py test apps.subscriptions.tests.UserSubscriptionUpdateApiTest
```

預期結果：`OK`，沒有 `FAIL` 或 `ERROR`。

---

## 三、手動 API 測試（curl）

以下指令假設 server 在 `localhost`，如果 ssh 進去測請把 `localhost` 換成對應 IP。

### 3.1 建立測試用 Alias

因為目前沒有 admin 建立 alias 的 API，需透過 `AliasTaskQueue` 讓 worker 在 LDAP 建立。
**不能直接寫 DB**——`run_consistency_check()` 以 LDAP 為 source of truth，DB 裡有但 LDAP 沒有的 alias 會被刪掉。

```bash
sudo docker compose exec web python manage.py shell -c "
from apps.subscriptions.models import AliasTaskQueue
AliasTaskQueue.objects.create(alias_name='test-list', action='add')
AliasTaskQueue.objects.create(alias_name='workstation', action='add')
print('done')
"
```

手動觸發一次同步，讓 worker 在 LDAP 建立這兩筆 alias：

```bash
sudo docker compose exec web python manage.py shell -c "
from apps.subscriptions.tasks import flush_ldap_tasks
flush_ldap_tasks()
"
```

確認 DB 已有這兩筆：

```bash
sudo docker compose exec web python manage.py shell -c "
from apps.subscriptions.models import Alias
print(list(Alias.objects.values('alias_name', 'display_name')))
"
```

---

### 3.2 Auth — 登入

```bash
curl -s -c cookies.txt -X POST http://localhost:8000/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "<LDAP帳號>", "password": "<密碼>"}' | python3 -m json.tool
```

**預期 200**：
```json
{ "username": "b13902xxx", "is_staff": false }
```

`cookies.txt` 會儲存 `sessionid` 與 `csrftoken`，後續請求使用。

---

### 3.3 Auth — 確認登入狀態

```bash
curl -s -b cookies.txt http://localhost:8000/api/v1/auth/me/ | python3 -m json.tool
```

**預期 200**：
```json
{ "username": "b13902xxx", "is_admin": false }
```

---

### 3.4 訂閱列表（一般使用者）

```bash
curl -s -b cookies.txt http://localhost:8000/api/v1/user/subscriptions/ | python3 -m json.tool
```

**預期 200**，每筆含 `is_subscribed` 欄位：
```json
[
  { "alias_name": "test-list", "display_name": "測試清單", "description": "...", "is_subscribed": false },
  { "alias_name": "workstation", "display_name": "工作站", "description": "...", "is_subscribed": false }
]
```

---

### 3.5 更新訂閱（PUT）

先從 cookies.txt 取出 CSRF token：

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

再打一次相同請求（10 分鐘 cooldown）：

**預期 429**：
```json
{ "detail": "請等待 X 秒後再試" }
```

---

### 3.6 確認 DB 已更新（不等 LDAP 同步）

```bash
sudo docker compose exec web python manage.py shell -c "
from apps.subscriptions.models import Alias, UserTaskQueue
a = Alias.objects.get(alias_name='test-list')
print('DB user_id:', a.user_id)
print('Pending tasks:', list(UserTaskQueue.objects.values()))
"
```

預期 `user_id` 已包含你的帳號，`UserTaskQueue` 有一筆 `action=add` 待執行。

---

### 3.7 Admin 別名列表

使用有 `is_staff=True` 的帳號重新登入：

```bash
curl -s -c admin_cookies.txt -X POST http://localhost:8000/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "<admin帳號>", "password": "<密碼>"}' | python3 -m json.tool

curl -s -b admin_cookies.txt http://localhost:8000/api/v1/admin/aliases/ | python3 -m json.tool
```

**預期 200**：列表不含 `is_subscribed` 欄位。

若用一般使用者 cookie 打這個 endpoint：**預期 403**。

---

### 3.8 Auth — 登出

```bash
CSRF=$(grep csrftoken cookies.txt | awk '{print $NF}')
curl -s -b cookies.txt -c cookies.txt -X POST http://localhost:8000/api/v1/auth/logout/ \
  -H "X-CSRFToken: $CSRF" -v 2>&1 | grep "< HTTP"
```

**預期 205 Reset Content**。

登出後再打 `/me/`：

```bash
curl -s -b cookies.txt http://localhost:8000/api/v1/auth/me/ | python3 -m json.tool
```

**預期 403**（session 已清除）。

---

## 四、LDAP 同步驗證

> 此步驟需等 Django-Q 排程觸發（每 3 分鐘一次）。

### 4.1 觀察 worker log

```bash
sudo docker compose logs worker -f
```

等待看到 `flush_ldap_tasks` 執行的 log，或手動觸發：

```bash
sudo docker compose exec web python manage.py shell -c "
from apps.subscriptions.tasks import flush_ldap_tasks
flush_ldap_tasks()
"
```

### 4.2 確認 LDAP 已更新

由使用者自行執行（依 CLAUDE.md 規範，不自動執行 LDAP 指令）：

```bash
ldapsearch -H ldap://172.16.127.109:389 \
  -D "uid=mailtest,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw" \
  -w <密碼> \
  -b "ou=Aliases,dc=csie,dc=ntu,dc=edu,dc=tw" \
  "(cn=test-list)" uniqueMember
```

預期結果：`uniqueMember` 包含你的帳號 DN。

### 4.3 Consistency check 後 DB 與 LDAP 一致

```bash
sudo docker compose exec web python manage.py shell -c "
from apps.subscriptions.models import Alias
for a in Alias.objects.all():
    print(a.alias_name, a.user_id)
"
```

---

## 五、錯誤排查

| 現象 | 可能原因 | 檢查指令 |
|------|----------|----------|
| 登入回 401 | LDAP_URI / 帳密錯誤 | `sudo docker compose logs web --tail=20` |
| 登入回 500 | LDAP 連不到 | `sudo docker compose exec web python manage.py shell -c "import ldap; ldap.initialize('ldap://172.16.127.109:389').simple_bind_s()"` |
| PUT 回 400 | request body 缺少某個 alias | 先 GET 確認目前 alias 清單，body 需包含全部 |
| worker 沒動作 | Redis 連線問題 | `sudo docker compose exec redis redis-cli ping` |
| migrate 失敗 | DB 未就緒 | `sudo docker compose exec postgres pg_isready` |
