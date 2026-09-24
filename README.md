# ClipForge 🎬

Turn long YouTube videos into fully-edited vertical **Shorts** — automatically.

Give it a niche (`podcast`, `gaming`, `finance`...) or a video link, and it:
1. **Researches** trending long videos in your niche (nothing downloaded yet)
2. **Reads the captions first** (seconds, not gigabytes)
3. **Finds the best moments** — questions, hype, strong opinions, reactions
4. **Downloads ONLY those moments** (MBs, not GBs)
5. **Edits each into a 9:16 Short** — smart crop, hook card, karaoke captions, zoom punch-ins, clean audio
6. **Writes titles, descriptions, hashtags** for every clip
7. **Uploads to YouTube** via the official API, or **schedules** for later

No AI voiceover. Your original audio stays untouched.

---

## Quick Start (4 steps)

```bash
git clone https://github.com/ashudhanda/clipforge
cd clipforge && pip install -r requirements.txt
python -m clipforge.cli setup      # first-time setup (asks once, saves on your system)
python -m clipforge.cli dashboard  # opens the dashboard in your browser
```

That's it — the dashboard walks you through everything (generate clips,
preview, upload, schedule). Beginners never need the terminal after this.

---

## Quickstart (3 steps)

**1. Setup** — one command, works on Windows/Mac/Linux:

```bash
python setup.py
```

This installs everything (Python packages, ffmpeg, AI models) and creates
`~/.clipforge/` for your settings. Safe to run again anytime.

**2. First-run wizard:**

```bash
python -m clipforge.cli setup
```

It asks a few simple questions (channel name, niche, caption style) and
saves everything on your system — you answer once, never again.

**3. Make clips:**

```bash
# Auto mode: research your niche and build 5 clips
python -m clipforge.cli auto --niche podcast --clips 5

# Link mode: build clips from one video
python -m clipforge.cli from-link "https://www.youtube.com/watch?v=..." --clips 5
```

Then preview the MP4s in `~/.clipforge/clips/`, and:

```bash
python -m clipforge.cli list                 # see your clips
python -m clipforge.cli upload <clip_id>     # upload one now
python -m clipforge.cli schedule <clip_id> --at "2026-09-25 18:00"  # or later
python -m clipforge.cli worker               # process due scheduled uploads
```

Tip: `pip install -e .` once, and you can use the short `clipforge` command
instead of `python -m clipforge.cli`.

---

## YouTube upload setup (one time)

Uploads use the official YouTube Data API with your own Google login:

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → create a project
2. Enable **YouTube Data API v3** (APIs & Services → Library)
3. Credentials → Create Credentials → **OAuth client ID** → Desktop app
4. Download the JSON → save as `~/.clipforge/client_secret.json`
5. Run `python -m clipforge.cli setup` → browser opens → sign in with Google

Done. The token refreshes itself forever.

**Quota note:** Google gives 10,000 free API units/day; one upload costs
1,600 (~6 uploads/day). ClipForge tracks this and automatically pushes
extra scheduled uploads to the next day.

---

## Features

- **Two modes** — auto-research by niche, or direct video link
- **Captions-first pipeline** — reads subtitles before downloading anything; falls back to local transcription (faster-whisper) when a video has no captions
- **Smart moment detection** — rule-based virality scoring (questions, hype, triggers) with optional LLM re-ranking (Gemini free key, OpenAI, Groq, Ollama…)
- **12 caption styles** — hormozi, mrbeast, pop, neon, karaoke, and more
- **Hook cards** — the first 2 seconds mined from the transcript, never filler
- **Face-aware 9:16 crop** — keeps the speaker framed (YuNet, runs locally)
- **Comment triggers** — descriptions and pinned comments matched to the moment (challenge / mystery / debate / tip)
- **Quality gate + dedup** — bad renders rejected, near-duplicates blocked
- **Scheduler** — quota-aware, miss-safe (missed jobs are reported, never silently skipped)
- **Dashboard-ready** — `clipforge/api.py` is the service layer the web UI plugs into

---

## Config reference

Everything lives in `~/.clipforge/config.yaml` (see `config.example.yaml`
for all options with explanations): channel name, niche presets (window
sizes + keywords per niche), caption style, clip length, hashtags,
upload privacy, `made_for_kids` flag, LLM provider, research filters.

Secrets (LLM keys, OAuth token) live in `secrets.yaml` / `token.json`
with owner-only permissions and are never logged.

---

## Responsible use ⚠️

- **Only use videos you have the right to use.** Downloading and re-uploading
  someone else's content can trigger copyright claims or YouTube's
  reused-content policy (which affects monetization). ClipForge edits are
  transformative (cuts, reframe, captions, hooks) but that is **not** a
  legal guarantee — when in doubt, use your own videos or properly
  licensed content, and always credit the source (ClipForge adds the
  credit line to every description automatically).
- **Respect YouTube's Terms of Service** and rate limits. Don't hammer
  searches/downloads; the tool backs off politely.

---

## How it works (for the curious)

```
research (yt-dlp search, no download)
   → captions fetch (subtitle file only, KBs)
   → moment detection (sliding windows + virality scoring + diversity filter)
   → download ONLY selected segments (yt-dlp --download-sections, MBs)
   → word-level transcription of each segment (exact caption timings)
   → 9:16 edit (ffmpeg: smart crop, zoompan, ASS karaoke burn, loudnorm)
   → title/description/hashtags/pinned comments
   → quality gate → queued for preview → upload / schedule
```

## Roadmap

- Web dashboard (in design) — visual preview, one-click upload, calendar scheduling
- Hosted version — run on a server, download finished clips
- More caption styles, multi-language niches

## License

MIT — see [LICENSE](LICENSE).
