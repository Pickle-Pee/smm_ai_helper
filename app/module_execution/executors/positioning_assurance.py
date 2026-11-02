"""Canonical product assurance detector; generation uses a simple text schema."""
import re


ASSURANCE = re.compile(
    r"\b(?:гаранти\w*|опытн\w*|квалифицированн\w*|сертифицированн\w*|"
    r"профессиональн\w*|безусловн\w*|guarantee\w*|experienced|qualified|"
    r"certified|professional|unconditional\w*)\b", re.IGNORECASE)
