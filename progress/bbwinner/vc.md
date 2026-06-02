# Vulnerability Check

---

## Stage 1

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

### Stage 1-B
 
目的：確認 Python/JS 依賴套件沒有已知 CVE。

#### Frontend（npm）

```
cd frontend
npm audit --package-lock-only --omit=dev
npm audit fix
```

`node_modules`: should be added in .gitignore
> [!Note]
> 更改 `package-lock.json` and `package.json` 要 rebuild
> `docker compose up -d --build`

#### Backend

```
No known vulnerabilities found
```

#### Python 靜態分析（Bandit）


```bash
docker compose run --rm web bash -c "pip install bandit && bandit -r apps/ -ll"
```

```
WARNING: Running pip as the 'root' user can result in broken permissions and conflicting behaviour with the system package manager, possibly rendering your system unusable. It is recommended to use a virtual environment instead: https://pip.pypa.io/warnings/venv. Use the --root-user-action option if you know what you are doing and want to suppress this warning.
[main]	INFO	profile include tests: None
[main]	INFO	profile exclude tests: None
[main]	INFO	cli include tests: None
[main]	INFO	cli exclude tests: None
[main]	INFO	running on Python 3.11.15
Run started:2026-05-30 01:29:55.949535+00:00

Test results:
	No issues identified.

Code scanned:
	Total lines of code: 1409
	Total lines skipped (#nosec): 0

Run metrics:
	Total issues (by severity):
		Undefined: 0
		Low: 14
		Medium: 0
		High: 0
	Total issues (by confidence):
		Undefined: 0
		Low: 0
		Medium: 14
		High: 0
Files skipped (0):
```

#### Django 部署安全設定

```
WARNINGS:
?: (security.W004) You have not set a value for the SECURE_HSTS_SECONDS setting. If your entire site is served only over SSL, you may want to consider setting a value and enabling HTTP Strict Transport Security. Be sure to read the documentation first; enabling HSTS carelessly can cause serious, irreversible problems.
?: (security.W008) Your SECURE_SSL_REDIRECT setting is not set to True. Unless your site should be available over both SSL and non-SSL connections, you may want to either set this setting True or configure a load balancer or reverse-proxy server to redirect all connections to HTTPS.
?: (security.W012) SESSION_COOKIE_SECURE is not set to True. Using a secure-only session cookie makes it more difficult for network traffic sniffers to hijack user sessions.
?: (security.W016) You have 'django.middleware.csrf.CsrfViewMiddleware' in your MIDDLEWARE, but you have not set CSRF_COOKIE_SECURE to True. Using a secure-only CSRF cookie makes it more difficult for network traffic sniffers to steal the CSRF token.
?: (security.W018) You should not have DEBUG set to True in deployment.
```

### CI（GitHub Actions）

#### Gitleaks

- 觸發：`push`、`pull_request`
- 內容：掃描 git history 是否有 secrets（API key / password / private key）
- 檔案：`.github/workflows/gitleaks.yml`

#### Dependency CVE Check

- 觸發：`pull_request`
- 內容：
	- `pip-audit` 掃 `requirements.txt`
	- `npm audit --package-lock-only --omit=dev --audit-level=high` 掃 frontend production dependencies
- 檔案：`.github/workflows/dep-cve.yml`

#### Bandit SAST

- 觸發：`pull_request`
- 內容：`bandit -r apps/ -ll` 掃 Python code（只顯示 medium 以上）
- 檔案：`.github/workflows/bandit.yml`

---

## Stage 2

