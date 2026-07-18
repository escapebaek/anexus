import os
import re
import requests
import jwt
import boto3
from botocore.config import Config as BotoConfig
from django.core.files.storage import Storage
from django.conf import settings
from datetime import datetime, timedelta
from storages.backends.s3boto3 import S3Boto3Storage

class SupabaseStorage(Storage):
    def __init__(self):
        self.supabase_url = settings.SUPABASE_URL
        self.supabase_key = settings.SUPABASE_KEY
        self.supabase_secret = settings.SUPABASE_JWT_SECRET
        self.bucket = settings.SUPABASE_STORAGE_BUCKET

    def _generate_jwt(self):
        payload = {
            "role": "authenticated",
            "exp": datetime.utcnow() + timedelta(hours=1)
        }
        token = jwt.encode(payload, self.supabase_secret, algorithm="HS256")
        return token

    def _save(self, name, content):
        # 파일의 바이너리 데이터를 읽음
        file_data = content.read()
        url = f"{self.supabase_url}/storage/v1/object/{self.bucket}/{name}"
        headers = {
            "apikey": self.supabase_key,
            "Authorization": f"Bearer {self.supabase_key}",
            "Content-Type": content.content_type
        }
        response = requests.post(url, headers=headers, data=file_data)
        if response.status_code != 200:
            raise Exception(f"Failed to upload file to Supabase: {response.text}")
        return name

    def url(self, name):
        return f"{self.supabase_url}/storage/v1/object/public/{self.bucket}/{name}"
    
    def exists(self, name):
        url = f"{self.supabase_url}/storage/v1/object/public/{self.bucket}/{name}"
        response = requests.head(url)
        return response.status_code == 200
    
    def size(self, name):
        url = f"{settings.SUPABASE_URL}/storage/v1/object/{settings.SUPABASE_STORAGE_BUCKET}/{name}"
        response = requests.head(url, headers={
            'apikey': settings.SUPABASE_KEY,
            'Authorization': f"Bearer {settings.SUPABASE_KEY}"
        })
        return int(response.headers.get('Content-Length', 0))


class PaperStorage(S3Boto3Storage):
    """
    Private object storage for journal PDFs, backed by Backblaze B2 (S3-compatible API).
    Bucket is kept private; access is only ever granted via short-lived presigned
    URLs issued from generate_paper_url() to logged-in/approved users.
    """
    bucket_name = settings.B2_BUCKET
    endpoint_url = settings.B2_ENDPOINT_URL
    access_key = settings.B2_KEY_ID
    secret_key = settings.B2_APPLICATION_KEY
    region_name = settings.B2_REGION
    default_acl = 'private'
    file_overwrite = False
    querystring_auth = True
    custom_domain = None


def _b2_client():
    return boto3.client(
        's3',
        endpoint_url=settings.B2_ENDPOINT_URL,
        aws_access_key_id=settings.B2_KEY_ID,
        aws_secret_access_key=settings.B2_APPLICATION_KEY,
        config=BotoConfig(signature_version='s3v4'),
        region_name=settings.B2_REGION,
    )


def _safe_filename(name, fallback='paper.pdf'):
    name = re.sub(r'[^A-Za-z0-9._\-]+', '_', name).strip('_')
    return f"{name}.pdf" if name else fallback


def generate_paper_url(key, disposition='inline', filename=None, expires_in=None):
    """
    Issue a short-lived presigned B2 URL for a paper PDF.
    disposition='inline' -> render in the in-page PDF reader
    disposition='attachment' -> force a browser download
    Callers must gate access (login/approval check) before calling this.
    """
    if not key:
        return None
    expires_in = expires_in or settings.B2_PRESIGNED_URL_EXPIRE
    params = {
        'Bucket': settings.B2_BUCKET,
        'Key': key,
        'ResponseContentType': 'application/pdf',
    }
    if disposition == 'attachment':
        params['ResponseContentDisposition'] = f'attachment; filename="{_safe_filename(filename or key)}"'
    else:
        params['ResponseContentDisposition'] = 'inline'
    return _b2_client().generate_presigned_url('get_object', Params=params, ExpiresIn=expires_in)