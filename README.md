# Gandy's Bot

Bot de WhatsApp para gandys.com.py: responde preguntas frecuentes e informacion
de productos usando RAG (ChromaDB + Azure OpenAI) sobre un catalogo scrapeado
periodicamente. Expone un webhook para Twilio y sabe enviar templates de tipo
Carousel con productos.

## Arquitectura

- `app/main.py` — servicio FastAPI que recibe el webhook de Twilio (WhatsApp).
- `app/rag/` — embeddings, vector store (ChromaDB) y cadena de respuesta (RAG).
- `app/llm/azure_openai.py` — cliente de Azure OpenAI (chat + embeddings).
- `app/templates/carousel.py` — creacion/envio de templates WhatsApp Carousel.
- `worker/scraper.py` — scraping del catalogo de gandys.com.py.
- `worker/run_worker.py` — proceso separado que re-scrapea e indexa cada N horas.
- `scripts/ingest.py` — pipeline scrape -> embed -> guardar en ChromaDB.

## Quickstart

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
copy .env.example .env      # completar credenciales reales
python -m scripts.ingest    # primera carga del catalogo + FAQs
uvicorn app.main:app --reload
```

En otra terminal, exponer el puerto 8000 con ngrok y pegar la URL en la consola
de Twilio (Sandbox o numero de WhatsApp) en "When a message comes in":
`https://<subdominio>.ngrok-free.app/webhook/whatsapp`.

Ver la guia completa paso a paso en la conversacion/documentacion del proyecto.

## Tests

```bash
pytest
```
