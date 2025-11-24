from pydantic import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    TELEGRAM_BOT_TOKEN: str
    API_BASE_URL: str = "http://localhost:8000"

    # Для open-source LLM через OpenRouter (опционально)
    OPENROUTER_API_KEY: str | None = None

    class Config:
        env_file = ".env"


settings = Settings()
