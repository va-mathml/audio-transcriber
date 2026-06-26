"""
bot.py
Handler de Telegram para el transcriptor de audio/video.
Modo: webhook (Modo 2) - Telegram llama a /webhook en Railway.
Soporta: audio, video, notas de voz, documentos de audio/video.
Autor: Victor Aguilar - github.com/va-mathml
"""

import os
import re
import asyncio
import logging
import tempfile
from pathlib import Path

import httpx

from transcriber import transcribe, transcribe_youtube, ALL_FORMATS

logger = logging.getLogger(__name__)

# ─── Configuracion ──────────────────────────────────────────────────────────
BOT_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
MAX_FILE_MB  = int(os.getenv("MAX_FILE_SIZE_MB", "50"))

# Mensajes del bot
YOUTUBE_RE = re.compile(
    r'(https?://)?(www\.)?(youtube\.com/(watch\?v=|shorts/|live/)|youtu\.be/)\S+'
)

MSG_WELCOME = (
    "Hola. Soy un transcriptor de audio y video.\n\n"
    "Envíame:\n"
    "- Una nota de voz\n"
    "- Un archivo de audio (MP3, WAV, OGG, M4A)\n"
    "- Un archivo de video (MP4, MKV, WebM)\n"
    "- Un link de YouTube\n\n"
    "Te devuelvo el texto transcrito."
)

MSG_PROCESSING = "Procesando tu archivo... un momento."

MSG_UNSUPPORTED = (
    "Formato no soportado.\n"
    "Envía audio (MP3, WAV, OGG, OPUS, M4A) o video (MP4, MKV, WebM)."
)

MSG_TOO_LARGE = f"Archivo demasiado grande. Máximo {MAX_FILE_MB} MB."

MSG_ERROR = (
    "Ocurrió un error al transcribir el archivo.\n"
    "Intenta con otro archivo o formato."
)


# ════════════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA - llamado desde main.py /webhook
# ════════════════════════════════════════════════════════════════════════════

async def handle_update(update: dict) -> None:
    """
    Procesa un update de Telegram.
    Telegram envía un JSON con la estructura del mensaje recibido.
    """
    message = update.get("message") or update.get("edited_message")
    if not message:
        logger.info("Update sin mensaje - ignorado")
        return

    chat_id = message["chat"]["id"]
    text    = message.get("text", "")

    # Comandos de texto
    if text.startswith("/start") or text.startswith("/help"):
        await send_message(chat_id, MSG_WELCOME)
        return

    # Link de YouTube
    if text and YOUTUBE_RE.match(text.strip()):
        await _handle_youtube(chat_id, text.strip())
        return

    # Detectar tipo de archivo en el mensaje
    file_info = _extract_file_info(message)

    if not file_info:
        await send_message(
            chat_id,
            "No detecté ningún archivo ni link de YouTube.\n"
            "Usa /help para ver qué puedo hacer."
        )
        return

    file_id   = file_info["file_id"]
    file_name = file_info.get("file_name", f"audio_{file_id[:8]}")
    file_size = file_info.get("file_size", 0)

    # Validar tamaño antes de descargar
    if file_size and file_size > MAX_FILE_MB * 1024 * 1024:
        await send_message(chat_id, MSG_TOO_LARGE)
        return

    # Notificar que estamos procesando
    await send_message(chat_id, MSG_PROCESSING)

    # Descargar, transcribir, responder
    try:
        text_result = await _download_and_transcribe(file_id, file_name)
        await _send_transcription(chat_id, text_result, file_name)

    except ValueError as e:
        await send_message(chat_id, f"Error de validacion: {e}")

    except Exception as e:
        logger.error(f"Error procesando archivo {file_name}: {e}")
        await send_message(chat_id, MSG_ERROR)


# ════════════════════════════════════════════════════════════════════════════
# YOUTUBE
# ════════════════════════════════════════════════════════════════════════════

async def _handle_youtube(chat_id: int, url: str) -> None:
    """Descarga audio de YouTube y transcribe."""
    await send_message(chat_id, "Descargando audio de YouTube... un momento.")
    try:
        result = await asyncio.to_thread(transcribe_youtube, url)
        await _send_transcription(chat_id, result, result["source_file"])
    except ValueError as e:
        await send_message(chat_id, f"No se pudo procesar el video: {e}")
    except Exception as e:
        logger.error(f"Error YouTube {url}: {e}")
        await send_message(chat_id, "No pude transcribir ese video. ¿Es público y sin restricciones de edad?")


# ════════════════════════════════════════════════════════════════════════════
# LOGICA DE DESCARGA Y TRANSCRIPCION
# ════════════════════════════════════════════════════════════════════════════

