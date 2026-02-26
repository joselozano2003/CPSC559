import boto3
import os
from django.conf import settings
from botocore.exceptions import ClientError
import uuid


class S3ImageUploader:
    def __init__(self):
        # Check if we're using MinIO (local development)
        endpoint_url = os.getenv('AWS_S3_ENDPOINT_URL')
        if endpoint_url:
            self.s3_client = boto3.client(
                's3',
                endpoint_url=endpoint_url,
                aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
                region_name=os.getenv('AWS_REGION', 'us-east-1')
            )
        else:
            # Production AWS S3
            self.s3_client = boto3.client('s3')
        
        self.bucket_name = os.getenv('S3_BUCKET_NAME')
        self.region = os.getenv('AWS_REGION', 'us-east-1')
        self.endpoint_url = endpoint_url
    
    def generate_presigned_url(self, file_key: str, expiration: int = 3600) -> str:
        """
        Generate a presigned URL for uploading files to S3
        
        Args:
            file_key: The S3 object key (filename)
            expiration: URL expiration time in seconds (default 1 hour)
        
        Returns:
            Presigned URL string
        """
        try:
            response = self.s3_client.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': file_key,
                    'ContentType': 'image/jpeg'  # Adjust as needed
                },
                ExpiresIn=expiration
            )
            
            # For MinIO, replace internal Docker address with localhost
            if self.endpoint_url and 'minio:9000' in response:
                response = response.replace('minio:9000', 'localhost:9000')
            
            return response
        except ClientError as e:
            print(f"Error generating presigned URL: {e}")
            return None
    
    def generate_unique_filename(self, original_filename: str, user_id: str) -> str:
        """
        Generate a unique filename for S3 storage
        
        Args:
            original_filename: Original file name
            user_id: User ID for organizing files
        
        Returns:
            Unique S3 key
        """
        file_extension = original_filename.split('.')[-1] if '.' in original_filename else 'jpg'
        unique_id = str(uuid.uuid4())[:8]
        return f"images/{user_id}/{unique_id}.{file_extension}"
    
    def get_public_url(self, file_key: str) -> str:
        """
        Get the public URL for an S3 object
        
        Args:
            file_key: The S3 object key
        
        Returns:
            Public URL string
        """
        if self.endpoint_url:
            # MinIO local development - use localhost for external access
            external_url = self.endpoint_url.replace('minio:9000', 'localhost:9000')
            return f"{external_url}/{self.bucket_name}/{file_key}"
        else:
            # Production AWS S3
            return f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{file_key}"
    
    def delete_file(self, file_key: str) -> bool:
        """
        Delete a file from S3
        
        Args:
            file_key: The S3 object key to delete
        
        Returns:
            True if successful, False otherwise
        """
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=file_key)
            return True
        except ClientError as e:
            print(f"Error deleting file: {e}")
            return False