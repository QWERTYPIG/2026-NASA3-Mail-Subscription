# Setup

---

## 環境變數

在 `docker-compose.yml` 中設定，以下為預設值：

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `DB_NAME` | `Subscriptions` | PostgreSQL 資料庫名稱 |
| `DB_USER` | `MailAdmin` | PostgreSQL 使用者 |
| `DB_PASSWORD` | `password` | PostgreSQL 密碼 |
| `REDIS_QUEUE_URL` | `redis://redis:6379/0` | Django-Q task queue |
| `REDIS_CACHE_URL` | `redis://redis:6379/1` | Rate limit TTL cache |
| `LDAP_URI` | `ldap://172.16.127.109:389` | LDAP server |
| `SMTP_HOST` | `localhost` | Alert email 用的 SMTP server |
| `SMTP_PORT` | `25` | SMTP port（Mailpit 用 `1025`）|
| `ALERT_EMAIL_SENDER` | `mailsub-alert@csie.ntu.edu.tw` | Alert email 寄件人 |

> [!warning] Redis index 分開
> index 0（queue）與 index 1（cache）刻意分開，避免 task queue 的 key 被 cache 操作誤刪。

---

## Docker 網路設定

Docker 網段設定為 `10.5.0.0`，避免與系上網段 `172.16.0.0` 衝突。

---

## 常用指令

```bash
# 啟動服務
docker compose up -d

# 初次建置：migrate DB schema（第一次跑或 model 有改動時）
docker compose exec web python manage.py migrate

# 關閉服務
docker compose down

# 關閉並清除資料庫 volume
docker compose down -v
```

---

## 初始化 Django 專案（僅需做一次）

```bash
docker compose run --rm --user "$(id -u):$(id -g)" web django-admin startproject core .
```

產生的結構：
```
manage.py
core/
├── __init__.py
├── asgi.py
├── settings.py
├── urls.py
└── wsgi.py
```

---

## App 結構

```
apps/
└── accounts/
    ├── apps.py         # AppConfig，需加入 settings.py INSTALLED_APPS
    ├── permissions.py  # has_permission：檢查 admin 權限
    ├── views.py        # login / me / logout 行為
    └── urls.py         # endpoint 對應
core/
└── urls.py             # 掛載 api/v1/auth/ prefix
```

API endpoint 細節見 [api](./docs/api.md)。