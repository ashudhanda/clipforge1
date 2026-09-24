"""Comment triggers — mined from the transcript, built INTO the moment.

The strongest comment engines match the moment's nature: challenge ->
attempt reports, mystery -> theories, debate -> arguments, tip ->
worked/didn't-work reports. A generic "W or L?" under every clip is
wallpaper; a trigger matched to the moment multiplies comments.

detect_trigger(text) -> "challenge" | "mystery" | "debate" | "tip" | "none".
Pure/deterministic; never raises. The pipeline prefers moments WITH a
natural trigger when ranking, and the description CTA + pinned comments
are matched to the detected trigger (see meta.py).
"""

import re

_PATTERNS = [
    ("challenge", [
        r"\b(can you|try this|beat this|first try)\b",
        r"\b\d+(\.\d+)?%\s*(can|of you)\b",
        r"\b(impossible|no one can|nobody can)\b",
        r"\b(clutch|1v3|1v2|2v1|speedrun)\b",
    ]),
    ("mystery", [
        r"\b(what is|what\'s|whats|who is|who\'s|where did|how did|why is)\b.{0,20}\?",
        r"\b(never seen|never heard|what the heck is)\b",
    ]),
    ("debate", [
        r"\b(best|worst|better than|vs\.?|versus|w or l|overrated|underrated)\b",
        r"\b(would you|should i|or should)\b",
    ]),
    ("tip", [
        r"\b(did you know|pro tip|here\'s how|you can just|secret|hidden)\b",
        r"\bif you (do|press|click|place)\b",
    ]),
]

_CTAS = {
    "challenge": "Think YOU can beat that? Drop your attempt in the comments",
    "mystery": "What IS that?! Comment your theory below",
    "debate": "W or L? Settle it in the comments",
    "tip": "Did this actually work for you? Comment below",
    "none": "What would YOU do here? Comment below",
}

_PINNED = {
    "challenge": ["First try or nah? Be honest",
                  "What would YOUR attempt look like?"],
    "mystery": ["What do YOU think happened here?",
               "Anyone know what this is called?"],
    "debate": ["W or L?",
               "Luck or skill — you decide"],
    "tip": ["Trying this tonight — who else?",
            "Did it work for you?"],
    "none": ["W or L?",
             "What would YOU do here?"],
}


def detect_trigger(text):
    """Trigger type mined from transcript text. Never raises."""
    try:
        text = text or ""
        for trig, pats in _PATTERNS:
            for p in pats:
                if re.search(p, text, re.I):
                    return trig
        return "none"
    except Exception:
        return "none"


def trigger_cta(trigger):
    """Description CTA matched to the trigger type."""
    return _CTAS.get(trigger) or _CTAS["none"]


def trigger_pinned(trigger, n=2):
    """Pinned-comment suggestions matched to the trigger type."""
    return list((_PINNED.get(trigger) or _PINNED["none"])[:max(1, n)])


def trigger_bonus(trigger):
    """Ranking nudge: moments with a natural trigger rank higher."""
    return 0.5 if trigger and trigger != "none" else 0.0
