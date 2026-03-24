"""
Cronoi LS — Core Configuration
"""

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Cronoi LS"
    DEBUG: bool = False
    SECRET_KEY: str  # .env'den gelir
    
    # Database
    DATABASE_URL: str  # postgresql+asyncpg://user:pass@host/db
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379"
    
    # JWT
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    
    # CORS
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:5173",   # Vite dev server
        "https://app.cronoi.com",  # Production
    ]
    
    # AWS S3 / Cloudflare R2 (export dosyaları için)
    S3_BUCKET: str = ""
    S3_ENDPOINT_URL: str = ""
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    
    # Celery (async optimizer)
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    class Config:
        env_file = ".env"


settings = Settings()
