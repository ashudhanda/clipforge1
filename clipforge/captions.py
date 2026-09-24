"""Caption styles + ASS subtitle builder.

12 trending caption presets. The user picks one (config caption_style);
every preset renders word-level karaoke: one Dialogue event per word
showing its chunk, with the ACTIVE word highlighted via inline ASS
overrides — plain ASS, no plugin semantics to get wrong (a tested
approach refined over dozens of published Shorts).

The "pop" family additionally scales the active word up (inline
\fscx\fscy) for the trending bouncy-caption feel.

build_ass(words, hook_text, style, path, hook_mode) writes the .ass file:
  - karaoke word events in the chosen preset
  - hook card (HookCard style, first 2s) or small hook text, per hook_mode
  - words = [(start, end, word)] in CLIP-relative seconds

build_ass_lines(cues, ...) is the fallback for plain line captions.
"""

import logging

log = logging.getLogger("clipforge")

# fontsize tuned for 1080x1920. highlight = ASS color of the ACTIVE word
# (&HAABBGGRR). pop_scale = active-word scale % for the bouncy feel.
STYLES = {
    "hormozi":  {"fontsize": 69, "highlight": "&H0000FFFF&", "outline": 5,
                 "shadow": 2},   # yellow word pop (classic)
    "mrbeast":  {"fontsize": 76, "highlight": "&H0000FF00&", "outline": 6,
                 "shadow": 2},   # green word pop, chunkier
    "clean":    {"fontsize": 64, "highlight": None, "outline": 3,
                 "shadow": 0},   # plain white, podcast-style
    "pop":      {"fontsize": 80, "highlight": "&H0000FFFF&", "outline": 6,
                 "shadow": 2, "pop_scale": 118},  # bouncy karaoke
    "neon":     {"fontsize": 72, "highlight": "&H00FFFF00&", "outline": 4,
                 "shadow": 3},   # cyan glow highlight
    "minimal":  {"fontsize": 54, "highlight": None, "outline": 2,
                 "shadow": 0},   # small thin lower-third
    "bold":     {"fontsize": 88, "highlight": None, "outline": 8,
                 "shadow": 3},   # huge white, heavy outline
    "karaoke":  {"fontsize": 68, "highlight": "&H000000FF&", "outline": 4,
                 "shadow": 2},   # classic red karaoke sweep
    "box":      {"fontsize": 66, "highlight": "&H0000FFFF&", "outline": 3,
                 "shadow": 0, "box": True},  # active word in solid box
    "top":      {"fontsize": 62, "highlight": "&H0000FFFF&", "outline": 4,
                 "shadow": 2, "align_top": True},  # captions at top
    "mono":     {"fontsize": 60, "highlight": "&H00FF9900&", "outline": 3,
                 "shadow": 0},   # orange highlight, understated
    "punch":    {"fontsize": 84, "highlight": "&H0000FFFF&", "outline": 7,
                 "shadow": 2, "pop_scale": 125},  # extra-bouncy, loud
}

DEFAULT_STYLE = "hormozi"
HOOK_CARD_S = 2.0
_MARKER_RE = None  # compiled lazily (avoids import-time cost)


def _marker_re():
    global _MARKER_RE
    if _MARKER_RE is None:
        import re
        _MARKER_RE = re.compile(r"^\[.*\]$")
    return _MARKER_RE


def list_styles():
    return sorted(STYLES)


def ass_header(style=DEFAULT_STYLE):
    st = STYLES.get(style, STYLES[DEFAULT_STYLE])
    align = 8 if st.get("align_top") else 2          # 8=top-center, 2=bottom
    border = 3 if st.get("box") else 1               # 3=opaque box
    back = "&HFF000000&" if st.get("box") else "&H80000000&"
    margin_v = 180 if st.get("align_top") else 360
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Noto Sans,{st['fontsize']},&H00FFFFFF,&H00FFFFFF,&H80000000,{back},-1,0,0,0,100,100,0,0,{border},{st['outline']},{st['shadow']},{align},60,60,{margin_v},1
Style: Hook,Noto Sans,81,&H0000FFFF,&H00FFFFFF,&H80000000,&H99000000,-1,0,0,0,100,100,0,0,3,5,2,8,60,60,180,1
Style: HookCard,Noto Sans,120,&H00FFFFFF,&H00FFFFFF,&H80000000,&H99000000,-1,0,0,0,100,100,0,0,3,5,2,5,60,60,180,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_time(s):
    ms = max(0, int(round(s * 1000)))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    sec, ms = divmod(ms, 1000)
    return f"{h}:{m:02d}:{sec:02d}.{ms // 10:02d}"


def _ass_esc(t):
    return t.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _chunk_words(words, max_words=5, max_gap=0.8, max_dur=3.0):
    chunks, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or w[0] - cur[-1][1] > max_gap
                    or w[1] - cur[0][0] > max_dur):
            chunks.append(cur)
            cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def build_ass(words, path, style=DEFAULT_STYLE, hook_text=None,
              hook_mode="card"):
    """Write karaoke ASS. words=[(start,end,word)] clip-relative seconds.

    Returns True when at least one caption event was written.
    """
    st = STYLES.get(style, STYLES[DEFAULT_STYLE])
    hl = st["highlight"]
    ps = st.get("pop_scale")
    mre = _marker_re()
    ev = []
    clean_words = [(s, e, w) for s, e, w in words
                   if w and not mre.match(w.strip())]
    for ch in _chunk_words(clean_words):
        tail = ch[-1][1] + 0.25
        for i, (s, e, w) in enumerate(ch):
            ns = ch[i + 1][0] if i + 1 < len(ch) else tail
            parts = []
            for j, (_, _, ww) in enumerate(ch):
                ww = _ass_esc(ww.upper())
                if hl and j == i:
                    if ps:
                        parts.append(f"{{\\fscx{ps}\\fscy{ps}\\c{hl}}}{ww}"
                                     f"{{\\fscx100\\fscy100\\c&H00FFFFFF&}}")
                    else:
                        parts.append(f"{{\\c{hl}}}{ww}{{\\c&H00FFFFFF&}}")
                else:
                    parts.append(ww)
            ev.append(f"Dialogue: 0,{_ass_time(s)},{_ass_time(ns)},Caption,,0,0,0,,"
                      + " ".join(parts))
    if hook_text and hook_mode != "off":
        if hook_mode == "card":
            ev.append(f"Dialogue: 0,{_ass_time(0)},{_ass_time(HOOK_CARD_S)},"
                      f"HookCard,,0,0,0,,{hook_text}")
        else:  # cold
            ev.append(f"Dialogue: 0,{_ass_time(0)},{_ass_time(2.5)},"
                      f"Hook,,0,0,0,,{hook_text}")
    if not ev:
        return False
    path.write_text(ass_header(style) + "\n".join(ev) + "\n", encoding="utf-8")
    log.info("captions: %d events, style=%r%s", len(ev), style,
             " + hook" if hook_text and hook_mode != "off" else "")
    return True


def build_ass_lines(cues, path, style=DEFAULT_STYLE):
    """Fallback: plain line captions from subtitle cues [(s,e,text)]."""
    mre = _marker_re()
    ev = []
    for s, e, t in cues:
        t = _ass_esc(" ".join(t.split()))
        if t and not mre.match(t):
            ev.append(f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},Caption,,0,0,0,,"
                      + t.upper())
    if not ev:
        return False
    path.write_text(ass_header(style) + "\n".join(ev) + "\n", encoding="utf-8")
    return True
