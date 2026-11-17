"""Finding the vocabulary's systems in a text by their spellings (#34).

Used to draft the `systems` of gold tickets and by the keyword backend. The model itself
chooses the systems by meaning; this matcher only sees spellings.
"""

import re
from functools import cache

from megatron.departments import System

# A spelling matches as a whole word or with a case ending, so inflected forms count
# ("Телеграме", "вотсапе", "printers") but other words that start with a short spelling do
# not: "вам" is not "ВА", "Максим" and "максимально" are not "Макс".
ENDING = r"(?:а|у|е|ом|ой|ы|и|ах|ам|ов|ей|ю|я|s|es)?"


@cache
def spelling_pattern(spelling: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(spelling)}{ENDING}(?!\w)", re.IGNORECASE)


def find_systems(text: str, systems: list[System]) -> list[str]:
    """Ids of the systems whose spellings occur in the text, in vocabulary order."""
    return [s.id for s in systems if any(spelling_pattern(sp).search(text) for sp in s.spellings)]
