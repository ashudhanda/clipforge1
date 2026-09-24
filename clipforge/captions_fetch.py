"""Fetch subtitles ONLY — no video download.

`yt-dlp --write-subs --write-auto-subs --skip-download` pulls just the
caption track (KBs, seconds). Manual subtitles are preferred over
auto-generated ones.

Returns (segments, meta) where segments = [{start, end, text}] in seconds
and meta = {"has_captions": bool, "lang": str, "auto": bool}.
When a video has no captions at all, has_captions is False and the caller
falls back to transcribe.py (audio-only + faster-whisper).

Never raises — returns ([], {"has_captions": False}) on failure.
"""

import logging
import re
import subprocess
import tempfile
from pathlib import Path

from . import config as C
from .research import antibot_args

log = logging.getLogger("clipforge")

_VTT_TS = re.compile(
    r"(\d+):(\d+):(\d+)\.(\d+)\s+-->\s+(\d+):(\d+):(\d+)\.(\d+)")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _ts(h1, m1, s1, ms1):
    return int(h1) * 3600 + int(m1) * 60 + int(s1) + int(ms1) / 1000.0


def _word_overlap(a_words, b_words):
    """Longest k where a's tail == b's head (word level)."""
    best = 0
    for k in range(min(len(a_words), len(b_words)), 0, -1):
        if a_words[-k:] == b_words[:k]:
            return k
    return best


def parse_vtt(text):
    """Parse WebVTT into [{start, end, text}]. Never raises.

    Handles YouTube's rolling auto-captions: consecutive cues overlap in
    time AND repeat words ("hello world" -> "hello world foo"). The
    already-seen words are trimmed so the transcript has no duplicates —
    and cues stay small so moment detection keeps its granularity.
    """
    segments = []
    recent = []  # running window of recently emitted words
    try:
        for m in _VTT_TS.finditer(text):
            start = _ts(*m.groups()[:4])
            end = _ts(*m.groups()[4:])
            block = text[m.end():]
            # cue text runs until a blank line (skip leading blanks)
            lines, started = [], False
            for line in block.splitlines():
                if not line.strip():
                    if started:
                        break
                    continue
                if "-->" in line:
                    break
                started = True
                lines.append(line)
            cue = _WS_RE.sub(" ", _TAG_RE.sub("", " ".join(lines))).strip()
            if not cue or end <= start:
                continue
            words = cue.split()
            if segments and start < segments[-1]["end"]:
                # overlapping (rolling) cue: drop already-seen head words
                # against the running word window (the previous segment
                # was already trimmed, so compare against history)
                k = _word_overlap(recent[-40:], words)
                words = words[k:]
                if not words:
                    continue  # fully duplicate rolling cue
            else:
                recent = []
            segments.append({"start": start, "end": end,
                             "text": " ".join(words)})
            recent.extend(words)
            recent = recent[-40:]
    except Exception:
        pass
    return segments


def fetch(video_url, langs=("en.*",)):
    """Download subtitle files only. Returns (segments, meta)."""
    meta = {"has_captions": False, "lang": "", "auto": True}
    try:
        with tempfile.TemporaryDirectory(prefix="cf_subs_") as td:
            out = str(Path(td) / "subs")
            cmd = ([C.ytdlp_path(), "--skip-download", "--write-subs",
                    "--write-auto-subs", "--sub-format", "vtt",
                    "--sub-langs", ",".join(langs),
                    "-o", out, "--no-warnings"]
                   + antibot_args() + [video_url])
            p = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=300)
            files = sorted(Path(td).glob("subs.*.vtt"))
            if not files:
                log.info("no captions found for %s", video_url)
                return [], meta
            # Prefer manual subs: yt-dlp names them subs.<lang>.vtt,
            # auto-subs subs.<lang>.vtt with "auto" in the lang tag... in
            # practice pick the largest file (manual subs are fuller).
            files.sort(key=lambda f: f.stat().st_size, reverse=True)
            # crude manual-vs-auto guess from filename
            best = files[0]
            for f in files:
                if ".auto." not in f.name and "auto" not in f.name.lower():
                    best = f
                    break
            text = best.read_text(encoding="utf-8", errors="replace")
            segments = parse_vtt(text)
            m = re.search(r"subs\.(.+?)\.vtt$", best.name)
            lang = m.group(1) if m else ""
            meta.update({"has_captions": bool(segments), "lang": lang,
                         "auto": "auto" in best.name.lower()})
            log.info("captions: %d segments (%s%s)", len(segments), lang,
                     ", auto" if meta["auto"] else "")
            return segments, meta
    except Exception as e:
        log.warning("caption fetch failed (%s)", type(e).__name__)
    return [], meta
