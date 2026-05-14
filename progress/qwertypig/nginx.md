# Nginx Setup Documemtation
## Install
`sudo apt update`
`sudo apt install nginx`
## Config
`cd /etc/nginx/conf.d`
`sudo vim mailsus.conf`
```
upstream mail_frontend {
    server 172.16.127.102:55111 max_fails=3 fail_timeout=30s;
    server 172.16.127.116:55111 max_fails=3 fail_timeout=30s;
    server 172.16.127.117:55111 max_fails=3 fail_timeout=30s;
}

server {
    listen 80;
    server_name mailsus.csie.org;

    location / {
	proxy_pass http://mail_frontend;
        
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```
