"""Clip editor — turns one downloaded segment into a finished 9:16 Short.

Pipeline per segment:
1. smart_crop_x(): face-aware horizontal crop offset via YuNet (local
   ~230KB ONNX, CPU). Falls back to a centered crop — never raises.
2. trim_silence(): leading/trailing silence is cut (caption word timings
   are shifted by the exact trim so karaoke stays in sync).
3. render(): ffmpeg filter graph —
     - 1080x1920 full-bleed cover crop (face-aware offset or center)
     - subtle zoompan punch-in for the high-energy feel
     - ASS captions burned in (karaoke word-highlight in the chosen style)
     - loudnorm audio, libx264 veryfast crf 21, aac 128k, faststart

No voiceover (ClipForge rule). No letterboxing — always full-bleed 9:16.
"""

import logging
import re
import subprocess
import tempfile
from pathlib import Path

from . import config as C

log = logging.getLogger("clipforge")

OUT_W, OUT_H = 1080, 1920
_YUNET = None


def _ffmpeg():
    return C.ffmpeg_path()


def probe_duration(path):
    """Media duration in seconds. Parses `ffmpeg -i` stderr — never raises.

    (imageio-ffmpeg ships no ffprobe binary, so we don't depend on one.)
    """
    try:
        p = subprocess.run(
            [_ffmpeg(), "-hide_banner", "-i", str(path)],
            capture_output=True, text=True, timeout=60)
        m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", p.stderr or "")
        if not m:
            return 0.0
        return (int(m.group(1)) * 3600 + int(m.group(2)) * 60
                + float(m.group(3)))
    except Exception:
        return 0.0


def probe_dimensions(path):
    """Displayed (w, h) of the video stream — never raises.

    Decodes one real frame (so rotation metadata is honored — this is
    the DISPLAYED size, unlike container dims) and reads it with cv2.
    Returns (0, 0) on failure.
    """
    try:
        import cv2
        with tempfile.TemporaryDirectory() as td:
            png = str(Path(td) / "probe.png")
            subprocess.run(
                [_ffmpeg(), "-hide_banner", "-y", "-v", "error",
                 "-i", str(path), "-frames:v", "1", png],
                capture_output=True, timeout=120)
            img = cv2.imread(png)
            if img is None:
                return 0, 0
            h, w = img.shape[:2]
            return w, h
    except Exception:
        return 0, 0


def probe_streams(path):
    """One-shot media probe via `ffmpeg -i` stderr. Never raises.

    Returns {"duration", "width", "height", "has_video", "has_audio",
    "fps"}. Dimensions come from a decoded frame (rotation-safe).
    """
    info = {"duration": 0.0, "width": 0, "height": 0,
            "has_video": False, "has_audio": False, "fps": 0.0}
    try:
        p = subprocess.run(
            [_ffmpeg(), "-hide_banner", "-i", str(path)],
            capture_output=True, text=True, timeout=60)
        err = p.stderr or ""
        m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
        if m:
            info["duration"] = (int(m.group(1)) * 3600
                                + int(m.group(2)) * 60 + float(m.group(3)))
        for line in err.splitlines():
            if "Video:" in line:
                info["has_video"] = True
                mf = re.search(r"(\d+(?:\.\d+)?)\s+fps", line)
                if mf:
                    info["fps"] = float(mf.group(1))
            if "Audio:" in line:
                info["has_audio"] = True
        w, h = probe_dimensions(path)
        info["width"], info["height"] = w, h
    except Exception:
        pass
    return info


def _yunet():
    """Lazy singleton YuNet face detector."""
    global _YUNET
    if _YUNET is None:
        import cv2
        model = str(C.FACE_MODEL)
        _YUNET = cv2.FaceDetectorYN_create(model, "", (320, 320))
    return _YUNET


