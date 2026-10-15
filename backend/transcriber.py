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


def _ffmpeg_bin() -> str:
    """
    Devuelve la ruta al binario de ffmpeg.

    Prioriza el binario que empaqueta imageio-ffmpeg (funciona en cualquier
    contenedor sin depender de que el build system instale ffmpeg del sistema,
    p.ej. en Render). Si no esta, usa el 'ffmpeg' del PATH.
    """
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


FFMPEG_BIN = _ffmpeg_bin()

# ─── Formatos soportados ────────────────────────────────────────────────────
AUDIO_FORMATS = {".mp3", ".wav", ".ogg", ".opus", ".m4a", ".flac", ".webm"}
VIDEO_FORMATS = {".mp4", ".mkv", ".avi", ".mov", ".webm"}
ALL_FORMATS   = AUDIO_FORMATS | VIDEO_FORMATS

# Groq acepta estos audios directamente (sin conversion ffmpeg)
GROQ_NATIVE   = {".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wav"}
# Todos los videos deben extraer el audio para no enviar el peso del video a Groq
FFMPEG_NEEDED = {".mp4", ".mkv", ".avi", ".mov", ".webm"}

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
            [FFMPEG_BIN, "-version"],
            capture_output=True, text=True, timeout=15
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def extract_audio(input_path: Path, output_path: Path) -> Path:
    """
    Extrae/convierte cualquier audio o video a AAC mono 16kHz a 32 kbps
    (contenedor .m4a, aceptado por Groq).

    Whisper trabaja internamente a 16kHz mono, asi que AAC 32k no pierde
    calidad util para transcripcion pero pesa ~0.23 MB/min: una charla de
    90 min queda en ~21 MB, por debajo del limite de 25 MB de Groq.

    Se usa el encoder AAC nativo de ffmpeg (compilado en TODA build, incluida
    la que empaqueta imageio-ffmpeg), a diferencia de libopus/libmp3lame que
    dependen de librerias externas que el binario puede no traer.

    Retorna output_path si exito, lanza excepcion si falla.
    """
    cmd = [
        FFMPEG_BIN,
        "-i", str(input_path),
        "-vn",                   # eliminar video
        "-c:a", "aac",           # AAC nativo (siempre disponible)
        "-b:a", "32k",           # 32 kbps: sobra para voz a 16 kHz
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

    # mime segun extension (flac tras compresion; original si no hay ffmpeg)
    mime = {
        ".flac": "audio/flac", ".mp3": "audio/mpeg", ".wav": "audio/wav",
        ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".opus": "audio/opus",
        ".webm": "audio/webm",
    }.get(audio_path.suffix.lower(), "application/octet-stream")

    with open(audio_path, "rb") as f:
        params = {
            "file": (audio_path.name, f, mime),
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

def transcribe(file_path: Path, language: Optional[str] = None) -> dict:
    """
    Interfaz principal de transcripcion.

    Logica de keys:
      1. Intenta con GROQ_API_KEY (key primaria)
      2. Si falla (cuota, error de red, key invalida), intenta con GROQ_API_KEY_2
      3. Si ambas fallan, lanza RuntimeError con ambos errores

    Retorna dict con:
      - text: str            texto transcrito
      - engine: str          motor usado ('groq_key1' | 'groq_key2')
      - language: str        idioma usado
      - duration_sec: float  duracion del audio procesado
      - char_count: int      longitud del texto
      - source_file: str     nombre del archivo original
    """
    if not GROQ_API_KEY and not GROQ_API_KEY_2:
        raise RuntimeError("No hay ninguna GROQ_API_KEY configurada en las variables de entorno")

    validate_file(file_path)

    lang = language or LANGUAGE or None

    suffix = file_path.suffix.lower()

    with tempfile.TemporaryDirectory() as tmp_dir:
        # Comprimimos SIEMPRE a AAC 16kHz mono. Groq rechaza archivos
        # > 25 MB (free tier), y muchos formatos "nativos" (m4a, mp3 de
        # alta calidad, etc.) pasan ese limite con audios largos. AAC
        # 32k reduce el peso a ~0.23 MB/min sin perder calidad para voz.
        if check_ffmpeg():
            audio_path = Path(tmp_dir) / "audio_converted.m4a"
            extract_audio(file_path, audio_path)
        else:
            # Sin ffmpeg no podemos comprimir: enviamos el original y
            # que Groq decida (puede fallar con 413 si supera 25 MB).
            logger.warning("ffmpeg no disponible: se envia el archivo original sin comprimir")
            audio_path = file_path

        duration = _get_duration(audio_path)

        text   = ""
        engine = ""
        error1 = None

        # Intento con key primaria (turbo: rapido)
        if GROQ_API_KEY:
            try:
                text   = transcribe_with_groq(audio_path, GROQ_API_KEY, GROQ_MODEL, lang)
                engine = "groq_key1"
            except Exception as e:
                error1 = e
                logger.warning(f"GROQ_API_KEY fallo ({e}), intentando con GROQ_API_KEY_2")

        # Fallback a key secundaria (large-v3: preciso)
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

    return {
        "text":         text,
        "engine":       engine,
        "language":     lang or "auto",
        "duration_sec": duration,
        "source_file":  file_path.name,
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
