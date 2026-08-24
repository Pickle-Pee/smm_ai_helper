# app/agents/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
import logging
from typing import Any, Dict, List, Optional

from app.config import settings
from app.llm.openai_text import chat as openai_chat
from app.services.expert_instruction_composer import ExpertInstructionComposer
from .utils import safe_json_parse


log = logging.getLogger(__name__)
_instruction_composer = ExpertInstructionComposer()


def _default_temperature_for_model(model: str) -> Optional[float]:
    """
    Политика температуры:
    - по умолчанию НЕ отправляем temperature для gpt-5*, чтобы не ловить 400 и ретраи
    - если где-то нужна температура — задаём явно в конкретном месте
    """
    if model.startswith("gpt-5"):
        return None
    # если вдруг оставишь не-gpt-5 модель для light
    if model == settings.DEFAULT_TEXT_MODEL_LIGHT:
        return 0.7
    return None


class BaseAgent(ABC):
    """
    Базовый агент:
    - умеет звать LLM как обычный текст
    - умеет просить строго JSON (через response_format json_object)
    """

    system_prompt: str = "Ты — опытный SMM-специалист."
    model_override: str | None = None
    max_output_tokens_override: int | None = None

    async def llm_text(
        self,
        user_content: str,
        temperature: float | None = None,
        model: str | None = None,
    ) -> str:
        composed = _instruction_composer.compose(self.system_prompt)
        self._log_expert_core_version(composed.expert_core_version)
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": composed.rendered_text},
            {"role": "user", "content": user_content},
        ]
        selected_model = model or self.model_override or settings.DEFAULT_TEXT_MODEL_LIGHT

        # если temperature не задан — выставляем разумный дефолт по модели
        if temperature is None:
            temperature = _default_temperature_for_model(selected_model)

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
        temperature: float | None = None,
        model: str | None = None,
    ) -> Dict[str, Any]:
        response_mode_instructions = (
            "Отвечай строго валидным JSON-объектом без комментариев и текста до/после.\n"
            f"Структура ответа (подсказка): {json_schema_hint}"
        )
        composed = _instruction_composer.compose(
            self.system_prompt,
            response_mode_instructions=response_mode_instructions,
        )
        self._log_expert_core_version(composed.expert_core_version)
        messages: List[Dict[str, str]] = [
            {
                "role": "system",
                "content": composed.rendered_text,
            },
            {"role": "user", "content": instruction},
        ]

        selected_model = model or self.model_override or settings.DEFAULT_TEXT_MODEL_LIGHT

        if temperature is None:
            temperature = _default_temperature_for_model(selected_model)

        # Основной путь: structured output json_object
        raw, _usage = await openai_chat(
            messages=messages,
            model=selected_model,
            temperature=temperature,
            max_output_tokens=self.max_output_tokens_override,
            response_format={"type": "json_object"},
        )

        return safe_json_parse(raw)

    def _log_expert_core_version(self, version: str) -> None:
        log.info(
            "Expert Core instructions composed",
            extra={
                "expert_core_version": version,
                "agent_type": self.__class__.__name__,
            },
        )

    @abstractmethod
    async def run(self, brief: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        ...
