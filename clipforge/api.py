"""ClipForge service layer — what the dashboard (later) plugs into.

Thin wrappers over the pipeline modules. Every function returns
JSON-serializable dicts/lists (no Path objects, no exceptions leaking).
The dashboard will call these; the CLI calls them too (single backend).

start_auto/start_link run synchronously by default (the CLI waits).
Pass background=True and they return immediately with a job_id —
poll get_status(job_id) for progress (the dashboard will use this).

Nothing here touches the network directly except through pipeline /
uploader / scheduler.
"""

import threading
import time
import json

from . import config as C
from . import store


def _clip_json(c):
    if not c:
        return None
    c = dict(c)
    c.pop("hook_dhash", None)  # internal bookkeeping, not for UI
    return c


# ---------------------------------------------------------------- clips
def list_clips(status=None):
    return [_clip_json(c) for c in store.list_clips(status=status)]


def get_clip(clip_id):
    return _clip_json(store.get_clip(clip_id))


def approve_clip(clip_id):
    """Mark a queued clip approved (ready to upload/schedule)."""
    c = store.get_clip(clip_id)
    if not c:
        return {"ok": False, "error": f"clip nahi mila: {clip_id}"}
    if c.get("status") not in ("queued", "rejected"):
        return {"ok": False,
                "error": f"ye clip {c.get('status')} hai — approve nahi ho sakta"}
    store.update_clip(clip_id, status="approved")
    return {"ok": True, "clip": _clip_json(store.get_clip(clip_id))}


def reject_clip(clip_id):
    c = store.get_clip(clip_id)
    if not c:
        return {"ok": False, "error": f"clip nahi mila: {clip_id}"}
    store.update_clip(clip_id, status="rejected")
    return {"ok": True}


def delete_clip(clip_id):
    c = store.get_clip(clip_id)
    if not c:
        return {"ok": False, "error": f"clip nahi mila: {clip_id}"}
    from pathlib import Path
    try:
        f = c.get("file")
        if f:
            Path(f).unlink(missing_ok=True)
    except OSError:
        pass
    store.delete_clip(clip_id)
    return {"ok": True}


# ---------------------------------------------------------------- jobs
def _run_background(kind, params, fn):
    """Run fn() in a daemon thread. Returns {"job_id"} immediately.

    The wrapper job tracks the background task; fn() (the pipeline)
    creates and updates its own inner job with stage progress.
    Poll get_status() on the wrapper job_id.
    """
    job_id = store.new_job(kind, dict(params, background=True))

    def _target():
        try:
            res = fn()
            inner = (res or {}).get("job_id")
            store.update_job(job_id, status="done", result=res,
                             message=(res or {}).get("error")
                             or f"{len((res or {}).get('clips', []))} clips taiyaar",
                             inner_job_id=inner, progress=1.0)
        except Exception as e:
            store.update_job(job_id, status="failed",
                             error=str(e)[:200])

    threading.Thread(target=_target, daemon=True,
                     name=f"clipforge-{kind}").start()
    return {"job_id": job_id, "background": True}


def start_auto(niche=None, n_clips=None, caption_style=None,
               progress_cb=None, background=False):
    """Start a research run. Sync: {"job_id", "clips", "error"}.
    background=True: returns {"job_id"} immediately; poll get_status()."""
    from . import pipeline as P
    if background:
        return _run_background(
            "auto", {"niche": niche, "n_clips": n_clips},
            lambda: P.auto_mode(niche, n_clips, caption_style,
                                progress_cb))
    return P.auto_mode(niche, n_clips, caption_style, progress_cb)


def start_link(url, n_clips=None, caption_style=None, progress_cb=None,
               background=False):
    """Start a link run. Sync: {"job_id", "clips", "error"}.
    background=True: returns {"job_id"} immediately; poll get_status()."""
    from . import pipeline as P
    if background:
        return _run_background(
            "link", {"url": url, "n_clips": n_clips},
            lambda: P.link_mode(url, n_clips, caption_style,
                                progress_cb))
    return P.link_mode(url, n_clips, caption_style, progress_cb)


