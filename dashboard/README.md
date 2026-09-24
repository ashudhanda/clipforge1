# ClipForge dashboard

Local web UI for ClipForge — beginner-friendly control panel.

- **Theme:** "Acid" — dark mode `#090C07` bg / `#C8FF3D` lime / `#FF4D8D` pink,
  plus a light-mode twin. Toggle in the topbar (saved in localStorage).
- **Animations (3, subtle):** ShinyText logo sheen, CountUp stat tiles,
  SpotlightCard hover glow on clip cards, plus a static film-grain overlay.
  No WebGL, no build step — plain HTML/CSS/vanilla JS.
- **Backend:** `clipforge/dashboard_server.py` (stdlib only) exposes
  `clipforge/api.py` as `POST /api/<fn>` and serves these static files.
  Finished Shorts stream from `~/.clipforge/clips/` via `/media/<file>`
  (HTTP Range support so the `<video>` preview can seek).

Run it:

    clipforge dashboard            # opens the browser
    clipforge dashboard --no-browser --port 8765

Pages: **Generate** (auto-research + link mode, live progress),
**Clips** (grid + right-side preview/edit/approve/upload/schedule panel),
**Uploads** (scheduled queue, quota, history), **Settings** (channel, AI keys,
YouTube OAuth, danger zone). First run shows a 3-step setup wizard.

Secrets (LLM keys, OAuth token) are never sent back to the UI —
key fields show `••••••` when a key is stored.
