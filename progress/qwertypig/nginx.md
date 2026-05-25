# Nginx Setup Documentation
## Install
`sudo apt update`
`sudo apt install nginx`
## Config
`cd /etc/nginx/conf.d`
`sudo vim mailsus.conf`
```
# 1. Frontend Pool (React/Vite on port 55111)
upstream mail_frontend {
    ip_hash;
    server 172.16.127.102:55111 max_fails=3 fail_timeout=30s;
    server 172.16.127.116:55111 max_fails=3 fail_timeout=30s;
    server 172.16.127.117:55111 max_fails=3 fail_timeout=30s;
}

# 2. Backend Pool (Django on port 8000)
upstream mail_backend {
    server 172.16.127.102:8000 max_fails=3 fail_timeout=30s;
    server 172.16.127.116:8000 max_fails=3 fail_timeout=30s;
    server 172.16.127.117:8000 max_fails=3 fail_timeout=30s;
}

server {
    listen 80;
    server_name mailsus.csie.org;

    # --- ROUTE 1: Django API & Admin ---
    # Intercepts any request starting with /api/ or /admin/ and sends it to Python
    location ~ ^/(api|admin)/ {
        proxy_pass http://mail_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # --- ROUTE 2: React Frontend ---
    # Everything else falls through to your Vite containers
    location / {
        proxy_pass http://mail_frontend;
        
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support for Vite HMR
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    # --- ROUTE 3: Mailpit
    location = /mailpit {
        return 301 /mailpit/;
    }

    # 2. The actual reverse proxy
    location /mailpit/ {
        proxy_pass http://172.16.127.118:8025;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Mailpit requires WebSockets for its live-updating UI
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```
