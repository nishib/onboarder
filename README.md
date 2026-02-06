# OnboardAI

**AI-powered employee onboarding** — a single place for new hires to ask questions, see sync status from internal tools, and stay updated on competitor intelligence. Built as a hackathon demo with **Composio**, **You.com**, and **Render**.

---

## Business use case

New employees at a company need fast, accurate answers about product, team, and strategy without hunting through Notion, GitHub, and Slack. They also benefit from curated competitor intelligence so they can speak to the market from day one.

**OnboardAI** gives them:

- **Q&A over company knowledge** — Ask in natural language; get answers grounded in internal docs (Notion pages, GitHub READMEs, Slack context) with citations.
- **Sync visibility** — See when internal sources were last synced and trigger a refresh (Composio: Notion, GitHub, Slack).
- **Competitor intel feed** — A feed of research on competitors (e.g. Intercom, Zendesk, Gorgias) powered by You.com, cached and surfaced in both the feed and in RAG answers.
- **Usage dashboard** — For ops: view Render workspaces, services, and bandwidth (Phase 5) so the platform can be monitored without manual dashboard checks.

**Velora** is a **fictional company** used in this demo. All data (Notion pages, GitHub repos, Slack messages, competitor names) is **synthetic**. The app simulates what a real company could do: connect real Composio/You.com/Render accounts and point them at real Notion/GitHub/Slack and real competitors; the architecture and flows stay the same.

---

## Tech stack and why

| Layer | Choice | Why |
|-------|--------|-----|
| **API** | FastAPI (Python) | Async-ready, OpenAPI, simple dependency injection for DB and env. |
| **Frontend** | React + Vite | Fast dev loop, proxy to API; single-page app with clear sections for chat, sync, intel, usage. |
| **Database** | PostgreSQL + pgvector | Relational data plus vector similarity (cosine) for RAG; one store for knowledge, intel, and sync state. |
| **Embeddings & LLM** | Google Gemini | Single provider for 768-d embeddings and generative answers; good for citations and concise responses. |
| **Integrations** | Composio | One API for Notion, GitHub, Slack; connected accounts and tool execution without building N connectors. |
| **Search / intel** | You.com | Web search API for competitor research; results cached in DB and reused in RAG context. |
| **Scheduling** | Celery + Redis | Cron-like sync every 6 hours; Redis as broker/backend so the worker can run on Render or any host. |
| **Hosting** | Render | Web service, background worker, and Postgres (with pgvector) from one repo and `render.yaml`; fits hackathon and small-team deploys. |

Secrets (API keys) are **never** hardcoded: they are read from the environment (e.g. `.env` locally, Render env vars in production). This keeps the app safe for autonomy and CI/CD.

---

## Technical implementation

### High-level flow

1. **Knowledge ingestion** — Composio sync (manual trigger or Celery every 6h) pulls from Notion, GitHub, Slack into `knowledge_items` with optional Gemini embeddings. Seed script can load **fake Velora data** from `mock_data/` when no real integrations are configured.
2. **Competitor intel** — You.com search runs for configured competitors/queries; results are stored in `competitor_intel` and shown in the feed. RAG can include these rows as context so answers cite both internal and external intel.
3. **RAG Q&A** — User question → Gemini embedding → pgvector cosine similarity over `knowledge_items` → top-k chunks + recent `competitor_intel` → Gemini prompt → answer + citations.
4. **Usage** — Render API (with `RENDER_API_KEY`) lists workspaces, services, and bandwidth; the backend exposes this as a single JSON endpoint so the frontend can show a usage section without hitting Render from the browser.

### Core components

- **`server.py`** — FastAPI app: health, `/api/ask`, `/api/sync/status`, `/api/sync/trigger`, `/api/intel/feed`, `/api/intel/refresh`, `/api/render/usage`. Loads `.env` so local runs work without exporting keys. Lifespan creates tables and inits pgvector; if DB is unavailable, the app still starts and reports DB status via `/health`.
- **`rag.py`** — Embedding (Gemini), pgvector similarity search, context formatting, and Gemini synthesis with citations. Falls back to mock embeddings and concatenation when the key is missing or the model fails.
- **`composio_sync.py`** — Lists Composio connected accounts, runs Notion/GitHub/Slack tools, upserts into `knowledge_items` (with optional embeddings), and updates `sync_state` (last_sync_at, next_sync_at).
- **`you_com.py`** — You.com search, parse web results, and insert into `competitor_intel`; used by `/api/intel/refresh` and by RAG for competitor context.
- **`render_usage.py`** — Calls Render API (owners, services, metrics/bandwidth) with Bearer token from env; returns a safe payload (no keys). Used by `/api/render/usage`.
- **`worker.py`** — Celery app with beat: one task `sync_data_sources` runs every 6 hours and calls Composio sync. Broker/backend from `REDIS_URL`.
- **`models.py`** — SQLAlchemy: `KnowledgeItem` (source, content, embedding 768-d, metadata), `CompetitorIntel` (competitor_name, intel_type, content, source_url), `SyncState` (key-value for last/next sync).
- **Frontend** — React app: health + sync status + “Trigger sync”, chat (sample questions + freeform), intel feed + “Refresh intel”, Render usage block. Vite proxy sends `/api` and `/health` to the backend.

