from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework import status

class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')

        # This triggers django-auth-ldap to reach out to the LDAP server
        user = authenticate(request, username=username, password=password)

        if user is not None:
            # Creates the session in the database and sets the sessionid cookie
            login(request, user)
            
            # Forces Django to generate and send the csrftoken cookie to React
            get_token(request)
            
            return Response({
                "username": user.username,
                "is_staff": user.is_staff
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                "error": "Authentication credentials were not provided or CSRF verification failed.",
                "code": "NOT_AUTHENTICATED"
            }, status=status.HTTP_401_UNAUTHORIZED)


class CheckSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # The proposal specifically asks for the key "is_admin" here, 
        # so we map the database's is_staff flag to it.
        return Response({
            "username": request.user.username,
            "is_admin": request.user.is_staff
        }, status=status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Destroys the session in the Postgres database and clears the cookies
        logout(request)
        return Response(status=status.HTTP_205_RESET_CONTENT)
