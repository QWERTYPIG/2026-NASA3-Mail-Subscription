# Monitor Script Test Guide

這份文件是在測試環境驗證 `scripts/monitor/monitor.py` 用。重點驗證：

- monitor `/health` 有回報 worker、DB sync、web、frontend 狀態
- `web` / `frontend` down 時只寫 log 與改 `/health`，不參與 ACTIVE 選舉
- monitor log 是 JSON 格式，能被 Alloy 收進 Loki
- 原本 ACTIVE / STANDBY / failover 行為沒有被破壞

> 注意：不要直接執行任何會修改 LDAP tree 的指令，例如 `ldapadd`、`ldapmodify`、`ldapdelete`。

---

## 0. 測試前確認

在 `mail1`、`mail2`、`mail3` 各自確認：

```bash
sudo systemctl status mailsub-monitor --no-pager
docker compose -f /opt/mailsub/docker-compose.yml ps
```

確認 monitor env 有這些設定：

```bash
sudo grep -E 'THIS_MACHINE_IP|MONITOR_PEERS|COMPOSE_FILE|ENV_ROLE|WEB_PORT|FRONTEND_PORT' /etc/mailsub/monitor.env
```

預期：

- `COMPOSE_FILE=/opt/mailsub/docker-compose.yml`
- `WEB_PORT=8000`
- `FRONTEND_PORT=55111`
- `THIS_MACHINE_IP` 是該台機器自己的 IP
- `MONITOR_PEERS` 包含 `mail1/mail2/mail3`

如果修改過 `/etc/mailsub/monitor.env`：

```bash
sudo systemctl restart mailsub-monitor
```

---

## 1. 檢查 Django web health endpoint

在每台 `mail1`、`mail2`、`mail3` 上測：

```bash
curl -s http://127.0.0.1:8000/api/v1/health/
```

預期：

```json
{"status":"ok"}
```

如果失敗，先看 web container：

```bash
docker compose -f /opt/mailsub/docker-compose.yml ps web
docker compose -f /opt/mailsub/docker-compose.yml logs --tail=100 web
```

---

## 2. 檢查 monitor /health

在每台機器本機測：

```bash
curl -s http://127.0.0.1:9123/health
```

預期至少包含這些欄位：

```json
{
  "worker_running": true,
  "db_sync_ready": true,
  "web_running": true,
  "web_api_ok": true,
  "frontend_running": true,
  "frontend_http_ok": true
}
```

從別台機器測 peer monitor：

```bash
curl -s http://172.16.127.102:9123/health
curl -s http://172.16.127.116:9123/health
curl -s http://172.16.127.117:9123/health
```

如果 `web_running=true` 但 `web_api_ok=false`，代表 container 還在，但 Django HTTP endpoint 不健康。

如果 `frontend_running=true` 但 `frontend_http_ok=false`，代表 container 還在，但 Vite frontend HTTP 不健康。

---

## 3. 檢查 structured systemd log

在任一台 mail server：

```bash
sudo journalctl -u mailsub-monitor -n 50 --no-pager
```

預期 message 是 JSON 字串，例如：

```json
{"event":"monitor_loop_starting","level":"INFO","logger":"mailsub-monitor","message":"monitor loop starting","peers":["172.16.127.102","172.16.127.116","172.16.127.117"]}
```

確認沒有舊格式 plain text，例如：

```text
ACTIVE transition 172.16.127.116 -> 172.16.127.102
```

現在應該長得像：

```json
{"event":"active_transition","level":"INFO","logger":"mailsub-monitor","message":"ACTIVE transition","new_active":"172.16.127.102","old_active":"172.16.127.116"}
```

---

## 4. 模擬 web down

在測試環境選一台，例如 `mail1`。

停掉 web：

```bash
docker compose -f /opt/mailsub/docker-compose.yml stop web
```

因為 `docker-compose.yml` 有 `restart: always`，Docker 可能會嘗試重啟。若它立刻恢復，這仍可視為 restart policy 生效；若需要觀察 down 狀態，可以連續查幾次：

```bash
watch -n 1 'curl -s http://127.0.0.1:9123/health'
```

預期 down 時 `/health` 會出現：

```json
{
  "web_running": false,
  "web_api_ok": false
}
```

查看 monitor log：

```bash
sudo journalctl -u mailsub-monitor -n 100 --no-pager | grep serving_health_down
```

預期看到類似：

```json
{"check":"web_running","event":"serving_health_down","level":"WARNING","logger":"mailsub-monitor","message":"web compose service is not running","service":"web","target":"web"}
```

恢復 web：

```bash
docker compose -f /opt/mailsub/docker-compose.yml up -d web
```

預期 `/health` 回到：

```json
{
  "web_running": true,
  "web_api_ok": true
}
```

查看 recovered log：

```bash
sudo journalctl -u mailsub-monitor -n 100 --no-pager | grep serving_health_recovered
```

預期看到 `service="web"`、`check="web_running"` 或 `check="web_api_ok"` 的 recovery event。

---

## 5. 模擬 frontend down

停掉 frontend：

```bash
docker compose -f /opt/mailsub/docker-compose.yml stop frontend
```

