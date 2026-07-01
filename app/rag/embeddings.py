from app.config import settings
from app.llm.azure_openai import get_embedding_client

_client = get_embedding_client()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Convierte una lista de textos en sus vectores de embedding via Azure OpenAI."""
    response = _client.embeddings.create(
        model=settings.azure_openai_embedding_deployment,
        input=texts,
    )
    return [item.embedding for item in response.data]


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]
