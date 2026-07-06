"""Desktop helper adapter: copy the message you're arguing with, press a
hotkey, and the winning comeback lands on your clipboard ready to paste —
in ANY app (Discord, iMessage, Slack, email), with zero account automation.

Like every adapter it only translates (clipboard text → ArgumentContext),
invokes the engine, and renders (clipboard + notification) — the core engine
is untouched. The GUI dependencies (pynput, pyperclip) are imported lazily
inside `run_desktop`, so this module's pure logic imports and tests without a
display server.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import UTC, datetime

from argumentwinner.container import App
from argumentwinner.core.models import (
    ArgumentContext,
    ArgumentTurn,
    CandidateResponse,
    ConversationRef,
    EngineResult,
    Participant,
    Persona,
    Role,
    VoiceProfile,
)

from .notify import notify

log = logging.getLogger(__name__)

_REF = ConversationRef(platform="desktop", guild_id=None, channel_id="clipboard")
_OPPONENT = Participant(id="opponent", display_name="Opponent")
_YOU = Participant(id="you", display_name="You")


def build_context_from_text(
    text: str,
    forced_persona: Persona | None = None,
    voice: VoiceProfile | None = None,
) -> ArgumentContext:
    """A single pasted message becomes a one-turn argument context — no history
    to fetch, so the opponent's message is both the target and the transcript."""
    target = ArgumentTurn(
        role=Role.OPPONENT,
        author=_OPPONENT,
        content=text.strip(),
        message_id="clipboard",
        timestamp=datetime.now(UTC),
    )
    return ArgumentContext(
        ref=_REF,
        target=target,
        transcript=(target,),
        beneficiary=_YOU,
        forced_persona=forced_persona,
        voice=voice,
    )


class CandidateCycler:
    """Holds the last batch of candidates so the cycle hotkey can page through
    them without regenerating. Pure — no clipboard, no engine."""

    def __init__(self) -> None:
        self._candidates: tuple[CandidateResponse, ...] = ()
        self._index = 0

    def load(self, result: EngineResult) -> CandidateResponse | None:
        self._candidates = result.candidates
        self._index = 0
        return self.current()

    def current(self) -> CandidateResponse | None:
        return self._candidates[self._index] if self._candidates else None

    def advance(self) -> CandidateResponse | None:
        if not self._candidates:
            return None
        self._index = (self._index + 1) % len(self._candidates)
        return self._candidates[self._index]

    def position(self) -> str:
        return f"{self._index + 1}/{len(self._candidates)}" if self._candidates else "0/0"


def _describe(cycler: CandidateCycler, candidate: CandidateResponse) -> tuple[str, str]:
    title = f"Comeback {cycler.position()} copied — paste it ({candidate.persona.value})"
    return title, candidate.text


class DesktopHelper:
    def __init__(self, app: App) -> None:
        self._engine = app.engine
        self._settings = app.settings
        self._voice = app.voice
        self._cycler = CandidateCycler()
        self._loop = asyncio.new_event_loop()

    # ─── engine access from the listener thread ────────────────────────────────

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _suggest(self, text: str) -> EngineResult:
        ctx = build_context_from_text(text, self._settings.aw_desktop_persona, self._voice)
        return await self._engine.suggest(ctx)

    # ─── hotkey handlers (run on pynput's listener thread) ─────────────────────

    def on_generate(self, read_clipboard, write_clipboard) -> None:
        text = (read_clipboard() or "").strip()
        if not text:
            notify("Clipboard is empty — copy the message first")
            return
        notify("Thinking…")
        try:
            future = asyncio.run_coroutine_threadsafe(self._suggest(text), self._loop)
            result = future.result(timeout=180)
        except Exception:  # noqa: BLE001 — surface the failure, keep the helper alive
            log.exception("generation failed")
            notify("Couldn't generate a comeback — check your API key / connection")
            return
        candidate = self._cycler.load(result)
        if candidate is None:
            notify("No usable comeback this time — try rephrasing")
            return
        write_clipboard(candidate.text)
        notify(*_describe(self._cycler, candidate))

    def on_cycle(self, write_clipboard) -> None:
        candidate = self._cycler.advance()
        if candidate is None:
            notify("Nothing to cycle — generate a comeback first")
            return
        write_clipboard(candidate.text)
        notify(*_describe(self._cycler, candidate))


def run_desktop(app: App) -> None:
    """Blocking entry point. Imports the GUI deps here so the rest of the
    package stays importable on a headless box."""
    try:
        import pyperclip
        from pynput import keyboard
    except ImportError as exc:  # noqa: BLE001
        raise RuntimeError(
            "The desktop helper needs the 'desktop' extra: pip install -e '.[desktop]'"
        ) from exc

    logging.basicConfig(level=logging.INFO)
    helper = DesktopHelper(app)
    threading.Thread(target=helper._run_loop, daemon=True).start()

    hotkeys = {
        app.settings.aw_desktop_hotkey: lambda: helper.on_generate(
            pyperclip.paste, pyperclip.copy
        ),
        app.settings.aw_desktop_cycle_hotkey: lambda: helper.on_cycle(pyperclip.copy),
    }
    persona = app.settings.aw_desktop_persona
    print(
        "ArgumentWinner desktop helper is running "
        f"(provider: {app.provider.name}"
        + (f", persona: {persona.value}" if persona else "")
        + (", voice: on" if app.voice else "")
        + ").\n"
        f"  Copy an opponent's message, then press {app.settings.aw_desktop_hotkey} "
        "to put a comeback on your clipboard.\n"
        f"  Press {app.settings.aw_desktop_cycle_hotkey} to cycle to the next option.\n"
        "  Ctrl-C here to quit."
    )
    with keyboard.GlobalHotKeys(hotkeys) as listener:
        listener.join()
