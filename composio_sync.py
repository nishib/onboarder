"""
Composio sync — Notion, GitHub, Slack.
Credentials from environment only: COMPOSIO_API_KEY, COMPOSIO_PROJECT_ID.
Normalizes and cleans raw tool output for better brief generation.
"""
import base64
import os
import re
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from models import KnowledgeItem, SyncState

# Read from env only; never hardcode or log
_BASE = "https://backend.composio.dev/api/v3"
_ENTITY_ID = "onboardai_velora"
_SYNC_INTERVAL_HOURS = 6


def _headers() -> dict:
    key = os.environ.get("COMPOSIO_API_KEY")
    if not key:
        return {}
    return {"x-api-key": key, "Content-Type": "application/json"}


def _get(path: str, params: Optional[dict] = None) -> Optional[dict]:
    if not _headers():
        return None
    try:
        r = httpx.get(f"{_BASE}{path}", headers=_headers(), params=params or {}, timeout=30.0)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _post(path: str, body: dict) -> Optional[dict]:
    if not _headers():
        return None
    try:
        r = httpx.post(f"{_BASE}{path}", headers=_headers(), json=body, timeout=60.0)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def list_connections(toolkit_slugs: Optional[list[str]] = None) -> list[dict]:
    """List connected accounts for the project. Returns list of {id, user_id, toolkit.slug}."""
    params = {}
    if toolkit_slugs:
        params["toolkit_slugs"] = toolkit_slugs
    data = _get("/connected_accounts", params=params)
    if not data or "items" not in data:
        return []
    return data.get("items", [])


def execute_tool(tool_slug: str, connected_account_id: str, arguments: Optional[dict] = None) -> Optional[dict]:
    """Execute a Composio tool. Returns response data or None. Timeout 45s per call."""
    body = {"connected_account_id": connected_account_id}
    if arguments:
        body["arguments"] = arguments
    try:
        r = httpx.post(f"{_BASE}/tools/execute/{tool_slug}", headers=_headers(), json=body, timeout=45.0)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return None
    if not data:
        return None
    return data.get("data") if isinstance(data.get("data"), dict) else data


def _normalize_raw_text(text: str) -> str:
    """Normalize raw tool output for brief: fix fragments, remove noise, dedupe lines."""
    if not text or not isinstance(text, str):
        return ""
    s = text.strip()
    # Collapse multiple whitespace and newlines
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    # Remove common API noise (standalone key: value lines)
    s = re.sub(r"^\s*(id|type|created_at|updated_at)\s*:\s*[^\n]+\s*$", " ", s, flags=re.IGNORECASE | re.MULTILINE)
    # Dedupe by line (case-insensitive prefix)
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    seen = set()
    unique = []
    for ln in lines:
        key = ln.lower()[:200]
        if key not in seen and len(ln) > 2:
            seen.add(key)
            unique.append(ln)
    return "\n".join(unique).strip()


def _embed(text: str) -> Optional[list]:
    try:
        from rag import get_embedding
        return get_embedding(text, task_type="RETRIEVAL_DOCUMENT")
    except Exception:
        return None


def _upsert_knowledge(db: Session, source: str, content: str, metadata_: dict) -> None:
    if not content or not content.strip():
        return
    content = _normalize_raw_text(content)
    if not content or len(content) < 3:
        return
    emb = _embed(content)
    item = KnowledgeItem(
        source=source,
        content=content[:100000],
        embedding=emb,
        metadata_=metadata_,
        created_at=datetime.utcnow(),
    )
    db.add(item)


def _notion_extract_text(fetch: Any) -> str:
    """Extract readable text from a Notion fetch response (block or page)."""
    if not fetch or not isinstance(fetch, dict):
        return ""
    text_parts = []
    if fetch.get("content"):
        text_parts.append(str(fetch["content"]))
    for key in ("title", "plain_text", "name"):
        val = fetch.get(key)
        if val is not None and val != "":
            text_parts.append(str(val) if not isinstance(val, list) else " ".join(str(x) for x in val))
    if fetch.get("rich_text"):
        rt = fetch["rich_text"]
        if isinstance(rt, list):
            text_parts.append(" ".join(str(t.get("plain_text", t) if isinstance(t, dict) else t) for t in rt))
        else:
            text_parts.append(str(rt))
    for children_key in ("children", "blocks", "results", "content"):
        children = fetch.get(children_key) or []
        if not isinstance(children, list):
            continue
        for c in children[:80]:
            if isinstance(c, dict):
                if c.get("plain_text"):
                    text_parts.append(c["plain_text"])
                if c.get("rich_text"):
                    rt = c["rich_text"]
                    text_parts.append(" ".join(t.get("plain_text", "") for t in (rt if isinstance(rt, list) else [])))
                if c.get("type") and c.get("type") not in ("divider", "breadcrumb"):
                    text_parts.append(_notion_extract_text(c))
            else:
                text_parts.append(_notion_extract_text(c))
    return " ".join(p for p in text_parts if p).strip()


