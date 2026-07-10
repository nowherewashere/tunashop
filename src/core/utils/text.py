import re

# A leading emoji (plus any surrounding whitespace, variation selectors and ZWJ).
# Covers the common pictographic blocks; plan names use plain unicode emoji (🐟 / 🦈).
_LEADING_EMOJI = re.compile(
    "^[\\s"
    "\U0001f300-\U0001faff"  # symbols & pictographs (+ supplemental / extended)
    "\U00002600-\U000027bf"  # misc symbols + dingbats
    "\U0001f1e6-\U0001f1ff"  # regional indicators
    "\U00002b00-\U00002bff"  # misc symbols and arrows (⭐ etc.)
    "\U0000fe00-\U0000fe0f"  # variation selectors
    "\U0000200d"  # zero-width joiner
    "]+",
)


def strip_leading_emoji(text: str) -> str:
    """Drop a leading emoji (and surrounding whitespace) from a label.

    Used to render a plan name without its emoji in the hub while keeping it
    everywhere else the name appears. Plain-unicode emoji only; a no-op when the
    label has no leading emoji.
    """
    return _LEADING_EMOJI.sub("", text).strip()
