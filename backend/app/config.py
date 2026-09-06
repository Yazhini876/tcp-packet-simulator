from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    max_sessions: int = 200
    """Safety cap on concurrently held in-memory sessions."""


settings = Settings()
