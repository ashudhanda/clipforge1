"""ClipForge dashboard server — stdlib only (no Flask/FastAPI).

Serves the dashboard UI from ~/workspace/clipforge/dashboard/ (or the
installed package's dashboard dir) and exposes the backend API as
POST /api/<fn> with a JSON body.

    python -m clipforge.dashboard_server [--port 8765] [--no-browser]

Media: GET /media/<filename> streams finished Shorts from
~/.clipforge/clips/ (with HTTP Range support so <video> seeking works).
"""

import argparse
import html
import http.server
import json
import mimetypes
import os
import socketserver
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

DASH_DIR = Path(__file__).resolve().parent.parent / "dashboard"


# ---------------------------------------------------------------- API dispatch
def _api_table():
    from . import api as A
    return {
        # clips
        "list_clips":      (A.list_clips, ("status",)),
        "get_clip":        (A.get_clip, ("clip_id",)),
        "approve_clip":    (A.approve_clip, ("clip_id",)),
        "reject_clip":     (A.reject_clip, ("clip_id",)),
        "delete_clip":     (A.delete_clip, ("clip_id",)),
        "update_clip_meta": (A.update_clip_meta, ("clip_id", "patch")),
        # generation
        "start_auto":      (A.start_auto, ("niche", "n_clips", "caption_style")),
        "start_link":      (A.start_link, ("url", "n_clips", "caption_style")),
        "get_status":      (A.get_status, ("job_id",)),
        # upload / schedule
        "upload_clip":     (A.upload_clip, ("clip_id",)),
        "schedule_clip":   (A.schedule_clip, ("clip_id", "at")),
        "cancel_schedule": (A.cancel_schedule, ("clip_id",)),
        "list_scheduled":  (A.list_scheduled, ()),
        "run_worker_once": (A.run_worker_once, ()),
        "quota":           (A.quota, ()),
        # youtube auth
        "youtube_authorized":  (A.youtube_authorized, ()),
        "youtube_connect":     (A.youtube_connect, ()),
        "youtube_disconnect":  (A.youtube_disconnect, ()),
        "client_secret_status": (A.client_secret_status, ()),
        "save_client_secret":  (A.save_client_secret, ("json_text",)),
        # config / setup
        "get_config":      (A.get_config, ()),
        "is_first_run":    (A.is_first_run, ()),
        "update_config":   (A.update_config, ("patch",)),
        "caption_styles":  (A.caption_styles, ()),
        # llm keys (masked — never echoed back)
        "llm_key_status":  (A.llm_key_status, ()),
        "set_llm_key":     (A.set_llm_key, ("provider", "key")),
        # danger zone
        "clear_cache":     (A.clear_cache, ()),
    }


def _call_api(name, body):
    table = _api_table()
    if name not in table:
        return {"ok": False, "error": f"unknown api: {name}"}
    fn, params = table[name]
    kwargs = {}
    for p in params:
        if p in body:
            kwargs[p] = body[p]
    if name in ("start_auto", "start_link"):
        kwargs["background"] = True  # dashboard always runs jobs in bg
    try:
        res = fn(**kwargs)
    except TypeError as e:
        return {"ok": False, "error": f"bad params: {e}"}
    except Exception as e:  # never leak a traceback to the UI
        return {"ok": False, "error": str(e)[:300]}
    if isinstance(res, dict):
        return res
    return {"ok": True, "result": res}


# ---------------------------------------------------------------- HTTP handler
class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "ClipForgeDashboard/1.0"

    def log_message(self, fmt, *args):  # quiet-ish logging
        sys.stderr.write("dashboard: " + fmt % args + "\n")

    # -- helpers ------------------------------------------------------
    def _json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _static(self, rel):
        path = (DASH_DIR / rel).resolve()
        if not str(path).startswith(str(DASH_DIR.resolve())) or not path.is_file():
            self._not_found()
            return
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _not_found(self):
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"not found")

    def _media(self, name):
        """Stream a finished clip from ~/.clipforge/clips/ (Range-aware)."""
        from . import config as C
        safe = Path(urllib.parse.unquote(name)).name  # strip any ../ tricks
        path = (C.CLIPS_DIR / safe).resolve()
        if not str(path).startswith(str(C.CLIPS_DIR.resolve())) \
                or not path.is_file():
            self._not_found()
            return
        size = path.stat().st_size
        ctype = mimetypes.guess_type(str(path))[0] or "video/mp4"
        start, end = 0, size - 1
        status = 200
        rng = self.headers.get("Range")
        if rng:
            try:
                unit, _, spec = rng.partition("=")
                s, _, e = spec.partition("-")
                if unit.strip() == "bytes":
                    start = int(s) if s else max(0, size - int(e))
                    end = int(e) if e else size - 1
                    end = min(end, size - 1)
                    if 0 <= start <= end:
                        status = 206
            except ValueError:
                pass
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range",
                             f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1024 * 256, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    # -- routes -------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        p = parsed.path
        if p == "/" or p == "/index.html":
            self._static("index.html")
        elif p.startswith("/media/"):
            self._media(p[len("/media/"):])
        elif p in ("/styles.css", "/app.js"):
            self._static(p[1:])
        else:
            self._not_found()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        p = parsed.path
        if not p.startswith("/api/"):
            self._not_found()
            return
        name = p[len("/api/"):]
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
            if not isinstance(body, dict):
                body = {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = {}
        self._json(_call_api(name, body))


# ---------------------------------------------------------------- entry
def pick_port(preferred=8765):
    import socket
    port = preferred
    while port < preferred + 50:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                port += 1
    raise OSError("koi free port nahi mila")


def run(port=None, open_browser=True, block=True):
    port = port or pick_port()
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    url = f"http://127.0.0.1:{port}/"
    print(f"\nClipForge dashboard: {url}")
    print("Band karne ke liye Ctrl+C dabao.\n")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    if block:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nDashboard band.")
        return 0
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)
    return run(port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    sys.exit(main())
