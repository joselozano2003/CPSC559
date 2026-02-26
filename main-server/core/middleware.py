from django.utils.deprecation import MiddlewareMixin
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from django.contrib.auth.models import AnonymousUser
from .models import User


class JWTAuthenticationMiddleware(MiddlewareMixin):
    def process_request(self, request):
        """
        Add JWT user to request if valid token is provided
        """
        jwt_auth = JWTAuthentication()
        
        try:
            # Try to authenticate using JWT
            auth_result = jwt_auth.authenticate(request)
            if auth_result:
                validated_token = auth_result[1]
                user_id = validated_token.get('user_id')
                
                if user_id:
                    try:
                        user = User.objects.get(user_id=user_id)
                        # Create a simple user object for request.user
                        request.user = type('User', (), {
                            'user_id': user.user_id,
                            'email': user.email,
                            'is_authenticated': True,
                            'is_anonymous': False,
                            '_user': user
                        })()
                    except User.DoesNotExist:
                        request.user = AnonymousUser()
                else:
                    request.user = AnonymousUser()
            else:
                request.user = AnonymousUser()
        except (InvalidToken, TokenError):
            request.user = AnonymousUser()
        
        return None