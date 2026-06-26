"""
transcriber.py
Motor de transcripcion: Groq Whisper API con dos keys en rotacion
Autor: Victor Aguilar - github.com/va-mathml
"""

import os
import logging
import tempfile
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Formatos soportados ────────────────────────────────────────────────────
AUDIO_FORMATS = {".mp3", ".wav", ".ogg", ".opus", ".m4a", ".flac", ".webm"}
VIDEO_FORMATS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}
ALL_FORMATS   = AUDIO_FORMATS | VIDEO_FORMATS

# Groq acepta estos formatos directamente (sin conversion ffmpeg)
GROQ_NATIVE   = {".flac", ".mp3", ".mp4", ".m4a", ".ogg", ".opus", ".wav", ".webm"}
# Solo estos requieren ffmpeg para extraer el audio
FFMPEG_NEEDED = {".mkv", ".avi", ".mov"}

# ─── Configuracion desde entorno ────────────────────────────────────────────
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
GROQ_API_KEY_2 = os.getenv("GROQ_API_KEY_2", "")
GROQ_MODEL     = os.getenv("GROQ_MODEL",   "whisper-large-v3-turbo")  # key1: rapido
GROQ_MODEL_2   = os.getenv("GROQ_MODEL_2", "whisper-large-v3")        # key2: preciso
MAX_FILE_MB    = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
LANGUAGE       = os.getenv("TRANSCRIPTION_LANGUAGE", "es")


# ════════════════════════════════════════════════════════════════════════════
# UTILIDADES ffmpeg
# ════════════════════════════════════════════════════════════════════════════

