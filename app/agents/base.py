# app/agents/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from app.llm_provider import get_llm_provider
from .utils import safe_json_parse


class BaseAgent(ABC):
    """
    Базовый агент:
    - умеет звать LLM как обычный текст
    - умеет просить строго JSON по описанной схеме
    """

    system_prompt: str = "Ты — опытный SMM-специалист."

    async def llm_text(
        self,
        user_content: str,
        temperature: float = 0.7,
        model: str | None = None,
    ) -> str:
        provider = get_llm_provider()
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]
        return await provider.chat(messages, model=model, temperature=temperature)

    async def llm_json(
        self,
        instruction: str,
        json_schema_hint: str,
        temperature: float = 0.7,
        model: str | None = None,
    ) -> Dict[str, Any]:
        provider = get_llm_provider()
        messages: List[Dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    self.system_prompt
                    + "\n\nОтвечай строго валидным JSON без комментариев и текста до/после.\n"
                    f"Структура ответа (подсказка, не обязательно дословно): {json_schema_hint}"
                ),
            },
            {"role": "user", "content": instruction},
        ]
        raw = await provider.chat(messages, model=model, temperature=temperature)
        return safe_json_parse(raw)

    @abstractmethod
    async def run(self, brief: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        ...
