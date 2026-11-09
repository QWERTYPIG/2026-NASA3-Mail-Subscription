from django.db.models import Exists, OuterRef
from django.http import Http404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminUser

from . import writes
from .models import Alias, AliasMember
from .serializers import (
    AliasSerializer,
    AliasCreateSerializer,
    AliasUpdateSerializer,
    SubscriptionSerializer,
    UserSubscriptionUpdateSerializer,
    AddAliasMemberSerializer,
    MemberUidSerializer,
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
            writes.add_member(alias_name, uid)
        except writes.AliasNotFound:
            return not_found_response()
        except writes.MemberExists:
            # 使用 utils.py 中的 conflict_response 回傳 HTTP 409
            return conflict_response("該用戶已經存在於此別名中", {"uid": uid})
        except Exception:
            return internal_error_response()

        return Response(
            {"status": "success", "message": f"User {uid} added to {alias_name}"}, 
            status=status.HTTP_200_OK
        )

class AdminAliasUserDetailView(APIView):
    permission_classes = [IsAdminUser]

    def delete(self, request, alias_name, uid):
        serializer = MemberUidSerializer(data={"uid": uid})
        if not serializer.is_valid():
            return validation_error_response(serializer.errors)
        uid = serializer.validated_data["uid"]

        try:
            writes.remove_member(alias_name, uid)
        except writes.AliasNotFound:
            return not_found_response()
        except writes.MemberNotFound:
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
            writes.create_alias(**serializer.validated_data)
        except writes.AliasExists:
            return conflict_response("Alias name already exists.", {"existing_alias": alias_name})
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
            writes.delete_alias(kwargs[self.lookup_field])
        except writes.AliasNotFound:
            return not_found_response()
        except Exception:
            return internal_error_response()

        return Response(status=status.HTTP_204_NO_CONTENT)


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

        changed_aliases, created_task_ids = writes.set_subscriptions(
            request.user.get_username(), serializer.validated_data
        )

        return Response(
            {
                "status": "accepted",
                "message": "Subscription update accepted.",
                "changed_aliases": changed_aliases,
                "task_ids": created_task_ids,
            },
            status=status.HTTP_202_ACCEPTED,
        )
