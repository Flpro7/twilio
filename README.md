# Gandy's WhatsApp Bot

WhatsApp assistant for [gandys.com.py](https://gandys.com.py) (B2B sale and rental of logistics equipment: racks, forklifts, stackers, cleaning machines, pallets, etc.). It answers customer questions using RAG over the site's real catalog and loaded FAQs, can show a product carousel with images right inside the WhatsApp chat, remembers recent conversation context, and can hand a customer off to a human advisor by sharing a contact card.

## How it works

1. A customer writes on WhatsApp → Twilio sends a `POST` to the webhook (`/webhook/whatsapp`).
2. The request signature (`X-Twilio-Signature`) is validated to confirm it actually came from Twilio.
3. An LLM classifies the message into one of four intents:
   - **SALUDO** (greeting / small talk) → replies with a canned greeting, no search performed. This exists because a bare "hi" has no real semantic content, so a naive embedding search for it can surface an unrelated product.
   - **CATALOGO** (wants to browse several options) → tries to send a WhatsApp **carousel** (photo, description, "Contactar" and "Ver en gandys" buttons) if 3+ relevant products with an image are found. If not enough are found, falls back to a broader, product-only-filtered text search instead of a plain 4-chunk lookup, so a browsing question doesn't collapse into "I only have this one."
   - **ASESOR** (wants a human) → sends a WhatsApp contact card (vCard) for a Gandy's advisor, generated on the fly from an environment variable. Also triggers if the customer briefly confirms a previous offer to connect them with an advisor (e.g. replying "yes" right after the bot offered it) — the classifier is given the assistant's last message as context for this.
   - **PREGUNTA** (a specific question) → a text reply is built with Azure OpenAI (GPT) using retrieved catalog/FAQ context plus recent conversation history, and returned as TwiML.
4. If there's no relevant context for a PREGUNTA, the bot says it doesn't have that info yet and offers to hand off to an advisor (which the customer can accept in their next message).
5. Every turn (both sides of the conversation) is saved to a small local conversation history store, so follow-up questions like "what's that first one for?" can be resolved against what was just discussed.

## Stack

- **FastAPI** + **uvicorn** — webhook server
- **Twilio** — WhatsApp channel (inbound/outbound messages, Content API for the carousel, vCard media for advisor handoff)
- **Azure OpenAI** — chat completion (`gpt-5.4-mini` or whichever deployment you configure), embeddings (`text-embedding-3-small`), and a small/cheap call for intent classification
- **ChromaDB** — local vector store, persisted to disk
- **SQLite** (Python stdlib, no extra dependency) — short conversation history per sender, persisted alongside the Chroma data
- **httpx + BeautifulSoup4 + lxml** — scraping of static pages
- **Playwright** — scraping of the category search pages, which are JS-rendered
- **APScheduler** — worker that re-scrapes and re-indexes the catalog periodically
- **Railway** — hosting for the webhook service (see [Deploying to Railway](#deploying-to-railway))
- **pytest** — tests

## Project structure

```
app/
  main.py               FastAPI app, webhook endpoint, /static/asesor.vcf route
  config.py             Settings (pydantic-settings, reads .env)
  twilio_client.py       Twilio REST client, signature validation, send_vcard()
  conversation_store.py  SQLite-backed conversation history per sender
  llm/
    azure_openai.py      Chat completion + intent classification wrappers
  rag/
    chain.py              answer_question(), classify_intent(), get_catalog_answer(),
                           get_product_matches()
    embeddings.py          embed_text() / embed_texts()
    vector_store.py        ChromaDB wrapper (upsert, query, query_with_metadata)
  templates/
    carousel.py            WhatsApp Carousel creation/sending via Content API

worker/
  scraper.py             Catalog scraper (fast mode and full mode)
  run_worker.py           Process that re-scrapes + re-indexes every N hours

scripts/
  ingest.py               Pipeline: scrape -> embed -> store in Chroma
  send_carousel_demo.py    CLI to create/approve/check status/send the carousel template
  faqs.json                Frequently asked questions, indexed alongside products

tests/
  test_webhook.py          Webhook endpoint tests

data/chroma/               Persisted vector store + conversation_history.sqlite3
                           (not versioned, see .gitignore)

Procfile                  Tells Railway (or any Heroku-style platform) how to start the app
```

## Prerequisites

- Python 3.11+
- A **Twilio** account with WhatsApp enabled (sandbox for testing, or a production WhatsApp Sender)
- An **Azure OpenAI** resource with two deployments: one for chat (e.g. `gpt-5.4-mini`) and one for embeddings (e.g. `text-embedding-3-small`)
- For local development: some way to expose your `localhost` to the internet (dev tunnels, ngrok, etc.), since Twilio needs a public URL to send webhooks to
- For deployment: a [Railway](https://railway.app) account and the [Railway CLI](https://docs.railway.com/cli), if you want the webhook always-on with a fixed URL (see [Deploying to Railway](#deploying-to-railway))

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

| Variable | Description |
|---|---|
| `TWILIO_ACCOUNT_SID` | Your Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token (never commit this to the repo) |
| `TWILIO_WHATSAPP_NUMBER` | Enabled WhatsApp number, `whatsapp:+E164` format |
| `VALIDATE_TWILIO_SIGNATURE` | Always `true` in production. Only set to `false` to test the endpoint locally without a valid signature |
| `TWILIO_CAROUSEL_CONTENT_SID` | `ContentSid` of the carousel template already **approved** by WhatsApp. Leave empty until you have one — the bot always falls back to text |
| `TWILIO_CAROUSEL_NUM_CARDS` | Number of cards in the template (must match the value used when it was created) |
| `GANDYS_CONTACT_WHATSAPP_NUMBER` | WhatsApp contact number, digits only with country code, **no `+` and no `whatsapp:` prefix** (e.g. `595981234567`). Used both for the carousel's "Contactar" button (`wa.me/<number>`) and for the advisor vCard sent on handoff. This is a template *variable*, not baked into any approved template text, so updating it and restarting is enough — no re-approval needed |
| `CONVERSATION_HISTORY_MAX_EXCHANGES` | How many previous user+assistant exchanges get sent to the LLM as conversation context. Default `3`; safe to raise later without any other code change |
| `AZURE_OPENAI_ENDPOINT` | Your Azure OpenAI resource URL |
| `AZURE_OPENAI_API_KEY` | API key for the resource |
| `AZURE_OPENAI_API_VERSION` | API version (e.g. `2025-01-01-preview`) |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | Chat deployment name |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | Embedding deployment name |
| `CHROMA_PERSIST_DIR` | Local folder where the vector store (and conversation history DB) persists |
| `CHROMA_COLLECTION_NAME` | Name of the Chroma collection |
| `SCRAPE_BASE_URL` | Base domain to scrape |
| `SCRAPE_USER_AGENT` | User-Agent used by the scraper |

## Loading the catalog (first time, and whenever it changes)

```bash
python -m scripts.ingest
```

This scrapes the full catalog (uses Playwright to walk the category search pages, which are JS-rendered, and `httpx` for each product's page), loads `scripts/faqs.json`, generates embeddings, and uploads everything to ChromaDB.

> The site doesn't publish prices (it's quote-based B2B sale/rental), so the price field is empty for almost every product — that's expected behavior, not a bug. The carousel card shows the product's description instead of a price.

## Running the server

```bash
uvicorn app.main:app --reload
```

To test the webhook locally, expose the port (dev tunnels, ngrok, etc.) and set that public URL + `/webhook/whatsapp` as the **"Webhook URL for incoming messages"** in the Twilio console (WhatsApp Sender → Messaging Endpoint Configuration), with method `HTTP Post`.

> If you're behind a proxy/tunnel that rewrites the `Host` header (like Microsoft dev tunnels, or Railway), signature validation is already set up to reconstruct the real URL from `X-Forwarded-Proto` / `X-Forwarded-Host` — no changes needed.

## Setting up the WhatsApp carousel (optional, one-time)

The carousel needs a template pre-approved by WhatsApp. Each card shows the product name, its description (no price), an image, and two buttons: **"Contactar"** (opens a WhatsApp chat with `GANDYS_CONTACT_WHATSAPP_NUMBER` via a `wa.me` link) and **"Ver en gandys"** (links to the product's page on the site).

The template is created and approved once:

```bash
python -m scripts.send_carousel_demo create
# returns a ContentSid, e.g.: HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

python -m scripts.send_carousel_demo approve HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

python -m scripts.send_carousel_demo status HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# status can take anywhere from minutes to more than a day to go from "pending" to "approved"
```

Once `status` is `approved`, put that `ContentSid` in `TWILIO_CAROUSEL_CONTENT_SID` in your `.env` and restart the server. If it comes back `rejected`, the response's `rejection_reason` field tells you exactly why.

> Any change to the template's fixed text or button layout requires creating and approving a **new** template — you can't edit an approved one in place. Changing `GANDYS_CONTACT_WHATSAPP_NUMBER` does **not** require this, since it's a variable value filled in at send time, not part of the approved text.

## Human advisor handoff

When the intent classifier detects **ASESOR** (an explicit request for a human, or a short confirmation like "yes" right after the bot offered to connect them), the bot sends a WhatsApp contact card instead of a text reply. This uses the same mechanism WhatsApp uses for sharing a contact from your phone book: a `.vcf` file passed as `media_url`, no special message type or template approval needed since it's a reply within the active 24-hour session.

The vCard is generated on the fly by `GET /static/asesor.vcf`, using `GANDYS_CONTACT_WHATSAPP_NUMBER` — the same variable used for the carousel's "Contactar" button. Update that one variable when you have the real advisor's number; nothing else needs to change.

## Conversation memory

Each sender's recent turns (both what the customer said and what the bot replied) are stored in a small SQLite database (`app/conversation_store.py`), kept inside the same directory as the Chroma data (`CHROMA_PERSIST_DIR`) so it survives restarts without needing a second persistent volume. `CONVERSATION_HISTORY_MAX_EXCHANGES` controls how many recent exchanges get replayed to the LLM as context for both the reply itself and the intent classification of the next message. When the carousel is sent, a short text summary of which products were shown is stored instead of the raw carousel payload, so a follow-up question about "the second one" has something to resolve against.

## Deploying to Railway

Only the **webhook** (the FastAPI service) is deployed to Railway; the scraping worker (which needs Playwright) is kept running on a local machine, since Playwright's browser download has a spotty track record on Railway's default builder. Deploying just the webhook needs no Playwright at all.

1. **Push this repo to GitHub**, including the `Procfile` at the repo root (`web: uvicorn app.main:app --host 0.0.0.0 --port $PORT`) — Railway auto-detects it as the start command.
2. **Create a Railway project** from that GitHub repo (New Project → Deploy from GitHub repo).
3. **Set environment variables**: in the service's *Variables* tab, use the *RAW Editor* to paste the same key/value pairs as your local `.env` (with real values — `.env` itself is never pushed to GitHub).
4. **Add a Volume**: *Settings → Volumes → Add Volume*, mount path exactly `/app/data/chroma` (this has to match `CHROMA_PERSIST_DIR`, resolved against Railway's `/app` working directory). Without this, both the Chroma data and the conversation history SQLite file get wiped on every redeploy.
5. **Generate a public domain**: *Settings → Networking → Generate Domain*. This URL is fixed and doesn't change between deploys — it's what you'll put in Twilio's webhook config.
6. **Upload your locally-ingested Chroma data** to the volume (Railway starts with an empty volume — nothing re-scrapes on Railway itself):
   ```bash
   railway login
   railway link
   railway volume files upload ./data/chroma/chroma.sqlite3 /chroma.sqlite3 --overwrite
   railway volume files upload ./data/chroma/<your-uuid-folder> /<your-uuid-folder> --overwrite
   ```
   Upload each top-level item from your local `data/chroma/` **directly to the volume root** (`/...`), not into a subfolder — uploading the whole `data/chroma` folder as one unit nests it one level too deep and the app won't find it. `railway volume files list /` lets you check what actually ended up where.
   > This command needs an SSH key registered with your Railway account. If you get "No SSH keys found", run `ssh-keygen -t ed25519` once, then `railway ssh keys add`, then retry the upload.
7. **Restart the service** after the upload so it picks up the data on a clean boot instead of whatever empty Chroma instance it may have initialized in memory on first start.
8. **Point Twilio at the new URL**: WhatsApp Sender → Messaging Endpoint Configuration → set the webhook to `https://<your-domain>.up.railway.app/webhook/whatsapp`, method `HTTP Post`.

Whenever you re-run `scripts.ingest` locally to refresh the catalog, repeat step 6 (and step 7) to push the updated data to the deployed bot — there's no automatic sync between your local ingest and the Railway volume.

## Automatic re-indexing worker

To keep the *local* catalog up to date without running `ingest` by hand:

```bash
python -m worker.run_worker
```

Re-scrapes and re-indexes every 6 hours (configurable via `INGEST_INTERVAL_HOURS` in `worker/run_worker.py`). Meant to run as a separate, persistent local process — see [Deploying to Railway](#deploying-to-railway) for why this isn't deployed alongside the webhook, and for how to push its output to the deployed bot.

## Tests

```bash
pytest
```

## Notes and known limitations

- **The scraper has two modes**: `scrape_products()` (fast, ~30 sample products, no Playwright) and `scrape_products_full()` (full catalog, ~135 products, requires Playwright). `ingest.py` uses the full mode.
- **The carousel requires exactly `TWILIO_CAROUSEL_NUM_CARDS` products with an image** to trigger; if the search finds fewer, it falls back to a broader product-only text search (`get_catalog_answer`), and only to the fully generic text search (`answer_question`) for non-browsing questions.
- **An approved carousel template is locked to a fixed number of cards and fixed literal text.** Structural changes (card count, wording, button layout) need a new template and a new approval round.
- **Intent classification is an LLM call, not a keyword list** — it's deliberately robust to typos and rephrasing, but it is a small extra request (and a small extra cost/latency) on every incoming message.
- **Conversation history is per-sender and unbounded in storage** (every turn is kept in SQLite), even though only the last `CONVERSATION_HISTORY_MAX_EXCHANGES` are replayed to the LLM. There's no cleanup/expiry job yet.
- **The Railway deployment only runs the webhook.** The catalog on Railway only updates when you manually re-upload `data/chroma` after running `ingest` locally — see [Deploying to Railway](#deploying-to-railway).
- **`VALIDATE_TWILIO_SIGNATURE=false`** is only for one-off local debugging. It must never be `false` in production: without that validation, anyone who discovers the webhook URL can send fake messages as if they came from Twilio.
