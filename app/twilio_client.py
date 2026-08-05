from twilio.request_validator import RequestValidator
from twilio.rest import Client

from app.config import settings

client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
_validator = RequestValidator(settings.twilio_auth_token)


def is_valid_twilio_request(url: str, form_params: dict, signature: str) -> bool:
    return _validator.validate(url, form_params, signature)


def send_whatsapp_message(to: str, body: str) -> str:
    """Envia un mensaje de WhatsApp de sesion libre (fuera del webhook). Devuelve el SID."""
    message = client.messages.create(from_=settings.twilio_whatsapp_number, to=to, body=body)
    return message.sid


def send_vcard(to: str, vcard_url: str, caption: str = "") -> str:
    """Envia un contacto (vCard) por WhatsApp. WhatsApp reconoce un archivo
    .vcf igual que reconoce una imagen -- via el mismo parametro media_url,
    no hace falta ningun tipo de mensaje especial ni aprobacion de WhatsApp
    (es una respuesta dentro de la ventana de 24hs de la conversacion)."""
    message = client.messages.create(
        from_=settings.twilio_whatsapp_number,
        to=to,
        body=caption,
        media_url=[vcard_url],
    )
    return message.sid