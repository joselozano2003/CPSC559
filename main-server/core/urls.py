from django.urls import path, include
from django.http import HttpResponse
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework_simplejwt.views import TokenVerifyView
from . import views
from .views import FileUploadView

def home(request):
    return HttpResponse("OK — MapleQuest is running!", status=200)

# DRF Router for ViewSets
router = DefaultRouter()
router.register(r'users', views.UserViewSet)


urlpatterns = [
    path('', home, name='home'),
    path('health/', views.health_check, name='health_check'),
    path('api/token/verify/', TokenVerifyView.as_view(), name='token_verify'),
    
    # Authentication endpoints
    path('auth/register/', views.register, name='register'),
    path('auth/login/', views.login, name='login'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    #jp changes
    path('download/<int:file_id>/', views.download_metadata, name='download_metadata'),
    path('download/chunk/<uuid:chunk_id>/', views.download_chunk, name='download_chunk'),
    #jp changes

    path('nodes/heartbeat/', views.node_heartbeat, name='node-heartbeat'),
    path('files/upload/', FileUploadView.as_view(), name='file-upload'),
    path('files/<uuid:file_id>/download/', views.download_file, name='file-download'),
    path('files/', views.list_files, name='list-files'),
    
    # API endpoints
    path('api/', include(router.urls)),
    
]