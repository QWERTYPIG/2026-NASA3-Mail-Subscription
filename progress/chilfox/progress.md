# 進度紀錄

> 最後更新：2026-04-15

---

## 已完成

### 後端架構與設定

- [x] Django 專案初始化（`core/`）
- [x] Docker Compose 四服務架構（postgres、redis、web、worker）
- [x] 環境變數設定（DB、Redis、LDAP）
- [x] PostgreSQL + Redis 整合進 Django settings
- [x] django-auth-ldap 設定（user search、group mapping → `is_staff`）
- [x] Django-Q worker 設定（4 workers、Redis index 0 作為 broker）
- [x] CORS headers 設定

### 資料模型（`apps/subscriptions/models.py`）

- [x] `Alias`：alias_name（PK）、display_name、description、user_id（ArrayField）
  - RegexValidator 防止 LDAP injection（只允許 `[a-zA-Z0-9-]+`）
- [x] `AliasTaskQueue`：alias_name、action（add/remove），依 id 排序
- [x] `UserTaskQueue`：alias_name、user_uid、action（add/remove），依 id 排序
- [x] Migrations
  - `0001_initial`：初始 schema
  - `0002_add_flush_ldap_schedule`：加入 Django-Q 排程（每 3 分鐘執行 `flush_ldap_tasks`）

### 認證系統（`apps/accounts/`）

- [x] `LoginView`（POST `/api/v1/auth/login/`）：LDAP bind → 建立 session → 回傳 username + is_staff
- [x] `CheckSessionView`（GET `/api/v1/auth/me/`）：回傳目前登入狀態
- [x] `LogoutView`（POST `/api/v1/auth/logout/`）：清除 session
- [x] `IsAdminUser` permission class

### 訂閱 API（`apps/subscriptions/views.py`、`serializers.py`）

- [x] `AdminAliasListView`（GET `/api/v1/admin/aliases/`）：Admin 專用，列出所有 alias（不含 `is_subscribed`）
- [x] `UserSubscriptionListView`（GET `/api/v1/user/subscriptions/`）：列出所有 alias 並標示目前使用者是否訂閱
- [x] `UserSubscriptionListView`（PUT `/api/v1/user/subscriptions/`）：批次更新訂閱狀態
  - 接受完整 alias→boolean map
  - 驗證：必須包含所有 alias、只允許 boolean 值、不得有未知 alias
  - 將差異寫入 `UserTaskQueue`
  - 更新 PostgreSQL cache（`transaction.atomic()`）
  - 回傳 202 Accepted
- [x] `UserSubscriptionCooldownThrottle`：Redis-based，每個使用者 10 分鐘 cooldown（PUT 用）

### LDAP 同步（`apps/subscriptions/tasks.py`）

- [x] `flush_alias_tasks()`：依序處理 `AliasTaskQueue`
  - add：在 LDAP 建立 `groupOfUniqueNames`（含 bind DN placeholder）
  - remove：刪除 LDAP entry + 清除對應的 `UserTaskQueue`（race condition 防護）
- [x] `flush_user_tasks()`：依序處理 `UserTaskQueue`
  - MODIFY_ADD / MODIFY_DELETE `uniqueMember`
- [x] `run_consistency_check()`：從 LDAP 拉取所有 alias，同步進 PostgreSQL（以 LDAP 為 source of truth）
- [x] `flush_ldap_tasks()`：主入口點
  - Redis lock（TTL 300s）防止重疊執行
  - 依序執行：alias tasks → user tasks → consistency check
- [x] `_with_retry()`：指數退避重試（最多 5 次：0.5→1→2→4→8 秒）

### 測試（`apps/subscriptions/tests.py`，313 行）

- [x] `SubscriptionModelsTest`：model 建立與 validator 測試
- [x] `FlushAliasTasksTest`：LDAP add/remove、dangling task 清除、失敗留在 queue
- [x] `ConsistencyCheckTest`：DB 從 LDAP 同步、過濾 bind DN placeholder
- [x] `FlushLdapTasksTest`：Redis lock 機制
- [x] `AliasListApiTest`：permission 檢查、response 格式
- [x] `UserSubscriptionUpdateSerializerTest`：輸入驗證
- [x] `UserSubscriptionUpdateApiTest`：認證、202、400、429 回應

### 文件（`docs/`）

- [x] `architecture.md`：整體架構與技術選型
- [x] `api.md`：API endpoint 規格
- [x] `auth.md`：認證流程與 RBAC
- [x] `database.md`：PostgreSQL schema
- [x] `ldap.md`：LDAP 目錄結構與讀寫規則
- [x] `sync.md`：背景 worker 同步邏輯
- [x] `setup.md`：環境設定與 Docker 指令
- [x] `testing.md`：測試執行方式
- [x] `open-decisions.md`：待決定事項清單

---

## 尚未完成 / 待決定

### Open Decisions（參見 `docs/open-decisions.md`）

- [ ] **Admin 編輯 UX**：顯示所有學生 vs. 搜尋後操作
  - 影響是否需要 `/api/users/search` endpoint
- [ ] **訂閱更新回應狀態碼**：200 OK vs. 202 Accepted（非同步操作語意）
  - 目前實作回傳 202，尚未在文件上定案
- [ ] **Admin 訂閱列表 schema**：與使用者格式統一（去掉 `is_subscribed`）或獨立 endpoint

### 功能缺口

- [ ] Admin 管理 alias 的寫入 API（新增/刪除 alias）
  - 目前 `AliasTaskQueue` 已有對應 model，但沒有 API endpoint
- [ ] Admin 管理 alias 成員的 API（修改特定 alias 的成員名單）
- [ ] 使用者搜尋 API（視 Admin UX 決定是否需要）
- [ ] 前端 React app（本 repo 為純後端）

### 技術債 / 待確認

- [ ] `settings.py` 中 group search 使用的 DC 路徑（`dc=nasa,dc=csie,...`）與 `ldap.md` 文件（`dc=csie,...`）不一致，需確認正確值
- [ ] `DEBUG = True`、`SESSION_COOKIE_SECURE = False`——需在正式部署前改為 production 設定
- [ ] `Dockerfile` 使用 Python 3.11，但 `pyproject.toml` 要求 Python ≥3.12，需對齊
- [ ] `accounts/tests.py` 尚未建立（文件提到但 repo 中不存在）
- [ ] `flush_user_tasks` 失敗時的錯誤處理——目前 retry 機制在 alias tasks 有完整測試，user tasks 的測試較少
