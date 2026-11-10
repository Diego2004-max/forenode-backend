from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Forenode AI Enterprise Core"
    app_version: str = "4.0.0"
    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = Field(min_length=1)
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=60, ge=5, le=1440)
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:4200"]
    inventory_max_age_hours: int = Field(default=72, ge=1, le=720)
    weather_timeout_seconds: float = Field(default=10.0, ge=1.0, le=30.0)
    supabase_url: str | None = None
    supabase_jwt_secret: str | None = None
    admin_email: str | None = None
    admin_recovery_password: str | None = Field(default=None, min_length=10)

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()

