"""Helper para crear y enviar un WhatsApp Carousel via el Content API de Twilio.

Se usa HTTP directo (no el SDK) contra la Content API porque su forma es estable
entre versiones del SDK de twilio-python. Verificar siempre el schema vigente en
https://www.twilio.com/docs/content/carousel antes de usar en produccion: Twilio
puede iterar el formato de "cards"/"actions".

Flujo real de WhatsApp:
1. Se crea UN template de carousel con placeholders ({{1}}, {{2}}, ...) para un
   numero FIJO de tarjetas (ej. 3). Este paso se hace una sola vez.
2. Meta/WhatsApp debe APROBAR el template (create_carousel_template +
   submit_for_whatsapp_approval) antes de poder enviarlo fuera de la ventana de
   24hs de conversacion.
3. Una vez aprobado, se envia muchas veces rellenando los placeholders con
   productos reales (send_carousel), sin volver a pedir aprobacion.
"""

import json

import httpx

from app.config import settings
from app.twilio_client import client

CONTENT_API_BASE = "https://content.twilio.com/v1/Content"
_auth = (settings.twilio_account_sid, settings.twilio_auth_token)


def build_carousel_payload(friendly_name: str, num_cards: int = 3) -> dict:
    """Arma el payload de creacion de un template twilio/carousel con N tarjetas
    de placeholders. Los indices de variables son continuos: body + (title, body,
    media, url) por cada tarjeta.
    """
    cards = []
    var_index = 2  # {{1}} se usa para el nombre del cliente en el body general
    for _ in range(num_cards):
        cards.append(
            {
                "title": f"{{{{{var_index}}}}}",
                "body": f"{{{{{var_index + 1}}}}}",
                "media": [f"{{{{{var_index + 2}}}}}"],
                "actions": [
                    {"type": "URL", "title": "Ver producto", "url": f"{{{{{var_index + 3}}}}}"}
                ],
            }
        )
        var_index += 4

    return {
        "friendly_name": friendly_name,
        "language": "es",
        "variables": {"1": "cliente"},
        "types": {
            "twilio/carousel": {
                "body": "Hola {{1}}! Mira estos productos de Gandy's:",
                "cards": cards,
            }
        },
    }


def create_carousel_template(friendly_name: str, num_cards: int = 3) -> str:
    """Crea el template en Twilio y devuelve el ContentSid generado."""
    payload = build_carousel_payload(friendly_name, num_cards)
    response = httpx.post(CONTENT_API_BASE, json=payload, auth=_auth, timeout=20)
    response.raise_for_status()
    return response.json()["sid"]


def submit_for_whatsapp_approval(content_sid: str, name: str, category: str = "MARKETING") -> dict:
    """Envia el template a revision de WhatsApp. Requerido antes de usarlo fuera
    de una sesion activa de 24hs."""
    url = f"{CONTENT_API_BASE}/{content_sid}/ApprovalRequests/whatsapp"
    response = httpx.post(url, json={"name": name, "category": category}, auth=_auth, timeout=20)
    response.raise_for_status()
    return response.json()


def send_carousel(to: str, content_sid: str, content_variables: dict) -> str:
    """Envia el carousel ya aprobado, con los datos reales de los productos.

    content_variables: dict con TODAS las claves usadas en el template, ej:
      {"1": "Juan", "2": "Zapatilla X", "3": "Gs. 350.000", "4": "https://.../img.jpg",
       "5": "https://gandys.com.py/producto/zapatilla-x", ...}
    """
    message = client.messages.create(
        from_=settings.twilio_whatsapp_number,
        to=to,
        content_sid=content_sid,
        content_variables=json.dumps(content_variables),
    )
    return message.sid


def products_to_content_variables(customer_name: str, products: list[dict]) -> dict:
    """Convierte hasta N productos scrapeados en el dict de content_variables
    esperado por un template creado con build_carousel_payload."""
    variables = {"1": customer_name}
    var_index = 2
    for product in products:
        variables[str(var_index)] = product.get("name", "")
        variables[str(var_index + 1)] = product.get("price", "")
        variables[str(var_index + 2)] = product.get("image_url", "")
        variables[str(var_index + 3)] = product.get("url", "")
        var_index += 4
    return variables
