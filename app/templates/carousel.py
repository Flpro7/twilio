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
import re
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.twilio_client import client

CONTENT_API_BASE = "https://content.twilio.com/v1/Content"
_auth = (settings.twilio_account_sid, settings.twilio_auth_token)

_WHITESPACE_RUN_RE = re.compile(r"[ \t]{2,}")

# Twilio exige que las variables en un boton de tipo URL solo aparezcan al
# final de un string con dominio fijo (no puede ser la URL entera una
# variable), asi que el template usa esta base fija + el slug del producto
# como variable.
_PRODUCT_URL_BASE = settings.scrape_base_url.rstrip("/") + "/productos/"

# El boton "Contactar" usa un link de WhatsApp click-to-chat (wa.me/<numero>)
# en vez del tipo de boton nativo PHONE_NUMBER de Twilio. Se eligio asi a
# proposito: PHONE_NUMBER NO admite variables (ni el texto del boton ni el
# numero -- van fijos, grabados en el template aprobado). Un boton URL en
# cambio SI admite variable al final del string, asi que el numero se manda
# como cualquier otro dato dinamico en cada envio. Resultado: cambiar el
# numero de contacto es solo actualizar settings.gandys_contact_whatsapp_number
# (ver app/config.py) y reiniciar -- NO hace falta crear un template nuevo
# ni volver a pedir aprobacion a WhatsApp.
_WHATSAPP_CONTACT_URL_BASE = "https://wa.me/"

# Margen conservador para nombre + descripcion: WhatsApp exige que title +
# body combinados no superen 160 caracteres por tarjeta. Se trunca el
# nombre tambien (no solo la descripcion) para tener un presupuesto
# predecible sin importar que tan largo sea el nombre real del producto.
_MAX_NAME_CHARS = 40
_MAX_DESCRIPTION_CHARS = 60

# Imagen real del sitio, usada solo como ejemplo para que WhatsApp pueda
# renderizar la vista previa de aprobacion (no es la que se manda en produccion
# -- esa la reemplaza siempre products_to_content_variables con la real).
_SAMPLE_IMAGE_URL = (
    "https://excellent-bear-d150ebb5f0.media.strapiapp.com/"
    "large_Whats_App_Image_2026_05_29_at_14_48_21_4b9575c620.jpeg"
)


def _extract_product_slug(product_url: str) -> str:
    path = urlparse(product_url).path.rstrip("/")
    return path.rsplit("/", 1)[-1] if path else ""


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _sanitize_variable_value(text: str) -> str:
    """Twilio rechaza ContentVariables (error 21656) si un valor tiene
    saltos de linea, tabs, o mas de 4 espacios seguidos. El texto scrapeado
    a veces trae ese tipo de whitespace por como el HTML concatena nodos."""
    if not text:
        return text
    cleaned = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    cleaned = _WHITESPACE_RUN_RE.sub(" ", cleaned)
    return cleaned.strip()


