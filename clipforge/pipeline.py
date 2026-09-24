"""ClipForge pipeline — orchestrates the whole flow.

auto_mode(niche, n_clips, caption_style): research a niche -> clips.
link_mode(url, n_clips, caption_style):   clips from one video link.

Optimized flow (the core design):
  1. research:   find candidate long videos (NO download)
  2. captions:   fetch subtitles ONLY via yt-dlp (seconds, KBs)
  3. fallback:   no captions? download AUDIO ONLY -> faster-whisper
  4. moments:    detect best moments from the transcript (timestamps)
  5. download:   ONLY the selected segments (--download-sections, MBs)
  6. words:      re-transcribe each short segment for exact word timings
  7. edit:       9:16 render — smart crop, hook card, karaoke captions,
                 zoom punch-in, silence trim, loudnorm
  8. meta:       title / description / hashtags / pinned comments
  9. gate:       quality gate (resolution, duration, audio, title...)
  10. store:     clip queued for preview -> upload / schedule

progress_cb(stage, frac, message) is called throughout — the dashboard
uses it for live progress; the CLI prints the messages.

Every stage logs in plain language. A single moment failing never kills
the run — it's skipped and the rest continue.
"""

import logging
import time
from pathlib import Path

from . import config as C
from . import store

log = logging.getLogger("clipforge")


def _cb(cb, stage, frac, message):
    log.info("[%s] %s", stage, message)
    if cb:
        try:
            cb(stage, frac, message)
        except Exception:
            pass


def _get_moments_source(video_url, niche, cb):
    """Captions-first transcript. Returns (segments, duration_s, via)."""
    from . import captions_fetch as CF
    from . import transcribe as TR
    _cb(cb, "captions", 0.15, "Captions nikaal rahe hain (video download nahi ho rahi)...")
    segments, meta = CF.fetch(video_url)
    if segments:
        dur = max(s["end"] for s in segments)
        _cb(cb, "captions", 0.25,
            f"Captions mil gaye: {len(segments)} lines")
        return segments, dur, "captions"
    _cb(cb, "captions", 0.2,
        "Is video mein captions nahi hain — sirf audio download karke "
        "transcribe kar rahe hain (ye thoda time lega, normal hai)...")
    segments = TR.transcribe_video(video_url)
    if not segments:
        return [], 0, "none"
    dur = max(s["end"] for s in segments)
    return segments, dur, "whisper"


def _gate_clip(mp4_path, title):
    """Light quality gate. Returns (ok, reason)."""
    cfg = C.load_config()
    try:
        from .editor import probe_streams
        info = probe_streams(mp4_path)
        if (info["width"], info["height"]) != (1080, 1920):
            return False, (f"resolution {info['width']}x{info['height']} "
                           f"!= 1080x1920")
        dur = info["duration"]
        if not (cfg.get("min_clip_s", 25) - 2
                <= dur <= cfg.get("max_clip_s", 58) + 3):
            return False, f"duration {dur:.1f}s out of range"
        if not info["has_audio"]:
            return False, "no audio stream"
        size_mb = Path(mp4_path).stat().st_size / 1e6
        if not (0.5 <= size_mb <= 150):
            return False, f"size {size_mb:.1f}MB suspicious"
        if not (10 <= len(title or "") <= cfg.get("title_max_len", 100)):
            return False, "title length bad"
        return True, "pass"
    except Exception as e:
        return False, str(e)[:100]


