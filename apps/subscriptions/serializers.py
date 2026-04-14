from rest_framework import serializers

from .models import Alias


class AliasSerializer(serializers.ModelSerializer):
    """Admin alias listing."""

    class Meta:
        model = Alias
        fields = ["alias_name", "display_name", "description"]


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
