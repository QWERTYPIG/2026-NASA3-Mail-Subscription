# Open Decisions

尚未決定的技術細節。決定後將結論移到對應的 doc，並刪除此處的 entry。

---

| 主題 | 負責人 | 說明 |
|------|--------|------|
| Frontend production serving：vite dev server → static build |  | production 跑 `vite dev` 使 image 內含 node/npm，Trivy 報 11 HIGH（base-image npm）。根本解＝改 multi-stage 靜態 build。詳見 [§ Frontend production serving](#frontend-production-serving)。 |

---

## Frontend production serving

**What**：production 直接跑 `vite dev`，整個 node/npm toolchain 留在 runtime image → Trivy 報 11 HIGH，全在 base image `node:20-alpine` 內附的 npm（`/usr/local/lib/node_modules/npm/...`），非專案依賴，build-time only、runtime 打不到（VC 暫 Accept）。

**Solution**：`frontend/Dockerfile` 改 multi-stage（node build → `nginx:alpine` 服務 `dist/`），最終 image 無 node/npm，11 個全消。frontend container 只在 mail1-3，候選做法是容器內 nginx 仍 listen `55111` 並自行 proxy `/api → web:8000`，則 mail4 RR 設定不動、只需 rebuild mail1-3。

**待決**：
- (a) `/api` proxy 落在容器內 nginx 還是 mail4。
- (b) `VITE_*` API base URL 改 build-arg 或前端走相對路徑 `/api`。
- (c) cookie/CSRF 行為需與現有 vite proxy 對齊。
- (d) HMR 靜態模式取消。

決定前 frontend image CVE 維持 Accept。
