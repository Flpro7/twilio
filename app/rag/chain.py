from app.llm.azure_openai import get_chat_completion, get_intent_completion
from app.rag.embeddings import embed_text
from app.rag.vector_store import query, query_with_metadata

FALLBACK_ANSWER = (
    "Todavia no tengo esa informacion cargada. Un asesor de Gandy's te va a "
    "responder a la brevedad por este mismo chat."
)


def answer_question(question: str) -> str:
    question_embedding = embed_text(question)
    matched_chunks = query(question_embedding, n_results=4)

    if not matched_chunks:
        return FALLBACK_ANSWER

    context = "\n---\n".join(matched_chunks)
    return get_chat_completion(question=question, context=context)


def classify_intent(question: str) -> str:
    """Usa el LLM para decidir si conviene mandar un carousel de productos
    o responder con texto. A diferencia de buscar palabras clave a mano,
    esto entiende la intencion real del mensaje sin importar errores de
    tipeo ni formas de preguntar que no se anticiparon.

    Devuelve "CATALOGO" o "PREGUNTA". Ante cualquier falla (o una respuesta
    que no sea ninguna de las dos) devuelve "PREGUNTA" -- el fallback mas
    seguro, porque en el peor caso responde con texto en vez de mandar un
    carousel de mas que ignore la pregunta real del cliente.
    """
    try:
        raw = get_intent_completion(question)
    except Exception:  # noqa: BLE001
        return "PREGUNTA"

    return "CATALOGO" if "CATALOGO" in raw.strip().upper() else "PREGUNTA"


def get_product_matches(question: str, max_products: int) -> list[dict]:
    """Busca productos relevantes a la pregunta para armar un carousel.

    Devuelve hasta max_products dicts con la metadata de cada producto
    (name, price, image_url, url). Descarta:
    - matches que no sean de tipo "product" (ej. chunks de FAQ)
    - productos duplicados (mismo url)
    - productos sin image_url (una tarjeta sin foto no tiene sentido)

    Pedimos mas resultados de los necesarios (max_products * 3) porque parte
    de lo que devuelve el retrieval se va a descartar por los filtros de
    arriba.
    """
    question_embedding = embed_text(question)
    results = query_with_metadata(question_embedding, n_results=max_products * 3)

    products: list[dict] = []
    seen_urls: set[str] = set()
    for item in results:
        metadata = item["metadata"]
        if metadata.get("type") != "product":
            continue
        url = metadata.get("url", "")
        if not url or url in seen_urls:
            continue
        if not metadata.get("image_url"):
            continue
        seen_urls.add(url)
        products.append(metadata)
        if len(products) >= max_products:
            break

    return products