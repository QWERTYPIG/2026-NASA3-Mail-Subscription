# Subscriptions API Progress (bbwinner)

## Scope

### Task 1: Read-only alias APIs

1. Create `serializers.py` for response formatting.
2. Implement admin endpoint: `GET /api/v1/admin/aliases/`.
3. Implement user endpoint: `GET /api/v1/user/subscriptions/`.

### Task 2: User update API + cooldown

1. Add DRF throttling cooldown with Redis cache.
2. Implement `PUT /api/v1/user/subscriptions/`.
3. Push changed actions to `UserTaskQueue`.
4. Update `Alias.user_id` local cache directly.

---

## Implemented Changes

### (1) Serializers (`apps/subscriptions/serializers.py`)

- `AliasSerializer`
  - For admin alias listing.
  - Fields: `alias_name`, `display_name`, `description`.

- `SubscriptionSerializer`
  - For user alias listing.
  - Fields: `alias_name`, `display_name`, `description`, `is_subscribed`.
  - `is_subscribed` is computed by checking:
    - `request.user.username in Alias.user_id`.

- `UserSubscriptionUpdateSerializer`
  - Validates full payload map: `alias_name -> boolean`.
  - Rejects:
    - non-object payload
    - non-string keys
    - non-boolean values
    - missing aliases
    - unknown aliases

### (2) Views (`apps/subscriptions/views.py`)

- `AdminAliasListView`
  - Endpoint: `GET /api/v1/admin/aliases/`
  - Permission: `IsAdminUser`
  - Behavior: returns alias list without `is_subscribed`.

- `UserSubscriptionListView`
  - Endpoint: `GET /api/v1/user/subscriptions/`
  - Permission: `IsAuthenticated`
  - Behavior: returns alias list with `is_subscribed`.

- `UserSubscriptionListView.put`
  - Endpoint: `PUT /api/v1/user/subscriptions/`
  - Permission: `IsAuthenticated`
  - Throttle: `UserSubscriptionCooldownThrottle`
  - Uses `transaction.atomic()` for consistency.
  - For each changed alias:
    - create one `UserTaskQueue` row (`add` / `remove`)
    - update `Alias.user_id` local cache
  - Returns `202 Accepted` with changed aliases and created task IDs.

### (3) Throttle (`apps/subscriptions/throttles.py`)

- `UserSubscriptionCooldownThrottle`
  - Redis-backed per-user cooldown.
  - Cache key format: `user_subscription_cooldown:<username>`
  - Applies to `PUT` only.
  - Cooldown window: `600s` (10 minutes).

### (4) URLs

- Added routes in `apps/subscriptions/urls.py`:
  - `admin/aliases/`
  - `user/subscriptions/`
- Included in `core/urls.py` under `/api/v1/`.

---

## Permission Notes

- `IsAdminUser` (custom, `apps/accounts/permissions.py`)
  - only authenticated users with `is_staff=True`.

- `IsAuthenticated` (DRF built-in)
  - any logged-in user.

---

## Test Coverage

### API tests

- `AliasListApiTest`
  - unauthenticated user cannot access admin endpoint
  - authenticated non-admin cannot access admin endpoint
  - authenticated admin gets alias list
  - unauthenticated user cannot access user endpoint
  - authenticated user gets `is_subscribed`

- `UserSubscriptionUpdateApiTest`
  - auth required
  - invalid payload returns 400
  - queue rows + alias cache updated correctly
  - second PUT within cooldown returns 429

### Serializer tests

- `UserSubscriptionUpdateSerializerTest`
  - accepts full map
  - rejects missing aliases
  - rejects non-boolean values
  - rejects unknown alias keys

### Manual test result

- 13 tests passed:
  - `AliasListApiTest`
  - `UserSubscriptionUpdateSerializerTest`
  - `UserSubscriptionUpdateApiTest`

---

## Debug Note

- Encountered `ModuleNotFoundError: ldap3` in container.
- Root cause: image/container dependency mismatch.
- Fix: rebuild and recreate Docker containers.
