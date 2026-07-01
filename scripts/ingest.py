"""Pipeline de ingesta para el RAG: scrapea productos + carga FAQs, genera
embeddings con Azure OpenAI y los guarda en ChromaDB.

Uso: python -m scripts.ingest
"""

import json
import logging
from pathlib import Path

from app.rag.embeddings import embed_texts
from app.rag.vector_store import upsert_documents
from worker.scraper import scrape_products

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gandys-bot.ingest")

FAQS_PATH = Path(__file__).parent / "faqs.json"
BATCH_SIZE = 50


def _product_to_document(product: dict) -> str:
    return (
        f"Producto: {product.get('name', '')}\n"
        f"Precio: {product.get('price', '')}\n"
        f"Descripcion: {product.get('description', '')}\n"
        f"URL: {product.get('url', '')}"
    )


def _faq_to_document(faq: dict) -> str:
    return f"Pregunta frecuente: {faq['question']}\nRespuesta: {faq['answer']}"


def _load_faqs() -> list[dict]:
    if not FAQS_PATH.exists():
        return []
    return json.loads(FAQS_PATH.read_text(encoding="utf-8"))


def _upsert_in_batches(ids: list[str], texts: list[str], metadatas: list[dict]) -> None:
    for start in range(0, len(texts), BATCH_SIZE):
        batch_ids = ids[start : start + BATCH_SIZE]
        batch_texts = texts[start : start + BATCH_SIZE]
        batch_metadatas = metadatas[start : start + BATCH_SIZE]
        batch_embeddings = embed_texts(batch_texts)
        upsert_documents(batch_ids, batch_texts, batch_embeddings, batch_metadatas)
        logger.info("Indexados %d documentos", start + len(batch_texts))


def run_ingest() -> None:
    ids: list[str] = []
    texts: list[str] = []
    metadatas: list[dict] = []

    products = scrape_products()
    logger.info("Productos scrapeados: %d", len(products))
    for i, product in enumerate(products):
        ids.append(f"product-{i}-{product.get('url', i)}")
        texts.append(_product_to_document(product))
        metadatas.append({"type": "product", "url": product.get("url", "")})

    faqs = _load_faqs()
    logger.info("FAQs cargadas: %d", len(faqs))
    for i, faq in enumerate(faqs):
        ids.append(f"faq-{i}")
        texts.append(_faq_to_document(faq))
        metadatas.append({"type": "faq"})

    if not texts:
        logger.warning("No hay documentos para indexar")
        return

    _upsert_in_batches(ids, texts, metadatas)
    logger.info("Ingest completo: %d documentos totales", len(texts))


if __name__ == "__main__":
    run_ingest()
