# LDAP

系統使用系上 LDAP server 作為唯一的 source of truth。Django 透過 `django-auth-ldap` 進行身份驗證，Django-Q worker 負責所有對 `ou=Aliases` 的寫入操作。

**LDAP URI：** `ldap://172.16.127.109:389`

> [!note] LDAP 是外部伺服器
> LDAP server 由系上 identity service 組維護，不在 docker-compose 管理範圍內。`ou=group` 的新增／修改（如 `cn=mailAdmin` 成員管理）需聯繫 identity service 組，或由有 LDAP admin 權限的人員直接操作。

**Bind DN（mail 組使用帳號）：** `uid=mailtest,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw`

> [!note]
> 這個帳號不是 LDAP admin（`cn=admin,...`），而是系上為 mail 組開立的服務帳號，擁有完整的 LDAP 操作權限，可直接執行 `ldapadd` / `ldapmodify` 等管理操作。

---

## Directory Structure

```
dc=csie,dc=ntu,dc=edu,dc=tw
├── ou=people          # read-only — 使用者身份
│   └── uid=<username> # objectClass: posixAccount, inetOrgPerson
├── ou=group           # read-only — 群組角色查詢
│   ├── cn=student     # gidNumber: 450
│   └── cn=mailAdmin   # Admin 判定依據（見下方），gidNumber: 62100
└── ou=Aliases         # writable — 僅 Django-Q worker 可寫
    ├── cn=ws-user     # objectClass: groupOfUniqueNames
    └── cn=meow-user
```

---

## 讀寫權限

| OU | Django（API）| Django-Q（worker）|
|----|-------------|-------------------|
| `ou=people` | 唯讀（身份驗證）| 不存取 |
| `ou=group` | 唯讀（admin 判定）| 不存取 |
| `ou=Aliases` | 唯讀（consistency check 來源）| **可寫** |

> [!warning] `ou=Aliases` 的寫入者只有 Django-Q worker
> Django API 本身不直接寫入 LDAP。所有訂閱變更都先寫入 PostgreSQL task queue，由 worker 非同步處理。

---

## Admin 群組判定

使用者登入時，`django-auth-ldap` 查詢 `ou=group,cn=mailAdmin`，確認該使用者是否為其成員。

```
ou=group
└── cn=mailAdmin
    ├── objectClass: posixGroup
    ├── gidNumber: 62100
    └── memberUid: alice
        memberUid: bob
```

若使用者的 `uid` 出現在 `cn=mailAdmin` 的 `memberUid` 中，Django 標記 `is_admin=True`。

---

## `ou=Aliases` Entry 格式

每個 alias 是一個 `groupOfUniqueNames` entry：

```ldif
dn: cn=ws-user,ou=Aliases,dc=csie,dc=ntu,dc=edu,dc=tw
objectClass: groupOfUniqueNames
cn: ws-user
uniqueMember: uid=b13902992,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw
uniqueMember: uid=r13922003,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw
```

- `cn`：alias 的唯一識別碼，對應 PostgreSQL `alias.alias_name`。
- `uniqueMember`：訂閱者的完整 DN（`uid=<username>,ou=people,...`）。

---

## Task Queue 優先順序

Flush 排程執行時，**alias task queue 優先於 user task queue**：

1. 先處理所有 alias 層級的操作（新增 / 刪除 alias entry）
2. 再處理所有 user 層級的操作（MOD_ADD / MOD_DELETE uniqueMember）

詳見 [sync](./docs/sync.md)。

---

## Alias 刪除時的 Race Condition

### 問題

Alias task 先執行、user task 後執行，但如果中間某個 alias 被刪除，後續針對該 alias 的 user task 就會對不存在的 entry 操作（LDAP 回傳 no such object）。

有兩個需要處理的視窗：

1. **Flush 內部**：同一輪 flush 中，alias delete 執行完後，queue 裡還有針對該 alias 的 pending user task。
2. **Enqueue 時**：Admin 提交 alias 刪除後（alias delete task 進 queue，但尚未 flush），user 仍可送出針對該 alias 的訂閱變更。

### 解法

**兩個機制合用：**

#### 1. Flush 後清理（保證正確性）

Worker 每次成功執行 alias delete 後，立即刪除同一 alias 的所有 pending user task：

```python
UserTaskQueue.objects.filter(alias_name=alias_name).delete()
```

這是正確性的保證。無論 user task 何時被 enqueue，只要 alias 被刪除，相關 task 就會被清掉。

#### 2. Enqueue 前確認 alias 存在（Fail-fast 優化）

User 送出訂閱變更時，API 層先確認 `alias` 仍存在於 DB，不存在就直接拒絕，不進 task queue。

這不是正確性的必要條件（方法 1 已保證），但可以避免明顯無效的 task 進入 queue。

> [!note]
> 視窗 2（alias delete task pending、但 user task 已 enqueue）由方法 1 處理：下次 flush 執行 alias delete 時，會一併清除這些 user task。不需要 soft-delete 旗標。
