"""Single-attempt module capability over the existing Responses transport."""
from app.config import settings
from app.llm.openai_text import chat


async def production_model_call(*, instruction: str, text: str, response_schema: dict) -> str:
    raw, _usage = await chat(
        messages=[{"role": "system", "content": instruction}, {"role": "user", "content": text}],
        model=settings.DEFAULT_TEXT_MODEL_HARD,
        max_output_tokens=4000,
        response_format={"type": "json_schema", "name": "module_output", "strict": True,
                         "schema": response_schema},
        single_attempt=True,
    )
    # No parsing, repair, retries or persistence here. The executor fails closed.
    return raw
