"""Terminal REPL adapter: the full engine with no Discord.

Proves the platform boundary (if the engine wins arguments over stdin/stdout it
is genuinely platform-agnostic) and doubles as the prompt-tuning workbench
against real providers.

Unlike chat platforms there is no channel history to fetch, so this adapter
keeps its own local transcript — that is adapter state, not engine state.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from itertools import count

from argumentwinner.container import App
from argumentwinner.core.models import (
    ArgumentContext,
    ArgumentTurn,
    ConversationRef,
    EngineResult,
    Participant,
    Persona,
    Role,
)

_REF = ConversationRef(platform="cli", guild_id=None, channel_id="repl")
_OPPONENT = Participant(id="opponent", display_name="Opponent")
_US = Participant(id="us", display_name="You")

_HELP = """\
Paste your opponent's message and get 3 winning replies.
Commands:
  /persona logician|savage|diplomat|socratic|auto   force a persona
  1|2|3        mark that candidate as sent (feeds future context)
  /usage       show token counts and estimated cost so far
  /reset       start a fresh argument
  /quit        exit
"""


def _render(result: EngineResult) -> str:
    lines = [f"\n  ~ {result.state_digest}\n"]
    for i, c in enumerate(result.candidates, start=1):
        lines.append(f"[{i}] ({c.persona.value}, {c.risk.value}) {c.tactic_note}")
        lines.append(f"    {c.text}\n")
    return "\n".join(lines)


async def run_repl(app: App) -> None:
    print(
        f"ArgumentWinner REPL — provider: {app.provider.name}"
        + (", voice: on" if app.voice else "")
    )
    print(_HELP)
    transcript: list[ArgumentTurn] = []
    forced: Persona | None = None
    last_result: EngineResult | None = None
    ids = count(1)

    loop = asyncio.get_running_loop()
    while True:
        try:
            line = (await loop.run_in_executor(None, input, "opponent> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line == "/quit":
            return
        if line == "/usage":
            print(app.meter.format_report())
            continue
        if line == "/reset":
            transcript.clear()
            last_result = None
            print("(argument reset)")
            continue
        if line.startswith("/persona"):
            arg = line.removeprefix("/persona").strip() or "auto"
            try:
                forced = Persona(arg)
            except ValueError:
                print(f"unknown persona {arg!r}")
                continue
            forced = None if forced is Persona.AUTO else forced
            print(f"(persona: {arg})")
            continue
        if line in ("1", "2", "3") and last_result is not None:
            idx = int(line) - 1
            if idx < len(last_result.candidates):
                sent = last_result.candidates[idx]
                transcript.append(
                    ArgumentTurn(
                        role=Role.US,
                        author=_US,
                        content=sent.text,
                        message_id=f"cli-{next(ids)}",
                        timestamp=datetime.now(UTC),
                    )
                )
                print(f'(sent: "{sent.text}")')
            continue

        target = ArgumentTurn(
            role=Role.OPPONENT,
            author=_OPPONENT,
            content=line,
            message_id=f"cli-{next(ids)}",
            timestamp=datetime.now(UTC),
        )
        transcript.append(target)
        ctx = ArgumentContext(
            ref=_REF,
            target=target,
            transcript=tuple(transcript),
            beneficiary=_US,
            forced_persona=forced,
            our_recent_lines=tuple(t.content for t in transcript if t.role is Role.US)[-8:],
            voice=app.voice,
        )
        try:
            last_result = await app.engine.suggest(ctx)
        except Exception as exc:  # noqa: BLE001 — REPL must not die on provider errors
            print(f"(generation failed: {exc})")
            continue
        print(_render(last_result))
