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
