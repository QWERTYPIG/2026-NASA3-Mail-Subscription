from django.urls import path

from .views import (
    HealthView,
    AdminAliasListView, 
    AdminAliasDetailView, 
    UserSubscriptionListView, 
    AdminAliasUserListView,
    AdminAliasUserDetailView
)


urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("manage/aliases/", AdminAliasListView.as_view(), name="admin-alias-list"),
    path(
        "manage/aliases/<str:alias_name>/",
        AdminAliasDetailView.as_view(),
        name="admin-alias-detail",
    ),
    path(
        "manage/aliases/<str:alias_name>/users/",
        AdminAliasUserListView.as_view(),
        name="admin-alias-user-list",
    ),
    path(
        "manage/aliases/<str:alias_name>/users/<str:uid>/",
        AdminAliasUserDetailView.as_view(),
        name="admin-alias-user-detail",
    ),
    path(
        "user/subscriptions/",
        UserSubscriptionListView.as_view(),
        name="user-subscription-list",
    ),
]
