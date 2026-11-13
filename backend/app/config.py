from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ADROBOT_",
        env_file=Path(__file__).resolve().parents[2] / ".env",
        extra="ignore",
    )

    mode: Literal["demo", "keitaro", "readonly"] = "demo"
    database_url: str = "sqlite:///./adrobot.sqlite3"
    timezone: str = "Europe/Moscow"
    keitaro_url: str = ""
    keitaro_api_key: SecretStr = SecretStr("")

    @model_validator(mode="after")
    def validate_settings(self):
        ZoneInfo(self.timezone)
        if self.mode != "demo":
            url = urlsplit(self.keitaro_url)
            if (
                url.scheme != "https" or not url.hostname or url.username or url.password
                or url.path not in ("", "/") or url.query or url.fragment
            ):
                raise ValueError("ADROBOT_KEITARO_URL должен быть HTTPS-адресом без пути")
            if not self.keitaro_api_key.get_secret_value():
                raise ValueError("Для подключения Keitaro нужен ADROBOT_KEITARO_API_KEY")
        return self
