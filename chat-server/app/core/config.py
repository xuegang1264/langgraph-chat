import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Chat Server")
    app_version: str = os.getenv("APP_VERSION", "0.1.0")
    sqlite_path: str = os.getenv("SQLITE_PATH", "data/checkpoints.sqlite")
    app_log_level: str = os.getenv("APP_LOG_LEVEL", "INFO")
    tokenplan_api_key: str | None = os.getenv("TOKENPLAN_API_KEY")
    tokenplan_model: str = os.getenv("TOKENPLAN_MODEL", "qwen-plus")
    tokenplan_base_url: str | None = os.getenv("TOKENPLAN_BASE_URL")
    qweather_api_key: str | None = os.getenv("QWEATHER_API_KEY")
    qweather_jwt: str | None = os.getenv("QWEATHER_JWT")
    qweather_private_key: str | None = os.getenv("QWEATHER_PRIVATE_KEY")
    qweather_developer_id: str | None = os.getenv("QWEATHER_DEVELOPER_ID") or os.getenv("DEVELOPER_ID")
    qweather_project_id: str | None = os.getenv("QWEATHER_PROJECT_ID") or os.getenv("PROJECT_ID")
    qweather_credential_id: str | None = os.getenv("QWEATHER_CREDENTIAL_ID") or os.getenv("CREDENTIAL_ID")
    qweather_api_host: str = os.getenv("QWEATHER_API_HOST", "https://devapi.qweather.com")


settings = Settings()
