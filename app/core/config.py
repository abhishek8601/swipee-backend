import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent

class Settings(BaseSettings):
    BASE_DIR: Path = BASE_DIR
    APP_NAME: str = "Swipee"
    APP_ENV: str = "local"
    APP_DEBUG: bool = True
    APP_URL: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:5173"
    SECRET_KEY: str = "swipee-secret-key-change-in-production-1234567890abcdef"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Database
    DB_CONNECTION: str = "mysql"
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_DATABASE: str = "swipee"
    DB_USERNAME: str = "root"
    DB_PASSWORD: str = "root"

    # SQLite fallback if MySQL is offline or not preferred
    USE_SQLITE_FALLBACK: bool = True

    # Try-on
    TRYON_DRIVER: str = "pollinations"
    TRYON_PHOTOROOM_KEY: str = ""
    HUGGINGFACE_TOKEN: str = ""

    # Demo escape hatch (mirrors Laravel's tryon.allow_placeholder_publish).
    # Placeholder looks (stub canvas, Pollinations "imagined garment") must not
    # reach shoppers; flip only for demos.
    TRYON_ALLOW_PLACEHOLDER_PUBLISH: bool = False

    # Reel (AI video) generation. The keyframe comes from TRYON_DRIVER; this
    # provider animates it. Empty VIDEO_PROVIDER means "not configured" and the
    # API refuses to queue reels rather than pretending to render one.
    VIDEO_PROVIDER: str = ""  # replicate
    REPLICATE_API_TOKEN: str = ""
    REPLICATE_VIDEO_MODEL: str = ""  # "owner/name" of an image-to-video model on replicate.com
    REPLICATE_IMAGE_INPUT_KEY: str = "image"
    REPLICATE_DURATION_INPUT_KEY: str = ""  # set only if the chosen model accepts a duration input
    VIDEO_JOB_TIMEOUT_SECONDS: int = 900
    VIDEO_MAX_BYTES: int = 200 * 1024 * 1024
    REEL_DAILY_LIMIT_PER_MERCHANT: int = 20
    REEL_MAX_ACTIVE_PER_MERCHANT: int = 3

    # Google Drive storage for generated reels. Auth is either a service account
    # (JSON key file kept outside the repo; folder must live in a Shared Drive,
    # service accounts have no My Drive quota) or an OAuth refresh token.
    GOOGLE_DRIVE_FOLDER_ID: str = ""
    GOOGLE_SERVICE_ACCOUNT_FILE: str = ""
    GOOGLE_DRIVE_CLIENT_ID: str = ""
    GOOGLE_DRIVE_CLIENT_SECRET: str = ""
    GOOGLE_DRIVE_REFRESH_TOKEN: str = ""
    GOOGLE_DRIVE_SCOPE: str = "https://www.googleapis.com/auth/drive"

    # Storage
    STORAGE_DIR: Path = BASE_DIR / "storage" / "app" / "public"
    # Not mounted under /storage: generated videos are served through the
    # access-controlled /api/reels/{id}/video endpoint only.
    PRIVATE_STORAGE_DIR: Path = BASE_DIR / "storage" / "app" / "private"

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def database_url(self) -> str:
        if self.DB_CONNECTION == "mysql":
            # pymysql URL
            pwd = f":{self.DB_PASSWORD}" if self.DB_PASSWORD else ""
            return f"mysql+pymysql://{self.DB_USERNAME}{pwd}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_DATABASE}?charset=utf8mb4"
        return f"sqlite:///{BASE_DIR}/swipee.db"

settings = Settings()
os.makedirs(settings.STORAGE_DIR, exist_ok=True)
os.makedirs(settings.PRIVATE_STORAGE_DIR, exist_ok=True)
