from app.llm.azure_openai import get_chat_completion, get_intent_completion
from app.rag.embeddings import embed_text
from app.rag.vector_store import query, query_with_metadata

FALLBACK_ANSWER = (
    "Todavia no tengo esa informacion cargada. Si querés, puedo proporcionarte el contacto de un asesor de Gandy's por este mismo chat."
)


def answer_question(question: str, history: list[dict] | None = None) -> str:
    question_embedding = embed_text(question)
    matched_chunks = query(question_embedding, n_results=4)

    if not matched_chunks:
        return FALLBACK_ANSWER

    context = "\n---\n".join(matched_chunks)
    return get_chat_completion(question=question, context=context, history=history)


def classify_intent(question: str) -> str:
    """Usa el LLM para decidir si el mensaje es un saludo, un pedido de
    catalogo, o una pregunta puntual. A diferencia de buscar palabras clave
    a mano, esto entiende la intencion real del mensaje sin importar
    errores de tipeo ni formas de preguntar que no se anticiparon.

    Devuelve "SALUDO", "CATALOGO" o "PREGUNTA". Ante cualquier falla (o una
    respuesta que no sea ninguna de las tres) devuelve "PREGUNTA" -- el
    fallback mas seguro, porque en el peor caso responde con texto en vez
    de mandar un carousel de mas o saltarse una consulta real.
    """
    try:
        raw = get_intent_completion(question)
    except Exception:  # noqa: BLE001
        return "PREGUNTA"

    normalized = raw.strip().upper()
    if "SALUDO" in normalized:
        return "SALUDO"
    if "CATALOGO" in normalized:
        return "CATALOGO"
    return "PREGUNTA"


def get_catalog_answer(
    question: str, history: list[dict] | None = None, max_results: int = 8
) -> str:
    """Respuesta de texto para preguntas de tipo CATALOGO cuando no se pudo
    mandar el carousel (ej. menos de 3 productos con imagen encontrados).

    A diferencia de answer_question() -- que pide solo 4 chunks sin filtrar,
    mezclando productos y FAQs -- esta busca mas resultados y los filtra a
    SOLO productos, deduplicados por url. Para preguntas amplias ("cuales
    son todos los racks que tienen") esto evita que la respuesta se quede
    con 1 sola coincidencia fuerte cuando en realidad hay varias opciones
    reales en el catalogo.
    """
    question_embedding = embed_text(question)
    results = query_with_metadata(question_embedding, n_results=max_results * 2)

    seen_urls: set[str] = set()
    product_docs: list[str] = []
    for item in results:
        metadata = item["metadata"]
        if metadata.get("type") != "product":
            continue
        url = metadata.get("url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        product_docs.append(item["document"])
        if len(product_docs) >= max_results:
            break

    if not product_docs:
        return FALLBACK_ANSWER

    context = "\n---\n".join(product_docs)
    return get_chat_completion(question=question, context=context, history=history)


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