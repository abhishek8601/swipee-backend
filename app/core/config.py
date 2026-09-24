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

    # Storage
    STORAGE_DIR: Path = BASE_DIR / "storage" / "app" / "public"

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
