"""Render usage — fetch services and bandwidth from Render API.

API key must be set via RENDER_API_KEY env var only. Never log or expose the key.
"""
import os
from typing import Any

import httpx

RENDER_API_BASE = "https://api.render.com/v1"
TIMEOUT = 15.0


def _get_headers() -> dict[str, str]:
    """Build auth headers from env. Returns empty dict if key not set (no key in headers)."""
    key = os.environ.get("RENDER_API_KEY", "").strip()
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}"}


def get_usage() -> dict[str, Any]:
    """Fetch Render usage: owners (workspaces), services, and bandwidth metrics.

    Key is read from RENDER_API_KEY only. Never includes or logs the key.
    Returns a safe payload for the dashboard; on error returns error message only.
    """
    headers = _get_headers()
    if not headers:
        return {
            "ok": False,
            "error": "RENDER_API_KEY not set",
            "owners": [],
            "services": [],
            "bandwidth": [],
        }

    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            # List workspaces (owners)
            owners_res = client.get(f"{RENDER_API_BASE}/owners", headers=headers)
            owners_res.raise_for_status()
            owners_data = owners_res.json()
            if isinstance(owners_data, list):
                owners = owners_data
            elif isinstance(owners_data, dict) and "items" in owners_data:
                owners = owners_data["items"]
            else:
                owners = []

            # List services (optional filter by first owner)
            owner_id = owners[0].get("id") if owners else None
            params = {"ownerId": owner_id} if owner_id else {}
            services_res = client.get(
                f"{RENDER_API_BASE}/services", headers=headers, params=params
            )
            services_res.raise_for_status()
            services_data = services_res.json()
            if isinstance(services_data, list):
                services = services_data
            elif isinstance(services_data, dict) and "items" in services_data:
                services = services_data["items"]
            else:
                services = []

            # Bandwidth for each service (by service id)
            bandwidth_list = []
            for svc in services[:20]:  # limit to avoid too many calls
                sid = svc.get("id") if isinstance(svc, dict) else None
                if not sid:
                    continue
                try:
                    bw_res = client.get(
                        f"{RENDER_API_BASE}/metrics/bandwidth",
                        headers=headers,
                        params={"serviceId": sid},
                    )
                    if bw_res.status_code == 200:
                        bw_data = bw_res.json()
                        if isinstance(bw_data, dict):
                            bandwidth_list.append(
                                {
                                    "serviceId": sid,
                                    "serviceName": svc.get("name", "Unknown"),
                                    "type": svc.get("type"),
                                    **{k: v for k, v in bw_data.items() if k != "serviceId"},
                                }
                            )
                        elif isinstance(bw_data, list):
                            bandwidth_list.append(
                                {
                                    "serviceId": sid,
                                    "serviceName": svc.get("name", "Unknown"),
                                    "type": svc.get("type"),
                                    "data": bw_data,
                                }
                            )
                except Exception:
                    bandwidth_list.append(
                        {
                            "serviceId": sid,
                            "serviceName": svc.get("name", "Unknown"),
                            "type": svc.get("type"),
                            "error": "Could not fetch bandwidth",
                        }
                    )

            return {
                "ok": True,
                "owners": [
                    {"id": o.get("id"), "name": o.get("name")}
                    for o in owners
                    if isinstance(o, dict)
                ],
                "services": [
                    {
                        "id": s.get("id"),
                        "name": s.get("name"),
                        "type": s.get("type"),
                        "serviceDetails": s.get("serviceDetails", {}).get("url")
                        if isinstance(s.get("serviceDetails"), dict)
                        else None,
                    }
                    for s in services
                    if isinstance(s, dict)
                ],
                "bandwidth": bandwidth_list,
            }
    except httpx.HTTPStatusError as e:
        return {
            "ok": False,
            "error": f"Render API error: {e.response.status_code}",
            "owners": [],
            "services": [],
            "bandwidth": [],
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e)[:200],
            "owners": [],
            "services": [],
            "bandwidth": [],
        }
