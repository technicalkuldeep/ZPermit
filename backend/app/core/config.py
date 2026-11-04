"""Typed configuration loaded from environment variables and backend/.env."""

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ZPERMIT_",
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite:///./zpermit.db"
    cors_origins: list[str] = []
    dev_owner_id: str = "development-owner"
    dev_agent_id: str = "shopping-agent"
    dev_owner_credential: SecretStr | None = None
    dev_agent_credential: SecretStr | None = None
    bitrefill_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices(
        "BITREFILL_API_KEY", "ZPERMIT_BITREFILL_API_KEY"))
    bitrefill_live_purchases_enabled: bool = Field(default=False, validation_alias=AliasChoices(
        "BITREFILL_LIVE_PURCHASES_ENABLED", "ZPERMIT_BITREFILL_LIVE_PURCHASES_ENABLED"))
    bitrefill_timeout_seconds: float = Field(default=10, ge=0.1, le=30)
    bitrefill_preview_ttl_seconds: int = Field(default=60, ge=1, le=300)

    @field_validator("dev_owner_id", "dev_agent_id")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        if not value.strip() or len(value) > 128:
            raise ValueError("Development identities must contain 1 to 128 characters")
        return value.strip()

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("database_url must not be empty")
        return value

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, origins: list[str]) -> list[str]:
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
                or "*" in origin
            ):
                raise ValueError("CORS origins must be explicit HTTP(S) origins without paths")
            try:
                parsed.port
            except ValueError as exc:
                raise ValueError("CORS origin has an invalid port") from exc
        return origins


@lru_cache
def get_settings() -> Settings:
    return Settings()
