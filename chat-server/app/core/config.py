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
    dashscope_api_key: str | None = os.getenv("DASHSCOPE_API_KEY")
    dashscope_model: str = os.getenv("DASHSCOPE_MODEL", "qwen-plus")
    dashscope_base_url: str | None = os.getenv("DASHSCOPE_BASE_URL")


settings = Settings()
