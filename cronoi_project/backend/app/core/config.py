"""
Cronoi LS — Core Configuration
"""

from pydantic_settings import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):
    APP_NAME: str = "Cronoi LS"
    DEBUG: bool = False
    SECRET_KEY: str = "dev-secret-key-change-in-production"

    # Database
    DATABASE_URL: str

    # JWT
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # CORS
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:3000",
        "null",
    ]

    # Sprint 2'de aktif olacak (şimdilik opsiyonel)
    REDIS_URL: Optional[str] = None
    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None
    S3_BUCKET: Optional[str] = None
    S3_ENDPOINT_URL: Optional[str] = None
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
