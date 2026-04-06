# Open Decisions

尚未決定的技術細節。決定後將結論移到對應的 doc，並刪除此處的 entry。

---

| 主題 | 負責人 | 說明 |
|------|--------|------|
| Rate limit 實作方式 | — | Redis TTL（傾向）vs DB timestamp。決定後更新 [auth](./docs/auth.md) 並補充 [database](./docs/database.md) |
| User table | — | 若採用 DB timestamp 方案則需要；schema 待定 |
| Admin 編輯介面 UX | — | 全列出所有學生 vs 搜尋後操作，影響是否需要 `/api/users/search` |