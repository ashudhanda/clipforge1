"""ClipForge backend logic tests — NO network.

Run from the repo root with:  python -m tests.test_backend
or:  python tests/test_backend.py

Uses a temporary HOME so the real ~/.clipforge is never touched.
"""
import os
import sys
import tempfile
from pathlib import Path

# isolate user data BEFORE importing clipforge.config
TMPHOME = tempfile.mkdtemp(prefix="cf_test_home_")
os.environ["HOME"] = TMPHOME
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clipforge import config as C, store, moments, captions, hooks, meta, triggers
from clipforge.captions_fetch import parse_vtt

passed, failed = [], []


def check(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f" :: {detail}" if detail and not cond else ""))


# ---- synthetic 30-min podcast transcript ----
def synth_transcript(dur_s=1800):
    segs, t = [], 0.0
    i = 0
    while t < dur_s:
        d = 4.0
        if 300 <= t < 360:
            txt = "What is the biggest secret nobody tells you about money? Honestly it's insane!"
        elif 900 <= t < 960:
            txt = "I made a huge mistake and lost everything. Never do this again, warning!"
        elif 1400 <= t < 1460:
            txt = "[laughter] Oh my god, no way! That is unbelievable, wow!"
        else:
            txt = f"So um like you know we were talking about things and stuff number {i}."
        segs.append({"start": t, "end": t + d, "text": txt})
        t += d
        i += 1
    return segs


segs = synth_transcript()
moms = moments.detect(segs, 5, "podcast")
check("moments: returns list", isinstance(moms, list))
check("moments: found >=3", len(moms) >= 3, f"got {len(moms)}")
# non-overlapping incl. 3s padding
ok = True
for a in range(len(moms)):
    for b in range(a + 1, len(moms)):
        A, B = moms[a], moms[b]
        if A["start"] < B["end"] + 3.0 and B["start"] < A["end"] + 3.0:
            ok = False
