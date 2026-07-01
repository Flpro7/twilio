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
