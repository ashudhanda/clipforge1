"""Upload scheduler — quota-aware, miss-safe.

schedule_clip(clip_id, at): queue a clip for a future time.
    `at` = "YYYY-MM-DD HH:MM" (local time) or a datetime.

check_due(): the worker (`clipforge worker`) calls this. For every due
job it:
    1. refreshes the YouTube token (uploader does this internally),
    2. checks quota — if a day's quota is spent, the job is pushed to
       next morning 09:00 instead of failing (quota-aware spreading),
    3. uploads, marks the clip uploaded.

Missed jobs: a job whose time passed while the worker wasn't running is
marked "missed" — NEVER silently skipped and never auto-uploaded stale.
`clipforge list` surfaces missed jobs; the user re-schedules or uploads
manually.

All state lives in store (the single backend), so CLI and dashboard see
the same queue.
"""

import datetime as dt
import logging
import time

from . import store
from . import uploader as U

log = logging.getLogger("clipforge")

_MISS_GRACE_S = 6 * 3600   # a job this overdue counts as missed, not due
_NEXT_DAY_HOUR = 9         # quota-exhausted jobs move to next day 09:00


def _parse_at(at):
    if isinstance(at, dt.datetime):
        return at
    text = str(at).strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"time samajh nahi aaya: {at!r} "
                     f"(format: YYYY-MM-DD HH:MM)")


def schedule_clip(clip_id, at):
    """Queue a clip. Returns (ok, message)."""
    clip = store.get_clip(clip_id)
    if not clip:
        return False, f"clip nahi mila: {clip_id}"
    if clip.get("status") == "uploaded":
        return False, "ye clip pehle hi upload ho chuka hai"
    try:
        when = _parse_at(at)
    except ValueError as e:
        return False, str(e)
    if when.timestamp() < time.time() - 60:
        return False, "time future mein hona chahiye"
    job_id = store.new_job("upload", {"clip_id": clip_id})
    store.update_job(job_id, at=when.timestamp(),
                     at_human=when.strftime("%Y-%m-%d %H:%M"),
                     status="scheduled")
    store.update_clip(clip_id, status="scheduled")
    return True, (f"schedule ho gaya: {clip.get('title', clip_id)[:50]} "
                  f"-> {when.strftime('%Y-%m-%d %H:%M')}")


def cancel_schedule(clip_id):
    clip = store.get_clip(clip_id)
    if not clip or clip.get("status") != "scheduled":
        return False, "koi active schedule nahi hai is clip pe"
    store.cancel_upload_jobs_for_clip(clip_id)
    store.update_clip(clip_id, status="approved")
    return True, "schedule cancel ho gaya"


def _push_to_next_day(job_id):
    nxt = (dt.datetime.now() + dt.timedelta(days=1)).replace(
        hour=_NEXT_DAY_HOUR, minute=0, second=0, microsecond=0)
    store.update_job(job_id, at=nxt.timestamp(),
                     at_human=nxt.strftime("%Y-%m-%d %H:%M"),
                     note="quota full thi — next day 09:00 pe shift hua")
    log.info("quota full: job %s -> %s", job_id,
             nxt.strftime("%Y-%m-%d %H:%M"))


def check_due():
    """Upload every due job. Returns {done, pushed, missed, failed}."""
    now = time.time()
    summary = {"done": 0, "pushed": 0, "missed": 0, "failed": 0}
    # atomic claim (one lock): due -> uploading, too-old -> missed
    uploading, missed_jobs = store.claim_due_upload_jobs(now, _MISS_GRACE_S)
    for j in missed_jobs:
        summary["missed"] += 1
        clip_id = j.get("params", {}).get("clip_id")
        log.warning("missed schedule (worker band tha): %s", clip_id)
        # back to approved so the user can re-schedule or upload manually
        if clip_id:
            store.update_clip(clip_id, status="approved")

    for j in uploading:
        job_id = j["job_id"]
        clip_id = j.get("params", {}).get("clip_id")
        clip = store.get_clip(clip_id)
        if not clip or not clip.get("file"):
            store.update_job(job_id, status="failed",
                             error="clip file nahi mili")
            summary["failed"] += 1
            continue
        if clip.get("status") == "uploaded":
            # already uploaded by hand — don't upload twice
            store.update_job(job_id, status="done",
                             result={"url": clip.get("youtube_url"),
                                     "note": "pehle hi upload ho chuka tha"})
            summary["done"] += 1
            continue
        if store.quota_remaining() < store.QUOTA_PER_UPLOAD:
            store.update_job(job_id, status="scheduled")
            _push_to_next_day(job_id)
            summary["pushed"] += 1
            continue
        url = U.upload_video(clip["file"], clip.get("title", ""),
                             clip.get("description", ""),
                             clip.get("hashtags", []))
        if url:
            store.update_job(job_id, status="done", result={"url": url})
            store.update_clip(clip_id, status="uploaded",
                              youtube_url=url,
                              uploaded_at=time.time())
            summary["done"] += 1
        else:
            store.update_job(job_id, status="failed",
                             error="upload fail — `clipforge list` dekho")
            summary["failed"] += 1
    if any(summary.values()):
        log.info("worker: done=%d pushed=%d missed=%d failed=%d",
                 summary["done"], summary["pushed"],
                 summary["missed"], summary["failed"])
    return summary


def list_scheduled():
    jobs = store.list_jobs(kind="upload",
                           status=["scheduled", "missed", "failed"])
    jobs.sort(key=lambda j: j.get("at") or 0)
    return jobs
