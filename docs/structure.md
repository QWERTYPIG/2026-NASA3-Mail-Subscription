# Basic Structure Documentation
## Docker
### Dockerfile
install needed packages (in requirements.txt)
install dependencies for ldap and postgresql
### docker-compose.yml
set default values for environmental variables
* DB_NAME = Subscriptions
* DB_USER = MailAdmin
* DB_PASSWORD = password
* REDIS_QUEUE_URL=redis://redis:6379/0
* REDIS_CACHE_URL=redis://redis:6379/1
* LDAP_URI = ldap://172.16.127.109:389
separate task queue cache and user modification cache to avoid accidental deletions
configure docker web to be `10.5.0.0` to avoid default collision with `172.16.0.0`
### Django setup
use `docker compose run --rm --user "$(id -u):$(id -g)" web django-admin startproject core .` to initialize django
generates:
* manage.py
* core
    - \_\_init\_\_.py
    - asgi.py
    - settings.py
    - urls.py
    - wsgi.py

edit `settings.py`
> modifications are tagged with comments, though may be a bit ambiguous since the auto-generated script also has comments

* `import os`: enable reading of environmental variables
* add REST and Django-Q to installed apps
* change default database to postgresql
* set cache to redis (index 1)
* configure Django-Q (uses redis index 0)
### Authorization