def _build_clips_from_video(video_url, video_title, channel, niche, n_clips,
                            caption_style, cb, job_id):
    from . import downloader as DL
    from . import transcribe as TR
    from . import moments as MO
    from . import hooks as HK
    from . import meta as MT
    from . import editor as ED
    from . import dedup as DD
    from . import triggers as TG

    cfg = C.load_config()
    pad = cfg.get("segment_pad_s", 3.0)
    min_s, max_s = cfg.get("min_clip_s", 25), cfg.get("max_clip_s", 58)

    segments, duration_s, via = _get_moments_source(video_url, niche, cb)
    if not segments:
        _cb(cb, "moments", 0.3, "Transcript nahi mil paya — ye video skip")
        return []
    _cb(cb, "moments", 0.3,
        f"Best moments dhundh rahe hain ({len(segments)} lines mein se)...")
    moment_list = MO.detect(segments, n_clips, niche, duration_s)
    if not moment_list:
        _cb(cb, "moments", 0.35, "Koi strong moment nahi mila — video skip")
        return []

    taken_titles = store.clip_titles()
    made = []
    for i, m in enumerate(moment_list):
        frac = 0.35 + 0.6 * (i / max(len(moment_list), 1))
        _cb(cb, "download", frac,
            f"Clip {i + 1}/{len(moment_list)}: sirf ye moment download ho raha "
            f"hai ({m['start']:.0f}s–{m['end']:.0f}s)...")
        start = max(0.0, m["start"] - pad)
        end = m["end"] + pad
        seg_path = (C.TMP_DIR /
                    f"seg_{job_id}_{i}.mp4")
        got = DL.download_section(video_url, start, end, seg_path)
        if not got:
            _cb(cb, "download", frac, f"Clip {i + 1}: download fail — skip")
            continue

        _cb(cb, "transcribe", frac,
            f"Clip {i + 1}: exact word timings nikaal rahe hain...")
        words = []
        try:
            for s in TR.transcribe_audio(got, word_timestamps=True):
                words.extend(s.get("words", []))
        except Exception:
            pass
        if not words:
            # fallback: synthesize word timings from segment text
            text = m["text"]
            toks = text.split()
            if toks:
                per = (m["end"] - m["start"]) / len(toks)
                words = [(m["start"] - start + k * per,
                          m["start"] - start + (k + 1) * per, w)
                         for k, w in enumerate(toks)]

        _cb(cb, "edit", frac, f"Clip {i + 1}: edit ho raha hai (crop, "
                              f"captions, hook card)...")
        hook_text = HK.hook_card_text(
            m["text"], opening_text=" ".join(w for _, _, w in words[:8]))
        creator = MT.clean_creator_name(channel, video_url)
        title = MT.pick_title(m["text"], creator=creator, niche=niche,
                              hook_line=hook_text, taken=taken_titles)
        taken_titles.append(title)
        out_path = (C.CLIPS_DIR /
                    f"{time.strftime('%Y%m%d_%H%M%S')}_{job_id[-6:]}_{i}.mp4")
        try:
            out, shifted = ED.render(got, out_path, words=words,
                                     caption_style=caption_style,
                                     hook_text=hook_text,
                                     hook_mode=cfg.get("hook_mode", "card"),
                                     max_dur_s=max_s)
        except Exception as e:
            _cb(cb, "edit", frac, f"Clip {i + 1}: render fail ({str(e)[:80]})")
            continue
        finally:
            try:
                seg_path.unlink()
            except OSError:
                pass

        ok, reason = _gate_clip(out, title)
        if not ok:
            _cb(cb, "edit", frac, f"Clip {i + 1}: quality gate fail "
                                  f"({reason}) — reject")
            try:
                out.unlink()
            except OSError:
                pass
            continue
        dh = DD.hook_frame_dhash(out)
        if dh and DD.is_near_duplicate(dh, store.hook_hashes()):
            _cb(cb, "edit", frac, f"Clip {i + 1}: duplicate lag raha hai — "
                                  f"reject")
            try:
                out.unlink()
            except OSError:
                pass
            continue

        trigger = TG.detect_trigger(m["text"])
        hashtags = MT.pick_hashtags(niche)
        description, pinned = MT.build_description(
            title, creator, video_url, m["text"], niche=niche,
            hashtags=hashtags, trigger=trigger,
            event=MT.event_phrase(m["text"], hook_text, niche))
        clip_id = store.save_clip({
            "title": title, "description": description,
            "hashtags": hashtags, "pinned_comments": pinned,
            "file": str(out), "hook_line": hook_text,
            "hook_dhash": dh, "trigger": trigger,
            "source_video_url": video_url, "source_title": video_title,
            "moment_start": m["start"], "moment_end": m["end"],
            "moment_score": m["score"], "moment_reason": m["reason"],
            "niche": niche, "caption_style": caption_style or
            cfg.get("caption_style", "hormozi"),
            "transcript_via": via,
            "status": "queued", "created_at": time.time(),
        })
        made.append(clip_id)
        _cb(cb, "edit", frac, f"Clip {i + 1} taiyaar: {title[:60]}")
    return made


