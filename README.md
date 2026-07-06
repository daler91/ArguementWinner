# ArgumentWinner

A framework that wins arguments for you. Feed it your opponent's message (plus
the conversation around it) and it produces replies engineered to win — on the
merits and for the crowd. Discord is the first platform; the core engine is
platform-agnostic so Telegram, Slack, etc. can be added as adapters.

## ⚠️ Setup trap #1 (read this first)

The Discord bot needs the **Message Content Intent**, which is *privileged*.
In the [Discord Developer Portal](https://discord.com/developers/applications):
**your app → Bot → Privileged Gateway Intents → toggle "Message Content
Intent" ON.** Without it every message the bot sees is an empty string and
nothing works.

## Quick start

```bash
# 1. Install (Python 3.11+)
pip install -e ".[dev]"          # or: uv sync --extra dev

# 2. Configure
cp .env.example .env             # then fill in the keys you need

# 3. Prove it works in the terminal (no Discord, no API key needed)
AW_LLM_PROVIDER=fake python -m argumentwinner --repl

# 4. Same, against a real model
AW_LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-... python -m argumentwinner --repl

# 5. Run the Discord bot
python -m argumentwinner
```

## Using it on Discord

Two modes, both available at once:

**Suggestion mode** (private) — right-click any message → **Apps → Win this
argument**. The bot shows you 2–3 candidate replies (ephemeral — only you see
them), each with a persona, a risk badge, and a one-line tactic note. Press
**Send #N** to have the bot post it as a reply, or **Plain text** to copy it
and send it as yourself. `/argue [persona]` does the same for the latest
opponent message in the channel.

**Auto-combat mode** (public) — `/combat start [persona] [opponent]` and the
bot argues on its own: it replies when @mentioned or when a registered
opponent posts, with a cooldown, a reply cap, and a debounce so it never
spams. `/combat stop` ends it. A thread and its parent channel are separate
arguments.

## How it decides what to say

Each reply is two LLM calls:

1. **Analyze** — dissect the opponent's message: claims, logical fallacies
   (with exact quotes), tone, weak points, dodged questions.
2. **Select strategy** — pure Python picks a persona: **Logician** (facts and
   fallacy-calling), **Savage** (roast-flavored wit), **Diplomat** (win by
   agreement), **Socratic** (trap questions). You can force one; otherwise
   it adapts, and in combat it stays sticky until the analysis disagrees twice
   in a row.
3. **Generate** — candidates written with the analysis as ammunition, under
   hard rules: shorter than the opponent, never fabricate, concede trivial
   points, never contradict what your side already said.
4. **Order** — a pure-function sanity pass demotes overlength, over-spicy and
   near-duplicate candidates.

`AW_SPICE_LEVEL` (mild / medium / savage) caps how mean it can get.

## Configuration

Everything is env vars (or a git-ignored `.env`) — see [.env.example](.env.example)
for the full annotated list. LLM backends: `anthropic` (default), `openai`,
`ollama` (any OpenAI-compatible endpoint), or `fake` (offline, deterministic).

## Architecture

```
src/argumentwinner/
├── config.py            env → Settings (pydantic-settings, SecretStr tokens)
├── container.py         composition root: Settings → provider → store → engine
├── core/                the hexagon — imports only stdlib + pydantic (enforced by a test)
│   ├── models.py        domain models + LLM schemas
│   ├── ports.py         LLMProvider / SessionStore protocols
│   ├── engine.py        analyze → strategy → generate → order
│   ├── strategy.py      persona selection (table-driven, spice-capped)
│   ├── prompts.py       every prompt template (golden-file tested)
│   ├── ranking.py       candidate ordering sanity pass
│   └── sessions.py      combat session control-state + in-memory store
├── llm/                 anthropic / openai+ollama / fake backends, RoleRouter
└── adapters/
    ├── discord/         translate, suggestion UI, auto-combat, sending
    └── cli/             REPL — proves the engine is platform-agnostic
```

Design decisions worth knowing:

- **Conversation content is never stored.** Every invocation re-fetches fresh
  channel history, so edits and deletions are handled for free. Combat
  sessions hold control state only (persona, opponents, cooldowns).
- **Fail-fast drop, not a queue.** If the bot is mid-generation or cooling
  down, incoming events are discarded — the next engagement's fresh history
  fetch sees those messages anyway. No burst-spam.
- **Attachments are annotated**, so an image-only *"explain this, genius"*
  never reaches the engine as an empty string.
- **A new platform adapter** = translate native events → core models, fetch
  history, call `engine.suggest()` / `engine.combat_reply()`, render the
  result. Zero core changes (the CLI REPL is the proof).

## Development

```bash
pytest                   # full offline suite (fake provider, no network)
pytest -m live           # provider contract tests against real APIs (needs keys)
ruff check src tests
```

Prompt templates are pinned by golden files; after an intentional prompt
change, regenerate them with `python -m tests.core.test_prompts_golden`.

If you set `AW_MODEL_ANALYZER` (a cheaper model for the analysis call), make
sure it is still structured-output proficient — Haiku-class minimum, never a
tiny local model. A weak analyzer feeds garbage tone/fallacy data to the strong
generator and quality collapses. `pytest -m live` includes a golden that checks
the analyzer still catches a strawman.
