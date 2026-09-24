"""ClipForge configuration.

All user data lives under ~/.clipforge/ (Path.home() based — no hardcoded
paths, works on any OS/user):

    ~/.clipforge/
        config.yaml      user settings (channel, niche, styles, ...). 0644.
        secrets.yaml     LLM keys etc. 0600 — never logged.
        token.json       YouTube OAuth token. 0600 — never logged.
        assets/          face_yunet.onnx (face-aware crop model)
        clips/           finished Shorts + sidecar JSONs
        tmp/             scratch downloads
        db.json          clips/jobs/quota database (see store.py)

First run: `clipforge setup` walks through a wizard and writes config.yaml.
"""

import os
import stat
from pathlib import Path

import yaml

HOME = Path.home() / ".clipforge"
CONFIG_FILE = HOME / "config.yaml"
SECRETS_FILE = HOME / "secrets.yaml"
TOKEN_FILE = HOME / "token.json"
ASSETS_DIR = HOME / "assets"
CLIPS_DIR = HOME / "clips"
TMP_DIR = HOME / "tmp"
DB_FILE = HOME / "db.json"
FACE_MODEL = ASSETS_DIR / "face_yunet.onnx"

# Default caption style must exist in captions.STYLES.
DEFAULTS = {
    "channel_name": "",
    "niche": "podcast",
    "clips_per_run": 5,
    "caption_style": "hormozi",
    "hook_mode": "card",          # card | cold | off
    "title_max_len": 100,
    "hashtags": ["#Shorts"],
    "made_for_kids": False,       # REQUIRED by the YouTube API on upload
    "privacy": "public",          # public | unlisted | private
    "youtube_category_id": "22",  # People & Blogs
    "min_clip_s": 25,
    "max_clip_s": 58,
    "segment_pad_s": 3.0,
    "download_height": 720,
    "ffmpeg_path": "",            # auto-detected (imageio-ffmpeg, then PATH)
    "niche_presets": {
        "podcast":  {"window_min_s": 40, "window_max_s": 70,
                     "keywords": ["podcast", "interview", "conversation"]},
        "gaming":   {"window_min_s": 20, "window_max_s": 40,
                     "keywords": ["gameplay", "gaming", "highlights"]},
        "finance":  {"window_min_s": 30, "window_max_s": 60,
                     "keywords": ["money", "investing", "finance", "stocks"]},
        "motivation": {"window_min_s": 30, "window_max_s": 60,
                     "keywords": ["motivation", "mindset", "success"]},
    },
    "llm": {
        "provider": "none",       # none | gemini | openai_compat
        "model": "",
        "base_url": "",           # openai_compat only, e.g. Groq/OpenRouter/Ollama
    },
    "research": {
        "min_duration_min": 20,
        "max_age_days": 30,
        "min_views": 50000,
        "max_results": 15,
    },
}

_config_cache = None
_secrets_cache = None


def _read_yaml(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _deep_merge(base, override):
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(refresh=False):
    """Merged config dict (defaults + ~/.clipforge/config.yaml). Never raises."""
    global _config_cache
    if _config_cache is None or refresh:
        _config_cache = _deep_merge(DEFAULTS, _read_yaml(CONFIG_FILE))
    return _config_cache


def save_config(cfg):
    """Write user config (never stores secrets — those go to secrets.yaml)."""
    HOME.mkdir(parents=True, exist_ok=True)
    clean = {k: v for k, v in cfg.items()}
    CONFIG_FILE.write_text(yaml.safe_dump(clean, sort_keys=False,
                                          allow_unicode=True),
                           encoding="utf-8")


def load_secrets(refresh=False):
    """Secrets dict. File is created with 0600; never logged anywhere."""
    global _secrets_cache
    if _secrets_cache is None or refresh:
        _secrets_cache = _read_yaml(SECRETS_FILE)
    return _secrets_cache


def save_secrets(secrets):
    HOME.mkdir(parents=True, exist_ok=True)
    SECRETS_FILE.write_text(yaml.safe_dump(dict(secrets), sort_keys=False),
                            encoding="utf-8")
    _lock_down(SECRETS_FILE)


def _lock_down(path):
    """chmod 0600 — owner read/write only. Best effort on Windows."""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def lock_down(path):
    _lock_down(Path(path))


def ensure_dirs():
    for d in (HOME, ASSETS_DIR, CLIPS_DIR, TMP_DIR):
        d.mkdir(parents=True, exist_ok=True)


def ffmpeg_path():
    """Resolve an ffmpeg binary: config override -> imageio-ffmpeg -> PATH."""
    cfg = load_config()
    override = (cfg.get("ffmpeg_path") or "").strip()
    if override and Path(override).exists():
        return str(Path(override))
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return str(exe)
    except Exception:
        pass
    return "ffmpeg"  # fall back to PATH; caller reports a clear error if missing


def ytdlp_path():
    """Resolve the yt-dlp binary (pip venv -> PATH)."""
    import shutil
    exe = shutil.which("yt-dlp")
    return exe or "yt-dlp"  # callers catch FileNotFoundError with a hint


def niche_preset(niche_name):
    cfg = load_config()
    presets = cfg.get("niche_presets") or {}
    name = (niche_name or cfg.get("niche") or "podcast").lower()
    base = {"window_min_s": 30, "window_max_s": 60, "keywords": [name]}
    preset = dict(base)
    preset.update(presets.get(name, {}))
    return preset
