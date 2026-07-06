"""Golden-file tests: prompt changes must show up as reviewable diffs.

Regenerate after an intentional prompt change with:
    python -m tests.core.test_prompts_golden
"""

from __future__ import annotations

from pathlib import Path

from argumentwinner.core import prompts
from argumentwinner.core.models import Persona, Role, SpiceLevel
from tests.conftest import make_analysis, make_context, make_turn

GOLDEN_DIR = Path(__file__).parent / "goldens"


def _rendered() -> dict[str, str]:
    ctx = make_context(
        prior=(
            make_turn("Spaces respect the style guide.", role=Role.US),
            make_turn("Style guides are written by cowards."),
        ),
        our_recent_lines=("Spaces respect the style guide.",),
    )
    analysis = make_analysis()
    return {
        "analysis_system.txt": prompts.ANALYSIS_SYSTEM,
        "analysis_user.txt": prompts.analysis_user(ctx),
        "generation_system_medium.txt": prompts.generation_system(SpiceLevel.MEDIUM),
        "generation_user_suggest.txt": prompts.generation_user(
            ctx, analysis, Persona.LOGICIAN, Persona.SOCRATIC, 3, combat=False
        ),
        "generation_user_combat.txt": prompts.generation_user(
            ctx, analysis, Persona.SAVAGE, Persona.LOGICIAN, 2, combat=True
        ),
    }


def test_prompts_match_goldens():
    for name, rendered in _rendered().items():
        golden = GOLDEN_DIR / name
        assert golden.exists(), (
            f"missing golden {name} — regenerate: python -m tests.core.test_prompts_golden"
        )
        assert rendered == golden.read_text(), (
            f"{name} drifted from its golden. If the change is intentional, "
            "regenerate: python -m tests.core.test_prompts_golden"
        )


if __name__ == "__main__":
    GOLDEN_DIR.mkdir(exist_ok=True)
    for name, rendered in _rendered().items():
        (GOLDEN_DIR / name).write_text(rendered)
        print(f"wrote {GOLDEN_DIR / name}")