def sync_notion(db: Session, connected_account_id: str) -> int:
    """Fetch Notion pages via Composio and store in DB. Returns count of items added."""
    added = 0
    out = execute_tool("NOTION_SEARCH_NOTION_PAGE", connected_account_id, {"query": ""})
    if not out:
        return 0
    results = out.get("results") if isinstance(out, dict) else (out if isinstance(out, list) else [])
    if not isinstance(results, list):
        results = []
    page_ids = []
    for r in results[:25]:
        if isinstance(r, dict):
            pid = r.get("id")
        else:
            pid = None
        if pid:
            page_ids.append(pid)
    for page_id in page_ids[:20]:
        fetch = execute_tool("NOTION_FETCH_BLOCK_CONTENTS", connected_account_id, {"block_id": page_id})
        if not fetch:
            fetch = execute_tool("NOTION_FETCH_DATA", connected_account_id, {"resource_id": page_id})
        content = _notion_extract_text(fetch) if fetch else ""
        content = content or f"Page {page_id}"
        title = (content[:200]) if content else str(page_id)
        _upsert_knowledge(db, "notion", content, {"page_id": page_id, "title": title, "created": datetime.utcnow().isoformat()})
        added += 1
    return added


def _normalize_repos_list(out: Any) -> list:
    """Extract list of repos from various Composio/GitHub API response shapes."""
    if not out:
        return []
    if isinstance(out, list):
        return out
    if isinstance(out, dict):
        for key in ("repos", "data", "items", "repositories"):
            val = out.get(key)
            if isinstance(val, list):
                return val
        if out.get("total_count") is not None and isinstance(out.get("items"), list):
            return out["items"]
    return []


def _decode_readme_content(raw: Any) -> str:
    """Decode README content from API (string or base64)."""
    if raw is None:
        return ""
    if isinstance(raw, dict):
        raw = raw.get("content") or raw.get("body") or raw.get("text") or str(raw)
    s = str(raw).strip()
    if not s:
        return ""
    if s.startswith("data:"):
        try:
            s = base64.b64decode(s.split(",", 1)[-1]).decode("utf-8", errors="replace")
        except Exception:
            pass
    return s


def sync_github(db: Session, connected_account_id: str) -> int:
    """Fetch GitHub repos and READMEs via Composio. Tries multiple tool slugs for accuracy."""
    added = 0
    repos = []
    for slug in ("GITHUB_REPOS_LIST_FOR_AUTHENTICATED_USER", "GITHUB_LIST_REPOS", "GITHUB_REPOS_LIST"):
        out = execute_tool(slug, connected_account_id, {"per_page": 15})
        repos = _normalize_repos_list(out)
        if repos:
            break
    for repo in repos[:15]:
        if not isinstance(repo, dict):
            continue
        owner_obj = repo.get("owner")
        owner = owner_obj.get("login") if isinstance(owner_obj, dict) else repo.get("owner_login") or repo.get("owner")
        name = repo.get("name") or repo.get("repo") or repo.get("repository")
        if isinstance(owner, dict):
            owner = owner.get("login")
        if not owner or not name:
            continue
        owner, name = str(owner).strip(), str(name).strip()
        full_name = f"{owner}/{name}"
        title = repo.get("full_name") or full_name
        description = (repo.get("description") or "").strip()
        readme_content = ""
        for readme_slug in ("GITHUB_REPOS_GET_README", "GITHUB_GET_README", "GITHUB_REPOS_GET_README"):
            readme_out = execute_tool(readme_slug, connected_account_id, {"owner": owner, "repo": name})
            if readme_out:
                readme_content = _decode_readme_content(readme_out)
                if readme_content:
                    break
        body_parts = [description] if description else []
        body_parts.append(readme_content or f"Repository: {full_name}")
        content = "\n\n".join(p for p in body_parts if p).strip() or f"README {full_name}"
        _upsert_knowledge(
            db,
            "github",
            content,
            {
                "repo_name": name,
                "owner": owner,
                "full_name": full_name,
                "title": title,
                "created": datetime.utcnow().isoformat(),
            },
        )
        added += 1
    return added


def _slack_channel_list(out: Any) -> list:
    """Extract channel list from Composio/Slack response."""
    if not out:
        return []
    if isinstance(out, list):
        return out
    if isinstance(out, dict):
        for key in ("channels", "data", "items"):
            val = out.get(key)
            if isinstance(val, list):
                return val
    return []


