"""Additional conservative output checks; acceptance still belongs to Quality Gates."""
import json
from pydantic import ValidationError

from .common import (
    BaseExecutor, ResultContractError, ResultFailureRule, SemanticRule,
    StatementSemanticsError, plain,
)
from .claim_support import assertion_support
from .numeric_quantity import has_numeric_quantity


def supported_text(statement, local, parents):
    return tuple(local[e].value if isinstance(local[e].value, str)
                 else json.dumps(plain(local[e].value), ensure_ascii=False) for e in statement.evidence_ids) + tuple(
        text for p in statement.parent_claim_ids for text in assertion_support(parents[p].value))


def require_supported_numbers(text, supports):
    # Numerical statements must be supplied verbatim, not assembled by a model
    # from unrelated numbers (including budgets, sample sizes and percentages).
    if has_numeric_quantity(text) and not any(text in source for source in supports):
        raise StatementSemanticsError(SemanticRule.NUMERICAL_SUPPORT_REQUIRED)


class IntelligenceExecutor(BaseExecutor):
    def build_result(self, request, output, evidence, parents):
        # Code-added support/limitations must retain the same bounded wire shape.
        try:
            self.output_type.model_validate(output.model_dump())
        except ValidationError:
            raise ResultContractError(ResultFailureRule.POST_MUTATION_PYDANTIC_INVALID) from None
        names = [s.output_name for s in output.outputs]
        if len(names) != len(set(names)):
            raise ResultContractError(ResultFailureRule.OUTPUT_DUPLICATE_NAMES,
                                      output_index=next(i for i, name in enumerate(names) if name in names[:i]))
        return super().build_result(request, output, evidence, parents)

    def validate_statement(self, statement, local, parents):
        supports = supported_text(statement, local, parents)
        require_supported_numbers(statement.text, supports)
        if statement.kind == "OBSERVATION" and not any(statement.text in s for s in supports):
            raise ValueError("Observations must quote supplied support")