def build_carousel_payload(friendly_name: str, num_cards: int = 3) -> dict:
    """Arma el payload de creacion de un template twilio/carousel con N tarjetas
    de placeholders.

    Indices de variables:
    - {{1}}: nombre del cliente (saludo inicial)
    - {{2}}: numero de WhatsApp de contacto, COMPARTIDO por las 3 tarjetas
      (wa.me/{{2}} en el boton "Contactar" de cada una) -- se reusa el mismo
      indice en vez de repetirlo 3 veces para no sumar variables de mas.
    - Desde {{3}} en adelante, 4 variables por tarjeta: title, body, media,
      slug del producto (para el boton "Ver en gandys").

    Diseno de cada tarjeta:
    - title: la variable del nombre va SANDWICHEADA entre texto literal
      real ("Mirá {nombre} en Gandy's") -- NO puede terminar en la
      variable pelada (regla de WhatsApp, ver nota de schema abajo).
    - body: la descripcion tambien va sandwicheada ("Detalle: {descripcion}
      · Consultanos por este chat.") -- NO puede empezar en la variable
      pelada, por la misma regla. Sin precio -- Gandy's no publica precios,
      se consulta con un asesor.
    - 2 botones tipo URL, SIEMPRE en este orden (WhatsApp exige el mismo
      orden en todas las tarjetas): "Contactar" (wa.me) + "Ver en gandys".

    Notas de schema (verificado contra https://www.twilio.com/docs/content/carousel
    y https://www.twilio.com/docs/content/using-variables-with-content-api):
    - "media" tiene que ser un string, no un array.
    - "url" de un boton tipo URL solo admite la variable al FINAL de un
      dominio fijo, precedida por "/" -- no puede ser la URL completa una
      variable.
    - TODAS las variables usadas en el template necesitan un valor default
      en "variables", no solo {{1}}. Sin esto, WhatsApp no puede renderizar
      la vista previa de aprobacion y la rechaza con un 400.
    - Los identificadores de variable deben ser secuenciales sin saltos
      (el conjunto de numeros usados, no repeticiones -- reusar {{2}} en
      varias tarjetas esta bien en tanto no se salteen numeros).
    - Un body/title NO puede empezar ni terminar en una variable pelada --
      necesita texto real (no solo puntuacion) antes Y despues. Este fue
      el motivo real del error 21656 al mandar: el body empezaba
      directamente con la variable de la descripcion.
    - Proporcion real exigida por Meta: por cada x variables, minimo 2x+1
      palabras no-variables en el texto (no 3x+1 como se estimo en un
      intento anterior a partir de una fuente no oficial).
    """
    cards = []
    variables = {"1": "cliente", "2": settings.gandys_contact_whatsapp_number}
    var_index = 3
    for card_number in range(1, num_cards + 1):
        cards.append(
            {
                "title": f"Mirá {{{{{var_index}}}}} en Gandy's",
                "body": (
                    f"Detalle: {{{{{var_index + 1}}}}} · Consultanos "
                    "por este chat."
                ),
                "media": f"{{{{{var_index + 2}}}}}",
                "actions": [
                    {
                        "type": "URL",
                        "title": "Contactar",
                        "url": f"{_WHATSAPP_CONTACT_URL_BASE}{{{{2}}}}",
                    },
                    {
                        "type": "URL",
                        "title": "Ver en gandys",
                        "url": f"{_PRODUCT_URL_BASE}{{{{{var_index + 3}}}}}",
                    },
                ],
            }
        )
        variables[str(var_index)] = f"Producto de ejemplo {card_number}"
        variables[str(var_index + 1)] = (
            "Descripcion de ejemplo para la vista previa de aprobacion"
        )
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
                    "que podrían interesarte según lo que consultaste. "
                    "Mirá los detalles en cada tarjeta:"
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
    - "received"/"pending": en revision, todavia no se puede usar fuera de una sesion.
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
      {"1": "Juan", "2": "595984294691", "3": "Racks Selectivos",
       "4": "Ideal para depositos con...", "5": "https://.../img.jpg",
       "6": "racks-selectivos", ...}
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

    - {{2}} siempre lleva settings.gandys_contact_whatsapp_number -- cambiar
      el numero de contacto es solo tocar ese setting, no hace falta tocar
      esta funcion.
    - La variable de "Ver en gandys" manda solo el slug (ej.
      "racks-selectivos"), no la URL completa -- el dominio fijo ya esta en
      el texto aprobado del template (ver _PRODUCT_URL_BASE).
    - Nombre y descripcion se truncan (_MAX_NAME_CHARS / _MAX_DESCRIPTION_CHARS)
      para no superar el limite de 160 caracteres combinados (title + body)
      que exige WhatsApp, ahora que ambos llevan texto literal extra
      alrededor (ver build_carousel_payload).
    - NO se incluye precio en ningun lado: Gandy's no publica precios, se
      consulta con un asesor (por eso el boton de contacto por WhatsApp).
    """
    variables = {"1": customer_name, "2": settings.gandys_contact_whatsapp_number}
    var_index = 3
    for product in products:
        name = _sanitize_variable_value(product.get("name", "")) or "Producto"
        name = _truncate(name, _MAX_NAME_CHARS)
        description = product.get("description") or "Consultá más detalles con un asesor."
        description = _sanitize_variable_value(description)
        variables[str(var_index)] = name
        variables[str(var_index + 1)] = _truncate(description, _MAX_DESCRIPTION_CHARS)
        variables[str(var_index + 2)] = product.get("image_url", "")
        variables[str(var_index + 3)] = _extract_product_slug(product.get("url", ""))
        var_index += 4
    return variables