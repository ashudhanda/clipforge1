"""Near-duplicate detection for ClipForge clips.

Two rules:
1. source-url dedup: clips already built from a source video are skipped
   (see store.source_video_used).
2. perceptual dedup: dHash (difference hash, 64-bit) of each finished
   clip's hook frame (~0.8s). A new clip within HAMMING_THRESHOLD bits of
   any stored clip is rejected — catches the failure mode of same
   speaker + same background + slightly different captions.

Stdlib + cv2 + numpy only. Never raises: on any failure the check is
skipped and the caller logs loudly.
"""

import logging
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("clipforge")

HAMMING_THRESHOLD = 8  # bits
HOOK_FRAME_T = 0.8     # seconds into the clip


def _ffmpeg_bin():
    from . import config as C
    return C.ffmpeg_path()


def _dhash_bits(img_bgr, hash_size=8):
    import cv2
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (hash_size + 1, hash_size),
                       interpolation=cv2.INTER_AREA)
    return (small[:, 1:] > small[:, :-1]).flatten()


def dhash_hex(img_bgr):
    bits = _dhash_bits(img_bgr)
    return "%016x" % int("".join("1" if b else "0" for b in bits), 2)


def hamming(h1, h2):
    return bin(int(h1, 16) ^ int(h2, 16)).count("1")


def hook_frame_dhash(mp4_path, t=HOOK_FRAME_T):
    """dHash of the frame at t seconds. Returns hex str or None."""
    try:
        import cv2
        with tempfile.TemporaryDirectory() as td:
            jpg = str(Path(td) / "hook.jpg")
            p = subprocess.run(
                [_ffmpeg_bin(), "-hide_banner", "-y", "-v", "error",
                 "-ss", f"{t:.2f}", "-i", str(mp4_path),
                 "-frames:v", "1", "-q:v", "3", jpg],
                capture_output=True, text=True, timeout=120)
            if p.returncode != 0:
                return None
            img = cv2.imread(jpg)
            if img is None:
                return None
            return dhash_hex(img)
    except Exception as e:
        log.warning("hook_frame_dhash failed (%s)", str(e)[:100])
        return None


def is_near_duplicate(new_hash, existing_hashes,
                      threshold=HAMMING_THRESHOLD):
    try:
        for h in existing_hashes or []:
            if h and hamming(new_hash, h) <= threshold:
                return True
        return False
    except Exception:
        return False
