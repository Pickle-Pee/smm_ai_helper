# POSITIONING word quantities remain a canonical acceptance condition

The existing unit-aware has_numeric_quantity algorithm and cardinal vocabulary
are preserved. Its bounded modifier list now also recognizes introductory and
Russian вводный inflections: single introductory session must not hide a count.
The same at-most-two listed modifiers and punctuation boundaries still apply. Unsupported word quantities (including one/single and Russian
inflections) still fail actual executor validation, even when syntax is valid.
Supplied numeric assertions remain available as full exact SOURCE values and
require their actually cited source; an enum entry never adds a citation.

Generation uses the existing simple ASCII-digit-free assertion pattern and explicit
QUALITATIVE/SOURCE modes. Instructions prohibit invented or respelled counts,
including stylistic singulars, and require complete source assertions for actual
supplied durations. There is no finite-word blacklist in provider syntax. Ordinary
words such as стоимость, однако, триггер and oneself remain available. The former
provider-only vocabulary accessor and trie implementation are removed; no duplicate
editable lexicon, word normalization, response repair or retry remains.

The exact-cardinal, prefix-pruned and tagged/full-vocabulary variants stopped early
in full restored synthetic requests despite passing minimal compatibility cases.
A targeted singular grammar passed the workshop but stopped on the course. Those
variants were held outside production. This history does not establish a provider
internal mechanism. The simple producer variant completed both restored contexts
and passed unchanged strict validation, cited literal RTB and Quality Gates; exact
payload equivalence in the final immutable image and full CI remain deployment gates.

Regression tests explicitly prove that word-number and Unicode-number responses
are admitted by provider syntax and independently rejected by the real canonical
validator when unsupported. Tests also cover complete sourced word/digit quantities,
ordinary words, unmodified decode values and uncited source rejection. Canonical
validation retains its existing finite language/unit limits, not general NLP
entailment. Public DTOs, storage, migrations, model and budgets are unchanged.
