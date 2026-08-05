import logging

from fastapi import FastAPI, Request, Response
from twilio.twiml.messaging_response import MessagingResponse

from app.config import settings
from app.conversation_store import append_message, get_recent_history
from app.rag.chain import (
    answer_question,
    classify_intent,
    get_catalog_answer,
    get_product_matches,
)
from app.templates.carousel import products_to_content_variables, send_carousel
from app.twilio_client import is_valid_twilio_request, send_vcard

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gandys-bot")

app = FastAPI(title="Gandy's WhatsApp Bot")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


def _resolve_public_base(request: Request) -> str:
    """scheme://host sin path -- para construir URLs publicas absolutas
    (ej. el vCard del asesor) que Twilio necesita poder buscar desde afuera.
    Usa los mismos headers que _resolve_public_url, ver esa funcion."""
    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_proto and forwarded_host:
        return f"{forwarded_proto}://{forwarded_host}"
    return f"{request.url.scheme}://{request.url.netloc}"


def _resolve_public_url(request: Request) -> str:
    """
    Reconstruye la URL publica de la request para validar la firma de Twilio.

    Detras de un proxy/tunel (dev tunnels, ngrok, Railway, etc.) el header
    Host que ve FastAPI a veces no es el dominio publico real, mientras que
    Twilio firmo la request contra ese dominio publico. Los proxies
    estandar exponen ese dominio original en X-Forwarded-Proto /
    X-Forwarded-Host, asi que los usamos cuando estan presentes y caemos a
    request.url si no.
    """
    base = _resolve_public_base(request)
    url = f"{base}{request.url.path}"
    if request.url.query:
        url += f"?{request.url.query}"
    return url


@app.get("/static/asesor.vcf")
async def asesor_vcard() -> Response:
    """Vcard del asesor de Gandy's, generado dinamicamente a partir del
    mismo numero que ya usa el boton "Contactar" del carousel (ver
    settings.gandys_contact_whatsapp_number en app/config.py) -- asi hay un
    solo lugar donde cambiarlo cuando se reemplace por el asesor real.
    Se sirve como archivo publico porque Twilio/WhatsApp lo leen igual que
    a una imagen (via media_url) para mandarlo como contacto."""
    numero = settings.gandys_contact_whatsapp_number
    vcard = (
        "BEGIN:VCARD\r\n"
        "VERSION:3.0\r\n"
        "FN:Asesor Gandy's\r\n"
        f"TEL;TYPE=CELL:+{numero}\r\n"
        "END:VCARD\r\n"
    )
    return Response(content=vcard, media_type="text/vcard")


def _try_send_carousel(sender: str, incoming_message: str) -> bool:
    """Intenta mandar el carousel de productos via la API REST de Twilio.

    Asume que el llamador ya determino que la intencion es CATALOGO -- esta
    funcion no clasifica, solo busca productos y envia. Devuelve True si lo
    mando (para que el caller no mande TAMBIEN una respuesta de texto por
    TwiML). Si algo falla, o si no hay suficientes productos con imagen,
    devuelve False y el caller cae al flujo de texto normal.
    """
    if not settings.twilio_carousel_content_sid:
        # Sin ContentSid (todavia no aprobado por WhatsApp) ni vale la pena
        # buscar productos -- el envio va a fallar seguro.
        return False

    try:
        num_cards = settings.twilio_carousel_num_cards
        product_matches = get_product_matches(incoming_message, num_cards)

        if len(product_matches) < num_cards:
            logger.info(
                "Solo %d/%d productos con imagen encontrados para %r, cae a texto",
                len(product_matches), num_cards, incoming_message,
            )
            return False

        content_variables = products_to_content_variables("cliente", product_matches)
        send_carousel(sender, settings.twilio_carousel_content_sid, content_variables)
        logger.info(
            "Carousel enviado a %s con %d productos", sender, len(product_matches)
        )
        product_names = ", ".join(p.get("name", "") for p in product_matches)
        append_message(
            sender,
            "assistant",
            f"[Se envió un carousel con estos productos: {product_names}]",
        )
        return True
    except Exception:  # noqa: BLE001
        # Cubre tanto fallos de busqueda (embeddings/Chroma) como de envio
        # (API de Twilio) -- cualquiera de los dos debe caer al texto, no
        # tirar un 500 al webhook.
        logger.exception("Fallo el intento de carousel, caigo a respuesta de texto")
        return False


