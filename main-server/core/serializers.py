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
    temp_chunk_id = serializers.CharField()
    order = serializers.IntegerField(min_value=0)
    size = serializers.IntegerField(min_value=1)
    hash = serializers.CharField(max_length=64, required=False, allow_null=True)


class FileUploadRequestSerializer(serializers.Serializer):
    filename = serializers.CharField(max_length=255)
    size = serializers.IntegerField(min_value=1)
    chunks = ChunkUploadRequestSerializer(many=True)

    def validate_chunks(self, chunks):
        indices = sorted([c['order'] for c in chunks])
        if indices != list(range(len(chunks))):
            raise serializers.ValidationError("Chunk order must be sequential starting from 0.")
        return chunks


class ChunkUploadResponseSerializer(serializers.Serializer):
    temp_chunk_id = serializers.CharField()
    chunk_id = serializers.CharField()
    order = serializers.IntegerField()
    presigned_url = serializers.URLField()
    presigned_urls = serializers.ListField(child=serializers.URLField())
    public_url = serializers.URLField()
    replica_nodes = serializers.ListField(child=serializers.CharField(), required=False)
    expected_hash = serializers.CharField(max_length=64, required=False, allow_null=True)


class SCInfoSerializer(serializers.Serializer):
        seq_no = serializers.IntegerField()
        op_id = serializers.CharField()
        quorum_achieved = serializers.BooleanField()
        replicas_contacted = serializers.IntegerField()


class FileUploadResponseSerializer(serializers.Serializer):
    file_id = serializers.UUIDField()
    filename = serializers.CharField()
    total_chunks = serializers.IntegerField()
    chunks = ChunkUploadResponseSerializer(many=True)
    sc = SCInfoSerializer(required=False)
