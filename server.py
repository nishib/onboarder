"""FastAPI application for OnboardAI."""
import os
import concurrent.futures
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# Load .env from repo root so RENDER_API_KEY etc. work when set locally
load_dotenv(Path(__file__).resolve().parent / ".env")

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import engine, get_db, init_pgvector, SessionLocal
from models import Base
from rag import ask, generate_daily_brief


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create tables and enable pgvector. Tolerate DB unavailable so app still starts."""
    try:
        Base.metadata.create_all(bind=engine)
        db = next(get_db())
        try:
            init_pgvector(db)
        finally:
            db.close()
    except Exception:
        pass  # DB may be unavailable; /health will report disconnected
    yield


app = FastAPI(title="OnboardAI", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static PDF brief
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Serve frontend build (Vite React app)
frontend_dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(frontend_dist):
    # Serve static assets (JS, CSS, images) from /assets
    assets_dir = os.path.join(frontend_dist, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    # Serve other static files (favicon, etc.)
    @app.get("/favicon.ico")
    @app.get("/vite.svg")
    async def serve_static_files(request):
        file_path = os.path.join(frontend_dist, request.url.path.lstrip("/"))
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return {"detail": "Not Found"}


def check_db():
    """Test database connectivity."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "connected"
    except Exception:
        return "disconnected"


@app.get("/health")
def health():
    """Health check for Render and frontend."""
    return {
        "status": "healthy",
        "database": check_db(),
    }


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    citations: list[dict]
    brief: dict | None = None  # structured daily brief when user asks for it


class BriefResponse(BaseModel):
    summary: list[str]
    product: list[str]
    sales: list[str]
    company: list[str]
    onboarding: list[str]
    risks: list[str]


_ASK_TIMEOUT_SEC = 50
_BRIEF_TIMEOUT_SEC = 65
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

_BRIEF_TRIGGERS = (
    "today's brief", "todays brief", "daily brief", "give me the brief",
    "product brief", "generate brief", "create brief", "brief me",
)


def _is_brief_request(question: str) -> bool:
    q = (question or "").lower().strip()
    return any(t in q for t in _BRIEF_TRIGGERS)


def _ask_with_fresh_session(question: str):
    """Run RAG ask in a thread with a fresh DB session (sessions are not thread-safe)."""
    db = SessionLocal()
    try:
        return ask(db, question)
    finally:
        db.close()


def _brief_with_fresh_session():
    """Run daily brief generation in a thread with a fresh DB session."""
    db = SessionLocal()
    try:
        return generate_daily_brief(db)
    finally:
        db.close()


@app.get("/api/brief", response_model=BriefResponse)
@app.post("/api/brief", response_model=BriefResponse)
def api_brief(db: Session = Depends(get_db)):
    """Generate structured daily product brief from recent Composio + intel data."""
    try:
        future = _executor.submit(_brief_with_fresh_session)
        result = future.result(timeout=_BRIEF_TIMEOUT_SEC)
        return BriefResponse(
            summary=result.get("summary", []),
            product=result.get("product", []),
            sales=result.get("sales", []),
            company=result.get("company", []),
            onboarding=result.get("onboarding", []),
            risks=result.get("risks", []),
        )
    except concurrent.futures.TimeoutError:
        return BriefResponse(
            summary=["Brief generation timed out. Try again."],
            product=[], sales=[], company=[], onboarding=[], risks=[],
        )
    except Exception:
        return BriefResponse(
            summary=["Brief generation failed. Ensure DB and GEMINI_API_KEY are set."],
            product=[], sales=[], company=[], onboarding=[], risks=[],
        )


