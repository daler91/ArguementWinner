"""Desktop helper: the pure parts (context building + candidate cycling) and
the full generate/cycle flow driven through fake clipboard functions and the
FakeLLMProvider — no pynput, no display server."""

from __future__ import annotations

from argumentwinner.adapters.desktop.helper import (
    CandidateCycler,
    DesktopHelper,
    build_context_from_text,
)
from argumentwinner.adapters.desktop.notify import notify
from argumentwinner.container import App
from argumentwinner.core.engine import ArgumentEngine
from argumentwinner.core.models import (
    CandidateResponse,
    EngineResult,
    EngineSettings,
    Persona,
    Risk,
    Role,
    SpiceLevel,
)
from argumentwinner.core.sessions import InMemorySessionStore
from argumentwinner.llm.fake import FakeLLMProvider
from tests.conftest import make_analysis, make_batch


def _result(*texts: str) -> EngineResult:
    return EngineResult(
        analysis=make_analysis(),
        candidates=tuple(
            CandidateResponse(text=t, persona=Persona.LOGICIAN, tactic_note="t", risk=Risk.SAFE)
            for t in texts
        ),
        state_digest="digest",
    )


# ─── build_context_from_text ──────────────────────────────────────────────────


def test_context_targets_the_pasted_message():
    ctx = build_context_from_text("  you're wrong  ")
    assert ctx.target.content == "you're wrong"  # stripped
    assert ctx.target.role is Role.OPPONENT
    assert ctx.ref.platform == "desktop"
    assert ctx.transcript == (ctx.target,)  # single message = single turn
    assert ctx.forced_persona is None


def test_context_carries_forced_persona():
    ctx = build_context_from_text("x", Persona.SAVAGE)
    assert ctx.forced_persona is Persona.SAVAGE


# ─── CandidateCycler ──────────────────────────────────────────────────────────


def test_cycler_starts_empty():
    c = CandidateCycler()
    assert c.current() is None
    assert c.advance() is None
    assert c.position() == "0/0"


def test_cycler_loads_and_reports_position():
    c = CandidateCycler()
    first = c.load(_result("a", "b", "c"))
    assert first.text == "a"
    assert c.position() == "1/3"


def test_cycler_advances_and_wraps():
    c = CandidateCycler()
    c.load(_result("a", "b"))
    assert c.advance().text == "b"
    assert c.position() == "2/2"
    assert c.advance().text == "a"  # wraps
    assert c.position() == "1/2"


def test_reload_resets_to_first():
    c = CandidateCycler()
    c.load(_result("a", "b"))
    c.advance()
    assert c.load(_result("x", "y")).text == "x"
    assert c.position() == "1/2"


# ─── notify never raises ──────────────────────────────────────────────────────


def test_notify_is_safe(capsys):
    notify("hello", "world")
    assert "hello" in capsys.readouterr().out


# ─── full generate/cycle flow (fake clipboard + fake provider) ────────────────


class FakeClipboard:
    def __init__(self, initial: str = "") -> None:
        self.value = initial

    def paste(self) -> str:
        return self.value

    def copy(self, text: str) -> None:
        self.value = text


def make_helper(queue) -> DesktopHelper:
    engine = ArgumentEngine(FakeLLMProvider(queue), EngineSettings(spice=SpiceLevel.MEDIUM))
    app = App(
        settings=make_settings(),
        provider=None,
        store=InMemorySessionStore(),
        engine=engine,
    )
    helper = DesktopHelper(app)
    import threading

    threading.Thread(target=helper._run_loop, daemon=True).start()
    return helper


def make_settings():
    from argumentwinner.config import Settings

    return Settings(_env_file=None, aw_llm_provider="fake")


def test_generate_puts_best_comeback_on_clipboard():
    clip = FakeClipboard("Tabs are better, everyone knows it.")
    helper = make_helper(
        [
            make_analysis(),
            make_batch(
                ("Where's the evidence?", Persona.LOGICIAN, Risk.SAFE),
                ("Repetition isn't proof.", Persona.LOGICIAN, Risk.SPICY),
            ),
        ]
    )
    helper.on_generate(clip.paste, clip.copy)
    assert clip.value == "Where's the evidence?"


def test_generate_on_empty_clipboard_does_nothing():
    clip = FakeClipboard("   ")
    helper = make_helper([])
    helper.on_generate(clip.paste, clip.copy)
    assert clip.value == "   "  # untouched, no engine call


def test_cycle_pages_through_without_regenerating():
    clip = FakeClipboard("you're wrong")
    helper = make_helper(
        [
            make_analysis(),
            make_batch(
                ("first", Persona.LOGICIAN, Risk.SAFE),
                ("second", Persona.SOCRATIC, Risk.SAFE),
            ),
        ]
    )
    helper.on_generate(clip.paste, clip.copy)
    assert clip.value == "first"
    helper.on_cycle(clip.copy)
    assert clip.value == "second"
    helper.on_cycle(clip.copy)
    assert clip.value == "first"  # wrapped


def test_cycle_before_generate_is_a_noop():
    clip = FakeClipboard("original")
    helper = make_helper([])
    helper.on_cycle(clip.copy)
    assert clip.value == "original"


def test_generation_failure_leaves_clipboard_intact():
    from argumentwinner.core.ports import StructuredOutputError

    clip = FakeClipboard("beat this")
    helper = make_helper([make_analysis(), StructuredOutputError("boom")])
    helper.on_generate(clip.paste, clip.copy)
    assert clip.value == "beat this"  # not clobbered on failure
