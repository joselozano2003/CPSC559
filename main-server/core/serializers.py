from rest_framework import serializers
from .models import *


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    
    class Meta:
        model = User
        fields = ['user_id', 'email', 'password', 'first_name', 'last_name', 'created_at']
        extra_kwargs = {
            'user_id': {'read_only': True},
            'password': {'write_only': True},
            'points': {'read_only': True},
            'created_at': {'read_only': True}
        }
    
    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()

class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['user_id', 'email', 'first_name', 'last_name', 'created_at']
        read_only_fields = ['user_id', 'points', 'created_at']

class ChunkUploadRequestSerializer(serializers.Serializer):
    """Represents a single chunk the client wants to upload."""
    temp_chunk_id = serializers.CharField()
    order = serializers.IntegerField(min_value=0)
    size = serializers.IntegerField(min_value=1)


class FileUploadRequestSerializer(serializers.Serializer):
    """Incoming upload request from the client."""
    filename = serializers.CharField(max_length=255)
    size = serializers.IntegerField(min_value=1)
    chunks = ChunkUploadRequestSerializer(many=True)

    def validate_chunks(self, chunks):
        indices = sorted([c['order'] for c in chunks])
        if indices != list(range(len(chunks))):
            raise serializers.ValidationError("Chunk order must be sequential starting from 0.")
        return chunks


class ChunkUploadResponseSerializer(serializers.Serializer):
    """Returned to client for each chunk."""
    temp_chunk_id = serializers.CharField()
    chunk_id = serializers.CharField()
    order = serializers.IntegerField()
    presigned_url = serializers.URLField()
    presigned_urls = serializers.ListField(child=serializers.URLField())
    public_url = serializers.URLField()


class FileUploadResponseSerializer(serializers.Serializer):
    """Full response returned to client after upload is initiated."""
    file_id = serializers.UUIDField()
    filename = serializers.CharField()
    total_chunks = serializers.IntegerField()
    chunks = ChunkUploadResponseSerializer(many=True)