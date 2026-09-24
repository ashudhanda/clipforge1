"""YouTube research — find candidate long videos for a niche. NO download.

Uses `yt-dlp ytsearchN:"query"` (no API key needed), then filters:
    - duration >= min_duration_min (long videos only — podcasts etc.)
    - uploaded within max_age_days (recent)
    - view_count >= min_views (popular)
    - skips live/upcoming/premiere entries

Returns [{video_id, title, channel, duration_s, view_count, upload_date,
url}]. Never raises — returns [] when search fails (caller logs plainly).
"""

import json
import logging
import subprocess
import time

from . import config as C

log = logging.getLogger("clipforge")

def _ytdlp():
    return C.ytdlp_path()


def _impersonation_ok():
    """True when yt-dlp can do TLS impersonation (needs curl_cffi)."""
    try:
        import curl_cffi  # noqa: F401
        return True
    except ImportError:
        return False


def antibot_args():
    """Args that keep yt-dlp working on strict networks.

    player_client=web_embedded,default completes downloads where other
    clients get 403s; chrome-136 TLS impersonation helps on datacenter IPs
    (skipped gracefully when curl_cffi isn't installed);
    cookies.txt (if the user exported one) is the strongest signal.
    """
    args = ["--extractor-args", "youtube:player_client=web_embedded,default"]
    if _impersonation_ok():
        args += ["--impersonate", "chrome-136"]
    cookies = C.HOME / "cookies.txt"
    if cookies.exists():
        args += ["--cookies", str(cookies)]
    return args


def _run(cmd, timeout=180):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError:
        log.error("yt-dlp nahi mila — setup.py dobara chalao")
        return None
    if p.returncode != 0:
        return None
    return p.stdout


def video_meta(url):
    """Title/channel for one video URL — no download. Returns {} on failure."""
    out = _run([_ytdlp(), "--skip-download", "--print",
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
    """
    cmd = ([_ytdlp(), "--skip-download",
            "--print", "%(.{id,title,channel,duration,view_count,upload_date,live_status})j",
            url] + antibot_args())
    out = _run(cmd, timeout=120)
    if not out:
        return None
    try:
        return json.loads(out.strip().splitlines()[0])
    except Exception:
        return None


def discover(niche, max_results=None):
    """Search YouTube for recent, popular long videos in `niche`.

    Two stages, zero downloads:
      1. flat `ytsearch` (fast) for candidate entries;
      2. per-video metadata for entries missing a duration, so the
         long-video filter never drops a good video on missing data.

    Query combines the niche with its preset keywords, e.g.
    "podcast interview popular 2026". Deterministic filters from config.
    """
    cfg = C.load_config()
    r_cfg = cfg.get("research", {})
    preset = C.niche_preset(niche)
    keywords = " ".join(preset.get("keywords", [niche]))
    query = f"{keywords} full episode"
    n = max_results or r_cfg.get("max_results", 15)

    cmd = ([_ytdlp(), "--skip-download", "--flat-playlist",
            "--print", "%(.{id,title,channel,duration,view_count,upload_date})j",
            f"ytsearch{n}:{query}"]
           + antibot_args())
    out = _run(cmd)
    if out is None:
        log.warning("YouTube search failed (network or bot-check). "
                    "Try again later, or paste a video link directly.")
        return []

    min_dur = r_cfg.get("min_duration_min", 20) * 60
    max_age = r_cfg.get("max_age_days", 30) * 86400
    min_views = r_cfg.get("min_views", 50000)
    now = time.time()
    results = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            v = json.loads(line)
        except Exception:
            continue
        vid = v.get("id")
        if not vid:
            continue
        dur = v.get("duration") or 0
        if not dur:
            # stage 2: flat entries don't always carry duration
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
    log.info("research: %d candidates for niche %r", len(results), niche)
    return results
