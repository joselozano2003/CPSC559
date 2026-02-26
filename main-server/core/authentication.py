from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt import settings as jwt_settings
from django.contrib.auth.models import AnonymousUser
from .models import User


class CustomJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        """
        Get user from JWT token using our custom User model
        """
        try:
            user_id = validated_token[jwt_settings.api_settings.USER_ID_CLAIM]
            user = User.objects.get(user_id=user_id)
            # User model now has all required Django authentication attributes built-in
            return user
        except (KeyError, User.DoesNotExist):
            return AnonymousUser()