check("moments: zero overlap (pad 3s)", ok)
# spread: moments should come from different parts of the video
quarters = {int(m["start"] // 450) for m in moms}
check("moments: spread across video", len(quarters) >= 2, f"quarters={quarters}")
# strong moments ranked first
check("moments: has score+reason", all("score" in m and "reason" in m for m in moms))
check("moments: top score > 3", moms[0]["score"] > 3, f"top={moms[0]['score']}")

# ---- captions ASS ----
words = [(0.0 + i * 0.3, 0.25 + i * 0.3, w)
         for i, w in enumerate("what is the biggest secret nobody tells you".split())]
for style in captions.list_styles():
    p = Path(tempfile.gettempdir()) / f"cf_t_{style}.ass"
    ok_s = captions.build_ass(words, p, style=style,
                              hook_text="BIG SECRET?!", hook_mode="card")
    txt = p.read_text(encoding="utf-8")
    valid = ok_s and "[V4+ Styles]" in txt and "Dialogue:" in txt and "HookCard" in txt
    check(f"captions: style {style} valid ASS", valid)
check("captions: 12 styles", len(captions.list_styles()) == 12,
      f"got {len(captions.list_styles())}")
# line fallback
ok_l = captions.build_ass_lines([(0, 2, "hello world"), (2, 4, "second line")],
                                Path(tempfile.gettempdir()) / "cf_t_lines.ass")
check("captions: line fallback", ok_l)

# ---- hooks ----
card = hooks.hook_card_text("What is the biggest secret? It is insane! " * 5,
                            opening_text="what is the biggest")
check("hooks: card <=8 words", len(card.split()) <= 8, card)
check("hooks: card uppercase", card == card.upper(), card)
card2 = hooks.hook_card_text("um uh like you know stuff things " * 20)
check("hooks: fallback card", card2 in hooks.FALLBACK_CARDS, card2)

# ---- triggers ----
check("triggers: challenge", triggers.detect_trigger("can you beat this impossible level?") == "challenge")
check("triggers: mystery", triggers.detect_trigger("what is this? never seen before") == "mystery")
check("triggers: cta", "comments" in triggers.trigger_cta("debate").lower())

# ---- meta ----
title = meta.pick_title("the secret money mistake story " * 10, creator="JohnDoe",
                        niche="podcast", taken=())
check("meta: title <=100", len(title) <= 100, title)
check("meta: title has creator", "JohnDoe" in title, title)
t2 = meta.pick_title("the secret money mistake story " * 10, creator="JohnDoe",
                     niche="podcast", taken=(title,))
check("meta: title unique", t2 != title, t2)
tags = meta.pick_hashtags("podcast")
check("meta: hashtags", "#Shorts" in tags and not any("fyp" in t.lower() for t in tags), tags)
desc, pinned = meta.build_description(title, "JohnDoe", "https://www.youtube.com/watch?v=x",
                                      "secret money story", niche="podcast",
                                      hashtags=tags, trigger="mystery")
check("meta: desc has credit", "youtube.com/watch" in desc)
check("meta: desc has cta", "comment" in desc.lower())
check("meta: 2 pinned", len(pinned) == 2, pinned)
check("meta: creator never URL", meta.clean_creator_name("https://www.youtube.com/@JohnDoe") == "JohnDoe")

# ---- VTT parse (basic) ----
vtt = """WEBVTT

00:00:01.000 --> 00:00:03.500
Hello <b>world</b>

00:00:03.500 --> 00:00:06.000
Second line here
"""
pv = parse_vtt(vtt)
check("vtt: parsed 2 cues", len(pv) == 2, f"got {len(pv)}")
check("vtt: tags stripped", pv[0]["text"] == "Hello world", pv[0]["text"])
check("vtt: times", abs(pv[0]["start"] - 1.0) < 0.01 and abs(pv[1]["end"] - 6.0) < 0.01)

# ---- VTT parse (rolling auto-captions dedup) ----
rolling = """WEBVTT

00:00:00.000 --> 00:00:02.000
hello world

00:00:01.000 --> 00:00:03.000
hello world foo bar

00:00:02.000 --> 00:00:04.000
hello world foo bar baz qux

00:00:05.000 --> 00:00:07.000
brand new sentence here
"""
pr = parse_vtt(rolling)
full_text = " ".join(s["text"] for s in pr)
check("vtt-rolling: repeats removed",
      full_text.count("hello world") == 1 and full_text.count("foo bar") == 1,
      full_text)
check("vtt-rolling: new words kept", "baz qux" in full_text, full_text)
check("vtt-rolling: granularity kept", len(pr) >= 3, f"got {len(pr)} cues")
check("vtt-rolling: non-overlapping cue untouched",
      any(s["text"] == "brand new sentence here" for s in pr))

# ---- config/store ----
C.ensure_dirs()
check("config: dirs created", C.HOME.exists() and C.CLIPS_DIR.exists())
cfg = C.load_config()
check("config: defaults merged", cfg["caption_style"] == "hormozi" and "podcast" in cfg["niche_presets"])
cfg["channel_name"] = "TestChannel"
C.save_config(cfg)
check("config: roundtrip", C.load_config(refresh=True)["channel_name"] == "TestChannel")
C.save_secrets({"llm": {"gemini_key": "abc123"}})
import stat as _st
mode = oct(os.stat(C.SECRETS_FILE).st_mode & 0o777)
check("secrets: 0600 perms", mode == "0o600", mode)
check("secrets: roundtrip", C.load_secrets(refresh=True)["llm"]["gemini_key"] == "abc123")

cid = store.save_clip({"title": "T1", "status": "queued", "created_at": 1})
check("store: save/get clip", store.get_clip(cid)["title"] == "T1")
store.update_clip(cid, status="approved")
check("store: update", store.get_clip(cid)["status"] == "approved")
check("store: list filter", len(store.list_clips(status="approved")) == 1)
check("store: titles", "T1" in store.clip_titles())
store.quota_consume(1600)
check("store: quota", store.quota_used_today() == 1600 and store.quota_remaining() == 8400)
check("store: llm disabled default", __import__("clipforge.llm", fromlist=["x"]).enabled() is False)

# ---- scheduler parse + missed handling ----
from clipforge import scheduler as S, api as API
import datetime as _dt
import time as _t
future = (_dt.datetime.now() + _dt.timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
r = API.schedule_clip(cid, future)
check("scheduler: schedule ok", r["ok"], r)
sched = API.list_scheduled()
check("scheduler: listed", len(sched) == 1 and sched[0]["status"] == "scheduled")
# simulate a missed job: backdate it beyond grace (public API)
sched_job = sched[0]
store.update_job(sched_job["job_id"], at=_t.time() - 7 * 3600)
s = S.check_due()
check("scheduler: missed marked, not uploaded", s["missed"] == 1 and s["done"] == 0, s)
sched2 = API.list_scheduled()
check("scheduler: missed visible", any(j["status"] == "missed" for j in sched2))
check("scheduler: missed clip back to approved",
      store.get_clip(cid)["status"] == "approved")
# cancel path
r2 = API.schedule_clip(cid, future)
check("scheduler: reschedule ok", r2["ok"], r2)
rc = S.cancel_schedule(cid)
check("scheduler: cancel ok", rc[0], rc)
check("scheduler: cancel reverts clip", store.get_clip(cid)["status"] == "approved")
check("store: list_jobs", isinstance(store.list_jobs(kind="upload"), list))
check("store: cancel_upload_jobs_for_clip", store.cancel_upload_jobs_for_clip("nope") == 0)

print("== api background + double-upload ==")
# background start_auto with stubbed pipeline (no network)
import clipforge.pipeline as P
_orig_auto = P.auto_mode


def fake_auto(niche, n_clips=None, caption_style=None, progress_cb=None):
    jid = store.new_job("auto", {"niche": niche})
    store.update_job(jid, status="done", stage="done", progress=1.0)
    _t.sleep(0.3)
    return {"job_id": jid, "clips": ["x"], "error": None}


P.auto_mode = fake_auto
try:
    r = API.start_auto("podcast", n_clips=1, background=True)
    check("api: background returns job_id", "job_id" in r and r.get("background"), r)
    deadline = _t.time() + 5
    st = None
    while _t.time() < deadline:
        st = API.get_status(r["job_id"])
        if st["job"].get("status") == "done":
            break
        _t.sleep(0.2)
    check("api: background job completes", st and st["job"].get("status") == "done")
    check("api: background result clips", (st["job"].get("result") or {}).get("clips") == ["x"])
    # sync path still works
    r2 = API.start_auto("podcast", n_clips=1)
    check("api: sync start_auto", r2.get("clips") == ["x"], r2)
finally:
    P.auto_mode = _orig_auto

# double-upload protection: stale scheduled job for an uploaded clip
cid2 = store.save_clip({"title": "Double upload guard", "file": __file__,
                        "status": "uploaded", "youtube_url": "https://youtu.be/abc",
                        "created_at": _t.time()})
jid3 = store.new_job("upload", {"clip_id": cid2})
store.update_job(jid3, at=_t.time() - 5, status="scheduled")
s3 = S.check_due()
check("scheduler: already-uploaded clip not re-uploaded",
      s3["done"] == 1 and store.get_job(jid3)["status"] == "done", s3)

print(f"\n{len(passed)} passed, {len(failed)} failed")
sys.exit(1 if failed else 0)
