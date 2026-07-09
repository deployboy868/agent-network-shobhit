"""
Web service hosting:
  POST /api/messages  — Microsoft Teams bot endpoint (Bot Framework)
  POST /api/a2a       — agent-to-agent messages from peer twin services
  GET  /healthz       — health probe

Run locally (after pip install -r requirements-teams.txt):
  PYTHONPATH=. python -m agent_network.teams.app
Then expose https publicly (Azure App Service, or `devtunnel`/ngrok for testing)
and set that URL as the bot messaging endpoint.
"""

from __future__ import annotations

import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _normalize_emulator_service_url(activity) -> None:
    """
    Emulator runs on the host; Docker must call back via host.docker.internal,
    not localhost (which inside the container is the container itself).
    """
    from agent_network.config import bot_emulator_mode

    if not bot_emulator_mode():
        return
    host = os.getenv("EMULATOR_HOST", "host.docker.internal").strip() or "host.docker.internal"
    url = getattr(activity, "service_url", None) or ""
    if not url:
        return
    if "localhost" in url or "127.0.0.1" in url:
        activity.service_url = url.replace("127.0.0.1", host).replace("localhost", host)
        logger.info("Emulator callback URL: %s", activity.service_url)


def create_app():
    from aiohttp import web
    from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings
    from botbuilder.schema import Activity

    from agent_network.a2a.server import handle_a2a_request
    from agent_network.config import (
        bot_emulator_mode,
        teams_app_id,
        teams_app_password,
    )
    from agent_network.teams.bot import build_bot

    app_id = teams_app_id()
    app_password = teams_app_password()
    emulator = bot_emulator_mode()

    if emulator:
        logger.warning(
            "BOT EMULATOR MODE — Azure auth disabled. "
            "Do not expose publicly without MICROSOFT_APP_ID/PASSWORD."
        )

    settings = BotFrameworkAdapterSettings(app_id or "", app_password or "")
    adapter = BotFrameworkAdapter(settings)
    bot = build_bot()

    async def on_error(context, error):  # pragma: no cover
        logger.exception("Bot error: %s", error)
        await context.send_activity("The twin hit an error handling that. Try again.")

    adapter.on_turn_error = on_error

    async def messages(req):
        if "application/json" not in req.headers.get("Content-Type", ""):
            return web.Response(status=415)
        body = await req.json()
        activity = Activity().deserialize(body)
        auth_header = req.headers.get("Authorization", "")

        if emulator:
            _normalize_emulator_service_url(activity)
            try:
                from botbuilder.connector.auth import MicrosoftAppCredentials

                if activity.service_url:
                    MicrosoftAppCredentials.trust_service_url(activity.service_url)
            except Exception:
                pass
            auth_header = ""

        try:
            response = await adapter.process_activity(activity, auth_header, bot.on_turn)
        except Exception as exc:
            logger.exception("Bot message failed: %s", exc)
            return web.Response(status=500, text=str(exc))

        if response:
            return web.json_response(data=response.body, status=response.status)
        return web.Response(status=201)

    async def a2a(req):
        payload = await req.json()
        result = handle_a2a_request(payload)
        return web.json_response(result, status=200 if result.get("accepted") else 400)

    async def health(_req):
        return web.json_response({"status": "ok"})

    app = web.Application()
    app.router.add_post("/api/messages", messages)
    app.router.add_post("/api/a2a", a2a)
    app.router.add_get("/healthz", health)
    return app


def main() -> None:
    from aiohttp import web

    port = int(os.getenv("PORT", "3978"))
    logger.info("Starting Teams + A2A service on port %d", port)
    web.run_app(create_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
