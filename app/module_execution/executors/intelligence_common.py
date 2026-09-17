"""Additional conservative output checks; acceptance still belongs to Quality Gates."""
import json
import re

from .common import BaseExecutor, plain


def supported_text(statement, local, parents):
    return tuple(local[e].value if isinstance(local[e].value, str)
                 else json.dumps(plain(local[e].value), ensure_ascii=False) for e in statement.evidence_ids) + tuple(
        str(parents[p].value) for p in statement.parent_claim_ids)


def require_supported_numbers(text, supports):
    # Numerical statements must be supplied verbatim, not assembled by a model
    # from unrelated numbers (including budgets, sample sizes and percentages).
    if re.search(r"\d", text) and not any(text in source for source in supports):
        raise ValueError("Numerical assertion must be an exact supplied statement")


class IntelligenceExecutor(BaseExecutor):
    def build_result(self, request, output, evidence, parents):
        # Code-added support/limitations must retain the same bounded wire shape.
        self.output_type.model_validate(output.model_dump())
        names = [s.output_name for s in output.outputs]
        if len(names) != len(set(names)):
            raise ValueError("Exactly one statement per requested output is required")
        return super().build_result(request, output, evidence, parents)

    def validate_statement(self, statement, local, parents):
        supports = supported_text(statement, local, parents)
        require_supported_numbers(statement.text, supports)
        if statement.kind == "OBSERVATION" and not any(statement.text in s for s in supports):
            raise ValueError("Observations must quote supplied support")
