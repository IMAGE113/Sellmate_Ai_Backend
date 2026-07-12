import os
import boto3
from botocore.exceptions import ClientError
import logging

class S3Service:
    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
            region_name=os.getenv('AWS_REGION', 'ap-southeast-1')
        )
        self.bucket_name = os.getenv('S3_BUCKET_NAME')

    async def upload_file(self, file_content: bytes, object_name: str) -> str:
        """Upload a file to an S3 bucket"""
        if not self.bucket_name:
            logging.error("S3_BUCKET_NAME environment variable not set.")
            raise ValueError("S3 bucket name not configured.")

        try:
            self.s3_client.put_object(Bucket=self.bucket_name, Key=object_name, Body=file_content)
            logging.info(f"File {object_name} uploaded to {self.bucket_name}")
            return f"https://{self.bucket_name}.s3.{self.s3_client.meta.region_name}.amazonaws.com/{object_name}"
        except ClientError as e:
            logging.error(f"Error uploading file to S3: {e}")
            raise

s3_service = S3Service()
