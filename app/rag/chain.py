from app.llm.azure_openai import get_chat_completion
from app.rag.embeddings import embed_text
from app.rag.vector_store import query

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
