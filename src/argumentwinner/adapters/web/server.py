"""Web adapter: a phone-friendly page + tiny JSON API over the same engine.

Deploy it anywhere with a domain (Railway gives HTTPS for free), open it on
your phone, Add to Home Screen, and it behaves like an app: paste the
opponent's message, tap, copy the winning reply.

Design notes:
- aiohttp is already a hard dependency (via discord.py), so unlike the
  desktop/telegram extras this adapter installs nothing new.
- Auth is a single shared secret (AW_WEB_TOKEN) sent as a Bearer header and
  kept in the browser's localStorage — the page itself is public, every API
  call is not. Comparison is constant-time.
- Stateless by design: like the desktop helper, each request is a one-shot
  pasted-text argument (single_message_context) — no transcript server-side.
"""

from __future__ import annotations

import hmac
import logging
from importlib import resources

from aiohttp import web

from argumentwinner.adapters.common import single_message_context
from argumentwinner.container import App
from argumentwinner.core.models import Persona
from argumentwinner.core.ports import StructuredOutputError

log = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 4000
PLATFORM = "web"


def _authorized(request: web.Request, token: str) -> bool:
    supplied = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    return bool(supplied) and hmac.compare_digest(supplied, token)


def build_web_app(app: App, token: str) -> web.Application:
    async def index(_request: web.Request) -> web.Response:
        html = resources.files(__package__).joinpath("index.html").read_text("utf-8")
        return web.Response(text=html, content_type="text/html")

    async def argue(request: web.Request) -> web.Response:
        if not _authorized(request, token):
            return web.json_response({"error": "bad or missing token"}, status=401)
        try:
            payload = await request.json()
        except ValueError:
            return web.json_response({"error": "body must be JSON"}, status=400)
        message = str(payload.get("message") or "").strip()
        if not message:
            return web.json_response({"error": "message is required"}, status=400)
        if len(message) > MAX_MESSAGE_CHARS:
            return web.json_response(
                {"error": f"message too long (max {MAX_MESSAGE_CHARS} characters)"}, status=400
            )
        persona: Persona | None = None
        if raw := payload.get("persona"):
            try:
                persona = Persona(str(raw))
            except ValueError:
                return web.json_response({"error": f"unknown persona {raw!r}"}, status=400)
            if persona is Persona.AUTO:
                persona = None

        ctx = single_message_context(
            message,
            platform=PLATFORM,
            channel_id="webapp",
            forced_persona=persona,
            voice=app.voice,
        )
        try:
            result = await app.engine.suggest(ctx)
        except StructuredOutputError as exc:
            return web.json_response({"error": f"generation failed: {exc}"}, status=502)
        except Exception:  # noqa: BLE001 — never leak internals to the page
            log.exception("web argue failed")
            return web.json_response(
                {"error": "generation failed — check the server logs"}, status=502
            )
        return web.json_response(
            {
                "digest": result.state_digest,
                "candidates": [
                    {
                        "text": c.text,
                        "persona": c.persona.value,
                        "risk": c.risk.value,
                        "tactic_note": c.tactic_note,
                    }
                    for c in result.candidates
                ],
            }
        )

    async def usage(request: web.Request) -> web.Response:
        if not _authorized(request, token):
            return web.json_response({"error": "bad or missing token"}, status=401)
        return web.json_response({"report": app.meter.format_report()})

    web_app = web.Application()
    web_app.router.add_get("/", index)
    web_app.router.add_post("/api/argue", argue)
    web_app.router.add_get("/api/usage", usage)
    return web_app


def run_web(app: App) -> None:
    """Blocking entry point — web.run_app owns the event loop."""
    secret = app.settings.aw_web_token
    token = secret.get_secret_value().strip() if secret else ""
    if not token:
        raise RuntimeError(
            "AW_WEB_TOKEN must be set to run the web adapter — it is the secret "
            "you type into the page on your phone. Pick a long random string."
        )
    logging.basicConfig(level=logging.INFO)
    host, port = app.settings.aw_web_host, app.settings.aw_web_port
    print(
        f"ArgumentWinner web app on http://{host}:{port} "
        f"(provider: {app.provider.name}"
        + (", voice: on" if app.voice else "")
        + ") — open it on your phone and enter AW_WEB_TOKEN."
    )
    web.run_app(build_web_app(app, token), host=host, port=port)
