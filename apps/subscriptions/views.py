from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminUser

from .models import Alias, UserTaskQueue
from .serializers import (
    AliasSerializer,
    SubscriptionSerializer,
    UserSubscriptionUpdateSerializer,
)
from .throttles import UserSubscriptionCooldownThrottle


class AdminAliasListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        aliases = Alias.objects.all().order_by("alias_name")
        serializer = AliasSerializer(aliases, many=True)
        return Response(serializer.data)


class UserSubscriptionListView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserSubscriptionCooldownThrottle]

    def get(self, request):
        aliases = Alias.objects.all().order_by("alias_name")
        serializer = SubscriptionSerializer(
            aliases,
            many=True,
            context={"request": request},
        )
        return Response(serializer.data)

    def put(self, request):
        serializer = UserSubscriptionUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        desired_map = serializer.validated_data
        username = request.user.get_username()
        changed_aliases = []
        created_task_ids = []

        with transaction.atomic():
            aliases = Alias.objects.filter(alias_name__in=desired_map.keys())

            for alias in aliases:
                desired_is_subscribed = desired_map[alias.alias_name]
                currently_subscribed = username in alias.user_id

                if desired_is_subscribed == currently_subscribed:
                    continue

                action = "add" if desired_is_subscribed else "remove"
                task = UserTaskQueue.objects.create(
                    alias_name=alias.alias_name,
                    user_uid=username,
                    action=action,
                )
                created_task_ids.append(task.id)

                if desired_is_subscribed:
                    updated_user_ids = list(alias.user_id) + [username]
                else:
                    updated_user_ids = [uid for uid in alias.user_id if uid != username]

                alias.user_id = updated_user_ids
                alias.save(update_fields=["user_id"])
                changed_aliases.append(alias.alias_name)

        return Response(
            {
                "status": "accepted",
                "message": "Subscription update accepted.",
                "changed_aliases": sorted(changed_aliases),
                "task_ids": created_task_ids,
            },
            status=status.HTTP_202_ACCEPTED,
        )
