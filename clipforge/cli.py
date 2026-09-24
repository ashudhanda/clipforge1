"""ClipForge CLI — simple commands for the terminal.

    clipforge setup                          first-run wizard (beginner start)
    clipforge auto --niche podcast --clips 5 find videos, build clips
    clipforge from-link URL --clips 5         build clips from one video
    clipforge list [--status queued]          show clips
    clipforge approve <clip_id>               approve a clip
    clipforge upload <clip_id>                upload to YouTube now
    clipforge schedule <clip_id> --at "2026-09-25 18:00"
    clipforge scheduled                       show the upload queue
    clipforge dashboard [--port N] [--no-browser]
    clipforge worker [--loop]                 upload whatever is due
    clipforge quota                            show YouTube API quota

Run `clipforge <command> --help` for details on each command.
"""

import argparse
import logging
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("clipforge")


def _progress(stage, frac, message):
    bar = int(frac * 20)
    print(f"[{'#' * bar}{'-' * (20 - bar)}] {message}", flush=True)


# ---------------------------------------------------------------- setup
def cmd_setup(_args):
    from . import config as C
    from . import api as API
    C.ensure_dirs()
    print("\n=== ClipForge setup ===\n")
    cfg = C.load_config()

    def ask(prompt, default=""):
        d = f" [{default}]" if default else ""
        v = input(f"{prompt}{d}: ").strip()
        return v or default

    cfg["channel_name"] = ask("YouTube channel ka naam", cfg.get("channel_name", ""))
    print("\nNiche presets:", ", ".join(cfg.get("niche_presets", {})))
    cfg["niche"] = ask("Niche", cfg.get("niche", "podcast")).lower() or "podcast"
    cfg["clips_per_run"] = int(ask("Ek run mein kitne clips", str(cfg.get("clips_per_run", 5))) or 5)
    print("\nCaption styles:", ", ".join(API.caption_styles()))
    cfg["caption_style"] = ask("Caption style", cfg.get("caption_style", "hormozi"))
    cfg["hook_mode"] = ask("Hook style (card/cold/off)", cfg.get("hook_mode", "card"))
    mfk = ask("Kya channel 'made for kids' hai? (yes/no)",
              "yes" if cfg.get("made_for_kids") else "no")
    cfg["made_for_kids"] = mfk.lower().startswith("y")
    cfg["privacy"] = ask("Upload privacy (public/unlisted/private)",
                         cfg.get("privacy", "public"))

    print("\n--- AI (optional, best-moment ranking ke liye) ---")
    print("none = band | gemini = free key | openai_compat = OpenAI/Groq/Ollama")
    prov = ask("LLM provider", cfg.get("llm", {}).get("provider", "none")).lower()
    cfg.setdefault("llm", {})["provider"] = prov or "none"
    secrets = C.load_secrets()
    secrets.setdefault("llm", {})
    if prov == "gemini":
        cfg["llm"]["model"] = ask("Model", cfg["llm"].get("model") or "gemini-2.0-flash")
        key = ask("Gemini API key (Google AI Studio se, free)",
                  "****" if secrets["llm"].get("gemini_key") else "")
        if key and key != "****":
            secrets["llm"]["gemini_key"] = key
    elif prov == "openai_compat":
        cfg["llm"]["base_url"] = ask("Base URL",
                                     cfg["llm"].get("base_url") or "http://localhost:11434/v1")
        cfg["llm"]["model"] = ask("Model", cfg["llm"].get("model") or "")
        key = ask("API key (optional, Ollama ke liye khaali chhodo)",
                  "****" if secrets["llm"].get("openai_key") else "")
        if key and key != "****":
            secrets["llm"]["openai_key"] = key
    C.save_config(cfg)
    C.save_secrets(secrets)
    C.load_config(refresh=True)
    print("\nConfig save ho gayi ~/.clipforge/ mein.")

    # face-detection model for the smart crop (ships with the package)
    try:
        from pathlib import Path as _P
        src = _P(__file__).resolve().parent.parent / "assets" / "face_yunet.onnx"
        dst = C.FACE_MODEL
        if src.exists() and not dst.exists():
            import shutil
            shutil.copy2(src, dst)
            print("Face model copy ho gaya (smart crop ke liye).")
    except Exception as e:
        print(f"Face model copy nahi ho paya ({e}) — smart crop bina face "
              f"detection ke chalega.")

    # YouTube OAuth
    from . import uploader as U
    if U.is_authorized():
        print("YouTube login pehle se hai. Done!")
        return 0
    if ask("\nYouTube login karna hai abhi? (yes/no)", "yes").lower().startswith("y"):
        print("Browser khul raha hai — Google se login karo...")
        if U.authorize():
            print("Login ho gaya!")
        else:
            print("Login skip — baad mein `clipforge setup` dobara chalao.")
    print("\nSetup complete! Try: clipforge auto --niche podcast --clips 3")
    return 0


# ---------------------------------------------------------------- commands
def cmd_auto(args):
    from . import api as API
    r = API.start_auto(niche=args.niche, n_clips=args.clips,
                       caption_style=args.style, progress_cb=_progress)
    if r["error"]:
        print("Error:", r["error"])
        return 1
    print(f"\nDone — {len(r['clips'])} clips. `clipforge list` se dekho.")
    return 0


def cmd_from_link(args):
    from . import api as API
    r = API.start_link(args.url, n_clips=args.clips,
                       caption_style=args.style, progress_cb=_progress)
    if r["error"]:
        print("Error:", r["error"])
        return 1
    print(f"\nDone — {len(r['clips'])} clips. `clipforge list` se dekho.")
    return 0


