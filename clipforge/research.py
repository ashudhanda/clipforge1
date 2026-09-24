"""YouTube research — find candidate long videos for a niche. NO download.

Uses `yt-dlp ytsearchN:"query"` (no API key needed), then filters:
    - duration >= min_duration_min (long videos only — podcasts etc.)
    - uploaded within max_age_days (recent)
    - view_count >= min_views (popular)
    - skips live/upcoming/premiere entries

Returns [{video_id, title, channel, duration_s, view_count, upload_date,
url}]. Never raises — returns [] when search fails (caller logs plainly).

On failure, `last_error` is set to "missing" (yt-dlp not installed)
or "search_failed" (network/bot-check) so callers can explain why.
"""

import functools
import json
import logging
import subprocess
import time

from . import config as C

log = logging.getLogger("clipforge")

def _ytdlp():
    return C.ytdlp_cmd()


# Set by discover(): "" on success, otherwise a short reason code —
# "missing" (yt-dlp not installed), "search_failed" (network/bot-check),
# "filtered_out" (search worked but quality filters rejected everything).
# pipeline.py uses this to show an honest, actionable message.
last_error = ""
# stderr of the failed yt-dlp search (trimmed) — for the real reason.
last_stderr = ""
# {"found": raw entries, "kept": after filters, "relaxed": bool}
last_stats = {}


_impersonate_target_cache = "unprobed"


def impersonate_target():
    """Newest available Chrome impersonation target (e.g. "chrome-136"), or
    None when impersonation isn't usable.

    Probed once per process via `yt-dlp --list-impersonate-targets` and
    cached. Never hardcoded — hardcoding is what broke real users when
    their curl_cffi version didn't have the assumed target.
    """
    global _impersonate_target_cache
    if _impersonate_target_cache != "unprobed":
        return _impersonate_target_cache
    target = None
    try:
        p = subprocess.run(_ytdlp() + ["--list-impersonate-targets"],
                           capture_output=True, text=True, timeout=30)
        if p.returncode == 0:
            best = 0
            for line in (p.stdout or "").splitlines():
                line = line.strip().lower()
                # rows look like: "chrome-136      macos-15     curl_cffi"
                if line.startswith("chrome-"):
                    num = "".join(ch for ch in line.split()[0][7:]
                                  if ch.isdigit())
                    if num.isdigit() and int(num) > best:
                        best = int(num)
            if best:
                target = f"chrome-{best}"
    except Exception:
        target = None
    _impersonate_target_cache = target
    return target


def antibot_args():
    """Args that keep yt-dlp working on strict networks.

    player_client=web_embedded,default completes downloads where other
    clients get 403s; TLS impersonation uses the newest Chrome target this
    install actually supports (probed, never assumed); cookies.txt (if the
    user exported one) is the strongest signal.
    """
    args = ["--extractor-args", "youtube:player_client=web_embedded,default"]
    tgt = impersonate_target()
    if tgt:
        args += ["--impersonate", tgt]
    cookies = C.HOME / "cookies.txt"
    if cookies.exists():
        args += ["--cookies", str(cookies)]
    return args


def _run(cmd, timeout=180, note_stderr=False):
    """Run a command; return stdout, or None on failure.

    With note_stderr=True the trimmed stderr is saved to `last_stderr`
    so callers can report the real reason (bot-check text, etc.).
    """
    global last_stderr
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        if note_stderr:
            last_stderr = "timeout (180s)"
        return None
    except FileNotFoundError:
        log.error("yt-dlp nahi mila — setup.py dobara chalao")
        return None
    if p.returncode != 0:
        if note_stderr:
            err = (p.stderr or "").strip().replace("\n", " ")
            # keep the most informative tail (yt-dlp puts ERROR: last)
            last_stderr = err[-300:] if len(err) > 300 else err
        return None
    return p.stdout


def video_meta(url):
    """Title/channel for one video URL — no download. Returns {} on failure."""
    out = _run(_ytdlp() + ["--skip-download", "--print",
                "%(.{title,channel})j", url] + antibot_args())
    if not out:
        return {}
    try:
        return json.loads(out.strip().splitlines()[0])
    except Exception:
        return {}


def _full_meta(url):
    """Full metadata for one video — still no download.

    Used as stage 2 when the flat search entry is missing fields
    (duration especially: flat playlist entries don't always carry it).
    Cached so the relaxed filter pass doesn't re-fetch the same videos.
    """
    return _full_meta_cached(url)


