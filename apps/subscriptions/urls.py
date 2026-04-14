from django.urls import path

from .views import AdminAliasListView, UserSubscriptionListView


urlpatterns = [
    path("admin/aliases/", AdminAliasListView.as_view(), name="admin-alias-list"),
    path(
        "user/subscriptions/",
        UserSubscriptionListView.as_view(),
        name="user-subscription-list",
    ),
]
