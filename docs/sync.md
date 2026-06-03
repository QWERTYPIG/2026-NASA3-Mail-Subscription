# Background Sync — Django-Q Worker

所有對 LDAP 的寫入都由 Django-Q worker 非同步處理。系統採用**單一 Flush 排程**（每 30 分鐘），其中包含兩個階段：先處理 task queue，再執行 consistency check。

---

> [!important] HA 環境
> `flush_ldap_tasks()` 會檢查 `FLUSH_ENABLED`，只有 ACTIVE 才會執行 flush。  
> `FLUSH_ENABLED` 由 monitor 寫入 `.env.role`，確保 standby 不會寫 LDAP。

---

## Flush 排程（每 30 分鐘）

將 PostgreSQL `alias_task_queue` 與 `user_task_queue` 中的 task 批次送至 LDAP。

### 執行順序

```
① 取出所有 alias_task_queue 的 tasks
② 依序執行 alias entry 的新增 / 刪除
   └─ add：建立 groupOfUniqueNames entry，以 bind DN 作為 uniqueMember 佔位符
          （確保 groupOfUniqueNames 至少有一個 member；consistency check 會在之後修正）
   └─ delete：刪除 alias entry，並同步清除 user_task_queue 中針對該 alias 的所有 tasks
③ 取出所有 user_task_queue 的 tasks
④ 依序執行 uniqueMember 的 MOD_ADD / MOD_DELETE
```

**`alias_task_queue` 必須先於 `user_task_queue` 執行**，確保 user modify 操作時 alias entry 已存在（或已被刪除）。詳見 [ldap — Alias 刪除時的 Race Condition](./ldap.md#alias-刪除時的-race-condition)。

### Retry 機制

每個 LDAP 操作採用 exponential backoff：

```
嘗試間隔：0.5 → 1 → 2 → 4 → 8 秒，共 6 次嘗試
超過後放棄，task row 留在 queue 不刪除
```

### 冪等處理

部分 LDAP 結果代表**目標狀態已達成**，視為成功並刪除 task，不計入失敗：

| 操作 | 冪等結果 | 說明 |
|------|----------|------|
| alias add | `LDAPEntryAlreadyExistsResult` | alias entry 已存在 |
| user add | `LDAPAttributeOrValueExistsResult` | 成員已在 `uniqueMember` 中 |
| user remove | `LDAPNoSuchAttributeResult` | 成員本來就不在 `uniqueMember` 中 |

### Failed Task 處理

全部 retry 耗盡且非冪等結果後，task row **保留在 queue**（不刪除）。由於 `alias_task_queue` 與 `user_task_queue` 都以 `id` 排序（`ordering = ['id']`），失敗的 task 在下一次 flush 時仍會排在最前面優先處理。

### Redis Lock（防止重疊執行）

`flush_ldap_tasks()` 使用 Redis lock 防止前一次 flush 尚未結束時下一次排程重複執行：

```
FLUSH_LOCK_KEY = "flush_ldap_tasks_lock"
FLUSH_LOCK_TTL = 300 秒
```

若 lock 已被佔用，本次排程直接 return，不執行任何 LDAP 操作。無論執行成功或失敗，`finally` 區塊保證 lock 一定被釋放。

---

## Consistency Check（Flush 結束後執行）

Flush 完成、`user_task_queue` 清空後，立即執行一次 consistency check。

驗證 PostgreSQL `alias.user_id` 與 LDAP `ou=Aliases` 的實際內容是否一致。

```
① Flush 結束，user_task_queue 已清空
② 從 LDAP pull 所有 ou=Aliases 的 uniqueMember 列表
③ 與 PostgreSQL alias.user_id 逐一比對
④ 若有差異，以 LDAP 為準，更新 PostgreSQL
```

> [!note] Consistency check 只修 DB，不修 LDAP
> LDAP 是 source of truth。若發現不一致，永遠是 DB 跟 LDAP 對齊，不反過來。

---

## 錯誤紀錄（Structured Logs）

Django-Q worker 以 `mailsub-worker` logger 寫出 JSON log event，由 container syslog / Alloy / Loki 收集。log event 欄位包含 `level`、`logger`、`event`、`message`，並依事件附加 `alias_name`、`user_uid`、`action`、`failure_count`、`failures`、`error` 等欄位。

| 觸發點 | 條件 | Event |
|--------|------|-------|
| `_connect()` | 無法連上 LDAP server（`LDAPException`）| `ldap_connect_failed` |
| `_with_retry()` | LDAP 操作失敗且準備 retry | `ldap_retry` |
| `flush_alias_tasks()` | alias task 耗盡所有 retry 後仍失敗 | `alias_task_failed`、`alias_flush_failed` |
| `flush_user_tasks()` | user task 耗盡所有 retry 後仍失敗 | `user_task_failed`、`user_flush_failed` |
| `run_consistency_check()` | LDAP search 或 DB 操作失敗 | `consistency_check_failed` |
| `flush_ldap_tasks()` | 停用、lock busy、或其他預期外錯誤 | `flush_disabled`、`flush_lock_busy`、`flush_unexpected_error` |

`flush_alias_tasks` 與 `flush_user_tasks` 會在單次 flush 內彙整失敗項目，並用 `failures` 陣列輸出摘要，避免大量 task 失敗時產生過多重複訊息。

`_connect()` 與 `run_consistency_check()` 在寫出錯誤 log 後會重新拋出例外，讓 `flush_ldap_tasks()` 的錯誤處理正常運作。

---

## 兩個階段的關係

Consistency Check 不是獨立排程，而是每次 Flush 的後半段：

```
Flush（每 3 分鐘）
  └─ 處理 alias_task_queue
  └─ 處理 user_task_queue
  └─ Consistency Check（queue 清空後立即執行）
```

| 階段 | 方向 | 目的 |
|------|------|------|
| Flush | DB → LDAP | 把待處理的變更送出去 |
| Consistency Check | LDAP → DB | 確保 DB cache 與 LDAP 一致 |
