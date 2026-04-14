from django.core.cache import cache
from rest_framework.throttling import BaseThrottle


class UserSubscriptionCooldownThrottle(BaseThrottle):
    """Per-user cooldown throttle for subscription update endpoint.

    Uses Redis cache via Django cache backend.
    Allows one PUT per user per cooldown window.
    """

    cooldown_seconds = 600
    cache_key_prefix = "user_subscription_cooldown"

    def _cache_key(self, request):
        return f"{self.cache_key_prefix}:{request.user.get_username()}"

    def allow_request(self, request, view):
        if request.method != "PUT":
            return True
        # Unauthenticated users are not throttled here; permission classes will handle access control.
        if not request.user or not request.user.is_authenticated:
            return True

        key = self._cache_key(request)
        created = cache.add(key, "1", timeout=self.cooldown_seconds)
        return created

    def wait(self):
        # Optional for DRF 429 details; omitted precise TTL lookup for portability.
        return self.cooldown_seconds
