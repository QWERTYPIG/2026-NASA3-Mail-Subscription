# Subscriptions models

## Set up DB

1. Create `apps/subscriptions`

```
.
├── apps
│   ├── accounts
│   │   ├── apps.py
│   │   ├── permissions.py
│   │   ├── urls.py
│   │   └── views.py
│   └── subscriptions
│       ├── apps.py
│       ├── __init__.py
│       └── models.py
...
```
- `models.py` defines the structure of PostgreSQL

2. Apply changes

After creating or modify `models.py`, one must update the database schema using Django's migration system

```bash
# make migration
docker compose exec web python manage.py makemigrations subscriptions
# build DB
docker compose exec web python manage.py migrate
```

3. Testing

> Reference
> - [Writing and running tests | django](https://docs.djangoproject.com/en/6.0/topics/testing/overview/)

- Create `tests.py` under `apps/subscriptions`
- function name should be `test_xxx`
- Run those test cases using
    ```sh
    docker compose exec web python manage.py test apps.subscriptions.tests
    ```
- use `self.assertEqual()` to check

4. Note

- 如果有改 `models.py`，需要 make migration
- 記得在 `git pull` 後執行 `docker compose exec web python manage.py migrate` 以更新 local database。