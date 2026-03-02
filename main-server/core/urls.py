from django.urls import path, include
from django.http import HttpResponse
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

def home(request):
    return HttpResponse("OK — MapleQuest is running!", status=200)

# DRF Router for ViewSets
router = DefaultRouter()
router.register(r'users', views.UserViewSet)


urlpatterns = [
    path('', home, name='home'),
    path('health/', views.health_check, name='health_check'),
    
    # Authentication endpoints
    path('auth/register/', views.register, name='register'),
    path('auth/login/', views.login, name='login'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    #jp changes
    path('upload/', views.upload_metadata, name='upload_metadata'),
    path('download/<int:file_id>/', views.download_metadata, name='download_metadata'),
    #jp changes
    
    # API endpoints
    path('api/', include(router.urls)),
]