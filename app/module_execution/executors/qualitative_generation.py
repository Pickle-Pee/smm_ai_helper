"""Small generation filter for the observed count failure, not quantity validation."""
from .numeric_quantity import _CARDINALS
from .regular_word_generation import SEPARATOR as _SEPARATOR, allowed_word_pattern


GENERATION_COUNT_WORDS = frozenset(("two", "два", "две", "двух", "двум", "двумя"))
assert GENERATION_COUNT_WORDS <= _CARDINALS


def _allowed_word_pattern():
    return allowed_word_pattern(GENERATION_COUNT_WORDS)


# Word branches must be maximal. Repeating adjacent allowed prefixes would
# accept a forbidden word by splitting it, e.g. д + ва. Each nonempty word is
# separated from its successor by at least one separator. Anchors occur only
# at the outside: a provider diagnostic returned empty/incomplete for an end
# anchor inside a repeated alternative, even on a tiny otherwise valid trie.
_WORD_PATTERN = _allowed_word_pattern()
QUALITATIVE_GENERATION_PATTERN = (
    "^" + _SEPARATOR + "*(?:" + _WORD_PATTERN
    + "(?:" + _SEPARATOR + "+" + _WORD_PATTERN + ")*)?" + _SEPARATOR + "*$"
)
# This covers the observed "два варианта"/"two options" generation failure.
# Other quantities, Unicode digits and source provenance remain the unchanged
# full canonical guard's responsibility. Absence of a pattern rejection proves
# nothing about numerical safety. Complete source-bound quotations still use
# numeric_context. A full-vocabulary grammar failed actual CMO generation.
