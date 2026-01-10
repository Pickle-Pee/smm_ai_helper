from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    TELEGRAM_BOT_TOKEN: str
    API_BASE_URL: str = "http://localhost:8000"

    OPENAI_API_KEY: str = Field(..., min_length=1)
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"

    DEFAULT_TEXT_MODEL_LIGHT: str = "gpt-4o-mini"
    DEFAULT_TEXT_MODEL_HARD: str = "gpt-5-mini"
    DEFAULT_IMAGE_MODEL: str = "gpt-image-1"

    IMAGE_STORAGE_PATH: str = "/data/images"
    IMAGE_MAX_ITERS: int = 2

    HTTP_TIMEOUT: float = 60.0
    HTTP_RETRIES: int = 2
    HTTP_BACKOFF: float = 0.5

    class Config:
        env_file = ".env"


settings = Settings()
