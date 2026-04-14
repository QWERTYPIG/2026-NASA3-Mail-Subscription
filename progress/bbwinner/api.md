# Subscriptions API Progress

## Task scope

Implement read-only alias APIs for both admin and normal users:

1. Create `serializers.py` for response formatting.
2. Implement admin endpoint: `GET /api/v1/admin/aliases/`.
3. Implement user endpoint: `GET /api/v1/user/subscriptions/`.

---

## What I implemented

### 1 Serializers (`apps/subscriptions/serializers.py`)

- `AliasSerializer`
  - For admin alias list output.
  - Fields:
    - `alias_name`
    - `display_name`
    - `description`

- `SubscriptionSerializer`
  - For normal user alias list output.
  - Fields:
    - `alias_name`
    - `display_name`
    - `description`
    - `is_subscribed` (computed field)
  - `is_subscribed` logic:
    - check whether `request.user.username` is in `Alias.user_id`.

### 2 Views (`apps/subscriptions/views.py`)

- `AdminAliasListView`
  - Endpoint: `GET /api/v1/admin/aliases/`
  - Permission: `IsAdminUser`
  - Behavior: returns all aliases without `is_subscribed`.

- `UserSubscriptionListView`
  - Endpoint: `GET /api/v1/user/subscriptions/`
  - Permission: `IsAuthenticated`
  - Behavior: returns all aliases with per-user `is_subscribed`.

### 3 URLs

- Added routes in `apps/subscriptions/urls.py`:
  - `admin/aliases/`
  - `user/subscriptions/`
- Included subscriptions routes under `/api/v1/` in `core/urls.py`.

---

## Permission notes

- `IsAdminUser` (custom, in `apps/accounts/permissions.py`)
  - allows only authenticated users with `is_staff=True`.

- `IsAuthenticated` (DRF built-in)
  - allows any logged-in user.

---

## Test coverage (API)

Added/updated tests in `apps/subscriptions/tests.py` (`AliasListApiTest`):

- admin endpoint
  - unauthenticated user -> forbidden
  - authenticated non-admin user -> forbidden
  - authenticated admin user -> 200 + expected fields

- user endpoint
  - unauthenticated user -> forbidden
  - authenticated user -> 200 + includes `is_subscribed`

---

## Debug note

- Encountered `ModuleNotFoundError: ldap3` in container.
- Root cause: container/image dependency mismatch.
- Resolved by **rebuilding** and recreating Docker containers.
