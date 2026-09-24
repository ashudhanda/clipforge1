"""Titles, descriptions, hashtags — config-driven, niche-agnostic.

Title formula: "{Creator}'s {Event}! ({Niche})" or "{Event}! ({Niche})",
<= title_max_len chars (default 100). Never repeats a title (deterministic
variants on collision, then " (Part N)").

Event mining: generic patterns (secret, mistake, tip, story...) work for
any niche; niche keywords from the config add niche-specific phrases.
Descriptions: channel identity line, 2 truthful sentences, ONE
trigger-matched CTA, source credit, hashtags. No emoji by default.

Deterministic (no randomness, no network); never raises.
"""

import re

from . import config as C
from . import triggers

# (regex, event phrase) — first match wins, priority order. Generic so
# they work for podcasts, finance, gaming, motivation, anything.
_EVENT_RES = [
    (re.compile(r"\bsecret\b|\beaster egg\b|\bhidden\b|\bmissed\b", re.I),
     "Secret Detail"),
    (re.compile(r"\bmistake\b|\bwrong\b|\bfail\b|\bregret\b", re.I),
     "Big Mistake"),
    (re.compile(r"\btip\b|\bhack\b|\btrick\b|\bhow to\b", re.I),
     "Pro Tip"),
    (re.compile(r"\bstory\b|\btime when\b|\bremember when\b", re.I),
     "Untold Story"),
    (re.compile(r"\bmoney\b|\bmillion\b|\bbillion\b|\brich\b", re.I),
     "Money Truth"),
    (re.compile(r"\bnever\b.*\b(again|before)\b", re.I),
     "Never Again"),
    (re.compile(r"\bwarning\b|\bcareful\b|\bdanger\b", re.I),
     "Warning"),
    (re.compile(r"\bvs\.?\b|\bversus\b|\bbetter than\b", re.I),
     "Vs Breakdown"),
    (re.compile(r"\bquestion\b|\bask\b", re.I),
     "Honest Answer"),
]

_BANNED_TAGS = {"#viral", "#fyp", "#foryou", "#foryoupage"}


def clean_creator_name(raw, channel_url=""):
    """Creator display name. NEVER returns a URL (classic bug class)."""
    try:
        raw = (raw or "").strip()
        if raw and not re.match(r"https?://", raw, re.I):
            return raw[:60]
        cu = (channel_url or "") or raw or ""
        m = re.search(r"@([A-Za-z0-9_.\-]+)", cu)
        if m:
            return m.group(1)[:60]
        m = re.search(r"youtube\.com/(?:c/|user/)?([A-Za-z0-9_.\-]+)", cu, re.I)
        if m:
            return m.group(1)[:60]
        return "Unknown Creator"
    except Exception:
        return "Unknown Creator"


def _fix_caps(text):
    return re.sub(r"\b([A-Za-z]+)'S\b", r"\1's", text)


def event_phrase(text, hook_line=None, niche=""):
    """Primary event phrase for a clip."""
    try:
        cands = []
        for rx, ev in _EVENT_RES:
            if rx.search(text or ""):
                cands.append(ev)
                break
        # niche-specific flavor from config keywords
        preset = C.niche_preset(niche)
        for kw in preset.get("keywords", [])[:2]:
            if kw and re.search(r"\b" + re.escape(kw) + r"\b", text or "", re.I):
                cands.append(kw.title() + " Insight")
                break
        if hook_line:
            h = _fix_caps(re.sub(r"\s+", " ", hook_line.strip()).title())
            h = h.strip(" -\\u2013\\u2014:;,.!?")[:34].rstrip(" -\\u2013\\u2014:;,.!?")
            if h and h not in cands:
                cands.append(h)
        return cands[0] if cands else "Epic Moment"
    except Exception:
        return "Epic Moment"


def _fit(text, max_len):
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text
    cut = text[: max_len - 3].rsplit(" ", 1)[0] or text[: max_len - 3]
    return cut.rstrip(" -\\u2013\\u2014:;,.!?")[:max_len]


def pick_title(text, creator="", niche="", hook_line=None, taken=()):
    """Clip title, <= title_max_len, never a duplicate of `taken`."""
    cfg = C.load_config()
    max_len = cfg.get("title_max_len", 100)
    niche_label = (niche or cfg.get("niche") or "").strip().title()
    event = event_phrase(text, hook_line, niche)
    creator = (creator or "").strip()
    base = f"{creator}'s {event}! ({niche_label})" if creator else f"{event}! ({niche_label})"
    base = _fix_caps(base.strip(" ()!"))
    taken = set(taken or [])
    cand = _fit(base, max_len)
    if cand not in taken:
        return cand
    n = 2
    while True:
        cand = _fit(f"{base} (Part {n})", max_len)
        if cand not in taken:
            return cand
        n += 1


def pick_hashtags(niche="", extra=()):
    """#Shorts + niche tags. Never #viral/#fyp."""
    cfg = C.load_config()
    tags = list(cfg.get("hashtags") or ["#Shorts"])
    seen = {t.lower() for t in tags}
    preset = C.niche_preset(niche)
    for kw in list(preset.get("keywords", []))[:2] + list(extra or []):
        tag = "#" + re.sub(r"[^A-Za-z0-9]", "", kw.title())[:24]
        if tag and tag.lower() not in seen and tag.lower() not in _BANNED_TAGS:
            tags.append(tag)
            seen.add(tag.lower())
    return tags


def build_description(title, creator, source_url, text, niche="",
                      hashtags=None, trigger="none", event=None):
    """Description: identity line, 2 sentences, trigger CTA, credit, tags."""
    cfg = C.load_config()
    channel = cfg.get("channel_name") or "ClipForge"
    cta = triggers.trigger_cta(trigger)
    pinned = triggers.trigger_pinned(trigger)
    ev = (event or event_phrase(text, niche=niche)).lower()
    c = creator or "this creator"
    body = (f"{c} on {ev} — the part everyone misses. "
            f"Watch it all the way through. {cta}.")
    tags = " ".join(hashtags if hashtags is not None else pick_hashtags(niche))
    desc = (f"{channel} {niche.title()} Shorts\n"
            f"\n{body}\n"
            f"\nClip from {c}: {source_url}\n"
            f"\n{tags}")
    return desc, pinned
