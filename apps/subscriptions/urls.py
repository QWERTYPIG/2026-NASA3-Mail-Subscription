from django.urls import path

from .views import (
    AdminAliasListView, 
    AdminAliasDetailView, 
    UserSubscriptionListView, 
    AdminAliasUserListView,
    AdminAliasUserDetailView
)


urlpatterns = [
    path("manage/aliases/", AdminAliasListView.as_view(), name="admin-alias-list"),
    path(
        "manage/aliases/<str:alias_name>/",
        AdminAliasDetailView.as_view(),
        name="admin-alias-detail",
    ),
    path(
        "mange/aliases/<str:alias_name>/users/",
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