@functools.lru_cache(maxsize=64)
def _full_meta_cached(url):
    cmd = (_ytdlp() + ["--skip-download",
            "--print", "%(.{id,title,channel,duration,view_count,upload_date,live_status})j",
            url] + antibot_args())
    out = _run(cmd, timeout=120)
    if not out:
        return None
    try:
        return json.loads(out.strip().splitlines()[0])
    except Exception:
        return None


def _parse_entries(out):
    """Parse flat ytsearch JSON lines into raw entry dicts."""
    entries = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            v = json.loads(line)
        except Exception:
            continue
        if v.get("id"):
            entries.append(v)
    return entries


def _filter_entries(entries, min_dur, max_age, min_views):
    """Apply quality filters. Stage 2 fetches metadata for entries
    missing a duration, so good videos aren't dropped on missing data."""
    now = time.time()
    results = []
    for v in entries:
        vid = v.get("id")
        dur = v.get("duration") or 0
        if not dur:
            meta = _full_meta(f"https://www.youtube.com/watch?v={vid}")
            if meta:
                v = meta
                dur = v.get("duration") or 0
        if not dur or dur < min_dur:
            continue
        views = v.get("view_count") or 0
        if views and views < min_views:
            continue
        ud = str(v.get("upload_date") or "")
        try:
            age = now - time.mktime(time.strptime(ud, "%Y%m%d"))
            if age > max_age:
                continue
        except Exception:
            pass
        if v.get("is_live") or v.get("live_status") in ("is_live", "is_upcoming"):
            continue
        results.append({
            "video_id": vid,
            "title": v.get("title") or "",
            "channel": v.get("channel") or "",
            "duration_s": int(dur),
            "view_count": views or 0,
            "upload_date": ud,
            "url": f"https://www.youtube.com/watch?v={vid}",
        })
    # Most-viewed first — popular videos have the best moments.
    results.sort(key=lambda r: r["view_count"], reverse=True)
    return results


def discover(niche, max_results=None):
    """Search YouTube for recent, popular long videos in `niche`.

    Two stages, zero downloads:
      1. flat `ytsearch` (fast) for candidate entries;
      2. per-video metadata for entries missing a duration, so the
         long-video filter never drops a good video on missing data.

    Query combines the niche with its preset keywords, e.g.
    "podcast interview popular 2026". Deterministic filters from config.
    If strict filters reject everything, one relaxed pass runs
    (10+ min, 90 days, 10k+ views) before giving up.
    """
    cfg = C.load_config()
    r_cfg = cfg.get("research", {})
    preset = C.niche_preset(niche)
    keywords = " ".join(preset.get("keywords", [niche]))
    query = f"{keywords} full episode"
    n = max_results or r_cfg.get("max_results", 15)

    global last_error, last_stderr, last_stats
    last_error, last_stderr, last_stats = "", "", {}
    if not C.ytdlp_available():
        last_error = "missing"
        log.error("yt-dlp nahi mila — setup.py dobara chalao "
                  "(pip install yt-dlp).")
        return []

    cmd = (_ytdlp() + ["--skip-download", "--flat-playlist",
            "--print", "%(.{id,title,channel,duration,view_count,upload_date})j",
            f"ytsearch{n}:{query}"]
           + antibot_args())
    out = _run(cmd, note_stderr=True)
    if out is None:
        last_error = "search_failed"
        log.warning("YouTube search failed (network or bot-check). "
                    "Try again later, or paste a video link directly.")
        return []

    entries = _parse_entries(out)
    min_dur = r_cfg.get("min_duration_min", 20) * 60
    max_age = r_cfg.get("max_age_days", 30) * 86400
    min_views = r_cfg.get("min_views", 50000)

    results = _filter_entries(entries, min_dur, max_age, min_views)
    relaxed = False
    if not results:
        # relaxed pass — looser quality bar beats zero clips
        results = _filter_entries(entries, 10 * 60, 90 * 86400, 10000)
        relaxed = bool(results)
    last_stats = {"found": len(entries), "kept": len(results),
                  "relaxed": relaxed}
    if not results:
        last_error = "filtered_out"
    log.info("research: %d/%d candidates for niche %r (relaxed=%s)",
             len(results), len(entries), niche, relaxed)
    return results
