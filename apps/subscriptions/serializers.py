from rest_framework import serializers
from django_auth_ldap.backend import LDAPBackend

from .models import Alias


class AliasSerializer(serializers.ModelSerializer):
    """Admin alias listing."""

    class Meta:
        model = Alias
        fields = ["alias_name", "display_name", "description"]


class AliasCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alias
        fields = ["alias_name", "display_name", "description"]
        extra_kwargs = {
            "alias_name": {"required": True, "allow_blank": False},
            "display_name": {"required": True, "allow_blank": False},
            "description": {"required": True, "allow_blank": False},
        }

    def validate_alias_name(self, value):
        if Alias.objects.filter(alias_name=value).exists():
            raise serializers.ValidationError("Alias with this name already exists.")
        return value


class AliasUpdateSerializer(serializers.ModelSerializer):
    """Admin alias update (PATCH)."""

    class Meta:
        model = Alias
        fields = ["display_name", "description"]
        extra_kwargs = {
            "display_name": {
                "required": False,
                "allow_blank": True,
                "max_length": 255,
            },
            "description": {
                "required": False,
                "allow_blank": True,
                "max_length": 500,
            },
        }


class SubscriptionSerializer(serializers.ModelSerializer):
    """User alias listing with subscription status."""

    is_subscribed = serializers.SerializerMethodField()

    class Meta:
        model = Alias
        fields = ["alias_name", "display_name", "description", "is_subscribed"]

    def get_is_subscribed(self, obj):
        user = self.context["request"].user
        return user.username in obj.user_id


class UserSubscriptionUpdateSerializer(serializers.Serializer):
    """Validate full alias->subscribed map payload for user update endpoint.

    Expected request body example:
    {
      "workstation": true,
      "activities": false
    }
    """

    default_error_messages = {
        "not_object": "Payload must be a JSON object mapping alias_name to boolean.",
        "invalid_key": "Each alias_name key must be a string.",
        "invalid_value": "Each alias status value must be a boolean.",
        "missing_aliases": "Payload must include all aliases. Missing: {aliases}",
        "unknown_aliases": "Payload contains unknown aliases: {aliases}",
    }

    def _raise_non_field_error(self, key, **kwargs):
        message = self.error_messages[key].format(**kwargs)
        raise serializers.ValidationError({"non_field_errors": [message]})

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            self._raise_non_field_error("not_object")

        normalized = {}
        for alias_name, status in data.items():
            if not isinstance(alias_name, str):
                self._raise_non_field_error("invalid_key")
            if not isinstance(status, bool):
                self._raise_non_field_error("invalid_value")
            normalized[alias_name] = status

        return normalized

    def validate(self, attrs):
        all_aliases = set(Alias.objects.values_list("alias_name", flat=True))
        payload_aliases = set(attrs.keys())

        missing = sorted(all_aliases - payload_aliases)
        if missing:
            self._raise_non_field_error("missing_aliases", aliases=", ".join(missing))

        unknown = sorted(payload_aliases - all_aliases)
        if unknown:
            self._raise_non_field_error("unknown_aliases", aliases=", ".join(unknown))

        return attrs

class AddAliasMemberSerializer(serializers.Serializer):
    """Validate UID format and existence in LDAP before adding."""
    uid = serializers.CharField(max_length=50)

    def validate_uid(self, value):
        uid = value.strip().lower()
        
        # 1. Basic format validation (matching the frontend rules)
        if not uid.isalnum():
            raise serializers.ValidationError("UID 格式錯誤，僅允許英數字。")

        # 2. LDAP Synchronous Verification
        # Leverage your existing AUTH_LDAP_USER_SEARCH settings to query the server
        ldap_backend = LDAPBackend()
        ldap_user = ldap_backend.populate_user(uid)
        
        if ldap_user is None:
            # This string maps directly to errorData.details.uid[0] in React
            raise serializers.ValidationError("此帳號不存在於 LDAP 系統中。")
            
        return uid
