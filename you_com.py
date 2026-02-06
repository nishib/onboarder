"""
You.com competitor intelligence.
Live web search + news search; cached competitor intel.
API key from environment only: YOU_API_KEY. Never hardcode or log.
"""
import os
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from models import CompetitorIntel

# Search API (returns both web and news)
_BASE = "https://ydc-index.io/v1"
# Live News API (news-only; may require early-access)
_NEWS_BASE = "https://api.ydc-index.io"
_COMPETITORS = [
    ("Intercom", "pricing", "Intercom customer support software pricing news"),
    ("Zendesk", "product", "Zendesk AI customer service product updates"),
    ("Gorgias", "market", "Gorgias e-commerce support growth funding"),
]


def _headers() -> dict:
    key = os.environ.get("YOU_API_KEY")
    if not key:
        return {}
    return {"X-API-Key": key, "Accept": "application/json"}


def search(query: str, count: int = 10, freshness: str = "month") -> Optional[dict]:
    """You.com unified search (web + news). Returns raw response JSON or None."""
    if not _headers():
        return None
    try:
        r = httpx.get(
            f"{_BASE}/search",
            headers=_headers(),
            params={"query": query, "count": min(count, 20), "freshness": freshness},
            timeout=15.0,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def search_news(query: str, count: int = 10) -> Optional[dict]:
    """You.com Live News API (news-only). Returns raw response or None (e.g. if no early access)."""
    if not _headers():
        return None
    try:
        r = httpx.get(
            f"{_NEWS_BASE}/livenews",
            headers=_headers(),
            params={"q": query, "count": min(count, 40)},
            timeout=15.0,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _normalize_web_hit(hit: dict) -> dict:
    """Normalize a web result for live search response."""
    url = hit.get("url") or ""
    title = hit.get("title") or ""
    desc = hit.get("description") or ""
    snippets = hit.get("snippets") or []
    content = desc or (snippets[0] if snippets else title) or url
    return {
        "title": (title or "").strip(),
        "content": (content[:1500] + "..." if len(content) > 1500 else content).strip(),
        "url": url[:512] if url else None,
        "thumbnail_url": (hit.get("thumbnail_url") or "").strip() or None,
    }


def _normalize_news_hit(hit: dict) -> dict:
    """Normalize a news result (unified search or livenews) for live search response."""
    url = hit.get("url") or ""
    title = hit.get("title") or ""
    desc = hit.get("description") or ""
    content = desc or title or url
    return {
        "title": (title or "").strip(),
        "content": (content[:1500] + "..." if len(content) > 1500 else content).strip(),
        "url": url[:512] if url else None,
        "thumbnail_url": (hit.get("thumbnail_url") or (hit.get("thumbnail") or {}).get("src") or "").strip() or None,
        "source_name": (hit.get("source_name") or "").strip() or None,
        "page_age": hit.get("page_age") or hit.get("age") or None,
    }


def live_search(query: str, count: int = 8, freshness: str = "month") -> dict:
    """
    Run live You.com search and return normalized web + news for the UI.
    Returns {"web": [...], "news": [...], "query": str}. Uses unified search (web + news in one call).
    """
    out = {"web": [], "news": [], "query": (query or "").strip()}
    if not out["query"] or not _headers():
        return out
    data = search(out["query"], count=count, freshness=freshness)
    if not data:
        return out
    results = data.get("results") or {}
    # Web results
    web = results.get("web") or []
    if isinstance(web, list):
        for hit in web[:count]:
            if isinstance(hit, dict) and (hit.get("title") or hit.get("description") or hit.get("snippets")):
                out["web"].append(_normalize_web_hit(hit))
    # News from same unified response
    news = results.get("news") or []
    if isinstance(news, list):
        for hit in news[:count]:
            if isinstance(hit, dict) and (hit.get("title") or hit.get("description")):
                out["news"].append(_normalize_news_hit(hit))
    # If no news in unified response, try Live News API (may 403 without early access)
    if not out["news"]:
        news_data = search_news(out["query"], count=min(count, 15))
        if news_data:
            news_obj = news_data.get("news") or {}
            news_list = news_obj.get("results") if isinstance(news_obj, dict) else []
            if isinstance(news_list, list):
                for hit in news_list[:count]:
                    if isinstance(hit, dict) and (hit.get("title") or hit.get("description")):
                        out["news"].append(_normalize_news_hit(hit))
    return out


def live_search_for_rag(question: str, max_items: int = 5) -> list[dict]:
    """
    Run live You.com search for a question and return RAG-style context items.
    Returns list of {source, title, snippet, content} for generate_answer.
    Used to augment RAG when the question is about competitors or external research.
    """
    out = []
    q = (question or "").strip()
    if not q or not _headers():
        return out
    result = live_search(q, count=max_items, freshness="month")
    for item in (result.get("web") or []) + (result.get("news") or []):
        title = (item.get("title") or "").strip()
        content = (item.get("content") or "").strip()
        if not content:
            continue
        source = "you_com_live"
        if item.get("source_name"):
            source = f"you_com_live ({item['source_name']})"
        out.append({
            "source": source,
            "title": title or "You.com result",
            "snippet": content[:300] + "..." if len(content) > 300 else content,
            "content": content,
        })
        if len(out) >= max_items:
            break
    return out


def _parse_web_results(data: dict, competitor_name: str, intel_type: str) -> list[dict]:
    """Parse You.com response into intel items: {competitor_name, intel_type, content, source_url}."""
    items = []
    results = data.get("results") or {}
    web = results.get("web") or []
    if not isinstance(web, list):
        return items
    for hit in web[:5]:
        if not isinstance(hit, dict):
            continue
        url = hit.get("url") or ""
        title = hit.get("title") or ""
        desc = hit.get("description") or ""
        snippets = hit.get("snippets") or []
        content = desc or (snippets[0] if snippets else title) or url
        if not content or len(content.strip()) < 20:
            continue
        items.append({
            "competitor_name": competitor_name,
            "intel_type": intel_type,
            "content": (content[:2000] + "..." if len(content) > 2000 else content).strip(),
            "source_url": url[:512] if url else None,
        })
    return items


def refresh_competitor_intel(db: Session) -> int:
    """
    Search You.com for Intercom, Zendesk, Gorgias; store in CompetitorIntel (cached).
    Returns number of new items stored. Uses YOU_API_KEY from env only.
    """
    added = 0
    if not _headers():
        return 0
    for competitor_name, intel_type, query in _COMPETITORS:
        data = search(query, count=5, freshness="month")
        if not data:
            continue
        for item in _parse_web_results(data, competitor_name, intel_type):
            row = CompetitorIntel(
                competitor_name=item["competitor_name"],
                intel_type=item["intel_type"],
                content=item["content"],
                source_url=item.get("source_url"),
                created_at=datetime.utcnow(),
            )
            db.add(row)
            added += 1
    if added:
        db.commit()
    return added


def get_intel_feed(db: Session, limit: int = 20):
    """Return recent CompetitorIntel rows for feed (timeline)."""
    from sqlalchemy import select
    stmt = (
        select(CompetitorIntel)
        .order_by(CompetitorIntel.created_at.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())
