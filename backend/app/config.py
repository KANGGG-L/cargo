from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]  # repo root (cargo/)


class Settings(BaseSettings):
    """Runtime settings, overridable via backend/.env or environment variables."""

    model_config = SettingsConfigDict(env_file=ROOT_DIR / "backend" / ".env", extra="ignore")

    # LLM: any OpenAI-compatible endpoint (GLM / DeepSeek / OpenAI / Ollama).
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    llm_api_key: str = ""  # empty -> mock mode
    llm_model: str = "glm-4-flash"

    db_path: Path = ROOT_DIR / "data" / "control_tower.sqlite"

    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def is_mock_mode() -> bool:
    return not get_settings().llm_api_key
