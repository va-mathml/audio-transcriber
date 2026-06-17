# Audio Transcriber

Speech-to-text API with Telegram bot and web interface. Send any audio or video
file and get the transcript back in seconds.

**Live services**
- Web: https://audio-transcriber.onrender.com
- Bot: [@vatranscriber_bot](https://t.me/vatranscriber_bot) on Telegram

---

## What it does

You receive a voice message on WhatsApp, a meeting recording, a lecture clip,
or any audio/video file. Forward it to the Telegram bot or drop it on the web
interface. The transcript appears in the same chat or on screen - no account
required, no file size gymnastics beyond 50 MB.

---

## Architecture

```
Telegram user                    Web user (laptop)
sends audio/video                drags & drops file
      |                                |
      v                                v
Telegram API              Render - Static frontend
(webhook POST)            frontend/index.html
      |                   drag & drop interface
      |                   calls /transcribe via fetch()
      v                                |
      +────────────────────────────────+
                     |
                     v
         Railway - FastAPI backend
         backend/main.py
         backend/bot.py
         backend/transcriber.py
                     |
                     v
      Dual Groq Whisper (100% cloud, no local model)
      - GROQ_API_KEY  → whisper-large-v3-turbo  (fast, primary)
      - GROQ_API_KEY_2 → whisper-large-v3       (precise, fallback)
                     |
                     v
      Native formats (no ffmpeg): OGG, MP3, MP4, M4A, WAV, FLAC, WEBM
      ffmpeg only for: MKV, AVI, MOV
```

**Two independent services, one codebase:**
- Railway runs the bot and API (always on, webhook mode)
- Render serves the web UI (static, zero cold-start cost)

---

## Supported formats

| Category | Formats |
|----------|---------|
| Audio | MP3, WAV, OGG, OPUS, M4A, FLAC |
| Video | MP4, MKV, AVI, MOV, WebM |
| Telegram native | Voice notes (.ogg), video notes |
| WhatsApp forwarded | Voice messages (.ogg/.opus) |

---

## Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI + Uvicorn |
| Transcription | Groq Whisper API (dual key, cloud-only) |
| Audio pipeline | ffmpeg (only for MKV/AVI/MOV) |
| Bot | Telegram Bot API - webhook mode |
| Frontend | Vanilla HTML/CSS/JS - drag and drop |
| Backend deploy | Railway |
| Frontend deploy | Render |
| Config | python-dotenv |

---

## Skills demonstrated

- REST API design with FastAPI (file upload, async endpoints, CORS)
- Dual-key Groq architecture with automatic fallback (turbo → large-v3)
- Direct audio streaming to Groq API (no intermediate conversion for most formats)
- Telegram Bot API integration - webhook mode (Mode 2, always-on)
- Dual-cloud deployment strategy (Railway + Render, same codebase)
- Security basics: input validation, file sanitization, path traversal prevention
- Async Python with httpx for non-blocking file downloads
- Environment-based configuration for dev/prod parity

---

## Project structure

```
audio-transcriber/
├── backend/
│   ├── main.py            # FastAPI app - /transcribe + /webhook + /health
│   ├── transcriber.py     # Dual Groq keys: turbo (primary) + large-v3 (fallback)
│   ├── bot.py             # Telegram handler - audio, video, voice notes
│   ├── utils.py           # Validation, formatting, cleanup helpers
│   ├── requirements.txt
│   └── Procfile           # Railway entry point
├── frontend/
│   └── index.html         # Drag & drop UI - calls backend API
├── scripts/
│   └── set_webhook.py     # Register Railway URL as Telegram webhook
├── .env.example           # All environment variables documented
├── .gitignore
└── README.md
```

---

## Local setup (development)

**Prerequisites:** Python 3.10+, ffmpeg

```bash
# 1. Clone
git clone https://github.com/va-mathml/audio-transcriber.git
cd audio-transcriber

# 2. Install dependencies
pip install -r backend/requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your GROQ_API_KEY and TELEGRAM_BOT_TOKEN

# 4. Run backend
cd backend
uvicorn main:app --reload --port 8000

# 5. Open frontend
# Open frontend/index.html in your browser
# Set BACKEND_URL = "http://localhost:8000" in index.html for local testing
```

---

## Deploy

### Backend - Railway

1. Push this repo to GitHub
2. New project on railway.app - connect repo
3. Set root directory: `backend`
4. Add environment variables from `.env.example`
5. Railway auto-detects `Procfile` and deploys
6. Copy the generated URL (e.g. `https://audio-transcriber.railway.app`)

### Register Telegram webhook

```bash
# Set WEBHOOK_URL in .env, then:
python scripts/set_webhook.py

# Verify
python scripts/set_webhook.py --status
```

### Frontend - Render

1. New static site on render.com - connect same repo
2. Set root directory: `frontend`
3. Build command: (leave empty)
4. Publish directory: `frontend`
5. Edit `BACKEND_URL` in `frontend/index.html` to point to your Railway URL
6. Deploy

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | Yes | Primary key from console.groq.com |
| `GROQ_API_KEY_2` | Recommended | Secondary key (fallback if primary hits quota) |
| `TELEGRAM_BOT_TOKEN` | Yes | Token from @BotFather |
| `WEBHOOK_URL` | Yes | Railway app URL (no trailing slash) |
| `GROQ_MODEL` | No | Default: `whisper-large-v3-turbo` (primary) |
| `GROQ_MODEL_2` | No | Default: `whisper-large-v3` (fallback) |
| `TRANSCRIPTION_LANGUAGE` | No | Default: `es` (leave empty for auto-detect) |
| `MAX_FILE_SIZE_MB` | No | Default: `50` |
| `ALLOWED_ORIGINS` | No | CORS origins, comma-separated |

---

## Roadmap

- YouTube URL transcription via yt-dlp
- Speaker diarization (who said what)
- Transcript summary via LLM
- Multi-language auto-detection per message
- WhatsApp direct integration via Meta API

---

## Author

Victor Aguilar - Mathematics and AI educator, Cali, Colombia

GitHub: [va-mathml](https://github.com/va-mathml)
LinkedIn: [vaguilar-ai](https://linkedin.com/in/vaguilar-ai)
