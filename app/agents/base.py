# app/agents/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from app.config import settings
from app.llm.openai_text import chat as openai_chat
from .utils import safe_json_parse


class BaseAgent(ABC):
    """
    Базовый агент:
    - умеет звать LLM как обычный текст
    - умеет просить строго JSON по описанной схеме
    """

    system_prompt: str = "Ты — опытный SMM-специалист."
    model_override: str | None = None
    max_output_tokens_override: int | None = None

    async def llm_text(
        self,
        user_content: str,
        temperature: float = 0.7,
        model: str | None = None,
    ) -> str:
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]
        selected_model = model or self.model_override or settings.DEFAULT_TEXT_MODEL_LIGHT
        content, _usage = await openai_chat(
            messages=messages,
            model=selected_model,
            temperature=temperature,
            max_output_tokens=self.max_output_tokens_override,
        )
        return content

    async def llm_json(
        self,
        instruction: str,
        json_schema_hint: str,
        temperature: float = 0.7,
        model: str | None = None,
    ) -> Dict[str, Any]:
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
        selected_model = model or self.model_override or settings.DEFAULT_TEXT_MODEL_LIGHT
        raw, _usage = await openai_chat(
            messages=messages,
            model=selected_model,
            temperature=temperature,
            max_output_tokens=self.max_output_tokens_override,
            response_format={"type": "json_object"},
        )
        return safe_json_parse(raw)

    @abstractmethod
    async def run(self, brief: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        ...
