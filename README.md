# Gandy's WhatsApp Bot

WhatsApp assistant for [gandys.com.py](https://gandys.com.py) (B2B sale and rental of logistics equipment: racks, forklifts, stackers, cleaning machines, pallets, etc.). It answers customer questions using RAG over the site's real catalog and loaded FAQs, and can show a product carousel with images right inside the WhatsApp chat.

## How it works

1. A customer writes on WhatsApp → Twilio sends a `POST` to the webhook (`/webhook/whatsapp`).
2. The request signature (`X-Twilio-Signature`) is validated to confirm it actually came from Twilio.
3. The message is embedded and searched against ChromaDB (products scraped from the site + FAQs).
4. If there are **3 or more products with an image** that match the query well, a WhatsApp **carousel** is sent (photo, price or "consult an advisor", "View product" button) via Twilio's Content API.
5. Otherwise, a text reply is built with Azure OpenAI (GPT) using those documents as context, and returned as TwiML.
6. If there's no relevant context, the bot says it doesn't have that info yet and offers to hand off to a human advisor.

## Stack

- **FastAPI** + **uvicorn** — webhook server
- **Twilio** — WhatsApp channel (inbound/outbound messages, Content API for the carousel)
- **Azure OpenAI** — chat completion (`gpt-5.4-mini` or whichever deployment you configure) + embeddings (`text-embedding-3-small`)
- **ChromaDB** — local vector store, persisted to disk
- **httpx + BeautifulSoup4 + lxml** — scraping of static pages
- **Playwright** — scraping of the category search pages, which are JS-rendered
- **APScheduler** — worker that re-scrapes and re-indexes the catalog periodically
- **pytest** — tests

## Project structure

```
app/
  main.py              FastAPI app + webhook endpoint
  config.py            Settings (pydantic-settings, reads .env)
  twilio_client.py      Twilio REST client + signature validation
  llm/
    azure_openai.py     Chat completion wrapper
  rag/
    chain.py             answer_question() and get_product_matches()
    embeddings.py         embed_text() / embed_texts()
    vector_store.py       ChromaDB wrapper (upsert, query, query_with_metadata)
  templates/
    carousel.py           WhatsApp Carousel creation/sending via Content API

worker/
  scraper.py             Catalog scraper (fast mode and full mode)
  run_worker.py           Process that re-scrapes + re-indexes every N hours

scripts/
  ingest.py               Pipeline: scrape -> embed -> store in Chroma
  send_carousel_demo.py    CLI to create/approve/check status/send the carousel template
  faqs.json                Frequently asked questions, indexed alongside products

tests/
  test_webhook.py          Webhook endpoint tests

data/chroma/               Persisted vector store (not versioned, see .gitignore)
```

## Prerequisites

- Python 3.11+
- A **Twilio** account with WhatsApp enabled (sandbox for testing, or a production WhatsApp Sender)
- An **Azure OpenAI** resource with two deployments: one for chat (e.g. `gpt-5.4-mini`) and one for embeddings (e.g. `text-embedding-3-small`)
- For local development: some way to expose your `localhost` to the internet (dev tunnels, ngrok, etc.), since Twilio needs a public URL to send webhooks to

## Installation

```bash
git clone <this-repository>
cd gandys-bot

python -m venv .venv
# Windows:
.venv\Scripts\Activate.ps1
# Linux/Mac:
source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium   # browser binaries, required for full catalog scraping
```

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

### Environment variables

| Variable                            | Description                                                                                                                                |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `TWILIO_ACCOUNT_SID`                | Your Twilio account SID                                                                                                                    |
| `TWILIO_AUTH_TOKEN`                 | Twilio Auth Token (never commit this to the repo)                                                                                          |
| `TWILIO_WHATSAPP_NUMBER`            | Enabled WhatsApp number, `whatsapp:+E164` format                                                                                           |
| `VALIDATE_TWILIO_SIGNATURE`         | Always `true` in production. Only set to `false` to test the endpoint locally without a valid signature                                    |
| `TWILIO_CAROUSEL_CONTENT_SID`       | `ContentSid` of the carousel template already **approved** by WhatsApp. Leave empty until you have one — the bot always falls back to text |
| `TWILIO_CAROUSEL_NUM_CARDS`         | Number of cards in the template (must match the value used when it was created)                                                            |
| `AZURE_OPENAI_ENDPOINT`             | Your Azure OpenAI resource URL                                                                                                             |
| `AZURE_OPENAI_API_KEY`              | API key for the resource                                                                                                                   |
| `AZURE_OPENAI_API_VERSION`          | API version (e.g. `2025-01-01-preview`)                                                                                                    |
| `AZURE_OPENAI_CHAT_DEPLOYMENT`      | Chat deployment name                                                                                                                       |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | Embedding deployment name                                                                                                                  |
| `CHROMA_PERSIST_DIR`                | Local folder where the vector store persists                                                                                               |
| `CHROMA_COLLECTION_NAME`            | Name of the Chroma collection                                                                                                              |
| `SCRAPE_BASE_URL`                   | Base domain to scrape                                                                                                                      |
| `SCRAPE_USER_AGENT`                 | User-Agent used by the scraper                                                                                                             |

## Loading the catalog (first time, and whenever it changes)

```bash
python -m scripts.ingest
```

This scrapes the full catalog (uses Playwright to walk the category search pages, which are JS-rendered, and `httpx` for each product's page), loads `scripts/faqs.json`, generates embeddings, and uploads everything to ChromaDB.

> The site doesn't publish prices (it's quote-based B2B sale/rental), so the price field is empty for almost every product — that's expected behavior, not a bug.

## Running the server

```bash
uvicorn app.main:app --reload
```

To test the webhook locally, expose the port (dev tunnels, ngrok, etc.) and set that public URL + `/webhook/whatsapp` as the **"Webhook URL for incoming messages"** in the Twilio console (WhatsApp Sender → Messaging Endpoint Configuration), with method `HTTP Post`.

> If you're behind a proxy/tunnel that rewrites the `Host` header (like Microsoft dev tunnels), signature validation is already set up to reconstruct the real URL from `X-Forwarded-Proto` / `X-Forwarded-Host` — no changes needed.

## Setting up the WhatsApp carousel (optional, one-time)

The carousel needs a template pre-approved by WhatsApp. It's created and approved once:

```bash
python -m scripts.send_carousel_demo create
# returns a ContentSid, e.g.: HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

python -m scripts.send_carousel_demo approve HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

python -m scripts.send_carousel_demo status HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# status can take anywhere from minutes to more than a day to go from "pending" to "approved"
```

Once `status` is `approved`, put that `ContentSid` in `TWILIO_CAROUSEL_CONTENT_SID` in your `.env` and restart the server. If it comes back `rejected`, the response's `rejection_reason` field tells you exactly why.

## Automatic re-indexing worker

To keep the catalog up to date without running `ingest` by hand:

```bash
python -m worker.run_worker
```

Re-scrapes and re-indexes every 6 hours (configurable via `INGEST_INTERVAL_HOURS` in `worker/run_worker.py`). Meant to run as a separate, persistent process (systemd, a service on your hosting, etc.), not inside the same process as the web server.

## Tests

```bash
pytest
```

## Notes and known limitations

- **The scraper has two modes**: `scrape_products()` (fast, ~30 sample products, no Playwright) and `scrape_products_full()` (full catalog, ~135 products, requires Playwright). `ingest.py` uses the full mode.
- **The carousel requires exactly `TWILIO_CAROUSEL_NUM_CARDS` products with an image** to trigger; if the search finds fewer, it automatically falls back to the normal text reply.
- **An approved carousel template is locked to a fixed number of cards.** If you change `TWILIO_CAROUSEL_NUM_CARDS`, you need to create and re-approve a new template — you can't edit the card count of one that's already approved.
- **`VALIDATE_TWILIO_SIGNATURE=false`** is only for one-off local debugging. It must never be `false` in production: without that validation, anyone who discovers the webhook URL can send fake messages as if they came from Twilio.
