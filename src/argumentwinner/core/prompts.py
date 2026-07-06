"""Every prompt template in one module — tuning these is 80% of the product.

All functions are pure: context in, string out. Golden-file tests pin the
rendered output so prompt changes show up as reviewable diffs.
"""

from __future__ import annotations

from .models import Analysis, ArgumentContext, ArgumentTurn, Persona, Role, SpiceLevel

PERSONA_BRIEFS: dict[Persona, str] = {
    Persona.LOGICIAN: (
        "Logician: win on substance. Dismantle claims with reasoning, name logical "
        "fallacies (quoting the opponent's exact words), and force them to defend "
        "their weakest point. Calm, precise, never rattled."
    ),
    Persona.SAVAGE: (
        "Savage: win the crowd. Witty, cutting comebacks that make the opponent's "
        "position look ridiculous. Sharp, not cruel — mock the argument and the "
        "logic, never immutable traits."
    ),
    Persona.DIPLOMAT: (
        "Diplomat: win by agreement. Concede what's trivially true, reframe the "
        "disagreement so your position sounds like common sense, and guide the "
        "opponent into agreeing with the core of your point."
    ),
    Persona.SOCRATIC: (
        "Socratic: win with questions. Ask short, pointed questions the opponent "
        "cannot answer without contradicting themselves or conceding. Never state "
        "what a question can extract."
    ),
}

_ROLE_LABELS = {Role.OPPONENT: "OPPONENT", Role.US: "US", Role.BYSTANDER: "BYSTANDER"}


def render_transcript(turns: tuple[ArgumentTurn, ...], max_chars: int = 6000) -> str:
    """Chronological transcript, oldest first, trimmed from the front to fit
    the character budget."""
    lines = [
        f"[{_ROLE_LABELS[t.role]}] {t.author.display_name}: {t.content}" for t in turns
    ]
    while lines and sum(len(line) + 1 for line in lines) > max_chars:
        lines.pop(0)
    return "\n".join(lines) if lines else "(no prior messages)"


# ─── Analysis ──────────────────────────────────────────────────────────────────

ANALYSIS_SYSTEM = (
    "You are the analysis stage of an argument-winning engine. You read an "
    "ongoing argument from a chat platform and dissect the opponent's latest "
    "message so a later stage can craft a winning reply.\n"
    "Rules:\n"
    "- Quote fallacies using the opponent's EXACT words — never paraphrase a quote.\n"
    "- List dodged_points only for things OUR side actually raised that the "
    "opponent ignored.\n"
    "- recommended_persona: logician when their logic is weak, socratic when they "
    "dodge or overreach, savage when they are hostile or smug and deserve heat, "
    "diplomat when they are reasonable and can be won over.\n"
    "- Be terse. Lists of short phrases, not essays."
)


def analysis_user(ctx: ArgumentContext) -> str:
    parts = [
        "## Argument so far (oldest first)",
        render_transcript(ctx.transcript),
        "",
        "## The message we must beat (from the opponent)",
        f"{ctx.target.author.display_name}: {ctx.target.content}",
    ]
    if ctx.our_recent_lines:
        parts += [
            "",
            "## Things OUR side already said (for dodged_points)",
            *(f"- {line}" for line in ctx.our_recent_lines),
        ]
    parts += ["", "Analyze the opponent's message."]
    return "\n".join(parts)


# ─── Generation ────────────────────────────────────────────────────────────────

_SPICE_RULES: dict[SpiceLevel, str] = {
    SpiceLevel.MILD: (
        "Spice level: MILD. Every candidate must be risk=safe. Stay civil and "
        "measured; no mockery."
    ),
    SpiceLevel.MEDIUM: (
        "Spice level: MEDIUM. Candidates may be risk=safe or risk=spicy. Wit and "
        "pointed jabs are fine; no scorched-earth."
    ),
    SpiceLevel.SAVAGE: (
        "Spice level: SAVAGE. Any risk tier is allowed, including one nuclear "
        "option — but at least one candidate must still be risk=safe."
    ),
}


def generation_system(spice: SpiceLevel) -> str:
    return (
        "You are the reply stage of an argument-winning engine. You write replies "
        "that WIN the argument — for the crowd and on the merits.\n"
        "\n"
        "Personas:\n"
        + "\n".join(f"- {brief}" for brief in PERSONA_BRIEFS.values())
        + "\n\n"
        "Hard rules for every candidate:\n"
        "- SHORTER than the opponent's message. Brevity reads as confidence.\n"
        "- Never fabricate facts, statistics or quotes. If you quote the opponent, "
        "use their exact words.\n"
        "- Concede trivially true points — it buys credibility for the attack.\n"
        "- Never contradict anything our side already said.\n"
        "- Attack the argument, never protected characteristics.\n"
        "- Plain chat register: no headers, no bullet lists, no 'Firstly'. It must "
        "read like a person typing in the channel.\n"
        "- Keep each candidate under 1800 characters.\n"
        f"\n{_SPICE_RULES[spice]}"
    )


def generation_user(
    ctx: ArgumentContext,
    analysis: Analysis,
    primary: Persona,
    runner_up: Persona,
    n: int,
    combat: bool = False,
) -> str:
    ammo: list[str] = []
    if analysis.claims:
        ammo.append("Their claims: " + "; ".join(analysis.claims))
    for f in analysis.fallacies:
        ammo.append(f'Fallacy — {f.name}: they said "{f.quote}" ({f.explanation})')
    if analysis.weak_points:
        ammo.append("Weak points: " + "; ".join(analysis.weak_points))
    if analysis.dodged_points:
        ammo.append("They dodged: " + "; ".join(analysis.dodged_points))
    ammo.append(f"Their tone: {analysis.tone}")

    parts = [
        "## Argument so far (oldest first)",
        render_transcript(ctx.transcript),
        "",
        "## The message to beat",
        f"{ctx.target.author.display_name}: {ctx.target.content}",
        "",
        "## Ammunition from analysis",
        *(f"- {a}" for a in ammo),
    ]
    if ctx.our_recent_lines:
        parts += [
            "",
            "## Our side already said (NEVER contradict these)",
            *(f"- {line}" for line in ctx.our_recent_lines),
        ]
    if combat:
        parts += [
            "",
            f"## Task\nWrite {n} candidate replies in the {primary.value} persona, best "
            "first. This is live combat: each must be a single punchy message, "
            "distinctly different tactics.",
        ]
    else:
        parts += [
            "",
            f"## Task\nWrite {n} candidate replies, best first: "
            f"{max(n - 1, 1)} in the {primary.value} persona using distinct tactics, "
            f"and 1 in the {runner_up.value} persona. Span the allowed risk tiers "
            "(at least one safe).",
        ]
    return "\n".join(parts)
