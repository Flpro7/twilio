import chromadb

from app.config import settings

_chroma_client = chromadb.PersistentClient(path=settings.chroma_persist_dir)


def get_collection():
    return _chroma_client.get_or_create_collection(
        name=settings.chroma_collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def upsert_documents(
    ids: list[str],
    texts: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict],
) -> None:
    collection = get_collection()
    collection.upsert(ids=ids, documents=texts, embeddings=embeddings, metadatas=metadatas)


def query(query_embedding: list[float], n_results: int = 4) -> list[str]:
    """Devuelve solo el texto de los documentos (uso actual en chain.py)."""
    results = query_with_metadata(query_embedding, n_results=n_results)
    return [item["document"] for item in results]


def query_with_metadata(query_embedding: list[float], n_results: int = 4) -> list[dict]:
    """Devuelve documentos junto con su metadata (name, url, image_url, type)
    y la distancia coseno a la query (mas bajo = mas relevante).

    El campo distance no se usa activamente hoy para filtrar (se probo un
    umbral en get_product_matches y resulto demasiado estricto, bloqueaba
    carousels validos -- ver historial). Queda disponible por si se retoma
    esa idea mas adelante con un enfoque mejor calibrado.
    """
    collection = get_collection()
    if collection.count() == 0:
        return []
    result = collection.query(query_embeddings=[query_embedding], n_results=n_results)
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    return [
        {"document": doc, "metadata": meta or {}, "distance": dist}
        for doc, meta, dist in zip(documents, metadatas, distances)
    ]