"""Application settings, read from environment variables only (never from files)."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    database_url: str = "postgresql+psycopg://localetl:localetl@127.0.0.1:5432/localetl"
    test_database_url: str = "postgresql+psycopg://localetl:localetl@127.0.0.1:5432/localetl_test"
    localetl_data_dir: Path = Path("./data")
    localetl_max_upload_mb: int = Field(default=100, ge=1)
    localetl_cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    localetl_chunk_rows: int = Field(default=50_000, ge=1)

    @field_validator("localetl_cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("localetl_data_dir", mode="after")
    @classmethod
    def _resolve_data_dir(cls, value: Path) -> Path:
        # A relative data dir is relative to the repository root (architecture section 4).
        return value if value.is_absolute() else (REPO_ROOT / value).resolve()

    @property
    def max_upload_bytes(self) -> int:
        return self.localetl_max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
