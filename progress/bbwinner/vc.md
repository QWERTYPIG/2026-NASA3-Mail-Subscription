## 5/25

### Stage 1-A

#### Step 1

```sh
git log --all --full-history --name-only --pretty=format: -- '.env' '.env.*' \
  | grep -v '^\s*$' \
  | grep -v '.env.example' \
  | grep -v '.env.role.example'
```
- Result: `.env` 未存在在 git history

#### Step 2
```sh
sudo docker run --rm \
  -v "$PWD:/repo" \
  zricethezav/gitleaks:latest \
  detect --source=/repo --no-banner --redact
```
```
6:23AM INF 156 commits scanned.
6:23AM INF scanned ~534060 bytes (534.06 KB) in 161ms
6:23AM INF no leaks found
```

#### Step 3

發現 `core/settings.py` 有 hardcoded 的 `SECRET_KEY`，已修正為從環境變數讀取

- `core/settings.py`：`DB_PASSWORD` 移除預設值（避免落回 `secret`）

```sh
sudo docker compose exec -T web env DJANGO_SETTINGS_MODULE=core.settings python - <<'PY'
from django.conf import settings
print("SECRET_KEY set:", bool(settings.SECRET_KEY))
PY
```

Result
```sh
SECRET_KEY set: True
```

後續動作：
- 需在三台機器的 `.env` 設定相同的 `SECRET_KEY` (`openssl rand -base64 48`)
- 更新 `.env` 後重啟 web/worker 使設定生效（例：`docker compose up -d --force-recreate web worker`）

備註：
- `DB_PASSWORD` 若未設定會變成空字串，DB 連線會失敗（安全失敗，避免默默使用弱預設值）
