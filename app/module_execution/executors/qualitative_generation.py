"""Small generation filter for the observed count failure, not quantity validation."""
from .numeric_quantity import _CARDINALS


GENERATION_COUNT_WORDS = frozenset(("two", "два", "две", "двух", "двум", "двумя"))
assert GENERATION_COUNT_WORDS <= _CARDINALS
_ALPHABET = "abcdefghijklmnopqrstuvwxyzабвгдеёжзийклмнопрстуфхцчшщъыьэюя"
_LETTERS = "A-Za-zА-Яа-яЁё"
_WORD_CHARACTER = f"[{_LETTERS}]"
_SEPARATOR = f"[^{_LETTERS}0-9]"


def _character_class(letters):
    """Compress a finite explicit alphabet into ordinary character ranges."""
    characters = sorted({form for letter in letters for form in (letter, letter.upper())})
    ranges = []
    start = end = characters[0]
    for character in characters[1:]:
        if ord(character) == ord(end) + 1:
            end = character
            continue
        ranges.append(start + "-" + end if ord(end) - ord(start) > 1
                      else start + (end if end != start else ""))
        start = end = character
    ranges.append(start + "-" + end if ord(end) - ord(start) > 1
                  else start + (end if end != start else ""))
    return "[" + "".join(ranges) + "]"


def _allowed_word_pattern():
    """Complement the small observed-count trie using regular expressions.

    A word is allowed when it ends at a nonterminal prefix, diverges from the
    trie, or continues beyond a terminal leaf. No lookaround, flags or Unicode
    shorthand classes are needed by the provider's constrained decoder.
    """
    trie = {}
    for word in sorted(GENERATION_COUNT_WORDS):
        node = trie
        for letter in word:
            node = node.setdefault(letter, {})
        node[""] = True

    def suffix(node, *, root=False):
        children = sorted(letter for letter in node if letter)
        if not children:
            # Every leaf is a complete forbidden word: another character is
            # necessary before this word can be accepted.
            return _WORD_CHARACTER + "+"
        branches = [""] if not root and "" not in node else []
        other_letters = set(_ALPHABET) - set(children)
        if other_letters:
            branches.append(_character_class(other_letters) + _WORD_CHARACTER + "*")
        branches.extend(_character_class((letter,)) + suffix(node[letter])
                        for letter in children)
        return "(?:" + "|".join(branches) + ")"

    return suffix(trie, root=True)


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
