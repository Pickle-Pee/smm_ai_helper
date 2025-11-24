# app/llm_provider.py
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Literal, Optional

import httpx

from app.config import settings


Role = Literal["system", "user", "assistant"]


class LLMProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> str:
        ...


class OpenRouterProvider(LLMProvider):
    """
    Пример провайдера через OpenRouter (можно использовать их бесплатные модели
    типа llama-3, qwen, mistral, которые часто дают приличное качество).
    https://openrouter.ai/
    """

    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1") -> None:
        self.api_key = api_key
        self.base_url = base_url

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> str:
        if model is None:
            # Можешь выбрать любую из бесплатных/дешёвых моделей, типа:
            # "meta-llama/llama-3.1-8b-instruct:free" или аналог
            model = "meta-llama/llama-3.1-8b-instruct:free"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://your-app-url.example",  # можешь подставить свой домен/бота
            "X-Title": "SMM Swarm",
        }

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]


class LocalOllamaProvider(LLMProvider):
    """
    Провайдер для локального Ollama (https://ollama.com/).
    Ты ставишь Ollama, запускаешь, качаешь модель (например, llama3), и этот код
    шлёт запросы на http://localhost:11434.
    """

    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        self.base_url = base_url

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> str:
        if model is None:
            model = "llama3"  # или любая другая, которую ты скачал: qwen2, mistral и т.п.

        # Для Ollama формат другой
        prompt = ""
        for m in messages:
            role = m["role"]
            content = m["content"]
            prompt += f"{role.upper()}: {content}\n"
        prompt += "ASSISTANT:"

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "options": {"temperature": temperature},
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/api/generate",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["response"]


# Глобальный фабричный метод, чтобы менять провайдера одной строкой

_llm_provider: Optional[LLMProvider] = None


def get_llm_provider() -> LLMProvider:
    global _llm_provider
    if _llm_provider is None:
        # Вариант 1: локальная модель через Ollama (полностью бесплатно, кроме железа)
        _llm_provider = LocalOllamaProvider()

        # Вариант 2: OpenRouter (бесплатные/дешёвые модели, нужен API-ключ)
        # from app.config import settings
        # _llm_provider = OpenRouterProvider(api_key=settings.OPENROUTER_API_KEY)

    return _llm_provider