def get_status(job_id):
    j = store.get_job(job_id)
    if not j:
        return {"ok": False, "error": f"job nahi mila: {job_id}"}
    return {"ok": True, "job": j}


# ---------------------------------------------------------------- upload / schedule
def upload_clip(clip_id):
    """Upload one approved clip to YouTube now."""
    from . import uploader as U
    c = store.get_clip(clip_id)
    if not c:
        return {"ok": False, "error": f"clip nahi mila: {clip_id}"}
    if c.get("status") == "uploaded":
        return {"ok": False, "error": "ye clip pehle hi upload ho chuka hai"}
    if c.get("status") not in ("approved", "queued", "scheduled"):
        return {"ok": False,
                "error": f"status {c.get('status')} — pehle approve karo"}
    url = U.upload_video(c["file"], c.get("title", ""),
                         c.get("description", ""), c.get("hashtags", []))
    if url:
        # a manual upload cancels any pending scheduled job for this clip
        # (otherwise the worker would upload it a second time)
        store.cancel_upload_jobs_for_clip(clip_id)
        store.update_clip(clip_id, status="uploaded", youtube_url=url,
                          uploaded_at=time.time())
        return {"ok": True, "url": url}
    return {"ok": False,
            "error": "upload fail hua — quota khatam ho sakti hai ya login "
                     "chahiye (`clipforge setup`)"}


def schedule_clip(clip_id, at):
    from . import scheduler as S
    ok, msg = S.schedule_clip(clip_id, at)
    return {"ok": ok, "message" if ok else "error": msg}


def cancel_schedule(clip_id):
    from . import scheduler as S
    ok, msg = S.cancel_schedule(clip_id)
    return {"ok": ok, "message" if ok else "error": msg}


def list_scheduled():
    from . import scheduler as S
    return S.list_scheduled()


def run_worker_once():
    """Process due scheduled uploads. For `clipforge worker` / cron."""
    from . import scheduler as S
    return S.check_due()


def quota():
    return {"used": store.quota_used_today(),
            "remaining": store.quota_remaining(),
            "per_day": store.QUOTA_PER_DAY,
            "per_upload": store.QUOTA_PER_UPLOAD}


def youtube_authorized():
    from . import uploader as U
    return U.is_authorized()


# ---------------------------------------------------------------- config
def get_config():
    # config.yaml never holds secrets (those live in secrets.yaml),
    # so the whole config is safe to return.
    return dict(C.load_config())


def is_first_run():
    """True when the user hasn't completed setup yet."""
    if not C.CONFIG_FILE.exists():
        return True
    cfg = C.load_config()
    return not (cfg.get("channel_name") or "").strip()


def update_config(patch):
    """Update user config (keys must already exist in defaults)."""
    cfg = C.load_config()
    allowed = set(C.DEFAULTS)
    for k, v in (patch or {}).items():
        if k in allowed:
            cfg[k] = v
    C.save_config(cfg)
    C.load_config(refresh=True)
    return {"ok": True, "config": get_config()}


def update_clip_meta(clip_id, patch):
    """Edit a clip's title/description/hashtags/caption_style before upload."""
    c = store.get_clip(clip_id)
    if not c:
        return {"ok": False, "error": f"clip nahi mila: {clip_id}"}
    if c.get("status") == "uploaded":
        return {"ok": False, "error": "uploaded clip edit nahi ho sakta"}
    allowed = {"title", "description", "hashtags", "caption_style"}
    fields = {k: v for k, v in (patch or {}).items() if k in allowed}
    if isinstance(fields.get("hashtags"), str):
        fields["hashtags"] = [h.strip() for h in fields["hashtags"].split()
                              if h.strip()]
    if "title" in fields and isinstance(fields["title"], str):
        fields["title"] = fields["title"][:100]
    store.update_clip(clip_id, **fields)
    return {"ok": True, "clip": _clip_json(store.get_clip(clip_id))}


