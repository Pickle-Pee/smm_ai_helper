"""Shared finite assurance detector and positive provider word grammar."""
import re
from functools import lru_cache


# Preserve the existing canonical detector exactly. Provider grammar is more
# conservative for suffixed English words; canonical source authority stays here.
ASSURANCE = re.compile(
    r"\b(?:гаранти\w*|опытн\w*|квалифицированн\w*|сертифицированн\w*|"
    r"профессиональн\w*|безусловн\w*|guarantee\w*|experienced|qualified|"
    r"certified|professional|unconditional\w*)\b", re.IGNORECASE)

STEMS = tuple("""гаранти опытн квалифицированн сертифицированн профессиональн
безусловн guarantee experienced qualified certified professional unconditional""".split())
ALPHABET = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя_")


def _character_class(values):
    codes = sorted(ord(char) for char in values)
    parts = []
    index = 0
    while index < len(codes):
        end = index
        while end + 1 < len(codes) and codes[end + 1] == codes[end] + 1:
            end += 1
        if end - index >= 2:
            parts.append(re.escape(chr(codes[index])) + "-" + re.escape(chr(codes[end])))
        else:
            parts.extend(re.escape(chr(value)) for value in codes[index:end + 1])
        index = end + 1
    return "[" + "".join(parts) + "]"


@lru_cache(maxsize=1)
def qualitative_assurance_pattern():
    """Exclude finite RU/EN word prefixes using positive regular alternatives.

    A word can end before a forbidden prefix, or diverge from its trie. Once it
    diverges, its remaining letters are unrestricted. Completed forbidden stems
    have no valid continuation. Every word consumes a trailing separator, so
    concatenating two short valid tokens cannot bypass a forbidden whole word.
    Literal supplied assertions are a separate schema branch, without this
    punctuation requirement. No lookaround, backreference or negated schema.
    """
    trie = {}
    for word in STEMS:
        node = trie
        for char in word:
            node = node.setdefault(char, {})
        node[None] = {}
    alphabet = _character_class(ALPHABET)

    def allowed_word(node, *, root=False):
        if None in node:
            return None
        excluded = {char for key in node for char in (key, key.upper())}
        options = [_character_class(ALPHABET - excluded) + alphabet + "*"]
        for char, child in sorted(node.items()):
            tail = allowed_word(child)
            if tail is not None:
                options.append(_character_class({char, char.upper()}) + tail)
        body = "(?:" + "|".join(options) + ")"
        return body if root else body + "?"

    separator = "[^0-9" + alphabet[1:-1] + "]"
    # Every word must end at a separator. This prevents splitting a forbidden
    # word into two individually valid tokens, without lookaround/backrefs.
    return "^(?:" + separator + "|" + allowed_word(trie, root=True) + separator + ")+$"