查看 monitor health：

```bash
curl -s http://127.0.0.1:9123/health
```

預期 down 時：

```json
{
  "frontend_running": false,
  "frontend_http_ok": false
}
```

查看 log：

```bash
sudo journalctl -u mailsub-monitor -n 100 --no-pager | grep serving_health_down
```

預期看到：

```json
{"check":"frontend_running","event":"serving_health_down","level":"WARNING","logger":"mailsub-monitor","message":"frontend compose service is not running","service":"frontend","target":"frontend"}
```

恢復 frontend：

```bash
docker compose -f /opt/mailsub/docker-compose.yml up -d frontend
```

確認恢復：

```bash
curl -s http://127.0.0.1:9123/health
sudo journalctl -u mailsub-monitor -n 100 --no-pager | grep serving_health_recovered
```

---

## 6. 確認 web/frontend 不影響 ACTIVE 選舉

先找目前 ACTIVE：

```bash
cat /opt/mailsub/.env.role
```

ACTIVE 機器會有：

```text
FLUSH_ENABLED=1
DB_HOST=<自己的 IP>
```

在 ACTIVE 機器上停 frontend：

```bash
docker compose -f /opt/mailsub/docker-compose.yml stop frontend
```

等待至少一個 monitor interval：

```bash
sleep 20
```

再次確認：

```bash
cat /opt/mailsub/.env.role
```

預期：

- `FLUSH_ENABLED` 不因 frontend down 改變
- `DB_HOST` 不因 frontend down 改變
- 不應出現 ACTIVE transition 到其他機器

查 log：

```bash
sudo journalctl -u mailsub-monitor -n 200 --no-pager | grep active_transition
```

預期沒有因 frontend/web down 而產生新的 `active_transition`。

恢復 frontend：

```bash
docker compose -f /opt/mailsub/docker-compose.yml up -d frontend
```

同樣也可以對 `web` 做一次，但請注意停 `web` 會影響使用者 API；測試環境才做。

---

## 7. Loki / Grafana 查詢

前提：Alloy 已安裝在 `mail1`、`mail2`、`mail3`，且有收 `mailsub-monitor.service` 的 systemd journal。

在 Grafana Explore 選 Loki。

查所有 monitor logs：

```logql
{unit="mailsub-monitor.service"}
```

查 web/frontend down：

```logql
{unit="mailsub-monitor.service"} |= "serving_health_down"
```

只查 web down：

```logql
{unit="mailsub-monitor.service"} |= "\"service\":\"web\"" |= "serving_health_down"
```

只查 frontend down：

```logql
{unit="mailsub-monitor.service"} |= "\"service\":\"frontend\"" |= "serving_health_down"
```

查 recovered：

```logql
{unit="mailsub-monitor.service"} |= "serving_health_recovered"
```

如果查不到：

```bash
sudo systemctl status alloy --no-pager
sudo journalctl -u alloy -n 100 --no-pager
```

確認 Alloy 有在該 mail server 上執行，而不是只在 Proxmox node 上執行。

---

## 8. Grafana alert 建議

最簡單的 alert rule：

```logql
count_over_time({unit="mailsub-monitor.service"} |= "serving_health_down" [5m]) > 0
```

意思是：最近 5 分鐘只要有任何 serving health down event，就告警。

web-only：

```logql
count_over_time({unit="mailsub-monitor.service"} |= "\"service\":\"web\"" |= "serving_health_down" [5m]) > 0
```

frontend-only：

```logql
count_over_time({unit="mailsub-monitor.service"} |= "\"service\":\"frontend\"" |= "serving_health_down" [5m]) > 0
```

如果你不想短暫 restart 也告警，可以把 window 拉長，或改成 Prometheus/blackbox 連續多次失敗再告警。

---

## 9. 原本 HA 行為 smoke test

這段確認這次 serving health 改動沒有破壞 ACTIVE 選舉。

在三台機器查：

```bash
cat /opt/mailsub/.env.role
```

預期只有一台：

```text
FLUSH_ENABLED=1
```

其他兩台：

```text
FLUSH_ENABLED=0
```

查看 monitor `/health`：

```bash
curl -s http://127.0.0.1:9123/health
```

只要 core 欄位健康，該機器仍可被選為 ACTIVE：

```json
{
  "worker_running": true,
  "db_sync_ready": true
}
```

`web_*` / `frontend_*` 欄位只用於觀測與 log，不應影響 `.env.role`。

---

## Quick Checklist

| Test | Expected |
|---|---|
| Django health | `/api/v1/health/` returns `{"status":"ok"}` |
| Monitor health | `/health` includes worker, db sync, web, frontend fields |
| web down | `/health.web_* = false`, `serving_health_down` log appears |
| web recovered | `/health.web_* = true`, `serving_health_recovered` log appears |
| frontend down | `/health.frontend_* = false`, `serving_health_down` log appears |
| frontend recovered | `/health.frontend_* = true`, `serving_health_recovered` log appears |
| ACTIVE election | No role switch caused only by web/frontend down |
| Loki | Grafana can query `serving_health_down` from `mailsub-monitor.service` |