def check_ffmpeg() -> bool:
    """Verifica que ffmpeg este disponible en PATH."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def extract_audio(input_path: Path, output_path: Path) -> Path:
    """
    Extrae/convierte cualquier audio o video a WAV mono 16kHz.
    Formato optimo para Whisper.
    Retorna output_path si exito, lanza excepcion si falla.
    """
    cmd = [
        "ffmpeg",
        "-i", str(input_path),
        "-vn",                   # eliminar video
        "-acodec", "pcm_s16le",  # PCM 16-bit
        "-ar", "16000",          # 16 kHz
        "-ac", "1",              # mono
        "-y",                    # sobreescribir sin preguntar
        str(output_path)
    ]

    logger.info(f"ffmpeg: {input_path.name} -> {output_path.name}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300  # 5 min max para archivos grandes
    )

    if result.returncode != 0:
        logger.error(f"ffmpeg stderr: {result.stderr[-500:]}")
        raise RuntimeError(f"ffmpeg fallo con codigo {result.returncode}")

    return output_path


def validate_file(file_path: Path) -> None:
    """
    Valida extension y tamano del archivo.
    Lanza ValueError con mensaje descriptivo si falla.
    """
    suffix = file_path.suffix.lower()

    if suffix not in ALL_FORMATS:
        supported = ", ".join(sorted(ALL_FORMATS))
        raise ValueError(f"Formato '{suffix}' no soportado. Usa: {supported}")

    size_mb = file_path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_FILE_MB:
        raise ValueError(
            f"Archivo demasiado grande: {size_mb:.1f} MB "
            f"(maximo: {MAX_FILE_MB} MB)"
        )


# ════════════════════════════════════════════════════════════════════════════
# MOTOR GROQ
# ════════════════════════════════════════════════════════════════════════════

def transcribe_with_groq(audio_path: Path, api_key: str, model: str, language: Optional[str] = None) -> str:
    """
    Transcribe usando Groq Whisper API.
    Groq free tier: 7200 seg/dia por cuenta.
    """
    try:
        from groq import Groq
    except ImportError:
        raise RuntimeError("groq no instalado. Ejecuta: pip install groq")

    client = Groq(api_key=api_key)
    logger.info(f"Groq: {audio_path.name} | modelo: {model}")

    with open(audio_path, "rb") as f:
        params = {
            "file": (audio_path.name, f, "audio/wav"),
            "model": model,
            "response_format": "verbose_json",
            "temperature": 0.0,
        }
        if language:
            params["language"] = language

        transcription = client.audio.transcriptions.create(**params)

    text = transcription.text.strip()
    logger.info(f"Groq: {len(text)} caracteres transcritos")
    return text


# ════════════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════

def _transcribe_audio_file(audio_path: Path, lang: Optional[str]) -> tuple[str, str]:
    """
    Transcribe con dual-key fallback. Retorna (text, engine).
    Lanza RuntimeError si ambas keys fallan o no hay keys configuradas.
    """
    if not GROQ_API_KEY and not GROQ_API_KEY_2:
        raise RuntimeError("No hay ninguna GROQ_API_KEY configurada en las variables de entorno")

    text   = ""
    engine = ""
    error1 = None

    if GROQ_API_KEY:
        try:
            text   = transcribe_with_groq(audio_path, GROQ_API_KEY, GROQ_MODEL, lang)
            engine = "groq_key1"
        except Exception as e:
            error1 = e
            logger.warning(f"GROQ_API_KEY fallo ({e}), intentando con GROQ_API_KEY_2")

    if not text and GROQ_API_KEY_2:
        try:
            text   = transcribe_with_groq(audio_path, GROQ_API_KEY_2, GROQ_MODEL_2, lang)
            engine = "groq_key2"
        except Exception as e2:
            msg = "Ambas keys de Groq fallaron."
            if error1:
                msg += f" Key1: {error1} | Key2: {e2}"
            else:
                msg += f" Key2: {e2}"
            raise RuntimeError(msg)

    if not text and error1:
        raise RuntimeError(f"GROQ_API_KEY_2 no configurada y key primaria fallo: {error1}")

    return text, engine


def transcribe(file_path: Path, language: Optional[str] = None) -> dict:
    """
    Transcribe un archivo de audio o video local.
    Retorna dict con text, engine, language, duration_sec, char_count, source_file.
    """
    validate_file(file_path)
    lang   = language or LANGUAGE or None
    suffix = file_path.suffix.lower()

    with tempfile.TemporaryDirectory() as tmp_dir:
        if suffix in FFMPEG_NEEDED:
            audio_path = Path(tmp_dir) / "audio_converted.wav"
            extract_audio(file_path, audio_path)
        else:
            audio_path = file_path

        duration      = _get_duration(audio_path)
        text, engine  = _transcribe_audio_file(audio_path, lang)

    return {
        "text":         text,
        "engine":       engine,
        "language":     lang or "auto",
        "duration_sec": duration,
        "source_file":  file_path.name,
        "char_count":   len(text),
    }


def transcribe_youtube(url: str, language: Optional[str] = None) -> dict:
    """
    Descarga el audio de un video de YouTube con yt-dlp y lo transcribe con Groq.
    Retorna el mismo dict que transcribe(), con source_file = título del video.
    Lanza ValueError para errores del video (privado, no existe, muy largo).
    """
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError("yt-dlp no instalado. Ejecuta: pip install yt-dlp")

    lang = language or LANGUAGE or None

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        ydl_opts = {
            "format":      "bestaudio/best",
            "outtmpl":     str(tmp_path / "%(id)s.%(ext)s"),
            "quiet":       True,
            "no_warnings": True,
            "noplaylist":  True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e:
            raise ValueError(f"No se pudo descargar el video: {e}")

        title    = info.get("title", "video_youtube")
        duration = float(info.get("duration", 0))

        files = list(tmp_path.iterdir())
        if not files:
            raise RuntimeError("yt-dlp no generó ningún archivo de audio")

        audio_path = files[0]
        size_mb    = audio_path.stat().st_size / (1024 * 1024)

        if size_mb > 24:
            raise ValueError(
                f"El audio del video es demasiado largo ({size_mb:.0f} MB). "
                "Groq acepta máximo ~25 MB (~25 minutos de audio)."
            )

        suffix = audio_path.suffix.lower()
        if suffix in FFMPEG_NEEDED or suffix not in GROQ_NATIVE:
            converted  = tmp_path / "converted.wav"
            extract_audio(audio_path, converted)
            audio_path = converted

        text, engine = _transcribe_audio_file(audio_path, lang)

    return {
        "text":         text,
        "engine":       engine,
        "language":     lang or "auto",
        "duration_sec": duration,
        "source_file":  title,
        "char_count":   len(text),
    }


def _get_duration(wav_path: Path) -> float:
    """Obtiene duracion en segundos usando ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(wav_path)
            ],
            capture_output=True, text=True, timeout=10
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0
