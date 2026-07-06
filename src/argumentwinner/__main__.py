"""Entry point: `python -m argumentwinner` runs the Discord bot,
`python -m argumentwinner --repl` runs the terminal REPL."""

from __future__ import annotations

import argparse
import asyncio

from argumentwinner.container import build_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="argumentwinner")
    parser.add_argument(
        "--repl", action="store_true", help="run the terminal REPL instead of the Discord bot"
    )
    args = parser.parse_args()

    app = build_app()
    if args.repl:
        from argumentwinner.adapters.cli.repl import run_repl

        asyncio.run(run_repl(app))
    else:
        from argumentwinner.adapters.discord.bot import run_bot

        run_bot(app)


if __name__ == "__main__":
    main()
