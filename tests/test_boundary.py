"""The boundary rule, enforced: core/ imports only stdlib + pydantic —
never a platform SDK or provider SDK."""

from __future__ import annotations

import re
from pathlib import Path

CORE = Path(__file__).parent.parent / "src" / "argumentwinner" / "core"
FORBIDDEN = (
    "discord",
    "telegram",
    "anthropic",
    "openai",
    "argumentwinner.llm",
    "argumentwinner.adapters",
)

_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([\w.]+)", re.MULTILINE)


def test_core_never_imports_platform_or_provider_sdks():
    offenders: list[str] = []
    for path in CORE.rglob("*.py"):
        for module in _IMPORT_RE.findall(path.read_text()):
            if any(module == f or module.startswith(f + ".") for f in FORBIDDEN):
                offenders.append(f"{path.name}: {module}")
    assert not offenders, f"core/ must stay platform-agnostic, found: {offenders}"
