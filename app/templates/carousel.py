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
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.twilio_client import client

CONTENT_API_BASE = "https://content.twilio.com/v1/Content"
_auth = (settings.twilio_account_sid, settings.twilio_auth_token)

# gandys.com.py no publica precios (venta/alquiler B2B por cotizacion), asi
# que el campo "price" del scraper viene vacio para casi todos los productos.
# Se usa como parte de la frase "Precio: {valor}" del body de cada tarjeta,
# por eso NO repite la palabra "precio".
NO_PRICE_FALLBACK = "consultar con un asesor"

# Twilio exige que las variables en el boton URL solo aparezcan al final de
# un string con dominio fijo (no puede ser la URL entera una variable), asi
# que el template usa esta base fija + el slug del producto como variable.
_PRODUCT_URL_BASE = settings.scrape_base_url.rstrip("/") + "/productos/"


def _extract_product_slug(product_url: str) -> str:
    path = urlparse(product_url).path.rstrip("/")
    return path.rsplit("/", 1)[-1] if path else ""


# Imagen real del sitio, usada solo como ejemplo para que WhatsApp pueda
# renderizar la vista previa de aprobacion (no es la que se manda en produccion
# -- esa la reemplaza siempre products_to_content_variables con la real).
_SAMPLE_IMAGE_URL = (
    "https://excellent-bear-d150ebb5f0.media.strapiapp.com/"
    "large_Whats_App_Image_2026_05_29_at_14_48_21_4b9575c620.jpeg"
)


def build_carousel_payload(friendly_name: str, num_cards: int = 3) -> dict:
    """Arma el payload de creacion de un template twilio/carousel con N tarjetas
    de placeholders. Los indices de variables son continuos: body + (title, body,
    media, url) por cada tarjeta.

    Nota de schema (verificado contra https://www.twilio.com/docs/content/carousel):
    - "media" tiene que ser un string, no un array.
    - "url" del boton de tipo URL solo admite la variable al FINAL de un
      dominio fijo -- no puede ser la URL completa una variable.
    - TODAS las variables usadas en el template necesitan un valor default
      en "variables", no solo {{1}}. Sin esto, WhatsApp no puede renderizar
      la vista previa de aprobacion y la rechaza con un 400.
    """
    cards = []
    variables = {"1": "cliente"}
    var_index = 2
    for card_number in range(1, num_cards + 1):
        cards.append(
            {
                "title": f"Producto: {{{{{var_index}}}}}",
                "body": f"Precio: {{{{{var_index + 1}}}}} · Coordiná tu compra o alquiler por este chat.",
                "media": f"{{{{{var_index + 2}}}}}",
                "actions": [
                    {
                        "type": "URL",
                        "title": "Ver producto",
                        "url": f"{_PRODUCT_URL_BASE}{{{{{var_index + 3}}}}}",
                    }
                ],
            }
        )
        variables[str(var_index)] = f"Producto de ejemplo {card_number}"
        variables[str(var_index + 1)] = "Gs. 500.000"
        variables[str(var_index + 2)] = _SAMPLE_IMAGE_URL
        variables[str(var_index + 3)] = "racks-selectivos"
        var_index += 4

    return {
        "friendly_name": friendly_name,
        "language": "es",
        "variables": variables,
        "types": {
            "twilio/carousel": {
                "body": (
                    f"Hola {{{{1}}}}! Encontramos estos productos de Gandy's "
                    "que podrían interesarte segun lo que consultaste. "
                    "Mirá los detalles y el precio en cada tarjeta:"
                ),
                "cards": cards,
            }
        },
    }


def create_carousel_template(friendly_name: str, num_cards: int = 3) -> str:
    """Crea el template en Twilio y devuelve el ContentSid generado."""
    payload = build_carousel_payload(friendly_name, num_cards)
    response = httpx.post(CONTENT_API_BASE, json=payload, auth=_auth, timeout=20)
    if response.status_code >= 400:
        # Imprimimos el cuerpo del error de Twilio -- raise_for_status() solo
        # tira el codigo, y el detalle (que campo esta mal) viene aca.
        print("Twilio Content API error:", response.status_code, response.text)
    response.raise_for_status()
    return response.json()["sid"]


def submit_for_whatsapp_approval(content_sid: str, name: str, category: str = "MARKETING") -> dict:
    """Envia el template a revision de WhatsApp. Requerido antes de usarlo fuera
    de una sesion activa de 24hs."""
    url = f"{CONTENT_API_BASE}/{content_sid}/ApprovalRequests/whatsapp"
    response = httpx.post(url, json={"name": name, "category": category}, auth=_auth, timeout=20)
    if response.status_code >= 400:
        print("Twilio Content API error:", response.status_code, response.text)
    response.raise_for_status()
    return response.json()


def check_approval_status(content_sid: str) -> dict:
    """Consulta el estado de la solicitud de aprobacion de WhatsApp.

    El campo "status" de la respuesta puede ser:
    - "received": en revision, todavia no se puede usar fuera de una sesion.
    - "approved": ya se puede usar en produccion.
    - "rejected": revisar el campo "rejection_reason" para el motivo.
    """
    url = f"{CONTENT_API_BASE}/{content_sid}/ApprovalRequests"
    response = httpx.get(url, auth=_auth, timeout=20)
    if response.status_code >= 400:
        print("Twilio Content API error:", response.status_code, response.text)
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
    esperado por un template creado con build_carousel_payload.

    La variable de URL manda solo el slug (ej. "racks-selectivos"), no la URL
    completa -- el dominio fijo ya esta en el texto aprobado del template
    (ver _PRODUCT_URL_BASE / build_carousel_payload)."""
    variables = {"1": customer_name}
    var_index = 2
    for product in products:
        price = product.get("price") or NO_PRICE_FALLBACK
        variables[str(var_index)] = product.get("name", "")
        variables[str(var_index + 1)] = price
        variables[str(var_index + 2)] = product.get("image_url", "")
        variables[str(var_index + 3)] = _extract_product_slug(product.get("url", ""))
        var_index += 4
    return variables