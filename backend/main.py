"""
main.py
FastAPI - endpoints principales del transcriptor
  POST /transcribe  -> recibe archivo desde frontend web
  POST /webhook     -> recibe updates de Telegram
  GET  /health      -> healthcheck para Railway/Render
Autor: Victor Aguilar - github.com/va-mathml
"""

import os
import logging
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from transcriber import transcribe, ALL_FORMATS, MAX_FILE_MB, check_ffmpeg
from bot import handle_update

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)
# httpx logs every request URL at INFO; Telegram URLs embed the bot token
logging.getLogger("httpx").setLevel(logging.WARNING)

# ─── App ────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Audio Transcriber API",
    description="Speech-to-text API con Groq Whisper (dos keys en rotacion)",
    version="2.0.0",
    docs_url="/docs",
    redoc_url=None,
)

# ─── CORS (permite llamadas desde el frontend Render) ───────────────────────
# La API no usa cookies ni sesiones, asi que abrir CORS es seguro:
# el navegador solo bloquea paginas, curl/scripts siempre pudieron llamarla.
# Nota: allow_origins NO soporta comodines tipo "https://*.onrender.com".
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Frontend vive en Render (servicio separado)
# Este backend solo expone la API REST


# ─── Registro automatico del webhook ────────────────────────────────────────
@app.on_event("startup")
async def register_webhook():
    """
    Registra {URL publica}/webhook en Telegram al arrancar.
    Render expone RENDER_EXTERNAL_URL automaticamente; WEBHOOK_URL lo sobreescribe.
    Asi no hace falta correr set_webhook.py ni tener el token en local.
    """
    import httpx

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    base  = (os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
    if not token or not base.startswith("https://"):
        logger.info("Webhook no registrado: falta TELEGRAM_BOT_TOKEN o URL publica https")
        return

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/setWebhook",
                json={
                    "url":             f"{base}/webhook",
                    "allowed_updates": ["message", "edited_message"],
                },
            )
        data = response.json()
        if data.get("ok"):
            logger.info(f"Webhook registrado en {base}/webhook")
        else:
            logger.error(f"Telegram rechazo el webhook: {data.get('description', data)}")
    except Exception as e:
        logger.error(f"No se pudo registrar el webhook: {e}")


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/", include_in_schema=False)
async def root():
    return FileResponse("static/index.html")


@app.get("/health")
async def health():
    """
    Healthcheck para Railway y Render.
    Retorna estado del servicio y keys disponibles.
    """
    return {
        "status":  "ok",
        "engines": {
            "groq_key1": bool(os.getenv("GROQ_API_KEY", "")),
            "groq_key2": bool(os.getenv("GROQ_API_KEY_2", "")),
        },
        "ffmpeg":            check_ffmpeg(),   # True => comprime a Opus antes de Groq
        "codec":             "aac-16k-mono-32k",
        "max_file_mb":       MAX_FILE_MB,
        "supported_formats": sorted(ALL_FORMATS),
    }


@app.post("/transcribe")
async def transcribe_endpoint(file: UploadFile = File(...)):
    """
    Recibe un archivo de audio o video y retorna la transcripcion.

    Acepta: mp3, wav, ogg, opus, mp4, mkv, webm, m4a, flac
    Retorna JSON con texto transcrito y metadatos.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No se recibio ningun archivo")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALL_FORMATS:
        raise HTTPException(
            status_code=415,
            detail=f"Formato '{suffix}' no soportado. Formatos validos: {', '.join(sorted(ALL_FORMATS))}"
        )

    # Guardar archivo temporalmente
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        content  = await file.read()
        tmp.write(content)

    size_mb = len(content) / (1024 * 1024)
    logger.info(f"/transcribe: {file.filename} ({size_mb:.1f} MB)")

    try:
        result = transcribe(tmp_path)
        return JSONResponse({
            "success":     True,
            "text":        result["text"],
            "engine":      result["engine"],
            "language":    result["language"],
            "duration_sec": result["duration_sec"],
            "char_count":  result["char_count"],
            "source_file": file.filename,
        })

    except ValueError as e:
        # Errores de validacion (formato, tamano)
        raise HTTPException(status_code=400, detail=str(e))

    except RuntimeError as e:
        # Errores de procesamiento (ffmpeg, API)
        logger.error(f"Error transcribiendo {file.filename}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Limpiar archivo temporal siempre
        if tmp_path.exists():
            tmp_path.unlink()


@app.post("/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Recibe updates de Telegram via webhook (Modo 2).
    Telegram llama a este endpoint cuando el bot recibe un mensaje.
    La URL debe estar registrada con set_webhook.py

    Responde 200 de inmediato y procesa el update en segundo plano:
    si la transcripcion tarda (o el servicio viene de un cold start en Render),
    Telegram no reintenta el mismo update y el audio no se transcribe dos veces.
    """
    try:
        update = await request.json()
        logger.info(f"Webhook recibido: update_id={update.get('update_id')}")
        background_tasks.add_task(handle_update, update)
        return {"ok": True}

    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        # Siempre retornar 200 a Telegram para evitar reintentos infinitos
        return {"ok": False, "error": str(e)}


# ════════════════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════════════════

# Railway y Render arrancan via Procfile:
# web: uvicorn main:app --host 0.0.0.0 --port $PORT
