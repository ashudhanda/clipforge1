"""Download ONLY the selected moments — never the full video.

Verified behavior (yt-dlp source, 2026-09): `--download-sections` sets
section_start/section_end, but ONLY the external ffmpeg downloader honors
them (via -ss/-t input seeking, which uses HTTP range requests — MBs, not
GBs). The default native downloaders ignore sections and pull the whole
file. So every call here passes `--downloader ffmpeg`.

Format: best mp4 <= configured height (default 720p) + m4a audio, merged
by yt-dlp automatically.

download_section() retries once, then verifies the file actually has a
video stream (via ffmpeg). Never raises — returns None on failure so the
pipeline can skip that moment and continue with the rest.
"""

import logging
import subprocess
from pathlib import Path

from . import config as C
from .research import antibot_args

log = logging.getLogger("clipforge")


def _fmt_ts(s):
    """Seconds -> HH:MM:SS.mmm for --download-sections."""
    s = max(0.0, float(s))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{sec:06.3f}"


def _has_video(path):
    """True when the file has a decodable video stream. Never raises."""
    try:
        from .editor import probe_streams
        return bool(probe_streams(path)["has_video"])
    except Exception:
        return False


def download_section(video_url, start, end, out_path, height=None,
                     retries=1):
    """Download [start, end] seconds only. Returns Path or None."""
    cfg = C.load_config()
    height = height or cfg.get("download_height", 720)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    section = f"*{_fmt_ts(start)}-{_fmt_ts(end)}"
    fmt = (f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/"
           f"b[height<={height}][ext=mp4]/b")

    for attempt in range(retries + 1):
        if out_path.exists():
            out_path.unlink()
        cmd = ([C.ytdlp_path(), "--downloader", "ffmpeg",
                "--download-sections", section,
                "-f", fmt, "--no-playlist",
                "-o", str(out_path), "--no-warnings"]
               + antibot_args() + [video_url])
        try:
            p = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=1800)
        except subprocess.TimeoutExpired:
            log.warning("section download timed out (%.0fs-%.0fs)", start, end)
            continue
        except FileNotFoundError:
            log.error("yt-dlp nahi mila — setup.py dobara chalao")
            return None
        if p.returncode == 0 and out_path.exists() and _has_video(out_path):
            log.info("downloaded section %.0fs-%.0fs (%.1fMB)",
                     start, end, out_path.stat().st_size / 1e6)
            return out_path
        err = (p.stderr or p.stdout or "")[-300:].strip()
        log.warning("section download failed (attempt %d/%d): %s",
                    attempt + 1, retries + 1, err or "unknown error")
    return None
