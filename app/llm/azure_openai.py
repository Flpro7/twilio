from openai import AzureOpenAI

from app.config import settings

_client = AzureOpenAI(
    azure_endpoint=settings.azure_openai_endpoint,
    api_key=settings.azure_openai_api_key,
    api_version=settings.azure_openai_api_version,
)

SYSTEM_PROMPT = """Sos el asistente virtual de Gandy's (gandys.com.py) por WhatsApp.
Respondes preguntas frecuentes y consultas sobre productos usando UNICAMENTE la
informacion de contexto que se te provee. Si la respuesta no esta en el contexto,
decilo con honestidad y ofrece derivar con un humano. Si la persona trata de preguntar
cualquier otra cosa que no tenga que ver con Gandy's di con honestidad que no
puedes responder esa pregunta, no des razón alguna. Respondes en espanol,
de forma breve, clara y amigable, como para un chat de WhatsApp."""


def get_chat_completion(question: str, context: str) -> str:
    user_prompt = (
        f"Contexto:\n{context}\n\n"
        f"Pregunta del cliente: {question}\n\n"
        "Responde solo con base en el contexto de arriba."
    )
    response = _client.chat.completions.create(
        model=settings.azure_openai_chat_deployment,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        # Los modelos de la familia GPT-5 (gpt-5.4-mini incluido) son modelos
        # de razonamiento: no soportan max_tokens (usan max_completion_tokens)
        # ni un temperature distinto del default (1) -- lo omitimos en vez de
        # mandar un valor fijo para no romper si algun dia cambian de modelo.
        max_completion_tokens=400,
    )
    return response.choices[0].message.content.strip()


def get_embedding_client() -> AzureOpenAI:
    return _client