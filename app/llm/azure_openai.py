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
decilo con honestidad y ofrece derivar con un humano.

El contexto que recibis es apenas una MUESTRA de los productos que coincidieron con
la busqueda, NUNCA el catalogo completo de Gandy's (que tiene muchos mas productos).
Por eso NUNCA digas frases como "solo tenemos este producto" o "es el unico que
tenemos" -- eso no es cierto, simplemente es lo que matcheo esa busqueda puntual. Si
el contexto no cubre bien lo que se pregunto, decilo con honestidad y sugerí que
pregunten por una categoria mas especifica o que se los derive con un asesor.

Si la persona trata de preguntar cualquier otra cosa que no tenga que ver con Gandy's
di con honestidad que no puedes responder esa pregunta, no des razón alguna. Respondes
en espanol, de forma breve, clara y amigable, como para un chat de WhatsApp."""

INTENT_SYSTEM_PROMPT = """Sos un clasificador de intencion para un bot de WhatsApp de
Gandy's (venta y alquiler de equipamiento logistico: racks, montacargas, apiladoras,
pallets, maquinas de limpieza, etc.).

Dado el mensaje de un cliente, respondé con UNA SOLA PALABRA, sin explicaciones ni
puntuacion:

SALUDO -> el mensaje es un saludo o charla trivial sin contenido real sobre
productos (ej: "hola", "buenas", "como estas", "gracias", "chau"). NO es una
consulta sobre el catalogo, no hay que buscar productos para esto.

CATALOGO -> el cliente quiere ver varios productos disponibles o explorar opciones
en general (ej: "que productos tienen", "que montacargas hay", "mostrame las
opciones de racks", "mandame el catalogo").

PREGUNTA -> el cliente esta preguntando algo puntual sobre un producto especifico:
para que sirve, como funciona, caracteristicas, diferencias con otro, precio, o
cualquier otra consulta concreta. Tambien es PREGUNTA si el mensaje tiene errores
de tipeo pero la intencion de fondo es una consulta puntual, no un pedido de ver
varias opciones.

Respondé UNICAMENTE con la palabra SALUDO, CATALOGO o la palabra PREGUNTA."""


def get_chat_completion(
    question: str, context: str, history: list[dict] | None = None
) -> str:
    user_prompt = (
        f"Contexto:\n{context}\n\n"
        f"Pregunta del cliente: {question}\n\n"
        "Responde solo con base en el contexto de arriba."
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history or []:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_prompt})

    response = _client.chat.completions.create(
        model=settings.azure_openai_chat_deployment,
        messages=messages,
        # Los modelos de la familia GPT-5 (gpt-5.4-mini incluido) son modelos
        # de razonamiento: no soportan max_tokens (usan max_completion_tokens)
        # ni un temperature distinto del default (1) -- lo omitimos en vez de
        # mandar un valor fijo para no romper si algun dia cambian de modelo.
        max_completion_tokens=400,
    )
    return response.choices[0].message.content.strip()


def get_intent_completion(question: str) -> str:
    """Llamada corta y barata (max_completion_tokens=10) solo para clasificar
    si el mensaje es un saludo, un pedido de catalogo, o una pregunta puntual.
    Separada de get_chat_completion porque usa un system prompt distinto y no
    necesita contexto del RAG."""
    response = _client.chat.completions.create(
        model=settings.azure_openai_chat_deployment,
        messages=[
            {"role": "system", "content": INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        max_completion_tokens=10,
    )
    return response.choices[0].message.content.strip()


def get_embedding_client() -> AzureOpenAI:
    return _client