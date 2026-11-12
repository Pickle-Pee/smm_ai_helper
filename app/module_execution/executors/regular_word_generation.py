"""Finite word/prefix complements using ordinary regular expressions only."""

ALPHABET = "abcdefghijklmnopqrstuvwxyzабвгдеёжзийклмнопрстуфхцчшщъыьэюя"
LETTERS = "A-Za-zА-Яа-яЁё"
WORD_CHARACTER = f"[{LETTERS}]"
SEPARATOR = f"[^{LETTERS}0-9]"


def character_class(letters):
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


def allowed_word_pattern(exact_words, *, prefixes=()):
    """Nonempty maximal words outside finite exact words and prefix families.

    An exact terminal requires further letters; a prefix terminal has no valid
    continuation. Nonterminal prefixes may end or diverge from the trie.
    """
    trie = {}
    for terminal, words in (("exact", exact_words), ("prefix", prefixes)):
        for word in sorted(words):
            if not word or any(letter not in ALPHABET for letter in word):
                raise ValueError("Expected nonempty lowercase alphabet word")
            node = trie
            for letter in word:
                node = node.setdefault(letter, {})
            node[terminal] = True

    def suffix(node, *, root=False):
        if "prefix" in node:
            return None
        children = sorted(letter for letter in node if len(letter) == 1)
        if not children:
            return WORD_CHARACTER + "+" if root or "exact" in node else WORD_CHARACTER + "*"
        branches = [""] if not root and "exact" not in node else []
        other_letters = set(ALPHABET) - set(children)
        if other_letters:
            branches.append(character_class(other_letters) + WORD_CHARACTER + "*")
        for letter in children:
            tail = suffix(node[letter])
            if tail is not None:
                branches.append(character_class((letter,)) + tail)
        return "(?:" + "|".join(branches) + ")"

    return suffix(trie, root=True)
