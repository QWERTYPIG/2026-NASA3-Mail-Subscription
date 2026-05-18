# Frontend
Frontend code is copied from [UI-UX's repo](https://github.com/2026-NTUCSIE-NASA-UIUX/Mail-Subscription-Frontend/)
Currently their repo is cloned locally, and needed files are copied to `frontend` for usage.
Connect to frontend at port `55111`.

## Dev Server Proxy
`vite.config.js` 會將 `/api` 代理到 `VITE_API_TARGET`（在 docker compose 內預設 `http://web:8000`），前端只需呼叫 `/api/...`。

## HMR Behind Nginx
`vite.config.js` 設定 `server.hmr.clientPort = 80`，讓瀏覽器的 HMR WebSocket 連線走 Nginx 的 80 port（對應 `mailsus.csie.org` 的反向代理場景）。

## Structure
```text
.
└─── frontend/                  # React application
    ├── src/
    │   ├── api/               # Axios instance and interceptors
    │   ├── constants/         # Configuration-driven navigation and routes
    │   └── navConfig.js            # navigation bar settings   
    │   ├── component/         # HTML element components (e.g. buttons)
    │   └── pages/             # Page components
    │        ├── AdminAliasPage.jsx # Admin view all alias and create new alias
    │        ├── AliasDetail.jsx    # Admin modify page for single alias
    │        ├── index.jsx          # Index mapping
    │        ├── HomePage.jsx       # User HomePage showing all alias add toggle, has "send" button for batch updates
    │        └── LoginPage.jsx      # User/Admin login page
    └── vite.config.js         # Vite configuration with proxy settings
```

