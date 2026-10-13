# Communication with UI-UX
> we have only finished user api and admin login/view alias api, so only those were tested
## Minor Inconsistencies
> mostly format issues, already fixed in our codebase
- `src/api/axios.js`: change prefix to `/api/v1`, add xsrf settings
- `checkAuth` in `src/App.jsx`: change response data to that of Django (username, is_admin)
- `src/App.jsx`: update urls 
- (optional) footer message in `src/App.jsx`: change Node.js to Django 
- `handleSubmit` in `src/pages/LoginPage.jsx`: change api url and response data format
- `handleToggle` in `src/pages/HomePage.jsx`: change api url and push data format (need entire state of alias)
- terminology in `src/pages/HomePage.jsx`: will need to change `alias.id` to `alias.alias_name`, `alias.name` to `alias.display_name` (we don't have display_name yet, so keep it this way for easier testing)
- `src/pages/AdminAliasesPage.jsx`: change api url and update data format

## Major Inconsistencies
- `src/pages/AdminUserPage.jsx`: not needed, mail admins don't have permission to create new users in LDAP database
- `src/pages/HomePage.jsx`: admins don't have subscriptions; should have different-looking HomePage
- `src/pages/HomePage.jsx`: need "send modifications" button for users; modifications are sent after they toggle each alias to desired subscription state and click that button