def smart_crop_x(seg):
    """Horizontal offset for the 9:16 cover crop, or None for center.

    Samples 1 fps, finds the median largest-face position. Never raises —
    any failure means a plain centered crop.
    """
    try:
        import cv2
        det = _yunet()
        sw, sh = probe_dimensions(seg)
        if sw <= 0 or sh <= 0:
            return None
        scale = max(OUT_W / sw, OUT_H / sh)
        max_x = sw * scale - OUT_W
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(
                [_ffmpeg(), "-hide_banner", "-y", "-v", "error",
                 "-i", str(seg), "-vf", "fps=1",
                 str(Path(td) / "f%03d.jpg")],
                capture_output=True, timeout=300)
            boxes = []
            for img_p in sorted(Path(td).glob("*.jpg")):
                img = cv2.imread(str(img_p))
                if img is None:
                    continue
                h, w = img.shape[:2]
                det.setInputSize((w, h))
                _, faces = det.detect(img)
                if faces is not None and len(faces):
                    f = max(faces, key=lambda r: r[2] * r[3])
                    boxes.append(float(f[0] + f[2] / 2))
        if not boxes or len(boxes) < 3:
            log.info("smart crop: no reliable face; center crop")
            return None
        med_cx = sorted(boxes)[len(boxes) // 2]
        crop_x = min(max(med_cx * scale - OUT_W / 2, 0.0), max_x)
        log.info("smart crop: face offset %.0f", crop_x)
        return crop_x
    except Exception as e:
        log.info("smart crop unavailable (%s); center crop",
                 str(e)[:100])
        return None


def detect_silence_trims(seg, max_trim_s=2.0):
    """Leading/trailing silence durations (seconds). Never raises.

    Only trims real silence at the very start/end (the padded moments
    often begin/end mid-breath). Capped so a quiet clip is never gutted.
    """
    lead, trail = 0.0, 0.0
    try:
        dur = probe_duration(seg)
        if dur <= 0:
            return 0.0, 0.0
        p = subprocess.run(
            [_ffmpeg(), "-hide_banner", "-v", "info", "-i", str(seg),
             "-af", "silencedetect=noise=-32dB:d=0.4", "-f", "null", "-"],
            capture_output=True, text=True, timeout=300)
        starts, ends = [], []
        for line in (p.stderr or "").splitlines():
            m = re.search(r"silence_start: ([\d.]+)", line)
            if m:
                starts.append(float(m.group(1)))
            m = re.search(r"silence_end: ([\d.]+)", line)
            if m:
                ends.append(float(m.group(1)))
        if starts and starts[0] < 0.05 and ends:
            lead = min(ends[0], max_trim_s)
        if starts and ends and starts[-1] > dur - max_trim_s - 0.5:
            # trailing silence runs to the end of the file
            trail = min(dur - starts[-1], max_trim_s)
        if lead:
            log.info("trimming %.2fs leading silence", lead)
        if trail:
            log.info("trimming %.2fs trailing silence", trail)
    except Exception as e:
        log.info("silence detect failed (%s); no trim", str(e)[:80])
    return lead, trail


def _shift_words(words, delta):
    return [(max(0.0, s + delta), max(0.0, e + delta), w)
            for s, e, w in words]


def render(seg, out_path, words=None, caption_style="hormozi",
           hook_text=None, hook_mode="card", crop_x=None,
           max_dur_s=58.0):
    """Render the finished Short. Returns (out_path, shifted_words).

    words: [(start, end, word)] in SEGMENT-relative seconds (from
    transcribing the downloaded segment). They are shifted by any
    silence trim so captions stay in sync; the shifted list is returned
    for the sidecar record.
    """
    from . import captions as CAP
    cfg = C.load_config()
    style = caption_style or cfg.get("caption_style", "hormozi")
    hook_mode = hook_mode or cfg.get("hook_mode", "card")
    max_dur_s = max_dur_s or cfg.get("max_clip_s", 58)

    seg = Path(seg)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. silence trim (shift caption timings to match)
    lead, trail = detect_silence_trims(seg)
    words = _shift_words(words or [], -lead)

    # 2. caption ASS
    ass_path = out_path.with_suffix(".ass")
    if words:
        ok = CAP.build_ass(words, ass_path, style=style,
                           hook_text=hook_text, hook_mode=hook_mode)
    else:
        ok = False
    if not ok:
        ass_path = None

    # 3. crop offset
    if crop_x is None:
        crop_x = smart_crop_x(seg)
    crop_part = ("crop=1080:1920:x=(in_w-1080)/2:y=(in_h-1920)/2"
                 if crop_x is None else
                 f"crop=1080:1920:x={crop_x:.0f}:y=(in_h-1920)/2")
    # punch-in zoom: 1.0 -> 1.18 over the clip, then hold
    zoom_part = ("zoompan=z='min(1.0+0.0012*on\\,1.18)':"
                 "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                 "d=1:s=1080x1920:fps=30")
    vf = (f"[0:v]fps=30,scale=1080:1920:force_original_aspect_ratio=increase,"
          f"{crop_part},{zoom_part}")
    if ass_path is not None:
        sp = str(ass_path).replace("\\", "/").replace(":", "\\:").replace("'", "")
        vf += f",subtitles='{sp}'"
    vf += "[vout]"
    af = ("[0:a]aresample=44100,loudnorm=I=-16:TP=-1.5:LRA=11,"
          "aformat=sample_fmts=fltp:channel_layouts=stereo[aout]")

    seg_dur = probe_duration(seg) or max_dur_s
    take = max(1.0, min(seg_dur - lead - trail, max_dur_s))
    cmd = [_ffmpeg(), "-hide_banner", "-y", "-i", str(seg)]
    if lead > 0.01:
        # -ss AFTER -i: frame-accurate (fast seek snaps to keyframes,
        # which would desync the shifted caption timings)
        cmd += ["-ss", f"{lead:.2f}"]
    cmd += ["-t", f"{take:.2f}",
            "-filter_complex", vf + ";" + af,
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", str(out_path)]
    log.info("rendering %s (%.0fs)...", out_path.name, take)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if p.returncode != 0 or not out_path.exists():
        err = (p.stderr or "")[-600:].strip()
        raise RuntimeError(f"ffmpeg render failed: {err}")
    try:
        if ass_path is not None:
            ass_path.unlink()
    except OSError:
        pass
    log.info("built short: %s (%.1fMB)", out_path.name,
             out_path.stat().st_size / 1e6)
    return out_path, words
