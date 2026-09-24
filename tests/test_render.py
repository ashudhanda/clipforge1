"""ClipForge render test — synthetic media, no network.

Builds a 30s 1080x1920 test video with audio, then runs the real
editor.render() (smart crop, hook card, karaoke captions, zoom,
silence trim, loudnorm) and the quality gate. Verifies with the
ffmpeg-based probes.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TMPHOME = tempfile.mkdtemp(prefix="cf_render_home_")
os.environ["HOME"] = TMPHOME
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clipforge import config as C
from clipforge import editor as ED

FF = C.ffmpeg_path()
print("ffmpeg:", FF)
TD = Path(tempfile.mkdtemp(prefix="cf_render_"))
SRC = TD / "src.mp4"

# 30s 1080x1920 testsrc + sine audio (with 1s silence at start to
# exercise the silence trimmer)
p = subprocess.run(
    [FF, "-hide_banner", "-y", "-v", "error",
     "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=30",
     "-f", "lavfi", "-i", "sine=frequency=440:duration=30",
     "-af", "adelay=1000|1000",
     "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
     "-c:a", "aac", "-shortest", str(SRC)],
    capture_output=True, text=True, timeout=300)
assert p.returncode == 0 and SRC.exists(), p.stderr[-500:]
print("synthetic src:", SRC, SRC.stat().st_size // 1024, "KB")

info = ED.probe_streams(SRC)
print("probe:", info)
assert (info["width"], info["height"]) == (1080, 1920), info
assert 29 <= info["duration"] <= 31, info["duration"]
assert info["has_audio"] is True

# word timings across the 30s
text = ("this is a test of the clipforge rendering pipeline with burned "
        "karaoke captions and a hook card on top ".split())
words = [(1.5 + i * 0.5, 1.9 + i * 0.5, w) for i, w in enumerate(text * 2)][:40]

OUT = TD / "out.mp4"
out, shifted = ED.render(
    SRC, OUT, words=words, caption_style="hormozi",
    hook_text="RENDER TEST?!", hook_mode="card", max_dur_s=58)
print("rendered:", out, "shifted words:", len(shifted))
assert Path(out).exists() and Path(out).stat().st_size > 100_000

oinfo = ED.probe_streams(out)
print("output probe:", oinfo)
assert (oinfo["width"], oinfo["height"]) == (1080, 1920), oinfo
assert oinfo["has_audio"] is True
assert 20 <= oinfo["duration"] <= 58, oinfo["duration"]
# silence trim should have cut the leading 1s of silence
assert oinfo["duration"] < 29.5, f"silence not trimmed? {oinfo['duration']}"

# quality gate (same one the pipeline uses)
from clipforge import pipeline as PL
ok, reason = PL._gate_clip(out, "Render test clip title here")
print("gate:", ok, reason)
assert ok, reason

print("\nRENDER TEST PASSED")