def _slack_message_list(out: Any) -> list:
    """Extract message list from Slack history response."""
    if not out:
        return []
    if isinstance(out, list):
        return out
    if isinstance(out, dict):
        for key in ("messages", "data", "items"):
            val = out.get(key)
            if isinstance(val, list):
                return val
    return []


def sync_slack(db: Session, connected_account_id: str) -> int:
    """Fetch Slack #general and #product history via Composio. Returns count added."""
    added = 0
    for list_slug in ("SLACK_CONVERSATIONS_LIST", "SLACK_CHANNELS_LIST"):
        channels_out = execute_tool(list_slug, connected_account_id, {"limit": 50})
        ch_list = _slack_channel_list(channels_out)
        if not ch_list:
            continue
        channel_ids = {}
        for ch in ch_list:
            if not isinstance(ch, dict):
                continue
            name = (ch.get("name") or ch.get("channel") or "").lower()
            cid = ch.get("id") or ch.get("channel_id")
            if name in ("general", "product", "engineering") and cid:
                channel_ids[name] = cid
        if not channel_ids:
            continue
        for ch_name, ch_id in channel_ids.items():
            for hist_slug in ("SLACK_CONVERSATIONS_HISTORY", "SLACK_CHANNEL_HISTORY"):
                hist = execute_tool(hist_slug, connected_account_id, {"channel": ch_id, "limit": 30})
                messages = _slack_message_list(hist)
                for msg in messages[:30]:
                    if not isinstance(msg, dict):
                        continue
                    text = msg.get("text") or msg.get("content") or msg.get("message") or ""
                    if not text or not str(text).strip():
                        continue
                    user = msg.get("user") or msg.get("username") or msg.get("user_id") or "unknown"
                    ts = msg.get("ts") or msg.get("timestamp") or datetime.utcnow().isoformat()
                    _upsert_knowledge(
                        db,
                        "slack",
                        str(text).strip(),
                        {"channel": f"#{ch_name}", "author": user, "timestamp": ts, "created": datetime.utcnow().isoformat()},
                    )
                    added += 1
                if messages:
                    break
        if channel_ids:
            break
    return added


def _set_sync_state(db: Session, key: str, value: Any) -> None:
    row = db.get(SyncState, key)
    if row:
        row.value = value
        row.updated_at = datetime.utcnow()
    else:
        db.add(SyncState(key=key, value=value))
    db.commit()


def _get_sync_state(db: Session, key: str) -> Any:
    row = db.get(SyncState, key)
    return row.value if row and row.value else None


def run_sync(db: Session) -> dict:
    """
    Run full Composio sync: list connections, fetch Notion/GitHub/Slack, store in DB.
    Updates last_sync_at. Returns {notion, github, slack, last_sync_at, next_sync_at}.
    """
    result = {"notion": 0, "github": 0, "slack": 0, "last_sync_at": None, "next_sync_at": None}
    if not _headers():
        return result
    connections = list_connections(["notion", "github", "slack"])
    by_toolkit = {}
    for c in connections:
        if not isinstance(c, dict):
            continue
        tid = (c.get("toolkit") or {}).get("slug") if isinstance(c.get("toolkit"), dict) else c.get("toolkit")
        if tid:
            by_toolkit.setdefault(tid, []).append(c.get("id"))
    for toolkit, ids in by_toolkit.items():
        if not ids:
            continue
        ca_id = ids[0]
        if toolkit == "notion":
            result["notion"] = sync_notion(db, ca_id)
        elif toolkit == "github":
            result["github"] = sync_github(db, ca_id)
        elif toolkit == "slack":
            result["slack"] = sync_slack(db, ca_id)
    db.commit()
    now = datetime.utcnow()
    next_at = now + timedelta(hours=_SYNC_INTERVAL_HOURS)
    _set_sync_state(db, "last_sync_at", now.isoformat())
    _set_sync_state(db, "next_sync_at", next_at.isoformat())
    result["last_sync_at"] = now.isoformat()
    result["next_sync_at"] = next_at.isoformat()
    return result


def get_sync_status(db: Session) -> dict:
    """Return last_sync_at and next_sync_at for dashboard."""
    last = _get_sync_state(db, "last_sync_at")
    next_ = _get_sync_state(db, "next_sync_at")
    if not next_ and last:
        try:
            dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
            next_ = (dt + timedelta(hours=_SYNC_INTERVAL_HOURS)).isoformat()
        except Exception:
            pass
    if not next_:
        # Default: next sync in 6 hours so dashboard always shows something
        next_ = (datetime.utcnow() + timedelta(hours=_SYNC_INTERVAL_HOURS)).isoformat()
    return {"last_sync_at": last, "next_sync_at": next_}
