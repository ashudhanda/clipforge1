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

## Quick Start (3 steps)

```bash
git clone https://github.com/ashudhanda/clipforge
cd clipforge
python setup.py
```

Bas — `setup.py` sab kuch install karke **dashboard khud browser mein khol
deta hai**. Pehli baar hai to dashboard ke andar hi setup wizard aayega
(channel name, niche, caption style) — uske baad terminal ki zaroorat nahi.

Manual route (optional): `pip install -r requirements.txt`, phir
`python -m clipforge.cli dashboard`.

### Dashboard dobara kholna (setup ke baad)

Sabse easy — file par **double-click** karo:
- **Windows:** `ClipForge.bat`
- **Mac:** `Start ClipForge.command`

Ya terminal mein ye short command (`clipforge` folder ke andar):

```bash
python start.py
```

- Dashboard browser mein khul jayega (`http://127.0.0.1:8765`) — dobara install nahi hoga
- Jab tak terminal/command window khuli hai, dashboard chalta rahega
- Band karoge to koi data loss nahi — clips/settings `~/.clipforge/` mein safe rehte hain
- Settings kabhi bhi badal sakte ho: dashboard → **Settings** (dobara wizard chalane ki zaroorat nahi)

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

## YouTube upload setup (one time, ~5 min)

Uploads use the official YouTube Data API with your own Google login.
Follow every step — especially **Test users** (step 9), else Google blocks the login:

**A. Project banao**
1. Go to [console.cloud.google.com](https://console.cloud.google.com) → sign in with your Gmail
2. Top bar → **Select a project** → **New Project** → name it (e.g. `ClipForge`) → Create → select it

**B. YouTube Data API v3 enable karo**
3. ☰ menu → **APIs & Services → Library** → search `YouTube Data API v3` → **Enable**

**C. OAuth consent screen (login ke liye zaroori)**
4. ☰ menu → **APIs & Services → OAuth consent screen** → User Type: **External**
5. App name `ClipForge`, support email + developer email = your Gmail → Save and Continue (×2)
6. **Test users → Add users → apna Gmail add karo** → Save ⚠️ (bina iske "Access blocked" aayega)

**D. OAuth client JSON banao**
7. ☰ menu → **APIs & Services → Credentials → Create Credentials → OAuth client ID** → type **Desktop app** → Create → **Download JSON**

**E. ClipForge se jodo**
8. Dashboard kholo → **Settings → YouTube connection** → downloaded file ka poora content paste karo → **Save OAuth JSON**
9. **Connect YouTube** dabao → browser mein Gmail chuno → **"Google hasn't verified this app"** aaye to **Advanced → Go to ClipForge (unsafe)** → Continue

Done! Token khud refresh hota rahega. Note: test-mode login har **7 din** mein expire hota hai — bas dobara Connect dabana hota hai.

⚠️ **Zaroori:** jab tak Google tumhara app verify nahi karta, API se upload ki hui videos YouTube **zabardasti private** kar deta hai — chahe dashboard mein public chuno. Public upload ke liye Google Cloud mein app verification karwana padta hai.

**Quota note:** Google gives 10,000 free API units/day; one upload costs
~100 units (Dec 2025 se pehle 1,600 tha — Google ke hisaab se figure badal
sakta hai). ClipForge tracks this and automatically pushes extra scheduled
uploads to the next day.

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
