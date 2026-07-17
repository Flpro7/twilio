import logging

from fastapi import FastAPI, Request, Response
from twilio.twiml.messaging_response import MessagingResponse

from app.config import settings
from app.rag.chain import answer_question, get_product_matches
from app.templates.carousel import products_to_content_variables, send_carousel
from app.twilio_client import is_valid_twilio_request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gandys-bot")

app = FastAPI(title="Gandy's WhatsApp Bot")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


def _resolve_public_url(request: Request) -> str:
    """
    Reconstruye la URL publica de la request para validar la firma de Twilio.

    Detras de un proxy/tunel (dev tunnels, ngrok, etc.) el header Host que
    ve FastAPI suele ser localhost, mientras que Twilio firmo la request
    contra el dominio publico real. Los proxies estandar exponen ese
    dominio original en X-Forwarded-Proto / X-Forwarded-Host, asi que los
    usamos cuando estan presentes y caemos a request.url si no.
    """
    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")

    if forwarded_proto and forwarded_host:
        url = f"{forwarded_proto}://{forwarded_host}{request.url.path}"
        if request.url.query:
            url += f"?{request.url.query}"
        return url

    return str(request.url)


def _try_send_carousel(sender: str, incoming_message: str) -> bool:
    """Intenta mandar el carousel de productos via la API REST de Twilio.

    Devuelve True si lo mando (para que el caller no mande TAMBIEN una
    respuesta de texto por TwiML). Si algo falla, si no hay suficientes
    productos con imagen para llenar el template, o si todavia no hay un
    ContentSid aprobado configurado, devuelve False y el caller cae al
    flujo de texto normal.
    """
    if not settings.twilio_carousel_content_sid:
        # Sin ContentSid (todavia no aprobado por WhatsApp) ni vale la pena
        # buscar productos -- el envio va a fallar seguro. Nos ahorramos la
        # llamada a Azure OpenAI en cada mensaje mientras se espera.
        return False

    try:
        num_cards = settings.twilio_carousel_num_cards
        product_matches = get_product_matches(incoming_message, num_cards)

        if len(product_matches) < num_cards:
            return False

        content_variables = products_to_content_variables("cliente", product_matches)
        send_carousel(sender, settings.twilio_carousel_content_sid, content_variables)
        logger.info(
            "Carousel enviado a %s con %d productos", sender, len(product_matches)
        )
        return True
    except Exception:  # noqa: BLE001
        # Cubre tanto fallos de busqueda (embeddings/Chroma) como de envio
        # (API de Twilio) -- cualquiera de los dos debe caer al texto, no
        # tirar un 500 al webhook.
        logger.exception("Fallo el intento de carousel, caigo a respuesta de texto")
        return False


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
        twiml.message("Hola! Soy el asistente de Gandy's. Contame en que te puedo ayudar.")
        return Response(content=str(twiml), media_type="application/xml")

    carousel_sent = _try_send_carousel(sender, incoming_message)

    if not carousel_sent:
        twiml.message(answer_question(incoming_message))

    # Si el carousel se mando, devolvemos TwiML vacio: el carousel ya salio
    # por la API REST, y una respuesta de texto aca duplicaria el mensaje.
    return Response(content=str(twiml), media_type="application/xml")
