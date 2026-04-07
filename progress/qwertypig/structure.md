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
edit `settings.py`
* import needed libraries
* set cookie permissions 
* configure ldap user search and group search
* mirrors ldap search result to local session database
### Login
* `apps/accounts/apps.py`, add `apps.accounts` to INSTALLED_APPS in `settings.py`
* `apps/accounts/premissions.py`: `has_permission` checks if request has admin previleges (won't be used for now)
* `apps/accounts/views.py`: defines behavior for post and get of login/check session/logout apis
* `apps/accounts/urls.py`: map views to url endpoints
* `core/urls.py`: add `path('api/v1/auth/', include('apps.accounts.urls')),` to map accounts url with desired prefix

### Testing
run docker: `docker compose up -d`
migrate tables written in python to postgresql: `docker compose exec web python manage.py migrate` (only when first setting up database)
close docker: `docker compose down` (add `-v` if wish to destroy databases)

#### Test admin
login:
```bash
curl -i -X POST http://localhost:8000/api/v1/auth/login/ \
     -H "Content-Type: application/json" \
     -d '{"username": "mailtest", "password": "<redacted>"}' \
     -c cookies.txt
```
result:
```
HTTP/1.1 200 OK
Date: Mon, 06 Apr 2026 04:20:24 GMT
Server: WSGIServer/0.2 CPython/3.11.15
Content-Type: application/json
Vary: Accept, Cookie
Allow: POST, OPTIONS
X-Frame-Options: DENY
Content-Length: 39
X-Content-Type-Options: nosniff
Referrer-Policy: same-origin
Cross-Origin-Opener-Policy: same-origin
Set-Cookie:  csrftoken=6gxg72nYMGtlddtHOMGhK4pAgItffjxb; expires=Mon, 05 Apr 2027 04:20:24 GMT; Max-Age=31449600; Path=/; SameSite=Lax
Set-Cookie:  sessionid=e0c94e2x4cgrwfqp6ss0xiqocchqq9lf; expires=Mon, 20 Apr 2026 04:20:24 GMT; HttpOnly; Max-Age=1209600; Path=/; SameSite=Lax

{"username":"mailtest","is_staff":true}
```
check session:
```bash
curl -i -X GET http://localhost:8000/api/v1/auth/me/ \
     -b cookies.txt
```
result:
```
HTTP/1.1 200 OK
Date: Mon, 06 Apr 2026 04:21:08 GMT
Server: WSGIServer/0.2 CPython/3.11.15
Content-Type: application/json
Vary: Accept, Cookie
Allow: GET, HEAD, OPTIONS
X-Frame-Options: DENY
Content-Length: 39
X-Content-Type-Options: nosniff
Referrer-Policy: same-origin
Cross-Origin-Opener-Policy: same-origin

{"username":"mailtest","is_admin":true}
```
logout:
```bash
curl -i -X POST http://localhost:8000/api/v1/auth/logout/ \
     -b cookies.txt \
     -H "X-CSRFToken: <csrf token as in cookies.txt>"
```
result:
```
HTTP/1.1 205 Reset Content
Date: Mon, 06 Apr 2026 04:23:45 GMT
Server: WSGIServer/0.2 CPython/3.11.15
Vary: Accept, Cookie
Allow: POST, OPTIONS
X-Frame-Options: DENY
Content-Length: 0
X-Content-Type-Options: nosniff
Referrer-Policy: same-origin
Cross-Origin-Opener-Policy: same-origin
Set-Cookie:  sessionid=""; expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; Path=/; SameSite=Lax
```
#### Test normal
same as admin, just change username and password (such as both using b13902994)
> search ldap users with `ldapsearch -H ldap://172.16.127.109:389 -D "uid=mailtest,ou=people,dc=csie,dc=ntu,dc=edu,dc=tw" -W   -b "ou=People,dc=csie,dc=ntu,dc=edu,dc=tw" "(objectClass=*)"`

should get `"is_staff": false` and `"is_admin": false`
