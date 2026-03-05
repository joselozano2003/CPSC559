import boto3
import os
from botocore.exceptions import ClientError


class BucketClient:
    def __init__(self):
        # Check if we're using MinIO (local development)
        endpoint_url = os.getenv('BUCKET_ENDPOINT_URL')
        if endpoint_url:
            self.s3_client = boto3.client(
                's3',
                endpoint_url=endpoint_url,
                aws_access_key_id=os.getenv('BUCKET_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('BUCKET_SECRET_ACCESS_KEY'),
                region_name=os.getenv('AWS_REGION', 'us-east-1')
            )
        else:
            # Production BUCKET
            self.s3_client = boto3.client('s3')
        
        self.bucket_name = os.getenv('BUCKET_NAME')
        self.region = os.getenv('AWS_REGION', 'us-east-1')
        self.endpoint_url = endpoint_url
    
    def generate_presigned_upload_url(self, file_key: str, expiration: int = 3600) -> str:
        """
        Generate a presigned URL for uploading files to Bucket
        
        Args:
            file_key: The Bucket object key (filename)
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
    
    def generate_presigned_download_url(self, file_key: str, expiration: int = 3600) -> str:
        try:
            response = self.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': file_key,
                },
                ExpiresIn=expiration
            )
            if self.endpoint_url and 'minio:9000' in response:
                response = response.replace('minio:9000', 'localhost:9000')
            return response
        except ClientError as e:
            print(f"Error generating presigned download URL: {e}")
            return None
    
    def generate_object_key(self, chunk_id: str) -> str:
        """
        Generate a storage key for a chunk.
        Args:
            chunk_id: The unique chunk identifier
        Returns:
            MinIO object key
        """
        return f"chunks/{chunk_id}"
    
    def get_public_url(self, file_key: str) -> str:
        """
        Get the public URL for an Bucket object
        
        Args:
            file_key: The Bucket object key
        
        Returns:
            Public URL string
        """
        if self.endpoint_url:
            # MinIO local development - use localhost for external access
            external_url = self.endpoint_url.replace('minio:9000', 'localhost:9000')
            return f"{external_url}/{self.bucket_name}/{file_key}"
        else:
            # Production BUCKET Bucket
            return f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{file_key}"
    
    def delete_file(self, file_key: str) -> bool:
        """
        Delete a file from Bucket
        
        Args:
            file_key: The Bucket object key to delete
        
        Returns:
            True if successful, False otherwise
        """
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=file_key)
            return True
        except ClientError as e:
            print(f"Error deleting file: {e}")
            return False