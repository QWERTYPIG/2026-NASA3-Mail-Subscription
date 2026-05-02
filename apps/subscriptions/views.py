from django.db import transaction
from django.http import Http404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminUser

from .models import Alias, AliasTaskQueue, UserTaskQueue
from .serializers import (
    AliasSerializer,
    AliasCreateSerializer,
    AliasUpdateSerializer,
    SubscriptionSerializer,
    UserSubscriptionUpdateSerializer,
)
from .throttles import UserSubscriptionCooldownThrottle


class AdminAliasListView(generics.ListCreateAPIView):
    permission_classes = [IsAdminUser]
    queryset = Alias.objects.all().order_by("alias_name")

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return AliasCreateSerializer
        return AliasSerializer

    def create(self, request, *args, **kwargs):
        alias_name = request.data.get("alias_name")
        if alias_name and Alias.objects.filter(alias_name=alias_name).exists():
            return Response(
                {
                    "error": "Alias name already exists.",
                    "code": "CONFLICT",
                    "details": {"existing_alias": alias_name},
                },
                status=status.HTTP_409_CONFLICT,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                instance = serializer.save()
                AliasTaskQueue.objects.create(
                    alias_name=instance.alias_name,
                    action="add",
                )
        except Exception:
            return Response(
                {
                    "error": "An unexpected error occurred. Please contact the administrator.",
                    "code": "INTERNAL_SERVER_ERROR",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class AdminAliasDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAdminUser]
    queryset = Alias.objects.all()
    serializer_class = AliasSerializer
    lookup_field = "alias_name"

    def get_serializer_class(self):
        if self.request.method in {"PATCH", "PUT"}:
            return AliasUpdateSerializer
        return AliasSerializer

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        try:
            instance = self.get_object()
        except Http404:
            return Response(
                {
                    "error": "The requested resource was not found.",
                    "code": "NOT_FOUND",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        if not serializer.is_valid():
            return Response(
                {
                    "error": "Validation failed",
                    "code": "VALIDATION_ERROR",
                    "details": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            self.perform_update(serializer)
        except Exception:
            return Response(
                {
                    "error": "An unexpected error occurred. Please contact the administrator.",
                    "code": "INTERNAL_SERVER_ERROR",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(serializer.data)

    def perform_destroy(self, instance):
        AliasTaskQueue.objects.create(
            alias_name=instance.alias_name,
            action="remove",
        )
        instance.delete()


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
