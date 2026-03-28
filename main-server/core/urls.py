from django.urls import path, include
from django.http import HttpResponse
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework_simplejwt.views import TokenVerifyView
from . import views
from .views import FileUploadView

def home(request):
    return HttpResponse("OK — Main Server is running!", status=200)

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
    path('files/<uuid:file_id>/delete/', views.delete_file, name='file-delete'),
    path('token/receive/', views.receive_token, name='token-receive'),
    path('sc/apply/', views.sc_apply, name='sc-apply'),
    path('sc/ack/', views.sc_ack, name='sc-ack'),
    #jp changes

    path('nodes/heartbeat/', views.node_heartbeat, name='node-heartbeat'),
    path('files/upload/', FileUploadView.as_view(), name='file-upload'),
    path('files/<uuid:file_id>/download/', views.download_file, name='file-download'),
    path('files/', views.list_files, name='list-files'),

    # Bully election endpoints
    path('election/', views.election, name='election'),
    path('bully/', views.bully, name='bully'),
    path('leader-announce/', views.leader, name='leader-announce'),
    path('leader/', views.leader_info, name='leader-info'),
    path('heartbeat/', views.heartbeat_check, name='heartbeat-check'),

    # API endpoints
    path('api/', include(router.urls)),
]
