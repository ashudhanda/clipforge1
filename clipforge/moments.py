"""Best-moment detection from a transcript.

Sliding windows over the caption/transcript segments, scored by a
rule-based virality model (questions, hype phrases, strong words,
audience reactions, comment triggers):

    +3.0  question in the window
    +2.0  exclamation / hype phrase ("insane", "no way", ...)
    +1.5  each strong word (secret, never, mistake, truth, ...)
    +1.0  [laughter] / [applause] / [music] markers
    +0.5  numbers / money / percentages
    +0.5  comment trigger present (challenge/mystery/debate/tip)
    -2.0  too little speech (<40 words) — nothing to caption
    -1.5  filler-heavy ("um", "uh", "like", "you know" > 25%)

DIVERSITY: moments must not overlap (padding included) and are spread
across the video — first pass picks with a wide gap (spread), second
pass fills the rest (quality). No two clips from the same stretch.

Optional LLM rerank (llm.rank_moments) when the user configured a key —
otherwise the rule-based order stands.

detect(segments, n, niche) -> [moment], moment =
    {"start", "end", "score", "reason", "text"}  (times in video seconds)
Never raises — returns [] when nothing scores above the bar.
"""

import logging
import re

from . import config as C
from . import llm as LLM
from . import triggers

log = logging.getLogger("clipforge")

_HYPE_RE = re.compile(
    r"\b(oh my god|omg|no+ w+a+y|wait what|holy (shit|crap)|what the|wtf|"
    r"insane|crazy|unbelievable|impossible|ridiculous|nasty|haha+|lol|lmao|"
    r"wow|damn|jesus)\b", re.I)
_STRONG_RE = re.compile(
    r"\b(secret|never|always|mistake|truth|lie|exposed|shocking|billion|"
    r"million|first time|nobody|everyone|worst|best|kill|dead|arrest|scam|"
    r"hack|free money|guarantee|warning|urgent|breaking)\b", re.I)
_MARKER_RE = re.compile(r"\[(laughter|applause|music|cheering|crowd)[^\]]*\]", re.I)
_NUMBER_RE = re.compile(r"\$\d[\d,.]*[kmb]?|\b\d+(\.\d+)?%|\b\d{2,}\b")
_QUESTION_RE = re.compile(r"\?")
_EXCLAM_RE = re.compile(r"!")
_FILLER_RE = re.compile(r"\b(um+|uh+|er+|like|you know|i mean|sort of|kind of)\b", re.I)

_MIN_SCORE = 1.0  # below this a window isn't worth a clip


def _window_text(segments, start, end):
    parts = []
    for s in segments:
        if s["end"] > start and s["start"] < end:
            parts.append(s["text"])
    return " ".join(parts)


def _score_window(text):
    """(score, [reasons]) for one window of transcript text."""
    score, reasons = 0.0, []
    words = text.split()
    nw = len(words)
    if nw < 40:
        return -2.0, ["too little speech"]
    if _QUESTION_RE.search(text):
        score += 3.0
        reasons.append("question")
    if _EXCLAM_RE.search(text):
        score += 2.0
        reasons.append("exclamation")
    if _HYPE_RE.search(text):
        score += 2.0
        reasons.append("hype moment")
    strong = _STRONG_RE.findall(text)
    if strong:
        score += 1.5 * min(len(strong), 4)
        reasons.append(f"strong words ({len(strong)})")
    if _MARKER_RE.search(text):
        score += 1.0
        reasons.append("audience reaction")
    if _NUMBER_RE.search(text):
        score += 0.5
        reasons.append("numbers")
    trig = triggers.detect_trigger(text)
    bonus = triggers.trigger_bonus(trig)
    if bonus:
        score += bonus
        reasons.append(f"{trig} trigger")
    filler = len(_FILLER_RE.findall(text))
    if nw and filler / nw > 0.25:
        score -= 1.5
        reasons.append("filler-heavy")
    # very long windows dilute the moment
    if nw > 220:
        score -= 1.0
    return score, reasons


def _candidates(segments, duration_s, niche):
    preset = C.niche_preset(niche)
    wmin = preset.get("window_min_s", 30)
    wmax = preset.get("window_max_s", 60)
    step = 10
    cands = []
    # try the preset's max window first, then smaller — a great 40s moment
    # beats a padded 70s one
    for wlen in (wmax, (wmin + wmax) // 2, wmin):
        t = 0.0
        while t + wlen <= duration_s:
            text = _window_text(segments, t, t + wlen)
            score, reasons = _score_window(text)
            if score >= _MIN_SCORE:
                cands.append({"start": t, "end": t + wlen,
                              "score": score,
                              "reason": ", ".join(reasons[:3]),
                              "text": text[:1200]})
            t += step
    # best score per overlapping region: keep the highest-scoring window
    # when two overlap heavily
    cands.sort(key=lambda c: c["score"], reverse=True)
    deduped = []
    for c in cands:
        if all(not (c["start"] < d["end"] - 5 and d["start"] < c["end"] - 5)
               for d in deduped):
            deduped.append(c)
    return deduped


def _overlaps(a_start, a_end, b_start, b_end, pad):
    return a_start < b_end + pad and b_start < a_end + pad


def _select_diverse(cands, n, duration_s, pad):
    """Two-pass greedy: spread first, then fill. Zero overlap."""
    picked = []

    def try_pick(min_gap):
        for c in cands:
            if len(picked) >= n:
                return
            if any(p is c for p in picked):
                continue
            if any(_overlaps(c["start"], c["end"],
                             p["start"], p["end"], pad + min_gap)
                   for p in picked):
                continue
            picked.append(c)

    # pass 1: wide gap forces clips from different parts of the video
    wide = max(90.0, duration_s / max(n, 1) / 2)
    try_pick(wide)
    # pass 2: fill remaining slots, still never overlapping
    try_pick(20.0)
    picked.sort(key=lambda c: c["score"], reverse=True)
    return picked[:n]


def _llm_rerank(cands, n):
    order = LLM.rank_moments(
        [{"start": c["start"], "end": c["end"], "text": c["text"]}
         for c in cands[: max(n * 3, 12)]])
    if not order:
        return None
    ranked = [cands[i] for i in order]
    # re-apply diversity on the LLM order
    return _select_diverse(ranked, n,
                           max((c["end"] for c in ranked), default=0), 3.0)


def detect(segments, n, niche, duration_s=None):
    """Top-N diverse moments from transcript segments."""
    try:
        n = max(1, int(n))
        if not segments:
            return []
        dur = duration_s or max((s["end"] for s in segments), default=0)
        if dur <= 0:
            return []
        cands = _candidates(segments, dur, niche)
        if not cands:
            log.info("moments: nothing scored above the bar")
            return []
        log.info("moments: %d candidates above bar", len(cands))
        if LLM.enabled():
            reranked = _llm_rerank(cands, n)
            if reranked:
                log.info("moments: LLM rerank applied")
                return reranked
        pad = C.load_config().get("segment_pad_s", 3.0)
        picked = _select_diverse(cands, n, dur, pad)
        log.info("moments: picked %d diverse moments", len(picked))
        return picked
    except Exception as e:
        log.warning("moment detection failed (%s)", type(e).__name__)
        return []
