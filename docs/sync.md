# Background Sync — Django-Q Worker

所有對 LDAP 的寫入都由 Django-Q worker 非同步處理。有兩個獨立排程：**Flush**（處理 task queue）和 **Consistency Check**（驗證 DB 與 LDAP 一致）。

---

## Flush 排程（每 3 分鐘）

將 PostgreSQL `task_queue` 中的 task 批次送至 LDAP。

### 執行順序

```
① 取出所有 alias_task_queue 的 tasks
② 依序執行 alias entry 的新增 / 刪除
   └─ 每次 alias delete 完成後，刪除 user_task_queue 中針對該 alias 的所有 tasks
③ 取出所有 user_task_queue 的 tasks
④ 依序執行 uniqueMember 的 MOD_ADD / MOD_DELETE
```

**`alias_task_queue` 必須先於 `user_task_queue` 執行**，確保 user modify 操作時 alias entry 已存在（或已被刪除）。詳見 [ldap — Alias 刪除時的 Race Condition](./ldap.md#alias-刪除時的-race-condition)。

### Retry 機制

每個 LDAP 操作採用 exponential backoff：

```
嘗試間隔：0.5 → 1 → 2 → 4 → 8 秒
超過後放棄，task.status = 'failed'
```

### Failed Task 處理

`failed` task 會在**下一次 flush 排程時排在第一個**優先處理，不會被遺棄。

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