@app.post("/api/ask", response_model=AskResponse)
def api_ask(req: AskRequest, db: Session = Depends(get_db)):
    """RAG Q&A (Gemini): embed, semantic search, synthesis with citations. Times out after 50s."""
    q = (req.question or "").strip()
    if not q:
        return AskResponse(answer="Please ask a question about Velora.", citations=[])
    if _is_brief_request(q):
        try:
            future = _executor.submit(_brief_with_fresh_session)
            brief = future.result(timeout=_BRIEF_TIMEOUT_SEC)
            return AskResponse(answer="", citations=[], brief=brief)
        except concurrent.futures.TimeoutError:
            return AskResponse(
                answer="Brief generation timed out. Try the “Today’s brief” button or try again.",
                citations=[],
            )
        except Exception:
            return AskResponse(
                answer="Brief generation failed. Ensure DB and GEMINI_API_KEY are set.",
                citations=[],
            )
    try:
        future = _executor.submit(_ask_with_fresh_session, q)
        result = future.result(timeout=_ASK_TIMEOUT_SEC)
        return AskResponse(answer=result["answer"], citations=result["citations"])
    except concurrent.futures.TimeoutError:
        return AskResponse(
            answer="The request took too long. Please try again or ask a shorter question.",
            citations=[],
        )
    except Exception:
        return AskResponse(
            answer="The knowledge base is unavailable. Ensure the database is running and seeded.",
            citations=[],
        )


@app.get("/api/sync/status")
def sync_status(db: Session = Depends(get_db)):
    """Return last_sync_at and next_sync_at for dashboard (Composio)."""
    try:
        from composio_sync import get_sync_status
        return get_sync_status(db)
    except Exception:
        from datetime import datetime, timedelta
        return {"last_sync_at": None, "next_sync_at": (datetime.utcnow() + timedelta(hours=6)).isoformat()}


@app.post("/api/sync/trigger")
def sync_trigger(db: Session = Depends(get_db)):
    """Trigger Composio sync manually (Phase 3 – Composio)."""
    try:
        from composio_sync import run_sync
        result = run_sync(db)
        return {"status": "ok", **result}
    except Exception as e:
        return {"status": "error", "error": str(e)[:200]}


@app.get("/api/intel/feed")
def intel_feed(db: Session = Depends(get_db)):
    """Competitive Intelligence Feed (You.com) — cached results."""
    try:
        from you_com import get_intel_feed
        rows = get_intel_feed(db, limit=20)
        return [
            {
                "id": r.id,
                "competitor": r.competitor_name,
                "type": r.intel_type,
                "content": r.content,
                "source_url": r.source_url,
                "timestamp": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    except Exception:
        return []


@app.get("/api/intel/search")
def intel_search(q: str = "", count: int = 8, freshness: str = "month"):
    """Live You.com web + news search. Returns { web, news, query } for the given query."""
    try:
        from you_com import live_search
        result = live_search(q.strip(), count=min(max(1, count), 20), freshness=freshness)
        return result
    except Exception as e:
        return {"web": [], "news": [], "query": q or "", "error": str(e)[:200]}


@app.post("/api/intel/refresh")
def intel_refresh(db: Session = Depends(get_db)):
    """Refresh competitor intel from You.com (Phase 4 – You.com)."""
    try:
        from you_com import refresh_competitor_intel
        added = refresh_competitor_intel(db)
        return {"status": "ok", "added": added}
    except Exception as e:
        return {"status": "error", "added": 0, "error": str(e)[:200]}


@app.get("/api/render/usage")
def render_usage():
    """Render usage — workspaces, services, bandwidth. Key from env only."""
    from render_usage import get_usage
    return get_usage()


# Catch-all route to serve frontend index.html for client-side routing
# This must be LAST so API routes are matched first
@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    """Serve React frontend for all non-API routes (client-side routing)."""
    frontend_dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")
    index_file = os.path.join(frontend_dist, "index.html")

    # If frontend build exists, serve index.html
    if os.path.isfile(index_file):
        return FileResponse(index_file)

    # Fallback for development (no frontend build yet)
    return {
        "detail": "Frontend not built. Run: cd frontend && npm install && npm run build",
        "path": full_path,
    }
