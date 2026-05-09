# Frontend
Frontend code is copied from [UI-UX's repo](https://github.com/2026-NTUCSIE-NASA-UIUX/Mail-Subscription-Frontend/)
Currently their repo is cloned locally, and needed files are copied to `frontend` for usage.
Connect to frontend at port `55111`.
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

