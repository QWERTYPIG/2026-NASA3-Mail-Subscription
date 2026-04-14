from rest_framework.throttling import SimpleRateThrottle


class UserSubscriptionCooldownThrottle(SimpleRateThrottle):
    """Per-user cooldown throttle for subscription update endpoint.

    Uses Redis cache via Django cache backend.
    Scope rate is configured in settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].
    """

    scope = "user_subscription_cooldown"

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return None
        return self.cache_format % {
            "scope": self.scope,
            "ident": request.user.get_username(),
        }
