"""Thin capabilities over the existing single-attempt production transport."""
import httpx
from copy import deepcopy

from app.llm.openai_text import ModelResponseError
from app.orchestration_runtime.model_adapter import production_model_call
from app.product_context.errors import ExtractorUnavailableError
from .api_errors import ProviderUnavailable
from .contracts import CopilotContractError
from .interpreter import MarketingIntentInterpreter


def expected_provider_failure(exc):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, (httpx.HTTPError, TimeoutError, ModelResponseError)):
            return True
        # Only the project's transport wrapper is traversed, never arbitrary
        # application ValueError/AssertionError with an unrelated chained cause.
        if not isinstance(exc, RuntimeError):
            return False
        exc = exc.__cause__
    return False


async def application_model_call(**kwargs):
    try:
        return await production_model_call(**structured_arguments(kwargs))
    except Exception as exc:
        if not expected_provider_failure(exc):
            raise
        raise ProviderUnavailable() from exc


async def owned_site_extractor(**kwargs):
    try:
        return await production_model_call(**structured_arguments(kwargs))
    except Exception as exc:
        if not expected_provider_failure(exc):
            raise
        raise ExtractorUnavailableError("Owned-site extractor unavailable") from exc


def structured_arguments(kwargs):
    # Strict structured output requires every property, including nullable ones.
    # Keep the internal DTO unchanged; normalize only the provider wire schema.
    schema = deepcopy(kwargs["response_schema"])
    def normalize(value):
        if isinstance(value, dict):
            value.pop("default", None)
            if value.get("type") == "object":
                value["required"] = list(value.get("properties", {}))
                value["additionalProperties"] = False
            for child in value.values():
                normalize(child)
        elif isinstance(value, list):
            for child in value:
                normalize(child)
    normalize(schema)
    return {**kwargs, "response_schema": schema}


class PublicIntentInterpreter:
    def __init__(self, model_call):
        self.interpreter = MarketingIntentInterpreter(model_call)

    async def interpret(self, text):
        try:
            return await self.interpreter.interpret(text)
        except CopilotContractError as exc:
            # Here this is invalid provider intent, not a downstream application bug.
            raise ProviderUnavailable() from exc

    async def interpret_request(self, text):
        try:
            return await self.interpreter.interpret_request(text)
        except CopilotContractError as exc:
            raise ProviderUnavailable() from exc
