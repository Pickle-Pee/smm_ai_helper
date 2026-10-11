"""Offline structural sizing, not provider generation or semantic acceptance.

Run from the repository root with a Python environment containing requirements.txt
and optional tiktoken. Prints counts only; all source material is synthetic.
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tiktoken
from jsonschema import Draft202012Validator

from app.module_execution.executors.intelligence_schemas import StrategyOutput
from app.module_registry import ModuleId, ModuleRegistry


def main():
    encoding = tiktoken.get_encoding("o200k_base")
    names = ModuleRegistry.load("1.3.0").get(ModuleId.VIRTUAL_CMO).outputs
    prose = "Проверить спрос на форматы посещения без предположений о рентабельности. Сопоставить потребности семей с подтверждёнными форматами посещения. "
    quote = "Полный день стоит 30 000 рублей в месяц; неполный день — 18 000 рублей. "
    parents = ["clm_" + hashlib.sha256(str(i).encode()).hexdigest()[:48] for i in range(8)]
    validator = Draft202012Validator(StrategyOutput.model_json_schema())
    for summary_chars in (250, 500, 1000):
        for quote_chars in (100, 300, 1000):
            payload = dict(outputs=[dict(
                output_name=name, text=(prose * 40)[:summary_chars],
                kind="HYPOTHESIS", confidence="MEDIUM",
                items=[prose] * (1 if name == "main_growth_constraint" else 3),
                evidence_ids=[], parent_claim_ids=parents,
                numeric_context=[dict(support_id=parents[i], quote=(quote * 20)[:quote_chars])
                                 for i in range(3)],
            ) for name in names], assumptions=[prose] * 2, limitations=[prose] * 2)
            StrategyOutput.model_validate(payload)
            validator.validate(payload)
            raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            before = dict(payload, outputs=[{k: v for k, v in s.items() if k != "numeric_context"}
                                            for s in payload["outputs"]])
            previous = json.dumps(before, ensure_ascii=False, separators=(",", ":"))
            print(json.dumps(dict(summary_chars=summary_chars, quote_chars=quote_chars,
                visible_tokens=len(encoding.encode(raw)),
                before_numeric_context_tokens=len(encoding.encode(previous)), characters=len(raw))))


if __name__ == "__main__":
    main()
