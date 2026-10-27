"""
Hikvision AI CCTV Platform — Application Configuration
Loads all settings from environment variables via Pydantic Settings.
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration loaded from .env file and environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Hikvision NVR ---
    hik_nvr_ip: str = "192.168.1.100"
    hik_nvr_port: int = 554
    hik_nvr_user: str = "admin"
    hik_nvr_password: str = "YourNVRPassword123"

    # --- Hikvision DVR ---
    hik_dvr_ip: str = "192.168.1.101"
    hik_dvr_port: int = 554
    hik_dvr_user: str = "admin"
    hik_dvr_password: str = "YourDVRPassword123"

    # --- CP Plus Camera ---
    cpplus_cam_ip: str = "192.168.1.120"
    cpplus_cam_port: int = 554
    cpplus_cam_user: str = "admin"
    cpplus_cam_password: str = "YourCPPlusPassword123"

    # --- PostgreSQL ---
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "cctv_ai"
    postgres_user: str = "cctv_admin"
    postgres_password: str = "SecureDbPassword!2026"

    # --- Redis ---
    redis_host: str = "redis"
    redis_port: int = 6379

    # --- MQTT ---
    mqtt_host: str = "mosquitto"
    mqtt_port: int = 1883

    # --- Frigate ---
    frigate_host: str = "frigate"
    frigate_port: int = 5000

    # --- Telegram ---
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # --- FastAPI ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_secret_key: str = "change-this-to-a-random-secret-key-in-production"

    # --- Media Storage ---
    media_dir: str = "/app/media"
    media_max_size_gb: int = 40
    media_retention_days: int = 21

    # --- AI Model Paths ---
    yolo_model_path: str = "/app/models/yolov8n.onnx"
    insightface_model_path: str = "/app/models/insightface"
    lpr_model_path: str = "/app/models/lprnet.onnx"
    clip_model_path: str = "/app/models/mobileclip_s2.onnx"

    @property
    def database_url(self) -> str:
        """Async PostgreSQL connection string for SQLAlchemy."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        """Sync PostgreSQL connection string for migrations."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    @property
    def media_path(self) -> Path:
        return Path(self.media_dir)


# Singleton instance
settings = Settings()
