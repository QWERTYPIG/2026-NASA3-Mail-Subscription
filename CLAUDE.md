# CLAUDE.md

## Project

系上 mail alias 訂閱管理系統。使用者可訂閱或退訂各個 mail alias；Admin 可管理成員與 alias。

## Docs

所有架構與技術決策文件在 `docs/`，從 [docs/architecture.md](./docs/architecture.md) 開始閱讀。

## Constraints

- LDAP 是唯一的 source of truth，不得直接修改 LDAP——所有寫入都透過 task queue 由 Django-Q worker 非同步執行
- `ou=Aliases` 的寫入者只有 Django-Q worker，Django API 不直接寫入

## Open Decisions

遇到 [docs/open-decisions.md](./docs/open-decisions.md) 中列出的主題，請留下 `# TODO(decision): ...` 註解，不要自行選擇方案。
