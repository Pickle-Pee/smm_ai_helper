"""A bounded RU/EN generation subset, not numerical or provenance validation."""
from .numeric_quantity import _CARDINALS


def _cardinal_pattern():
    # Explicit case pairs and alphabet boundaries avoid provider-specific flags
    # and Unicode word-boundary semantics. Share the guard's finite vocabulary.
    return "|".join("".join("[" + letter + letter.upper() + "]" for letter in word)
                    for word in sorted(_CARDINALS))


_BOUNDARY = "[^A-Za-zА-Яа-яЁё]"
QUALITATIVE_GENERATION_PATTERN = (
    r"^(?![\s\S]*(?:^|" + _BOUNDARY + ")(?:" + _cardinal_pattern()
    + ")(?:" + _BOUNDARY + r"|$))[^0-9]*$"
)
# This deliberately also excludes harmless standalone cardinals such as "one
# of the options". Other languages/Unicode digits and actual source provenance
# remain the unchanged canonical guard's responsibility. Numeric quotations
# use their separate complete, source-bound numeric_context branch.
