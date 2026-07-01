import logging

from fastapi import FastAPI, Request, Response
from twilio.twiml.messaging_response import MessagingResponse

from app.config import settings
from app.rag.chain import answer_question
from app.twilio_client import is_valid_twilio_request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gandys-bot")

app = FastAPI(title="Gandy's WhatsApp Bot")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request) -> Response:
    form = await request.form()
    form_dict = dict(form)

    if settings.validate_twilio_signature:
        signature = request.headers.get("X-Twilio-Signature", "")
        request_url = str(request.url)
        if not is_valid_twilio_request(request_url, form_dict, signature):
            logger.warning("Firma de Twilio invalida para %s", request_url)
            return Response(status_code=403)

    incoming_message = form_dict.get("Body", "").strip()
    sender = form_dict.get("From", "desconocido")
    logger.info("Mensaje de %s: %s", sender, incoming_message)

    reply_text = answer_question(incoming_message) if incoming_message else (
        "Hola! Soy el asistente de Gandy's. Contame en que te puedo ayudar."
    )

    twiml = MessagingResponse()
    twiml.message(reply_text)
    return Response(content=str(twiml), media_type="application/xml")
