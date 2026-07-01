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
    collection = get_collection()
    if collection.count() == 0:
        return []
    result = collection.query(query_embeddings=[query_embedding], n_results=n_results)
    documents = result.get("documents") or [[]]
    return documents[0]
