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

## Consistency Check 排程（每 5 分鐘，獨立排程）

驗證 PostgreSQL `alias.user_id` 與 LDAP `ou=Aliases` 的實際內容是否一致。

**執行前提：`user_task_queue` 為空。** 若 queue 中仍有 pending task，跳過本次 check，等下一輪。這樣可避免 consistency check 把「已寫入 DB、尚未 flush 至 LDAP」的訂閱狀態還原。

```
① 確認 user_task_queue 為空，否則跳過
② 從 LDAP pull 所有 ou=Aliases 的 uniqueMember 列表
③ 與 PostgreSQL alias.user_id 逐一比對
④ 若有差異，以 LDAP 為準，更新 PostgreSQL
```

> [!note] Consistency check 只修 DB，不修 LDAP
> LDAP 是 source of truth。若發現不一致，永遠是 DB 跟 LDAP 對齊，不反過來。

---

## 兩個排程的關係

| 排程 | 間隔 | 方向 | 目的 |
|------|------|------|------|
| Flush | 3 分鐘 | DB → LDAP | 把待處理的變更送出去 |
| Consistency Check | 5 分鐘 | LDAP → DB | 確保 DB cache 是正確的 |

兩者獨立執行，不互相等待。
