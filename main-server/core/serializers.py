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