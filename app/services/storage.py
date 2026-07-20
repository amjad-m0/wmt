import boto3
from botocore.config import Config
import uuid
import os
from app.config import get_settings

settings = get_settings()


def get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto"
    )


def _r2_configured() -> bool:
    """R2 is only considered configured if real (non-placeholder) values are set"""
    return bool(settings.R2_ACCOUNT_ID) and "your-" not in settings.R2_ACCOUNT_ID


async def upload_file(file_content: bytes, filename: str, content_type: str = "image/jpeg") -> str:
    """Upload file to R2 and return public URL"""
    if not _r2_configured():
        # Save locally if R2 not configured (dev mode)
        local_path = f"uploads/{filename}"
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(file_content)
        return f"/static/uploads/{filename}"

    client = get_r2_client()
    key = f"wms/{filename}"
    client.put_object(
        Bucket=settings.R2_BUCKET_NAME,
        Key=key,
        Body=file_content,
        ContentType=content_type,
    )
    return f"{settings.R2_PUBLIC_URL}/{key}"


async def upload_photo(file_bytes: bytes, folder: str = "photos") -> str:
    """Generate unique filename and upload"""
    ext = "jpg"
    filename = f"{folder}/{uuid.uuid4().hex}.{ext}"
    return await upload_file(file_bytes, filename, "image/jpeg")


async def upload_pdf(pdf_bytes: bytes, folder: str = "receipts") -> str:
    """Upload PDF receipt"""
    filename = f"{folder}/{uuid.uuid4().hex}.pdf"
    return await upload_file(pdf_bytes, filename, "application/pdf")