def auto_mode(niche, n_clips=None, caption_style=None, progress_cb=None):
    """Niche -> research -> clips. Returns {"job_id", "clips", "error"}."""
    from . import research as RS
    cfg = C.load_config()
    niche = (niche or cfg.get("niche") or "podcast").strip()
    n_clips = n_clips or cfg.get("clips_per_run", 5)
    caption_style = caption_style or cfg.get("caption_style", "hormozi")
    C.ensure_dirs()

    job_id = store.new_job("auto", {"niche": niche, "n_clips": n_clips})
    result = {"job_id": job_id, "clips": [], "error": None}
    try:
        _cb(progress_cb, "research", 0.05,
            f"'{niche}' mein trending long videos dhundh rahe hain...")
        cands = RS.discover(niche)
        fresh = [c for c in cands
                 if not store.source_video_used(c["url"])]
        if not cands:
            if RS.last_error == "missing":
                msg = ("yt-dlp nahi mila — `python setup.py` dobara chalao "
                       "(yt-dlp install hoga), phir Generate dabao.")
            else:
                msg = ("YouTube search fail hua (network ya bot-check). "
                       "Thodi der baad try karo — ya Link mode mein seedha "
                       "video link paste kar do.")
            _cb(progress_cb, "research", 0.1, msg)
            result["error"] = msg
            store.update_job(job_id, status="done", result=result,
                             message=msg)
            return result
        if not fresh:
            msg = ("Is niche ki mili hui videos sab use ho chuki hain. "
                   "Kal naye videos ke saath try karo — ya Link mode mein "
                   "seedha video link paste kar do.")
            _cb(progress_cb, "research", 0.1, msg)
            result["error"] = msg
            store.update_job(job_id, status="done", result=result,
                             message=msg)
            return result
        cands = fresh
        v = cands[0]
        _cb(progress_cb, "research", 0.12,
            f"Mili: {v['title'][:70]} ({v['channel']})")
        clips = []
        # walk fresh videos until we have n_clips (or run out) — each
        # video contributes only its STRONG moments, never weak filler
        for v in cands:
            if len(clips) >= n_clips:
                break
            _cb(progress_cb, "research", 0.12,
                f"Video: {v['title'][:60]} ({v['channel']})")
            got = _build_clips_from_video(
                v["url"], v["title"], v["channel"], niche,
                n_clips - len(clips), caption_style, progress_cb, job_id)
            clips.extend(got)
            if len(clips) < n_clips:
                _cb(progress_cb, "moments", 0.3,
                    f"Is video se {len(got)} strong moments mile — "
                    f"agli video try kar rahe hain...")
        result["clips"] = clips
        msg = (f"{len(clips)} clips taiyaar" if clips
               else "Is video se koi clip nahi ban paya")
        _cb(progress_cb, "done", 1.0, msg)
        store.update_job(job_id, status="done", result=result, message=msg,
                         progress=1.0, stage="done")
    except Exception as e:
        result["error"] = str(e)[:200]
        store.update_job(job_id, status="failed", error=result["error"])
        log.error("auto_mode failed: %s", result["error"])
    return result


def link_mode(url, n_clips=None, caption_style=None, progress_cb=None):
    """One video link -> clips. Returns {"job_id", "clips", "error"}."""
    import re
    cfg = C.load_config()
    niche = cfg.get("niche") or "podcast"
    n_clips = n_clips or cfg.get("clips_per_run", 5)
    caption_style = caption_style or cfg.get("caption_style", "hormozi")
    C.ensure_dirs()

    job_id = store.new_job("link", {"url": url, "n_clips": n_clips})
    result = {"job_id": job_id, "clips": [], "error": None}
    try:
        m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{6,})", url)
        if not m:
            result["error"] = "Ye YouTube link samajh nahi aaya"
            store.update_job(job_id, status="failed", error=result["error"])
            return result
        video_url = f"https://www.youtube.com/watch?v={m.group(1)}"
        if store.source_video_used(video_url):
            _cb(progress_cb, "research", 0.05,
                "Is video se pehle clips ban chuke hain — phir bhi bana rahe "
                "hain (naye moments dhundhenge)")
        _cb(progress_cb, "research", 0.08, "Video ki details nikaal rahe hain...")
        from . import research as RS
        meta = RS.video_meta(video_url)
        title, channel = meta.get("title", ""), meta.get("channel", "")
        clips = _build_clips_from_video(video_url, title, channel, niche,
                                        n_clips, caption_style,
                                        progress_cb, job_id)
        result["clips"] = clips
        msg = (f"{len(clips)} clips taiyaar" if clips
               else "Is video se koi clip nahi ban paya")
        _cb(progress_cb, "done", 1.0, msg)
        store.update_job(job_id, status="done", result=result, message=msg,
                         progress=1.0, stage="done")
    except Exception as e:
        result["error"] = str(e)[:200]
        store.update_job(job_id, status="failed", error=result["error"])
        log.error("link_mode failed: %s", result["error"])
    return result