async def _download_and_transcribe(file_id: str, file_name: str) -> dict:
    """
    Descarga el archivo de Telegram y lo transcribe.
    Retorna el dict de resultado de transcriber.transcribe()
    """
    # Obtener URL de descarga de Telegram
    download_url = await _get_file_url(file_id)

    # Determinar extension
    suffix = Path(file_name).suffix.lower()
    if not suffix or suffix not in ALL_FORMATS:
        suffix = ".ogg"  # default para notas de voz Telegram

    # Descargar a archivo temporal
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            logger.info(f"Descargando {file_name} desde Telegram")
            response = await client.get(download_url)
            response.raise_for_status()
            tmp_path.write_bytes(response.content)

        size_mb = tmp_path.stat().st_size / (1024 * 1024)
        logger.info(f"Descargado: {file_name} ({size_mb:.1f} MB)")

        # Transcribir
        result = transcribe(tmp_path)
        return result

    finally:
        if tmp_path.exists():
            tmp_path.unlink()


async def _send_transcription(chat_id: int, result: dict, file_name: str) -> None:
    """
    Formatea y envía la transcripción al usuario.
    Si el texto es muy largo, lo divide en partes.
    """
    text = result["text"]

    if not text:
        await send_message(chat_id, "No se detectó texto en el audio.")
        return

    # Encabezado como mensaje plano
    header = (
        "🎙️ Transcripción lista\n"
        "Desarrollado por Victor Aguilar · linkedin.com/in/vaguilar-ai"
    )
    await send_message(chat_id, header)

    # Texto en bloque de código (muestra botón copiar en Telegram)
    safe_text = text.replace("`", "'")

    if len(safe_text) <= 4000:
        await send_message(chat_id, f"```\n{safe_text}\n```", parse_mode="Markdown")
    else:
        chunks = [safe_text[i:i+3900] for i in range(0, len(safe_text), 3900)]
        for i, chunk in enumerate(chunks, 1):
            await send_message(chat_id, f"```\nParte {i}/{len(chunks)}:\n\n{chunk}\n```", parse_mode="Markdown")


# ════════════════════════════════════════════════════════════════════════════
# HELPERS TELEGRAM API
# ════════════════════════════════════════════════════════════════════════════

def _extract_file_info(message: dict) -> dict | None:
    """
    Extrae informacion del archivo segun el tipo de mensaje Telegram.

    Tipos soportados:
    - voice       : notas de voz (.ogg/opus)
    - audio       : archivos de audio enviados como audio
    - video       : archivos de video
    - video_note  : videos circulares de Telegram
    - document    : archivos enviados como documentos (cualquier formato)
    """
    # Nota de voz (prioridad - mas comun)
    if "voice" in message:
        v = message["voice"]
        return {
            "file_id":   v["file_id"],
            "file_name": f"voice_{v['file_id'][:8]}.ogg",
            "file_size": v.get("file_size", 0),
        }

    # Audio (MP3, M4A, etc.)
    if "audio" in message:
        a = message["audio"]
        return {
            "file_id":   a["file_id"],
            "file_name": a.get("file_name", f"audio_{a['file_id'][:8]}.mp3"),
            "file_size": a.get("file_size", 0),
        }

    # Video
    if "video" in message:
        v = message["video"]
        return {
            "file_id":   v["file_id"],
            "file_name": v.get("file_name", f"video_{v['file_id'][:8]}.mp4"),
            "file_size": v.get("file_size", 0),
        }

    # Video circular (video_note)
    if "video_note" in message:
        vn = message["video_note"]
        return {
            "file_id":   vn["file_id"],
            "file_name": f"videonote_{vn['file_id'][:8]}.mp4",
            "file_size": vn.get("file_size", 0),
        }

    # Documento (cualquier archivo enviado como doc)
    if "document" in message:
        d      = message["document"]
        fname  = d.get("file_name", "documento")
        suffix = Path(fname).suffix.lower()
        if suffix in ALL_FORMATS:
            return {
                "file_id":   d["file_id"],
                "file_name": fname,
                "file_size": d.get("file_size", 0),
            }

    return None


async def _get_file_url(file_id: str) -> str:
    """
    Obtiene la URL de descarga de un archivo en Telegram.
    Telegram no da URLs directas - hay que pedirlas via getFile.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{TELEGRAM_API}/getFile",
            params={"file_id": file_id}
        )
        response.raise_for_status()
        data = response.json()

    if not data.get("ok"):
        raise RuntimeError(f"Telegram getFile fallo: {data}")

    file_path = data["result"]["file_path"]
    return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"


async def send_message(chat_id: int, text: str, parse_mode: str = None) -> None:
    """Envia un mensaje de texto a un chat de Telegram."""
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
        if response.status_code != 200:
            logger.error(f"Error enviando mensaje: {response.text}")
