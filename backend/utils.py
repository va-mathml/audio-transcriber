"""
utils.py
Helpers de limpieza, validacion y formato.
Autor: Victor Aguilar - github.com/va-mathml
"""

import os
import logging
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
# LIMPIEZA DE ARCHIVOS TEMPORALES
# ════════════════════════════════════════════════════════════════════════════

def cleanup(*paths: Path) -> None:
    """Elimina archivos temporales sin lanzar excepcion si no existen."""
    for path in paths:
        try:
            if path and Path(path).exists():
                Path(path).unlink()
                logger.debug(f"Eliminado: {path}")
        except Exception as e:
            logger.warning(f"No se pudo eliminar {path}: {e}")


def safe_tempfile(suffix: str) -> Path:
    """
    Crea un archivo temporal y retorna su Path.
    El llamador es responsable de eliminarlo con cleanup().
    """
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return Path(path)


# ════════════════════════════════════════════════════════════════════════════
# FORMATO DE SALIDA
# ════════════════════════════════════════════════════════════════════════════

def format_duration(seconds: float) -> str:
    """
    Convierte segundos a formato legible.
    Ejemplos: 65 -> '1m 5s' | 3600 -> '1h 0m' | 45 -> '45s'
    """
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        minutes, secs = divmod(seconds, 60)
        return f"{minutes}m {secs}s"
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m"


def format_file_size(bytes_size: int) -> str:
    """
    Convierte bytes a formato legible.
    Ejemplos: 1024 -> '1.0 KB' | 1048576 -> '1.0 MB'
    """
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.1f} GB"


def truncate_text(text: str, max_chars: int = 200, ellipsis: str = "...") -> str:
    """
    Trunca texto largo para logs o previsualizaciones.
    """
    if len(text) <= max_chars:
        return text
    return text[:max_chars - len(ellipsis)] + ellipsis


# ════════════════════════════════════════════════════════════════════════════
# VALIDACION
# ════════════════════════════════════════════════════════════════════════════

def sanitize_filename(filename: str) -> str:
    """
    Limpia el nombre de archivo removiendo caracteres peligrosos.
    Evita path traversal y caracteres invalidos en Windows/Linux.
    """
    # Tomar solo el nombre base, sin directorios
    name = Path(filename).name

    # Caracteres permitidos: alfanumericos, guion, guion bajo, punto
    safe = "".join(
        c if (c.isalnum() or c in "-_. ") else "_"
        for c in name
    )

    # Limitar longitud
    if len(safe) > 100:
        stem   = Path(safe).stem[:90]
        suffix = Path(safe).suffix
        safe   = stem + suffix

    return safe or "archivo"


def is_valid_telegram_token(token: str) -> bool:
    """
    Valida formato basico de un token de bot de Telegram.
    Formato: 123456789:ABCdefGHIjklMNOpqrSTUvwxyz
    """
    if not token:
        return False
    parts = token.split(":")
    if len(parts) != 2:
        return False
    bot_id, secret = parts
    return bot_id.isdigit() and len(secret) >= 35


def is_valid_groq_key(key: str) -> bool:
    """Valida formato basico de una Groq API key."""
    return key.startswith("gsk_") and len(key) > 20


# ════════════════════════════════════════════════════════════════════════════
# LOGGING DE RESULTADOS
# ════════════════════════════════════════════════════════════════════════════

def log_transcription_result(result: dict, source: str = "api") -> None:
    """
    Registra el resultado de una transcripcion de forma estructurada.
    Util para monitoreo en Railway/Render logs.
    """
    logger.info(
        f"[TRANSCRIPCION] "
        f"fuente={source} | "
        f"archivo={result.get('source_file', 'desconocido')} | "
        f"motor={result.get('engine', '?')} | "
        f"duracion={format_duration(result.get('duration_sec', 0))} | "
        f"caracteres={result.get('char_count', 0)} | "
        f"preview='{truncate_text(result.get('text', ''), 80)}'"
    )