def cmd_list(args):
    from . import api as API
    clips = API.list_clips(status=args.status)
    if not clips:
        print("Koi clips nahi hain abhi. `clipforge auto --niche podcast` chalao.")
        return 0
    for c in clips:
        print(f"{c['clip_id']}  [{c.get('status')}]  {c.get('title', '')[:70]}")
        if c.get("youtube_url"):
            print(f"    -> {c['youtube_url']}")
    return 0


def cmd_approve(args):
    from . import api as API
    r = API.approve_clip(args.clip_id)
    print("Approved." if r["ok"] else f"Error: {r['error']}")
    return 0 if r["ok"] else 1


def cmd_reject(args):
    from . import api as API
    r = API.reject_clip(args.clip_id)
    print("Rejected." if r["ok"] else f"Error: {r['error']}")
    return 0 if r["ok"] else 1


def cmd_delete(args):
    from . import api as API
    r = API.delete_clip(args.clip_id)
    print("Deleted." if r["ok"] else f"Error: {r['error']}")
    return 0 if r["ok"] else 1


def cmd_upload(args):
    from . import api as API
    print("Upload ho raha hai...")
    r = API.upload_clip(args.clip_id)
    if r["ok"]:
        print("Live:", r["url"])
        return 0
    print("Error:", r["error"])
    return 1


def cmd_schedule(args):
    from . import api as API
    r = API.schedule_clip(args.clip_id, args.at)
    print(r.get("message") or r.get("error"))
    return 0 if r["ok"] else 1


def cmd_scheduled(_args):
    from . import api as API
    jobs = API.list_scheduled()
    if not jobs:
        print("Koi scheduled upload nahi hai.")
        return 0
    for j in jobs:
        cid = j.get("params", {}).get("clip_id", "?")
        print(f"{j['status']:9} {j.get('at_human', '?')}  {cid}")
    return 0


def cmd_worker(args):
    from . import api as API
    if args.loop:
        print("Worker chal raha hai (Ctrl+C se band karo)...")
        try:
            while True:
                API.run_worker_once()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nWorker band.")
        return 0
    s = API.run_worker_once()
    print(f"done={s['done']} pushed(next day)={s['pushed']} "
          f"missed={s['missed']} failed={s['failed']}")
    return 0


def cmd_dashboard(args):
    from . import dashboard_server as DS
    return DS.run(port=args.port, open_browser=not args.no_browser)


def cmd_quota(_args):
    from . import api as API
    q = API.quota()
    print(f"YouTube API quota: {q['used']}/{q['per_day']} used, "
          f"{q['remaining']} bacha hai (1 upload = {q['per_upload']})")
    return 0


# ---------------------------------------------------------------- main
def build_parser():
    p = argparse.ArgumentParser(prog="clipforge",
                                description="YouTube Shorts pipeline — "
                                            "research, build, upload, schedule.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="First-run wizard (yahan se shuru karo)")
    s.set_defaults(fn=cmd_setup)

    s = sub.add_parser("auto", help="Niche se trending videos dhundh ke clips banao")
    s.add_argument("--niche", default=None, help="jaise podcast, gaming, finance")
    s.add_argument("--clips", type=int, default=None, help="kitne clips (default 5)")
    s.add_argument("--style", default=None, help="caption style")
    s.set_defaults(fn=cmd_auto)

    s = sub.add_parser("from-link", help="Ek YouTube link se clips banao")
    s.add_argument("url", help="YouTube video ka link")
    s.add_argument("--clips", type=int, default=None, help="kitne clips (default 5)")
    s.add_argument("--style", default=None, help="caption style")
    s.set_defaults(fn=cmd_from_link)

    s = sub.add_parser("list", help="Bane hue clips dikhao")
    s.add_argument("--status", default=None,
                   help="filter: queued, approved, scheduled, uploaded")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("approve", help="Ek clip approve karo")
    s.add_argument("clip_id")
    s.set_defaults(fn=cmd_approve)

    s = sub.add_parser("reject", help="Ek clip reject karo")
    s.add_argument("clip_id")
    s.set_defaults(fn=cmd_reject)

    s = sub.add_parser("delete", help="Ek clip delete karo (file samet)")
    s.add_argument("clip_id")
    s.set_defaults(fn=cmd_delete)

    s = sub.add_parser("upload", help="Clip abhi YouTube pe upload karo")
    s.add_argument("clip_id")
    s.set_defaults(fn=cmd_upload)

    s = sub.add_parser("schedule", help="Clip future mein upload ke liye lagao")
    s.add_argument("clip_id")
    s.add_argument("--at", required=True,
                   help='kab: "2026-09-25 18:00" (future time)')
    s.set_defaults(fn=cmd_schedule)

    s = sub.add_parser("scheduled", help="Upload queue dikhao")
    s.set_defaults(fn=cmd_scheduled)

    s = sub.add_parser("dashboard", help="Browser dashboard kholo (beginners)")
    s.add_argument("--port", type=int, default=None,
                   help="port (default: free port, 8765 se shuru)")
    s.add_argument("--no-browser", action="store_true",
                   help="browser khud mat kholo, sirf URL print karo")
    s.set_defaults(fn=cmd_dashboard)

    s = sub.add_parser("worker", help="Due scheduled uploads process karo")
    s.add_argument("--loop", action="store_true",
                   help="lagatar chalta rahe (background service)")
    s.add_argument("--interval", type=int, default=300,
                   help="loop mein kitne second baad check (default 300)")
    s.set_defaults(fn=cmd_worker)

    s = sub.add_parser("quota", help="YouTube API quota dikhao")
    s.set_defaults(fn=cmd_quota)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args) or 0
    except KeyboardInterrupt:
        print("\nRok diya.")
        return 130
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
