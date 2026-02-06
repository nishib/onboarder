"""RAG pipeline: Gemini embeddings, pgvector search, Gemini LLM synthesis with citations."""
import json
import os
import re
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import KnowledgeItem, CompetitorIntel

# API key from environment only; never hardcode or log
_GEMINI_KEY = "GEMINI_API_KEY"
_EMBED_MODEL = "models/gemini-embedding-001"
_LLM_MODEL = "models/gemini-2.0-flash"
_EMBED_DIM = 768
_TOP_K = 5
_TOP_K_BRIEF = 25  # more context for daily brief
_REQUEST_TIMEOUT_MS = 45_000  # 45 seconds for generate/embed
_BRIEF_TIMEOUT_MS = 60_000  # 60s for brief (larger output)


def _client():
    """Return Gemini client if key is set, else None. Key is read from env only."""
    api_key = os.environ.get(_GEMINI_KEY)
    if not api_key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=api_key)
    except Exception:
        return None


def get_embedding(text: str, task_type: str = "RETRIEVAL_QUERY") -> Optional[list]:
    """
    Get 768-dim embedding from Gemini. task_type: RETRIEVAL_QUERY for questions,
    RETRIEVAL_DOCUMENT for documents. Returns None if key missing or API fails.
    """
    client = _client()
    if not client:
        return None
    try:
        from google.genai import types
        config = types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=_EMBED_DIM,
        )
        result = client.models.embed_content(
            model=_EMBED_MODEL,
            contents=text,
            config=config,
        )
        if not result.embeddings:
            return None
        emb = result.embeddings[0]
        values = getattr(emb, "values", None) or getattr(emb, "embedding", None)
        if values is None and hasattr(emb, "__iter__"):
            values = list(emb)
        return values if isinstance(values, list) else list(values) if values else None
    except Exception:
        return None


def search_similar(db: Session, query_embedding: list, k: int = _TOP_K):
    """Return up to k KnowledgeItems nearest to query_embedding (cosine distance)."""
    if not query_embedding or len(query_embedding) != _EMBED_DIM:
        return []
    try:
        stmt = (
            select(KnowledgeItem)
            .where(KnowledgeItem.embedding.isnot(None))
            .order_by(KnowledgeItem.embedding.cosine_distance(query_embedding))
            .limit(k)
        )
        return list(db.scalars(stmt).all())
    except (AttributeError, TypeError):
        # Fallback: order by id when .cosine_distance not available (e.g. older pgvector)
        stmt = (
            select(KnowledgeItem)
            .where(KnowledgeItem.embedding.isnot(None))
            .order_by(KnowledgeItem.id)
            .limit(k)
        )
        return list(db.scalars(stmt).all())


def _format_context(item: KnowledgeItem) -> dict:
    """Build citation-friendly context from a KnowledgeItem."""
    meta = item.metadata_ or {}
    title = meta.get("title") or meta.get("repo_name") or meta.get("channel") or item.source
    if meta.get("author"):
        title = f"{title} ({meta['author']})"
    snippet = (item.content or "")[:400].strip()
    if len((item.content or "")) > 400:
        snippet += "..."
    return {
        "source": item.source,
        "title": str(title),
        "snippet": snippet,
        "content": item.content,
    }


def _first_sentence(text: str, max_len: int = 200) -> str:
    """Return the first sentence or first max_len chars of text, trimmed."""
    if not text or not text.strip():
        return ""
    text = text.strip()
    for end in (". ", ".\n", "! ", "? "):
        i = text.find(end)
        if i != -1:
            return text[: i + 1].strip()
    return text[:max_len].strip() + ("..." if len(text) > max_len else "")


_COMPETITOR_KEYWORDS = ("intercom", "zendesk", "gorgias", "competitor", "competitors", "pricing", "competition", "market", "rival")


def _is_competitor_question(question: str) -> bool:
    """Heuristic: question likely about competitors or external research."""
    q = (question or "").lower().strip()
    return any(k in q for k in _COMPETITOR_KEYWORDS)


