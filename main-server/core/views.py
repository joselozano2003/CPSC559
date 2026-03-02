from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated, BasePermission
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.tokens import RefreshToken
from django.db import models
from .models import *
from .serializers import *
from .s3_utils import S3ImageUploader
from django.http import JsonResponse
from django.db import connection
from django.utils import timezone
import uuid


class IsOwnerOrReadOnly(BasePermission):
    """
    Custom permission to only allow users to edit their own profile.
    """
    def has_object_permission(self, request, view, obj):
        # Read permissions for any authenticated user
        if request.method in ['GET']:
            return True
        
        # Write permissions only to the owner of the profile
        return obj.user_id == request.user.user_id


class IsOwner(BasePermission):
    """
    Custom permission to only allow users to access their own data.
    """
    def has_object_permission(self, request, view, obj):
        # Only allow access if the user owns this object
        return obj.user_id == request.user.user_id


def get_tokens_for_user(user):
    """Generate JWT tokens for our custom User model"""
    # User model now has all required Django authentication attributes
    refresh = RefreshToken.for_user(user)
    
    # Add custom claims
    refresh['user_id'] = user.user_id
    refresh['email'] = user.email
    
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }


def health_check(request):
    """
    Health check endpoint that verifies database connectivity
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        
        return JsonResponse({
            'status': 'healthy',
            'timestamp': timezone.now().isoformat(),
            'database': 'connected'
        })
    except Exception as e:
        return JsonResponse({
            'status': 'unhealthy',
            'timestamp': timezone.now().isoformat(),
            'database': 'disconnected',
            'error': str(e)
        }, status=503)


@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """
    Register a new user
    """
    serializer = UserSerializer(data=request.data)
    if serializer.is_valid():
        # Generate unique user_id
        user_id = str(uuid.uuid4())[:15]
        while User.objects.filter(user_id=user_id).exists():
            user_id = str(uuid.uuid4())[:15]
        
        serializer.validated_data['user_id'] = user_id
        user = serializer.save()
        
        # Generate JWT tokens
        tokens = get_tokens_for_user(user)
        
        return Response({
            'user': UserProfileSerializer(user).data,
            'tokens': tokens,
            'message': 'User registered successfully'
        }, status=status.HTTP_201_CREATED)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    """
    Login user with email and password
    """
    serializer = LoginSerializer(data=request.data)
    if serializer.is_valid():
        email = serializer.validated_data['email']
        password = serializer.validated_data['password']
        
        try:
            user = User.objects.get(email=email)
            if user.check_password(password):
                # Generate JWT tokens
                tokens = get_tokens_for_user(user)
                
                return Response({
                    'user': UserProfileSerializer(user).data,
                    'tokens': tokens,
                    'message': 'Login successful'
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'error': 'Invalid credentials'
                }, status=status.HTTP_401_UNAUTHORIZED)
        except User.DoesNotExist:
            return Response({
                'error': 'Invalid credentials'
            }, status=status.HTTP_401_UNAUTHORIZED)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()  # Required for router, but filtered in get_queryset()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated, IsOwner]
    
    def get_queryset(self):
        """
        Users can only see their own profile
        """
        return User.objects.filter(user_id=self.request.user.user_id)
    
    def get_serializer_class(self):
        """
        Use different serializers for different actions
        """
        if self.action in ['list', 'retrieve']:
            return UserProfileSerializer
        return UserSerializer
    
    def perform_create(self, serializer):
        """
        Prevent creation through this endpoint - use registration instead
        """
        raise PermissionDenied("Use /auth/register/ to create new users")
    
    @action(detail=False, methods=['get'])
    def me(self, request):
        """
        Get current user's profile - same as /auth/profile/
        """
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def friends(self, request):
        """
        Get current user's list of friends (accepted friend requests)
        """
        friends = request.user.friends()
        serializer = UserProfileSerializer(friends, many=True)
        return Response({
            'friends': serializer.data,
            'count': friends.count()
        })
    
    # --- NEW ACTION FOR SYNCING POINTS ---
    @action(detail=False, methods=['post'])
    def update_points(self, request):
        """
        Manually update the current user's points from the frontend
        """
        points = request.data.get('points')
        
        if points is None:
            return Response({
                'error': 'points value is required'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        # Update the user's points
        user = request.user
        user.points = int(points)
        user.save()
        
        return Response({
            'message': 'Points updated successfully',
            'total_points': user.points
        }, status=status.HTTP_200_OK)
    # -------------------------------------

    @action(detail=False, methods=['post'])
    def generate_upload_url(self, request):
        """
        Generate a presigned URL for uploading images to S3
        """
        filename = request.data.get('filename')
        if not filename:
            return Response({
                'error': 'filename is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        s3_uploader = S3ImageUploader()
        file_key = s3_uploader.generate_unique_filename(filename, request.user.user_id)
        presigned_url = s3_uploader.generate_presigned_url(file_key)
        
        if not presigned_url:
            return Response({
                'error': 'Failed to generate upload URL'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        public_url = s3_uploader.get_public_url(file_key)
        
        return Response({
            'upload_url': presigned_url,
            'public_url': public_url,
            'file_key': file_key,
            'expires_in': 3600  # 1 hour
        })

#jp changes
STORAGE_NODES = [
    "not sure here"
]

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def upload_metadata(request):
    """
    Client sends file metadata, server returns upload URLs per chunk.
    """
    filename = request.data.get("filename")
    size = request.data.get("size")
    num_chunks = request.data.get("num_chunks")

    if not filename or not num_chunks:
        return Response({"error": "filename and num_chunks required"}, status=400)

    file_obj = File.objects.create(
        owner=request.user,
        filename=filename,
        size=size
    )

    chunks_data = []
    for i in range(int(num_chunks)):
        chunk_id = str(uuid.uuid4())
        storage_node = STORAGE_NODES[i % len(STORAGE_NODES)]

        Chunk.objects.create(
            file=file_obj,
            chunk_id=chunk_id,
            storage_node=storage_node,
            order=i
        )

        chunks_data.append({
            "chunk_id": chunk_id,
            "upload_url": f"{storage_node}/upload/{chunk_id}/"
        })

    return Response({
        "file_id": file_obj.pk,
        "chunks": chunks_data
    })

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def download_metadata(request, file_id):
    """
    Returns chunk IDs and storage node URLs for a given file.
    """
    user = request.user
    if not user or not user.is_authenticated:
        return Response({"error": "Authentication required"}, status=401)

    try:
        file_obj = File.objects.get(pk=file_id, owner=user)
    except File.DoesNotExist:
        return Response({"error": "File not found"}, status=404)

    chunks = file_obj.chunks.order_by("order")
    response_chunks = [
        {
            "chunk_id": chunk.chunk_id,
            "download_url": f"{chunk.storage_node}/download/{chunk.chunk_id}/"
        }
        for chunk in chunks
    ]

    return Response({
        "file_id": file_obj.pk,
        "filename": file_obj.filename,
        "size": file_obj.size,
        "chunks": response_chunks
    })
#jp changes