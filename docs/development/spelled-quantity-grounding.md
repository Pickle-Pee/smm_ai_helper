# Quantities written as words

## Defect and acceptance boundary

The previous numerical boundary used Unicode decimal digits alone. It accepted
unsupported promises about a single visit and experiment designs requesting two
questions when these quantities were written as words. Five synthetic regression
cases (POSITIONING RU/EN, EXPERIMENTS intervention RU/EN and minimum inputs RU)
failed their expected-rejection tests before the change.

`numeric_quantity.has_numeric_quantity` now detects the existing Unicode `\d`
boundary plus a bounded RU/EN cardinal followed by a counted unit. The same pure
helper serves `require_supported_numbers`, numeric-context extraction, CMO
text/items validation, and structured-parent assertion filtering. It does not parse
values, convert words to digits, calculate, normalize quotations, or repair text.

POSITIONING and EXPERIMENTS continue to require the entire numerical statement or
design field to occur verbatim in actually cited assertion support. A matching
number in an unrelated source, a new rationale, or assembled assertions does not
qualify. Existing numeric/source/seed/product rules retain their precedence.

CMO text and items remain qualitative even if a count is supplied. Whole source
leaves containing recognized word quantities can instead enter `numeric_context`.
The exact support-ID/whole-quote pair, actual citation, attribution and original
field bounds remain authoritative. Catalog caps remain 64 entries and 16 KiB:
whole entries may be omitted at those caps and are never shortened. Adding newly
recognized units may change which entries fit, so this is an intentionally bounded
provider subset. Plain accepted assertions retain their existing numeric authority;
structured CMO context quotes and quantitative summaries/items do not become
assertion support for downstream outputs.

## Bounded language support

The code contains finite explicit lexicons: English zero through nineteen, tens,
hundred/thousand and single; Russian zero through nineteen, tens, hundred/thousand
and listed case forms. Counted units cover visits, questions, actions, participants,
customers, items, images, tasks, groups, options, experiments/hypotheses, time,
currency and percentages. Units and modifiers are listed explicitly in the helper;
there is no stem wildcard, inferred morphology or external NLP dependency.

At most two listed modifiers (for example short/additional or короткими) may occur
between cardinal and unit, separated only by whitespace or hyphens. Case folding
is used for detection only. `one of the questions`, `один из вопросов`, ordinals,
`first customers`, `первые клиенты`, `one should visit`, and sentence-separated
words are not detected as counted quantities. Ranges/compound forms are detected
when their final recognized cardinal is followed by a recognized unit.

This is deliberately not a complete number grammar. Unknown languages, units,
modifiers, adverbs such as very/очень, larger inflected scales, Roman numerals,
fractions, words such as twice/вдвоём, and compounds such as двухчасовой can remain
outside the word detector. Ambiguous cardinal/unit phrases can conservatively
require source support. Idiom exclusions do not establish semantic entailment.

## Provider guidance and compatibility

The existing simple ASCII digit patterns and provider union structure are
unchanged. They do not prove absence of quantities written as words (or Unicode
digits); local validation remains authoritative. No word-based source enum branch
is added to EXPERIMENTS solely for this change: complete word quotations already
fit its qualitative provider branch and still face actual cited-source checks.
CMO uses its existing bounded exact-pair catalog structure for newly eligible
whole-leaf quotations. Catalog flags and legacy normalization policies are unchanged.

Module guidance explicitly closes the word-number loophole. POSITIONING guidance
also preserves supplied fulfillment conditions such as postprocessing and delayed
collection, and requires owner confirmation for new operational promises rather
than presenting them as an asserted offer. This guidance does not deterministically
prove all qualitative operational entailment, including promises with no recognized
quantity. Product outputs remain useful synthesized marketing text; they are not
all locked to source quotations or removed to obtain a pass.

Canonical DTOs, payload versions and persisted data formats are unchanged; no
migration is needed to read existing artifacts. Revalidating previously accepted
word quantities can now reject them by design. Current instruction capture goldens
change, while historical incident bytes/hashes/outcomes remain immutable evidence.
Offline contract tests do not establish live model quality or final acceptance.