def _enhance_query_for_competitive_search(question: str) -> str:
    """
    Transform user's question into a competitive/market-focused search query.
    Example: "What is Velora's main product?" -> "AI customer support main product competition market"
    """
    q = (question or "").strip().lower()

    # Extract key terms and add competitive context
    # Remove common question words
    q = q.replace("what is", "").replace("what are", "").replace("who is", "")
    q = q.replace("velora's", "").replace("velora", "")
    q = q.replace("our", "").replace("the", "")
    q = q.replace("?", "").strip()

    # Add competitive/market context keywords
    if "product" in q:
        q = f"AI customer support {q} competition market alternatives"
    elif "pricing" in q or "cost" in q or "price" in q:
        q = f"customer support software {q} pricing comparison competitors"
    elif "feature" in q:
        q = f"AI customer support {q} competitive analysis market"
    else:
        # Generic enhancement: add market/competition context
        q = f"AI customer support {q} market competition alternatives"

    return q.strip()


def _recent_knowledge_for_brief(db: Session, limit: int = _TOP_K_BRIEF) -> list:
    """Return recent knowledge items (by created_at) for daily brief—no query embedding."""
    try:
        stmt = (
            select(KnowledgeItem)
            .order_by(KnowledgeItem.created_at.desc())
            .limit(limit)
        )
        return list(db.scalars(stmt).all())
    except Exception:
        return []


def _competitor_context_items(db: Session, question: str, limit: int = 5) -> list[dict]:
    """
    Fetch competitor context for RAG: cached DB intel + live You.com search.
    Always searches you.com to provide current market/competitive intelligence.
    """
    from sqlalchemy import select
    from you_com import live_search_for_rag

    items = []
    # Always include cached intel (fast)
    stmt = (
        select(CompetitorIntel)
        .order_by(CompetitorIntel.created_at.desc())
        .limit(limit)
    )
    rows = list(db.scalars(stmt).all())
    for r in rows:
        items.append({
            "source": "you_com",
            "title": f"{r.competitor_name} ({r.intel_type})",
            "snippet": (r.content or "")[:300],
            "content": r.content,
        })
    # ALWAYS add live You.com web + news (up to 5 items) to augment with current info
    # This ensures every question gets enriched with live market/competitive context
    # Transform the question into a competitive search query
    enhanced_query = _enhance_query_for_competitive_search(question)
    live = live_search_for_rag(enhanced_query, max_items=5)
    for c in live[:5]:
        items.append(c)
    return items


def generate_answer(question: str, context_items: list, competitor_context: Optional[list] = None) -> tuple[str, list]:
    """
    Use Gemini to synthesize an answer from retrieved contexts + optional competitor intel.
    Returns (answer_text, citations). citations: list of {source, title, snippet} for UI.
    """
    client = _client()
    contexts = [_format_context(it) for it in context_items]
    if competitor_context:
        contexts.extend(competitor_context)
    citations = [{"source": c["source"], "title": c["title"], "snippet": c["snippet"]} for c in contexts]

    if not client or not contexts:
        if not contexts:
            return "I couldn't find relevant information in the knowledge base. Try rephrasing or ask about Velora's product, team, or competitors.", []
        # Fallback: short synthesis from top context (no dump)
        c0 = contexts[0]
        fallback = f"According to [{c0['source']}: {c0['title']}], {_first_sentence(c0.get('snippet') or c0.get('content', ''))}"
        if len(contexts) > 1:
            c1 = contexts[1]
            s1 = _first_sentence(c1.get('snippet') or c1.get('content', ''))
            if s1:
                fallback += f" Additionally, [{c1['source']}: {c1['title']}] notes that {s1}"
        fallback += "."
        return fallback, citations

    try:
        from google.genai import types
        context_blob = "\n\n---\n\n".join(
            f"[Source: {c['source']} – {c['title']}]\n{c['content']}" for c in contexts
        )
        prompt = f"""You are an onboarding assistant for Velora, an AI customer support startup.

Rules:
- Use ONLY the provided context. Do NOT list or dump raw sources.
- Write a concise answer that directly addresses the question in 5–10 lines (short paragraphs or 3–5 bullet points).
- Synthesize the information: summarize, compare, and answer the question. Do not repeat long snippets.
- Cite sources inline where relevant, e.g. [Notion: Product Strategy] or [Slack: #general].
- Answer the question asked; do not just repeat the context.

Context:
{context_blob}

Question: {question}

Answer (5–10 lines, synthesized, with inline source citations):"""

        config_kw = {"temperature": 0.2, "max_output_tokens": 1024}
        try:
            config_kw["http_options"] = types.HttpOptions(timeout=_REQUEST_TIMEOUT_MS)
        except (TypeError, AttributeError):
            pass
        response = client.models.generate_content(
            model=_LLM_MODEL,
            contents=types.Part.from_text(prompt),
            config=types.GenerateContentConfig(**config_kw),
        )
        text = None
        if response.candidates:
            cand = response.candidates[0]
            finish = getattr(cand, "finish_reason", None) or getattr(cand, "finishReason", None)
            if str(finish).upper() in ("BLOCKED", "SAFETY", "RECITATION"):
                text = None
            else:
                part = cand.content.parts[0] if cand.content.parts else None
                if part:
                    text = getattr(part, "text", None) or str(part)
        if not text or not str(text).strip():
            text = "I couldn't generate an answer. Please try rephrasing."
        return str(text).strip(), citations
    except Exception:
        if contexts:
            # Synthesize a short summary from top 1–2 contexts instead of dumping all
            c0 = contexts[0]
            fallback = f"According to [{c0['source']}: {c0['title']}], {_first_sentence(c0.get('snippet') or c0.get('content', ''))}"
            if len(contexts) > 1:
                c1 = contexts[1]
                s1 = _first_sentence(c1.get('snippet') or c1.get('content', ''))
                if s1:
                    fallback += f" Additionally, [{c1['source']}: {c1['title']}] notes that {s1}"
            fallback += "."
            return fallback, citations
        return "An error occurred while generating the answer.", []


