"""
Microsoft Graph presence client.

Reads a user's Teams presence (Available / Away / Busy / Offline ...) using the
client-credentials flow. Requires an Entra app with the application permission
`Presence.Read.All` and admin consent.

Env:
  TENANT_ID, GRAPH_CLIENT_ID (or MICROSOFT_APP_ID), GRAPH_CLIENT_SECRET (or MICROSOFT_APP_PASSWORD)
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional
from urllib.request import Request, urlopen

from agent_network.config import (
    graph_client_id,
    graph_client_secret,
    graph_tenant_id,
)

logger = logging.getLogger(__name__)

_GRAPH = "https://graph.microsoft.com/v1.0"
_token_cache: dict[str, object] = {"value": None, "exp": 0.0}


def _acquire_token() -> Optional[str]:
    now = time.time()
    if _token_cache["value"] and float(_token_cache["exp"]) > now + 60:
        return str(_token_cache["value"])
    try:
        import msal
    except ImportError:
        logger.warning("msal not installed — cannot read Teams presence")
        return None

    authority = f"https://login.microsoftonline.com/{graph_tenant_id()}"
    app = msal.ConfidentialClientApplication(
        client_id=graph_client_id(),
        client_credential=graph_client_secret(),
        authority=authority,
    )
    result = app.acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )
    token = result.get("access_token")
    if not token:
        logger.warning("Graph token error: %s", result.get("error_description"))
        return None
    _token_cache["value"] = token
    _token_cache["exp"] = now + int(result.get("expires_in", 3600))
    return token


def _graph_get(path: str, token: str) -> Optional[dict]:
    req = Request(
        f"{_GRAPH}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:  # pragma: no cover - network dependent
        logger.warning("Graph GET %s failed: %s", path, e)
        return None


def get_presence_by_email(email: str) -> Optional[str]:
    """Return availability string for a user, or None if unavailable."""
    token = _acquire_token()
    if not token:
        return None
    user = _graph_get(f"/users/{email}", token)
    if not user or "id" not in user:
        return None
    presence = _graph_get(f"/users/{user['id']}/presence", token)
    if not presence:
        return None
    # availability: Available, Away, BeRightBack, Busy, DoNotDisturb, Offline, ...
    return presence.get("availability")
