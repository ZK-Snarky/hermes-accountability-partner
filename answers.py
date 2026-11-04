"""Read a one-line check-in answer like "yes no yes", "y n", "✅❌✅" or "all done".

Only a reply made entirely of answer words counts, and only when it answers every question.
Anything else (a sentence, a partial answer) returns None and is left to the conversation.
"""

from __future__ import annotations

import re
from typing import Optional

_YES = {"yes", "y", "yep", "yeah", "yup", "done", "did", "kept", "✅", "👍", "✔", "✔️", "☑️", "1"}
_NO = {"no", "n", "nope", "nah", "miss", "missed", "skip", "skipped", "didnt", "❌", "👎", "✖", "✗", "0"}
_ALL_YES = {"all yes", "all done", "all kept", "yes to all", "all of them", "all ✅"}
_ALL_NO = {"all no", "none", "none of them", "no to all", "all missed", "all ❌"}
_FILLER = {"and", "&", "then"}
_EMOJI = re.compile(r"(✅|❌|👍|👎|✔️|✔|☑️|✖|✗)")


def parse(text: str, count: int) -> Optional[list[bool]]:
    """One bool per question, in order, or None when the reply is not a clean full answer."""
    if count < 1 or not text:
        return None
    flat = " ".join(text.lower().replace("’", "'").replace("didn't", "didnt").split())
    flat = flat.strip(" .!")
    if flat in _ALL_YES:
        return [True] * count
    if flat in _ALL_NO:
        return [False] * count
    spaced = _EMOJI.sub(r" \1 ", flat)
    words = [w for w in re.split(r"[\s,;/.!]+", spaced) if w and w not in _FILLER]
    # "1 yes 2 no" style: drop the numbers that label each answer when they run 1..n in order
    if len(words) == 2 * count and all(words[i] == str(i // 2 + 1) for i in range(0, len(words), 2)):
        words = words[1::2]
    if len(words) != count:
        return None
    out = []
    for word in words:
        if word in _YES:
            out.append(True)
        elif word in _NO:
            out.append(False)
        else:
            return None
    return out