_DAILY_BRIEF_SYSTEM = """You are an AI that generates a clean daily product brief from raw, unstructured tool outputs (e.g., Composio extractions, internal tools, Slack, Notion, web results).

The input will change every time and may be messy, incomplete, duplicated, or partially cut off.

Your job is to:
1. Normalize and clean the raw text (fix fragments, remove noise, deduplicate).
2. Extract only factual, decision-relevant updates.
3. Infer structure when the input is unstructured.
4. Rewrite everything in clear, concise, professional product-brief language.
5. Group related facts and merge overlapping points.

Output the final brief as a single JSON object with exactly these keys (use empty arrays for missing sections):
- summary: array of 3–5 strings (most important leadership-level takeaways)
- product: array of strings (shipping updates; performance/reliability; bugs/incidents; max ~5)
- sales: array of strings (pipeline; customer objections; GTM/revenue; max ~5)
- company: array of strings (strategy; positioning; competitive landscape; max ~5)
- onboarding: array of strings (onboarding process; success metrics; common issues; max ~5)
- risks: array of strings (product; market/competitive; execution/operational; max ~5)

Rules:
- Do NOT mention sources (e.g., Slack, Notion, web).
- Do NOT quote raw text; rewrite in your own words.
- If information is missing for a section, use an empty array [] for that section.
- If multiple items conflict, surface the conflict clearly in one bullet.
- Keep each section scannable and concise (max ~5 bullets per section).
- Prioritize what leadership would care about today.
- Return ONLY valid JSON, no markdown code fence or extra text."""


def _raw_context_blob_for_brief(items: list, competitor_dicts: list) -> str:
    """Build a single raw text blob from knowledge + intel for the brief (no source labels)."""
    parts = []
    for it in items:
        content = (it.content or "").strip()
        if content:
            parts.append(content)
    for c in (competitor_dicts or []):
        content = (c.get("content") or c.get("snippet") or "").strip()
        if content:
            parts.append(content)
    return "\n\n---\n\n".join(parts)


