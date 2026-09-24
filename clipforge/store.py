"""ClipForge local database — the SINGLE backend for CLI and dashboard.

One JSON file (~/.clipforge/db.json) holding:
    clips: {clip_id: {...}}   finished / queued Shorts
    jobs:  {job_id: {...}}    research+build runs (for progress + history)
    quota: {date: "YYYY-MM-DD", used: int}  YouTube API units (10000/day)

All access goes through here with an OS file lock, so the CLI and the
dashboard can never corrupt each other's data. Never raises on lock
problems — falls back to uncontended access rather than crashing a run.
"""

import contextlib
import json
import time
import uuid
from pathlib import Path

from . import config as C

_SCHEMA = {"clips": {}, "jobs": {}, "quota": {"date": "", "used": 0}}


@contextlib.contextmanager
def _locked(path):
    """Yield an open file handle with an exclusive OS lock (best effort)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+b")
    locked = False
    try:
        try:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            locked = True
        except Exception:
            try:
                import msvcrt
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
                locked = True
            except Exception:
                pass
        yield fh
    finally:
        try:
            if locked:
                try:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
        finally:
            fh.close()


def _read():
    try:
        data = json.loads(C.DB_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return dict(_SCHEMA)
        for k, v in _SCHEMA.items():
            data.setdefault(k, v)
        return data
    except Exception:
        return {"clips": {}, "jobs": {}, "quota": {"date": "", "used": 0}}


def _write(data):
    tmp = C.DB_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(C.DB_FILE)


def _mutate(fn):
    with _locked(C.DB_FILE):
        data = _read()
        result = fn(data)
        _write(data)
        return result


# ---------------------------------------------------------------- clips
def save_clip(clip):
    """Insert/update a clip record. Returns the clip_id."""
    clip = dict(clip)
    clip.setdefault("clip_id", "clip_" + uuid.uuid4().hex[:12])
    clip["updated_at"] = time.time()

    def _do(data):
        data["clips"][clip["clip_id"]] = clip
        return clip["clip_id"]
    return _mutate(_do)


def get_clip(clip_id):
    with _locked(C.DB_FILE):
        return _read()["clips"].get(clip_id)


def list_clips(status=None):
    """All clips, newest first. status filters: queued|approved|uploaded|..."""
    with _locked(C.DB_FILE):
        clips = list(_read()["clips"].values())
    clips.sort(key=lambda c: c.get("created_at", 0), reverse=True)
    if status:
        clips = [c for c in clips if c.get("status") == status]
    return clips


def update_clip(clip_id, **fields):
    def _do(data):
        c = data["clips"].get(clip_id)
        if not c:
            return False
        c.update(fields)
        c["updated_at"] = time.time()
        return True
    return _mutate(_do)


def delete_clip(clip_id):
    def _do(data):
        return data["clips"].pop(clip_id, None) is not None
    return _mutate(_do)


def clip_titles():
    """All clip titles ever made — used to keep titles unique per batch."""
    with _locked(C.DB_FILE):
        return [c.get("title", "") for c in _read()["clips"].values()
                if c.get("title")]


def source_video_used(video_url):
    """True when a clip was already built from this source video."""
    if not video_url:
        return False
    with _locked(C.DB_FILE):
        return any(c.get("source_video_url") == video_url
                   for c in _read()["clips"].values())


def hook_hashes():
    """Stored perceptual hashes for near-duplicate detection (see dedup)."""
    with _locked(C.DB_FILE):
        return [c.get("hook_dhash") for c in _read()["clips"].values()
                if c.get("hook_dhash")]


# ---------------------------------------------------------------- jobs
def new_job(kind, params):
    job_id = "job_" + uuid.uuid4().hex[:10]

    def _do(data):
        data["jobs"][job_id] = {
            "job_id": job_id, "kind": kind, "params": params,
            "status": "running", "stage": "starting",
            "progress": 0.0, "message": "",
            "created_at": time.time(), "updated_at": time.time(),
            "result": None, "error": None,
        }
        return job_id
    return _mutate(_do)


def update_job(job_id, **fields):
    def _do(data):
        j = data["jobs"].get(job_id)
        if not j:
            return False
        j.update(fields)
        j["updated_at"] = time.time()
        return True
    return _mutate(_do)


def get_job(job_id):
    with _locked(C.DB_FILE):
        return _read()["jobs"].get(job_id)


def list_jobs(kind=None, status=None):
    """Jobs, newest first. status: one value or a list of values."""
    with _locked(C.DB_FILE):
        jobs = list(_read()["jobs"].values())
    jobs.sort(key=lambda j: j.get("created_at", 0), reverse=True)
    if kind:
        jobs = [j for j in jobs if j.get("kind") == kind]
    if status:
        ss = {status} if isinstance(status, str) else set(status)
        jobs = [j for j in jobs if j.get("status") in ss]
    return jobs


def claim_due_upload_jobs(now, miss_grace_s):
    """Atomically claim due upload jobs (single lock, crash-safe).

    Scheduled upload jobs with at <= now become "uploading" — except
    jobs older than miss_grace_s, which become "missed".
    Returns (uploading_jobs, missed_jobs) as plain dicts.
    """
    def _do(data):
        uploading, missed = [], []
        for j in data["jobs"].values():
            if (j.get("kind") == "upload" and j.get("status") == "scheduled"
                    and (j.get("at") or 0) <= now):
                age = now - (j.get("at") or 0)
                if age > miss_grace_s:
                    j["status"] = "missed"
                    missed.append(dict(j))
                else:
                    j["status"] = "uploading"
                    uploading.append(dict(j))
                j["updated_at"] = now
        return uploading, missed
    return _mutate(_do)


def cancel_upload_jobs_for_clip(clip_id):
    """Mark scheduled upload jobs for a clip cancelled. Returns count."""
    def _do(data):
        n = 0
        for j in data["jobs"].values():
            if (j.get("kind") == "upload"
                    and j.get("params", {}).get("clip_id") == clip_id
                    and j.get("status") == "scheduled"):
                j["status"] = "cancelled"
                j["updated_at"] = time.time()
                n += 1
        return n
    return _mutate(_do)


# ---------------------------------------------------------------- quota
QUOTA_PER_DAY = 10000
# YouTube Data API cost of one video insert. Was 1600 until Dec 2025;
# current docs put videos.insert at ~100 units (Google notes the figure
# is subject to change — check the quota-cost page if uploads start
# hitting quotaExceeded).
QUOTA_PER_UPLOAD = 100


def quota_used_today():
    today = time.strftime("%Y-%m-%d")

    def _do(data):
        q = data["quota"]
        if q.get("date") != today:
            q["date"], q["used"] = today, 0
        return q["used"]
    return _mutate(_do)


def quota_consume(units):
    today = time.strftime("%Y-%m-%d")

    def _do(data):
        q = data["quota"]
        if q.get("date") != today:
            q["date"], q["used"] = today, 0
        q["used"] += units
        return q["used"]
    return _mutate(_do)


def quota_remaining():
    return max(0, QUOTA_PER_DAY - quota_used_today())
