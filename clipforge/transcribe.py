"""Transcription fallback — only used when a video has NO captions.

Downloads AUDIO ONLY (a few MB even for a 2-hour video — never the video),
then runs faster-whisper locally with VAD (silence skipping), which makes
it 2-4x faster than plain transcription.

Plain-language progress is logged because a long video can still take a
while: "Transcription slow hai — ye normal hai, ~X min lagenge."

Returns [{start, end, text}] (segment-level; word timings when available
are attached as segment["words"] = [(start, end, word)]). Never raises —
returns [] on failure.
"""

import logging
import subprocess
import tempfile
from pathlib import Path

from . import config as C
from .research import antibot_args

log = logging.getLogger("clipforge")

_MODEL = None


def _model():
    """Lazy singleton faster-whisper model (downloads weights on first use)."""
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        size = C.load_config().get("whisper_model", "base")
        log.info("loading transcription model %r (first run downloads it, "
                 "one time)", size)
        _MODEL = WhisperModel(size, device="cpu", compute_type="int8")
    return _MODEL


def download_audio(video_url, out_dir):
    """Audio-only download. Returns Path or None."""
    out = Path(out_dir) / "audio.m4a"
    cmd = ([C.ytdlp_path(), "-x", "--audio-format", "m4a",
            "--audio-quality", "5",
            "-o", str(out), "--no-warnings"]
           + antibot_args() + [video_url])
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
        if p.returncode == 0 and out.exists():
            return out
        log.warning("audio download failed: %s", (p.stderr or "")[-200:])
    except Exception as e:
        log.warning("audio download error (%s)", type(e).__name__)
    return None


def transcribe_audio(audio_path, word_timestamps=True):
    """Run faster-whisper. Returns [{start, end, text, words?}]."""
    segments = []
    try:
        model = _model()
        wav = str(audio_path)
        log.info("transcribing audio (VAD on) — long videos take a while, "
                 "ye normal hai...")
        result, _info = model.transcribe(
            wav, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            word_timestamps=word_timestamps)
        for seg in result:
            words = []
            if word_timestamps and getattr(seg, "words", None):
                words = [(w.start, w.end, w.word.strip())
                         for w in seg.words if w.word.strip()]
            text = (seg.text or "").strip()
            if text:
                segments.append({"start": float(seg.start),
                                 "end": float(seg.end),
                                 "text": text, "words": words})
        log.info("transcribed %d segments", len(segments))
    except ImportError:
        log.warning("faster-whisper not installed — run setup.py again")
    except Exception as e:
        log.warning("transcription failed (%s)", type(e).__name__)
    return segments


def transcribe_video(video_url, work_dir=None):
    """Full fallback: audio download + transcription. Returns segments."""
    td = work_dir or tempfile.mkdtemp(prefix="cf_tr_")
    audio = download_audio(video_url, td)
    if not audio:
        return []
    try:
        return transcribe_audio(audio)
    finally:
        try:
            audio.unlink()
        except OSError:
            pass
