from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminUser

from .models import Alias
from .serializers import AliasSerializer, SubscriptionSerializer


class AdminAliasListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        aliases = Alias.objects.all().order_by("alias_name")
        serializer = AliasSerializer(aliases, many=True)
        return Response(serializer.data)


class UserSubscriptionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        aliases = Alias.objects.all().order_by("alias_name")
        serializer = SubscriptionSerializer(
            aliases,
            many=True,
            context={"request": request},
        )
        return Response(serializer.data)
