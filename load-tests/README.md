# Load Tests — mailsus.csie.org

k6 壓力測試腳本。目標：驗證三台 nginx round-robin 分配、找出各端點瓶頸、確認 rate limiting 正確運作。

## 環境

```bash
brew install k6   # macOS
# or
docker pull grafana/k6
```

## 前置步驟

### 1. nginx 加識別 header（三台各自操作）

```nginx
# /etc/nginx/conf.d/mailsus.conf — mail1 上：
add_header X-Served-By "mail1" always;
```

改完 `nginx -s reload`。**測試完記得移除。**

### 2. 建測試帳號（由使用者執行 ldapadd）

在 `ou=People` 下建 `testuser01`–`testuser30`，均加入 `ou=Students` group。

### 3. 準備 USERS env var

```bash
export USERS='[
  {"username":"testuser01","password":"..."},
  {"username":"testuser02","password":"..."}
]'
```

## 執行順序

```bash
mkdir -p results

# 1. Health baseline（不需 USERS）
k6 run --out json=results/health.json load-tests/01-health.js

# 2. Login stress（LDAP 瓶頸）
k6 run --out json=results/login.json load-tests/02-login.js
# 完成後清 session table：
# docker exec <db> psql -U <user> -d <db> -c "DELETE FROM django_session;"

# 3. 已認證讀取
k6 run --out json=results/read.json load-tests/03-read.js

# 4. Rate limiting 驗證（所有 check 必須 100% pass）
k6 run load-tests/04-rate-limit.js
# 完成後清 Redis TTL key：
# redis-cli -n 1 KEYS "user_subscription_cooldown:*" | xargs redis-cli -n 1 DEL

# 5. 混合負載（最接近真實，5 分鐘）
k6 run --out json=results/mixed.json load-tests/05-mixed.js
```

## 關鍵指標

| 指標 | 目標 |
|------|------|
| `http_req_failed` | < 0.1% |
| `http_req_duration p95` | < 500ms |
| `http_req_duration p99` | < 1000ms |
| `node_hits_mail{1,2,3}` | 各約 33% ± 5% |

## 結果分析

```bash
# 三台節點分配
cat results/mixed.json | jq '
  [.[] | select(.type=="Point" and .metric | startswith("node_hits"))]
  | group_by(.metric)
  | map({ node: .[0].metric, hits: (map(.data.value) | add) })
'

# p95 latency 摘要
k6 run --summary-export=results/summary.json load-tests/05-mixed.js
cat results/summary.json | jq '.metrics.http_req_duration'
```
