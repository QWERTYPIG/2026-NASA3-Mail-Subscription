from django.urls import path

from .views import AdminAliasListView, AdminAliasDetailView, UserSubscriptionListView, AdminAliasUserListView


urlpatterns = [
    path("admin/aliases/", AdminAliasListView.as_view(), name="admin-alias-list"),
    path(
        "admin/aliases/<str:alias_name>/",
        AdminAliasDetailView.as_view(),
        name="admin-alias-detail",
    ),
    path(
        "admin/aliases/<str:alias_name>/users/",
        AdminAliasUserListView.as_view(),
        name="admin-alias-user-list",
    ),
    path(
        "user/subscriptions/",
        UserSubscriptionListView.as_view(),
        name="user-subscription-list",
    ),
]