### Data and demo behavior

- **Velora** and all content in `mock_data/` (e.g. `velora_notion.json`, `velora_github.json`, `velora_slack.json`) are **fake**. They exist so the app runs and demos RAG/sync/intel without real Composio or You.com setup.
- With real keys: point Composio at real Notion/GitHub/Slack, set You.com and optional RENDER_API_KEY; the same code paths run against live data and Render.

---

## Technical details relevant to autonomy

These choices make the system scriptable, deployable, and observable without manual steps.

1. **Secrets only in environment**  
   All API keys (Gemini, Composio, You.com, Render) are read via `os.environ` (or `.env` loaded at startup). Nothing is logged or returned in API responses. Safe for automated deploys and secret managers.

2. **Scheduled worker**  
   Celery Beat runs Composio sync every 6 hours. No human trigger required for periodic ingestion; the worker can be scaled or disabled via Render/Redis.

3. **Resilient startup**  
   If the database is down, the API still starts: lifespan catches DB errors, and `/health` reports `database: disconnected`. Sync/intel/ask endpoints return fallbacks or errors instead of crashing. This allows the frontend and usage endpoint to work even when Postgres is not yet available.

4. **RESTful API**  
   All capabilities are exposed as HTTP endpoints. The frontend is one consumer; scripts or other services can call the same API for ask, sync trigger, intel refresh, or usage.

5. **Single deploy descriptor**  
   `render.yaml` defines web service, worker, and Postgres (with pgvector). Render uses it for one-repo deploy; env vars are configured in the dashboard (or linked from the DB). No custom runbooks for “how to start the stack.”

6. **Caching and idempotency**  
   Competitor intel is stored in the DB; RAG and the feed read from the DB. Sync writes into `knowledge_items` and updates `sync_state`. Repeated triggers or refreshes are safe and reduce external API calls.

7. **No frontend secrets**  
   The browser never sees API keys. The backend proxies to Composio, You.com, and Render; the frontend only talks to the backend (direct or via Vite proxy).

---

## Run the full stack (local)

**Velora is fake; the app is real.** Use two terminals from the project root.

**Terminal 1 — Backend**

```bash
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
# Optional: start DB + Redis, then seed (see below)
uvicorn server:app --reload --port 8000
```

**Terminal 2 — Frontend**

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000**. The UI shows chat, sync status + “Trigger sync”, Competitive Intelligence Feed + “Refresh intel”, and Render Usage (or an error if `RENDER_API_KEY` is not set).

**Optional — database and seed (for full RAG/sync/intel):**

```bash
docker-compose up -d postgres redis
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/onboardai
python seed_data.py
```

Seed uses **fake Velora data** from `mock_data/` so the app works without real Composio. With real keys, sync and intel refresh populate from live sources.

---

## Deploy on Render

1. Connect the repo to Render; use the **Blueprint** from `render.yaml` (web service, worker, Postgres with pgvector).
2. Set env vars in the dashboard: `DATABASE_URL` (from the Postgres service), `REDIS_URL`, and when ready: `GEMINI_API_KEY`, `COMPOSIO_API_KEY`, `COMPOSIO_PROJECT_ID`, `YOU_API_KEY`, `RENDER_API_KEY`.
3. Deploy. The web service serves the API; the worker runs Celery with beat for the 6-hour sync.  
   **Note:** `render.yaml` is a config file for Render, not a shell command.

---

## API keys (reference)

| Key | Purpose |
|-----|--------|
| **GEMINI_API_KEY** | Phase 2 — RAG embeddings and answer generation ([Google AI Studio](https://aistudio.google.com/)). |
| **COMPOSIO_API_KEY** / **COMPOSIO_PROJECT_ID** | Phase 3 — Notion, GitHub, Slack via [Composio](https://app.composio.dev). |
| **YOU_API_KEY** | Phase 4 — Competitor search via [You.com API](https://api.you.com). |
| **RENDER_API_KEY** | Phase 5 — Usage (workspaces, services, bandwidth) from Render Dashboard → Account Settings → API Keys. |

Phase 1 (foundation + demo) works with no keys: seed uses fake Velora data and mock embeddings.

---

## URLs

- **API:** http://localhost:8000  
- **Health:** http://localhost:8000/health  
- **Frontend (demo):** http://localhost:3000  
- **PDF brief:** http://localhost:8000/static/onboarding_brief.pdf  

---

## Sponsor integrations (summary)

| Phase | Sponsor | Role |
|-------|---------|------|
| 1 | — | Foundation + fake Velora data |
| 2 | **Gemini** | RAG embeddings + LLM |
| 3 | **Composio** | Notion, GitHub, Slack sync + manual trigger |
| 4 | **You.com** | Competitor intel feed + refresh + RAG context |
| 5 | **Render** | Hosting + usage API (workspaces, services, bandwidth) |
| 5 | **Composio** | Celery worker — sync every 6 hours |

All of this is wired for a **fake company (Velora)** and synthetic data so a real company can drop in their own Composio/You.com/Render and get the same behavior with real data.
