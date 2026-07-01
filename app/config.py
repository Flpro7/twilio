from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Twilio
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_whatsapp_number: str
    validate_twilio_signature: bool = True

    # Azure OpenAI
    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_chat_deployment: str
    azure_openai_embedding_deployment: str

    # RAG
    chroma_persist_dir: str = "./data/chroma"
    chroma_collection_name: str = "gandys_knowledge"

    # Scraper
    scrape_base_url: str = "https://gandys.com.py"
    scrape_user_agent: str = "GandysBotScraper/1.0"


settings = Settings()
