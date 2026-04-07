# Open Decisions

尚未決定的技術細節。決定後將結論移到對應的 doc，並刪除此處的 entry。

---

| 主題 | 負責人 | 說明 |
|------|--------|------|
| Admin 編輯介面 UX | — | 全列出所有學生 vs 搜尋後操作，影響是否需要 `/api/users/search` |
| Subscriptions 更新 API 回應碼 | — | `POST /api/v1/subscriptions/update/` 應回 `200 OK` 或 `202 Accepted`（目前流程為非同步 enqueue + worker flush） |
| Admin 取得 subscriptions 的 response schema | — | `GET /api/v1/subscriptions/` 對 admin 應回傳與 user 同 schema（僅移除 `is_subscribed`）或使用不同 endpoint/schema |