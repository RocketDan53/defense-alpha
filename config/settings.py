"""
Defense Alpha Intelligence Engine - Configuration

Loads settings from environment variables with sensible defaults.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

# Load .env file
load_dotenv()

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    DATABASE_URL: str = Field(
        default=f"sqlite:///{PROJECT_ROOT}/data/defense_alpha.db"
    )

    @property
    def project_root(self) -> Path:
        """Return project root directory."""
        return PROJECT_ROOT

    # Application
    DEBUG: bool = Field(default=False)
    LOG_LEVEL: str = Field(default="INFO")

    # Data sources (API keys loaded from environment)
    USASPENDING_API_KEY: str = Field(default="")
    CRUNCHBASE_API_KEY: str = Field(default="")
    SAM_GOV_API_KEY: str = Field(default="")

    # LLM API
    ANTHROPIC_API_KEY: str = Field(default="")

    # Entity resolution settings
    FUZZY_MATCH_THRESHOLD: int = Field(default=85)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
