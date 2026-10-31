"""Conservative quantity authority for new free-form case-Mentor answers."""
import json
import re

from app.module_execution.executors.numeric_quantity import has_numeric_quantity


class MentorGroundingError(ValueError):
    """A generated quantitative line has no literal authorized source."""


_LIST_PREFIX = re.compile(r"^\s*(?:(?:[-*•]\s+)(?:\d{1,3}[.)]\s+)?|\d{1,3}[.)]\s+)")
_IDENTIFIER = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")
_ADJECTIVE_ENDING = r"(?:ый|ая|ое|ые|ого|ой|ых|ому|ым|ую|ыми|ом)"
_ONE_OFF = re.compile(
    r"\b(?:(?:одноразов|единоразов|разов)" + _ADJECTIVE_ENDING
    + r"|однократн(?:о|" + _ADJECTIVE_ENDING + r")|one[- ‐‑‒–—](?:off|time))\b", re.I)


def validate_answer_quantities(generated, packet):
    """Require the whole emitted quantitative line in an authorized source.

    Only the actual bounded packet's supplied inputs, user questions/reports and
    server arithmetic grant numeric authority. Generated strategy/dialogue cannot
    launder earlier invented numbers. Copied namespaced identifiers and list
    indices are structural metadata. Output itself is never rewritten.
    """
    authority = [row["text"] for row in packet["accepted_case"] if row["key"] == "inputs"]
    authority.append(packet["current_question"])
    authority.extend(row["user"] for row in packet["dialogue"])
    for row in packet["feedback"]:
        authority.extend((row["notes"], row["metrics"], json.dumps(row["analysis"], ensure_ascii=False)))
    identifiers = {match.group() for source in authority for match in _IDENTIFIER.finditer(source)
                   if any(c.isdecimal() for c in match.group())}
    for paragraph in (*generated.paragraphs, *generated.unknowns):
        for line in paragraph.splitlines():
            candidate = _LIST_PREFIX.sub("", line).strip()
            detected = _IDENTIFIER.sub(lambda m: "" if m.group() in identifiers else m.group(), candidate)
            if ((has_numeric_quantity(detected) or _ONE_OFF.search(detected))
                    and not any(candidate in source for source in authority)):
                raise MentorGroundingError("numerical_support_required")
