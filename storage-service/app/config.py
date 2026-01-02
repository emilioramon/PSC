import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database
    database_url: str = os.getenv(
        "DATABASE_URL", 
        "postgresql://faas:faas123@localhost:5432/faas_storage"
    )
    
    # MinIO
    minio_endpoint: str = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    minio_access_key: str = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    minio_secret_key: str = os.getenv("MINIO_SECRET_KEY", "minioadmin")
    minio_secure: bool = os.getenv("MINIO_SECURE", "false").lower() == "true"
    
    # Buckets
    lambdas_bucket: str = "lambdas"
    encargos_input_bucket: str = "encargos-input"
    encargos_result_bucket: str = "encargos-result"
    
    # Limits
    max_zip_size: int = 100 * 1024 * 1024  # 100MB

settings = Settings()