GREETING_REPLY = "Hola! Soy el asistente de Gandy's. Contame en que te puedo ayudar."


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request) -> Response:
    form = await request.form()
    form_dict = dict(form)

    if settings.validate_twilio_signature:
        signature = request.headers.get("X-Twilio-Signature", "")
        request_url = _resolve_public_url(request)
        if not is_valid_twilio_request(request_url, form_dict, signature):
            logger.warning("Firma de Twilio invalida para %s", request_url)
            return Response(status_code=403)

    incoming_message = form_dict.get("Body", "").strip()
    sender = form_dict.get("From", "desconocido")
    logger.info("Mensaje de %s: %s", sender, incoming_message)

    twiml = MessagingResponse()

    if not incoming_message:
        twiml.message(GREETING_REPLY)
        return Response(content=str(twiml), media_type="application/xml")

    # Se lee el historial de ANTES de este mensaje -- tiene que ser antes de
    # agregar el mensaje actual, si no aparece duplicado (una vez como
    # historial, otra vez como la pregunta puntual de este turno).
    history = get_recent_history(sender, settings.conversation_history_max_exchanges)
    last_assistant_message = next(
        (turn["content"] for turn in reversed(history) if turn["role"] == "assistant"),
        None,
    )
    append_message(sender, "user", incoming_message)

    intent = classify_intent(incoming_message, last_assistant_message)
    logger.info("Intencion clasificada para %r: %s", incoming_message, intent)

    if intent == "SALUDO":
        # Un saludo simple no tiene contenido real que buscar -- si lo
        # mandamos a embeddings, el "match mas cercano" puede ser
        # cualquier cosa random del catalogo (paso real: "buenas" termino
        # hablando de un producto de unas sin ninguna relacion).
        append_message(sender, "assistant", GREETING_REPLY)
        twiml.message(GREETING_REPLY)
        return Response(content=str(twiml), media_type="application/xml")

    if intent == "ASESOR":
        try:
            vcard_url = f"{_resolve_public_base(request)}/static/asesor.vcf"
            send_vcard(sender, vcard_url)
            logger.info("Contacto de asesor enviado a %s", sender)
            append_message(sender, "assistant", "[Se envió el contacto de un asesor]")
        except Exception:  # noqa: BLE001
            logger.exception("Fallo el envio del contacto de asesor")
            fallback_text = (
                "Tuvimos un problema para compartirte el contacto. Podés "
                "escribir directo a gandys.com.py mientras lo solucionamos."
            )
            append_message(sender, "assistant", fallback_text)
            twiml.message(fallback_text)
        return Response(content=str(twiml), media_type="application/xml")

    carousel_sent = intent == "CATALOGO" and _try_send_carousel(sender, incoming_message)

    if not carousel_sent:
        if intent == "CATALOGO":
            # No alcanzo para el carousel (menos de 3 productos con
            # imagen), pero sigue siendo un pedido de ver opciones -- una
            # busqueda mas amplia y filtrada a solo productos da una
            # respuesta mas representativa que el answer_question generico.
            reply_text = get_catalog_answer(incoming_message, history=history)
        else:
            reply_text = answer_question(incoming_message, history=history)
        append_message(sender, "assistant", reply_text)
        twiml.message(reply_text)

    # Si el carousel se mando, devolvemos TwiML vacio: el carousel ya salio
    # por la API REST, y una respuesta de texto aca duplicaria el mensaje.
    return Response(content=str(twiml), media_type="application/xml")