# POSITIONING numerical assertion grounding

## Defect and boundary

During synthetic course acceptance, POSITIONING emitted a validation_plan with
an invented sample of 5–10 learners, a completion threshold above 50%, and a
promotional review of 5–10 photographs. The supplied course duration was six
weeks; it did not supply those samples or decision thresholds. Labeling the
statement RECOMMENDATION did not make the invented numbers supported.

POSITIONING inherited BaseExecutor and enforced its seed/product support rules,
but did not call the existing numerical assertion guard used by the intelligence
executors. Its statement therefore passed schema, local validation and gates.
The regression retains the actual synthetic provider statement, without the
Telegram renderer's recommendation/confidence suffix. Before this change the
executor accepted that fixture; the regression failed because no error arose.

## Acceptance change

After its existing missing-seed, differentiation and product-truth checks,
PositioningExecutor.validate_statement calls the existing supported_text and
require_supported_numbers helpers. Any statement containing a decimal digit
must occur verbatim within one of that statement's cited local evidence values
or accepted parent assertion texts. A supplied number alone cannot authorize a
new rationale, derived number or statement assembled from independent sources.
The source-selection and assertion_support rules remain authoritative; CMO
numeric_context does not become numerical assertion evidence downstream.

Failure uses the existing NUMERICAL_SUPPORT_REQUIRED semantic rule and
statement_semantics_invalid stage. It is not retried. The provider text is not
repaired, deduplicated, shortened or removed to obtain acceptance. Existing
seed/product semantic checks retain precedence when multiple rules fail.
Qualitative recommendations remain allowed. Exact supported numerical text,
including the supplied course duration, remains allowed from cited local data
or accepted parent assertions.

The instruction explicitly requests qualitative statements, except supported
verbatim numerical assertions, and forbids invented thresholds, sample sizes,
budgets, deadlines and calculated/combined numbers. This instruction improves
model guidance; deterministic local validation, rather than stochastic prompt
compliance, enforces the boundary.

## Compatibility and validation

This tightens quality acceptance for new POSITIONING results. Previously
accepted invented numerical statements will now fail; this is intentional.
There is no persisted schema/DTO, registry or migration change. Stored artifacts
remain readable and are not rewritten or retroactively repaired. Both original
and projected provider schemas retain the same structural contracts.

Regression coverage includes the synthetic incident statement, unsupplied
thresholds/samples/budgets/deadlines/numbered lists and Unicode decimal digits,
exact local/parent numeric support, uncited sources, invented rationales and
calculated/assembled numbers, qualitative controls, existing semantic precedence,
and the production HTTP adapter with projection disabled and enabled. Each
rejected model response has one model call and no automatic repair or retry.

The composed instruction changes from 53367 to 53673 UTF-8 bytes. Its current
SHA-256 is 9e3ae6760899dbc4679b4db5fdac8d20632b042848a77e8a51789b664fe3bd24.
Offline regressions do not establish live completion rates or strategy quality;
new live acceptance remains a separate release check.
