from django.db import models
import uuid
from django.contrib.auth.hashers import make_password, check_password
from .utils import getModelFields


class User(models.Model):
    user_id = models.CharField(primary_key=True, max_length=15, db_column='userId')
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=128)  # Increased for hashed passwords
    first_name = models.CharField(max_length=50, blank=True)
    last_name = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    
    def set_password(self, raw_password):
        self.password = make_password(raw_password)
    
    def check_password(self, raw_password):
        return check_password(raw_password, self.password)
    
    # Django authentication compatibility
    @property
    def pk(self):
        """Return user_id as primary key for Django compatibility"""
        return self.user_id
    
    @property
    def id(self):
        """Return user_id as id for Django compatibility"""
        return self.user_id
    
    @property
    def is_active(self):
        """All users are active by default"""
        return True
    
    @property
    def is_authenticated(self):
        """Return True if this is a real user account"""
        return True
    
    @property
    def is_anonymous(self):
        """Return False since this is a real user"""
        return False


    def __str__(self):
        return getModelFields(self)

#jp changes
class File(models.Model):
    STATUS_PENDING = "pending"
    STATUS_COMPLETE = "complete"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_COMPLETE, "Complete"),
        (STATUS_FAILED, "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    filename = models.CharField(max_length=255)
    size = models.BigIntegerField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.filename} ({self.owner.email})"

class Chunk(models.Model):
    file = models.ForeignKey(File, on_delete=models.CASCADE, related_name="chunks")
    chunk_id = models.CharField(max_length=255, unique=True)
    size = models.IntegerField(null=True, blank=True)
    order = models.IntegerField()
    uploaded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['order']
        unique_together = ('file', 'order')

    def __str__(self):
        return f"Chunk {self.order} of {self.file.filename}"

class StorageNode(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=128)
    address = models.CharField(max_length=256)
    is_active = models.BooleanField(default=True)
    last_heartbeat = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class ChunkReplica(models.Model):
    chunk = models.ForeignKey(Chunk, on_delete=models.CASCADE, related_name="replicas")
    storage_node = models.ForeignKey(StorageNode, on_delete=models.SET_NULL, null=True, related_name="replicas")
    confirmed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('chunk', 'storage_node')


class PendingDelete(models.Model):
    storage_node = models.ForeignKey(StorageNode, on_delete=models.CASCADE, related_name="pending_deletes")
    chunk_id = models.CharField(max_length=255)
    retry_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('storage_node', 'chunk_id')
