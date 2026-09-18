from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    TELEGRAM_BOT_TOKEN: str
    API_BASE_URL: str = "http://localhost:8000"
    BOT_BACKEND_TOKEN: str = ""
    REDIS_URL: str = "redis://redis:6379/0"
    WORKER_CONCURRENCY: int = Field(default=2, ge=1, le=8)
    # Legacy WORKER_CONCURRENCY remains the fixed lane count only.
    GRAPH_WORKER_CONCURRENCY: int = Field(default=1, ge=1, le=8)
    GRAPH_TIMEOUT_SECONDS: int = Field(default=300, ge=5, le=900)
    GRAPH_LEASE_SECONDS: int = Field(default=330, ge=6, le=960)
    WORKFLOW_TIMEOUT_SECONDS: int = Field(default=240, ge=5, le=900)
    TASK_FINALIZATION_TIMEOUT_SECONDS: int = Field(default=240, ge=5, le=900)

    OPENAI_API_KEY: str = Field(..., min_length=1)
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"

    DEFAULT_TEXT_MODEL_LIGHT: str = "gpt-5-mini"
    DEFAULT_TEXT_MODEL_HARD: str = "gpt-5"
    DEFAULT_IMAGE_MODEL: str = "gpt-image-1"
    FALLBACK_IMAGE_MODEL: str = "dall-e-3"

    IMAGE_STORAGE_PATH: str = "/data/images"
    IMAGE_MAX_ITERS: int = 2

    HTTP_TIMEOUT: float = 60.0
    HTTP_RETRIES: int = 2
    HTTP_BACKOFF: float = 0.5

    @model_validator(mode="after")
    def graph_execution_window(self):
        if not 0 < self.HTTP_TIMEOUT < self.GRAPH_TIMEOUT_SECONDS < self.GRAPH_LEASE_SECONDS:
            raise ValueError("Require 0 < HTTP_TIMEOUT < GRAPH_TIMEOUT_SECONDS < GRAPH_LEASE_SECONDS")
        return self

    class Config:
        env_file = ".env"

settings = Settings()


TOKEN_BUDGETS: dict[str, int] = {
    "default": 1200,
    "summary": 1200,
    "facts_json": 1500,
    "qc_json": 1200,
    "image_brief": 1500,
    "copy": 1400,
    "strategy": 2500,
    "analysis": 2500,
    "url_insights_json": 2200,
}

MAX_OUTPUT_TOKENS_CAP: int = 4000
