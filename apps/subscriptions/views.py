from django.db import transaction
from django.db.models import Exists, OuterRef
from django.http import Http404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminUser

from .models import Alias, AliasMember, SyncTask
from .serializers import (
    AliasSerializer,
    AliasCreateSerializer,
    AliasUpdateSerializer,
    SubscriptionSerializer,
    UserSubscriptionUpdateSerializer,
    AddAliasMemberSerializer
)
from .throttles import UserSubscriptionCooldownThrottle
from .utils import not_found_response, internal_error_response, validation_error_response, conflict_response


class HealthView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({"status": "ok"}, status=status.HTTP_200_OK)


class AdminAliasUserListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, alias_name):
        try:
            alias = Alias.objects.get(alias_name=alias_name)
        except Alias.DoesNotExist:
            return not_found_response()
        except Exception:
            return internal_error_response()
        user_ids = list(alias.members.values_list("user_uid", flat=True))
        return Response(user_ids, status=status.HTTP_200_OK)

    def post(self, request, alias_name):
        # 1. 使用 Serializer 進行驗證 (包含 LDAP 同步檢查)
        serializer = AddAliasMemberSerializer(data=request.data)
        if not serializer.is_valid():
            return validation_error_response(serializer.errors)

        # 2. 取得經過正規化 (lowercase) 且驗證存在的 UID
        uid = serializer.validated_data["uid"]

        try:
            with transaction.atomic():
                try:
                    # 使用 select_for_update 避免併發競爭
                    alias = Alias.objects.select_for_update().get(alias_name=alias_name)
                except Alias.DoesNotExist:
                    return not_found_response()

                # 3. 檢查是否已在訂閱名單中，避免重複寫入
                if AliasMember.objects.filter(alias=alias, user_uid=uid).exists():
                    # 使用 utils.py 中的 conflict_response 回傳 HTTP 409
                    return conflict_response(
                        "該用戶已經存在於此別名中", 
                        {"uid": uid}
                    )

                AliasMember.objects.create(alias=alias, user_uid=uid)

                # 4. 寫入 Task Queue 供背景工作同步至 LDAP
                SyncTask.objects.create(
                    kind=SyncTask.KIND_MEMBER,
                    action=SyncTask.ACTION_ADD,
                    alias_name=alias.alias_name,
                    user_uid=uid,
                )
        except Exception:
            return internal_error_response()

        return Response(
            {"status": "success", "message": f"User {uid} added to {alias_name}"}, 
            status=status.HTTP_200_OK
        )

class AdminAliasUserDetailView(APIView):
    permission_classes = [IsAdminUser]

    def delete(self, request, alias_name, uid):
        if not uid:
            return validation_error_response({"uid": ["User not found."]})

        try:
            with transaction.atomic():
                try:
                    # Select for update to prevent concurrent edits
                    alias = Alias.objects.select_for_update().get(alias_name=alias_name)
                except Alias.DoesNotExist:
                    return not_found_response()

                deleted, _ = AliasMember.objects.filter(alias=alias, user_uid=uid).delete()
                if not deleted:
                    return not_found_response("User not found in this alias.")

                SyncTask.objects.create(
                    kind=SyncTask.KIND_MEMBER,
                    action=SyncTask.ACTION_REMOVE,
                    alias_name=alias.alias_name,
                    user_uid=uid,
                )
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
                SyncTask.objects.create(
                    kind=SyncTask.KIND_ALIAS,
                    action=SyncTask.ACTION_ADD,
                    alias_name=instance.alias_name,
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
        SyncTask.objects.create(
            kind=SyncTask.KIND_ALIAS,
            action=SyncTask.ACTION_REMOVE,
            alias_name=instance.alias_name,
        )
        # alias_member rows go with it (ON DELETE CASCADE)
        instance.delete()


class UserSubscriptionListView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserSubscriptionCooldownThrottle]

    def get(self, request):
        username = request.user.get_username()
        aliases = Alias.objects.annotate(
            is_subscribed=Exists(
                AliasMember.objects.filter(alias=OuterRef("pk"), user_uid=username)
            )
        ).order_by("alias_name")
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
            subscribed = set(
                AliasMember.objects.filter(
                    user_uid=username, alias__in=aliases
                ).values_list("alias_id", flat=True)
            )

            for alias in aliases:
                desired_is_subscribed = desired_map[alias.alias_name]
                currently_subscribed = alias.alias_name in subscribed

                if desired_is_subscribed == currently_subscribed:
                    continue

                action = SyncTask.ACTION_ADD if desired_is_subscribed else SyncTask.ACTION_REMOVE
                task = SyncTask.objects.create(
                    kind=SyncTask.KIND_MEMBER,
                    action=action,
                    alias_name=alias.alias_name,
                    user_uid=username,
                )
                created_task_ids.append(task.id)

                if desired_is_subscribed:
                    AliasMember.objects.create(alias=alias, user_uid=username)
                else:
                    AliasMember.objects.filter(alias=alias, user_uid=username).delete()

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
