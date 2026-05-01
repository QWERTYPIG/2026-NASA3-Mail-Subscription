# Frontend
Frontend code is copied from [UI-UX's repo](https://github.com/2026-NTUCSIE-NASA-UIUX/Mail-Subscription-Frontend/)
Currently their repo is cloned locally, and needed files are copied to `frontend` for usage.
## Inconsistencies
Frontend code currently works with their backend stub, so some files need to be changed to integrate with our actual backend.
Changes are listed below, will talk to UI-UX to ask for modifications.
- `src/api/axios.js`: change prefix to `/api/v1`, add xsrf settings
- `checkAuth` in `src/App.jsx`: change response data to that of Django (username, is_admin)
- `src/App.jsx`: update urls 
- (optional) footer message in `src/App.jsx`: change Node.js to Django 
- `handleSubmit` in `src/pages/LoginPage.jsx`: change api url and response data format
- `src/pages/AdminUserPage.jsx`: not needed
- `handleToggle` in `src/pages/HomePage.jsx`: change api url and push data format (need entire state of alias)
- terminology in `src/pages/HomePage.jsx`: will need to change `alias.id` to `alias.alias_name`, `alias.name` to `alias.display_name` (we don't have display_name yet, so keep it this way for easier testing)
- `src/pages/AdminAliasesPage.jsx`: change api url and update data format


## misc
- add `authentication_classes = []` in LoginView in `apps/accounts/views.py`
- add `CSRF_TRUSTED_ORIGINS` in `core/settings.py`
