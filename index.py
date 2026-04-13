import os
import boto3
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from botocore.exceptions import ClientError
from typing import Optional
import uuid
from datetime import datetime

app = FastAPI(title="S3 File Uploader", version="1.1.0")

# CORS (adjust in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Config via App Runner Environment Variables
AWS_REGION     = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "invoice-processing-2025")


def get_s3_client():
    """
    Uses IAM Role automatically provided by AWS App Runner.
    DO NOT pass credentials manually.
    """
    return boto3.client("s3", region_name=AWS_REGION)


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h2>UI not found</h2>")


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    folder: Optional[str] = Form(default="uploads"),
    make_public: Optional[bool] = Form(default=False),
):
    if not S3_BUCKET_NAME:
        raise HTTPException(status_code=500, detail="S3_BUCKET_NAME is not configured.")

    # Create unique filename
    ext       = os.path.splitext(file.filename)[1]
    unique_id = uuid.uuid4().hex[:8]
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{timestamp}_{unique_id}{ext}"

    folder = folder.strip("/") if folder else "uploads"
    s3_key = f"{folder}/{safe_name}"

    try:
        s3 = get_s3_client()

        extra_args = {
            "ContentType": file.content_type or "application/octet-stream"
        }

        if make_public:
            extra_args["ACL"] = "public-read"

        contents = await file.read()

        s3.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=s3_key,
            Body=contents,
            **extra_args,
        )

        file_url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{s3_key}"

        return JSONResponse({
            "success": True,
            "message": "File uploaded successfully.",
            "file_name": file.filename,
            "s3_key": s3_key,
            "bucket": S3_BUCKET_NAME,
            "region": AWS_REGION,
            "url": file_url,
            "size_bytes": len(contents),
            "content_type": file.content_type,
        })

    except ClientError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/list")
async def list_files(folder: str = "uploads", max_keys: int = 50):
    if not S3_BUCKET_NAME:
        raise HTTPException(status_code=500, detail="S3_BUCKET_NAME is not configured.")

    try:
        s3 = get_s3_client()
        prefix = folder.strip("/") + "/"

        response = s3.list_objects_v2(
            Bucket=S3_BUCKET_NAME,
            Prefix=prefix,
            MaxKeys=max_keys,
        )

        files = []
        for obj in response.get("Contents", []):
            files.append({
                "key": obj["Key"],
                "name": obj["Key"].split("/")[-1],
                "size_bytes": obj["Size"],
                "last_modified": obj["LastModified"].isoformat(),
                "url": f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{obj['Key']}",
            })

        return {
            "success": True,
            "files": files,
            "count": len(files)
        }

    except ClientError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/delete")
async def delete_file(s3_key: str):
    if not S3_BUCKET_NAME:
        raise HTTPException(status_code=500, detail="S3_BUCKET_NAME is not configured.")

    try:
        s3 = get_s3_client()
        s3.delete_object(Bucket=S3_BUCKET_NAME, Key=s3_key)

        return {
            "success": True,
            "message": f"Deleted {s3_key}"
        }

    except ClientError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "bucket_configured": bool(S3_BUCKET_NAME),
        "region": AWS_REGION,
    }