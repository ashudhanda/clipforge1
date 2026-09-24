"""Hook mining — the first 2 seconds decide everything.

make_hook_text() just uppercased the first spoken words, which are usually
filler ("so uh guys today we are..."). Filler openers are the #1 reason
viewers swipe in the first 2 seconds.

This module scans the window for the most hookable sentence (questions,
exclamations, hype phrases, numbers) and falls back to curiosity-gap
templates, so the opening always carries a reason to keep watching.
Hook cards are <=8 words and never echo the opening caption verbatim.

Modes (config hook_mode):
    card  big centered curiosity-gap card, first 2s (default)
    cold  small top-center hook text, first 2.5s
    off   no hook text

No emoji is ever generated inside the video.
"""

import hashlib
import re

_TERMINAL_RE = re.compile(r"[.!?\u2026]+$")
_HYPE_RE = re.compile(
    r"\b(oh my god|omg|no+ w+a+y|wait what|let'?s go+|holy (shit|crap)|"
    r"what the|wtf|insane|crazy|unbelievable|impossible|ridiculous|nasty|"
    r"disgusting|haha+|lol|lmao)\b", re.I)
_TEASE_RE = re.compile(
    r"\b(watch this|look at this|check this out|wait for it|wait till|"
    r"you won'?t believe|nobody expected|trust me)\b", re.I)
_NUMBER_RE = re.compile(r"\$\d[\d,]*|\b\d{2,}\b")
_QUESTION_RE = re.compile(r"\?")
_EXCLAM_RE = re.compile(r"!")

# Curiosity-gap fallbacks — only when the transcript has no hookable line.
# Picked deterministically from the transcript hash so the same clip always
# gets the same card (stable, reviewable).
FALLBACK_CARDS = [
    "WAIT FOR IT",
    "HE DID WHAT?!",
    "THIS IS INSANE",
    "WATCH TILL THE END",
    "NO WAY THIS WORKED",
    "YOU MISSED THIS",
]


def _sentences(text):
    """Split text into sentences. Returns [text]."""
    parts = re.split(r"(?<=[.!?\u2026])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _score_sentence(text):
    """Hookability score. Higher = better opener."""
    score = 0.0
    if _QUESTION_RE.search(text):
        score += 3.0
    if _EXCLAM_RE.search(text):
        score += 2.0
    if _HYPE_RE.search(text):
        score += 2.0
    if _TEASE_RE.search(text):
        score += 2.0
    if _NUMBER_RE.search(text):
        score += 1.0
    nwords = len(text.split())
    if nwords > 12:
        score -= (nwords - 12) * 0.3
    if nwords < 3:
        score -= 1.0
    return score


def _truncate_punchy(text, max_words=8):
    """Trim to <=max_words keeping the punchy tail (the payoff words)."""
    toks = text.split()
    if len(toks) <= max_words:
        return text
    return " ".join(toks[-max_words:])


def pick_hook_line(text, lookahead_frac=0.6):
    """Best hookable sentence from the first ~60% of the text.

    The hook must tease what is COMING, never the payoff at the end.
    Returns the raw sentence, or None when nothing hookable exists.
    """
    if not text or not text.strip():
        return None
    sents = _sentences(text)
    if not sents:
        return None
    cutoff = max(1, int(len(sents) * lookahead_frac))
    best, best_score = None, 0.5  # must beat the filler threshold
    for s in sents[:cutoff]:
        sc = _score_sentence(s)
        if sc > best_score:
            best, best_score = s, sc
    return best


def hook_card_text(text, opening_text=""):
    """Final hook-card text (<=8 words, UPPERCASE).

    Uses the mined hook line; falls back to a deterministic curiosity-gap
    card. Never echoes the opening caption verbatim (the echo guard).
    """
    line = pick_hook_line(text)
    if line:
        card = _truncate_punchy(
            re.sub(r"\s+", " ", line).strip(" -\\u2013\\u2014:;,.!?"), 8)
        # echo guard: if the card is basically the opening caption,
        # fall back to a template instead
        if card and opening_text:
            op = re.sub(r"\W+", "", opening_text[:40]).lower()
            cp = re.sub(r"\W+", "", card).lower()
            if op and (cp.startswith(op[:20]) or op[:20].startswith(cp[:20])):
                line = None
            else:
                return card.upper()
        elif card:
            return card.upper()
    # deterministic fallback from the transcript hash
    h = hashlib.md5((text or "").encode("utf-8")).hexdigest()
    return FALLBACK_CARDS[int(h, 16) % len(FALLBACK_CARDS)]
