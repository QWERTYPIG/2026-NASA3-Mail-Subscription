from django.urls import path
from .views import LoginView, CheckSessionView, LogoutView

urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('me/', CheckSessionView.as_view(), name='check-session'),
    path('logout/', LogoutView.as_view(), name='logout'),
]