def caption_styles():
    from . import captions as CAP
    return CAP.list_styles()


# ---------------------------------------------------------------- youtube auth (dashboard buttons)
_oauth_running = False


def youtube_connect():
    """Start the OAuth browser flow in a background thread.

    Returns immediately; poll youtube_authorized() for the result.
    Fails fast when client_secret.json is missing (with a hint).
    """
    global _oauth_running
    from . import uploader as U
    if _oauth_running:
        return {"ok": True, "started": True, "note": "login already chal raha hai"}
    if not C.TOKEN_FILE.exists() and not (C.HOME / "client_secret.json").exists():
        return {"ok": False,
                "error": "OAuth JSON set nahi hai. Dashboard → Settings → "
                         "YouTube connection mein client_secret.json ka content "
                         "paste karke Save dabao, phir Connect karo."}

    def _run():
        global _oauth_running
        try:
            U.authorize()
        finally:
            _oauth_running = False

    _oauth_running = True
    import threading
    threading.Thread(target=_run, daemon=True,
                     name="clipforge-oauth").start()
    return {"ok": True, "started": True}


def youtube_disconnect():
    try:
        C.TOKEN_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": True}


def client_secret_status():
    """Is the Google OAuth client_secret.json configured? (never returns its content)"""
    p = C.HOME / "client_secret.json"
    if not p.exists():
        return {"configured": False}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        section = data.get("installed") or data.get("web") or {}
        ok = bool(section.get("client_id") and section.get("client_secret"))
        return {"configured": ok}
    except Exception:
        return {"configured": False, "invalid": True}


def save_client_secret(json_text):
    """Save Google OAuth client credentials pasted from the dashboard.

    Accepts the full client_secret.json content (as downloaded from Google
    Cloud Console). Validates structure, writes with 0600 permissions.
    The secret is never echoed back.
    """
    import json as _json
    text = (json_text or "").strip()
    if not text:
        return {"ok": False, "error": "khaali hai — JSON paste karo"}
    try:
        data = _json.loads(text)
    except Exception:
        return {"ok": False,
                "error": "ye valid JSON nahi lag raha. Google Cloud se download "
                         "ki hui file ka poora content paste karo."}
    section = data.get("installed") or data.get("web")
    if not isinstance(section, dict) or not section.get("client_id") \
            or not section.get("client_secret"):
        return {"ok": False,
                "error": "is JSON mein OAuth client_id/client_secret nahi mile. "
                         "OAuth client ID (Desktop app) wali file download karo — "
                         "sirf API key se upload nahi hota."}
    C.HOME.mkdir(parents=True, exist_ok=True)
    dest = C.HOME / "client_secret.json"
    dest.write_text(_json.dumps(data, indent=2), encoding="utf-8")
    C.lock_down(dest)
    return {"ok": True}


# ---------------------------------------------------------------- llm keys (masked — never echoed back)
def llm_key_status():
    s = C.load_secrets().get("llm", {})
    return {"gemini_set": bool(s.get("gemini_key")),
            "openai_set": bool(s.get("openai_key"))}


def set_llm_key(provider, key):
    """Store an LLM key. Empty key clears it."""
    if provider not in ("gemini", "openai_compat"):
        return {"ok": False, "error": "provider galat hai"}
    s = C.load_secrets()
    s.setdefault("llm", {})
    field = "gemini_key" if provider == "gemini" else "openai_key"
    if key:
        s["llm"][field] = key
    else:
        s["llm"].pop(field, None)
    C.save_secrets(s)
    C.load_secrets(refresh=True)
    return {"ok": True, "set": bool(key)}


# ---------------------------------------------------------------- danger zone
def clear_cache():
    """Delete scratch downloads (tmp/). Never touches clips or config."""
    import shutil
    n = 0
    C.ensure_dirs()
    for p in C.TMP_DIR.iterdir():
        try:
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p)
            else:
                p.unlink()
            n += 1
        except OSError:
            pass
    return {"ok": True, "cleared": n}
