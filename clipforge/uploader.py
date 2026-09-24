"""YouTube upload via the official Data API v3.

Setup (one time, guided by README + `clipforge setup`):
  1. Google Cloud Console -> new project -> enable "YouTube Data API v3"
  2. Create OAuth client ID (Desktop app) -> download client_secret.json
  3. Save it as ~/.clipforge/client_secret.json
  4. `clipforge setup` opens a browser for Google sign-in (one click)

After that the OAuth token lives at ~/.clipforge/token.json (0600) and
refreshes itself automatically — the user never thinks about it again.

API notes that matter:
  - madeForKids is REQUIRED on every upload (config made_for_kids),
    otherwise the API rejects the request.
  - One upload costs 1600 quota units of the 10000/day default quota
    (~6 uploads/day). Quota is tracked in store and the scheduler
    spreads uploads across days when it runs out.
  - Vertical videos <= 3 min upload as Shorts automatically.

upload_video() returns the watch URL, or None on failure (never raises).
"""

import logging
from pathlib import Path

from . import config as C
from . import store

log = logging.getLogger("clipforge")

_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
_CLIENT_SECRET = C.HOME / "client_secret.json"


def _imports():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    return (Request, Credentials, InstalledAppFlow, build, HttpError,
            MediaFileUpload)


def authorize():
    """Run the OAuth browser flow. Returns True on success.

    Plain-language errors: the #1 beginner failure is a missing
    client_secret.json, which gets a step-by-step hint, not a traceback.
    """
    try:
        (Request, Credentials, InstalledAppFlow, build, HttpError,
         MediaFileUpload) = _imports()
    except ImportError:
        log.error("Google API libraries missing — run setup.py again")
        return False
    if not _CLIENT_SECRET.exists():
        log.error(
            "client_secret.json nahi mila ~/.clipforge/ mein.\n"
            "YouTube upload ke liye ek baar ye karna hoga:\n"
            "  1. console.cloud.google.com -> new project\n"
            "  2. 'YouTube Data API v3' enable karo\n"
            "  3. Credentials -> Create Credentials -> OAuth client ID "
            "(Desktop app)\n"
            "  4. Download karke ~/.clipforge/client_secret.json naam se rakho\n"
            "  5. Phir `clipforge setup` dobara chalao")
        return False
    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(_CLIENT_SECRET), _SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")
        C.TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        C.lock_down(C.TOKEN_FILE)
        log.info("YouTube login ho gaya — token save ho gaya (dobara nahi "
                 "poochhega)")
        return True
    except Exception as e:
        log.error("YouTube login fail hua (%s)", str(e)[:200])
        return False


def get_credentials():
    """Valid credentials, refreshing silently. None when not authorized."""
    try:
        (Request, Credentials, InstalledAppFlow, build, HttpError,
         MediaFileUpload) = _imports()
    except ImportError:
        return None
    if not C.TOKEN_FILE.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(C.TOKEN_FILE),
                                                      _SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            C.TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
            C.lock_down(C.TOKEN_FILE)
            log.info("YouTube token refresh ho gaya")
        if creds.valid:
            return creds
    except Exception as e:
        log.warning("YouTube token invalid (%s) — `clipforge setup` se "
                    "dobara login karo", str(e)[:120])
    return None


def is_authorized():
    return get_credentials() is not None


def upload_video(mp4_path, title, description, tags=(), privacy=None,
                 category_id=None, made_for_kids=None):
    """Upload one Short. Returns the youtube watch URL, or None."""
    cfg = C.load_config()
    privacy = privacy or cfg.get("privacy", "public")
    category_id = category_id or cfg.get("youtube_category_id", "22")
    if made_for_kids is None:
        made_for_kids = bool(cfg.get("made_for_kids", False))

    if store.quota_remaining() < store.QUOTA_PER_UPLOAD:
        log.warning("YouTube quota khatam (10000/day). Kal phir try karo, "
                    "ya schedule kar do — scheduler khud next day upload "
                    "karega.")
        return None
    creds = get_credentials()
    if not creds:
        log.error("YouTube login nahi hai — pehle `clipforge setup` chalao")
        return None
    try:
        (Request, Credentials, InstalledAppFlow, build, HttpError,
         MediaFileUpload) = _imports()
        yt = build("youtube", "v3", credentials=creds,
                   cache_discovery=False)
        body = {
            "snippet": {
                "title": title[:100],
                "description": description or "",
                "tags": list(tags or [])[:30],
                "categoryId": str(category_id),
            },
            "status": {
                "privacyStatus": privacy,
                "madeForKids": bool(made_for_kids),
            },
        }
        media = MediaFileUpload(str(mp4_path), mimetype="video/mp4",
                                resumable=True, chunksize=8 * 1024 * 1024)
        req = yt.videos().insert(part="snippet,status", body=body,
                                 media_body=media)
        resp = None
        while resp is None:
            status, resp = req.next_chunk()
        video_id = resp.get("id")
        store.quota_consume(store.QUOTA_PER_UPLOAD)
        url = f"https://www.youtube.com/watch?v={video_id}"
        log.info("uploaded: %s", url)
        return url
    except HttpError as e:
        log.error("YouTube upload fail: %s", str(e)[:300])
    except Exception as e:
        log.error("YouTube upload fail (%s)", type(e).__name__)
    return None
