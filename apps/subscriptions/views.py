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
from .utils import not_found_response, internal_error_response, validation_error_response, conflict_response


class AdminAliasUserListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, alias_name):
        try:
            alias = Alias.objects.get(alias_name=alias_name)
        except Alias.DoesNotExist:
            return not_found_response()
        except Exception:
            return internal_error_response()
        return Response(alias.user_id, status=status.HTTP_200_OK)

    def post(self, request, alias_name):
        uid = request.data.get("uid")
        
        if not uid or len(uid) != 9:
            return validation_error_response({"uid": ["Ensure this field has exactly 9 characters."]})

        try:
            with transaction.atomic():
                try:
                    # Select for update to prevent concurrent race conditions
                    alias = Alias.objects.select_for_update().get(alias_name=alias_name)
                except Alias.DoesNotExist:
                    return not_found_response()

                if uid not in alias.user_id:
                    alias.user_id.append(uid)
                    alias.save(update_fields=["user_id"])
                    
                    UserTaskQueue.objects.create(
                        alias_name=alias.alias_name,
                        user_uid=uid,
                        action="add",
                    )
        except Exception:
            return internal_error_response()

        return Response(status=status.HTTP_200_OK)


class AdminAliasUserDetailView(APIView):
    permission_classes = [IsAdminUser]

    def delete(self, request, alias_name, uid):
        if not uid or len(uid) != 9:
            return validation_error_response({"uid": ["Ensure this field has exactly 9 characters."]})

        try:
            with transaction.atomic():
                try:
                    # Select for update to prevent concurrent edits
                    alias = Alias.objects.select_for_update().get(alias_name=alias_name)
                except Alias.DoesNotExist:
                    return not_found_response()

                if uid in alias.user_id:
                    alias.user_id.remove(uid)
                    alias.save(update_fields=["user_id"])
                    
                    UserTaskQueue.objects.create(
                        alias_name=alias.alias_name,
                        user_uid=uid,
                        action="remove",
                    )
                else:
                    return not_found_response("User not found in this alias.")
        except Exception:
            return internal_error_response()

        return Response(status=status.HTTP_204_NO_CONTENT)


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
            return conflict_response("Alias name already exists.", {"existing_alias": alias_name})

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
            return internal_error_response()

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
            return not_found_response()

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        if not serializer.is_valid():
            return validation_error_response(serializer.errors)

        try:
            self.perform_update(serializer)
        except Exception:
            return internal_error_response()

        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except Http404:
            return not_found_response()

        try:
            with transaction.atomic():
                self.perform_destroy(instance)
        except Exception:
            return internal_error_response()

        return Response(status=status.HTTP_204_NO_CONTENT)

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