def _parse_brief_json(text: str) -> dict:
    """Parse JSON from model output; tolerate markdown code block."""
    if not text or not str(text).strip():
        return {}
    raw = str(text).strip()
    # Strip optional markdown code fence
    for pattern in (r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", r"^```\s*\n?(.*?)\n?```\s*$"):
        m = re.search(pattern, raw, re.DOTALL)
        if m:
            raw = m.group(1).strip()
    try:
        out = json.loads(raw)
        if not isinstance(out, dict):
            return {}
        # Normalize keys and ensure arrays
        result = {}
        for key in ("summary", "product", "sales", "company", "onboarding", "risks"):
            val = out.get(key)
            if isinstance(val, list):
                result[key] = [str(x).strip() for x in val if str(x).strip()]
            else:
                result[key] = []
        return result
    except json.JSONDecodeError:
        return {}


def generate_daily_brief(db: Session) -> dict:
    """
    Generate a structured daily product brief from recent knowledge + competitor intel.
    Returns { summary, product, sales, company, onboarding, risks } (each list of strings).
    """
    client = _client()
    items = _recent_knowledge_for_brief(db, limit=_TOP_K_BRIEF)
    competitor_rows = []
    try:
        stmt = (
            select(CompetitorIntel)
            .order_by(CompetitorIntel.created_at.desc())
            .limit(10)
        )
        competitor_rows = list(db.scalars(stmt).all())
    except Exception:
        pass
    competitor_dicts = [
        {"source": "you_com", "title": f"{r.competitor_name} ({r.intel_type})", "snippet": (r.content or "")[:500], "content": r.content}
        for r in competitor_rows
    ]
    context_blob = _raw_context_blob_for_brief(items, competitor_dicts)

    if not context_blob:
        return {
            "summary": ["No recent data available. Run a Composio sync and refresh intel to generate a brief."],
            "product": [],
            "sales": [],
            "company": [],
            "onboarding": [],
            "risks": [],
        }

    if not client:
        return {
            "summary": ["Brief generation requires GEMINI_API_KEY."],
            "product": [],
            "sales": [],
            "company": [],
            "onboarding": [],
            "risks": [],
        }

    try:
        from google.genai import types
        prompt = f"""{_DAILY_BRIEF_SYSTEM}

Raw context (do not mention these sources in the brief):

{context_blob[:120000]}

Respond with a single JSON object only (keys: summary, product, sales, company, onboarding, risks)."""

        config_kw = {"temperature": 0.2, "max_output_tokens": 2048}
        try:
            config_kw["http_options"] = types.HttpOptions(timeout=_BRIEF_TIMEOUT_MS)
        except (TypeError, AttributeError):
            pass
        response = client.models.generate_content(
            model=_LLM_MODEL,
            contents=types.Part.from_text(prompt),
            config=types.GenerateContentConfig(**config_kw),
        )
        text = None
        if response.candidates:
            cand = response.candidates[0]
            finish = getattr(cand, "finish_reason", None) or getattr(cand, "finishReason", None)
            if str(finish).upper() in ("BLOCKED", "SAFETY", "RECITATION"):
                text = None
            else:
                part = cand.content.parts[0] if cand.content.parts else None
                if part:
                    text = getattr(part, "text", None) or str(part)
        if not text or not str(text).strip():
            return {
                "summary": ["Could not generate brief. Try again or check API key."],
                "product": [],
                "sales": [],
                "company": [],
                "onboarding": [],
                "risks": [],
            }
        parsed = _parse_brief_json(str(text).strip())
        if not parsed:
            return {
                "summary": ["Brief response was not valid. Try again."],
                "product": [],
                "sales": [],
                "company": [],
                "onboarding": [],
                "risks": [],
            }
        return parsed
    except Exception:
        return {
            "summary": ["Brief generation failed. Ensure GEMINI_API_KEY is set and try again."],
            "product": [],
            "sales": [],
            "company": [],
            "onboarding": [],
            "risks": [],
        }


def ask(db: Session, question: str) -> dict:
    """
    Full RAG: embed question, search knowledge + competitor intel (You.com cache), generate answer.
    Returns {answer, citations}. Competitor intel is included so answers cite You.com research.
    """
    import numpy as np
    query_embedding = get_embedding(question, task_type="RETRIEVAL_QUERY")
    if not query_embedding:
        np.random.seed(hash(question) % (2**32))
        query_embedding = np.random.randn(_EMBED_DIM).tolist()
    items = search_similar(db, query_embedding, k=_TOP_K)
    competitor_context = _competitor_context_items(db, question, limit=5)
    answer, citations = generate_answer(question, items, competitor_context=competitor_context)
    return {"answer": answer, "citations": citations}
