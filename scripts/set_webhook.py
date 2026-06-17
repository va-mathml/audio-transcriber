"""
set_webhook.py
Registra la URL de Railway como webhook de Telegram.
Ejecutar UNA SOLA VEZ despues de cada deploy en Railway.

Uso:
    python set_webhook.py              # registra webhook
    python set_webhook.py --delete     # elimina webhook (vuelve a polling)
    python set_webhook.py --status     # muestra webhook actual

Requisitos en .env:
    TELEGRAM_BOT_TOKEN=...
    WEBHOOK_URL=https://your-app.railway.app
"""

import os
import sys
import httpx
from dotenv import load_dotenv

load_dotenv()

# ─── Config ─────────────────────────────────────────────────────────────────
BOT_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_URL  = os.getenv("WEBHOOK_URL", "")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def validate_env() -> None:
    """Verifica que las variables necesarias esten configuradas."""
    errors = []
    if not BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN no configurado en .env")
    if not BOT_TOKEN.count(":") == 1:
        errors.append("TELEGRAM_BOT_TOKEN tiene formato invalido (debe ser 123456:ABC...)")
    if not WEBHOOK_URL and "--delete" not in sys.argv and "--status" not in sys.argv:
        errors.append("WEBHOOK_URL no configurado en .env")
    if WEBHOOK_URL and not WEBHOOK_URL.startswith("https://"):
        errors.append("WEBHOOK_URL debe empezar con https:// (Telegram no acepta HTTP)")
    if errors:
        print("\nErrores de configuracion:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)


def get_status() -> None:
    """Muestra el webhook actualmente registrado."""
    print("Consultando webhook actual...")
    response = httpx.get(f"{TELEGRAM_API}/getWebhookInfo")
    data     = response.json()

    if not data.get("ok"):
        print(f"Error de Telegram: {data}")
        return

    info = data["result"]
    url  = info.get("url", "(ninguno)")

    print(f"\nWebhook actual : {url}")
    print(f"Pendientes     : {info.get('pending_update_count', 0)}")
    print(f"Ultimo error   : {info.get('last_error_message', 'ninguno')}")

    if info.get("last_error_date"):
        import datetime
        ts = datetime.datetime.fromtimestamp(info["last_error_date"])
        print(f"Fecha error    : {ts.strftime('%Y-%m-%d %H:%M:%S')}")


def set_webhook() -> None:
    """Registra WEBHOOK_URL/webhook como endpoint de Telegram."""
    target = f"{WEBHOOK_URL}/webhook"
    print(f"Registrando webhook en: {target}")

    response = httpx.post(
        f"{TELEGRAM_API}/setWebhook",
        json={
            "url":                  target,
            "allowed_updates":      ["message", "edited_message"],
            "drop_pending_updates": True,   # ignorar mensajes acumulados
        }
    )
    data = response.json()

    if data.get("ok"):
        print(f"Webhook registrado correctamente.")
        print(f"Telegram enviara updates a: {target}")
    else:
        print(f"Error al registrar webhook: {data.get('description', data)}")
        sys.exit(1)


def delete_webhook() -> None:
    """Elimina el webhook - el bot volvera a modo polling si lo corres localmente."""
    print("Eliminando webhook...")
    response = httpx.post(
        f"{TELEGRAM_API}/deleteWebhook",
        json={"drop_pending_updates": True}
    )
    data = response.json()

    if data.get("ok"):
        print("Webhook eliminado. El bot ya no recibira updates via webhook.")
    else:
        print(f"Error: {data}")
        sys.exit(1)


# ─── Entry point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    validate_env()

    if "--status" in sys.argv:
        get_status()

    elif "--delete" in sys.argv:
        delete_webhook()
        get_status()

    else:
        set_webhook()
        print()
        get_status()
