# POSITIONING cardinal words during generation

The exact restored workshop probe on1921e53 completed but failed numerical
validation at points_of_difference. A network-none inventory of all16statements
found only the unsupported cardinal word «одном»; there were no remaining
assurance violations. The response was not repaired, accepted, retried or
persisted. Candidate19 was not deployed; production remained105ffcb.

The positive free-text grammar now reuses the exact immutable cardinal vocabulary
from the existing unit-aware has_numeric_quantity guard. Exact cardinal tokens
cannot terminate a free word, while ordinary continuations remain available
(одна -> однако, три -> триггер, one -> oneself). Assurance prefixes still cannot
continue at all. The shared trie uses positive regular alternatives, mandatory
word separators and no lookaround; the resulting pattern is shared once in $defs.
Digits and cardinal words require a complete supplied assertion alternative.

The provider branch deliberately excludes cardinal articles even without counted
units. The original canonical guard remains unit-aware and unchanged; ordinals,
word quantities, Unicode digits and actual source authority keep their existing
semantics. The lexicon accessor returns a frozenset, not a second editable table.
Supplied complete assertions preserve word/digit quantities and original text,
but never add an implicit citation. No parsing, respelling, number calculation,
source/response normalization, filtering, hidden retry or budget increase.

The explicit RU/EN alphabet and finite lexicon are conservative, not a general
number parser. Other Unicode spellings and language constructions remain subject
to canonical validation and manual quality review. Long sources are not truncated;
schema bounds still refuse excessive catalogs. Canonical storage, DTOs, flags,
historic readers, QG and migrations are unchanged.

Three regressions failed on the former provider schema. Coverage includes the
entire shared lexicon in both cases, longer noncardinal words and ordinals,
exact sourced word/digit assertions, no decoder repair, 5000 reference comparisons
and independent Unicode validation. Full CI and both live business contexts remain
deployment gates; failed probes never count as final Telegram acceptance.
