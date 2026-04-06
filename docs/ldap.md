# LDAP

系統使用系上 LDAP server 作為唯一的 source of truth。Django 透過 `django-auth-ldap` 進行身份驗證，Django-Q worker 負責所有對 `ou=Aliases` 的寫入操作。

**LDAP URI：** `ldap://172.16.127.109:389`

---

## Directory Structure

```
dc=csie,dc=ntu,dc=edu,dc=tw
├── ou=people          # read-only — 使用者身份
│   └── uid=<username> # objectClass: posixAccount, inetOrgPerson
├── ou=group           # read-only — 群組角色查詢
│   ├── cn=student     # gidNumber: 450
│   └── cn=mailAdmin   # Admin 判定依據（見下方）
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
    ├── gidNumber: <TBD>
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

## LDAP 操作指令格式

### 新增訂閱者（MOD_ADD）

```ldif
dn: cn=ws-user,ou=Aliases,dc=csie,dc=ntu,dc=edu,dc=tw
changetype: modify
add: uniqueMember
uniqueMember: uid=charlie,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw
```

### 移除訂閱者（MOD_DELETE）

```ldif
dn: cn=ws-user,ou=Aliases,dc=csie,dc=ntu,dc=edu,dc=tw
changetype: modify
delete: uniqueMember
uniqueMember: uid=charlie,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw
```

### 新增 Alias Entry（Admin 操作）

```ldif
dn: cn=new-alias,ou=Aliases,dc=csie,dc=ntu,dc=edu,dc=tw
changetype: add
objectClass: groupOfUniqueNames
cn: new-alias
uniqueMember: uid=placeholder,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw
```

> [!note] `groupOfUniqueNames` 要求至少一個 `uniqueMember`
> 新增空 alias 時需放一個 placeholder member，待第一個真實訂閱者加入後再移除。

### 刪除 Alias Entry（Admin 操作）

```ldif
dn: cn=old-alias,ou=Aliases,dc=csie,dc=ntu,dc=edu,dc=tw
changetype: delete
```

---

## Task Queue 優先順序

Flush 排程執行時，**alias task queue 優先於 user task queue**：

1. 先處理所有 alias 層級的操作（新增 / 刪除 alias entry）
2. 再處理所有 user 層級的操作（MOD_ADD / MOD_DELETE uniqueMember）

這樣可以確保 user modify 不會對一個還不存在（或已被刪除）的 alias entry 操作。

詳見 [sync](./docs/sync.md)。
