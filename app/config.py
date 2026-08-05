from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Twilio
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_whatsapp_number: str
    validate_twilio_signature: bool = True

    # WhatsApp Carousel
    # twilio_carousel_content_sid queda vacio hasta correr
    # scripts/send_carousel_demo.py (create + approve) y que WhatsApp
    # apruebe el template -- mientras tanto el bot cae siempre al flujo de
    # texto normal.
    twilio_carousel_content_sid: str = ""
    twilio_carousel_num_cards: int = 3

    # Numero de WhatsApp para el boton "Contactar" del carousel (wa.me/...).
    # IMPORTANTE: formato SIN "+" y SIN el prefijo "whatsapp:" -- son solo
    # digitos con codigo de pais, ej. Paraguay: 595984294691. Es distinto
    # al formato de TWILIO_WHATSAPP_NUMBER de arriba. Es una variable del
    # template (no esta grabada en el texto aprobado), asi que cambiar este
    # valor y reiniciar el servidor alcanza -- no hace falta crear un
    # template nuevo ni volver a pedir aprobacion.
    gandys_contact_whatsapp_number: str = "595984294691"

    # Azure OpenAI
    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_chat_deployment: str
    azure_openai_embedding_deployment: str

    # RAG
    chroma_persist_dir: str = "./data/chroma"
    chroma_collection_name: str = "gandys_knowledge"

    # Memoria de conversacion
    # Cuantos intercambios previos (usuario+asistente) se le mandan al LLM
    # como contexto de la charla. Subilo mas adelante si hace falta mas
    # memoria -- no requiere ningun otro cambio de codigo.
    conversation_history_max_exchanges: int = 3

    # Scraper
    scrape_base_url: str = "https://gandys.com.py"
    scrape_user_agent: str = "GandysBotScraper/1.0"


settings = Settings()